"""Fixed fabricated-book gates; external authority never granted by numerical output."""

from __future__ import annotations

import math
import statistics
from typing import Any, cast

from quant_research.strategies.rank1_single_name.rank1_core import Blocked, Insufficient, configurations, report


def sharpe(xs: list[float] | tuple[float, ...]) -> float:
    x = [float(v) for v in xs]
    if len(x) < 2 or any(not math.isfinite(v) for v in x):
        raise Insufficient("undefined daily series")
    sd = statistics.stdev(x)
    if sd <= 0:
        raise Insufficient("zero variance; no infinite Sharpe")
    return statistics.mean(x) / sd * math.sqrt(252)


def occupied(trades: list[Any], start: int, end: int) -> int:
    full = (end - start + 1) // 20
    return len({(t.entry - start) // 20 for t in trades if start <= t.entry <= end and (t.entry - start) // 20 < full})


def regime_labels(
    market: Any, indices: Any, vix: Any, dev_prior_vix: Any, synthetic_only: bool = False
) -> tuple[Any, Any]:
    if synthetic_only is not True:
        raise Blocked("fabricated labels only")
    # DEV source timestamps/coverage must be independently fixed; no holdout median fit here.
    if not dev_prior_vix or any(v is None or not math.isfinite(float(v)) for v in dev_prior_vix):
        raise Blocked("frozen DEV VIX prior-close sample missing")
    med = statistics.median(dev_prior_vix)
    last = max(indices)
    levels = market.total_return_levels("SYNTH_SPY", last)
    labels: dict[str, list[Any]] = {k: [] for k in ("ABOVE", "BELOW", "HIGH", "LOW", "VIX_GT25")}
    for t in indices:
        if t < 200 or len(levels[t - 200 : t]) != 200:
            raise Insufficient("200 prior SPY-TR observations missing")
        if t - 1 not in vix or vix[t - 1] is None or not math.isfinite(float(vix[t - 1])):
            raise Blocked("lagged VIX missing")
        above = levels[t - 1] > sum(levels[t - 200 : t]) / 200
        labels["ABOVE"].append(above)
        labels["BELOW"].append(not above)
        high = vix[t - 1] > med
        labels["HIGH"].append(high)
        labels["LOW"].append(not high)
        labels["VIX_GT25"].append(vix[t - 1] > 25)
    return labels, med


def entirely_within(trade: Any, allowed: set[int]) -> bool:
    return all(t in allowed for t in range(trade.entry, trade.exit + 1))


def baseline_numbers(
    primary: Any, stress: Any, alpha_t: Any, dsr: Any, bootstrap_receipt: Any
) -> tuple[list[Any], list[Any]]:
    """Pure numeric baseline layer. No caller can use it to authorize real OOS."""
    problems = []
    fails = []
    if len(primary.trades) < 100 or primary.occupied_blocks() < 30:
        problems.append("baseline counts100/30")
    if len(primary.rows) != len(stress.rows) or any(a["day"] != b["day"] for a, b in zip(primary.rows, stress.rows)):
        raise Blocked("cost paths must retain identical dates")
    for name, book, bar in (("primary", primary, 0.5), ("global_2x", stress, 0)):
        try:
            if sharpe([r["excess"] for r in book.rows]) <= bar:
                fails.append(name + " Sharpe")
        except Insufficient:
            problems.append(name + " Sharpe undefined")
    if primary.trades:
        gross = statistics.mean(float(t.gross_matched_excess) for t in primary.trades)
        cost = statistics.mean(float(t.all_in_cost_fraction) for t in primary.trades)
        if gross <= 2 * cost:
            fails.append("gross matched excess <= twice mean primary all-in cost")
    if alpha_t is None or dsr is None:
        problems.append("alpha/DSR receipt absent")
    elif not math.isfinite(alpha_t) or not math.isfinite(dsr):
        problems.append("alpha/DSR undefined")
    elif alpha_t < 3 or dsr < 0.95:
        fails.append("alpha t>=3 and DSR>=.95")
    if not bootstrap_receipt or bootstrap_receipt.get("rng_accepted") is not True:
        problems.append("approved exact PCG64/runtime unavailable")
    else:
        expected = {"opportunity_pct", "opportunity_usd_over_100k"}
        if (
            bootstrap_receipt.get("joint_draws") is not True
            or set(bootstrap_receipt.get("series", {})) != expected
            or set(bootstrap_receipt.get("fields_read", [])) != expected
        ):
            raise Blocked("Q2 BOTH explicit opportunity series and identical joint block draws required")
        for field in sorted(expected):
            values = bootstrap_receipt["series"][field]
            if any(k not in values or not math.isfinite(float(values[k])) for k in ("mean", "lower_05")):
                raise Insufficient("undefined named opportunity bootstrap statistic")
            if values["mean"] <= 0 or values["lower_05"] <= 0:
                fails.append(field + " mean/lower bound")
    return problems, fails


def robustness_numbers(primary_books: dict[str, Any], stress_books: dict[str, Any]) -> tuple[list[str], list[str]]:
    ids = {c.id for c in configurations()}
    if set(primary_books) != ids or set(stress_books) != ids:
        raise Blocked("all23 IDs required; no empty/duplicate pruning")
    insufficient = []
    fails = []
    for cfg in configurations():
        if cfg.id in {"H48", "H120"}:
            continue
        p, s = primary_books[cfg.id], stress_books[cfg.id]
        base = primary_books["H48" if cfg.delay == 48 else "H120"]
        mintr, minbl = (100, 30) if cfg.id == "NE48" else (30, 12)
        if len(p.trades) < mintr or p.occupied_blocks() < minbl:
            insufficient.append(cfg.id + " counts")
        try:
            a = sharpe([r["excess"] for r in p.rows])
            b = sharpe([r["excess"] for r in base.rows])
            c = sharpe([r["excess"] for r in s.rows])
            if a <= 0 or a < 0.5 * b or c <= 0:
                fails.append(cfg.id + " robustness Sharpe")
        except Insufficient:
            insufficient.append(cfg.id + " undefined Sharpe")
    return insufficient, fails


def regimes_covid_concentration(
    primary: Any, stress: Any, shock: Any, labels: Any, concentration_policy: Any = None
) -> tuple[list[Any], list[Any], dict[str, Any]]:
    problems: list[str] = []
    fails: list[str] = []
    details: dict[str, Any] = {}
    if concentration_policy != "NET_POSITIVE_AGGREGATE":
        raise Blocked("Q_CONCENTRATION_DENOMINATOR: accepted net-positive aggregate policy required")
    rows = primary.rows
    indices = [r["index"] for r in rows]
    for left, right in (("ABOVE", "BELOW"), ("HIGH", "LOW")):
        if left in labels and right in labels and any(bool(a) == bool(b) for a, b in zip(labels[left], labels[right])):
            raise Blocked("regime complements inconsistent")
    for name in ("ABOVE", "BELOW", "HIGH", "LOW", "VIX_GT25"):
        if name not in labels or len(labels[name]) != len(rows):
            raise Blocked("complete fixed regime labels required")
        allowed = {i for i, b in zip(indices, labels[name]) if b}
        ts = [t for t in primary.trades if entirely_within(t, allowed)]
        rs = [r for r in rows if r["index"] in allowed]
        if len(rs) < 60 or len(ts) < 10:
            problems.append(name + " 60days/10contained trades")
        else:
            try:
                value = sharpe([r["excess"] for r in rs])
                details[name] = value
                if value < -0.5:
                    fails.append(name + " Sharpe<-.5")
            except Insufficient:
                problems.append(name + " undefined Sharpe")
    windows = (
        ("COVID_2020", "2020-03-02", "2020-12-31", 100, 20, 6, primary, False),
        ("EX2020", "2021-01-04", "2025-05-22", 100, 20, 6, stress, True),
        ("MAR_JUN_SHOCK", "2020-03-02", "2020-06-30", 60, 10, 3, shock, True),
    )
    for name, lo, hi, nr, nt, nb, book, positive in windows:
        rs = [r for r in book.rows if lo <= r["day"].isoformat() <= hi]
        ts = [
            t
            for t in book.trades
            if lo <= book.m.cal.sessions[t.entry].day.isoformat() <= book.m.cal.sessions[t.exit].day.isoformat() <= hi
        ]
        if not rs:
            problems.append(name + " fixed window empty")
            continue
        # Blocks anchored to actual fixed window start; no re-anchor to first retained trade/row.
        anchor = next((i for i, s in enumerate(book.m.cal.sessions) if s.day.isoformat() == lo), None)
        last = rs[-1]["index"]
        if anchor is None:
            problems.append(name + " anchor absent")
            continue
        if len(rs) < nr or len(ts) < nt or occupied(ts, anchor, last) < nb:
            problems.append(name + " fixed adequacy")
        else:
            try:
                value = sharpe([r["excess"] for r in rs])
                details[name] = value
                if positive and value <= 0:
                    fails.append(name + " required positive Sharpe")
            except Insufficient:
                problems.append(name + " undefined Sharpe")
    yearly: dict[Any, Any] = {}
    previous = 100000.0
    for r in rows:
        year = r["day"].year
        delta = float(r["nav"]) - previous
        previous = float(r["nav"])
        yearly[year] = yearly.get(year, 0) + delta
    aggregate = sum(yearly.values())
    positive_sum = sum(max(v, 0) for v in yearly.values())
    details["year_PnL"] = yearly
    details["net_aggregate"] = aggregate
    details["sum_positive_years"] = positive_sum
    if aggregate <= 0:
        fails.append("aggregate net PnL<=0")
    elif any(v / aggregate > 0.4 for v in yearly.values()):
        fails.append("calendar-year contribution>40% net positive aggregate")
    return problems, fails, details


class OneOpeningState:
    """In-memory MOCK sequencing only. Never reads or modifies actual seals/RUNLOG."""

    def __init__(self) -> None:
        self.frozen = False
        self.dev = False
        self.opened = False

    def mock_freeze(self, evidence_complete: bool, design_resolutions_complete: bool) -> None:
        if evidence_complete is not True or design_resolutions_complete is not True:
            raise Blocked("incomplete evidence/semantics")
        self.frozen = True

    def record_dev(self, receipt: dict[str, Any]) -> None:
        if not self.frozen or receipt.get("disposition") != "SYNTHETIC_ONLY_PASS":
            raise Blocked("deterministic DEV must pass first")
        self.dev = True

    def mock_open(self) -> str:
        if not self.frozen or not self.dev or self.opened:
            raise Blocked("one opening after frozen DEV only")
        self.opened = True
        return "MOCK_ONLY_NO_ACTUAL_UNLOCK"


def aggregate_oos(
    numeric: Any,
    robustness: Any,
    regimes: Any,
    pbo: Any,
    design_questions_resolved: bool = False,
    external_evidence_complete: bool = False,
) -> dict[str, Any]:
    missing = []
    failed = []
    for p, f in (*numeric, robustness, regimes[:2]):
        missing.extend(p)
        failed.extend(f)
    if pbo is None:
        missing.append("card23 PBO absent")
    elif not math.isfinite(pbo):
        missing.append("PBO undefined")
    elif pbo >= 0.20:
        failed.append("card23 PBO>=.20")
    if missing:
        status = "INSUFFICIENT"
    elif failed:
        status = "FAIL"
    else:
        status = "SYNTHETIC_ONLY_PASS"
    # Numerical layer and authority layer reported separately. Never a real conditional PASS.
    result = report(status, dict(missing=missing, failed=failed, numeric_only=True))
    result["real_data_disposition"] = "BLOCKED"
    result["external_evidence_complete"] = external_evidence_complete
    result["design_questions_resolved"] = design_questions_resolved
    result["production_enabled"] = False
    return result


def concentration_disclosure(book: Any, frozen_sectors: dict[str, str]) -> dict[str, Any]:
    by_sector: dict[str, Any] = {}
    for r in book.rows:
        for issuer, value in r.get("holdings", {}).items():
            sector = frozen_sectors.get(issuer, "UNKNOWN_AT_VINTAGE")
            by_sector[sector] = by_sector.get(sector, 0) + float(value / r["nav"]) / len(book.rows)
    return dict(
        mean_daily_sector_weights=by_sector,
        distinct_issuers=len({t.issuer for t in book.trades}),
        max_concurrent=book.max_concurrent,
        occupied_full20_blocks=book.occupied_blocks(),
        actual_independent_N_claimed=False,
    )


def synthetic_monthly_coverage(
    rows: list[dict[str, Any]], warmup_complete: bool, embargo_complete: bool
) -> dict[str, Any]:
    """Producer totals only, never read/reconstruct any issuer/event rows."""
    expected = {
        (y, m, c) for y in range(2016, 2026) for m in range(1, 13) if (y, m) <= (2025, 5) for c in ("H48", "H120")
    }
    got = {}
    missing = []
    if warmup_complete is not True or embargo_complete is not True:
        raise Blocked("complete warmup/embargo proof missing")
    for r in rows:
        if r.get("synthetic_only") is not True:
            raise Blocked("fabricated monthly totals only")
        key = r["year"], r["month"], r["clock"]
        if key in got:
            raise Blocked("duplicate monthly coverage receipt")
        got[key] = r
        if (
            r.get("shards_complete") is not True
            or r.get("pagination_complete") is not True
            or r.get("terminal_denominator_verified") is not True
        ):
            raise Blocked("unresolved shard/retirement denominator defect")
        n, d, raw = r.get("covered"), r.get("active_denominator"), r.get("fixed_cohort_denominator")
        if (
            any(type(v) is not int for v in (n, d, raw))
            or not 0 <= cast(int, n) <= cast(int, d) <= cast(int, raw)
            or d == 0
        ):
            raise Insufficient("unknown/zero/invalid coverage denominator")
        if 10 * cast(int, n) < 9 * cast(int, d):
            missing.append(key)
    if set(got) != expected:
        raise Insufficient("exact Jan2016-May2025 both-clock monthly receipts required; dates cannot move")
    return report(
        "INSUFFICIENT" if missing else "SYNTHETIC_ONLY_PASS",
        dict(under90pct=missing, months_each_clock=113, real_data_authority=False),
    )


def synthetic_parser_totals_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Only yearly totals; not an audit, signed seen receipt, or header read."""
    from fractions import Fraction

    from quant_research.strategies.rank1_single_name.rank1_core import hash_shape

    allowed = {
        "year",
        "clock",
        "partial_2025",
        "truth_up",
        "correct_up",
        "truth_down",
        "correct_down",
        "predictions",
        "correct_predictions",
        "private_receipt_sha256",
        "independent_truth_inventory",
        "synthetic_only",
    }
    expected = {(y, c) for y in range(2016, 2026) for c in ("H48", "H120")}
    seen = set()
    insuff = []
    fails = []
    intervals = []

    def wilson(k: int, n: int) -> tuple[float, float]:
        z = 1.959963984540054
        p = k / n
        den = 1 + z * z / n
        center = (p + z * z / (2 * n)) / den
        radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
        return center - radius, center + radius

    for r in rows:
        if set(r) != allowed or r.get("synthetic_only") is not True:
            raise Blocked("yearly totals-only schema; no event/label/text exports")
        key = r["year"], r["clock"]
        if key in seen or key not in expected:
            raise Blocked("duplicate/invalid parser clock-year")
        seen.add(key)
        if r["partial_2025"] is not (r["year"] == 2025):
            raise Blocked("2025 must be explicitly partial")
        if r["independent_truth_inventory"] is not True or not hash_shape(r["private_receipt_sha256"]):
            raise Blocked("independent private inventory/receipt missing")
        counts = [
            r[x] for x in ("truth_up", "correct_up", "truth_down", "correct_down", "predictions", "correct_predictions")
        ]
        if any(type(x) is not int or x < 0 for x in counts):
            raise Blocked("invalid private-evaluator totals")
        pairs = (
            (r["correct_up"], r["truth_up"], Fraction(9, 10)),
            (r["correct_down"], r["truth_down"], Fraction(9, 10)),
            (r["correct_predictions"], r["predictions"], Fraction(19, 20)),
        )
        for numerator, denominator, floor in pairs:
            if numerator > denominator:
                raise Blocked("numerator exceeds denominator")
            if denominator < 30:
                insuff.append(key)
            elif Fraction(numerator, denominator) < floor:
                fails.append(key)
        if all(n >= 30 for _, n, _ in pairs):
            intervals.append(dict(year=key[0], clock=key[1], Wilson95=[wilson(k, n) for k, n, _ in pairs]))
    if seen != expected:
        raise Insufficient("all2016-partial2025 both-clock totals required")
    return report(
        "INSUFFICIENT" if insuff else "FAIL" if fails else "SYNTHETIC_ONLY_PASS",
        dict(
            insufficient=sorted(set(insuff)),
            failed=sorted(set(fails)),
            Wilson95_totals_only=intervals,
            actual_audit_occurred=False,
        ),
    )
