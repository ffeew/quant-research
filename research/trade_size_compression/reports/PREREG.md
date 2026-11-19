# PRE-REGISTRATION (DRAFT): Trade-size compression (retail-attention crowding)
`slug: trade-size-compression` · **Owner:** the derivatives researcher (Quant Researcher) · **Source:** original (not a paper replication) · **Written:** Fri 30 Oct 2026, ~02:25 SGT, **before any run on outcomes**
**Status:PARKED** this batch (validator 2026-11-06). Spec retained as draft shelf text; **not freezing; no Stage A/B returns; no tick backfill.** Decision: the internal review record. Reason: full tick panel not feasible; narrowing now would change the hypothesis/signed-control and add trials. 0.74 haircut + signed-control obligation preserved for future unpark; all-size proxy auxiliary only. CVA/MXD proceed independently.

> **PARKED (validator 2026-11-06):** no freeze, no Stage A/B, no tick backfill this batch. See `../validation` decision `2026-11-06-tsc-bounded-input-feasibility.md`. Historical N rows preserved.
**Binding companion:** `../COMMON.md`, including C8 data access (DESK_RULES #5), C9 input timestamps and C10 Addendum A checklist.

## 1. Hypothesis (falsifiable)
When a stock's average dollar trade size falls sharply against its own past year, after controlling for its price change, volume surge and recent return, small (retail-sized) orders are crowding into it. Such stocks underperform over the next month. Stocks whose average trade size rises (institutional participation) outperform.
- **H2:** the V1 long (highest signal = trade size *rising*) minus short (largest *compression*) spread is positive.
- **Falsified if:** the Stage A gate fails, any hard bar in COMMON C6 is missed in Stage B, or the spread is negative. The opposite sign is not a separate trial.

## 2. Economic rationale
- **Who is on the other side.**
  - Attention-driven retail buyers. Zero-commission apps since Oct 2019 and fractional shares concentrate them on salient names.
  - Their flow lowers the average print size before it shows up in returns or turnover rankings.
  - Literature: retail buying is attention-driven (Barber-Odean 2008), and heavy small-trade buying predicts poor returns at longer horizons (Barber-Odean-Zhu 2009). Those papers need signed TAQ trades.
- **What is new here.**
  - The signal uses only SIP daily `volume × vwap / trade_count`, which needs no trade signing. It treats a shift in the *composition* of trade sizes toward small orders as a crowding measure.
  - **Prior art (disclosed, validator 02:35): Hvidkjaer (2008, RFS, "Small Trades and the Cross-Section of Stock Returns")** shows that small-trade buy-initiated imbalance predicts low future returns. TSC is therefore not unpublished in spirit. My variant differs (unsigned, from daily SIP aggregates, trade-size composition rather than signed imbalance, S&P 500 only), but validator keeps the **0.74 haircut** and requires a small-trade order-imbalance control (§5).
- **Why it persists.**
  - Retail flow is sticky and sentiment-driven.
  - Short-selling attention stocks is risky (squeezes) and capacity-limited, so arbitrageurs under-correct.
  - In S&P 500 names the effect should be smaller than in small caps but cheaper to trade.
- **Distinct from momentum and low vol.**
  - Dollar trade size mechanically scales with price, because share lots are sticky. An earlier, **unlogged** interactive check of the raw measure showed a +0.455 rank correlation with 12-1 momentum; it is now logged in `../FORKING_PATHS.md` (it motivated the PCHG control).
  - **v0.4 recompute with the fixed code** (`../feasibility/feasibility_tsc_v04.py`: VWAP-based ATS, base window t−252..t−22, ratio-jump split rule; Stage A signal dates only; signal statistics only): mean rank correlation of the residual signal **+0.006 with 12-1 momentum, +0.084 with low-vol, −0.001 with r21, +0.002 with PCHG**, +0.542 with the raw TSC; 60 Stage A month-ends, 476-486 names per month (C1 table).

## 3. Exact rule
| Item | Rule |
|---|---|
| Universe | COMMON C1. Needs ≥ 252 sessions of history. **Also excludes** any name with a split ex-date (`corporate_actions/splits.parquet`) in the trailing 252 sessions, or a raw/adjusted close-ratio jump > 20% in one day in that window (this catches splits missing from the CA feed). Splits mechanically change per-trade size. |
| Daily trade size | `ATS_i,t = volume_raw_i,t × vwap_raw_i,t / trade_count_i,t` (USD per trade); masked on `zero_volume`. |
| Raw signal | `TSC_i = ln( median(ATS, last 21 sessions) / median(ATS, sessions t−252..t−22) )` |
| Controls | `PCHG_i` = ln(median raw close over the last 21 sessions / median raw close over t−252..t−22). `ABV_i` = ln(ADV$_20 / mean daily $volume over t−252..t−22). `r21_i` as in COMMON. `lnP_i` = ln(raw close_t), because odd-lot share rises with price. |
| Signal | Cross-sectional OLS residual of TSC on [1, PCHG, ABV, r21, lnP]. Higher = trade size rising relative to peers → long. |
| Price-tier break rule (odd-lot / round-lot changes; causal) | Each month-end, median ATS21 is computed per raw-price tier (< $25, 25-50, 50-100, 100-250, ≥ 250) over PIT members. A tier is **flagged** when its monthly Δln(median ATS21) minus the cross-tier median Δln exceeds 0.25 in absolute value. Names in a flagged tier are **excluded from TSC ranking at that month-end and the next** (2 rebalances). Uses only data ≤ t, so it runs identically in Stage A and B. Stage A check (run 02:27, signal-only): one flag, 2020-03-31, tier < $25 (−0.294). Stage B additionally reports V1 with and without months from 2025-11 (SEC round-lot redefinition) as a diagnostic, not a trial. |
| Splits | Split ex-date (known_as_of ≤ t) in the trailing 252 **sessions**, or a > 20% one-day jump in raw/adjusted close in t−252..t → excluded (v0.3 feasibility used 366 calendar days; fixed). |
| Book / execution / holding | COMMON C2-C4. Long the top 30, short the bottom 30, 20% keep-band, monthly, **next-open MOO**, 1-month hold, stops and earnings blackout. **Long-short, dollar-neutral.** |

## 4. Expected turnover and costs (COMMON C7; the TCA owner's cost check; no returns used)
- **Rebalance turnover** (signal-only V1 book): **6.03 (v0.4 recompute 6.07)/yr** of equity; keep-rate 0.567 (v0.4: 0.564).
- **Early-exit add-on (TCA owner d):** 2 × p_U × 0.58 × keep × 12 with p_U = 1 − (1 − 20/63)(1 − 0.524) = 0.675 → **5.33/yr**. **T = 11.35/yr** (the TCA owner).
- **Drag:** 11.35 × 16.34 bps = 1.85% trading + 0.29% borrow (flat 1%) = **2.14% of equity/yr** = break-even gross. **2× bar:** gross ≥ **4.29%/yr on equity**.
- **My check (flagged):** pricing stop legs at max(TCA owner stop cost, floor) (19.32 bps weighted vs 16.34) adds ≈ +0.11 pp → drag ≈ 2.25%, 2× bar ≈ 4.51%. The TCA owner's numbers are the planning figures; the engine charges actual per-trade, per-bucket costs (lagged 20d ADV; MOO 1.0× half-spread, 1.5× impact; stop fills at the worse of stop and next price).
- **Borrow:** flat 1% primary (the validator); S4 = 10% HTB stress on names not ETB today/absent from the snapshot; S6a/S6b = the TCA owner's 25 / 100 bps (informational). Conflict between the TCA owner (25/100) and the validator (1%/10%) is noted in COMMON C7 for them to reconcile.
- **Sizing:** round-to-nearest shares; skip only at 0 shares or > 50% weight error; S5 = no-skip sensitivity.

## 5. Primary metric and pass/fail
COMMON C6 on V1 Stage B daily net returns. Primary: OOS net Sharpe > 0.5, plus DSR ≥ 0.95, NW t ≥ 3.0, α t ≥ 3.0 (α ≥ 50% of raw), PBO < 0.20, > 0 at 2× costs, break-even ≥ 2×. Stage A gate: Stage A V1 net Sharpe (base costs, before the 0.74 haircut) > 0.68 and mean net L−S > 0. **Extra required diagnostic:** α must survive adding an abnormal-turnover control, to show the effect is not just the high-volume return premium (ABV is already a control in the signal; this is the return-level check).

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
- **TSC-specific α controls (in the Stage B gate):**
  - **Abnormal turnover (the validator):** monthly EW decile L/S on ln(mean daily $volume over t−20..t / median daily $volume over t−252..t−22), C1 universe, next-open fills, gross. In the gate regression (not just a diagnostic).
  - **Required small-trade prior-art control (Hvidkjaer 2008):NOT YET BUILDABLE.** Needs the data owner's historical SIP trade/size-bucket + quote panel and validator sign-off on the predeclared signing rule in `../derived/TSC_SIGNING_PREDECLARE.md` (Lee-Ready midpoint with strictly earlier quote; tick rule on midpoint; native size bins 1–99 / 100 / 200; `?` condition policy; max quote age 2s; asof identity; vendor-reprocessed disclosure). Feasibility of raw access: `data/docs/TSC_ALPACA_FEASIBILITY_20261106.md` (sha `0de864bc…`) — conditional yes on credentials, **no full panel yet**. **The derivatives researcher does not run the data owner's validation or any tick backfill.** TSC freeze is gated on that panel + validation (delisted/renamed, corporate actions, 2025–26 regime boundary, perf/storage) + the validator's signing sign-off.
  - **Auxiliary diagnostic only (does NOT satisfy the required control):** all-size count-direction proxy = Σ sign(r_d)·trade_count_d / Σ trade_count_d over 21 sessions (v0.4 formula). May be reported; never labelled as the Hvidkjaer control. 0.74 haircut kept.
  - **0.74 haircut kept** for expected Sharpe (the validator).

## 6. Fixed variant list (18 counted configs + cost-only columns; family **N = 393**, COMMON C11)
| ID | Variant | Role |
|---|---|---|
| V1 | Spec above | **primary** |
| V2 | Factor diagnostic: EW quintile L/S, 50/50 gross, no stops/blackout/rounding | signal vs implementation |
| V3 | V1, MOC fill at the next session's close | venue |
| V4 | V1 short leg only + SPY long hedge of equal $ | tests the "crowded retail names underperform" leg alone |
| V5 | V1 ranked within the correlation-assigned sector-ETF cluster | industry neutrality |
| R1-R2 | recent window 21 → 17 / 25 | §7 |
| R3-R4 | base window 252 → 202 / 302 (t−202..t−22 / t−302..t−22). R4's Stage A starts at its first full-history month; **Stage B for all variants starts 2023-03-31 so that R4's window never reaches before 2022-01-03** (COMMON C5) | §7 |
| R5-R6 | keep-band 20% → 16% / 24% | §7 |
| R7-R8 | names per leg 30 → 24 / 36 | §7 |
| R9-R10 | joint −20% / +20% | §7 |
| S1 | delisting stress: 0% for all unmatched delistings (primary: −30%, listed failures −100%; COMMON C2) | data stress |
| S2 | stops disabled (H6 effect; not tradable) | implementation stress |
| S3 | V1 at 2× costs and 2× borrow (C6 #2) | cost stress, counted (validator decision 2) |
| S4 | V1 with 10%/yr borrow on names not ETB in today's asset snapshot or absent from it (also the today's-flags sensitivity) | borrow stress, counted |
| S5 | V1 with no skipping in share rounding (TCA owner c) | sizing sensitivity, counted |
| S6a / S6b | V1 with the TCA owner's borrow 25 bps / 100 bps on all shorts (informational) | counted (conservative) |
**Counted configs = 18** (V1–V5, R1–R10, S1, S2, S5). S3/S4/S6a/S6b are **cost-only columns** (not in N) if holdings/eligibility/DD paths unchanged (COMMON C11). PBO uses V+R only. **DSR family N = 393.**

## 7. Train / test split
COMMON C5 (v0.4). Stage A signal dates 2016-12-30 .. 2021-11-30 (R3/R4 from their first full-history month). Embargo holdings 2022-01-03 .. 2023-03-31, never evaluated. **Stage B signal dates 2023-03-31 .. 2026-09-30 (43 rebalances; holdings 2023-04-03 → 2026-10-28), sealed, run once.** The start ensures R4's t−302 window stays at or after 2022-01-03.

## 8. Data
- **In the store:** SIP `trade_count`, `volume`, `vwap` (0% null, 2016-2026); splits; raw and adjusted closes.
- **Coverage (v0.4 fixed code, Stage A only):** 476-486 names per month on average by year (COMMON C1 table); split/ratio-jump exclusions 6.9-14.0 per month. The v0.3 figure (mean 490.8) came from the buggy script.
- **SIP questions (blocker C-2, the data owner), with pre-specified actions:** (a) odd lots included in `trade_count` (expected since Dec 2013) → spec unchanged; if not → ATS is mis-measured for high-priced names, and V1 is restricted to raw price < $250 at formation (fixed now). (b) Extended-hours prints included → spec unchanged (they are in both windows), disclosed. (c) A methodology change in 2016-2026 → the price-tier break rule (§3) applies; a market-wide break needs no action.
- **Questions for the data owner:**
  - Does Alpaca's `trade_count` include odd lots? (They have been on the SIP since Dec 2013.)
  - Does it include extended-hours prints?
  - Was there any SIP methodology change 2016-2026, such as the 2020-21 odd-lot and round-lot rule changes? A market-wide break is harmless to the ranking; a name-specific one is not.
- **Data reference:** as in close-vwap-accumulation §8 (v1.1; pin at run).

- **v0.4 release cited:** the data owner's v1.2 (`8972e558…`, incl. raw bars `9ef7d734…`); binding pin `<DATA_RELEASE_ID>` pending the data owner (COMMON C8).
- **Data release to cite:** `<DATA_RELEASE_ID>` (the data owner's frozen release; placeholder). Derived controls: events `<EVENTS_VERSION>`/`<EVENTS_SHA>`, SUE `<SUE_VERSION>`/`<SUE_SHA>` (COMMON C9).

**TSC-specific freeze gate (v0.5):** blocked on data owner tick panel + validation + validator signing sign-off. CVA/MXD proceed independently.

## 9. Caveats
- **Prior art:** Hvidkjaer (2008); see §2 and the §5 control.
- **SEC round-lot redefinition (effective Nov 2025)** falls inside Stage B; handled causally by the §3 price-tier rule and reported as a diagnostic split.
- **Market-structure breaks.** The tick-size pilot (2016-18) was small caps, so it is mostly outside the universe. Zero-commission (Q4 2019) and the 2021 meme period are both in Stage A. If the effect lives only in 2020-21, the §7 year-concentration rule (no year > 40% of PnL) will catch it.
- **Short-leg squeeze risk** (crowded retail names). The 2× ATR stops cap it in simulation, but gap risk through stops remains.

## 10. Change log
- 2026-11-06 ~06:45 SGT, **PARKED**: validator batch-scope decision — park TSC; no Stage A/B; no backfill; preserve N rows; CVA/MXD-only freeze path.
- 2026-11-06, v0.5: validator final decision — N=393; all-size proxy demoted to auxiliary; tick signing predeclared (`derived/TSC_SIGNING_PREDECLARE.md`); freeze gated on data owner panel. No backtest.
- 2026-10-30 02:28-02:45 SGT, v0.4: the validator's line-by-line review + the TCA owner's cost check. Hvidkjaer (2008) disclosed; small-trade imbalance proxy and abnormal-turnover decile added to the gate controls; 0.74 haircut kept; price-tier break rule; split rule in sessions + ratio jump; feasibility code fixed (VWAP ATS, t−252..t−22) and signal statistics recomputed on Stage A only; unlogged +0.455 check logged; Stage B start 2023-03-31 (R4 lookback); S4-S6b; costs per the TCA owner (T 11.35, drag 2.14%, 2× bar 4.29%) with my flag; runs 22; family N = 405. v0.2 change-log line restored to "family N = 328". Still draft; no runs.
- 2026-10-30 ~02:25 SGT, v0.3: the validator's second decision. N verified against TRIAL_LOG and raised to 390 (2 FF49 constructions + 60 non-identical reruns added back); primary SUE from 8-K EX-99.1 GAAP diluted EPS at τ, with XBRL fallback (share logged); monthly-decile controls; coverage rule (< 300 names → month dropped; > 10% of Stage B → CONDITIONAL cap); controls frozen before Stage A; data owner promotion path and data-release placeholder. Still draft; no runs.
- 2026-10-30 ~02:20 SGT, v0.2: the validator's interim decisions 1-7 (primary = 30/30 book; S3 2×-cost run added as a trial; family N = 328; ceiling CONDITIONAL PASS + paper probation; Stage-B α gate; desk SUE/8-K controls; VIX from the data owner's store only). Still a draft; no runs.
- 2026-10-30 ~02:15 SGT: Addendum A compliance (C9 timestamps, SUE control, C8 data access per DESK_RULES #5). Draft stage, before sign-off, so not a trial.
- 2026-10-30 ~02:25 SGT: v0 draft.
