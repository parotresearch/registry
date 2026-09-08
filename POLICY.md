# Registry policy

The Cartridge registry is a directory of listings. It never stores the
cartridge files themselves — those live wherever the publisher puts them
(Hugging Face Hub, an object store, any host). A listing is a small JSON
document that says what a cartridge contains, where to get it, and under what
license.

## What a cartridge is, for policy purposes

A cartridge reproduces its source **byte for byte**. Anyone who opens it can
read the original text back out in full. So listing a cartridge is
**redistributing the text**, not merely pointing at an index of it. Every rule
below follows from that one fact: if you may not republish the underlying text
in a public place, you may not list a cartridge of it here.

## What you may list

- Public-domain works (e.g. Project Gutenberg texts, expired-copyright material).
- Content under an open license from the allowlist below.
- Government open data and other officially published open datasets.
- Corpora you own outright, or created yourself.
- Material that was already released publicly with no restriction on
  redistribution. The Enron email corpus is the canonical example.

## What you may not list

- Scrapes of websites whose terms forbid redistribution.
- Books, news articles, song lyrics, transcripts, or paywalled text that the
  publisher does not own.
- Anything containing personal data that was not already lawfully public.
- Anything containing credentials, secrets, or private keys.

If you are unsure whether you have the right to redistribute something, you do
not list it.

## License allowlist

A listing's `license` must be one of these SPDX identifiers (or
`public-domain`). Anything else is refused by CI:

| id | name |
| --- | --- |
| `CC0-1.0` | Creative Commons Zero (public domain dedication) |
| `CC-BY-4.0` | Creative Commons Attribution 4.0 |
| `CC-BY-SA-4.0` | Creative Commons Attribution-ShareAlike 4.0 |
| `ODbL-1.0` | Open Database License 1.0 |
| `PDDL-1.0` | Open Data Commons Public Domain Dedication and License 1.0 |
| `MIT` | MIT License |
| `Apache-2.0` | Apache License 2.0 |
| `public-domain` | Works in the public domain with no single SPDX license |

To propose adding a license, open an issue; do not work around the list.

## Namespaces

- `registry/<name>` is the reserved, first-party catalogue. Only the
  maintainers listed in `.github/CODEOWNERS` may add or change these listings.
- `<org>/<name>` is a third-party namespace. You may publish under `<org>`
  only when `<org>` is your own GitHub login, or a GitHub organization you are
  a **public** member of. CI checks this against your GitHub account.
- Slugs are lowercase `[a-z0-9-]`, 1–64 characters, with no leading or
  trailing hyphen.
- An existing listing may only change when its `version` increases, and only
  by someone who owns the namespace.

## The rights warranty

Every listing carries a warranty, stated once in the pull-request template and
repeated here verbatim:

> I have the right to distribute this content in this form. A cartridge
> reproduces its source byte for byte, so listing it is redistributing the
> text. If someone claims otherwise, the listing comes down while it is
> resolved, and the DMCA agent named at cartridge.app/legal handles the notice.

Both the listing document (`warranty: true`) and the checked checkbox in the
pull-request body are required. A listing without both is refused.

## Attribution

Every listing records its license and source, and any application that ships
with a cartridge must carry that attribution through to the people who use it.

## Takedown

A complaint to **legal@cartridge.app** is handled in two steps:

1. **Delist first.** The listing is reverted and the registry is redeployed —
   a matter of minutes — so it stops appearing while the claim is examined.
2. **Resolve second.** The DMCA agent named at cartridge.app/legal handles the
   formal notice and any counter-notice.

Because the registry is generated from this git repository and a merge is the
deploy, delisting is just reverting a pull request. Publishers who repeatedly
list material they have no right to distribute lose their namespace.

## No encryption at rest

Do not list anything you would not put on a public bucket. Listings are public,
the bytes they point at are public, and nothing here is a place to hide
sensitive material behind a key.
