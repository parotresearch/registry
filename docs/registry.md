# The registry contract

This is the binding description of what a registry listing is, how it is
referenced, how it is validated, and how it is served. It complements
[`POLICY.md`](../POLICY.md), which governs *what* may be listed; this document
governs the *form*.

## The listing document

One listing lives at `r/<name>.json` (or `r/<org>/<name>.json`). It is validated
against [`schema/listing.schema.json`](../schema/listing.schema.json), which
forbids unknown fields. Its `card` field is validated against
[`schema/card.schema.json`](../schema/card.schema.json), a verbatim copy of the
Card 1.0 object the presser embeds in every cartridge.

```json
{
  "schema": 1,
  "name": "registry/wikipedia-en",
  "title": "English Wikipedia",
  "version": "2026.09",
  "publisher": "Parot",
  "license": "CC-BY-SA-4.0",
  "source_url": "https://dumps.wikimedia.org/enwiki/",
  "warranty": true,
  "description": "Full text of English Wikipedia articles, one record per article.",
  "size_bytes": 4831838208,
  "sha256": "<64 lowercase hex>",
  "filename": "wikipedia-en.cart",
  "urls": ["https://huggingface.co/datasets/parotresearch/wikipedia-en/resolve/main/wikipedia-en.cart"],
  "card": { "…": "the full Card 1.0 object" },
  "published_at": "2026-09-08T00:00:00Z",
  "homepage": "https://cartridge.app/marketplace/parotresearch/wikipedia-en"
}
```

### Fields

| field | required | type | meaning |
| --- | --- | --- | --- |
| `schema` | yes | `1` | Listing document version. Fixed at 1. |
| `name` | yes | string | `registry/<slug>` or `<org-slug>/<slug>`. See the resolution table below. |
| `title` | yes | string | Human title shown for the listing. |
| `version` | yes | string | Dotted numeric (e.g. `2026.09`). An existing `name` may change only when this increases. |
| `publisher` | yes | string | Who published the listing. |
| `license` | yes | string | SPDX id (or `public-domain`) from the allowlist in POLICY.md. |
| `source_url` | yes | string | `https://` — where the underlying material came from. |
| `warranty` | yes | boolean | Must be `true`; the PR body must also carry the checked, complete rights warranty exactly as written in POLICY.md. |
| `description` | no | string | One or two plain sentences about the contents. |
| `size_bytes` | yes | integer | Size of the cartridge file, `1 …` up to the 50 GiB cap. |
| `sha256` | yes | string | Lowercase hex SHA256 of the cartridge file bytes. |
| `filename` | yes | string | The cartridge file name. Exactly one path component: no slashes. |
| `urls` | yes | array | One or more `https://` URLs where the bytes live, tried in order (mirrors). No host may be `cartridge.app` or a subdomain of it. |
| `card` | yes | object | The full Card 1.0 object, copied verbatim from the cartridge. |
| `published_at` | yes | string | RFC3339 timestamp. |
| `homepage` | no | string | `https://` page describing the cartridge. |

`urls` is a **list** so a listing can name several mirrors; a reader tries them
in order. `homepage` and `description` are the only optional fields; everything
else is required.

## Reference resolution

A `name` maps to a path under `r/` and to a served URL:

| reference | file | served at |
| --- | --- | --- |
| `registry/<name>` | `r/<name>.json` | `/r/<name>.json` |
| `<org>/<name>` | `r/<org>/<name>.json` | `/r/<org>/<name>.json` |
| bare `<name>` | — | shorthand for `registry/<name>` |

A bare name with no slash means the reserved `registry/` namespace. The
`registry/` prefix does **not** add a directory level: `registry/shakespeare`
is the file `r/shakespeare.json`, not `r/registry/shakespeare.json`.

## The index

`r/index.json` is **generated** by `scripts/build-index.py` and must never be
hand-edited. It is a JSON array, sorted by `name`, of one compact row per
listing:

```json
[
  {"name": "registry/shakespeare", "title": "…", "size_bytes": 2048, "version": "2026.09", "license": "public-domain"}
]
```

`build-index.py --check` fails if the committed index is out of date; CI runs it
on every pull request, so a listing PR must also commit the regenerated index.

## Pull-request flow

1. Add or edit a listing under `r/`, and regenerate `r/index.json`.
2. Open a pull request into `main`. Fill in the template, including the rights
   warranty checkbox.
3. `validate.yml` runs every check below on each changed listing and comments
   the result. On success it comments a summary (name, size, license, source,
   publisher, URLs); on failure it comments the exact failing check.
4. A maintainer reviews and merges. **Automation never merges.** For the
   reserved `registry/*` catalogue, whose PRs are opened by the code owner, a
   repository admin merges (an author cannot approve their own PR).
5. Merging pushes to `main`, which runs `deploy.yml` and republishes the site.

## CI checks

Every check is reported by name with `pass` / `fail` / `skip` and an exact
reason. A check that cannot run because the network is disabled is reported as
**skipped**, visibly and distinctly, never as passed. A reader configuration
that is present but incomplete fails the PR instead of skipping or running the
reader directly.

| check | what it verifies |
| --- | --- |
| `schema` | Valid against `listing.schema.json` (card included); unknown fields rejected; `schema` is `1`. |
| `name` | File path matches `name`; slug rules; `filename` is one path component; `registry/*` only from a CODEOWNER; on an edit, `version` increased. |
| `namespace` | For `<org>/<name>`, `<org>` is the author's GitHub login or an org they are a public member of. *(network)* |
| `url` | Every URL is `https://`; no host is `cartridge.app` or a subdomain; `size_bytes` is within the 50 GiB cap. |
| `url-reachable` | Each URL answers a HEAD (following redirects) and its `Content-Length` equals `size_bytes`. *(network)* |
| `bytes` | The downloaded file's SHA256 equals `sha256`. *(needs the file)* |
| `card-check` | When a reader is configured, it is required: the reader runs in a no-network, resource-limited container, exits 0, the file is **sealed**, and the card inside the file equals the listing's `card` field (the first differing path is reported). Without reader configuration, it is visibly skipped. |
| `license` | `license` is on the allowlist, else it fails with a pointer to POLICY.md. |
| `warranty` | `warranty` is `true` **and** the PR body carries the checked, complete rights warranty exactly as written in POLICY.md. |
| `rate-limit` | The author has at most five open PRs in this repo. *(network)* |

The card comparison uses `cartridge info FILE --json`. That command prints a
wrapper object — `{archive, card, case_mode, codec, flags, manifest, seal,
shards, sizes, version}` — and the check reads two fields from it: `.card` (the
Card 1.0 object, which must equal the listing's `card`) and `.seal.status` (a
string). A licensed press writes `valid`, or `legacy` until the press service
ships; both are accepted. `missing`, `unsealed`, `invalid`, or an absent seal
are refused with the status named. Reader compatibility and an accepted seal
status do not identify how a file was pressed; the policy, card, and seal gates
enforce the advertised publication contract.
The same Card 1.0 object can also be printed bare with
`cartridge card show FILE --json`.

The reader is never executed directly. It runs through `timeout --kill-after=5s
120s docker run --rm --network none --memory 4g --pids-limit 256 --read-only`,
with the reader and file mounted read-only. The workflow defaults
`CARTRIDGE_READER_URL` to the supported
`https://cartridge.app/dl/x86_64-unknown-linux-musl/cartridge.gz` release
archive; it may be overridden with another compatible gzip archive. Its
`CARTRIDGE_READER_SHA256` value must hash the downloaded gzip bytes before
unpacking. CI also requires `CARTRIDGE_SANDBOX_IMAGE`; a partial configuration
fails loudly.

## Deploy path

On every push to `main`:

1. `r/index.json` is regenerated and committed back if it changed.
2. The exact assembled static tree is published to **GitHub Pages** (build
   type: workflow) as a mirror, immediately live at
   `https://parotresearch.github.io/registry/r/`.
3. Optionally that same tree is deployed as the `cartridge-registry`
   **Cloudflare Workers static-assets** service on the path-specific Workers
   Route `cartridge.app/r/*`. That route takes precedence over the existing
   website's Pages custom domain only for `/r/*`; every other website path
   stays unchanged. The `_headers` file sets `Content-Type: application/json`
   for `/r/*` and `Cache-Control: public, max-age=31536000, immutable` for
   every listing, except `index.json` which gets `max-age=300`. This job is
   skipped until the Cloudflare secrets and the `CLOUDFLARE_DEPLOY` variable
   are set.

Because a merge is the deploy and the site is generated from this repository,
delisting is just reverting a pull request and letting the next deploy run.
