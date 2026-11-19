from __future__ import annotations

import bisect
import builtins
import calendar
import datetime as dt
import hashlib
import io
import json
import math
import os
import platform
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, BinaryIO, Literal, TextIO, cast, overload

from quant_research.utils.pins import desk_pin

if TYPE_CHECKING:
    import numpy.typing as npt

# h2c_dev_run.py - H2-C DEV runner (confirmatory DEV leg), FROZEN CODE, per sealed PREREG r3 + Erratum 01
# + Erratum 02 (seal note). Method adapted from h2_dev.py (helpers copied, not imported).
# DEV ONLY. Never opens HOLDOUT / TRANSCRIPTS_HOLDOUT / TRANSCRIPTS_EXCLUDED / ROUTE_TABLE / clean/. No network, no env vars.
# Real run: --pull_root <dir> only (LOCK command, PREREG r3 §12; required, no default). Test run: --synthetic <cfg.json>, all paths must sit under SYNTH_ROOT.
# Exit codes: 0 ok | 2 sha mismatch | 3 mapping cross-check | 4 schema | 5 LOCK slots unfilled | 6 allowlist/forbidden path
#             7 purge mismatch | 8 partition (row outside DEV) | 9 interpreter/flags/version/import | 10 argv/config | 11 calendar
#             12 uncaught exception BEFORE any output (coded STOP, FD-6) | 13 any STOP/exception AFTER RUN_DIR/STATS exist (FD-6, final)
# FREEZE r2 (FD-1..FD-8, FI-4/FI-7 AMEND per validator): real input shapes from schema walks.
import sys

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

try:  # FD-6: import failure is a coded STOP 9
    import exchange_calendars as xc
    import numpy as np
    from scipy import stats
except BaseException as _e:
    sys.stdout.write(f"STOP code=9: IMPORT {type(_e).__name__}\n")
    sys.exit(9)

# ============================ CONSTANTS BLOCK (all paths + shas; LOCK edits only this block) ============================
FREEZE_DIR = f"{_QR.DESK_DIR}/research/original/h2c_freeze_r2_20261114"
SYNTH_ROOT = FREEZE_DIR + "/synthetic_test/"
# FD-4: the AV pull copy (no scratch path). Its root is a required real-run argument (--pull_root), no default.
PULL_ROOT_PLACEHOLDER = "<--pull_root>"
PULL_REL = {"COPY_SUMS": "/COPY_SUMS", "PRICES_DEV": "/DEV/PRICES_DEV.json", "EARNINGS_DEV": "/DEV/EARNINGS_DEV.json"}
PINS = {
    "COPY_SUMS": (
        PULL_ROOT_PLACEHOLDER + PULL_REL["COPY_SUMS"],
        desk_pin("strategies.sentiment_returns.h2c_dev_run", "PINS.COPY_SUMS[1]"),
    ),  # FD-4
    "PRICES_DEV": (
        PULL_ROOT_PLACEHOLDER + PULL_REL["PRICES_DEV"],
        desk_pin("strategies.sentiment_returns.h2c_dev_run", "PINS.PRICES_DEV[1]"),
    ),
    "EARNINGS_DEV": (
        PULL_ROOT_PLACEHOLDER + PULL_REL["EARNINGS_DEV"],
        desk_pin("strategies.sentiment_returns.h2c_dev_run", "PINS.EARNINGS_DEV[1]"),
    ),
    "PURGE": (
        f"{_QR.DESK_DIR}/validation/dmitri/h2c_av_pull_20261114_r1_inc70/PURGE.tsv",
        desk_pin("strategies.sentiment_returns.h2c_dev_run", "PINS.PURGE[1]"),
    ),
    "TX_DEV_SUMS": (
        f"{_QR.DESK_DIR}/validation/dmitri/h2c_tx_route_20261114_r1_inc70/TRANSCRIPTS_DEV/SHA256SUMS",
        desk_pin("strategies.sentiment_returns.h2c_dev_run", "PINS.TX_DEV_SUMS[1]"),
    ),
    "FYE_MONTH_FROZEN": (
        f"{_QR.DESK_DIR}/research/original/sentiment_returns_fiscal_diag_s6b_20261111/FYE_MONTH_FROZEN.tsv",
        desk_pin("strategies.sentiment_returns.h2c_dev_run", "PINS.FYE_MONTH_FROZEN[1]"),
    ),  # path+sha as pinned in h2_dev.py/L32
    # ---- LOCK SLOTS (COST decision): filled at LOCK only ----
    "COST_EARNINGS_CLEAN": (
        f"{_QR.DESK_DIR}/validation/dmitri/h2c_cost_clean_20261114_r4_inc70/COST_EARNINGS_DEV_CLEAN.json",
        desk_pin("strategies.sentiment_returns.h2c_dev_run", "PINS.COST_EARNINGS_CLEAN[1]"),
    ),  # The data owner's DEV-only H4 clean output for COST (after validator readback)
    "COST_TX_SUMS": (
        f"{_QR.DESK_DIR}/validation/dmitri/h2c_cost_delta_route_20261114_r2_inc70/TRANSCRIPTS_DEV/SHA256SUMS",
        desk_pin("strategies.sentiment_returns.h2c_dev_run", "PINS.COST_TX_SUMS[1]"),
    ),  # SHA256SUMS of COST's TRANSCRIPTS_DEV delta-route partition
}
COPY_SUMS_REL = {
    "PRICES_DEV": "DEV/PRICES_DEV.json",
    "EARNINGS_DEV": "DEV/EARNINGS_DEV.json",
}  # FD-4: relative lines of COPY_SUMS
TX_DEV_ROOT = f"{_QR.DESK_DIR}/validation/dmitri/h2c_tx_route_20261114_r1_inc70/TRANSCRIPTS_DEV"
COST_TX_ROOT = f"{_QR.DESK_DIR}/validation/dmitri/h2c_cost_delta_route_20261114_r2_inc70/TRANSCRIPTS_DEV"  # LOCK SLOT: COST delta-route TRANSCRIPTS_DEV root
COST_EXCLUDED_BY_ERRATUM = False  # set True ONLY by a sealed erratum excluding COST (before any DEV result)
COST_ERRATUM_PIN = (None, None)  # required (path, sha) when COST_EXCLUDED_BY_ERRATUM is True
RUN_DIR = f"{_QR.DESK_DIR}/research/original/h2c_dev_run_20261114_r2"  # LOCK SLOT: new run dir (must not exist; created with 'x' semantics)
EXPECTED_ROWS = {"PRICES_DEV": 89913, "EARNINGS_DEV": 1397, "TX_DEV": 1361, "TX_DEV_SYMBOLS": 49}
EXPECTED_PURGE_2020 = {
    "in_window_rows": 13,
    "purged": 6,
    "kept": 7,
    "excl_no_reporttime": 0,
}  # FI-8; FD-3 column names
PURGE_WINDOW_START, PURGE_WINDOW_END = "2020-11-01", "2020-12-31"  # FI-7 AMEND: mirrors route.py (BRIEF_H2C_d4 c16)
EXPECTED_PURGE_HEADER = ["boundary", "in_window_rows", "purged", "kept", "excl_no_reporttime"]  # FD-3 (walk 1)
PURGE_BOUNDARY_DEV = "2020"
PURGE_DATA_ROWS = 2  # FD-3: 2 data rows; DEV checks 2020 only
EXPECTED_PRICE_KEYS = {
    "1. open",
    "2. high",
    "3. low",
    "4. close",
    "5. adjusted close",
    "6. volume",
    "7. dividend amount",
    "8. split coefficient",
}  # FD-2/FI-4: walk 2 key set
PRICE_ADJ_KEY = "5. adjusted close"  # FD-2: route.py PF / walk 2
EXPECTED_EARN_KEYS = {
    "fiscalDateEnding",
    "reportedDate",
    "reportedEPS",
    "estimatedEPS",
    "surprise",
    "surprisePercentage",
    "reportTime",
}  # FD-1/FI-4: 7 keys, NO 'symbol' (walk 1)
EXPECTED_TX_KEYS = {"symbol", "quarter", "transcript"}  # h2_dev.py; FI-4 (walk 1)
EXPECTED_TX_ENTRY_KEYS = {"content", "sentiment", "speaker", "title"}  # FI-4 (walk 1); only `sentiment` read
FYE_REQUIRED_COLS = {"symbol", "fye_month", "status"}  # h2_dev.py
VERSIONS = {"python": "3.13.5", "numpy": "2.5.4", "scipy": "1.18.1", "exchange_calendars": "4.13.2"}
VENV_PY = f"{_QR.DATA_DIR}/.venv/bin/python"  # LOCK runtime (unchanged)
ACCEPT_PY = f"{_QR.SCRATCH_DIR}/scratch/v_fd8_stage_20261114/venv/bin/python"  # FD-8 (validator note L12): accept interpreter, SYNTHETIC only
ACCEPT_IN_ROOT = f"{_QR.SCRATCH_DIR}/scratch/v_fd8_stage_20261114/in/"  # FD-8 (note L11, L22): the validator's stage in/ copies, SYNTHETIC only
# =====================================================================================================================
UNIVERSE = sorted(
    [
        "AAPL",
        "ABBV",
        "ADBE",
        "AMD",
        "AMZN",
        "AVGO",
        "BA",
        "BAC",
        "C",
        "CAT",
        "CMCSA",
        "COST",
        "CRM",
        "CSCO",
        "CVX",
        "DIS",
        "GE",
        "GOOGL",
        "GS",
        "HD",
        "HON",
        "INTC",
        "JNJ",
        "JPM",
        "KO",
        "LLY",
        "MA",
        "MCD",
        "META",
        "MRK",
        "MS",
        "MSFT",
        "NFLX",
        "NKE",
        "NVDA",
        "ORCL",
        "PEP",
        "PFE",
        "PG",
        "QCOM",
        "SBUX",
        "T",
        "TSLA",
        "TXN",
        "UNH",
        "V",
        "VZ",
        "WFC",
        "WMT",
        "XOM",
    ]
)  # r3 §2
HEDGE = "SPY"
DEV_LO, DEV_HI = "2014-01-01", "2020-12-31"  # r3 §3.1 EARNINGS_DEV reportedDate window
PX_LO, PX_HI = "2014-01-02", "2020-12-31"  # r3 §3.1 PRICES_DEV sessions
SCORE_LO = "2015-01-01"  # r3 §3.1: 2014 warm-up, scored 2015..2020
SCORED_QUARTERS = [f"{y}Q{q}" for y in range(2015, 2021) for q in range(1, 5)]  # 24
G0_MIN_Q, Q_MIN_EVENTS = 22, 20  # r3 §9 G0, §8
BETA_N, H0, H1 = 252, 1, 21  # r3 §7
LAG = 100
NPRIOR_MAX, NPRIOR_MIN, TONE_MIN = 4, 2, 10
COST_SIDE, COST_SIDE_SENS, BORROW = 0.0010, 0.0020, 0.10
FORBIDDEN_TOKENS = (
    "HOLDOUT",
    "TRANSCRIPTS_EXCLUDED",
    "ROUTE_TABLE",
    "kaggle_staging",
    "verdicts-log",
    "av_sentiment_20261110/clean",
    "/proc",
    ".secrets",
)
DISCLOSURES = (
    "PREREG r3 §10 items 1-18 apply: tone not point-in-time (UPPER BOUND, forward shadow check needed); "
    "survivorship upward; event date is a reportedDate+reportTime PROXY; 2014 warm-up, 24 DEV quarters; "
    "missing reportTime excluded per partition, no rescue; COST via LOCK slots / delta route."
)


class Stop(Exception):
    code: int

    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code


LOGBUF: list[str] = []


def log(*a: object) -> None:
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOGBUF.append(s)


# ------------------------------ allowlist guard (r3 §12; brief) ------------------------------
_real_open = builtins.open
ALLOW_FILES: set[str] = set()
ALLOW_WRITE_DIR: list[str | None] = [None]
SYS_PREFIXES = tuple({os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix)})


def _check_path(p: str | os.PathLike[str] | int, mode: str) -> None:
    if isinstance(p, int):
        return
    rp = os.path.realpath(os.fspath(p))
    for t in FORBIDDEN_TOKENS:
        if t in os.fspath(p) or t in rp:
            raise Stop(6, f"FORBIDDEN path token {t!r}: {p}")
    w = any(c in mode for c in "wax+")
    if w:
        d = ALLOW_WRITE_DIR[0]
        if d is None or not rp.startswith(d + os.sep):
            raise Stop(6, f"write outside run dir refused: {p}")
        return
    if rp in ALLOW_FILES:
        return
    if ALLOW_WRITE_DIR[0] and rp.startswith(ALLOW_WRITE_DIR[0] + os.sep):
        return  # own run dir (SUMS of outputs)
    if rp.startswith(SYS_PREFIXES):
        return  # interpreter / library resources only
    raise Stop(6, f"ALLOWLIST: refused to open {p}")


@overload
def guarded_open(file: str | os.PathLike[str] | int, mode: Literal["r", "x"] = "r", *a: Any, **k: Any) -> TextIO: ...


@overload
def guarded_open(file: str | os.PathLike[str] | int, mode: Literal["rb"], *a: Any, **k: Any) -> BinaryIO: ...


def guarded_open(file: str | os.PathLike[str] | int, mode: str = "r", *a: Any, **k: Any) -> TextIO | BinaryIO:
    _check_path(file, mode)
    return cast(TextIO | BinaryIO, _real_open(file, mode, *a, **k))


def install_guard() -> None:
    builtins.open = guarded_open  # type: ignore[assignment]  # allowlist wrapper replaces builtin open
    io.open = guarded_open  # type: ignore[assignment]  # allowlist wrapper replaces io.open


def allow(p: str) -> None:
    ALLOW_FILES.add(os.path.realpath(p))


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_pinned(path: str, want: str) -> bytes:
    """sha verified on the raw bytes BEFORE any parse; mismatch = STOP 2."""
    allow(path)
    with guarded_open(path, "rb") as fh:
        b = fh.read()
    got = sha_bytes(b)
    log("input", path, got)
    if got != want:
        raise Stop(2, f"SHA MISMATCH {path}: got {got} want {want}")
    return b


def parse_sums(b: bytes) -> dict[str, str]:
    d: dict[str, str] = {}
    for line in b.decode("utf-8").splitlines():
        if not line.strip():
            continue
        h, q = line.split(None, 1)
        q = q.lstrip("*")
        if q.startswith("./"):
            q = q[2:]
        if q.startswith("/") or ".." in q.split("/") or q == "":
            raise Stop(6, f"SUMS path not relative / escapes root: {q!r}")  # FD-4
        if len(h) != 64 or q in d:
            raise Stop(4, f"SUMS format: {line!r}")
        d[q] = h
    return d


# ------------------------------ fiscal mapping (h2_dev.py, EDGE adapted to DEV) ------------------------------
def me(y: int, m: int) -> dt.date:
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def qend(Y: int, m: int, n: int) -> dt.date:
    k = m - 3 * (4 - n)
    return me(Y if k > 0 else Y - 1, (k - 1) % 12 + 1)


D_LO, D_HI = dt.date(2014, 1, 1), dt.date(2020, 12, 31)


def fy_map(rows: list[dict[str, Any]], m: int, Y: int) -> tuple[dict[int, dict[str, Any] | None], str]:
    """rows: list of dicts (f, r, ...) for one symbol. Returns ({n: row or None}, why).
    Interior year (every quarter end >= 2014-01-01 and due by 2020-12-31): exactly 4 rows, Q4 within 7d of FY end (v5 §2).
    Edge year (FREEZE ITEM FI-9): per-quarter bins as h2_dev.py open-year branch; unique row per bin."""
    a0, a1 = me(Y - 1, m), me(Y, m)
    b = [a0 + dt.timedelta(7)] + [qend(Y, m, n) + dt.timedelta(7) for n in (1, 2, 3)] + [a1 + dt.timedelta(7)]
    q = sorted([x for x in rows if b[0] < x["f"] <= b[4]], key=lambda x: x["f"])
    interior = all(qend(Y, m, n) >= D_LO and qend(Y, m, n) + dt.timedelta(LAG) <= D_HI for n in range(1, 5))
    if interior:
        if len(q) != 4:
            return dict.fromkeys(range(1, 5)), f"closed_rows_{len(q)}"
        if abs((q[-1]["f"] - a1).days) > 7:
            return dict.fromkeys(range(1, 5)), "q4_not_within_7d_of_annual"
        if len({x["f"] for x in q}) != 4:
            return dict.fromkeys(range(1, 5)), "closed_rows_not_unique"
    out: dict[int, dict[str, Any] | None] = {}
    why: list[str] = []
    for n in range(1, 5):
        qn = [x for x in q if b[n - 1] < x["f"] <= b[n]]
        if len(qn) != 1:
            out[n] = None
            why.append(f"Q{n}_rows_{len(qn)}")
            continue
        if not (0 <= (qn[0]["r"] - qn[0]["f"]).days <= LAG):
            out[n] = None
            why.append(f"Q{n}_lag")
            continue
        out[n] = qn[0]
    return out, ";".join(why)


# ------------------------------ stats helpers (h2_dev.py,) ------------------------------
def nw_t(x: npt.ArrayLike, L: int) -> float:
    x = np.asarray(x, float)
    T = len(x)
    m = x.mean()
    u = x - m
    lrv = (u @ u) / T
    for l in range(1, L + 1):
        w = 1 - l / (L + 1)
        lrv += 2 * w * (u[l:] @ u[:-l]) / T
    return cast(float, m / np.sqrt(lrv / T))


def tq(d: str) -> str:
    return f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"


def load_config(argv: list[str]) -> dict[str, Any]:
    """Returns (pins, settings). Real mode: constants only. Synthetic: every path must be under SYNTH_ROOT."""
    S: dict[str, Any] = dict(
        PINS=dict(PINS),
        TX_DEV_ROOT=TX_DEV_ROOT,
        COST_TX_ROOT=COST_TX_ROOT,
        COST_EXCLUDED_BY_ERRATUM=COST_EXCLUDED_BY_ERRATUM,
        COST_ERRATUM_PIN=COST_ERRATUM_PIN,
        RUN_DIR=RUN_DIR,
        EXPECTED_ROWS=dict(EXPECTED_ROWS),
        EXPECTED_PURGE_2020=dict(EXPECTED_PURGE_2020),
        COPY_SUMS_REL=dict(COPY_SUMS_REL),
        synthetic=False,
    )
    if len(argv) == 1:
        raise Stop(10, "missing required --pull_root <dir> (AV pull copy root; no default)")
    if len(argv) == 3 and argv[1] == "--pull_root":
        root = argv[2].rstrip("/")
        if not root:
            raise Stop(10, "missing required --pull_root <dir> (AV pull copy root; no default)")
        S["PINS"].update({k: (root + rel, S["PINS"][k][1]) for k, rel in PULL_REL.items()})
        return S
    if len(argv) != 3 or argv[1] != "--synthetic":
        raise Stop(10, f"bad argv {argv[1:]}")
    cp = os.path.realpath(argv[2])
    roots_ = (SYNTH_ROOT, ACCEPT_IN_ROOT)  # FD-8: stage in/ copies allowed
    if not cp.startswith(roots_):
        raise Stop(10, "synthetic config must be under SYNTH_ROOT")
    allow(cp)
    C = json.loads(guarded_open(cp, "r").read())
    for k, v in C.items():
        if k == "PINS":
            S["PINS"] = {kk: tuple(vv) for kk, vv in v.items()}
        else:
            S[k] = v
    S["synthetic"] = True
    paths = [p for p, _ in S["PINS"].values() if p] + [
        S["TX_DEV_ROOT"],
        S["COST_TX_ROOT"],
        S["RUN_DIR"],
        S["COST_ERRATUM_PIN"][0],
    ]
    for p in paths:
        if p and not any(os.path.realpath(p).startswith(r_.rstrip("/")) or p.startswith(r_) for r_ in roots_):
            raise Stop(10, f"synthetic path outside SYNTH_ROOT: {p}")
    return S


def main(argv: list[str]) -> int:
    S = load_config(argv)
    P = S["PINS"]
    log("H2-C DEV runner; synthetic" if S["synthetic"] else "H2-C DEV runner; REAL")
    log(DISCLOSURES)
    # ---- interpreter / flags / versions (r3 §12) ----
    vers = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": __import__("scipy").__version__,
        "exchange_calendars": xc.__version__,
    }
    log(
        "interpreter",
        sys.executable,
        "isolated",
        sys.flags.isolated,
        "dont_write_bytecode",
        sys.flags.dont_write_bytecode,
        vers,
    )
    # FD-8: real mode = LOCK runtime VENV_PY only; synthetic mode also accepts the validator's stage ACCEPT_PY (read-only bind of the
    # same venv; under the tmpfs mask VENV_PY does not exist, so it is matched by its literal path, never resolved via cio/data).
    py_ok = os.path.realpath(sys.executable) == os.path.realpath(VENV_PY) or (
        S["synthetic"] and os.path.abspath(sys.executable) == ACCEPT_PY
    )
    if not (sys.flags.isolated and sys.flags.dont_write_bytecode) or vers != VERSIONS or not py_ok:
        raise Stop(9, "interpreter/flags/version mismatch")
    # ---- LOCK slots BEFORE any data byte (COST decision) ----
    unfilled = []
    if S["RUN_DIR"] is None:
        unfilled.append("RUN_DIR")
    if S["COST_EXCLUDED_BY_ERRATUM"]:
        if None in S["COST_ERRATUM_PIN"]:
            unfilled.append("COST_ERRATUM_PIN")
    else:
        for k in ("COST_EARNINGS_CLEAN", "COST_TX_SUMS"):
            if None in P.get(k, (None, None)):
                unfilled.append(k)
        if S["COST_TX_ROOT"] is None:
            unfilled.append("COST_TX_ROOT")
    if unfilled:
        raise Stop(5, "LOCK slots unfilled: " + ",".join(unfilled))
    if os.path.exists(S["RUN_DIR"]):
        raise Stop(10, "RUN_DIR exists")
    # FD-8: never write next to the runner's own file or into the venv (read-only venv mount at the validator's real call)
    rdp = os.path.realpath(S["RUN_DIR"])
    own = os.path.dirname(os.path.realpath(__file__))
    bad_roots = [
        os.path.dirname(os.path.dirname(VENV_PY)),
        os.path.dirname(os.path.dirname(ACCEPT_PY)),
        *list(SYS_PREFIXES),
    ]
    if (
        any(rdp == b or rdp.startswith(b + os.sep) for b in bad_roots)
        or os.path.dirname(rdp) == own
        or (rdp.startswith(own + os.sep) and not (S["synthetic"] and rdp.startswith((SYNTH_ROOT, ACCEPT_IN_ROOT))))
    ):
        raise Stop(10, "RUN_DIR next to the runner or inside the venv/interpreter prefix (FD-8)")
    # ---- calendar (r3 §3.1 boundary sessions) ----
    cal = xc.get_calendar("XNYS")
    allsess = [d.strftime("%Y-%m-%d") for d in cal.sessions_in_range("2013-12-02", "2021-03-31")]
    chk = {
        "first2011": cal.date_to_session("2011-01-01", "next").strftime("%Y-%m-%d"),
        "last2013": cal.date_to_session("2013-12-31", "previous").strftime("%Y-%m-%d"),
        "first2014": cal.date_to_session("2014-01-01", "next").strftime("%Y-%m-%d"),
        "last2020": cal.date_to_session("2020-12-31", "previous").strftime("%Y-%m-%d"),
    }
    if chk != {
        "first2011": "2011-01-03",
        "last2013": "2013-12-31",
        "first2014": "2014-01-02",
        "last2020": "2020-12-31",
    }:
        raise Stop(11, f"calendar boundary mismatch {chk}")
    sess = [d for d in allsess if PX_LO <= d <= PX_HI]
    sidx = {d: i for i, d in enumerate(sess)}
    _aidx = {d: i for i, d in enumerate(allsess)}
    # ---- pinned reads: every sha verified before parse ----
    if S["COST_EXCLUDED_BY_ERRATUM"]:
        read_pinned(*S["COST_ERRATUM_PIN"])
    pull = parse_sums(read_pinned(*P["COPY_SUMS"]))  # FD-4: COPY_SUMS, relative lines
    for k, rel in S["COPY_SUMS_REL"].items():
        if pull.get(rel) != P[k][1]:
            raise Stop(2, f"{k} sha not equal to its COPY_SUMS line {rel}")
    fye_b = read_pinned(*P["FYE_MONTH_FROZEN"])
    purge_b = read_pinned(*P["PURGE"])
    px_b = read_pinned(*P["PRICES_DEV"])
    ea_b = read_pinned(*P["EARNINGS_DEV"])
    cost_b = None if S["COST_EXCLUDED_BY_ERRATUM"] else read_pinned(*P["COST_EARNINGS_CLEAN"])
    # transcript SUMS: equivalent of sha256sum -c --strict, restricted to listed files
    tx_index = {}  # (sym, label) -> (abs path, sha)
    roots = [(S["TX_DEV_ROOT"], P["TX_DEV_SUMS"], False)]
    if not S["COST_EXCLUDED_BY_ERRATUM"]:
        roots.append((S["COST_TX_ROOT"], P["COST_TX_SUMS"], True))
    for root, (sp, sh), is_cost in roots:
        sums = parse_sums(read_pinned(sp, sh))
        rroot = os.path.realpath(root)
        for rel, h in sums.items():
            parts = rel.split("/")
            ap = os.path.realpath(os.path.join(root, rel))
            if not ap.startswith(rroot + os.sep):
                raise Stop(6, f"SUMS entry escapes partition root: {rel}")
            if len(parts) != 2 or not parts[1].endswith(".json"):
                raise Stop(4, f"transcript name {rel}")
            sym, lab = parts[0], parts[1][:-5]
            if sym not in UNIVERSE or len(lab) != 6 or lab[4] != "Q" or lab[5] not in "1234" or not lab[:4].isdigit():
                raise Stop(4, f"transcript label {rel}")
            if (sym == "COST") != is_cost:
                raise Stop(8, f"COST file in wrong root (COST HELD from TRANSCRIPTS_DEV): {rel}")
            if (sym, lab) in tx_index:
                raise Stop(4, f"duplicate transcript {rel}")
            tx_index[(sym, lab)] = (ap, h)
    n_tx_dev = sum(1 for k in tx_index if k[0] != "COST")
    n_sym_dev = len({k[0] for k in tx_index if k[0] != "COST"})
    if n_tx_dev != S["EXPECTED_ROWS"]["TX_DEV"] or n_sym_dev != S["EXPECTED_ROWS"]["TX_DEV_SYMBOLS"]:
        raise Stop(4, f"TRANSCRIPTS_DEV count {n_tx_dev}/{n_sym_dev}")

    def sha_check_tx(key: tuple[str, str]) -> bytes:
        ap, h = tx_index[key]
        allow(ap)
        with guarded_open(ap, "rb") as fh:
            b = fh.read()
        if sha_bytes(b) != h:
            raise Stop(2, f"SHA MISMATCH transcript {key}")
        return b

    # strict -c: every listed file verified (bytes hashed only; parsed only if needed for tone, §3.3)
    for key in sorted(tx_index):
        sha_check_tx(key)
    log("transcript sums -c --strict OK", len(tx_index))
    # ---- schema (fail-closed: missing or extra keys = STOP 4) ----
    ISO = re.compile(r"\d{4}-\d\d-\d\d")

    def fnum(v: object, what: str) -> float:
        if not isinstance(v, str):
            raise Stop(4, f"{what}: value not str")
        try:
            return float(v)
        except ValueError:
            raise Stop(4, f"{what}: non-float string")

    def prices_of(b: bytes) -> list[dict[str, Any]]:
        """FD-2: dict symbol -> list of [date 'YYYY-MM-DD', {8 AV keys: str}] (BRIEF_H2C_d4 iterate 'Time Series (Daily)',
        d.append([k,dict(v)]), json.dumps(PD,sort_keys=True); key set from walk 2). Rows arrive DESCENDING -> sorted
        ascending here. Returns flat rows {symbol, date, adjusted_close} (only '5. adjusted close' is used)."""
        D_ = json.loads(b)
        if not isinstance(D_, dict) or set(D_) != set(UNIVERSE) | {HEDGE}:
            raise Stop(4, "PRICES_DEV: top level not dict of 50 names + SPY")
        out: list[dict[str, Any]] = []
        for s in sorted(D_):
            L_ = D_[s]
            if not isinstance(L_, list):
                raise Stop(4, f"PRICES_DEV {s}: value not a list")
            rows: list[dict[str, Any]] = []
            for x in L_:
                if not (isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and isinstance(x[1], dict)):
                    raise Stop(4, f"PRICES_DEV {s}: row not [str, dict]")
                if not ISO.fullmatch(x[0]):
                    raise Stop(4, f"PRICES_DEV {s}: date not ISO")
                if set(x[1]) != EXPECTED_PRICE_KEYS:
                    raise Stop(4, f"PRICES_DEV {s}: key set {sorted(x[1])}")
                if not all(isinstance(v, str) for v in x[1].values()):
                    raise Stop(4, f"PRICES_DEV {s}: value not str")
                rows.append(
                    dict(
                        symbol=s, date=x[0], adjusted_close=fnum(x[1][PRICE_ADJ_KEY], f"PRICES_DEV {s} {PRICE_ADJ_KEY}")
                    )
                )
            rows.sort(key=lambda r_: r_["date"])  # descending in file -> ascending
            out += rows
        return out

    def earnings_of(b: bytes, name: str, keys_req: set[str]) -> list[dict[str, Any]]:
        """FD-1: dict symbol -> list of 7-key row dicts, all values str, NO 'symbol' key (symbol = dict key). Rows arrive
        DESCENDING by reportedDate -> sorted ascending. COST rows in EARNINGS_DEV are HELD: container checked, never used."""
        D_ = json.loads(b)
        if not isinstance(D_, dict) or set(D_) != keys_req:
            raise Stop(4, f"{name}: top level not dict of {len(keys_req)} symbols")
        out: list[dict[str, Any]] = []
        for s in sorted(D_):
            L_ = D_[s]
            if not isinstance(L_, list) or not all(isinstance(x, dict) for x in L_):
                raise Stop(4, f"{name} {s}: not a list of dicts")
            if name == "EARNINGS_DEV" and s == "COST":
                out += [dict(symbol="COST", _held=True)] * len(L_)
                continue
            rows: list[dict[str, Any]] = []
            for x in L_:
                if set(x) != EXPECTED_EARN_KEYS:
                    raise Stop(4, f"{name} {s}: key set {sorted(x)}")
                if not all(isinstance(v, str) for v in x.values()):
                    raise Stop(4, f"{name} {s}: value not str")
                rows.append(dict(x, symbol=s))
            rows.sort(key=lambda r_: (r_["reportedDate"], r_["fiscalDateEnding"]))
            out += rows
        return out

    PX = prices_of(px_b)
    EA = earnings_of(ea_b, "EARNINGS_DEV", set(UNIVERSE))
    if len(PX) != S["EXPECTED_ROWS"]["PRICES_DEV"] or len(EA) != S["EXPECTED_ROWS"]["EARNINGS_DEV"]:
        raise Stop(4, f"row counts {len(PX)}/{len(EA)}")
    CE: list[dict[str, Any]] = (
        [] if cost_b is None else earnings_of(cost_b, "COST_EARNINGS_CLEAN", {"COST"})
    )  # FD-1 shape, COST key only
    fl = fye_b.decode("utf-8").splitlines()
    fh_ = fl[0].split("\t")
    if not set(fh_) >= FYE_REQUIRED_COLS:
        raise Stop(4, "FYE_MONTH_FROZEN header")
    FY = [dict(zip(fh_, l.split("\t"))) for l in fl[1:] if l.strip()]
    M = {x["symbol"]: int(x["fye_month"]) for x in FY if x["status"] == "FROZEN"}
    if not set(UNIVERSE) <= set(M):
        raise Stop(4, "FYE_MONTH_FROZEN does not cover all 50 names (OQ-5)")
    # ---- prices panel (r3 §3.1/§7: PRICES_DEV only, adjusted_close ratios) ----
    syms_px = [*UNIVERSE, HEDGE]
    col = {s: j for j, s in enumerate(syms_px)}
    A = np.full((len(sess), len(syms_px)), np.nan)
    seen: set[tuple[str, str]] = set()
    for x in PX:
        d, s = x["date"], x["symbol"]
        if d < PX_LO or d > PX_HI:
            raise Stop(8, f"price row outside DEV: {d}")
        if d not in sidx:
            raise Stop(11, f"price date not an XNYS session: {d}")
        if s not in col:
            raise Stop(4, f"unknown price symbol {s}")
        if (s, d) in seen:
            raise Stop(4, f"duplicate price {s} {d}")
        seen.add((s, d))
        v = float(x["adjusted_close"])
        if not (math.isfinite(v) and v > 0):
            raise Stop(4, f"bad adjusted_close {s} {d}")
        A[sidx[d], col[s]] = v
    del PX, px_b
    r = np.full_like(A, np.nan)
    r[1:] = A[1:] / A[:-1] - 1.0
    # ---- EARNINGS rows: COST rows from EARNINGS_DEV are HELD -> always dropped ----
    cnt = {"cost_rows_dropped_from_EARNINGS_DEV": 0}
    ER: list[dict[str, Any]] = []
    for src, rows in (("EARNINGS_DEV", EA), ("COST_EARNINGS_CLEAN", CE)):
        for x in rows:
            s = x["symbol"]
            if src == "EARNINGS_DEV" and s == "COST":
                cnt["cost_rows_dropped_from_EARNINGS_DEV"] += 1
                continue
            if src == "COST_EARNINGS_CLEAN" and s != "COST":
                raise Stop(4, "non-COST row in COST clean file")
            if s not in UNIVERSE:
                raise Stop(4, f"unknown earnings symbol {s}")
            ER.append(dict(x, src=src))
    if S["COST_EXCLUDED_BY_ERRATUM"]:
        cnt["cost_excluded_by_erratum"] = 1

    def pdate(v: object) -> dt.date | None:
        try:
            return dt.date.fromisoformat(str(v))
        except Exception:
            return None

    for e in ER:
        e["f"] = pdate(e["fiscalDateEnding"])
        e["r"] = pdate(e["reportedDate"])
        if e["f"] is None:
            raise Stop(4, f"unparseable fiscalDateEnding {e['symbol']}")
        if e["r"] is not None and not (D_LO <= e["r"] <= D_HI):
            raise Stop(8, f"EARNINGS row outside DEV {e['symbol']} {e['r']}")
    # ---- §6.1 mapping transcript label -> EARNINGS row; cross-check vs the data owner's DEV routing ----
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for e in ER:
        if e["r"] is not None:
            by_sym.setdefault(e["symbol"], []).append(e)
    tx_of: dict[tuple[str, str], str] = {}
    diag: dict[str, list[int]] = {}
    for s, lab in sorted(tx_index):
        Y, n = int(lab[:4]), int(lab[5])
        qm, why = fy_map(by_sym.get(s, []), M[s], Y)
        row = qm[n]
        dg = diag.setdefault(s, [0, 0])
        dg[0] += 1
        if row is None:
            raise Stop(3, f"MAPPING CROSSCHECK FAIL (unmappable DEV transcript) {s} {lab} {why}")
        if not (D_LO <= row["r"] <= D_HI):
            raise Stop(3, f"MAPPING CROSSCHECK FAIL (outside DEV) {s} {lab}")
        key = (s, cast(str, row["fiscalDateEnding"]))
        if key in tx_of:
            raise Stop(3, f"two transcripts map to one event {key}")
        tx_of[key] = lab
        dg[1] += 1
    step4 = {s: dict(files=v[0], matched=v[1], rate=v[1] / v[0], flag=v[1] / v[0] < 0.90) for s, v in diag.items()}

    # ---- §5 events ----
    def sess_next(d_iso: str) -> int | None:  # first session >= date
        i = bisect.bisect_left(allsess, d_iso)
        return i if i < len(allsess) else None

    EV: list[dict[str, Any]] = []
    for e in sorted(ER, key=lambda e: (e["symbol"], str(e["reportedDate"]), e["fiscalDateEnding"])):
        ev: dict[str, Any] = dict(
            symbol=e["symbol"],
            fiscalDateEnding=e["fiscalDateEnding"],
            reportedDate=str(e["reportedDate"]),
            reportTime=str(e["reportTime"]),
            label=tx_of.get((e["symbol"], e["fiscalDateEnding"]), ""),
            src=e["src"],
            day0="",
            quarter="",
            ret_start="",
            ret_end="",
            n_parseable="",
            tone=np.nan,
            n_prior="",
            surprise=np.nan,
            beta=np.nan,
            ret_raw=np.nan,
            target=np.nan,
            status="",
            i0=None,
            info_i0=None,
        )
        if e["r"] is None:
            ev["status"] = "excl_no_timestamp"
            EV.append(ev)
            continue
        ev["quarter"] = tq(ev["reportedDate"])
        rd = ev["reportedDate"]
        rt = ev["reportTime"]
        if rt == "pre-market":
            a = sess_next(rd)
        elif rt == "post-market":
            a = sess_next((e["r"] + dt.timedelta(1)).isoformat())
        else:
            a = None
            b1 = sess_next((e["r"] + dt.timedelta(1)).isoformat())
            ev["info_i0"] = (
                b1 + 1 if b1 is not None else None
            )  # withdrawn OQ-12 default: 2nd session after reportedDate (INFO)
        ev["a0"] = a
        if a is not None:
            ev["day0"] = allsess[a]
            ev["ret_start"] = allsess[a + H0] if a + H0 < len(allsess) else ""
            ev["ret_end"] = allsess[a + H1] if a + H1 < len(allsess) else ""
        EV.append(ev)
    # OQ-18: one event per symbol per calendar quarter of reportedDate; earlier kept (FI-10: applied before timing filters)
    seenq: dict[tuple[str, str], dict[str, Any]] = {}
    for ev in EV:
        if ev["status"]:
            continue
        qkey = (cast(str, ev["symbol"]), cast(str, ev["quarter"]))
        if qkey in seenq:
            ev["status"] = "excl_dup_symbol_quarter"
        else:
            seenq[qkey] = ev
    # PURGE counts (2020 boundary only; 2013 row checked at holdout run per the COST decision)
    # FI-7 AMEND: mirror route.py c16 exactly: window reportedDate 2020-11-01..2020-12-31; excl = reportTime not pre/post ONLY;
    # OQ-18 duplicates are NOT excl (classified by timing like route.py); purged = session(day0+21) > 2020-12-31; kept = rest.
    pw = [
        ev
        for ev in EV
        if ev["status"] != "excl_no_timestamp" and PURGE_WINDOW_START <= ev["reportedDate"] <= PURGE_WINDOW_END
    ]
    pc = {"in_window_rows": len(pw), "purged": 0, "kept": 0, "excl_no_reporttime": 0}
    for ev in EV:
        if ev["status"]:
            continue
        if ev["reportTime"] not in ("pre-market", "post-market"):
            ev["status"] = "excl_no_reporttime"
            continue
        if ev["ret_end"] == "" or ev["ret_end"] > DEV_HI:
            ev["status"] = "purged_straddle_2020"
            continue
        # signal availability: proxied call (pre: before open(reportedDate session); post: after close(reportedDate))
        call_session = ev["reportedDate"] if ev["reportTime"] == "post-market" else ev["day0"]
        if call_session > allsess[ev["a0"] + H0]:
            ev["status"] = "excl_call_after_close_p1"
            continue
    for ev in pw:
        if ev["reportTime"] not in ("pre-market", "post-market"):
            pc["excl_no_reporttime"] += 1
        elif ev["ret_end"] == "" or ev["ret_end"] > PURGE_WINDOW_END:
            pc["purged"] += 1
        else:
            pc["kept"] += 1
    # FD-3: real header; every column access by the real names; exactly 2 data rows of 5 fields; DEV uses the 2020 row only
    lines = [l for l in purge_b.decode("utf-8").splitlines() if l.strip()]
    if not lines or lines[0].split("\t") != EXPECTED_PURGE_HEADER:
        raise Stop(4, "PURGE.tsv header")
    hdr = EXPECTED_PURGE_HEADER
    data = [l.split("\t") for l in lines[1:]]
    if len(data) != PURGE_DATA_ROWS or any(len(r_) != len(hdr) for r_ in data):
        raise Stop(4, "PURGE.tsv data rows/fields")
    rows2020 = [dict(zip(hdr, r_)) for r_ in data if r_[0] == PURGE_BOUNDARY_DEV]
    if len(rows2020) != 1:
        raise Stop(4, "PURGE.tsv 2020 row")
    try:
        ref = {k: int(rows2020[0][k]) for k in hdr[1:]}
    except ValueError:
        raise Stop(4, "PURGE.tsv 2020 row: non-integer count")
    log("purge_2020 computed", pc, "PURGE.tsv", ref, "expected", S["EXPECTED_PURGE_2020"])
    if pc != ref or ref != S["EXPECTED_PURGE_2020"]:
        raise Stop(7, f"PURGE MISMATCH computed {pc} ref {ref}")

    # ---- §6.2 tone: open only DEV transcripts mapped to non-purged events (r3 §3.3); only `sentiment` used ----
    def tone_of(ev: dict[str, Any]) -> tuple[int | None, float | None]:
        if not ev["label"]:
            return None, None
        d = json.loads(sha_check_tx((ev["symbol"], ev["label"])))
        if not isinstance(d, dict) or set(d) != EXPECTED_TX_KEYS:
            raise Stop(4, "transcript schema")
        if d["symbol"] != ev["symbol"] or d["quarter"] != ev["label"]:
            raise Stop(3, f"transcript key mismatch {ev['symbol']} {ev['label']}")
        if not isinstance(d["transcript"], list):
            raise Stop(4, "transcript schema: transcript not a list")  # FI-4 (walk 1)
        for ent in d["transcript"]:
            if (
                not isinstance(ent, dict)
                or set(ent) != EXPECTED_TX_ENTRY_KEYS
                or not all(isinstance(x_, str) for x_ in ent.values())
            ):
                raise Stop(4, f"transcript entry schema {ev['symbol']} {ev['label']}")
        v = []
        for ent in d["transcript"]:
            try:
                f = float(ent.get("sentiment"))
                if np.isfinite(f):
                    v.append(f)
            except Exception:
                pass
        return len(v), (float(np.mean(v)) if len(v) >= TONE_MIN else np.nan)

    for ev in EV:
        if ev["status"] in ("", "excl_no_reporttime"):
            if ev["status"] == "excl_no_reporttime":
                i = ev["info_i0"]
                if i is None or i + H1 >= len(allsess) or allsess[i + H1] > DEV_HI:
                    continue
            n_, t_ = tone_of(ev)
            if n_ is not None:
                ev["n_parseable"], ev["tone"] = n_, t_
    # ---- §6.3 surprise: previous up to 4 available same-partition calls (strictly earlier day0), >= 2 ----
    avail: dict[str, list[dict[str, Any]]] = {}
    for ev in EV:
        if ev["status"] == "" and np.isfinite(ev["tone"]):
            avail.setdefault(ev["symbol"], []).append(ev)

    def surprise(ev: dict[str, Any], d0: str) -> tuple[int, float]:
        pr = sorted([p for p in avail.get(ev["symbol"], []) if p["day0"] < d0], key=lambda p: (p["day0"], p["label"]))[
            -NPRIOR_MAX:
        ]
        s_ = (
            ev["tone"] - np.mean([p["tone"] for p in pr])
            if len(pr) >= NPRIOR_MIN and np.isfinite(ev["tone"])
            else np.nan
        )
        return len(pr), cast(float, s_)

    # ---- §7 target and beta (PRICES_DEV only, 252 returns ending day0-1) ----
    def target(sym: str, d0: str) -> tuple[str, float, float, float]:
        if d0 not in sidx:
            return "excl_missing_target", np.nan, np.nan, np.nan
        i0 = sidx[d0]
        if i0 - BETA_N < 1:
            return "excl_beta_warmup", np.nan, np.nan, np.nan
        j, m = col[sym], col[HEDGE]
        x, y = r[i0 - BETA_N : i0, m], r[i0 - BETA_N : i0, j]
        if i0 + H1 >= len(sess) or not (np.isfinite(x).all() and np.isfinite(y).all()):
            return "excl_missing_target", np.nan, np.nan, np.nan
        bta = np.cov(y, x, ddof=1)[0, 1] / np.var(x, ddof=1)
        g = np.prod(1 + r[i0 + H0 + 1 : i0 + H1 + 1], axis=0) - 1
        if not (np.isfinite(g[j]) and np.isfinite(g[m])):
            return "excl_missing_target", np.nan, np.nan, np.nan
        return "", cast(float, bta), cast(float, g[j]), cast(float, g[j] - bta * g[m])

    for ev in EV:
        if ev["status"]:
            continue
        ev["n_prior"], ev["surprise"] = surprise(ev, ev["day0"])
        if ev["reportedDate"] < SCORE_LO:
            ev["status"] = "warmup_2014_not_scored"
            continue
        if not ev["label"]:
            ev["status"] = "excl_missing_transcript"
            continue
        if not np.isfinite(ev["tone"]):
            ev["status"] = "excl_tone_lt10_parseable"
            continue
        if not np.isfinite(ev["surprise"]):
            ev["status"] = "excl_lt2_prior_calls"
            continue
        st, ev["beta"], ev["ret_raw"], ev["target"] = target(ev["symbol"], ev["day0"])
        ev["status"] = st or "candidate"
    # INFO only: events excluded for reportTime that the withdrawn default would have kept (per quarter, DEV)
    info: dict[str, int] = {}
    for ev in EV:
        if ev["status"] != "excl_no_reporttime" or ev["info_i0"] is None or ev["reportedDate"] < SCORE_LO:
            continue
        i = ev["info_i0"]
        if i + H1 >= len(allsess) or allsess[i + H1] > DEV_HI or not ev["label"] or not np.isfinite(ev["tone"]):
            continue
        if not np.isfinite(surprise(ev, allsess[i])[1]):
            continue
        if target(ev["symbol"], allsess[i])[0]:
            continue
        info[ev["quarter"]] = info.get(ev["quarter"], 0) + 1
    qn: dict[str, int] = {}
    for ev in EV:
        if ev["status"] == "candidate":
            qn[ev["quarter"]] = qn.get(ev["quarter"], 0) + 1
    for ev in EV:
        if ev["status"] == "candidate":
            ev["status"] = "included" if qn[ev["quarter"]] >= Q_MIN_EVENTS else "excl_quarter_lt20_events"
    # ---- §8 metrics, §9.1 costs ----
    periods: list[dict[str, Any]] = []
    for q in SCORED_QUARTERS:
        g = [ev for ev in EV if ev["status"] == "included" and ev["quarter"] == q]
        if not g:
            continue
        n = len(g)
        leg = n // 5
        o = sorted(g, key=lambda e: (e["surprise"], e["symbol"], e["label"]))
        sh, lo = o[:leg], o[-leg:]
        ic = stats.spearmanr([e["surprise"] for e in g], [e["target"] for e in g]).statistic
        hedge = abs(np.mean([e["beta"] for e in lo]) - np.mean([e["beta"] for e in sh]))
        days = np.mean(
            [(dt.date.fromisoformat(e["ret_end"]) - dt.date.fromisoformat(allsess[e["a0"] + H0])).days for e in sh]
        )
        ls_b = np.mean([e["target"] for e in lo]) - np.mean([e["target"] for e in sh])
        ls_r = np.mean([e["ret_raw"] for e in lo]) - np.mean([e["ret_raw"] for e in sh])
        c10 = COST_SIDE * (4 + 2 * hedge)
        c20 = COST_SIDE_SENS * (4 + 2 * hedge)
        bor = BORROW * days / 365
        periods.append(
            dict(
                quarter=q,
                n=n,
                k=leg,
                n_symbols=len({e["symbol"] for e in g}),
                ic=ic,
                ls_raw=ls_r,
                ls_badj=ls_b,
                hedge_notional=hedge,
                cost10=c10,
                cost20=c20,
                borrow=bor,
                net10_badj=ls_b - c10,
                net20_badj=ls_b - c20,
                net10_badj_borrow=ls_b - c10 - bor,
                turnover_units=4 + 2 * hedge,
            )
        )
    T = len(periods)
    ics = np.array([p["ic"] for p in periods], float)
    q20 = sum(1 for q in SCORED_QUARTERS if qn.get(q, 0) >= Q_MIN_EVENTS)
    res: dict[str, Any] = dict(
        periods=T, df=T - 1, g0_quarters_ge20=q20, g0_required=G0_MIN_Q, G0_pass=bool(q20 >= G0_MIN_Q)
    )
    if T >= 2:
        t = nw_t(ics, 1)
        mn: Callable[[str], float] = lambda k_: float(np.mean([p[k_] for p in periods]))
        res.update(
            mean_ic=float(ics.mean()),
            ic_sd=float(ics.std(ddof=1)),
            nw_lag=1,
            nw_t=float(t),
            p_one_sided=float(1 - stats.t.cdf(t, df=T - 1)),
            ls_badj_mean=mn("ls_badj"),
            ls_raw_mean=mn("ls_raw"),
            net10_badj_mean=mn("net10_badj"),
            net20_badj_mean=mn("net20_badj"),
            net10_badj_borrow_mean=mn("net10_badj_borrow"),
            breakeven_cost_per_side=mn("ls_badj") / mn("turnover_units"),
        )
        res["G1"] = dict(i=res["mean_ic"] > 0, ii=res["nw_t"] >= 2.0, iii=res["net10_badj_mean"] > 0)
        res["G1_pass"] = bool(res["G0_pass"] and all(res["G1"].values()))
    else:
        res["G1_pass"] = False
    res["verdict"] = (
        "DEV PASS (G0+G1) - holdout may be considered per §12"
        if res["G1_pass"]
        else "DEV FAIL - H2-C closed; holdout never opened"
    )
    counts: dict[str, Any] = dict(
        cnt,
        status_by_partition_DEV={},
        excl_no_reporttime_per_quarter={},
        info_default_would_keep_DEV=info,
        info_default_would_keep_DEV_total=sum(info.values()),
        purge_2020=pc,
        step4=step4,
        tx_listed=len(tx_index),
        tx_mapped=len(tx_of),
        quarters_lt20={q: qn.get(q, 0) for q in SCORED_QUARTERS if qn.get(q, 0) < Q_MIN_EVENTS},
    )
    for ev in EV:
        counts["status_by_partition_DEV"][ev["status"]] = counts["status_by_partition_DEV"].get(ev["status"], 0) + 1
        if ev["status"] == "excl_no_reporttime":
            counts["excl_no_reporttime_per_quarter"][ev["quarter"]] = (
                counts["excl_no_reporttime_per_quarter"].get(ev["quarter"], 0) + 1
            )
    # ---- §11 outputs. FD-6: every text is built in memory BEFORE the run dir exists; nothing touches disk until all
    # input checks and all computations have passed. Run dir created with 'x' semantics. ----
    pk = list(periods[0]) if periods else ["quarter"]
    ek = [
        "symbol",
        "label",
        "fiscalDateEnding",
        "reportedDate",
        "reportTime",
        "day0",
        "quarter",
        "ret_start",
        "ret_end",
        "n_parseable",
        "tone",
        "n_prior",
        "surprise",
        "beta",
        "ret_raw",
        "target",
        "status",
    ]
    OUT = [
        (
            "STATS.json",
            json.dumps(dict(disclosures=DISCLOSURES, stats=res, counts=counts, versions=vers), indent=1, default=float),
        ),
        (
            "periods.tsv",
            f"# {DISCLOSURES}\n"
            + "\t".join(pk)
            + "\n"
            + "".join("\t".join(str(p[k_]) for k_ in pk) + "\n" for p in periods),
        ),
        (
            "events.tsv",
            f"# {DISCLOSURES} No transcript text.\n"
            + "\t".join(ek)
            + "\n"
            + "".join("\t".join(str(ev[k_]) for k_ in ek) + "\n" for ev in EV),
        ),
        ("counts.json", json.dumps(counts, indent=1, default=float)),
    ]
    log("done; G0", res["G0_pass"], "verdict", res["verdict"])
    rd_ = os.path.realpath(S["RUN_DIR"])
    POST_STATS[0] = True
    os.mkdir(rd_)
    ALLOW_WRITE_DIR[0] = rd_

    def W(name: str, text: str) -> None:
        with guarded_open(f"{rd_}/{name}", "x") as fh:
            fh.write(text)

    for nm_, tx_ in OUT:
        W(nm_, tx_)
    W("run.log", "\n".join(LOGBUF) + "\n")
    digests = ""
    for nm in sorted(os.listdir(rd_)):
        with guarded_open(f"{rd_}/{nm}", "rb") as fh:
            digests += f"{sha_bytes(fh.read())}  {nm}\n"
    W("SHA256SUMS", digests)
    return 0


POST_STATS = [False]  # FD-6: True from the moment the run dir (STATS) may exist


def _one_line(x: object) -> str:
    return " ".join(str(x).split())[:300]


def run(argv: list[str]) -> int:
    """FD-6/FD-8 entry point: callable after import (the validator's stage accept call) or as __main__. Returns the exit code."""
    try:
        install_guard()
        rc = main(argv)
    except BaseException as e:  # FD-6: every exception is a coded STOP; one line; nothing written to STATS
        if POST_STATS[0]:
            rc = 13
            msg = (
                f"STOP code=13 POST-STATS (final for H2-C): {type(e).__name__}"
                + (f" code={e.code}" if isinstance(e, Stop) else "")
                + f": {_one_line(e)}"
            )
        elif isinstance(e, Stop):
            rc = e.code
            msg = f"STOP code={e.code}: {_one_line(e)}"
        else:
            rc = 12
            msg = f"STOP code=12 UNCAUGHT {type(e).__name__}: {_one_line(e)}"
        try:
            log(msg)
        except BaseException:
            sys.stdout.write(msg + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(run(sys.argv))
