# SUE / earnings-surprise control — SPEC (derivatives researcher derived)
**Status:** `sue_v0.6_draft` built end-to-end on the v1.3 pin · **NOT frozen · NOT promoted · coverage_complete=false (real gaps below)**
**Owner:** the derivatives researcher · **Updated:** 2026-11-06 · **Binding text:** `../COMMON.md` C9.
**No strategy/factor returns, no backtests, no CVA/MXD/TSC outcome joins.** Manifest + explicit schema: `out/SUE_MANIFEST.json`; hashes: `SHA256SUMS`.

## 0. Authority and what this is / is not
- Desk-wide **control** for CVA/MXD (TSC parked). Not a strategy under test.
- **Single enumeration:** v1.3 `edgar_8k_202` form 8-K (keep-all-actings, 28,590 accessions) + `earnings_events` + `edgar_10q10k` + `fundamentals/xbrl_facts`, all read from `releases/v1.3` (top). `common.STORE = releases/v1.3` (the live store differs from v1.3 for `xbrl_facts`, `daily_total_return`, `SPY` raw, so nothing is read from it).
- **Sentiment researcher v1 and v2 are NOT used for any value, event, timestamp or exhibit pointer** (`ex99_rule=ethan_v1_additive` rows = 0). All 28,590 exhibit URLs point into the event's own accession (verified), so they were public at τ. Therefore no cluster-first/keep-all mixing (validation v1 PIT decision §5; v2 review §6.4) and the v2 as-of exhibit rule is not triggered. If a later version uses v2 exhibit pointers, it must gate on `ex99_available_utc ≤ decision time` (v2 §6.1).
- **AA (CIK 1675149, 43 v1.3 8-K events) / EVHC (CIK 1578318, 5)**: v1.3 keeps them; 0+0 fall inside PIT S&P 500 membership. They are **not an in-index coverage gap** (v2 review §2.3). The earlier v0.5 condition “complete only after sentiment researcher v2 AA/EVHC” is **withdrawn** (it was invalid).

## 1. Inputs (all v1.3; hashes in `out/sue_build.log.json → input_hashes`)
`earnings/edgar_8k_202.parquet` · `earnings/earnings_events.parquet` · `earnings/edgar_10q10k.parquet` · `fundamentals/xbrl_facts.parquet` (v1.3 component) · `corporate_actions/splits.parquet` · `universe/sp500_membership.parquet` · `bars/daily/total_return/daily_total_return.parquet` (announcement control only) · `bars/daily/raw/SPY.parquet` (session calendar). Own exhibits map `out/exhibits.parquet` (EDGAR index of each accession).

## 2. Event selection and availability (binding, enforced by `test_sue_availability.py`, ALL_PASS)
1. Every v1.3 form-8-K Item 2.02 accession is extracted (28,590/28,590; no drop for missing EX-99 — 6,115 events use the 8-K body; 83 of those yield GAAP EPS).
2. Rule-based extractor (`eps8k_extract.py`, no LLM). Primary = GAAP diluted EPS; unlabeled-per-share and adjusted-only rejected.
3. **Fiscal period is point-in-time** (`pit_period.py`, new in v0.6): text “quarter ended <date>” from the filing, else roll-forward from the latest XBRL period end **already public at τ**; ±7-day snap to the XBRL calendar date only canonicalises the date. The v0.5 label used the full ex-post XBRL table (selection look-ahead); it is kept only as QA (`fiscal_period_expost`, agreement 0.9926).
4. Quarterly-result rule: τ within (period end, +100 d]; not preannouncement / non-periodic; first 8-K per (cik, period).
5. **8-K EPS known at its own acceptance τ** (`acceptance_datetime_et`). **XBRL fallback known only at its own 10-Q/10-K acceptance** (`accn` join), else the data owner `available_session` 09:29 ET (flagged `available_session_fallback`). 3-month durations only; **0 FY−9M rows**.
6. Lags q−1…q−12 are matched by date (nearest known period end within ±20 d of q−k·91.31 d) and taken **as known at τ_q** (8-K value preferred if public, earliest filing). `avail_et = max(knowledge of numerator, all lags)`; audit: = numerator knowledge for all ok rows.
7. SUE = (EPS_q − EPS_q−4)/σ, σ = sd(ddof=1) of up to 8 seasonal differences (min 4), floor $0.01 (flagged); drift variant separate; splits applied only if `known_as_of ≤ τ_q`.
8. Announcement-return control: one row per eligible quarterly 8-K event (independent of EPS parse), stock TR − SPY TR from close before `reaction_session` to close of `reaction_session+1`; `usable_session` = next session (open). Not a strategy return.
9. Coverage: formation = last session of month; SUE row usable if `avail_et < 16:00 ET` that day and ≤ 130 sessions old; latest per CIK; PIT members by ticker.

## 3. Results (real outputs, `out/sue_build.log.json`)
| Item | Value |
|---|---|
| Events extracted | 28,590 (GAAP 19055, none 7448, unlabeled 1824, adjusted-only 263) |
| Funnel | GAAP parsed 19055 → excl. preann/non-periodic 254 → excl. no PIT period/outside 100 d 449 → later same-period 8-K 14 → **eligible 8-K numerators 18338** |
| Numerator panel (cik×period) | 33,098 (8-K 18338, XBRL 14760; XBRL includes 2012-15 lag history) |
| SUE ok / total | 27,072 / 33,098 (missing lag4 as-of 3159, <4 σ lags 2867) |
| XBRL-fallback share of ok rows by numerator year | 2017 0.2853, 2018 0.2727, … 2026 0.2028 |
| Median fallback knowledge lag vs same-period 8-K τ | 1.06 days (5670 rows) |
| Mixed-source share / floored σ share (ok) | 0.3618 / 0.0007 |
| Extractor vs XBRL (QA, \|diff\| ≤ $0.011) | all 0.9017, GAAP 0.9285 on 16994 comparable rows |
| **Coverage 2017-01..2026-10** | 118 months, **118 ≥ 300**, dropped 0; mean 474.5 SUE names (min 466, max 480) of mean 505.2 PIT members; mean XBRL-fallback share 0.1243 |
| **Coverage 2017-2018** | 24 months, **24 ≥ 300**; mean 470.9 (min 466) of 506.9 |
| Stage B months dropped | 0 of 47 |
| Announcement control rows | ok 26339, missing bars 432, outside calendar 100 |
| Reproducibility | two consecutive runs byte-identical (sue_events, drift, annret, coverage, history) |

## 4. Real coverage gaps (why coverage_complete=false)
| Gap class | Count | Handling |
|---|---|---|
| 8-K events with no usable GAAP diluted EPS (none / unlabeled / adjusted-only) | 7448 / 1824 / 263 | XBRL fallback at its own later knowledge time where a 3-month value exists; else missing. Never dropped silently; counted |
| Events with no PIT fiscal period | 1065 (of which 177 had an ex-post label) | excluded from 8-K numerators; counted |
| `earnings_events` join miss (event_type NaN) | 568 | kept (not preannouncement-flagged); disclosed |
| PIT members without a usable SUE per month | mean 30.7 (2017 38.8; 2020-26 ≈ 29) | reported monthly in `sue_monthly_coverage.csv` (n_members − n_sue) |
| Extractor disagreement with XBRL on comparable GAAP rows | 0.0715 | QA only; no correction from XBRL (would be look-ahead); the review to set a tolerance |
| Membership join at ticker grain | — | security-ID join not yet implemented in coverage projection |
| AA / EVHC | 0 in-index | **not a gap** |

## 9. Open questions (data owner)
1–8 as prior SPEC (unlabeled-per-share reject, availability=max lags, splits known_as_of, ddof, winsorize, min lags 4 vs 6, CIK chain, BasicAndDiluted).  
9. Confirm parent spine = v1.3 pins for all Stage A/B until a data owner SUE addendum.  
10. ~~AA/EVHC re-inclusion~~ — withdrawn (not a gap; v2 review §2.3).  
11. NEW: acceptable extractor-vs-XBRL disagreement tolerance (measured 7.15% of comparable GAAP rows).  
12. NEW: accept the PIT fiscal-period rule (text → PIT roll-forward → ±7 d snap) that replaces the ex-post XBRL label.  
13. NEW: security-ID (not ticker) membership join for the coverage projection.

## 10. Change log
- 2026-11-06 (v0.6): full extraction 28,590/28,590 merged (4 workers + checkpoint, de-duplicated, 0 missing); all inputs read from releases/v1.3 (XBRL fallback rebuilt from v1.3 xbrl_facts: 30,166 rows vs 30,353 live); PIT fiscal-period labels; date-matched lags; available_session XBRL rows usable at 09:29 ET of that session (previously silently dropped as NaT); announcement control per event; availability audit ALL_PASS; manifest+schema; AA/EVHC condition withdrawn; sentiment researcher v1/v2 unused. coverage_complete=false (real gaps §4). Prior code archived in `versions_pre_finalize/`.
- 2026-11-06 (data owner audit): parent = v1.3; sentiment researcher v1 additive only; no drop on missing EX-99; gap table; NOT coverage-complete; never describe either table as frozen complete SUE input.
- 2026-11-06: SPEC created with SUE build; v0.5 / validation decisions.
