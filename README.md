# Cartridge registry

A public directory of **cartridge listings**, served as static JSON at
`https://cartridge.app/r/`.

The registry is a catalogue, not a host. It never stores cartridge files
themselves — those live on Hugging Face Hub or anywhere else the publisher puts
them. Each entry here is a small JSON document that says what a cartridge
contains, where to download it, its size and checksum, and the license it is
distributed under.

There is no server and no database. **GitHub is the database, pull requests are
the write path, CI is the validator, and a merge is the deploy.** Every change
is a pull request; a human merges it; merging regenerates and republishes the
static site.

## What is served

- `https://cartridge.app/r/index.json` — the full index: one
  `{name, title, size_bytes, version, license}` row per listing, sorted by name.
- `https://cartridge.app/r/<name>.json` — one listing document
  (`registry/<name>` listings live at `r/<name>.json`; third-party
  `<org>/<name>` listings live at `r/<org>/<name>.json`).

The same tree is also live on GitHub Pages at
`https://parotresearch.github.io/registry/r/index.json`.

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
3. Open a pull request; fill in the template, including the rights-warranty
   checkbox.

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
- Point `CARTRIDGE_BIN` at a `cartridge` reader to run the card comparison
  locally; without it, that check is skipped visibly.
- `--file FILE.cart` uses a local cartridge file for the checksum and card
  checks instead of downloading it.

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

On every push to `main` (i.e. after a merge), `deploy.yml`:

1. Regenerates `r/index.json` and commits it back if it changed.
2. Publishes the `r/` tree to **GitHub Pages** — live immediately at
   `https://parotresearch.github.io/registry/r/`.
3. Optionally publishes the same tree to **Cloudflare**, routed at
   `cartridge.app/r/*`, with `Content-Type: application/json` and long-lived
   caching for every listing except `index.json`. This job is **skipped** until
   the user sets the `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` secrets
   and flips the `CLOUDFLARE_DEPLOY` repository variable to `true`.

The reader-backed card check in `validate.yml` is likewise **skipped** until the
`CARTRIDGE_READER_URL` and `CARTRIDGE_READER_SHA256` repository variables are
set.

## Learn more

- [`POLICY.md`](POLICY.md) — what may be listed, the license allowlist, the
  namespace rules, the rights warranty, and takedown.
- [`docs/registry.md`](docs/registry.md) — the full contract: every field of a
  listing, how references resolve, the PR flow, and every CI check.
- <https://cartridge.app/learn/07> — the registry, explained.
