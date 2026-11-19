# av_returns_events_20261111 (Marcus, data engineer)
Purpose: daily prices, earnings report dates and sectors for Ethan's sentiment prereg (draft e1f9ee2b). Approved: Daniel 13:29 SGT 11 Nov 2026 (relayed by Jeremy). Plan: PLAN.md.
Raw: raw/{daily,earnings,overview}/<SYM>.json, AV bytes as received (TIME_SERIES_DAILY_ADJUSTED full x51 incl SPY; EARNINGS x50; OVERVIEW x50). raw/SHA256SUMS. Hash-only.
Partitioned (split_validate.py sha 42828576, reviewed by Victor L289, run offline): boundary per Victor 0f2713de: DEV <= 2024-12-31, HOLDOUT 2025-01-01..2026-10-31 (first session 2025-01-02).
- dev/daily_dev.csv, holdout/daily_holdout.csv: symbol,date,close,adjusted_close,dividend,split_coefficient (AV strings verbatim), 2021-03-01..2026-10-31.
- dev/earnings_dev.csv, holdout/earnings_holdout.csv: symbol,fiscalDateEnding,reportedDate,reportTime, split by reportedDate. reportedDate is AV's earnings REPORT date, NOT a verified earnings-call timestamp.
- meta/sectors.csv: Sector, Industry from OVERVIEW = CURRENT snapshot (11 Nov 2026): look-ahead, not point-in-time.
- VALIDATION_DEV.tsv (full), VALIDATION_HOLDOUT.tsv (fail counts only), COUNTS.tsv (row identity), RUN.log.
HOLDOUT: never opened by any agent; hashed and counted only (X2, L288). DEV goes to Ethan only after Jeremy releases it and Victor seals the prereg.
Format: CSV, not parquet (pyarrow not installed; Jeremy agreed).
