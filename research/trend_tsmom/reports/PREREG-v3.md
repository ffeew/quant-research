# PRE-REGISTRATION v3: limits-compliant ETF trend sleeve (single primary spec, one run)

**Owner:** Maya (Macro Strategist) · **Drafted:** Fri 30 Oct 2026, ~01:45 SGT · **Status: SIGNED OFF by the validator with amendments A1–A6 (§9.A), 01:47 SGT; §9.B CONFIRMED with conditions C1–C12 (§9.C), decision the internal review record. Nothing has been run. Run blocked until the data owner's build hash AND corporate-action table hash are pinned in §2 and logged in §12 (A4, run gate). 02:15 SGT: the validator approved data option (b); 02:26 SGT: he approved amendments (a)–(c) (non-trial, N = 57). **CANDIDATE FREEZE (02:30 SGT), pending the validator's confirmation before data owner builds v2.**
- v3 code (`run_v3.py`, `tsmom/engine_v3.py`, `data_v3.py`, `v3spec.py`, `stats_v3.py`) is written and unit-tested on synthetic bars and the 2016+ desk store only.
- `bars/daily/extended/` has not been opened by me at any point.
- The validator's decision: v2 V1 must not be rerun on the backfill, and he will accept exactly **one** new pre-registration. This file is that one.

**Freeze rule:**
- This file is frozen when the CIO and validator sign it.
- Any later change must be logged in §12 with a timestamp and a reason, before the run. A change after the run is a new trial, and is not allowed this sprint (§10).

**Inputs read:**

| Document | sha256 at drafting |
|---|---|
| `risk/LIMITS.md` | `af513e3a…1cf6` |
| `validation/STANDARD.md` | `b6a09d47…cac1` |
| `validation/backtests/trend_sleeve/results.md` (the validator) | — |
| MOP 2012 and HOP 2017 paper cards | — |

## 1. Rationale
The rationale comes only from LIMITS, cost economics and the published defaults. It does not come from 2017+ results.

- **Published defaults (MOP 2012, *JFE* 104(2); HOP 2017, *JPM*):**
  - Signal: sign of the trailing 12-month excess return (MOP's headline k = 12).
  - Risk: positions scaled by ex-ante EWMA volatility, centre of mass 60 days (MOP), with a 40% annual vol target per instrument (MOP) and a 10% portfolio vol target (HOP).
  - Rebalance: monthly (MOP).
  - v3 uses these without modification. The 1/3/12 blend (HOP) is **not** used: its 1- and 3-month legs raise turnover, which the cost model penalises at ETF spreads (TCA owner v1.1, §5 turnover algebra).
- **LIMITS (`risk/LIMITS.md` §1, in force):**
  - H1: |position| ≤ 10% of equity.
  - H2: risk from entry to stop ≤ 1% of equity.
  - H3: gross ≤ 60%.
  - H4: no leverage; longs cash-funded.
  - H6: a full-quantity protective stop on every position, never loosened.
  - H8 and H9: drawdown breakers.
  - v3 builds the book inside these limits, using the portfolio-construction lead's implementation buffers (9.5%, 0.95%, 58%), instead of scaling to a vol target and then clipping.
- **Cost economics** (TCA owner v1.1 structure, independent of any backtest):
  - One-way cost is fees + bucket half-spread + √-impact + paper buffer.
  - Bucket defaults are 2.75/2 bps, 5/4, 12/8 and 30/15.
  - Annual drag ≈ turnover × one-way cost.
  - Choices that follow:
    - **(a)** Restrict the universe to L1/L2 ETFs (≤ about 10 bps one-way at desk size). An L4 ETF needs about 4–5× the edge per unit of turnover.
    - **(b)** Rebalance monthly with a no-trade band, so small drift trades that cost more than their risk benefit are skipped.
    - **(c)** Cash-fund all longs and hold any unallocated cash at RF, so there is no financing cost.
    - **(d)** Assume borrow at STANDARD's 1%/yr floor. The TCA owner's 25 bps is lower, and STANDARD §5 says the higher figure applies.

## 2. Pinned inputs
| Item | Pin |
|---|---|
| **Universe (explicit, 11 ETFs)** | SPY, QQQ, IWM, EFA, EEM, EWJ (equity) · IEF, TLT (Treasuries) · GLD, SLV, USO (commodities). No substitutions, additions or removals. |
| **Shortability (pinned list, not a file)** | Long/short: SPY QQQ IWM EFA EEM EWJ IEF TLT GLD SLV (shortable and ETB per the Alpaca snapshot `assets_2026-10-29.parquet`, sha256 `3996cd92…09` at 01:40 SGT). **USO is long/flat** (not shortable). The list is applied to the whole history (look-ahead; §9). |
| **Data build (backfill)** | **`c998ca5c33eee487bbdcdbee929ecc2e003078653c2ec5cf15b905c3f9e0ab78`** (data owner sign-off; pinned 2026-11-06 06:14:23 SGT; path `$QR_DATA_DIR/bars/daily/extended/signoff/trend_v3_v2_etf_daily_20261030.parquet`). This row pins the data owner's **v2** build hash, and the "Substitution diff (v2)" row pins its diff hash. Both are to be filled in. The run is blocked until data owner signs off and both fields are filled (logged in §12). File (a), `trend_v3_etf_daily_20261030.parquet` (sha256 `c3cd8429…791df2`), is **never** pinned or run. |
| **Substitution diff (v2)** | **`8225dded490c5567ec446d81b9e10d9161ee1225a3f7bc27e94dccc46bd671ee`** (data owner v2 diff; pinned 2026-11-06 06:14:23 SGT; path `$QR_DATA_DIR/bars/daily/extended/signoff/trend_v3_v2_substitution_diff_20261030.csv`). This is the old/new value diff for every substituted row (rule S6 below). Filled in together with the v2 build hash. |
| **Reference-source table** | **`1388e51cdf124667d2e4fb3d60f4a6fb853f63ccb4e816cd3cecfd3dc91c7380`** (the data owner; `$QR_DATA_DIR/bars/daily/extended/signoff/reference_sources_trend_v3_20261030.csv`; sha256 verified 02:25 SGT; pinned before the v2 build; TBD-2 closed). The table says the only free official close is Nasdaq.com historical 'Close/Last', which runs 2016-10-28 → 2026-10-28 and covers the close only. Nasdaq's O/H/L match Alpaca SIP consolidated values and are not official. No free official close exists for any of the 11 before 2016-10-28, and no issuer file gives a daily market close. Under rule S2 this table is **informational**: the reference is Yahoo raw for all fields, and Nasdaq is a report-only cross-check (X1–X3). |
| **Corporate-action table** | **`b415ae397380b6adf287110bdb759afa5ece1f1cde7dd0832d5924993c72fb5e`** (data owner sign-off; pinned 2026-11-06 06:14:23 SGT; path `$QR_DATA_DIR/bars/daily/extended/signoff/corporate_actions_splits_snapshot_trend_v3_v2_20261030.parquet`). This is the split source from **2016-01-05** on (§9.C C7 as amended). Before 2016-01-05 the split source is the Yahoo split events in the next row. The run is blocked until this field is filled (logged in §12). |
| **Pre-2016 split events (Yahoo)** | The table starts in 2016, so these five Yahoo split events are the complete split source before 2016-01-05. Ratios are new shares per old share, from the data owner's `$QR_SCRATCH_DIR/trend_v3_build/work_splitlog.parquet` (sha256 `d749ec2e5bc90ef5ac34e8d3f2d534e5e18ebffb08149189063fd936c9639700`, column `yahoo_ratio`). They are frozen in code as `v3spec.PRE2016_SPLITS`. **IWM 2005-06-09 2:1; EFA 2005-06-09 3:1; EEM 2005-06-09 3:1; EEM 2008-07-24 3:1; SLV 2008-07-24 10:1.** The C7 > 30% raw-vs-TR cross-check, with abort on any mismatch, runs over the **full history** against the merged source (this list before 2016-01-05, the corporate-action table from then on). A split that is in neither source, a wrong ratio, or the two sources overlapping all abort the run. |
| **Data substitution rule (frozen before v2 build; non-trial per the validator)** | the validator approved this as option (b) on 2026-10-30 ~02:15 SGT and confirmed amendments (a)–(c) at ~02:26 SGT. It is a **non-trial** data change, so N stays 57 (§11). The rule is frozen here before data owner builds data v2 and is applied mechanically. **S1 Scope:** all 11 tickers, every session from 2005 on, fields open, high, low and close. There are **no named-date exceptions**: March 2020 is caught by the rule or not at all. **S2 Reference:** the **Yahoo raw unadjusted** value for **all four** fields (open, high, low, close), on every date and ticker, so the reference row is internally consistent. The validator waived his earlier 'prefer the official close' condition. Nasdaq's official close is **not** a reference: it is a report-only cross-check (X1–X3) with no substitution effect, which removes any tie-break between Yahoo and Nasdaq (e.g. 2026-04-20). **S3 Trigger:** a row triggers if \|build close / Yahoo raw close − 1\| > 25bp, OR \|build open, high or low / its Yahoo raw value − 1\| > 50bp for any of the three. Comparisons are strict. **Pre-2016 rows never trigger:** the build's base data before 2016-01-04 *is* Yahoo, so the build value equals the reference. The source switches to Alpaca SIP on 2016-01-04, per the data owner's sign-off. This is intended: the rule targets Alpaca SIP prints. A substituted row dated before 2016-01-04 in the diff therefore aborts the run (code audit). **S4 Action:** replace **all four** OHLC fields of a triggered row with the Yahoo raw values. Volume is unchanged. Total return is recomputed from the substituted closes, plus dividends and the split sources above (corporate-action table from 2016-01-05, Yahoo events before). **S5 Aborts:** if a triggered row has no Yahoo raw value for any of its four fields, ABORT; the bad print is never kept. If a row breaks low ≤ min(open, close) and max(open, close) ≤ high after substitution, ABORT; do not clip or repair. The run re-audits the published diff for both conditions. **S6 Publication:** every substituted row is flagged by row and published by the data owner as a diff with old and new values (columns symbol, date, old_/new_ open, high, low, close). The diff hash is pinned above. **S7 Gates:** v2 must pass all 11 overlap-correlation checks (> 0.999), or there is no run. File (a) is never run, not even as a diagnostic. **S8 Disclosure:** the 25bp and 50bp thresholds are the data owner's existing v1 QA price-agreement tolerances. They were set after he had seen the flag counts on file (a): 72 rows off against Yahoo (29 closes > 25bp, 43 opens/highs/lows > 50bp), and overlap correlation ≤ 0.999 for SPY, EFA and GLD. He had seen no returns. They also **match** the thresholds of the data owner's unpublished dry run (§9 item 10, §12). |
| **Nasdaq official-close cross-check (report only; no substitution effect)** | The input is the data owner's per-row cross-check file (columns symbol, date, nasdaq_close_raw, yahoo_close_raw; its path and sha256 go in `data_spec_v3.json` and `meta.json`). It is derived from his Nasdaq.com snapshot `$QR_SCRATCH_DIR/trend_v3_build/refsrc/nasdaq_hist_snapshot_20261030.parquet` (sha256 `6937e858c287a2b1aa0f67233d4e0e34bb21cf97b1b75006728ad6f51acfb5fb`), with the Nasdaq close de-adjusted to raw using the split factors. It covers 2016-10-28 → 2026-10-28. **X1:** report, per ticker, the share of days on which Nasdaq's official close agrees with the Yahoo raw close within 1bp. **X2:** list every **substituted** row where \|Nasdaq / Yahoo − 1\| > 10bp. Every such row must appear in the data owner's published diff; the run aborts if one does not. **X3:** list every row, substituted or not, where the gap is > 25bp, flagged by whether it was substituted. X2 replaces the earlier 25bp threshold for substituted rows. The outputs are `outputs_v3/nasdaq_yahoo_agreement.csv`, `nasdaq_yahoo_substituted_gt10bp.csv` and `nasdaq_yahoo_all_gt25bp.csv`. The data owner's v1 figures (reference-source table, 2513 common days per ticker; share within 1bp; on v1 Alpaca rows > 25bp off Yahoo, the count where Nasdaq sides with Yahoo within 1bp): SPY 99.92% (8/8), QQQ 100.00% (0/0), IWM 99.96% (5/5), EFA 100.00% (1/1), EEM 99.96% (1/1), EWJ 99.96% (1/1), IEF 99.96% (0/0), TLT 99.96% (0/0), GLD 99.92% (2/2), SLV 99.92% (1/1), USO 99.96% (10/10). Days > 1bp: SPY 2019-07-16 −2.3bp and 2026-04-20 +20.0bp; IWM 2017-03-20 −7.9bp; EEM 2017-03-20 +8.8bp; EWJ 2017-03-20 +1.3bp; IEF 2020-07-09 +1.6bp; TLT 2019-05-28 +7.0bp; GLD 2017-03-20 +4.6bp and 2026-04-20 +86.9bp; SLV 2017-03-20 +4.2bp and 2026-04-20 +205.1bp; USO 2017-03-20 +5.4bp. |
| **Jump and split checks (the data owner's C7, `SIGNOFF_trend_v3_20261030.md`; code `$QR_SCRATCH_DIR/trend_v3_build/validate_trend.py`)** | These checks apply to v2 as a sign-off condition: any failure means no sign-off and no run. **J1 Splits** (validate_trend.py lines 56–64): every split in the split sources above (corporate-action table from 2016-01-05, Yahoo events before) must show a raw close ratio on its ex-date within 15% (relative) of the expected ratio, and a split-adjusted price return under 15% in absolute value that day. From 2016-01-04 the split must also be detected in both sources (Alpaca ratio = Yahoo ratio). **J2 Non-split jumps** (lines 67–69): a day is flagged if \|raw close_t / raw close_{t−1} − 1\| > 0.25 AND the split_ratio from the split sources == 1. A flagged day is corroborated, and so kept, if \|ret_total − r_yahoo\| < 0.01 (1 percentage point, i.e. 100bp **absolute**). Here ret_total is our total return for that day and r_yahoo is Yahoo's adjusted-close return for the same day. The trigger uses raw close-to-close; the corroboration uses total returns. A flagged day that is not corroborated is unexplained and fails C7. **J3:** the rule is general, and no dates are listed in it. Disclosure: it is written into this PREREG after the data owner saw the data; see §9 item 10. |
| Required fields | Per ETF and session: total-return index, raw open/high/low/close, volume; splits from the data owner's corporate-action table from 2016-01-05 and the frozen Yahoo split events before that (§2). SPY total-return index and RF over the full history. ~~If OHLC is absent for any ETF and date, the pre-registered fallbacks in §4.4 and §4.5 apply.~~ **Superseded by §9.C C8:** missing OHLC where needed aborts the run (no fallback pre-granted); missing opens may fall back to the close on ≤ 0.5% of open-priced fills, above that the run aborts. Nothing is chosen after seeing data. |
| Risk-free | Ken French daily RF (`factors/ken_french/ff3_daily.parquet`, sha256 at drafting `97daa708…041`; the hash is re-pinned with the data build). Forward-filled past its last date and flagged. |
| **Cost model** | **TCA owner v1.1**, `tca/tca_scripts/cost_model.py`, **sha256 `df67d604489583d36bb1a16dc7ed30c5568b9a17526f450e4c1a335f9fe8eebf`**. |
| Cost settings | `trade_cost()` with venue `continuous` for **all** fills (rebalances, stops, drift trims and the H8 close trim, §9.C C2), k = 1.0, bucket-default spread and buffer. ADV and σ are the lagged 20-day values *as of each historical date*. |
| Borrow | **1.00%/yr** on short market value, calendar days / 360. |
| NAV for costs | **$100,000** (desk equity, LIMITS §1 worked levels). |
| Code | New `run_v3.py` plus engine options, hashed into meta.json. Unit checks (§8) must pass before the run. |

## 3. Signal and target weights (monthly)
At the close of the last session of each month, *t*:
1. **Signal:** s_i = sign(cumulative excess total return over the trailing 252 sessions). It is 0 until the asset is live under the late-inception rule **A3** (≥ 252 return observations for the signal and ≥ 60 for the EWMA); there is no backfill before inception. USO: s = max(s, 0).
2. **Ex-ante vol:** σ_i = √(252 × EWMA variance of daily excess returns, centre of mass 60, minimum 60 observations).
3. **MOP sizing:** raw_i = s_i × 0.40 / σ_i / N_live, where N_live is the number of assets with a valid signal.
4. **HOP book overlay (the only vol overlay; LIMITS §5):** m = min(1, 0.10 / σ_book).
   - σ_book uses a 252-session sample covariance of live assets.
   - The rule is never above 1, because H4 forbids leverage.
   - w_i = m × raw_i.
5. **Limits:**
   1. H1: |w_i| ≤ 0.095.
   2. H2: |w_i| ≤ 0.0095 / d_i, where d_i is the stop distance in §4.1.
   3. H3: if Σ|w_i| > G_cap, scale all weights pro-rata to G_cap.
      - G_cap = **0.58** normally.
      - G_cap = **0.29** while the H8 breaker is active (§5).
   4. H4: longs ≤ NAV − Σ(short proceeds excluded). This is implied by G_cap ≤ 0.58 and checked anyway.
6. **No-trade band** (fill day):
   - If sign(target) ≠ sign(current): trade to the target.
   - Else if |target − current| > max(0.25·|target|, 0.005): trade to the target.
   - Otherwise hold, and adjust the stop quantity only.
   - After banding, re-apply step 5.3.
7. **Fill:** at the **next session's open** (STANDARD §2: next-bar open or worse), via a market order costed at venue `continuous`.
   - P&L from close *t* to open *t+1* accrues on the old weights; from open *t+1* onward, on the new weights.
   - Fallback if a session has no open price: next session's close.
8. **Cash:** the residual earns RF (equivalent to flat BIL). It is never traded and has no cost.

## 4. Stops (LIMITS H6: every position, full quantity, never loosened)
4.1 **Level.**
- d_i = 2 × ATR(14)_i / close_i at signal date *t*. ATR is the **simple mean of the last 14 true ranges** (the desk convention in `portfolio/construct.py`; not Wilder's smoothing, see §9.B(10)) on raw (split-adjusted, not dividend-adjusted) OHLC, i.e. the desk implementation buffer for H6 (`portfolio/construct.py`).
- On every entry fill at price F:
  - long stop = F × (1 − d_i);
  - short stop = F × (1 + d_i).

4.2 **Never loosened, monthly tighten-only.**
- At each month-end rebalance where the position is kept (same sign), the candidate is F' × (1 ∓ d_i'), using that rebalance's open fill price F' (or its reference open if banded) and the new d_i'.
- New stop = max(old, candidate) for longs and min(old, candidate) for shorts.
- On a resize, the level is unchanged and the stop quantity becomes the full new quantity.
- Split: level × split ratio. The ratio comes from the data owner's corporate-action table from 2016-01-05, and from the five frozen Yahoo events before that (§2; §9.C C7 as amended). Dividends: no adjustment, as with a real resting stop.

4.3 **Quantity:** the stop always covers 100% of the held quantity (H6). Partial stops are not allowed.

4.4 **Trigger and fill** (regular hours only, matching desk stops with `extended_hours = false`). **Amended by A5:** a bar that touches the stop fills at the worse of the stop and the open, and the stop is assumed hit first if anything else (target or same-bar order) is also hit; see §9.A.
- **Long:**
  - If open ≤ stop: exit the full quantity at the **open** (gap fill).
  - Else if low ≤ stop: exit at the **stop price**.
- **Short:** symmetric, using high and open.
- Same-day ordering: a rebalance fill at the open is processed first; the stop is then live for the rest of that session.
- ~~**Fallback (no high/low for that ETF and date):** trigger if close ≤ stop (long) or close ≥ stop (short), and exit at the next session's open.~~ **Superseded by §9.C C8:** no fallback is pre-granted; a held position without high/low data aborts the run.

4.5 **Stop costing:**
- Every stop exit pays TCA owner v1.1 `trade_cost` at venue `continuous` on the full notional (market-on-trigger). Gap slippage is captured by the fill price.
- If ADV or σ are missing, the bucket defaults apply.

4.6 **Re-entry:**
- After a stop-out the asset stays **flat until the next scheduled month-end rebalance**. There is no intra-month re-entry.
- At that rebalance the normal §3 rules apply. Re-entry can be in either direction, and is a new entry with a new stop (§4.1).

4.7 **H2 check:** at every entry or resize, |w_i| × d_i ≤ 0.95% of equity. Gap risk beyond the stop is reported (LIMITS §4 stress, 2 × stop distance) but is not a sizing input.

## 5. Drawdown breakers (H8, H9; LIMITS §1 in force, §2 re-entry mechanics as proposed)
- **Frozen (§9.C C1):** the breaker is simulated exactly as written in this section, §9.A A5 and §9.B(1). The later LIMITS v0.3.x changes are **not** adopted: H9 re-arm at EOD DD < 5%, the 3% / episode backstop, the chain lock, CIO-review validity and H8 inert while halved (T4 is still under validation). **Disclosure: the live desk breaker may differ from the one simulated here.**
- **Modelling basis:**
  - The sleeve is modelled as a standalone account, with HWM = highest end-of-day equity.
  - ~~Checks use end-of-day equity.~~ **Superseded by A5/A6 (§9.A):** trips are checked on a conservative intraday NAV bound, exactly as LIMITS §1 (live equity), and drawdown is measured in NAV dollars.
- **H8 (DD ≥ 5%):**
  - G_cap drops to 0.29.
  - ~~Trimmed pro-rata at the next open.~~ **Superseded by A5:** reduced to ≤ 29% by the trip day's US close, largest risk-to-stop first (LIMITS §2a).
  - G_cap returns to 0.58 only when EOD DD < 3%.
- **H9 (DD ≥ 8%):**
  - No new positions and no adds; exits, trims and stop maintenance are allowed.
  - The halt lifts after ≥ 5 trading days, once the **shadow book's** 5-day net return is ≥ 0. The shadow book is the same rules without halts.
  - CIO review is assumed to occur on day 5. This is a backtest proxy, disclosed.
  - Trading resumes at G_cap 0.29.
- **Not modelled:**
  - LIMITS §3 panic flag (proposed, not in force). Its 2,520-day percentile window is not evaluable on a 2005+ history until about 2015.
  - LIMITS §5 portfolio-construction lead 6% book cap: the sleeve uses the single HOP overlay.
  - Both are reported as gaps.

## 6. Evaluation
- **One run** on the full signed-off backfill.
- **Evaluation start:** the first month-end where ≥ 5 universe ETFs have a valid signal.
- **Assets without enough history are absent until eligible:**
  - SLV and USO have inception dates in 2006 (to be confirmed from the build manifest, not from returns).
  - GLD is late 2004.
- **Segments**, reported separately and together:

| Segment | Prior exposure | Use |
|---|---|---|
| **2005–2007** | **Fully blind** (only unseen segment) | **Gate (A2):** net return > 0. Trade count reported. Too short to judge on its own. |
| **2008–2016** | **Partly seen**: the validator's indicative Yahoo rerun of the *v1* configuration (levered, no stops): net SR 0.20 | Together with 2005–2007, forms the **quasi-OOS segment for STANDARD §3–§4 (2005–2016)** |
| **2017–2026-10** | **Seen** (v1, v2, validator diagnostics) | Reported. Used for PBO (common window with logged trials) and as a check. |

## 7. Pass criteria (STANDARD.md, applied as written; all net of costs, daily returns)
Hard bars (any miss = FAIL):
1. **Quasi-OOS (2005–2016) net Sharpe > 0.5 *after* STANDARD §2's 20% survivorship haircut**, i.e. unhaircut net SR > 0.625.
   - Reason for the haircut: the universe is today's surviving ETFs and was hand-picked.
2. **Net Sharpe > 0 at 2× costs** (OOS and full sample), and **break-even cost ≥ 2× assumed cost** (§8).
3. **DSR ≥ 0.95 at N = 57** (decision, A1; N = 47 reported alongside) (§11), on quasi-OOS net daily returns, reporting SR0, N, T, skew and kurtosis.
   - V[SR] gate: the variance of annualised *gross* Sharpes of the 24 trials with a logged T × N matrix (v2 convention).
   - The all-net-dispersion DSR is also reported. The validator may apply it instead; it is the stricter of the two.
4. **t ≥ 2.8** (replication of a published anomaly; STANDARD §4), Newey-West with 21 lags, on full-history net returns.
5. **PBO (CSCV, S = 16) < 0.20.** Computed on the T × 40 net-return matrix (40 of 57 trials with a daily series, §9.C C9) over the common 2017-02 → 2026-10 window where all logged trials exist; earlier trials are not rerun on the backfill.
   - ≤ 0.05 is needed for a full PASS; 0.05–0.20 caps the verdict at CONDITIONAL.
   - Where a logged diagnostic has no daily series, the count is noted and the PBO is computed on the available columns.
6. **Trade count ≥ 100** OOS trades (entries, exits and stop-outs; a sign flip counts as one trade, §9.B(11)/§9.C C11).
7. **Regimes (STANDARD §7):**
   - No calendar year > 40% of total net P&L (full sample).
   - No regime with Sharpe < −0.5, across calendar years, SPY above/below its 200dma, and VIX above/below its median and > 25.
   - VIX needs a desk-validated VIX series from the data owner; without one, this item is "insufficient evidence" = FAIL per STANDARD §1.
8. **Stability, ±20% (pre-listed; diagnostics, not selection):**
   - One-at-a-time:
     - lookback 9.6m / 14.4m;
     - stop multiple 1.6 / 2.4 × ATR;
     - HOP target 8% / 12%;
     - band 20% / 30%.
   - Joint: all −20% and all +20%.
   - That is 10 runs. Each must keep OOS net SR > 0 and ≥ 50% of the primary's.
9. **LIMITS mechanical compliance on 100% of days:**
   - gross ≤ 60%;
   - every |position| ≤ 10%;
   - every position has a full-quantity stop, never loosened;
   - H2 ≤ 1% at every entry;
   - H4 cash-funded;
   - breakers applied as §5.
   - **As ruled (§9.C C4):** every order is limit-compliant; every EOD buffer breach (trigger 9.75% / 59% / 29.5%) and every EOD hard-limit breach (> 10%, > 60% or > 30%) is cured at the next open; hard breaches are reported with dates; **if hard-limit breaches occur on > 1% of sessions, 7.9 fails.**
10. **Blind segment (2005–2007): net return > 0 (hard gate, A2).** Its trade count is reported. It is too short to judge on its own and cannot rescue a failure elsewhere.
11. Capacity (§8): every trade ≤ 1% of 20-day ADV at $100k.

**Verdict mapping (STANDARD §9):**
- **Because the survivorship haircut is used and the 2008–16 segment is only partly blind, the best attainable verdict is CONDITIONAL PASS** (≤ 50% of target size, ≥ 60 trades or 3 months of paper probation).
- **STANDARD §3 caveat:** strictly unseen OOS (2005–2007) is under 3 years. Using 2005–2016 as the OOS segment is a declared judgement for **the validator to accept or reject at sign-off**. If he rejects it, the verdict is FAIL by construction, and we should not run.

**A FAIL on any hard bar shelves trend for this sprint.**
- No v4.
- No re-tuning.
- No promotion of stability runs.
- No re-reading of the backfill.
- The REGISTRY rows stay `failed`.

## 8. Reported (not gated)
- **Performance:** gross and net return, vol, SR, CAGR and max DD per segment and in full; per-asset and per-class contributions.
- **Activity:** turnover; average cost (bps) by bucket; trades; average holding period; gross return per unit turnover.
- **Legs and exposure:**
  - long and short legs separately;
  - correlation to SPY (and to the desk book when available).
- **Stops and breakers:**
  - stop-outs (count; average and worst gap slippage);
  - breaker days at H8 and H9;
  - days with G_cap binding;
  - LIMITS §4 gap stress (2 × stop distance).
- **Haircut:** the STANDARD §6 expectation, min(OOS SR, 0.40 × published SR).
- **Cost and borrow sensitivities:**
  - 2× costs;
  - borrow at 25 bps (the TCA owner) vs 1%;
  - NAV $1M.
- **Artefacts:**
  - a dated trial log, appended (N = 47);
  - the T × N matrix (OOS and 2017+);
  - trade list and equity curve;
  - meta.json with data, cost and code hashes;
  - sha256 over sorted outputs.

**Unit checks before the run:**
- gross ≤ 0.58 and |w| ≤ 0.095 after every fill;
- stop quantity = held quantity every day, and stop never loosened;
- stop fills at the open on gap days;
- re-entry only at month-end;
- breaker state machine on a synthetic path;
- with stops, caps and breakers off, the engine reproduces the v2 engine.

## 9. Disclosure: what may have been influenced by what we have already seen
Honest list. Each item's ex-ante justification is in §1, but none of these choices is blind:
1. **Universe = v2's CORE-L12 (identical 11 ETFs).**
   - The L1/L2 rule is a liquidity rule, but bucket membership was observed on 2016+ ADV.
   - FX and SHY were dropped after seeing v1's cost attribution and the validator's review (FX cost 2.5%/yr of NAV from L4 ETFs; SHY at about 1× NAV).
   - I have also seen v1/v2 per-asset contributions on 2017+. No asset in the 11 was added or removed because of them.
2. **12-month lookback:** MOP's default, and also the best gross lookback in v1. The 1/3/12 blend was dropped, and it had failed net in v1.
3. **Next-open fills:** required by STANDARD, but the validator's v1 diagnostic showed next-open (net SR 0.34) beat next-close (0.20) on 2017+.
4. **No-trade band 25%:** carried from PREREG-v2, set before v2 ran. v2 then showed the band added about +0.04 SR on 2017+.
5. **Long/short where shortable:** the paper default. v1's short leg was positive gross and v2's was negative. I kept the default and did not choose long/flat, but I know both facts.
6. **HOP 10% target:** paper default. v2's stability run at 8% looked better on drawdown on 2017+; it is **not** used.
7. **2 × ATR(14) stop:** the desk H6 buffer, never tested on trend by us. Its effect is genuinely unseen.
8. **Pre-2017 knowledge:**
   - I have **not** seen any desk backfill data.
   - I have read the validator's summary of his Yahoo 2008–2016 rerun (v1 config, 23 ETFs: 2008–2016 net SR 0.20, max DD −22.8%; net 2008 +17.2%, 2016 −14.3%).
   - Public knowledge of managed-futures history (strong 2008, weak 2009–2012) also informs priors for 2008–2016.
   - 2005–2007 is blind on desk data, but public CTA-index history for those years exists and is generally known.
9. **Data and snapshot moves today:** the TR build was rebuilt during the session (latest 01:32 SGT, sha256 `0590692d…29db`), and the assets snapshot was rewritten at 01:40 SGT (sha256 now `3996cd92…09`; it was `18b0cf27…7c2329` earlier). This is why every input is pinned by hash.
10. **Data substitution and jump rules (§2), written after the data owner saw the data:**
   - The validator approved option (b) as a non-trial data change, with N = 57, on condition that the rule is frozen before the v2 build.
   - The 25bp/50bp substitution thresholds are the data owner's existing QA thresholds. They were set after he had seen the flag counts on file (a) (72 rows; SPY/EFA/GLD overlap < 0.999) but no returns.
   - The J2 jump carve-out was general in his C7 check from the start. On file (a) it cleared only two rows, SLV 2026-01-30 and USO 2020-03-09. They are disclosed here, not listed as exceptions; v2 gets no named-date exceptions.
   - **Forking path (dry run).** Before this freeze, data owner ran an unpublished code-test dry run with a rule that is **not** this PREREG: 25bp close, 50bp O/H/L, Yahoo wins ties, table plus Yahoo splits.
     - It substituted 74 rows, and all 11 tickers passed its overlap checks.
     - It also showed that a strict table-only split rule aborts, and that an "official close wins ties" rule aborts.
     - Amendments (a) and (b) (split sources, and Yahoo as the reference for all fields) were therefore made **knowing those build outcomes**.
     - **No strategy returns were computed or seen.** The outputs are quarantined at `$QR_SCRATCH_DIR/trend_v3_build/scratch_unpublished/DRYRUN_TEST_RULE_NOT_PREREG/`, must not be used, and I have not opened them.
     - The final thresholds **match** the dry run's (25bp/50bp). They are the data owner's existing v1 QA price-agreement tolerances, set before the dry run, and were not tuned to the substitution count or to the pass result.
     - The only differences from the test rule are the abort mechanics (S5), the whole-row replacement (S4), and Yahoo being the reference for all fields (S2). The last makes "Yahoo wins ties" moot.
   - Pre-2016 rows cannot trigger (base data = Yahoo; Alpaca SIP from 2016-01-04). Nasdaq's official close starts on 2016-10-28 and is report-only.
   - I have not opened file (a), the dry-run outputs, or anything in `bars/daily/extended/`. The one exception is the pinned reference-source CSV (metadata, read to quote the data owner's per-ticker agreement stats). These facts come from the data owner's sign-off note and that CSV.

### 9.A validator's sign-off amendments (01:47 SGT; binding, added before any run; they supersede earlier text where they conflict)
- **A1. Trial count for the decision.**
  - DSR is decided at **N = 57**: 47 + the 10 stability runs. This is conservative, because of partial contamination.
  - N = 47 is reported alongside.
  - PBO uses every logged trial with a daily series (§9.B item 9).
- **A2. Blind 2005–2007 segment is a hard gate.**
  - Net return over 2005–2007 must be **> 0**.
  - Its trade count is reported.
  - The report must say plainly that **2005–2007 is too short to judge on its own**. Passing it is necessary, not sufficient.
- **A3. Late-inception rule (pre-specified).**
  - An ETF goes live on the first month-end at which it has **≥ 252 daily return observations** (signal) **and ≥ 60** observations for the EWMA variance. The 60 sit inside the 252, so 252 binds.
  - Until then its weight is 0, and it is excluded from N_live and the book covariance.
  - No prices are back-filled.
  - **Live-asset count by year** (min / mean / max per year at month-ends) is reported.
- **A4. Data hash.**
  - The sha256 of **the data owner's signed-off snapshot** is pinned in §2 and logged in §12 **before** the run.
  - **No run on a placeholder:** `run_v3.py run` refuses to start while §2 holds the placeholder, or if the file's hash differs from the pin.
- **A5. Conservative intraday execution.**
  - **Stops:** if a bar touches the stop (long: low ≤ stop; short: high ≥ stop), the fill is the **worse of the stop and the open** (long min(stop, open); short max(stop, open)). If a stop and any target or other same-bar level are both hit in one bar, **the stop is assumed hit**. v3 has no profit targets; the rule also governs the same-bar entry-and-stop case.
  - **Breakers simulated exactly as `risk/LIMITS.md` defines them:**
    - Peak (HWM) = highest **end-of-day** NAV.
    - Trips are checked on **live (intraday)** NAV. With daily bars this is a conservative bound: every open position marked at its adverse extreme (longs at the low, shorts at the high).
    - **5% → halve gross:** cap 30%, buffer 29%. Reduce to ≤ 29% by the trip day's US close, trimming the **largest risk-to-stop positions first**. Risk-reducing orders are always allowed.
    - **Full gross is restored only when EOD DD < 3%.** Between 3% and 5% the book stays halved.
    - **8% → halt:** no new positions and no adds. Exits, trims and tighten-only stop maintenance are allowed, and the cap stays at 30%.
    - **The halt lifts only when all three hold:** (1) CIO review, assumed completed and logged on the earliest eligible day; (2) ≥ 5 trading days since the halt; (3) the shadow book's 5-trading-day return is ≥ 0. The shadow book is the same signals and sizing with no breakers, net of TCA owner v1.1 costs and marked at closes.
    - **On lifting,** trading resumes in the halved state (29%). Full gross returns only via the < 3% rule.
- **A6. Drawdown in NAV, not R.**
  - All drawdowns (breakers, max DD, reports) are measured on **sleeve NAV in dollars** relative to the HWM: DD = 1 − NAV / HWM.
  - They are never measured in R-multiples or per-trade risk units.
- **Label.** 2005–2016 is the **quasi-OOS** segment throughout. 2005–2007 is blind, 2008–2016 partly seen, and 2017+ seen.

### 9.B Implementation clarifications (written with the engine, before any run; **CONFIRMED by the validator with conditions, §9.C**)
These fill gaps the spec did not pin. None is chosen from results; the engine has only touched 2016+ desk data and synthetic bars.
1. **Trip and re-arm.**
   - H8 re-arms only after full gross is restored. The first restore test (EOD DD < 3%) is at the EOD **after** the trip day; a trip and a restore cannot happen on the same session.
   - H9 re-arms only after the halt has lifted **and** an EOD close has been above the 8% line. This prevents a re-trip on every bar while DD stays ≥ 8% after a legitimate lift.
2. **Order of events on a session:**
   1. Overnight mark.
   2. Gap stops at the open.
   3. Pending trims at the open.
   4. Rebalance fill at the open.
   5. Intraday stop check on all positions, including ones opened that morning.
   6. Intraday breaker check.
   7. Breaker trim at the close.
   8. EOD restore and lift checks.
   9. EOD drift checks.
3. **Same-day re-entry.** An asset stopped out on a rebalance fill day cannot be re-entered by that day's fill. It waits for the next month-end rebalance (§4.6).
4. **Drift beyond H1 or H3** between rebalances is trimmed back to the buffer (9.5% per name; 58%, or 29% when halved, for gross) at the **next open** (STANDARD next-bar rule), pro-rata for gross. The trim triggers when EOD drift uses half of the buffer-to-hard gap (|w| > 9.75%, gross > 59% or 29.5%); this avoids daily dust trades of a few dollars while keeping every EOD inside the hard limit in all tests.
   - EOD hard-limit breaches (|w| > 10%, gross > 60% or 30%) are counted and reported. Criterion 7.9 is read as: every order is limit-compliant, and every buffer breach is cured at the next open. **The validator to confirm.**
5. **Missing ADV.** TCA owner v1.1 assigns bucket **L4** when ADV is missing (code behaviour). This is more conservative than "bucket default" in §4.5, and the engine follows the code.
6. **Cost-model notional.**
   - Notional is |Δw| × $100,000 (fixed NAV basis, the same convention as v1 and v2).
   - Cost in NAV = |Δw| × bps. Costs reduce NAV.
7. **Splits.**
   - A split day is any day where the raw-close ratio and the TR ratio differ by more than 30%.
   - On that day the stop level is scaled by the implied ratio and ATR uses split-adjusted OHLC. This also handles a splice seam between split-adjusted history and raw 2016+ bars.
8. **No OHLC.**
   - If any universe ETF lacks high/low data where an ATR is needed, ATR(14) is undefined. **The run aborts rather than inventing a proxy.** Any ATR fallback needs the validator's prior decision.
   - A missing open price falls back to the close (§3.7).
9. **PBO columns.**
   - ~~The 2017-02 → 2026-10 net matrix holds the 24 logged trials, the v3 primary and the 10 stability runs: 35 of 57.~~ **Superseded by §9.C C9: 40 of 57** (adds the validator's 5 v1 cost settings).
   - The validator's 17 diagnostics have no saved daily series and will not be regenerated before the run. The gap (17) is reported.
10. **ATR convention.** ATR(14) is the simple mean of the last 14 true ranges, matching the desk's H6 implementation (`portfolio/construct.py`). §4.1's earlier "Wilder's" wording was wrong and is corrected.
11. **Trade count (§7.6, A2).** Counted trades are entries, exits (including stop-outs and breaker exits) and sign flips. Resizes, band re-caps and drift trims are logged and costed but not counted.
12. **H8 trim cost.** Gross is trimmed to ≤ 29% of post-trim NAV (the trim is repeated once if its own cost lifts gross above 29.01%).

### 9.C the validator's §9.B decision (2026-10-30 ~02:10 SGT; binding conditions, part of the frozen spec)
Source: the internal review record (he reviewed this file at sha256 `bc39db73…e3af`). Items 3, 5, 6, 10 and 12 are confirmed as written, and so is calendar-year concentration as a hard test (§7.7).
- **C1. Trip/re-arm, confirmed.** The breaker is **frozen** as written in §5 / §9.A A5 / §9.B(1). **LIMITS v0.3.x is NOT adopted.** Disclosed in §5 and in `meta.json`: the live breaker may differ. Engine: `FROZEN_BREAKER` constant; the engine never reads `LIMITS.md`.
- **C2. Order of events, confirmed.** The H8 close trim is costed at TCA owner venue **`continuous`**, not `open`. Engine: `trim_venue="continuous"`; every trade row records its venue.
- **C4. Drift trims and criterion 7.9, confirmed** with the 9.75% / 59% / 29.5% triggers and next-open trims. Every EOD hard-limit breach is also cured at the next open and **reported with dates** (`outputs_v3/limit_breaches.csv`). **Hard-limit breaches on > 1% of sessions fail 7.9.** Engine: `limits_compliance()`.
- **C7. Splits, amended (02:25 SGT; validator-approved as non-trial, 02:26 SGT).** The split source is **the data owner's corporate-action table from its start, 2016-01-05**, and **Yahoo split events before that**. The five Yahoo events are listed in §2: IWM, EFA and EEM on 2005-06-09, and EEM and SLV on 2008-07-24. *Why:* the corporate-action table starts in 2016 and lacks those five pre-2016 splits. A strict table-only rule would therefore always abort on the > 30% cross-check, so it cannot be run as written. The > 30% raw-vs-TR heuristic remains a **cross-check only** (it misses 5:4 and 4:3 splits), and it runs over the **full history** against the merged source. **Any mismatch aborts the run**: a heuristic split missing from the merged source, a factor that disagrees with the raw/TR ratio by more than 5% (log), a corporate-action row before 2016-01-05, or a Yahoo row on/after it. **Every split applied is listed with its source** (`outputs_v3/splits_applied.csv`, column `source`).
- **C8. No OHLC, confirmed: abort, no fallback pre-granted.** A needed ATR, or a held position's close/high/low, missing → abort. The old close-trigger stop fallback is removed. A missing open may fall back to the close only if such fills are **≤ 0.5% of open-priced fills** (rebalances, next-open trims, gap and intraday stops); above that the run aborts. The count is reported.
- **C9. PBO: 40 of 57.** Adds the validator's 5 v1 cost settings: columns 20–24 (`costs_2x`, `venue_close(MOC)`, `impact_k0.5`, `nav_10m`, `borrow_50bps`) of `validation/backtests/trend_sleeve/u23/trial_matrix_net_TxN24.csv` (sha256 `b0506fca…28d8`, pinned in code), 2017-02-01 → 2026-10-28. The gap is the validator's 17 diagnostics (no daily series). **DSR still uses N = 57.**
- **C11. Trade count, confirmed.** A sign flip counts as **one** trade.
- **C12. H8 trim to ≤ 29% post-cost, confirmed.**
- **Run gate.** No run until the data owner's signed-off **build hash and corporate-action table hash** are both pinned in §2 and logged in §12. `run_v3.py run` refuses otherwise. `run_v3.py pin --sha256 <H> --ca-sha256 <C>` verifies both files before writing either pin.

**Prior expectation, stated before running:**
- At 58% gross with tight stops and breakers, I expect OOS net SR of roughly 0.2–0.5 and a high stop-out rate.
- P(all hard bars met) ≈ 5–10%. The most likely failure points are item 1 (SR > 0.625) and item 3 (DSR).

## 10. Run protocol
1. The validator and the CIO sign this file. The §2 reference-source table (TBD-2) is pinned before the v2 build. Data owner builds v2 under the §2 substitution rule and publishes the diff. v2 passes all 11 overlap checks and his C7 jump/split checks. Data owner then signs off the backfill, its corporate-action table and the diff, and all three hashes are entered in §2 and logged in §12.
2. Code is written and the unit checks pass on the **2016+ desk data only**, with no performance printed. Code hashes are recorded.
3. **One execution** writes `outputs_v3/`. Results go into RESULTS-v3.md and the trial log (trial #47).
4. A bug found after the run may be fixed only if it is a mechanical error against this spec. The fix is logged, the rerun is disclosed, and the validator decides whether it counts as a new trial. No parameter changes are allowed.

## 11. Multiple-testing accounting (desk convention)
**N = 47 = 46 prior trials + this one.**

| Prior trials | Count |
|---|---|
| v1 logged signal/sizing trials | 19 |
| v1 cost settings, counted per the validator | 5 |
| The validator's diagnostics (timing 3, extra cost cells 2, stability 8, limits 3, universe u25 1) | 17 |
| v2 pre-registered variants | 5 |
| **Total prior** | **46** |

- **Convention:** every configuration ever run on desk data counts, including cost settings and the validator's diagnostics, whether or not it was used for selection. The validator's Yahoo extension (the same config on other data) is not counted.
- **The 10 stability runs in §7 item 8 are required STANDARD diagnostics.** Under the strict form of this convention they would also count. **Per A1 the decision uses N = 57** (conservative, for partial contamination), with N = 47 reported alongside.

## 12. Change log
- 2026-10-30 ~01:45 SGT: draft written. Data-build hash is a placeholder. Nothing run.
- 2026-10-30 01:47 SGT: the validator's sign-off amendments A1–A6 and the quasi-OOS label added (§9.A), with inline pointers in §3, §4.4, §5, §6, §7 and §11. Implementation clarifications added (§9.B). Data hash still a placeholder. Nothing run.
- 2026-10-30 ~02:04 SGT: engine written and unit-tested on synthetic and 2016+ desk data only (53/53 checks). §4.1 ATR wording corrected (simple mean, §9.B(10)); §9.B(1) restore timing, §9.B(4) drift-trim trigger, §9.B(11) trade-count definition and §9.B(12) trim cost added. Data hash still a placeholder. Nothing run.
- 2026-10-30 ~02:13 SGT: the validator's §9.B decision (the internal review record, reviewed sha `bc39db73…e3af`) applied as §9.C. C1: breaker frozen, LIMITS v0.3.x not adopted, live-breaker disclosure added. C2: H8 close trim costed at continuous. C4: 7.9 now requires every EOD hard breach cured at the next open and reported with dates, and fails at > 1% of sessions. C7: splits from the data owner's corporate-action table, heuristic is a cross-check, a mismatch aborts, every applied split is listed; new §2 placeholder row. C8: OHLC fallbacks removed (abort); missing-open fallback ≤ 0.5% of open-priced fills, otherwise abort. C9: PBO 40 of 57 (+ u23 columns 20–24), gap 17, DSR N = 57. C11: flip = one trade. Run gate now requires both the build and the corporate-action table hashes. Engine and tests updated: 86/86 checks pass on synthetic and 2016+ desk data only. The run_v3 pipeline was smoke-tested end-to-end on random synthetic bars in a throwaway copy (no real data, discarded). Both hashes still placeholders. Nothing run.
- 2026-10-30 ~02:15 SGT: the validator approved option (b); substitution and jump rules frozen before the v2 build; non-trial, N=57; nothing run.
- 2026-10-30 ~02:25 SGT: TBD-2 closed. Reference-source table pinned (`1388e51c…7380`, sha256 verified). Amendments, approved by the validator at ~02:26 SGT as non-trial, N=57:
  - (a) Splits come from the corporate-action table from 2016-01-05 and from the five frozen Yahoo events before that, with the C7 cross-check and abort over the full history. C7 reworded: a table-only rule always aborts because the table starts in 2016.
  - (b) The reference is Yahoo raw for all four OHLC fields. The validator waived 'prefer official close'. Nasdaq's official close is a report-only cross-check: X1 per-ticker agreement within 1bp, X2 substituted rows > 10bp (must be in the diff), X3 all rows > 25bp.
  - (c) Pre-2016 rows never trigger (base data = Yahoo; Alpaca SIP from 2016-01-04); a pre-2016 diff row aborts. Nasdaq coverage starts 2016-10-28.
  - **Forking-path disclosure:** the data owner's unpublished dry run used a test rule that is NOT this PREREG (25bp close, 50bp O/H/L, Yahoo wins ties, table plus Yahoo splits). It substituted 74 rows and all 11 tickers passed. No returns were seen. The output is quarantined at `$QR_SCRATCH_DIR/trend_v3_build/scratch_unpublished/DRYRUN_TEST_RULE_NOT_PREREG/` and was not opened by me. The final thresholds MATCH the dry run's (25bp/50bp) because they are the data owner's existing v1 QA price-agreement tolerances, set before the dry run, and not tuned to the substitution count or to the pass result. The only differences from the test rule are the abort and whole-row replacement mechanics, plus Yahoo as the reference for all fields, which makes 'Yahoo wins ties' moot. Decisions (a) and (b) were made knowing the dry run's build outcomes (table-only splits abort; official-close-wins-ties aborts).
  - Code: merged split source and audit, S4/S5/S3 diff audit, Nasdaq cross-check report. Tests pass (see FROZEN-v3.txt). Nothing run on real data.
- 2026-11-06 06:14:23 SGT: data-build hash pinned (A4): `c998ca5c33eee487bbdcdbee929ecc2e003078653c2ec5cf15b905c3f9e0ab78` for `$QR_DATA_DIR/bars/daily/extended/signoff/trend_v3_v2_etf_daily_20261030.parquet`; corporate-action table hash pinned: `b415ae397380b6adf287110bdb759afa5ece1f1cde7dd0832d5924993c72fb5e` for `$QR_DATA_DIR/bars/daily/extended/signoff/corporate_actions_splits_snapshot_trend_v3_v2_20261030.parquet`; v2 substitution-diff hash pinned (option (b)): `8225dded490c5567ec446d81b9e10d9161ee1225a3f7bc27e94dccc46bd671ee` for `$QR_DATA_DIR/bars/daily/extended/signoff/trend_v3_v2_substitution_diff_20261030.csv` (data_spec_v3.json sha256 `cd5553db078ec5626d56788e1b4d558b581a7ebf18e83911bb041771a2ee74c9`). Nothing run yet.
