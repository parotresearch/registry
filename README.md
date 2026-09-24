# Cartridge registry

A public directory of **cartridge listings**, designed for deployment as static
JSON under `https://cartridge.app/r/`.

The registry is a catalogue, not a host. It never stores cartridge files
themselves — those live on Hugging Face Hub or anywhere else the publisher puts
them. Each entry here is a small JSON document that says what a cartridge
contains, where to download it, its size and checksum, and the license it is
distributed under.

There is no application server and no database. **Git is the database, pull
requests are the write path, CI is the validator, and a human merge triggers
the static deployment workflow.** Every change is a pull request; automation
never merges it.

## What deployment serves

When the deployment workflow is configured, it publishes:

- `https://cartridge.app/r/index.json` — the full index: one
  `{name, title, size_bytes, version, license}` row per listing, sorted by name.
- `https://cartridge.app/r/<name>.json` — one listing document
  (`registry/<name>` listings live at `r/<name>.json`; third-party
  `<org>/<name>` listings live at `r/<org>/<name>.json`).

The same static tree is published to the configured GitHub Pages endpoint.

## Publishing a cartridge

The easy path is the presser:

```
cartpress push FILE.cart --name org/name --url https://…/name.cart
```

That opens a pull request adding `r/<org>/<name>.json` for you.

The manual path is to add the listing by hand and open a PR at
<https://github.com/parotresearch/registry/compare>:

1. Host your `.cart` file somewhere public over `https://` (not on
   `cartridge.app`).
2. Add `r/<org>/<name>.json` following the schema in
   [`docs/registry.md`](docs/registry.md).
3. Open a pull request; fill in the template and check the complete
   rights-warranty text exactly as written.

CI validates the listing and comments the result. It never merges — a
maintainer does that.

### Who can merge

Branch protection requires a code-owner review before merge. The seeded
`registry/*` catalogue is opened by the maintainer, who **cannot approve their
own pull request**; a repository admin holds the merge button for those. All
other rules (required checks, no force-push) apply to everyone.

## Validating locally

Everything CI runs is in `scripts/validate.py`, and it runs on your machine:

```
uv run scripts/validate.py r/shakespeare.json \
    --author YOUR_LOGIN \
    --pr-body /path/to/body.md \
    --skip-network
```

- `--skip-network` skips the checks that need the internet (URL reachability,
  GitHub org membership, the open-PR rate limit). They are reported as
  **skipped**, never as passed.
- `--file FILE.cart` uses a local cartridge file for the checksum and card
  checks instead of downloading it.
- Card comparison requires both `CARTRIDGE_BIN` and
  `CARTRIDGE_SANDBOX_IMAGE`; the reader is mounted into a no-network Docker
  container with a 4 GiB memory limit, a 256-process limit, and a hard timeout.
  The validator refuses to execute a reader directly.

CI defaults the reader URL to
`https://cartridge.app/dl/x86_64-unknown-linux-musl/cartridge.gz`. Set
`CARTRIDGE_READER_SHA256` to the digest published beside that gzip archive and
set `CARTRIDGE_SANDBOX_IMAGE` to a compatible image. A custom
`CARTRIDGE_READER_URL` must likewise name a gzip archive; CI verifies its
compressed bytes before unpacking it.

Regenerate the index and check it in sync:

```
uv run scripts/build-index.py          # rewrite r/index.json
uv run scripts/build-index.py --check  # fail if it is out of date (CI runs this)
```

Run the tests:

```
uv run pytest
```

## How deploys work

When a human merge pushes to `main`, `deploy.yml` is configured to:

1. Regenerate `r/index.json` and commit it back if it changed.
2. Publish the exact assembled static tree to the repository's GitHub Pages
   environment as a mirror.
3. Optionally deploy that same tree as the `cartridge-registry` **Cloudflare
   Workers static-assets** service on the path-specific Workers Route
   `cartridge.app/r/*`, with `Content-Type: application/json` and long-lived
   caching for every listing except `index.json`. The route takes precedence
   over the existing website's Pages custom domain only for `/r/*`; every other
   website path stays unchanged. This job is **skipped** until the user sets the
   `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets and flips the
   `CLOUDFLARE_DEPLOY` repository variable to `true`.

The reader-backed card check is skipped only while every reader setting is
absent. Once any reader setting is present, CI obtains the configured (or
default) gzip archive, requires its SHA256 and `CARTRIDGE_SANDBOX_IMAGE`, and
rejects incomplete configuration rather than running a reader outside its
sandbox.

## Learn more

- [`POLICY.md`](POLICY.md) — what may be listed, the license allowlist, the
  namespace rules, the rights warranty, and takedown.
- [`docs/registry.md`](docs/registry.md) — the full contract: every field of a
  listing, how references resolve, the PR flow, and every CI check.
- <https://cartridge.app/learn/07> — the registry, explained.
