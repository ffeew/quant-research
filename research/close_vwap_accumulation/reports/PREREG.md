# PRE-REGISTRATION (DRAFT): Close-above-VWAP accumulation
`slug: close-vwap-accumulation` · **Owner:** the derivatives researcher (Quant Researcher) · **Source:** original (not a paper replication) · **Written:** Fri 30 Oct 2026, ~02:20 SGT, **before any run on outcomes**
**Batch note:** TSC is **parked** this round (validator 2026-11-06); **CVA remains on the freeze path** subject to its own gates + SUE control.

**Status:** DRAFT **v0.8**, NOT frozen (2026-11-06 ~23:20 SGT; COMMON C13 applies the validator's FINAL SUE/C12 decision — borrow, capacity flag, span disclosure, DSR, SUE restrictions). v0.7 status (2026-11-06 ~22:35 SGT): Data pin v1.3 + SIP methodology settled (validator SIP decision). Open: COMMON README v0.7 blocker list (delisting map, borrow conflict, SUE review/promotion, C12 questions). v0.6/v0.5/v0.4 archived read-only in `../versions/`. (v0.5 status text: addressed the validator's final v0.4 decision and data owner TSC feasibility.)
**Binding companion:** `../COMMON.md`, including C8 data access (DESK_RULES #5), C9 input timestamps and C10 Addendum A checklist (universe, execution, LIMITS book, earnings blackout, split, pass bars, cost inputs). Where this file and COMMON disagree, this file wins for H1-specific items only.

## 1. Hypothesis (falsifiable)
Over a month, some stocks keep closing above their own daily VWAP, beyond what their intraday drift explains. These stocks earn higher returns over the next month than stocks that keep closing below VWAP.
- **H1:** the long-minus-short spread of V1 (top vs bottom ranked names) is positive.
- **H0 / falsified if:** any of the following holds:
  - the Stage A gate fails (COMMON C5);
  - Stage B V1 net Sharpe ≤ 0.5, or any hard bar in COMMON C6 is missed;
  - the Stage B spread is negative.
- **The opposite sign is NOT a separate trial.** A significantly negative result (late-day pressure reverting) is a FAIL of this hypothesis. It could become a new hypothesis only on future paper data.

## 2. Economic rationale (who is on the other side, why it persists)
- **Mechanism.** Informed or conviction buyers work large parent orders over days. They lean on the afternoon and the close when they want completion, so the price ends the day above the session's volume-weighted average. A one-day close-above-VWAP is noise (auction dislocations revert, per Bogousslavsky-Muravyev in the TCA owner's §3). A *persistent* month-long footprint is a cumulative order-flow imbalance that the daily close-to-close return does not show. If the metaorder carries information, its permanent impact is incomplete while it is still being worked, so prices keep drifting.
- **Other side.**
  - Liquidity providers and intraday mean-reversion traders who sell into the late-day bid.
  - Passive and benchmark sellers whose flows are uninformed and unconcerned with price within the day.
- **Why it persists.**
  - It is a slow, low-signal-to-noise statistic in large caps. Capturing it requires holding across weeks, which is unattractive to high-frequency liquidity providers.
  - It is not a standard academic factor. The nearest relatives are the technical "accumulation/distribution" and close-location-value indicators, which use the high-low range rather than VWAP, and market-level intraday momentum (Gao-Han-Li-Zhou 2018). Neither is a cross-sectional VWAP footprint.
- **Why it should be distinct from momentum, low vol and industry momentum.**
  - The signal is residualised on the 21d return, the 21d intraday (open→close) drift and 63d vol.
  - Feasibility (signals only, 2017-2022, `../feasibility/feasibility_results.json`) shows mean cross-sectional rank correlations of +0.044 with 12-1 momentum, +0.010 with low-vol (−σ63) and −0.023 with r21.

## 3. Exact rule
| Item | Rule |
|---|---|
| Universe | COMMON C1 (PIT S&P 500, raw close > $5, defect exclusions, earnings-coverage eligibility). Needs ≥ 63 sessions of history. |
| Daily footprint | `d_i,t = ln(close_raw_i,t / vwap_raw_i,t)` from the same SIP daily bar. Both are raw, so it is split-invariant. `zero_volume` rows are masked. |
| Monthly raw signal | `CVA_i = mean(d_i,t)` over the last **21** sessions ending at the signal date (≥ 18 valid). |
| Controls | `ICO_i` = mean ln(close/open) over the same 21 sessions (intraday drift); `r21_i` = Σ ln(1+ret_total_best) over 21 sessions; `lnσ_i` = ln(std of daily ret_total_best over **63** sessions). |
| Signal | Cross-sectional OLS residual of CVA on [1, ICO, r21, lnσ] on the signal date. Higher = stronger accumulation. |
| V5 sector code | The correlation-based sector assignment is the **same code file as MXD §3** (incl. the XLC rule), hashed at the Stage A code freeze. |
| Ranking / weighting / legs | COMMON C3: long the 30 highest, short the 30 lowest, 0.967% equity each, keep-band 20%, whole shares, stops, H8/H9 gates. |
| Rebalance / execution | Monthly. Signal after the close of the month's last session; **fill at the next session's open (MOO)**. |
| Holding period | 1 month, or until a stop or the earnings-blackout exit (COMMON C4). |
| Long-only vs long-short | **Long-short, dollar-neutral** (V1). A long-only version is diagnostic V4. |

## 4. Expected turnover and costs (COMMON C7; the TCA owner's cost check; no returns used)
- **Rebalance turnover** (signal-only V1 book): **9.60/yr** of equity; keep-rate 0.310.
- **Early-exit add-on (TCA owner d):** 2 × p_U × 0.58 × keep × 12 with p_U = 1 − (1 − 20/63)(1 − 0.524) = 0.675 → **2.91/yr**. **T = 12.51/yr** (the TCA owner).
- **Drag:** 12.51 × 16.34 bps = 2.04% trading + 0.29% borrow (flat 1%) = **2.33% of equity/yr** = break-even gross. **2× bar:** gross ≥ **4.67%/yr on equity**.
- **My check (flagged):** pricing stop legs at max(TCA owner stop cost, floor) (19.32 bps weighted vs 16.34) adds ≈ +0.11 pp → drag ≈ 2.44%, 2× bar ≈ 4.89%. The TCA owner's numbers are the planning figures; the engine charges actual per-trade, per-bucket costs (lagged 20d ADV; MOO 1.0× half-spread, 1.5× impact; stop fills at the worse of stop and next price).
- **Borrow:** flat 1% primary (the validator); S4 = 10% HTB stress on names not ETB today/absent from the snapshot; S6a/S6b = the TCA owner's 25 / 100 bps (informational). Conflict between the TCA owner (25/100) and the validator (1%/10%) is noted in COMMON C7 for them to reconcile.
- **Sizing:** round-to-nearest shares; skip only at 0 shares or > 50% weight error; S5 = no-skip sensitivity.

## 5. Primary metric and pass/fail
As COMMON C6, on **V1 Stage B daily net returns**. Primary metric: OOS annualised net Sharpe > 0.5, with DSR ≥ 0.95, NW t ≥ 3.0, incremental α t ≥ 3.0 (α ≥ 50% of raw), PBO < 0.20 (≤ 0.05 for PASS), > 0 at 2× costs, break-even ≥ 2× cost. Stage A gate: Stage A V1 net Sharpe (base costs, before the 0.74 haircut) > 0.68 and mean net L−S > 0.

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
- **CVA-specific:** none beyond the above; V6 (month-end-excluded footprint) is reported side by side.

## 6. Fixed variant list (counts toward N; nothing else will be run)
| ID | Variant | Role |
|---|---|---|
| V1 | Spec above | **primary** |
| V2 | Factor diagnostic: EW quintile L/S, 50/50 gross, no stops/blackout/rounding, next-open | signal vs implementation |
| V3 | V1, fills at the next session's **close** (MOC, the TCA owner `venue="close"`) | venue side-by-side (the TCA owner §3) |
| V4 | V1 long leg only + SPY short hedge of equal $ (29%/29%) | long-only usability |
| V5 | V1 with the residual ranked within the correlation-assigned sector-ETF cluster (as in macro-exposure-diffusion §3) | industry-neutrality check |
| V6 | V1 with the footprint and ICO computed over the month's sessions **excluding its last two sessions** (19 sessions, ≥ 16 valid), to remove month-end/index-rebalance closing flows (the validator) | counted trial | **v0.5 window (binding):** mean over last **21 NYSE sessions** ending on the signal date, **excluding the final 2** (sessions t−20..t−2); not calendar-month-minus-two. ~~Auction source for minute VWAP still open~~ — superseded by the SIP decision: V6 uses the same daily eligible-trade `vwap_raw`/`close_raw` as V1; no minute VWAP, no auction-print claim, no last-regular-trade substitute.
| R1-R2 | footprint window 21 → 17 / 25 | §7 ±20% |
| R3-R4 | vol-control lookback 63 → 50 / 76 | §7 |
| R5-R6 | keep-band 20% → 16% / 24% | §7 |
| R7-R8 | names per leg 30 → 24 / 36 (per-name weight rescaled to keep 58% gross) | §7 |
| R9-R10 | joint −20% / +20% on all four | §7 |
| S1 | delisting stress: 0% for all unmatched delistings (primary: −30%, listed failures −100%; COMMON C2) | data stress |
| S2 | stops disabled (H6 effect; not tradable) | implementation stress |
| S3 | V1 at 2× costs and 2× borrow (C6 #2) | cost stress, counted (validator decision 2) |
| S4 | V1 with 10%/yr borrow on names not ETB in today's asset snapshot or absent from it (also the today's-flags sensitivity) | borrow stress, counted |
| S5 | V1 with no skipping in share rounding (TCA owner c) | sizing sensitivity, counted |
| S6a / S6b | V1 with the TCA owner's borrow 25 bps / 100 bps on all shorts (informational) | counted (conservative) |
**Counted configs = 19** (V1–V6, R1–R10, S1, S2, S5). S3/S4/S6a/S6b cost-only per C11. **DSR N = 393.**

## 7. Train / test split
COMMON C5 (v0.4). Stage A signal dates 2016-12-30 .. 2021-11-30. Embargo holdings 2022-01-03 .. 2023-01-31, never evaluated. **Stage B signal dates 2023-01-31 .. 2026-09-30 (45 rebalances; holdings 2023-02-01 open → 2026-10-28), sealed, run once** with the other surviving specs; the start is set so that no Stage B input (longest lookback: V5's 252-session sector assignment) predates 2022-01-03. Ceiling CONDITIONAL PASS, then paper probation of 60+ trades or 3 months.

## 8. Data
- **In the store:** SIP daily raw bars (`close`, `open`, `vwap`, `volume`, `zero_volume`), `ret_total_best`, PIT membership, Nasdaq calendar (blackout only), FF factors, `delisting_returns`, asset snapshot (shortability, today only).
- **Coverage:** in the IS feasibility the H1 signal was computable for 498-504 names per month (mean 502.3).
- ~~Possible extra: regular-session VWAP (1-min SIP bars)~~ — **not needed** (validator SIP decision: daily eligible-trade VWAP excludes T/U/I; V1 locked to it).
- **Data reference at drafting:** `data/VERSION` = `v1.1 6e6353ec9dab861c1e95595cb9cef21d4a2370cb419a46ef1aca5185cd5fa7d1` (2026-10-30T01:50:54+08:00). SHA256 hashes:
  - `daily_total_return.parquet` 0590692d…a129db
  - raw-bars dir (sha256 of sorted per-file sha256s) 39d0fa3e…0450045
  - membership d3e01d89…c33763
  - nasdaq_calendar a4acfed5…399707
- **v0.4 release cited:** the data owner's v1.2 (`8972e558…`, incl. raw bars `9ef7d734…`); binding pin `<DATA_RELEASE_ID>` pending the data owner (COMMON C8). The v1.1 hashes above are the drafting reference only.
- (v0.4 text, superseded:) Data release to cite: `<DATA_RELEASE_ID>` placeholder; derived controls `<EVENTS_*>`, `<SUE_*>`.
- **Data release to cite (v0.7, current):** v1.3 top `d137eea39928ec8d27b4e8ace5266c01bf74a81ca7e6d07a9d84f9a71b6dc13a` + SIP methodology `5e0767ce…` + QA `23cb8be3…` (COMMON C8). Derived controls: events = v1.3 `edgar_8k_202` `d0735831…` / `earnings_events` `83feda17…` (sentiment researcher v1/v2 unused); SUE = **draft** `sue_v0.6_draft` (`derived/out/SUE_MANIFEST.json`), **not frozen, not promoted** — `<SUE_VERSION>/<SUE_SHA>` remain placeholders until validator review + data owner promotion.

## 9. Known risks / caveats
- **Closing-auction inclusion:** the daily eligible-trade `vwap`/`close` are vendor fields, not official auction prints (SIP methodology; aggregator vintage UNKNOWN, disclosed); the old §3 branches are superseded; V6 removes the last two sessions of each month (month-end and index-rebalance auctions).
- **Closing auction share.** It grew from 3% to more than 7.5% of volume over 2010-2018 and is higher since. A secular rise in MOC volume raises close-vs-VWAP dispersion for index-heavy names. Cross-sectional ranking removes the common part only.
- **Look-ahead in shortability** (today's ETB flags) and in the blackout dates (realised Nasdaq dates).

## 10. Change log
- 2026-11-06 ~23:20 SGT, v0.8 (text only, no runs): applied validator FINAL decision the internal review record (sha256 `66e0c4a6…aa4e2`) via COMMON C13 — borrow resolved (1% primary + 10% S4 pass bar; TCA owner informational), ≤1% ADV capacity evidence + 5%-of-1-min/opening-auction flags, evaluated span 8.75 y disclosed, DSR N = 393 with PEAD OOS caveat and larger-SR₀ gate, SUE P1 draft restrictions (A0 pending data owner manifest; A1 before any returns). No parameter, grid, trial or embargo change.
- 2026-11-06 ~22:35 SGT, v0.7 (text only, no runs): stale minute-VWAP / `<DATA_RELEASE_ID>` / auction-branch text marked superseded (kept); current data/SUE citation added; execution, stop, NW/PBO/DSR, VIX and rebalance-count procedures now frozen in COMMON C2/C3/C6/C11 v0.7 (H3 = no-trade).
- 2026-11-06 ~22:15 SGT, v0.6 (pre-freeze, no returns): signal-input check on v1.3 (`../prefreeze_checks/cva_mxd_input_checks.py` sha `cf365f0c2c41fe5bd2605657a41bedc6b5a4553b65a6e77d09914c272507655a`; Stage A dates only, bars filtered at load ≤ 2021-12-31): 971,797 stock bars, 927 zero-volume rows masked, 0 invalid close/vwap, **0 rows with vwap outside [low, high]**; 60 signal months, members with ≥ 18 valid d over 21 sessions mean 502.9 (min 501, **before** the remaining C1 filters); MOO H2 daily open present on the next session for all but **6** name-months (H3 cases). No extra data module (validator SIP decision). V5 sector code = `../macro-exposure-diffusion/mxd_signal.py` sha `ea312803e57cffebf96219941f7794a74b819a0140fdf07a43c3d7ef7edd1d3f`.
- 2026-11-06 ~06:50 SGT: SIP/VWAP/MOO decision — lock eligible-trade daily VWAP/close; MOO H1/H2/H3; no RTH minute module for V1; v1.3 pin.
- 2026-11-06 ~06:45 SGT: TSC parked by the validator; this idea continues on freeze path.
- 2026-11-06, v0.5: validator final decision — N=393 (V6 counts; S3/S4/S6 cost-only); V6 window clarified; auction source still external. No backtest.
- 2026-10-30 02:28-02:45 SGT, v0.4: the validator's line-by-line review + the TCA owner's cost check. VWAP/auction branches pre-specified (blocker with the data owner); V6 (last-two-sessions excluded) added as a counted trial; S4-S6b added; Stage B start moved to 2023-01-31 (no input before 2022-01-03); costs per the TCA owner (T 12.51, drag 2.33%, 2× bar 4.67%) with my +0.11 pp stop-leg flag; flat 1% borrow + 10% HTB stress; round-to-nearest sizing; −30% unmatched delistings (S1 = 0%); VIX FAIL rule; rebalance-count and per-trade capacity gates; runs 23; family N = 393. v0.2 change-log line restored to its original "family N = 328" (v0.3 had overwritten it). Earlier entries' "~" times are approximate; true per-version mtimes/hashes are in README. Still draft; no runs.
- 2026-10-30 ~02:25 SGT, v0.3: the validator's second decision. N verified against TRIAL_LOG and raised to 390 (2 FF49 constructions + 60 non-identical reruns added back); primary SUE from 8-K EX-99.1 GAAP diluted EPS at τ, with XBRL fallback (share logged); monthly-decile controls; coverage rule (< 300 names → month dropped; > 10% of Stage B → CONDITIONAL cap); controls frozen before Stage A; data owner promotion path and data-release placeholder. Still draft; no runs.
- 2026-10-30 ~02:20 SGT, v0.2: the validator's interim decisions 1-7 (primary = 30/30 book; S3 2×-cost run added as a trial; family N = 328; ceiling CONDITIONAL PASS + paper probation; Stage-B α gate; desk SUE/8-K controls; VIX from the data owner's store only). Still a draft; no runs.
- 2026-10-30 ~02:15 SGT: Addendum A compliance (C9 timestamps, SUE control, C8 data access per DESK_RULES #5). Draft stage, before sign-off, so not a trial.
- 2026-10-30 ~02:20 SGT: v0 draft.
