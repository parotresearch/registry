#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "jsonschema>=4.21",
#   "referencing>=0.34",
#   "requests>=2.31",
#   "typer>=0.12",
# ]
# ///
"""Validate one or more registry listing documents.

Every check is reported by name with a status (pass / fail / skip) and an exact
reason. A check that cannot run because the network is disabled or a reader is
not configured is SKIPPED VISIBLY -- never silently reported as passed. The
script exits non-zero if any check failed.

This is exactly what .github/workflows/validate.yml runs on every changed
listing in a pull request, and it runs locally on explicit paths:

    uv run scripts/validate.py r/registry/shakespeare.json \\
        --author octocat --pr-body /tmp/body.md --skip-network
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests
import typer
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

app = typer.Typer(add_completion=False, help=__doc__)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schema"

LICENSE_ALLOWLIST = (
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "ODbL-1.0",
    "PDDL-1.0",
    "MIT",
    "Apache-2.0",
    "public-domain",
)
MAX_BYTES = 50 * 1024 * 1024 * 1024  # 50 GiB hard cap
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
WARRANTY_CHECKBOX = "- [x] I have the right to distribute this content in this form."
RESERVED_NAMESPACE = "registry"
MAX_OPEN_PRS = 5
GITHUB_API = "https://api.github.com"
HTTP_TIMEOUT = 30

# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    name: str
    status: str  # "pass" | "fail" | "skip"
    reason: str

    def line(self) -> str:
        mark = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[self.status]
        return f"  [{mark}] {self.name}: {self.reason}"


def _pass(name: str, reason: str) -> list[Verdict]:
    return [Verdict(name, "pass", reason)]


def _fail(name: str, reason: str) -> list[Verdict]:
    return [Verdict(name, "fail", reason)]


def _skip(name: str, reason: str) -> list[Verdict]:
    return [Verdict(name, "skip", reason)]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def build_validator() -> Draft202012Validator:
    """A listing validator whose `card` $ref resolves to the local card schema."""
    listing_schema = json.loads((SCHEMA_DIR / "listing.schema.json").read_text())
    card_schema = json.loads((SCHEMA_DIR / "card.schema.json").read_text())
    registry = Registry().with_resources(
        [(card_schema["$id"], Resource.from_contents(card_schema))]
    )
    return Draft202012Validator(listing_schema, registry=registry)


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class Ctx:
    doc: dict
    path: Path
    registry_dir: Path
    author: str | None
    pr_body: str | None
    codeowners: set[str]
    base_doc: dict | None
    skip_network: bool
    local_file: Path | None
    token: str | None
    reader_cmd_prefix: list[str] | None  # e.g. ["/path/to/cartridge"] or docker wrapper
    repo: str | None  # "owner/name" for the rate-limit search
    download_cache: list = None  # memoised downloaded file path (single-element box)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_schema(ctx: Ctx) -> list[Verdict]:
    validator = build_validator()
    errors = sorted(validator.iter_errors(ctx.doc), key=lambda e: list(e.path))
    if not errors:
        return _pass("schema", "valid against listing.schema.json (card included)")
    first = errors[0]
    loc = "/".join(str(p) for p in first.path) or "<root>"
    return _fail("schema", f"at {loc}: {first.message}")


def _expected_path(name: str, registry_dir: Path) -> Path:
    org, slug = name.split("/", 1)
    if org == RESERVED_NAMESPACE:
        return registry_dir / f"{slug}.json"
    return registry_dir / org / f"{slug}.json"


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def check_name(ctx: Ctx) -> list[Verdict]:
    name = ctx.doc["name"]
    if "/" not in name:
        return _fail("name", f"name '{name}' must be '<org>/<slug>' or 'registry/<slug>'")
    org, slug = name.split("/", 1)
    for part, label in ((org, "namespace"), (slug, "slug")):
        if not SLUG_RE.match(part):
            return _fail(
                "name",
                f"{label} '{part}' must be [a-z0-9-], 1-64 chars, no leading/trailing hyphen",
            )

    # filename is exactly one path component.
    filename = ctx.doc["filename"]
    if "/" in filename or "\\" in filename:
        return _fail("name", f"filename '{filename}' must be exactly one path component (no slash)")

    # File path must match the declared name.
    expected = _expected_path(name, ctx.registry_dir).resolve()
    actual = ctx.path.resolve()
    if expected != actual:
        rel = expected.relative_to(ctx.registry_dir.resolve().parent)
        return _fail("name", f"name '{name}' must live at {rel}, not {ctx.path}")

    # Reserved namespace is CODEOWNERS-only.
    if org == RESERVED_NAMESPACE:
        if ctx.author is None:
            return _fail("name", "registry/* namespace requires a PR author to check against CODEOWNERS")
        if ctx.author.lower() not in {o.lower() for o in ctx.codeowners}:
            return _fail(
                "name",
                f"registry/* is reserved for CODEOWNERS; '{ctx.author}' is not one",
            )

    # An existing name may only change if the version increases.
    if ctx.base_doc is not None:
        old = _version_tuple(ctx.base_doc["version"])
        new = _version_tuple(ctx.doc["version"])
        if new <= old:
            return _fail(
                "name",
                f"'{name}' already exists at version {ctx.base_doc['version']}; "
                f"a change requires a higher version, got {ctx.doc['version']}",
            )
        return _pass(
            "name",
            f"path matches; version {ctx.base_doc['version']} -> {ctx.doc['version']}",
        )

    return _pass("name", f"path and slug rules ok for '{name}'")


def _org_member(org: str, login: str, token: str | None) -> bool:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if org.lower() == login.lower():
        return True
    resp = requests.get(
        f"{GITHUB_API}/orgs/{org}/public_members/{login}",
        headers=headers,
        timeout=HTTP_TIMEOUT,
    )
    return resp.status_code == 204


def check_namespace(ctx: Ctx) -> list[Verdict]:
    name = ctx.doc["name"]
    org = name.split("/", 1)[0]
    if org == RESERVED_NAMESPACE:
        return _pass("namespace", "registry/* ownership settled by the name check (CODEOWNERS)")
    if ctx.author is None:
        return _skip("namespace", "no PR author supplied; org membership not checked")
    if org.lower() == ctx.author.lower():
        return _pass("namespace", f"author '{ctx.author}' owns namespace '{org}'")
    if ctx.author.lower() in {o.lower() for o in ctx.codeowners}:
        return _pass("namespace", f"author '{ctx.author}' is a CODEOWNER")
    if ctx.skip_network:
        return _skip("namespace", f"network disabled; public membership of '{org}' by '{ctx.author}' not checked")
    if _org_member(org, ctx.author, ctx.token):
        return _pass("namespace", f"author '{ctx.author}' is a public member of '{org}'")
    return _fail(
        "namespace",
        f"'{ctx.author}' is neither '{org}' nor a public member of it",
    )


def _host_is_cartridge(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "cartridge.app" or host.endswith(".cartridge.app")


def check_url(ctx: Ctx) -> list[Verdict]:
    urls = ctx.doc["urls"]
    for url in urls:
        if not url.startswith("https://"):
            return _fail("url", f"'{url}' must be https://")
        if _host_is_cartridge(url):
            return _fail("url", f"'{url}' points at cartridge.app; the registry never hosts bytes")
    if ctx.doc["size_bytes"] > MAX_BYTES:
        return _fail("url", f"size_bytes {ctx.doc['size_bytes']} exceeds the 50 GiB cap")
    return _pass("url", f"{len(urls)} https url(s), none on cartridge.app, size within cap")


def check_url_reachable(ctx: Ctx) -> list[Verdict]:
    if ctx.skip_network:
        return _skip("url-reachable", "network disabled; HEAD and Content-Length not checked")
    verdicts: list[Verdict] = []
    for url in ctx.doc["urls"]:
        resp = requests.head(url, allow_redirects=True, timeout=HTTP_TIMEOUT)
        if resp.status_code >= 400:
            verdicts.extend(_fail("url-reachable", f"HEAD {url} returned {resp.status_code}"))
            continue
        length = resp.headers.get("Content-Length")
        if length is None:
            verdicts.extend(_fail("url-reachable", f"{url} sent no Content-Length"))
            continue
        if int(length) != ctx.doc["size_bytes"]:
            verdicts.extend(
                _fail(
                    "url-reachable",
                    f"{url} Content-Length {length} != size_bytes {ctx.doc['size_bytes']}",
                )
            )
            continue
        verdicts.extend(_pass("url-reachable", f"{url} reachable, Content-Length matches"))
    return verdicts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_file(ctx: Ctx) -> Path | None:
    """The cartridge file to inspect, or None only when offline with no --file.

    A download failure RAISES (so it becomes a loud FAIL verdict at the check
    boundary) rather than returning None, which would masquerade as a skip.
    """
    if ctx.local_file is not None:
        return ctx.local_file
    if ctx.skip_network:
        return None
    if ctx.download_cache and ctx.download_cache[0] is not None:
        return ctx.download_cache[0]
    dest_dir = REPO_ROOT / ".cartridge-download"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / ctx.doc["filename"]
    with requests.get(ctx.doc["urls"][0], stream=True, timeout=HTTP_TIMEOUT) as resp:
        resp.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                handle.write(chunk)
    if ctx.download_cache is not None:
        ctx.download_cache[0] = dest
    return dest


def check_bytes(ctx: Ctx) -> list[Verdict]:
    local = resolve_file(ctx)
    if local is None:
        return _skip("bytes", "no cartridge file available (network disabled and no --file)")
    actual = _sha256(local)
    if actual != ctx.doc["sha256"]:
        return _fail("bytes", f"sha256 {actual} != listing sha256 {ctx.doc['sha256']}")
    return _pass("bytes", f"sha256 matches ({actual[:12]}...)")


def first_diff(a, b, path: str = "card"):
    """The first path where two JSON values differ, or None if equal."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                return f"{path}.{key} (missing in file)"
            if key not in b:
                return f"{path}.{key} (missing in listing)"
            diff = first_diff(a[key], b[key], f"{path}.{key}")
            if diff:
                return diff
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path} (length {len(a)} in listing vs {len(b)} in file)"
        for idx, (ai, bi) in enumerate(zip(a, b)):
            diff = first_diff(ai, bi, f"{path}[{idx}]")
            if diff:
                return diff
        return None
    if a != b:
        return f"{path} ({a!r} in listing vs {b!r} in file)"
    return None


def run_reader(prefix: list[str], file_path: Path) -> dict:
    """Run the cartridge reader on the file, returning its info JSON."""
    if "{file}" in " ".join(prefix):
        cmd = [part.replace("{file}", str(file_path)) for part in prefix]
    else:
        cmd = [*prefix, "info", "--json", str(file_path)]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if completed.returncode != 0:
        raise RuntimeError(
            f"reader exited {completed.returncode}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return json.loads(completed.stdout)


def check_card(ctx: Ctx) -> list[Verdict]:
    if ctx.reader_cmd_prefix is None:
        return _skip("card-check", "reader not configured (set CARTRIDGE_BIN or the CI reader vars)")
    local = resolve_file(ctx)
    if local is None:
        return _skip("card-check", "no cartridge file available to read")
    # `cartridge info FILE --json` prints a wrapper object; the card lives in
    # its `.card` field and its sealed-ness in `.seal`.
    info = run_reader(ctx.reader_cmd_prefix, local)
    if "seal" not in info:
        return _fail("card-check", "reader info JSON has no `seal` field")
    if not info["seal"]:
        return _fail("card-check", "reader reports the file is not sealed (`seal` is falsy)")
    file_card = info.get("card")
    if file_card is None:
        return _fail("card-check", "reader info JSON has no `card` field")
    diff = first_diff(ctx.doc["card"], file_card)
    if diff is not None:
        return _fail("card-check", f"listing card differs from the file's card at {diff}")
    return _pass("card-check", "reader exit 0, file sealed, card matches the listing")


def check_license(ctx: Ctx) -> list[Verdict]:
    spdx = ctx.doc["license"]
    if spdx not in LICENSE_ALLOWLIST:
        return _fail(
            "license",
            f"'{spdx}' is not on the allowlist ({', '.join(LICENSE_ALLOWLIST)}); see POLICY.md",
        )
    return _pass("license", f"'{spdx}' is on the allowlist")


def check_warranty(ctx: Ctx) -> list[Verdict]:
    if ctx.doc["warranty"] is not True:
        return _fail("warranty", "listing 'warranty' must be true")
    if ctx.pr_body is None:
        return _skip("warranty", "warranty is true in the document; no PR body supplied to check the checkbox")
    normalized = re.sub(r"[ \t]+", " ", ctx.pr_body)
    if WARRANTY_CHECKBOX not in normalized:
        return _fail(
            "warranty",
            "PR body is missing the checked warranty checkbox "
            f"('{WARRANTY_CHECKBOX}')",
        )
    return _pass("warranty", "warranty true and PR body carries the checked checkbox")


def check_rate_limit(ctx: Ctx) -> list[Verdict]:
    if ctx.author is None:
        return _skip("rate-limit", "no PR author supplied; open-PR count not checked")
    if ctx.skip_network:
        return _skip("rate-limit", f"network disabled; open-PR count for '{ctx.author}' not checked")
    if ctx.repo is None:
        return _skip("rate-limit", "no repo supplied; open-PR count not checked")
    headers = {"Accept": "application/vnd.github+json"}
    if ctx.token:
        headers["Authorization"] = f"Bearer {ctx.token}"
    query = f"repo:{ctx.repo} type:pr state:open author:{ctx.author}"
    resp = requests.get(
        f"{GITHUB_API}/search/issues",
        params={"q": query, "per_page": 1},
        headers=headers,
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    count = resp.json()["total_count"]
    if count > MAX_OPEN_PRS:
        return _fail("rate-limit", f"'{ctx.author}' has {count} open PRs; the cap is {MAX_OPEN_PRS}")
    return _pass("rate-limit", f"'{ctx.author}' has {count} open PR(s) (cap {MAX_OPEN_PRS})")


CHECKS = (
    check_schema,
    check_name,
    check_namespace,
    check_url,
    check_url_reachable,
    check_bytes,
    check_card,
    check_license,
    check_warranty,
    check_rate_limit,
)


def run_checks(ctx: Ctx) -> list[Verdict]:
    """Run every check, converting an unexpected exception into a FAIL verdict."""
    verdicts: list[Verdict] = []
    for check in CHECKS:
        name = check.__name__.removeprefix("check_").replace("_", "-")
        try:
            verdicts.extend(check(ctx))
        except Exception as exc:  # case boundary: a crash is a loud failure, not a skip
            verdicts.append(Verdict(name, "fail", f"check raised {type(exc).__name__}: {exc}"))
    return verdicts


# ---------------------------------------------------------------------------
# File acquisition and CODEOWNERS
# ---------------------------------------------------------------------------


def parse_codeowners(path: Path) -> set[str]:
    if not path.exists():
        return set()
    owners: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0]
        owners.update(m.lstrip("@") for m in re.findall(r"@[A-Za-z0-9-]+", line))
    return owners


def reader_prefix() -> list[str] | None:
    """The command prefix that runs the reader, or None when unconfigured.

    A docker sandbox image in CARTRIDGE_SANDBOX_IMAGE wraps CARTRIDGE_BIN with
    --network none and resource limits; otherwise CARTRIDGE_BIN runs directly.
    """
    binary = os.environ.get("CARTRIDGE_BIN")
    if not binary:
        return None
    image = os.environ.get("CARTRIDGE_SANDBOX_IMAGE")
    if image:
        return [
            "docker", "run", "--rm", "--network", "none", "--memory", "4g",
            "--pids-limit", "256", "-v", "{file}:/cart:ro", image,
            binary, "info", "--json", "/cart",
        ]
    return [binary]


# ---------------------------------------------------------------------------
# PR comment
# ---------------------------------------------------------------------------


def summary_comment(ctx: Ctx, verdicts: list[Verdict], ok: bool) -> str:
    doc = ctx.doc
    if ok:
        lines = [
            f"### Registry validation passed for `{doc['name']}`",
            "",
            f"- **name**: `{doc['name']}`",
            f"- **size**: {doc['size_bytes']:,} bytes",
            f"- **license**: {doc['license']}",
            f"- **source**: {doc['source_url']}",
            f"- **publisher**: {doc['publisher']}",
            "- **urls**:",
            *[f"  - {u}" for u in doc["urls"]],
        ]
    else:
        failed = [v for v in verdicts if v.status == "fail"]
        lines = [
            f"### Registry validation failed for `{doc.get('name', ctx.path.name)}`",
            "",
            "Failing checks:",
            *[f"- **{v.name}**: {v.reason}" for v in failed],
            "",
            "See POLICY.md and docs/registry.md, fix the listing, and push again.",
        ]
    skipped = [v for v in verdicts if v.status == "skip"]
    if skipped:
        lines += ["", "Skipped (not run):", *[f"- _{v.name}_: {v.reason}" for v in skipped]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command()
def main(
    listings: list[Path] = typer.Argument(..., help="Listing documents to validate."),
    author: str = typer.Option(None, "--author", help="PR author's GitHub login.", envvar="PR_AUTHOR"),
    pr_body: Path = typer.Option(None, "--pr-body", help="File holding the PR body text.", envvar="PR_BODY"),
    repo: str = typer.Option(None, "--repo", help="owner/name for the open-PR rate limit.", envvar="GITHUB_REPOSITORY"),
    token: str = typer.Option(None, "--token", help="GitHub token for API calls.", envvar="GITHUB_TOKEN"),
    registry_dir: Path = typer.Option(REPO_ROOT / "r", "--registry-dir", help="Directory holding listings."),
    codeowners: Path = typer.Option(REPO_ROOT / ".github" / "CODEOWNERS", "--codeowners", help="CODEOWNERS file."),
    base_file: Path = typer.Option(None, "--base-file", help="Prior version of the SAME listing (from main) for the version check."),
    file: Path = typer.Option(None, "--file", help="Local cartridge file (skip download for the byte/card checks)."),
    skip_network: bool = typer.Option(False, "--skip-network", help="Skip every network-dependent check (visibly)."),
    comment_out: Path = typer.Option(None, "--comment-out", help="Write the PR summary comment here."),
) -> None:
    body_text = pr_body.read_text() if pr_body is not None else None
    owner_set = parse_codeowners(codeowners)
    base_doc = json.loads(base_file.read_text()) if base_file is not None else None
    prefix = reader_prefix()

    all_ok = True
    last_ctx: Ctx | None = None
    last_verdicts: list[Verdict] = []

    if file is not None and not file.exists():
        raise FileNotFoundError(f"--file {file} does not exist")

    for listing in listings:
        doc = json.loads(listing.read_text())
        ctx = Ctx(
            doc=doc,
            path=listing,
            registry_dir=registry_dir,
            author=author,
            pr_body=body_text,
            codeowners=owner_set,
            base_doc=base_doc,
            skip_network=skip_network,
            local_file=file,
            token=token,
            reader_cmd_prefix=prefix,
            repo=repo,
            download_cache=[None],
        )
        verdicts = run_checks(ctx)
        ok = not any(v.status == "fail" for v in verdicts)
        all_ok = all_ok and ok

        typer.echo(f"{listing}: {'PASS' if ok else 'FAIL'}")
        for verdict in verdicts:
            typer.echo(verdict.line())
        last_ctx, last_verdicts = ctx, verdicts

    if comment_out is not None and last_ctx is not None:
        comment_out.write_text(summary_comment(last_ctx, last_verdicts, all_ok))

    if not all_ok:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
