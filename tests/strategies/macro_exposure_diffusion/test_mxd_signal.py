"""Synthetic-data unit tests for mxd_signal.py (no market data, no returns of any strategy)."""

import numpy as np
import pandas as pd

from quant_research.strategies.macro_exposure_diffusion import mxd_signal as M


def synth(seed=0, n=300, extra_cluster=8):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    f = {k: rng.normal(0, 0.01, n) for k in ["SPY", *M.SECT, *M.MAC]}
    R = pd.DataFrame(f, index=idx)
    R.loc[R.index[:100], "XLC"] = np.nan  # XLC < 240 obs -> ineligible
    cols = {}
    for j in range(extra_cluster):  # XLK cluster of 8
        cols[f"K{j}"] = (
            R.SPY + 0.9 * R.XLK + (0.5 * R.TLT if j == 0 else 0) + rng.normal(0, 0.005, n)
        )  # K0 idiosyncratic TLT beta
    for j in range(3):  # XLE cluster of 3 -> fallback
        cols[f"E{j}"] = R.SPY + 0.9 * R.XLE - 0.4 * R.USO + rng.normal(0, 0.005, n)
    S = pd.DataFrame(cols, index=idx)
    return pd.concat([R, S], axis=1)


def test_all():
    R = synth()
    t = R.index[-1]
    stocks = [c for c in R.columns if c[0] in "KE"]
    sec, info = M.assign_sectors(R, t, stocks)
    assert "XLC" not in info["eligible_etfs"]
    assert (sec[[s for s in stocks if s.startswith("K")]] == "XLK").all()
    assert (sec[[s for s in stocks if s.startswith("E")]] == "XLE").all()
    W = R.iloc[-252:]
    S, f = M.loo_sector_regressor(W, sec)
    assert set(f["fallback_spdr"]) == {"E0", "E1", "E2"}
    k = [s for s in stocks if s.startswith("K")]
    exp = W[[x for x in k if x != "K0"]].mean(axis=1)
    assert np.allclose(S["K0"].values, exp.values)  # LOO excludes own return
    assert np.allclose(S["E0"].values, W["XLE"].values)  # fallback = SPDR
    df, info = M.mxd_signal(R, t, stocks)
    assert info["n_signal"] == len(stocks)
    k0 = df.set_index("symbol").loc["K0"]
    assert abs(k0.beta_TLT - 0.5) < 0.1  # recovers planted macro beta
    # no forward data: appending future rows must not change the signal at t
    fut = pd.DataFrame(
        np.random.default_rng(9).normal(0, 0.5, (5, R.shape[1])),
        columns=R.columns,
        index=pd.bdate_range(t + pd.Timedelta(days=1), periods=5),
    )
    df2, _ = M.mxd_signal(pd.concat([R, fut]), t, stocks)
    assert np.allclose(df.mxd.values, df2.mxd.values)
    # tie-break: duplicate ETF column XLF := XLK -> must pick XLK (earlier in SECT order)
    R2 = R.copy()
    R2["XLF"] = R2["XLK"]
    sec2, _ = M.assign_sectors(R2, t, ["K0"])
    assert sec2["K0"] == "XLK"
    d = M.rank_diagnostic(R, t, stocks)
    assert {"rank_loo", "rank_spdr", "rank_change"} <= set(d.columns)
    print("test_mxd_signal: ALL PASS", info)


if __name__ == "__main__":
    test_all()
