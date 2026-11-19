# DEV_RESULTS — sentiment→returns, prereg v5 (4b045f05…4c91, sealed L293). DEV ONLY. Not verified point-in-time;
# survivorship upper bound; timestamp zone unconfirmed. No HOLDOUT file opened; no OOS computed; no trading.
Freeze file: DEV_FREEZE.json (0444). Code: dev_run.py, fiscal_diag.py. Logs: dev_run.log, RUN_LOG.txt, fiscal_diag.log.
Per-period tables: periods_<H>_<reading>.tsv (date, n, k, IC, L/S raw & beta-adj, turnover).

| Hyp | Reading | Periods (df) | Mean IC | NW t (lag) | p one-sided | L/S gross raw | L/S net 10bps | A2 |
|---|---|---|---|---|---|---|---|---|
| H1a weekly | UTC | 146 (145) | −0.0181 | −1.01 (4) | 0.843 | −0.093%/wk | −0.392%/wk | FAIL |
| H1a weekly | ET  | 146 (145) | −0.0171 | −0.96 (4) | 0.832 | +0.069%/wk | −0.227%/wk | FAIL |
| H1b daily  | UTC | 299 (298) | +0.0013 | +0.10 (5) | 0.459 | +0.059%/day | −0.300%/day | sign gate met |
| H1b daily  | ET  | 304 (303) | +0.0026 | +0.23 (5) | 0.408 | −0.041%/day | −0.402%/day | sign gate met |

- **A2:** H1a DEV mean IC ≤ 0 under both readings → **FAIL**; Holm p := 1; no OOS run for H1a; N stays 2.
  H1b mean IC > 0 under both → eligible for the single sealed OOS run (that is not a PASS; DEV t ≈ 0.1–0.2).
- **A4 materiality (DEV):** H1a |ΔIC| 0.0010 < 0.01, no sign flip, no p crossing → not material. H1b |ΔIC| 0.0013 < 0.01 → not material.
- **Counts (symbol-obs):** H1a: 148 calendar decisions; 1 pre-coverage (2022-03-04), 1 purged B3/B8 (2024-12-27);
  146 scored, 0 dropped for <20 names; scored obs UTC 5,686 / ET 5,667; below-min UTC 1,608 / ET 1,627; coverage=0 (CAT 2023-08) 6; capped 0.
  H1b: 714 calendar decisions; 1 pre-coverage (2022-03-01), 1 purged (2024-12-31); periods dropped for <20 names UTC 413 / ET 408;
  scored UTC 299 / ET 304; scored obs UTC 7,282 / ET 7,362; below-min UTC 22,611 / ET 22,590; obs in dropped periods UTC 5,681 / ET 5,622; coverage=0 26; capped 0.
  Missing target 0 (beta warm-up never binds). News: 1,700 DEV files (50 stocks × 2022-03..2024-12) sha-OK; 53,685 items;
  kept 52,441; relevance < 0.50 1,234; unparseable 0; after DEV cutoff 10 dropped; 6 items with duplicate ticker entries (first used).
- Fiscal diagnostic: INCONCLUSIVE — see FISCAL_DIAGNOSTIC.md (needs Victor).

## Implementation notes / deviations (prereg silent → conservative choice)
1. H1a "week" = ISO calendar week; decision = last XNYS session of the week, using the XNYS calendar (no data) to 2025-01-10 so
   the week of 2024-12-30 decides on 2025-01-03 (prereg §0); window = (15:30 ET previous decision, 15:30 ET decision].
2. Multi-day targets: compounded adjusted_close ratios close(dec)→close(next dec), target = R_i − β_i·R_SPY with the daily
   β at the decision session (252 returns ending t−1, sample OLS cov/var).
3. Window drop "before coverage": window start earlier than 2022-03-01 00:00 ET → period dropped (first H1a/H1b dates).
4. coverage=0 / capped overlap: a window excludes a symbol if any calendar month touched by [start−1 d, end+1 d] is flagged
   (over-excludes by up to a day; conservative). No capped months in DEV (checked in files and coverage_news.tsv).
5. DEV-cutoff item drop: an item is dropped if its instant under EITHER reading is after 2024-12-31 16:00 ET (10 items).
6. ET reading: nominal time as America/New_York wall clock (zoneinfo, fold=0 for ambiguous times).
7. Item with >1 entry for the same ticker: first entry used (6 items).
8. L/S: legs ranked by signal (ties broken by symbol); equal weight ±1/k; "L/S gross raw" uses unadjusted-for-beta total
   returns (no winsorizing), beta-adjusted spread also in the freeze file. Costs = 10 bps × turnover, turnover = Σ|Δw| vs
   the previous scheduled period (positions flat across unscored periods; closing trade charged to the last scored period;
   intra-period drift ignored). 20 bps sensitivity in freeze file.
9. NW variance: Bartlett weights, lag per prereg (H1a 4, H1b 5), denominator T; p = 1 − F_t(t, df = periods − 1).
10. SPY/QQQ news files not opened (excluded from cross-sections; not needed). sectors.csv not used (R-SECTOR, R-EARN
   robustness not run in this pass — remaining work).
