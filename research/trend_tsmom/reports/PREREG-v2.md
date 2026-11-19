# PRE-REGISTRATION v2: unlevered, lower-cost ETF trend sleeve

**Owner:** Maya (Macro Strategist) · **Written:** Fri 30 Oct 2026, ~01:35 SGT, **before any v2 backtest was run** · **Requested by:** CIO (Jeremy)
**Status:** FROZEN. Any change to this file after the first v2 run must be logged in §9 with a timestamp and a reason, and the changed spec counts as a new trial.
**Predecessor:** `RESULTS.md` (v1, ETFs only, 19 trials). Crypto stays excluded by desk decision.

## 1. Why v2: what v1's cost attribution showed
The v1 baseline (12m, monthly, 10% book vol, 23 ETFs) earned 6.8% gross and 2.3% net (Sharpe 0.20). The 4.5%/yr gap came from three sources:
- **FX ETFs** (UUP/FXE/FXY/FXB/FXA/FXC):
  - These are all in Tomas's L4 bucket (ADV < $50M), at about 45–65 bps one-way.
  - They earned 0.8% gross against 2.5% of cost, for −1.8%/yr net.
  - They carried about 1.0× NAV of combined notional.
  - FXE and FXB are not shortable today.
- **SHY:**
  - At about 1.5% vol, inverse-vol sizing gave it about 1.0× NAV average notional.
  - That meant 4.8× turnover per year and about 0.7% of cost per year.
- **Leverage and vol churn:**
  - The book averaged 3.2× gross (max 5.9×), and monthly re-sizing to the vol target alone generated 15× turnover.
  - Faster signals and weekly rebalancing all failed net.

v2 therefore:
- removes leverage (gross ≤ 1.0×);
- removes SHY and the FX basket, keeping UUP in one variant only;
- restricts the core universe to ETFs in Tomas's L1/L2 buckets;
- adds a no-trade band;
- keeps the paper's 12-month signal fixed rather than re-choosing it.

**Selection caveat (forking paths).** Two v2 choices are informed by v1 results:
- The universe rule (L1/L2 buckets) is a liquidity rule set by ex-ante cost, not by return. But I have seen the v1 per-asset contributions: FX was the weakest class gross, and SHY was the largest gross contributor. Excluding them is therefore not fully blind.
- The 12m lookback is the paper's spec, and it also ranked best gross in v1.

This is why the v2 trials are added to the v1 count rather than counted fresh (§7).

## 2. Common specification (all variants unless stated otherwise)
| Item | Specification |
|---|---|
| Data | Desk bar store, `total_return/daily_total_return.parquet` → `tr_index_best`, the build current at run time. Its sha256 is recorded in `outputs_v2/meta.json`. At pre-registration the sha256 was `87d09bb9…5ead` (file mtime 01:29 SGT). If the build differs at run time, v2 still runs, and the v1 primary is **re-run on the same build** so the comparison stays like-for-like. RF is Ken French daily RF, forward-filled past its last date. Shortability comes from `assets_2026-10-29.parquet` (today's flags; `shortable AND easy_to_borrow`). |
| Evaluation window | **2017-02-01 → 2026-10-28** (same as v1; last session in the frozen build). Subperiods: 2017–19, 2020–22, 2023–26YTD. |
| Signal | Sign of the trailing **12-month** (252-session) cumulative excess return over RF. No blend and no other lookbacks. |
| Short rule | If the signal is negative and the ETF is shortable and ETB today → short. Otherwise → flat (0). |
| Ex-ante vol | EWMA variance of daily excess returns, centre of mass 60 days, annualised ×252; minimum 60 observations. |
| Risk weights | raw_i = s_i / σ_i (inverse vol), equal risk per live asset, normalised by N_live. |
| Book vol target | Scale the raw book to **10% ex-ante annual vol**, using a 252-session sample covariance of the live assets. |
| **Gross cap (hard)** | After vol scaling, if Σ\|w_i\| > **1.00**, scale all weights pro-rata so Σ\|w_i\| = 1.00. The vol target is therefore a ceiling that usually binds below 10%. Between rebalances, the drifted gross is checked **daily**. If it exceeds 1.00, all positions are scaled pro-rata back to 1.00 at that day's close (costed, not subject to the band). |
| Cash residual | NAV − Σ(long weights) − short collateral is held as cash at RF (equivalent to a flat, never-traded BIL/SHY position): **zero excess return and zero cost** by construction. No BIL/SHY trading is modelled. |
| Rebalance timing | Signal at the close of the last session of the rebalance period; fill at the **next session's close** (lag 1). Weights drift between rebalances. |
| **No-trade band** | At each scheduled rebalance and for each asset, given current drifted weight c and target t: (a) if sign(t) ≠ sign(c), including moves to or from 0, trade fully to t; (b) else if \|t − c\| > max(**0.25·\|t\|**, 0.005), trade fully to t; (c) otherwise do not trade that asset. After banding, if gross > 1.00, apply the pro-rata cap. |
| Costs | **Tomas v1.1** `cost_model.trade_cost()` (pin: `cost_model.py` sha256 `df67d604…eebf`). Same assumptions as v1: continuous venue, impact k = 1.0, bucket-default spreads and buffer, lagged 20-day σ and ADV, $1M NAV. Borrow is 25 bps/yr on short MV (360-day basis, calendar days). If Tomas releases a newer model before the run, v1.1 stays the pre-registered base and the newer one is reported as a sensitivity. |
| P&L | Daily excess return over RF; net = gross − trading costs − borrow. Margin interest is not applicable (no leverage). |

### Universes
- **CORE-L12** (11 ETFs): card ETFs whose modal v1 cost-model bucket was L1 or L2.
  - Equity: SPY, QQQ, IWM, EFA, EEM, EWJ
  - Rates: IEF, TLT
  - Commodity: GLD, SLV, USO (USO is not shortable today, so long/flat)
  - All others are shortable/ETB today.
- **CORE-L12 + UUP** (12 ETFs): CORE-L12 plus UUP as the single USD leg. UUP is L4 but shortable.
- **BROAD-exFX** (16 ETFs): the v1 card universe minus SHY and the five non-USD FX ETFs and UUP, i.e. CORE-L12 plus EWG, EWU, UNG, DBA, DBC (L3/L4; all shortable today). This tests breadth against cost once leverage is removed.

## 3. Variants (5 trials, fixed)
| ID | Universe | Shorts | Rebalance | Band | Role |
|---|---|---|---|---|---|
| **V1 (PRIMARY)** | CORE-L12 | where shortable/ETB today, else flat | monthly (last session of month) | 25% relative / 0.5% NAV floor | **Primary.** Decision rests on this one only. |
| V2 | CORE-L12 | **none: long/flat for all** | monthly | same | Long/flat-only implementation |
| V3 | CORE-L12 + UUP | where shortable | monthly | same | Is a single USD leg worth its cost? |
| V4 | CORE-L12 | where shortable | **quarterly** (last session of Jan/Apr/Jul/Oct, so the first rebalance falls on 2017-01-31) | same | Slower rebalance |
| V5 | BROAD-exFX | where shortable | monthly | same | Breadth vs cost |

Everything not listed in the table is the common spec in §2. No other variants will be run as trials.

**Non-trial sensitivities.** These are reported for V1 only and do not change the signal, the weights or the decision:
- 2× costs
- MOC venue (`venue="close"`)
- $10M NAV
- borrow at 50 bps/yr
- band switched off (to show what the band saves)

**Benchmarks** (not trials): SPY excess TR; long-only CORE-L12 with the same sizing and cap (signal fixed at +1).

## 4. Metrics reported for every variant (gross and net)
- annualised excess return, vol, Sharpe, t-stat, Sharpe SE (Lo/Mertens), CAGR, max drawdown
- monthly skew
- annual one-way turnover, average cost (bps one-way), break-even cost
- average and max gross exposure, average net exposure, and the number of daily cap breaches and forced trims
- correlation to SPY (daily and monthly)
- return in SPY's worst-decile months
- per-asset and per-class contributions
- subperiods and calendar years
- **net Sharpe excluding calendar 2022**
- Tomas §6 flag

## 5. Pass/fail criterion: applies to V1 (PRIMARY) only
**Stage A: "pass to Victor for validation".** V1 must meet ALL of the following over the evaluation window:
1. **Net Sharpe ≥ 0.40** at base costs.
2. **Tomas flag = PASS**: net return > 0 at 2× costs, AND cost drag ≤ 50% of gross return.
3. **Max drawdown (net) no worse than −15%.**
4. **Not a one-year result**: net Sharpe excluding calendar 2022 > 0, AND net return > 0 in at least 2 of the 3 subperiods.
5. **Deflated Sharpe ≥ 0.50** on V1 net returns (§7 accounting, N = 24). DSR ≥ 0.50 means the deflated evidence is at least better than a coin flip.
6. **Mechanical**: gross exposure ≤ 1.00 at every close after any forced trim, and no short in an ETF flagged non-shortable.

**Stage B: "validated".**
- **DSR ≥ 0.95**, with the identical V1 spec (no re-tuning), on an extended history once Dmitri's 2005+ backfill exists.
- Stage A alone cannot reach this: with 9.7 years, a DSR of 0.95 would need a net Sharpe of roughly 0.9+, which is implausible for trend after 2010.

**Failure rules (fixed now):**
- If V1 fails any Stage A item, **the v2 sleeve fails**. We do not promote a secondary variant that happens to pass, and we do not tune band, cap, universe or lookback afterwards.
- A secondary variant that passes Stage A may only be proposed as a **new pre-registration**, counted as a further trial and tested on Stage B data.

## 6. Pre-stated expectations (to check honesty afterwards, not a criterion)
- Removing leverage should roughly halve or third the gross return vs v1.
  - v1's 2×-capped version showed 3.6–3.7% gross.
  - Expect V1 gross of about 2–4% at a realised vol of about 5–8%, with the cap binding most months because of IEF/TLT.
- Turnover should fall from about 15× to about 1–3× per year, and the average one-way cost from about 26 bps to about 5–8 bps.
- Whether net Sharpe clears 0.40 is genuinely uncertain. I give it a probability of about 35%.

## 7. Multiple-testing accounting
- **Trial count:** N = **24** = 19 v1 signal/sizing trials + 5 v2 trials (V1–V5).
  - Not counted as trials: v1's 5 cost variants, the benchmarks, and the §3 non-trial sensitivities. None of them changes the signal or the weights.
  - The crypto runs from the original v1 draft are excluded from the count, because crypto was removed from scope before conclusions were drawn.
- **DSR method** (Bailey & López de Prado 2014), computed on V1 daily net returns, using V1's own skew and kurtosis:
  - SR0 = √V[SR] · ((1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))), with N = 24.
  - V[SR] is the variance of the annualised **gross** Sharpe ratios across all 24 trials. Gross is used because v1's net dispersion is dominated by cost-model effects on the fast variants: it gives SR0 ≈ 1.4, which no trend strategy could clear.
  - I will **also report** the all-net-dispersion DSR for transparency. Only the gross-dispersion version is the Stage A test.
- Also reported: the probabilistic Sharpe vs 0, and the Harvey-Liu-Zhu t > 3 reference.
- **Forking paths:** see the §1 caveat. If V1 passes Stage A, Victor should treat the effective N as larger than 24. Stage B on unseen pre-2016 data is the real out-of-sample test.

## 8. Code changes needed before running (implementation only, no new degrees of freedom)
- `engine.Config`: add `band_rel=0.25`, `band_abs=0.005`, `gross_cap_hard=1.0` with a daily drift check and forced trim, `long_flat_all`, and `rebalance="Q-JAN"`. This must match §2 exactly.
- `run_v2.py`: runs exactly V1–V5, the §3 sensitivities and the benchmarks, and writes to `outputs_v2/`. The v1 files stay untouched.
- Unit checks before the first v2 run:
  - Gross ≤ 1.0 after every trim.
  - A non-shortable ETF never goes negative.
  - With the band set to 0, the engine reproduces v1 behaviour.

## 9. Change log
- 2026-10-30 ~01:35 SGT: initial pre-registration. No v2 runs yet.

### Amendment A1: Victor (Signal Validation Lead) sign-off with amendments. Logged 2026-10-30 ~01:35 SGT, BEFORE any v2 run
Victor signed off on this pre-registration subject to the following. They are recorded here in substance and take precedence over §5–§7 where they conflict:
1. **Stage A is a screen, not a pass.**
   - Clearing Stage A earns only **"eligible for Stage B validation"**. It is NOT a PASS or CONDITIONAL PASS, and nothing trades (paper or otherwise) on it.
   - `validation/STANDARD.md` still requires net (OOS) Sharpe > 0.5 and DSR ≥ 0.95 for any pass.
   - 2017–2026 was seen in v1, so it is not out-of-sample. Stage B on the 2005+ backfill is the real test.
2. **Effective N.**
   - Victor deflates at **N = 30**.
   - Results report DSR at N = 24, 30 and 50, each in both the gross-dispersion and the all-net-dispersion version. V[SR] always comes from the 24 logged trials; only N varies.
   - The Stage A gate (§5 item 5) stays at **gross-dispersion, N = 24, DSR ≥ 0.50**.
3. **Stability checks** (V1 only; NOT trials and NOT decision inputs):
   - lookback 9m and 15m (vol target 10%);
   - vol target 8% and 12% (lookback 12m).
   - Requirement for each, reported against V1: net Sharpe > 0 AND ≥ 50% of V1's net Sharpe.
   - Also report V1 results split by **SPY above vs below its 200-day moving average**. The regime is known at close t−1 and applied to day t returns.
4. **PBO via CSCV**: computed on the T × 24 daily **net** return matrix (19 v1 trials re-run on the current data build, plus V1–V5) over the common evaluation window, with S = 16 blocks and all C(16,8) combinations, ranked by Sharpe. This is reported, not gated, at Stage A.
5. **Look-ahead limitation**: the results must state that shortability uses today's (2026-10-29) Alpaca flags applied to the whole history.

### Amendment A2: Maya, STANDARD.md items applied where relevant. Logged ~01:36 SGT, BEFORE any v2 run
These are reporting additions only. No change to any variant, to the Stage A gate, or to the primary.
- §7 regime/stability, reported for V1:
  - calendar-year P&L and the share of P&L from the largest year (STANDARD flag if > 40%);
  - long and short legs separately;
  - correlation to SPY.
  - VIX high/low cannot be reported: there is no VIX series in the desk store. This is stated as a gap.
- §8: annual turnover, average holding period, gross return per unit turnover, and break-even cost vs 2× the assumed cost.
- §5 cost minimums:
  - STANDARD's short-borrow floor is 1%/yr general collateral, against Tomas v1.1's 25 bps. A **borrow 1%/yr** non-trial sensitivity is added for V1.
  - The base stays at Tomas v1.1 as pre-registered. Any later STANDARD verdict must use the higher borrow.
- §2 fills: our fills are at the next session's close (lag 1). That is later than STANDARD's "next-bar open or worse" minimum, but it is not an open fill. Stated as a caveat.
- §1 artefacts written to `outputs_v2/`:
  - trial log with all 24 trials;
  - the T × 24 net and gross daily return matrices;
  - V1 equity curve and trade list;
  - meta.json with data, cost-model and code hashes;
  - a sha256 over the sorted outputs_v2 files.
- Data build: the TR file was rewritten at 01:29 SGT, after the v1 run at 01:25. Per §2, the 19 v1 trials are re-run on the current build (same 23-ETF symbol list as v1) for DSR/PBO. The `outputs/` (v1) files stay untouched.
- The extended 2005+ file (`bars/daily/extended/etf_total_return_spliced.parquet`) exists but is **not read** in this step. It is reserved for Stage B.
