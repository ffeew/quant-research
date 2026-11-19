# $QR_DATA_DIR: desk research data store (owner: the data owner, Data Engineer)

Point-in-time (PIT), source-traceable research data. **No number here is invented.** Every value comes from the named API or page and carries a fetch time. Gaps are listed below instead of being filled in.
Status snapshot for the CIO: `STATUS.md`. Machine-readable run summary (counts, coverage, failures): `manifest.json`. Logs: `logs/`.

- Python env: `$QR_DATA_DIR/.venv` (pandas, pyarrow, exchange_calendars, requests, lxml, tabulate). Lock file: `pipelines/requirements.lock.txt`.
  Desk members should keep their own venvs (e.g. The derivatives researcher: $QR_SCRATCH_DIR/dave_venv) and only *read* these files.
- All writes are atomic: `<file>.tmp.parquet` is written first, then `os.replace` swaps it in. A reader never sees a half-written file.
- Credentials come only from env vars `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY`. They are never logged or stored.
  SEC requests send `SEC_USER_AGENT`. Set it to "<org> <real contact email>" per SEC fair-access policy. The default placeholder works but is not compliant long-term.

## Pre-existing files from other desk members (left untouched)
| path | what it is | note |
|---|---|---|
| `$QR_DESK_DIR/data.json` (CIO, quant.py) | Alpaca **IEX** daily bars, `adjustment=all` (split+div adjusted), ~420 calendar days, ~120 symbols, plus snapshots and BTC/ETH/SOL | Prices are adjusted. **Volume is IEX-only (~2-4% of consolidated)**. Survivor-only universe. |
| `$QR_DESK_DIR/statarb/data/daily_bars.json` (the stat-arb researcher/statarb) | IEX daily bars (2020-07+) | Same IEX volume issue, survivor universe. Use `bars/daily/adjusted` instead. |
| `research/replication/_public_data/` (the derivatives researcher) | Ken French CSV/zip copies, AQR BAB | Superseded by `factors/ken_french/` (parsed, decimal). |

"Bars look unadjusted": `bars/daily/raw/` is **intentionally** unadjusted (as traded). The adjusted set is `bars/daily/adjusted/`, and total returns are in `bars/daily/total_return/`.

## Dataset catalog

### 1. Daily equity/ETF bars: `bars/daily/{raw,adjusted}/<SYMBOL>.parquet`
- **Source:** Alpaca Market Data `GET https://data.alpaca.markets/v2/stocks/bars`, `timeframe=1Day`, **`feed=sip`** (consolidated tape), `limit=10000`, paginated with `page_token`, 100 symbols per request.
  - `raw` = `adjustment=raw`.
  - `adjusted` = `adjustment=all`: splits, cash dividends and spin-offs, back-adjusted **as of the fetch date**. The history is restated when a new action occurs. The incremental job re-pulls a symbol's full history when a new ex-date appears.
- **Account/feed:**
  - Auth OK. SIP historical works. Only the most recent 15 minutes is blocked on this plan (HTTP 403 "subscription does not permit querying recent SIP data").
  - The job caps `end` at the last completed session's 20:00 ET and at now-16min.
  - IEX is not used (see the IEX vs SIP section).
- **Fields:**
  - `symbol`
  - `session_date` (America/New_York trading date)
  - `timestamp_utc` (Alpaca bar timestamp = 00:00 ET of the session, stored as UTC)
  - `open high low close volume trade_count vwap`
  - `adjustment` (raw|all), `feed`, `zero_volume`
  - `asof_mapping` (symbol-mapping date used, former members only), `fetched_at_utc`
- **Coverage:** 2016-01-04 .. 2026-10-28 (last completed session at build time). 772 symbols, 1,853,950 rows per variant.
  - 503 current S&P 500 constituents (Wikipedia snapshot 2026-10-30).
  - 49 ETFs:
    - Broad: SPY QQQ IWM DIA
    - Sector: XLK XLF XLE XLV XLY XLP XLI XLU XLB XLRE XLC SMH
    - Country/region: EFA EEM EWJ EWZ FXI EWG EWU INDA EWY EWT EWA EWC
    - Bonds: TLT IEF SHY LQD HYG TIP AGG BND BIL
    - Commodities: GLD SLV USO DBC UNG DBA
    - FX: UUP FXE FXY FXB FXA FXC
  - 220 former S&P 500 members removed on or after 2016-01-01. **All 220 have Alpaca bars, including delisted/acquired names** (e.g. TWTR to 2022-10-27, CELG to 2019-11-20, SIVB to 2023-03-09). They are queried with `asof=<last membership day - 1>` so Alpaca maps the ticker to the historical company and not to a later company that reused the ticker.
- **Survivorship and ticker-reuse handling:**
  - A former member's series is cut at the first gap of more than 10 NYSE sessions. This was needed for POM, SPLS, NFX, APC, CA, CSRA, DNB and TE: Alpaca appended a different, later company under the same ticker.
  - **Placeholder bars after delisting:** Alpaca keeps emitting bars with volume=0 and trade_count=0 at a carried-forward price after a delisting, sometimes for years, sometimes followed by a new company on the same ticker. Examples: MON after 2018-06-06, INFO after 2022-02-25, EMC, XL, SBNY, SE, ADT, and the CHK/DO/MNK/ESV bankruptcies.
    - Former members are cut at the first run of 5 or more zero-volume bars (`clip_stale_fill`). This removed 16,470 synthetic rows from 11 symbols.
    - Every file has a boolean `zero_volume` column. 933 such rows remain: trading halts, and current members with history from a previous listing, e.g. DOW 2017-09..2019-04 (old Dow Chemical stub before the 2019 spin) and SMCI 2018-08..2020-01 (Nasdaq delisting; OTC prints are not on SIP). **Mask `zero_volume` rows and use membership dates.**
  - Renamed companies continue under their new identity (e.g. ADS continues after it became BFH), because that is the same entity.
  - Current members carry pre-rename history under the new ticker (META includes FB 2016-2022), through Alpaca's default symbol mapping.
- **Knowledge time:**
  - A daily bar is final after the official close (16:00 ET, or 13:00 ET on early-close days) plus the SIP delay. Use bar `t` only for decisions at or after the close of `t`.
  - Late corrections can change volume/vwap slightly. Re-pull the last few days if exactness matters.
  - `adjusted` prices are **not PIT**: they embed future corporate actions. Use them for returns. Use `raw` (plus the corporate actions table) for "price as seen on day t", e.g. price filters and share counts.
- **Update:** `pipelines/daily_bars.py` (incremental; `--full` for a rebuild, `--symbols A,B`).
  - Data is available about 16:20 ET. Recommended run: **07:30 SGT Tue-Sat**. That is 19:30 ET while EDT is in force (until 1 Nov 2026) and 18:30 ET under EST (UTC+8 vs UTC-4/-5), so it is safely after close and late prints year-round.
  - Takes about 1-2 minutes incrementally and about 10 minutes for a full build.

```python
import pandas as pd

adj = pd.read_parquet("$QR_DATA_DIR/bars/daily/adjusted")  # all symbols, one frame
raw = pd.read_parquet("$QR_DATA_DIR/bars/daily/raw", filters=[("symbol", "in", ["AAPL", "SPY"])])
close = adj.pivot(index="session_date", columns="symbol", values="close")
one = pd.read_parquet("$QR_DATA_DIR/bars/daily/adjusted/AAPL.parquet")
```

### 2. Daily total return: `bars/daily/total_return/daily_total_return.parquet`
- Built from raw bars plus Alpaca corporate actions: `ret_total_t = (close_t + div_t) * split_ratio_t / close_{t-1} - 1`, with cash dividends reinvested at the ex-date close. `tr_index` is the cumulative product.
  It is validated against Alpaca's `adjustment=all` close-to-close return (`alpaca_adj_ret`, `abs_diff_bps`):
  - Median difference: 0.25 bp over 1,853,178 validated rows. p99: 4.4 bp.
  - On 20,232 dividend ex-dates: median 0.66 bp, p95 4.2 bp.
  - 802 rows (86 symbols) differ by more than 50 bp (`tr_mismatch_gt50bps`). These are spin-offs (not reinvested in our formula) and corporate actions filed under a historical ticker (e.g. CHK's 1:200 reverse split of 2020-04, now under EXE).
- **Use `ret_total_best` / `tr_index_best`.** These equal the Alpaca adjusted return, which also handles spin-offs. Fall back to `ret_total` where adjusted is missing.
- Other columns:
  - `ret_price`: split-adjusted price return
  - `div_cash`, `split_ratio`, `other_action` (spin-off on that date)
  - `close_raw`, `close_adj`, `open/high/low_adj`, `volume_raw/adj`
- Report: `qa/total_return_validation_<date>.md`. Mismatch rows: `qa/<date>_total_return_mismatch_gt50bps.parquet`.
- Update: `pipelines/total_return.py`. Local only, recomputed in full, about 10 s. Run after `daily_bars.py` and `corporate_actions.py`.

```python
tr = pd.read_parquet(
    "$QR_DATA_DIR/bars/daily/total_return/daily_total_return.parquet",
    columns=["symbol", "session_date", "ret_total_best", "tr_index_best", "tr_mismatch_gt50bps"],
)
R = tr.pivot(index="session_date", columns="symbol", values="ret_total_best")
```

### 3. Corporate actions: `corporate_actions/{splits,dividends,stock_dividends,all_actions}.parquet`
- **Source:** Alpaca `GET /v1/corporate-actions`, all types, for universe symbols, window 2016-01-01 .. today+120d.
  - Alpaca filters on `process_date`, which can trail the ex-date by about a month, so the window looks ahead.
  - The pull is de-duplicated on Alpaca `id`.
- **Counts:** 20,649 cash dividends (586 symbols, ex-dates 2016-01-04 .. 2027-01-06 incl. announced), 110 forward / 29 reverse / 1 unit splits, 100 cash mergers, 92 stock mergers, 28 stock+cash mergers, 43 spin-offs, 80 name changes, 1 stock dividend.
- **Fields:**
  - Splits: symbol, type, ex_date, record_date, payable_date, process_date, old_rate, new_rate, split_ratio (= new/old), cusips, id
  - Dividends: symbol, ex_date, record_date, payable_date, process_date, rate ($/share), special, foreign
  - `all_actions` adds merger, spin-off and name-change fields (acquirer/acquiree symbols, rates, cash_rate, effective_date, old/new symbol).
- **Knowledge time:** `known_as_of_date` = min(ex_date, process_date). Alpaca does **not** provide the declaration/announcement date, so this is conservative for dividends: they are usually declared weeks before the ex-date.
- **Known gaps:**
  - 7,810 dividends lack record and payable dates (mostly older records).
  - **Merger records start in 2020-04**, so pre-2020 deal terms are missing.
  - Actions recorded under historical tickers can be missed when keyed by the current ticker.
- Update: `pipelines/corporate_actions.py` (full refresh, about 80 s).

### 4. Universe and PIT S&P 500 membership: `universe/`
- `universe.parquet`: 772 symbols.
  - Fields: `role` (sp500_current | etf | sp500_former_since_2016), Alpaca asset status/exchange, `security`, `cik`, and **`gics_sector`, `gics_sub_industry`**.
  - GICS fields come from the Wikipedia snapshot. They are the **current classification, not point-in-time** (`gics_asof_date`), and are null for former members.
- `sp500_current.parquet`: Wikipedia "List of S&P 500 companies" snapshot (symbol, security, GICS, HQ, date_added, CIK, founded).
- `sp500_changes.parquet`: Wikipedia "Historical components of the S&P 500" changes table. 412 rows, 1976-07-01 .. 2026-10-06, 247 rows since 2016.
- `sp500_membership.parquet`: **PIT membership intervals** `[start_date, end_date)` per ticker.
  - Rebuilt by walking the changes table backwards from today's list. A change is effective at the open of `effective_date`.
  - `start_known=False` means the name was a member since before the earliest recorded change. `start_date_filled` uses 1976-07-01 as the lower bound.
  - Reconstructed counts are 503-508 at every month-end since 2016. This is plausible: the index has 500 companies and ~503 share classes.
- `sp500_monthend_members.parquet`: convenience panel (date, symbol), every business month-end 2016-01 .. 2026-10. 130 dates, mean 505 names.
- `sp500_membership_anomalies.parquet`: 26 rows where the table is internally inconsistent. Almost all are ticker renames that the Wikipedia table does not record (FB vs META, PCLN vs BKNG, JEC vs J, COG vs CTRA, RE vs EG, FLT vs CPAY, SATS...), and most are pre-2016.
- `delisting_returns.parquet`: terminal returns for the 120 names whose bars stop before the last session (see §5).
- Source HTML is archived in `universe/raw/` (dated).
- **Caveats:**
  - Wikipedia is crowd-sourced. It is not S&P's official record (S&P DJI historical constituents are paid).
  - Membership uses the ticker at the time of the change, except for current members (current ticker).
  - S&P 400/600: only **current** lists are available (`reference/sp400_current.parquet` 400 rows, `sp600_current.parquet` 603 rows). The Wikipedia pages have no complete change history, so **S&P 1500 PIT membership is not available**.
- Update: `pipelines/universe.py` (about 5 s; re-run weekly or after index changes).

```python
mem = pd.read_parquet("$QR_DATA_DIR/universe/sp500_membership.parquet")


def members_on(d):
    d = pd.Timestamp(d).date()
    ok = (mem.start_date_filled <= d) & (mem.end_date.isna() | (mem.end_date > d))
    return set(mem.loc[ok, "symbol"])


panel = pd.read_parquet("$QR_DATA_DIR/universe/sp500_monthend_members.parquet")
```

### 5. Delisting / terminal returns: `universe/delisting_returns.parquet`
- For each name whose bars end before the last session, the table records the last raw close and the deal terms from Alpaca merger corporate actions (acquiree = symbol, effective within -10..+45 days of the last bar):
  - Cash deals: `terminal_value` = cash.
  - Stock deals: ratio x acquirer raw close on the first session on or after the effective date.
  - Stock+cash deals: the sum of both.
  - `terminal_return = terminal_value/last_close - 1`.
- Results: 120 names. 47 matched (median terminal return +0.1%). 3 have no acquirer price (`acquirer_price_missing`, e.g. a CVR-type acquirer symbol). **70 are unmatched** (`no_deal_in_alpaca_CA`). The `suspect` flag (|terminal return| > 15%) is kept for future runs; 0 rows are flagged now. In the earlier run, the DO 2024 cash-only leg was flagged, but DO is now cut at its 2020 bankruptcy suspension.
- Unmatched names are mostly pre-2020 deals, because Alpaca merger history starts in 2020-04. They also include failures and bankruptcies (SIVB, FRC, SBNY, BBBY). Their terminal returns are **null, not imputed**.
- `approximate=True` on every row: the calculation ignores the time to payment, CVRs, elections and proration.
- Update: `pipelines/delisting.py`.

### 6. Earnings announcements: `earnings/`
- `edgar_8k_202.parquet`: **SEC EDGAR 8-K / 8-K/A with Item 2.02** ("Results of Operations"), from `data.sec.gov/submissions`.
  - 25,869 filings, 594 symbols, 2016-01-04 .. 2026-10-29.
  - `acceptance_datetime_utc` is the exact moment the filing became public. It is the **PIT knowledge time** (`knowledge_time_utc`).
  - `timing` from acceptance time in ET: BMO (<09:30) 13,076, AMC (>=16:00) 11,675, DURING_MKT 1,118.
  - Caveats: the press release can precede the 8-K by minutes. Item 2.02 is also used for pre-announcements and restatements.
- `nasdaq_calendar.parquet`: Nasdaq earnings calendar (`api.nasdaq.com/api/calendar/earnings?date=`), every weekday 2016-01-04 .. today+30d.
  - 159,565 rows, 5,068 tickers, 607 universe tickers.
  - Fields: report_date, time (pre-market / after-hours / not supplied), eps (actual), epsForecast (consensus), surprise %, noOfEsts, fiscalQuarterEnding, marketCap.
  - **Not PIT for EPS, consensus or marketCap**: they are shown as of the fetch, consensus vintage unknown.
  - The `time` field is often "time-not-supplied" historically. 1 date failed (2026-02-19). Raw JSON is cached in `earnings/raw/nasdaq/`.
- `earnings_events.parquet`: combined events for universe names, 26,778 events / 608 symbols.
  - EDGAR is preferred when both sources have an event within ±3 days. Nasdaq-only events get a conservative knowledge time (BMO 07:00 ET, AMC/unknown 16:05 ET).
  - `first_tradable_session`: the first session whose open reflects the news.
  - Scheduled future events are included (`source=nasdaq_scheduled`, 235 rows).
- **Gaps:**
  - Former members are covered mainly via Nasdaq. EDGAR coverage of former members is being extended with the ticker-CIK map; re-run `earnings.py --source edgar`.
  - No PIT consensus. Compute SUE from EDGAR/XBRL EPS with a seasonal random walk.
- Update: `pipelines/earnings.py` (EDGAR about 4 min, Nasdaq about 6 min with cache). Daily, together with the bars job.

### 7. Fundamentals and shares outstanding (SEC XBRL): `fundamentals/` *(build in progress at the time of writing; see manifest)*
- Source: `data.sec.gov/api/xbrl/companyfacts/CIK*.json` for every universe CIK.
- `xbrl_facts.parquet`: long table (symbol, cik, taxonomy, tag, unit, value, period_start/end, fy, fp, form, filed, accn, frame).
  - `knowledge_date` = `filed`. `available_session` = the first NYSE session **after** the filed date (conservative, since the time of day is unknown).
  - All restated versions are kept, so as-of joins on `available_session` are PIT.
  - Tags: Revenues/RevenueFromContract..., CostOfRevenue/COGS, GrossProfit, OperatingIncomeLoss, NetIncomeLoss, CFO, Assets, AssetsCurrent, LiabilitiesCurrent, Liabilities, Cash, ShortTermBorrowings, DebtCurrent, LongTermDebt(Current/Noncurrent), D&A, StockholdersEquity (+NCI), PreferredStockValue, dividends and buybacks paid, EPS basic/diluted, weighted shares, R&D, SG&A, tax, interest, inventory, receivables, PP&E; dei EntityCommonStockSharesOutstanding, EntityPublicFloat.
- `shares_outstanding.parquet`: dei cover-page shares and us-gaap balance-sheet shares, PIT by filed date. `multi_class` flags GOOGL/GOOG, BRK, FOX, NWS etc. Companyfacts drops dimensional (per-class) facts, so those values can be partial.
- `market_cap_daily.parquet`: raw close x the latest cover-page shares known before that session. This is an approximation: shares are stale between filings and partial for multi-class issuers.
- Banks/insurers use different line items. Tag choice per field (Revenues vs RevenueFromContract...) is left to the researcher, and every tag is kept.
- Update: `pipelines/sec_fundamentals.py` (about 10 min). Weekly is enough; daily during earnings season.

### 8. Factors: `factors/ken_french/<set>_{daily,monthly}.parquet`
- Source: Ken French Data Library CSV zips (mba.tuck.dartmouth.edu). Raw zips are archived by date in `factors/ken_french/raw/`.
- Sets:
  - `ff3`: Mkt-RF, SMB, HML, RF. 1926-07 .. 2026-09-30.
  - `ff5` (2x3): + RMW, CMA. 1963-07 .. 2026-09.
  - `mom`: Mom.
  - `st_rev`: ST_Rev.
  - `lt_rev`: LT_Rev.
- **Values are decimal returns** (the CSV percent is divided by 100). `date` = trading day (daily) or month-end (monthly). Only the main table is kept; annual sub-tables are dropped.
- PIT: the library is updated with a lag of about 1-2 months and is **revised between vintages** (CRSP updates), so keep the dated zips for reproducibility.
- Update: `pipelines/ken_french.py`, monthly (about 20 s).

```python
ff = pd.read_parquet("$QR_DATA_DIR/factors/ken_french/ff5_daily.parquet").merge(
    pd.read_parquet("$QR_DATA_DIR/factors/ken_french/mom_daily.parquet").drop(columns="source_file"), on="date"
)
```

### 9. FOMC calendar: `macro/fomc_meetings.parquet`
- Source: federalreserve.gov `fomccalendars.htm` (2021-2027) and `fomchistorical<YYYY>.htm` (2016-2020). 104 rows: 93 with a statement link, 8 unscheduled/one-day actions (e.g. 2020-03-03, 2020-03-15, 2025-08-22 notation vote), 9 scheduled future meetings (through 2027-12).
- Fields: meeting_start/end, statement_date, statement_url, has_press_conference, `sep` (projections meeting, 2021+), minutes_date (2021+), unscheduled, status, statement_time_et (14:00 for scheduled meetings; null for unscheduled), knowledge_time_utc.
- Scheduled meeting **dates** are public more than a year ahead, so they are PIT-safe as a calendar. Statement *content* is known at 14:00 ET.
- Update: `pipelines/fomc.py` (weekly).

### 10. Alpaca asset flags (borrow): `assets/snapshots/assets_<ET date>.parquet`
- `GET /v2/assets?status=all&asset_class=us_equity`: 33,509 assets with shortable, easy_to_borrow, marginable, tradable, fractionable, status. 668 universe names matched, 613 shortable/ETB today.
- **History starts 2026-10-29 ET and cannot be backfilled.** Run daily (pre-open, e.g. 08:00 ET = 20:00/21:00 SGT, or with the 07:30 SGT job). Alpaca exposes no borrow fees.
- Update: `pipelines/assets_snapshot.py`.

### 11. Reference: ticker-CIK map with history (for the sentiment researcher): `reference/`
- `ticker_cik_map.parquet`: ticker, cik, entity_name, valid_from, valid_to, source, match_method, confidence, in_universe. 12,048 rows / 10,593 tickers. Sources, in order of preference:
  - `wikipedia_sp500_cik`
  - `sec_company_tickers` (current only)
  - `edgar_submissions` (tickers on each CIK)
  - `alpaca_name_change`: old to new ticker, with the switch date as valid_to/valid_from. Example: **MMC to MRSH on 2026-01-14, CIK 62709**. Also FB to META on 2022-06-09.
  - `efts_name_search`: EDGAR entity search on the Wikipedia security name for former members, confidence=medium, valid range = first..last Alpaca bar.
- Coverage: 722 of 772 universe tickers resolved. Unresolved: the ETFs (not needed) and 15 former members (BMS BRCM DISH DPS EMC ESRX FLIR GAS HES HOT PBCT PCP RTN TSS WYN; name search ambiguous).
- valid_from/valid_to are best-effort; null = unknown/open.
- `cik_former_names.parquet`: EDGAR `formerNames` (name, from, to) per CIK. 582 rows.
- `sp400_current.parquet`, `sp600_current.parquet`: current lists only (not PIT).

```python
# for the sentiment researcher: ticker -> CIK valid on a date (prefer high confidence)
ref = pd.read_parquet("$QR_DATA_DIR/reference/ticker_cik_map.parquet").dropna(subset=["cik"])


def cik_for(ticker, d):
    d = pd.Timestamp(d).date()
    r = ref[ref.ticker == ticker]
    r = r[(r.valid_from.isna() | (r.valid_from <= d)) & (r.valid_to.isna() | (r.valid_to > d))]
    return r.sort_values("confidence").cik.iloc[0] if len(r) else None  # 'high' < 'medium' alphabetically
```

### 12. QA reports: `qa/`
- `qa_report_<date>.md` (`pipelines/qa.py`). Latest run 2026-10-30, after ticker-reuse and stale-fill clipping (1,853,950 rows per variant). Flag files from earlier runs that day are in `qa/superseded/`.
  - 0 duplicate (symbol, session) rows.
  - 0 non-positive or inconsistent OHLC rows.
  - 0 bars on non-session dates.
  - 0 missing sessions inside any symbol's bar range (vs the Alpaca `/v2/calendar` NYSE calendar).
  - 933 zero-volume rows (halts, previous-listing stubs; see §1). Before clipping there were 7,085.
  - Raw |ret|>40%: 242. 94 fall exactly on a split ex-date (unadjusted splits, as expected in raw). 148 are other moves, e.g. CHK 2020-21, BBBY 2021-23, GME 2021, CVNA 2022-23.
  - Adjusted |ret|>40%: 141. No split-like jumps remain. The large negative ones include separation/spin days where the adjusted series does not net out the distribution, e.g. APTV 2017-12-05 (Delphi Technologies spin), AA 2016-11-01 (Alcoa/Arconic separation), ARNC 2020-04-01, CNX 2017-11-29, and CTVA 2026-10-01 (-83.8%, not yet investigated). Check against corporate actions before using them as signals.
  - Raw vs adjusted factor changes >0.2% not on a known CA ex-date: 1,745. These are dividends Alpaca has not yet put in the CA feed (ex-date passed, process_date in future) and actions under historical tickers.
  - 120 symbols end before the last session. All are delisted/acquired/failed former members. The 11 Alpaca-"active" ones (ADT, CAM, CSRA, EMC, NFX, PCL, POM, SBNY, SE, SPLS, TE) are tickers that are now reused or still carry placeholders.
- `feed_compare_<date>.md/.parquet`: IEX vs SIP study.
- Flagged-row parquet files: `<date>_<raw|adjusted>_<check>.parquet`.

### DEPRECATED / OUT OF SCOPE: crypto `bars/daily/crypto/`
`BTC_USD.parquet`, `ETH_USD.parquet` (Alpaca `/v1beta3/crypto/us/bars`, UTC calendar-day bars 2021-01-01..2026-10-28, 2,127 rows each) were pulled before the 2026-10-30 scope change. **Crypto is out of scope.** The files are left in place but are not maintained, and `pipelines/crypto_bars.py` is not part of the daily job. Convention, for the record: 24/7 market, 1Day bar = 00:00-23:59:59 UTC, `bar_date` = UTC date.

## IEX vs SIP: why only SIP is used (`qa/feed_compare_2026-10-30.md`)
Sample of 22 liquid stocks/ETFs, 2016-2026:
- IEX volume is a **median 3.4%** of SIP consolidated volume over the last 12 months (QQQ 1.5% .. KO 6.2%). It was about 2.0-2.3% in 2020-2024.
- IEX bars only exist from 2018-11 at the earliest (median start 2020-07).
- IEX close vs SIP close: median |diff| 1-2 bp, p95 3-17 bp.
- Consequence: ADV, turnover, volume-surprise and liquidity filters computed from IEX data (`$QR_DESK_DIR/data.json`, `statarb/data/daily_bars.json`) understate volume by about 30x and are noisy. Prices are close but not identical.
- SIP works for all history older than 15 minutes on this account. Only real-time SIP needs a paid plan.

## Pipelines (`pipelines/`, all idempotent; run with `$QR_DATA_DIR/.venv/bin/python`)
| script | output | cadence | runtime |
|---|---|---|---|
| `universe.py` | universe/*, membership, GICS | weekly | 5 s |
| `corporate_actions.py` | corporate_actions/* | daily, before bars | 80 s |
| `daily_bars.py` | bars/daily/{raw,adjusted} (incremental; `--full`, `--symbols`, `--refresh-delisted`) | daily | 1-2 min (full ~10 min) |
| `total_return.py` | bars/daily/total_return | daily, after bars | 10 s |
| `qa.py` | qa/qa_report_<date>.md | daily, last | 15 s |
| `earnings.py` | earnings/* (`--source edgar|nasdaq|both`) | daily | 5-10 min |
| `assets_snapshot.py` | assets/snapshots | daily | 5 s |
| `delisting.py` | universe/delisting_returns | weekly | 10 s |
| `sec_fundamentals.py` | fundamentals/* | weekly (daily in earnings season) | ~10 min |
| `reference.py` | reference/* | weekly | 3 min |
| `ken_french.py` | factors/ken_french | monthly | 20 s |
| `fomc.py` | macro/fomc_meetings | weekly | 2 s |
| `feed_compare.py` | qa/feed_compare | ad hoc | 25 s |
| `crypto_bars.py` | DEPRECATED | - | - |
| `alfred_store.py` | macro/treasury, macro/carry/g10_3m, sentiment/credit (frozen dated ALFRED vintages; `python alfred_store.py treasury g10_3m credit treasury_extra`) | weekly (daily for treasury/credit if needed); each run writes new dated files | ~1-2 min |

Suggested daily order: corporate_actions, then daily_bars, total_return, assets_snapshot, earnings, qa. Run it at **07:30 SGT Tue-Sat** (US close + about 3.5 h; robust to the 1 Nov 2026 DST change). No schedules are configured; Daniel sets routines.

## Blockers / not freely obtainable
- **Macro release calendar (CPI/NFP/GDP/PCE/ISM), vintage-aware.**
  - bls.gov returns HTTP 403 to scripted requests. Future BLS schedules are readable in a browser, but the historical release dates are only in PDF filenames.
  - bea.gov/news/schedule works but covers the current year only.
  - FRED/ALFRED now works (key available since 2026-10-30; see "FRED / ALFRED loader"). Release dates are available via `ddc.fred_release_dates(release_id)`, but the vintage-aware calendar has not been built yet. That is the next step; it is no longer blocked.
- **Point-in-time GICS** (S&P/MSCI, paid). We only have the current classification.
- **Official S&P index history and S&P 400/600 PIT membership** (S&P DJI, paid). The S&P 500 table is Wikipedia-based.
- **Consensus EPS PIT / I/B/E/S** (paid). Nasdaq consensus has an unknown vintage.
- **Borrow fees / historical shortability.** Alpaca exposes only current flags, so history starts today.
- **Pre-2020 merger terms** for delisting returns (Alpaca CA starts in 2020-04). Could be built from SEC 8-K/S-4/DEFM14A filings, but that needs per-deal parsing.
- **Intraday bars** (1-5 min SIP) are available from Alpaca but not yet pulled. This is the next step, not a blocker.
- **Alpaca news** (for the sentiment researcher's sentiment) is available via `/v1beta1/news` but not yet pulled.
- **Real-time SIP** needs a paid Alpaca plan. Historical SIP is fine.

## Paper data-requirement coverage (from research/REGISTRY.md + replication/DATA_REQUESTS_dave.md)
Legend: COVERED = in store now; PARTIAL = usable with caveats; NO = not in store.
| paper (owner) | needs | status |
|---|---|---|
| blitz-huij-martens-2011 residual momentum (the derivatives researcher) | adjusted SIP bars, PIT S&P 500 incl. former, FF3 daily/monthly, borrow flags | COVERED: bars, membership, FF. PARTIAL: borrow (from today) |
| blitz-huij-lansdorp-verbeek-2013 residual reversal (the stat-arb researcher) | adjusted daily TR bars, FF3 daily, borrow | COVERED: TR bars, FF3/5, ST_Rev. PARTIAL: borrow flags from today; NO: fees |
| avellaneda-lee-2010 PCA/ETF residuals (the stat-arb researcher) | adjusted bars stocks + sector ETFs, borrow | COVERED (11 SPDRs+SMH from 2016; XLRE from 2015-10, XLC from 2018-06). PARTIAL: borrow |
| gatev 2006 / rad-low-faff 2016 / do-faff 2010 & 2012 pairs (the stat-arb researcher) | adjusted bars, industry classification, borrow fees | COVERED: bars. PARTIAL: GICS is current only. NO: borrow fees |
| lou-polk-skouras 2019 overnight/intraday (the stat-arb researcher) | adjusted open and close | COVERED: adjusted open/close daily; intraday bars NO (next step) |
| tadi-kortchemski 2021 crypto pairs (the stat-arb researcher) | crypto | OUT OF SCOPE (crypto dropped) |
| crypto-tsmom-liu-tsyvinski-2021 (Maya) | BTC/ETH daily | OUT OF SCOPE (crypto dropped; deprecated files exist) |
| frazzini-pedersen-2014 BAB (the derivatives researcher/PC) | adjusted daily returns, market, RF | COVERED (bars, FF RF/Mkt). AQR BAB copy in the derivatives researcher's _public_data |
| moskowitz-grinblatt-1999 industry momentum (the derivatives researcher) | sector ETF history >10y, PIT GICS | PARTIAL: ETFs from 2016 only in store (Alpaca SIP starts 2016); GICS current only |
| jegadeesh-1990 ST reversal (the derivatives researcher) | daily returns, FF ST_Rev | COVERED |
| novy-marx-2013 gross profitability; AFP-2019 QMJ; sloan-1996 accruals (the derivatives researcher) | PIT fundamentals with filing dates, market cap | PARTIAL: XBRL companyfacts (filed-date PIT, 2014+ filings) and market_cap_daily (approx.); bank/insurer tags and multi-class caveats |
| bernard-thomas-1989 PEAD; martineau-2022 (the derivatives researcher/sentiment researcher) | earnings dates+timing, EPS actuals, consensus | COVERED: dates/timing (EDGAR PIT), EPS actuals (XBRL, Nasdaq). PARTIAL: consensus (Nasdaq, not PIT) |
| jegadeesh-kim-krische-lee-2004 rec changes (the sentiment researcher) | analyst recommendations | NO (paid: I/B/E/S) |
| cohen-malloy-pomorski-2012 insiders (the sentiment researcher) | Form 4 filings, ticker-CIK map | PARTIAL: ticker-CIK map COVERED; Form 4 not pulled (free on EDGAR, next step) |
| ke-kelly-xiu-2019 / price-2012 call tone (the sentiment researcher) | news text / call transcripts | NO (Alpaca news is pullable, transcripts are paid) |
| greenwood-sammon-2025 index effect (the sentiment researcher) | S&P add/drop dates + announcement dates, bars | PARTIAL: effective dates COVERED; announcement dates NO (Wikipedia has effective date only) |
| tsmom-moskowitz 2012; trend-century 2017 (Maya) | cross-asset ETF adjusted bars 15y+, T-bill | PARTIAL: 49 ETFs from 2016 only (Alpaca limit); BIL plus FF RF as T-bill; pre-2016 needs another source |
| carry-koijen 2018 (Maya) | rates curves, futures, dividend yields | NO (futures/rates not in store); dividends for ETFs COVERED |
| pre-fomc-drift-lucca-moench-2015 (Maya) | FOMC timestamps, intraday SPY | PARTIAL: FOMC calendar COVERED 2016-2027; intraday SPY NO (next step) |
| macro-announcement-premium-savor-wilson-2013 (Maya) | macro release calendar, SPY/IEF/TLT/BIL TR | PARTIAL: TR COVERED; release calendar BLOCKED (see Blockers) |
| daniel-moskowitz-2016; barroso-santa-clara-2015 (the risk manager) | SPY daily 2y+, momentum factor daily | COVERED (SPY TR, FF Mom daily) |
| khandani-lo-2011 (the risk manager) | fundamentals B/M, E/P, earnings surprise | PARTIAL (XBRL + earnings events) |
| moreira-muir-2017, ledoit-wolf-2004, HRP-2016, beta-estimation (PC) | 10y+ clean PIT daily returns, factors | COVERED (10.8y SIP from 2016-01; FF factors back to 1926/1963) |
| garleanu-pedersen-2013 (PC) | per-name costs/borrow | PARTIAL: SIP volume/vwap/trade_count; no borrow fees |
| kaminski-lo-2014 stop-loss (the risk manager) | daily returns | COVERED for ETFs/stocks; the paper's futures data NO |
| frazzini-israel-moskowitz-2018, almgren-chriss, perold, ATHL (the TCA owner) | SIP volume/ADV, intraday for impact | PARTIAL: SIP daily volume/vwap COVERED; intraday/quotes NO |
| The validator's references (HLZ, DSR, PBO, McLean-Pontiff) | none (methodology) | n/a |

The derivatives researcher's numbered requests:
1. SIP adjusted+raw incl. former members: COVERED.
2. PIT membership per date, start_known resolved: COVERED (`start_date_filled`, monthly panel).
3. Delisting returns: PARTIAL (47 matched 2020+; pre-2020 null).
4. PIT shares/market cap: PARTIAL (XBRL dei, approx.).
5. Daily asset snapshots: COVERED from 2026-10-29 forward.
6. FF factors: COVERED.
7. PIT fundamentals: PARTIAL.
8. PEAD earnings: COVERED dates/timing/EPS, PARTIAL consensus.
9. PIT GICS: NO (current only).

## Shared data client (`lib/desk_data_client.py`)
**Rule for every desk agent: read history from the local store, and make any live Alpaca market-data call
(`https://data.alpaca.markets/...`: bars, quotes, trades, snapshots, news, corporate actions) only through this client.**
The desk shares one Alpaca key (free plan: 200 req/min for the whole key). Direct `requests.get` calls from several agents are what cause the HTTP 429s.

```python
import sys

sys.path.insert(0, "$QR_DATA_DIR/lib")
import desk_data_client as ddc

df = ddc.get_daily_bars(["AAPL", "SPY"], "2020-01-01", "2026-10-29", adjustment="all")  # or "raw"
```
It works from any desk venv: it needs only the stdlib, pandas and pyarrow, plus `requests` for live calls (no new dependencies, so the lock file is unchanged). `statarb/.venv` has no `requests`: local reads work there, but live calls raise a clear ImportError.

- `get_daily_bars(symbols, start, end=None, adjustment="all"|"raw")` returns long format, the store's columns plus `source` (`local`/`api`).
  - Reads `bars/daily/{adjusted,raw}/<SYM>.parquet` first and never re-fetches history that is on disk.
  - Calls the API only for (a) sessions after the store's coverage end (`ddc.store_coverage()`, the last SPY session) and (b) symbols with no local file.
  - Symbols whose local series ends before the coverage end (delisted or former members) are **not** extended from the API, because the ticker may now belong to a different company.
  - Today's still-open session is dropped unless `include_partial=True`.
  - If the API's `adjustment=all` close on the seam day differs from the stored one (a new corporate action restated history), a warning goes into `df.attrs["warnings"]`. Wait for the pipeline's full re-pull before relying on that seam.
- Intraday: `ddc.get_minute_bars(syms, start, end)`, `ddc.get_hour_bars(...)` and `ddc.get_intraday_bars(syms, start, end, timeframe="5Min")`.
  - Naive times are read as America/New_York. A bare date as `end` means the end of that day.
  - `end` is capped at now-16 min (the free plan has no SIP data for the last 15 minutes), floored to 5 min.
  - Results include pre- and post-market bars.
- Any other endpoint: `ddc.alpaca_get(path, params)` or `ddc.alpaca_get_paginated(path, params, items_key="bars"|"news"|"quotes"|...)`. Pagination follows `next_page_token`.
- **Throttle:** one token bucket shared by every process on the box.
  - State is kept under a `fcntl` lock in `.cache/ratelimit/alpaca_data.state.json`. The default is 150 req/min with a burst of 10; override with env `DESK_ALPACA_RPM` / `DESK_ALPACA_BURST`.
  - On 429 and 5xx it backs off exponentially with full jitter and honors `Retry-After` / `X-RateLimit-Reset`.
  - A 429, or `X-RateLimit-Remaining` <= 3, pauses **all** client processes until the key's reset time.
  - A request ledger (epoch, pid, path; no params or headers) is written to `.cache/ratelimit/alpaca_data.requests.log`.
- **Cache:** `.cache/http/<2 chars>/<sha256(url+params)>.json`, with each page cached separately.
  - Requests whose `end` is more than 1 day in the past are cached forever. Anything else has a TTL of 300 s (`DESK_ALPACA_CACHE_TTL`, or `ttl=` per call).
  - `use_cache=False` bypasses the cache. `ddc.purge_cache(older_than_days=30)` cleans it up.
- **Credentials:** read from `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` and sent only as headers. They are never logged, cached or written. Error messages carry only the status, the path and the response body.
- **Scripts with their own HTTP code** (including future runs of `pipelines/*.py`, which use `common.get`) should either call `ddc.alpaca_get(url, params)` in place of their own GET, or at minimum take a shared token before each data-API request:
  ```python
  sys.path.insert(0, "$QR_DATA_DIR/lib")
  import desk_data_client as ddc

  ddc.throttle().acquire("my_script")  # then do the existing requests.get(...)
  ```
  The bucket covers market data (`data.alpaca.markets`) only. Trading-API calls (`paper-api.alpaca.markets`, e.g. `/v2/calendar`, `/v2/assets`) are not routed through it.

### FRED / ALFRED loader (same file, `lib/desk_data_client.py`)
- **Key:** read from env `FRED_API_KEY`, or from `~/.secrets/fred_api_key` if the env var is missing.
  - It is sent only as the `api_key` query parameter, which is the only way FRED accepts it.
  - It is stripped from cache keys, cached records, the request ledger and error messages.
  - A logging filter scrubs it from urllib3/requests DEBUG URL logs.
- **Throttle:** its own cross-process bucket (`.cache/ratelimit/fred.*`), separate from Alpaca's.
  - Default 100 req/min with a burst of 10 (FRED allows 120/min); override with env `DESK_FRED_RPM` / `DESK_FRED_BURST`.
  - Backoff and the shared pause on 429/5xx work as for Alpaca. A 429 pauses every client for at least 20 s.
- **Cache:** same layout as Alpaca (`.cache/http/`), keyed on the URL and params with `api_key` removed.
  - Vintage requests whose `realtime_end` is more than 1 day in the past are kept forever. Everything else expires after 1 h (`DESK_FRED_CACHE_TTL`).
- **Functions:**
  - `fred_series(id, start, end)`: latest values. FRED `'.'` becomes NaN.
  - `alfred_vintages(id, start, end)`: every vintage of each observation, with `realtime_start`/`realtime_end`.
    - Uses output_type=1. FRED allows at most 2000 vintage dates per request, so the real-time axis is split into chunks of 1900 vintage dates and re-merged.
  - `fred_vintage_dates(id)`, `fred_series_info(id)`, `fred_release_dates(release_id)` (e.g. 18 = H.15), and the raw `fred_get` / `fred_get_all`.
- **Point-in-time reads from the local store**, which is how Maya and every other reader should consume the data:
  - `alfred_asof(id, asof_et)` gives the value of each observation as known at `asof` (naive = New York time), using only vintages with `available_at_et <= asof`.
  - `alfred_first_available(id)` gives the "as first available" view.
  - `alfred_store(id)` gives all stored vintages.
  - A series that is not in the store is pulled live, with conservative end-of-day availability.

```python
import sys, pandas as pd

sys.path.insert(0, "$QR_DATA_DIR/lib")
import desk_data_client as ddc

y10 = ddc.alfred_asof("DGS10", "2022-04-04 17:00")  # what was known at 17:00 ET that day
hy = ddc.alfred_asof("BAMLH0A0HYM2", pd.Timestamp("2026-10-29 22:30", tz="Asia/Singapore"))
```

### 13. ALFRED vintage datasets (Maya: curve / carry / credit): frozen, dated, sha256-verified
Built by `pipelines/alfred_store.py`; observation start 2004-01-01. Every run writes **new dated, read-only (0444) files**. Earlier files are never overwritten. Check them with `sha256sum -c SHA256SUMS_<group>_<YYYYMMDD>.txt`.

| group | dir | series | rows (vintages / obs) | coverage |
|---|---|---|---|---|
| treasury | `macro/treasury/` | DGS3MO DGS2 DGS5 DGS10 DGS30 T10Y2Y | 36,273 / 35,725 | 2004-01-01 .. 2026-10-27 (T10Y2Y .. 10-28) |
| treasury_extra (optional) | `macro/treasury/` | DGS1MO DGS6MO DGS1 DGS3 DGS7 DGS20 | 35,742 / 35,724 | 2004-01-01 .. 2026-10-27 |
| g10_3m | `macro/carry/g10_3m/` | IR3TIB01{US,EZ,GB,JP,CH,CA,AU,NZ,SE,NO}M156N (OECD MEI 3m interbank, monthly, %) | 7,046 / 2,712 | 2004-01 .. 2026-09 (EZ, GB .. 2026-01; JP, AU .. 2026-08) |
| credit | `sentiment/credit/` | BAMLC0A0CM (IG OAS), BAMLH0A0HYM2 (HY OAS) | 1,589 / 1,588 | **2023-10-30** .. 2026-10-28 only |

- **Files per group** (`<g>` = group, `<D>` = YYYYMMDD in SGT):
  - `<g>_vintages_<D>.parquet` is the full vintage table.
  - `<g>_pit_first_available_<D>.parquet` holds the first vintage of each observation.
  - `<g>_series_meta_<D>.parquet` holds FRED metadata, `last_updated`, vintage counts and lag statistics.
  - `SHA256SUMS_<g>_<D>.txt`, `summary_<g>_<D>.json`, and the QA report `qa/fred_<g>_qa_<D>.md`.
- **Fields:**
  - `series_id`, `observation_date`, `value` (NaN = FRED `'.'`, e.g. a holiday)
  - `realtime_start`, `realtime_end` (date; 9999-12-31 = current)
  - `is_current`, `is_first_vintage`, `n_vintages`, `revised` (more than one vintage), `lag_days`, `lag_bdays`
  - `pre_alfred`, `available_at_et`, `available_at_sgt`, `available_at_et_strict`, `availability_method`, `availability_time_et`
- **Availability convention** (ALFRED vintages carry a date only):
  - **Date** = `realtime_start`, the day FRED posted the value. **Offset and time of day** are measured empirically per series. Each series' FRED `last_updated` timestamp (an exact time in US Central) is compared with the date of its newest vintage. The difference in business days is applied to every vintage, and the time is converted to ET and rounded **up** to the next 30 min.
    - DGS* (H.15): `realtime_start` + 0 bd at **16:30 ET**. Last update 15:16 CT = 16:16 ET. The lag from observation to first vintage is a median of **1 business day** (2012+; 2 bd in 2007-2011, 3 bd in 2006), so the value for day t is usable after 16:30 ET on t+1.
    - T10Y2Y: + 0 bd at **17:30 ET**. Since 2019, FRED posts it the **same day**, at about 17:03 ET (lag 0 bd; 1 bd in 2014-18).
    - ICE BofA OAS: **+1 bd at 10:30 ET**. FRED back-dates these vintages to the observation date, but the update actually lands at about 09:26 CT the next morning. Using `realtime_start` alone would be look-ahead.
    - OECD monthly interbank rates: + 0 bd at 17:00 ET (16:30 for AU). `observation_date` is the first of the month. The first release comes about **42-45 days** later (mid next month), and about 70 days later for JP. The last-3y median is 45 days (JP 75).
  - **`pre_alfred` rows.** These are observations whose first vintage is the series' first ALFRED vintage date and that lag by more than 10 days (daily) or 120 days (monthly). ALFRED only started tracking then, so `realtime_start` is not the publication date.
    - DGS*: obs 2004-01 .. 2005-06, first vintage 2005-06-28. T10Y2Y: obs 2004 .. 2014-01, first vintage 2014-01-27. G10: obs 2004-01 .. 2013-02, first vintage 2013-06-03.
    - For these rows, `available_at_et` is an **estimate**: observation date + the series' typical first-release lag, which is the median of the earliest 250 genuine releases for daily series (3 bd for DGS*, 1 bd for T10Y2Y) and the overall genuine median for monthly series (42-70 days).
    - `available_at_et_strict` (= `realtime_start`-based) is kept for strict use. The estimate rule is recorded in `availability_method`.
  - The time of day is based on one empirical sample per series (the latest update). FRED posting times vary, so treat it as an estimate. `available_at_sgt` is the same instant in SGT.
- **Revisions** (share of observations with more than one vintage):
  - DGS* 0.02-0.08% (1-5 observations per series, e.g. DGS10 2014-01-14 2.77 -> 2.88, 2022-04-01 2.38 -> 2.39). T10Y2Y 0.05%.
  - **DGS30 8.9%.** The 30y was not published from 2002-02 to 2006-02. FRED backfilled those 2004-2006 observations on **2020-07-21**, so `alfred_asof` correctly returns NaN for them before that date.
  - G10 interbank: heavily revised. Share of observations revised: CH 93%, CA 92%, EZ 90%, GB 73%, AU 46%, US 42%, JP 40%, SE 25%, NO 11%, NZ 1.5%, with up to 10 vintages per observation. **Use `alfred_asof`, never the latest values, for carry backtests.**
  - Credit: IG 1 observation (2025-02-13, published NaN then 0.81), HY 0.
- **QA** (`qa/fred_<group>_qa_<D>.md`):
  - 0 duplicate (series, observation, realtime_start) rows.
  - 0 missing weekdays (daily) or months (monthly): FRED carries holidays as `'.'`, which are stored as NaN. That is 245 NaN rows per DGS series and about 8-9 for the OAS series.
  - The last 60 current values match the no-key `fredgraph.csv` exactly in every series (max abs diff 0, or 4e-16 for EZ), with the same last date.
- **Caveats:**
  - **ICE BofA OAS history on FRED starts 2023-10-30** (`observation_start` = first vintage = 2023-10-30): ICE licensing limits FRED to a rolling ~3-year window, and ALFRED has no earlier vintages. No backfill from any other source has been done. Longer history needs ICE/Bloomberg data or a proxy (e.g. Moody's `BAA10Y`/`AAA10Y` on FRED); a proxy would be flagged separately.
  - The Euro Area and UK OECD 3m series currently end at 2026-01 (the OECD MEI publication lag or discontinuation). They are not substituted.


## Frozen releases (`releases/<version>/`)
The live store is mutable: fixes land in place (v1.0, v1.1, ...). A snapshot hash alone does not freeze content, because the live files can be replaced after hashing. A **release** is a read-only copy (`chmod -R a-w`) of every data file. Its manifest hashes the copies.
| version | top_hash | files | notes |
|---|---|---|---|
| v1.2 | — | 1,939 | first frozen release. Includes bars/daily/raw, security master v1.2b, VIX, index, macro. Earnings captured mid validator fix #2 (final earnings fixes go to v1.3). See `releases/v1.2/RELEASE.md` |
| v1.3 | — | 1,939 | derivatives researcher freeze pin. v1.2 bars unchanged; Fix-2-final earnings (`edgar_8k_202`, `earnings_events`). SIP methodology doc. SUE not included (addendum). See `releases/v1.3/RELEASE.md` |
- Releases v1.0/v1.1 were never frozen. By 02:10 SGT, `earnings_events`, `edgar_8k_202` and `ticker_cik_map` no longer matched the v1.1 manifest, so v1.1 content cannot be reproduced.
- **Policy:** cut a new frozen release after each fix batch (`releases/v1.3/`, ...), never overwrite one, and append to `snapshots/CHANGELOG.md`. Researchers read from `releases/<version>/...` and cite **release version + top_hash**. Verify with the snippet in RELEASE.md.
- **Derivatives researcher batch pin (2026-11-06):** use `releases/v1.3/`. SIP bar definitions: `docs/SIP_DAILY_BAR_METHODOLOGY.md`. SUE table not in v1.3.
```python
R = "$QR_DATA_DIR/releases/v1.2"
raw = pd.read_parquet(f"{R}/bars/daily/raw")
tr = pd.read_parquet(f"{R}/bars/daily/total_return/daily_total_return.parquet")
```

## Staleness reporting (added 2026-11-06 06:15 SGT)
- Module/check: `lib/staleness.py`. It writes one JSON per dataset to `staleness/<dataset>.json`, using the max observation column of the newest parquet (not mtime).
- Check command: `.venv/bin/python lib/staleness.py [dataset...]`. It exits 1 if any dataset is STALE or MISSING.
- Hooked after commit (it never changes a script exit code) into daily_bars.py, total_return.py, assets_snapshot.py, earnings_forward.py, update_sp500_index.py, and alfred_store.py (credit group).
- Release pins (releases/, snapshots/) are not tracked; they are frozen by design.
- **Schedule reality:** there is NO local scheduler (no cron or systemd timers). Only three Grok Bot routines exist (S&P 16:50 ET, next-earnings 06:30 ET, borrow 08:00 ET), and they failed from 10-30 to 11-05 because of missing usage. Nothing else refreshes unless someone runs it. Freshness is not guaranteed.
- 06:14 SGT check: FRESH for index_sp500, bars_daily, total_return, credit_oas (2026-11-04), earnings_forward, and assets_borrow. STALE: vix_vix3m (2026-10-28), which has no build script. Not tracked/stale: earnings_events and corporate_actions (left alone during the validator fixes).
## Immutable component reconciliation (2026-11-06, 06:49 SGT)

### Sentiment researcher 8-K Item 2.02 timestamp component — optional additive only
- `/derived/earnings_events_8k202_v1.parquet` remains a **timestamps/event-spine additive component only**, not a replacement for v1.3 `edgar_8k_202` or multi-source `earnings_events`; not a SUE-ready input, v1.4, return-bearing authorization or a full complete press-release package.
- Immutable addendum: `/derived/earnings_events_8k202_v1_reconciliation/DECISION.md`, `accession_union_diff.parquet`, `reconciliation_summary.json`, `build_reconciliation.py`. Local independent check verified every documented count and SHA256; all five addendum files are mode 0444.
- Canonical parent remains v1.3. Its EDGAR table is event-symbol grain (29,519 rows/28,768 unique accessions); the sentiment researcher is accession grain (31,467). Reconciled union is 31,913: 28,322 shared with exactly equal UTC acceptance and first-open-session fields; 446 v1.3-only = 397 withheld as cluster member + 49 AA/EVHC identity mapping; 3,145 sentiment-researcher-only = 2,807 intentional 2015 extension + 338 requiring lineage review. 131 shared accessions retain CIK alias/display differences; 133 v1.3-only contain an 8-K/A in forms (NOT an assertion of amended public-content timing). These are bounded/known gaps, not silent superset or complete-identity coverage.
- Validator disposition measured from file bytes, the internal review record. ACCEPT INPUT TIMESTAMP TABLE only, not main promotion/SUE. Do not mix cluster-first vs keep-all-actings enumeration policies in one trial; need explicit dual-pin/versioned trial pin when optional component used. v1 files and README remain byte-identical and read-only.
- Future v2 by the sentiment researcher (new immutable paths) must restore/support AA & EVHC lineage, preserve all component CIK aliases, reason-code the diffs and separately audit late/partial siblings/amendments and EX-99 timing/content. First SEC acceptance is not inferred as full release-public evidence. No source table was silently repaired.

### Gate primary-calendar candidate — DATA usable for replay but adoption WITHHELD
- `/earnings/gate/DATA_ADOPTION_WITHHELD.md` is the controlling disposition for this candidate: **Historical disposition of the original rejection**—the risk manager has since re-verified the corrected gate (signed2026-11-06~06:54 SGT); exact state below: **pin replacement/cutover is false** and old accepted Risk pin registry is unchanged. Tables 20261105 retain exact observed hashes (`earnings_events`, `nasdaq_calendar`, sidecar) for independent replay, not for Risk adoption. Future-bias note: future rows are schedules/estimates, not proof a company announced a forthcoming date. `fetched_at_utc` is provenance of my fetch, not company knowledge time; EDGAR acceptance belongs to realised filings, not advance confirmation of a future earnings release.
- Portfolio-construction lead currently found 20 forecasts incorrectly marked confirmed by consumer branch, skipping estimate buffer; 11 names fell outside required warning/entry window and three had late/wrong exits. Previous 0 stale-fail-safe count was source-freshness behavior ONLY, not an all-clear. Raw hashes still validate content integrity, not policy correctness. Do not point production construct at candidate; no construct/target rerun by the data owner. Full fail-safe state/CIO hold remains until consumer correction + independent tests + risk manager Risk re-verification. Unknown AVGO stays unknown; BAC/JNJ carried-forward records are explicitly NOT freshly rechecked.
- `/earnings/next_earnings/` sidecar stored dates are unbuffered. Estimated short/entry window = 15 sessions before earliest candidate; long-buffer release = 5 sessions before; preserve minimum actual candidate dates and exact exit contracts in consumer, not hack dates stored in data. Required future explicit forecast-vs-company-confirmed metadata does not authorize retroactively altering pinned candidate bytes.


- **Signed gate correction / exact pin + read-only shadow CLOSED:** `risk/2026-11-06-earnings-gate-reverification.md` initial / measured (parent-stated recorded separately). Owner final (shadow); sidecar pin. Evidence 7/14/70/3; targets unchanged; hold/tradable false. Status `EXACT_GATE_SIDECAR_READ_ONLY_SHADOW_CLOSED_NO_PRODUCTION_TRADING`; scope `read_only_shadow_closed_exact_gate_sidecar`; `eval_safety=false`; no production construct/trades. Historic `earnings/gate/DATA_ADOPTION_WITHHELD.md` retained.

### Routine/staleness source truth — current override of earlier statements above
- Routine records enabled as of 06:49 SGT: S&P ~16:50 ET, earnings evidence (forward+gate-only+sidecar) ~06:30 ET weekdays, borrow ~08:00, daily bars/total return ~19:00, credit ~11:30, VIX ~22:00 (all NY local dates except VIX clock schedule). The earlier statement "only three routines" was true at 06:15 and is superseded. Routines are not a local croned scheduler; do not assume silently successful runs; inspect current run result.
- Actual scripts: `/pipelines/daily_bars.py`, `/pipelines/total_return.py`, `/pipelines/update_vix_vix3m.py`, `/pipelines/alfred_store.py`, `/pipelines/earnings_forward.py`, `/pipelines/earnings_gate_refresh.py` (gate calendar only; sidecar parameterized future build not yet supported), `/pipelines/update_sp500_index.py`, `/pipelines/assets_snapshot.py`. Primary gate orchestrator is data candidate only, not production approval; routine earns source observations even when not adopted. Some reported prior routine errors were lacking plan usage, NOT data/source faults; don't relabel.
- `lib/staleness.py` current sha256 must be read live, not copied from earlier revisions. It also contains a pointer/written-hash `earnings_gate_calendar` record: no overwritten timestamps or lexicographic date shortcut, observation-time basis `fetched_at_utc` aligned to NYSE session. If record says FRESH or STALE it refers narrowly to source freshness, **not** estimated/confirmed gate correctness or investor permission.
- 06:41 verified snapshot: VIX latest published source session Nov4; Nov5 source session pending (no fabricated observation). S&P and forward-earnings through Nov5 fresh; next-sidecar fresh 94; exact-gate read-only shadow closed (no production trading). TSC parked with NO full/creeping backfill. No future data artifact/output generated by these documentation notes.
