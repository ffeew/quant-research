#!/usr/bin/env python3
"""Fail if the git tree contains research data, bulky files, or leaked identifiers.

Rules, applied to tracked files and to untracked files that are not gitignored:

* Anything under the repository-root data directory.
* Parquet, CSV, Feather, and pickle files over 64 KiB.
* Any file over 1 MiB (1,048,576 bytes).
* Text that contains an absolute home-directory or workspace-root prefix
  (the prefixes are assembled in ``_absolute_prefixes``).
* UUID-shaped agent ids (8-4-4-4-12 hex).
* An Alpha Vantage API key assignment (a non-empty literal). Reads from the
  environment are allowed. One synthetic test value is allowlisted below.

The allowlists are intentionally empty except for that one test value.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DATA_DIR_NAME = "data"
MAX_FILE_BYTES = 1024 * 1024
MAX_DATA_FILE_BYTES = 64 * 1024
DATA_SUFFIXES: frozenset[str] = frozenset({".parquet", ".csv", ".feather", ".pkl", ".pickle"})

# Explicit exceptions. Keep these empty unless a checked-in file must be exempt,
# and put the reason on the line that adds the path.
LARGE_FILE_ALLOWLIST: frozenset[str] = frozenset()
DATA_FILE_ALLOWLIST: frozenset[str] = frozenset()
DATA_DIR_ALLOWLIST: frozenset[str] = frozenset()
ABSOLUTE_PATH_ALLOWLIST: frozenset[str] = frozenset()
UUID_ALLOWLIST: frozenset[str] = frozenset()
# Synthetic value the iv_gap runner test assigns to prove the runner stops. Not a credential.
KEY_VALUE_ALLOWLIST: dict[str, frozenset[str]] = {
    "tests/strategies/iv_gap/test_runner.py": frozenset({"dummy-test-value"}),
}

UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def _api_key_name() -> str:
    return "ALPHA" + "VANTAGE_API_KEY"


def _absolute_prefixes() -> tuple[str, ...]:
    return ("/" + "home" + "/", "/" + "workspace" + "/")


def _assignment_patterns() -> tuple[re.Pattern[str], re.Pattern[str]]:
    key = re.escape(_api_key_name())
    # [ \t] rather than \s so an empty KEY= cannot swallow the next line.
    quoted = re.compile(rf"{key}['\"]?\]?[ \t]*=[ \t]*['\"]([^'\"]+)['\"]")
    unquoted = re.compile(rf"(?m)^[ \t#]*(?:export[ \t]+)?{key}[ \t]*=[ \t]*([^'\"\s#][^\s#]*)")
    return quoted, unquoted


@dataclass(frozen=True)
class Finding:
    path: str
    message: str
    line: int | None = None

    def format(self) -> str:
        if self.line is None:
            return f"{self.path}: {self.message}"
        return f"{self.path}:{self.line}: {self.message}"


def list_git_files(root: Path) -> list[str]:
    try:
        raw = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else str(exc.stderr)
        raise SystemExit(f"git ls-files failed: {detail}") from exc
    found: list[str] = []
    for item in raw.split(b"\0"):
        if item:
            found.append(item.decode("utf-8", "surrogateescape"))
    return found


def _normalize(rel: str) -> str:
    path = PurePosixPath(rel.replace("\\", "/"))
    if path.is_absolute():
        raise SystemExit(f"refusing to scan absolute path {rel}")
    parts = [part for part in path.parts if part not in ("", ".")]
    return PurePosixPath(*parts).as_posix() if parts else ""


def _under_data_dir(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return bool(parts) and parts[0] == DATA_DIR_NAME


def _data_suffix(rel: str) -> str | None:
    name = PurePosixPath(rel).name.lower()
    for suffix in sorted(DATA_SUFFIXES, key=len, reverse=True):
        if name.endswith(suffix):
            return suffix
    return None


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _size(path: Path) -> int | None:
    try:
        return path.lstat().st_size
    except OSError:
        return None


def _read_text(path: Path) -> str | None:
    if path.is_symlink():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


def _scan_text(rel: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    if rel not in ABSOLUTE_PATH_ALLOWLIST:
        for prefix in _absolute_prefixes():
            start = 0
            while True:
                index = text.find(prefix, start)
                if index < 0:
                    break
                findings.append(Finding(rel, f"absolute path prefix {prefix}", _line_of(text, index)))
                start = index + len(prefix)
    if rel not in UUID_ALLOWLIST:
        for match in UUID_RE.finditer(text):
            findings.append(Finding(rel, "UUID-like agent id", _line_of(text, match.start())))
    allowed = KEY_VALUE_ALLOWLIST.get(rel, frozenset())
    for pattern in _assignment_patterns():
        for match in pattern.finditer(text):
            value = match.group(1)
            if value in allowed:
                continue
            findings.append(Finding(rel, "ALPHAVANTAGE key assignment", _line_of(text, match.start())))
    return findings


def _scan_one(root: Path, rel: str) -> list[Finding]:
    findings: list[Finding] = []
    if not rel:
        return findings
    if _under_data_dir(rel) and rel not in DATA_DIR_ALLOWLIST:
        findings.append(Finding(rel, "path is under /data"))
    path = root / rel
    size = _size(path)
    if size is None:
        findings.append(Finding(rel, "listed in the tree but missing on disk"))
        return findings
    if size > MAX_FILE_BYTES and rel not in LARGE_FILE_ALLOWLIST:
        findings.append(Finding(rel, f"{size} bytes exceeds 1 MiB"))
    suffix = _data_suffix(rel)
    if suffix is not None and size > MAX_DATA_FILE_BYTES and rel not in DATA_FILE_ALLOWLIST:
        findings.append(
            Finding(rel, f"{suffix} file is {size} bytes, over the {MAX_DATA_FILE_BYTES}-byte data-file limit")
        )
    if path.is_symlink():
        findings.extend(_scan_text(rel, os.readlink(path)))
        return findings
    text = _read_text(path)
    if text is not None:
        findings.extend(_scan_text(rel, text))
    return findings


def _dedupe(findings: Iterable[Finding]) -> list[Finding]:
    unique: dict[tuple[str, int | None, str], Finding] = {}
    for finding in findings:
        unique[finding.path, finding.line, finding.message] = finding
    return sorted(unique.values(), key=lambda item: (item.path, -1 if item.line is None else item.line, item.message))


def scan(root: Path, rel_paths: Sequence[str] | None = None) -> list[Finding]:
    """Scan ``root``. ``rel_paths`` overrides git ls-files (used by tests)."""
    root = root.resolve()
    selected = list_git_files(root) if rel_paths is None else list(rel_paths)
    findings: list[Finding] = []
    for rel in selected:
        findings.extend(_scan_one(root, _normalize(rel)))
    return _dedupe(findings)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print(f"unexpected arguments: {' '.join(args)}", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    findings = scan(root)
    if findings:
        for finding in findings:
            print(finding.format())
        print(f"{len(findings)} hygiene finding(s)", file=sys.stderr)
        return 1
    print("repo hygiene ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
