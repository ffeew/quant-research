"""The desk-reference sweep changed no logic.

Each swept module is compared with its pre-sweep version (git ref recorded per file) as an AST, after
dropping docstrings and the added ``desk_pin`` import:

- a ``desk_pin(ns, key)`` call must sit exactly where the old module had a sha256 literal, so the
  code is the old code once the desk pin file holds the old values;
- any other changed string must be prose in which only person names and review references
  (line refs, ticket ids, review ids) were swapped for role words, with every number kept;
- an identifier (or identifier-like key string) may differ only through one repo-wide one-to-one
  renaming whose new names add nothing but role words and do not collide with any old name;
- everything else must be identical.

Each file is checked as the sweep left it (its recorded git blob), so later edits do not trip it.
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
    "validation",
    "costs",
    "cio",
    "research",
}
RENAME_WORDS = ROLE_WORDS | {"sha", "inputs"}
IDENT_FIELDS = {"id", "attr", "name", "arg", "asname", "names", "module"}
IDENT = re.compile(r"(-{0,2})([A-Za-z_][A-Za-z0-9_]*)")
REF_TOKENS = [
    re.compile(r"\bL\d+(?:[-–]L?\d+)?"),
    re.compile(r"\bINC-?\d+\w*"),
    re.compile(r"[Rr]uling\s+\d\w*(?:-\d+)?"),
]
# per swept file: its git blob right after the sweep and the ref it is compared with
# (kept as data so code greps over tests stay clean)
SWEPT: dict[str, dict[str, str]] = json.loads((Path(__file__).with_name("desk_ref_sweep_blobs.json")).read_text())


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
        (w[:1].isupper() and (w[1:].islower() or w[1:].isupper() or not w[1:]))
        or w.lower() in {"ruling", "rulings", "l", "inc"}
        or w.isdigit()
        for w in removed
    )
    return name_like and all(w.lower() in ROLE_WORDS for w in added)


class Renames:
    """Repo-wide one-to-one renaming inferred from the AST pairs, plus prose strings to check at the end."""

    def __init__(self) -> None:
        self.fwd: dict[str, str] = {}
        self.bwd: dict[str, str] = {}
        self.same: set[str] = set()
        self.prose: list[tuple[str, str, str]] = []
        self.errors: list[str] = []

    def add(self, old: str, new: str, where: str) -> None:
        if old == new:
            self.same.add(old)
        elif self.fwd.setdefault(old, new) != new or self.bwd.setdefault(new, old) != old:
            self.errors.append(f"{where}: inconsistent rename {old!r} -> {new!r}")

    def check_partial(self) -> list[str]:
        """A name renamed somewhere but kept elsewhere (or a new name that also occurs unrenamed)."""
        return sorted((self.same & set(self.fwd)) | (self.same & set(self.bwd)))

    def apply(self, s: str) -> str:
        for old, new in self.fwd.items():
            s = re.sub(r"(?<![A-Za-z0-9_])" + re.escape(old) + r"(?![A-Za-z0-9_])", new, s)
        return s


def _tokens(name: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", name)}


def _is_pin_call(n: ast.AST) -> bool:
    return (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "desk_pin"
        and len(n.args) == 2
        and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in n.args)
    )


def _fstring_text(node: ast.JoinedStr) -> str:
    return "".join(str(v.value) if isinstance(v, ast.Constant) else " {} " for v in node.values)


def compare(o: Any, n: Any, ctx: Renames, pins_seen: list[tuple[str, str]], where: str, field: str = "") -> None:
    if isinstance(n, ast.AST) and _is_pin_call(n):
        assert isinstance(o, ast.Constant) and isinstance(o.value, str) and HEX64.search(o.value), where
        assert isinstance(n, ast.Call)
        pins_seen.append((n.args[0].value, n.args[1].value))  # type: ignore[attr-defined]
        return
    if isinstance(o, list):
        assert isinstance(n, list) and len(o) == len(n), where
        for a, b in zip(o, n, strict=True):
            compare(a, b, ctx, pins_seen, where, field)
        return
    if not isinstance(o, ast.AST):
        if isinstance(o, str) and isinstance(n, str) and field in IDENT_FIELDS:
            ctx.add(o, n, where)
            return
        assert o == n, (where, o, n)
        return
    assert type(o) is type(n), (where, type(o).__name__, type(n).__name__)
    if isinstance(o, ast.ImportFrom):
        assert isinstance(n, ast.ImportFrom) and (o.module, o.level) == (n.module, n.level), where
        # import sorting may reorder renamed names: pair the unchanged ones, then the rest in order
        key = [(x.name, x.asname) for x in o.names]
        new_key = [(x.name, x.asname) for x in n.names]
        assert len(key) == len(new_key), where
        for pair_o, pair_n in zip(
            [k for k in key if k not in new_key], [k for k in new_key if k not in key], strict=True
        ):
            compare(list(pair_o), list(pair_n), ctx, pins_seen, f"{where}.names", "names")
        return
    if isinstance(o, ast.JoinedStr):
        assert isinstance(n, ast.JoinedStr)
        old_fv = [v for v in o.values if isinstance(v, ast.FormattedValue)]
        new_fv = [v for v in n.values if isinstance(v, ast.FormattedValue)]
        compare(old_fv, new_fv, ctx, pins_seen, f"{where}.fstring")
        old_text, new_text = _fstring_text(o), _fstring_text(n)
        if old_text != new_text:
            ctx.prose.append((old_text, new_text, where))
        return
    if isinstance(o, ast.Constant) and isinstance(o.value, str):
        assert isinstance(n, ast.Constant)
        assert isinstance(n.value, str), where
        mo, mn = IDENT.fullmatch(o.value), IDENT.fullmatch(n.value)
        if mo and mn and mo.group(1) == mn.group(1):
            ctx.add(mo.group(2), mn.group(2), where)
        elif o.value != n.value:
            ctx.prose.append((o.value, n.value, where))
        return
    for f in o._fields:
        if f == "ctx":
            continue
        compare(getattr(o, f), getattr(n, f), ctx, pins_seen, f"{where}.{f}", f)


def _old_names(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        for f in IDENT_FIELDS:
            v = getattr(node, f, None)
            if isinstance(v, str):
                out.add(v)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and IDENT.fullmatch(node.value):
            out.add(node.value.lstrip("-"))
    return out


def _pin_tables() -> dict[str, dict[str, Any]]:
    with PINS_FILE.open("rb") as fh:
        return tomllib.load(fh)


Result = tuple[str, list[tuple[str, str]], str]  # status, pins seen, message


@pytest.fixture(scope="module")
def sweep_check() -> tuple[dict[str, Result], Renames, set[str]]:
    """Compare every swept file once, so renames are checked across the whole repo."""
    ctx = Renames()
    results: dict[str, Result] = {}
    old_names: set[str] = set()
    for path, rec in sorted(SWEPT.items()):
        try:
            _git("cat-file", "-e", f"{rec['ref']}^{{commit}}")
        except (OSError, subprocess.SubprocessError):
            results[path] = ("skip", [], f"ref {rec['ref']} not in git history")
            continue
        # later edits are not part of the sweep: compare the file as the sweep left it
        try:
            swept_src = _git("cat-file", "blob", rec["blob"])
        except (OSError, subprocess.SubprocessError):
            results[path] = ("skip", [], f"swept blob of {path} not in git history")
            continue
        old = _strip(ast.parse(_git("show", f"{rec['ref']}:{path}")), False)
        old_names |= _old_names(old)
        new = _strip(ast.parse(swept_src), True)
        seen: list[tuple[str, str]] = []
        try:
            compare(old, new, ctx, seen, path)
        except AssertionError as e:
            results[path] = ("fail", seen, repr(e.args))
            continue
        results[path] = ("ok", seen, "")
    return results, ctx, old_names


@pytest.mark.parametrize("path", sorted(SWEPT))
def test_swept_module_is_equivalent(path: str, sweep_check: tuple[dict[str, Result], Renames, set[str]]) -> None:
    results, _, _ = sweep_check
    status, seen, msg = results[path]
    if status == "skip":
        pytest.skip(msg)
    assert status == "ok", msg
    tables = _pin_tables()
    for ns, key in seen:
        assert tables[ns][key] == pins.PENDING, (ns, key)
    if path.startswith("src/"):
        assert len(set(seen)) == len(seen), "duplicate pin keys"
        ns = path.removeprefix("src/quant_research/").removesuffix(".py").replace("/", ".")
        assert {k for n, k in seen if n == ns} == set(tables.get(ns, {})), "pin table out of step with the module"


def test_renames_are_one_to_one_role_renames(sweep_check: tuple[dict[str, Result], Renames, set[str]]) -> None:
    _, ctx, old_names = sweep_check
    assert not ctx.errors, ctx.errors
    assert not ctx.check_partial(), ctx.check_partial()
    for old, new in ctx.fwd.items():
        assert new not in old_names, f"{new} already existed before the sweep"
        assert _tokens(new) - _tokens(old) <= RENAME_WORDS, (old, new)
        assert _tokens(old) - _tokens(new), (old, new)


def test_changed_prose_only_swaps_names(sweep_check: tuple[dict[str, Result], Renames, set[str]]) -> None:
    _, ctx, _ = sweep_check
    for old, new, where in ctx.prose:
        renamed = ctx.apply(old)
        assert renamed == new or prose_ok(renamed, new), (where, old, new)


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
