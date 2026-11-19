# PRE-REGISTRATION DRAFT H3 v2 — Lower-turnover news-sentiment long/short on a fresh 100-name universe
Author: the sentiment researcher (Equity & Sentiment). Drafted 2026-11-11 SGT at the fund manager's request, for the validator (Signal Validation Lead) review.
v2 (2026-11-11 SGT) folds in the validator's AMEND decision (the internal review record, c302bee5…39eb)
and the fund manager's U1/G1 decisions (logged by the validator at). Changes listed in CHANGES_v1_to_v2.md; v1 (e8af0e34…) unchanged.
Structure, signal construction and boundary rules follow the sealed H1 prereg
`$QR_DESK_DIR/research/original/sentiment_returns_prereg_20261111/PREREG_DRAFT_v5.md` (sha 4b045f05…2c91, "v5").
Where this draft says "as v5 §x", that text applies verbatim except for the named changes.
Status: **DESIGN ONLY. DRAFT v2 for the validator's review. No data pulled, no returns or news for the new names exist on the desk,
nothing analysed, no backtest run.** Companions: UNIVERSE_RULE_H3_v2.md, DATA_REQUEST_H3_v2.md (both in this folder).

## D. DECLARATION — design informed by the H1b OOS result (binding disclosure)
- This design was drawn up **after** the validator's H1b OOS decision (decision e529d60d…): on the original 50 names over
  2025-01-02..2026-10-30, daily news sentiment had positive next-day rank IC (0.0207 UTC / 0.0180 ET; Holm-adjusted p 0.017 /
  0.048), but the daily raw long/short lost money net of 10 bps/side (−0.00159 / −0.00179 per day). H1b is FAIL; the 50-name
  holdout is consumed (v5: no reruns, variants or re-spec on those names).
- **What we know:** the 2025–26 behaviour of the 50 names under H1b (headline IC, p, net L/S) and their 2022–24 DEV behaviour
  (H1a/H1b/H2 DEV stats). The choices "rebalance weekly, smooth the signal, band the book, make costs the binding gate" were made
  *because* H1b was cost-killed. H3 is therefore **not independent of H1b**; it is a new test on new names, designed with
  knowledge of the old result.
- **Regime-leakage risk (stated honestly):** the new 100 names share the same calendar period, macro regime, news vendor,
  sentiment model and market factors as the 50. A cross-sectional news effect that was present in 2025–26 for mega caps is
  likely correlated with one in the next 100 large caps. A PASS on H3 HOLDOUT is therefore weaker evidence than a PASS on a truly
  unseen period: it shows the slower design survives costs on *different names in a period whose regime we partly know*, not
  that it would survive in a new regime. SPY's 2025–26 returns (beta input) were also used in H1b OOS. The author also has
  general knowledge of 2025–26 market events. Every H3 output carries: "Design informed by H1b OOS; HOLDOUT period not
  regime-blind."
- **Q-H7 RESOLVED:** Declaration D stands as written. In addition, any H3 PASS is recorded as **"conditional evidence
  (period not regime-blind)"**.
- **What is NOT known:** any return, news item or sentiment score for the 100 new names in either partition. No parameter below
  was set by looking at their data (there is none on the desk). Parameters are fixed here, before the pull.

## 0. HOLDOUT BOUNDARY (as v5 §0 /, re-applied to H3 — Q-H1 RESOLVED, accepted at)
- **B1:** DEV = closes and events dated ≤ 2024-12-31; HOLDOUT = 2025-01-01..2026-10-31 (first session 2025-01-02; last returns
  close 2026-10-30). Both partitions are **unseen** for the new names.
- **B2:** a return belongs to the partition of its END close. HOLDOUT may use DEV closes (beta warm-up, first return); DEV never
  uses a close dated 2025-01-01 or later.
- **B3/B8 (straddle):** an observation whose decision is DEV-dated but whose holding return ends after the 2024-12-31 close is
  **dropped from BOTH partitions**. OOS membership is by decision date (≥ 2025-01-01). For H3 weekly decisions (XNYS, last
  session of each ISO week): decision **2024-12-27** (return → close 2025-01-03) is dropped; last kept DEV decision
  **2024-12-20**; first OOS decision **2025-01-03**.
- **Calendar counts** (exchange_calendars 4.13.2 XNYS via `$QR_DATA_DIR/.venv/bin/python`, sessions only, no data):
  first H3 decision = **2022-04-01** (first week-end session whose 20-session news window opens on/after the 2022-03-01 session;
  it has 276 daily returns since 2021-03-01, so the 252-return beta window never binds). DEV decisions 2022-04-01..2024-12-27 =
  144; minus the 2024-12-27 straddle → **143 usable DEV weeks** (max 143 × 100 = 14,300 symbol-weeks). OOS decisions
  2025-01-03..2026-10-30 = 96; the last (2026-10-30) has no next-week close in the pull → **95 usable OOS weeks**.
- **B6 release:** data engineer partitions as DATA_REQUEST_H3_v2.md (prices by END close, news by month file, EARNINGS by reportedDate;
  price rows dated after 2026-10-31 sealed separately in `post_20261031/`, SUMS-only, not HOLDOUT).
  DEV released to sentiment researcher only after validator seals this prereg and fund manager releases it. HOLDOUT is hashed and counted only until the
  single OOS run.
- **DEV-stats freeze (A2, as v5):** before any HOLDOUT file is opened, the DEV statistics for H3 and the exploratory variants
  (mean IC, NW t, Student-t p, scored weeks, banded net L/S at 10 and 20 bps/side, mean one-way turnover), under BOTH timestamp
  readings, are written 0444 to this folder and sha-logged with the validator. Nothing in that file is recomputed afterwards.
- **OOS runner lock (as H1b):** the OOS runner and config are staged, hashed and confirmed by validator against the H3 DEV freeze
  before data engineer releases HOLDOUT. One run; any abort after the lock is an incident to the fund manager, no retry; raw output goes to
  Validator first.

## 1. Data under test (to be pulled; see DATA_REQUEST_H3_v2.md)
- **Universe (U1 RESOLVED by the fund manager,: full listing scan):** 100 US common stocks chosen by the point-in-time rule in
  UNIVERSE_RULE_H3_v2.md from a **full AV LISTING_STATUS scan** of stocks listed on NYSE, Nasdaq or NYSE American on 2021-02-26
  (names delisted since included): top 100 by median daily dollar volume (raw close × volume) over 2020-11-25..2021-02-26,
  after mechanical exclusion of the original 50 (by D-symbol, FB for META, plus GOOG), ETFs and other non-common types, ADRs and
  non-US issuers, and extra share classes (most liquid class kept). Names AV cannot serve at D are dropped before the cut,
  listed, and threshold-gated (UNIVERSE_RULE_H3_v2.md §5). No replacement; delisted names stay until their last AV bar. **No
  eligibility test uses news coverage or any other post-D data ( A1).** SPY and QQQ are benchmarks only, never in a
  cross-section. The v1 memory-drawn pool is superseded and not used for selection.
- **News:** AV NEWS_SENTIMENT per ticker, monthly files 2022-03..2026-10, same request parameters and capped-window handling as
  av_sentiment_20261110. Same schema as v5 §1 (`time_published`, `ticker_sentiment[]` {ticker, relevance_score,
  ticker_sentiment_score}).
- **Prices:** AV TIME_SERIES_DAILY_ADJUSTED (`outputsize=full`, pulled once per scanned name in Stage 1b; the final 100's
  2021-03-01..2026-10-31 series are reused from that pull). Selection uses raw close × volume in 2020-11-25..2021-02-26 only.
- **EARNINGS** (R-EARN only) and **OVERVIEW** (Stage 1c ADR/non-US/share-class check, and sector for R-SECTOR only; current
  snapshot, look-ahead, disclosed).
- Expected coverage risk: the next-100 large caps will have thinner news than the 50 mega caps (H1 median 37 items/month).
  Hence the 20-session window and the 40-name cross-section floor below. Realized coverage is reported, not tuned on.

## 2. Hypothesis (confirmatory N = 1) and signal construction (fixed in advance)
- **H3 (sole confirmatory hypothesis):** On the fresh 100-name universe, a weekly-rebalanced, banded long/short portfolio
  formed on trailing 20-session news sentiment earns positive mean return **net of 10 bps per side**, with positive
  cross-sectional rank IC against next-week beta-adjusted returns.
- **Exploratory only (never PASS, not in N; run in the same single OOS sitting and reported in full):**
  - **X1** — same as H3 but with the 5-session window (v5 H1a signal) and the same banding.
  - **X2** — same 20-session signal, weekly rebalance, **no banding** (plain top/bottom quintile each week) — measures what the
    banding buys in turnover and net return.
- **X1/X2 OOS results cannot seed any later prereg tested on the 2025-01-01..2026-10-31 period.** ( A4; Q-H5 RESOLVED.)
- No time-series variant, no monthly variant, no parameter sweep, no other band widths. Anything else = new prereg.

**Item filter** (as v5 §2): keep an item for symbol i only if `ticker_sentiment` has an entry with `ticker == i` and
`relevance_score ≥ 0.50`; item score s = that entry's `ticker_sentiment_score`. `overall_sentiment_score` not used.
Unparseable → dropped, counted.
**Timestamps** (as v5 §2, A3): both the UTC reading and the ET reading are computed; **R-TZ is a conjunctive gate** — H3 passes
only if every PASS criterion holds under BOTH readings, each against its own frozen DEV stats. A4 materiality reported.
**Calendar:** exchange_calendars 4.13.2 XNYS.
**Decision session t:** the last XNYS session of each ISO week (as v5 H1a).
**Signal window (CHANGED from v5):** items with ET timestamp in (15:30 ET on session t−20, 15:30 ET on session t], i.e. the
trailing 20 sessions (≈ 4 weeks), overlapping week to week. Position taken at the session-t close (30-min buffer).
**Aggregate:** S(i,t) = relevance-weighted mean of s over kept items (as v5).
**Minimum counts (CHANGED):** ≥ 5 kept items per symbol-window; below → missing (not 0, not neutral).
**Cross-section floor (CHANGED):** a week is scored only if ≥ 40 names have a valid signal AND a valid next-week return.
**Rank:** u(i,t) = (rank of S among qualifying names − 0.5) / n, ascending (ties → average rank).

**Portfolio and banding (NEW, fixed):**
- Long entry: u ≥ 0.80 (top quintile). Long stays long while u ≥ 0.60 (top 40%); exits when u < 0.60.
- Short entry: u ≤ 0.20 (bottom quintile). Short stays short while u ≤ 0.40; exits when u > 0.40.
- A long whose u falls to ≤ 0.20 flips directly to short (and vice versa).
- **Missing signal at a decision** (below minimum, coverage=0 or capped exclusion, delisting): the position is **exited** at that
  close (cost charged). No new entry without a valid signal. (Conservative on costs.)
- **Unscored week** (< 40 qualifying names): no trades except forced exits above; existing positions held; the week's
  portfolio return still counts in the L/S series; no IC is recorded.
- Weights: equal weight within each leg at each rebalance; long leg sums to +1, short leg to −1 (gross 2). Between rebalances
  weights drift with returns. If a leg has < 5 names after banding, the whole book is held flat for that week (counted).
  **Going flat and re-entering are both charged 10 bps/side on the traded weight** (exit to flat: Σ|0 − w_drifted|; re-entry
  from flat: Σ|w_new − 0|) ( A3).
- **Re-equal-weighting:** at each rebalance every held name (not only new entries) is reset to equal weight within its leg; that
  turnover is counted in Σ|w_new − w_drifted| and charged ( A3).
- Portfolio return for week t→t+1 = long-leg return − short-leg return, on **raw** adjusted-close returns (as the validator's H1b
  decision 2: gate on raw L/S; beta-adjusted L/S reported only).
- **Turnover and costs:** traded weight at each rebalance = Σ|w_new − w_drifted| over both legs; cost = 10 bps × traded weight
  (20 bps/side sensitivity). First week of each partition enters from flat with full entry cost (as H1b decision 4). No terminal
  liquidation cost is charged in the gate; a with-liquidation figure is reported.
- No turnover cap beyond the banding (the band is the turnover control; a hard cap would add a parameter).

## 3. Missing-data rules (as v5 §3, adapted)
- coverage=0 months: symbol excluded from every window overlapping that month. capped_incomplete: symbol excluded from every
  window overlapping a listed capped weekly window, with the ±1-day padding accepted by the validator for H1b (declared as a
  conservative choice). Exclusions counted.
- Below-minimum windows, unparseable values, no relevant items: missing, not zero. No forward-fill of sentiment.
- Symbol-week missing next-week return (incl. delisting mid-week): excluded from that week's IC; in the portfolio, a name with no
  return after its last AV bar is closed at that bar (no delisting return available — disclosed, §7).
- Names with no AV news at all in DEV stay in the universe and are simply never scored (counted, listed).

## 4. Companion data (to be pulled; DATA_REQUEST_H3_v2.md)
- Returns: r(t) = adjusted_close(t)/adjusted_close(t−1) − 1, **ratios only, no levels, no winsorizing** (as v5 §4A).
- EARNINGS: R-EARN only. OVERVIEW sector: R-SECTOR only (current snapshot, look-ahead; same response as Stage 1c). Neither
  touches a gate.
- Paths/shas: TBD-on-release. Sentiment researcher verifies shas on receipt and logs them.

## 5. Metric, test and PASS bars (fixed in advance)
- **Target for IC:** next-week beta-adjusted return r_i − β_i r_SPY, β_i from OLS on exactly 252 daily returns ending t−1.
- **IC:** weekly Spearman rank IC between S(i,t) and the target, over qualifying names; mean IC; Newey–West t with **4 lags**
  (also covers the 4-week signal overlap); one-sided p = 1 − F_t(NW t; df = scored weeks − 1).
- **Confirmatory family N = 1** → no Holm; one-sided α = 0.05 per reading (both readings required, A3).
- **DEV gate (A2, extended):** H3 FAILS outright, before any HOLDOUT open, if under either reading DEV mean IC ≤ 0 **or DEV
  banded raw L/S mean weekly net return at 10 bps/side ≤ 0**. (The cost gate is the binding question, so a design that loses
  money net on DEV does not consume the holdout.) DEV stats frozen 0444 first.
- **PASS (OOS), required under BOTH UTC and ET readings:**
  (i) DEV gate passed;
  (ii) OOS one-sided p < 0.05 for mean IC > 0;
  (iii) OOS mean IC > 0 and ≥ 50% of the frozen DEV mean IC of the same reading;
  (iv) **BINDING COST GATE: OOS banded raw L/S mean weekly return net of 10 bps/side > 0** (point estimate, as v5 (iv)).
  **FAIL** otherwise. No re-specification after seeing OOS. A PASS is recorded as **"conditional evidence (period not
  regime-blind)"** ( Q-H7). (iv) stays a point estimate > 0 ( Q-H3 RESOLVED).
- **Reported, not gating ( Q-H3):** net at 20 bps/side; NW t (4 lags) and one-sided p of the net 10 bps L/S series; mean weekly one-way
  turnover and average holding period; break-even cost per side (gross ÷ traded weight); beta-adjusted L/S; leg sizes; scored
  weeks; exclusions by reason; A4 materiality; with-liquidation net.
- **Power note (assumption, not data):** with ~100 names, per-week IC s.d. ≈ 0.10 assumed; at 95 OOS weeks (df 94) one-sided
  0.05 needs NW t ≳ 1.66, i.e. mean IC ≈ 0.017. Criterion (iv) has no power requirement; a small positive net mean can pass
  (iv) by chance — see Q-H3.

## 5b. Forward shadow (the fund manager's G1 decision as logged by the validator)
- **Shadow start S0 = 2026-11-06**: the first weekly decision after 2026-10-31, i.e. the last XNYS session of the ISO week
  containing 2026-11-02 (exchange_calendars 4.13.2 XNYS via `$QR_DATA_DIR/.venv/bin/python -I -B`, sessions only). The
  2026-10-30 decision (last HOLDOUT decision, no next-week close) is not a shadow week. If the single H3 HOLDOUT run happens
  after S0, the shadow starts at the **first weekly decision after the shadow data is sealed, never earlier than 2026-11-06**.
- **Data:** a separate, later AV pull for the same sealed 100 names plus SPY (news and prices dated after 2026-10-31), requested
  and sealed by the data engineer with its own SUMS; not part of DATA_REQUEST_H3_v2.md. Rows dated after 2026-10-31 that arrive with the
  Stage-1b `full` price pull are sealed in `post_20261031/` and are not used by the shadow unless re-hashed into its release.
- **Minimum length: 52 weekly decisions with a realized next-week close** (from S0 = 2026-11-06, the 52nd decision is
  2027-10-29, its return ending at the 2027-11-05 close; pinned calendar horizon ends 2027-11-11). Evaluated **once**, at the
  minimum length; no interim look at IC or L/S (data-quality counts only).
- **Bars (both UTC and ET readings, each against its own frozen H3 DEV stats):** (a) one-sided NW (4 lags) p < 0.05 for shadow
  mean IC > 0; (b) shadow mean IC > 0 and ≥ 50% of the frozen DEV mean IC; (c) **binding cost gate: banded raw L/S mean weekly
  net of 10 bps/side > 0** (point estimate). Shadow passes only if (a)–(c) all hold under both readings. Net at 20 bps/side,
  net-series NW p and break-even cost reported, not gating.
- **No parameter changes of any kind** between this prereg's seal and the end of the shadow: same 100 names (no additions or
  replacements; delisted names leave), same signal, window, item filter, minimum counts, floors, band, weights, cost model,
  calendar, timestamp readings and runner. Any change = new prereg, and the shadow restarts from a later S0.

## 6. Robustness (pre-registered; never change PASS/FAIL, except R-TZ which is a gate)
- R-TZ: conjunctive gate (§2). R-COST20: 20 bps/side. R-SECTOR: sector-demeaned IC (look-ahead disclosed).
- R-EARN: H3 excluding symbol-windows containing an earnings day 0 ±1 session (EARNINGS reportedDate proxy).
- R-LIQ: with terminal liquidation cost. Exploratory X1, X2 (§2).

## 7. Controls, caveats, limitations
- **Declaration D applies to every output** (design informed by; HOLDOUT period not regime-blind).
- Market beta removed in the IC target; the gate uses raw L/S (dollar-neutral, not beta-neutral; beta-adjusted reported).
- Survivorship: a full point-in-time LISTING_STATUS scan (delisted names included) replaces the v1 memory pool, but does not
  remove survivorship — AV may not serve price series for delisted or renamed D-symbols; those names are dropped **before** the
  top-100 cut (implicit promotion of lower-ranked names), listed by ticker and reason in UNIVERSE_H3.tsv, and gated by the
  pre-set threshold (UNIVERSE_RULE_H3_v2.md §5: > 2 v1-pool names or > 10% of the scan unservable → back to fund manager before any
  news pull). Ticker changes since D are not followed (keyed on D-symbol). OVERVIEW used in the ADR/non-US/class check is a
  current snapshot. No delisting returns exist. Any positive result is an upper bound.
- Point-in-time sentiment: as v5 §7 (scores pulled in Nov 2026 may be recomputed/backfilled; "not verified point-in-time").
- Timestamp zone unconfirmed (R-TZ gate). Sector map is a current snapshot. Costs are a flat 10 bps/side (no market impact,
  borrow cost or short constraints modelled); for next-100 large caps, 10 bps/side is a reasonable but not conservative
  all-in figure — hence 20 bps reported.

## 8. Statements
- **No trading.** Research only until validator validates and the fund manager approves next steps. A PASS is evidence, not a trading signal.
- No results reported to Daniel until validator validates. Outputs only under this folder, sealed 0444 with SHA256SUMS.
- No pulls by the sentiment researcher; data via data engineer per DATA_REQUEST_H3_v2.md. The fund manager approved the whole pull (Stage 1 scan + Stage 2,
  ≤ 60 calls/min), **effective only once validator locks the universe rule in his prereg decision**; data engineer seals the selected 100
  before any news is pulled.

## 9. Open questions — status after /
- **Q-H1 Boundary — RESOLVED:** B1–B8 carry over; straddle drop 2024-12-27, last DEV 2024-12-20, first OOS 2025-01-03;
  week counts re-checked at the DEV freeze.
- **Q-H2 DEV gate extension — RESOLVED:** DEV net L/S ≤ 0 at 10 bps (either reading) fails H3 before HOLDOUT is opened.
- **Q-H3 Cost gate strength — RESOLVED:** (iv) stays a point estimate > 0; net-series NW p and break-even cost reported.
- **Q-H4 Band and parameters — RESOLVED:** 80/60 band, 20 sessions, ≥ 5 items, ≥ 40 names, ≥ 5 per leg, exit on missing,
  fixed a priori; no change after the pull.
- **Q-H5 Exploratory set — RESOLVED ( A4):** X1/X2 accepted, with the no-seeding line in §2.
- **U1 Candidate pool — RESOLVED by the fund manager:** full LISTING_STATUS scan; v1 pool superseded (kept only as appendix and
  survivorship tripwire, UNIVERSE_RULE_H3_v2.md §5, Appendix A).
- **U2 Selection measure — RESOLVED:** median dollar volume accepted.
- **U3 Delisted names — RESOLVED ( A2):** unservable names listed by ticker and reason; pre-set threshold; post-drop cut
  disclosed (UNIVERSE_RULE_H3_v2.md §5).
- **Q-H6 Gate on raw L/S — RESOLVED:** raw kept.
- **Q-H7 Declaration D — RESOLVED:** stands; PASS recorded as "conditional evidence (period not regime-blind)".
- **G1 (use of 2025-01..2026-10 for H3) — the fund manager's decision logged by validator at.** v1-decision had it OPEN with the fund manager.
  This draft implements the forward shadow (§5b) as validator requested under and otherwise keeps §0/§5 as drafted; **the
  text was not read by the author for this draft** — the validator to confirm §0, §5 and §5b match the fund manager's decision.
- **New for the validator:** (a) the T1/T2 survivorship thresholds (UNIVERSE_RULE_H3_v2.md §5(b)); (b) R2 uses OVERVIEW Country as the
  non-US-primary proxy, which also drops US-primary foreign-domiciled issuers that v1 kept; (c) the 52-week shadow minimum and
  bars (§5b); (d) Nov 2020–Feb 2021 dollar volume includes the meme/SPAC episode (no point-in-time market cap to correct it).
Open — for the data engineer (data): AV exchange labels in LISTING_STATUS(date=2021-02-26) (expected `NYSE`, `NASDAQ`, `NYSE MKT`); whether
AV serves price series for delisted D-symbols; BRK-B/BF-B format for price and news; exact sort/limit/window parameters of the
original news pull; NEWS_SENTIMENT start date per selected name (reported only, never an eligibility test).
