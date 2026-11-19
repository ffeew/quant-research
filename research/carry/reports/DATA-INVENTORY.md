# Carry (KMPV 2018): data inventory for Maya's carry track

**Owner:** Maya (Macro Strategist) · **Written:** Fri 30 Oct 2026, ~02:30 SGT (UTC+8) · **Status:** inventory only. **No returns, signals or performance were computed.**
- Method: file listing, `sha256sum -c` on Dmitri's SHA256SUMS files, row/date coverage counts, and as-of spot checks through `ddc.alfred_asof` (store reads only; no live FRED or Alpaca call was needed).
- Script: `research/replications/carry/inventory_check.py` (sha256 `62d61866…bbab`), output `inventory_check_output.json` (sha256 `7109e825…c1be`). Every count below comes from that JSON unless another path is cited.
- **Not opened:** `data/bars/daily/extended/` (sealed trend-v3 holdout). There is also a `data/releases/v1.2/bars/daily/extended/` directory (seen only as a directory name in a file count); it was **not** opened either (see §6).
- Desk data VERSION at check: `v1.1 6e6353ec…a7d1 2026-10-30T01:50:54+08:00` (`data/VERSION`). A `snapshots/20261029T182421Z_v1.2.json` and `releases/v1.2/` also exist, so the snapshot to pin is a question for Dmitri.

## 1. Summary: which legs are feasible now

| KMPV leg | Signal data in store | Tradeable proxy (Alpaca, 2016+ non-extended bars) | Verdict |
|---|---|---|---|
| **Government bond / US Treasury term structure** (yield − short rate + roll-down) | **YES.** Full PIT UST curve 1m–30y, daily, ALFRED vintages, 2004-01 → 2026-10-27 | **YES.** BIL, SHY, IEF, TLT (all shortable/ETB today; L1/L2 liquidity). No IEI, GOVT, VGIT etc. in store | **FEASIBLE NOW** (primary) |
| **FX** (3m rate differential vs USD) | **PARTIAL.** OECD 3m interbank, monthly, PIT vintages, ~42–45 days lag (JP ~70–75); **EZ and GB end 2026-01** | **WEAK.** FXE, FXY, FXB, FXA, FXC, UUP in store; all **< $50M/day (L4)**; **FXE and FXB not shortable** today; **no CHF, NZD, SEK, NOK ETF** in store | **Data-feasible for 5 currencies, not recommended as primary** (cost + shortability + stale EUR/GBP rates). See §3 |
| **Equity index** (dividend yield − local short rate) | **NO dividend yields delivered.** Only ETF cash distributions (ex-dates 2016-06 →) from which a trailing proxy could be built | SPY, EFA, EEM, EWJ, EWG, EWU, EWA, EWC… in store | **NOT FEASIBLE as specified** (proxy only, needs Victor ruling) |
| **Commodity** (futures curve slope / roll yield) | **NO futures curves** (front/second month) in store | USO, UNG, DBC, DBA, GLD, SLV, CPER in store | **NOT FEASIBLE** (no signal data) |
| **Credit** (OAS-based carry) | **PARTIAL.** IG/HY OAS only **2023-10-30 → 2026-10-28** (~3 years) | LQD, HYG in store | **NOT FEASIBLE** for a validated test (STANDARD §2 needs ≥ 10y; §3 needs ≥ 3y OOS) |

Still missing (checked by filename search across the store, excluding the sealed dirs): **dividend yields, commodity futures curves, spot FX**. None is present. (`data/README.md` coverage table line for carry-koijen still reads "NO (futures/rates not in store)"; the rates part is now out of date since §13 landed.)

## 2. Government bond / Treasury term-structure leg

### 2.1 Signal data: `data/macro/treasury/` (README §13, built by `pipelines/alfred_store.py`)
`sha256sum -c` result: **all OK** for both SHA256SUMS files.

| File | sha256 (full, verified) |
|---|---|
| `treasury_vintages_20261030.parquet` | `f124f4a6decb56c8ca06fc4789a7a0afa95117fbaf77cee01c7ac5dd3a187d62` |
| `treasury_pit_first_available_20261030.parquet` | `c3e25e04aa7378674547c562f4dd2cc15c6f85c807968edb3b8d7ed830e924e1` |
| `treasury_series_meta_20261030.parquet` | `a994b70324655c80afa94509963a646585b76f1f0b763f7286b809410e91930e` |
| `treasury_extra_vintages_20261030.parquet` | `572d17bd31699dc28fa1f8f22db84431de593e1e9241a3caf9d0244a00d13cae` |
| `treasury_extra_pit_first_available_20261030.parquet` | `64dd3f79137a1220d09b5fb631dd4bf423274866094190b41d7ead45d5f52602` |
| `treasury_extra_series_meta_20261030.parquet` | `27ab8139f24a3a8108c4e419c24d6d486a42467589b3064d304e738fab217137` |

| Series | Obs start → end | Obs | NaN (first vintage) | pre_alfred rows (last obs) | Revised obs | Genuine median lag (cal. days) | Availability rule (README §13) |
|---|---|---|---|---|---|---|---|
| DGS3MO | 2004-01-01 → 2026-10-27 | 5,954 | 247 | 382 (2005-06-17) | 3 | 1 | realtime_start + 0 bd, 16:30 ET |
| DGS2 | 2004-01-01 → 2026-10-27 | 5,954 | 247 | 382 (2005-06-17) | 3 | 1 | same |
| DGS5 | 2004-01-01 → 2026-10-27 | 5,954 | 247 | 382 (2005-06-17) | 4 | 1 | same |
| DGS10 | 2004-01-01 → 2026-10-27 | 5,954 | 246 | 382 (2005-06-17) | 4 | 1 | same |
| DGS30 | 2004-01-01 → 2026-10-27 | 5,954 | 773 | 0 | 530 | 2 | same; 2004–06 gap backfilled 2020-07-21 |
| T10Y2Y | 2004-01-01 → 2026-10-28 | 5,955 | 245 | 2,621 (2014-01-16) | 3 | 0 | + 0 bd, 17:30 ET |
| DGS1MO, DGS6MO, DGS1, DGS3, DGS7, DGS20 (extra) | 2004-01-01 → 2026-10-27 | 5,954 each | 246–247 | 382 each (2005-06-17) | 1–5 | 1 | same as DGS* |

- **Frequency:** daily (business days; FRED holidays stored as NaN).
- **Point-in-time:** read with `ddc.alfred_asof(series_id, asof_et)`, which uses only vintages with `available_at_et ≤ asof`. A DGS value for day *t* becomes usable after **16:30 ET on t+1** (README §13).
- **pre_alfred:** irrelevant for a 2016+ test (last flagged DGS obs is 2005-06-17; T10Y2Y 2014-01-16, and T10Y2Y is not needed: it equals DGS10 − DGS2).
- **DGS30 check (as-of, via `ddc.alfred_asof`):** June-2004 observations are **0 non-NaN as of 2020-07-01 17:00 ET** and **21 non-NaN as of 2020-08-01**, matching the README's 2020-07-21 backfill note. Irrelevant for 2016+.
- **Curve nodes available for roll-down interpolation:** 1m, 3m, 6m, 1y, 2y, 3y, 5y, 7y, 10y, 20y, 30y.

### 2.2 Tradeable proxies (store bars `data/bars/daily/{adjusted,raw}/`, TR in `bars/daily/total_return/daily_total_return.parquet` sha256 `0590692d765515e0f76f4f6b7360c5ed7be38e2e85a5f91562dbfebcf8a129db`)
Shortability from `assets/snapshots/assets_2026-10-29.parquet` (sha256 `3996cd928f05c391372cc27ed5701ebf1c7a1df54c654845ae1e3a63b49b2809`; **today's flags only**, no history: `data/STATUS.md`). Dollar volume = median of raw close × SIP volume over the last 252 sessions (liquidity only, not a return). Tomas bucket edges from `tca/cost_model.md` §2 (20-day ADV: L1 > $1B, L2 $200M–1B, L3 $50–200M, L4 < $50M); the bucket used in a backtest is the lagged 20-day value as of each date, so the column is indicative only.

| ETF | Index maturity bucket (issuer description, not in store) | Bars | Sessions | Median $ vol (last 252) | Indicative bucket | Shortable / ETB today | Listing (`tca/tca_scripts/etf_listing.json`) |
|---|---|---|---|---|---|---|---|
| BIL | 1–3 month T-bills | 2016-01-04 → 2026-10-28 | 2,721 | $843M | L2 | yes / yes | ARCA |
| SHY | 1–3y Treasuries | same | 2,721 | $310M | L2 | yes / yes | NASDAQ |
| IEF | 7–10y Treasuries | same | 2,721 | $756M | L2 | yes / yes | NASDAQ |
| TLT | 20y+ Treasuries | same | 2,721 | $2,645M | L1 | yes / yes | NASDAQ |
| TIP | TIPS (not nominal curve) | same | 2,721 | $231M | L2 | yes / yes | — |
| AGG, BND | aggregate (mixed credit) | same | 2,721 | $863M / $599M | L2 | yes / yes | — |
| BWX | international govt bonds | same | 2,721 | $8.5M | L4 | **no / no** | — |

- **Not in store:** IEI (3–7y), GOVT, SHV, VGSH/VGIT/VGLT, EDV, ZROZ, SPTL, IGOV. So the 3–7y segment has no proxy, and there is no international-bond carry proxy beyond BWX (thin, not shortable, and no foreign 10y yields in store).
- **ETF effective maturity / duration history is not in store.** A carry signal must therefore pin a representative constant maturity per ETF ex-ante (see PREREG draft §3).
- **History:** 2016-01-04 → 2026-10-28 ≈ 10.8 years, which meets STANDARD §2 (≥ 10y) only barely once signal warm-up is taken out.
- **Seen status (disclosure):** IEF and TLT were in trend v1/v2 on 2017+ (`trend-sleeve/PREREG-v3.md` §2, §9); SHY was in v1 (dropped, §9 item 1); DGS2/DGS10 were used in the curve-slope gate inputs (`research/original/BATCH-MANIFEST.md`).

## 3. FX leg

### 3.1 Signal data: `data/macro/carry/g10_3m/` (OECD MEI `IR3TIB01{cc}M156N`, monthly, %)
`sha256sum -c`: **all OK**.

| File | sha256 (full, verified) |
|---|---|
| `g10_3m_vintages_20261030.parquet` | `95230c091acddcf4610e692dbd501cbde65d07916d70b6043c58301d34f6b885` |
| `g10_3m_pit_first_available_20261030.parquet` | `9dc4c43f1e37267e26ad95460db46b0b3a1c515153f648169d8c3f1cc0313f43` |
| `g10_3m_series_meta_20261030.parquet` | `1403a40b7bef5920b9ff4c0367196654373c346ac866babf255e266f02b29512` |

| cc | Obs start → end | Obs | Vintage rows | Revised obs | pre_alfred (≤ 2013-02) | Genuine median lag (cal. days; `summary_g10_3m_20261030.json` last-3y median) | Last obs as of 2026-10-29 17:00 ET (`alfred_asof`) | ETF proxy in store |
|---|---|---|---|---|---|---|---|---|
| US | 2004-01 → 2026-09 | 273 (1 NaN) | 390 | 116 | 110 | 44 (45) | 2026-09 | funding leg / UUP |
| EZ | 2004-01 → **2026-01** | 265 | 806 | 239 | 110 | 45 (45) | **2026-01** | FXE (not shortable) |
| GB | 2004-01 → **2026-01** | 265 | 1,125 | 193 | 110 | 42 (45) | **2026-01** | FXB (not shortable) |
| JP | 2004-01 → 2026-08 | 272 | 507 | 108 | 110 | 71 (75) | 2026-08 | FXY |
| CH | 2004-01 → 2026-09 | 273 | 1,089 | 255 | 110 | 45 (45) | — | **none** (FXF not in store) |
| CA | 2004-01 → 2026-09 | 273 | 1,425 | 251 | 110 | 43 (45) | — | FXC |
| AU | 2004-01 → 2026-08 | 272 | 690 | 124 | 110 | 42 (45) | — | FXA |
| NZ | 2004-01 → 2026-09 | 273 | 279 | 4 | 110 | 42 (45) | — | **none** |
| SE | 2004-01 → 2026-09 | 273 | 386 | 68 | 110 | 44 (45) | — | **none** |
| NO | 2004-01 → 2026-09 | 273 | 349 | 30 | 110 | 44 (45) | — | **none** |

- **Frequency:** monthly (observation_date = first of month). Availability = realtime_start + 0 bd at 17:00 ET (AU 16:30 ET). Heavily revised (README §13: CH 93% … NZ 1.5%), so **only `alfred_asof` reads are valid**.
- **pre_alfred:** all obs through 2013-02 have estimated availability. Irrelevant for a 2016+ signal.
- **Stale-signal problem:** at a month-end decision the newest usable rate is ~1.5 months old (JP ~2.5 months). For EUR and GBP the newest value is **2026-01**, i.e. 9 months stale today, and README §13 says they "are not substituted". A live EUR/GBP carry signal is not possible from this store.

### 3.2 Tradeable proxies (2016-01-04 → 2026-10-28, 2,721 sessions each)

| ETF | Currency | Median $ vol (last 252) | Indicative bucket | Shortable / ETB today | Cash distributions 2016+ (`corporate_actions/dividends.parquet`) |
|---|---|---|---|---|---|
| UUP | USD index (long USD) | $43.9M | L4 | yes / yes | 7 |
| FXE | EUR | $9.9M | L4 | **no / no** | 47 |
| FXY | JPY | $9.6M | L4 | yes / yes | 0 |
| FXB | GBP | $1.6M | L4 | **no / no** | 51 |
| FXA | AUD | $0.7M | L4 | yes / yes | 97 |
| FXC | CAD | $1.5M | L4 | yes / yes | 79 |

- **Spot FX: not in store.** For an ETF implementation, spot is not strictly needed for returns: the CurrencyShares TR (`ret_total_best`) already includes the deposit interest they distribute. It would be needed to check that ETF returns track spot plus the rate differential.
- **Cost context:** trend v1 found "FX cost 2.5%/yr of NAV from L4 ETFs" and FX was dropped for that reason (`trend-sleeve/PREREG-v3.md` §9 item 1). L4 default round trip ≈ 105.9 bps at a $10k clip (`tca/cost_model.md` §2). FXA at $0.7M/day also puts STANDARD §8's 1%-of-ADV cap near $7k per trade.
- **Verdict:** a long/short FX carry book is not implementable (2 of 5 proxies cannot be shorted; EUR/GBP rates stale). A long-only "high-carry currencies vs cash" variant on FXA/FXC/FXY/UUP is data-feasible, but it would be an extra trial at L4 costs. **Not in the first spec.**

## 4. Equity-index leg
- **Dividend yields: not delivered**, not in store (filename search, and `data/README.md` blockers list).
- **What exists:** ETF cash distributions in `corporate_actions/dividends.parquet` (sha256 `f834766c748e87665d1fdb25ba3ddf19533e74f352943c1d914f80742831454e`) with `ex_date` and `known_as_of_date`. First ex-dates: SPY 2016-06-17 (41 by 2026-09-18); EFA, EEM, EWA, EWJ, EWU, EWC, EWG 2016-06-22 → 2026-06-15 (18–22 each, semi-annual). A trailing-12m distribution yield could be built from about 2017-06. It is backward-looking, not the expected/futures-implied yield that KMPV use; this would be a different signal and needs a Victor ruling before use.
- **Local short rates:** G10 3m (§3) covers US/EZ/GB/JP/CA/AU, with the EZ/GB 2026-01 end. EEM, EWZ, FXI, INDA, EWY, EWT have no local rate in store.
- **Proxies in store:** SPY, QQQ, IWM, DIA, EFA, EEM, EWJ, EWZ, FXI, EWG, EWU, INDA, EWY, EWT, EWA, EWC (all 2016-01-04 → 2026-10-28). EWA **not shortable** today; EWG $59M, EWU $70M, EWA $87M, EWC $98M median $ vol (L3).
- **Verdict:** not feasible as KMPV specify it.

## 5. Commodity and credit legs
- **Commodity:** **no futures front/second-month prices** in store, so no roll-yield signal. Proxies exist only for returns: USO (**not shortable**), UNG, DBC ($21.7M, L4), DBA ($20.7M, L4), GLD, SLV, CPER ($21.0M, L4). The card's main data blocker for Dmitri still stands (`research/papers/carry-koijen-moskowitz-pedersen-vrugt-2018.md`). **Not feasible.**
- **Credit:** `data/sentiment/credit/` (`sha256sum -c` all OK): `credit_vintages_20261030.parquet` `e739c52dff967a5a1c939937af116da4cac1cdcf1d6483e40146e82526bc53c4`, `credit_pit_first_available_20261030.parquet` `738ff1ff2ef8aaecf56607ebd62756c725e9c4baa8ba86cd46de261da37c833e`, `credit_series_meta_20261030.parquet` `ed585a4413946451de9742370d01ddcba1e5fb84f270a9a504ae56699eabbdea`.
  - BAMLC0A0CM: 2023-10-30 → 2026-10-28, 794 obs (10 NaN), 1 revised. BAMLH0A0HYM2: same dates, 794 obs (8 NaN), 0 revised. Daily; available obs t+1 bd at 10:30 ET (realtime_start alone is look-ahead, README §13).
  - Proxies: LQD ($3,314M, L1), HYG ($3,066M, L1), both shortable/ETB.
  - ~3 years total cannot meet STANDARD §2 (≥ 10y) or §3 (≥ 3y OOS plus an IS). A longer proxy (Moody's BAA10Y/AAA10Y, README §13 caveat) is not in store. **Not feasible.**
- **Crypto (KMPV/card option):** excluded by desk rule (DESK_RULES #2, LIMITS H10). Not inventoried.

## 6. Other inputs a carry backtest needs (present)
- RF: `factors/ken_french/ff3_daily.parquet` sha256 `97daa7080a222846661a436cd90ab204f9ab3f261c9341dd102e3524b008f041`.
- VIX for STANDARD §7 regimes: `sentiment/vix/vix_vix3m_daily_20261030.parquet` sha256 `5ec8bca24a4e0b96392f65da384c16bb75393c728054a5bf26c3e56d146235b2` (filter `is_xnys_session`, per its README).
- Cost model: `tca/tca_scripts/cost_model.py` sha256 verified `df67d604489583d36bb1a16dc7ed30c5568b9a17526f450e4c1a335f9fe8eebf` (matches the brief).
- Corporate actions: `corporate_actions/splits.parquet` / `all_actions.parquet` (hash to be pinned with the build).

**Notes for Dmitri / Victor:**
1. A second extended tree exists at `data/releases/v1.2/bars/daily/extended/` (with `yahoo/` and `signoff/` subfolders by file count). I did not open it. The seal probably needs to cover this copy too.
2. `data/STATUS.md` says 49 ETFs, but BWX and CPER also have 2016+ bars in `bars/daily/adjusted/`.
3. `data/VERSION` reads v1.1 while a v1.2 snapshot/release exists; which one gets pinned for carry is open.
