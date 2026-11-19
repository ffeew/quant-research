# PRE-REGISTRATION: Oil cash-flow shocks: long energy / short consumer discretionary (and the reverse)
`slug: oil-shock-energy-vs-discretionary`

**Owner:** Maya (Macro Strategist) · **Source:** original (not a paper replication) · **Written:** Fri 30 Oct 2026, ~01:55 SGT (Thu 29 Oct ~13:55 ET), **before any run of any kind**
**Status (v1.1, after the validator's decision the internal review record (the validator, ~02:05 SGT)):** APPROVED WITH AMENDMENTS, but **GATE FAILED: DO NOT UNSEAL** (§15: projected 15.1 Stage B episodes < 30). Stage A returns are not run; it is overlay-context only unless re-pre-registered as a new trial. Earlier status: PRE-REGISTERED / candidate. No backtest, no conditional-return look, nothing computed on the outcome series. The validator must sign this spec before Stage A runs. After that sign-off, any change is logged in §12 with a timestamp and counts as a new trial.
**Governing documents:** `validation/STANDARD.md` v1.0 + Addendum A (2026-10-30 02:05 SGT); `risk/LIMITS.md` §1; `tca/cost_model.md` v1.1.

## 1. Hypothesis
When crude oil has moved sharply over the past quarter, the sector that receives the oil cash flow keeps outperforming the sector that pays for it over the following weeks:
- XLE beats XLY after oil spikes;
- XLY beats XLE after oil collapses.

In normal oil regimes there is no position.

## 2. Economic mechanism (why it should exist, who is on the other side)
- **Cash-flow transfer.** A sustained oil-price move is a large, measurable transfer of income between household and discretionary spending (gasoline as a tax) and producer revenues/FCF. It reaches *reported* earnings with a 1–2 quarter lag: realised prices, hedges rolling off, consumers drawing down savings before cutting spending.
- **Slow diffusion across industries.** Analysts and sector specialists in discretionary under-react to an input that sits outside their coverage, and revisions trickle in quarter by quarter. Energy analysts anchor on strip prices but lag on buyback and dividend capacity.
- **Who is on the other side, and why it persists.** Benchmark-constrained managers can't overweight energy far (it is a small index weight). Mean-reversion priors on oil ("it'll come back") make many fade the move. The signal fires rarely, so the edge is low-capacity in time and carries career and tracking-error risk.
- **Why no position in normal regimes.** I make no claim about small oil moves. The threshold keeps this a *shock* hypothesis rather than generic oil momentum.

## 3. Universe
XLE (Energy Select SPDR), XLY (Consumer Discretionary SPDR), USO (signal only, never traded), BIL (cash). All are in the store; all are L1/L2 by $ADV (to be checked at run time). XLE, XLY and BIL are flagged shortable/ETB in the 2026-10-29 snapshot.

Crypto is excluded (desk rule). There is no leverage and there are no options.

## 4a. Exact signal rules (single primary spec)
| Item | Rule |
|---|---|
| Oil signal | `o_t = ln(USO_close_t / USO_close_{t−63})` on split-adjusted SIP closes. USO pays no distributions, so the adjusted series = split-adjusted only. **Structural break disclosed (decision amendment 5), no adjustment:** from April 2020 USO moved away from holding only the front-month WTI contract to a mix spread across later months (plus the 1:8 reverse split). Its roll yield and its tracking of spot WTI therefore differ before and after 2020, and the break sits inside Stage A. That makes it PIT (no retroactive dividend adjustment), apart from the 2020 1:8 reverse split, which is handled by split adjustment. |
| State | `o_t ≥ +0.20` → **OIL-UP**; `o_t ≤ −0.20` → **OIL-DOWN**; otherwise **NEUTRAL**. The ±20% threshold was set ex ante as a round "shock" size. It is not fitted, and the distribution of `o_t` has not been looked at. |
| Evaluation | Weekly, at the close of the last session of each week (normally Friday), plus daily checks of the stops. |
| Positions | OIL-UP: long XLE `w`, short XLY `w`. OIL-DOWN: long XLY `w`, short XLE `w`. NEUTRAL: flat (BIL). Each leg is sized separately per §4. |
| Changes | Trade only when the weekly state changes. There is no weekly re-sizing (weights drift). A position never lasts beyond a state flip. |
| Fallback | Only if USO is absent from the extended file at Stage B: use ALFRED `DCOILWTICO` vintages lagged 1 session. This counts as +1 trial. |

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
| USO, XLE, XLY, BIL daily OHLC + TR (desk store, SIP) | SIP official close 16:00 ET on t. Store bars are final ~16:20 ET (the data owner's job) | Close t → trades at the **t+1 open** | Raw/split-adjusted: none. The TR series is dividend-adjusted retroactively, so it is used **only for P&L, never in the signal** |
| Same, Stage B (extended, Yahoo/yfinance splice) | End of day t (assumed). Yahoo's ingest time is not knowable, so treat it as close t | t+1 open | Yahoo adjusted closes are revised retroactively, so they are used for P&L only. The signal uses split-adjusted closes |
| Fallback only: WTI spot `DCOILWTICO` (EIA via ALFRED) | Per ALFRED `realtime_start`. EIA spot data are published with a lag (often weekly), which the vintage captures | First session after `realtime_start` (+1 lag) | Revisable, so vintages only |

### 6a. Source coverage by year (survivorship audit)
| Source | Span | Rows per year / coverage |
|---|---|---|
| Desk bar store (SIP), `total_return/daily_total_return.parquet` → `ret_total_best`, plus split-adjusted OHLC for ATR | 2016-01-04 → 2026-10-28 | Each year 2016–2025: 250–253 sessions; 2026: 207 (to 28 Oct). Counted 30 Oct ~01:55 SGT for USO, XLE, XLY, BIL. No gaps |
| Ken French FF5/UMD/ST_Rev daily (store `factors/`) | 1963 → 2026-09-30 | Full years. 2026 ends 30 Sep, so the alpha regression ends there |
| Stage B extended (sealed) | 2005+ per manifest; USO incepted Apr 2006 (public fact), so Stage B for H1 starts after a 63-session warm-up | **Coverage by year to be reported at unseal** (not opened) |

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
- **Stage B (OOS): **2006-10-02 → 2016-06-30**, about 9.7 years. USO started 10 Apr 2006, and the window allows for the 63-session warm-up and ATR.** This is the sealed `bars/daily/extended/` file. **Decision (b): it is opened ONCE for the whole batch** (trend v3, oil, curve). That happens only after every spec is frozen with a SHA-256-hashed PREREG logged in `trials.csv` (see `research/original/BATCH-MANIFEST.md`) and the data owner's signed-off snapshot hash is pinned. All the ideas run in one sitting. After the first result is seen there are no amendments, and no re-specification or re-run of a failed idea on the sealed data. The 2016+ overlap is excluded, so the two windows are disjoint.
- **Stage C (live paper):** shadow-traded from registration, with the PIT archive (the data owner) and no capital, as an extra forward check.
- **Trade-count gate:** done (§15). It projects 15.1 episodes < 30, so **do not unseal**.

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
     - **XLE beta to USO** (decision amendment 5) = daily USO excess return, so alpha is net of the strategy's direct oil exposure;
     - **spread TSMOM** = sign(12-1m XLE−XLY return, lagged) × daily XLE−XLY return;
     - **spread 5-day reversal** = −sign(5d XLE−XLY return) × daily spread return;
     - **oil TSMOM** = sign(USO 12-1m return) × daily USO return.

   This shows the edge is not plain sector momentum or oil trend.

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
- 2026-10-30 02:02 SGT (29 Oct 14:02 ET): v1.1 applies the validator's decision: N=79; batch single unseal; episode trade definition and ≥30 gate; alpha NW t ≥ 3.0; SUE waiver; LIMITS v0.3 halt semantics; USO 2020 break disclosed; XLE-on-USO beta control; raw Stage A SR > 0.68 precondition; CONDITIONAL PASS cap; partly-seen tickers (USO partly seen 2008–16). §15 gate run → DO NOT UNSEAL. No returns computed.
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
- **Related literature I am aware of (so the idea is "original" in construction, not in spirit):** Driesprong, Jacobsen & Maat (2008), oil predicts stock markets; Hong, Torous & Valkanov (2007), industries lead the market; Moskowitz & Grinblatt (1999), industry momentum. My construction (a threshold regime, an XLE/XLY cash-flow pair, flat otherwise) is not taken from any of them.

## 14. Blockers / dependencies before Stage A
- **B1, data ingest (the data owner):** none for the primary: everything is in the store. Fallback WTI would need an ALFRED pull.
- **B2, ALFRED:** an API key is needed for FRED/ALFRED vintages, and FRED CSV/API timed out from the box today (29 Oct ET). Without vintages, any FRED-sourced input fails Addendum A.
- **B3, Stage B access:** the data owner/validator must sign off opening `bars/daily/extended/` **once, for this frozen spec**. They must also confirm that the tickers in §3 are among the 37 spliced ones, and that the yfinance total-return splice is acceptable as a TR source (STANDARD requires TR). Each year's coverage must be reported once it is opened.
- **B4, earnings-surprise factor (WAIVED by the validator's decision; include it if it exists by run time):** it is not in the store. The derivatives researcher/data owner need to build a daily PIT SUE long-short factor (EDGAR acceptance time → next open; XBRL diluted EPS, seasonal random walk). Its coverage is limited to the XBRL era (~2009+), so for 2005–09 the alpha test runs without it and that is flagged.
- **B5:** the validator ruled ~02:05 SGT 30 Oct (the internal review record (the validator, ~02:05 SGT)). This v1.1 applies his amendments. N = 79.

## 15. Pre-unseal episode gate (decision (c)). Run 2026-10-30 02:01 SGT (29 Oct 14:01 ET) on signal inputs only.
- **Code and outputs:** `research/original/episode_gate/count_episodes.py`, giving `gate_results.json` and `oil_episodes.csv`.
  - Loaded: USO split-adjusted close and DGS2/DGS10 only, rows ≥ 2016-01-04.
  - **No XLE/XLY/XLF/XLU/SPY prices and no returns were loaded.**
- **Definition:**
  - Episode = a maximal run of consecutive weekly evaluations in the same non-neutral state. An opposite flip = one exit plus one new episode.
  - Stops cannot add episodes, since there is no re-entry within a state, so this is an upper bound on traded episodes.
- **Stage A (2016-07-01..2026-10-28, 10.32 yrs):** **16 episodes** (13 long-first-leg / 3 reverse). 1 was in progress at the window start and 1 is censored at the end.
  - Episodes by start year: 2016: 1 · 2017: 0 · 2018: 3 · 2019: 1 · 2020: 2 · 2021: 4 · 2022: 2 · 2023: 1 · 2024: 0 · 2025: 0 · 2026: 2
  - Active (non-neutral) weekly evaluations by year: 2016: 1 · 2017: 0 · 2018: 8 · 2019: 6 · 2020: 24 · 2021: 15 · 2022: 18 · 2023: 4 · 2024: 0 · 2025: 0 · 2026: 21 (of 540 weekly evaluations)
- **Rate:** 1.55/yr × Stage B 9.74 yrs = **projected 15.1 Stage B episodes → DO NOT UNSEAL (<30).**
- Thresholds are unchanged, per the decision. Changing them = a new PREREG and +1 trial.
- **Decision: DO NOT UNSEAL for oil.** Even counting the episode already in progress at the start and the one censored at the end, the rate is 1.55/yr. This pre-2016 projection uses the post-2016 rate only, with no adjustment for what I know about 2008 or 2014–16 (adjusting would use seen information). The oil idea is withdrawn from the batch unseal and the trend-v3 sitting. Its 7 logged trial slots still count in N, as conservative accounting; the validator may decide otherwise.

