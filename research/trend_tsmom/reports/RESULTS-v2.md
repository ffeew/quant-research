# RESULTS v2: unlevered, lower-cost ETF trend sleeve (pre-registered)

**Owner:** Maya (Macro Strategist) · **Run:** Fri 30 Oct 2026, 01:37 SGT · **Spec:** `PREREG-v2.md` §1–§8 plus Amendments A1 (Victor) and A2 (STANDARD.md items). Both amendments were logged before the run.
**One command:** `.venv/bin/python run_v2.py` (unit checks: `.venv/bin/python -m tests.test_v2_engine`, 23/23 PASS) · **Outputs:** `outputs_v2/` (v1 `outputs/` untouched)
**Hashes:**
- outputs_v2 directory: `1a19555e870896865cd3af470cbc4647138d2fa8f6f1748db7980d43f6a0039d`. This is the sha256 of `outputs_v2.MANIFEST.sha256`, the per-file sha256 list with sorted paths.
- Data build: TR `0590692d…29db`.
- Cost model: Tomas v1.1 `df67d604…eebf`, unchanged from the pre-registration.
- Code: combined `69f39bf7…0337`.
- PREREG-v2.md at run time: `db90f920…bda`.
- Full values are in `outputs_v2/meta.json`.

Crypto remains excluded by desk decision.

## Stage A verdict (V1 PRIMARY): **FAIL**
V1 misses 2 of the 7 Stage A items. Under PREREG §5 this means **the v2 sleeve fails**:
- No secondary variant is promoted.
- Nothing is re-tuned.
- Nothing trades.

Even a clear would only have meant "eligible for Stage B" (A1.1), not a pass.

| # | Criterion (PREREG §5 + A1) | V1 value | Met |
|---|---|---|---|
| 1 | Net Sharpe ≥ 0.40 | **0.395** | **NO** (near miss; not rounded) |
| 2 | Tomas flag PASS (net > 0 at 2× costs AND cost ≤ 50% of gross) | PASS: net at 2× costs +2.66%/yr; costs are 10.5% of gross | yes |
| 3 | Net max drawdown ≥ −15% | **−16.4%** | **NO** |
| 4a | Net Sharpe excluding 2022 > 0 | 0.34 | yes |
| 4b | Net return > 0 in ≥ 2 of 3 subperiods | 3/3 | yes |
| 5 | DSR (gross-dispersion, N = 24) ≥ 0.50 | 0.62 | yes |
| 6 | Mechanical: gross ≤ 1.00 at every close; no short in a non-shortable ETF | true (max gross 1.000; USO never short) | yes |

**Against `validation/STANDARD.md` the result would also fail:**
- There is no OOS: 2017–2026 was seen in v1.
- Net Sharpe 0.395 is below the 0.5 bar.
- DSR is 0.62, below 0.95.
- t = 1.23, below 2.8.
- PBO is 0.49, above 0.20.

## What changed vs v1
Removing leverage did what the cost attribution predicted:

| | v1 baseline (lb12_M, re-run on this build) | v1 implementable (2× cap + shortable) | **V1 PRIMARY** |
|---|---|---|---|
| Gross return / Sharpe | 6.8% / 0.61 | 3.7% / 0.49 | 3.4% / 0.44 |
| Net return / Sharpe (t) | 2.3% / 0.20 (0.63) | 1.8% / 0.24 (0.75) | **3.0% / 0.395 (1.23)** |
| Cost drag (trading + borrow) | 4.5%/yr | 1.9%/yr | **0.35%/yr** (0.26 + 0.09) |
| Turnover (one-way) / average cost | 15.5× / 26 bps | 6.9× / 24 bps | **3.2× / 8.2 bps** |
| Break-even cost | 44 bps | — | 105 bps (≥ 2× assumed cost ✓) |
| Average / max gross | 3.19× / 5.92× | 1.95× / 2.11× | 0.94× / 1.00× |
| Net max drawdown | −25.6% | −18.2% | −16.4% |
| Correlation to SPY (daily / monthly) | 0.04 | −0.05 | 0.11 / −0.09 |

V1 also had:
- an average holding period of about 7 months and an average net exposure of +0.21×;
- 106 days with forced cap trims;
- 1,155 asset-rebalance decisions held inside the band.

The largest single trade was 0.22% of 20-day ADV at $1M NAV, so STANDARD §8 (≤ 1%) is met.

Net Sharpe roughly doubled because costs fell by more than 90%. But the gross edge also halved, and what is left is not statistically distinguishable from zero (Sharpe SE 0.32).

## Secondary variants (descriptive only; cannot rescue the sleeve)
| Variant | Gross ret / SR | Net ret | Net vol | **Net SR** (t) | Net max DD | Turnover | Avg cost (bps) | Corr SPY (d) | Tomas |
|---|---|---|---|---|---|---|---|---|---|
| **V1 PRIMARY** (CORE-L12, L/S where shortable, M) | 3.4% / 0.44 | 3.0% | 7.6% | **0.395** (1.23) | −16.4% | 3.2× | 8.2 | 0.11 | PASS |
| V2 long/flat | 4.3% / 0.47 | 4.0% | 9.2% | 0.439 (1.37) | −22.1% | 3.0× | 7.9 | **0.63** | PASS |
| V3 CORE + UUP | 2.3% / 0.35 | 1.8% | 6.8% | 0.266 (0.83) | −17.2% | 3.2× | 13.6 | 0.12 | PASS |
| V4 quarterly | 2.7% / 0.32 | 2.4% | 8.4% | 0.290 (0.90) | −17.6% | 1.9× | 7.7 | 0.37 | PASS |
| V5 BROAD-exFX (16) | 3.2% / 0.43 | 2.6% | 7.4% | 0.357 (1.11) | −19.4% | 3.1× | 14.8 | 0.03 | PASS |

What the secondaries show:
- **No variant would clear Stage A.** Every one has max DD worse than −15%. V2 has the highest net Sharpe but a −22% drawdown, and its 0.63 SPY correlation makes it mostly a vol-managed long book.
- **UUP (V3) cost more than it added**, consistent with v1's FX attribution.
- **Quarterly rebalancing (V4) cut turnover but lost more gross** (slower signal response).
- **Breadth (V5) did not pay** once its L3/L4 names were included.

**Benchmarks:**
- The long-only CORE-L12 book with the same sizing, cap and band earned 5.3% net, Sharpe 0.57, max DD −22.1%, SPY correlation 0.81.
- SPY excess TR: Sharpe 0.74, max DD −34.0%.
- V1's net Sharpe is **below** the long-only benchmark built from the same machinery. Its value case rests on diversification (SPY correlation of about 0.1) and crisis behaviour, not on standalone Sharpe.

## Deflated Sharpe (V1 net Sharpe 0.395; T = 2,449 days; daily skew −0.51, kurtosis 6.71; PSR vs 0 = 0.89)
V[SR] always comes from the 24 logged trials; only N varies (A1.2).

| Dispersion | σ(trial SR), annualised | N = 24: SR0 / DSR | N = 30: SR0 / DSR | N = 50: SR0 / DSR |
|---|---|---|---|---|
| **gross** (Stage A gate) | 0.149 | 0.295 / **0.62** | 0.309 / 0.61 | 0.339 / 0.57 |
| all-net | 0.734 | 1.453 / 0.0005 | 1.521 / 0.0002 | 1.670 / 0.0000 |

- At Victor's N = 30, DSR is 0.61 in the gross version and about 0 in the all-net version. Both are far below 0.95.
- The all-net version is degenerate: the v1 fast and levered trials lost up to −2.4 Sharpe net, which inflates the dispersion. It is reported as A1.2 requires.

## PBO via CSCV (A1.4)
Setup: S = 16, C(16,8) = 12,870 splits, on the T × 24 daily matrix (`outputs_v2/returns_matrix_*_Tx24.csv`).
- **Net: PBO = 0.49** (median logit +0.08).
- **Gross: PBO = 0.79** (median logit −1.66).

**Reading:** picking the in-sample best of these 24 trials is about a coin flip out-of-sample on a net basis, and worse than a coin flip gross. This fails STANDARD's < 0.20 bar. Caveat: the matrix mixes the levered v1 trials with the unlevered v2 trials, so the in-sample "best" is often a v1 configuration. PBO here measures the whole research path, not V1 alone. It was reported, not gated, at Stage A.

## Stability (A1.3; V1 only; not trials, not decision inputs)
Requirement: net Sharpe > 0 and ≥ 50% of V1's (i.e. ≥ 0.198).

| Check | Net ret | Net SR | Net max DD | Turnover | Meets |
|---|---|---|---|---|---|
| lookback 9m | 3.6% | 0.500 | −21.0% | 3.6× | yes |
| lookback 15m (starts 2017-05-01, warm-up) | 1.7% | 0.220 | −24.0% | 3.0× | yes (barely) |
| vol target 8% | 2.9% | 0.407 | −13.6% | 3.2× | yes |
| vol target 12% | 2.8% | 0.361 | −18.0% | 3.3× | yes |

- All four meet the requirement, but the lookback dimension is not flat: Sharpe runs 0.50 → 0.395 → 0.22 for 9 → 12 → 15 months.
- **Forking-path warning:** the 8% vol-target run would have met criteria 1 and 3 (0.407, −13.6%). It is explicitly **not** a decision input and is **not** grounds for re-registering V1 at 8%. Doing so would be choosing on results.

**SPY 200-day MA regime** (regime known at t−1):

| Regime | Share of days | Net ret | Net SR |
|---|---|---|---|
| SPY above its 200dma | 83.5% | +3.8% | 0.55 |
| SPY below its 200dma | 16.5% | −0.8% | −0.07 |

- No regime has Sharpe below −0.5, which satisfies STANDARD §7.
- The sleeve did **not** earn its keep when SPY was below its 200dma. However, in SPY's 12 worst-decile months (average −7.7%), V1 averaged +0.86%.

**Calendar years** (net, compound): 2017 +6.8%, 2018 −3.2%, 2019 −2.0%, 2020 +2.7%, 2021 +0.9%, 2022 +7.6%, **2023 −7.5%**, 2024 +3.1%, 2025 +10.4%, 2026 YTD +9.5%.
- The largest year (2025) is 35% of total net P&L, under STANDARD's 40% flag.
- 2025 and 2026 YTD together are 67%, so results are back-loaded.

**Long vs short legs:**

| Leg | Average exposure | Gross contribution | Sharpe |
|---|---|---|---|
| Long | 0.58× | +4.7%/yr | 0.70 |
| Short | 0.37× | −1.3%/yr (plus 0.09%/yr borrow) | −0.25 |

The short leg lost money (mostly IEF/TLT and equity shorts).

**Per-asset net, ex-borrow** (`outputs_v2/per_asset_v1.csv`):

| ETF | Net (bps/yr) |
|---|---|
| QQQ | +93 |
| EEM | +57 |
| EWJ | +39 |
| USO (long/flat) | +37 |
| IEF | +36 |
| SPY | +29 |
| GLD | +28 |
| TLT | +13 |
| SLV | +5 |
| EFA | +5 |
| IWM | −30 |

**Non-trial cost sensitivities (V1):**

| Sensitivity | Net SR | Net max DD |
|---|---|---|
| Base | 0.395 | −16.4% |
| 2× costs | 0.361 | −16.6% |
| MOC venue | 0.414 | −16.3% |
| $10M NAV | 0.386 | −16.4% |
| Borrow 50 bps | 0.383 | −16.5% |
| **Borrow 1%/yr (STANDARD floor)** | **0.359** | −16.7% |
| Band off | 0.356 (turnover 3.8×) | −16.6% |

The band saved about 0.6× turnover and added about 0.04 to net Sharpe.

## Caveats / limitations
1. **Not out-of-sample.** 2017–2026 was fully seen in v1, and the v2 design was informed by v1's attribution (PREREG §1). Stage B on the 2005+ backfill is the real test. `bars/daily/extended/etf_total_return_spliced.parquet` exists but was **not read**.
2. **Shortability look-ahead (A1.5).** Today's (2026-10-29) Alpaca shortable/ETB flags are applied to the whole history. USO is long/flat for this reason. Historical borrow availability is unknown.
3. **Data build moved between pre-registration and run.** The TR file's sha256 was `87d09bb9…` at pre-registration (01:29 build) and `0590692d…` at run time (rebuilt 01:32:38 SGT). Per PREREG §2, all 19 v1 trials were re-run on the new build. They reproduce the v1-logged Sharpes to 3 decimals (e.g. baseline net 0.203, gross 0.607), so the rebuild did not move these ETFs materially.
4. **Fills** are at the next session's close (lag 1), not STANDARD §2's "next-bar open or worse" open fill.
5. **Borrow** base is Tomas's 25 bps. At STANDARD's 1%/yr floor, net Sharpe falls to 0.36.
6. **No VIX series in the desk store**, so STANDARD §7's VIX regime split is not reported (gap; Dmitri).
7. **Universe** is today's surviving ETFs (no delisted ETFs). STANDARD's 20% survivorship haircut would cut net Sharpe to about 0.32.
8. **Short sample.** 9.7 years gives a Sharpe SE of 0.32. The 0.395 vs 0.40 miss is far inside noise in both directions. The verdict is applied strictly as pre-registered, not because 0.005 is meaningful.
9. **Partial parameter neighbourhood.** Only lookback ±25% and vol target ±20% were perturbed, as A1.3 specified. Band width, cap and EWMA centre of mass were not perturbed, and no joint perturbation was run.
10. **Cost model.** Spreads are bucket defaults, not measured; ETF CA records are missing (TR index used). Both are open with Tomas and Dmitri.

## Files (`outputs_v2/`)
- **Trials and returns:** `trial_log_24.csv` (all 24 trials with configs), `returns_matrix_{net,gross}_Tx24.csv`.
- **Variant results:** `variants_v2.csv`, `stage_a_v1.csv`, `subperiods_v2.csv`.
- **Robustness:** `sensitivities_v1.csv`, `stability_v1.csv`, `dsr_table.csv`, `pbo_cscv.json`, `benchmarks.csv`.
- **V1 diagnostics:** `regime_spy200_v1.csv`, `calendar_years_v1.csv`, `legs_v1.csv`, `per_asset_v1.csv`.
- **V1 detail:** `trades_v1.csv`, `v1_daily.csv`, `v1_weights.csv`, `v1_equity_curve.csv`.
- **Run records:** `meta.json`, `run_stdout.txt`, `unit_checks_output.txt`.
- **Directory hash:** manifest at `../outputs_v2.MANIFEST.sha256`, hash at `../outputs_v2.HASH.txt`.

## Next steps (proposals only; any of them is a new trial and needs a new pre-registration)
- **Stage B:** run the frozen V1 spec unchanged on the 2005+ backfill (needs Dmitri's sign-off on the spliced file). This is the only route to a STANDARD verdict, and it requires DSR ≥ 0.95 and net Sharpe > 0.5.
- **Optional new pre-registration:** a long-only-plus-trend-overlay or vol-target-8% variant would have to be pre-registered as new trials (N → 25+) and judged on Stage B only.
