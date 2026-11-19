# FISCAL_DIAGNOSTIC_S6B: prereg v5 §2 step 4 rerun under validator decision plus Erratum 1, DEV metadata only
Run 2026-11-11 ~14:58 SGT with `python3 -I -B fiscal_diag_s6b.py` (EDGE defaults to 2024-12-31; log: fiscal_diag_s6b.log).
No transcript file was opened. No returns, sentiment, holdout/, raw/, news, staging, verdicts-log or network were touched.
The S6 folder sentiment_returns_fiscal_diag_s6_20261111/ was read only (SUMS, -c 6/6 OK) and not modified.

Inputs:
- annual_fye_dev.csv (SUMS OK)
- partitioned/dev/earnings_dev.csv (dev SUMS OK)
- coverage_transcripts.tsv (labels and status only, same use as S6)
- FYE_MONTH_FROZEN.tsv, a byte-for-byte copy of the S6 table that the validator accepted
- Erratum and decision (sha verified)

Files: fiscal_diag_s6b.py, FYE_MONTH_FROZEN.tsv (S2 input), FISCAL_DIAGNOSTIC_S6B.tsv (per symbol), FISCAL_DIAGNOSTIC_S6B_labels.tsv (per due label), NOT_YET_DUE.tsv, fiscal_diag_s6b.log, this file and SHA256SUMS.

## Rule as implemented (Erratum 1)
- A quarter n of FY Y is DUE at EDGE if nominal quarter-end (month-end of m−9, m−6, m−3 or m in the end-year convention) + 100 d <= EDGE.
  - At 2024-12-31, a quarter is due if its quarter-end is on or before 2024-09-22.
  - The test uses dates and the lag bound only, never whether a row exists.
- CLOSED FY means all 4 quarters are due. It is checked exactly as in S6: 4 rows in (end FY Y−1, annual end FY Y], Q4 within ±7 d of the annual end, and the rows are unique.
- Other FYs: k is the number of due quarters.
  - Each row is assigned to a quarter by date window (b0, b1], (b1, b2], (b2, b3], (b3, b4].
    - b0 is the prior annual end.
    - b1 to b3 are the nominal quarter-ends + 7 d.
    - b4 is the annual end if one exists; otherwise it is the nominal FY end + 7 d.
  - Each due quarter needs exactly 1 row with a lag of 0 to 100 d.
  - Each not-yet-due quarter may have at most 1 row (unique mapping). A missing row is not a failure.
  - In every open FY here, the row count equals k plus the number of not-yet-due rows present, so the window assignment matches the S6 ordinal assignment.
- S3 scope: FYs spanned by present labels 2021Q4–2025Q3, plus FYs through EDGE.year+1, each with at least 1 nominal quarter-end on or before the edge.
- Step 4 (new S4): the numerator and denominator cover present labels 2021Q4–2025Q3 of due quarters only. The 90% bar is unchanged.
  - A match needs the FY-level S3 check to pass, the quarter's unique row, and a lag of 0 to 100 d.
  - Off-by-one test (4b, m≠12): the label year is shifted by −1 and +1. A shifted quarter that is not yet due returns not_due.
- Not-yet-due labels are listed in NOT_YET_DUE.tsv: symbol, label, quarter_end, due_date, quarter_end_le_edge, row_present (y/n), and that row's dates. They are excluded from DEV H2 and are NEVER filled.
- EDGE is a parameter (argv[1]). The same rule applies at the OOS edge 2026-10-31, with the frozen months from FYE_MONTH_FROZEN.tsv.
  - At 2026-10-31 a quarter is due if its quarter-end is on or before 2026-07-23.
  - The script refuses any edge after 2024-12-31, because the OOS edge needs released HOLDOUT inputs.
  - It was NOT run at the OOS edge.

## Headline
- S1/S2: 50/50 months frozen and read from the copied table; a recomputation from the annual rows matches all 50. S4 exclusions: none.
- S3: PASS 50 / FAIL 0.
  - Closed-year checks: PASS 50.
  - Open-year checks: PASS 50.
  - Label uniqueness: PASS 50.
  - Every not-yet-due row that is present maps uniquely.
- Step 4: PASS 50 / FAIL 0. 587/587 due labels matched (100% for every symbol). Off-by-one findings: 0.
- H2-eligible, all 50: AAPL ABBV ADBE AMD AMZN AVGO BA BAC C CAT CMCSA COST CRM CSCO CVX DIS GE GOOGL GS HD HON INTC JNJ JPM KO LLY
  MA MCD META MRK MS MSFT NFLX NKE NVDA ORCL PEP PFE PG QCOM SBUX T TSLA TXN UNH V VZ WFC WMT XOM.
  - This covers due-quarter labels only. H2 still waits for the validator's readback.
- NOT_YET_DUE.tsv has 213 labels.
  - 90 have a quarter-end on or before 2024-12-31, which makes them new exclusions relative to S6. Of these, 50 have a DEV row present (all map uniquely) and 40 have none.
  - 123 have a quarter-end after the edge (these were already outside the S6 denominator).
- Open FY pattern at the edge:
  - m=12 (33 names): FY2024 k=2, Q3 row present.
  - m=9 (5 names): FY2024 k=3 with Q4 row present; FY2025 k=0, no rows.
  - m=6 (MSFT, PG): FY2025 k=0, Q1 row present.
  - m=8 (COST) and m=7 (CSCO): FY2025 k=0, Q1 row present.
  - m=5 (NKE, ORCL): FY2025 k=1, Q2 present.
  - m=1 (CRM, HD, NVDA, WMT): FY2025 k=2, Q3 present.
  - m=11 (ADBE) and m=10 (AVGO): FY2024 k=3, Q4 present.

## The 7 off-by-one flags from S6, re-evaluated (not waived)
- AAPL, DIS, QCOM, SBUX, V (m=9): CLEARED.
  - In S6 the flag was on label 2025Q1 (quarter-end 2024-12-31, no row) plus "more valid shifted": −1 gave 14 against 13 end-year.
  - Under the erratum, 2025Q1 is due 2025-04-10 and 2024Q4 (2024-09-30) is due 2025-01-08. Both are now not yet due and excluded.
  - The remaining 12 due labels match end-year 12/12. The −1 shift gives 12 (not more) and the +1 shift gives 8.
- MSFT, PG (m=6): CLEARED.
  - In S6 the flags were on 2025Q1 (2024-09-30) and 2025Q2 (2024-12-31), plus −1 giving 15 against 13.
  - Under the erratum, both labels are not yet due (2025-01-08 and 2025-04-10) and are excluded.
  - The remaining 13 due labels match end-year 13/13. The −1 shift gives 13 (not more) and the +1 shift gives 9.
- Reason in every case: each flag sat on a quarter the erratum now defines as not yet due. No due label fails end-year, and no shift produces more valid matches. A label-year error would show up here, and none does.

## COST row (S5, unchanged)
- The only DEV row with reportedDate earlier than fiscalDateEnding is COST m=8: fiscalDateEnding 2020-05-31, reportedDate 2020-05-28, post-market, a lag of −3 d.
  - It sits in COST FY2020, outside the label window and the S3 scope (FY2021+), so it is never mapped.
- COST passes: closed FY2021–FY2024; FY2025 k=0 with the Q1 row 2024-11-30 present and unique; step 4 13/13.

## Changes from S6
1. S3: closed means all 4 quarters are due (quarter-end + 100 d <= EDGE), replacing "annual row <= edge". The open-FY k counts due quarters, replacing "quarter-end <= edge".
   - Due quarters need exactly 1 row each with a lag of 0 to 100. Not-yet-due rows need to be unique only.
   - Row-to-quarter assignment in open FYs uses date windows instead of position.
2. S4 denominator: due-quarter labels only (587 labels), replacing "quarter-end <= 2024-12-31" (677 in S6). 90 labels moved into NOT_YET_DUE.
3. A new NOT_YET_DUE.tsv lists all 213 not-yet-due labels in the window.
4. S2 months are read from the copied FYE_MONTH_FROZEN.tsv and checked against the recomputation, instead of being rewritten.
5. EDGE is now a parameter, with a guard that refuses any edge after the DEV edge. The shift test returns not_due for not-yet-due shifted quarters.
6. Results: S3 went from 10 PASS / 40 FAIL to 50/0. Step 4 went from 10/40 to 50/0. H2-eligible went from 10 to 50.

## Points for the validator (nothing re-mapped or filled)
- Because of the 100 d bound, the m=12 2024Q3 labels (quarter-end 2024-09-30, calls reported Oct–Nov 2024 inside DEV, row present) are not yet due and excluded from DEV H2. That is 33 labels, plus similar ones for other months (50 present-row labels in total).
  - This follows the rule as written and is conservative, not a data problem.
- "Quarter-end" is taken as the nominal month-end, so the due test depends on dates only.
  - For 52/53-week filers (AAPL, COST and others), the actual period end differs by a few days. With this edge, no quarter changes due status either way (nominal Sep 30 and actual about Sep 28 are both after 2024-09-22; COST Q4 about Sep 1 and nominal Aug 31 are both due).
- The off-by-one test only flags when end-year matching fails. In fully reported years, −1 shifted labels also find rows (an equal count), so "cleared" means no evidence of a label-year error, not positive proof.
