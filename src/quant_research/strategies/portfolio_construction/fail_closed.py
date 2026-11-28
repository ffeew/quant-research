"""Fail-closed stops for portfolio construction: coded non-zero exits that list every reason.

Pure helpers, no I/O beyond one line on stderr per stop. A stop raises :class:`CodedStop`
(a ``SystemExit`` whose ``code`` is non-zero), so a caller that does not catch it exits non-zero
and writes nothing further.

Stop codes (distinct, never 0):

* ``EXIT_COMPLIANCE_FAIL`` (3): a compliance check has status ``FAIL`` (or any status other than
  ``PASS``/``INFO``, including ``WARN``), or the compliance block is missing, empty, or malformed,
  or a check's status is not a string (including unhashable values). No targets file is written;
  every failed check is listed. A FAIL in any document, including a shadow book, also blocks the
  tradable file.
* ``EXIT_SOLVE_FAILED`` (4): the optimiser did not return an optimal solution (infeasible,
  unbounded, inaccurate, solver error, or no/non-finite values). There is no fallback book.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn

__all__ = [
    "EXIT_COMPLIANCE_FAIL",
    "EXIT_SOLVE_FAILED",
    "CodedStop",
    "coded_stop",
    "failed_checks",
    "require_compliance_pass",
    "require_optimal",
    "solve_or_stop",
]

EXIT_COMPLIANCE_FAIL = 3
EXIT_SOLVE_FAILED = 4

_OK_STATUSES = frozenset({"PASS", "INFO"})


class CodedStop(SystemExit):
    """A deliberate stop: ``code`` is the non-zero exit code, ``reasons`` lists every reason."""

    def __init__(self, code: int, name: str, reasons: Sequence[str]) -> None:
        super().__init__(code)
        self.stop_name = name
        self.reasons: tuple[str, ...] = tuple(reasons)


def coded_stop(code: int, name: str, reasons: Sequence[str]) -> NoReturn:
    """Print one ``STOP`` line to stderr naming every reason, then raise :class:`CodedStop`."""
    print(f"STOP[{code}] {name}: " + "; ".join(reasons), file=sys.stderr)
    raise CodedStop(code, name, reasons)


def failed_checks(compliance: object) -> list[str]:
    """Every check that is not PASS/INFO, as ``"<limit> (value <v>, threshold <t>)"``.

    A missing, empty or malformed compliance block is itself a failure (fail closed).
    A status that is not a string (including unhashable values) is a failure, not a TypeError.
    """
    if not isinstance(compliance, (list, tuple)) or len(compliance) == 0:
        return ["compliance block missing or malformed"]
    bad: list[str] = []
    for c in compliance:
        row: Mapping[str, Any] = c if isinstance(c, Mapping) else {}
        status = row.get("status")
        # Membership is only tested for strings, so an unhashable status is a failure, not a TypeError.
        if not (isinstance(status, str) and status in _OK_STATUSES):
            bad.append(
                f"{row.get('limit', '?')} (status {status!r}, "
                f"value {row.get('value')!r}, threshold {row.get('threshold')!r})"
            )
    return bad


def _doc_label(path: str) -> str:
    """Parent directory plus basename, so shadow and tradable books (same filename) are distinct."""
    parts = str(path).replace("\\", "/").rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[0] if parts else str(path))


def require_compliance_pass(docs: Sequence[tuple[str, Mapping[str, Any]]]) -> None:
    """Stop (code 3) unless every doc's compliance checks all pass; lists every failed check of every doc.

    ``docs`` is ``[(target_path, doc), ...]``. Nothing is written by this function. A FAIL in any
    document, including a shadow (non-tradable) book, also blocks every other document: the tradable
    file is not written. The stop label for each path includes the parent directory, because both
    books are named ``targets_<stamp>.json``.
    """
    reasons: list[str] = []
    for path, doc in docs:
        reasons.extend(f"{_doc_label(path)}: {why}" for why in failed_checks(doc.get("compliance")))
    if reasons:
        coded_stop(EXIT_COMPLIANCE_FAIL, "COMPLIANCE_FAIL no targets written", reasons)


def require_optimal(status: object, values: object) -> None:
    """Stop (code 4) unless ``status`` is exactly ``"optimal"`` and ``values`` is a finite numeric array."""
    reasons: list[str] = []
    if status != "optimal":
        reasons.append(f"solver status {status!r} (only 'optimal' is accepted)")
    if values is None:
        reasons.append("no solution values")
    else:
        try:
            flat = [float(v) for v in _flatten(values)]
        except (TypeError, ValueError):
            reasons.append("solution values are not numeric")
        else:
            if not flat or not all(math.isfinite(v) for v in flat):
                reasons.append("solution values are empty or not finite")
    if reasons:
        coded_stop(EXIT_SOLVE_FAILED, "SOLVE_FAILED no targets written", reasons)


def _flatten(values: Any) -> list[Any]:
    arr = getattr(values, "ravel", None)
    return list(arr()) if callable(arr) else list(values) if isinstance(values, (list, tuple)) else [values]


def solve_or_stop(prob: Any, var: Any, *, solver: str = "CLARABEL") -> Any:
    """Solve ``prob``; stop (code 4) on a solver error or any non-optimal outcome. Returns ``var.value``."""
    try:
        prob.solve(solver=solver)
    except Exception as exc_solve:  # solver/DCP errors of any kind are a stop, never a fallback
        coded_stop(EXIT_SOLVE_FAILED, "SOLVE_FAILED no targets written", [f"solver error: {exc_solve!r}"])
    require_optimal(prob.status, var.value)
    return var.value
