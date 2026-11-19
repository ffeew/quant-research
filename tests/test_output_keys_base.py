"""Output field names (JSON / CSV / results keys) keep their base names after the desk-ref sweep.

The sweep renames internal identifiers only. Any identifier-like string literal or keyword-argument
name in base src that carries a desk name is an output key a downstream reader may depend on, so it
must still be present. Test JSON fixtures keep their base key sets.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = "f485f00"
NAMES = re.compile(r"(?i)(sofia|ethan|dave|tomas|victor|maya|marcus|dmitri|rachel|daniel|jeremy)")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# The only deliberate output-key renames since base: old name -> new name.
RENAMED = {
    "victor_pit_ruling_sha256": "validator_pit_ruling_sha256",
    "victor_passed": "validator_passed",
}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def _have_base() -> bool:
    try:
        _git("cat-file", "-e", f"{BASE}^{{commit}}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _have_base(), reason=f"base commit {BASE} not in this clone")


def _all_keys(src: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and IDENT.match(node.value):
            out.add(node.value)
        elif isinstance(node, ast.keyword) and node.arg:
            out.add(node.arg)
    return out


def _keys(src: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and IDENT.match(node.value):
            out.add(node.value)
        elif isinstance(node, ast.keyword) and node.arg:
            out.add(node.arg)
    return {k for k in out if NAMES.search(k)}


def _base_files(prefix: str, suffix: str) -> list[str]:
    return [f for f in _git("ls-tree", "-r", "--name-only", BASE, prefix).split() if f.endswith(suffix)]


def test_named_output_keys_match_base() -> None:
    base: set[str] = set()
    head: set[str] = set()
    for f in _base_files("src", ".py"):
        base |= _keys(_git("show", f"{BASE}:{f}"))
    for path in (ROOT / "src").rglob("*.py"):
        head |= _keys(path.read_text())
    assert base, "expected named output keys in base src"
    assert set(RENAMED) <= base
    assert sorted(base - head) == sorted(RENAMED)
    head_all: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        head_all |= _all_keys(path.read_text())
    assert set(RENAMED.values()) <= head_all


def _json_keys(obj: Any, path: str = "") -> set[str]:
    if isinstance(obj, dict):
        return {f"{path}/{k}" for k in obj} | {x for k, v in obj.items() for x in _json_keys(v, f"{path}/{k}")}
    if isinstance(obj, list):
        return {x for v in obj for x in _json_keys(v, f"{path}[]")}
    return set()


@pytest.mark.parametrize("rel", _base_files("tests", ".json") if _have_base() else [])
def test_json_fixture_keys_match_base(rel: str) -> None:
    base = _json_keys(json.loads(_git("show", f"{BASE}:{rel}")))
    assert _json_keys(json.loads((ROOT / rel).read_text())) == base
