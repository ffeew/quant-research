"""TCA-owner-pinned sigma20 definition; only FABRICATED certified-TR inputs executable.
No real TR basis is accepted here; no store, archive, NumPy or network reader.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal as D
from decimal import InvalidOperation
from typing import Any, cast

from quant_research.strategies.rank1_single_name.rank1_core import Blocked, clock, hash_shape
from quant_research.utils.pins import desk_pin

SIGMA_DEFINITION_SHA256 = (
    "75da49ee5c68dd95587f7a26917870dbae3c6ddae81ce77634485e871acd7ef2"  # gitleaks:allow (sha256 digest, not a secret)
)
TOMAS_SIGNED_NOTE_SHA256 = desk_pin("strategies.rank1_single_name.rank1_sigma", "TCA_SIGNED_NOTE_SHA256")
DEFINITION_BYTES = b'{"adjustment_basis_status":"PENDING_CERTIFICATION (Dmitri): exact split/distribution arithmetic not fixed by existing sources; estimator BLOCKS until certified basis is pinned","adv20_note":"ADV20 (bucket and impact denominator) = median of 20 lagged SIP unadjusted close x consolidated volume values, per ruling Q4 reading of B8","applies_to":"Rank1 v0.2/v0.3 single-name cost impact term I=k*sigma20*sqrt(Q/ADV20)*1e4 (all legs incl. terminal when canonical inputs exist)","estimator":"sample standard deviation, ddof=1: sigma20 = sqrt( sum_{i=1..20} (r_i - rbar)^2 / 19 ), rbar = (1/20) sum r_i","failure":"any check fails -> canonical estimator BLOCKED for that leg; no substitute window, no shorter window, no zero, no default","id":"rank1.sigma20.v1","no_execution":"definition only; nothing computed","price_series":"P = total-return-compatible regular-session close on the single internally consistent distribution-inclusive accounting path of the Rank1 data contract (split and distribution treatment as certified); never price-only returns substituted for total returns; never mixing dividend-adjusted prices with separately credited dividends","returns":"r_i = P_{s_i} / P_{s_{i-1}} - 1 (daily simple total return, decimal)","terminal_fallback":"only where B8 terminal rule explicitly permits: if terminal-lag sigma20 cannot be built, use the entry-leg sigma20 (same estimator, fixed at entry); if that is also unavailable, the B8/v0.3 accepted bucket-default sigma assumption; recorded as FALLBACK (not canonical) and counted","units":"daily decimal return SD; not annualized; not percent","validity_checks":["all 21 closes present, positive and finite","21 sessions consecutive on pinned XNYS calendar","certified TR basis pinned"],"window":"21 consecutive XNYS regular sessions s_0..s_20 with s_20 = t-1, the session immediately before execution session t; closes only; no same-day (t) data"}\n'


def validate_contract(contract: dict[str, Any] | None) -> str:
    """Static signed definition satisfied; TR-basis certification remains separate."""
    if not isinstance(contract, dict) or contract.get("synthetic_only") is not True:
        raise Blocked("real sigma/TR contract adoption disabled")
    if contract.get("signed_note_sha256") != TOMAS_SIGNED_NOTE_SHA256:
        raise Blocked("TCA owner signed sigma20 receipt identity mismatch")
    raw = contract.get("definition_bytes")
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != SIGMA_DEFINITION_SHA256:
        raise Blocked("sigma20 definition bytes MUST match exact TCA owner signed hash")
    basis = contract.get("tr_basis")
    if (
        not isinstance(basis, dict)
        or basis.get("synthetic_only") is not True
        or basis.get("status") != "MOCK_CERTIFIED_SINGLE_TR_PATH"
        or not hash_shape(basis.get("sha256"))
    ):
        raise Blocked(
            "data owner total-return adjustment BASIS CERTIFICATION MISSING; signed estimator alone is insufficient"
        )
    if (
        basis.get("definition_sha256") != SIGMA_DEFINITION_SHA256
        or basis.get("distribution_inclusive_once") is not True
        or basis.get("price_only_substitute") is not False
    ):
        raise Blocked("TR basis units/distribution/price-only contract invalid")
    return cast(str, basis["sha256"])


@dataclass(frozen=True)
class TRClose:
    index: int
    value: object
    known_at: str
    basis_sha256: str
    synthetic_only: bool = False


def canonical_sigma20(
    observations: Any,
    t: int,
    calendar: Any,
    contract: dict[str, Any],
    synthetic_only: bool = False,
) -> dict[str, Any]:
    if synthetic_only is not True:
        raise Blocked("production sigma20 execution unconditionally disabled")
    basis = validate_contract(contract)
    if type(t) is not int or t < 21 or t >= len(calendar.sessions):
        raise Blocked("21 consecutive prior XNYS closes required")
    obs = tuple(observations or ())
    if (
        len(obs) != 21
        or any(not isinstance(x, TRClose) or type(x.index) is not int for x in obs)
        or tuple(x.index for x in obs) != tuple(range(t - 21, t))
    ):
        raise Blocked("exact21 consecutive closes ending t-1; no same-day/shorter window")
    cut = calendar.cutoff(calendar.sessions[t])
    prices: list[D] = []
    for row in obs:
        if row.synthetic_only is not True or row.basis_sha256 != basis:
            raise Blocked("fabricated TR marker or certified basis mismatch")
        if clock(row.known_at) >= cut:
            raise Blocked("TR close not known before execution cutoff")
        try:
            value = D(str(row.value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise Blocked("missing/nonfinite/nonpositive TR close") from exc
        if not value.is_finite() or value <= 0:
            raise Blocked("missing/nonfinite/nonpositive TR close")
        prices.append(value)
    returns = [prices[i] / prices[i - 1] - 1 for i in range(1, 21)]
    average = sum(returns, D(0)) / 20
    sigma = (sum(((r - average) ** 2 for r in returns), D(0)) / 19).sqrt()
    return dict(
        sigma20=sigma,
        estimator_sha256=SIGMA_DEFINITION_SHA256,
        basis_sha256=basis,
        window_end=t - 1,
        observations=21,
        returns=20,
        ddof=1,
        units="daily decimal; not annualized",
        canonical=True,
        synthetic_only=True,
    )
