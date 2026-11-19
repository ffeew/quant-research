# PREREG — IV-gap study v2 (DRAFT r3 for Victor seal)

Author: Equity and Sentiment (Ethan). Drafted 2026-11-13 (SGT). Status: DRAFT r3, text only.
r3 supersedes r2 (iv_gap_prereg_v2r2_20261113/PREREG_IV_GAP_v2_DRAFT_r2.md 8af36be7...) and r1
(iv_gap_prereg_v2_20261113/PREREG_IV_GAP_v2_DRAFT.md 18bda59f...); neither was sealed and both are kept as evidence.
r2 = OQ-2 per Jeremy 13 Nov 2026 16:18 SGT. r3 = Victor L567 (log e0159e60) amendments A1-A7 on top of r2
(see CHANGES_r2_to_r3.md).
Approval: Jeremy, 13 Nov 2026, "prereg drafting only". No run is authorised by this document.
Drafting inputs (governance text only, no data): SUPERSEDED b3bc0a6c, PROVENANCE_LOG 5eab781b,
v2 STOP f00c3f67 / FORKING_PATH 338f2d04 / PROVENANCE 73b52e20 / MANIFEST 075b0e78,
options ideas 25087a7f + ERRATUM_1 74d2ae79, DESK_RULES.md. No file under $QR_DATA_DIR/ and
no v1 output was opened to draft this.

## 1. Question and scope
Q: On the DEV partition, how far does Alpha Vantage (AV) reported option IV depart from the desk's own
Black-76 IV for SPY and QQQ, and how much of the chain is usable? The answer decides only whether AV IV
may serve as a **cross-check** on the desk's own IV. It is never an alpha input and never a gate.

- Partition (Victor 63d3073d): DEV 2009-01..2016-05; OOS 2017-09..2022-07; holdout 2023-11 onward.
  **This study is DEV ONLY.** Options files dated 2016-06-01 or later (options/{SYM}/oos_holdout/) are
  never content-read, by this study or its runner.
- Underlyings: SPY, QQQ. QQQQ is mapped to QQQ before the 2011 ticker cutover **inside Dmitri's reader**;
  the runner applies no mapping of its own.
- Underlying close S (Jeremy ruling (c), 13 Nov 2026): the AV underlying daily close, read **only through
  Dmitri's sealed reader** under the same partition guard, on the same date as the options snapshot. Alpaca and
  desk_data_client get_daily_bars are **not** used. A sampled day with no reader S is excluded as `no_underlying`
  and counted.
- No trade is tested. No returns, P&L, realised vol, price paths or gate states are computed (cond. 3).

## 2. Ruling 5e5b3469 conditions, as encoded
1. DEV only — enforced by the reader (refuses oos_holdout/ and any date >= 2016-06-01), not by runner filters.
2. Reads only through Dmitri's sealed, hash-pinned AV options reader. No ALPHAVANTAGE_API_KEY in the run env
   (`env -u ALPHAVANTAGE_API_KEY`), no network, no direct file reads of chains or underlyings.
3. No returns, P&L, realised vol, paths or gate states.
4. Output = IV-gap and coverage statistics only, aggregated to at least symbol x year. No per-date or
   per-contract IV levels, no absolute IV medians, no per-date rows of any kind.
5. The 0.05/0.10 thresholds and the 10% kill stay frozen exactly as defined at source (A1, verbatim):
   - VRP PREREG_v0.1.md (sha 85dc4d12...) L119: "|vendor IV − desk IV| > 0.05 (absolute) is **flagged**, and > 0.10
     is **dropped**. Flag and drop rates are reported by year."
   - Same file L231: "K3: **Data quality.** The §7 exclusion rate is > **10%** of decision-window sessions in the
     segment, **or** the vendor-vs-desk IV drop rate is > 10% of candidate legs."
   - PARAMS_v0.1g (sha 15334796...) L570-571 (flag 0.05, drop 0.1), L609 (iv_thresholds_frozen_before_ethan_gap_study
     true), L1038 (vendor_iv_drop_rate_max 0.1); ruling 5e5b3469 L53-54. (Cites as given by Victor L567.)
   - Statistic: absolute gap |AV IV − Black-76 IV| per contract, in vol units; flag and drop rates are computed over
     legs (contracts). Any rule change = hashed amendment filed before any DEV result exists.
6. Logged as a forking path; anything it selects counts toward N (§8).
7. Provenance logged: every reader call (symbol, date), reader sha, runner sha, env, start/end SGT.

## 3. Method (pre-specified; nothing tuned)
**Sampling.** For each symbol and each DEV calendar month (2009-01..2016-05, 89 months), sample **1 trading
date** uniformly without replacement from the dates the reader lists for that symbol-month, using
`random.Random("20261113:{SYM}:{YYYY-MM}")` (Python stdlib, string seed; master seed **20261113**, new for v2,
not v1's). Months with no listed date are logged as `no_date` and not back-filled. Expected <= 178 sampled days.
Size chosen for the rule-6 35-minute budget, not from any result.

**Per sampled day, per expiry.** DTE = calendar days to expiry; T = DTE/365.
- Mid = (bid + ask)/2, computed by the runner. The AV `mark` field is used only in the sanity check (§4).
- Forward and discount from put-call parity: take the 5 strikes nearest the day's underlying close S with both
  call and put valid (bid > 0, ask >= bid); OLS of (C_mid - P_mid) on K gives slope = -DF, intercept = DF*F.
  The expiry is excluded as `parity_fail` if < 3 valid pairs, DF outside (0.95, 1.01], or F/S outside
  [0.90, 1.10]. **No clamping** of DF or F (v1's DF-clamp patch is not reused).
- Black-76: price = DF*[F N(d1) - K N(d2)] (call), DF*[K N(-d2) - F N(-d1)] (put). Solve sigma by Brent on
  [1e-4, 5.0], xtol 1e-8, max 200 iterations; failure to bracket or converge = `iv_fail`.
- Gap = AV-reported IV minus our Black-76 IV (vol units, e.g. 0.01 = 1 vol point). Per contract: flag = |gap| > 0.05;
  drop = |gap| > 0.10 (A1).
- AV IV is used **as reported** (A7). Its convention (model, spot vs forward, rate/dividend inputs, day-count) is
  undocumented by AV and is **unknown**; this is disclosed and not corrected or inferred.
- Disclosed limitation: SPY/QQQ options are American with dividends; Black-76 on a parity forward is an
  approximation, and the gap includes any early-exercise premium. Not corrected.

**Exclusions** (applied in this order; each contract counted once, in its first failing category):
`crossed` (ask < bid or either missing), `zero_bid` (bid <= 0), `dte_lt_3`, `dte_gt_365` (scope),
`mny_out` (|ln(K/F)| > 0.30, scope), `parity_fail` (whole expiry), `below_intrinsic`
(mid < DF*max(F-K,0) call / DF*max(K-F,0) put), `av_iv_missing` (AV IV null or <= 0), `iv_fail`.

**Buckets.** Moneyness m = ln(K/F), edges [-0.30, -0.15, -0.075, -0.025, 0.025, 0.075, 0.15, 0.30]
(7 buckets). DTE edges [3, 8, 22, 46, 91, 181, 366) (6 buckets). Year = calendar year of trade date
(2016 = Jan-May only). Option type C/P reported separately and pooled.

**Statistics per symbol x year x type x moneyness x DTE cell:** n, median gap, mean absolute gap, flag rate
(|gap| > 0.05) and drop rate (|gap| > 0.10) (A3). Cells with n < 20 report n only (stats and rates blank) to avoid
near-contract-level disclosure (floor accepted by Victor, OQ-6).
Also per symbol x year: coverage, every exclusion count (§3 list), contracts seen and kept, and the symbol-year flag
rate and drop rate over all kept legs (A3), in both gap_stats.csv and coverage.csv.

## 4. Additional checks (Jeremy)
**4a. Bid/ask/mark sanity, 2009 focus.** For every year (2009 shown first, 2010-2016 as comparison), per symbol:
fraction of contracts with (i) bid = 0, (ii) ask < bid, (iii) AV mark outside [bid, ask], (iv)
|AV mark - mid| > $0.005, (v) mark null. Counts and fractions only.
**4b. Put-call parity violations by year.** For each same-K, same-expiry pair with both legs valid, on expiries that
passed the parity fit: violation if C_bid - P_ask > DF(F-K) + 0.01 or C_ask - P_bid < DF(F-K) - 0.01 ($).
Report pairs tested, violations and rate per symbol x year x DTE bucket. Circularity (F, DF fitted from the
same quotes) is disclosed; this is a quote-consistency diagnostic, not an arbitrage claim.

**4c. Greek gaps.** NOT computed (A4; Victor ruled them not permitted under condition 4). No delta, vega,
theta or other greek field is read into any statistic or output.

## 5. Outputs (raw, to Victor first)
`gap_stats.csv`, `coverage.csv`, `sanity_bidask.csv`, `parity_violations.csv`, `reader_calls.tsv`
(symbol, date, reader sha — no contents), `run.log`, `SHA256SUMS`. Files 0444, dir 0555 at run end.
No IV levels, no per-date rows except the date list in reader_calls.tsv. Nothing else is written.

## 6. Prerequisites — hard STOPs (any unmet = no run; report to Victor and Jeremy)
- **STOP-a.** Dmitri's AV options reader is sealed and hash-pinned; it refuses oos_holdout/ and any date
  >= 2016-06-01, and carries the QQQQ->QQQ map. (Per Jeremy, queued behind Dmitri's r3md18 work.)
- **STOP-b.** Victor has sealed this prereg (sha pinned).
- **STOP-c.** RESOLVED (Jeremy 13 Nov 2026): S = AV underlying via Dmitri's reader. The reader must also serve
  the AV underlying close under the same partition guard; if it does not, STOP-a is unmet.
- **STOP-d.** Freeze and run are under the line Jeremy ruled at INC-96, carried verbatim in
  $QR_DESK_DIR/validation/dmitri/r3md18_design/BRIEF_r3md18_drafterA0.md (sha 5f45117420603de6c3dae3202117f673255bf4b7b45cd6a587da502b12d362be, L3 and L34) (A6):
  "Exact paths only; no recursive search; no /proc, ps or pkill; everything under full L3 with python3 -I -B; holdout files (2016-06-01 onward) are hashed and counted from raw bytes only, never parsed."
  (The 2016-06-01 date is Jeremy's text and refers to the condor holdout; it is kept unchanged.) This study's own
  window, stated separately: DEV 2009-01-01..2016-05-31 only; nothing dated 2016-06-01 or later is content-read.
  Runner freeze (SUMS) -> Victor confirmation -> LOCK -> **ONE run** on the INC-99 venv
  `$QR_DATA_DIR/.venv/bin/python -I -B`, `env -u ALPHAVANTAGE_API_KEY`, no network.
- **In-run STOPs** (end the run, no retry, report to Victor): reader refuses or returns any date >= 2016-06-01;
  any path under oos_holdout/ touched; key present in env; any network attempt; output would contain an IV
  level or per-date row; plan exceeds rule-6 budget (split instead, per rule 6(d)).
- Raw output and run.log go to Victor unread and unanalysed (S6 pattern). Nothing to anyone else first.

## 7. DECISION / USE
- Result use is limited to one question: may AV IV be used as a **cross-check** on the desk's Black-76 IV,
  and in which symbol x year x moneyness x DTE cells? It never becomes alpha, a signal, a gate or a filter.
- **Usability rule (A2; the only cut-off used).** A cell is reported with statistics only if n >= 20. A reported
  cell is **usable as a cross-check iff its drop rate (|gap| > 0.10) is <= 10%**. **Kill:** if a symbol-year's drop
  rate over all kept legs is > 10%, there is **no AV cross-check for that symbol-year**, whatever its cells show.
  The condor K3 itself stays in the condor prereg and is not decided here.
- Possible readings: (i) reported cell with drop rate <= 10% in a non-killed symbol-year -> AV IV usable as
  cross-check there; (ii) cell drop rate > 10%, or n < 20 -> not usable there, desk Black-76 IV only; (iii) kill
  tripped -> AV IV not used as cross-check at all for that symbol-year. 2009 is expected (§9 D3) to be scrutinised; a 2009 failure does not widen to other
  years without its own cells failing.
- The v1 entry "Dave's Black-76 IV is primary; AV IV is not used for gating" stands whatever v2 shows.
- **Trade expression.** This study tests no trade and produces no tradeable output. Any future trade test that
  cites it is stated as defined-risk only (vertical spreads, iron condors, or flies with long wings), with no
  naked short volatility and no leverage, needs its own prereg, and needs Rachel, Tomas and Daniel sign-off.
  Paper only (desk rule 3).

## 8. N / forking-path ledger
| # | Entry | Source | Counts toward N |
|---|---|---|---|
| F1 | "Dave's Black-76 IV is primary; AV IV is not used for gating" | v1 PROVENANCE_LOG §5 item 1; SUPERSEDED | Yes (+1), stands |
| F1b | v1 §5 item 2 (AV cross-check only where sane) | v1 PROVENANCE_LOG §5 | Yes (+1), separate from F1 (A5) |
| F1c | v1 §5 item 3 (contango sign, erratum'd) | v1 PROVENANCE_LOG §5 | Yes (+1), separate from F1 (A5) |
| F2 | v2 STOP attempt 2026-11-10 | v2 FORKING_PATH | 0 (nothing selected) |
| F3 | This study's cross-check usability selection (per cell) | this prereg §7 | Yes (+1 on completion) |
Any cell-level or parameter choice made after seal is an amendment and is appended here.

## 9. Deviations / disclosures to date
- **D1. v1 exists** (iv_gap_study_20261110, MANIFEST 8d6045c4, SUPERSEDED b3bc0a6c). It ran before ruling
  5e5b3469 and deviates: direct chain/underlying reads, two AV key calls, per-date IV levels, extra greek
  stats, and two analysis runs with a DF-clamp patch between them. Its outputs are **provenance only** and feed
  no gate, threshold, parameter or selection here.
- **D2. v2 STOP (2026-11-10)** inspected desk client code, the options MANIFEST.csv metadata and directory
  listings; no chain content. Not a selection.
- **D3. Drafter exposure.** The provenance log quotes v1 IV levels and a qualitative 2009 AV-IV anomaly; the
  drafter read that text. No v1 value sets any parameter here: seed is new, bucket edges, DTE edges, exclusion
  rules and sample size are stated defaults. The 2009 sanity check (§4a) is Jeremy's addition. 2009 findings
  are therefore not blind discovery and are labelled as such.
- **D4. New vs prior description:** added `crossed`, `dte_gt_365`, `mny_out`, `parity_fail`, `av_iv_missing`
  categories and the n < 20 suppression rule. Declared here, pre-run. r2 adds `no_underlying` (S missing from
  the reader for a sampled day).

## 10. OPEN QUESTIONS (Victor / Jeremy)
- **OQ-1 — RESOLVED (Victor L567).** Verbatim source text in §2 item 5 (A1); usability rule in §7 (A2).
- **OQ-2 — RESOLVED (Jeremy, 13 Nov 2026 16:18 SGT).** S = AV underlying close via Dmitri's reader (one vendor,
  one partition guard, date-aligned with the options snapshot). No Alpaca. S is used only to pick parity-fit
  strikes and the F/S sanity bound.
- **OQ-3 — RESOLVED (Victor L567, A7).** AV IV reported as-is; convention unknown and disclosed (§3).
- **OQ-4 — RESOLVED (Victor L567, A4).** Greeks not permitted; not computed (§4c).
- **OQ-5 — RESOLVED (Victor L567, A5).** Stricter reading: v1 §5 items 2 and 3 count +1 each (§8).
- **OQ-6 — RESOLVED (Victor L567).** Accepted: 1 sampled day per symbol-month; n < 20 floor.
- **OQ-7 (Dmitri via Jeremy).** Reader API names and whether it lists DEV dates per symbol (needed for sampling).
