# PRE-REGISTRATION DRAFT v5 — Sentiment-to-returns test on AV news + earnings-call transcripts
Author: Ethan (Equity & Sentiment). Drafted 2026-11-11 SGT for Victor (Signal Validation Lead) delta readback, via Jeremy.
Supersedes: PREREG_DRAFT_v4.md (sha 4f6dce8b…621a, kept unchanged), v3 (5f531a75…667b), v2 (75b3736e…17f5) and
v1 (e1f9ee2b…9d7e), all kept unchanged. Standalone document; changes listed item by item in CHANGES_v4_to_v5.md (A1–A6).
Status: **DESIGN ONLY. DRAFT for delta readback, then seal. Not sent. No data analysed, no returns loaded, no backtest run,
no results exist.**
§0 carries Victor's sealed boundary ruling incl. the Q15 straddle ruling (binding). §0R carries Victor's full review of v4
(verdict AMEND to v5; amendments A1–A6, binding). §4A adds data-handling notes from Marcus's RELEASE_NOTES.md.
No open questions remain (§9).

## 0. HOLDOUT BOUNDARY — RULED (Victor, Q6)
**Source:** `$QR_DESK_DIR/validation/prereg_rulings/2026-11-11-ethan-sentiment-returns-boundary-ruling.md`,
sha256 `0f2713def385f754cf2393ff7608c9d9713214a0355a35d483c692f1c8cf8ee1` (verified 2026-11-11 SGT, read in full, 13 lines;
ruled on v1 sha e1f9ee2b). Logged as row **L286** in `$QR_DESK_DIR/validation/verdicts-log.md`, per Victor (the log was
not opened by Ethan; cited as Victor stated it). Where a relay and the ruling file differ, the file governs (see
CHANGES_v2_to_v3.md §D). The Q15 straddle ruling (B8) is cited to the same ruling file and log row, per Victor.
- **B1 Boundary (one date for H1a, H1b, H2):** DEV = closes and events dated **≤ 2024-12-31**. HOLDOUT = dated
  **2025-01-01 .. 2026-10-31** (first HOLDOUT session 2025-01-02; last session in the returns pull 2026-10-30).
- **B2 Returns rule:** a daily return belongs to the partition of its **END close**. close(2024-12-31)→close(2025-01-02) is
  HOLDOUT. HOLDOUT rows may use DEV closes (beta warm-up, first return); DEV never uses a close dated 2025-01-01 or later.
- **B3 DEV purge:** a DEV observation counts only if its whole target window ends on or before the 2024-12-31 close.
  Purged observations are dropped from DEV and counted. **They are not added to HOLDOUT (ruled, B8 / Q15).**
- **B4 H2 boundary = 2025-01-01** (the 2016-06-01 alternative in v2 is **removed**: 2016-06-01 is the SPY/QQQ condor holdout,
  not a desk-wide rule, and returns start 2021-03-01). H2 DEV = calls with full return windows inside 2021-03-01..2024-12-31
  **after a 252-session beta warm-up**.
- **B5 Events** (EARNINGS reportedDate or any dated row) are partitioned by their own date on the same boundary.
- **B6 Release:** Marcus partitions `$QR_DATA_DIR/av_returns_events_20261111/` on B1/B2. HOLDOUT is hashed and counted
  from raw bytes only until the single pre-registered OOS run. **DEV release to Ethan is not before this prereg is sealed by
  Victor.** Marcus reports per partition: SUMS sha, row counts, max DEV date, min HOLDOUT date.
- **B7 Capped months:** all 22 capped_incomplete symbol-months fall in 2025-10..2026-08, inside HOLDOUT, and HOLDOUT carries
  heavier news coverage. Disclosed here and handled by §3; **not a reason to move the boundary.**
- **B8 Straddling observations — RULED (Victor, Q15).** Observations whose signal is DEV-dated but whose target window runs
  past the 2024-12-31 close are **dropped from BOTH partitions**.
  - **OOS membership is defined by signal date, not return date:** H1a/H1b OOS = decision dates **≥ 2025-01-01** (first
    H1b decision 2025-01-02, first H1a decision 2025-01-03). H2 OOS = events whose **report date ≥ 2025-01-01**.
  - A December 2024 decision or call carries a DEV-period signal, so it is **not holdout**. This includes an EARNINGS row
    reported 2024-12-31 post-market (or with missing/unknown reportTime, defaulted to post-market per §2) whose day 0 is
    2025-01-02: it is **purged from DEV and not added to HOLDOUT**.
  - **H2 partition key = REPORT date and session**, as given by `reportedDate`/`reportTime` (B5). An event whose reportedDate
    is in 2024 is **never OOS**, even if its day 0 falls in 2025.
  - **B2 assigns where a return's DATA sits; it does not move observations into HOLDOUT.** A HOLDOUT observation may use DEV
    closes (B2); a DEV-signal observation never becomes HOLDOUT because its return is HOLDOUT-dated.
  - Dropped counts (both partitions): **H1a 1 decision date (2024-12-27; ≤ 50 symbol-obs). H1b 1 decision date
    (2024-12-31; ≤ 50 symbol-obs). H2: every event with reportedDate ≤ 2024-12-31 and day 0 in 2024-12-02..2024-12-31,
    plus any 2024-reported event whose day 0 is in 2025 (only 2024-12-31 post-market/unknown → day 0 2025-01-02)**;
    the exact H2 count is fixed when DEV EARNINGS is released and is reported then.

**Boundary checks and purge counts** (XNYS, exchange_calendars 4.13.2 via `$QR_DATA_DIR/.venv/bin/python`; sessions
2021-03-01..2026-10-31; metadata from `coverage_transcripts.tsv` status column only; no scores, text, prices or returns read):
| Hypothesis | DEV decision dates/events (2022-03-01..2024-12-31) | Purged at boundary | Max symbol-obs purged | Last kept DEV |
|---|---|---|---|---|
| H1a weekly | 148 decision sessions (2022-03-04..2024-12-27) | **1**: 2024-12-27 (return → close 2025-01-03) | **50** (1 × 50) | 2024-12-20 (return → close 2024-12-27) |
| H1b daily | 714 decision sessions (2022-03-01..2024-12-31) | **1**: 2024-12-31 (return → close 2025-01-02) | **50** (1 × 50) | 2024-12-30 (return → close 2024-12-31) |
| H2 events | day 0 2022-03-01..2024-12-31 | every DEV call with day 0 in 2024-12-02..2024-12-31 (21 sessions) | count fixed at EARNINGS release | day 0 2024-11-29 (+21 = 2024-12-31) |
- Per B8, every "purged" row in this table is dropped from BOTH DEV and HOLDOUT.
- Victor's "last H1b session 2024-12-30" is consistent with v2's "decision 2024-12-31 dropped": 2024-12-30's return ends at the
  2024-12-31 close (kept); 2024-12-31's ends at the 2025-01-02 close (HOLDOUT under B2 → purged from DEV).
- H1a: v2's dropped week (decision 2024-12-27) is confirmed. The last kept H1a decision is **2024-12-20**, whose return ends at
  the 2024-12-27 close (B3: "next decision session on or before 2024-12-31"). The week of 2024-12-30 has decision session
  2025-01-03 (first HOLDOUT H1a decision).
- Separately (coverage, not boundary), the first H1 window of each kind starts before 2022-03-01 and is dropped as in v2:
  H1a 2022-03-04 (window from 15:30 ET 2022-02-25), H1b 2022-03-01 (window from 15:30 ET 2022-02-28). Usable-maximum DEV
  therefore: **H1a 146 dates × 50 = 7,300 symbol-obs; H1b 712 dates × 50 = 35,600 symbol-obs.**
- **Realized counts** after the relevance filter, minimum-item filters (3/week, 2/day), coverage=0/capped exclusions and the
  ≥ 20-name cross-section rule are computed at run time and reported; the figures above are calendar maxima only.
- Beta warm-up never binds in H1 DEV: the first H1b decision (2022-03-01) has exactly 252 daily returns ending t−1
  (2021-03-02..2022-02-28); H1a's first (2022-03-04) has 255.

**H2 DEV count (restated; ESTIMATE, bounded by fiscal-calendar uncertainty).**
- Eligible day-0 window: **first = 2022-03-01** (first session with 252 daily returns ending day 0 − 1, returns starting with
  the 2021-03-01→03-02 return); **last = 2024-11-29** (session +21 = 2024-12-31). The corresponding reportedDate window is
  R = [2022-02-28 (post-market → day 0 2022-03-01), 2024-11-29 (pre-market)].
- Tone-surprise baseline: ≥ 2 prior available calls per symbol. Every transcript present from 2021Q3 onward has ≥ 2 prior
  present labels (transcripts run from 2010Q1; the only missing labels near the window are WMT 2020Q1–Q3, which do not bind).
- **Rule (upper bound, stated exactly):** count a transcript (status present or present_repulled) with label YYYYQn as
  DEV-eligible if, under the end-year convention (§2, Q10), for SOME fiscal-year-end month m ∈ {Jan..Dec} of year YYYY, the
  quarter-end E(m) = month-end of (m − 3·(4 − n)) satisfies [E(m) − 7 d, E(m) + 107 d] ∩ R ≠ ∅ (0..100-day report lag from
  §2 mapping step 3, ±7 d for 52/53-week years), and the symbol has ≥ 2 earlier present labels.
  → **Upper bound = 800 transcripts** (labels 2021Q4..2025Q3, 16 labels × 50).
- Calendar-fiscal-year illustration (m = Dec for all names; [E, E+100 d] ∩ R ≠ ∅): 600 (2021Q4..2024Q3, 12 × 50); since
  calendar 2021Q4 reports fall mostly before 2022-02-28, the central expectation is ≈ **11 calendar quarters × 50 ≈ 550**,
  i.e. roughly fiscal 2022Q1..2024Q3.
- Window-certain count (plausible window inside R for every m): 300 (2023Q1..2024Q2) — a floor before mapping failures only.
- **The exact H2 DEV count is fixed only when EARNINGS reportedDate/reportTime is released (after sealing, B6)**: day 0 per §2,
  eligible iff 2022-03-01 ≤ day 0 ≤ 2024-11-29, unique valid transcript match, tone and baseline non-missing. Purged
  (day 0 2024-12-02..2024-12-31) and unmatched counts are reported then.
- Implication: v2's "≈ 2021Q2..2024Q3, ~14 quarters × 50 (~700)" is restated to **≈ 2022Q1..2024Q3, ~11 quarters × 50
  (~550)** because of B4's 252-session warm-up (with a 200-session minimum it would start ≈ 2021Q4: ~12 × 50).
- **H2 is thin — RESOLVED by A5 (§0R): H2 is pre-registered EXPLORATORY, outside the confirmatory family.** H2 cross-sections are calendar quarters of day 0 with ≥ 20 events: DEV ≈ 11
  scorable quarters (2022Q2..2024Q4; 2022Q1 has March only and is likely < 20 events), OOS = reportedDate ≥ 2025-01-01
  (B8), day 0 2025-01-02..2026-10-01 ≈ 7 quarters (2025Q1..2026Q3). With per-quarter IC s.d. ≈ 0.14, a one-sided Holm-level test on 7 OOS quarters needs mean IC
  of roughly 0.11–0.14 under v4's N = 3 Holm (≈ 0.10 at a nominal one-sided 0.05, Student t df = 6), and the "OOS ≥ 50% of
  DEV mean IC" comparison rests on ~11 DEV quarters. H2 is close to unpowered, so under A5 it can never PASS and is reported
  in full as exploratory only.

**File-opening rule (until Victor seals the prereg):** no HOLDOUT-period news, transcript or returns file is opened.
- News: no month file 2025-01 or later is opened. DEV signals never need one: the latest DEV cutoff is 15:30 ET 2024-12-30
  (H1b) / 2024-12-20 (H1a), earlier than any 2025-01 item under both the UTC and the ET reading (both are gate readings, A3).
- Transcripts: labels are FISCAL quarters, so the label alone does not decide the side of the boundary. Each transcript is
  first mapped to its day 0 from EARNINGS metadata only (§2.H2); only transcripts mapped to DEV day 0 (≤ 2024-11-29 for
  scoring; earlier ones as baselines) may be opened before the OOS run. Unmatched transcripts with label ≥ 2024Q3 are not
  opened. Since EARNINGS is released only after sealing (B6), no transcript is opened before sealing (Q14).
- Returns and EARNINGS: Ethan receives only the DEV partition, after sealing (B6); HOLDOUT is not released before the OOS run.
- **DEV-stats freeze (A2):** before ANY HOLDOUT file (news ≥ 2025-01, OOS-mapped transcripts, HOLDOUT returns or EARNINGS)
  is opened, the DEV statistics — mean IC, NW t, Student-t p and number of scored periods, per hypothesis (H1a, H1b, and
  exploratory H2) and per timestamp reading (UTC and ET, A3) — are written to a file in this folder, chmod 0444, and its
  sha256 is logged with Victor. That file is frozen; nothing in it is recomputed after HOLDOUT is opened.
After sealing, HOLDOUT files are opened once, only for the single pre-registered OOS run. DEV may be used to check plumbing
only; thresholds below are not tuned on DEV.

## 0R. FULL REVIEW OF v4 — RULED (Victor)
**Source:** `$QR_DESK_DIR/validation/prereg_rulings/2026-11-11-ethan-sentiment-returns-v4-full-review.md`,
sha256 `2ef504b769f76e2670852ca3977e3bc85bc61ab7f08e1046b4c7b4de37dbdbaf` (verified 2026-11-11 SGT, read in full, 21 lines; reviewed v4 sha 4f6dce8b and
CHANGES_v3_to_v4.md 9234b0c2). Logged as row **L291** in `$QR_DESK_DIR/validation/verdicts-log.md`, per Victor (the log was
not opened by Ethan; cited as Victor stated it). Where a relay and the ruling file differ, the file governs.
- **Verdict:** AMEND to v5; seal after a delta readback of A1–A6. B6 holds: no DEV release before the seal.
- **Accepted as written:** B8 straddle text (§0); §4A expected DEV counts (agree with Marcus's attested split, row L290 per
  Victor); disclosure of Jeremy's data limits (§2, §4, §4A, §6, §7); adjusted_close ratios only, no winsorizing; Q10, Q12, Q14.
- **A1** long-short legs k = floor(n/5); p from Student t, df = scored periods − 1 (§5). Thresholds accepted (§2, §5).
- **A2** DEV-sign gate: DEV mean IC ≤ 0 → FAIL; DEV stats frozen 0444 and sha-logged with Victor before any HOLDOUT open (§0, §5).
- **A3** R-TZ promoted to a conjunctive gate: PASS requires every criterion under BOTH the UTC and ET readings; N unchanged (§2, §5, §6).
- **A4** R-TZ materiality with an absolute floor 0.01 (§2, §6).
- **A5** confirmatory N = 2 (H1a primary, H1b), Holm 0.05 one-sided; H2 pre-registered EXPLORATORY, never PASS (§0, §2, §5).
- **A6** missing transcripts not assumed missing-at-random; metadata table in §3A and MISSING_TRANSCRIPTS_A6.tsv (§3, §3A, §5).
- INFO carried: §8 "no results to Daniel until Victor validates" stands; no trading; survivorship upper-bound caveat stands (§7).

## 1. Data under test (sealed, read-only)
- Path: `$QR_DATA_DIR/av_sentiment_20261110/clean/` — SHA256SUMS `ed284d37…2834` (6,184 entries), CLEANING.md `c14ef3d5…dab9`.
  Verified 2026-11-11 SGT: both shas match; `sha256sum -c SHA256SUMS` from clean/ = 6,184 OK / 0 FAILED (see VERIFY_LOG.txt).
- Universe: 52 symbols = 50 US large caps + SPY + QQQ (ETFs news-only). Survivorship-biased (picked 10 Nov 2026 with today's knowledge).
- News: `news/<SYM>/<YYYY-MM>.json`, 2022-03..2026-10 (56 months), 2,912 symbol-months, 588,198 items. Flags: ok 2,859,
  ok_repulled 1 (DIS 2025-07), **capped_incomplete 22** (all in 2025-10..2026-08, inside the HOLDOUT, ruling B7;
  JPM 7, NVDA 5, ORCL 2, AMD/AMZN/BAC/C/GS/MS/MSFT/WFC 1 each), **coverage=0 30** (QQQ 22, SPY 7, CAT 2023-08).
  Stock symbol-months: median 37 items/month (~8–9/week), 698 of 2,800 have <20 items (metadata from coverage_news.tsv).
- Transcripts: `transcripts/<SYM>/<YYYYQn>.json`, labels 2010Q1..2026Q3 (AV FISCAL quarters, "YYYYQM" per AV docs),
  50 stocks × 67 labels = 3,350 slots: 3,266 present, **84 missing** (82 empty replies: 25 expected pre-listing,
  19 unexplained, 38 unannotated; 2 error: LLY 2012Q4, AMD 2014Q3). Missing = missing, not zero.
- Schema (keys/types only; values never read). News item: `time_published` (str), `ticker_sentiment[]` {`ticker`,
  `relevance_score` (str), `ticker_sentiment_score` (str), `ticker_sentiment_label`}, plus `overall_sentiment_score`, `topics[]`,
  title/summary/source fields. Transcript: `symbol`, `quarter`, `transcript[]` {`speaker`, `title`, `content`, `sentiment` (str)}.
  **Transcript files carry no call date/time field** — only AV's fiscal-quarter label.
- Pull dates: every news/transcript file was pulled 10–11 Nov 2026 (Marcus, CALLS.log).
- Reads so far: CLEANING.md, README.md, SHA256SUMS, the three metadata TSVs, _counts.json, and key names of
  news/AAPL/2022-03.json and transcripts/AAPL/2022Q1.json. No scores, relevance values, text, prices or returns read.
- Companion datasets (pulled by Marcus, sealed, not yet released; pinned in §4): returns, EARNINGS, OVERVIEW.

## 2. Hypotheses (confirmatory N = 2, ruling A5) and signal construction (fixed in advance)
- **H1a (primary, confirmatory):** Weekly cross-sectional news sentiment predicts next-week beta-adjusted returns (positive rank IC).
- **H1b (secondary, confirmatory):** Daily cross-sectional news sentiment predicts next-day beta-adjusted returns (positive rank IC).
- **H2 (PRE-REGISTERED EXPLORATORY, A5):** Earnings-call tone surprise predicts post-event drift (sessions +2..+21) in
  beta-adjusted returns. Same specification as below, run once in the same single OOS run and reported in full, but it can
  **never PASS and never counts toward N**. Every H2 output is labelled "exploratory — not a confirmatory test".
- No time-series (single-name timing) variant, no SPY/QQQ market-timing variant, no parameter sweeps. Anything else = new prereg.

**Item filter (H1).** For symbol i, keep a news item only if `ticker_sentiment` contains an entry with `ticker == i` and
`relevance_score ≥ 0.50` (parsed as float). Item score s = that entry's `ticker_sentiment_score` (float). `overall_sentiment_score`
is NOT used. Unparseable values → item dropped (logged, counted).
**Timestamps (resolved Q1 as an assumption).** `time_published` is `YYYYMMDDTHHMMSS`. Its timezone is NOT documented by AV; the
only zone in AV's NEWS_SENTIMENT docs is the `time_from` request example ("1:30am UTC"), so **UTC is inferred, UNCONFIRMED**.
- **UTC reading:** parse as UTC, convert to America/New_York with zoneinfo (DST-aware), then apply the cutoffs below.
- **ET reading:** interpret the nominal `time_published` as America/New_York wall-clock (zoneinfo, DST-aware; each item's
  instant is 4h (EDT) / 5h (EST) later than under the UTC reading), with the identical cutoff, window, minimum-count and
  missing-data rules.
- **Look-ahead direction (A3).** If AV's stamps are really ET, the UTC reading places each item 4–5h EARLIER than it
  happened and can leak after-cutoff news into a window. The ET reading places items at or later than their true time under
  either truth, so it is the look-ahead-safe reading.
- **R-TZ is a CONJUNCTIVE GATE (A3).** Every statistic (DEV and OOS, H1a, H1b and exploratory H2) is computed under BOTH
  readings. A confirmatory hypothesis PASSes only if it meets EVERY PASS criterion of §5 under the UTC reading AND under the
  ET reading, each reading compared against its own frozen DEV stats. Both are reported. **N is unchanged** (same
  hypothesis, stricter test). The UTC reading remains the reference ("primary") for the A4 materiality report only.
- **R-TZ materiality (A4), reported as well as gated:** material = a sign flip in mean IC between readings, or
  |ΔIC| ≥ max(50% of |primary (UTC) mean IC|, 0.01), or the one-sided p crossing 0.05. Reported per hypothesis, DEV and OOS.
Trading sessions from exchange_calendars 4.13.2 XNYS (same pin as the sentiment check), not a hand list.
**Cutoff (anti-lookahead).** Signal for decision session t uses items with ET timestamp ≤ 15:30 ET on session t
(and > 15:30 ET on the previous decision session); position is taken at the session-t close; 30-min buffer.
- H1b daily: window (15:30 ET on t−1, 15:30 ET on t]; return = close(t) → close(t+1). Weekends/holidays roll into next session's window.
- H1a weekly: decision session = last XNYS session of each week; window = the 5-session span ending 15:30 ET on that session;
  return = close(decision) → close(next week's decision session).
**Aggregate.** S(i,window) = relevance-weighted mean of s over kept items (weights = relevance_score).
**Minimum counts.** H1a: ≥ 3 kept items per symbol-week; H1b: ≥ 2 per symbol-day. Below minimum → missing (not 0, not neutral).
A cross-section is scored only if ≥ 20 stocks qualify; otherwise the period is dropped and counted. (So k = floor(n/5) ≥ 4, §5.)

**H2 tone.** Pre-fixed scoring = AV's own per-entry `sentiment` field; no custom NLP, no reading of `content`.
Call tone T(i,q) = mean of float-parseable `sentiment` over all entries; require ≥ 10 parseable entries else missing.
Tone surprise = T(i,q) − mean of the symbol's previous 4 available calls (needs ≥ 2 prior calls, else missing); "previous" is
ordered by mapped day 0; unmatched or missing transcripts are not prior calls.
**H2 event date — PROXY (resolved Q3).** Source: AV EARNINGS (pulled by Marcus) `quarterlyEarnings` rows: `fiscalDateEnding`,
`reportedDate`, `reportTime`. **Disclosure: reportedDate + reportTime is a PROXY for the call time, not a verified call
timestamp**; a call held on a different session than the report would be misdated. Stated on every H2 output.
- **Day 0:** reportTime = pre-market → day 0 = the reportedDate session. reportTime = post-market → day 0 = the next XNYS
  session after reportedDate. If reportedDate is not an XNYS session, day 0 = the next XNYS session.
- **Missing/unknown reportTime rule (chosen): treat conservatively as post-market** — day 0 = next XNYS session after
  reportedDate. This applies to empty, null, unparseable or any value other than "pre-market"/"post-market" (incl. intra-day).
  Rationale: it can only date the event later than truth, never earlier, so it cannot introduce look-ahead; with the +2
  skip the worst case is a one-session lag. Count reported; a sensitivity excluding these events is reported (not pass/fail).
- Return window: sessions +2..+21 relative to day 0 (skips the announcement jump on day 0/+1).
- Cross-section = all events with day 0 in the same calendar quarter (≥ 20 events, else dropped and counted).
**Transcript → event mapping (FISCAL labels).** AV labels transcripts by fiscal quarter. Non-calendar fiscal years include
WMT, HD, NVDA, AAPL, MSFT, CSCO, ORCL and others, so label ≠ calendar quarter. Mapping, from EARNINGS metadata only:
1. Fiscal years per symbol from `annualEarnings.fiscalDateEnding` (point-in-time history, not the current OVERVIEW snapshot).
   Fiscal year Y = the fiscal year whose annual fiscalDateEnding falls in calendar year Y (end-year convention; see Q10).
   **Stated ASSUMPTION (Q10, resolved-as-assumption):** AV does not document its fiscal-year label convention (docs say only
   "Fiscal quarter in YYYYQM format" for transcripts and define `fiscalDateEnding` as a date; Marcus, 11 Nov). This prereg
   ASSUMES the label year is the calendar year in which the fiscal year ENDS (e.g. NVDA FY2025 = year ending Jan 2025).
   The assumption is tested by the DEV-only diagnostic in step 4 before any OOS run; it is not silently corrected.
2. Quarters Q1..Q4 of fiscal year Y = the `quarterlyEarnings` rows with fiscalDateEnding in (end of FY Y−1, end of FY Y],
   ordered by date; exactly 4 rows required, and Q4's fiscalDateEnding must be within ±7 days of the annual end (52/53-week years).
3. Transcript label YYYYQn is matched to that row. A match is valid only if it is **unique** (exactly one row) and the row's
   reportedDate lies within 0..100 calendar days after fiscalDateEnding. **No unique valid match → transcript excluded**
   (counted, by reason). No calendar-quarter fallback.
4. **Pre-OOS fiscal-label diagnostic (DEV only, metadata only — EARNINGS DEV rows and transcript file NAMES/labels; no
   transcript content).** For each symbol, over DEV-eligible labels:
   a. each transcript label YYYYQn must map to **exactly one** `quarterlyEarnings.fiscalDateEnding` under steps 1–3;
   b. **off-by-one-year check** for every non-December fiscal-year name (e.g. WMT, HD, NVDA, AAPL, MSFT, CSCO, ORCL and any
      other whose annual fiscalDateEnding month ≠ Dec): re-run the mapping with label year shifted −1 and +1; if a shifted
      mapping yields a unique valid match (0..100-day report lag) where the end-year mapping does not, or yields more valid
      matches, that is an off-by-one-year finding;
   c. per-symbol match rate = uniquely, validly matched labels / present labels in the DEV window.
   **Any symbol that fails (a) or (b), or has a match rate < 90%, is reported to Victor before any OOS run**, with the
   counts by reason. Nothing is re-mapped, re-labelled or fixed without Victor's ruling; the OOS run waits for it.

## 3. Missing-data rules
- coverage=0 months: symbol excluded from every window overlapping that month. Never 0 or neutral.
- capped_incomplete: symbol excluded from every window overlapping a listed capped weekly window (truncated, sort=EARLIEST,
  so late-window items are missing). Rest of that month usable. Exclusions counted and reported. (All 22 are in the holdout.)
- Below-minimum windows, unparseable values, and stocks with no relevant items: missing, not zero.
- Missing transcripts (84) and unmatched transcripts: excluded; no imputation; not prior calls for the surprise baseline.
  **Not assumed missing-at-random (A6):** the missingness is tabulated from metadata in §3A. Because H2 is exploratory (A5),
  no exclusion or imputation change is made; every H2 output states the count of missing transcripts per window, and
  exploratory H2 is reported alongside the §3A table.
- EARNINGS rows with missing reportedDate: event excluded (counted). Missing reportTime: §2 rule (post-market).
- No forward-fill of sentiment across windows. Any symbol-period missing returns → excluded from that cross-section.

## 3A. Missing-transcript table (A6; metadata only)
Source: `$QR_DATA_DIR/av_sentiment_20261110/clean/coverage_transcripts.tsv` (already read; columns symbol, quarter,
status, entries, source_file; status column used). No new file opened; no transcript, score or text read. Full per-label list:
`MISSING_TRANSCRIPTS_A6.tsv` in this folder. Window = H2 DEV-eligible label window **2021Q4..2025Q3** (§0, 16 labels × 50).
Status map: missing_empty_unexplained = unexplained, missing_empty = unannotated, missing_empty_expected = pre-listing,
missing_error = error.

| Category | Total | In window 2021Q4..2025Q3 | Before window (≤ 2021Q3) | After window (≥ 2025Q4) |
|---|---|---|---|---|
| unexplained | 19 | 0 | 18 | 1 (HD 2026Q2) |
| unannotated | 38 | 0 | 38 | 0 |
| pre-listing | 25 | 0 | 25 | 0 |
| error | 2 | 0 | 2 (LLY 2012Q4, AMD 2014Q3) | 0 |
| **Total** | **84** | **0** | **83** | **1** |

By symbol (28 symbols with ≥ 1 missing; none in window):
| Symbol | Missing | Categories | Label range |
|---|---|---|---|
| ABBV | 12 | pre-listing 12 | 2010Q1..2012Q4 |
| UNH | 12 | unexplained 12 | 2010Q1..2012Q4 |
| META | 10 | pre-listing 9, unannotated 1 | 2010Q1..2013Q2 |
| WMT | 6 | unexplained 6 | 2010Q1..2020Q3 |
| TSLA | 5 | pre-listing 4, unannotated 1 | 2010Q1..2011Q1 |
| AMD | 4 | unannotated 3, error 1 | 2010Q3..2014Q3 |
| C | 3 | unannotated 3 | 2010Q2..2012Q1 |
| CRM | 3 | unannotated 3 | 2010Q1..2011Q3 |
| NKE | 3 | unannotated 3 | 2010Q1..2011Q2 |
| ORCL | 3 | unannotated 3 | 2011Q3..2012Q2 |
| BAC, CSCO, DIS, GE, NVDA | 2 each | unannotated | 2010Q2..2011Q3 |
| AVGO, BA, CMCSA, COST, GOOGL, GS, INTC, JPM, MCD, QCOM, XOM | 1 each | unannotated | 2010Q1..2014Q3 |
| LLY | 1 | error | 2012Q4 |
| HD | 1 | unexplained | 2026Q2 |

Reading of the table (description, not a ruling):
- No missing label falls in the H2 DEV-eligible label window, so missingness does not reduce the H2 DEV sample. It can touch
  the tone-surprise baseline (previous 4 available calls, ≥ 2 required) only through earlier labels; the nearest are WMT
  2020Q1–Q3, which leave ≥ 2 prior present labels for every in-window WMT call (§0).
- 83 of 84 missing labels are 2010Q1..2020Q3, concentrated in ABBV/META/TSLA pre-listing and UNH 2010–2012 (unexplained).
- The one post-window missing label, **HD 2026Q2 (unexplained)**, is on the OOS side; it can affect at most one exploratory
  H2 OOS event and is counted on every H2 OOS output. Whether it maps to an OOS day 0 is decided only by the §2 mapping.
- Handling: excluded (no imputation); exploratory H2 reported alongside this table with missing counts per window.

## 4. Companion datasets (resolved Q2, Q3, Q5 — Jeremy decisions 2026-11-11)
**Returns.** Owner: Marcus (Data Engineer). AV TIME_SERIES_DAILY_ADJUSTED, 50 stocks + SPY, 2021-03..2026-10, adjusted close
(12 months pre-sample for beta warm-up). Root: `$QR_DATA_DIR/av_returns_events_20261111/`. Marcus splits into DEV and
HOLDOUT per ruling B1/B2/B6 (§0). **Ethan receives only the DEV partition, not before Victor seals this prereg (B6) and after
Jeremy's inspection; shas are given on release. No returns are read before then.**
- RETURNS_DEV_PATH: TBD-on-release
- RETURNS_DEV_SHA256SUMS sha256: TBD-on-release
- RETURNS_HOLDOUT_PATH / sha256: TBD-on-release (released only for the single sealed OOS run)
Note: holdout-period beta uses the trailing 252 sessions, which may include DEV-period returns (backward-looking; allowed).
**Earnings events.** Owner: Marcus. AV EARNINGS (reportedDate, reportTime, fiscalDateEnding; annual + quarterly), 50 stocks.
Used for H2 day 0 and transcript mapping (§2) and the H1 earnings-exclusion robustness (§7). Metadata, not returns; still
partitioned by row date (B5); opened only after release, which is after sealing (B6); DEV rows only before the OOS run.
- EARNINGS_PATH: TBD-on-release
- EARNINGS_sha256: TBD-on-release
**Sector map.** Owner: Marcus. AV OVERVIEW `Sector`, `Industry` — **current snapshot (Nov 2026), not point-in-time.**
Robustness only; never used in the primary test or any pass/fail gate. Look-ahead disclosed: today's classification applied
to 2022–2026 (reclassifications and 2026 knowledge leak in).
- OVERVIEW_PATH: TBD-on-release
- OVERVIEW_sha256: TBD-on-release
All three are validated and sealed as desk data by the data owner before use; Ethan verifies shas on receipt and logs them.

## 4A. Data handling (from Marcus's RELEASE_NOTES.md)
Source: `$QR_DATA_DIR/av_returns_events_20261111/RELEASE_NOTES.md`, sha256
`cba5d7c326949bd04526150392b99aac2b89e2c8a0579c0b3c0f9e3af81a8f2c` (prefix cba5d7c3 verified 2026-11-11 SGT; read in full,
10 lines). No other file under that root was opened. Where Marcus's message and the file differ, the file governs.
- **Returns from adjusted_close RATIOS only; price levels are never used.** On the last DEV day adjusted_close ≠ close for
  45 of 51 symbols (adjustment includes later corporate actions); return ratios are unaffected, levels are not.
  r(t) = adjusted_close(t) / adjusted_close(t−1) − 1. `close` and other level fields are not used anywhere in this study.
- **Three non-split moves > 25% are real data and kept:** INTC 2024-08-02, META 2022-02-03, NFLX 2022-04-20 (all DEV-dated).
  **No winsorizing, clipping or trimming of returns** — v3 specifies none, and v4 keeps that. Rank IC (§5) is already robust
  to single extreme returns; the long-short gate uses raw returns.
- **COST EARNINGS row** with reportedDate 2020-05-28 earlier than fiscalDateEnding 2020-05-31: kept and flagged by Marcus;
  it falls outside the 2021-03 DEV price window and the H2 day-0 window, so it never enters H2. It is still visible to the
  §2 mapping as history; a reportedDate before fiscalDateEnding fails the 0..100-day lag rule (step 3) and is counted.
- **Sectors** (`meta/sectors.csv` per the notes): current snapshot with look-ahead; robustness only (R-SECTOR), never a gate.
- **reportedDate is the earnings REPORT date, a proxy for the call date**, not a verified call timestamp (§2).
- **Expected DEV release** (Marcus, 11 Nov message): 51 symbols (50 stocks + SPY), **967 sessions 2021-03-01..2024-12-31**,
  **5,279 DEV EARNINGS rows**, and the sector snapshot. Per the notes, DEV is `partitioned/dev/` (sub-SUMS prefix b835e488)
  and HOLDOUT `partitioned/holdout/` (prefix 483163a4) stays sealed, hashed-only. **Paths and full shas remain
  TBD-on-release**; on receipt Ethan verifies the release against these expected counts and reports any mismatch.
- Note: the four sub-SUMS (raw, dev, holdout, meta) and RELEASE_NOTES.md itself are not listed in the top SHA256SUMS
  (stated in the notes); verification on release uses the sub-SUMS shas Jeremy/Marcus provide.

## 5. Primary metric, test, thresholds (fixed in advance)
- Target: beta-adjusted return r_i − β_i·r_SPY, β_i from OLS on exactly 252 daily returns ending t−1 (full window
  required, per ruling B4; never binds in H1 DEV, defines the H2 DEV start 2022-03-01).
- Metric: per-period Spearman rank IC between signal and next-period target; mean IC; Newey–West t (lags: H1a 4, H1b 5, H2 1).
- **p-value distribution (A1b):** one-sided p (IC > 0) = 1 − F_t(NW t; df = number of scored periods − 1), Student t, per
  hypothesis, per partition, per timestamp reading.
- **Confirmatory family N = 2 (A5): H1a (primary), H1b.** Multiple testing: Holm at family α = 0.05, one-sided (IC > 0),
  applied within each timestamp reading. With 2 tests the smaller p must be < 0.025 and the larger < 0.05. For H1a at the
  calendar maximum of 95 scorable OOS weeks (decisions 2025-01-03..2026-10-23; df = 94) that is NW t ≳ 1.99 (0.025) / 1.66
  (0.05); for H1b at 458 scorable OOS days (df = 457) ≈ 1.97 / 1.65. Realized df are set by realized scored periods.
- **H2 is exploratory (A5):** same spec, same metric and p definition, run once in the same OOS run, reported in full
  (DEV and OOS, both readings, missing-transcript counts per window, §3A); it can never PASS and is not in the Holm family.
  If H2 cannot be run (EARNINGS unusable), this is recorded and reported; N stays 2.
- **DEV-sign gate (A2):** if a confirmatory hypothesis's DEV mean IC ≤ 0 (under either reading, A3), it FAILS outright,
  before and regardless of OOS. It keeps its place in the Holm family with p := 1 (N stays 2, so the other hypothesis is not
  given extra α). Its OOS confirmatory test is not run (no OOS p or gate computed for it). DEV stats are frozen per §0
  (0444, sha-logged with Victor) before any HOLDOUT file is opened.
- **PASS (OOS, per confirmatory hypothesis), required under BOTH the UTC and ET readings (A3):** (i) DEV mean IC > 0 (A2);
  (ii) Holm-adjusted one-sided p < 0.05; (iii) OOS mean IC > 0 and ≥ 50% of the frozen DEV mean IC of the same reading;
  (iv) economic gate: long-short of the **top k and bottom k names, k = floor(n/5)** where n is the number of names in that
  period's scored cross-section (n ≥ 20 ⇒ k ≥ 4; A1a), equal-weight within each leg, net mean return > 0 after costs.
  **FAIL** otherwise; no re-specification after seeing OOS.
- Costs: 10 bps per side (20 bps round trip) on traded weight; turnover measured from actual rebalances. Sensitivity at 20 bps/side
  reported, not used for pass/fail.
- Power note (N = 2, A5): with ~50 names, per-period IC s.d. ≈ 0.14 (assumed); over ≤ 95 OOS weeks, t ≈ 1.99 needs mean IC
  ≈ 0.03 (H1a); H1b over ≤ 458 OOS days needs ≈ 0.013 at the same assumed s.d. H2 (exploratory) has only ~7 OOS quarterly
  cross-sections and would need mean IC ≈ 0.10 at a nominal one-sided 0.05 (df = 6); it is not powered as a confirmatory test.
- Reported regardless of outcome: counts of excluded windows/events by reason (incl. boundary purge (B3/B8, dropped from
  both partitions), fiscal-label diagnostic failures (§2 step 4), unmatched transcripts,
  reportTime-defaulted events, missing transcripts per H2 window per §3A), coverage per period, k per period, DEV and OOS
  stats under both timestamp readings, and the A4 materiality report.

## 6. Robustness checks (pre-registered; not counted in N; never change PASS/FAIL — except R-TZ, which is a gate)
- R-TZ: **promoted to a conjunctive gate (A3, §2, §5)** — not a robustness-only check. Materiality per A4 is also reported.
- R-SECTOR: sector-demeaned IC using the OVERVIEW current-snapshot Sector (look-ahead disclosed).
- R-EARN: H1a/H1b excluding symbol-windows containing an earnings day 0 ±1 session (EARNINGS proxy).
- R-RT: H2 excluding events whose reportTime was missing/unknown.
- Cost sensitivity at 20 bps/side (§5).

## 7. Controls, caveats and stated limitations
- Market beta removed in target. SPY and QQQ excluded from every cross-section (ETFs; sparse news).
- Survivorship: universe chosen with 2026 knowledge → any positive result is an upper bound; stated on every output.
- **Point-in-time limitation (resolved Q4 as a disclosed limitation).** AV does not document whether historical sentiment
  scores/relevance are as-of publication. All files were pulled 10–11 Nov 2026, so scores are whatever AV served then and
  may have been recomputed or backfilled with a later model (model-revision look-ahead possible); article sets may also have
  been back-filled. **All results, DEV and OOS, are interpreted with this caveat** and labelled "not verified point-in-time";
  a PASS is evidence about AV's current scores on past news, not proof a live signal would have existed at the time.
- Timestamp zone UNCONFIRMED (§2, R-TZ). Event time is a PROXY (§2). Sector map is a current snapshot (§4).

## 8. Statements
- **No trading.** No orders, sizing or live use. Research/context only until Victor validates and Jeremy approves next steps.
- No results are reported to Daniel from this study until Victor validates.
- The existing sentiment pre-trade check (MANIFEST_v3 `c347c9a1…`) is separate: it never enters DEV/OOS, never counts toward N,
  and is not modified by this study. This study does not feed the check's news slot.
- Sealed source files are read-only; outputs go only under this folder, sealed 0444 with a manifest. No new data pulls by Ethan.

## 9. Open questions
**None open.** All questions are resolved (Victor's full review, §0R, row L291 per Victor; earlier rulings §0, row L286).
- Q1 RESOLVED (as assumption) — timezone undocumented; UTC inferred (Marcus, 11 Nov). Under A3 both the UTC and ET readings
  are gate readings (§2).
- Q2 RESOLVED — returns: Marcus, AV TIME_SERIES_DAILY_ADJUSTED, `$QR_DATA_DIR/av_returns_events_20261111/`; DEV-only
  release after sealing (B6) and Jeremy's inspection. Paths/shas TBD-on-release (§4).
- Q3 RESOLVED — H2 kept (now exploratory, A5); event = AV EARNINGS reportedDate + reportTime proxy (Jeremy, 11 Nov).
- Q4 RESOLVED (as limitation) — point-in-time undocumented; disclosed §7 (Marcus, 11 Nov).
- Q5 RESOLVED — sector map: AV OVERVIEW current snapshot, robustness only (Jeremy, 11 Nov).
- Q6 RESOLVED — boundary ruled by Victor (ruling 0f2713de…8ee1, row L286): 2024-12-31 / 2025-01-01 (§0).
- Q7 RESOLVED — Victor A1: thresholds accepted (relevance ≥ 0.50, min items 3/2/10, ≥ 20 names, 15:30 ET cutoff,
  10 bps/side); long-short legs k = floor(n/5); p from Student t, df = scored periods − 1 (§5).
- Q8 RESOLVED — Victor A5: confirmatory N = 2 (H1a primary, H1b), Holm 0.05 one-sided; H2 pre-registered exploratory (§2, §5).
- Q9 RESOLVED — Victor A6: not missing-at-random by assumption; metadata table §3A; excluded, H2 exploratory reported with
  missing counts per window (§3).
- Q10 RESOLVED (as assumption; Victor ACCEPT) — end-year fiscal-label convention plus pre-OOS DEV diagnostic (§2 step 4).
- Q11 RESOLVED — no returns extension (B4).
- Q12 RESOLVED — Victor ACCEPT: missing/unknown reportTime → post-market; R-RT stays. Materiality definition amended by A4 (§2).
- Q13 RESOLVED — declined: Jeremy declined Marcus's source-page timestamp fetch.
- Q14 RESOLVED — Victor ACCEPT: transcripts opened only when mapped to DEV day 0, none before sealing (§0).
- Q15 RESOLVED — Victor straddle ruling B8 (row L286) (§0).
- A2 (new) — DEV-sign gate and DEV-stats freeze (§0, §5). Ruling-file note: the ruling says the hypothesis "FAILS outright";
  "no OOS confirmatory test for it" and "p := 1 in Holm" are this draft's implementation, for confirmation in the delta readback.
Open — for Marcus (data): none.
