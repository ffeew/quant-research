"""Data-defect sensitivity helpers (see $QR_DESK_DIR/validation/backtests/pead_long_pit/data_issues.json, read-only).
flagged_symbols(): tickers with reuse / re-add / membership anomalies, or incomplete bar history while a PIT member.
delisting_events(): last session + terminal return per former member, with the -30% stress for non-merger delistings."""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import json
import numpy as np
import pandas as pd
from .data import CIO

ISSUES = f"{_QR.DESK_DIR}/validation/backtests/pead_long_pit/data_issues.json"


def flagged_symbols(panel_close, member_pit, gap_sessions=1):
    """Returns dict of sets. member_pit = membership BEFORE '& close.notna()'."""
    mem = pd.read_parquet(CIO / "universe/sp500_membership.parquet")
    cnt = mem.symbol.value_counts()
    reuse = set(cnt[cnt > 1].index)                                   # re-added or reused tickers (incl. SNDK)
    an = pd.read_parquet(CIO / "universe/sp500_membership_anomalies.parquet")
    reuse |= set(an.loc[pd.to_datetime(an.effective_date) >= "2015-01-01", "symbol"])
    reuse |= {"SNDK", "POM", "SPLS", "NFX", "APC", "CA", "CSRA", "DNB", "TE"}  # SNDK + DE-fixed reuse list (STATUS.md)
    iss = json.load(open(ISSUES))
    nobars_issue = set(iss["members_without_bars_symbols"])
    mp = member_pit.reindex(columns=panel_close.columns, fill_value=False)
    missing = (mp & panel_close.isna()).sum()
    nobars_ours = set(missing[missing >= gap_sessions].index)
    return {"reuse_or_readd": reuse, "missing_bars_issue_list": nobars_issue, "missing_bars_while_member": nobars_ours,
            "all": reuse | nobars_issue | nobars_ours}


def delisting_events(stress=-0.30):
    d = pd.read_parquet(CIO / "universe/delisting_returns.parquet")
    d["last_session"] = pd.to_datetime(d.last_session)
    merger = d.reason.ne("no_deal_in_alpaca_CA")
    d["ret_used"] = np.where(merger, d.terminal_return.fillna(0.0), stress)
    d["kind"] = np.where(merger, "merger(terminal_return or 0)", f"non-merger stress {stress:+.0%}")
    return d[["symbol", "last_session", "reason", "terminal_return", "ret_used", "kind"]]


def apply_delisting(fwd, exec_, events):
    """Positions held over a delisting: open_t1 earns open(t+1)->open(t+2); if t+1 is the last session the return was
    NaN (=flat at last price). Replace it with ret_used. Same for close_t1 (close(t+1) = last close)."""
    f = fwd.copy(); hits = []
    idx = f.index
    for _, e in events.iterrows():
        if e.symbol not in f.columns or e.last_session not in idx:
            continue
        i = idx.get_loc(e.last_session)
        if i - 1 >= 0:
            f.iloc[i - 1, f.columns.get_loc(e.symbol)] = e.ret_used
            hits.append((e.symbol, idx[i - 1], e.ret_used))
    return f, hits


def end_of_data_holdings(W, panel_close, window=0):
    """Count names with a non-zero weight AFTER their last bar (zombie positions after delisting)."""
    out = []
    for s in W.columns:
        if s not in panel_close:
            continue
        lv = panel_close[s].last_valid_index()
        if lv is None or lv == panel_close.index[-1]:
            continue
        after = W[s].loc[lv:].iloc[2:]
        if after.abs().gt(1e-9).any():
            out.append({"symbol": s, "last_bar": str(lv.date()), "days_held_after": int(after.abs().gt(1e-9).sum())})
    return out


def straddle_audit(W, panel_close, flagged, trades=None, window=10):
    """Any non-zero target weight within `window` sessions on either side of a bar gap / membership boundary for
    flagged names, and any pair trade whose [entry, exit] spans a bar gap of the leg."""
    out = []
    for s in sorted(set(flagged) & set(W.columns)):
        c = panel_close[s]; v = c.notna().values
        # boundaries: transitions valid<->NaN inside the sample
        idx = np.where(v)[0]
        if len(idx) < 2:
            continue
        # internal gaps only (data stops and later RESUMES under the same ticker) = where a reuse could hide
        gaps = [(idx[i], idx[i + 1]) for i in range(len(idx) - 1) if idx[i + 1] - idx[i] > 1]
        for a, b in gaps:
            pre = W[s].iloc[max(0, a - window):a + 1].abs().gt(1e-9).any()
            post = W[s].iloc[b:b + window + 1].abs().gt(1e-9).any()
            held_through = W[s].iloc[a:b].abs().gt(1e-9).any()
            if (pre and post) or held_through:
                out.append({"symbol": s, "gap": f"{c.index[a].date()}..{c.index[b].date()}", "gap_sessions": int(b - a - 1),
                            "type": "position held across / on both sides of an internal bar gap"})
    if trades is not None and len(trades):
        for _, t in trades.iterrows():
            for leg in (t.y, t.x):
                seg = panel_close[leg].loc[t.entry:t.exit]
                if seg.isna().any():
                    out.append({"symbol": leg, "boundary": str(seg[seg.isna()].index[0].date()), "type": "pair trade spans bar gap"})
    return out
