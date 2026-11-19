# PRE-REGISTRATION (DRAFT): Macro-exposure diffusion (stock-level, sector-controlled)
`slug: macro-exposure-diffusion` · **Owner:** the derivatives researcher (Quant Researcher) · **Source:** original (not a paper replication) · **Written:** Fri 30 Oct 2026, ~02:30 SGT, **before any run on outcomes**
**Data pin:** v1.3 `d137eea…` + SIP methodology `5e0767…` (bars unchanged vs v1.2). SUE control not in v1.3 pin.
**Batch note:** TSC is **parked** this round (validator 2026-11-06); **MXD remains on the freeze path** subject to its own gates + SUE control.
**Status:** DRAFT **v0.8**, NOT frozen (2026-11-06 ~23:20 SGT; COMMON C13 applies the validator's FINAL SUE/C12 decision — borrow, capacity flag, span disclosure, DSR, SUE restrictions). v0.7 status (2026-11-06 ~22:35 SGT): Data pin v1.3 settled. LOO/sector code written + unit-tested, hash-freeze **proposed** (`mxd_signal.py` `ea312803…`, §10). Open: README v0.7 blocker list. v0.6/v0.5/v0.4 archived read-only in `../versions/`. (v0.5 status text: addressed the validator's final v0.4 decision and data owner TSC feasibility.)
**Binding companion:** `../COMMON.md`, including C8 data access (DESK_RULES #5), C9 input timestamps and C10 Addendum A checklist.

## 1. Hypothesis (falsifiable)
Some stocks carry a partial exposure to rates, the dollar, oil or gold *beyond* their market and own-sector exposure: rate-sensitive non-financials, dollar-sensitive multinationals, energy-cost users outside the energy sector. These stocks under-react to last month's moves in those macro assets. A stock's macro-implied return over the past month therefore predicts its return over the next month.
- **H3:** the V1 spread (top 30 predicted macro-implied return minus bottom 30) is positive.
- **Falsified if:** the Stage A gate fails, any hard bar in COMMON C6 is missed in Stage B, or the spread is negative. The opposite sign is not a separate trial.

## 2. Economic rationale
- **Who is on the other side.** Sector- and stock-specialist investors and analysts. They track firm and industry news but not cross-asset exposures that sit outside the stock's narrative (e.g. a REIT-like consumer name's rate duration, an industrial's dollar translation).
- **Why it persists.**
  - Limited attention and specialisation (the gradual-diffusion literature: Hong-Torous-Valkanov 2007, "Do industries lead stock markets?"; Cohen-Frazzini 2008, "Economic links").
  - The exposures are noisy and time-varying, so arbitrage is risky.
- **What is new.** The cross-asset partial betas come from liquid ETFs (TLT, UUP, USO, GLD), conditioned on SPY and the stock's own data-assigned sector ETF. This isolates exposures that sector rotation does not already carry.
- **Distinct from industry momentum and plain momentum.**
  - The sector-ETF control removes the industry channel by construction.
  - Feasibility (signals only, 2017-2022): mean rank correlation +0.152 with r21 (partly priced already, as expected), −0.035 with 12-1 momentum, +0.028 with low-vol.
- **Overlap with Maya's `oil-shock-energy-vs-discretionary`.** Maya's is an ETF-level oil-regime pair. Mine is a stock-level, sector-neutralised, every-month signal across four macro assets. Correlation with her sleeve will be reported. The validator decides whether this is the same family (question V4).

## 3. Exact rule
| Item | Rule |
|---|---|
| Universe | COMMON C1. Needs ≥ 240 valid daily returns in the 252-session window. |
| Sector assignment (PIT, no GICS) | For each stock at each signal date: SPY-residualise daily `ret_total_best` of the stock and of each sector SPDR {XLK XLF XLE XLV XLY XLP XLI XLU XLB XLRE XLC} over the trailing **252** sessions, using only ETFs with ≥ 240 valid obs in the window. The sector is the ETF with the highest residual correlation. This avoids the current-only GICS (null for former members). **XLC / XLRE breaks:** XLRE (2015-10) is eligible throughout Stage A; **XLC (first bar 2018-06-19) becomes eligible at the first month-end with ≥ 240 obs (mid-2019)**. The 2018-09 GICS reshuffle (media/internet names moved from XLK/XLY into XLC) and the XLC entry cause reassignment jumps; the number of names changing sector at those month-ends is reported (signal-only), not adjusted. |
| Sector regressor (leave-one-out; the validator) | `SECT_i,d` = **equal-weighted total return on day d of all other C1-universe stocks assigned to the same SPDR cluster on the signal date, excluding stock i** (not the SPDR's return, which contains the stock itself, e.g. ~20% AAPL in XLK). Clusters with < 5 other members fall back to the SPDR return (count reported). Signal-only diagnostic before freeze: for the 10 largest-weight SPDR constituents, the change in MXD rank vs the SPDR-regressor version. |
| Exposure regression | Daily OLS over the trailing **252** sessions: `r_i = a + b_m·SPY + b_s·SECT_i + Σ_k β_ik·r_k + e`, with k ∈ {**TLT, UUP, USO, GLD**} (total returns). |
| Macro move | `M_k` = Σ ln(1+r_k) over the last **21** sessions ending at the signal date. |
| Signal | `MXD_i = Σ_k β_ik · M_k` (the stock's macro-implied return over the last month, beyond market and sector). Higher → long. |
| Book / execution / holding | COMMON C2-C4. Long the top 30, short the bottom 30, 20% keep-band, monthly, **next-open MOO**, 1-month hold, stops and earnings blackout. **Long-short, dollar-neutral.** |

## 4. Expected turnover and costs (COMMON C7; the TCA owner's cost check; no returns used)
- **Rebalance turnover** (signal-only V1 book): **8.67/yr** of equity; keep-rate 0.377.
- **Early-exit add-on (TCA owner d):** 2 × p_U × 0.58 × keep × 12 with p_U = 1 − (1 − 20/63)(1 − 0.524) = 0.675 → **3.54/yr**. **T = 12.21/yr** (the TCA owner).
- **Drag:** 12.21 × 16.34 bps = 2.00% trading + 0.29% borrow (flat 1%) = **2.29% of equity/yr** = break-even gross. **2× bar:** gross ≥ **4.57%/yr on equity**.
- **My check (flagged):** pricing stop legs at max(TCA owner stop cost, floor) (19.32 bps weighted vs 16.34) adds ≈ +0.11 pp → drag ≈ 2.40%, 2× bar ≈ 4.79%. The TCA owner's numbers are the planning figures; the engine charges actual per-trade, per-bucket costs (lagged 20d ADV; MOO 1.0× half-spread, 1.5× impact; stop fills at the worse of stop and next price).
- **Borrow:** flat 1% primary (the validator); S4 = 10% HTB stress on names not ETB today/absent from the snapshot; S6a/S6b = the TCA owner's 25 / 100 bps (informational). Conflict between the TCA owner (25/100) and the validator (1%/10%) is noted in COMMON C7 for them to reconcile.
- **Sizing:** round-to-nearest shares; skip only at 0 shares or > 50% weight error; S5 = no-skip sensitivity.

## 5. Primary metric and pass/fail
- **Bars:** COMMON C6 on V1 Stage B daily net returns. Primary: OOS net Sharpe > 0.5, plus DSR ≥ 0.95, NW t ≥ 3.0, α t ≥ 3.0 (α ≥ 50% of raw), PBO < 0.20, > 0 at 2× costs, break-even ≥ 2×. Stage A gate: Stage A V1 net Sharpe (base costs, before the 0.74 haircut) > 0.68 and mean net L−S > 0.
- **Extra α controls (v0.4, in the Stage B gate):** (i) **own-asset returns (the validator):** daily total returns of TLT, UUP, USO and GLD, and each one's 21-day time-series momentum return sign(M_k,t−1 month-end)·r_k; (ii) **sector-ETF momentum series:** monthly L/S of the 3 highest minus the 3 lowest SPDRs (of those with ≥ 252 sessions) by trailing 21-session total return, equal weight, next-open fills, 1-month hold, gross; the reversal series is its negative and is not a separate regressor; (iii) my sector-momentum sleeve (`imom|imom_etf_ls|base|open|clean|2026-10-30 01:47`).

**Addendum A / data access (added 2026-10-30 ~02:15 SGT, before any run).**
- Every input and its first-availability time (ET) and first affected session is in COMMON C9. All signal inputs are SIP daily bars of session t, known after the ~16:20 ET finalisation, so they **trade at the t+1 open at the earliest**.
- No text, sentiment or LLM input is used.
- History is read only from the data owner's store. Any live market-data call goes only via `data/lib/desk_data_client.py` (COMMON C8).
- Incremental α is tested over FF5 + Mom + ST_Rev + in-universe momentum and reversal + the **desk-wide PIT earnings-surprise controls**: (a) SPY-adjusted announcement return from the close before `reaction_session` to the close of `reaction_session`+1, and (b) SUE from **8-K EX-99.1 GAAP diluted EPS at τ**, with XBRL 10-Q/10-K EPS as a logged fallback (COMMON C9). Both controls are monthly deciles (this idea rebalances monthly). Months with fewer than 300 SUE names drop out of the regression; > 10% of Stage B months dropped caps the verdict at CONDITIONAL. **Binding inputs: the data-owner-promoted, hashed `data/derived/` event and SUE files, frozen before Stage A.** Plus my sleeves. **The gate is on Stage B; the full history is reported alongside** (COMMON C6 #5).
- **Verdict ceiling: CONDITIONAL PASS.** Stage B (2023-26) is not blind; the clean test is paper probation of 60+ trades or 3 months (COMMON C5). VIX comes only from the pinned store file (sha 5ec8bca2…); insufficient VIX evidence FAILS criterion 7 (C6 #7, v0.4).

**v0.4 binding gate and controls (supersede the bullets above where they differ; COMMON C6).**
- **Stage A gate:** Stage A V1 net Sharpe (base costs, before the 0.74 haircut) **> 0.68 and mean net L−S > 0**; a miss stops the idea.
- **Stage B:** all of COMMON C6 #1-#9, including the rebalance count (≥ 30 executed Stage B rebalances, else FAIL), the per-trade 1%-ADV capacity check, and more than 2 soft flags → FAIL. NW t on the full history is reported incl. and excl. 2022.
- **VIX:** from `data/sentiment/vix/vix_vix3m_daily_20261030.parquet` (sha256 `5ec8bca2…6235b2`), `is_xnys_session` rows, day t classified by the t−1 VIX close. Insufficient VIX evidence = **FAIL of criterion 7** (not a cap).
- **α controls on Stage B:** FF5 + Mom + ST_Rev + in-universe 12-1 momentum and 1-month reversal deciles + announcement-return and SUE deciles (COMMON C9) + BAB sleeve `bab|bab_fp|base|open|clean|2026-10-30 01:47` + sector-momentum sleeve `imom|imom_etf_ls|base|open|clean|2026-10-30 01:47`, plus the hypothesis-specific controls below.
- **MXD-specific reports:** share of V1 gross P&L from the USO term by sub-period (Stage A pre/post 2020-04 USO restructuring; Stage B), and V1 without the USO term (diagnostic, §13).

## 6. Fixed variant list (22 runs; family N = 393, COMMON C11)
| ID | Variant | Role |
|---|---|---|
| V1 | Spec above | **primary** |
| V2 | Factor diagnostic: EW quintile L/S, 50/50 gross, no stops/blackout/rounding | signal vs implementation |
| V3 | V1, MOC fill at the next session's close | venue |
| V4 | V1 long leg only + SPY short hedge | long-only usability |
| V5 | Signal = MXD minus the stock's own 21d SPY-and-sector-residual return (the "un-priced gap" form) | tests the under-reaction channel directly |
| R1-R2 | macro window 21 → 17 / 25 | §7 |
| R3-R4 | beta window 252 → 202 / 302 (R4 Stage A from its first full-history month; **Stage B starts 2023-03-31 for all variants** so R4's window never reaches before 2022-01-03) | §7 |
| R5-R6 | keep-band 20% → 16% / 24% | §7 |
| R7-R8 | names per leg 30 → 24 / 36 | §7 |
| R9-R10 | joint −20% / +20% | §7 |
| S1 | delisting stress: 0% for all unmatched delistings (primary: −30%, listed failures −100%; COMMON C2) | data stress |
| S2 | stops disabled (H6 effect; not tradable) | implementation stress |
| S3 | V1 at 2× costs and 2× borrow (C6 #2) | cost stress, counted (validator decision 2) |
| S4 | V1 with 10%/yr borrow on names not ETB in today's asset snapshot or absent from it (also the today's-flags sensitivity) | borrow stress, counted |
| S5 | V1 with no skipping in share rounding (TCA owner c) | sizing sensitivity, counted |
| S6a / S6b | V1 with the TCA owner's borrow 25 bps / 100 bps on all shorts (informational) | counted (conservative) |
**Counted configs = 18** (V1–V5, R1–R10, S1, S2, S5). S3/S4/S6a/S6b cost-only per C11. **DSR N = 393.**

## 7. Train / test split
COMMON C5 (v0.4). Stage A signal dates 2016-12-30 .. 2021-11-30 (R4 from its first full-history month). Embargo holdings 2022-01-03 .. 2023-03-31, never evaluated. **Stage B signal dates 2023-03-31 .. 2026-09-30 (43 rebalances; holdings 2023-04-03 → 2026-10-28), sealed, run once.**

## 8. Data
- **In the store (all from 2016):** SIP TR for TLT, UUP, USO, GLD, SPY and the 11 SPDRs; stock TR. XLRE starts 2015-10 and XLC 2018-06; both are handled by the ≥ 240-obs rule.
- **Coverage:** H3 is computable for 494-504 names per month in IS (mean 499.7).
- **No extra data needed.**
- **Data reference:** as in close-vwap-accumulation §8 (v1.1 drafting reference; **binding pin now v1.3**, COMMON C8).

- **v0.4 release cited:** the data owner's v1.2 (`8972e558…`, incl. raw bars `9ef7d734…`); binding pin `<DATA_RELEASE_ID>` pending the data owner (COMMON C8).
- (v0.4 text, superseded:) Data release to cite: `<DATA_RELEASE_ID>` placeholder; derived controls `<EVENTS_*>`, `<SUE_*>`.
- **Data release to cite (v0.7, current):** v1.3 top `d137eea39928ec8d27b4e8ace5266c01bf74a81ca7e6d07a9d84f9a71b6dc13a` + SIP methodology `5e0767ce…` + QA `23cb8be3…` (COMMON C8). Derived controls: events = v1.3 `edgar_8k_202` `d0735831…` / `earnings_events` `83feda17…` (sentiment researcher v1/v2 unused); SUE = **draft** `sue_v0.6_draft` (`derived/out/SUE_MANIFEST.json`), **not frozen, not promoted** — `<SUE_VERSION>/<SUE_SHA>` remain placeholders until validator review + data owner promotion.

**v0.5 MXD implementation freeze items (before Stage A):** hash-freeze LOO regressor code, sector-assignment tie-break, <5 cluster fallback, and rank diagnostic vs SPDR regressors. “V1 without USO” is signal-only unless return-tested (+1 N). Proceeds independently of TSC ticks.

## 9. Caveats
- **LOO scope (validator v0.4 §3):** LOO removes stock i from its sector **regressor** only; the sector **assignment** still correlates i against SPDRs that contain i (e.g. AAPL in XLK). Not quantified yet: the assignment-contamination count (names whose assigned SPDR changes when i's own weight is removed) needs SPDR holdings weights, which are not in v1.3 (same data gap as the top-10 diagnostic).
- **Cluster membership timing:** memberships fixed at formation date t are applied to every day d of the 252-session window; they are known at t (no look-ahead for the t+1 trade) but are **not** the historical memberships at d.
- **Own-asset momentum control:** sign(M_k) uses only the 21 sessions ending at the prior formation date; this is spec text, and a code test is still to be written with the Stage A control code (not part of the signal module).
- **XLC/XLRE and the 2018-09 GICS reshuffle:** see §3; reassignment counts reported.
- **Own-asset momentum:** the macro ETFs' own trend is now a gate control (§5), so MXD must add α beyond simply riding TLT/UUP/USO/GLD momentum.
- **USO break.** USO changed its roll and contract mix in Apr-May 2020 and did a 1:8 reverse split. That is a structural break inside Stage A for the oil beta. It is disclosed, not adjusted (the validator's decision on Maya's oil idea).
- **Partly seen data.** I know the 2022 rates shock (embargo year) and the 2023-26 macro path in broad terms.
- **Estimation noise.** Betas from 252 daily obs with 7 regressors are noisy. No shrinkage is applied (shrinkage would be a new trial).

## 10. Change log
- 2026-11-06 ~23:20 SGT, v0.8 (text only, no runs): applied validator FINAL decision the internal review record (sha256 `66e0c4a6…aa4e2`) via COMMON C13 — borrow resolved (1% primary + 10% S4 pass bar; TCA owner informational), ≤1% ADV capacity evidence + 5%-of-1-min/opening-auction flags, evaluated span 8.583 y disclosed, DSR N = 393 with PEAD OOS caveat and larger-SR₀ gate, SUE P1 draft restrictions (A0 pending data owner manifest; A1 before any returns). SPDR: the all-name rank diagnostic 0.8689 is supplemental only; the registered top-10-weight diagnostic stays BLOCKED (holdings). No parameter, grid, trial or embargo change.
- 2026-11-06 ~22:35 SGT, v0.7 (text only, no runs): stale `<DATA_RELEASE_ID>` text marked superseded (kept); current data/SUE citation; LOO-scope, membership-timing and own-asset-momentum caveats added (validator v0.4 §3 MXD); procedures now frozen in COMMON v0.7.
- 2026-11-06 ~22:15 SGT, v0.6 (pre-freeze, no returns): **LOO/sector code written and unit-tested** — `mxd_signal.py` sha `ea312803e57cffebf96219941f7794a74b819a0140fdf07a43c3d7ef7edd1d3f`, `test_mxd_signal.py` sha `f8c98be4ba1d6e54ac1d4dec57f3e44fe243dcfd35f376f227d39b36eed30556` (synthetic data: LOO excludes own return, <5-other fallback to SPDR, XLC ≥240-obs rule, tie-break = first ETF in fixed SECT order, planted β recovered, appending future rows leaves the signal unchanged). Frozen choices are in the module docstring. Signal-only smoke run on v1.3 at 2021-11-30 (`../prefreeze_checks/cva_mxd_input_checks.py` sha `cf365f0c2c41fe5bd2605657a41bedc6b5a4553b65a6e77d09914c272507655a`, output sha `25c3afeccebe7468774c16b4695d7a8b202b147c88de8cc57cc1c1c151d5644e`, bars filtered at load ≤ 2021-12-31): 503 names, 0 unassigned, 0 fallback, 11 clusters; LOO vs SPDR-regressor MXD rank correlation 0.8689, median |Δrank| 0.0457. **The PREREG diagnostic for the "10 largest-weight SPDR constituents" cannot be run as written: SPDR holdings weights are not in v1.3** (data owner data item or validator-approved substitute). Hash-freeze proposed at these hashes; the validator to accept.
- 2026-11-06 ~06:50 SGT: cite v1.3 + SIP methodology; MOO hierarchy via COMMON C2.
- 2026-11-06 ~06:45 SGT: TSC parked by the validator; this idea continues on freeze path.
- 2026-11-06, v0.5: validator final decision — N=393; USO re-rank +1 if return-tested; LOO/sector code to hash-freeze; independent of TSC panel. No backtest.
- 2026-10-30 02:28-02:45 SGT, v0.4: the validator's line-by-line review + the TCA owner's cost check. Own-asset returns and 21d TS-momentum of TLT/UUP/USO/GLD in the α regression; sector-ETF momentum series defined; leave-one-out sector regressor; XLC/XLRE and 2018 GICS break handling; USO sub-period P&L share; Stage B start 2023-03-31 (R4 lookback); S4-S6b; costs per the TCA owner (T 12.21, drag 2.29%, 2× bar 4.57%) with my flag; runs 22; family N = 393. v0.2 change-log line restored to "family N = 328". Still draft; no runs.
- 2026-10-30 ~02:25 SGT, v0.3: the validator's second decision. N verified against TRIAL_LOG and raised to 390 (2 FF49 constructions + 60 non-identical reruns added back); primary SUE from 8-K EX-99.1 GAAP diluted EPS at τ, with XBRL fallback (share logged); monthly-decile controls; coverage rule (< 300 names → month dropped; > 10% of Stage B → CONDITIONAL cap); controls frozen before Stage A; data owner promotion path and data-release placeholder. Still draft; no runs.
- 2026-10-30 ~02:20 SGT, v0.2: the validator's interim decisions 1-7 (primary = 30/30 book; S3 2×-cost run added as a trial; family N = 328; ceiling CONDITIONAL PASS + paper probation; Stage-B α gate; desk SUE/8-K controls; VIX from the data owner's store only). Still a draft; no runs.
- 2026-10-30 ~02:15 SGT: Addendum A compliance (C9 timestamps, SUE control, C8 data access per DESK_RULES #5). Draft stage, before sign-off, so not a trial.
- 2026-10-30 ~02:30 SGT: v0 draft.

## 13. Family and overlap disclosure (validator decision 4)
*(Numbered §13 as validator requested; §11-12 are intentionally unused.)*
- **Separate family from Maya's `oil-shock-energy-vs-discretionary`** (validator decision 4). This idea's trials count in the desk PIT-equity family (COMMON C11), not in Maya's macro-ETF family.
- **Overlap disclosed:**
  - Both use USO 21-day returns as an oil-shock input.
  - Both are exposed to the same oil episodes (2020 crash and USO restructuring, 2022 spike in the embargo, 2025 tariff shock).
  - My short and long legs will load on energy-cost users vs producers outside XLE whenever oil moves.
  - I have read Maya's PREREG and her verdict status (registry), but none of her return series.
- **Reported at Stage B:**
  - the daily correlation of V1 with Maya's oil sleeve, if her sleeve's series exists;
  - V1 with the USO term removed (diagnostic only, not a new trial; computed from the same run's β·M decomposition);
  - the share of V1 P&L attributable to the USO term.
- If correlation with her sleeve is > 0.5, the desk treats the two as one risk allocation.

