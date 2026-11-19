# News sentiment on Alpaca/Benzinga news: research prototype (cf. Ke, Kelly & Xiu 2019)

Card: `$QR_DESK_DIR/research/papers/ke-kelly-xiu-2019-text-news-sentiment.md` (status: replicating).
This is research only. It places no orders.

## Rerun
```bash
cd $QR_DESK_DIR/equity/news_sentiment
# 1) Fetch news. This is resumable: finished months are skipped and each month is written atomically.
#    Credentials come from env ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY and are never printed.
nohup python3 fetch_news.py --start 2016-01 --end 2026-10 --workers 6 --rpm 180 > fetch.log 2>&1 &
nohup python3 fetch_news.py --symbols alias_symbols.txt --out raw_alias --workers 2 --rpm 15 > fetch_alias.log 2>&1 &
# 2) Score and test. Only months completed in raw/ are analysed.
DESK_OUT=out_pit ../.venv/bin/python news_signal.py > out_pit/run.log                                   # PIT universe (provisional)
DESK_OUT=out_current DESK_UNIVERSE_MODE=current ../.venv/bin/python news_signal.py > out_current/run.log    # survivor comparison
../.venv/bin/python make_results.py                                                                          # -> RESULTS.md
```
- `symbols.txt` holds every ticker in the data owner's point-in-time S&P 500 membership file (861 tickers, current and former).
- `alias_symbols.txt` and `aliases.csv` hold old tickers of renamed members (e.g. FB → META before 2022-06-09). They come from the data owner's `corporate_actions/all_actions.parquet` name_changes. Membership and bars use the current ticker for current members.
- **Throughput:** at about 150 to 180 pages a minute (Alpaca limit 200/min, about 1.9 s latency per page) and roughly 130 pages per month of news, the full 2016-01 to 2026-10 pull takes about 3 hours. The fetcher runs newest month first.
- Universe, bars and benchmark are swappable through env vars. See `../desk_data.py` (`DESK_MEMBERSHIP`, `DESK_BARS_DIR`, `DESK_BENCH`).

## Components (kept separate so each can be tested on its own)
1. **Text sentiment, stock level.** Scored on non-analyst articles only (LM primary, VADER robustness).
2. **Analyst rating changes**, parsed from Benzinga's structured headlines ("X Upgrades/Downgrades Co to ..."): +1 for an upgrade, −1 for a downgrade, averaged per stock-day.
3. **Analyst price-target changes** ("... Raises/Lowers Price Target to $X"): +1 or −1. Headlines carry no prior target, so there is no magnitude.
4. **Sector level.** Each component is averaged over member stocks with a score that day, by GICS sector, and mapped to the SPDR ETFs (XLK XLF XLE XLV XLY XLP XLI XLU XLB XLRE XLC). The test goes long the top-3 and short the bottom-3 ETFs at the open; the rating component uses top-1 minus bottom-1.
   GICS is today's classification from `universe.parquet`, not point-in-time. Former members have no GICS and drop out.

Panels for the validator: `out_*/stock_day_scores.parquet` (symbol, d, text_lm, text_vader, n_text, rating_chg, n_rating, pt_chg, n_pt) and `out_*/sector_day_scores.parquet` (sector, etf, d, text_lm, rating_chg, pt_chg, counts). Session d is the first trading session whose open may use the score.

**X posts are excluded.** X has no historical archive available to us, so it is archive-forward only and cannot be backtested.

## Method
**Sentiment (primary): Loughran-McDonald word lists**, scored on headline plus summary.
- Article score = (P − N) / (P + N), or 0 when no LM word appears.
- Why LM: it is built for financial text. General lexicons mis-score finance words such as liability, tax, cost and crude. Every score is a plain word count, so it is fully transparent.
- Lists: `lexicon/lm_positive.txt` (354 words) and `lm_negative.txt` (2,355 words). They are extracted from the master dictionary bundled in pysentiment2 0.1.1 (about the 2018 vintage). They have **not** been checked against the current SRAF release.
- LM has no negation handling.

**VADER compound** is a robustness variant. It is general purpose and rule-based, and it handles negation and intensifiers.

**Article filter:** keep articles that tag 3 symbols or fewer, which drops market roundups.

**Timing (no look-ahead):** session d receives articles with created_at in [09:30 ET of session d−1, 09:25 ET of session d). The overnight-only variant uses [16:00 ET of d−1, 09:25 ET of d). The trade happens at the **open** of d.
- Returns are open(d) → open(d+1) and open(d) → open(d+5), on split- and dividend-adjusted SIP bars that include delisted names.
- The 5-day results use overlapping daily cohorts.
- DST is handled through America/New_York. Weekend and holiday news rolls to the next session. `out_*/timing_audit_sample.csv` lists 40 sampled articles with their ET timestamp and assigned session.

**Universe:** the stock must be a point-in-time S&P 500 member on d.

**Score per stock-day:** the mean of its article scores.

**Tests (per day):**
- Long-short: equal-weighted long of every stock with score > 0, minus equal-weighted short of every stock with score < 0.
- D10 − D1: decile spread, run on days with at least 30 scored stocks.
- Stats: N days, hit rate, mean, and t clustered by calendar month.

**Costs:** the TCA owner's cost model v1.1 (`src/quant_research/backtest/costs/cost_model.py`).
- Round trip at the open by liquidity bucket, using lagged 20-day dollar ADV: L1 7.65, L2 15.02, L3 33.23 and L4 75.88 bps ($10k clip).
- Each leg is assumed to turn over fully every day, which is conservative. r5 is a 5-day cohort return net of one round trip per leg.
- ETB borrow of 25 bp a year on the short leg.
- A 2x cost stress is also reported.

**Variants:** 36 statistics per universe (see RESULTS.md). There was no tuning beyond these specs.

## Outputs
- `out_pit/`, `out_current/`: results.json, run.log, timing_audit_sample.csv, stock_day_scores.parquet, sector_day_scores.parquet
- `RESULTS.md`: summary.

## OOS lock, pre-registration and audits (added 2026-10-30)
- Validator logged the exploratory results (RESULTS.md, 2025-06 to 2026-10) as **FAIL**. Those 72 statistics count toward N.
- **The 2016-01 to 2025-05 history is a locked hold-out.** `news_signal.py` skips those months unless `PREREG_sector_lm_5d.md` is frozen: its sha256 must be in `PREREG_sector_lm_5d.sha256` and passed as `NEWS_OOS_UNLOCK`. `fetch_news.py` only fetches; nothing runs analysis automatically.
- The pre-registered single test is in `PREREG_sector_lm_5d.md` (currently DRAFT).
- The timestamp and coverage audit is in `DATA_AUDIT.md`. Rerun `audit/ts_internal.py` and `audit/coverage.py` after the fetch; they read metadata only.
- Alpaca's news time filter follows `updated_at`. Edited articles sit in the month of their last edit, but timing always uses `created_at`.

## Turn-5 changes (2026-10-30 ~02:10-02:25 SGT)
- **Desk rule 5:** `fetch_news.py` and `audit/sample_urls.py` now call Alpaca only through `$QR_DATA_DIR/lib/desk_data_client.py` (shared 150/min throttle); `--rpm` and private HTTP removed; default workers 2, running with 1.
- **Hold-out guard:** `$QR_DESK_DIR/equity/holdout_guard.py` seals archive sessions before 2025-06-02 for every design/card script until the sector-LM pre-registration is frozen and its gating run is logged (or a joint unseal). `news_signal.py` additionally stays on the seen sample until the gating run is logged.
- **Pre-registration artefacts:** `prereg_run.py` (draft, not executed; `--check` only), `make_manifest.py` → `PREREG_manifest.txt` (PROVISIONAL until fetch completes). `PREREG_sector_lm_5d.sha256` is intentionally absent until freeze.
- **Audits (metadata only):** `audit/edited_share.py` (drop share under the updated_at rule, coverage floor by month), `audit/coverage_by_size.py` (Benzinga coverage by size tercile). See `DATA_AUDIT.md` §5-§7.

### 2026-10-30 ~02:30 SGT: the validator's decisions (02:24) applied
- N = 153 (sector-LM, breadth, spillover); hype-fade gates at 345 (153 + 192 PEAD) and reports both. +4 VADER-twin trials; +1 R151 (breadth NB7, included: it is in the ±20% grid of R126).
- VADER finance-domain handling: `lexicon/vader_finance_neutral_v1.txt` (sha256 4e1ff542…7d7632; LM 2011 cited words + plurals; removes liability, liabilities, cancer, crude from VADER 3.3.2) applied by `vader_fin.py` (sha256 0b8506ea…a6ca); pinned in `prereg_run.py`.
- All four documents: pre-2024 years count as OOS only after the ≥90% coverage floor is shown from the fetch; verdict capped at CONDITIONAL until the TCA owner's 2-9 Nov opening-auction pilot is in; G9 (2019+) kept.
- Nothing frozen; no returns computed; no hold-out text read.

### 2026-10-30 ~02:35 SGT: TCA owner cost inputs wired in
- Pinned: `tca/ethan_cost_inputs.md` (sha256 67d0ab41…f409432) + all 11 files in `tca/ethan_inputs/` (hashes in `prereg_run.py` TOMAS_FILE_SHA).
- prereg_run.py: per side = max(model, floor 2 bp + full half-spread, TCA owner per-ETF Base); stop exits at continuous cost; whole shares; borrow 1%/yr calendar/360 (2× = 2%), HTB sensitivity 10%/yr; 25 bp reference only; today's ETB flags not used historically.
- All four documents: per-side costs, card cost expectations (labelled expectations, not results), the TCA owner's §4 caveats; uplift as primary entry cost for spillover and hype-fade (normal and 2× reported). N unchanged (153 / 345).

### 2026-11-06 ~06:10 SGT: the validator's 6 Nov decisions applied
- Uplift is the primary entry cost for spillover/hype-fade (normal base = diagnostic); 2× = 2× primary (101 / 105 bps per event, unchanged numbers, relabelled).
- 10%/yr HTB run is a REQUIRED gate (net Sharpe > 0 else FAIL on costs) for spillover and hype-fade single-name shorts; not applicable to sector-LM/breadth (ETF shorts only).
- No trials added: N 153 / 345. CONDITIONAL cap kept. Decision log in each document (A11 / PREREG "Decision log").

### 2026-11-06 ~06:25 SGT: validator 06:09 SGT decision, unknown-borrow gate extended to ETF shorts
- Sector-LM (new gate G11) and revision-breadth (gate 1, A12): 10%/yr borrow on every ETF short must leave net Sharpe > 0, else FAIL on costs. 1% base / 2% sensitivity stay as diagnostics. `prereg_run.py`: HTB_GATE_APPLIES = True. N unchanged (153 / 345). Historical quoted rates, if ever supplied, must be pinned and pre-registered before results.

### 2026-11-06 ~22:30 SGT: §5 control wiring (cost mode; nothing run)
- `prereg_run.py` (current draft sha256 `60fa1a33c0a1cbfc7c94fbb076ac09ed40aa3c7f437c25ef621829af11033b6a`; freeze hash still blank) now has as-of adapters for REV5, MOM12-1, ANNSHARE (v1 event table `d568a60d…6d2e`, strict 09:25 ET) and SUE (strict loader against a PROPOSED schema; `sue_xbrl.parquet` absent, unpinned). They run only after `check(strict=True)`; `--check` reads hashes/metadata only.
- Synthetic tests: `python3 -m unittest discover -s tests -v` (25 pass). Details, contract and blockers: `CONTROLS_WIRING.md`.
- No trials added (N 153 / 345); scoring, sizing, costs, borrow and OOS/seen locks unchanged; no prices, text, tone, returns, EPS or SUE computed.
