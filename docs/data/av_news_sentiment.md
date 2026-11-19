# Alpha Vantage news sentiment + earnings-call transcripts (for the sentiment researcher) - RAW layer
Built by the data engineer (Data Engineer), 10-11 Nov 2026 SGT. Assigned by the fund manager; pull approved by the desk head 22:39 SGT 10 Nov.
Status: RAW, sealed, pending the fund manager's inspection. Not yet released to the sentiment researcher. A separate clean/ layer will follow the fund manager's
cleaning decisions, with every rule and dropped row in CLEANING.md; raw/ stays untouched.

## Contents
- raw/news/<SYM>/<YYYY-MM>.json            NEWS_SENTIMENT, one calendar month, limit=1000, sort=EARLIEST (52 symbols x 56 months, 2022-03..2026-10)
- raw/news/<SYM>/<YYYY-MM>.h1.json|.h2.json half-month re-pulls where the month hit 1000 items (days 1-15, 16-end)
- raw/news/<SYM>/<YYYY-MM>.hNw1.json|.hNw2.json weekly re-pulls where a half hit 1000 (1-7, 8-15, 16-23, 24-end)
- raw/transcripts/<SYM>/<YYYYQn>.json      EARNINGS_CALL_TRANSCRIPT (50 stocks x 67 quarters, 2010Q1..2026Q3)
- *.attemptN.json                           retry attempts; the accepted file for each request is the row marked OK in CALLS.log
- CALLS.log  one tab-separated row per attempt: utc_ts, run, kind(PRIMARY/SPLIT), attempt, endpoint, params (no key),
             http_status, bytes, sha256, outcome, holdout_flag, file. Also MISSING / NOT_ATTEMPTED / SPLIT_CAP_REACHED rows.
- VALIDATION.md, validation_news.tsv, validation_transcripts.tsv  metadata-only checks
- PLAN.md (approved plan), fetch_av.py (R1, R5), fetch_av2.py (R1b, R2a..R7, R8), fetch_av2_r8b.py (R8b), run_chain.sh, validate.py
- RUN_<run>.started / .done markers, SHA256SUMS
Effective news set per month: weekly files if present for a half, else the half file, else the month file (validate.py logic).
Universe: AAPL MSFT NVDA AMZN GOOGL META TSLA JPM V MA UNH JNJ XOM CVX PG HD LLY ABBV MRK PFE KO PEP COST WMT BAC WFC GS MS C
AVGO ORCL CSCO ADBE CRM AMD INTC QCOM TXN NFLX DIS CMCSA T VZ NKE MCD SBUX BA CAT GE HON, plus SPY QQQ (news only).

## Totals
6,796 request attempts: 6,790 OK, 6 ERROR (all recovered on retry), 2 MISSING after 2 retries. 530 split calls (cap 800).
News: 2,912 symbol-months, all with an accepted file. Transcripts: 3,348 accepted of 3,350.

## Fields touched by validation (fund manager decision B, metadata only)
News: top-level 'feed' (list present, length), per item 'url' and 'time_published'. Transcripts: 'symbol', 'quarter',
'transcript' (entry count, and character count of each entry's 'content' summed; text never printed or stored).
Raw-byte checks: size, sha256, substring test for "Information" / "Note" / "Error Message" on bodies < 4 KB (decision C).
Never read: sentiment scores, relevance scores, transcript text, prices. No returns or signals computed.

## Known limits
1. Survivorship bias: universe picked on 10 Nov 2026 from my own knowledge of today's large caps.
2. Start dates (news 2022-03-01, transcripts 2010Q1) were from my knowledge, not verified in advance; observed news
   time_published starts 2022-03-01 for most symbols, consistent with that.
3. 32 weekly windows still at the 1000-item cap (truncated), logged SPLIT_CAP_REACHED:weekly_full, mostly Oct 2025 bank /
   mega-cap earnings weeks; JPM 14, NVDA 6, MSFT 2, MS 2, ORCL 2, AMD/AMZN/BAC/C/GS/WFC 1 each. Listed in VALIDATION.md.
4. Missing transcripts: LLY 2012Q4, AMD 2014Q3 (MISSING after 2 retries).
5. Empty transcripts (valid reply, no entries): 98 across symbols. Expected pre-listing gaps: META 2010Q1-2012Q1 (FB IPO May 2012),
   ABBV 2010-2012 (listed Jan 2013), TSLA 2010. Unexplained and worth inspecting: UNH 12 empty, WMT 6, others 1-3.
   The predicted FB->META ticker gap did not appear beyond the pre-IPO quarters.
6. ETFs: QQQ has 22 zero-item months and SPY 7; ETF news coverage is sparse. CAT 2023-08 is zero-item too.
7. DIS 2025-07 news reply has no 'feed' key; its bytes are identical to VZ 2026Q2 transcript reply (tiny generic body).
   Flagged for inspection; not re-pulled.
8. Duplicate sha groups (3): NVDA 2026-02 month == its h1 (expected with sort=EARLIEST when h1 alone exceeds 1000);
   the empty-feed replies (CAT 2023-08, five SPY months); DIS/VZ above.
9. Quarter labels are AV's; holdout flag in CALLS.log is by label (2016Q1+ = holdout) and is informational only.

## Deviations (self-reported)
- Medium: run_chain.sh (one background shell sequencing runs) was killed silently ~23:57 SGT 10 Nov after R2a; violated rule 6.
  Remaining runs restarted as fresh workers <= 35 min each. No calls lost or duplicated.
- Low: R8 process was killed at 04:56:32Z 11 Nov after 490/804 items (last OK SBUX 2015Q1; no .done). Remainder fetched by a
  fresh split run R8b (fetch_av2_r8b.py, 314/314 OK, orphan files 0). R8 is not counted as resumed.
- Low: news runs 2-4 split into R2a..R4b; R1b added for weekly re-splits of R1 halves (fund-manager-approved budget).
