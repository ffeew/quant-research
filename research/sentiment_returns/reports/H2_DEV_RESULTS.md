# EXPLORATORY: cannot PASS; DEV only; for the validator
**50 DEV calls excluded as not-yet-due (erratum 7584b5b5, S6b readback b4652cef).**
H2 = earnings-call tone surprise -> post-event drift, sessions +2..+21, beta-adjusted (prereg v5 4b045f05, §2/§5).
Exploratory - not a confirmatory test (A5): never PASS, not in the Holm family, N stays 2. DEV only (closes <= 2024-12-31).
Event date = AV EARNINGS reportedDate + reportTime PROXY, not a verified call timestamp. Survivorship-biased universe
(any positive result is an upper bound). Scores not verified point-in-time (§7). No trading. No results to Daniel until validator validates.
Script h2_dev.py; log h2_dev.log; stats H2_DEV_STATS.json; per-quarter H2_DEV_periods.tsv; per-event H2_DEV_events.tsv (no transcript text).

## Headline DEV stats (identical under the UTC and ET readings - H2 uses no news timestamps; A4: delta IC = 0, not material)
| Reading | Scored quarters | df | Mean IC | IC s.d. | NW t (lag 1) | One-sided p (Student t) | Events scored | Quarters |
|---|---|---|---|---|---|---|---|---|
| UTC | 9 | 8 | 0.094735 | 0.111272 | 2.7095 | 0.013339 | 446 | 2022Q3..2024Q3 |
| ET  | 9 | 8 | 0.094735 | 0.111272 | 2.7095 | 0.013339 | 446 | 2022Q3..2024Q3 |
Long/short top k / bottom k (k = floor(n/5), mean k 9.67, n 48-50 per quarter), mean per quarter (20-session holding):
gross raw 0.016756; net raw at 10 bps/side 0.012756; net raw at 20 bps/side 0.008756; gross beta-adj 0.013162; net beta-adj 10 bps 0.009162.
R-RT (exclude missing/unknown reportTime): 0 such events, so identical to the main run.
Exploratory: these numbers carry no PASS/FAIL meaning. DEV is plumbing/reference for the single OOS run only.

## Exclusion / event counts (587 due labels = universe of mapped events)
- Not-yet-due: 50 present DEV calls excluded (NOT_YET_DUE.tsv, 213 rows; never filled, never opened, not prior calls).
- Missing transcripts: 0 among the 587 due labels; 0 in the H2 label window 2021Q4..2025Q3 per coverage index; §3A table
  (MISSING_TRANSCRIPTS_A6.tsv fc305390): 84 total (unannotated 38, pre-listing 25, unexplained 19, error 2), 0 in window. DEV
  window missing = 0; the one post-window label (HD 2026Q2) is OOS-side and not touched here.
- Straddling (B3/B8, return window ends after 2024-12-31): 0. (Every due label's day 0 is <= 2024-10-02; Dec-2024 reports
  belong to not-yet-due quarters.)
- Below-minimum: tone < 10 parseable entries: 3 (CRM 2025Q2 4, WMT 2023Q4 8, XOM 2024Q1 4); < 2 prior calls: 35;
  day-0 quarter < 20 events: 22 (2022Q1 4, 2022Q2 17, 2024Q4 1) -> 3 quarters dropped.
- Baseline-only (day 0 before 2022-03-01, no 252-return beta): 81.
- Included (scored): 446. Missing target: 0. reportTime defaulted to post-market: 0 (pre 333, post 254).
- Mapping cross-check vs S6B labels tsv: 587/587 consistent (re-derived reportedDate rows, lag 0..100). Transcripts opened: 587, sha OK 587/587.

## Ambiguities and choices (conservative readings)
1. Baseline universe: only the 587 S6b due labels are mapped (per instruction), so labels before 2021Q4 are NOT used as prior
   calls. v5 §0 had assumed earlier labels as baselines; this costs early events (35 with < 2 priors; 2022Q1-Q2 dropped < 20).
2. "Previous 4 available calls": available = due-mapped, present, and tone non-missing (>= 10 parseable); a call with missing
   tone is not a prior call. Strictly earlier day 0; up to the 4 most recent; >= 2 required.
3. Beta for an event = OLS on exactly 252 daily returns ending day 0 - 1 (dev_run beta at index day 0); target =
   compounded raw return over sessions +2..+21 (close(+1) -> close(+21)) minus beta x SPY compounded return (dev_run convention).
4. Cross-section = calendar quarter of day 0; the 20-event minimum is applied after all event-level exclusions.
5. Costs: H2 event holdings do not roll from quarter to quarter, so each scored quarter is charged a full flat-book round
   trip (turnover 4: enter 2 gross, exit 2) at 10 bps/side (20 bps sensitivity). More conservative than dev_run's rebalance turnover.
6. Ties in long/short leg ranking broken by (surprise, symbol, label). No same-symbol duplicate within a quarter occurred.
7. Timestamp readings: v5 asks for both; H2 inputs contain no news timestamps, so both are reported and identical by construction.
8. Tone = mean of float-parseable, finite `sentiment` values over all transcript entries; `content` never read; symbol/quarter keys asserted.
9. Transcripts opened only for due labels with day 0 <= 2024-11-29 (all 587 qualified); none from not-yet-due labels.
10. Helper logic copied from dev_run.py (80f4bb71) and fiscal_diag_s6b.py (5aa458ac), not imported (both execute and write at import).
11. Day 0: pre-market -> reportedDate session (or next session); post-market / unknown -> next XNYS session after reportedDate.
