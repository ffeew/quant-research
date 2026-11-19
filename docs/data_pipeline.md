# Data pipeline

Data is **not** included in this repository (vendor licensing). Rebuild it locally:

1. `cp .env.example .env` and fill in `ALPHAVANTAGE_API_KEY` (plus `ALPACA_*`, `FRED_API_KEY`,
   `SEC_USER_AGENT` for the builders that need them); `export $(grep -v '^#' .env | xargs)`.
2. `export QR_DATA_DIR=/path/to/data` (defaults to `./data`, which is git-ignored).
3. `qr datasets` to list builders, then `qr build-data <name>` (or `make build-data DATASET=<name>`).

Packages are grouped by **source**, with fetch -> clean -> build stages inside each:

| Package | Fetchers | Cleaners / QA | Builders |
|---|---|---|---|
| `data/pipelines` (Alpaca, FRED/ALFRED, Ken French, SEC) | `daily_bars`, `extended_bars`, `corporate_actions`, `fomc`, `macro_calendar`, `alfred_store`, `ken_french`, `assets_snapshot`, `update_sp500_index`, `update_vix_vix3m` | `qa`, `price_qa`, `feed_compare`, `delisting`, `delisting_terms` | `total_return`, `universe`, `security_master`, `shares_classes`, `sec_fundamentals`, `earnings*`, `snapshot` |
| `data/alphavantage/*` | `options/fetch_options_history`, `news_sentiment/fetch_av2`, `returns_events/fetch_raw`, `h3_universe/fetch_1a`, `fetch_1b`, `daily_adjusted/fetch_av_h1h2` | `options/dq_options`, `news_sentiment/validate`, `returns_events/split_validate`, `daily_adjusted/crosscheck_av_alpaca` | `news_sentiment/build_clean`, `h3_universe/filter_1a` |
| `data/sec_edgar` | `sec_http`, `fetch_exhibits`, `xbrl_eps` | `pit_period`, `htmltables` | `eps8k_extract`, `run_extract_*`, `finalize_merge`, `sue_build` |
| `data/earnings_events` | `ee_fetch`, `ee_exhibits` | `v2/validate_v2`, `v2_1/validate_v2_1` | `ee_map`, `v2/build_v2`, `v2_1/build_recon_aligned` |
| `data/insider`, `data/news`, `data/etf_distributions` | `news/fetch_news`, `etf_distributions/fetch`, `scripts/data/fetch_form345.sh` | | `insider/build_trades`, `etf_distributions/build` |
| `data/client` | | `staleness` | `desk_data_client`, `earnings_lookup` (readers used by strategies) |

Grouping by source (rather than one flat `fetchers/ cleaners/ builders/` split) keeps each
source's modules together, since they import each other.

Dataset specs: [datasets.md](datasets.md) and [data/](data/).
