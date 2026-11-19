"""TSMOM backtest engine (Moskowitz-Ooi-Pedersen 2012; Hurst-Ooi-Pedersen 2017 variants).

Timing (no look-ahead): signal and vol use data through the close of rebalance day t; trades fill at the
close of t+`lag` sessions (default lag=1, MOC-style); new weights earn returns from the session after the fill.
Weights drift with prices between rebalances. P&L is an EXCESS return over the risk-free rate (positions are
treated as financed / collateralised at RF, as in the paper). Margin interest above RF is NOT modelled.
"""
from __future__ import annotations
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys
from dataclasses import dataclass, field, asdict
import numpy as np
import pandas as pd

sys.path.insert(0, f"{_QR.COSTS_DIR}")
from quant_research.backtest.costs import cost_model as tca  # Tomas's model (v1.1). Equities/ETFs only.

from quant_research.strategies.trend_tsmom.tsmom.data import ASSET_CLASS

ANN = 252



@dataclass
class Config:
    name: str = "baseline"
    lookbacks: tuple = (12,)          # months; signal = mean(sign(excess ret over each lookback))
    rebalance: str = "M"              # "M" month-end, "W" week-end
    vol_com: float = 60.0             # EWMA centre of mass (days), paper = 60
    asset_vol_target: float = 0.40    # per-asset ex-ante vol (paper = 40%)
    sizing: str = "pvt"               # "pvt": scale book to port_vol_target; "mop": equal-weight 40%-vol positions / N
    port_vol_target: float = 0.10
    cov_window: int = 252             # sessions for portfolio covariance (pvt)
    class_balanced: bool = False      # equal risk budget per asset class instead of per instrument
    gross_cap: float | None = None    # e.g. 2.0 for Reg-T-ish feasibility
    honour_shortable: bool = False    # long/flat for ETFs not shortable+ETB in today's Alpaca snapshot
    lag: int = 1
    nav_usd: float = 1_000_000.0      # book size for cost model (impact/fees)
    cost_mult: float = 1.0
    venue: str = "continuous"
    impact_k: float = 1.0
    borrow_rate: float = tca.BORROW_RATE_ETB_DEFAULT
    long_only_benchmark: bool = False # signal forced to +1 (vol-scaled long-only benchmark)


def _rebalance_dates(idx: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    s = pd.Series(idx, index=idx)
    key = idx.to_period("M") if freq == "M" else idx.to_period("W-FRI")
    return pd.DatetimeIndex(s.groupby(key).max().values)


def run(panel: dict, symbols: list[str], cfg: Config, shortable: dict | None = None) -> dict:
    syms = [s for s in symbols if s in panel["px"].columns]
    P = panel["px"][syms]
    C = panel["close_raw"][syms]
    V = panel["volume_raw"][syms]
    rf = panel["rf"]
    idx = P.index
    R = P.pct_change(fill_method=None)                      # total (or price) return
    RX = R.sub(rf, axis=0)                                  # excess return
    # ex-ante vol (annualised) known at close t
    vol = np.sqrt(RX.ewm(com=cfg.vol_com, min_periods=60).var() * ANN)
    # lagged liquidity inputs for the cost model
    adv_sh = V.rolling(20, min_periods=10).mean()
    sig_d = R.rolling(20, min_periods=10).std()
    logx = np.log1p(RX.fillna(0.0)).where(RX.notna())
    cumx = logx.cumsum()
    n_valid = RX.notna().cumsum()

    rdates = _rebalance_dates(idx, cfg.rebalance)
    pos = {d: i for i, d in enumerate(idx)}
    max_lb = max(cfg.lookbacks) * 21

    def target_weights(t: pd.Timestamp) -> pd.Series:
        i = pos[t]
        sig = pd.Series(0.0, index=syms)
        ok = (n_valid.iloc[i] > max_lb) & vol.iloc[i].notna() & RX.iloc[i].notna()
        for lb in cfg.lookbacks:
            h = lb * 21
            if i - h < 0:
                return pd.Series(0.0, index=syms)
            sig += np.sign(cumx.iloc[i] - cumx.iloc[i - h]).fillna(0.0)
        sig /= len(cfg.lookbacks)
        if cfg.long_only_benchmark:
            sig[:] = 1.0
        for s in syms:  # long/flat constraint for ETFs not shortable/ETB (optional)
            if (cfg.honour_shortable and shortable is not None and not shortable.get(s, False)):
                sig[s] = max(sig[s], 0.0)
        sig = sig.where(ok, 0.0)
        live = ok[ok].index
        if len(live) == 0:
            return pd.Series(0.0, index=syms)
        raw = sig * cfg.asset_vol_target / vol.iloc[i]
        raw = raw.where(ok, 0.0).fillna(0.0)
        if cfg.class_balanced:
            cls = pd.Series({s: ASSET_CLASS.get(s, "other") for s in live})
            n_cls = cls.nunique()
            scale = cls.map(lambda c: 1.0 / (n_cls * (cls == c).sum()))
            w = raw * scale.reindex(syms).fillna(0.0)
        else:
            w = raw / len(live)
        if cfg.sizing == "pvt":
            win = RX.iloc[max(0, i - cfg.cov_window + 1): i + 1][list(live)]
            cov = win.cov(min_periods=60).fillna(0.0).values * ANN
            wl = w[list(live)].values
            pv = float(np.sqrt(max(wl @ cov @ wl, 0.0)))
            if pv > 0:
                w = w * (cfg.port_vol_target / pv)
        if cfg.gross_cap is not None:
            g = w.abs().sum()
            if g > cfg.gross_cap:
                w = w * (cfg.gross_cap / g)
        return w

    # pending trades: fill date -> target
    fills = {}
    for t in rdates:
        i = pos[t]
        j = i + cfg.lag
        if j < len(idx):
            fills[idx[j]] = target_weights(t)

    n = len(idx)
    W = np.zeros((n, len(syms)))     # weights held at close of day (after any fill)
    pnl = np.zeros(n); cost = np.zeros(n); borrow = np.zeros(n); turn = np.zeros(n)
    contrib = np.zeros((n, len(syms))); costa = np.zeros((n, len(syms))); turna = np.zeros((n, len(syms)))
    buckets = {}
    w = np.zeros(len(syms))
    Rv = R.fillna(0.0).values; RXv = RX.fillna(0.0).values; rfv = rf.fillna(0.0).values
    Cv = C.values; ADVv = adv_sh.shift(1).values; SIGv = sig_d.shift(1).values
    
    for k in range(n):
        if k > 0:
            c = w * RXv[k]
            contrib[k] = c
            rp = c.sum()
            pnl[k] = rp
            # borrow on shorts held overnight (calendar days, 360 basis)
            days = (idx[k] - idx[k - 1]).days
            short_mv = -w[w < 0].sum()
            borrow[k] = short_mv * cfg.borrow_rate * days / 360.0
            # drift: notional grows with total return, NAV with rf + excess pnl
            w = w * (1 + Rv[k]) / (1 + rfv[k] + rp)
        t = idx[k]
        if t in fills:
            tgt = fills[t].values
            dw = tgt - w
            cst = 0.0
            for a in np.nonzero(np.abs(dw) > 1e-10)[0]:
                notional = abs(dw[a]) * cfg.nav_usd
                if True:
                    price = Cv[k, a]
                    if not np.isfinite(price) or price <= 0:
                        continue
                    adv = ADVv[k, a] if np.isfinite(ADVv[k, a]) and ADVv[k, a] > 0 else None
                    sd = SIGv[k, a] if np.isfinite(SIGv[k, a]) else None
                    side = "buy" if dw[a] > 0 else "sell"
                    tc = tca.trade_cost(side, price, notional / price, adv, sd, None, k=cfg.impact_k,
                                        venue=cfg.venue, trade_date=t.date())
                    bps = tc["total_bps"]
                    buckets.setdefault(syms[a], []).append(tc["bucket"])
                cst += abs(dw[a]) * bps / 1e4
                costa[k, a] = abs(dw[a]) * bps / 1e4 * cfg.cost_mult
                turna[k, a] = abs(dw[a])
            cost[k] = cst * cfg.cost_mult
            turn[k] = np.abs(dw).sum()
            w = tgt.copy()
        W[k] = w
    out = pd.DataFrame({"gross": pnl, "cost": cost, "borrow": borrow, "turnover": turn}, index=idx)
    out["net"] = out["gross"] - out["cost"] - out["borrow"]
    out["gross_lev"] = np.abs(W).sum(1)
    out["net_lev"] = W.sum(1)
    first = next((d for d in sorted(fills) if np.abs(fills[d].values).sum() > 0), None)
    out = out.loc[first:] if first is not None else out.iloc[0:0]
    return {"daily": out, "weights": pd.DataFrame(W, index=idx, columns=syms).loc[out.index],
            "contrib": pd.DataFrame(contrib, index=idx, columns=syms).loc[out.index],
            "cost_by_asset": pd.DataFrame(costa, index=idx, columns=syms).loc[out.index],
            "turn_by_asset": pd.DataFrame(turna, index=idx, columns=syms).loc[out.index],
            "buckets": {k: max(set(v), key=v.count) for k, v in buckets.items()},
            "cfg": asdict(cfg), "symbols": syms}
