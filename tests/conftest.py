"""Load the hyphenated CLI scripts as importable modules for the tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
STUB_READER = Path(__file__).resolve().parent / "bin" / "cartridge"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look themselves up here at class-creation time
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def validate():
    return _load("validate_mod", ROOT / "scripts" / "validate.py")


@pytest.fixture(scope="session")
def build_index():
    return _load("build_index_mod", ROOT / "scripts" / "build-index.py")


@pytest.fixture
def pass_listing() -> dict:
    return json.loads((FIXTURES / "pass" / "shakespeare.json").read_text())


@pytest.fixture
def card() -> dict:
    return json.loads((FIXTURES / "card.json").read_text())


@pytest.fixture
def cart_file() -> Path:
    return FIXTURES / "shakespeare.cart"
