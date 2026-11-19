# earnings_events_8k202 v1

Point-in-time S&P 500 earnings-event table built from SEC EDGAR 8-K / 8-K/A filings that list **Item 2.02** (Results of Operations and Financial Condition).

- **Owner:** Ethan (Equity Analyst)
- **File:** `earnings_events_8k202.parquet` (zstd)
- **Version string:** `earnings_events_8k202 v1 (Ethan, 2026-11-06)`
- **Window:** acceptance times from 2015-01-01 through 2026-10-29 (ET)
- **Rows:** 31,467 unique accessions (24,963 while the issuer was a PIT S&P 500 member)
- **No prices, returns, or EPS are in this table.** See `SUE_NOTE.md` for how Dave can build SUE on top.

## Event definition

1. Start from PIT S&P 500 membership (`$QR_DATA_DIR/universe/sp500_membership.parquet`) mapped to CIK segments (`ee_map.py` → `work/member_cik_segments.parquet`), identity-checked against SEC submissions names and periodic filings (`ee_validate.py`), with manual CIK fixes in `work/manual_cik_fixes.csv` (`ee_build.py` merges them into `work/segments_final.parquet`).
2. Pull every 8-K / 8-K/A whose `items` list contains `2.02` from the cached SEC submissions JSON (`raw/sec/`, fetched by `ee_fetch.py` under the declared User-Agent, ≤ 8 req/s).
3. **Cluster** filings of the same CIK within 3 calendar days (ET) of the cluster’s first filing. The event row is the **first** filing in the cluster (by `acceptance_utc`). `cluster_n_filings`, `cluster_has_amendment`, and `cluster_accessions` keep the rest of the cluster.
4. Tag `in_sp500` if any validated segment for that CIK covers the acceptance date. `index_symbols` lists every index ticker sharing the CIK that day (e.g. GOOGL,GOOG).
5. **Deduplicate by accession** at finalize: the same EDGAR accession can appear under two related CIKs when both list the filing in submissions (EXC/Pepco, SO/Southern Co Gas, Xerox Corp/Holdings, Baker Hughes Co/Holdings LLC, Mylan Inc/Mylan II). Keep the `in_sp500` row when exactly one is in-index; otherwise keep the lower CIK. Dropped rows are in `work/events_dup_accessions_dropped.parquet` (137 rows).

## Timing columns

`acceptance_utc` is the SEC `acceptanceDateTime` parsed as UTC (verified against EDGAR headers). `acceptance_et` is that instant in `America/New_York` (tz-aware in the final file).

Using the NYSE calendar (`exchange_calendars` XNYS):

| Flag | Meaning |
|---|---|
| `pre_open` | session day, acceptance before the open |
| `intraday` | session day, at/after open and before close |
| `post_close` | session day, at/after the close |
| `non_session_day` | weekend/holiday (7 events in v1) |
| `timing` | one of the four labels above |
| `session_date` | first NYSE session whose open is **strictly after** acceptance |
| `session_date_0925` | first session whose open−5 minutes is strictly after acceptance (PREREG_sector_lm_5d s5) |

## Exhibit columns (EX-99 press release)

Fetched only for `in_sp500` events in v1 (`ee_exhibits.py`). Source is each accession’s `-index-headers.html` (index.json has filenames but not document TYPE). Selection rules, in order:

1. TYPE in `{EX-99.1, EX-99.01, EX-99.(1), EX-99.1A}` → rule `EX-99.1`
2. Else first EX-99.* whose DESCRIPTION/FILENAME matches press/release/earn/result/quarter/financial → `EX-99.x press-release keyword`
3. Else first EX-99.* → `first EX-99.x`
4. Else → `no EX-99 exhibit` (results may be in the 8-K body; recorded honestly, not dropped)

| in_sp500 rule | n |
|---|---:|
| EX-99.1 | 22,420 |
| first EX-99.x | 1,448 |
| EX-99.x press-release keyword | 760 |
| no EX-99 exhibit | 335 |
| **ex99_url present** | **24,628 / 24,963 (98.66%)** |

Outside-index events have `ex99_rule = "not fetched in v1 (event outside S&P 500 membership)"` and null exhibit fields. Raw headers are write-once under `raw/sec_index_headers/<accession>.html.gz` with `MANIFEST.jsonl`.

## Columns (final parquet)

`cik, ticker_at_event, ticker_source, accession, form, items, filing_date, acceptance_utc, acceptance_et, session_date, pre_open, intraday, post_close, non_session_day, timing, session_date_0925, is_amendment, cluster_n_filings, cluster_has_amendment, cluster_accessions, in_sp500, index_symbols, map_source, sec_name, ex99_url, ex99_filename, exhibit_count, ex99_type, ex99_description, ex99_rule, primary_doc, filing_index_url, acceptance_raw, dataset_version`

## Coverage

See `COVERAGE.md` and `coverage_by_year.csv`. For full-year mapped members, share with ≥ 3 events is ≥ 0.99 every year 2015–2025; 2026 is YTD through 2026-10-30. Unmapped tickers are FRC and SBNY in the years they appear (no usable CIK mapping). Segment-level periodic-filing gaps (possible holdco/predecessor issues) are listed in `work/segment_gaps.csv` (BAX, GEN, KHC, SMCI, TRMB, XRAY) — events for those segments are still included; treat with care.

## Pipeline (reproducible)

```
ee_map.py        → work/member_cik_segments.parquet, work/unmapped.parquet
ee_fetch.py      → raw/sec/*.json.gz (+ MANIFEST)
ee_validate.py   → work/segments_validated.parquet
ee_gaps.py       → work/segment_gaps.csv
ee_build.py      → work/all_202_filings.parquet, work/events_core.parquet
                   (+ merges work/manual_cik_fixes.csv → segments_final)
ee_exhibits.py   → work/exhibits.parquet, raw/sec_index_headers/
ee_finalize.py   → earnings_events_8k202.parquet
ee_coverage.py   → COVERAGE.md, coverage_by_year.csv
```

SEC fair access: User-Agent from env `SEC_USER_AGENT` (default set in `ee_fetch.py`), ≤ 8 requests/s, exponential backoff on 403/429/5xx/timeouts (6 attempts).

## Build notes (2026-11-06)

- Core events and coverage were built 2026-10-30. The exhibit fetch (`ee_exhibits.py`) started then, paused across a machine restart ~2026-11-06 03:43 SGT, and the same orphan PID 183136 resumed at 05:42 SGT and finished at 06:31 SGT (`done 24906` in `work/exhibits.log`). Prior partial `raw/sec_index_headers/` cache was reused; no second fetch was started while it ran.
- Intermittent HTTP 503 and ReadTimeouts were retried per the script; **0** accessions ended as `index-headers unavailable`.
- After the orphan finished, `events_core` had 57 additional in_sp500 accessions (mostly 2015–2018 delistings) that the in-memory run had not seen. They were topped up with the same `ee_exhibits.one` helper (`work/exhibits_topup.log`); exhibits are now 24,963 = all current in_sp500 accessions.
- No trading returns were computed. News-sentiment pre-registration was not touched.

## Hand-off

Ready for Dave (event spine + `ex99_url` for any later EX-99.1 parse; SUE method in `SUE_NOTE.md`) and Victor (timestamp integrity, no returns in this artifact). Pin `SHA256SUMS` before joining outcomes.
