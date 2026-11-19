# RESULTS v3: limits-compliant ETF trend sleeve (single pre-registered run)

**Owner:** Maya (Macro Strategist) · **Run:** Fri 6 Nov 2026, 06:21:23 → 06:21:59 SGT · **Spec:** `PREREG-v3.md` (§1–§12; Victor A1–A6, §9.B/§9.C, option-(b) data rules).
**One command:** `.venv/bin/python run_v3.py run` (after one authorised `pin` and a clean `preflight`). Unit checks at run: 106/106 PASS. **Outputs:** `outputs_v3/` (v1/v2 outputs untouched).
**Single-run statement:** this is the one pre-registered v3 execution. No retry, no alternate data, no parameter change. Research only; not a trade.

**Hashes (from `outputs_v3/meta.json` and `outputs_v3.HASH.txt`):**
- outputs_v3 directory: `87acf086fec28c3005f253a4abbeec4ab50505acbaa3d6219a4ad6418423c647` = sha256 of `outputs_v3.MANIFEST.sha256` (23 files; stamped 2026-11-06 06:21:59 SGT).
- PREREG-v3.md at run: `4689e3a411b9f2112fa7eb1c39ba8793225a96724701aefc40f2b0746e7ef2e4` (pinned state; candidate freeze was `c2718d67…4c0c` before the §2 pin wrote the build/CA/diff hashes).
- Data build (v2): `c998ca5c33eee487bbdcdbee929ecc2e003078653c2ec5cf15b905c3f9e0ab78` (`…/signoff/trend_v3_v2_etf_daily_20261030.parquet`; 2005-01-03 → 2026-10-28).
- Corporate-action table: `b415ae397380b6adf287110bdb759afa5ece1f1cde7dd0832d5924993c72fb5e`.
- Substitution diff: `8225dded490c5567ec446d81b9e10d9161ee1225a3f7bc27e94dccc46bd671ee` (72 substituted rows).
- Nasdaq xcheck input: `0a0b01461eda7c11cc7721120c2166e4b3fc801ab648ea2edd9116d6727ec0eb`.
- Reference-source table: `1388e51cdf124667d2e4fb3d60f4a6fb853f63ccb4e816cd3cecfd3dc91c7380`.
- data_spec_v3.json: `cd5553db078ec5626d56788e1b4d558b581a7ebf18e83911bb041771a2ee74c9`.
- Cost model (Tomas v1.1): `df67d604489583d36bb1a16dc7ed30c5568b9a17526f450e4c1a335f9fe8eebf`.
- VIX series: `5ec8bca24a4e0b96392f65da384c16bb75393c728054a5bf26c3e56d146235b2`.
- Full values: `outputs_v3/meta.json`.

**Harness fix (non-trial, pre-run; Victor ruling):** `validation/prereg_rulings/2026-11-06-trend-v3-preflight-fix.md`. Only `tests/test_v3_engine.py` changed. Old sha256 `47e8be7384a1a42d3e091a05296a3a76c0a56abe3ffd081e67b5d24ae7716cc1` → new `f70e21d4492f99da0c51845d268559ab826aa12fbc75838eacee7c85eff27e6d`. Log: `NOTES-v3-preflight-fix-2026-11-06.md`. No strategy, data, threshold or N change.

## Mechanical verdict: **FAIL** (trend shelved for this sprint)

This is the pipeline's mechanical verdict from `outputs_v3/criteria.csv` / `meta.json` (`mechanical_verdict`). **Victor's formal verdict is now logged:** FAIL; trend v3 shelved for this sprint. See `validation/prereg_rulings/2026-11-06-trend-v3-results.md` and `validation/verdicts-log.md` (06:29 SGT).

## Criteria (exactly `outputs_v3/criteria.csv`)

| # | Criterion | Value | Pass |
|---|---|---|---|
| 1 | quasi-OOS net SR ×0.8 > 0.5 | −0.051651 | False |
| 2a | net SR > 0 at 2× costs (quasi-OOS) | −0.213696 | False |
| 2b | net SR > 0 at 2× costs (full) | −0.082514 | False |
| 2c | break-even cost ≥ 2× assumed (quasi-OOS) | 0.694826 | False |
| 3 | DSR ≥ 0.95 at N=57 (gross-dispersion) | 0.087202 | False |
| 4 | NW t ≥ 2.8 full history | 0.106445 | False |
| 5 | PBO < 0.20 | 0.380186 | False |
| 6 | quasi-OOS trades ≥ 100 | 1520 | True |
| 7a | no year > 40% of net PnL | 6.187624 | False |
| 7b | no calendar-year Sharpe < −0.5 (§7.7; confirmed hard by Victor) | −2.108033 | False |
| 7c | no SPY/VIX regime Sharpe < −0.5 (VIX required) | −0.426921 | True |
| 8 | stability: all 10 > 0 and ≥ 50% of primary | 2 | False |
| 9 | LIMITS compliance (ruling 9B-4: orders ok, breaches cured next open, hard-breach sessions ≤ 1%) | sessions 5218; hard_breach_sessions 1 (2020-04-06); share 0.000192; uncured []; orders_ok true; pass true | True |
| 9s | LIMITS compliance strict (no EOD hard breach) | (empty) | False |
| 10 | blind 2005–2007 net return > 0 (A2) | −0.075226 | False |
| 11 | every trade ≤ 1% ADV20 | 0.000648 | True |

Passed: 6, 7c, 9, 11. Failed: 1, 2a, 2b, 2c, 3, 4, 5, 7a, 7b, 8, 9s, 10.

## Segment metrics (`outputs_v3/segments.csv`)

| Segment | Net ann ret | Net Sharpe | NW t | Max DD (NAV) | Trades | Turnover/yr | Avg cost (bps) | Break-even (bps) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Full (2006-02-01 → 2026-10-28) | +0.077% | 0.021 | 0.106 | 8.01% | 2891 | 5.65 | 9.17 | 11.8 |
| Quasi-OOS 2005–2016 | −0.269% | −0.065 | −0.247 | 8.01% | 1520 | 5.82 | 11.03 | 7.7 |
| Blind 2005–2007 | −4.016% | −1.054 | −1.362 | 5.31% | 259 | 7.78 | 13.76 | −37.0 |
| 2008–2016 partly seen | +0.527% | 0.124 | 0.459 | 8.01% | 1261 | 5.40 | 10.19 | 21.3 |
| 2017+ seen | +0.462% | 0.145 | 0.497 | 7.87% | 1371 | 5.46 | 6.96 | 16.7 |

Full gross: ann ret 0.667%, Sharpe 0.179. Avg / max gross: 0.250 / 0.607. H8 days 3089; halt days 10. Stop exits 1403. Max % ADV20 0.065%. Legs (meta): long Sharpe 0.317; short Sharpe −0.097.

Blind note (meta): "2005-2007 is too short to judge on its own (A2); passing it is necessary, not sufficient."

## DSR / PBO / NW

- **NW t (full):** 0.106445 (criterion 4).
- **DSR** (`outputs_v3/dsr.csv`), gate row gross-dispersion, N=57, T=2749: DSR **0.087202** (sr_ann −0.064564; sr0 0.3464). N=47 companion: 0.093089. All-net-dispersion rows are reported alongside and are ~0.
- **PBO** (`outputs_v3/pbo.json`): S=16, 12870 combinations, **40 of 57** trials with daily series, T=2448, **PBO 0.380186**, median logit 0.446. Gap 17 = Victor's diagnostics (ruling 9B-9). Decision N remains 57 (`meta.n_trials`).
- Trial log append: trial 47 `V3_PRIMARY`, data sha `c998ca5c…`, quasi-OOS net SR −0.064564.

## Stability (`outputs_v3/stability.csv`) and sensitivities

Stability on the quasi-OOS window (criterion 8 value = 2 passes of 10):

| Run | Net Sharpe | Pass (≥0 and ≥50% of primary) |
|---|---:|---|
| lookback_9.6m | −0.0655 | False |
| lookback_14.4m | +0.0265 | True |
| stop_1.6atr | −0.0916 | False |
| stop_2.4atr | −0.0399 | False |
| voltarget_8pct | −0.0312 | False |
| voltarget_12pct | −0.0748 | False |
| band_20pct | −0.0611 | False |
| band_30pct | −0.0265 | False |
| joint_minus20 | −0.0382 | False |
| joint_plus20 | +0.0367 | True |

Sensitivities (`outputs_v3/sensitivities.csv`), selected:
- costs_2× quasi-OOS net SR −0.214; full −0.083 (criteria 2a/2b).
- borrow_25bps_tomas quasi-OOS net SR −0.054; full +0.026.
- nav_1m quasi-OOS net SR −0.070; full +0.015; max % ADV20 rises to ~0.65%.

## Costs / turnover / trades

From the full segment: one-way turnover 116.9 (5.65×/yr), average cost 9.17 bps, break-even 11.8 bps. Quasi-OOS break-even / assumed-cost ratio 0.695 (criterion 2c). Trades: 2891 full / 1520 quasi-OOS (flip = one trade per §9.C C11).

## Open fallback, splits, Nasdaq xcheck, breaker

- **Open fallback:** 0 fallback fills / 3530 open-priced fills (share 0.0; limit 0.5%).
- **Splits applied (7):** Yahoo pre-2016 — IWM 2005-06-09 ×0.5; EFA/EEM 2005-06-09 ×1/3; EEM 2008-07-24 ×1/3; SLV 2008-07-24 ×0.1. CA table — EWJ 2016-11-07 ×4; USO 2020-04-29 ×8. File: `outputs_v3/splits_applied.csv`.
- **Substitution diff audit:** 72 rows (SPY 16, USO 15, EEM 14, IWM 9, GLD/SLV/QQQ 4, EWJ 3, EFA 2, TLT 1; IEF 0).
- **Nasdaq xcheck (report-only):** per-ticker share within 1bp on 2513 days — EFA/QQQ 100%; others 99.92–99.96%. Substituted rows with \|Nasdaq−Yahoo\| > 10bp: **0**. All rows > 25bp: **2** (GLD and SLV on 2026-04-20; neither substituted).
- **LIMITS / breaker:** frozen to PREREG-v3 §5/§9.A/§9.B (LIMITS.md af513e3a…1cf6 at drafting). Disclosure: LIMITS v0.3.x not adopted (ruling 9B-1); the live breaker may differ. Criterion 9 passes (one hard breach 2020-04-06, cured next open). Criterion 9s fails (strict: any EOD hard breach). Buffer breaches also cured (see `limit_breaches.csv`).

## Output paths

- Directory: `research/replications/trend-sleeve/outputs_v3/`
- Manifest: `outputs_v3.MANIFEST.sha256` (23 lines)
- Hash stamp: `outputs_v3.HASH.txt` → `87acf086fec28c3005f253a4abbeec4ab50505acbaa3d6219a4ad6418423c647`
- Key files: `criteria.csv`, `segments.csv`, `meta.json`, `pbo.json`, `dsr.csv`, `stability.csv`, `sensitivities.csv`, `trial_log_append.csv`, `limit_breaches.csv`, `splits_applied.csv`, `nasdaq_yahoo_*.csv`, `v3_daily.csv`, `v3_trades.csv`, `v3_weights.csv`, …

## Disposition

Mechanical FAIL, independently confirmed by Victor: trend v3 shelved for this sprint. No further v3 run or same-trial tweak. Any future variant needs a new PREREG, trial budget and Victor ruling. Preserve `outputs_v3/` and directory hash unchanged. Formal ruling: `validation/prereg_rulings/2026-11-06-trend-v3-results.md` (sha256 `92c62f463d3debb6eed13c07df5b00bdc63aed89fcbcb6a1d9c01dd9bc48e2de`).
