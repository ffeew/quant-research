"""Fail-closed checks: sha256 pins, SUMS lines, acceptance hash, identity list, leakage guards."""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pandas as pd

PENDING = "PENDING"
RC_BLOCKED = 1
RC_FINAL_LIST_MISMATCH = 18

FINAL_LIST_HEADER = b"symbol\tdecision\treasons\tissuer_name\n"
FINAL_LIST_COLUMNS = ("symbol", "decision", "reasons", "issuer_name")
FINAL_LIST_DECISIONS = {"KEPT": "kept", "EXCLUDED": "excluded"}


class Blocked(SystemExit):
    """Fail-closed refusal. Subclass of SystemExit (rc 1): nothing runs after it."""

    def __init__(self, msg: str, code: int = RC_BLOCKED):
        super().__init__(code)
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


class FinalListMismatch(Blocked):
    """Identity list absent, sha != pin, or any header/row violation (rc 18)."""

    def __init__(self, msg: str):
        super().__init__(msg, RC_FINAL_LIST_MISMATCH)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_pending(v: object) -> bool:
    return v is None or (isinstance(v, str) and (not v.strip() or v.strip() == PENDING))


def verify_pinned_file(name: str, path: str | Path | None, sha: str | None) -> Path:
    """Refuse unless path and sha are set, the file exists, and its raw bytes hash to the pin."""
    if is_pending(path) or is_pending(sha):
        raise Blocked(f"REFUSING: input {name!r} path/sha PENDING.")
    p = Path(str(path))
    try:
        ok = p.is_file() and sha256_file(p) == str(sha).strip().lower()
    except OSError:
        ok = False
    if not ok:
        raise Blocked(f"REFUSING: input {name!r} absent or sha256 != pin.")
    return p


def read_pinned_bytes(name: str, path: str | Path | None, sha: str | None) -> bytes:
    """Read once and hash the bytes actually read (the bytes read are the bytes hashed)."""
    if is_pending(path) or is_pending(sha):
        raise Blocked(f"REFUSING: input {name!r} path/sha PENDING.")
    try:
        raw = Path(str(path)).read_bytes()
    except OSError:
        raise Blocked(f"REFUSING: input {name!r} absent or unreadable.") from None
    if sha256_bytes(raw) != str(sha).strip().lower():
        raise Blocked(f"REFUSING: input {name!r} sha256 != pin.")
    return raw


def verify_sums_line(sums_path: str | Path, sums_sha: str, target_path: str | Path, target_sha: str) -> None:
    """The target's line in a pinned SHA256SUMS must be exactly '<sha>  <path>'. Text only."""
    raw = read_pinned_bytes("sums", sums_path, sums_sha)
    mine = [ln for ln in raw.decode("utf-8").splitlines() if ln.endswith("  " + str(target_path))]
    if mine != [f"{target_sha}  {target_path}"]:
        raise Blocked("REFUSING: target line in its pinned SHA256SUMS != pinned sha + path.")


def verify_sums_dir(d: str | Path, sums_sha: str, sums_name: str = "SHA256SUMS") -> dict[str, str]:
    """sha256(d/SHA256SUMS) must equal the pin, then every listed file must match its entry."""
    raw = read_pinned_bytes("sums_dir", Path(d) / sums_name, sums_sha)
    listed: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        h, name = line.split("  ", 1)
        if "/" in name or name.startswith("."):
            raise Blocked(f"REFUSING: SUMS entry {name!r} is not a plain file name.")
        if sha256_file(Path(d) / name) != h:
            raise Blocked(f"REFUSING: {name} sha != its SHA256SUMS entry.")
        listed[name] = h
    return listed


def require_acceptance_hash(provided: str | None, prereg_path: str | Path | None, prereg_pin: str | None,
                            stage: str) -> str:
    """Any return-computing stage needs --acceptance-hash == sha256(prereg) == configured pin."""
    if not provided:
        raise Blocked(f"REFUSING --stage {stage}: pass --acceptance-hash <sha256 of the pre-registration>.")
    if is_pending(prereg_path) or is_pending(prereg_pin):
        raise Blocked("REFUSING: pre-registration path/sha PENDING.")
    actual = sha256_file(str(prereg_path))
    want = provided.strip().lower()
    if want != actual or want != str(prereg_pin).strip().lower():
        raise Blocked(f"REFUSING --stage {stage}: --acceptance-hash != sha256(pre-registration) / pin.")
    return actual


def require_pins(pins: dict[str, object]) -> None:
    pending = sorted(k for k, v in pins.items() if is_pending(v))
    if pending:
        raise Blocked(f"REFUSING: pins PENDING: {pending}")


def parse_final_list(raw: bytes) -> dict[str, object]:
    """Identity list (TSV). Header bytes exact; 4 fields per row; KEPT/EXCLUDED only;
    EXCLUDED needs a reason; no duplicate symbol. Any violation -> FinalListMismatch (rc 18)."""
    if not raw.startswith(FINAL_LIST_HEADER):
        raise FinalListMismatch(f"REFUSING: identity list header bytes != {FINAL_LIST_HEADER!r}.")
    try:
        body = raw[len(FINAL_LIST_HEADER):].decode("utf-8")
    except UnicodeDecodeError:
        raise FinalListMismatch("REFUSING: identity list body is not UTF-8.") from None
    rows = [line.split("\t") for line in body.split("\n") if line.strip()]
    excluded: dict[str, str] = {}
    kept: set[str] = set()
    for r in rows:
        role = FINAL_LIST_DECISIONS.get(r[1]) if len(r) == len(FINAL_LIST_COLUMNS) else None
        if role is None or r[0] in excluded or r[0] in kept or (role == "excluded" and not r[2].strip()):
            raise FinalListMismatch(f"REFUSING: malformed identity list row {r!r}.")
        if role == "excluded":
            excluded[r[0]] = r[2]
        else:
            kept.add(r[0])
    return {"sha256": sha256_bytes(raw), "excluded": excluded, "kept": kept}


def load_final_list(path: str | Path | None, sha: str | None) -> dict[str, object]:
    """PENDING -> Blocked (rc 1); absent / sha mismatch / malformed -> FinalListMismatch (rc 18)."""
    if is_pending(path) or is_pending(sha):
        raise Blocked("REFUSING: identity list path/sha PENDING.")
    try:
        raw = Path(str(path)).read_bytes()
    except OSError:
        raw = None
    if raw is None or sha256_bytes(raw) != str(sha).strip().lower():
        raise FinalListMismatch("REFUSING: identity list absent or sha != pin.")
    return parse_final_list(raw)


def assert_no_rows_after(index: pd.Index | pd.Series, end: date, what: str) -> None:
    """Leakage guard: no session past the read-time end may survive."""
    if (pd.to_datetime(pd.Series(index)) > pd.Timestamp(end)).any():
        raise RuntimeError(f"holdout/leakage guard: {what} has rows past {end}")
