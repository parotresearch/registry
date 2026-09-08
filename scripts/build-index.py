#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["typer>=0.12"]
# ///
"""Regenerate r/index.json from every listing under r/ (excluding index.json).

The index is a JSON array of {name, title, size_bytes, version, license} for
every listing, sorted by name. It is a GENERATED file: never hand-edit it, and
`--check` fails loudly when it is out of date.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

app = typer.Typer(add_completion=False, help=__doc__)

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_KEYS = ("name", "title", "size_bytes", "version", "license")


def listing_paths(registry_dir: Path) -> list[Path]:
    """Every listing file under r/, excluding the generated index.json."""
    return sorted(
        p
        for p in registry_dir.rglob("*.json")
        if p.name != "index.json"
    )


def index_entry(path: Path) -> dict:
    """The compact index row for one listing document."""
    doc = json.loads(path.read_text())
    missing = [k for k in INDEX_KEYS if k not in doc]
    if missing:
        raise ValueError(f"{path}: listing is missing index fields {missing}")
    return {k: doc[k] for k in INDEX_KEYS}


def build_index(registry_dir: Path) -> list[dict]:
    """The full index array, sorted by name."""
    entries = [index_entry(p) for p in listing_paths(registry_dir)]
    return sorted(entries, key=lambda e: e["name"])


def render(index: list[dict]) -> str:
    """Deterministic on-disk form: 2-space indent, trailing newline."""
    return json.dumps(index, indent=2, ensure_ascii=False) + "\n"


@app.command()
def main(
    registry_dir: Path = typer.Option(
        REPO_ROOT / "r", "--registry-dir", help="Directory holding listing documents."
    ),
    check: bool = typer.Option(
        False, "--check", help="Verify index.json is current; exit non-zero if stale."
    ),
) -> None:
    index_path = registry_dir / "index.json"
    rendered = render(build_index(registry_dir))

    if check:
        current = index_path.read_text() if index_path.exists() else "<missing>"
        if current == rendered:
            typer.echo(f"index up to date ({index_path})")
            return
        typer.echo(
            f"STALE: {index_path} is out of date. Run scripts/build-index.py to regenerate.",
            err=True,
        )
        raise typer.Exit(code=1)

    index_path.write_text(rendered)
    typer.echo(f"wrote {index_path} ({len(json.loads(rendered))} listings)")


if __name__ == "__main__":
    app()
