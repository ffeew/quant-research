# Opportunistic insider buying — research prototype (Cohen, Malloy & Pomorski 2012)

Card: `$QR_DESK_DIR/research/papers/cohen-malloy-pomorski-2012-opportunistic-insiders.md` (status: replicating).
Research only. No orders.

## Rerun
```bash
cd $QR_DESK_DIR/equity/insider
./fetch_form345.sh 2012 2026        # SEC Insider Transactions Data Sets, skips files already in raw/
../.venv/bin/python build_trades.py  # -> trades.parquet (Form 4 non-derivative P/S lines x reporting owner)
DESK_OUT=out_pit ../.venv/bin/python insider_signal.py > out_pit/run.log                                 # PIT universe (primary, provisional)
DESK_OUT=out_current DESK_UNIVERSE_MODE=current ../.venv/bin/python insider_signal.py > out_current/run.log  # survivor comparison
../.venv/bin/python make_results.py                                                                        # -> RESULTS.md
```
- SEC fair access: declared User-Agent with a contact string, one request at a time with 1 s sleeps (far below 10 req/s).
  SEC serves 2026q2+ from `/files/datastandardsinnovation/...`; the script tries both paths.
- The venv is `$QR_DESK_DIR/equity/.venv` (pandas, pyarrow, vaderSentiment).

## Swapping in Dmitri's files
All universe and price inputs come from `../desk_data.py`. Override them with env vars, with no code edits needed:
`DESK_MEMBERSHIP` (symbol, start_date, end_date), `DESK_UNIVERSE` (symbol, cik), `DESK_BARS_DIR` (`<SYM>.parquet` with session_date, open, close), `DESK_BENCH` (default SPY).
The defaults point to Dmitri's `$QR_DATA_DIR/universe/sp500_membership.parquet`, `universe.parquet`, and `bars/daily/adjusted/`.

## Timing source (no store event dates)
Only the SEC FILING_DATE from the Form 4 bulk sets is used. Dmitri's earnings and event dates are not used.
The position opens at the close of the first trading day of the month after filing. A filing accepted on the last day of month t, even after hours, therefore precedes entry by at least one full session. Intraday acceptance time is not needed for this monthly construction. A daily version would need EDGAR `acceptanceDateTime` per accession.

## Method
1. **Data.** Form 4 originals (not 4/A) for 2012Q1–2026Q3, non-derivative transaction codes P (open-market purchase) and S (open-market sale), one row per transaction line per reporting owner.
2. **Classification** is done per (insider CIK, issuer CIK) at the start of each calendar year Y, using only trade dates in Y-3..Y-1.
   - A pair is **eligible** if it traded in each of the 3 prior years.
   - An eligible pair is **routine** if it traded in the same calendar month in all 3 years. Otherwise it is **opportunistic**.
   - A pair with less than 3 years of history is **unclassified**.
3. **Timing** uses the filing month t (FILING_DATE). Entry is at the close of the first trading day of t+1, so the position starts at least one full session after any filing in month t. Exit is at the close of the first trading day of t+2 (1M) or t+4 (3M).
4. **Universe** is the issuer's point-in-time S&P 500 membership on the filing date (Dmitri's `sp500_membership.parquet`). Issuer CIK is mapped to a ticker by a chain where the first hit wins, using only tickers in the membership file:
   1. Dmitri's `reference/ticker_cik_map.parquet`, CIK → ticker valid on the filing date (valid_from/valid_to). Override with `DESK_TICKER_CIK`. When v2 lands, rerun only `insider_signal.py`.
   2. The `cik` column in Dmitri's `universe.parquet`.
   3. The SEC `company_tickers.json` (current tickers only), cached in `ref/` as a stopgap.
   4. The issuer's own ticker on the filing, used only when no CIK is known anywhere.

   On this run, step 1 resolved 238,616 trade rows and step 4 resolved 4,400. Steps 2 and 3 added none. Known misses are listed in `out_pit/mapping_misses.csv`.
5. **Returns** use split- and dividend-adjusted closes and are measured as excess vs SPY (primary) and vs the equal-weighted point-in-time S&P 500 (secondary). Portfolios are equal-weighted within each monthly cohort. For delisted names, the last close is compounded with the `terminal_return` from Dmitri's `universe/delisting_returns.parquet` (override with `DESK_DELISTING`). Rows flagged `suspect` are skipped. Names with no terminal return use the last close and are listed in `results.json`.
   Adjusted closes reproduce Dmitri's `tr_index_best` (total return) exactly; this was checked on JNJ.
6. **Stats:**
   - Event level: N, hit rate, mean, t clustered by formation month.
   - Cohort portfolios: mean, hit rate, plain t for 1M and Newey-West(2) t for the overlapping 3M horizon.
   - Long-short: opportunistic buys minus routine buys, and opportunistic buys minus opportunistic sells.

## Outputs
- `out_pit/ and out_current/ (results.json)`: all stats plus diagnostics (counts by code and class, CIK vs ticker mapping, filing lag).
- `out_*/events.csv`: one row per stock × filing-month × group, with the forward excess returns.
- `out_*/run.log`
- `RESULTS.md`: a summary of the results.
