"""Exact block geometry/quantile kernels; NO unapproved RNG substitution."""

from __future__ import annotations

import math
from typing import Any

from quant_research.strategies.rank1_single_name.rank1_core import Blocked, Insufficient, report

SEED = 20261107
REPLICATIONS = 10000
BLOCK = 20


def required_pcg64() -> None:
    # Installed distribution metadata alone is NOT the accepted byte-pinned RNG/runtime.
    raise Blocked("EXACT APPROVED PCG64/NumPy/runtime BYTE LOCK MISSING; no import, RNG call or replacement")


def block_indices(T: int, sampler: Any) -> tuple[int, ...]:
    if T < BLOCK:
        raise Insufficient("20-session noncircular blocks required")
    starts = sampler.integers(0, T - BLOCK + 1, math.ceil(T / BLOCK))
    if len(starts) != math.ceil(T / BLOCK) or any(type(s) is not int or not 0 <= s <= T - BLOCK for s in starts):
        raise Blocked("invalid starts/endpoint/length")
    return tuple(i for s in starts for i in range(s, s + BLOCK))[:T]


def mock_bootstrap_joint(rows: list[dict[str, Any]], sampler: Any, synthetic_only: bool = False) -> dict[str, Any]:
    if synthetic_only is not True or getattr(sampler, "mock_only", False) is not True:
        raise Blocked("only clearly MOCK sampler for synthetic tests")
    fields = ("opportunity_pct", "opportunity_usd_over_100k")
    if any(
        r.get("synthetic_only") is not True
        or "opportunity" in r
        or "opportunity_dollar" in r
        or any(k not in r for k in fields)
        for r in rows
    ):
        raise Blocked("explicit BOTH named opportunity series required; unnamed legacy fields REFUSED")
    values = {k: [float(r[k]) for r in rows] for k in fields}
    if any(not math.isfinite(v) for xs in values.values() for v in xs):
        raise Blocked("nonfinite joint opportunity")
    estimates: dict[str, list[float]] = {k: [] for k in fields}
    for _ in range(REPLICATIONS):
        inds = block_indices(len(rows), sampler)
        # Exactly ONE joint draw per replication for BOTH series and every other field.
        for k in fields:
            estimates[k].append(sum(values[k][i] for i in inds) / len(rows))
    series: dict[str, dict[str, float]] = {}
    for k in fields:
        estimates[k].sort()
        at = 0.05 * (REPLICATIONS - 1)
        lo = int(at)
        fraction = at - lo
        series[k] = dict(
            lower_05=estimates[k][lo] * (1 - fraction) + estimates[k][lo + 1] * fraction,
            mean=sum(values[k]) / len(rows),
        )
    out = report(
        "BLOCKED",
        dict(
            reason="MOCK sampler is NOT PCG64 inference",
            replications=REPLICATIONS,
            seed_required=SEED,
            series=series,
            joint_draws=True,
            fields_read=list(fields),
        ),
    )
    out.update(rng_accepted=False, series=series, joint_draws=True, fields_read=list(fields))
    return out
