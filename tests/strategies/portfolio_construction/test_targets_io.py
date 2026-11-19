#!/usr/bin/env python3
"""Tests for the never-overwrite / append-only output layer. Run: .venv/bin/python tests/test_targets_io.py"""

import datetime as dt
import json
import multiprocessing as mp
import os
import subprocess
import sys
import tempfile
from typing import cast

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOTP = os.path.dirname(
    cast(str, __import__("quant_research.strategies.portfolio_construction", fromlist=["_"]).__file__)
)
sys.path.insert(0, ROOTP)
from quant_research.strategies.portfolio_construction import targets_io as tio

PY = sys.executable


def test_write_exclusive_no_overwrite():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "targets", "targets_20261030T013500SGT.json")
        tio.write_exclusive(p, {"a": 1})
        try:
            tio.write_exclusive(p, {"a": 2})
            raise AssertionError("overwrite was allowed")
        except FileExistsError:
            pass
        assert json.load(open(p)) == {"a": 1}, "original content changed"
        assert not [f for f in os.listdir(os.path.dirname(p)) if f.startswith(".tmp_")], "temp file left behind"


def test_run_stamp_format():
    now, st = tio.run_stamp(dt.datetime(2026, 10, 30, 1, 35, 7, tzinfo=dt.UTC))
    assert st == "20261030T093507SGT" and now.utcoffset() == dt.timedelta(hours=8), st


def _app(args):
    path, i = args
    for j in range(25):
        tio.append_log(path, {"proc": i, "j": j, "pad": "x" * 2000})


def test_append_only_and_concurrent():
    with tempfile.TemporaryDirectory() as d:
        log = os.path.join(d, "targets_log.jsonl")
        tio.append_log(log, {"first": True})
        head = open(log, "rb").read()
        with mp.Pool(8) as pool:
            pool.map(_app, [(log, i) for i in range(8)])
        data = open(log, "rb").read()
        assert data.startswith(head), "earlier bytes were modified"
        lines = data.decode().splitlines()
        assert len(lines) == 1 + 8 * 25, len(lines)
        recs = [json.loads(l) for l in lines]  # every line is complete, valid JSON
        assert sorted((r["proc"], r["j"]) for r in recs[1:]) == sorted((i, j) for i in range(8) for j in range(25))


def test_latest_symlink():
    with tempfile.TemporaryDirectory() as d:
        a = os.path.join(d, "t1.json")
        b = os.path.join(d, "t2.json")
        tio.write_exclusive(a, {"n": 1})
        tio.update_latest(a)
        tio.write_exclusive(b, {"n": 2})
        tio.update_latest(b)
        assert os.readlink(os.path.join(d, "latest.json")) == "t2.json"
        assert json.load(open(a)) == {"n": 1}


def test_construct_end_to_end_no_overwrite():
    """Two construct.py runs with the same --run_ts: the 2nd must fail and must not touch files or the log."""
    with tempfile.TemporaryDirectory() as d:
        flat = os.path.join(d, "pos.json")
        open(flat, "w").write("[]")
        # Synthetic fresh NORMAL breaker with new_trades_allowed=true so the tradable de-risk file is still written
        # (live desk file may have CIO all-new-trading hold -> new_trades_allowed=false -> tradable suppressed).
        bp = os.path.join(d, "breaker.json")
        pp = os.path.join(d, "panic.json")
        json.dump(
            dict(
                as_of_sgt="2026-10-30T01:50:00+08:00",
                state="NORMAL",
                gross_cap_pct=60,
                new_trades_allowed=True,
                halt_armed=True,
                backstop_equity=None,
                current_equity=100000,
            ),
            open(bp, "w"),
        )
        json.dump(
            dict(
                as_of_sgt="2026-10-30T01:50:00+08:00",
                panic=False,
                multiplier_momentum_trend=1.0,
                new_loser_shorts_allowed=True,
                momentum_short_notional_multiplier=1.0,
                net_beta_floor=None,
                stale=False,
                fail_closed=False,
                status="test FINAL",
            ),
            open(pp, "w"),
        )
        cmd = [
            PY,
            os.path.join(ROOTP, "construct.py"),
            "--outdir",
            d,
            "--positions",
            flat,
            "--equity",
            "100000",
            "--proxy_src",
            "statarb",
            "--proxy_path",
            f"{_QR.DESK_DIR}/statarb/data/_deprecated/daily_bars.json",
            "--live_source",
            "offline_test",
            "--panic_path",
            pp,
            "--breaker_path",
            bp,
            "--now",
            "2026-10-30T01:50:00+08:00",
            "--equity_source",
            "test",
            "--run_ts",
            "2026-10-30T01:50:00+08:00",
        ]
        r1 = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOTP)
        assert r1.returncode == 0, r1.stderr[-2000:]
        f_tr = os.path.join(d, "targets", "targets_20261030T015000SGT.json")
        f_sh = os.path.join(d, "shadow", "targets_20261030T015000SGT.json")
        assert os.path.exists(f_tr) and os.path.exists(f_sh)
        log = os.path.join(d, "targets_log.jsonl")
        n1 = open(log).read().splitlines()
        assert len(n1) == 2 and {json.loads(l)["book"] for l in n1} == {"SHADOW", "DE-RISK ONLY"}
        rec = json.loads(n1[0])
        for k in [
            "method_version",
            "type",
            "generated_sgt",
            "book",
            "sleeve_id",
            "equity",
            "equity_source",
            "positions_source",
            "positions_mtime_sgt",
            "state",
            "targets",
            "file_sha256",
        ]:
            assert k in rec, k
        assert rec["generated_sgt"].endswith("+08:00")
        sh = json.load(open(f_sh))
        assert sh["sleeve_id"] == "shadow_fallback_composite_v2" and sh["description"]
        assert tio.sha256(f_sh) == [json.loads(l) for l in n1 if json.loads(l)["book"] == "SHADOW"][0]["file_sha256"]
        before = (open(f_tr, "rb").read(), open(f_sh, "rb").read(), open(log, "rb").read())
        r2 = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOTP)
        assert r2.returncode != 0 and "refusing to overwrite" in (r2.stderr + r2.stdout)
        assert before == (open(f_tr, "rb").read(), open(f_sh, "rb").read(), open(log, "rb").read()), (
            "2nd run modified outputs"
        )
        r3 = subprocess.run([*cmd[:-1], "2026-10-30T01:50:01+08:00"], capture_output=True, text=True, cwd=ROOTP)
        assert r3.returncode == 0, r3.stderr[-2000:]
        lines = open(log).read().splitlines()
        assert len(lines) == 4 and open(log, "rb").read().startswith(before[2])
        assert os.readlink(os.path.join(d, "shadow", "latest.json")) == "targets_20261030T015001SGT.json"


def test_cio_hold_suppresses_tradable_write():
    """2026-11-06 rule: new_trades_allowed=false -> shadow only; no targets/*.json even if empty."""
    with tempfile.TemporaryDirectory() as d:
        flat = os.path.join(d, "pos.json")
        open(flat, "w").write("[]")
        bp = os.path.join(d, "breaker.json")
        pp = os.path.join(d, "panic.json")
        json.dump(
            dict(
                as_of_sgt="2026-11-06T06:03:00+08:00",
                state="NORMAL",
                gross_cap_pct=60,
                new_trades_allowed=False,
                halt_armed=True,
                backstop_equity=None,
                current_equity=100023.06,
            ),
            open(bp, "w"),
        )
        json.dump(
            dict(
                as_of_sgt="2026-11-06T06:00:45+08:00",
                panic=False,
                multiplier_momentum_trend=1.0,
                new_loser_shorts_allowed=True,
                momentum_short_notional_multiplier=1.0,
                net_beta_floor=None,
                stale=False,
                fail_closed=False,
                status="test FINAL",
            ),
            open(pp, "w"),
        )
        cmd = [
            PY,
            os.path.join(ROOTP, "construct.py"),
            "--outdir",
            d,
            "--positions",
            flat,
            "--equity",
            "100023.06",
            "--proxy_src",
            "statarb",
            "--proxy_path",
            f"{_QR.DESK_DIR}/statarb/data/_deprecated/daily_bars.json",
            "--live_source",
            "offline_test",
            "--panic_path",
            pp,
            "--breaker_path",
            bp,
            "--now",
            "2026-11-06T06:05:00+08:00",
            "--equity_source",
            "test",
            "--run_ts",
            "2026-11-06T06:05:00+08:00",
            "--no_latest",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOTP)
        assert r.returncode == 0, r.stderr[-2000:]
        sh = os.path.join(d, "shadow", "targets_20261106T060500SGT.json")
        tr_dir = os.path.join(d, "targets")
        assert os.path.exists(sh)
        assert not os.path.exists(os.path.join(tr_dir, "targets_20261106T060500SGT.json"))
        assert "TRADABLE SUPPRESSED" in (r.stdout + r.stderr)
        books = {
            json.loads(l).get("book")
            for l in open(os.path.join(d, "targets_log.jsonl"))
            if json.loads(l).get("type", "run") == "run"
        }
        assert books == {"SHADOW"}


def test_correction_records_reader():
    """Corrections are appended (never edit lines); read_log applies them to an effective view; mismatches are ignored."""
    with tempfile.TemporaryDirectory() as d:
        log = os.path.join(d, "targets_log.jsonl")
        tio.append_log(
            log,
            dict(
                schema_version=1,
                run_id="backfill_x",
                generated_sgt="2026-10-30T01:35:36+08:00",
                book="SHADOW",
                backfill=True,
            ),
        )
        tio.append_log(
            log, dict(schema_version=1, run_id="r1", generated_sgt="2026-10-30T01:43:40+08:00", book="SHADOW")
        )
        tio.append_log(
            log,
            dict(
                schema_version=3,
                type="run",
                method_version="v2",
                run_id="r2",
                generated_sgt="2026-10-30T02:30:00+08:00",
                book="SHADOW",
            ),
        )
        head = open(log, "rb").read()
        c = tio.correction_record(
            [
                dict(line=1, run_id="backfill_x", book="SHADOW", generated_sgt="2026-10-30T01:35:36+08:00"),
                dict(line=2, run_id="WRONG", book="SHADOW"),
            ],
            dict(method_version="legacy_pre_v1", generated_sgt_semantics="file_mtime"),
            "test",
        )
        tio.append_log(log, c)
        assert open(log, "rb").read().startswith(head)
        runs, corr, issues = tio.read_log(log)
        assert len(runs) == 3 and len(corr) == 1 and corr[0]["type"] == "correction"
        e = {r["run_id"]: r["_effective"] for r in runs}
        assert (
            e["backfill_x"]["method_version"] == "legacy_pre_v1"
            and e["backfill_x"]["method_version_source"] == "correction"
        )
        assert e["backfill_x"]["generated_sgt_semantics"] == "file_mtime" and e["backfill_x"]["corrections"] == [
            c["correction_id"]
        ]
        assert (
            e["r1"]["method_version"] == "v1"
            and e["r1"]["method_version_source"] == "inferred"
            and not e["r1"]["corrections"]
        )
        assert e["r2"]["method_version"] == "v2" and e["r2"]["method_version_source"] == "record"
        assert len(issues) == 1 and "WRONG" in issues[0]
        assert "_effective" not in json.loads(open(log).readline())  # reader never writes back


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"{len(tests)} tests passed")
