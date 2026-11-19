# VRP-IC pre-registration DRAFT v0.1: SPY/QQQ volatility-risk-premium iron condors gated by IV rank and the VIX/VIX3M slope

**DRAFT, not frozen, no data viewed, no returns computed.** Owner: Dave (Quantitative Researcher). Assigned by Jeremy (CIO / Fund Manager), 2026-11-10 SGT. Written Tue 10 Nov 2026, ~01:40-02:10 SGT (UTC+8).
Machine-readable mirror: `PARAMS_v0.1.json` (same folder). Hashes: `SHA256SUMS`.
Documents only. This file authorises **no** data load, DEV/OOS/holdout run, backtest, fetch, API call, paper order or live order. Sizing below is an **assumption borrowed from Risk's DRAFT**; it is not a risk approval. Options are **H5 = None** in `risk/LIMITS.md` today, and nothing trades without Victor's validation pass (desk rule 3) plus Rachel's sign-off, Tomas's execution and Daniel's own pinned confirmation (N1).

---

## 0. Inputs, provenance and a statement that no data was viewed

| Input | Path | SHA256 (full, computed 2026-11-10 ~01:37 SGT) | Check |
|---|---|---|---|
| Ethan's idea file (idea #1 "Rank 1" only) | `$QR_DESK_DIR/research/original/2026-11-10_ethan_options_ideas.md` | `25087a7ffbc25e465f942e9e5ef81ba5ade561360b12e1e5b2923875eca542cc` | Jeremy's quoted prefix `25087a7f` **MATCHES**. Treated as the pinned version. |
| Rachel's derivatives risk-limits DRAFT | `$QR_DESK_DIR/risk/drafts/2026-11-10-derivatives-risk-limits-DRAFT-v0.1.md` | `f35afbe8ab5d5ad7573798556f81d68c607ecd6c6db2bb34618bd99afad49201` | Caps confirmed against the file (quoted in §8). The file is marked "DRAFT, NOT EFFECTIVE". |

The house-style reading was text only: `dave/COMMON.md`, `dave/FORKING_PATHS.md`, `dave/sentiment_sector_switch_20261107/PREREG_v0.3.md` (first ~60 lines), `validation/STANDARD.md` and the header of `tca/cost_model.md`. I also listed directory names (not contents) under `$QR_DESK_DIR`, `validation/` and `tca/`.

**No-data statement.** In writing this document I opened **no** market, option, VIX, price, return or Alpha Vantage file. I opened nothing under `$QR_DATA_DIR/` and made no network, fetch or API call. I did not use `ALPHAVANTAGE_API_KEY`. I ran no code except `sha256sum` and `mkdir`. Every parameter below comes from the idea text, the Risk draft, desk standards, published practitioner/academic convention or arithmetic. None was chosen from outcomes. This statement is part of the frozen text.

## 1. Prior exposure / contamination (READ FIRST)

**1a. Ethan's file contains no outcome information.** It has no backtest results, performance numbers, Sharpe ratios, P&L, hit rates or observed returns. It declares itself "DESIGN ONLY — no ... backtests, signals, returns". For completeness, these items are **non-outcome priors and assumptions**. They are flagged here, and none was used to tune a parameter:
- the qualitative prior that "VRP is persistent in index options" (a literature claim citing Bakshi & Kapadia 2003, not a desk measurement);
- the regime list "cover 2018 vol crush, 2020, 2022", which is general market-history awareness and not an outcome of this strategy;
- cost assumptions marked "ASSUME", not measured: $0.50-0.65/contract/leg commission, ~$0.03-0.05 regulatory, 50-100% of mid-to-touch width, and a stress of 2x widths with 1.5x fees;
- vendor list prices and coverage dates (ORATS / ThetaData / Databento / Cboe), which are metadata and not outcomes.

**1b. Desk-level and personal contamination (labelled).**
- The desk, including me, has already worked with SPY and VIX/VIX3M history:
  - SCS (`sentiment_sector_switch_20261107/`) uses the same VIX/VIX3M log-slope family;
  - COMMON C6 #7 uses VIX regimes;
  - my replication sleeves and the desk PEAD verdicts were seen over 2016-2026 (COMMON C5, FORKING_PATHS #5).
- I also know the broad public history of 2008-2026 volatility episodes: 2008, May 2010, Aug 2011, Aug 2015, Feb 2018 (the short-vol ETP blow-up), Mar 2020, 2022, Aug 2024 and Apr 2025. I know in general terms that short-volatility strategies lost heavily in several of them.
- **Consequences:**
  - the OOS and holdout segments below are **not blind**;
  - the historical verdict ceiling is **CONDITIONAL PASS** (as in COMMON C5);
  - the only clean test is **forward paper** (§12).
- The split boundaries in §9 come from a mechanical month-count rule, not from where these episodes fall. As disclosed, Feb 2018 falls in OOS and Mar 2020 / 2022 H1 fall in OOS.

**1c. Source survivorship.** SPY and QQQ are chosen today as the most liquid ETF option roots, so they are survivors by construction. This is disclosed. Whether STANDARD §2's 20% survivorship haircut applies to an index-ETF universe is open question Q-V4.

## 2. Hypothesis, economic rationale, null

- **H1 (primary).** A defined-risk short-volatility position (a delta-selected iron condor on a standard monthly SPY/QQQ expiry) that is opened only when (a) the underlying's 30-day ATM implied vol is elevated relative to its own trailing year (IV rank) **and** (b) the VIX term structure is in contango earns a positive net-of-cost return. The return is measured as risk-adjusted daily sleeve NAV, and it has positive alpha versus the S&P 500 (SPY total return).
- **H2 (gate value).** The same structure with the gates off (control C01) has a lower OOS Sharpe than P01.
- **Rationale.**
  - Index implied variance exceeds subsequently realised variance on average: the variance risk premium (e.g. Bakshi & Kapadia 2003; Carr & Wu 2009). Cboe PutWrite-style literature shows short index options earn this premium.
  - Selling when IV is high relative to its own history harvests a larger premium per unit of tail risk.
  - VIX-curve contango (VIX < VIX3M) marks a calm, mean-reverting regime. In backwardation, realised vol tends to stay high and short-vol losses cluster. The slope of the VIX term structure is documented to predict variance-risk-premium returns (e.g. Johnson 2017, JFQA, "Risk Premia and the VIX Term Structure").
  - Iron condors cap the tail by construction, as Rachel's draft requires for defined risk.
- **Null H0.** The OOS net Sharpe of P01's daily sleeve returns is ≤ 0 (tested against the §11 hurdles). For H2, P01 OOS Sharpe ≤ C01 OOS Sharpe.

**Departures from Ethan's sketch, made ex ante with reasons.**
1. The slope gate requires **contango**, as Jeremy's brief asks. Ethan wrote of a "vol-rich / term-stress" region, which may mean the opposite sign. His alternative is **not registered**, and registering it later would be a new trial (Q-E1).
2. Wings use **delta**, not "$5 SPY". A fixed dollar width is not comparable over the 2008-2026 range in SPY's price level.
3. Ethan's 21-DTE time exit is kept, and Jeremy's **2-DTE mandatory close** is added as a hard backstop.
4. Fills are at the **next-session** EOD snapshot, not "next regular open", because the chains are end-of-day only (STANDARD §2 "next bar or worse").

## 3. Universe and expiries

- **Underlyings:** SPY and QQQ (root `QQQQ` before the Nasdaq listing change in 2011 must map to QQQ; Dmitri/Ethan document the mapping). They are American-style, physically settled and have a 100-share standard deliverable.
- **Expiry:** **standard monthly** only (the third Friday, or the preceding session if that is an exchange holiday). Weeklies, quarterlies and end-of-month series are excluded. Rationale: monthlies are the only series continuously listed across 2008-2026 on both roots. That keeps the instrument definition constant across DEV, OOS and holdout, and monthlies have the deepest liquidity.
- **Underlying ADV floor** (Rachel §5): ADV20 ≥ 1,000,000 shares, using Dmitri's pinned bars lagged one day. This is a formality for SPY/QQQ, but it is checked.

## 4. Entry

| Item | Rule (P01) | Rationale |
|---|---|---|
| Snapshot | Alpha Vantage historical **end-of-day** chain for session t. Each record is treated as **available at 21:30 ET on t** (the desk SCS cutoff family). No intraday information. | EOD-only data. A late, conservative availability time. |
| Decision / fill | Decide at 21:30 ET on t from snapshot t. **Fill on the snapshot of session t+1** (next XNYS session), with the strikes locked at t (no re-selection at t+1). | STANDARD §2: no same-bar fills. A live analogue is a near-close combo order on t+1. |
| Target DTE | The fill-session calendar DTE to expiry E is in **[35, 45]** (target 45, tolerance −10/+0). The decision window is every session t whose next session t+1 has DTE(E) in [35, 45]. The **first** t in the window with all gates passing and no open position in that underlying triggers the entry. If the window ends with no entry, cycle E is skipped. At most **one entry per (underlying, expiry)**. | 45 DTE is the conventional entry point and the top of Ethan's 21-45 range, and it is ≥ Rachel's 7-DTE minimum. The window gives a one-week entry opportunity per monthly cycle. |
| Short strikes | One short put and one short call, each with desk Black-76 \|Δ\| **nearest 0.16**, restricted to \|Δ\| in [0.12, 0.20]. A tie goes to the strike further OTM. | ~1-sigma convention (Ethan's "~16Δ"). |
| Wings (primary = **delta**) | Long put and long call with \|Δ\| **nearest 0.05**, restricted to [0.03, 0.08], strictly further OTM than the short strike (≥ 1 listed strike beyond it). A tie goes to the strike nearer the short. Put and call widths may differ. | Scale-invariant across an 8x+ price-level range and vol regimes. Fixed-$ width is rejected (§2). |
| Delta / IV source | **Primary = desk-recomputed** (§4a). Alpha Vantage IV/greeks are a cross-check only (§7). | AV historical greeks/IV methodology is undocumented on the desk (Q-E2). |
| IV-rank gate | IV30_t = desk constant-maturity 30-calendar-day ATM IV (§4a). IVR_t = 100 × (IV30_t − min) / (max − min), with min and max over the **252 XNYS sessions ending t** (inclusive). At least 240 valid IV30 values are required, otherwise the gate is INVALID (no entry). Pass if **IVR_t ≥ 30**. | 252 is one trading year. 30 is the conventional practitioner floor for "elevated" IV rank. It is not tuned, and it keeps trade count up (§11 trade-count constraint). |
| Slope gate | z_t = mean of ln(VIX_close / VIX3M_close) over **K = 5** XNYS sessions **ending t**. Pass if **z_t < 0** (contango, strict). Any missing VIX or VIX3M close in the window means INVALID (no entry; never imputed, never a tie). | K = 5 reuses the desk's SCS P01 value (no new free parameter). 0 is the natural contango boundary. |
| Slope timing | Cboe VIX and VIX3M closes for t are final after the 16:15 ET index close. Using them at the 21:30 ET cutoff for a t+1 fill is point-in-time. The source is Dmitri's pinned VIX/VIX3M release (`<VIX_RELEASE_SHA>` at freeze), with first-seen values only and no later revisions. VIX3M history starts Dec 2007 (public index history), before warm-up. | |
| Overlap | **At most one open condor per underlying.** No stacking or rolling. SPY and QQQ positions may coexist. | Ethan's rule. It keeps the per-underlying cap at one position. |
| Events | **No FOMC/CPI/event filter in any registered configuration.** Event-vol is Ethan's separate idea #2. | Avoids an unregistered fork. |

### 4a. Desk IV, delta and IV30 recomputation (primary)
- Per expiry and session: derive the forward F and discount factor D from a put-call-parity regression C_mid − P_mid = D·(F − K) over strikes within ±5% of the underlying close that have valid call and put quotes. At least 3 pairs are required, otherwise the expiry is unusable that session.
- IV per option: invert **Black-76** on the OTM mid (puts for K < F, calls for K ≥ F; the ATM strike uses both), with Brent's root-finder on [0.001, 5.0] and tolerance 1e-8. If the mid is outside the no-arbitrage bounds, the IV is undefined and the quote is dropped.
- Delta = Black-76 forward delta (put delta negative, |Δ| is used).
- The European approximation for American ETF options is **disclosed**. It is small for OTM options and is monitored against vendor IV (§7).
- IV30: take the two standard monthly expiries bracketing 30 calendar days with DTE ≥ 7. ATM IV per expiry = mean of call and put IV at the strike nearest F. Interpolate total variance linearly in calendar time to 30 days. If there is no expiry below 30 DTE with DTE ≥ 7, use the nearest expiry's ATM IV (flagged).

## 5. Management (all checks on snapshot t at mid; every exit fills the **whole condor** on snapshot t+1)

| Priority | Trigger at t | Rule |
|---|---|---|
| 1 | **Mandatory 2-DTE close** | The fill must occur **no later than the last XNYS session with calendar DTE(E) ≥ 2**. The decision is logged the session before. Nothing is ever held into expiry day. This is stricter than Rachel §4. |
| 2 | **Ex-dividend / early-exercise defence** | Trigger at session t if the next session t+1 is the last session before a known (PIT) or issuer-scheduled ex-dividend date **and** any short call has extrinsic value (mid − intrinsic) below the projected dividend. The projected dividend is the last paid regular dividend, known PIT. The condor is then closed at the t+1 snapshot, before the exercise deadline. Short puts: the same test applies to ITM short puts whose extrinsic value falls below 0.5 × (the carry implied by D over the remaining DTE). In practice priority 3 almost always fires first, because an ITM short means a breached strike. Both counts are reported. |
| 3 | **Stop: short strike breached** | Raw (unadjusted) underlying close at t ≤ short put strike, or ≥ short call strike (Dmitri's pinned raw bars). This is Ethan's rule. It uses the underlying close, which is robust to option-quote noise. |
| 4 | **Profit take** | Mid cost-to-close at t ≤ **50%** of the entry **mid** credit (the fill-model-independent reference). |
| 5 | **Time exit** | The fill session is the **first XNYS session with DTE(E) ≤ 21**. This is Ethan's rule. |

- **Assignment modelling.** No assignment is simulated while every short is OTM. Any session where a short leg's extrinsic value is below the projected dividend (calls) or the carry bound (puts) is counted as an "assignment-risk session". The target is zero by construction of rules 2 and 3. Any realised assignment risk in paper follows Rachel §3: flatten by the next session, log an incident.
- **Exit fill failure.** If a required exit cannot fill on its session because quotes fail §7, it fills at the next session with valid quotes, under **natural** prices in both fill models. For the 2-DTE backstop, if no valid quotes exist on the deadline session, the position is booked at **full defined max loss** (W − credit, plus fees). This is conservative and counted.
- **Leg with bid = 0 at exit.** A long wing that is sold for 0 earns 0 proceeds. A short leg needs a valid ask to be bought back, otherwise the exit-fill-failure rule applies.

## 6. Fill model (per leg, per side, entry and exit) and costs

- Half-spread h = (ask − bid)/2 and mid = (bid + ask)/2, from the fill-session snapshot.
- **Primary (k = 0.5):** sell at mid − 0.5·h, buy at mid + 0.5·h (= mid ∓ 25% of the full spread). Each leg is rounded **adversely** to the tick.
- **Stress (k = 1.0, natural):** sell at bid, buy at ask, and fees x2. That is 2x the primary spread cost and 2x fees, which matches STANDARD §5 "2x costs".
- **Combo pricing.** The combo is priced **leg by leg** from the chain: net price = sum of the four rounded leg fills. No complex-order-book improvement is assumed.
- **Tick.** $0.01 at all premium levels for SPY/QQQ (penny-pilot roots). This is an ASSUMPTION for pre-2010 history pending Tomas (Q-T2).
- **Fees (ASSUMPTIONS pending Tomas, Q-T1):** commission **$0.65** per contract per leg per side (the top of Ethan's range; Alpaca's own options commission may be $0, but the conservative figure binds), plus exchange/regulatory/clearing fees (ORF, OCC, FINRA TAF, SEC on sales) **$0.05** per contract per leg per side all-in. A round-trip condor is 8 leg-sides × $0.70 = **$5.60 per condor contract** (primary) or **$11.20** (stress).
- **Cost-only stress.** Sizing (§8) and all triggers (§5) are independent of k and of fees, so the stress is a cost-only column (asserted in code: identical position paths). Tomas's figures replace these when higher or better evidenced (STANDARD §5).
- **Marks.** Daily mark-to-market is at **mid** for every leg. Entry and exit cash flows use the fill model, so spread cost appears on fill days.

## 7. Data-quality filters, provenance and point-in-time rules

**Per-quote filters.** These apply to every candidate leg at the decision snapshot t and again at the fill snapshot t+1. A failing quote is dropped, and the drop is counted by reason and year.
1. **Crossed or locked:** drop if ask ≤ bid.
2. **Zero bid:** drop if bid ≤ 0 (at entry; for exits see §5).
3. **Missing fields:** drop if bid, ask, strike, expiry or type is missing; or vendor IV or delta is missing (a broken-record signal, even though desk IV is primary); or desk IV is undefined (§4a).
4. **IV sanity:** desk IV outside [0.01, 3.00] is dropped. |vendor IV − desk IV| > 0.05 (absolute) is **flagged**, and > 0.10 is **dropped**. Flag and drop rates are reported by year.
5. **Staleness:** if the record carries a quote timestamp, it must lie within ±15 minutes of the session's option close (16:15 ET, or the early-close equivalent), otherwise it is stale. If there is no timestamp, a quote is stale when bid, ask and vendor IV are all identical to the previous session's while the underlying raw close moved by more than 0.5%. Stale quotes are dropped.
6. **Liquidity (entry legs only, from snapshot t; Rachel §5):** open interest ≥ **500**, session volume ≥ **100**, and relative spread (ask − bid)/mid ≤ **0.10**, or (ask − bid) ≤ **$0.10** when mid < $1.00. OI in an EOD record is treated as start-of-day OI (the OCC convention). The vendor field definition is to be confirmed (Q-E3).
7. **Put-call parity:** a strike pair with |C_mid − P_mid − D(F − K)| > max($0.05, 0.5 × (call spread + put spread)) is excluded from IV computation. Also |F/S − 1| ≤ 0.02 for DTE ≤ 60, otherwise the expiry is unusable that session.
8. **Monotonicity:** call mids must be non-increasing and put mids non-decreasing in strike within an expiry. Violating strikes are excluded.
9. **Existence:** every leg contract must exist in the chain on **every** session from fill to exit, with a standard root, standard 100-share deliverable and standard monthly expiry. **Adjusted / non-standard-deliverable series are excluded**, and so are any corporate-action-adjusted contracts.

**Missing days.** These are inventoried by underlying and year and **never forward-filled**. If an open position cannot be marked on a session, that session has no NAV observation. The P&L accrues to the next markable session as a multi-day return, and the count is reported. Gate inputs are never imputed.

**Coverage threshold (decided now; uses counts only, no prices or returns).**
- An underlying-session is *usable* if the snapshot has a standard monthly expiry with DTE in [21, 60] that has a derivable parity forward and **≥ 10 valid OTM puts and ≥ 10 valid OTM calls** after filters 1-9.
- An underlying-year *passes* if **≥ 95%** of its XNYS sessions are usable.
- Fallback start rule, per underlying u: the start year Y_u is the smallest Y in {2009, 2010, 2011, 2012} such that year Y−1 (warm-up) and **every** year from Y−1 through the data cutoff pass. u has no trades before Y_u, and the segment boundaries in §9 are unchanged.
- If no such Y exists for **either** root, **STOP**. Return to Victor, with no SPY-only rescoping without an amendment.
- The coverage table is produced by the data owner (Dmitri/Ethan) as counts only, before DEV, and Dave sees counts only.

**Provenance (required before DEV).**
- Each Alpha Vantage response (symbol, date) is stored as raw bytes with sha256, first-seen UTC timestamp and request parameters, **with the apikey redacted**.
- "Information" or rate-limit notes are never stored as data.
- There must be a data-owner manifest (sha256 of every file plus a top hash).
- Dmitri/Ethan document AV's historical-options IV/greeks methodology, field definitions (OI timing, quote timestamp, snapshot time) and the QQQQ→QQQ mapping (Q-E2, Q-E3).
- Underlying raw closes, SPY total return and VIX/VIX3M come from **Dmitri's pinned store**, not from ad-hoc pulls.

**Point-in-time.** Snapshot t is usable at 21:30 ET on t. No later vendor correction is used. Dividends: the projected amount is the last paid regular dividend, and the ex-date is the issuer-published or historically scheduled date as known at t (the source is pinned by Dmitri). Segment read-filters are asserted at load (§9).

**Data-quality exclusion rate.** This is the share of decision-window sessions in a segment where an otherwise eligible entry (gates evaluable) was blocked purely by §7 filters. It is reported, and a kill applies if it exceeds 10% (§11).

## 8. Sizing (Risk DRAFT caps used as assumptions only)

Exact lines confirmed in Rachel's draft (sha `f35afbe8…`), §2 table:
- `| Per-position max loss | **0.5%** | Half of H2 (1%). ...`
- `| Per-underlying aggregate max loss (all option structures on one root) | **1.0%** | ...`
- `| Options sleeve aggregate max loss (sum of defined max losses) | **3.0%** | ...`

The header says "**Status: DRAFT, NOT EFFECTIVE.**" and §2 is titled "Proposed position and sleeve limits — **PROPOSED** (Daniel confirmation required)". The same draft (§5) also says to "Reject the ticket if natural-price max loss breaches §2 caps even when mid does not". That rule is adopted here.

- **Max loss per contract:** ML₁ = (W − credit_natural) × 100 + $5.60. Here W = the **larger** of the put-wing and call-wing widths, credit_natural = net credit at **natural** prices on the fill snapshot, and $5.60 = the round-trip primary fees.
- **Contracts:** n = **floor**(0.005 × B / ML₁). If n = 0 (even one contract breaches 0.5%), **SKIP** the entry; it is counted and not re-tried that cycle.
- **Underlying and sleeve caps:** check Σ ML per root ≤ 1.0% × B and Σ ML across the sleeve ≤ 3.0% × B. With one condor per root (§4), at most 0.5% per root and 1.0% per sleeve are used, so these caps never bind in P01. They are checked anyway. Rachel's max of 10 open structures also never binds (≤ 2).
- **Base B = constant model NAV $1,000,000, with no compounding.** Daily return = daily P&L / B, and drawdown = peak-to-trough of cumulative P&L / B. Rationale: it keeps position paths identical across fill models and across variants that differ only in exits (cost-only stress), and it keeps integer-contract granularity small.
- **Feasibility diagnostic D01:** identical rules with B = **$100,000** (the desk's current HWM in LIMITS). It reports the skip rate. If the OOS skip rate is > 50%, the verdict must state that P01 is **not deployable at the current paper NAV** under delta wings, and Rachel/Jeremy must resolve it before any paper use (Q-R2). An arithmetic note: at $100k the per-position budget is $500, and 5Δ wings at 45 DTE on index ETFs are typically wider than that permits. This is general knowledge, not data.
- Cash earns the daily risk-free rate (Ken French RF, pinned), so sleeve excess return = option P&L / B. Sizing is research only; real limits come from Rachel's effective version.

## 9. Split: warm-up / DEV / embargo / OOS / embargo / holdout (fixed now)

All segments are defined on **entry-decision dates**. Each trade's P&L belongs to its entry segment, and its daily NAV runs to its exit (max hold ≤ 45 calendar days, well inside any embargo).

| Segment | Entry-decision sessions | Read-filter bound (asserted at load) | Months |
|---|---|---|---|
| Warm-up (gate inputs only, no trades) | 2008-01-02 .. 2008-12-31 | — | 12 |
| **DEV** | **2009-01-02 .. 2016-05-31** | data ≤ 2016-07-31 | 89 |
| Embargo A (never evaluated) | 2016-06-01 .. 2017-08-31 | — | 15 |
| **OOS** (one look) | **2017-09-01 .. 2022-07-29** | data 2016-06-01 .. 2022-09-30 | 59 |
| Embargo B (never evaluated) | 2022-08-01 .. 2023-10-31 | — | 15 |
| **Holdout** (sealed until Victor approves) | **2023-11-01 .. 2026-08-31** | data 2022-08-01 .. 2026-10-30 | 34 |

- **Rule used to set the dates (mechanical, not outcome-based):**
  - data span 2008-01 .. 2026-08 entries (224 months);
  - minus 12 months warm-up;
  - minus two 15-month embargoes;
  - minus a 34-month holdout, ending so that every holdout trade closes before the data cutoff 2026-10-30;
  - the remaining 148 months are split 60/40 into DEV 89 and OOS 59 months.
- **Embargo length.** It must be ≥ max holding period (≤ 45 calendar days ≈ 37 sessions) + IV-rank lookback (252 sessions) = **≥ 289 XNYS sessions**. 15 calendar months is about 315 sessions, and the code asserts ≥ 289 for both embargoes. The OOS's first IVR window (from ~Aug 2016) and the holdout's first window (from ~Oct 2022) lie wholly inside the preceding embargo.
- **Coverage fallback** (§7): per-underlying start years shift DEV's start only (to 2010, 2011 or 2012 at the latest). OOS and holdout boundaries never move.
- **Holdout custody:** Dmitri keeps holdout-period files in a separately hashed partition. OOS/DEV code cannot read past its bound (asserted).
- STANDARD §3 requires ≥ 3 years strictly OOS: OOS = 4.9 years ✓ (not blind, §1b). STANDARD §2 requires ≥ 10 years of history: 2008-2026 ✓.

## 10. Metrics (reported under **both** the primary and stress fills, for every configuration and segment)

**Primary.**
1. **Annualised Sharpe** of daily sleeve **excess** returns, marked to market daily at mid on every session including non-trade days: mean/sd × √252, net of all costs.
2. **Max drawdown** of cumulative daily P&L / B.
3. **Alpha vs the S&P 500.** OLS of daily sleeve excess return on SPY **total-return** excess return (Dmitri's pinned TR, Ken French RF): r_s − rf = α + β(r_SPY − rf) + ε. α is annualised × 252. Newey-West HAC uses the Bartlett kernel with **lag L = floor(4·(T/100)^(2/9))**, T = daily observations used (the COMMON C6 #4 convention), with no prewhitening and small-sample factor T/(T−1). Segments are not adjacent, so autocovariances are summed within a segment only.

**Secondary.**
- Hit rate; trade count by exit reason; average entry credit / ML₁; average days held.
- Worst day, worst 5-session week, worst trade.
- Daily CVaR 95% and 99% (historical).
- Daily skew and excess kurtosis.
- Exposure-adjusted return (P&L per unit of average Σ ML outstanding).
- Turnover: contracts and condors per year.
- **Cost share** = (spread cost + fees) / gross entry mid credit.
- Gate pass rates (IVR, slope, both).
- Skip counts (sizing n = 0, filters, window expiry).
- Assignment-risk sessions; exit-fill failures; D01 skip rate.
- Regime table (STANDARD §7): calendar year; SPY above/below its 200-day SMA (t−1); VIX t−1 above/below the evaluated-sample median; VIX t−1 > 25 vs ≤ 25.
- **Deflated Sharpe Ratio** (Bailey & López de Prado 2014). SR₀ = √(s²_SR) × [(1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne))], γ = 0.5772. s²_SR is the sample variance of the annualised OOS net Sharpes of the non-stress configurations (plus any family IDs Victor adds). The DSR statistic uses daily units, T, skew and raw kurtosis, as in COMMON C11. Report SR₀, N, T, skew and kurtosis. **N** per §13.
- PBO: with fewer than 10 configurations it is **uninformative** (STANDARD §4). It is stated as such and never used as a pass.

## 11. Pass and kill criteria (numeric, fixed now; P01 only is eligible; one look at OOS; holdout opened once)

**Stage gate DEV → OOS (all required, else STOP and OOS is never opened):**
- D1: DEV net Sharpe (primary) ≥ **0.68**. This is 0.5 / 0.74, so the STANDARD §6 haircut still clears 0.5.
- D2: DEV net Sharpe (stress/natural) > **0**.
- D3: DEV max drawdown ≤ **3.0%** of B.
- D4: no kill criterion K1-K5 triggered in DEV.
- D5: **Trade-count projection.** Projected OOS trades = floor(DEV entries per eligible cycle × 118 eligible OOS cycles, i.e. 59 months × 2 roots). If this is **< 100** (STANDARD §3), return to Victor **before** opening OOS. No redesign is allowed to raise the count (Q-V1).

**OOS pass (all hard; any miss = FAIL):**
- O1: OOS net Sharpe (primary) > **0.5**.
- O2: OOS net Sharpe (natural fills + 2x fees) > **0** (STANDARD's 2x-cost bar; stricter than "non-negative").
- O3: OOS max drawdown ≤ **3.0%** of B under the primary fills. This equals Rachel's 3% sleeve cap and leaves headroom under H8 5%.
- O4: alpha NW **t(α) ≥ 3.0** on DEV ∪ OOS daily returns (embargo excluded; STANDARD new-signal hurdle), with α > 0 in OOS alone. If Victor rules that VRP counts as a published theory-motivated anomaly, the bar becomes 2.8 (Q-V3). Until then 3.0 binds.
- O5: **DSR ≥ 0.95** at both N = 8 and N = 614 (§13) until Victor rules on the family.
- O6 (H2 gate value): OOS Sharpe(P01) − OOS Sharpe(C01) > **0**, primary fills.
- O7: neighbours R01-R04 each have OOS Sharpe > 0 and ≥ **50%** of P01's (STANDARD §7).
- O8: ≥ **100** OOS trades (STANDARD §3), unless Victor rules otherwise before freeze (Q-V1).
- O9: no calendar year contributes > **40%** of total OOS+DEV net P&L, and no regime in the §10 table has Sharpe < **−0.5**.

**Kill criteria (any segment; any hit = FAIL / immediate stop):**
- K1: **Single-event loss.** Any single trade's realised loss > **0.60%** of B (the 0.5% defined max plus a 20% allowance for fees and rounding). That would mean a model, gap-fill or assignment failure.
- K2: **Regime concentration.** More than **40%** of the segment's net P&L comes from one calendar year (as O9), **or** more than **60%** of gross losses fall in a single episode of ≤ 20 consecutive sessions.
- K3: **Data quality.** The §7 exclusion rate is > **10%** of decision-window sessions in the segment, **or** the vendor-vs-desk IV drop rate is > 10% of candidate legs.
- K4: **Costs.** Total primary costs (spread + fees) are > **40%** of gross entry mid credit over the segment. At that level the natural stress would consume > 80% of the credit.
- K5: **Exit integrity.** More than **2%** of trades hit the 2-DTE max-loss booking (§5), or any position is held into expiry day (code assertion; must be zero).

**Holdout (opened once, all configurations in one sitting, only after Victor approves the OOS verdict).** It is a confirmation, not a re-tune. P01 holdout net Sharpe (primary) > **0**, natural-fill Sharpe ≥ **0**, max drawdown ≤ **3.0%**, and no K1-K5 hit. A miss means FAIL. No amendment is allowed after the holdout is opened.

**Verdict ceiling:** CONDITIONAL PASS (§1b). Expected Sharpe for sizing = min(OOS SR, 0.74 × DEV SR) (STANDARD §6). Variants and controls are never promoted.

## 12. Forward paper (the clean test; not authorised by this document)
After a historical CONDITIONAL PASS, the clean test is P01 on Alpaca paper, rules unchanged: ≥ **60 trades or 3 months**, whichever is later (STANDARD §9). It also needs Rachel's effective limits, Tomas's TCA and Daniel's pinned confirmation lifting H5. Paper fills are compared with the §6 primary model, and re-review fires if realised costs exceed 1.5x the assumed costs.

## 13. Trial inventory and forking paths (closed list; no other variant may be run without a hashed amendment that raises N)

| ID | Definition (differences from P01 only) | Role |
|---|---|---|
| **P01** | as above | **Sole primary; only eligible to pass** |
| C01 | IVR and slope gates **off** | Control for H2 (gate value) |
| R01 | short \|Δ\| 0.192 [0.15, 0.24]; wing \|Δ\| 0.06 [0.04, 0.09] (+20% joint) | Neighbourhood |
| R02 | short \|Δ\| 0.128 [0.10, 0.16]; wing \|Δ\| 0.04 [0.02, 0.06] (−20% joint) | Neighbourhood |
| R03 | IVR threshold **36** (+20%) | Neighbourhood |
| R04 | IVR threshold **24** (−20%) | Neighbourhood |
| R05 | No 21-DTE time exit (hold until the profit/stop/ex-div exit or the 2-DTE backstop) | Robustness (gamma exposure) |
| D01 | B = $100,000 (integer-feasibility diagnostic) | Diagnostic, never promotable |

- Local enumerated **N = 8**. The stress fill is a **cost-only column**, not a trial, because sizing and triggers are fill-independent and position paths are asserted identical.
- Robustness variants and controls **cannot rescue** a failed P01.
- PBO is uninformative at 7 non-stress configurations.
- **Family N:** the slope gate shares the VIX/VIX3M curve family with SCS (N ≥ 606). Until Victor rules (Q-V2), DSR is gated at both N = 8 and N = **614** (606 + 8), and both must clear.
- **Not registered:** Ethan's "term-stress" sign, fixed-$ wings, weeklies, event filters, profit-take and stop alternatives, other DTEs and K values. Running any of them is a new trial.
- **Forking-path log for this folder (append-only, started now):**
  - #1, 2026-11-10 ~01:37 SGT: `sha256sum` of the two inputs. No data.
  - #2, ~01:38-01:41: read text files listed in §0. No data.
  - #3, ~01:42: `mkdir` of this folder.
  - #4, ~01:45-02:10: wrote PREREG_v0.1.md, PARAMS_v0.1.json and SHA256SUMS with `/usr/bin/python3` / `sha256sum` (hashing and JSON validation only).
  - No data was touched.
- **STANDARD §7 neighbourhood:** the full ±20% one-at-a-time and joint grid over every parameter (short Δ, wing Δ, entry DTE, profit-take, time exit, IVR threshold, IVR lookback, K) would add up to ~16 + 2⁸ configurations. This draft registers the reduced set above, and Victor must accept or extend it **before freeze** (Q-V5).

## 14. Governance

- **Approvals required before DEV:**
  1. Victor validates this prereg (and any amendments) and issues a freeze receipt.
  2. Rachel's risk sign-off covers *effective* limits. This draft only borrows proposed caps.
  3. Tomas confirms the options cost schedule (§6).
  4. Dmitri/Ethan, as data owners, accept the AV chain data with a sha manifest, the methodology note and the counts-only coverage table (§7).
  5. A synthetic-only test suite for the evaluator passes, with the code hash sealed.
- Paper use additionally requires Daniel's own pinned confirmation (N1) and H5 amended in LIMITS. Agent-relayed approval is not approval.
- **Amendments:** append-only. Each is a new file `AMENDMENT_v0.1x_*.md` with a sha256 HASH_DIFF against the prior pins. Predecessor files are never edited. Any change after freeze that affects positions is a new trial (N rises). No amendment is allowed after OOS opens except a documented bug fix, which is logged as a new trial.
- **Outcome custody (proposed; role appointments go to Daniel through Jeremy, and I do not fill them):**
  - DEV may be run only after the five approvals above, by the person Daniel appoints. I propose Dave as the code author, with the code hash pinned and read-filters asserted.
  - OOS is run once, all 8 configurations in one sitting with PREREG hashes logged first, by a custodian Victor nominates.
  - The holdout is opened only by Victor's decision, once.
  - Every run appends to a trial log with the T × N daily return matrix (STANDARD §1).
- **Data handling:** the Alpha Vantage key is never printed or logged. Dave does not view chains, VIX or prices before DEV is authorised. Coverage information reaches Dave as counts only.

## 15. Open questions

**Ethan.**
- **Q-E1:** your idea says "vol-rich / term-stress" for the slope region. Did you mean contango required (registered here) or backwardation? The other sign would be a separate, counted trial.
- **Q-E2:** document Alpha Vantage's historical-options IV/greeks methodology (model, rate, dividends, American/European, snapshot time). Without it, AV IV stays cross-check only.
- **Q-E3:** confirm the AV field definitions: quote timestamp present? OI start-of-day vs end-of-day? Does the "date" mean the 16:00 or 16:15 ET snapshot? Is the QQQQ→QQQ pre-2011 mapping handled? Are adjusted/non-standard series flagged?
- **Q-E4:** should the chain data land in Dmitri's store (desk rule) rather than an Ethan-owned path? It also needs a holdout partition.

**Victor.**
- **Q-V1:** P01 has at most 118 OOS cycles (59 months × 2 roots). With gates, < 100 OOS trades is likely, so STANDARD §3 (≥ 100) is probably unattainable by design. Accept a lower bound with the CONDITIONAL ceiling, count OOS + holdout, or treat it as FAIL? A ruling is needed before freeze.
- **Q-V2:** is the DSR family N = 8 (local) or the union with SCS (N ≥ 606, 614 total) because of the shared VIX/VIX3M input? Interim: both must clear.
- **Q-V3:** alpha hurdle 3.0 (new signal) vs 2.8 (published VRP anomaly)?
- **Q-V4:** does STANDARD §2's survivorship haircut apply to an SPY/QQQ-only universe?
- **Q-V5:** is the reduced ±20% neighbourhood (§13) acceptable?
- **Q-V6:** is a fill at the next-session EOD snapshot acceptable as "next bar or worse" for options?

**Rachel.**
- **Q-R1:** the caps are borrowed from DRAFT v0.1 (not effective). Will the effective version keep 0.5/1/3% and the natural-price max-loss rule?
- **Q-R2:** at a $100k HWM, 0.5% = $500 per position, so many 5Δ-wing condors will round to zero contracts. Is a larger paper NAV acceptable, or should a narrower-wing design be registered as a separate trial?
- **Q-R3:** the ex-dividend rule uses the last paid dividend as the projection. Is that acceptable?

**Tomas.**
- **Q-T1:** confirm the options commission ($0.65 assumed vs Alpaca's actual) and the all-in ORF/OCC/TAF/SEC fees ($0.05 per contract per side assumed).
- **Q-T2:** is the $0.01 tick valid for SPY/QQQ options across 2008-2026?
- **Q-T3:** is k = 0.5 (mid ∓ 25% of the full spread) a fair primary for 4-leg combos on SPY/QQQ? Is a paper-vs-vendor fill haircut needed?

**Dmitri.**
- **Q-D1:** pin the VIX/VIX3M release, the SPY TR, the raw bars and the dividend ex-date and amount source for 2008-2026.
- **Q-D2:** produce the counts-only coverage table and the holdout partition.

*End of PREREG DRAFT v0.1. Not frozen. No data viewed, no returns computed, nothing authorised.*
