"""Unit tests for scripts/check_repo_hygiene.py. Patterns are built at runtime."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_repo_hygiene.py"
    spec = importlib.util.spec_from_file_location("check_repo_hygiene", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_repo_hygiene"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def hygiene():
    return _load()


def _key() -> str:
    return "ALPHA" + "VANTAGE_API_KEY"


def _home() -> str:
    return "/" + "home" + "/"


def _workspace() -> str:
    return "/" + "workspace" + "/"


def _uuid() -> str:
    return "12345678" + "-1234-5678-9abc-" + "def012345678"


def test_allowlist_stays_small(hygiene) -> None:
    assert not hygiene.LARGE_FILE_ALLOWLIST
    assert not hygiene.DATA_FILE_ALLOWLIST
    assert not hygiene.DATA_DIR_ALLOWLIST
    assert not hygiene.ABSOLUTE_PATH_ALLOWLIST
    assert not hygiene.UUID_ALLOWLIST
    allowed = {"tests/strategies/iv_gap/test_runner.py": frozenset({"dummy-test-value"})}
    assert allowed == hygiene.KEY_VALUE_ALLOWLIST


def test_repository_tree_passes(hygiene) -> None:
    root = Path(__file__).resolve().parents[1]
    findings = hygiene.scan(root)
    assert findings == [], "\n".join(item.format() for item in findings)


def test_package_data_dir_is_not_the_store(hygiene, tmp_path: Path) -> None:
    rel = "src/quant_research/data/note.py"
    dest = tmp_path / rel
    dest.parent.mkdir(parents=True)
    dest.write_text("x = 1\n")
    assert hygiene.scan(tmp_path, [rel]) == []


def test_root_data_dir_fails(hygiene, tmp_path: Path) -> None:
    rel = "data/note.txt"
    dest = tmp_path / rel
    dest.parent.mkdir(parents=True)
    dest.write_text("x")
    findings = hygiene.scan(tmp_path, [rel])
    assert [item.message for item in findings] == ["path is under /data"]


def test_data_file_size_boundary(hygiene, tmp_path: Path) -> None:
    small = tmp_path / "small.csv"
    small.write_text("a,b\n")
    exact = tmp_path / "exact.csv"
    with exact.open("wb") as handle:
        handle.seek(hygiene.MAX_DATA_FILE_BYTES - 1)
        handle.write(b"x")
    over = tmp_path / "over.parquet"
    with over.open("wb") as handle:
        handle.seek(hygiene.MAX_DATA_FILE_BYTES)
        handle.write(b"x")
    assert hygiene.scan(tmp_path, ["small.csv", "exact.csv"]) == []
    findings = hygiene.scan(tmp_path, ["over.parquet"])
    assert len(findings) == 1
    assert "data-file limit" in findings[0].message


def test_pickle_and_feather_suffixes(hygiene, tmp_path: Path) -> None:
    for name in ("blob.pkl", "blob.pickle", "frame.feather"):
        path = tmp_path / name
        with path.open("wb") as handle:
            handle.seek(hygiene.MAX_DATA_FILE_BYTES)
            handle.write(b"x")
        findings = hygiene.scan(tmp_path, [name])
        assert len(findings) == 1
        assert "data-file limit" in findings[0].message


def test_one_mib_boundary(hygiene, tmp_path: Path) -> None:
    exact = tmp_path / "exact.bin"
    with exact.open("wb") as handle:
        handle.seek(hygiene.MAX_FILE_BYTES - 1)
        handle.write(b"x")
    over = tmp_path / "over.bin"
    with over.open("wb") as handle:
        handle.seek(hygiene.MAX_FILE_BYTES)
        handle.write(b"x")
    assert hygiene.scan(tmp_path, ["exact.bin"]) == []
    findings = hygiene.scan(tmp_path, ["over.bin"])
    assert len(findings) == 1
    assert "exceeds 1 MiB" in findings[0].message


def test_large_file_allowlist(hygiene, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "over.bin"
    with path.open("wb") as handle:
        handle.seek(hygiene.MAX_FILE_BYTES)
        handle.write(b"x")
    monkeypatch.setattr(hygiene, "LARGE_FILE_ALLOWLIST", frozenset({"over.bin"}))
    assert hygiene.scan(tmp_path, ["over.bin"]) == []


def test_absolute_prefixes_and_uuid(hygiene, tmp_path: Path) -> None:
    rel = "notes.md"
    (tmp_path / rel).write_text(f"see {_home()}alice and {_workspace()}proj\nuid {_uuid()}\n")
    messages = [item.message for item in hygiene.scan(tmp_path, [rel])]
    assert f"absolute path prefix {_home()}" in messages
    assert f"absolute path prefix {_workspace()}" in messages
    assert "UUID-like agent id" in messages


def test_key_assignment_rules(hygiene, tmp_path: Path) -> None:
    key = _key()
    rel = "pkg/fetch.py"
    dest = tmp_path / rel
    dest.parent.mkdir(parents=True)
    dest.write_text(
        "\n".join(
            [
                f'{key} = ""',
                f"{key}=",
                f'os.environ.get("{key}")',
                f'{key} = "real-looking-value"',
                f"{key}=ABCDEFGH12345678",
            ]
        )
        + "\n"
    )
    findings = hygiene.scan(tmp_path, [rel])
    assert len(findings) == 2
    assert {item.line for item in findings} == {4, 5}
    assert all(item.message == "ALPHAVANTAGE key assignment" for item in findings)


def test_synthetic_runner_value_is_allowlisted_only_in_that_file(hygiene, tmp_path: Path) -> None:
    key = _key()
    allowed = "tests/strategies/iv_gap/test_runner.py"
    other = "tests/other.py"
    body = f'os.environ["{key}"] = "dummy-test-value"\n'
    for rel in (allowed, other):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body)
    assert hygiene.scan(tmp_path, [allowed]) == []
    findings = hygiene.scan(tmp_path, [other])
    assert len(findings) == 1
    extra = tmp_path / allowed
    extra.write_text(body + f'os.environ["{key}"] = "another-value-here"\n')
    again = hygiene.scan(tmp_path, [allowed])
    assert len(again) == 1
    assert again[0].line == 2
