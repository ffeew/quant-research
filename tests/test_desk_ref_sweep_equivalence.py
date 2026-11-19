"""The desk-reference sweep changed no logic.

Each swept module is compared with its pre-sweep version (git ``REF``) as an AST, after dropping
docstrings and the added ``desk_pin`` import:

- a ``desk_pin(ns, key)`` call must sit exactly where the old module had a sha256 literal, so the
  code is the old code once the desk pin file holds the old values;
- any other changed string must be prose in which only person names and review references
  (line refs, ticket ids, review ids) were swapped for role words, with every number kept;
- everything else must be identical.

A file edited after the sweep is skipped (its recorded git blob no longer matches).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from quant_research.utils import pins
from quant_research.utils.config import REPO_ROOT

REF = "f485f00"  # main before the sweep
PINS_FILE = REPO_ROOT / "configs" / "pins" / "desk_pins.toml"
HEX64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
ROLE_WORDS = {
    "the",
    "validator",
    "fund",
    "manager",
    "data",
    "owner",
    "derivatives",
    "researcher",
    "risk",
    "tca",
    "engineer",
    "sentiment",
    "stat",
    "arb",
    "portfolio",
    "construction",
    "lead",
    "decision",
    "decisions",
    "internal",
    "review",
    "record",
}
REF_TOKENS = [
    re.compile(r"\bL\d+(?:[-–]L?\d+)?"),
    re.compile(r"\bINC-?\d+\w*"),
    re.compile(r"[Rr]uling\s+\d\w*(?:-\d+)?"),
]
# git blob of each swept file right after the sweep (kept as data so code greps over tests stay clean)
SWEPT: dict[str, str] = json.loads((Path(__file__).with_name("desk_ref_sweep_blobs.json")).read_text())


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=True, timeout=60
    ).stdout


def _strip(tree: ast.Module, drop_pin_import: bool) -> ast.Module:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    if drop_pin_import:
        tree.body = [
            n for n in tree.body if not (isinstance(n, ast.ImportFrom) and n.module == "quant_research.utils.pins")
        ]
    return tree


def _words(s: str) -> list[str]:
    return re.findall(r"[A-Za-z]+|\d+", s)


def prose_ok(old: str, new: str) -> bool:
    """Only names / review refs swapped for role words; numbers unchanged."""
    if " " not in old:
        return False
    digits_old, digits_new = Counter(re.findall(r"\d+", old)), Counter(re.findall(r"\d+", new))
    in_refs = Counter(d for r in REF_TOKENS for m in r.findall(old) for d in re.findall(r"\d+", m))
    if digits_new - digits_old or (digits_old - digits_new) - in_refs:
        return False
    removed = Counter(_words(old)) - Counter(_words(new))
    added = Counter(_words(new)) - Counter(_words(old))
    name_like = all(
        (w[:1].isupper() and (w[1:].islower() or not w[1:]))
        or w.lower() in {"ruling", "rulings", "l", "inc"}
        or w.isdigit()
        for w in removed
    )
    return name_like and all(w.lower() in ROLE_WORDS for w in added)


def _fstring_text(node: ast.JoinedStr) -> str:
    return "".join(str(v.value) if isinstance(v, ast.Constant) else " {} " for v in node.values)


def _is_pin_call(n: ast.AST) -> bool:
    return (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "desk_pin"
        and len(n.args) == 2
        and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in n.args)
    )


def compare(o: Any, n: Any, pins_seen: list[tuple[str, str]], where: str) -> None:
    if isinstance(n, ast.AST) and _is_pin_call(n):
        assert isinstance(o, ast.Constant) and isinstance(o.value, str) and HEX64.search(o.value), where
        assert isinstance(n, ast.Call)
        pins_seen.append((n.args[0].value, n.args[1].value))  # type: ignore[attr-defined]
        return
    if isinstance(o, list):
        assert isinstance(n, list) and len(o) == len(n), where
        for a, b in zip(o, n, strict=True):
            compare(a, b, pins_seen, where)
        return
    if not isinstance(o, ast.AST):
        assert o == n, (where, o, n)
        return
    assert type(o) is type(n), (where, type(o).__name__, type(n).__name__)
    if isinstance(o, ast.JoinedStr):
        assert isinstance(n, ast.JoinedStr)
        old_fv = [v for v in o.values if isinstance(v, ast.FormattedValue)]
        new_fv = [v for v in n.values if isinstance(v, ast.FormattedValue)]
        compare(old_fv, new_fv, pins_seen, f"{where}.fstring")
        old_text, new_text = _fstring_text(o), _fstring_text(n)
        assert old_text == new_text or prose_ok(old_text, new_text), (where, old_text, new_text)
        return
    if isinstance(o, ast.Constant) and isinstance(o.value, str):
        assert isinstance(n, ast.Constant)
        if o.value == n.value:
            return
        assert isinstance(n.value, str) and prose_ok(o.value, n.value), (where, o.value, n.value)
        return
    for field in o._fields:
        if field == "ctx":
            continue
        compare(getattr(o, field), getattr(n, field), pins_seen, f"{where}.{field}")


def _pin_tables() -> dict[str, dict[str, Any]]:
    with PINS_FILE.open("rb") as fh:
        return tomllib.load(fh)


@pytest.fixture(scope="module")
def have_ref() -> None:
    try:
        _git("cat-file", "-e", f"{REF}^{{commit}}")
    except (OSError, subprocess.SubprocessError):
        pytest.skip("pre-sweep commit not in git history")


@pytest.mark.parametrize("path", sorted(SWEPT))
def test_swept_module_is_equivalent(path: str, have_ref: None) -> None:
    if _git("hash-object", path).strip() != SWEPT[path]:
        pytest.skip(f"{path} changed after the sweep")
    old = _strip(ast.parse(_git("show", f"{REF}:{path}")), False)
    new = _strip(ast.parse((REPO_ROOT / path).read_text()), True)
    seen: list[tuple[str, str]] = []
    compare(old, new, seen, path)
    tables = _pin_tables()
    for ns, key in seen:
        assert tables[ns][key] == pins.PENDING, (ns, key)
    if path.startswith("src/"):
        assert len(set(seen)) == len(seen), "duplicate pin keys"
        ns = path.removeprefix("src/quant_research/").removesuffix(".py").replace("/", ".")
        assert {k for n, k in seen if n == ns} == set(tables.get(ns, {})), "pin table out of step with the module"


def test_public_pin_file_is_all_pending() -> None:
    for ns, table in _pin_tables().items():
        for key, value in table.items():
            assert value == pins.PENDING, (ns, key)


def test_desk_pin_reads_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "pins.toml"
    f.write_text('["strategies.example"]\n"A_SHA" = "' + "ab" * 32 + '"\n"N" = 3\n[strategies.nested]\nB = "x"\n')
    monkeypatch.setenv(pins.PINS_ENV, str(f))
    pins.reload()
    try:
        assert pins.desk_pin("strategies.example", "A_SHA") == "ab" * 32
        assert pins.desk_pin("strategies.nested", "B") == "x"
        assert pins.desk_pin("strategies.example", "MISSING") == pins.PENDING
        with pytest.raises(TypeError):
            pins.desk_pin("strategies.example", "N")
        monkeypatch.setenv(pins.PINS_ENV, str(tmp_path / "absent.toml"))
        pins.reload()
        assert pins.desk_pin("strategies.example", "A_SHA") == pins.PENDING
    finally:
        monkeypatch.delenv(pins.PINS_ENV, raising=False)
        pins.reload()
        assert os.environ.get(pins.PINS_ENV) is None
