# Signal-combination & portfolio-construction framework (DRAFT v0.7.1)

- **Owner:** Portfolio Construction Quant (combine stage of the SPRINT pipeline)
- **Drafted:** Fri 30 Oct 2026, 01:10 SGT. **v0.2:** ~01:35 SGT, after follow-up. The fallback is now shadow / de-risk only (confirmed and implemented). Also new: the TCA §5 cost model, the GP option, and LW-vs-HRP results. **v0.3:** ~01:30 SGT, aligned with `risk/LIMITS.md` §1, §3 and §5 (see §4a): one sleeve-level vol overlay, Risk's panic flag and drawdown breakers read from `risk/state/` with fail-safe defaults, new compliance rows, and crypto ruled out entirely (hard exclusion). **v0.4:** 01:35 SGT. Covariance now uses the Ledoit–Wolf (2004) optimal δ* (fixed 0.5 kept as an option), and the 6% vol cap uses a risk-forecast inflation factor k = 1.25 (§3). HRP and GP partial trading stay off. **v0.5:** 01:43 SGT. The shadow book has a stable ID `shadow_fallback_composite_v1` (§8a). Every run writes new timestamped files that are never overwritten, plus an append-only JSONL run log (§8b). k was re-estimated on the store's 10.8-year PIT S&P 500 SIP data, using the L/S shadow construction: bias 1.14–1.23, so k = 1.25 is kept (§3). **v0.6:** 02:08 SGT, aligned with `risk/LIMITS.md` (LIMITS header then **v0.3.5**; current header **v0.3.7** as of this verification). Changes:
  - **Earnings (H7):** shorts are never held through their own release. The rule uses the data owner's earnings calendar (`data/earnings/`). An unknown next date blocks new or larger shorts in the tradable book and is flagged in the shadow book (§4a.7).
  - **σ_target (§5 T12):** the expanding median of the 126d proxy vol once ≥3 years of history exist (§4a.1).
  - **Provisional panic flag:** context only, not applied. The fail-safe is kept (§4a.2).
  - **Breaker:** new RESUMED_DISARMED state, with `backstop_equity` logged. An unknown state goes to HALVED (§4a.3).
  - **Crypto:** no caps remain (§4a.6).
  - **The validator's data defects:** every result built on the data owner's SIP/PIT store is marked **PROVISIONAL – data defects pending the data owner's fixes**. Today's books are not affected (§4a.8). k stays 1.25.
  - **Run log:** schema v2.
- **v0.7:** 02:22 SGT, after the 02:12 and 02:13 risk decisions. Changes:
  - **Data-provenance rule (§4a.9):** all history now comes from the shared store, and live Alpaca market data only through `data/lib/desk_data_client.py`. data.json and direct HTTP are gone from construct.py and from every research script.
  - **Sleeve proxy:** now a PIT S&P 500 proxy on the store (`--proxy_src store_pit`). The validator's 59 defect names (incl. SNDK) are excluded, and the proxy is **PROVISIONAL** until the data owner's fixes land. The derivatives researcher's deprecated file is used by the tests only (audit copy). Old vs new m / σ_target are in §4a.9.
  - **Shadow v2:** the shadow book is now `shadow_fallback_composite_v2` (§8a). Every new log line carries `method_version`. Log schema 3 adds correction records (§8b).
  - **LIMITS v0.3.5 T4:** construction reads Risk's current *episode* backstop from `breaker_state.json` and never infers a lift (§4a.3). Discrepancies are listed in §4a.3.
  - **Unchanged per Risk's decisions:** the strict earnings gate (no estimated dates); and the provisional panic flag stays non-applied, with the ×0.5 fail-safe on a missing or stale file.
- **v0.7.1 verification (2026-11-06 ~06:05 SGT):** after the risk manager's post-outage risk-state refresh. Confirmed FINAL panic is binding; provisional remains context-only; `momentum_short_notional_multiplier` / `new_loser_shorts_allowed` / `net_beta_floor` honored from the file (null floor with panic off is valid). LIMITS references updated to **v0.3.7**. No construction-rule gaps found in v0.3.6–v0.3.7 beyond fields already wired. Default `--asof_bar_cutoff` now derives from `--now` (ET session; prior session if before 09:30 ET) instead of the hardcoded 2026-10-29.
- **Applies to:** `$QR_DESK_DIR/portfolio/construct.py` (v0.7; the pre-rule-5 v0.6 file is archived at `archive/construct_v6_pre-rule5_2026-10-30.py`)
- **Research results:** `research/RESULTS_2026-10-30.md`
- **Evidence:** cards in `$QR_DESK_DIR/research/papers/` for:
  - `ledoit-wolf-2004-covariance-shrinkage`
  - `moreira-muir-2017-volatility-managed-portfolios`
  - `lopez-de-prado-2016-hierarchical-risk-parity`
  - `garleanu-pedersen-2013-dynamic-trading-tcosts`
  - `beta-estimation-and-neutralisation` (my reference card on beta estimation and neutralisation; it cites Frazzini–Pedersen 2014 and Novy-Marx–Velikov 2022). BAB as a signal is the derivatives researcher's card. I have not edited it.
- **Risk limits:** `risk/LIMITS.md` **v0.3.7** (read-only; header parsed at run time by `limits_version`). State files: `risk/state/panic_flag.json`, `risk/state/breaker_state.json` (read-only).
- **Validation standard:** the validation pass bar (a recorded PASS or CONDITIONAL PASS verdict).

## 0. Desk constraints (hard; from risk/ and the project brief)
- About $100k Alpaca **paper** equity (99,997.56 in performance/history.csv on 2026-10-30).
- Long/short US-listed equities and ETFs only: no options, no leverage. **Crypto is ruled out entirely** (CIO, 2026-10-30): hard exclusion in code, see §4a.6.
- Limits:
  - max 10% equity per position
  - max 1% equity at risk per trade (entry-to-stop)
  - max 60% gross
- Stops on every position.
- Drawdown breakers (LIMITS H8/H9): 5% drawdown → gross cap 30%; 8% → no new trades (exits, trims, stop tightening only).
- About 290 daily bars of history in data.json. That is too short for the validator's ≥10-year requirement, so any signal must be validated on the data owner's longer data, not on data.json.

## 1. Admission gate: what may enter the combiner
A signal reaches `construct.py`'s alpha only if it passes **both** stages below.

**Stage A: validation (hard gate).** A recorded verdict of **PASS** or **CONDITIONAL PASS**. The bar:
- a reproducible rule
- point-in-time data and a survivorship-free universe
- realistic costs: ≥5 bps per side plus borrow, next-open fills
- ≥100 OOS trades, or a justified lower bar
- walk-forward OOS Sharpe > 0 after costs
- deflated Sharpe probability > 0.95 counting **every variant tried**
- stability across regimes
- economic intuition

A CONDITIONAL PASS enters with its conditions copied into the targets file. For example, a CONDITIONAL PASS with a size cap is honoured as a per-signal risk-budget cap.

**Stage B: live combine check (Portfolio Construction; soft gate).** Computed on the desk's own recent cross-section:
- rank IC on non-overlapping 5-day windows, 60% in-sample / 40% OOS
- the signal keeps its IC weight only if OOS IC > 0 and t ≥ 1 (current code)
- a signal with OOS t ≤ −2 is muted (weight 0) even if validator passed it, and the conflict is reported to the validator

Stage B can only **down-weight** a passed signal. It can never admit a signal the validator has not passed.

**Status on 2026-10-30:**
- Validation FAILED all 5 current trades for insufficient evidence (2026-10-30 01:00).
- No research signal has a PASS yet.
- ⇒ **zero admitted signals** ⇒ §8 fallback applies.

**Implementation (v2):** Stage A is an explicit input, `--validator_passed SIG1,SIG2`, with default empty, i.e. none passed as of 2026-10-30. A signal is validated only if it is in that list **and** passes Stage B. To do: parse the recorded verdicts directly.

## 2. Combination: IC-weighted, shrunk toward equal weight, with a correlation adjustment
For admitted signals k = 1..K, each a cross-sectional z-score winsorised at ±3:

1. **IC shrinkage toward 0:** IC_shr,k = IC_OOS,k · n_k/(n_k + n0), with n0 = 20 windows.
2. **Correlation adjustment:** C_shr = ½·corr(signal z-scores) + ½·I. Raw weights are w_IC ∝ C_shr⁻¹ · IC_shr, so correlated signals share a budget instead of double-counting. This is the multi-signal analogue of the IR ≈ IC·√breadth reasoning used in Ledoit–Wolf's Appendix C.
3. **Shrinkage toward equal weight (correlation-adjusted):** w = ½·w_IC + ½·w_EQ, with w_EQ ∝ C_shr⁻¹·1, both normalised to unit composite variance.
4. **Composite IC:** IC_c = sqrt(IC_shrᵀ C_shr⁻¹ IC_shr), floored at 0.02 in fallback.
5. **Alpha per name:** α_i = IC_c · σ_i · score_i, Grinold's "alpha = volatility × IC × score" (*JPM* 1994, [doi:10.3905/jpm.1994.409482](https://doi.org/10.3905/jpm.1994.409482); citation verified, text not read).

**To do:** replace in-sample/OOS IC from data.json with the validator's walk-forward IC and decay profile once a signal passes. Add a per-signal risk-budget cap of 40% of composite variance so no single signal dominates (many small edges).

## 3. Covariance
- **Current (v0.4):**
  - 120-day daily returns; Σ = δF + (1−δ)S, with F the constant-correlation target.
  - **δ = Ledoit–Wolf (2004) optimal intensity δ\* = max(0, min(1, κ̂/T))**, κ̂ = (π̂ − ρ̂)/γ̂. This is my own implementation of the paper's Appendix B / Ledoit's covCor.m, the same code as research `lw_cc`; it is not sklearn's identity target.
  - δ\* is logged in every targets file. On 2026-10-30, **δ\* = 0.0858** (average correlation 0.087, 120d).
  - The v2 fixed-δ model is still available: `--shrinkage fixed --shrink_delta 0.5`.
- **Risk-forecast inflation (v0.4):**
  - The 6% book vol cap is applied to k·√(w'Σw), i.e. Σ_cap = k²·Σ·252, with **k = `--risk_inflation` = 1.25** by default.
  - Source: my walk-forward forecast bias of 1.15–1.37 for the MV models on the legacy statarb bars (MV-LW 1.20, CI [1.10, 1.30]). See RESULTS §2 and the addendum.
  - k applies **only** inside the vol-cap constraint. It is not used for alpha, the risk-aversion term or the reported raw vol.
  - It recalibrates the forecast and is **not** a vol-scaling overlay. It does not stack with the per-sleeve m (§4a.1), which is a separate time-series overlay on alpha and remains the single vol overlay.
  - It is logged as `risk_overlays.risk_inflation` and `assumptions.risk_inflation`, and checked in the compliance row "Book ex-ante vol cap (inflated)".
- **Walk-forward check of the cap** (MV-LW, long-only min-var scaled by c = min(1, 6%/(k·σ̂)) with the rest in cash; L120 weekly, 10 bp; stationary bootstrap, block 10, 2,000 reps; `research/volcap_wf.py`):

| Data | k | Realised vol [95% CI] | Realised / 6% | Mean ex-ante (raw → inflated) | Bias [95% CI] | 63d windows > 6% | Mean scale c |
|---|---|---|---|---|---|---|---|
| The derivatives researcher's statarb bars, 2021-01-20 → 2026-10-28 (1,448 days, 290 rebal.) | 1.00 | 7.19% [6.62, 7.79] | 1.20 | 6.00% → 6.00% | 1.20 [1.10, 1.30] | 73% | 0.69 |
| | **1.25** | **5.75% [5.30, 6.24]** | **0.96** | 4.80% → 6.00% | 1.20 [1.10, 1.30] | 37% | 0.55 |
| data.json, 2026-03-03 → 2026-10-28 (167 days, 34 rebal.) | 1.00 | 7.02% [5.96, 8.03] | 1.17 | 5.97% → 5.97% | 1.17 [1.00, 1.34] | 81% | 0.89 |
| | **1.25** | **5.63% [4.79, 6.44]** | **0.94** | 4.80% → 6.00% | 1.17 [1.00, 1.34] | 40% | 0.72 |

  With k = 1.25, realised vol lands at 5.6–5.8%, and 6% is inside the CI on both data sets. With k = 1.0 it overshoots by 17–20%, and 6% is outside the CI on statarb. The k=1.25 minus k=1.0 Δvol CI is [−1.56, −1.32] pp on statarb and [−1.60, −1.16] pp on data.json.
- **v0.5 re-estimate of k on ≥10 years of PIT data, L/S shadow construction** (`research/ls_volcap_wf.py`; RESULTS Addendum 3). **PROVISIONAL – data defects pending the data owner's fixes.**
  - The validator's `validation/backtests/pead_long_pit/data_issues.json` (2026-10-30) affects this result:
    - missing delisting returns (70 of 120 unmatched → 0% exit);
    - missing history for former members and predecessors (59 symbols with member-days but no bars);
    - SNDK ticker reuse.
  - How exposed the backtest is (RESULTS Addendum 4):
    - on average 4.3 of the 100-name universe are former members and 3.2 are defect-list symbols;
    - former members carry 7.1–9.2% of gross, defect-list symbols 3.5–4.4%;
    - defect names held: AGN, ATVI, BCR, CXO, ESRX, LIN, PXD, RHT, SNDK, TWTR, XLNX (+WCG in the all-five variant). **SNDK was in the book.**
  - **Sensitivity with every defect-list symbol plus SNDK excluded:** at k = 1.25, live-weights bias is 1.16 [1.09, 1.25] with realised vol 5.57% (vs 1.16 [1.10, 1.23] / 5.57%); all-five bias is 1.23 [1.15, 1.33] with 5.89% (vs 1.23 / 5.91%).
  - So the k conclusion does not move. But excluding names cannot repair the 0% delisting exits or the missing predecessor histories, so the result stays provisional until the data fixes land. **k is unchanged at 1.25**. Its primary evidence, the walk-forward on the legacy statarb bars and data.json, does not use the store.
  - **Data:** the data owner's SIP bars, 2016-01-04 → 2026-10-28 (10.81 y). OOS 2017-01-11 → 2026-10-28 (2,463 days, 9.77 y, 493 weekly rebalances).
  - **Universe:** at each rebalance, PIT S&P 500 members with 120 complete returns; top 100 by 63d median $ volume, plus SPY as the hedge.
  - **Book:** the shadow method. Composite with PIT sleeve m (expanding σ_target), α = 0.02·σ₅d·z, and an MV optimiser with:
    - LW δ\* Σ (mean δ\* 0.31, range 0.08–1.00; mean average correlation 0.28);
    - k²-inflated 6% cap;
    - 9.5% / 0.95%-to-stop / 58% gross, |β| ≤ 0.01, sector 20% / 10% on current GICS;
    - 10 bp costs and 25 bp/yr borrow.
  - **Bias statistic (PROVISIONAL – data defects pending the data owner's fixes):** std(r_t / σ̂_t), with σ̂ the raw daily ex-ante forecast at the rebalance. CIs from a stationary bootstrap, block 10, 2,000 reps.

*Table below: PROVISIONAL – data defects pending the data owner's fixes.*

| Signal weights | k | Realised vol [95% CI] | Realised / 6% | Mean ex-ante raw → inflated | Bias [95% CI] | 63d windows > 6% | Cap binding |
|---|---|---|---|---|---|---|---|
| Live shadow (RS63 = 0, others 0.25) | 1.00 | 6.79% [6.42, 7.18] | 1.13 | 5.98% → 5.98% | 1.14 [1.07, 1.21] | 69% | 96% |
| | **1.25** | **5.57% [5.26, 5.88]** | **0.93** | 4.80% → 6.00% | 1.16 [1.10, 1.23] | 28% | 100% |
| All five at 0.2 (sensitivity) | 1.00 | 7.10% [6.72, 7.50] | 1.18 | 5.98% → 5.98% | 1.20 [1.13, 1.27] | 78% | 96% |
| | **1.25** | **5.91% [5.58, 6.29]** | **0.99** | 4.80% → 6.00% | 1.23 [1.16, 1.32] | 38% | 99% |

  - **Conclusion:** the long-horizon L/S bias of 1.14–1.23 matches the short-sample long-only estimate (MV-LW 1.20 [1.10, 1.30]), so **k = 1.25 is kept**.
    - At k = 1.25, realised vol is 5.6–5.9%. The CI excludes 6% for the live weights and includes it for the all-five variant.
    - k = 1.0 overshoots by 13–18%, and its CIs exclude 6%.
    - k = 1.15 (the point estimate) would put realised vol at ≈6% with no margin. The upper CI bounds are 1.21–1.32.
  - **Risk-level caveat:** the bias is strongly regime-dependent. By year it was 2017 1.01–1.07, 2019 0.99–1.07, 2020 1.47–1.61 and 2024 1.20–1.32. A static k does not protect against a 2020-type quarter: 28–38% of 63-day windows were still above 6% at k = 1.25. That job falls to the panic flag and breakers, which are not simulated here.
  - **Survivorship / PIT caveats** (details in RESULTS Addendum 3):
    - Membership is PIT but reconstructed from Wikipedia, not S&P's official record, with 26 flagged anomalies.
    - Members removed **before** 2016 are absent, so the early years under-represent names that later failed.
    - Delisting returns: 47 matched terminal returns were applied. Names with null terminal returns got 0 on the exit day. Held this way: ESRX, APC, CELG, XLNX and TWTR (all acquisitions, weights ≤ 3.6%).
    - GICS sectors are **current**, not PIT, and null for former members, which therefore escape the sector caps.
    - Adjusted prices are back-adjusted, which is fine for returns and ratios. Dollar volume uses adjusted C×V.
    - Signals use full-day bars, unlike the live partial bar.
    - Not simulated: panic, breakers, stop-outs, the 1% minimum position, the no-trade band, rounding, TCA per-name costs.
  - **Not a performance claim:** fallback-composite Sharpe was −0.05 / −0.07 (live weights, k 1.0 / 1.25) and +0.19 / +0.14 (all five), with max drawdown −23.5% to −29.5% on gross ≈ 57%. This is consistent with no validated signal.
- **Walk-forward evidence (research/RESULTS_2026-10-30.md §2):**
  - On the 94 single stocks, MV with LW δ* (mean δ* ≈ 0.16–0.27) beat fixed δ = 0.5 on realised vol in every configuration.
  - Example: the legacy statarb bars, L120 weekly, 2021–2026: 11.13% vs 11.20%. On data.json, weekly: 7.96% vs 8.55%, Δvol bootstrap CI [0.25, 0.96] pp.
  - All MV variants **under-forecast** risk, with a bias statistic of 1.15–1.37 on statarb and up to 1.92 on data.json (MV-S, L60).
- **To do:**
  - ~~Switch to LW δ\*~~ Done in v0.4. ~~Inflate ex-ante vol for the bias~~ Done in v0.4 (k = 1.25).
  - ~~Re-estimate k on ≥10 years of PIT data and on the L/S book~~ Done in v0.5 (below). Result: keep k = 1.25.
  - Consider a regime-dependent k. Bias was 1.47–1.61 in 2020 and ≈1.0 in 2017 and 2019.
  - Keep cross-asset ETFs (TLT, HYG, GLD, SLV, EEM, EFA) out of the constant-correlation block (LW footnote 4).
  - Consider EWMA vol × shrunk correlation once the validator's walk-forward can compare them.

## 4. Sizing
| Option | Role | Status |
|---|---|---|
| Mean-variance with shrunk Σ, L1 cost and hard constraints (cvxpy/Clarabel) | Primary sizer: handles signed alpha, beta and sector constraints | **Implemented** |
| Inverse-vol / equal weight | Implicit in fallback (equal signal weights, correlation-adjusted C_shr⁻¹·1, α ∝ σ·score), plus the vol cap | **Implemented (implicitly)** |
| HRP (López de Prado 2016) | Alternative risk allocator, tested head-to-head in walk-forward (RESULTS §2). Its forecasts were better calibrated (bias 1.07–1.14), but it had +0.96 to +1.60 pp higher realised vol than MV-LW (all bootstrap CIs exclude 0), and Sharpe differences were not significant | **Not adopted**. Re-test on ≥10y PIT data |
| Book ex-ante vol cap | 6% annualised on k²× the 120d LW-shrunk covariance (k = `--risk_inflation` 1.25). An **optimiser constraint only**, not a scaler: it never rescales a solved book (`--vol_target`) | **Implemented** |
| Sleeve vol scaling (LIMITS.md §5; Moreira–Muir 2017 idea, scale-down only) | m_s = min(1, σ_target,s / σ̂_126d,s) per sleeve. This is the **only** vol-scaling overlay. The planned SPY 20d/120d market regime scaler was **dropped** to avoid double-scaling. Treated as risk control, not alpha (Cederburg et al. 2020). Details in §4a.1 | **Implemented (v0.3)** |

Per-name size caps (all implemented):
- |w_i| ≤ min(9.5%, 0.95% / stop-distance%)
- gross ≤ 58%
- minimum new position 1%

## 4a. Risk-limit alignment (LIMITS.md §1, §3, §5): implemented in v0.3

**Order of operations (construct.py):**
1. Combine signals (IC / equal weights, §2).
2. Sleeve weights: momentum = MOM_12_1 + RS63; trend = TREND; reversal = REV5; event = PEAD.
3. Vol-scaling multiplier m per sleeve (§4a.1).
4. Panic multiplier on the momentum and trend sleeves (§4a.2).
5. Book optimisation: beta, sector, 6% ex-ante vol constraint (LW Σ × k², k = 1.25), position, risk-to-stop and gross caps, including the breaker gross cap (§4a.3).
6. Stops (§7).
7. Compliance check (§4a.5). Targets are written only if no excluded asset is present.

The composite is Σ_k sw_k·m_s(k)·p_s(k)·Z_k, divided by the cross-sectional std of the **unscaled** composite Σ_k sw_k·Z_k. So m < 1 or panic shrinks alpha (and therefore trading) without being re-normalised away. With all multipliers at 1 the book is identical to v2. This was checked on 2026-10-30: the archived v2 and v0.3 with m forced to 1 give the same shadow and tradable books.

### 4a.1 Sleeve vol scaling (LIMITS §5)
- σ̂_126d is the annualised std of the last **126** daily returns of the sleeve's **backtest proxy**: a dollar-neutral, unit-gross book on the sleeve's cross-sectional z-score, lagged one day, over the current alpha universe. **v0.7:** bars come from `--proxy_src store_pit` (default): the data owner's store, SIP, adjustment=all, read through desk_data_client with `allow_api=False`. The universe is every PIT S&P 500 member on each date (`universe/sp500_membership.parquet`) minus the validator's defect names and SNDK, and the result is **PROVISIONAL**. `statarb` (the derivatives researcher's deprecated IEX bars, via `--proxy_path`) is kept for tests and audit only. `datajson` was removed. *(Pre-v0.7: statarb was the default, starting 2020-07.)*
- **σ_target (v0.6, LIMITS §5 T12):**
  - Once the proxy has ≥3 years (`--sigma_min_days` 756) of daily history, σ_target is the **median of the rolling 126d realised vol over the expanding window** up to the cutoff.
  - Before that, it is the proxy's full-sample realised vol.
  - The 1× cap (m ≤ 1) is unchanged.
  - Code: `sigma_target_rule()`. `--sigma_target_rule fullsample` restores v0.5. `--sigma_target momentum=0.12,...` still overrides.
  - LIMITS says "own live/paper daily returns once ≥3 years exist". The sleeves have no live history (the pilot started 2026-10-30), so the **backtest proxy** is used, as LIMITS allows before 3 years.
  - The statarb proxy (pre-v0.7) ran 2020-07 → 2026-10-28, with 1,370–1,564 proxy days per sleeve. The store_pit proxy (v0.7) runs 2016-01..2016-10 → 2026-10-28, with 2,521–2,715 proxy days. Both are ≥756 for every sleeve, so every sleeve uses the median rule.
  - 2026-10-30 values (σ_target median vs the old full-sample value):

    | Sleeve | σ_target (median) | Old full-sample | σ̂_126d | m (v0.6) | m (v0.5) |
    |---|---|---|---|---|---|
    | momentum | 10.40% | 11.85% | 23.07% | 0.451 | 0.514 |
    | trend | 10.46% | 12.19% | 22.52% | 0.464 | 0.541 |
    | reversal | 9.58% | 10.21% | 16.75% | 0.572 | 0.610 |
    | event | 9.49% | 9.73% | 14.06% | 0.675 | 0.692 |

  - T13 (σ̂/σ_target > 1.5) is logged as an INFO alert for Risk. Today it fires for momentum (2.22), trend (2.15) and reversal (1.75).
  - The data owner's 10.8-year SIP store could supply a longer proxy, but that would make σ_target PROVISIONAL under the validator's defects, so it is **not** used (`--proxy_src` has no SIP option).
- m = min(1, σ_target/σ̂) ∈ [0, 1]. If the proxy has fewer than 126 days, m = 1 and a note is logged.
- The window is 126 days for m. The covariance and beta stay on 120 days (Blume 0.67β + 0.33). Both windows are acceptable under LIMITS §5 when documented, as here.

### 4a.2 Panic flag (LIMITS §3)
- Source: `--panic_path` (default `risk/state/panic_flag.json`). Fields used: `panic`, `multiplier_momentum_trend` and `status`.
- **v0.6: the flag is PROVISIONAL, so it is context only.**
  - LIMITS §3 is explicit and not ambiguous: "PROVISIONAL: Alpaca-only, context plus the existing rules … The flag is computed and reported for context only. **The §3 responses are not binding.** H1–H10 and §2/§4 apply as usual". The responses become binding only once the long-history flag is live.
  - So a **valid** flag whose `status` contains "PROVISIONAL" (or which has `provisional: true`) is **read, logged (`panic_provisional: true`, `panic_applied`) and shown in the compliance table, but none of the three responses below is applied** (default `--panic_provisional context`).
  - `--panic_provisional apply` brings back the v0.5 behaviour with one flag.
  - A flag file **without** a provisional marker is binding.
  - **The fail-safe is unchanged and always applied:** a missing, stale, invalid or future-dated file means panic ON ×0.5 plus the loser-short ban and the β floor. This follows the risk file's own rule ("stale … act as if panic=true"). The asymmetry is deliberate.
- When applied (binding flag ON, or fail-safe):
  - the momentum and trend sleeves are multiplied by the file multiplier (0.5);
  - **no new loser-shorts**: names with a negative z in any active momentum or trend signal may not be newly shorted, and existing shorts may not be increased (optimiser constraint w_i ≥ min(0, w0_i));
  - **net β ≥ −0.10** (Σβw with 120d Blume beta) as an optimiser constraint. In de-risk mode, beta-negative contributors are reduced share by share instead.

### 4a.3 Drawdown breakers (LIMITS H8/H9)
- Source: `--breaker_path` (default `risk/state/breaker_state.json`). Fields used: `state` (NORMAL / HALVED / HALTED / RESUMED_DISARMED), `gross_cap_pct`, `new_trades_allowed`, `backstop_equity`, `halt_armed` and `current_equity`.
- The effective gross cap is min(file cap, state cap), with NORMAL 60, HALVED 30, HALTED 30 and **RESUMED_DISARMED 30** (v0.6, LIMITS §2b).
- **RESUMED_DISARMED** (v0.6):
  - 30% cap, new trades allowed, H9 disarmed;
  - `backstop_equity` is read from the file as **Risk's current episode backstop** (LIMITS v0.3.5 T4). It is never recomputed here. `halt_armed` is logged in the targets file and in the run log;
  - if the file's `current_equity`, or this run's equity, is ≤ `backstop_equity`, the run treats the state as **HALTED** (de-risk only) until Risk updates the file. v0.7 applies this in **any** non-HALTED state that carries a backstop, not only RESUMED_DISARMED;
  - RESUMED_DISARMED with a missing or invalid `backstop_equity` → **fail-safe HALVED**.
- **LIMITS v0.3.5 T4 (v0.7), as implemented:**
  - Lifts:
    - Exit (i) is automatic on shadow conditions plus a review. Exit (ii) is discretionary, needs an explicit logged OK, and resumes as RESUMED_DISARMED.
    - Every exit-(ii) lift **resets** the episode backstop.
    - Construction **never infers a lift**. Only the `state` in `breaker_state.json` counts: HALTED never allows new trades, whatever `current_equity` is.
    - Lift or episode fields, if Risk adds them, are passed through verbatim (`lift_fields_in_file`). They are never used to relax anything.
  - Backstop handling:
    - `backstop_equity` is the episode backstop (`backstop_role`).
    - An invalid backstop → fail-safe.
    - RESUMED_DISARMED without a valid backstop → HALVED.
    - `halt_armed: false` in NORMAL or HALVED is treated as inconsistent → fail-safe HALVED. This is my own fail-safe reading, not a LIMITS rule.
  - Tests: `test_t4_*` (3) in `tests/test_risk_state.py`, and `test_E_episode_backstop_hit_in_normal_state`.
  - **Discrepancies (reported, not edited; files are the risk manager's):**
    1. The `breaker_state.json` legend still says "backstop = 0.97 x equity at resumption". The LIMITS §2b body text still describes E_resume × 0.97. Both pre-date the v0.3/v0.3.2/v0.3.5 episode rule (tighter of 0.97 × resume and 0.92 × peak, set once per episode, reset on each exit-(ii) lift). Construction takes the number in the file, so the conflict only matters if Risk computes it with the old rule.
    2. The file has no episode or lift fields, so construction cannot verify that an exit-(ii) lift carries the logged OK. It relies on the risk `state` alone.
    3. As of 01:55 SGT the file reads NORMAL, `backstop_equity: null`, `halt_armed: true`. No episode is active, so there is no backstop check this run.
- **Any unknown state → fail-safe HALVED 30%** (unchanged; now tested with new states and wrong case). The optimiser uses cap − 1pp (58% or 29%).
- The SPY hedge must also fit under the cap.
- In de-risk mode, the largest risk-to-stop positions are trimmed first until gross ≤ cap − 1pp.
- **HALTED** (or `new_trades_allowed: false`) forces the tradable file to DE-RISK ONLY, even if signals are validated. No new names, no increases, stops only tightened.

### 4a.4 Fail-safe (Risk-confirmed 2026-10-30)
- If a state file is missing, unparseable, has invalid fields, has an as_of in the future, or has an `as_of_sgt` **more than 1 US trading day old**, it is treated as:
  - panic: ON, multiplier 0.5;
  - breaker: HALVED, gross cap 30%, new trades allowed.
- Age is the number of NYSE sessions (2026–27 holidays hard-coded) after the ET date of as_of, up to today's ET date. `--state_max_age_days` and `--now` are parameters.
- This replaces the earlier "missing path = flag off" rule.
- Code: `risk_state.py`. Tests: `tests/test_risk_state.py`, 13 tests (v0.7: + 3 T4 tests): missing, unparseable, stale, valid, invalid fields and future dates, holiday calendar, and in v0.6 the provisional marker, RESUMED_DISARMED, a backstop breach or missing backstop, and unknown state → HALVED. `tests/test_construct_limits02.py` runs 5 end-to-end runs on synthetic state files (v0.7: + D store_pit proxy and defect exclusion, + E episode backstop hit in NORMAL).

### 4a.5 Logging and compliance
- Every targets file (shadow and tradable) carries `risk_overlays`:
  - pipeline order;
  - per-sleeve σ̂, σ_target, m, proxy span and source;
  - panic factor per sleeve;
  - the full panic and breaker readings (path, as_of, age, fail-safe flag and reason);
  - gross cap and buffer; HALT state; the loser-short ban list;
  - the state files used.
- New compliance rows:
  - vol scaling m ∈ [0,1] with one overlay per sleeve;
  - panic factor;
  - panic: no new loser-shorts;
  - panic: net β floor;
  - breaker gross cap (H8);
  - breaker HALT (H9; INFO on the non-tradable shadow);
  - risk state files;
  - no crypto.

### 4a.6 Asset exclusion
- Crypto is ruled out entirely. There is no crypto sleeve, cap or logic.
- v0.6 check: grepping construct.py, risk_state.py, earnings_gate.py and the docs finds no crypto cap. The only crypto code left is the exclusion. data.json still contains BTC/USD, ETH/USD and SOL/USD bars, which are dropped at load. LIMITS §6 is marked REJECTED/VOID, and so is its crypto ×0.5 panic response.
- `excluded_asset()` rejects any symbol containing "/" or on a short deny-list:
  - at load (data and bars);
  - in the positions file, where the run aborts;
  - in the compliance table;
  - in a final guard that refuses to write any targets file containing one.

### 4a.7 Earnings (LIMITS H7, v0.6): `earnings_gate.py`
  - **(2026-11-06 correction, the risk manager):** Main-calendar `nasdaq_scheduled` / other forecasts are **never** confirmed next dates; `edgar_8k_2.02` is a realised release, not advance confirmation. Confirmed next dates require sidecar company/IR evidence. Missing sidecar pin → fail-closed. See `research/EARNINGS_GATE_CORRECTION_OWNER_REPORT_20261106.md`. Earliest across sources preserved; estimated −5-session buffer binding.
- **Calendar: yes, one exists on the box.** It is the data owner's (read-only), described in `data/README.md` §6:
  - `data/earnings/earnings_events.parquet`: 26,780 events, columns symbol, announce_date_et, timing BMO/AMC/INTRADAY/UNKNOWN, source and knowledge_time. Sources: edgar_8k_2.02 25,085, nasdaq_reported_or_past 1,460, **nasdaq_scheduled 235**.
  - `data/earnings/nasdaq_calendar.parquet`: 3,129 scheduled rows, report dates up to 2026-11-27, last fetched 2026-10-29 17:14 UTC = 01:14 SGT 30 Oct.
  - We use `announce_date_et` + `timing` only, **not** `first_tradable_session`, which has the validator's DURING_MKT alignment defect.
- **Horizon:**
  - The execution session is today (ET) if it is a session and before 16:00 ET, else the next session.
  - The horizon ends `--earn_horizon_sessions` (6) sessions later: on 2026-10-30 that is 2026-10-29 → 2026-11-06.
  - The next release is the first event not yet public (a BMO / 8-K already out today counts as released).
- **Release inside the horizon:**
  - the name may not be opened or increased on either side (both books);
  - a held position gets `exit_by`: the release day for AMC, else the previous session (UNKNOWN timing is treated as BMO);
  - if `exit_by` is today the target is 0 (de-risk closes it);
  - **shorts: no exceptions.** A long may be held through only if listed in `--earnings_hold_exceptions`. LIMITS requires a logged CIO exception with a 3× stop-gap stress; that is the CIO's sign-off.
- **Fail-safe for an unknown next date** (no upcoming event in a fresh calendar, or the calendar missing or stale for more than 1 US session):
  - **tradable book:** no new or larger short (w ≥ min(0, w0)), as an optimiser constraint in FULL mode; DE-RISK mode cannot add anyway;
  - **shadow book:** not constrained, but each such short is **flagged**, with an INFO compliance row and `unknown_date_shorts_flagged` in the log.
- **ETFs** (universe role `etf`, index/macro and sector ETFs) are exempt.
- The manual `--blackout` list (AMZN, INTC, XOM, CVX) stays on top.
- **Coverage today:**
  - 22 in-window names: AAPL, ABBV, AMD, AMGN, AMZN, BKNG, BRK.B, CI, COP, CVX, ETN, GILD, INTC, MCD, PFE, QCOM, REGN, SBUX, SYK, UBER, VRTX, XOM;
  - **60 single stocks with no known next date.** Mostly these reported in Sep–Oct, and their next date is beyond the Nasdaq window (to 2026-11-27). MMC is also on the list: it is not in the data owner's universe.
  - The strict fail-safe therefore blocks new shorts in about half the universe once a tradable FULL book exists. A possible relaxation (not decided): "reported within the last ~70 days and none scheduled in the calendar window". This is **not** implemented.
- Compliance rows: H7 no hold through release; H7 no new/added risk into release; unknown date (FAIL-SAFE in tradable, flag in shadow); calendar freshness.
- Tests: `tests/test_earnings.py` (20 tests; risk manager 2026-11-06 rejection regressions included).

### 4a.8 Data provenance and the validator's data defects (v0.6)
- The validator's `validation/backtests/pead_long_pit/data_issues.json` lists defects in **the data owner's SIP/PIT store**: missing delisting returns, history gaps for former members and predecessors, and SNDK ticker reuse.
- **Today's books are not affected.**
  - *(v0.6, superseded by §4a.9.)* Prices, betas, vols and the LW Σ came from `data.json` (Alpaca IEX via quant.py), and sleeve m and σ_target from the legacy statarb bars. Neither was the data owner's store.
  - The 120-name data.json universe and the 117-name statarb universe contain **no former member and no SNDK**.
  - The only overlap with the defect list is **LIN**: the defect is the missing pre-2018-10-31 Praxair history *in the data owner's store*. data.json's LIN bars are a separate source, and only 120 days are used.
- **The earnings calendar** is from the data owner's store but is a separate dataset. Forward dates come from Nasdaq scheduled rows; the validator's earnings caveats (DURING_MKT alignment; 105/220 coverage of former members) do not touch current names. It is listed in `data_provenance`.
- **Marked PROVISIONAL – data defects pending the data owner's fixes:**
  - the v0.5 L/S k re-estimate (`research/ls_volcap_wf.py`, `research/out/ls_volcap_sip_*`), in §3 and RESULTS Addenda 3 and 4;
  - the `risk_inflation.ten_year_pit_check_status` field in every targets file.
- Every targets file carries a `data_provenance` block (`book_affected_by_data_defects: false`, reason, provisional results referenced). Every log line carries `data_defects` (book_affected, provisional_results_referenced, label).

### 4a.9 Data provenance under DESK_RULES #5 (v0.7, 2026-10-30 02:22 SGT)
| Input | v0.6 (retired) | v0.7 |
|---|---|---|
| Universe | data.json symbols (non-crypto) | `DESK_UNIVERSE` = the same frozen 117 symbols (keys of `SECTOR`). MMC is absent from the store (it trades as MRSH there). The client fetches it from the API, but it has <260 bars, so it is dropped as before → 116 names |
| Book history (prices, ATR, betas, LW Σ, signals) | data.json (Alpaca IEX via quant.py) | `desk_data_client.get_daily_bars(..., adjustment="all")`: store first (SIP, coverage end 2026-10-28; store VERSION v1.1, 2026-10-30T01:50:54+08:00), with zero-volume rows masked; window = today − 420 calendar days (as quant.py) |
| Today's live row | data.json partial bar (IEX) | `desk_data_client.get_intraday_bars(..., "5Min")`: SIP 5-min bars from 09:30 ET, aggregated (o first, h/l max/min, v sum, c last). The client caps the end at now − 16 min. **Fails closed** if no bar comes back. `--live_source offline_test` (placeholder row, no API) is for tests only |
| Sleeve proxy (m, σ_target) | the derivatives researcher's statarb IEX bars (deprecated 02:09) | `store_pit`: store bars via the client (`allow_api=False`) × PIT S&P 500 membership, minus the validator's `members_without_bars_symbols` (59, incl. SNDK) and SNDK. No delisting returns (as before). **PROVISIONAL – data defects pending the data owner's fixes**. A missing defect file → fail closed |
| ADV | IEX × 21.6 | SIP from the store (TCA file where measured; median ratio 0.999) |
| Earnings | the data owner's `data/earnings` | unchanged |
| Direct HTTP / Alpaca calls | none in construct.py (the data.json fetch was quant.py's) | none. Every live call goes through the client (shared throttle + cache) |

Research scripts:
- `riskmodels_wf`, `volcap_wf` and `gp_wf` default to `src="store"` (desk universe through the client, `allow_api=False`).
- `datajson` / `statarb` are RETIRED and raise unless `--allow_retired` / `--retired` is given (audit reproduction).
- `ls_volcap_wf` reads the store's parquet files read-only. It makes no API calls (documented in its docstring).
- Earlier outputs are listed in `research/out/RETIRED_SOURCES.md`. They were not re-run on the store in this pass.

**Sleeve m / σ_target, old vs new** (shadow files `20261030T020824SGT` vs `20261030T022224SGT`; σ_target = expanding median of the 126d proxy vol):

| Sleeve | v0.6 statarb: days | σ̂_126d | σ_target | full-sample σ | **m** | v0.7 store_pit: days (start) | σ̂_126d | σ_target | full-sample σ | **m** |
|---|---|---|---|---|---|---|---|---|---|---|
| momentum | 1,506 | 23.07% | 10.40% | 11.85% | 0.451 | 2,657 (2016-04-06) | 16.33% | 7.71% | 10.06% | **0.472** |
| trend | 1,370 | 22.52% | 10.46% | 12.19% | 0.464 | 2,521 (2016-10-18) | 14.86% | 7.47% | 10.71% | **0.503** |
| reversal | 1,564 | 16.75% | 9.58% | 10.21% | 0.572 | 2,715 (2016-01-12) | 12.86% | 6.33% | 8.96% | **0.492** |
| event | 1,542 | 14.06% | 9.49% | 9.73% | 0.675 | 2,700 (2016-02-03) | 11.11% | 5.98% | 6.69% | **0.539** |

- The broader PIT universe (≈482 members/day vs the 117-name statarb set) lowers both σ̂ and σ_target. m moves up for momentum and trend and down for reversal and event.
- The T13 alert ratio σ̂/σ_target is now 1.86–2.12 for all four sleeves; at v0.6 event was not above 1.5.
- **Book-level effect:** the SIP history changes the in-sample/OOS signal study. MOM_12_1's OOS t is now −2.62 (v0.6: −0.87), so the fallback's "OOS t ≤ −2 → weight 0" rule drops it. Weights are now TREND / REV5 / PEAD at 1/3 each, with MOM_12_1 and RS63 at 0.

## 5. Beta and sector neutralisation
**Implemented:**
- 120-day daily beta vs SPY, shrunk 0.67β + 0.33.
- Optimiser constraint |βᵀw| ≤ 0.01.
- After integer rounding, a whole-share SPY hedge, then a post-check |β| ≤ 0.02.
- Sector caps: gross ≤ 20%, |net| ≤ 10% per sector (sector map in construct.py).

**To do:**
- Move to the Frazzini–Pedersen beta: σ from 1 year, ρ from overlapping 3-day returns over the longest available window, β = 0.6·β_TS + 0.4.
- Report net dollars and beta together. A beta-neutral book that is net-long dollars (e.g. +16.4% on 2026-10-30) carries an implicit low-beta/BAB tilt. Per Novy-Marx & Velikov (2022), that premium is unproven in mega-caps, so the risk manager should see it explicitly.

## 6. Turnover and cost model, with Gârleanu–Pedersen partial trading
**Implemented (v2):**
- **Per-name cost model, the default** (`--cost_model tca`), from the TCA owner's `tca/baseline_report.md` §5. Per side:
  - cost_bps = HS + k·σ_daily·√(Q/ADV20)·1e4 + H(bucket).
  - HS is the measured pilot half-spread from `tca/fills_20261030.csv` (corrected file) where available; otherwise the bucket default (L1 2.75 bps).
  - k = 0.75 (an assumption; cost_model.md uses 1.0).
  - Q = 5% of equity.
  - ADV20 is SIP from the TCA file where available. Otherwise, from v0.7, it is SIP ADV20 from the data owner's store (×1.0). The median TCA/store ratio on the 5 pilot names is 0.999. *(Pre-v0.7: IEX ADV from data.json × 21.6.)*
  - H = 2 bps.
  - Borrow: 25 bps/yr on short MV (a `tca/cost_model.md` §4 assumption; Alpaca paper charges none).
  - On 2026-10-30 the per-side cost was 2.4–9.8 bps, median 5.0 bps. It is close to the validator's ≥5 bps/side bar on average, but below it for GOOGL/XLE. Use `--cost_model flat --tc_bps 10` as the conservative stress.
- The penalty is amortised over `--hold_periods` 5-day periods (default 4). In fallback there is no amortisation (H = 1).
- 1% no-trade band on held names, applied only while still inside the buffered hard limits.
- Shares rounded toward zero.

**Pilot slippage (corrected; the TCA owner, baseline_report.md §2):** CAT 3.82, GOOGL 1.32, XLE 0.73, LLY 7.63 bps; mean 3.14 bps. MA's slippage was 2.20 bps. These are vs the NBBO mid at submission. Earlier figures in the hundreds of bps came from a TCA time-zone bug and are **retracted**. No file in portfolio/ used them.

**GP option (implemented, OFF by default):**
- `--gp_ell ℓ` (ℓ = λ/γ, cost-to-risk-aversion ratio, under GP Assumption A Λ = λΣ), or `--gp_rate τ` directly, and `--gp_rho` (per-period discount, default 0).
- Prop. 2, scalar: b = (1−ρ) + ℓρ; a/γ = (−b + √(b² + 4ℓ(1−ρ)²)) / (2(1−ρ)); trade rate τ = (a/γ)/ℓ. With ρ = 0: ℓ = 0.5 → τ 0.732; ℓ = 2 → τ 0.5; ℓ = 8 → τ 0.297.
- Prop. 4 aim: each signal's weight is scaled by 1/(1 + φ_k·a/γ), with φ_k = 1 − mean 5-day cross-sectional Spearman autocorrelation over the trailing 120 days. Fast-decaying signals such as REV5 (φ ≈ 1) get down-weighted.
- Trade: w = w₀ + τ(w* − w₀), then the usual limit checks.
- **Known issue:** blending from a non-beta-neutral current book breaks the |β| ≤ 0.02 check (shadow β −0.09 to −0.18 on 2026-10-30). To do: re-project or re-hedge beta after blending.
- Walk-forward results are in RESULTS §3. On the MV-LW book, τ = 0.5 roughly halves cost (115 → 70 bp/yr at flat 10 bps) for 0.8% TE to the full-rebalance book.

**To do:** calibrate ℓ from the TCA owner's per-name costs and the desk's risk aversion; use IC-decay curves from validated signals for φ_k instead of signal autocorrelation.

## 7. Stops and limit enforcement
**Implemented:**
- Stop = the tighter of 2×ATR(14) and any live broker stop parsed from orders_status.json. Stops are never loosened.
- Risk-to-stop ≤ 0.95% equity per name.
- 0.5% position and 2% gross buffers below the RM limits for price drift.
- An earnings blackout list, where existing positions may only be reduced (hard-coded: AMZN, INTC, XOM, CVX).
- A PASS/FAIL compliance table written into targets_*.json and README.md.
- Breaker gross cap, HALT and panic constraints from Risk's state files with fail-safe (§4a).

**To do:**
- Replace the hard-coded blackout list with an earnings-calendar feed from the data owner.
- Read the static RM limits (10% / 1% / 60%) from risk/ files instead of CLI defaults. The breaker and panic state are already read from `risk/state/`.
- Fail closed (write no targets) if any hard-limit check fails.
- Remove hard-coded date defaults (`--date`, `--asof_bar_cutoff`).

## 8. Fallback: zero validated signals: SHADOW / DE-RISK ONLY (CIO-confirmed 2026-10-30, implemented in v2)
**Policy:** with no validator-passed signal, the tradable output may only **reduce or close existing risk**:
- trim, cover or sell;
- tighten stops;
- **never** open a new name, increase a position or flip its sign.

**Implementation:** `--fallback derisk` is the default; `--fallback full` is the v1 behaviour, for research only.
1. The full fallback-composite book (`shadow_fallback_composite_v1`, §8a) is computed as before and written to `shadow/targets_<stamp>SGT.json` (v0.5 layout, §8b; `shadow/targets_<date>.json` before v0.5), with `book_type: SHADOW`, `tradable: false` and the label "SHADOW BOOK - NOT FOR TRADING".
2. The tradable `targets_<date>.json` (`book_type: DE-RISK ONLY`) is built per held position:
   - close if the shadow is flat or opposite-signed;
   - trim toward the shadow if |shadow| < |current|, skipped if the change is within the 1% band and the position is inside limits;
   - otherwise hold;
   - then trim share by share until within the buffered limits.
3. Stops are the tighter of 2×ATR and the live broker stop.
4. Three checks are added: no new names, no increase or flip, stops only tightened. Net beta becomes **INFO**, because the de-risk book cannot add a hedge.

**2026-10-30 v0.7 run (02:22:24 SGT, primary; shadow v2; LIMITS v0.3.5; DESK_RULES #5 data):**
- Files: `shadow/targets_20261030T022224SGT.json` (`shadow_fallback_composite_v2`) and `targets/targets_20261030T022224SGT.json` (`tradable_derisk_only_v1`, **empty**, flat book, 25 PASS / 1 INFO / 0 FAIL). Log lines 8–9 (schema 3, `method_version: v2`). Line 7 is the correction record.
- Inputs:
  - equity 100,024.08 (performance/history.csv);
  - breaker NORMAL, cap 60%, `backstop_equity: null`, `halt_armed: true`;
  - panic OFF, with the file marked provisional (not applied either way);
  - live row = SIP 5-min bars up to 2026-10-29 18:05 UTC bar end (14:05 ET; 02:05 SGT Fri 30 Oct).
- Shadow:
  - 8 names: LRCX −8.13%, NFLX −6.68%, MU +4.66%, SPY +4.60%, UNH +4.45%, PANW +3.01%, ACN +2.70%, META +1.26%;
  - gross 35.49%, net 5.87% (long 20.68 / short −14.81), β +0.0038, ex-ante vol 4.64% raw / 5.80% inflated (k = 1.25), exp. α 5.3 bp (5d);
  - 21 PASS / 2 INFO / 0 FAIL. INFO 1: unknown-next-earnings shorts flagged, LRCX and NFLX. INFO 2: T13 vol alert on all 4 sleeves.
- vs v0.6 (02:08, v1): 12 → 8 names; gross 42.89 → 35.49%; net 5.43 → 5.87%; ISRG, MRK, SMH and CAT left the book. The driver is MOM_12_1 dropping out of the fallback weights (§4a.9).
- `book_affected_by_data_defects: true`. Sleeve m comes from the PROVISIONAL store_pit proxy.

**2026-10-30 v0.6 run (02:08:24 SGT; superseded by the v0.7 run, see §4a.9; LIMITS alignment then cited as "v0.2", now v0.3.5):**
- Files and log:
  - `targets/targets_20261030T020824SGT.json`: tradable_derisk_only_v1, **empty**, 25 PASS + 1 INFO (T13 alert), 0 FAIL;
  - `shadow/targets_20261030T020824SGT.json`: shadow_fallback_composite_v1, 21 PASS + 2 INFO, 0 FAIL;
  - log lines 5–6 (schema_version 2).
- Shadow: **12 names, gross 42.89%, net 5.43%, β +0.0022, ex-ante vol 4.64% raw / 5.79% inflated.** Names: LRCX −8.18%, NFLX −6.76%, UNH 5.70%, SPY 3.84%, MU 3.77%, PANW 3.39%, ISRG −3.13%, MRK 2.97%, SMH 2.24%, META 1.27%, ACN 0.98%, CAT −0.66%.
  - **Earnings flag (shadow):** the shorts LRCX, NFLX, ISRG and CAT have no known next release date.
  - No in-window name is held. PANW's release (2026-11-18) is outside the horizon.
- State:
  - panic off, PROVISIONAL, applied = false; breaker NORMAL (cap 60%, halt_armed true, backstop_equity null); no fail-safe;
  - δ\* = 0.0858, k = 1.25;
  - m: momentum 0.4507, trend 0.4642, reversal 0.5716, event 0.6754 (median σ_target);
  - equity 100,024.08 from performance/history.csv (2026-10-30 row); positions.json `[]`.
- Versus v0.5 (01:43: 15 names, 50.98% gross): lower m (median σ_target) and the earnings constraints (22 in-window names) shrink the book. The live intraday bar also moved.
- **Book ID:** the shadow ID stays `shadow_fallback_composite_v1` in this run. By my own §8a rule, the v0.6 earnings constraint and σ_target change are material, so the ID **should** go to `_v2`. That is flagged for the CIO (§8a), not changed, to keep this to the single requested run.

**2026-10-30 v0.5 run (01:43:40 SGT; superseded by v0.6):**
- Files: `targets/targets_20261030T014340SGT.json` (tradable_derisk_only_v1, **empty**, 21/21 PASS) and `shadow/targets_20261030T014340SGT.json` (shadow_fallback_composite_v1): 15 names, gross 50.98%, net 6.10%, β −0.0004, ex-ante vol 4.61% raw / 5.76% inflated, 18/18 PASS. It differs from 01:35 (12 names, 45.14%) because the live intraday bar in data.json moved; the method is unchanged.
- Logged as lines 3–4 of `targets_log.jsonl`; lines 1–2 are the back-filled legacy files.
- Inputs: positions.json (01:33:41 SGT, `[]`); equity 100,024.08 from breaker_state.
  - history.csv was updated at 01:38:57 SGT and its last row now also shows 100,024.08, flat. Future runs can use the default equity source.
- State: panic off, breaker NORMAL (cap 60%), no fail-safe fired. δ\* = 0.0858, k = 1.25. m: momentum 0.5135, trend 0.5412, reversal 0.6097, event 0.6919.

**2026-10-30 v0.4 run (01:35 SGT, primary):**
- `positions.json` was refreshed at 01:33 SGT and is now `[]` (flat), so the run uses current positions.
- Equity is $100,024.08 from breaker_state current_equity (01:22 SGT). performance/history.csv (01:05 SGT) predates the flat book.
- LW δ\* = 0.0858, k = 1.25. Panic off, breaker NORMAL, no fail-safe fired.
- Tradable: **DE-RISK ONLY, empty**; 21/21 checks PASS.
- Shadow: 12 names, gross 45.14%, β +0.0008, ex-ante vol 4.59% raw / **5.74% inflated**; 18/18 checks PASS.
- Comparisons in `research/runs/v4_*`:
  - fixed δ 0.5 with k 1.25: 13 names, gross 36.56%;
  - LW with k 1.0: 10 names, gross 54.32%, vol 5.71%;
  - fail-safe: gross 19.14%;
  - fixed 0.5, k 1.0, m = 1: identical to v0.3 (56.78% gross, 17 names).

**2026-10-30 v0.3 run (01:30 SGT, LIMITS-aligned; superseded):**
- `positions.json` (00:52 SGT) is **stale**: it still lists 5 positions. Risk's decisions-log says the book was **flat** at 01:22 SGT (0 positions, 0 open orders, equity $100,024.08).
- The primary run therefore uses `--positions research/inputs/positions_flat_2026-10-30_0122SGT.json` (empty) and `--equity 100024.08` (breaker_state current_equity).
- Tradable: **DE-RISK ONLY, empty** (nothing to reduce). All 20 checks PASS.
- Shadow: 13 names, gross 48.65%, β +0.004, vol 5.67%. All 17 checks PASS.
- m: momentum 0.513, trend 0.541, reversal 0.610, event 0.692. Panic off (factor 1.0). Breaker NORMAL (cap 60%). No fail-safe fired.
- Scenario runs (fail-safe, panic + HALVED, HALTED, stale state, stale positions) are in `research/runs/`.

**Earlier 2026-10-30 run (v2, before LIMITS alignment; superseded; based on the now-stale positions.json, TCA cost model):**
- Tradable book: MA 15→12, LLY 7→4, XLE 146→59, CAT −15→−6, GOOGL −35→−2.
- Gross 21.65%, beta −0.04 (current −0.25), vol 3.24%.
- All hard-limit checks PASS. MA's stop is tightened 615.88 → 616.02.
- Shadow: 16 names, gross 55.54%, beta −0.001, vol 5.60%.
- Under flat 10 bps (the earlier v2 run), the trims were smaller: XLE 146→136, MA 15→14, LLY 7→5, CAT −15→−8, GOOGL −35→−14. The cost assumption drives the size of the trims.
- **Option for the CIO:** a stricter "limits-only" de-risk would trim only positions breaching the buffers (MA only). Not implemented.

**(Superseded. Kept for history: this proposal was confirmed and implemented in v2 as described above.)** Original proposal: because SPRINT.md says nothing trades without a validation pass, in fallback construct.py should:
- (a) **not add new alpha risk**, so no new names and no increases;
- (b) only **de-risk** existing positions toward the hard limits and toward beta ≈ 0 (e.g. with the SPY hedge);
- (c) keep all stops in place;
- (d) still compute the full fallback-composite book as a **shadow portfolio** for tracking (Priya), clearly labelled non-executable.

This was implemented as `--fallback derisk` (default) in v2.

## 8a. Book identity (v0.5): names and IDs for downstream consumers (Priya / Leo)
Every targets file carries `sleeve_id`, `book_name` and `description`. The shadow file also carries `book_type: SHADOW` and `tradable: false`.

| sleeve_id | book_name | File | Meaning |
|---|---|---|---|
| `shadow_fallback_composite_v1` | Shadow fallback composite v1 | `shadow/targets_<stamp>SGT.json` | Non-tradable tracking book (description below) |
| `tradable_derisk_only_v1` | Tradable de-risk-only book v1 | `targets/targets_<stamp>SGT.json` | No validated signal or HALTED: trim, close or cover, and tighten stops only |
| `tradable_validated_composite_v1` | Tradable validated composite v1 | `targets/…` | Only once validator validates a signal |
| `research_full_fallback_v1` | Research full fallback v1 | `targets/…` (research runs only) | `--fallback full` on unvalidated signals; not CIO policy |

**Shadow description (verbatim, `SHADOW_DESCRIPTION` in construct.py):** "Non-tradable tracking book (paper, never executed). Five price signals (MOM_12_1, RS63, TREND, REV5, PEAD) are equal-weighted in the fallback (any signal with OOS t <= -2 gets weight 0; RS63 on 2026-10-30), grouped into momentum/trend/reversal/event sleeves, each scaled by its 126d vol multiplier m (<= 1) and the panic factor, then sized long/short by a mean-variance optimiser on a 120d Ledoit-Wolf constant-correlation covariance with a 6% ex-ante vol cap (forecast x1.25), |beta| <= 0.01 via an SPY hedge, sector, 9.5% position, 0.95% risk-to-stop and 58% (or breaker) gross caps, TCA cost model; 2xATR(14) stops. US equities/ETFs only."

The earlier label "equal-risk" was inaccurate and has been retired. The signal weights are equal (correlation-adjusted C_shr⁻¹·1, which is equal when the IC history is short). The actual weights of each run are in `signal_weights`.

**Version rule:** bump `_vN` only for a material methodology change: the signal set or definitions, the combination rule, the risk model (Σ estimator, k), the constraint set or limits, or the sizing objective. Parameter refreshes (δ\*, m, betas, prices) do not bump the version. Every bump is logged here:
- `v1`: 2026-10-30 01:43 SGT. Construction as of construct.py v0.4/v0.5: LW δ\*, k = 1.25, sleeve m, panic/breakers, TCA costs.
- *(v0.6, 02:08 SGT)* construct.py v0.6 added the H7 earnings constraints, the median σ_target and the provisional-panic treatment, but the 02:08 run still carried `_v1`.
- **`v2`: 2026-10-30 02:22 SGT** (CIO 02:12), first run `20261030T022224SGT` (log line 8). The method changed in four ways:
  1. σ_target rule: the LIMITS §5 T12 expanding median of the 126d proxy vol;
  2. H7 earnings gate: strict, no estimated dates;
  3. a provisional panic flag that is **not applied** (×0.5 fail-safe on a missing or stale file);
  4. a new data source (DESK_RULES #5): store plus desk_data_client for book history and the live row (SIP), and the store_pit PIT S&P 500 sleeve proxy (PROVISIONAL).
  - Every log line from line 8 on carries `method_version: "v2"`.
  - The v1 lines (3–6) have no field. `targets_io.read_log` infers `v1` (`method_version_source: inferred`).
  - The tradable IDs (`tradable_derisk_only_v1`, …) were **not** bumped, because the brief scoped v2 to the shadow book. Their log lines carry `method_version: v2`. Whether to bump them is a CIO question.
  - The back-filled 01:35:36 lines (1–2) are the **legacy** method (`legacy_pre_v1`), per the correction record on line 7 (§8b).
  - ~~The back-filled 01:35 SGT legacy file is the same method~~ Corrected (line 7): the back-fill is the legacy pre-v1 method, and its ID was assigned retroactively.
  - Earlier 2026-10-30 runs (v2 / v0.3, fixed δ = 0.5, k = 1) are **not** v1. They were overwritten in place and survive only in `research/runs/` and the archive.

## 8b. Output layout and run log (v0.5)
- **Immutable, timestamped files.** One file per run per book: `targets/targets_<YYYYMMDD>T<HHMMSS>SGT.json` (tradable) and `shadow/targets_<YYYYMMDD>T<HHMMSS>SGT.json`. A `_gp` suffix is added if GP is on.
  - They are written by exclusive create (temp file + fsync + `os.link`), so a run **fails** rather than overwrite. Both paths are checked before anything is written. Mode 0644.
- **Run log:** `targets_log.jsonl`. It is append-only, one JSON line per book per run, appended under `fcntl.flock` with `O_APPEND` + fsync. The schema is in README.
  - The log is the **authoritative** index. Each line carries the file path and its sha256.
- **`targets/latest.json` and `shadow/latest.json`** are relative symlinks, swapped atomically after the log append. They are **non-authoritative** convenience pointers: a concurrent run can move them. Readers should use the log, or a timestamped file plus its sha256.
- **Legacy files preserved unchanged:** `targets_2026-10-30.json` and `shadow/targets_2026-10-30.json` (mtime 01:35:36 SGT, v0.4).
  - Each is back-filled as one log line with `backfill: true` and a note. The note says the path was overwritten in place by successive runs, so only its final content is described, and that generated_sgt is the file mtime.
- **Tests:** `tests/test_targets_io.py` (5 tests: exclusive create, stamp format, 8 processes × 25 concurrent appends, latest symlink, end-to-end refuse-to-overwrite plus append).
- **Log schema v3 (v0.7):**
  - Every run line adds `type: "run"`, `method_version` (`"v2"`), `limits_version` (`"v0.3.5"`) and `data_source{book_history, live_row, sleeve_proxy, sleeve_proxy_status}`.
  - **Correction records:** `type: "correction"`, `correction_id`, `generated_sgt` (time of the correction), `corrects[{line, run_id, book, generated_sgt, file, file_sha256}]`, `fields{…}`, `note`, `author` and `requested_by`. They are appended. Earlier lines are **never** edited.
  - Readers must skip correction records as books. `targets_io.read_log()` returns `(runs, corrections, issues)`, with an `_effective` view per run line: the record's fields overlaid with every matching correction's `fields`, with `method_version` resolved (`record` / `correction` / `inferred`). Every given key of a correction target must match exactly; a mismatch is ignored and reported in `issues`.
  - **Line 7** (`corr_20261030T022150SGT`) corrects lines 1–2: `method_version: legacy_pre_v1`; `generated_sgt_semantics: file_mtime_not_true_run_time`.
  - Tests: `test_correction_records_reader` in `tests/test_targets_io.py` (now 6 tests).
- **Log schema v2 (v0.6):** adds `state.panic_provisional`, `state.panic_applied`, `state.breaker_state_in_file`, `state.backstop_equity`, `state.halt_armed` and `state.sigma_target`; `earnings{calendar_fresh, calendar_fetched_at_utc, horizon_end_session, n_in_window, n_unknown_next_date, unknown_date_shorts_flagged}`; and `data_defects{book_affected, provisional_results_referenced, label}`. Lines 1–4 stay schema 1.

## 9. Implemented vs to-do summary
| Component | construct.py today | To do |
|---|---|---|
| Admission gate | ✅ `--validator_passed` AND internal OOS test | Parse the recorded verdicts automatically |
| IC weights + shrinkage + correlation adjustment | ✅ (n0 = 20, C_shr, 50/50 blend) | Walk-forward IC and decay from the validator; per-signal budget cap |
| Covariance shrinkage | ✅ LW 2004 optimal δ\* to constant correlation (fixed 0.5 optional) | Exclude cross-asset ETFs from the CC block |
| Risk-forecast inflation | ✅ k = 1.25 in the 6% cap only (short-sample bias 1.15–1.37; v0.5 10y PIT L/S bias 1.14–1.23, **PROVISIONAL – data defects pending the data owner's fixes**) | Regime-dependent k (2020 bias ~1.5); re-run ls_volcap_wf after the data owner's fixes |
| MV optimiser + 6% ex-ante vol **constraint** | ✅ 6% annualised (constraint, not scaler) | – |
| Sleeve vol scaling (LIMITS §5) | ✅ m = min(1, σ_tgt/σ̂_126d) per sleeve; the only overlay; σ_target = expanding median of 126d proxy vol (≥3y) (v0.6) | Switch to live sleeve returns after 3y; SIP proxy after the data owner's fixes |
| Panic (LIMITS §3) + breakers (H8/H9) | ✅ from risk/state with fail-safe; provisional panic = context only (v0.6); RESUMED_DISARMED + backstop (v0.6); tested | Re-enable panic responses when Risk drops PROVISIONAL (automatic: no marker → binding) |
| Asset exclusion | ✅ crypto hard-excluded + compliance row + write guard | – |
| HRP | ❌ (walk-forward done: not adopted) | Re-test on ≥10y PIT data |
| Beta neutral | ✅ \|β\| ≤ 0.01, SPY hedge | FP beta estimator; net-$ reporting |
| Sector caps | ✅ 20% gross / 10% net | Map from the data owner's data |
| Cost model | ✅ TCA §5 per-name (HS + k·σ√(Q/ADV) + H) + 25 bps/yr borrow; flat 10 bps as option | Calibrate k and HS on more fills; live borrow rates |
| GP aim / partial trading | ✅ option, off by default (`--gp_ell` / `--gp_rate`) | Beta re-hedge after blending; ℓ calibration; IC-decay φ |
| Stops + RM limits | ✅ with buffers + compliance table | Limits from risk/ files; fail-closed |
| Earnings (H7) | ✅ v0.6: the store calendar; no hold through release (shorts: no exceptions); unknown date → tradable short block / shadow flag; plus manual list | Relaxation rule for recently-reported names (open) |
| Fallback | ✅ SHADOW (not for trading) + DE-RISK ONLY tradable file | Optional limits-only mode |
| Book IDs + immutable outputs + run log | ✅ v0.5 (§8a, §8b), tested | Priya/Leo to read `targets/` + log |

## 10. Open questions
1. ~~Should the fallback trade at all?~~ Resolved: shadow / de-risk only (CIO, 2026-10-30). Still open: should de-risk trims follow the shadow book, or the limits only?
2. Card owner naming: the pipeline lists "the portfolio-construction lead" for combine; cards use "Portfolio Construction Quant". Confirm.
3. Status vocabulary for method papers: validator uses "reference (methodology)" in REGISTRY. My cards use "candidate" as SPRINT.md specifies.
4. Data needed:
   - borrow rates and HTB flags (Alpaca)
   - ~~an earnings calendar~~ Found: the data owner's `data/earnings/` (v0.6, §4a.7)
   - ~~≥10 years of PIT history from the data owner~~ Received: 2016-01-04 → 2026-10-28 SIP, PIT S&P 500 membership. Used for k in v0.5. Still to do: IC decay and the HRP re-test on it.
5. ~~the TCA owner's per-name cost curve~~ Done: baseline_report.md §5 is in use. Open: k (0.75 vs 1.0) and live borrow.

### §8c Post-run note (02:10 SGT 2026-10-30): sleeve-proxy source deprecated
At 02:09 SGT, one minute after the v0.6 run (20261030T020824SGT), `statarb/data/daily_bars.json` was moved to `statarb/data/_deprecated/` (DEPRECATED.md: retired direct-Alpaca IEX pull, survivorship-biased universe, audit only). That file was the default `--proxy_src statarb` input for the §4a.1 sleeve m / σ_target. The 02:08 books were built from it, so the sleeve multipliers in that run rest on a source that is now deprecated. construct.py now **fails closed** with an explicit message when the proxy file is missing (no targets written). `--proxy_path` was added as an override. The tests point it at the audit copy to exercise the logic only; that does not endorse the data. The replacement source (e.g. a survivorship-correct proxy from the store, which carries the known validation defects) was an open decision. **Resolved 02:12 SGT:** store_pit PIT proxy, PROVISIONAL (§4a.9). `statarb` + `--proxy_path` remains for tests and audit only.


### §8d 2026-11-06 verification (post-outage)
See `research/VERIFICATION_20261106T061200SGT.md`. Earnings calendar fail-safe fired (5 sessions stale). CIO all-new-trading hold: tradable targets publish suppressed when `new_trades_allowed=false`; Nov 6 empty tradable files retained for audit but must not be used. Shadow `20261106T061200SGT` is the tracking book.
