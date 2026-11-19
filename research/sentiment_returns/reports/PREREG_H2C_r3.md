# PRE-REGISTRATION DRAFT r3 — H2-C: earnings-call tone surprise → post-call drift, confirmatory test on 2011–2020 (HOLDOUT 2011–2013, DEV 2014–2020)
Author: Ethan (Equity and Sentiment researcher, Daniel Koh's desk). r1 drafted 2026-11-13 ~23:55 SGT; r2 drafted 2026-11-14 ~00:10 SGT (UTC+8).
Status: **DRAFT r2, TEXT ONLY.** Amends r1 (7c082db8…) per Victor's review 9beb8f92 (log L660), Jeremy's OQ-1 and OQ-10
rulings, and Jeremy's 14 Nov 2026 ruling on attestation slot (iii).
**r3** (drafted 2026-11-14 ~00:10–00:40 SGT, UTC+8) amends r2 (SUMS b1543e29…, PREREG 704e8bdb…) per Victor's r2 review
ee3bd0e6 (log L663: OQ-19, OQ-20, OQ-21, §16 items) and Jeremy's confirmation of the OQ-19 gate change and of Victor's
other rulings (log L664, 14 Nov 2026), with the two additions (a) holdout warm-up source and (b) per-partition
missing-reportTime counts. No code written, no data pulled, no run made, and no data file's contents opened for this
draft. Ethan-sealed 0444 for Victor's seal; **NOT Victor-sealed**. Nothing in it authorises a run (see §12). Changes from
r1 are listed in §17 and DIFF_r1_r2.md; changes from r2 in §17 and DIFF_r2_r3.md.
Recipient: Victor (Signal Validation Lead). Then Jeremy (Fund Manager) per §12.

## 0. Sources (read for this draft; shas verified 2026-11-13 SGT)
| Item | Path | sha256 |
|---|---|---|
| Approved proposal (basis of this prereg) | $QR_DESK_DIR/research/original/proposal_next_hypothesis_20261113/PROPOSAL.md | f33d213235b0e51d5a3d5246f35a900be7677200214d1431ce57a239a97120da (verified, read in full) |
| Jeremy's approval terms | relayed message, Jeremy → Ethan, 2026-11-13 (H2-C APPROVED up to PREREG, changes 1–4) | message, no file |
| H2 DEV folder SUMS | $QR_DESK_DIR/research/original/sentiment_returns_h2_dev_20261111/SHA256SUMS | 76216058e890c39010288196a5cc258211a7b25e128f1f242b55d7534ab1d2ac |
| H2 DEV method code | …/sentiment_returns_h2_dev_20261111/h2_dev.py | dba0e8fbea36d63fbac0c2e2ae2a2933bee627507067fa49689b8517be4b3b48 (read in full; listed in SUMS) |
| H2 DEV results (method choices 1–11) | …/sentiment_returns_h2_dev_20261111/H2_DEV_RESULTS.md | 2e13c20a7a94eca501dfc603f157c2c46238308fb160b7454c7d739d1cd8b758 (per SUMS) |
| Sentiment-returns prereg family (H1a/H1b/H2) | $QR_DESK_DIR/research/original/sentiment_returns_prereg_20261111/PREREG_DRAFT_v5.md | 4b045f05da541175624946865ab695ed2f2c2fc1484554c065d940a2ec284c91 (§2, §3, §3A, §4, §4A, §5–§9 read) |
| v5 seal | $QR_DESK_DIR/validation/prereg_rulings/2026-11-11-ethan-sentiment-returns-v5-seal.md | 87e2b3a2833de8e297ccc72af8c20654dcb9dc3e0a9f1e2a487bc3124cb4ea65 (sha only) |
| Victor L305 H2 DEV readback | $QR_DESK_DIR/validation/prereg_rulings/2026-11-11-ethan-h2-dev-exploratory-readback.md | f1632650a993bccfefe32b73bf1ee122b9ea361b0ade3a42adf4aa60e7697793 (read) |
| Victor H1b OOS ruling | $QR_DESK_DIR/validation/prereg_rulings/2026-11-11-ethan-h1b-oos-pass-fail-ruling.md | e529d60de2eb7c005776c87e51053823b7f386658e4caf896cb71df961e563c4 (read) |
| H3 prereg v2 seal | $QR_DESK_DIR/validation/prereg_rulings/2026-11-13-ethan-h3-prereg-v2-seal.md | 40ddcc9c946172fb727d86f13e7ca002838dcb1709cfc7f55b84e104e1c488f3 (read) |
| Transcript manifest (universe) | $QR_DATA_DIR/av_sentiment_20261110/clean/MANIFEST.tsv | 758512c363bd1a572b619f58f0d4318f89dbeacbe141d4ef1ed762c0e4d005cf (metadata columns read) |
| Clean transcripts SUMS | $QR_DATA_DIR/av_sentiment_20261110/clean/SHA256SUMS | ed284d3751656def917ee5116e2b5efbf96ebec24fbc86f792692ca628442834 (sha only) |
| Cleaning notes | $QR_DATA_DIR/av_sentiment_20261110/clean/CLEANING.md | c14ef3d50d7015bf9e503eb01c2db4d40031e5b214a50397df44d1c4f765dab9 (sha only, not read) |
| Desk records cited in §4 P2 | see §4 | shas in §4 |
| r1 (superseded) | $QR_DESK_DIR/research/original/h2c_prereg_20261113/PREREG_H2C_DRAFT_r1.md | 7c082db87b0c1a325b21c4a900326c839e880939daed759b23c1e2867e52fa2c (verified, read in full) |
| Victor's r1 review (P1–P4, OQ rulings; log L660) | $QR_DESK_DIR/validation/2026-11-13-REVIEW_PREREG_H2C_r1.md | 9beb8f92f61ecf1d327ca674551804c98b17d502db6b29f7145851148022ecc3 (verified, read in full) |
| Jeremy's OQ-1 ruling and OQ-10 pre-approved swap; swap-in-force message; slot (iii) ruling 14 Nov 2026 | relayed messages, Jeremy → Ethan | message, no file |
| Attestations (Ethan, Dave, Sofia, Marcus; Dmitri record) | §16 | messages, no file |
| r2 (superseded by this r3) | $QR_DESK_DIR/research/original/h2c_prereg_r2_20261113/PREREG_H2C_DRAFT_r2.md | 704e8bdb90879f2746e9a90ba66c2e654451141f84e84f18996f66decfc6eb35 (verified; r2 SHA256SUMS b1543e290afedb6547440b56a9ed678ca41a19ac4bc6d3696c6b6ae1b7170115 verified) |
| Victor's r2 review (OQ-19..21, §16 items; log L663) | $QR_DESK_DIR/validation/2026-11-14-REVIEW_PREREG_H2C_r2.md | ee3bd0e673a5ffbd49c1d26bf4e2374055d8ab992078ceab2bb99590835e03dd (verified, read in full) |
| Jeremy's OQ-19/OQ-21 confirmation and additions (a)/(b) (log L664) | relayed messages, Jeremy → Ethan and Victor → Ethan, 14 Nov 2026 | message, no file |
| H1 DEV runner (evidence for §16(i)) | $QR_DESK_DIR/research/original/sentiment_returns_dev_20261111/dev_run.py (exact path taken from h2_dev.py dba0e8fb L38) | 80f4bb71485d2e20741f76a5a2197d64cdb05afeaf7f4d11ba7ac565d462329f (verified; matches h2_dev.py L38 pin; read in full) |
Where this draft and the proposal differ, the difference is stated (D-n, §13) or raised as an open question (OQ-n, §14).

## 1. Hypothesis (one confirmatory test, fixed in advance)
**H2-C:** For the frozen 50-stock universe (§2), an earnings call whose tone is above the firm's own previous calls (tone
surprise, §6) predicts positive beta-adjusted drift over sessions +2..+21 after the event (§7). Measured as a positive
cross-sectional rank IC per calendar quarter (§8), confirmed only if every gate in §9 holds.
Rationale (from the proposal §1): investors under-react to soft guidance carried in tone (limited attention). Turnover is
quarterly, so costs are far lower than H1b/H3, whose costs killed them (H1b ruling e529d60d: IC held OOS, net at 10 bps < 0).
Origin: H2 DEV (exploratory; L305 f1632650): 9 quarters 2022Q3–2024Q3, 446 events, mean IC 0.0947, NW t 2.71, net
+1.28%/qtr at 10 bps (raw L/S). H2 can never PASS (v5 A5) and has no 2025+ holdout. H2-C re-tests the same specification in
an older window. **No other hypothesis, variant, horizon, parameter sweep or sub-universe is part of this prereg.**

## 2. Universe — FROZEN (binding, Jeremy term 5)
The 50 common stocks with transcripts in MANIFEST.tsv 758512c3 (rows with tr_present > 0). Listed explicitly (with the
manifest's tr_first_q, metadata only):
AAPL 2010Q1, ABBV 2013Q1, ADBE 2010Q1, AMD 2010Q1, AMZN 2010Q1, AVGO 2010Q1, BA 2010Q1, BAC 2010Q1, C 2010Q1, CAT 2010Q1,
CMCSA 2010Q2, COST 2010Q1, CRM 2010Q2, CSCO 2010Q1, CVX 2010Q1, DIS 2010Q1, GE 2010Q1, GOOGL 2010Q1, GS 2010Q1, HD 2010Q1,
HON 2010Q1, INTC 2010Q1, JNJ 2010Q1, JPM 2010Q1, KO 2010Q1, LLY 2010Q1, MA 2010Q1, MCD 2010Q1, META 2012Q2, MRK 2010Q1,
MS 2010Q1, MSFT 2010Q1, NFLX 2010Q1, NKE 2010Q2, NVDA 2010Q1, ORCL 2010Q1, PEP 2010Q1, PFE 2010Q1, PG 2010Q1, QCOM 2010Q1,
SBUX 2010Q1, T 2010Q1, TSLA 2011Q2, TXN 2010Q1, UNH 2013Q1, V 2010Q1, VZ 2010Q1, WFC 2010Q1, WMT 2010Q2, XOM 2010Q1.
Count = 50. Hedge instrument: SPY (no transcripts; never in a cross-section). QQQ is in the manifest (no transcripts) and is
**not** used anywhere in H2-C.
- No additions, removals or substitutions, ever. P2 is resolved (Victor L660): the remedy is the window swap (§3.1), not
  dropping names; **all 50 names stay** (Jeremy). No removal can be made after sealing or after any H2-C data is opened.
- Names without a transcript or a price for an event are excluded from that event (counted, §11), not replaced.
- Crypto check: none of the 50 names, SPY or QQQ is a crypto proxy (proposal §5). MSTR is not in the universe.
- Coverage gaps (proposal §2, manifest): META from 2012Q2, ABBV/UNH from 2013Q1, TSLA from 2011Q2 — all inside the r2
  HOLDOUT (2011–2013), which is therefore thinner (§10 item 11). Missing labels per v5 §3A table (MISSING_TRANSCRIPTS_A6.tsv
  fc305390): 83 of the 84 missing labels fall in 2010Q1..2020Q3 and so fall inside H2-C's windows (incl. UNH 2010–2012
  unexplained 12, now holdout-side; WMT 6 unexplained up to 2020Q3, now DEV-side). Missingness is **not assumed at random**
  (v5 A6); counts are reported per quarter and per partition (§11).

## 3. Data, owner and partition (binding, Jeremy term 1)
**Owner: Dmitri (Data Engineer), not Marcus.** Jeremy approved the AV pull himself (~100 calls, within the 75/min budget):
- AV TIME_SERIES_DAILY_ADJUSTED, 50 stocks + SPY, clipped to **2009-12-01..2021-02-26** (as approved). Under r2 nothing
  dated after 2020-12-31 is needed or read (2021 is a known-seen window); Dmitri may clip at 2020-12-31 (§3.1);
- AV EARNINGS (quarterlyEarnings fiscalDateEnding, reportedDate, reportTime; annualEarnings fiscalDateEnding) for the 50
  stocks, **only if not already held** (see OQ-4 and P3).
The pull is queued behind Dmitri's current S1d2 seal. **Ethan makes no pull of his own.** Already held and reused:
clean transcripts (SUMS ed284d37), opened only as allowed in §3.3.

### 3.1 Partition boundary (by EARNINGS reportedDate) — r2 WINDOW SWAP (Jeremy OQ-10; Victor P2, L660; binding)
- **Calendar:** XNYS sessions from exchange_calendars 4.13.2 (H2/v5 pin). Boundary sessions (the runner asserts them from
  the pin; mismatch = STOP): first 2011 session 2011-01-03; last 2013 session 2013-12-31; first 2014 session 2014-01-02;
  last 2020 session 2020-12-31.
- **HOLDOUT events:** reportedDate in **2011-01-01..2013-12-31** AND day 0 + 21 (§7) ≤ **2013-12-31**.
- **DEV events:** reportedDate in **2014-01-01..2020-12-31** AND day 0 + 21 ≤ **2020-12-31**.
- **Straddle purge, both boundaries, same rule (binding):** an event reported ≤ 2013-12-31 whose day 0 + 21 is after
  2013-12-31, or reported ≤ 2020-12-31 whose day 0 + 21 is after 2020-12-31, is **PURGED**: not scored in either partition,
  not moved to the other, and contributes no return, IC or L/S anywhere. Decided from reportedDate, reportTime and the XNYS
  calendar alone (no price read). Roughly the reports from late November onward in 2013 and 2020 (counted, §11). No 2021
  price is ever read.
- **2010 calls (reportedDate 2010-01-01..2010-12-31) are holdout-side baselines only**; never scored, never used by DEV.
- **No baseline crosses the partition boundary (Victor OQ-7, binding):** DEV events use only DEV-side prior calls
  (reportedDate ≥ 2014-01-01). Holdout events may use 2010 calls and earlier holdout calls only; priors are strictly
  earlier, so a holdout baseline never draws on a DEV call.
- **2014 is a DEV WARM-UP YEAR ONLY (r3; Victor OQ-19(a), L663; CONFIRMED by Jeremy, 14 Nov 2026, L664; binding,
  structural, fixed before any data):** 2014 prices (PRICES_DEV from 2014-01-02) feed DEV betas; 2014 calls (reportedDate
  2014-01-01..2014-12-31) serve as DEV baselines; **no 2014 event is scored** (counted as "warmup_2014_not_scored").
  **Scored DEV events: reportedDate 2015-01-01..2020-12-31** (with the 2020 straddle purge). No 2013 price is released to
  DEV (Victor OQ-19(b) REJECTED).
- **Holdout warm-up source (r3 addition (a); Victor/Jeremy L664; binding):** holdout betas and the ≥ 2 earlier calls used
  as baseline come **only** from 2010 data inside the PRICES_HOLDOUT pull starting 2009-12-01 (2010 prices; 2010 calls),
  **plus strictly earlier holdout data**: for a holdout event, prices only through day 0 − 1 and calls only from strictly
  earlier holdout events. Holdout warm-up **never uses 2014+ data** (no PRICES_DEV, EARNINGS_DEV or DEV transcript is
  opened in the holdout run) and never uses holdout-window data that is not strictly earlier than the event.
- **Holdout rows (never read by Ethan, or by the DEV run, before the holdout opens):** (a) prices dated ≤ 2013-12-31 (the
  50 names and SPY, including the 2009-12-01 onward warm-up); (b) EARNINGS rows with reportedDate ≤ 2013-12-31; (c)
  transcripts mapped to events with reportedDate ≤ 2013-12-31 (2010 baselines, holdout events, purged late-2013 events);
  (d) anything derived from (a)–(c).
- **Partition spec for Dmitri (r3, final; Victor L663 accepted r2 STATUS boundaries with PRICES_DEV from 2014-01-02 and no
  2013 release; Jeremy L664):**
  - PRICES_HOLDOUT = XNYS sessions **2009-12-01..2013-12-31** (50 names + SPY; holds the 2010 beta warm-up for 2011 events).
  - PRICES_DEV = XNYS sessions **2014-01-02..2020-12-31** (2014 = warm-up year). **No 2013 price in DEV.** Nothing dated
    after 2020-12-31 is needed (the approved pull may run to 2021-02-26; Dmitri clips at 2020-12-31).
  - EARNINGS_HOLDOUT = reportedDate **≤ 2013-12-31**; EARNINGS_DEV = reportedDate **2014-01-01..2020-12-31**.
  - TRANSCRIPTS_HOLDOUT = a **separate sealed partition** (OQ-8 YES) of transcripts whose **mapped event reportedDate** is
    **2010-01-01..2013-12-31** (Victor OQ-20: YES; his "2010-2013 labels" wording is superseded); TRANSCRIPTS_DEV = mapped
    reportedDate **2014-01-01..2020-12-31** (e.g. a 2013Q4 label reported in 2014 is DEV). Labels that cannot be mapped
    from metadata stay in the sealed holdout partition.
  - Straddle purge as above (events reported ≤ 2013-12-31 or ≤ 2020-12-31 with day 0 + 21 past the boundary are purged;
    decided from metadata and the XNYS calendar only). Annual-FYE rows (no reportedDate): OQ-5, a freeze item. HOLDOUT
    partitions are sealed and hashed only, released only for the single holdout run.
  - **Sequencing (Jeremy, L664): Dmitri partitions only after r3 is sealed by Victor; his pull brief goes to Jeremy first,
    after the S1d2 accept.** No pull or partitioning is authorised by this draft.
- **DEV warm-up (r3, replaces r2 text):** DEV betas use PRICES_DEV only. 2014 has 252 XNYS sessions, so the first full
  252-return beta exists for a day 0 on or after about 2015-01-05; any 2015 event in the first days of January without a
  full beta is excluded and counted ("excl_beta_warmup"). G0 is evaluated on 2015Q1..2020Q4 (§9).
- The H1/H2/H3 holdouts (2025-01-01+) and the IV-gap options holdout (2016-06-01+, option chains only) are untouched.
  (H2-C reads no option data, so the IV-gap holdout boundary is not crossed even though 2016-06..2020 equity prices are DEV.)

### 3.2 Reader interface expected from Dmitri (unknowns are OQs)
Expected (to be confirmed by Dmitri; OQ-6): read-only sealed folders, files 0444, dirs 0555; a SHA256SUMS per partition
with **paths relative to the partition root** (IV-gap v2 lesson: the runner's pin check failed on a SUMS format change);
returns computed from adjusted_close ratios only, r(t) = adj(t)/adj(t−1) − 1, price levels never used (v5 §4A); columns at
least date, symbol, adjusted_close for prices and symbol, fiscalDateEnding, reportedDate, reportTime for EARNINGS;
row counts and date ranges stated in a NOTE; any non-split move > 25% listed and kept (no winsorising, v5 §4A). Whether
Dmitri delivers flat files (as for H2 DEV: daily_dev.csv / earnings_dev.csv) or a sealed reader module (as for IV-gap v2)
is OQ-6. The runner verifies every sha before reading anything; a mismatch is a STOP (§12).

### 3.3 Transcript access rule
- Transcripts are opened only by the frozen runner, never by Ethan by hand, and only the per-entry `sentiment` field is
  used; `content` is never read (v5 §2, H2 choice 8).
- DEV run: opens only transcripts mapped (§6.1) to DEV events (reportedDate 2014-01-01..2020-12-31), **excluding purged
  late-2020 events**. It never opens any transcript mapped to reportedDate ≤ 2013-12-31 (STOP if attempted).
- HOLDOUT run: opens only the separate sealed holdout transcript partition: transcripts mapped to holdout events and to
  2010 baseline calls (Victor L24, OQ-7). Purged late-2013 events are not needed and not opened.
- Holdout transcripts are physically separated into a sealed partition (OQ-8 YES); protection no longer rests on the
  runner allowlist alone. The DEV transcript source path and allowlist are fixed at freeze (OQ-6).

## 4. PRE-SEAL GATES — outcomes from Victor's review (9beb8f92, L660) and Jeremy's rulings
**P1 — Family count: RESOLVED (Victor note L4–7).** N = **5**, one-sided **α = 0.05/5 = 0.01** (Bonferroni): H1a, H1b, H3,
H2 DEV (counted as the selection look that seeded H2-C; N only goes up) and H2-C. Jeremy accepts. Ethan's Rank1 line
(c66d1edc) has its own N floor; Jeremy adds it if a confirmatory sentiment test from it ran (Victor has no record).
**P2 — Contamination: RESOLVED, 2018–2020 EXPOSED (Victor note L8–11).** Records: 6fd89382 L28–32 (v1.2 S&P 500 DEV,
name-days 2017-01-03..2021-12-29); Sofia's h1h2 DEV 2015-12-31..2022-03-29; PEAD work SIP 2016-01..2026-10; c66d1edc L14
("the desk has already seen S&P single-name returns over 2016-2026"). Remedy (Jeremy OQ-10, pre-approved, now in force):
**WINDOW SWAP**, HOLDOUT 2011–2013 / DEV 2014–2020 (§3.1); no names dropped. Swap condition (2011–2013 unseen) confirmed
from desk records by Victor (L12–15; records cannot prove a negative) and by the attestations in §16.
**P3 — EARNINGS metadata exposure: RESOLVED, DISCLOSED (Victor L18, OQ-4).** h2_dev.py (dba0e8fb L53–54) loaded the whole
$QR_DATA_DIR/av_returns_events_20261111/partitioned/dev/earnings_dev.csv (cb6a4e6f…; 5,279 rows, reportedDate ≤
2024-12-31), which includes 2011–2013 rows (dates, reportTime, EPS/surprise fields). Metadata, not returns or outcomes;
disclosed (§10 item 10). H2-C's holdout EARNINGS rows come **only** from Dmitri's fresh sealed holdout partition.
**P4 — Transcript sentiment exposure: RESOLVED (Victor L25 condition; Jeremy 14 Nov).** No record of any research reading
transcript sentiment for 2010–2020 labels (H2 DEV opened 2021Q4+ only, L305). Marcus (who built clean/ c14ef3d5) attests
no sentiment statistic was computed on 2010–2013 labels (§16, statement as given; his character count is disclosed as a
length measure). Dmitri's "did not produce it" is recorded as a record only (§16).
**P5 — Seal contents.** Victor seals this r3 0444 with its SHA256SUMS, records P1–P4 outcomes, confirms §13 deviations
(incl. D-2 r3 and D-11), Jeremy's slot (iii) reading (confirmed by Victor, L662/L663) and the §14 rulings (OQ-19 confirmed
by Jeremy, L664; OQ-20, OQ-21 resolved).

## 5. Point-in-time event rule (binding; Jeremy term 4 and Jeremy's OQ-1 ruling — r2 rewrite)
- **Event date = AV EARNINGS reportedDate.** The call time is **proxied** by reportedDate + reportTime. Per Victor OQ-11 the
  proxy stays primary; Dmitri may report whether a transcript timestamp key exists (key names only), and any such
  timestamp is a disclosed diagnostic only. A call held on a different session than the report is misdated; disclosed on
  every output (v5 §2).
- **Day 0 = the first XNYS session whose open follows the (proxied) call:**
  - reportTime = "pre-market" → day 0 = reportedDate session (or the next session if reportedDate is not a session);
  - reportTime = "post-market" → day 0 = the next XNYS session after reportedDate;
  - **missing or ambiguous reportTime** (empty, null, unparseable, "intra-day"/"during market", any other value) with a
    valid reportedDate → **EXCLUDED and COUNTED** ("excl_no_reporttime"), per Jeremy's OQ-1 text ("or with no timestamp, is
    excluded"); **no rescue** (r3; Victor OQ-21, L663; Jeremy L664). The r2/OQ-12 conservative default (day 0 = second
    session after reportedDate) is **withdrawn as a scoring rule**; it is computed only to report, as **INFO only**, how
    many excluded events it would have kept ("info_default_would_keep"), per partition.
- **Signal availability (Jeremy OQ-1, binding):** an event's tone uses only a transcript whose call is timestamped (proxy)
  **before close(day 0 + 1)**. Calls before the open or after the close of the reporting session both qualify. Under the
  day-0 rules above every proxied call falls before open(day 0), hence before close(day 0 + 1).
- **Excluded and COUNTED (reported in §11):** (a) **no timestamp** — reportedDate missing or unparseable
  ("excl_no_timestamp"), or reportTime missing/ambiguous ("excl_no_reporttime", above); (b) **call timestamped after close(day 0 + 1)** ("excl_call_after_close_p1"; expected 0 under the
  proxy). If an OQ-11 diagnostic timestamp exists, the number of events whose diagnostic time falls after close(day 0 + 1)
  is reported as a diagnostic (Victor OQ-11: proxy primary); see OQ-21. reportedDate before fiscalDateEnding or more than
  100 days after → fails the §6.1 lag rule (counted).
- **Entry and measurement (Jeremy OQ-1):** the tradable entry is **close(day 0 + 1)**, which is also the gate start; exit at
  close(day 0 + 21). The gate return is close(day 0 + 1) → close(day 0 + 21), beta-adjusted (§7): post-announcement drift
  only; the day 0/+1 announcement move is never in the return. Costs are charged at entry and at exit (§9.1). The r1
  "open(day 0) availability anchor" wording is withdrawn.
- Cross-section assignment: **calendar quarter of reportedDate** (D-1). DEV scored = exactly **24** quarters
  (2015Q1..2020Q4; 2014Q1..Q4 are warm-up only, never scored); HOLDOUT = exactly 12 (2011Q1..2013Q4).
- **Missing-reportTime counts per partition (r3 addition (b); binding):** "excl_no_reporttime" (and the INFO
  "info_default_would_keep") are counted and disclosed **separately for DEV and HOLDOUT**, per quarter and in total. These
  exclusions count against G0 like any other: **if they push G0 below threshold, G0 FAILS, with no rescue** (no default,
  no re-dating, no threshold change).
- **One event per symbol per calendar quarter (Victor OQ-18):** if a symbol has two reportedDates in one quarter, the
  earlier is kept and the later dropped and counted.

## 6. Signal definition (fixed in advance; H2 method, h2_dev.py dba0e8fb / v5 §2)
### 6.1 Transcript → event mapping
v5 §2 fiscal-label mapping steps 1–3, unchanged: fiscal year Y = the year whose annual fiscalDateEnding falls in calendar
year Y (end-year assumption, Q10); Q1..Q4 = the quarterlyEarnings rows in (end FY Y−1, end FY Y], exactly 4 required for
closed years, Q4 within ±7 days of the annual end; label YYYYQn matched to that row only if unique and reportedDate is
0..100 calendar days after fiscalDateEnding; no unique valid match → transcript excluded (counted by reason); no
calendar-quarter fallback. FYE months: the frozen FYE_MONTH_FROZEN.tsv (67d7eab8…) used by H2; its validity back to 2009
and annual-FYE coverage 2009–2020 must be shown by Dmitri **before the DEV freeze** (Victor OQ-5: blocks the freeze, not
the seal). The **v5 §2 step-4 fiscal-label diagnostic** (metadata only: EARNINGS DEV rows and DEV transcript file names)
runs inside the DEV run over DEV labels; any symbol failing (a)/(b) or with match rate < 90% is reported to Victor in the
raw output, and the HOLDOUT is not released until Victor rules. Holdout-run mapping uses the same rules.
### 6.2 Tone
T(i,q) = arithmetic mean of the float-parseable, finite AV per-entry `sentiment` values over all entries of the mapped
transcript; **≥ 10 parseable entries required**, else tone missing (H2 choice 8, v5 §2). Symbol and quarter keys in the
file are asserted equal to the expected label. No custom NLP; `content` never read.
### 6.3 Baseline and surprise
S(i,q) = T(i,q) − mean T over the symbol's **previous up to 4 available calls**, ordered by day 0 (strictly earlier day 0).
"Available" = mapped, present, tone non-missing, **and in the same partition** (§3.1); missing/unmatched transcripts are
not prior calls (H2 choice 2). **Minimum history: ≥ 2 prior calls** (sealed v5/H2 rule; Victor OQ-13 keeps ≥ 2), else
surprise missing and the event is excluded (counted). DEV priors: DEV-side calls only (reportedDate ≥ 2014-01-01); 2014 calls are
baselines for the scored 2015+ events (2014 events themselves are not scored; OQ-19). HOLDOUT priors: 2010 baseline calls
and strictly earlier holdout calls only (§3.1 addition (a)). No baseline crosses the boundary in either direction (Victor OQ-7). "Own last 4 calls" is implemented as
previous up to 4, ≥ 2 required (D-3).

## 7. Target (return window)
- Daily returns from adjusted_close ratios only (v5 §4A). No winsorising or trimming.
- Window: sessions day 0 + 2 .. day 0 + 21 = **close(day 0 + 1) → close(day 0 + 21)**, 20 daily returns, compounded:
  R_i = Π(1 + r_i,t) − 1; same for SPY.
- **Beta:** OLS slope of r_i on r_SPY over **exactly 252 daily returns ending day 0 − 1** (the session before day 0)
  (H2 choice 3; v5 §5; ruling B4). Point-in-time: uses only prices through day 0 − 1. Full 252-return window required, else
  the event is excluded (counted). Holdout: with PRICES_HOLDOUT from 2009-12-01 the first beta is available ~early
  December 2010, so all 2011 holdout events can have a beta. DEV: PRICES_DEV starts 2014-01-02 (no 2013 release); 2014 is
  the beta warm-up year and no 2014 event is scored; the first full beta is available for day 0 ≈ 2015-01-05 onward, and an
  earlier 2015 event without one is excluded and counted ("excl_beta_warmup") (OQ-19, §3.1).
- **Target = R_i − β_i · R_SPY** (beta-adjusted). Raw R_i also recorded.
- Any missing price in the window or in the beta window → event excluded (counted, "excl_missing_target").

## 8. Metrics
- **Cross-section:** all included events with reportedDate in the same calendar quarter (§5). A quarter is **scored only if
  ≥ 20 included events**; otherwise dropped from the IC series and counted (v5 §2).
- **IC:** per scored quarter, Spearman rank correlation between surprise S and the beta-adjusted target. Mean IC = simple
  mean over scored quarters. IC s.d. reported (ddof 1).
- **NW t:** Newey–West with Bartlett weights, **lag 1** (v5 §5 H2 lag), t = mean / sqrt(LRV/T), LRV as in h2_dev.py nw_t.
- **p:** one-sided (IC > 0), p = 1 − F_t(NW t; df = T − 1), Student t (v5 A1b). Holdout with all 12 quarters: df 11.
- **Quintile L/S:** per scored quarter, n included events, **k = floor(n/5)** (≥ 4 when n ≥ 20); long the k highest S,
  short the k lowest; ties broken by (surprise, symbol, label) (H2 choice 6); equal weight within each leg. One event per
  symbol per quarter (§5, OQ-18; the later duplicate is dropped and counted before ranking).
  - L/S beta-adjusted (gate): mean target(long) − mean target(short). L/S raw also reported.
  - Note (disclosure): this is an event-cohort return — each leg's events are held their own 20 sessions at staggered
    dates — not a single dated portfolio NAV (as in H2 DEV).
- **Effective sample:** per quarter n, k, number of symbols; per partition total events, scored quarters, df.

## 9. Pre-registered gate (binding, exactly as the proposal; Jeremy terms 6 and 4)
**G0 — Coverage (each partition, evaluated in that partition's run; Victor OQ-3):** ≥ 20 scored events in **≥ 90% of
quarters**: **DEV ≥ 22 of 24 quarters, 2015Q1..2020Q4** (21.6 rounded up); HOLDOUT ≥ 11 of 12, 2011Q1..2013Q4 (10.8
rounded up). **GATE CHANGE (r3): CONFIRMED (Jeremy, 14 Nov 2026; L664)**, as ruled by Victor (OQ-19(a), L663): the DEV
denominator is the 24 structurally eligible quarters after the 2014 warm-up year; the 90% rule is unchanged; r2's
"≥ 26 of 28" is withdrawn (Victor self-reported his earlier "28 DEV" ceiling as wrong). Missing-reportTime exclusions
count against G0; if they push G0 below threshold, G0 FAILS with no rescue (§5).
Fail → STOP; H2-C closes (DEV fail means the holdout is never opened).
**G1 — DEV (all must hold):** (i) mean quarterly rank IC > 0; (ii) NW t (lag 1) ≥ 2.0; (iii) mean net quintile L/S > 0
at 10 bps per side (cost model §9.1). **A DEV fail means the holdout is NEVER opened** and H2-C is closed.
**G2 — HOLDOUT (all must hold):** (i) mean IC > 0; (ii) one-sided **p ≤ 0.01** (N 5, P1; NW lag 1, t df = T − 1, 11 if 12 quarters);
(iii) holdout mean IC ≥ 0.5 × the frozen DEV mean IC; (iv) beta-adjusted quintile L/S, full round trip per quarter at
10 bps per side, mean net > 0, **and** still > 0 after the 10%/yr short-borrow charge on the short leg.
Reported, never gating: 20 bps/side, break-even cost per side, raw L/S, DEV L/S with borrow.
**Kill:** any fail (G0, G1 or G2) closes H2-C: no variants, no re-specification, no reruns, and **no reuse of 2011–2013
(the holdout) for transcript tone** (proposal §4). **A pass is conditional:** an UPPER BOUND (§10 item 1), which needs a
forward shadow check on calls after 2026-10-31 before any paper trading (OQ-14: spec pre-registered before any shadow data
is pulled), and per the H3 seal S1 pattern also Rachel's sizing, Tomas's costs and Daniel's confirmation before anything
goes to paper.
### 9.1 Cost model (entry close(day 0 + 1), exit close(day 0 + 21); Jeremy OQ-1)
- Each scored quarter is charged a **full flat-book round trip** at entry and exit: turnover 4 (enter 2 gross at
  close(+1), exit 2 at close(+21)) × 10 bps = **40 bps per quarter** (H2 choice 5; L305 D-H2-2). 20 bps/side sensitivity
  = 80 bps.
- **SPY beta hedge trades (Victor OQ-15: YES):** 10 bps/side on the hedge notional |mean β(long) − mean β(short)|, charged
  at entry and at exit; included in G1(iii) and G2(iv).
- **Short borrow (G2 iv second leg; Victor OQ-16):** 10%/yr on the short leg's gross notional (1.0) for the **calendar days
  actually held**, close(day 0 + 1) → close(day 0 + 21) per short event, / 365, averaged equally over the short leg's
  events; deducted after the trading costs. (Typically ~28–30 calendar days ≈ 0.77–0.82% per quarter.)
- No leverage beyond 1 long + 1 short gross; no financing credit on the long leg.

## 10. Binding disclosures (Jeremy term 3 and r2 additions; stated on every output)
1. **Look-ahead:** AV scored the 2010–2020 transcripts recently with a current model; tone is **not point-in-time** and
   may carry hindsight. Any PASS is an **UPPER BOUND** and needs a forward shadow check before paper.
2. **Survivorship:** the 50 names were chosen in 2026 (today's large caps). Expected direction of bias: **upward** — the
   sample keeps firms that went on to succeed (e.g. NVDA, TSLA, AMD, META) and drops firms that shrank, merged or failed,
   so large post-call gains and improving tone are over-represented and any positive result is an upper bound (v5 §7).
   Counter-mechanism stated honestly: firms that failed could have shown falling tone with falling returns, which would
   support the hypothesis; their absence pushes the other way. Net expected direction: upward; magnitude unknown. Under
   r2 the holdout (2011–2013) is the window furthest from the 2026 selection, so survivorship is expected to be at least
   as strong in the holdout as in DEV.
3. **Power (r3 restatement: 24 DEV quarters, α 0.01, N 5).** Assumptions (stated, not estimated from any H2-C data): true
   mean quarterly IC μ = 0.095 and per-quarter IC s.d. σ = 0.111 (H2 DEV, proposal §8e); quarters independent (NW lag-1
   correction ignored); one-sided test of mean IC treated as a t-test on T quarterly ICs, df = T − 1; power =
   P(noncentral t(df, ncp) > t crit), ncp = (μ/σ)·√T, μ/σ = 0.856. Computed with scipy.stats nct/t (venv, text only):
   - **DEV, T = 24 (2015Q1..2020Q4):** ncp = 0.856 × √24 = 4.19; df 23. At the DEV gate G1(ii) (NW t ≥ 2.0): power
     ≈ **98%**. At α 0.01 (t crit 2.500, df 23), for reference: ≈ **95%**. (r2's 28 quarters gave ncp 4.53, ≈ 99% at t ≥ 2.0
     and ≈ 98% at α 0.01; the drop to 24 scored quarters lowers DEV power, disclosed in item 16.)
   - **HOLDOUT, T = 12 (2011Q1..2013Q4), the confirmatory α 0.01 test G2(ii):** ncp = 0.856 × √12 = 2.96; t crit 2.718
     (df 11); power ≈ **61%**. With 11 quarters (the G0 minimum): ncp 2.84, t crit 2.764, ≈ **55%**. Correction: r2's
     "about 55%" for 12 quarters was a rough hand estimate; the exact noncentral-t value under the same assumptions is
     ≈ 61%.
   - **Thinner holdout names (item 11; META, ABBV, UNH, TSLA):** fewer events per 2011–2013 quarter raise σ. Illustration:
     σ = 0.125 → ≈ 49%; σ = 0.14 → ≈ 40% (T = 12, α 0.01). **Holdout power is therefore expected below 61%**, before the
     0.5× DEV-IC and cost conditions G2(iii)–(iv), which lower it further. Restated at freeze from DEV-partition quantities
     only. A FAIL is weak evidence against.
4. **Origin in H2 DEV, counted in N:** the idea came from H2 DEV (exploratory, 2022Q3–2024Q3). H2 DEV counts as the
   selection look and H2-C as a confirmatory test: family **N 5** (P1); N only goes up.
5. **Overlap with H3:** same vendor (AV) and scoring family, but calls rather than news; H3 tests 2025+ and H2-C
   2011–2020, so no period overlap, but a shared vendor model bias would push both the same way. No H3 result, data or
   threshold is used in H2-C. If H3 has reported before the H2-C seal, that is disclosed in the seal.
6. Event date is a reportedDate proxy (§5); 2020 (COVID) is now in DEV; missing transcripts not at random (§2).
7. Exploratory-to-confirmatory: the specification is H2's, chosen after seeing H2 DEV (2022–2024).
8. **Window swap after an exposure check (Jeremy OQ-10; Victor P2):** r1's holdout 2018–2020 was found EXPOSED by desk
   records; the swap to HOLDOUT 2011–2013 / DEV 2014–2020 was pre-approved by Jeremy before the check and applied after it.
   The **holdout is earlier in time than DEV**; it is not an out-of-time forward test, and the **forward shadow check
   before paper still applies**.
9. **SPY 2011–2013 has been seen** (condor DEV 2008–16; IV-gap read SPY spot 2009–16). SPY is the hedge and beta input
   only, never in the cross-section (Victor P2(a)).
10. **2011–2013 EARNINGS metadata was loaded by h2_dev.py** (earnings_dev.csv cb6a4e6f: dates, reportTime, EPS/surprise
    fields; not returns or outcomes). Holdout EARNINGS rows come only from Dmitri's sealed holdout partition (Victor P2(b)).
11. **Thinner holdout:** META from 2012Q2, ABBV/UNH from 2013Q1, TSLA from 2011Q2 (with ≥ 2 priors their first scorable
    events come about two quarters later). Lower effective N and power; per-quarter n is reported; G0 denominators are 24 DEV
    (2015Q1..2020Q4, r3) / 12 HOLDOUT quarters (Victor P2(c); OQ-19).
12. **Sofia (attestation slot (iii), in her words per Jeremy's ruling):** the AV full-history files (manifest f6d8f569)
    were parsed mechanically; the split and dividend counts may span 2011–13; there are no records before 29 Oct 2026.
    Accepted as UNSEEN WITH DISCLOSURE by Jeremy (14 Nov 2026); **CONFIRMED by Victor** at r2 review (ee3bd0e6, L662/L663)
    (§16(iii), her two sentences quoted verbatim).
13. **Marcus (P4):** the clean/ build computed a total character count over transcript text fields, used only to flag the
    82 empty replies; a length measure, not a sentiment statistic (§16).
14. **Dave:** his SUE build used XBRL quarterly EPS facts whose seasonal history may include 2011–2013 fiscal periods
    (earnings figures, not returns); his VRP work read SPY/QQQ options and spot 2009–2016 (ETFs, not single names) (§16).
15. **Limits of the unseen claim:** it rests on desk records (which cannot prove a negative) and on recall attestations
    (§16), not on a filesystem audit.
16. **DEV has 24 scored quarters, not 28 (r3; Victor L663):** 2014 is a warm-up year (betas and baselines only; no 2014
    event scored), because the swap moved the warm-up to the start of the DEV partition and no 2013 price is released to
    DEV. DEV G0 is ≥ 22 of 24 (gate change confirmed by Jeremy, L664). Lower DEV power (item 3).
17. **Missing reportTime (r3; addition (b)):** events with a missing or ambiguous reportTime are excluded and counted,
    **per partition (DEV and HOLDOUT)**, with no rescue; the number the withdrawn OQ-12 default would have kept is
    reported as INFO only. If these exclusions push G0 below threshold, G0 fails.
18. **Holdout warm-up (r3; addition (a)):** holdout betas and baselines come only from 2010 data inside the 2009-12-01 price
    pull plus strictly earlier holdout data (§3.1); never from 2014+ data.

## 11. Outputs (raw to Victor first)
Each run writes only into its own new run directory (created by the runner with 'x' semantics, must not pre-exist) plus a
console file outside it:
- run.log (inputs and shas, interpreter, flags, versions, counts);
- STATS json (G0/G1 or G0/G2 values, every reported figure, verdict fields);
- periods.tsv (per quarter: n, k, n_symbols, IC, L/S raw and beta-adjusted, gross and net);
- events.tsv (per event: symbol, label, fiscalDateEnding, reportedDate, reportTime, day0, quarter, ret_start, ret_end,
  n_parseable, tone, n_prior, surprise, beta, ret_raw, target, status; **no transcript text**);
- counts by exclusion reason (no timestamp, call after close(day 0 + 1), missing transcript, unmatched mapping, tone < 10
  entries, < 2 same-partition priors, beta warm-up, 2014 warm-up event not scored (DEV), missing target, purged straddle
  (each boundary), same-symbol duplicate dropped (OQ-18), quarter < 20, **missing/ambiguous reportTime excluded — per
  partition, per quarter and total**), the INFO count the withdrawn OQ-12 default would have kept (per partition), the
  OQ-11 timestamp diagnostic if any, missing-transcript counts per quarter, step-4 diagnostic;
- SHA256SUMS of the run dir. Every output carries the §10 disclosures.
**Raw output and console go to Victor first, unread by anyone else.** No result goes to Daniel or Jeremy until Victor
validates (v5 §8). The DEV-stats freeze is written 0444 and sha-logged with Victor **before** any holdout file is released.

## 12. Run protocol (two separate single runs)
**DEV run:** runner adapted from h2_dev.py (synthetic tests only) → FREEZE (runner, tests, pins, 0444, SUMS) → Victor
confirm → LOCK note (exact command, pins) → Jeremy's release → Victor go row → right before the run, re-check that the run
dir and console file are absent → **ONE run**.
**HOLDOUT run (only if G0 and G1 pass and Victor has ruled any step-4 findings):** DEV-stats freeze sha-logged with Victor →
holdout runner LOCK confirmed by Victor against that freeze → Jeremy's release of the holdout partitions → Victor go row →
absence re-check → **ONE run**.
**Command form (both runs), full desk L3:**
`env -i unshare -rnmp --fork --mount-proc <VENV>/bin/python -I -B <runner.py> > <console OUTSIDE run dir> 2>&1; echo "rc=$?" >> <console>`
(<VENV> = **$QR_DATA_DIR/.venv** (python 3.13.5), pinned as in the IV-gap run; Victor OQ-17 — r1's "venv no longer
exists" text was stale and is withdrawn; version pins fixed at freeze.) No network, no env vars.
**No rerun on any rc.** A STOP or non-zero rc ends that release; any new run needs a fresh release from Jeremy.
STOP conditions (runner exits non-zero before computing statistics): any sha mismatch; any holdout path opened in the DEV
run; any event row outside the partition being run; interpreter/flags/version mismatch with the LOCK; a mapping
cross-check failure.

## 13. Declared deviations from the proposal / H2 method
- D-1: cross-section = quarter of reportedDate, not of day 0 (H2), so DEV/HOLDOUT are exactly 24 scored (2015Q1..2020Q4,
  r3) / 12 quarters.
- D-2 (r3, replaces r2 D-2): unknown or ambiguous reportTime → event **excluded and counted** (H2: next session; r2: second
  session after reportedDate). Victor OQ-21 (L663), Jeremy L664; the default survives only as an INFO count.
- D-3: "last 4 calls" implemented as previous up to 4, ≥ 2 required (sealed v5/H2 rule; Victor OQ-13).
- D-4: SPY hedge cost charged at 10 bps/side (ACCEPTED, Victor OQ-15); proposal charged only the stock legs.
- D-5: the proposal §3 claim "before the 2021-03-01 start of any returns the desk has seen" is not relied on; the records
  show it is false (Victor L45).
- D-6: data owner Dmitri (proposal said Marcus); pull scope as Jeremy approved (~100 calls).
- D-7 (r2): windows swapped — proposal DEV 2011–2017 / HOLDOUT 2018–2020 → **DEV 2014–2020 / HOLDOUT 2011–2013**, both
  boundaries purged (Jeremy OQ-10; Victor P2).
- D-8 (r2): family N 5, α 0.01 (proposal N 4, α 0.0125) (Victor P1).
- D-9 (r2): one event per symbol per quarter, earlier kept (H2 kept duplicates; found 0) (Victor OQ-18).
- D-10 (r2): borrow on calendar days held / 365 (r1 proposed 20/252) (Victor OQ-16).
- D-11 (r3): 2014 is a DEV warm-up year (betas, baselines; no event scored); DEV G0 denominator 24 quarters 2015Q1..2020Q4,
  ≥ 22 required (proposal/r2: all DEV quarters). Gate change, CONFIRMED by Jeremy (L664) on Victor's OQ-19(a) (L663).

## 14. Open questions — r3 status (rulings: Victor 9beb8f92 L26–44 and ee3bd0e6 (L663); Jeremy as stated, incl. L664)
- OQ-1 RESOLVED (Jeremy): gate close(day 0 + 1) → close(day 0 + 21), beta-adjusted; transcripts timestamped before
  close(+1) only; late/untimestamped calls excluded and counted; entry close(+1); costs at entry and exit (§5, §9.1).
- OQ-2 RESOLVED (Victor): G1(iii) beta-adjusted, as drafted; raw is INFO.
- OQ-3 RESOLVED (Victor): G0 per partition, confirmed.
- OQ-4 RESOLVED (Victor, P3): fresh partitioned EARNINGS via Dmitri; earlier loading disclosed (§10 item 10).
- OQ-5 FREEZE ITEM (Victor): Dmitri shows annual-FYE coverage 2009–2020 and FYE_MONTH_FROZEN 67d7eab8 validity back to
  2009 before the DEV freeze; blocks the freeze, not the seal.
- OQ-6 FREEZE ITEM (Victor): Dmitri's reader interface; non-blocking.
- OQ-7 RESOLVED (Victor, under the swap): no baseline crosses the boundary (§3.1, §6.3).
- OQ-8 RESOLVED (Victor): YES, holdout transcripts in a separate sealed partition.
- OQ-9 RESOLVED (Victor, P1): N 5, α 0.01.
- OQ-10 RESOLVED (Jeremy, pre-approved; condition confirmed by Victor): window swap.
- OQ-11 RESOLVED (Victor): proxy stays primary; a timestamp key (names only) is a disclosed diagnostic.
- OQ-12 SUPERSEDED (r3, by OQ-21): the conservative default is withdrawn as a scoring rule; a missing reportTime is
  excluded and counted, with no rescue; the default's would-keep count is INFO only.
- OQ-13 RESOLVED (Victor): keep ≥ 2.
- OQ-14 OPEN, NON-BLOCKING (Victor): forward-shadow spec pre-registered before any shadow data is pulled.
- OQ-15 RESOLVED (Victor): YES, SPY hedge at 10 bps/side.
- OQ-16 RESOLVED (Victor): calendar days actually held / 365.
- OQ-17 RESOLVED (Victor): $QR_DATA_DIR/.venv exists (python 3.13.5); pinned as in the IV-gap run.
- OQ-18 RESOLVED (Victor): keep the earlier event only; count the dropped.
- **OQ-19 RESOLVED — GATE CHANGE CONFIRMED (Victor L663 option (a); Jeremy, 14 Nov 2026, L664).** (b) a 2013 price
  release to DEV is REJECTED (it would put holdout-window single-name returns into DEV betas). (a) ADOPTED as a structural
  rule fixed before any data: 2014 is a DEV warm-up year only (2014 prices feed betas, 2014 calls are baselines, no 2014
  event scored); DEV G0 over 2015Q1..2020Q4, ≥ 22 of 24 at the unchanged 90% rule; HOLDOUT G0 stays 12 quarters (warm-up and
  baselines from 2010 on the holdout side). Applied in §3.1, §5, §6.3, §7, §9 G0, §10 items 3/11/16, D-1, D-11.
- **OQ-20 RESOLVED (Victor L663: YES).** Transcripts partition by the mapped event's reportedDate; holdout transcript
  partition = mapped reportedDate 2010-01-01..2013-12-31 (§3.1).
- **OQ-21 RESOLVED (Victor L663; Jeremy L664).** The reportedDate/reportTime proxy is primary; r2's exclusion of calls after
  close(+1) on the proxy stands; the transcript-timestamp check stays a reported count. A MISSING reportTime is EXCLUDED and
  COUNTED per partition, with no rescue; the OQ-12 default's would-keep count is INFO only (§5, §11).

## 15. Statements
- **Paper only**, equity long/short hedged with SPY shares. No derivatives, no crypto or crypto proxies, no leverage.
- No orders, sizing or live use. Nothing goes to paper without the shadow check and the S1-pattern sign-offs (§9).
- Market sentiment (context only, never an input): proposal §6 (AAII 30.8% bull / 51.4% bear to 11 Nov; VIX 18.70 close
  12 Nov; cautious, bearish-leaning backdrop).
- Effort (proposal §7, Dmitri replacing Marcus): ~30 agent-hours, 3–5 desk-days; review cycles could double it.
- This file is 0444 with its SHA256SUMS; any change is a new revision (r4) with a CHANGES note.

## 16. Attestations (Jeremy, swap condition; Victor P2 L15 and P4 L25)
**(i) Ethan — SIGNED.** I, Ethan (Equity and Sentiment), have never read, computed on, or plotted single-name returns dated
2011-01-01..2013-12-31 for any of the 50 H2-C names. Checked before signing (r2 drafting, 14 Nov 2026 SGT): h2_dev.py
(dba0e8fb, listed in SUMS 76216058) reads prices only from …/av_returns_events_20261111/partitioned/dev/daily_dev.csv (L16,
L53) and asserts its dates are exactly the XNYS sessions 2021-03-01..2024-12-31 (L54, L56–57); returns and betas are
computed only from that frame (L58–63, L186). The 2011–2013 rows it loaded are EARNINGS metadata (L53–54; §10 item 10) and
annual-FYE metadata (L19, L74), not returns. Transcripts opened only for the S6b due labels (L110, L149–153; 2021Q4+ per
L305). My other single-name return work in the desk records starts 2016 or later (c66d1edc L14, DEV 2016–2019; 6fd89382
L28–32, 2017-01-03..2021-12-29). My 2009–2016 IV-gap work read SPY (an ETF, the hedge), disclosed in §10 item 9.
**Additional evidence (r3; Victor L663 item (2)): dev_run.py**, the H1 DEV runner whose helpers h2_dev.py copies. Exact path
from h2_dev.py L38 (its pin table): $QR_DESK_DIR/research/original/sentiment_returns_dev_20261111/dev_run.py, sha256
80f4bb71485d2e20741f76a5a2197d64cdb05afeaf7f4d11ba7ac565d462329f (verified 14 Nov 2026 SGT; equals the h2_dev.py L38 pin). Price input lines:
L10 `RET = '$QR_DATA_DIR/av_returns_events_20261111/partitioned/dev'`; L20 `daily = pd.read_csv(f'{RET}/daily_dev.csv')`
(its only price input; also `earnings_dev.csv`, EARNINGS metadata, used here only for a row count); L21 asserts 49,317 price
rows; L22 asserts `daily['date'].max() <= '2024-12-31'`; L24–25 assert the set of price dates equals the XNYS 4.13.2
sessions **2021-03-01..2024-12-31 exactly** (`sessions_in_range('2021-03-01', '2024-12-31')`), so no price dated before
2021-03-01 can be in the frame (the run fails otherwise); L27–34 returns and betas from that frame only. Its other inputs are
news coverage metadata and news JSON files for months 2022-03..2024-12 (L38–39, L44–45, L52–54; no transcripts, L2). No
price input outside 2021-03-01 onward: **CLEAN**.
Signed, Ethan, 14 Nov 2026 SGT.
**(ii) Dave — SIGNED (verbatim):** "I, Quantitative Researcher (Dave), have never read, computed on, or plotted S&P 500
single-name returns dated 2011-01-01 to 2013-12-31; every single-name return series I touched began 2016-01-04 or later
(Sofia's statarb daily_bars from 2020 for the round-1 replications, Dmitri's PIT SIP store 2016-2026 for the reruns and the
CVA/TSC/MXD signal statistics, 2017-2022)." Disclosures (1) XBRL quarterly EPS facts possibly including 2011–2013 fiscal
periods (earnings figures, not returns); (2) SPY/QQQ (ETF) options and spot 2009–2016 DEV. Limit: recall attestation from
his own sessions, not a filesystem audit. Signed, Dave, 14 Nov 2026 00:05 SGT.
**(iii) Sofia — ACCEPTED WITH DISCLOSURE per Jeremy 14 Nov 2026; CONFIRMED by Victor at r2 review (ee3bd0e6; L662/L663).**
Her two sentences, verbatim as relayed to Ethan: "I have never computed on or plotted returns for S&P 500 single names
dated 2011-01-01 to 2013-12-31." and "So I can't certify from my records that no 2011-2013 row was ever read by code."
Qualified statement: she never computed on or viewed, summarised or plotted any 2011–2013 single-name return value, but a
download script parsed the AV full-history files, which contain 2011–2013 price rows. Jeremy's ruling: UNSEEN WITH DISCLOSURE; it does not trigger
the both-windows branch (a holdout is spoiled by outcome information — returns, signals, or statistics or plots from
2011–2013 prices — reaching a decision-maker; a mechanical parse for the manifest, coverage and split/dividend counts
conveys nothing on post-earnings drift). Binding disclosure in her words: §10 item 12. **Victor confirms this ruling
(r2 review ee3bd0e6, L662).**
**(iv) Marcus (P4) — SIGNED, as given:** "I confirm that my raw validation and clean/ build for av_sentiment_20261110
(clean SUMS ed284d37) computed no sentiment statistics on 2010-13 labels." For 2010–2013 transcript files he computed only
file sha256 (incl. grouping identical files); JSON parse and Error/Note/Information body checks; symbol/quarter match and
presence; entry count and total character count (used only to flag the 82 empty replies as missing). "I never read,
aggregated or printed any sentiment score, relevance score or transcript text. The transcripts in clean/ are byte copies of
raw." Disclosure: the character count is a length measure over the text fields, not a sentiment statistic (§10 item 13).
Signed 14 Nov 2026 SGT.
**(v) Dmitri — RECORD ONLY (Jeremy):** his records show no cleaning run by him on av_sentiment_20261110/clean (SUMS
ed284d37); he did not produce that set. The H2-C price and EARNINGS pull has not run; its cleaning will compute no
sentiment statistics.

## 17. CHANGES
### r2 → r3 (full unified diff and ruling map: DIFF_r2_r3.md)
OQ-19 gate change CONFIRMED (Jeremy L664): 2014 DEV warm-up year, no 2013 release, DEV G0 ≥ 22 of 24 (2015Q1..2020Q4)
(§3.1, §5, §6.3, §7, §9, §10 items 11/16, D-1, D-11, §14); OQ-20 transcripts by mapped reportedDate (§3.1, §14); OQ-21
missing reportTime excluded and counted, no rescue, default INFO only (§5, §11, D-2, OQ-12, §14); addition (a) holdout
warm-up source (§3.1, §6.3, §10 item 18); addition (b) per-partition missing-reportTime counts, G0 fails with no rescue
(§5, §9, §10 item 17, §11); final partition spec and sequencing for Dmitri (§3.1); power restated for 24 DEV quarters (§10
item 3); Sofia verbatim and Victor's confirmation (§10 item 12, §16(iii)); dev_run.py evidence (§0, §16(i)); header, §0, P5.
### r1 → r2 (full unified diff: DIFF_r1_r2.md)
P1 N 5 / α 0.01 (§4, §9 G2(ii), §10.3–4, D-8); P2/OQ-10 window swap with both boundaries purged, price/EARNINGS/transcript
partitions, warm-up rule, no cross-boundary baselines (§2, §3, §3.1, §3.3, §6.3, §7, D-7); OQ-1 §5 rewrite and §9.1 costs;
OQ rulings marked (§13, §14); new disclosures 8–15 (§10); attestations (§16); new OQ-19..OQ-21.
