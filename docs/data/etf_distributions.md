# Issuer-document distribution & split ledger: 9 ETFs (gate G6), built 2026-11-07 SGT

- **Scope:** XLP, XLV, XLU, XLY, XLI, XLK (SSGA / Select Sector SPDR Trust) and IEF, SHY, TLT (iShares / BlackRock). The split question additionally covers all 11 Select Sector SPDRs.
- **Authority:** a bounded build approved via fund manager under Daniel's 18:45 SGT delegation. It is internal research data only, with no trades, returns, signals or outbound messages.
- **Sources:** only public issuer documents and one archived copy of an issuer document.
  - No performance or return pages were fetched, no Yahoo and no vendor price data.
  - The v1.3 corporate_actions files were read only and verified unchanged against the v1.3 MANIFEST.
- **Requests:** 32 HTTP requests between 2026-11-07 14:27:10 and 14:30:08 UTC (22:27–22:30 SGT): 21 returned 200, 10 returned 404 and 1 returned 403. The 403 was retried once and succeeded. Every request is listed in `fetch_log.jsonl` / `FETCH_LEDGER.csv`.
- **Build process:** `fetch.py` → `sources/` (raw bytes, sha256 in the fetch log); `build.py` (sha in MANIFEST) → `ledger/`.
  - The scratch check ran in $QR_SCRATCH_DIR/scratch_ledger, then a single main run followed.
  - The main output is byte-identical to the scratch output.
  - Parquet uses an explicit pyarrow schema, with a CSV twin.
  - Strict readback was performed: the Parquet tables are equal, and the CSV matches column-by-column after casting to the schema.

## Outputs (`ledger/`)

- **`ledger.parquet` / `.csv`:** 616 rows.
  - Each row has: type (CASH_DIST / CAP_GAIN / SPLIT); ex / record / payable / declaration dates; the published amount string plus decimal(18,9); income, STCG, LTCG and ROC component strings; the split ratio; source URL, file and doc sha256; and `date_field_provenance` (JSON naming which document supplied each date field).
  - Declaration dates are null wherever the source does not publish them; none are inferred.
- **`reconciliation_vs_v13.parquet` / `.csv`:** one row per (ticker, ex_date) across the issuer data and the v1.3 `corporate_actions/dividends.parquet`.
- **`split_resolution_sector_spdr_11.parquet` / `.csv`:** the 2025-12-05 split question for all 11 sector SPDRs, compared against v1.3 `splits.parquet`.
- **`build_summary.json`**

## Split resolution (2025-12-05)

- **Sources:**
  - State Street press release dated 2025-11-20 (`sources/split/statestreet_pr_20251120_five_sector_splits.html`);
  - SSGA Japan notice dated 2025-12-03;
  - IRS Form 8937 for each splitting fund, "Date of action December 5, 2025, 2:1 Share Split".
- **Funds that split:** exactly five, XLK, XLY, XLE, XLU and XLB, each **2:1**.
  - Record date: close of 2025-12-02.
  - Payable: after the close of 2025-12-04.
  - First post-split trading day: 2025-12-05.
  - No CUSIP changes.
- **Funds that did not split:** XLF, XLV, XLP, XLI, XLRE and XLC are not in the press release, and their 2025 Form 8937 URLs return 404.
- **v1.3 comparison:** v1.3 has forward splits for exactly those five, with new/old = 2.0, record 2025-12-02 and payable 2025-12-04. **That is 11/11 matches: 5 MATCH_SPLIT and 6 MATCH_NO_SPLIT.** The earlier inventory "discrepancy" was not an error; only five funds split.
- **Splits among the 9 ledger tickers:** XLK, XLU and XLY have the 2025-12-05 split. No other split is evidenced for the 9 tickers from 2016 onward. That is not a proof of no-split: there is no issuer-wide split list.

## Reconciliation vs v1.3 (646 keys)

| status | n | meaning |
|---|---|---|
| MATCH | 403 | ex date and summed amount equal at full published precision; record and payable equal |
| V13_RECORD_NULL\|V13_PAYABLE_NULL | 193 | ex and amount match; v1.3 has null record/payable dates (all rows before 2020); the issuer supplies them here |
| V13_ONLY_NO_ISSUER_ROW | 33 | IEF/SHY/TLT, all 11 of each in 2016: no 2016 iShares summary could be obtained (live 404; the only Wayback capture is a 403) |
| ISSUER_ONLY_MISSING_IN_V13 | 6 | 2016-03-18 dividend for each of the 6 SPDRs (record 2016-03-22, payable 2016-03-29) is absent in v1.3 |
| ISSUER_ONLY_AFTER_V13_CUTOFF | 3 | IEF/SHY/TLT 2026-11-02, after the v1.3 data end of 2026-10-28 |
| AMOUNT_DIFF | 5 | IEF 2020-06-01, 2020-07-01, 2020-10-01 and 2020-11-02, and TLT 2020-12-01: v1.3 has 7 decimal places (…9) where the issuer has 6, a difference of 1e-7 |
| AMOUNT_DIFF\|V13_RECORD_NULL\|V13_PAYABLE_NULL | 2 | IEF 2017-11-01: v1.3 has 0.1643, the issuer 0.164305 (diff 5e-6). SHY 2017-11-01: v1.3 has 0.0784, the issuer 0.078435 (diff 3.5e-5). v1.3 is truncated in both |
| V13_2_ROWS_SAME_EX | 1 | SHY 2021-12-01: two v1.3 rows (0.018007 + 0.031906) against one issuer row of 0.049913; the sum is equal |

No record-date or payable-date conflicts were found where both sides have values.

## Coverage and gaps

- **SPDRs:** ex 2016-03-18 to 2026-09-21. This is the issuer's full history file, with amounts as paid (not split-adjusted).
- **iShares:**
  - 2017-02-01 to 2025-12: annual tax summaries for 2017, 2018 and 2019, via Wayback raw captures of the issuer PDF;
  - 2020–2025: live issuer PDFs;
  - 2026-02 to 2026-11-02: projection of the issuer product-page distribution table, sealed in Phase 1. Only that table was used, the HTML is not copied here, and this is labelled `PRIOR_SEALED_PROJECTION_OF_ISSUER_PRODUCT_PAGE`.
- **GAP iShares 2016:** no issuer document was obtained. 33 v1.3 rows are unverified, and the v1.3 2016-08 distribution is also absent from the store.
- **GAP declaration dates:** null on all 613 distribution rows, because neither the SSGA XLSX nor the iShares summaries publish them. Only the 3 split rows have one: the 2025-11-20 press-release date.
- **GAP STCG for iShares 2020+:** short-term capital gains are not published separately (they are folded into ordinary dividends). No CAP_GAIN rows exist; every LTCG/STCG component in scope is zero or "-".
- **GAP 2026 iShares:** the source is the product-page projection, not an annual summary, and will need restamping when the 2026 summary is published.
- **GAP SPDR 2016-01 to 03:** the first SPDR ex-date in the window is 2016-03-18. No January/February 2016 distributions exist in the issuer file.
