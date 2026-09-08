"""Every check has a passing fixture and a failing fixture.

Network-dependent checks run against a local http.server, never the internet.
"""

from __future__ import annotations

import copy
import http.server
import json
import socketserver
import threading
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PASS_DIR = FIXTURES / "pass"
PASS_PATH = PASS_DIR / "shakespeare.json"
STUB_READER = Path(__file__).resolve().parent / "bin" / "cartridge"


def make_ctx(validate, doc, **overrides):
    defaults = dict(
        doc=doc,
        path=PASS_PATH,
        registry_dir=PASS_DIR,
        author="vmasrani",
        pr_body=None,
        codeowners={"vmasrani"},
        base_doc=None,
        skip_network=True,
        local_file=None,
        token=None,
        reader_cmd_prefix=None,
        repo=None,
    )
    defaults.update(overrides)
    return validate.Ctx(**defaults)


def status_of(verdicts, name):
    matches = [v for v in verdicts if v.name == name]
    assert matches, f"no verdict named {name}"
    return matches[0].status


# --------------------------------------------------------------------------- schema


def test_schema_valid(validate, pass_listing):
    ctx = make_ctx(validate, pass_listing)
    assert validate.check_schema(ctx)[0].status == "pass"


def test_schema_unknown_field(validate, pass_listing):
    doc = copy.deepcopy(pass_listing)
    doc["surprise"] = 1
    ctx = make_ctx(validate, doc)
    verdict = validate.check_schema(ctx)[0]
    assert verdict.status == "fail"
    assert "surprise" in verdict.reason or "additional" in verdict.reason.lower()


def test_schema_wrong_schema_const(validate, pass_listing):
    doc = copy.deepcopy(pass_listing)
    doc["schema"] = 2
    ctx = make_ctx(validate, doc)
    assert validate.check_schema(ctx)[0].status == "fail"


def test_schema_filename_with_slash(validate, pass_listing):
    doc = copy.deepcopy(pass_listing)
    doc["filename"] = "sub/shakespeare.cart"
    ctx = make_ctx(validate, doc)
    # The schema pattern rejects a slashed filename...
    assert validate.check_schema(ctx)[0].status == "fail"
    # ...and so does the name check, with a clear message.
    assert validate.check_name(ctx)[0].status == "fail"


# --------------------------------------------------------------------------- name


def test_name_ok(validate, pass_listing):
    ctx = make_ctx(validate, pass_listing)
    assert validate.check_name(ctx)[0].status == "pass"


def test_name_path_mismatch(validate, pass_listing, tmp_path):
    doc = copy.deepcopy(pass_listing)
    wrong = tmp_path / "notshakespeare.json"
    wrong.write_text(json.dumps(doc))
    ctx = make_ctx(validate, doc, path=wrong, registry_dir=tmp_path)
    assert validate.check_name(ctx)[0].status == "fail"


def test_name_bad_slug(validate, pass_listing, tmp_path):
    doc = copy.deepcopy(pass_listing)
    doc["name"] = "registry/-bad-"
    p = tmp_path / "-bad-.json"
    ctx = make_ctx(validate, doc, path=p, registry_dir=tmp_path)
    assert validate.check_name(ctx)[0].status == "fail"


def test_name_registry_from_non_codeowner(validate, pass_listing):
    ctx = make_ctx(validate, pass_listing, author="stranger", codeowners={"vmasrani"})
    verdict = validate.check_name(ctx)[0]
    assert verdict.status == "fail"
    assert "reserved" in verdict.reason.lower()


def test_name_version_not_increased(validate, pass_listing):
    base = copy.deepcopy(pass_listing)  # same version 2026.09
    ctx = make_ctx(validate, pass_listing, base_doc=base)
    verdict = validate.check_name(ctx)[0]
    assert verdict.status == "fail"
    assert "higher version" in verdict.reason


def test_name_version_increased_ok(validate, pass_listing):
    base = copy.deepcopy(pass_listing)
    doc = copy.deepcopy(pass_listing)
    doc["version"] = "2026.10"
    ctx = make_ctx(validate, doc, base_doc=base)
    assert validate.check_name(ctx)[0].status == "pass"


# --------------------------------------------------------------------------- namespace


def test_namespace_author_owns(validate, pass_listing, tmp_path):
    doc = copy.deepcopy(pass_listing)
    doc["name"] = "octocat/plays"
    p = tmp_path / "octocat" / "plays.json"
    ctx = make_ctx(validate, doc, path=p, registry_dir=tmp_path, author="octocat")
    assert validate.check_namespace(ctx)[0].status == "pass"


def test_namespace_skip_when_offline(validate, pass_listing, tmp_path):
    doc = copy.deepcopy(pass_listing)
    doc["name"] = "acme/plays"
    ctx = make_ctx(validate, doc, author="octocat", skip_network=True)
    assert validate.check_namespace(ctx)[0].status == "skip"


def test_namespace_mismatch_fails(validate, pass_listing, monkeypatch):
    doc = copy.deepcopy(pass_listing)
    doc["name"] = "acme/plays"
    monkeypatch.setattr(validate, "_org_member", lambda org, login, token: False)
    ctx = make_ctx(validate, doc, author="octocat", skip_network=False)
    verdict = validate.check_namespace(ctx)[0]
    assert verdict.status == "fail"


# --------------------------------------------------------------------------- url


def test_url_ok(validate, pass_listing):
    ctx = make_ctx(validate, pass_listing)
    assert validate.check_url(ctx)[0].status == "pass"


def test_url_non_https(validate, pass_listing):
    doc = copy.deepcopy(pass_listing)
    doc["urls"] = ["http://example.com/x.cart"]
    ctx = make_ctx(validate, doc)
    assert validate.check_url(ctx)[0].status == "fail"


def test_url_cartridge_app_host(validate, pass_listing):
    doc = copy.deepcopy(pass_listing)
    doc["urls"] = ["https://cartridge.app/files/x.cart"]
    ctx = make_ctx(validate, doc)
    verdict = validate.check_url(ctx)[0]
    assert verdict.status == "fail"
    assert "cartridge.app" in verdict.reason


def test_url_cartridge_app_subdomain(validate, pass_listing):
    doc = copy.deepcopy(pass_listing)
    doc["urls"] = ["https://cdn.cartridge.app/x.cart"]
    ctx = make_ctx(validate, doc)
    assert validate.check_url(ctx)[0].status == "fail"


# --------------------------------------------------------------------------- url reachable (local http.server)


class _FixedSizeHandler(http.server.BaseHTTPRequestHandler):
    payload = b""

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()

    def log_message(self, *args):
        pass


def _serve(payload: bytes):
    _FixedSizeHandler.payload = payload
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _FixedSizeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]


def test_url_reachable_content_length_matches(validate, pass_listing, cart_file):
    payload = cart_file.read_bytes()
    httpd, port = _serve(payload)
    try:
        doc = copy.deepcopy(pass_listing)
        doc["size_bytes"] = len(payload)
        doc["urls"] = [f"http://127.0.0.1:{port}/x.cart"]
        ctx = make_ctx(validate, doc, skip_network=False)
        assert validate.check_url_reachable(ctx)[0].status == "pass"
    finally:
        httpd.shutdown()


def test_url_reachable_wrong_size(validate, pass_listing, cart_file):
    payload = cart_file.read_bytes()
    httpd, port = _serve(payload)
    try:
        doc = copy.deepcopy(pass_listing)
        doc["size_bytes"] = len(payload) + 1  # mismatch
        doc["urls"] = [f"http://127.0.0.1:{port}/x.cart"]
        ctx = make_ctx(validate, doc, skip_network=False)
        verdict = validate.check_url_reachable(ctx)[0]
        assert verdict.status == "fail"
        assert "Content-Length" in verdict.reason
    finally:
        httpd.shutdown()


def test_url_reachable_skips_offline(validate, pass_listing):
    ctx = make_ctx(validate, pass_listing, skip_network=True)
    assert validate.check_url_reachable(ctx)[0].status == "skip"


class _HeadOkGetFailsHandler(http.server.BaseHTTPRequestHandler):
    """HEAD succeeds with the right size, but the actual download 404s."""

    payload = b""

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()

    def do_GET(self):
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_download_failure_is_loud_fail_not_masked_skip(validate, pass_listing, cart_file):
    # Regression: a dead download must be a FAIL verdict, never a crash and
    # never a bytes SKIP that hides behind a green url-reachable.
    payload = cart_file.read_bytes()
    _HeadOkGetFailsHandler.payload = payload
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _HeadOkGetFailsHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        doc = copy.deepcopy(pass_listing)
        doc["size_bytes"] = len(payload)
        doc["urls"] = [f"http://127.0.0.1:{port}/x.cart"]
        ctx = make_ctx(validate, doc, skip_network=False, download_cache=[None])
        verdicts = validate.run_checks(ctx)
        assert status_of(verdicts, "url-reachable") == "pass"  # HEAD is fine
        assert status_of(verdicts, "bytes") == "fail"  # GET 404 -> loud fail
    finally:
        httpd.shutdown()


# --------------------------------------------------------------------------- bytes


def test_bytes_match(validate, pass_listing, cart_file):
    ctx = make_ctx(validate, pass_listing, local_file=cart_file)
    assert validate.check_bytes(ctx)[0].status == "pass"


def test_bytes_wrong_hash(validate, pass_listing, cart_file):
    doc = copy.deepcopy(pass_listing)
    doc["sha256"] = "0" * 64
    ctx = make_ctx(validate, doc, local_file=cart_file)
    assert validate.check_bytes(ctx)[0].status == "fail"


def test_bytes_skip_no_file(validate, pass_listing):
    ctx = make_ctx(validate, pass_listing, local_file=None)
    assert validate.check_bytes(ctx)[0].status == "skip"


# --------------------------------------------------------------------------- card


def test_card_match(validate, pass_listing, cart_file):
    ctx = make_ctx(validate, pass_listing, local_file=cart_file, reader_cmd_prefix=[str(STUB_READER)])
    assert validate.check_card(ctx)[0].status == "pass"


def test_card_mismatch(validate, pass_listing, cart_file):
    doc = copy.deepcopy(pass_listing)
    doc["card"]["identity"]["title"] = "A Different Title"
    ctx = make_ctx(validate, doc, local_file=cart_file, reader_cmd_prefix=[str(STUB_READER)])
    verdict = validate.check_card(ctx)[0]
    assert verdict.status == "fail"
    assert "identity.title" in verdict.reason


def test_card_skip_no_reader(validate, pass_listing, cart_file):
    ctx = make_ctx(validate, pass_listing, local_file=cart_file, reader_cmd_prefix=None)
    assert validate.check_card(ctx)[0].status == "skip"


def test_card_unsealed_fails(validate, pass_listing, card, cart_file, monkeypatch):
    monkeypatch.setattr(validate, "run_reader", lambda prefix, path: {"card": card, "seal": False})
    ctx = make_ctx(validate, pass_listing, local_file=cart_file, reader_cmd_prefix=["x"])
    verdict = validate.check_card(ctx)[0]
    assert verdict.status == "fail"
    assert "sealed" in verdict.reason


def test_card_missing_seal_field_fails(validate, pass_listing, card, cart_file, monkeypatch):
    monkeypatch.setattr(validate, "run_reader", lambda prefix, path: {"card": card})
    ctx = make_ctx(validate, pass_listing, local_file=cart_file, reader_cmd_prefix=["x"])
    verdict = validate.check_card(ctx)[0]
    assert verdict.status == "fail"
    assert "seal" in verdict.reason


# --------------------------------------------------------------------------- license


def test_license_ok(validate, pass_listing):
    ctx = make_ctx(validate, pass_listing)
    assert validate.check_license(ctx)[0].status == "pass"


def test_license_off_allowlist(validate, pass_listing):
    doc = copy.deepcopy(pass_listing)
    doc["license"] = "GPL-3.0-only"
    ctx = make_ctx(validate, doc)
    verdict = validate.check_license(ctx)[0]
    assert verdict.status == "fail"
    assert "POLICY.md" in verdict.reason


# --------------------------------------------------------------------------- warranty


def test_warranty_ok(validate, pass_listing):
    body = "Some intro.\n- [x] I have the right to distribute this content in this form.\nmore"
    ctx = make_ctx(validate, pass_listing, pr_body=body)
    assert validate.check_warranty(ctx)[0].status == "pass"


def test_warranty_false_in_doc(validate, pass_listing):
    doc = copy.deepcopy(pass_listing)
    doc["warranty"] = False
    ctx = make_ctx(validate, doc, pr_body="- [x] I have the right to distribute this content in this form.")
    assert validate.check_warranty(ctx)[0].status == "fail"


def test_warranty_checkbox_unchecked(validate, pass_listing):
    body = "Some intro.\n- [ ] I have the right to distribute this content in this form.\n"
    ctx = make_ctx(validate, pass_listing, pr_body=body)
    verdict = validate.check_warranty(ctx)[0]
    assert verdict.status == "fail"
    assert "checkbox" in verdict.reason


# --------------------------------------------------------------------------- rate limit


def test_rate_limit_skips_offline(validate, pass_listing):
    ctx = make_ctx(validate, pass_listing, skip_network=True, repo="parotresearch/registry")
    assert validate.check_rate_limit(ctx)[0].status == "skip"


# --------------------------------------------------------------------------- full run


def test_full_run_passes_offline(validate, pass_listing, cart_file):
    body = "Intro.\n- [x] I have the right to distribute this content in this form.\n"
    ctx = make_ctx(
        validate,
        pass_listing,
        pr_body=body,
        local_file=cart_file,
        reader_cmd_prefix=[str(STUB_READER)],
    )
    verdicts = validate.run_checks(ctx)
    fails = [v for v in verdicts if v.status == "fail"]
    assert not fails, [v.line() for v in fails]
    # The offline-only checks are visibly skipped, not passed.
    assert status_of(verdicts, "url-reachable") == "skip"
    assert status_of(verdicts, "rate-limit") == "skip"
    # The card path really ran against the stub reader.
    assert status_of(verdicts, "card-check") == "pass"
