"""Pre-registered date boundaries and frozen strategy constants (do not edit; add a new version)."""

from __future__ import annotations

from datetime import date

# Splits: DEV evaluation, embargo, sealed holdout. Holdout rows are never loaded in DEV.
DEV0, DEV1 = date(2017, 1, 3), date(2021, 12, 31)
EMBARGO0, EMBARGO1 = date(2022, 1, 3), date(2022, 3, 29)
HOLDOUT0, HOLDOUT1 = date(2022, 3, 30), date(2026, 10, 28)
LOAD0 = date(2015, 12, 31)  # warm-up only; still filtered by the stage end

SECTOR_ETF = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}
ETFS = frozenset(SECTOR_ETF.values()) | {"SPY", "AGG", "BND"}

AUM = 10e6
NAME_CAP = 0.095 / 0.58  # 9.5% of equity at 58% gross
ATR_STOP_MULT = 3.0  # fixed ex ante
BASKET_STOP_EQUITY = 0.01  # 1% of equity
PARTICIPATION_CAP = 0.01  # 1% ADV; remainder carries
MARGIN = 2  # 2-session earnings margin
BORROW_UNKNOWN_REQUIRED = 0.10  # required-path borrow on every historically unknown short (ETF hedges too)
H2_DELISTING_STRESS_LONG = -0.30
H2_DELISTING_STRESS_SHORT = 0.0
H1_TERMINAL_PATHS = ("A", "B")


def stage_date_bounds(stage: str) -> tuple[date, date, date]:
    """Return (filter_end_inclusive, eval_start, eval_end) for read-time filters / evaluation."""
    if stage == "dev":
        return DEV1, DEV0, DEV1
    if stage == "holdout":
        return HOLDOUT1, HOLDOUT0, HOLDOUT1
    raise SystemExit(f"unknown stage {stage!r}")


def check_split_invariants() -> None:
    """Fail closed if the frozen boundaries were edited into an overlapping state."""
    if not (LOAD0 < DEV0 <= DEV1 < EMBARGO0 <= EMBARGO1 < HOLDOUT0 <= HOLDOUT1):
        raise SystemExit("split boundaries are not strictly ordered")
    if (HOLDOUT0 - EMBARGO1).days != 1:
        raise SystemExit("holdout must start the day after the embargo ends")
