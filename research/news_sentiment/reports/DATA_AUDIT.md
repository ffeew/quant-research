# News data audit: timestamps and coverage (no returns examined)

2026-10-30, the sentiment researcher.
- This audit uses metadata only: ids, timestamps, symbols and counts. **No prices, returns or signal statistics were computed.**
- Hold-out months (before 2025-06) were read only for timestamp and coverage counts.
- Scripts are in `audit/`: `ts_internal.py`, `sample_urls.py`, `coverage.py`. Rerun `ts_internal.py` and `coverage.py` once the fetch completes, because the coverage tables below are partial.

## 1. Timestamps: created_at vs updated_at vs Benzinga first publication
**Data:** 193,110 unique articles fetched so far (188,701 Benzinga; 4,063 `fiscal.ai`; 346 with no source).

**Findings:**
- **`updated_at` is never earlier than `created_at`.** 96.4% are equal (within 1 s).
- Shares where `updated_at` is later than `created_at`:
  - by more than 1 minute: 2.39%
  - by more than 1 hour: 0.73%
  - by more than 1 day: 0.16%
  - by more than 30 days: 0.025%
- Among articles updated by more than 1 s, the median lag is 149 s, the 90th percentile 4.3 h, and the 99th percentile about 12.9 days.
- By year, the share updated by more than 1 hour is 1.0% in 2024, 0.7% in 2025 and 0.5% in 2026. It is higher in the partial 2021–23 alias-only data (3–5%). Older articles were edited more.

**Benzinga page check.** I sampled 44 articles stratified by year plus 8 heavily-updated ones, recovered their URLs from Alpaca, and read the page JSON-LD `datePublished` / `dateModified` for 4 of them (fetch budget):

| id | Alpaca created_at (UTC) | Benzinga datePublished | Alpaca updated_at | Benzinga dateModified |
|---|---|---|---|---|
| 38677564 | 2024-05-07 17:10:42 | 2024-05-07T13:10:42-04:00 ✔ | 17:10:42 | 13:10:42-04:00 ✔ |
| 26687322 | 2022-04-19 13:12:18 | 2022-04-19T09:12:18-04:00 ✔ | 13:12:18 | 09:12:18-04:00 ✔ |
| 17812638 | 2020-10-07 04:23:26 | 2020-10-07T00:23:26-04:00 ✔ | 2023-03-09 14:39:19 | 2023-03-09T09:39:19-05:00 ✔ |
| 22022773 | 2021-07-16 21:26:33 | 2021-07-16T17:26:33-04:00 ✔ | 2022-03-01 20:00:56 | 2022-03-01T15:00:56-05:00 ✔ |

- In all 4 cases **`created_at` equals Benzinga's first-publication time to the second**, including two articles edited 1.4 and 2.4 years later. I found no case where created_at lags first publication or is revised.
- **Caveat:** this is a sample of 4 pages. Benzinga blocks curl (HTTP 403), and each page check costs a full page fetch.
- **Vendor-id check across the whole fetched set.** If created_at were reset on re-ingest, an article's created_at would be out of line with articles whose vendor ids are close to its own.
  - Measured against the median created_at of the 101 nearest ids, only 31 articles deviate by more than 1 hour and 1 by more than 1 day, out of 193k.
  - I found no sign of backdated or reset created_at.

**Important API behaviour found (affects the fetch and the rule):**
- Alpaca's `start`/`end` filter, and each article's position in the feed, follow **`updated_at`, not `created_at`**. I confirmed this for 3 of 3 heavily-updated articles: a ±1 s query around created_at does not return them, but a query around updated_at does.
- An article edited later is therefore stored once, in the month of its **last edit**, while still carrying its original created_at. Examples: a 2013 article in `raw_alias/2024-02`, and a 2020 article in `2023-03`.
- The API serves only the **latest** text. That is why the pre-registration drops any article whose `updated_at` is later than its 09:25 ET decision cutoff, so we only score text that existed at decision time. ~~About 2.4% of articles are affected.~~ **Correction (2026-10-30 ~02:20 SGT):** 2.39% is the share edited more than 1 minute after creation, not the share dropped by the rule. The measured drop share is in §5: 0.15-0.68% in 2024-26.
- Session assignment always uses created_at, never the file month.

**Rule adopted (PREREG §3–4):**
- Timing = `created_at`, which is first public availability, in America/New_York.
- Drop the article if `updated_at` ≥ the decision cutoff.
- `news_signal.py` (exploratory) does not yet apply the `updated_at` filter. The seen-sample numbers in RESULTS.md therefore include about 2% of articles whose text may have been edited after the decision time. This is minor, but noted.

## 2. Coverage by year and sector (survivor feed)
Partial: the fetch is still running.
- Fully fetched: 2024-09, 2024-11 and 2024-12 through 2026-10.
- `raw_alias/` (42 pre-rename tickers) adds 2021–2024. For other symbols, years before 2024 are not yet fetched, so do not read the pre-2024 rows as coverage.

| year | articles (unique) | ≤3 symbols | S&P members that year | members with ≥1 article | former members that year | former with news |
|---|---|---|---|---|---|---|
| 2024 (partial) | 20,098 | 17,297 | 521 | 518 (99.4%) | 52 | 52 |
| 2025 | 88,963 | 77,078 | 523 | 521 (99.6%) | 37 | 37 |
| 2026 (to Oct 29) | 78,554 | 65,987 | 521 | 519 (99.6%) | 18 | 18 |

Articles with ≤3 symbols, by sector (current GICS):

| sector | 2025 | 2026 |
|---|---|---|
| Information Technology | 16,674 | 15,318 |
| Consumer Discretionary | 10,546 | 8,087 |
| Financials | 9,130 | 8,750 |
| Industrials | 8,843 | 7,739 |
| Health Care | 7,403 | 6,263 |
| Communication Services | 5,361 | 5,021 |
| Consumer Staples | 3,752 | 2,930 |
| Energy | 2,478 | 2,235 |
| Real Estate | 2,060 | 1,871 |
| Utilities | 2,016 | 1,839 |
| Materials | 1,897 | 1,691 |
| no GICS (former members) | 9,661 | 6,979 |

The full table is in `audit/coverage_by_sector_year.csv`.

**Observations:**
- Coverage is skewed toward IT and Consumer Discretionary.
- Materials, Utilities and Real Estate have about 5–10× fewer articles. That makes small-sector scores noisier and more often ineligible under the ≥3-stock rule.
- About 11% of ≤3-symbol articles in 2025 tag former members, e.g. WBD, TTD, AAL. These have no GICS and drop out of the sector score, so PIT GICS is needed from the data owner.
- The key survivorship question is how coverage changes before 2024: whether delisted or acquired names lost their history from the feed. That can only be answered once the fetch is complete.

## 3. Ticker reuse in tags
- **`FB`:** Benzinga pages now label `FB` as "ProShares S&P 500 Dynamic Buffer ETF". Before 2022-06-09 it was Meta, which is handled through `aliases.csv` with a date cut-off. After that date, FB-tagged articles are the ETF and are not members, so they are excluded.
- **Reused single-letter tickers** (`S` = Sprint then SentinelOne, `X`, `M`): excluded unless the symbol is a PIT member on the date.
- **`SNDK`:** excluded before 2017.
- I recommend the data owner's ticker-reuse audit cover the news tags too.

## 4. Lock on the hold-out
`news_signal.py` now skips every month before 2025-06 unless the pre-registration is frozen and its hash is supplied (see the status block at the top of PREREG_sector_lm_5d.md). Nothing produces results automatically:
- `fetch_news.py` only writes `raw/`.
- No cron job or routine exists.
- I verified that the lock currently skips the hold-out months already present in `raw/`.

## 5. Edited-after-cutoff drop share (validation decision 5 / final X6 i, iv). Metadata only
- Script: `audit/edited_share.py` (reads id, created_at, updated_at, symbols; no text, tone, prices or returns). Outputs: `audit/edited_share_by_year.csv`, `audit/edited_share_by_sector_year.csv`, `audit/edited_share_by_membertype_year.csv`, `audit/coverage_floor_by_month.csv`, `audit/edited_share.json`.
- Rule measured exactly as PREREG §4.3: session d = first session whose 09:25 ET cutoff is after created_at; **dropped if updated_at ≥ 09:25 ET of d.** Scope: every fetched file in `raw/` and `raw_alias/`, deduplicated by id; year = year of session d. Universe: ≤ 3-symbol articles tagging a PIT S&P 500 member (the PREREG input).
- **Status: provisional.** At run time (2026-10-30 ~02:20 SGT) `raw/` held 2024-06..2026-10 only; the 2016-01..2024-05 months are still being fetched.

| year (session) | ≤3-sym member articles | dropped | drop share | all articles drop share | > 5%? |
|---|---|---|---|---|---|
| 2024 (Jun–Dec only) | 39,484 | 267 | **0.68%** | 0.69% | no |
| 2025 | 66,894 | 213 | **0.32%** | 0.38% | no |
| 2026 (to Oct) | 58,069 | 89 | **0.15%** | 0.25% | no |
| 2021 / 2022 / 2023 | 142 / 1,303 / 665 | 5 / 20 / 6 | 3.5% / 1.5% / 0.9% | | **not a measurement** (see below) |
| 2016, 2019, 2020 | 1, 3, 4 | all | 100% | | **artefact** (see below) |

- **Read the pre-2024 rows as artefacts, not estimates.** Alpaca filters on updated_at, so until a month is fetched the only articles from it that we hold are ones later edited into a fetched month (100% "dropped" by construction) or alias-ticker pulls. Real 2016-2023 shares will be filled when the fetch completes; then any year above 5% is flagged.
- **By sector (2024-26):** every sector-year is ≤ 1.42% (max: Consumer Discretionary 2024 1.42%). No sector-year with ≥ 100 articles is above 5% in 2024-26. Pre-2024 flagged sector-years (e.g. Consumer Discretionary 2022 7.3% of 110, 2023 8.8% of 34) rest on the same artefact and on tiny counts.
- **Former vs current members (2024-26):** former 0.43% / 0.24% / 0.21% vs current 0.69% / 0.32% / 0.15%.
- **Years above 5%: none among the years that can be measured today (2024-26).** Pending: 2016-2023.
- **Selection statement (required).** Dropping later-edited articles is a selection on newsworthiness and on future information: whether a story is edited after the decision cutoff is not known at 09:25 ET, and edited stories are plausibly developing or high-attention ones. Keeping them instead scores text that did not exist at decision time. Neither is clean. The pre-registration therefore runs the no-filter version as a bound (PREREG G10): if the two disagree on G1 or G4, the verdict is capped at CONDITIONAL.

## 6. Coverage floor by month and former vs current members (validation X7). Metadata only
- `audit/coverage_floor_by_month.csv`: share of PIT members with ≥ 1 member-tagged article per month (any symbol count), split current vs former members. Floor for the first OOS month: **≥ 90%**.
- Measured (complete months only): 2025: monthly min 93.5%, mean 97.0% (former members 96.9%). 2026: min 91.9%, mean 96.5% (former 93.1%). Every 2025-26 month meets the floor.
- 2016-2024-05: **pending fetch** (current partial values are not meaningful). The possible Feb 2015 to Oct 2016 Benzinga gap (Alpaca forum report, not verified) will show up here; if 2016 months fail the floor the PREREG OOS start moves and lengths are restated.

## 7. Benzinga coverage by size (spillover card disclosure, validation decision 6 / M11). Metadata + dollar volume only
- `audit/coverage_by_size.py` → `audit/coverage_by_size_year.csv`, `audit/coverage_by_membertype_sessions_year.csv`. Size proxy = within-index tercile of 63-session median dollar volume (close × volume) at the prior month end; market caps for 41 members are pending from the data owner. "Story" = ≥ 1 Benzinga article tagging the stock with ≤ 3 symbols, session-assigned at the 09:25 ET cutoff. Only fully fetched months (2024-06..2026-10).

| year | tercile | member-sessions | share of sessions with own story | articles per member-session | members with no story all year |
|---|---|---|---|---|---|
| 2024 (Jun–Dec) | small | 24,642 | 16.0% | 0.25 | 0.5% |
| | mid | 24,636 | 22.8% | 0.38 | 0.0% |
| | large | 24,640 | 45.9% | 1.09 | 1.0% |
| 2025 | small | 41,921 | 16.6% | 0.26 | 0.5% |
| | mid | 41,914 | 24.0% | 0.39 | 0.0% |
| | large | 41,919 | 43.8% | 1.09 | 0.5% |
| 2026 | small | 34,707 | 17.5% | 0.29 | 1.4% |
| | mid | 34,703 | 24.0% | 0.41 | 0.4% |
| | large | 34,705 | 44.4% | 1.16 | 0.5% |

- Former vs current members (share of sessions with own story): 2024 20.1% vs 28.9%; 2025 19.9% vs 28.6%; 2026 24.3% vs 28.7%.
- **Known bias:** smaller and former members are covered at roughly 0.35-0.55× the rate of the largest tercile per session, so "no news of its own" (no Benzinga story) is a weaker test for them; pre-2024 levels are unknown until the fetch completes.
