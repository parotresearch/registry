"""build-index regenerates deterministically and --check catches staleness."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_INDEX = ROOT / "scripts" / "build-index.py"


def _write_listing(directory: Path, name: str, title: str, size: int, version: str, lic: str):
    directory.mkdir(parents=True, exist_ok=True)
    slug = name.split("/", 1)[1]
    (directory / f"{slug}.json").write_text(
        json.dumps(
            {"schema": 1, "name": name, "title": title, "size_bytes": size,
             "version": version, "license": lic, "extra": "ignored"}
        )
    )


def test_build_index_sorted_and_projected(build_index, tmp_path):
    _write_listing(tmp_path, "registry/zebra", "Zebra", 200, "1.0", "MIT")
    _write_listing(tmp_path, "registry/apple", "Apple", 100, "2.1", "CC0-1.0")
    index = build_index.build_index(tmp_path)
    assert [e["name"] for e in index] == ["registry/apple", "registry/zebra"]
    assert index[0] == {
        "name": "registry/apple", "title": "Apple", "size_bytes": 100,
        "version": "2.1", "license": "CC0-1.0",
    }
    # index.json itself is excluded from its own regeneration.
    (tmp_path / "index.json").write_text(build_index.render(index))
    assert [e["name"] for e in build_index.build_index(tmp_path)] == ["registry/apple", "registry/zebra"]


def test_check_passes_when_current(build_index, tmp_path):
    _write_listing(tmp_path, "registry/apple", "Apple", 100, "1.0", "MIT")
    (tmp_path / "index.json").write_text(build_index.render(build_index.build_index(tmp_path)))
    result = subprocess.run(
        [sys.executable, str(BUILD_INDEX), "--registry-dir", str(tmp_path), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_check_fails_when_stale(build_index, tmp_path):
    _write_listing(tmp_path, "registry/apple", "Apple", 100, "1.0", "MIT")
    (tmp_path / "index.json").write_text("[]\n")  # stale
    result = subprocess.run(
        [sys.executable, str(BUILD_INDEX), "--registry-dir", str(tmp_path), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "STALE" in result.stderr


def test_repo_index_is_current(build_index):
    """The committed r/index.json is in sync with the listings in r/."""
    registry_dir = ROOT / "r"
    expected = build_index.render(build_index.build_index(registry_dir))
    assert (registry_dir / "index.json").read_text() == expected
