"""End-to-end: the validate.py CLI passes the good fixture and fails a bad one."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATE = ROOT / "scripts" / "validate.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PASS_DIR = FIXTURES / "pass"
STUB_READER = Path(__file__).resolve().parent / "bin" / "cartridge"


def _run(args, env_extra=None):
    env = dict(os.environ)
    env["CARTRIDGE_BIN"] = str(STUB_READER)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(VALIDATE), *args],
        capture_output=True, text=True, env=env,
    )


def test_cli_passes_good_listing(tmp_path):
    body = tmp_path / "body.md"
    body.write_text("Intro.\n- [x] I have the right to distribute this content in this form.\n")
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text("r/* @vmasrani\n")
    result = _run([
        str(PASS_DIR / "shakespeare.json"),
        "--skip-network",
        "--file", str(FIXTURES / "shakespeare.cart"),
        "--author", "vmasrani",
        "--pr-body", str(body),
        "--codeowners", str(codeowners),
        "--registry-dir", str(PASS_DIR),
        "--comment-out", str(tmp_path / "comment.md"),
    ])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "card-check" in result.stdout
    comment = (tmp_path / "comment.md").read_text()
    assert "validation passed" in comment
    assert "registry/shakespeare" in comment


def test_cli_fails_bad_license(tmp_path):
    import json
    doc = json.loads((PASS_DIR / "shakespeare.json").read_text())
    doc["license"] = "GPL-3.0-only"
    bad = tmp_path / "shakespeare.json"
    bad.write_text(json.dumps(doc))
    body = tmp_path / "body.md"
    body.write_text("- [x] I have the right to distribute this content in this form.\n")
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text("r/* @vmasrani\n")
    result = _run([
        str(bad),
        "--skip-network",
        "--file", str(FIXTURES / "shakespeare.cart"),
        "--author", "vmasrani",
        "--pr-body", str(body),
        "--codeowners", str(codeowners),
        "--registry-dir", str(tmp_path),
    ])
    assert result.returncode == 1
    assert "license" in result.stdout
