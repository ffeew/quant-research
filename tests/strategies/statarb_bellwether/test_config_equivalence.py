"""Behaviour equivalence: the config-driven runner vs the pre-cleanup runner (literal pins).

The pre-cleanup module is read from git history at test time. Every pin value it hard-coded is
evaluated from that source and written into a temporary config for the cleaned module, so no
pin or desk path is stored in this repo. Both modules then run the same refusal ladder and the
same computations on small synthetic fixtures, and must agree.
Skipped when the git history is not available (e.g. a shallow CI checkout).
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from quant_research.utils import config as qrc
from quant_research.utils import paths as qrp

REL = "src/quant_research/strategies/statarb_bellwether/backtest_h1_h2_v1_3f.py"
OLD_REV = "a866c23"  # initial import commit: the runner with literal pins
NEW_PATH = qrc.REPO_ROOT / REL
NEW_SRC = NEW_PATH.read_text()
PIN_NAMES = list(dict.fromkeys(re.findall(r'_pin\(\s*"([A-Z0-9_]+)"', NEW_SRC)))
DERIVED = ("EARNINGS_SHA256", "UNIVERSE_CUT_SHA256")
SITE = os.path.dirname(os.path.dirname(np.__file__))
H = "ab" * 32  # synthetic 64-hex value


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture(scope="module")
def old_src() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(qrc.REPO_ROOT), "show", f"{OLD_REV}:{REL}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("pre-cleanup runner not in git history")
    return out.stdout


# ---- fakes shared by both modules ----


def _group(pat: str, text: str, flags: int = 0) -> str:
    m = re.search(pat, text, flags)
    assert m is not None, pat
    return m.group(1)


def _fstring_value(node: ast.expr) -> str:
    """Value of the old f"{_QR.X}/..." literal (only _QR attributes and constants)."""
    assert isinstance(node, ast.JoinedStr)
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append(str(v.value))
        else:
            assert isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Attribute)
            assert ast.unparse(v.value.value) == "_QR"
            parts.append(str(getattr(qrp, v.value.attr)))
    return "".join(parts)


def fake_costs() -> types.ModuleType:
    m = types.ModuleType("costs_original")
    m.__dict__.update(
        BORROW_UNKNOWN_REQUIRED=0.10,
        EARLY_CLOSE_DAYS_2026={"2026-11-27"},
        K_IMPACT_BASE=1.0,
        K_IMPACT_LIGHTER=0.75,
        annual_drag=lambda *a, **k: 0.0,
        build_cost_config=lambda path: types.SimpleNamespace(
            label=path, borrow_rate=0.10, is_pass_bar=True, k_impact=1.0
        ),
        borrow_usd=lambda mv, days, cfg: {"usd": abs(mv) * cfg.borrow_rate * days / 360.0},
        one_way_bps=lambda side, px, sh, adv, sig, cfg, venue, symbol, etf_symbols: {
            "bps": 3.0 + (2.0 if symbol in etf_symbols else 0.0) + (1.0 if side == "sell" else 0.0)
        },
    )
    return m


def _exec(path: Path, name: str, cfg: Path | None) -> Any:
    saved_path, saved_env = list(sys.path), os.environ.get("QR_STATARB_BELLWETHER_CONFIG")
    sys.modules["costs_original"] = fake_costs()
    if cfg is not None:
        os.environ["QR_STATARB_BELLWETHER_CONFIG"] = str(cfg)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit as e:
            return ("exit", e.code)
        return mod
    finally:
        sys.path[:] = saved_path
        sys.modules.pop("costs_original", None)
        if saved_env is None:
            os.environ.pop("QR_STATARB_BELLWETHER_CONFIG", None)
        else:
            os.environ["QR_STATARB_BELLWETHER_CONFIG"] = saved_env


def _lit(v: Any) -> str:
    return f"Path({str(v)!r})" if isinstance(v, Path) else repr(v)


def patch_old(src: str, ov: dict[str, Any]) -> str:
    """Replace the old module-level literal assignments named in ov (whole statements)."""
    tree = ast.parse(src)
    lines = src.split("\n")
    edits = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            names = (
                [t.id] if isinstance(t, ast.Name) else [e.id for e in getattr(t, "elts", []) if isinstance(e, ast.Name)]
            )
            hit = [n for n in names if n in ov]
            if hit:
                assert len(hit) == len(names), names
                edits.append((node.lineno, node.end_lineno, "; ".join(f"{n} = {_lit(ov[n])}" for n in names)))
    for a, b, text in sorted(edits, reverse=True):
        lines[a - 1 : b] = [text]
    out = "\n".join(lines)
    # values the old runner kept inline
    if "NP_RECORD_REL" in ov:
        out = out.replace('NP_SITE + "/numpy-2.5.4.dist-info/RECORD"', f"NP_SITE + {'/' + ov['NP_RECORD_REL']!r}")
    if "NP_VERSION" in ov:
        out = out.replace('np.__version__ == "2.5.4"', f"np.__version__ == {ov['NP_VERSION']!r}")
    return out


def old_inline(src: str) -> dict[str, Any]:
    """Pins the old runner kept inline, evaluated from its source."""
    tree = ast.parse(src)
    vals: dict[str, Any] = {}
    inserts = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "sys.path.insert"]
    vals["COSTS_ORIGINAL_DIR"] = _fstring_value(inserts[-1].args[1])
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "bind_dev_inputs":
            for f in ast.walk(n):
                if isinstance(f, ast.For) and isinstance(f.iter, ast.Tuple):
                    vals["DEV_UNIVERSE_FILES"] = [ast.literal_eval(e) for e in f.iter.elts]
                if isinstance(f, ast.Compare) and ast.unparse(f.left) == "len(lineage)":
                    vals["LINEAGE_EXCL_COUNT"] = ast.literal_eval(f.comparators[0])
        if isinstance(n, ast.Subscript) and ast.unparse(n).startswith("PREREG_PATH.read_text().splitlines()["):
            vals["PREREG_TR_PIN_LINE"] = ast.literal_eval(n.slice) + 1
    vals["NP_RECORD_REL"] = _group(r'NP_SITE \+ "/([^"]+)"', src)
    vals["NP_VERSION"] = _group(r'np\.__version__ == "([^"]+)"', src)
    return vals


def _toml(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json.dumps(k)} = {_toml(x)}" for k, x in v.items()) + "}"
    return json.dumps(str(v))


def write_cfg(path: Path, vals: dict[str, Any]) -> Path:
    path.write_text("[pins]\n" + "".join(f"{k} = {_toml(v)}\n" for k, v in vals.items()))
    return path


def c7_values() -> dict[str, Any]:
    rel = f"numpy-{np.__version__}.dist-info/RECORD"
    return {
        "NP_SITE": SITE,
        "NP_RECORD_REL": rel,
        "NP_VERSION": np.__version__,
        "NP_RECORD_SHA256": sha((Path(SITE) / rel).read_bytes()),
    }


def pair(old_src: str, tmp: Path, ov: dict[str, Any]) -> tuple[Any, Any]:
    """Old with literal overrides; new with a config holding every value the old module ended up with."""
    full = {**c7_values(), **ov}
    old_file = tmp / "old_runner.py"
    old_file.write_text(patch_old(old_src, full))
    old = _exec(old_file, "old_runner", None)
    assert not isinstance(old, tuple), old
    inline = old_inline(old_src)
    vals = {n: full.get(n, getattr(old, n, None) if hasattr(old, n) else inline.get(n)) for n in PIN_NAMES}
    vals = {k: v for k, v in vals.items() if v is not None}
    new = _exec(NEW_PATH, "new_runner", write_cfg(tmp / "cfg.toml", vals))
    assert not isinstance(new, tuple), new
    return old, new


def test_example_config_refuses_at_import_like_old(old_src, tmp_path):
    old_file = tmp_path / "old_runner.py"
    old_file.write_text(old_src)
    assert _exec(old_file, "old_runner", None) == ("exit", 17)
    assert _exec(NEW_PATH, "new_runner", qrc.CONFIG_DIR / "statarb_bellwether.toml") == ("exit", 17)
    assert _exec(NEW_PATH, "new_runner", tmp_path / "absent.toml") == ("exit", 17)


def test_every_pin_value_identical(old_src, tmp_path):
    old, new = pair(old_src, tmp_path, {})
    names = [n for n in PIN_NAMES if hasattr(old, n)] + list(DERIVED)
    assert len(names) >= 50
    for n in names:
        a, b = getattr(old, n), getattr(new, n)
        assert type(a) is type(b) and a == b, n
    inline = old_inline(old_src)
    for n in ("DEV_UNIVERSE_FILES", "LINEAGE_EXCL_COUNT", "PREREG_TR_PIN_LINE", "COSTS_ORIGINAL_DIR"):
        assert list(getattr(new, n)) == list(inline[n]) if isinstance(inline[n], list) else getattr(new, n) == inline[n]


# ---- synthetic world ----


def world(tmp: Path, old_src: str) -> dict[str, Any]:
    """Synthetic files for every gate up to the desk-client static check."""
    d = tmp / "w"
    d.mkdir()
    pr = d / "PREREG.md"
    pr.write_text("".join(f"line {i}\n" for i in range(1, 38)) + f"| total return | `{H}` |\n" + "tail\n")
    inline = old_inline(old_src)
    dev, add = d / "dev_inputs", d / "addendum"
    dev.mkdir()
    add.mkdir()
    for name in inline["DEV_UNIVERSE_FILES"]:
        (dev / name).write_text("symbol\nAAA\nBBB\n")
    (dev / "SHA256SUMS").write_text(
        "".join(f"{sha((dev / n).read_bytes())}  {n}\n" for n in inline["DEV_UNIVERSE_FILES"])
    )
    lin = d / "lin.tsv"
    lin.write_text("symbol\treason\n" + "".join(f"Z{i:02d}\tsynthetic\n" for i in range(inline["LINEAGE_EXCL_COUNT"])))
    (add / "lineage.tsv").write_bytes(lin.read_bytes())
    (add / "SHA256SUMS").write_text(f"{sha(lin.read_bytes())}  lineage.tsv\n")
    cuts = d / "cuts"
    cuts.mkdir()
    old_keys = list(ast.literal_eval(_group(r"DEV_CUT_PINS = (\{.*?\n\})", old_src, re.S)))
    pins = {}
    for k in old_keys:
        (cuts / k).write_bytes(b"synthetic " + k.encode())
        pins[k] = sha((cuts / k).read_bytes())
    cut_sums = d / "OUT_SUMS"
    cut_sums.write_text("".join(f"{h}  {cuts / k}\n" for k, h in pins.items()))
    fl = d / "fl.tsv"
    fl.write_bytes(b"symbol\tdecision\treasons\tissuer_name\nAAA\tKEPT\t\tA\nGGG\tEXCLUDED\treuse\tG\n")
    b1c = d / "B1C"
    b1c.write_text("synthetic\n")
    client = d / "client.py"
    client.write_text("def xnys_sessions(a, b):\n    return None\n\ndef pit_membership():\n    return None\n")
    tr = d / "tr.parquet"
    days = pd.bdate_range("2021-01-04", periods=30)
    pd.DataFrame(
        {
            "symbol": "AAA",
            "session_date": [x.date() for x in days],
            "close_raw": 50.0,
            "volume_raw": 1e6,
            "ret_total_best": 0.001,
            "tr_index_best": 1.0,
        }
    ).to_parquet(tr)
    tr_sums = d / "TR_SUMS"
    tr_sums.write_text(f"{sha(tr.read_bytes())}  {tr}\n")
    pa_rel = next(p.name for p in Path(SITE).glob("pyarrow-*.dist-info")) + "/RECORD"
    ov = {
        "PREREG_PATH": pr,
        "DEV_INPUTS_DIR": str(dev),
        "DEV_INPUTS_SUMS_SHA256": sha((dev / "SHA256SUMS").read_bytes()),
        "ADDENDUM1_DIR": str(add),
        "ADDENDUM1_SUMS_SHA256": sha((add / "SHA256SUMS").read_bytes()),
        "LINEAGE_EXCL_FILE": "lineage.tsv",
        "LINEAGE_EXCL_SHA256": sha(lin.read_bytes()),
        "DEV_CUTS_DIR": str(cuts),
        "DEV_CUTS_SUMS_PATH": str(cut_sums),
        "DEV_CUTS_SUMS_SHA256": sha(cut_sums.read_bytes()),
        "DEV_CUT_PINS": pins,
        "FINAL_LIST_PATH": str(fl),
        "FINAL_LIST_SHA256": sha(fl.read_bytes()),
        "DESK_CLIENT_PATH": str(client),
        "DESK_CLIENT_SHA256": sha(client.read_bytes()),
        "PYARROW_SITE_APPROVED": SITE,
        "PYARROW_RECORD_REL": pa_rel,
        "PYARROW_RECORD_SHA256": sha((Path(SITE) / pa_rel).read_bytes()),
        "TR_PARENT_SHA256": H,
        "TR_DEV_CUT_PATH": str(tr),
        "TR_DEV_CUT_SHA256": sha(tr.read_bytes()),
        "TR_DEV_CUT_SUMS_PATH": str(tr_sums),
        "TR_DEV_CUT_SUMS_SHA256": sha(tr_sums.read_bytes()),
        "QUARANTINE": d / "quarantine",
        "OUT_DIR": d / "out",
    }
    return {"ov": ov, "b1c": b1c, "prereg_sha": sha(pr.read_bytes()), "dev": str(dev)}


def outcome(mod: Any, argv: list[str]) -> tuple[Any, ...]:
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mod.main(argv)
        return ("rc", rc, buf.getvalue())
    except SystemExit as e:
        code = e.code
        if isinstance(code, str):  # free-text refusal: compare its kind, not the wording
            code = code.split(":")[0]
        return ("exit", type(e).__name__, code)


def test_refusal_ladder_identical(old_src, tmp_path):
    w = world(tmp_path, old_src)
    good = ["--stage", "dev", "--acceptance-hash", w["prereg_sha"]]
    site = ["--pyarrow-site", SITE, "--pyarrow-site-sha", w["ov"]["PYARROW_RECORD_SHA256"]]
    ladders = {
        "pending_b1c": [
            ["--syntax-check"],
            [],
            ["--stage", "dev"],
            ["--stage", "dev", "--acceptance-hash", "0" * 64],
            good,
            good + ["--pyarrow-site", "/nonexistent"],
            good + ["--pyarrow-site", SITE, "--pyarrow-site-sha", H],
            good + site,
            ["--stage", "holdout", "--acceptance-hash", w["prereg_sha"]] + site,
            good + site + ["--delisting-stress", "--idea", "H1"],
            good + site + ["--delisting-stress", "--idea", "H2", "--av-factor-sensitivity"],
            good + site + ["--dev-inputs", "/nonexistent"],
            good + site + ["--dev-inputs", w["dev"]],
            good + site + ["--dev-inputs", w["dev"], "--av-factor-sensitivity"],
        ],
    }
    add2 = tmp_path / "addendum_short"
    add2.mkdir()
    n = old_inline(old_src)["LINEAGE_EXCL_COUNT"] - 1
    (add2 / "lineage.tsv").write_text("symbol\treason\n" + "".join(f"Z{i:02d}\tsynthetic\n" for i in range(n)))
    (add2 / "SHA256SUMS").write_text(f"{sha((add2 / 'lineage.tsv').read_bytes())}  lineage.tsv\n")
    short = {
        "ADDENDUM1_DIR": str(add2),
        "ADDENDUM1_SUMS_SHA256": sha((add2 / "SHA256SUMS").read_bytes()),
        "LINEAGE_EXCL_SHA256": sha((add2 / "lineage.tsv").read_bytes()),
    }
    seen = set()
    for label, ov in (
        ("pending_b1c", {}),
        ("short_lineage", short),
        ("b1c_ok", {"B1C_ACCEPTED_SUMS_PATH": str(w["b1c"]), "B1C_ACCEPTED_SUMS_SHA256": sha(w["b1c"].read_bytes())}),
        (
            "b1c_bad_final_list",
            {
                "B1C_ACCEPTED_SUMS_PATH": str(w["b1c"]),
                "B1C_ACCEPTED_SUMS_SHA256": sha(w["b1c"].read_bytes()),
                "FINAL_LIST_SHA256": H,
            },
        ),
    ):
        d = tmp_path / label
        d.mkdir()
        old, new = pair(old_src, d, {**w["ov"], **ov})
        for argv in ladders.get(label, [good + site + ["--dev-inputs", w["dev"]]]):
            a, b = outcome(old, argv), outcome(new, argv)
            assert a == b, (label, argv, a, b)
            seen.add(a[:3] if a[0] == "exit" else a[:2])
    # the ladder reached distinct refusals, the rc-18 identity check and the client static check
    assert ("exit", "FinalListMismatch", 18) in seen and ("rc", 0) in seen and len(seen) >= 4
    old, new = pair(old_src, tmp_path / "short_lineage", {**w["ov"], **short})
    for mod in (old, new):
        with pytest.raises(SystemExit, match="lineage exclusions"):
            mod.bind_dev_inputs(mod.DEV_INPUTS_DIR)


def bars(n: int = 420, seed: int = 3) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2016-01-04", periods=n)
    syms = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "XLK", "SPY"]
    mkt = rng.normal(0.0003, 0.008, n)
    R = pd.DataFrame({s: mkt + rng.normal(0, 0.01, n) for s in syms}, index=dates)
    R["XLK"] = R["SPY"] = mkt
    R.iloc[300:360, :2] += 0.004
    R.iloc[330, :2] += 0.08
    R.iloc[0] = np.nan
    PX = (1 + R.fillna(0)).cumprod() * 50.0
    VOL = pd.DataFrame(1e6, index=dates, columns=syms)
    VOL[["AAA", "BBB"]] = 3e6
    PX.iloc[400:, 2] = np.nan  # CCC stops printing (delisting paths)
    VOL.iloc[400:, 2] = 0
    R.iloc[400:, 2] = np.nan
    return {"R": R, "PX": PX, "VOL": VOL, "TRI": PX.copy()}


def earnings(dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for s in ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]:
        off = 0 if s in ("AAA", "BBB") else -10
        for k in (204, 267, 330, 393):
            d = dates[k + off]
            rows.append(
                {
                    "symbol": s,
                    "source": "sec_8k",
                    "timing_quality": "exact_acceptance_time",
                    "announce_date_et": d - pd.Timedelta(days=1),
                    "reaction_session": d,
                    "first_tradable_session": d,
                    "knowledge_time_utc": pd.Timestamp(d, tz="UTC") - pd.Timedelta(hours=2),
                }
            )
    return pd.DataFrame(rows)


class FakeClient:
    def pit_membership_sha256(self) -> str:
        return H

    def listing_status_sha256(self) -> str:
        return H

    def pit_membership(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "XLK", "GGG"],
                "start_date_filled": pd.Timestamp("2015-01-02"),
                "end_date": [None] * 8,
            }
        )

    def listing_status(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "AAA"],
                "ipoDate": ["2000-01-03"] * 6 + ["1990-01-02"],
                "delistingDate": ["null"] * 6 + ["1999-01-04"],
                "listing_source": ["active"] * 6 + ["delisted"],
            }
        )

    def xnys_sessions(self, a: Any, b: Any) -> pd.DatetimeIndex:
        return pd.bdate_range(a, b)

    def accepted_acquirer_closes(self, acq: str, a: Any, b: Any) -> pd.Series:
        return pd.Series(60.0, index=pd.bdate_range(a, b))


def _eq(a: Any, b: Any) -> None:
    if isinstance(a, pd.DataFrame | pd.Series):
        pd.testing.assert_frame_equal(a, b) if isinstance(a, pd.DataFrame) else pd.testing.assert_series_equal(a, b)
    elif isinstance(a, tuple | list):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            _eq(x, y)
    elif isinstance(a, dict):
        assert a.keys() == b.keys()
        for k in a:
            _eq(a[k], b[k])
    elif isinstance(a, np.ndarray):
        np.testing.assert_array_equal(a, b)
    else:
        assert a == b or (a != a and b != b), (a, b)


def _try(f: Any, *a: Any) -> Any:
    try:
        return f(*a)
    except SystemExit as e:
        return (type(e).__name__, e.code if not isinstance(e.code, str) else "msg")


def run_all(mod: Any, tmp: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    B = bars()
    mem, sub, sec, rec = mod.load_universe_v13a(
        FakeClient(),
        pd.Series("Semis", index=["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]),
        pd.Series("Information Technology", index=["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]),
        final_list=mod.load_final_list(),
    )
    out["universe"] = (mem, sub, sec, rec)
    E = mod.build_elig(B, mem)
    ev = earnings(pd.DatetimeIndex(B["R"].index))
    epi = mod.earliest_possible_index(ev, B["R"].index)
    evidx = mod.make_evidx(epi)
    last = len(B["R"].index) - 1 - mod.MARGIN
    W1, tr = mod.signal_h1(B, E, sub, evidx, eval_start=mod.DEV0, eval_end=mod.DEV1, last_exit_i=last)
    W2, pos = mod.signal_h2(B, E, sub, sec, ev, evidx, eval_start=mod.DEV0, eval_end=mod.DEV1, last_exit_i=last)
    cfg = mod.build_cost_config("unknown_borrow_required")
    r1 = mod.apply_costs_and_returns(B, W1, cfg, idea="H1")
    r2 = mod.apply_costs_and_returns(B, W2, cfg, idea="H2")
    roster = [
        {
            "symbol": "CCC",
            "identity_ok": True,
            "short_terms": {
                "h": str(B["R"].index[410].date()),
                "alternatives": [{"cash": 5.0, "ratio": 1.0, "acquirer_id": "ACQ", "acquirer_identity_accepted": True}],
            },
        }
    ]
    tb = [mod.h1_terminal_bound(B, W1, roster, cfg, client=FakeClient(), path=p) for p in mod.H1_TERMINAL_PATHS]
    out.update(
        elig=E,
        epi=epi,
        evidx=evidx,
        W1=W1,
        tr=tr,
        W2=W2,
        pos=pos,
        r1=r1,
        r2=r2,
        tb=tb,
        rec2=mod.h2_delisting_receipts(B, pos),
        stress=mod.h2_delisting_stress(B, W2, pos),
        sharpe=(mod.sharpe_ann(r1["daily"]["net"]), mod.sharpe_ann(r2["daily"]["net"])),
        bounds=[mod.stage_date_bounds(s) for s in ("dev", "holdout")],
        pins=[_try(mod.require_data_pins, flag) for flag in (False, True)],
    )
    mod.verify_pyarrow_site(SITE, mod.PYARROW_RECORD_SHA256)
    out["tr_bars"] = mod.load_bars_tr(mod.DEV1)
    out["dev_cuts"] = mod.verify_dev_cuts()
    out["dev_inputs"] = mod.bind_dev_inputs(mod.DEV_INPUTS_DIR)
    return out


# Computations changed on purpose by the review fixes (see test_v1_3f_fixes.py) and therefore
# excluded from old == new: signal_h1 weights (B1: held from the session after the signal bar),
# apply_costs_and_returns and everything priced from it (B2 ADV cap on the trade, B3 calendar-day
# borrow), and h1_terminal_bound (built on the H1 weights; B3 borrow overlay). Everything else,
# including every pin and config value, must still match the pre-cleanup module exactly.
# h2_delisting_stress now prices the position actually held (review round 2); on these fixtures
# that equals the target, so it stays in the comparison.
# Review round 3: R3-fill (a fill at close j-1 is priced, print-checked and capped on row j-1)
# changes the priced paths r1, r2, sharpe and the H1 bound tb; it leaves rec2 and stress equal here.
FIXED = {
    "W1": "B1",
    "r1": "B1 B2 B3 R3-fill",
    "r2": "B2 B3 R3-fill",
    "tb": "B1 B3 R3-fill",
    "sharpe": "B1 B2 B3 R3-fill",
}


def test_computations_identical_on_synthetic_fixtures(old_src, tmp_path):
    """Old == new on every computation except the FIXED ones (the three review fixes). For those,
    H1's weights must be exactly the old weights moved one session later."""
    w = world(tmp_path, old_src)
    r18 = tmp_path / "r18.json"
    r18.write_text(
        json.dumps({"tickers": [{"ticker": "DDD", "original_member_periods": [["2015-01-02", "2016-01-04"]]}]})
    )
    m14 = tmp_path / "m14.json"
    m14.write_text(json.dumps({"tickers": [{"ticker": "FFF"}]}))
    ov = {
        **w["ov"],
        "R18_INPUT_PATH": r18,
        "R18_INPUT_SHA256": sha(r18.read_bytes()),
        "M14_INPUT_PATH": m14,
        "M14_INPUT_SHA256": sha(m14.read_bytes()),
        "PIN_PIT_MEMBERSHIP_SHA256": H,
        "PIN_LISTING_STATUS_SHA256": H,
    }
    old, new = pair(old_src, tmp_path, ov)
    a, b = run_all(old, tmp_path), run_all(new, tmp_path)
    assert a.keys() == b.keys()
    for k in a:
        if k not in FIXED:
            _eq(a[k], b[k])
    _eq(a["W1"].shift(1).fillna(0.0), b["W1"])  # B1 only moves H1 one session later
    _eq(a["tr"], b["tr"])
    assert (a["W1"].abs().sum(axis=1) > 0).any() and a["pos"] and a["r1"]["n_sessions"] > 0  # paths exercised
    rec = a["universe"][3]
    assert rec["final_list_excluded"] == [{"symbol": "GGG", "reason": "reuse"}] and rec["r18_removed"] == ["DDD"]
    assert rec["m14_gap"][0]["symbol"] == "FFF" and rec["final_list_kept_covered_overlap"] == ["AAA"]
    assert a["pins"] == [("Blocked", "msg"), ("Blocked", "msg")]


def test_cleaned_file_has_no_desk_references():
    # no sha pins, no absolute paths, no ticket ids, no line-number citations
    pat = re.compile(r"\b[0-9a-f]{64}\b|[\"'](?:/[A-Za-z_.-]+){2,}|\b[A-Z]{2,5}-[0-9]{2,}\b|\bL[0-9]{3}\b")
    assert not pat.findall(NEW_SRC)
    assert not pat.findall((qrc.CONFIG_DIR / "statarb_bellwether.toml").read_text())
