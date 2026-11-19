# PRE-REGISTRATION: VIX term-structure backwardation → short-horizon SPY rebound (RISK-OVERLAY CANDIDATE)
`slug: vix-backwardation-spy-rebound`

**Owner:** Maya (Macro Strategist) · **Source:** original (not a paper replication) · **Written:** Fri 30 Oct 2026, ~01:55 SGT (Thu 29 Oct ~13:55 ET), **before any run of any kind**
**Status (v1.1, after the validator's decision the internal review record (the validator, ~02:05 SGT)):RECLASSIFIED: risk-overlay candidate for the risk manager/portfolio-construction lead, NOT an alpha signal.** It is not eligible for the sealed-file unseal as a signal test. Its 7 primary/neighbour slots and the placebo still count in N = 79. Earlier status: PRE-REGISTERED / candidate. No backtest, no conditional-return look, nothing computed on the outcome series. The validator must sign this spec before Stage A runs. After that sign-off, any change is logged in §12 with a timestamp and counts as a new trial.
**Governing documents:** `validation/STANDARD.md` v1.0 + Addendum A (2026-10-30 02:05 SGT); `risk/LIMITS.md` §1; `tca/cost_model.md` v1.1.

## 1. Hypothesis
When the VIX term structure inverts (spot VIX above 3-month VIX at the close), the S&P 500 earns an abnormally high return over the following ~2 weeks. That is compensation for supplying liquidity when near-term crash-hedging demand is acute. The claim is *beyond* what a plain price-drop reversal predicts.

## 2. Economic mechanism (why it should exist, who is on the other side)
- **What the inversion signals.** An inverted VIX/VIX3M means near-dated insurance is bid above longer-dated insurance. That is a direct, market-wide, price-based (non-survey) measure of acute hedging demand, and of forced de-risking by vol-target, risk-parity and VaR-constrained books.
- **Who is on the other side.** Dealers and vol sellers widen out, and capital for warehousing equity risk becomes scarce (limits to arbitrage). The buyer of equity at that moment earns a premium for bearing crash risk when the marginal investor's marginal utility is high.
- **Why it persists.** It requires buying exactly when drawdowns, stops and risk committees bind.
- **Why it is not just reversal.** The VIX state measures the *price of insurance*, not the price move itself. The required alpha test (controls for SPY 5- and 21-day reversal) and a pre-registered drawdown-matched placebo test exactly this.

## 3. Universe
SPY (long only; no shorts), BIL (cash). Signal inputs: CBOE VIX and VIX3M index levels (never traded; no options, per LIMITS H5).

Crypto is excluded (desk rule). There is no leverage and there are no options.

## 4a. Exact signal rules (single primary spec)
| Item | Rule |
|---|---|
| Ratio | `R_t = VIX_close_t / VIX3M_close_t` (CBOE official closes, 16:15 ET). |
| Entry | If `R_t > 1.00` and flat → buy SPY `w` at the **t+1 open**. |
| Hold / exit | Exit at the open after the **10th consecutive session with `R ≤ 1.00`** (episode end), or on a stop (2×ATR(14) from fill, never loosened), whichever comes first. A new inversion during the hold resets the 10-session count. There is no adding. |
| After a stop | No re-entry until the current episode has ended (10 sessions with R ≤ 1) and a fresh `R > 1.00` occurs. |
| Size | `w = min(9.5%, 0.95%/stop_pct)`. At stressed ATR this will often be < 9.5%. |
| Placebo (logged trial, not a candidate) | The same holding and stop logic, but entering on SPY's 10-session return ≤ q. q is set so that the number of entry days equals the primary's in **Stage A**. The placebo's returns enter the alpha regression. |

## 4. Execution, sizing, stops (common to the Maya original batch)
| Item | Rule |
|---|---|
| Signal time | At the official close of session t, using only inputs with first-public-availability (ET) ≤ the close of t (see §6). Inputs whose availability is unverified are lagged one extra session. |
| Fill | **Next session's open** (t+1), TCA owner v1.1 `venue="open"`. Per Addendum A, nothing computed after 15:59 ET trades before the next open. |
| Sizing per leg | `w = min(9.5%, 0.95% / stop_pct)`, where `stop_pct = 2 × ATR(14)_t / close_t` (LIMITS H1 buffer and H2 risk ≤ 1% per trade at the 0.95% buffer). This is fixed at entry and not re-sized while held. |
| Stops (H6) | Every position gets a stop for its full quantity at entry ± 2×ATR(14) from the fill price. The stop is **never loosened** (no trailing either; fixed for v1 simplicity). Simulation: a long is stopped if the session low ≤ stop; the fill is min(open, stop) (gap-through at the open). Shorts mirror this. Cost is the TCA owner `venue="continuous"`. |
| After a stop | Pair hypotheses (oil, curve): the other leg is closed at the next open, and the book stays flat until the signal *changes state*. VIX hypothesis: flat until a new trigger after the current episode ends. |
| Gross / leverage | Max gross ≤ 19% (two legs ≤ 9.5%) for the pair hypotheses, and ≤ 9.5% for the single-leg VIX hypothesis, far inside the LIMITS H3 gross buffer of 58%. Longs are cash-funded; short proceeds are not reinvested. Idle cash sits in **BIL** (total return). No leverage (H4) and no options (H5). |
| H7 earnings blackout | ETFs only, so n/a. Constituent-earnings concentration is noted as a risk, not a rule. |
| H8/H9 | **LIMITS v0.3 semantics, applied at the sleeve level in simulation** (decision amendment 4). A 5% DD from peak halves gross (cap 30%). An 8% DD from peak → HALTED. A halt *holds the book*: no new positions or adds, de-risk only, gross ≤ 30%, and stops stay live. Exits and stop-outs are always allowed. Lift (simulated): ≥ 5 sessions since the halt, the shadow book's 5-session net return ≥ 0, and the CIO review is assumed logged at the lift date. Resume at a 30% gross cap in RESUMED-DISARMED, with a 3% backstop (E_resume × 0.97, live) that re-halts immediately. Re-arm the 8% halt only once EOD DD < 5%. Full gross only once EOD DD < 3%. Chain cap: a second backstop trip in the same peak-to-peak episode holds the halt until EOD DD < 5%. In practice this sleeve's gross (≤ 19%) is already under 30%, so the binding effect is 'no new entries while halted'. |
| Shorts | Only if the ETF is shortable and ETB. Flags are today's snapshot (`assets_2026-10-29`), which is a **look-ahead caveat**: historical locate availability for SPDR sectors is assumed. Borrow cost **1%/yr GC base (STANDARD floor)**, with 2% in the 2× case. |

## 5. Data
**Data hash (pin at run):**
- `DATA_VERSION = <TO PIN: data/VERSION line at run time>`
- `SHA256(daily_total_return.parquet) = <TO PIN>`
- `SHA256(extended file) = <TO PIN at Stage B unseal>`
- `SHA256(each external input file) = <TO PIN>`

Reference at registration: VERSION `v1.0 9dac0fdc95a1e1ef9c4a6cf7713ebbf67f15a09e4ebe41d654893ddaeb9e6ad2` (2026-10-30T01:44:06+08:00), TR parquet `0590692d765515e0f76f4f6b7360c5ed7be38e2e85a5f91562dbfebcf8a129db`, snapshot `data/snapshots/20261029T174406Z_v1.0.json`. If the build differs at run time, the run uses the new build and records both hashes.

## 6. Point-in-time availability of every input (Addendum A, times ET)
| Input | First public availability (ET) | First session it can affect | Revision / vintage handling |
|---|---|---|---|
| CBOE VIX daily close (`VIX_History.csv`) | Official close **16:15 ET t**. The CBOE CSV for 28 Oct was Last-Modified 21:11 ET 28 Oct (upper bound) | Close t → **t+1 open** (Addendum A: computed after 15:59 ET) | Index prints are not revised. **Data-quality flag:** the CSV has more rows than NYSE sessions in 2022–25, so de-duplicate against the NYSE calendar |
| CBOE VIX3M daily close (`VIX3M_History.csv`) | 16:15 ET t. The CSV was Last-Modified 17:31 ET 28 Oct | t+1 open | Not revised |
| SPY, BIL (desk store, SIP; Stage B extended) | SIP close 16:00 ET t | t+1 open | The TR series is used for P&L only |

### 6a. Source coverage by year (survivorship audit)
| Source | Span | Rows per year / coverage |
|---|---|---|
| Desk bar store (SIP), `total_return/daily_total_return.parquet` → `ret_total_best`, plus split-adjusted OHLC for ATR | 2016-01-04 → 2026-10-28 | Each year 2016–2025: 250–253 sessions; 2026: 207 (to 28 Oct). Counted 30 Oct ~01:55 SGT for SPY, BIL. No gaps |
| CBOE VIX (as served 29 Oct) | 1990-01-02 → 2026-10-28 | 248–254 rows/yr 1990–2021; **256/257/259/258 in 2022–25** (anomaly); 213 in 2026 |
| CBOE VIX3M (as served) | **2009-09-18** → 2026-10-28 | 2009: 73; 2010–2025: 250–253; 2026: 207 |
| Ken French factors | 1963 → 2026-09-30 | Full |
| Stage B extended SPY (sealed) | 2005+ | Coverage by year reported at unseal |

Survivorship:
- The instruments are long-lived SPDR/major ETFs that exist today, which is a mild survivor bias. I know of no delisted or closed ETFs that would be substitutes.
- No accounts or feeds are used.

## 7. Cost model (TCA owner v1.1, `tca/tca_scripts/cost_model.py`)
- `trade_cost(side, price, shares, adv_shares, sigma_daily, spread_bps, venue, k=1.0)`:
  - ADV = trailing 20-session SIP ADV, lagged one day.
  - sigma = 20-day close-to-close volatility, lagged.
  - Bucket by $ADV: L1 > $1B, half-spread 2.75 bps + buffer 2.0 bps.
  - All instruments here are expected to be L1/L2. The run must check this, not assume it.
- Venue `open`: half-spread × 0.5, impact × 1.0. Stop exits use `continuous`. SEC fee 0.206 bps on sells; FINRA TAF per v1.1 (fee holiday to 31 Dec 2026, then modelled).
- Borrow: 1%/yr on short notional, accrued daily (base). Interest on BIL cash comes through BIL total return; there is no rebate on short proceeds.
- **Headline = k=1.0 base costs.** The 2× stress doubles every cost component including borrow. The break-even cost multiple must be ≥ 2× (STANDARD). k = 0.5 is reported only as a diagnostic.

## 8. LLM / text / sentiment-vintage statement (Addendum A)
- **No LLM is used at any step:** not for signal construction, labelling, parameter choice or evaluation. There are no prompts or models to pin. If any LLM step were later added, it would be a new pre-registration with the model version, prompt hash and a knowledge cutoff before the OOS start. For Stage B that means a cutoff **before 2005**, which no current model meets, so Stage B would be contaminated.
- **No vendor sentiment score, no X/news input, and no backfilled or recomputed sentiment data.** All inputs are exchange prints or official statistics, with first-availability timestamps per §6.
- Any FRED series is taken as an **ALFRED real-time vintage**: the value as first published on each date (`realtime_start` = observation availability), never the current revised value.

## 9. Evaluation windows, holdout, primary spec
- **Single primary spec** = §4a + §4. Nothing else is a candidate.
- **Stage A (in-sample, seen; *not* OOS):** desk store **2016-07-01 → 2026-10-28** (allowing for the 63-session warm-up). Purpose: a sanity and plumbing check, and the haircut-Sharpe precondition (§10.1). Because of §13, Stage A cannot pass the idea on its own.
- **Stage B (OOS): **2009-12-01 → 2016-06-30**, about 6.6 years. VIX3M as served starts 2009-09-18, and the window allows for warm-up. 2008 is therefore *not* testable with this input, and VXV older history is not used because it would be a different source.** This is the sealed `bars/daily/extended/` file. **Decision (b): it is opened ONCE for the whole batch** (trend v3, oil, curve). That happens only after every spec is frozen with a SHA-256-hashed PREREG logged in `trials.csv` (see `research/original/BATCH-MANIFEST.md`) and the data owner's signed-off snapshot hash is pinned. All the ideas run in one sitting. After the first result is seen there are no amendments, and no re-specification or re-run of a failed idea on the sealed data. The 2016+ overlap is excluded, so the two windows are disjoint.
- **Stage C (live paper):** shadow-traded from registration, with the PIT archive (the data owner) and no capital, as an extra forward check.
- **Reclassification (decision):** Stage B (2009-12 → 2016-06) lies entirely inside the partly-seen SPY 2008–16 window, and the rule is episodic. Validation moves to the risk manager's overlay framework: *does a 'no de-risking into backwardation' rule improve book drawdown and recovery?*, with the drawdown-matched placebo kept. The signal-style pass bars in §10 are superseded by the risk manager/portfolio-construction lead's overlay criteria, which they set. The PIT, cost and trial-accounting sections still apply.
- **Trade-count risk (now moot as a signal):** The rule is episodic, so OOS round trips are **likely well below 100** (this has not been counted and is a judgement only). It is registered mainly as a **risk-overlay candidate**: 'don't cut gross into backwardation'. That is for the risk manager/portfolio-construction lead, and it does not need the trade-count bar. As a trading signal it will probably fail item 7.

## 10. Pass criteria (STANDARD.md §1 hard bars + Addendum A). All must hold on **Stage B (OOS)**, net of base costs.
1. Net OOS Sharpe > 0.5 (annualised from daily returns, in excess of BIL), and > 0 at 2× costs.
   - **Stage A precondition (decision amendment 7):** 0.74 × raw Stage A net Sharpe > 0.5, i.e. **raw Stage A Sharpe > 0.68**. If Stage A fails that threshold, the idea **ends without unsealing**.
   - Stage B is judged unhaircut.
2. DSR ≥ 0.95 using the **cumulative** trial count N from §11 (**N = 79**, rising with any extra trend-v3 trials; §11), with the skew and kurtosis of the OOS returns.
3. Newey-West t ≥ 3.0 on mean daily net return. Lags = floor(4(T/100)^(2/9)), with 21 lags also reported.
4. **Incremental-alpha test (Addendum A, required).** Regress daily net excess returns on:
   - Ken French FF5 (Mkt-RF, SMB, HML, RMW, CMA);
   - **UMD (Mom)** and **ST_Rev** (daily, store copy `factors/`; it ends 2026-09-30, so after that the regression window ends there);
   - an **earnings-surprise factor: WAIVED** for these ETF-level macro rules, which are not keyed to earnings events (decision amendment 2; waiver logged here). If a PIT SUE factor exists by run time, it is included;
   - own-asset controls:
     - **SPY 5-day reversal** = −sign(SPY 5d return) × SPY daily return;
     - **SPY 21-day reversal**, built the same way;
     - **the drawdown-matched placebo's daily returns**.

   The primary must beat the placebo, with alpha vs the placebo at NW t ≥ 2.0.

   **Pass (decision amendment 1):** intercept > 0 with **NW t ≥ 3.0 on alpha**, as well as t ≥ 3.0 on the raw series (item 3), *and* alpha ≥ 50% of the raw mean excess return. A signal whose alpha vanishes once own-asset momentum/reversal is controlled for **fails** ("only restates recent returns").
4b. **Best attainable verdict = CONDITIONAL PASS.** Stage B is quasi-OOS only, because my §13 disclosure includes 2008 and the 2014–16 oil collapse (decision, Status).
5. PBO: with a single primary it is not computable or uninformative (< 10 variants). Reported as "n/a — single pre-registered spec". The ±20% neighbourhood (item 8) substitutes.
6. OOS ≥ 3 years (Stage B satisfies this; see §9). Embargo ≥ 5 sessions between any Stage A look and the Stage B start (the windows are disjoint in time, so the embargo is trivially met).
7. **Trades (decision (c)):**
   - A trade = **one pair episode** (entry → exit). The two legs are one decision.
   - The bar is **≥ 30 independent episodes in Stage B**. Otherwise it is FAIL on the hard bar, and the rule can go only to overlay context.
   - **Pre-unseal gate:** the Stage A episode count from signal inputs only (§15). If the projection is < 30, do not unseal.
8. Robustness:
   - every ±20% neighbour (§11) has net Sharpe > 0, and their median ≥ 50% of the primary's;
   - by year, no single year > 40% of total P&L;
   - regime splits: SPY above/below its 200-dma, VIX above/below its median, VIX > 25;
   - capacity: the position is ≤ 1% of 20-day ADV at the desk's $ size;
   - break-even cost ≥ 2× the assumed cost.
9. Max drawdown is reported. LIMITS v0.3 H8/H9 semantics apply in simulation (§4).

## 11. Trial accounting (Addendum A: every variant counts)
| Item | Count |
|---|---|
| Maya ETF macro-timing family to date, at the trend decision count (desk figure 46 so far, 47 with trend v3, decided at **N = 57** per v3 A1; decision (a)). *Corrected: the earlier 'validator counts 30' line was wrong.* | **57** |
| This batch, 3 hypotheses × (1 primary + 6 logged neighbours: lookback ±20%, threshold ±20%, joint (+,+) and (−,−)) | 21 |
| H3 placebo (drawdown-matched entry) | 1 |
| **Cumulative N for DSR (same family as trend; decision (a))** | **79** = 57 + 21 + 1 |
| Escalation | N rises one-for-one if trend v3 logs trials beyond 57. Any spec change after sign-off is +1. The USO→WTI fallback is +1 |

- All runs are logged to `outputs/trials.csv` (spec hash, time SGT/ET, metric) before results are viewed.
- Neighbours are robustness runs only. The primary is never replaced by a neighbour. Picking one would require a new pre-registration with N+1.

## 12. Change log
- 2026-10-30 02:02 SGT (29 Oct 14:02 ET): v1.1 applies the validator's decision: reclassified as a risk-overlay candidate for the risk manager/portfolio-construction lead, not a signal; trials still count (N=79); SPY and ^VIX partly seen for 2008–16; LIMITS v0.3 semantics. No episode gate is needed (not a pair signal). No returns computed.
- 2026-10-30 ~01:55 SGT: v1 written. No runs.

## 13. Disclosure: what I have already seen (forking-path audit)
- **Never computed:** any return of these rules, any conditional return of these ETFs on these signals, or any correlation between the signal inputs and future ETF returns. This applies to both the store and the extended data.
- **Seen in the store window (2016–2026):**
  - trend-sleeve v1/v2 results on CORE-L12 / the 23-ETF universe. That includes SPY, TLT/IEF, GLD and USO time-series momentum performance by year, but no XL* sector ETFs;
  - today's S&P 500 member breadth (28 Oct);
  - store metadata (coverage, row counts, ETB flags).
- **Seen in CBOE files today:**
  - the latest VIX/VIX9D/VIX3M/VIX6M closes and quotes (VIX/VIX3M ≈ 0.87–0.88, i.e. contango);
  - the first rows and row counts of the history CSVs (coverage audit only);
  - no history analysed.
- **General market knowledge (substantial; it contaminates Stage A):**
  - I know the broad shape of 2008, the 2014–16 oil collapse, the 2020 COVID crash and oil-negative episode, the 2021–22 energy outperformance and bear steepener/inversion, the March 2023 bank stress, and the VIX spikes of Aug-2015, Feb-2018, Mar-2020 and Aug-2024;
  - I know the 2026 Iran-war oil shock and the 2026 bear steepener.
  - **Motivation bias:** H1 and H2 were prompted by today's regime (Brent ~$113, 2s10s +38 bp). That is why Stage A (2016–26) is labelled **in-sample/seen**, and the verdict rests on Stage B.
- **Partly-seen tickers (decision (b)).** the validator's earlier 2008–16 trend read used the Yahoo chart-API extension for the 23-ETF trend universe plus ^VIX:
  - The universe was SPY QQQ IWM EFA EWJ EWG EWU EEM SHY IEF TLT GLD SLV USO UNG DBA DBC UUP FXE FXY FXB FXA FXC.
  - Sources: `validation/backtests/trend_sleeve/data_audit.py` and `fetch_yahoo.py`; `results.md` §8.
  - Of this batch's tickers, **SPY and USO (and ^VIX) were in it, so they are PARTLY SEEN for 2008–16.** Only 2005–07 is fully blind for them, and USO only exists from Apr 2006.
  - **XLE, XLY, XLF and XLU were NOT in it**, so they are unseen in the 2008–16 extension.
  - Seen means seen as one input to an aggregate trend result. I never saw conditional returns of these tickers.
- **Sealed extended file (`bars/daily/extended/`): NOT opened.** I know only manifest metadata relayed earlier: 2005+, Yahoo/yfinance source, 38 tickers, EWA not spliced. The validator's partial 2008–16 trend rerun on that file was reported to me only as an aggregate trend result, so 2008–16 is "partly seen" for SPY-heavy trend exposure. This matters most for H3 (SPY).
- **Related literature I am aware of (so the idea is "original" in construction, not in spirit):** Simon & Campasano (2014), VIX futures basis; the variance-risk-premium literature (Bollerslev, Tauchen & Zhou 2009); and practitioner lore that 'backwardation marks bottoms'. The construction here (a VIX/VIX3M threshold, a long-SPY rebound with a fixed episode rule, and the placebo) is mine. Because the idea is well-known folklore, I expect post-publication decay to apply in spirit.

## 14. Blockers / dependencies before Stage A
- **B1, data ingest (the data owner):** ingest CBOE VIX/VIX3M history into the store with session de-duplication and a first-availability column. The raw files are archived today in `research/sentiment/daily/raw/2026-10-30/`.
- **B2, ALFRED:** an API key is needed for FRED/ALFRED vintages, and FRED CSV/API timed out from the box today (29 Oct ET). Without vintages, any FRED-sourced input fails Addendum A.
- **B3, Stage B access:** the data owner/validator must sign off opening `bars/daily/extended/` **once, for this frozen spec**. They must also confirm that the tickers in §3 are among the 37 spliced ones, and that the yfinance total-return splice is acceptable as a TR source (STANDARD requires TR). Each year's coverage must be reported once it is opened.
- **B4, earnings-surprise factor (WAIVED by the validator's decision; include it if it exists by run time):** it is not in the store. The derivatives researcher/data owner need to build a daily PIT SUE long-short factor (EDGAR acceptance time → next open; XBRL diluted EPS, seasonal random walk). Its coverage is limited to the XBRL era (~2009+), so for 2005–09 the alpha test runs without it and that is flagged.
- **B5:** the validator ruled ~02:05 SGT 30 Oct (the internal review record (the validator, ~02:05 SGT)). This v1.1 applies his amendments. N = 79.
