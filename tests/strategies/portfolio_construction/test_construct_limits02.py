"""Run: $QR_DESK_DIR/portfolio/.venv/bin/python $QR_DESK_DIR/portfolio/tests/test_construct_limits02.py  (~45 s)
End-to-end construct.py runs into temp outdirs with synthetic Risk state files (never the risk manager's files):
 A  provisional panic ON + context (default) + RESUMED_DISARMED + --fallback full (tradable = optimiser)
 B  provisional panic ON + --panic_provisional apply + unknown breaker state
 C  missing panic file (fail-safe) -> applied with all fail-safe defaults
 F  FINAL panic ON with the file's response values (0.6 / 0.4 / no new loser-shorts / beta floor -0.05)
 G  FINAL panic OFF (02:27 file layout, renamed keys) -> binding but off; t8_status logged
 H  FINAL panic ON, new response fields missing -> fail-safe defaults 0.5 / 0.5 / false / -0.10
 I  --earnings_policy strict CLI option is logged"""

import glob
import json
import os
import subprocess
import sys
import tempfile
from typing import cast

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

HERE = os.path.dirname(
    cast(str, __import__("quant_research.strategies.portfolio_construction", fromlist=["_"]).__file__)
)
PY = sys.executable
NOW = "2026-10-30T02:00:00+08:00"
TS = "2026-10-30T01:22:00+08:00"
PROV = "PROVISIONAL: Alpaca-only (synthetic test)"
# Derivatives researcher deprecated statarb/data/daily_bars.json at 02:09 SGT; tests read the audit copy explicitly (logic tests, not a data endorsement)
sys.path.insert(0, HERE)
from quant_research.strategies.portfolio_construction.risk_state import limits_version

LIMITS_V = limits_version()  # whatever the LIMITS.md header says at test time (v0.3.7 at 02:28 SGT)
PROXY = f"{_QR.DESK_DIR}/statarb/data/_deprecated/daily_bars.json"
# Desk rule #5 (02:12): production default is --proxy_src store_pit + --live_source client; tests A-C pin the audit proxy and an
# offline live row (no API) so they are deterministic; test D exercises store_pit; test E the episode backstop at run equity.


def run(panic, breaker, *extra, proxy=("--proxy_src", "statarb", "--proxy_path", PROXY)):
    d = tempfile.mkdtemp()
    os.makedirs(f"{d}/targets")
    os.makedirs(f"{d}/shadow")
    pp, bp = f"{d}/panic.json", f"{d}/breaker.json"
    if panic is not None:
        json.dump(panic, open(pp, "w"))
    json.dump(breaker, open(bp, "w"))
    r = subprocess.run(
        [
            PY,
            f"{HERE}/construct.py",
            "--outdir",
            d,
            "--no_latest",
            "--now",
            NOW,
            *proxy,
            "--live_source",
            "offline_test",
            "--panic_path",
            pp,
            "--breaker_path",
            bp,
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr[-3000:]
    docs = {json.load(open(f))["book_type"]: json.load(open(f)) for f in glob.glob(f"{d}/*/targets_*.json")}
    log = [json.loads(x) for x in open(f"{d}/targets_log.jsonl")]
    return docs, log


def fails(doc):
    return [c["limit"] for c in doc["compliance"] if c["status"] == "FAIL"]


def test_A_provisional_context_resumed_disarmed_full():
    docs, log = run(
        dict(as_of_sgt=TS, panic=True, multiplier_momentum_trend=0.5, status=PROV),
        dict(
            as_of_sgt=TS,
            state="RESUMED_DISARMED",
            gross_cap_pct=30,
            new_trades_allowed=True,
            backstop_equity=90000.0,
            halt_armed=False,
            current_equity=100024.08,
        ),
        "--fallback",
        "full",
    )
    ((_bt, doc),) = docs.items()
    ro = doc["risk_overlays"]
    assert ro["panic_provisional"] is True and ro["panic_applied"] is False
    assert (
        all(v["panic_factor"] == 1.0 for v in ro["sleeve_multipliers"].values()) and ro["loser_short_ban_names"] == []
    )
    assert (
        ro["breaker"]["state"] == "RESUMED_DISARMED"
        and ro["gross_cap_pct"] == 30.0
        and doc["portfolio"]["target"]["gross_pct"] <= 30.0
    )
    assert not fails(doc), fails(doc)
    unk = set(ro["earnings"]["unknown_next_date"])
    new_unk_shorts = [
        r["symbol"] for r in doc["targets"] if r["symbol"] in unk and r["target_shares"] < min(0, r["current_shares"])
    ]
    assert not new_unk_shorts, new_unk_shorts  # tradable fail-safe
    inw = ro["earnings"]["in_window"]
    assert not [r for r in doc["targets"] if r["symbol"] in inw and abs(r["target_shares"]) > abs(r["current_shares"])]
    st = log[-1]["state"]
    assert (
        log[-1]["schema_version"] == 3
        and log[-1]["type"] == "run"
        and log[-1]["method_version"] == "v2"
        and log[-1]["limits_version"] == LIMITS_V
        and log[-1]["earnings_gate"] == "risk_ruling_20261030_0227"
        and st["panic_provisional"] is True
        and st["panic_applied"] is False
    )
    assert st["backstop_equity"] == 90000.0 and st["breaker_state"] == "RESUMED_DISARMED" and st["halt_armed"] is False
    assert log[-1]["data_defects"]["book_affected"] is False and "PROVISIONAL" in log[-1]["data_defects"]["label"]


def test_B_provisional_apply_unknown_state():
    docs, log = run(
        dict(as_of_sgt=TS, panic=True, multiplier_momentum_trend=0.5, status=PROV),
        dict(as_of_sgt=TS, state="SOMETHING_NEW", gross_cap_pct=60, new_trades_allowed=True),
        "--panic_provisional",
        "apply",
    )
    sh = docs["SHADOW"]
    ro = sh["risk_overlays"]
    assert ro["panic_applied"] is True and ro["sleeve_multipliers"]["momentum"]["panic_factor"] == 0.5
    assert ro["breaker"]["fail_safe"] and ro["breaker"]["state"] == "HALVED" and ro["gross_cap_pct"] == 30.0
    for d in docs.values():
        assert not fails(d), fails(d)
    assert all(l["state"]["panic_applied"] is True and l["state"]["breaker_state"] == "HALVED" for l in log)


def test_C_missing_panic_failsafe_applied():
    docs, _log = run(None, dict(as_of_sgt=TS, state="NORMAL", gross_cap_pct=60, new_trades_allowed=True))
    ro = docs["SHADOW"]["risk_overlays"]
    assert ro["panic"]["fail_safe"] and ro["panic_applied"] is True and ro["panic_provisional"] is False
    assert ro["sleeve_multipliers"]["trend"]["panic_factor"] == 0.5
    for d in docs.values():
        assert not fails(d), fails(d)


def test_D_store_pit_proxy_defects_excluded_v2():
    docs, log = run(
        dict(as_of_sgt=TS, panic=False, multiplier_momentum_trend=1.0, status=PROV),
        dict(as_of_sgt=TS, state="NORMAL", gross_cap_pct=60, new_trades_allowed=True, halt_armed=True),
        proxy=(),
    )
    sh = docs["SHADOW"]
    prov = sh["data_provenance"]
    sp = prov["sleeve_proxy"]
    assert sh["sleeve_id"] == "shadow_fallback_composite_v2" and sh["method_version"] == "v2"
    assert (
        sp["proxy_src"] == "store_pit"
        and "PROVISIONAL" in sp["status"]
        and prov["book_affected_by_data_defects"] is True
    )
    assert {"SNDK", "LIN"} <= set(sp["excluded_defects"]) and len(
        sp["excluded_defects"]
    ) == 59  # The validator's 59 names (SNDK already among them; added explicitly too, no double count)
    assert prov["live_row"]["source"] == "offline_test" and "store" in prov["book_history"]["source"].lower()
    assert all(v["proxy_status"].startswith("PROVISIONAL") for v in sh["risk_overlays"]["vol_scaling"].values())
    assert all(l["method_version"] == "v2" and l["data_source"]["sleeve_proxy"] == "store_pit" for l in log)
    for d in docs.values():
        assert not fails(d), fails(d)


def test_E_episode_backstop_hit_in_normal_state():
    # NORMAL in the file but run equity (100k test equity) <= Risk's episode backstop -> treated as HALTED (tighten only)
    docs, _log = run(
        dict(as_of_sgt=TS, panic=False, multiplier_momentum_trend=1.0, status=PROV),
        dict(
            as_of_sgt=TS,
            state="NORMAL",
            gross_cap_pct=60,
            new_trades_allowed=True,
            halt_armed=True,
            backstop_equity=1e9,
        ),
        "--equity",
        "100000",
        "--equity_source",
        "test",
    )
    for d in docs.values():
        b = d["risk_overlays"]["breaker"]
        assert b["state"] == "HALTED" and b["new_trades_allowed"] is False and b["backstop_equity"] == 1e9, b


FINAL = dict(
    as_of_sgt=TS,
    panic=False,
    multiplier_momentum_trend=1.0,
    new_loser_shorts_allowed=True,
    momentum_short_notional_multiplier=1.0,
    net_beta_floor=None,
    stale=False,
    fail_closed=False,
    ret_504d=0.33,
    vol_126d_ann=0.12,
    status="computed on S&P 500 official-close history (synthetic)",
)
BRK_N = dict(as_of_sgt=TS, state="NORMAL", gross_cap_pct=60, new_trades_allowed=True, halt_armed=True)


def test_F_final_panic_on_file_values():
    docs, log = run(
        dict(
            FINAL,
            panic=True,
            multiplier_momentum_trend=0.6,
            momentum_short_notional_multiplier=0.4,
            new_loser_shorts_allowed=False,
            net_beta_floor=-0.05,
        ),
        BRK_N,
    )
    for d in docs.values():
        ro = d["risk_overlays"]
        pn = ro["panic"]
        assert ro["panic_applied"] is True and ro["panic_provisional"] is False and pn["final"] is True
        assert (
            ro["sleeve_multipliers"]["momentum"]["panic_factor"] == 0.6
            and ro["sleeve_multipliers"]["trend"]["panic_factor"] == 0.6
        )
        assert ro["sleeve_multipliers"]["reversal"]["panic_factor"] == 1.0
        assert (pn["momentum_short_notional_multiplier"], pn["new_loser_shorts_allowed"], pn["net_beta_floor"]) == (
            0.4,
            False,
            -0.05,
        )
        assert d["portfolio"]["target"]["beta"] >= -0.05 - 1e-6 and d["t8_status"] == "pending_validation"
        assert not fails(d), fails(d)
    assert docs["SHADOW"]["risk_overlays"]["loser_short_ban_names"]  # ban active -> names listed
    assert all(
        l["t8_status"] == "pending_validation" and l["state"]["panic_responses"]["net_beta_floor"] == -0.05 for l in log
    )


def test_G_final_panic_off():
    docs, log = run(FINAL, BRK_N)
    for d in docs.values():
        ro = d["risk_overlays"]
        assert (
            ro["panic"]["final"] is True
            and ro["panic_provisional"] is False
            and ro["panic_applied"] is False
            and not ro["panic"]["fail_safe"]
        )
        assert (
            all(v["panic_factor"] == 1.0 for v in ro["sleeve_multipliers"].values())
            and ro["loser_short_ban_names"] == []
        )
        assert not fails(d), fails(d)
    assert all(
        l["state"]["panic_final"] is True
        and l["t8_status"] == "pending_validation"
        and l["earnings_gate"] == "risk_ruling_20261030_0227"
        for l in log
    )


def test_H_final_panic_on_fields_missing_defaults():
    old = {
        k: v
        for k, v in FINAL.items()
        if k
        not in (
            "new_loser_shorts_allowed",
            "momentum_short_notional_multiplier",
            "net_beta_floor",
            "multiplier_momentum_trend",
        )
    }
    docs, _log = run(dict(old, panic=True), BRK_N)
    for d in docs.values():
        pn = d["risk_overlays"]["panic"]
        assert (
            d["risk_overlays"]["panic_applied"] is True
            and d["risk_overlays"]["sleeve_multipliers"]["trend"]["panic_factor"] == 0.5
        )
        assert (pn["momentum_short_notional_multiplier"], pn["new_loser_shorts_allowed"], pn["net_beta_floor"]) == (
            0.5,
            False,
            -0.10,
        )
        assert d["portfolio"]["target"]["beta"] >= -0.10 - 1e-6 and not fails(d), fails(d)


def test_I_strict_policy_cli():
    docs, log = run(FINAL, BRK_N, "--earnings_policy", "strict")
    for d in docs.values():
        assert (
            d["earnings_gate"] == "strict" and d["risk_overlays"]["earnings"]["policy"] == "strict" and not fails(d)
        ), fails(d)
    assert all(l["earnings_gate"] == "strict" and l["earnings"]["policy"] == "strict" for l in log)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f()
        print("PASS", f.__name__)
    print(f"{len(fns)} tests passed")
