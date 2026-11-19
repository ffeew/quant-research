# PRE-REGISTRATION v1.2 (NEW SPEC): Yield-curve slope changes: financials vs utilities, with a hysteresis band
`slug: curve-slope-financials-vs-utilities`

**Owner:** Maya (Macro Strategist) · **Source:** original (not a paper replication) · **Written:** Fri 30 Oct 2026, ~01:55 SGT (Thu 29 Oct ~13:55 ET), **before any run of any kind**
**Status (v1.2, new pre-registration, +1 trial, N = 80):** written 30 Oct 2026 ~02:06 SGT under Victor's follow-up rulings (same rulings file, ~02:06 SGT). **GATE FAILED (provisional): DO NOT UNSEAL.** §15 projects 17.0 Stage B episodes < 30, on current FRED values pending ALFRED. It remains **BLOCKED on ALFRED vintages** in any case. Under ruling (3) curve keeps its holdout slot only if a version is frozen, hashed, gated (≥ 30) and on ALFRED before trend v3 unseals. v1.2 does not meet that, so the slot is forfeited unless a further pre-registration (+1 trial) passes in time. **Predecessor:** `PREREG.md` v1.1 (DO NOT UNSEAL). Everything not changed below is inherited verbatim from v1.1. No backtest, no conditional-return look, nothing computed on the outcome series.
**Governing documents:** `validation/STANDARD.md` v1.0 + Addendum A (2026-10-30 02:05 SGT); `risk/LIMITS.md` §1; `tca/cost_model.md` v1.1.

## 1. Hypothesis
When the 2s10s Treasury curve has steepened materially over the past quarter, financials (XLF) keep outperforming utilities (XLU) over the following weeks. After a material flattening, the reverse holds. Otherwise there is no position.

## 2. Economic mechanism (why it should exist, who is on the other side)
- **Banks (XLF ≈ 25–35% banks).** Their asset yields reprice off the intermediate/long curve faster than their deposit costs reprice off the front end. A steeper curve therefore raises forward net interest margin. This shows up in reported NII and guidance with a 1–2 quarter lag, and sell-side NII revisions trail the curve.
- **Utilities.** They are regulated, levered, long-duration cash flows priced as bond proxies. Higher long yields (bear steepening) raise their discount rate and refinancing cost, and rate-case relief lags by years.
- **Who is on the other side, and why it persists.** Income and low-vol investors hold XLU through rate moves for the yield. Generalists treat curve moves as macro noise until earnings confirm them. The trade is a low-frequency cross-asset duration bet that most equity mandates do not run.
- **Known ambiguity, stated ex ante.** In a *bull* steepening (front-end cuts), the utility leg's duration exposure works against the hypothesis. **The bull vs bear steepening split is reported as a diagnostic only, and it cannot become the primary** (ruling amendment 6).

## 3. Universe
XLF (Financial Select SPDR), XLU (Utilities Select SPDR), BIL (cash). All are in the store and flagged shortable/ETB in the 2026-10-29 snapshot. Note: XLF's index composition changed when real estate was carved out (XLRE, 2015–16) and in the GICS 2023 reclassification (payments moved into financials). This is a structural break to disclose, and there is no adjustment.

Crypto is excluded (desk rule). There is no leverage and there are no options.

## 4a. Exact signal rules (single primary spec)
| Item | Rule |
|---|---|
| Slope | `S_d = DGS10_d − DGS2_d` (constant-maturity Treasury yields, percent). The **ALFRED vintage** is the one available at the evaluation time, and the observation date is ≤ t−1 (one-session lag, because the H.15 posting time is unverified). |
| Signal | `ΔS_t = S_{t−1} − S_{t−1−63}` (63-session change). |
| State (hysteresis, v1.2) | Weekly state machine on `ΔS`:
  - From **NEUTRAL**: `ΔS ≥ +0.25` → STEEPENING; `ΔS ≤ −0.25` → FLATTENING.
  - From **STEEPENING**: `ΔS ≤ −0.25` → **reverse** to FLATTENING; else `ΔS ≤ +0.10` → NEUTRAL (flat); else stay.
  - From **FLATTENING**: `ΔS ≥ +0.25` → **reverse** to STEEPENING; else `ΔS ≥ −0.10` → NEUTRAL; else stay.
  - The entry 25 bp is unchanged from v1.1. **The 10 bp exit band is new.** It was chosen *after* seeing the v1.1 signal-only flicker counts (14 of 33 one-week episodes), **never any returns** (see §13). |
| Evaluation | Weekly (last session of the week), with daily stop checks. |
| Positions | STEEPENING: long XLF `w`, short XLU `w`. FLATTENING: long XLU `w`, short XLF `w`. NEUTRAL: flat (BIL). |
| Changes | Trade only on a state change, with no re-sizing between changes. A reversal = close both legs and open the opposite pair at the same next open (one exit + one new episode). |

## 4. Execution, sizing, stops (common to the Maya original batch)
| Item | Rule |
|---|---|
| Signal time | At the official close of session t, using only inputs with first-public-availability (ET) ≤ the close of t (see §6). Inputs whose availability is unverified are lagged one extra session. |
| Fill | **Next session's open** (t+1), Tomas v1.1 `venue="open"`. Per Addendum A, nothing computed after 15:59 ET trades before the next open. |
| Sizing per leg | `w = min(9.5%, 0.95% / stop_pct)`, where `stop_pct = 2 × ATR(14)_t / close_t` (LIMITS H1 buffer and H2 risk ≤ 1% per trade at the 0.95% buffer). This is fixed at entry and not re-sized while held. |
| Stops (H6) | Every position gets a stop for its full quantity at entry ± 2×ATR(14) from the fill price. The stop is **never loosened** (no trailing either; fixed for v1 simplicity). Simulation: a long is stopped if the session low ≤ stop; the fill is min(open, stop) (gap-through at the open). Shorts mirror this. Cost is Tomas `venue="continuous"`. |
| After a stop | Pair hypotheses (oil, curve): the other leg is closed at the next open, and the book stays flat until the signal *changes state*. VIX hypothesis: flat until a new trigger after the current episode ends. |
| Gross / leverage | Max gross ≤ 19% (two legs ≤ 9.5%) for the pair hypotheses, and ≤ 9.5% for the single-leg VIX hypothesis, far inside the LIMITS H3 gross buffer of 58%. Longs are cash-funded; short proceeds are not reinvested. Idle cash sits in **BIL** (total return). No leverage (H4) and no options (H5). |
| H7 earnings blackout | ETFs only, so n/a. Constituent-earnings concentration is noted as a risk, not a rule. |
| H8/H9 | **LIMITS v0.3 semantics, applied at the sleeve level in simulation** (ruling amendment 4). A 5% DD from peak halves gross (cap 30%). An 8% DD from peak → HALTED. A halt *holds the book*: no new positions or adds, de-risk only, gross ≤ 30%, and stops stay live. Exits and stop-outs are always allowed. Lift (simulated): ≥ 5 sessions since the halt, the shadow book's 5-session net return ≥ 0, and the CIO review is assumed logged at the lift date. Resume at a 30% gross cap in RESUMED-DISARMED, with a 3% backstop (E_resume × 0.97, live) that re-halts immediately. Re-arm the 8% halt only once EOD DD < 5%. Full gross only once EOD DD < 3%. Chain cap: a second backstop trip in the same peak-to-peak episode holds the halt until EOD DD < 5%. In practice this sleeve's gross (≤ 19%) is already under 30%, so the binding effect is 'no new entries while halted'. |
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
| XLF, XLU, BIL daily OHLC + TR (desk store, SIP) | SIP close 16:00 ET t; store final ~16:20 ET | t+1 open | The TR series is used for P&L only |
| DGS2, DGS10 (Fed H.15 via **ALFRED** vintages) | ALFRED `realtime_start` (date only). The H.15 daily posting time is **unverified**, so the rule lags it one full session | Observation of t−1 → used at close t → trades at the t+1 open | Revisable (rare corrections), so **vintages only**. The current FRED values are not allowed |
| Cross-check only: Treasury daily par yield curve CSV | Treasury posts it 'end of day'; time unverified | Not used in the signal | Corrections possible; Dmitri to archive |

### 6a. Source coverage by year (survivorship audit)
| Source | Span | Rows per year / coverage |
|---|---|---|
| Desk bar store (SIP), `total_return/daily_total_return.parquet` → `ret_total_best`, plus split-adjusted OHLC for ATR | 2016-01-04 → 2026-10-28 | Each year 2016–2025: 250–253 sessions; 2026: 207 (to 28 Oct). Counted 30 Oct ~01:55 SGT for XLF, XLU, BIL. No gaps |
| ALFRED DGS2 / DGS10 | Series from 1976 / 1962 per FRED (current-vintage CSV: DGS10 starts 1962-01-02). **Vintage coverage by year is not yet pulled**; the ALFRED API needs a key (the request returned 'api_key is not set') | TBD at pull. **Waiver path (ruling amendment 3):** if vintages don't cover 2005–16, current or first-release DGS values may be used *only if* Dmitri shows that vintage minus current is < 1 bp on ≥ 99.9% of the days the vintages do cover. The one-session lag is kept, and the waiver is logged. The API key goes through Jeremy |
| Ken French factors | 1963 → 2026-09-30 | Full |
| Stage B extended (sealed) | 2005+ | Coverage by year reported at unseal |

Survivorship:
- The instruments are long-lived SPDR/major ETFs that exist today, which is a mild survivor bias. I know of no delisted or closed ETFs that would be substitutes.
- No accounts or feeds are used.

## 7. Cost model (Tomas v1.1, `tca/tca_scripts/cost_model.py`)
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
- **Stage B (OOS): **2005-07-01 → 2016-06-30**, about 11 years (after warm-up).** This is the sealed `bars/daily/extended/` file. **Ruling (b): it is opened ONCE for the whole batch** (trend v3, oil, curve). That happens only after every spec is frozen with a SHA-256-hashed PREREG logged in `trials.csv` (see `research/original/BATCH-MANIFEST.md`) and Dmitri's signed-off snapshot hash is pinned. All the ideas run in one sitting. After the first result is seen there are no amendments, and no re-specification or re-run of a failed idea on the sealed data. The 2016+ overlap is excluded, so the two windows are disjoint.
- **Stage C (live paper):** shadow-traded from registration, with the PIT archive (Dmitri) and no capital, as an extra forward check.
- **Trade-count gate:** v1.2 FAILS provisionally (§15: 17.0 projected < 30). **DO NOT UNSEAL.**

## 10. Pass criteria (STANDARD.md §1 hard bars + Addendum A). All must hold on **Stage B (OOS)**, net of base costs.
1. Net OOS Sharpe > 0.5 (annualised from daily returns, in excess of BIL), and > 0 at 2× costs.
   - **Stage A precondition (ruling amendment 7):** 0.74 × raw Stage A net Sharpe > 0.5, i.e. **raw Stage A Sharpe > 0.68**. If Stage A fails that threshold, the idea **ends without unsealing**.
   - Stage B is judged unhaircut.
2. DSR ≥ 0.95 using the **cumulative** trial count N from §11 (**N = 80** for v1.2, rising with any extra trend-v3 trials; §11), with the skew and kurtosis of the OOS returns.
3. Newey-West t ≥ 3.0 on mean daily net return. Lags = floor(4(T/100)^(2/9)), with 21 lags also reported.
4. **Incremental-alpha test (Addendum A, required).** Regress daily net excess returns on:
   - Ken French FF5 (Mkt-RF, SMB, HML, RMW, CMA);
   - **UMD (Mom)** and **ST_Rev** (daily, store copy `factors/`; it ends 2026-09-30, so after that the regression window ends there);
   - an **earnings-surprise factor: WAIVED** for these ETF-level macro rules, which are not keyed to earnings events (ruling amendment 2; waiver logged here). If a PIT SUE factor exists by run time, it is included;
   - own-asset and duration controls:
     - **spread TSMOM** = sign(12-1m XLF−XLU return) × daily spread return;
     - **spread 5-day reversal**;
     - **duration factor** = daily IEF − BIL total-return difference.

   The XLU short is partly a bond short, so alpha must survive duration.

   **Pass (ruling amendment 1):** intercept > 0 with **NW t ≥ 3.0 on alpha**, as well as t ≥ 3.0 on the raw series (item 3), *and* alpha ≥ 50% of the raw mean excess return. A signal whose alpha vanishes once own-asset momentum/reversal is controlled for **fails** ("only restates recent returns").
4b. **Best attainable verdict = CONDITIONAL PASS.** Stage B is quasi-OOS only, because my §13 disclosure includes 2008 and the 2014–16 oil collapse (ruling, Status).
5. PBO: with a single primary it is not computable or uninformative (< 10 variants). Reported as "n/a — single pre-registered spec". The ±20% neighbourhood (item 8) substitutes.
6. OOS ≥ 3 years (Stage B satisfies this; see §9). Embargo ≥ 5 sessions between any Stage A look and the Stage B start (the windows are disjoint in time, so the embargo is trivially met).
7. **Trades (ruling (c)):**
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
| Maya ETF macro-timing family to date, at the trend decision count (desk figure 46 so far, 47 with trend v3, decided at **N = 57** per v3 A1; ruling (a)). *Corrected: the earlier 'Victor counts 30' line was wrong.* | **57** |
| This batch, 3 hypotheses × (1 primary + 6 logged neighbours: lookback ±20%, threshold ±20%, joint (+,+) and (−,−)) | 21 |
| H3 placebo (drawdown-matched entry) | 1 |
| **Cumulative N for DSR (same family as trend; ruling (a))** | 79 = 57 + 21 + 1 |
| Curve v1.2 (new spec; Victor follow-up (1)) | +1 |
| v1.2 neighbourhood | Reuses curve's 6 logged neighbour slots from the 21. The ±20% threshold neighbours scale the entry (25 bp) and exit (10 bp) bands jointly. If Victor counts these as new runs, N rises accordingly |
| **N for DSR from v1.2 onward** | **80**. It never goes down (follow-up (2)) |
| Escalation | N rises one-for-one if trend v3 logs trials beyond 57. Any spec change after sign-off is +1. The USO→WTI fallback is +1 |

- All runs are logged to `outputs/trials.csv` (spec hash, time SGT/ET, metric) before results are viewed.
- Neighbours are robustness runs only. The primary is never replaced by a neighbour. Picking one would require a new pre-registration with N+1.

## 12. Change log
- 2026-10-30 ~02:06 SGT (29 Oct ~14:06 ET): **v1.2 written as a new pre-registration.** The only change from v1.1 is the hysteresis exit band (enter ±25 bp, exit to flat at ±10 bp, reverse past the opposite ±25 bp), plus the 4-week episode-merge rule in the gate. N = 80. The §15 gate was re-run on signal inputs only (provisional FRED) → DO NOT UNSEAL.
- 2026-10-30 02:02 SGT (29 Oct 14:02 ET): v1.1 applies Victor's ruling: N=79; batch single unseal; episode definition and ≥30 gate; alpha NW t ≥ 3.0; SUE waiver; LIMITS v0.3; ALFRED waiver path; bull/bear diagnostic only; raw Stage A SR > 0.68 precondition; CONDITIONAL PASS cap; partly-seen tickers (XLF/XLU not in Victor's 2008–16 read). §15 provisional gate run on current FRED values. No returns computed.
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
- **Partly-seen tickers (ruling (b)).** Victor's earlier 2008–16 trend read used the Yahoo chart-API extension for the 23-ETF trend universe plus ^VIX:
  - The universe was SPY QQQ IWM EFA EWJ EWG EWU EEM SHY IEF TLT GLD SLV USO UNG DBA DBC UUP FXE FXY FXB FXA FXC.
  - Sources: `validation/backtests/trend_sleeve/data_audit.py` and `fetch_yahoo.py`; `results.md` §8.
  - Of this batch's tickers, **SPY and USO (and ^VIX) were in it, so they are PARTLY SEEN for 2008–16.** Only 2005–07 is fully blind for them, and USO only exists from Apr 2006.
  - **XLE, XLY, XLF and XLU were NOT in it**, so they are unseen in the 2008–16 extension.
  - Seen means seen as one input to an aggregate trend result. I never saw conditional returns of these tickers.
- **Sealed extended file (`bars/daily/extended/`): NOT opened.** I know only manifest metadata relayed earlier: 2005+, Yahoo/yfinance source, 38 tickers, EWA not spliced. Victor's partial 2008–16 trend rerun on that file was reported to me only as an aggregate trend result, so 2008–16 is "partly seen" for SPY-heavy trend exposure. This matters most for H3 (SPY).
- **Related literature I am aware of (so the idea is "original" in construction, not in spirit):** The bank-NIM/curve link is textbook, and the 'utilities as bond proxies' link is market folklore. I know of no specific paper that I am replicating. I'm aware of the general literature on term-spread predictability of stock returns (Fama & French 1989; Campbell 1987).

- **v1.2-specific disclosure (forking path):**
  - The 10 bp exit band was selected after I saw the v1.1 Stage A **signal-state** counts: 33 raw episodes, 14 of them one-week flickers, and 21 after Victor's 4-week merge.
  - Victor's ruling also suggested '±25 in, ±10 out' as an example, and I adopted it as given. I did not scan any other band widths.
  - **No returns of XLF, XLU or the pair were computed or viewed at any point**, for v1.1 or v1.2.
  - This is +1 trial (N = 80).

## 14. Blockers / dependencies before Stage A
- **B1, data ingest (Dmitri):** ingest ALFRED vintages of DGS2/DGS10 with `realtime_start` into the store (needs the FRED API key; see B2).
- **B2, ALFRED:** an API key is needed for FRED/ALFRED vintages, and FRED CSV/API timed out from the box today (29 Oct ET). Without vintages, any FRED-sourced input fails Addendum A.
- **B3, Stage B access:** Dmitri/Victor must sign off opening `bars/daily/extended/` **once, for this frozen spec**. They must also confirm that the tickers in §3 are among the 37 spliced ones, and that the yfinance total-return splice is acceptable as a TR source (STANDARD requires TR). Each year's coverage must be reported once it is opened.
- **B4, earnings-surprise factor (WAIVED by Victor's ruling; include it if it exists by run time):** it is not in the store. Dave/Dmitri need to build a daily PIT SUE long-short factor (EDGAR acceptance time → next open; XBRL diluted EPS, seasonal random walk). Its coverage is limited to the XBRL era (~2009+), so for 2005–09 the alpha test runs without it and that is flagged.
- **B5:** Victor ruled ~02:05 SGT 30 Oct (`validation/prereg_rulings/2026-10-30-maya-macro-batch.md` (Victor, ~02:05 SGT)). v1.1 applied his first amendments. v1.2 applies follow-up (1) (hysteresis = new spec, +1). N = 80.

## 15. Pre-unseal episode gate, v1.2. Run 2026-10-30 ~02:06 SGT on signal inputs only. **PROVISIONAL (current FRED, not ALFRED).**
- **Code and outputs:** `research/original/episode_gate/count_episodes_v12.py`, giving `gate_results_curve_v12.json` and `curve_v1.2_episodes_merged.csv`.
  - Inputs: DGS2/DGS10 from current FRED (`episode_gate/inputs/`, same files and hashes as v1.1's gate), plus store NYSE session dates only.
  - No ETF prices or returns were loaded.
- **Episode rule (Victor follow-up (1)):** an exit to neutral followed by a same-direction re-entry within 4 weeks (≤ 28 days between the last active and the re-entry weekly evaluation) is **one** episode. Opposite-direction flips are never merged.
- **v1.2 Stage A (2016-07-01 → 2026-10-28, 10.32 yrs):** 18 raw → **16 merged episodes** (8 steepening / 8 flattening). Median duration 13 weeks; 0 one-week episodes; 237 of 540 weekly evaluations active.
  - By start year: 2016: 2 · 2017: 2 · 2018: 1 · 2019: 0 · 2020: 2 · 2021: 2 · 2022: 1 · 2023: 3 · 2024: 1 · 2025: 2 · 2026: 0
- **Rate:** 1.55/yr × Stage B 11.0 yrs = **projected 17.0 → DO NOT UNSEAL (<30).**
- **Why the count fell:** hysteresis holds positions longer, which removes flicker but also removes re-entries. The independent-decision count falls further below 30.
- **Decision: DO NOT UNSEAL (v1.2).** Thresholds are not changed in response. Any further band change is a new pre-registration at +1 trial, and would still need ALFRED.
- An ALFRED re-gate is pending: no `FRED_API_KEY` was present in the environment at 30 Oct ~02:06 SGT, so vintages could not be pulled.
