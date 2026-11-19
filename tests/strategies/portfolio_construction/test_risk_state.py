"""Run: $QR_DESK_DIR/portfolio/.venv/bin/python $QR_DESK_DIR/portfolio/tests/test_risk_state.py
Covers missing, stale and valid state files (plus unparseable, future-dated, invalid fields, HALTED)."""

import datetime as dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant_research.strategies.portfolio_construction.risk_state import (
    SGT,
    read_breaker,
    read_panic,
    us_trading_days_between,
)

NOW = dt.datetime(2026, 10, 30, 1, 30, tzinfo=SGT)  # Thu 29 Oct 13:30 ET
tmp = tempfile.mkdtemp()


def w(name, obj):
    p = os.path.join(tmp, name)
    with open(p, "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))
    return p


def test_missing():
    p = read_panic(os.path.join(tmp, "nope.json"), NOW)
    b = read_breaker(os.path.join(tmp, "nope.json"), NOW)
    assert p["fail_safe"] and p["panic"] is True and p["multiplier_momentum_trend"] == 0.5 and "missing" in p["reason"]
    assert b["fail_safe"] and b["state"] == "HALVED" and b["gross_cap_pct"] == 30.0


def test_unparseable():
    p = read_panic(w("bad.json", "{not json"), NOW)
    b = read_breaker(w("bad2.json", ""), NOW)
    assert p["fail_safe"] and p["panic"] and b["fail_safe"] and b["state"] == "HALVED"


def test_stale():
    # as_of Thu 29 Oct 01:22 SGT = Wed 28 Oct ET; on Mon 2 Nov 10:00 SGT (Sun 1 Nov ET) -> Thu, Fri = 2 sessions -> stale
    pf = w("p_stale.json", dict(as_of_sgt="2026-10-29T01:22:00+08:00", panic=False, multiplier_momentum_trend=1.0))
    bf = w(
        "b_stale.json",
        dict(as_of_sgt="2026-10-29T01:22:00+08:00", state="NORMAL", gross_cap_pct=60, new_trades_allowed=True),
    )
    later = dt.datetime(2026, 11, 2, 10, 0, tzinfo=SGT)
    p, b = read_panic(pf, later), read_breaker(bf, later)
    assert p["fail_safe"] and p["panic"] and "stale" in p["reason"], p
    assert b["fail_safe"] and b["state"] == "HALVED" and b["gross_cap_pct"] == 30.0 and "stale" in b["reason"], b
    # exactly one session old (Wed-ET file read on Thu ET) is still fresh; two sessions (read Fri ET) is stale
    assert not read_panic(pf, dt.datetime(2026, 10, 30, 1, 0, tzinfo=SGT))["fail_safe"]
    assert read_panic(pf, dt.datetime(2026, 10, 30, 22, 0, tzinfo=SGT))["fail_safe"]


def test_valid():
    pf = w("p_ok.json", dict(as_of_sgt="2026-10-30T01:23:00+08:00", panic=False, multiplier_momentum_trend=1.0))
    bf = w(
        "b_ok.json",
        dict(as_of_sgt="2026-10-30T01:22:00+08:00", state="NORMAL", gross_cap_pct=60, new_trades_allowed=True),
    )
    p, b = read_panic(pf, NOW), read_breaker(bf, NOW)
    assert not p["fail_safe"] and p["panic"] is False and p["multiplier_momentum_trend"] == 1.0
    assert not b["fail_safe"] and b["state"] == "NORMAL" and b["gross_cap_pct"] == 60.0 and b["new_trades_allowed"]
    pon = read_panic(
        w("p_on.json", dict(as_of_sgt="2026-10-30T01:23:00+08:00", panic=True, multiplier_momentum_trend=0.5)), NOW
    )
    assert not pon["fail_safe"] and pon["panic"] and pon["multiplier_momentum_trend"] == 0.5
    halt = read_breaker(
        w(
            "b_halt.json",
            dict(as_of_sgt="2026-10-30T01:22:00+08:00", state="HALTED", gross_cap_pct=60, new_trades_allowed=True),
        ),
        NOW,
    )
    assert halt["state"] == "HALTED" and halt["gross_cap_pct"] == 30.0 and halt["new_trades_allowed"] is False


def test_invalid_fields_and_future():
    assert read_panic(w("p_inv.json", dict(as_of_sgt="2026-10-30T01:23:00+08:00", panic="no")), NOW)["fail_safe"]
    assert read_breaker(
        w(
            "b_inv.json",
            dict(as_of_sgt="2026-10-30T01:22:00+08:00", state="OK", gross_cap_pct=60, new_trades_allowed=True),
        ),
        NOW,
    )["fail_safe"]
    assert read_breaker(
        w(
            "b_fut.json",
            dict(as_of_sgt="2026-11-05T01:22:00+08:00", state="NORMAL", gross_cap_pct=60, new_trades_allowed=True),
        ),
        NOW,
    )["fail_safe"]


def test_calendar():
    # Thanksgiving 26 Nov 2026 is not a session: Wed 25 Nov ET -> Fri 27 Nov ET = 1 session
    assert (
        us_trading_days_between(
            dt.datetime(2026, 11, 26, 2, 0, tzinfo=SGT), dt.datetime(2026, 11, 28, 2, 0, tzinfo=SGT)
        )
        == 1
    )


# ---- LIMITS items added 2026-10-30 01:58 (then cited as v0.2; header cited at run time via risk_state.limits_version()) ----
OK_TS = "2026-10-30T01:22:00+08:00"


def test_panic_provisional_marker():
    prov = read_panic(
        w(
            "p_prov.json",
            dict(
                as_of_sgt=OK_TS,
                panic=True,
                multiplier_momentum_trend=0.5,
                status="PROVISIONAL: Alpaca-only ... not binding",
            ),
        ),
        NOW,
    )
    assert not prov["fail_safe"] and prov["panic"] and prov["provisional"] is True
    flag = read_panic(w("p_prov2.json", dict(as_of_sgt=OK_TS, panic=False, provisional=True)), NOW)
    assert flag["provisional"] is True
    binding = read_panic(w("p_bind.json", dict(as_of_sgt=OK_TS, panic=True, multiplier_momentum_trend=0.5)), NOW)
    assert binding["provisional"] is False  # no marker -> binding
    fs = read_panic(os.path.join(tmp, "missing.json"), NOW)
    assert fs["fail_safe"] and fs["panic"] and fs["provisional"] is None  # fail-safe is never 'provisional'


def test_resumed_disarmed():
    b = read_breaker(
        w(
            "b_rd.json",
            dict(
                as_of_sgt=OK_TS,
                state="RESUMED_DISARMED",
                gross_cap_pct=30,
                new_trades_allowed=True,
                backstop_equity=94000.0,
                current_equity=97000.0,
                halt_armed=False,
            ),
        ),
        NOW,
    )
    assert (
        not b["fail_safe"]
        and b["state"] == "RESUMED_DISARMED"
        and b["gross_cap_pct"] == 30.0
        and b["new_trades_allowed"]
    )
    assert b["backstop_equity"] == 94000.0 and b["halt_armed"] is False
    # file says 60 -> clipped to the state cap 30
    b60 = read_breaker(
        w(
            "b_rd60.json",
            dict(
                as_of_sgt=OK_TS,
                state="RESUMED_DISARMED",
                gross_cap_pct=60,
                new_trades_allowed=True,
                backstop_equity=94000.0,
            ),
        ),
        NOW,
    )
    assert b60["gross_cap_pct"] == 30.0


def test_resumed_disarmed_backstop_breach_and_missing():
    br = read_breaker(
        w(
            "b_rd_br.json",
            dict(
                as_of_sgt=OK_TS,
                state="RESUMED_DISARMED",
                gross_cap_pct=30,
                new_trades_allowed=True,
                backstop_equity=94000.0,
                current_equity=93999.0,
            ),
        ),
        NOW,
    )
    assert (
        br["state"] == "HALTED"
        and br["new_trades_allowed"] is False
        and br["state_in_file"] == "RESUMED_DISARMED"
        and not br["fail_safe"]
    )
    for bad in (None, 0, "94000", True):
        m = read_breaker(
            w(
                "b_rd_nb.json",
                dict(
                    as_of_sgt=OK_TS,
                    state="RESUMED_DISARMED",
                    gross_cap_pct=30,
                    new_trades_allowed=True,
                    backstop_equity=bad,
                ),
            ),
            NOW,
        )
        assert m["fail_safe"] and m["state"] == "HALVED" and m["gross_cap_pct"] == 30.0 and "backstop" in m["reason"], (
            bad,
            m,
        )


def test_unknown_state_failsafe_halved():
    for st in ("PAUSED", "resumed_disarmed", None, "HALF"):
        b = read_breaker(
            w("b_unk.json", dict(as_of_sgt=OK_TS, state=st, gross_cap_pct=60, new_trades_allowed=True)), NOW
        )
        assert b["fail_safe"] and b["state"] == "HALVED" and b["gross_cap_pct"] == 30.0 and b["new_trades_allowed"], (
            st,
            b,
        )


# ---- LIMITS T4 (v0.3.5 change log) (episode backstop; exit-(ii) lifts only via Risk's file; no inferred lifts) ----
def test_t4_no_inferred_lift():
    # HALTED stays de-risk only even if the file claims new_trades_allowed / carries lift-looking fields
    h = read_breaker(
        w(
            "b_h_lift.json",
            dict(
                as_of_sgt=OK_TS,
                state="HALTED",
                gross_cap_pct=30,
                new_trades_allowed=True,
                halt_armed=True,
                backstop_equity=None,
                current_equity=99000.0,
                lift_exit="ii",
                daniel_ok_logged="pending",
            ),
        ),
        NOW,
    )
    assert h["state"] == "HALTED" and h["new_trades_allowed"] is False and not h["fail_safe"]
    assert h["lift_fields_in_file"] == {"lift_exit": "ii", "daniel_ok_logged": "pending"}  # passed through, never used
    # RESUMED_DISARMED with new_trades_allowed=false in the file -> no new trades (we never override Risk upward)
    r = read_breaker(
        w(
            "b_rd_nt.json",
            dict(
                as_of_sgt=OK_TS,
                state="RESUMED_DISARMED",
                gross_cap_pct=30,
                new_trades_allowed=False,
                backstop_equity=94000.0,
                current_equity=97000.0,
            ),
        ),
        NOW,
    )
    assert r["new_trades_allowed"] is False and r["state"] == "RESUMED_DISARMED"


def test_t4_episode_backstop_from_file_only():
    # the backstop is Risk's episode level, used verbatim (an exit-(ii) reset is just a new value in the file)
    for bs, ceq in ((92000.0, 95000.0), (95500.0, 98000.0)):
        b = read_breaker(
            w(
                "b_ep.json",
                dict(
                    as_of_sgt=OK_TS,
                    state="RESUMED_DISARMED",
                    gross_cap_pct=30,
                    new_trades_allowed=True,
                    backstop_equity=bs,
                    current_equity=ceq,
                    halt_armed=False,
                    peak_eod_equity=100000.0,
                ),
            ),
            NOW,
        )
        assert (
            b["backstop_equity"] == bs
            and b["state"] == "RESUMED_DISARMED"
            and b["backstop_role"].startswith("current episode backstop")
        )
        assert b["backstop_equity"] != round(0.97 * ceq, 2)  # never recomputed as 0.97 x equity
    # a backstop still present in another non-HALTED state is enforced (tighten-only)
    hv = read_breaker(
        w(
            "b_hv_bs.json",
            dict(
                as_of_sgt=OK_TS,
                state="HALVED",
                gross_cap_pct=30,
                new_trades_allowed=True,
                halt_armed=True,
                backstop_equity=94000.0,
                current_equity=93500.0,
            ),
        ),
        NOW,
    )
    assert hv["state"] == "HALTED" and hv["new_trades_allowed"] is False and hv["state_in_file"] == "HALVED"
    bad = read_breaker(
        w(
            "b_bad_bs.json",
            dict(as_of_sgt=OK_TS, state="NORMAL", gross_cap_pct=60, new_trades_allowed=True, backstop_equity="x"),
        ),
        NOW,
    )
    assert bad["fail_safe"] and bad["state"] == "HALVED"


def test_t4_disarmed_flag_inconsistent():
    for st in ("NORMAL", "HALVED"):
        b = read_breaker(
            w(
                "b_arm.json",
                dict(
                    as_of_sgt=OK_TS,
                    state=st,
                    gross_cap_pct=60 if st == "NORMAL" else 30,
                    new_trades_allowed=True,
                    halt_armed=False,
                ),
            ),
            NOW,
        )
        assert (
            b["fail_safe"] and b["state"] == "HALVED" and b["gross_cap_pct"] == 30.0 and "halt_armed" in b["reason"]
        ), (st, b)
    ok = read_breaker(
        w(
            "b_arm_ok.json",
            dict(
                as_of_sgt=OK_TS,
                state="NORMAL",
                gross_cap_pct=60,
                new_trades_allowed=True,
                halt_armed=True,
                backstop_equity=None,
            ),
        ),
        NOW,
    )
    assert not ok["fail_safe"] and ok["gross_cap_pct"] == 60.0


# ---- Panic FINAL (Risk 2026-10-30 ~02:28): binding without a provisional marker; §3 responses from the file ----
FINAL_FILE = dict(
    as_of_sgt="2026-10-30T01:20:00+08:00",
    panic=False,
    multiplier_momentum_trend=1.0,
    new_loser_shorts_allowed=True,
    momentum_short_notional_multiplier=1.0,
    momentum_short_cut_deadline=None,
    net_beta_floor=None,
    stale=False,
    fail_closed=False,
    ret_504d=0.335763,
    vol_126d_ann=0.119763,
    vol_percentile_2520d=0.3123,
    tr_variant=dict(ret_504d=0.37),
    status="computed on S&P 500 official-close history (synthetic copy of the 02:27 layout)",
)


def test_panic_final_off():
    p = read_panic(w("pf_off.json", FINAL_FILE), NOW)
    assert not p["fail_safe"] and p["panic"] is False and p["provisional"] is False and p["final"] is True, p
    assert p["multiplier_momentum_trend"] == 1.0 and p["momentum_short_notional_multiplier"] == 1.0
    assert (
        p["new_loser_shorts_allowed"] is True and p["net_beta_floor"] is None and p["t8_status"] == "pending_validation"
    )


def test_panic_final_on_uses_file_values():
    p = read_panic(
        w(
            "pf_on.json",
            dict(
                FINAL_FILE,
                panic=True,
                multiplier_momentum_trend=0.6,
                momentum_short_notional_multiplier=0.4,
                new_loser_shorts_allowed=False,
                net_beta_floor=-0.05,
            ),
        ),
        NOW,
    )
    assert not p["fail_safe"] and p["panic"] is True and p["final"] is True
    assert (
        p["multiplier_momentum_trend"],
        p["momentum_short_notional_multiplier"],
        p["new_loser_shorts_allowed"],
        p["net_beta_floor"],
    ) == (0.6, 0.4, False, -0.05)
    assert set(p["response_source"].values()) == {"file"} and p["t8_status"] == "pending_validation"
    # file says loser shorts allowed while on -> applied as written
    q = read_panic(
        w(
            "pf_on2.json",
            dict(
                FINAL_FILE,
                panic=True,
                multiplier_momentum_trend=0.5,
                momentum_short_notional_multiplier=0.5,
                new_loser_shorts_allowed=True,
                net_beta_floor=-0.10,
            ),
        ),
        NOW,
    )
    assert q["new_loser_shorts_allowed"] is True and q["net_beta_floor"] == -0.10


def test_panic_provisional_context_only_marker():
    p = read_panic(w("pf_prov.json", dict(FINAL_FILE, panic=True, provisional=True)), NOW)
    assert p["provisional"] is True and p["final"] is False and not p["fail_safe"] and p["panic"] is True


def test_panic_new_fields_missing_safe_defaults():
    old = {
        k: v
        for k, v in FINAL_FILE.items()
        if k
        not in (
            "new_loser_shorts_allowed",
            "momentum_short_notional_multiplier",
            "net_beta_floor",
            "multiplier_momentum_trend",
        )
    }
    p = read_panic(w("pf_missing.json", dict(old, panic=True)), NOW)
    assert not p["fail_safe"] and p["panic"] is True
    assert (
        p["multiplier_momentum_trend"],
        p["momentum_short_notional_multiplier"],
        p["new_loser_shorts_allowed"],
        p["net_beta_floor"],
    ) == (0.5, 0.5, False, -0.10)
    assert all(v.startswith("default") for v in p["response_source"].values()), p["response_source"]
    # null / invalid values -> defaults too
    q = read_panic(
        w(
            "pf_bad.json",
            dict(
                FINAL_FILE,
                panic=True,
                multiplier_momentum_trend=1.7,
                momentum_short_notional_multiplier="half",
                new_loser_shorts_allowed="no",
                net_beta_floor=None,
            ),
        ),
        NOW,
    )
    assert (
        q["multiplier_momentum_trend"],
        q["momentum_short_notional_multiplier"],
        q["new_loser_shorts_allowed"],
        q["net_beta_floor"],
    ) == (0.5, 0.5, False, -0.10)


def test_panic_renamed_keys_do_not_trip_failsafe():
    p = read_panic(
        w("pf_keys.json", {k: v for k, v in FINAL_FILE.items() if not k.startswith(("ret_", "vol_", "tr_"))}), NOW
    )
    assert not p["fail_safe"] and p["reason"] == "valid"


def test_panic_file_says_stale_or_fail_closed():
    for k in ("stale", "fail_closed"):
        p = read_panic(w(f"pf_{k}.json", dict(FINAL_FILE, **{k: True})), NOW)
        assert (
            p["fail_safe"]
            and p["panic"] is True
            and p["net_beta_floor"] == -0.10
            and p["new_loser_shorts_allowed"] is False
        ), p


def test_limits_version_from_header():
    from quant_research.strategies.portfolio_construction.risk_state import limits_version

    h = w("LIMITS.md", "# Desk Risk Limits — v9.8.7 (synthetic)\nbody v0.0.1\n")
    assert limits_version(h) == "v9.8.7" and limits_version(os.path.join(tmp, "none.md")) is None


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f()
        print("PASS", f.__name__)
    print(f"{len(fns)} tests passed")
