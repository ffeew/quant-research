# Research results, 2026-10-30 (Portfolio Construction Quant)

**Generated:** Fri 30 Oct 2026, ~01:35 SGT. Research only: no orders placed, no messages sent. Every number below comes from files in `portfolio/research/out/` and `portfolio/*targets*`, produced by the scripts named.

## 0. Corrections and housekeeping (CIO steering, 01:12–01:15 SGT)

**Slippage retraction.**
- The pilot slippage figures I quoted earlier (+837 / +480 / +246 / −126 bps) are **retracted**. They came from a TCA time-zone bug and were benchmarked against pre-market quotes.
- Corrected figures vs the NBBO mid at submission (the TCA owner, `tca/baseline_report.md` §2): CAT 3.82, GOOGL 1.32, XLE 0.73, LLY 7.63 bps; mean 3.14 bps. MA was 2.20 bps.
- The wrong figures appeared only in my chat report. A grep of every file I own found none.
- Costs now follow `baseline_report.md` §5 (see §1 and §4).

**BAB card.**
- Derivatives researcher overwrote `research/papers/frazzini-pedersen-2014-betting-against-beta.md`. I did **not** edit that file. Per the new desk rule, BAB as a signal is the derivatives researcher's.
- My construction material is now `research/papers/beta-estimation-and-neutralisation.md`, a reference card citing Frazzini–Pedersen 2014 and Novy-Marx–Velikov 2022. It cites the derivatives researcher's replication in `research/replication/frazzini-pedersen-2014-betting-against-beta/` (read only).
- My temporary `…--construction.md` file has been removed.
- My REGISTRY row now points at the new slug. No other owner's row was touched.
- Ownership of the main BAB card is pending the fund manager. Note that no REGISTRY row now references that slug: the derivatives researcher or the fund manager should add one.

**Maya's notes.** `$QR_SCRATCH_DIR/maya-notes/vol-managed-duplicate-draft.md` was read only and treated as data.
- Only items I verified against Moreira–Muir (2017) or Cederburg et al. (2020) were folded into my MM card, cited as "notes from Macro Strategist (Maya)":
  - Table IV turnover, alpha and break-even;
  - Table V weight percentiles;
  - the COWY counts.
- Her "n/a" entries for alpha-after-10bp were filled from the paper.
- Not carried over: unverifiable VIX/regime commentary, Alpaca margin details and the MTUM/QUAL remarks.

**REGISTRY.** My 5 rows are `reference`, last_updated 2026-10-30, with blockers filled. The card status lines match.

## 1. Fallback is SHADOW / DE-RISK ONLY (construct.py v2)

**Implementation.** See FRAMEWORK.md §8; v1 is archived at `archive/construct_v1_2026-10-30.py`.
- `--fallback derisk` is the default.
- `--victor_passed` is empty, since no validator PASS exists as of 2026-10-30.
- The default cost model is `--cost_model tca`:
  - per side = measured pilot half-spread (or bucket default) + 0.75·σ·√(Q/ADV20) + H;
  - ADV is SIP where measured, else IEX × 21.6, the median SIP/IEX ratio over the 5 pilot names;
  - plus 25 bp/yr borrow (a TCA owner assumption).
- Per-side costs for 2026-10-30: min 2.43, median 5.01, max 9.82 bps.

**Tradable book: `targets_2026-10-30.json` (DE-RISK ONLY, tradable).**

| Symbol | Current | Target | Δ | Stop | Stop action |
|---|---|---|---|---|---|
| MA | 15 | 12 | −3 | 616.02 (broker 615.88) | tighten |
| LLY | 7 | 4 | −3 | 1296.85 | keep |
| XLE | 146 | 59 | −87 | 65.62 | keep |
| CAT | −15 | −6 | +9 (cover) | 707.01 | keep |
| GOOGL | −35 | −2 | +33 (cover) | 300.97 | keep |

- Book: gross 21.65%, net 12.63%, beta −0.043 (current −0.246), ex-ante vol 3.24%.
- Turnover $27,284.76. Estimated cost $11.88 under the TCA model, or $27.28 at flat 10 bp.
- Every hard-limit check PASSES. The three de-risk checks (no new names, no increase or flip, stops only tightened) PASS. Beta is INFO.

**Shadow book: `shadow/targets_2026-10-30.json` (SHADOW, NOT FOR TRADING).**
- 16 names, gross 55.54%, net 12.16%, beta −0.0009, vol 5.60%. All checks PASS.

**Sensitivity to the cost model.**
- Under flat 10 bps (the earlier v2 run at 01:12 SGT), the trims were smaller: XLE 146→136, MA 15→14, LLY 7→5, CAT −15→−8, GOOGL −35→−14. That book had gross 34.3% and beta −0.10.
- The lower TCA costs make larger moves toward the shadow book worthwhile.
- The direction of the trims comes from **unvalidated** signals. A stricter "limits-only" de-risk (trim only MA, which sits above the 9.5% buffer) is the conservative alternative. It is not implemented and is the CIO's call.

## 2. Ledoit–Wolf vs HRP: walk-forward head-to-head

**Code:** `research/riskmodels_wf.py` (+ `summarize.py`, `make_tables.py`). Outputs are in `research/out/wf_*.json` and `*_daily.csv`.

**Universe.** A fixed, equity-only universe from data.json:
- Excluded: crypto, cross-asset/benchmark ETFs (SPY, QQQ, IWM, TLT, HYG, GLD, SLV, EEM, EFA, etc.), and sector ETFs (XL*, SMH).
- That leaves 94 single stocks. MMC was dropped for <99% coverage.
- Two data sources:
  1. `data.json` (IEX, about 290 bars, 2025-07..2026-10-28).
  2. The derivatives researcher's `statarb/data/daily_bars.json` (IEX, adjusted, from 2020-07; read only). Same 94 names, so a longer but **survivorship-biased** sample (today's names).

**Methods.**
- (a) **IV:** inverse-vol.
- (b) **MV-S:** long-only min-variance on the sample Σ.
- (c) **MV-LW:** min-variance on Ledoit–Wolf (2004) constant-correlation shrinkage with the optimal intensity δ* = max(0, min(1, κ/T)).
  - This is my own implementation of the paper's formula, following the authors' `covCor.m`. It is **not** sklearn's `LedoitWolf`, which shrinks to a scaled identity.
  - Sanity check: δ* falls as T grows (T=60: 0.132; 250: 0.031; 2,000: 0.004; 20,000: 0.000).
- (d) **HRP:** López de Prado 2016, using correlation distance, single linkage, quasi-diagonalisation and recursive bisection with IVP cluster variance, on the sample Σ.
- Also shown: **MV-CC50**, the fixed δ = 0.5 used in construct.py today.
- All MV variants are long-only, with sum w = 1 and w ≤ 10% (cvxpy/Clarabel).

**Protocol (no look-ahead).**
- Weights are set at close t using returns through t, and held from t+1 with drift.
- Rebalancing is weekly (5d) or monthly (21d).
- Costs are 10 bp × |Δw|, with a TCA §5 per-name variant reported as "Sharpe (TCA cost)". TCA per side is 2.4–9.8 bp, median 4.9 bp. Its impact term uses full-sample median σ/ADV, but impact is <0.1 bp at these sizes, so this is immaterial.
- Each method's risk forecast is sqrt(w'Σ̂w), using its own Σ̂ (sample Σ for IV and HRP).
  - "Real/Fcst" = realised vol / mean forecast vol.
  - "Bias stat" = std(r_t/σ̂_t); 1 = well calibrated, >1 = risk under-forecast.
- Sharpe uses rf = 0, on total returns.
- Bootstrap: stationary (Politis–Romano), mean block 10 days, 2,000 replications, resampled jointly across methods.

**Caveats.**
- data.json gives only 167 OOS days (34 weekly rebalances) after a 120-day lookback. Its Sharpe CIs span about 4.5 units, so treat it as indicative only.
- statarb gives 1,448 OOS days (2021-01..2026-10), which is better, but uses a survivorship-biased universe on the IEX feed.
- Close-to-close fills.
- Neither sample meets the validator's ≥10y PIT bar.

#### A. statarb bars, L120, weekly: N=94, OOS 2021-01-20..2026-10-28 (1448 days, 290 rebalances)

| Method | Ret % | Vol % [95% CI] | Sharpe [95% CI] | MaxDD % | Turnover %/yr | Cost bp/yr (10bp) | Sharpe (TCA cost) | Fcst vol % | Real/Fcst | Bias stat [95% CI] | mean LW δ* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IV | 15.19 | 13.91 [12.29, 15.78] | 1.09 [0.32, 1.89] | -18.75 | 163 | 16.3 | 1.10 | 13.25 | 1.05 | 1.06 [0.95, 1.18] |  |
| MV-S | 11.20 | 11.30 [10.23, 12.54] | 0.99 [0.21, 1.82] | -15.66 | 1382 | 138.2 | 1.05 | 8.80 | 1.28 | 1.33 [1.22, 1.45] |  |
| MV-LW | 9.58 | 11.13 [10.08, 12.30] | 0.86 [0.07, 1.67] | -15.81 | 1152 | 115.2 | 0.91 | 9.44 | 1.18 | 1.20 [1.10, 1.30] | 0.272 |
| MV-CC50 | 9.01 | 11.20 [10.17, 12.37] | 0.81 [0.01, 1.59] | -16.69 | 954 | 95.4 | 0.85 | 9.71 | 1.15 | 1.17 [1.08, 1.27] | 0.500 |
| HRP | 11.64 | 12.48 [11.09, 14.11] | 0.93 [0.16, 1.68] | -15.55 | 1470 | 147.0 | 0.99 | 11.51 | 1.08 | 1.10 [0.99, 1.22] |  |

Differences vs MV-LW (stationary block bootstrap 95% CI; p = share of draws > 0):

- IV − MV-LW: Δvol [2.09, 3.52] pp (p>0 = 1.000); ΔSharpe [-0.28, 0.74] (p>0 = 0.819)
- MV-S − MV-LW: Δvol [0.03, 0.30] pp (p>0 = 0.993); ΔSharpe [-0.03, 0.30] (p>0 = 0.948)
- MV-CC50 − MV-LW: Δvol [-0.02, 0.16] pp (p>0 = 0.944); ΔSharpe [-0.18, 0.06] (p>0 = 0.175)
- HRP − MV-LW: Δvol [0.90, 1.84] pp (p>0 = 1.000); ΔSharpe [-0.29, 0.44] (p>0 = 0.662)

#### B. statarb bars, L120, monthly (21d): N=94, OOS 2021-01-20..2026-10-28 (1448 days, 69 rebalances)

| Method | Ret % | Vol % [95% CI] | Sharpe [95% CI] | MaxDD % | Turnover %/yr | Cost bp/yr (10bp) | Sharpe (TCA cost) | Fcst vol % | Real/Fcst | Bias stat [95% CI] | mean LW δ* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IV | 15.09 | 13.87 [12.26, 15.71] | 1.09 [0.32, 1.88] | -19.02 | 83 | 8.3 | 1.09 | 13.27 | 1.05 | 1.08 [0.95, 1.24] |  |
| MV-S | 12.04 | 11.39 [10.30, 12.66] | 1.06 [0.26, 1.88] | -14.98 | 696 | 69.6 | 1.09 | 8.81 | 1.29 | 1.37 [1.23, 1.52] |  |
| MV-LW | 9.84 | 11.27 [10.18, 12.53] | 0.87 [0.07, 1.70] | -14.98 | 600 | 60.0 | 0.90 | 9.44 | 1.19 | 1.24 [1.12, 1.38] | 0.273 |
| MV-CC50 | 8.83 | 11.34 [10.27, 12.59] | 0.78 [-0.03, 1.59] | -16.70 | 512 | 51.2 | 0.80 | 9.70 | 1.17 | 1.21 [1.10, 1.34] | 0.500 |
| HRP | 12.70 | 12.50 [11.06, 14.18] | 1.02 [0.22, 1.80] | -16.19 | 389 | 38.9 | 1.03 | 11.53 | 1.08 | 1.13 [0.99, 1.28] |  |

Differences vs MV-LW (stationary block bootstrap 95% CI; p = share of draws > 0):

- IV − MV-LW: Δvol [1.95, 3.25] pp (p>0 = 1.000); ΔSharpe [-0.30, 0.73] (p>0 = 0.801)
- MV-S − MV-LW: Δvol [-0.03, 0.26] pp (p>0 = 0.946); ΔSharpe [0.02, 0.35] (p>0 = 0.983)
- MV-CC50 − MV-LW: Δvol [-0.02, 0.16] pp (p>0 = 0.936); ΔSharpe [-0.22, 0.02] (p>0 = 0.060)
- HRP − MV-LW: Δvol [0.77, 1.69] pp (p>0 = 1.000); ΔSharpe [-0.23, 0.52] (p>0 = 0.779)

#### C. statarb bars, L252, monthly: N=94, OOS 2021-07-30..2026-10-28 (1316 days, 63 rebalances)

| Method | Ret % | Vol % [95% CI] | Sharpe [95% CI] | MaxDD % | Turnover %/yr | Cost bp/yr (10bp) | Sharpe (TCA cost) | Fcst vol % | Real/Fcst | Bias stat [95% CI] | mean LW δ* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IV | 14.01 | 13.98 [12.26, 15.97] | 1.00 [0.24, 1.82] | -18.71 | 69 | 6.9 | 1.01 | 13.81 | 1.01 | 1.06 [0.91, 1.23] |  |
| MV-S | 10.75 | 11.22 [10.04, 12.54] | 0.96 [0.12, 1.83] | -14.95 | 391 | 39.1 | 0.98 | 9.76 | 1.15 | 1.21 [1.07, 1.37] |  |
| MV-LW | 9.29 | 11.17 [10.02, 12.44] | 0.83 [0.01, 1.69] | -15.12 | 352 | 35.2 | 0.85 | 10.09 | 1.11 | 1.16 [1.02, 1.31] | 0.175 |
| MV-CC50 | 8.61 | 11.32 [10.21, 12.59] | 0.76 [-0.07, 1.60] | -15.29 | 268 | 26.8 | 0.77 | 10.30 | 1.10 | 1.15 [1.02, 1.29] | 0.500 |
| HRP | 11.64 | 12.47 [11.00, 14.17] | 0.93 [0.15, 1.77] | -15.37 | 338 | 33.8 | 0.95 | 12.11 | 1.03 | 1.08 [0.94, 1.24] |  |

Differences vs MV-LW (stationary block bootstrap 95% CI; p = share of draws > 0):

- IV − MV-LW: Δvol [2.05, 3.57] pp (p>0 = 1.000); ΔSharpe [-0.35, 0.73] (p>0 = 0.733)
- MV-S − MV-LW: Δvol [-0.03, 0.15] pp (p>0 = 0.896); ΔSharpe [0.02, 0.24] (p>0 = 0.991)
- MV-CC50 − MV-LW: Δvol [0.03, 0.27] pp (p>0 = 0.993); ΔSharpe [-0.24, 0.09] (p>0 = 0.177)
- HRP − MV-LW: Δvol [0.82, 1.77] pp (p>0 = 1.000); ΔSharpe [-0.28, 0.50] (p>0 = 0.703)

#### D. data.json, L120, weekly: N=94, OOS 2026-03-03..2026-10-28 (167 days, 34 rebalances)

| Method | Ret % | Vol % [95% CI] | Sharpe [95% CI] | MaxDD % | Turnover %/yr | Cost bp/yr (10bp) | Sharpe (TCA cost) | Fcst vol % | Real/Fcst | Bias stat [95% CI] | mean LW δ* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IV | 13.91 | 9.96 [8.69, 11.14] | 1.40 [-0.74, 3.68] | -6.12 | 186 | 18.6 | 1.41 | 9.88 | 1.01 | 1.02 [0.88, 1.15] |  |
| MV-S | 11.13 | 8.07 [6.69, 9.34] | 1.38 [-0.80, 3.66] | -5.36 | 1393 | 139.3 | 1.48 | 5.98 | 1.35 | 1.34 [1.14, 1.54] |  |
| MV-LW | 11.65 | 7.96 [6.64, 9.20] | 1.46 [-0.73, 3.76] | -5.10 | 1124 | 112.4 | 1.55 | 6.73 | 1.18 | 1.17 [1.00, 1.34] | 0.160 |
| MV-CC50 | 9.91 | 8.55 [7.41, 9.74] | 1.16 [-1.06, 3.55] | -4.73 | 830 | 83.0 | 1.22 | 7.74 | 1.10 | 1.11 [0.96, 1.25] | 0.500 |
| HRP | 6.38 | 9.56 [8.57, 10.48] | 0.67 [-1.48, 2.93] | -5.80 | 1665 | 166.5 | 0.76 | 8.98 | 1.06 | 1.08 [0.96, 1.19] |  |

Differences vs MV-LW (stationary block bootstrap 95% CI; p = share of draws > 0):

- IV − MV-LW: Δvol [0.73, 3.15] pp (p>0 = 1.000); ΔSharpe [-1.62, 1.29] (p>0 = 0.456)
- MV-S − MV-LW: Δvol [-0.09, 0.29] pp (p>0 = 0.863); ΔSharpe [-0.47, 0.37] (p>0 = 0.349)
- MV-CC50 − MV-LW: Δvol [0.25, 0.96] pp (p>0 = 1.000); ΔSharpe [-1.10, 0.40] (p>0 = 0.198)
- HRP − MV-LW: Δvol [0.87, 2.42] pp (p>0 = 1.000); ΔSharpe [-2.26, 0.44] (p>0 = 0.102)

#### E. data.json, L120, monthly: N=94, OOS 2026-03-03..2026-10-28 (167 days, 8 rebalances)

| Method | Ret % | Vol % [95% CI] | Sharpe [95% CI] | MaxDD % | Turnover %/yr | Cost bp/yr (10bp) | Sharpe (TCA cost) | Fcst vol % | Real/Fcst | Bias stat [95% CI] | mean LW δ* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IV | 14.67 | 9.95 [8.67, 11.13] | 1.48 [-0.69, 3.77] | -6.16 | 88 | 8.8 | 1.49 | 9.87 | 1.01 | 1.02 [0.88, 1.16] |  |
| MV-S | 10.96 | 8.26 [6.89, 9.47] | 1.33 [-1.05, 3.85] | -5.59 | 639 | 63.9 | 1.38 | 6.02 | 1.37 | 1.38 [1.15, 1.59] |  |
| MV-LW | 10.49 | 8.11 [6.83, 9.32] | 1.29 [-1.11, 3.82] | -5.13 | 496 | 49.6 | 1.33 | 6.77 | 1.20 | 1.19 [1.02, 1.36] | 0.170 |
| MV-CC50 | 7.96 | 8.70 [7.46, 9.93] | 0.92 [-1.34, 3.31] | -4.74 | 375 | 37.5 | 0.95 | 7.72 | 1.13 | 1.14 [0.97, 1.30] | 0.500 |
| HRP | 8.47 | 9.61 [8.50, 10.64] | 0.88 [-1.28, 3.10] | -5.58 | 385 | 38.5 | 0.91 | 9.10 | 1.06 | 1.07 [0.93, 1.21] |  |

Differences vs MV-LW (stationary block bootstrap 95% CI; p = share of draws > 0):

- IV − MV-LW: Δvol [0.54, 3.01] pp (p>0 = 0.998); ΔSharpe [-1.53, 1.80] (p>0 = 0.575)
- MV-S − MV-LW: Δvol [-0.12, 0.41] pp (p>0 = 0.831); ΔSharpe [-0.37, 0.48] (p>0 = 0.586)
- MV-CC50 − MV-LW: Δvol [0.17, 0.97] pp (p>0 = 0.999); ΔSharpe [-1.07, 0.23] (p>0 = 0.104)
- HRP − MV-LW: Δvol [0.52, 2.51] pp (p>0 = 0.999); ΔSharpe [-1.85, 0.81] (p>0 = 0.247)

#### F. data.json, L60, weekly: N=94, OOS 2025-12-03..2026-10-28 (227 days, 46 rebalances)

| Method | Ret % | Vol % [95% CI] | Sharpe [95% CI] | MaxDD % | Turnover %/yr | Cost bp/yr (10bp) | Sharpe (TCA cost) | Fcst vol % | Real/Fcst | Bias stat [95% CI] | mean LW δ* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IV | 16.79 | 9.70 [8.68, 10.64] | 1.73 [-0.12, 3.54] | -6.90 | 248 | 24.8 | 1.75 | 9.61 | 1.01 | 1.02 [0.91, 1.12] |  |
| MV-S | 14.13 | 8.94 [7.69, 9.96] | 1.58 [-0.44, 3.78] | -8.01 | 2586 | 258.6 | 1.74 | 4.73 | 1.89 | 1.92 [1.65, 2.16] |  |
| MV-LW | 12.75 | 8.44 [7.41, 9.25] | 1.51 [-0.61, 3.78] | -8.00 | 1950 | 195.0 | 1.63 | 6.35 | 1.33 | 1.33 [1.18, 1.45] | 0.270 |
| MV-CC50 | 11.30 | 8.79 [7.86, 9.50] | 1.29 [-0.85, 3.58] | -7.95 | 1565 | 156.5 | 1.38 | 7.17 | 1.23 | 1.24 [1.11, 1.35] | 0.500 |
| HRP | 11.51 | 9.40 [8.53, 10.17] | 1.22 [-0.62, 3.09] | -6.77 | 2210 | 221.0 | 1.35 | 8.39 | 1.12 | 1.14 [1.02, 1.24] |  |

Differences vs MV-LW (stationary block bootstrap 95% CI; p = share of draws > 0):

- IV − MV-LW: Δvol [0.42, 2.10] pp (p>0 = 1.000); ΔSharpe [-1.51, 1.95] (p>0 = 0.595)
- MV-S − MV-LW: Δvol [0.06, 0.93] pp (p>0 = 0.989); ΔSharpe [-0.54, 0.75] (p>0 = 0.582)
- MV-CC50 − MV-LW: Δvol [0.09, 0.63] pp (p>0 = 0.997); ΔSharpe [-0.82, 0.27] (p>0 = 0.185)
- HRP − MV-LW: Δvol [0.30, 1.68] pp (p>0 = 0.997); ΔSharpe [-1.47, 0.91] (p>0 = 0.301)


**Head-to-head findings.**
1. **MV-LW has the lowest realised vol** in every configuration.
   - Its edge over the sample MV is small but consistent: statarb weekly Δvol [0.03, 0.30] pp, p = 0.993.
   - Its edge over fixed δ = 0.5 is larger on data.json and marginal on statarb.
   - LW also cuts turnover vs MV-S by about 10–25%: statarb weekly 1,152% vs 1,382%/yr.
2. **HRP is not lower-risk here.**
   - Its vol is +0.96 to +1.60 pp vs MV-LW (point estimates). Every bootstrap CI excludes 0; the CIs span [0.30, 2.51] pp across configurations.
   - Weekly HRP turnover is the highest of all methods (1,470–1,665%/yr, from single-linkage tree instability). Monthly it falls to 385–389%/yr.
   - HRP's risk forecasts are the best calibrated (bias 1.07–1.14), but that measures the forecast, not the portfolio.
3. **Every MV variant under-forecasts risk:**
   - bias 1.15–1.37 on statarb;
   - bias 1.11–1.92 on data.json (the worst is MV-S at L60).
   - LW narrows the gap but does not close it.
   - Practical point: construct.py's 6% ex-ante vol cap probably delivers about 7%.
4. **Sharpe differences are not statistically significant:**
   - HRP − LW, statarb weekly: ΔSR CI [−0.29, 0.44].
   - The sample-MV vs LW difference is borderline: p>0 of 0.948 weekly and 0.983 monthly on statarb.
   - These are min-variance portfolios with no alpha, so Sharpe is not the objective. Vol and turnover are.
5. **TCA costs vs flat 10 bp** halve the cost drag. No ranking changes.

## 3. Gârleanu–Pedersen partial trading

**construct.py option** (off by default):
- `--gp_ell ℓ` or `--gp_rate τ`, plus `--gp_rho`.
- The scalar Prop. 2 under Λ = λΣ gives the trade rate τ. With ρ = 0: ℓ 0.5 → 0.732, ℓ 2 → 0.5, ℓ 8 → 0.2965.
- The Prop. 4 aim scales signal k by 1/(1 + φ_k·a/γ).
- Research test code is `research/gp_wf.py`; output is in `out/gp_wf.json`.
### GP-A: partial trading on risk portfolios (L120, weekly)

| Data | Method | τ | Turnover x/yr | Cost bp/yr (10bp) | Cost bp/yr (TCA) | Vol % | Sharpe (10bp) | Sharpe (TCA) | TE to target % | OOS |
|---|---|---|---|---|---|---|---|---|---|---|
| statarb | MV-LW | 1.000 | 11.52 | 115.2 | 56.2 | 11.13 | 0.86 | 0.91 | 0.00 | 2021-01-20..2026-10-28 |
| statarb | MV-LW | 0.732 | 8.93 | 89.3 | 43.6 | 11.14 | 0.89 | 0.93 | 0.40 | 2021-01-20..2026-10-28 |
| statarb | MV-LW | 0.500 | 6.96 | 69.6 | 34.0 | 11.14 | 0.91 | 0.94 | 0.78 | 2021-01-20..2026-10-28 |
| statarb | MV-LW | 0.296 | 5.15 | 51.5 | 25.1 | 11.13 | 0.94 | 0.97 | 1.26 | 2021-01-20..2026-10-28 |
| statarb | MV-LW | 0.100 | 2.78 | 27.8 | 13.6 | 11.10 | 1.00 | 1.02 | 2.23 | 2021-01-20..2026-10-28 |
| statarb | HRP | 1.000 | 14.70 | 147.0 | 72.2 | 12.48 | 0.93 | 0.99 | 0.00 | 2021-01-20..2026-10-28 |
| statarb | HRP | 0.732 | 9.80 | 98.0 | 48.1 | 12.47 | 0.98 | 1.02 | 0.28 | 2021-01-20..2026-10-28 |
| statarb | HRP | 0.500 | 6.39 | 63.9 | 31.4 | 12.45 | 1.02 | 1.04 | 0.51 | 2021-01-20..2026-10-28 |
| statarb | HRP | 0.296 | 3.77 | 37.7 | 18.5 | 12.43 | 1.05 | 1.06 | 0.74 | 2021-01-20..2026-10-28 |
| statarb | HRP | 0.100 | 1.41 | 14.1 | 6.9 | 12.38 | 1.08 | 1.09 | 1.12 | 2021-01-20..2026-10-28 |
| datajson | MV-LW | 1.000 | 11.24 | 112.4 | 53.9 | 7.96 | 1.46 | 1.55 | 0.00 | 2026-03-03..2026-10-28 |
| datajson | MV-LW | 0.732 | 8.48 | 84.8 | 40.6 | 8.00 | 1.47 | 1.54 | 0.34 | 2026-03-03..2026-10-28 |
| datajson | MV-LW | 0.500 | 6.47 | 64.7 | 31.0 | 8.06 | 1.46 | 1.51 | 0.75 | 2026-03-03..2026-10-28 |
| datajson | MV-LW | 0.296 | 4.70 | 47.0 | 22.5 | 8.18 | 1.48 | 1.52 | 1.34 | 2026-03-03..2026-10-28 |
| datajson | MV-LW | 0.100 | 2.44 | 24.4 | 11.7 | 8.51 | 1.50 | 1.52 | 2.64 | 2026-03-03..2026-10-28 |
| datajson | HRP | 1.000 | 16.65 | 166.5 | 81.0 | 9.56 | 0.67 | 0.76 | 0.00 | 2026-03-03..2026-10-28 |
| datajson | HRP | 0.732 | 11.08 | 110.8 | 53.9 | 9.55 | 0.78 | 0.84 | 0.42 | 2026-03-03..2026-10-28 |
| datajson | HRP | 0.500 | 7.27 | 72.7 | 35.3 | 9.57 | 0.85 | 0.90 | 0.77 | 2026-03-03..2026-10-28 |
| datajson | HRP | 0.296 | 4.33 | 43.3 | 21.0 | 9.61 | 0.90 | 0.93 | 1.12 | 2026-03-03..2026-10-28 |
| datajson | HRP | 0.100 | 1.64 | 16.4 | 8.0 | 9.63 | 0.94 | 0.96 | 1.72 | 2026-03-03..2026-10-28 |

### GP-B: long/short signal book (MOM_12_1, RS63, TREND, REV5; statarb bars; TCA cost + 25 bp/yr borrow)

| Variant | Turnover x/yr | Cost+borrow bp/yr | Gross ret % | Net ret % | Vol % | Sharpe gross | Sharpe net | MaxDD % | TE to full-rebalance % |
|---|---|---|---|---|---|---|---|---|---|
| full | 13.25 | 72.3 | 0.10 | -0.62 | 5.88 | 0.02 | -0.11 | -9.06 | 0.00 |
| partial tau=0.500 | 6.38 | 38.2 | -0.04 | -0.42 | 5.73 | -0.01 | -0.07 | -8.14 | 0.93 |
| partial tau=0.297 | 4.23 | 27.3 | 0.02 | -0.26 | 5.60 | 0.00 | -0.05 | -7.74 | 1.51 |
| partial tau=0.100 | 1.92 | 15.2 | 0.48 | 0.33 | 5.18 | 0.09 | 0.06 | -7.49 | 2.80 |
| GP ell=0.5 | 7.29 | 42.9 | 0.04 | -0.39 | 5.99 | 0.01 | -0.06 | -8.78 | 0.63 |
| GP ell=2 | 4.62 | 29.7 | 0.00 | -0.29 | 6.05 | 0.00 | -0.05 | -8.82 | 1.04 |
| GP ell=8 | 3.25 | 22.8 | 0.08 | -0.15 | 6.01 | 0.01 | -0.03 | -8.74 | 1.49 |

OOS 2021-10-29..2026-10-28. Mean φ_k (1 − 5-day rank autocorrelation): MOM_12_1 0.031, RS63 0.096, TREND 0.050, REV5 0.992
GP map (ℓ → a/γ, τ): ℓ=0.5: (0.366, 0.7321), ℓ=2: (1.000, 0.5000), ℓ=8: (2.372, 0.2965)

**GP findings.**
1. **Risk portfolios (GP-A).** Partial trading cuts turnover and cost roughly in proportion to τ, at a small tracking-error cost.
   - Example: MV-LW on statarb at τ = 0.5 has turnover 6.96x vs 11.52x/yr, cost 70 vs 115 bp/yr at 10 bp, and TE to target 0.78%/yr.
   - Vol is unchanged (11.14% vs 11.13%), and Sharpe is slightly higher (0.91 vs 0.86 at 10 bp).
   - For HRP the cost saving is larger, because its target is noisier.
   - On data.json the Sharpe changes are within noise.
2. **Signal book (GP-B).** The unvalidated desk-style signal book has about zero gross return over 2021-10..2026-10 (gross Sharpe ≈ 0), so net results are all ≤ ~0. This is a cost and turnover test, **not** alpha evidence.
   - Turnover falls from 13.2x/yr (full) to 4.6x/yr (GP ℓ = 2) and 3.2x/yr (ℓ = 8). Cost plus borrow falls from 72 to 30 and 23 bp/yr.
   - Compared with τ-only partial trading at the same τ, the GP aim (down-weighting fast-decaying REV5, φ ≈ 0.99) gives lower turnover: 4.62x vs 6.38x at τ = 0.5. TE to the no-aim full book is similar (1.04% vs 0.93%).
3. **The beta issue in construct.py on 2026-10-30.**
   - Blending from the current, non-neutral book (β −0.25) leaves the GP shadow book outside the |β| ≤ 0.02 check: β −0.090 (ℓ 0.5), −0.152 (ℓ 2), −0.178 (ℓ 8). The SPY hedge is limited by the gross buffer.
   - GP tradable de-risk files (`research/gp_runs/ell_*`) still pass every hard limit. Their trims are smaller than the default de-risk, e.g. ℓ = 2 gives XLE 146→101 and GOOGL −35→−21.
   - **Fix before enabling GP:** re-project the blended weights onto the beta constraint, or put the |β| constraint on the blended weights inside the optimiser.
4. **Parameters.**
   - ℓ = λ/γ is not yet calibrated. λ needs the TCA owner's per-name costs at our size, and γ the desk's risk aversion.
   - φ_k uses signal autocorrelation as a proxy for alpha decay. Proper IC-decay curves need validator-validated signals.
   - Measured mean φ on statarb: MOM_12_1 0.031, RS63 0.096, TREND 0.050, REV5 0.992. On data.json, at the latest 120 days: MOM 0.018, RS63 0.121, TREND 0.071, REV5 1.0, PEAD 0.362.

## 4. Recommendations

1. **Adopt LW δ\*** in construct.py in place of fixed δ = 0.5, logging δ* each run. Keep MV-LW as the primary risk model.
2. **Do not adopt HRP.** Re-test on ≥10y PIT data from the data owner.
3. **Recalibrate risk forecasts.** Either scale forecasts by the trailing realised/forecast ratio, or set the ex-ante cap to about 5% to deliver about 6%.
4. **Keep GP off** until the beta re-projection is in and ℓ is calibrated. Then a τ of about 0.5 (ℓ ≈ 2) is a reasonable starting point: about 40% less cost for <1% TE on risk books.
5. **Keep the de-risk fallback.** Decide whether de-risk trims follow the shadow book (current) or limits only.
6. **Costs.** Keep the TCA §5 model as default and flat 10 bp as stress. k (0.75 vs 1.0) and live borrow are open. GOOGL and XLE per-side costs are below the validator's 5 bp bar, so validation should still use ≥5 bp.

## 5. Files

**Changed (all mine):**
- `portfolio/construct.py`, `FRAMEWORK.md`, `README.md`
- `targets_2026-10-30.json`, `shadow/targets_2026-10-30.json`
- `research/{riskmodels_wf.py, gp_wf.py, summarize.py, make_tables.py, out/*, gp_runs/*}`
- `archive/*`
- `research/REGISTRY.md` (my 5 rows only)
- my cards: LW, MM, HRP, GP and `beta-estimation-and-neutralisation`

**Read only:**
- `tca/*`
- `statarb/data/daily_bars.json`
- The derivatives researcher's BAB card and replication
- Maya's notes
- `data.json`, `positions.json`, `orders_status.json`, `performance/history.csv`

## Addendum (01:32 SGT): LIMITS.md alignment run (construct.py v0.3)
- **Overlays.** One sleeve vol overlay per LIMITS §5: m = min(1, σ_target/σ̂_126d), with σ_target = the proxy's long-run vol (statarb bars, 2020-07 → 2026-10-28). The planned SPY 20d/120d regime scaler is removed. The 6% ex-ante vol cap is an optimiser constraint only.

| Sleeve | Proxy days | σ̂_126d | σ_target | m |
|---|---|---|---|---|
| momentum (MOM_12_1, RS63) | 1506 | 23.07% | 11.85% | 0.513 |
| trend (TREND) | 1370 | 22.52% | 12.19% | 0.541 |
| reversal (REV5) | 1564 | 16.75% | 10.21% | 0.610 |
| event (PEAD) | 1542 | 14.06% | 9.73% | 0.692 |

  Sanity check: REV5 proxy 126d vol is 0.168 on both statarb and data.json bars. Mean cross-sectional daily return dispersion was 2.14% over the last 126 days, against 1.58% over the full statarb sample. Recent sleeve vol is genuinely elevated, so m < 1 is not a data artefact.
- **Risk state (read 01:24 SGT files).**
  - panic_flag: panic false, multiplier 1.0, as_of 01:23 SGT, 0 sessions old.
  - breaker_state: NORMAL, gross cap 60%, new trades allowed, drawdown 0.0, as_of 01:22 SGT.
  - No fail-safe fired.
- **Primary 2026-10-30 run (flat book per Risk's 01:22 SGT log; positions.json is stale).**
  - Tradable: DE-RISK ONLY, empty; 20/20 PASS.
  - Shadow: 13 names, gross 48.65%, β +0.004, ex-ante vol 5.67%; 17/17 PASS.
- **Scenarios** (`research/runs/`):
  - fail-safe (missing files) and panic + HALVED: shadow gross 23.45% (cap 29%), 78 names under the loser-short ban; all PASS.
  - HALTED with validated signals: forced to de-risk only; all hard checks PASS.
  - stale state (as-of 3 sessions old): fail-safe fired; de-risk β −0.0986 ≥ −0.10.
  - regression (m forced to 1, panic off): identical to the archived v2 on current inputs.
- **Crypto** is ruled out entirely and hard-excluded (compliance row + write guard).

## Addendum 2 (01:35 SGT): LW δ* and risk-forecast inflation (construct.py v0.4, CIO-approved)
- **Covariance.** construct.py now uses the Ledoit–Wolf (2004) optimal constant-correlation δ* (own implementation, same as `lw_cc`). On 2026-10-30, δ* = **0.0858** over 120 days (average correlation 0.087). Fixed 0.5 stays available as `--shrinkage fixed`.
- **Risk inflation k = 1.25** applies only to the ex-ante vol in the 6% cap. Source: the §2 forecast bias of 1.15–1.37 for MV on the derivatives researcher's bars (MV-LW 1.20 [1.10, 1.30]). It does not stack with the sleeve m.
- **Realised vs targeted vol.** MV-LW, 6% cap applied as c = min(1, 6%/(k·σ̂)) with the rest in cash; L120 weekly, 10 bp; stationary bootstrap, block 10, 2,000 reps. Script: `research/volcap_wf.py`; outputs: `research/out/volcap_{statarb,datajson}_L120_w.json`.

| Data | k | Realised vol [95% CI] | Realised / 6% | Mean ex-ante (raw → inflated) | Bias [95% CI] | 63d windows > 6% | Mean scale c |
|---|---|---|---|---|---|---|---|
| The derivatives researcher's statarb bars, 2021-01-20 → 2026-10-28 (1,448 days, 290 rebal.) | 1.00 | 7.19% [6.62, 7.79] | 1.20 | 6.00% → 6.00% | 1.20 [1.10, 1.30] | 73% | 0.69 |
| | **1.25** | **5.75% [5.30, 6.24]** | **0.96** | 4.80% → 6.00% | 1.20 [1.10, 1.30] | 37% | 0.55 |
| data.json, 2026-03-03 → 2026-10-28 (167 days, 34 rebal.) | 1.00 | 7.02% [5.96, 8.03] | 1.17 | 5.97% → 5.97% | 1.17 [1.00, 1.34] | 81% | 0.89 |
| | **1.25** | **5.63% [4.79, 6.44]** | **0.94** | 4.80% → 6.00% | 1.17 [1.00, 1.34] | 40% | 0.72 |
  - Δvol (k=1.25 minus k=1.0): statarb [−1.56, −1.32] pp; data.json [−1.60, −1.16] pp.
  - LW δ* in the walk-forward: statarb mean 0.272 (range 0.090–0.688); data.json mean 0.160 (range 0.090–0.270).
  - Caveats: long-only min-var test book, not the long/short signal book; IEX bars; data.json has only 167 OOS days.
- **2026-10-30 re-run.** positions.json was refreshed at 01:33 SGT to `[]`, so the run uses current positions; equity is $100,024.08 (breaker_state).
  - Tradable: DE-RISK ONLY, empty; 21/21 PASS.
  - Shadow: 12 names, gross 45.14%, β +0.0008, vol 4.59% raw / 5.74% inflated; 18/18 PASS.
  - Regression: fixed 0.5, k = 1, m = 1 reproduces v0.3 exactly.

## Addendum 3 (~01:55 SGT): k re-estimated on ≥10 years of PIT data, L/S shadow construction (v0.5)

> **PROVISIONAL – data defects pending the data owner's fixes.** the validator's 2026-10-30 data_issues.json applies to the store this addendum uses: missing delisting returns, former-member and predecessor history gaps, and SNDK ticker reuse. See Addendum 4 for exposure and a sensitivity check. k stays 1.25.

**Data check (the data owner, `$QR_DATA_DIR/`, read-only):**
- **Span and coverage:** `bars/daily/adjusted/` covers SIP daily bars from **2016-01-04 → 2026-10-28** (10.81 years). There are 774 files for 772 symbols:
  - 503 current S&P 500 members;
  - 220 former members removed since 2016, including delisted names;
  - ETFs.
- **Supporting files:**
  - `total_return/daily_total_return.parquet` (`ret_total_best`);
  - `universe/sp500_membership.parquet` (PIT intervals);
  - `universe/delisting_returns.parquet`: 120 names, 47 with a terminal return.

≥ 10 years with a PIT large-cap universe, so the test was run.

**Method:** `research/ls_volcap_wf.py`.
- Weekly rebalances; 493 of them. OOS runs **2017-01-11 → 2026-10-28** (2,463 days, 9.77 y), after a 252-day warm-up.
- **Universe:** PIT S&P 500 members with 120 complete returns; top 100 by 63d median $ volume, plus SPY.
- **Composite and alpha:**
  - Signals per construct.py, with PIT sleeve m (expanding σ_target).
  - Composite normalised by the unscaled std, α = 0.02·σ₅d·z.
- **Optimiser:** MV with:
  - LW δ\* Σ (mean 0.31);
  - k² inflation in the 6% cap;
  - 9.5% / 0.95%-to-stop / 58%;
  - |β| ≤ 0.01 (Blume, 120d);
  - sector 20% / 10% (current GICS).
- **Costs:** 10 bp, plus 25 bp/yr borrow.
- **Measurement:**
  - Realised returns use daily drift between rebalances.
  - Forecast = raw √(w'Σw) at the rebalance.
  - Bias = std(r/σ̂).
  - CIs: stationary bootstrap, block 10, 2,000 reps.

**Outputs:** `research/out/ls_volcap_sip_N100_w.json` and `ls_volcap_sip_N100_all5_w.json`, each with a `_daily.csv`.

| Signal weights | k | Realised vol [95% CI] | Realised/forecast(raw) [CI] | Bias [95% CI] | 63d windows > 6% | Sharpe | Max DD |
|---|---|---|---|---|---|---|---|
| Live shadow (RS63 0, others 0.25) | 1.00 | 6.79% [6.42, 7.18] | 1.14 [1.07, 1.20] | 1.14 [1.07, 1.21] | 69% | −0.05 | −29.5% |
| | 1.25 | 5.57% [5.26, 5.88] | 1.16 [1.10, 1.23] | 1.16 [1.10, 1.23] | 28% | −0.07 | −26.8% |
| All five 0.2 | 1.00 | 7.10% [6.72, 7.50] | 1.19 [1.12, 1.26] | 1.20 [1.13, 1.27] | 78% | +0.19 | −27.9% |
| | 1.25 | 5.91% [5.58, 6.29] | 1.23 [1.16, 1.31] | 1.23 [1.16, 1.32] | 38% | +0.14 | −23.5% |

**Bias by year (live weights, k = 1 / 1.25):**

| Year | Bias, k = 1 / 1.25 |
|---|---|
| 2017 | 1.01 / 1.02 |
| 2018 | 1.14 / 1.17 |
| 2019 | 0.99 / 1.00 |
| 2020 | 1.50 / 1.47 |
| 2021 | 1.04 / 1.04 |
| 2022 | 1.11 / 1.10 |
| 2023 | 1.10 / 1.13 |
| 2024 | 1.20 / 1.23 |
| 2025 | 1.06 / 1.13 |
| 2026 YTD | 1.18 / 1.22 |

**Conclusion:** the re-estimated k is **1.14–1.23**, with upper 95% bounds of 1.21–1.32. This is consistent with the v0.4 short-sample long-only estimate (1.20 [1.10, 1.30]).
- **k = 1.25 is retained.** It puts realised vol at 5.6–5.9%, under the 6% cap.
- Lowering k to the point estimate of ~1.15 would leave no margin.
- Raising k is not supported on average. The residual risk is regime-specific (2020), and a static k cannot fix it. That is the job of panic and the breakers.

**Survivorship / PIT caveats:**
1. **Membership** is PIT but reconstructed from Wikipedia, not S&P's official record, with 26 anomalies flagged by the data owner.
2. **Survivorship:** only names that were members on or after 2016 are present. Pre-2016 leavers are absent. That does not matter for a universe drawn from members on date t ≥ 2016, but former members' histories end at delisting.
3. **Delistings:** 47 matched terminal returns were applied on the session after the last bar. Unmatched names (null terminal return) got 0% on exit. Held this way: ESRX, APC, CELG, XLNX and TWTR, all acquisitions, weights ≤ 3.6%. Bankruptcies such as SIVB, FRC and SBNY were not held, but a −100% would not be captured if they were.
4. **Sectors:** GICS is **current, not PIT**, and null for former members. Those names are unconstrained by sector caps, which slightly loosens the sector constraint historically.
5. **Prices:** adjusted prices are back-adjusted (not PIT levels). They are used only for ratios and returns. Dollar volume = adjusted C×V.
6. **Not simulated:** panic, breakers, stop-outs, the 1% minimum position, the no-trade band, rounding, per-name TCA costs. Full-day bars are used, not the live partial bar.
7. **Fixed signal weights:** the live-shadow weights apply RS63 = 0 over the whole history. That exclusion was learnt on 2026 data. The all-five run is the no-look-ahead check.
8. **Performance:** the Sharpe and drawdown figures are reported only for context. They are not evidence for any signal.


## Addendum 4 (02:10 SGT): LIMITS alignment (then cited as v0.2; current header v0.3.5) (construct.py v0.6) and the validator's data defects

### A. Data defects: what is affected
Source: `validation/backtests/pead_long_pit/data_issues.json` and `results.md` (the validator; read-only).
- **Affected, now marked PROVISIONAL – data defects pending the data owner's fixes:**
  - the Addendum 3 k re-estimate: `research/ls_volcap_wf.py`, `research/out/ls_volcap_sip_N100_w.json`, `ls_volcap_sip_N100_all5_w.json` and their `_daily.csv`;
  - the v2 re-runs below.
  - This is the only output of mine built on the data owner's SIP/PIT store.
- **Not affected:**
  - today's shadow and tradable books, and their betas, vols, LW Σ and sleeve m / σ_target;
  - the statarb/data.json walk-forwards (§2, Addendum 2, `research/out/volcap_*`, `riskmodels_*`).
  - Reason: they use data.json (Alpaca IEX) or the derivatives researcher's statarb bars. The data.json universe has 120 symbols (117 for statarb). Intersected with the 220 former members, or with SNDK, it is empty. The intersection with the validator's 59 no-bar symbols is {LIN} only, and LIN's defect is in the data owner's store (Praxair history before 2018-10-31), not in data.json.
- The new earnings gate reads the data owner's `data/earnings/` calendar. That is a separate dataset. It uses forward Nasdaq dates for current names and avoids `first_tradable_session` (the validator's DURING_MKT defect). It is listed in `data_provenance`, not marked provisional.

### B. Exposure of the k backtest to the defects, and a sensitivity check (PROVISIONAL)
`research/ls_volcap_wf.py` v2 (the v1 copy is in `archive/`) adds exposure tracking and `--exclude_defects`, which drops the validator's 59 symbols plus SNDK. Re-running without exclusion reproduces Addendum 3 exactly. Logs: `research/out/log_ls_{base,base_x,all5,all5_x}_v2.txt`; JSON: `ls_volcap_sip_N100_*_v2.json`.

| Weights | k | Defects | Realised vol [CI] | Bias [CI] | Mean former / defect names in top-100 | Gross share former / defect | Defect names held |
|---|---|---|---|---|---|---|---|
| Live | 1.25 | included | 5.57% [5.26, 5.88] | 1.16 [1.10, 1.23] | 4.3 / 3.2 | 7.1% / 3.5% | AGN, ATVI, BCR, CXO, ESRX, LIN, PXD, RHT, SNDK, TWTR, XLNX |
| Live | 1.25 | excluded | 5.57% [5.23, 5.94] | 1.16 [1.09, 1.25] | 2.0 / 0 | 4.5% / 0 | none |
| All five | 1.25 | included | 5.91% [5.58, 6.29] | 1.23 [1.16, 1.32] | 4.3 / 3.2 | 7.3% / 3.6% | as above + WCG |
| All five | 1.25 | excluded | 5.89% [5.52, 6.32] | 1.23 [1.15, 1.33] | 2.0 / 0 | 4.6% / 0 | none |
| Live | 1.00 | incl. / excl. | 6.79% / 6.69% | 1.14 / 1.13 | | | |
| All five | 1.00 | incl. / excl. | 7.10% / 7.05% | 1.20 / 1.20 | | | |

- **SNDK was in the backtest book** (ticker-reuse risk). After exclusion, held names without a terminal return are reduced to APC and CELG (0% exit day).
- **Reading:** the bias and the k = 1.25 conclusion do not move when the defect names are dropped. But exclusion is not a fix:
  - it cannot restore missing predecessor history or the 0% delisting exits;
  - it removes names, which is itself a survivorship tilt.
  - So the result stays **PROVISIONAL** until the data owner's fixes, and will be re-run then. **k unchanged at 1.25.**

### C. LIMITS v0.2 changes and the re-run
- Changes: see FRAMEWORK v0.6, §4a.1–4a.3, 4a.7 and 4a.8.
- Re-run 02:08:24 SGT (`run_id 20261030T020824SGT`, log lines 5–6, schema 2):
  - **Shadow:** 12 names, gross 42.89%, net 5.43%, β +0.0022, vol 4.64% raw / 5.79% inflated; 21 PASS, 2 INFO, 0 FAIL. The INFO rows are the unknown-earnings-date shorts LRCX, NFLX, ISRG and CAT, and the T13 alert.
  - **Tradable DE-RISK ONLY:** empty; 25 PASS, 1 INFO (T13), 0 FAIL.
  - Panic is off and PROVISIONAL, so it is not applied. Breaker NORMAL 60%, no fail-safe.
  - m: momentum 0.451, trend 0.464, reversal 0.572, event 0.675.

## Addendum 5 (02:25 SGT): DESK_RULES #5 data sources, store_pit sleeve proxy, shadow v2 (construct.py v0.7)
> **PROVISIONAL: data defects are pending the data owner's fixes.** This applies to the sleeve m / σ_target below (the store_pit proxy).

**Data sources (DESK_RULES #5)**
- History comes only from the data owner's store (v1.1 6e6353ec…, coverage end 2026-10-28), read through `desk_data_client`.
- The live row comes from SIP 5-min bars through the client.
- construct.py no longer reads data.json and makes no direct HTTP calls.
- The research scripts default to the store.
- Every result earlier in this file that is built on statarb or data.json (§2, Addenda 1–2, `volcap_*`, `wf_*`, `gp_wf.json`, `tables.md`) is now marked as a **retired source** in `out/RETIRED_SOURCES.md`. None was re-run on the store in this pass, so those numbers stand only as the audit trail.

**Sleeve m and σ_target, old vs new** (σ_target = expanding median of the 126d proxy vol):

| Sleeve | Old proxy: statarb (02:08), σ̂ / σ_target / m | New proxy: store_pit (02:22), σ̂ / σ_target / m |
|---|---|---|
| momentum | 23.07% / 10.40% / 0.451 | 16.33% / 7.71% / 0.472 |
| trend | 22.52% / 10.46% / 0.464 | 14.86% / 7.47% / 0.503 |
| reversal | 16.75% / 9.58% / 0.572 | 12.86% / 6.33% / 0.492 |
| event | 14.06% / 9.49% / 0.675 | 11.11% / 5.98% / 0.539 |

- Proxy days: 2,521–2,715 (from 2016) vs 1,370–1,564 before.
- The validator's 59 defect symbols (SNDK among them) are excluded, leaving ≈482 PIT members per day on average.
- Source: the `risk_overlays.vol_scaling` fields of `shadow/targets_20261030T020824SGT.json` and `shadow/targets_20261030T022224SGT.json`.

**Signal study on SIP history (same 420-day window as before)**
- MOM_12_1's OOS t moved from −0.87 to −2.62, so the fallback rule gives it weight 0.
- RS63 stays at 0 (OOS t −3.26).
- TREND, REV5 and PEAD each get 1/3.
- No signal passes; this is still a fallback book.

**Shadow v2** (`shadow_fallback_composite_v2`, run 20261030T022224SGT)
- 8 names, gross 35.49%, net 5.87%, β +0.0038, ex-ante vol 4.64% / 5.80% inflated.
- 0 FAIL. The 2 INFO rows are the earnings flags on LRCX and NFLX, and the T13 alert on all sleeves.
- The 02:08 v1 book had 12 names, gross 42.89% and net 5.43%.
