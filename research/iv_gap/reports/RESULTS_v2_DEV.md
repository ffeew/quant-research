# RESULTS: IV-gap v2, DEV gate readout
Written 2026-11-13. Governed by PREREG r3 `PREREG_IV_GAP_v2_DRAFT_r3.md` (sealed, the review).
Run: hash check 6/6 OK, console (rc=0), FREEZE_NOTE,
RUNCHECK (the review, RUN ACCEPTED). Derived only from the sealed outputs by `derive.py`. No reader, AV or chain call; no rerun,
no variant and no new cuts. The holdout (2016-06-01 onward) stayed unopened. v1 outputs were not opened.
**Status: to be checked against the raw output before any decision.**

## 1. What the prereg defines as the gate
The prereg defines **no overall PASS/FAIL gate**. §1: the result "decides only whether AV IV may serve as a **cross-check**... It is never an
alpha input and never a gate." §7 gives the only cut-offs: report a cell iff n >= 20; a reported cell is usable iff drop rate <= 10%;
**Kill:** a symbol-year with drop rate > 10% over all kept legs gets "no AV cross-check for that symbol-year, whatever its cells show." The outcome is
stated as readings (i)/(ii)/(iii) per cell. PASS/FAIL below is applied only to those pre-registered tests.
**Net after costs:** the prereg defines no net-after-cost metric for IV-gap v2 DEV, so none was computed (§1, §2 cond. 3: no returns or P&L).

| Pre-registered metric (source) | Threshold | Observed | Result |
|---|---|---|---|
| Cell report floor (§3, §7) | n >= 20 | 609/660 pooled cells reported (C 518/608, P 561/651) | applied |
| Cell usability (§7) | cell drop rate <= 0.10 | pooled: 319 usable cells | per cell (cell_usable.csv) |
| Symbol-year kill (§7; §2 item 5 K3 text) | sy drop rate > 0.10 = kill | 4 of 16 symbol-years killed | 12 PASS / 4 FAIL |
| Flag rate (§2 item 5, §3) | \|gap\| > 0.05 | reported only, no decision attached | n/a |
| **Overall (§7 readings)** | -- | AV IV may be a cross-check **only** in the 319 usable pooled cells (reading i), all in 2011-2016. It is not usable in 2009-2010 for either symbol (reading iii). Black-76 stays primary | **no single PASS/FAIL defined** |

## 2. Kill status and effective sample size per symbol-year
The flagged and dropped counts are derived as round(rate × kept). Every symbol-year has no_underlying = 0.
| Sym | Yr | days | no_date | seen | kept | kept/seen | flagged | dropped | flag rate | drop rate | Kill test |
|---|---|---|---|---|---|---|---|---|---|---|---|
| QQQ | 2009 | 12 | 0 | 11145 | 3888 | 0.349 | 3888 | 3862 | 1.000 | 0.993 | **FAIL (killed)** |
| QQQ | 2010 | 12 | 0 | 7749 | 4057 | 0.524 | 4057 | 4043 | 1.000 | 0.997 | **FAIL (killed)** |
| QQQ | 2011 | 12 | 0 | 9776 | 4751 | 0.486 | 631 | 366 | 0.133 | 0.077 | PASS |
| QQQ | 2012 | 12 | 0 | 14151 | 5996 | 0.424 | 739 | 243 | 0.123 | 0.041 | PASS |
| QQQ | 2013 | 12 | 0 | 17402 | 4534 | 0.261 | 737 | 325 | 0.163 | 0.072 | PASS |
| QQQ | 2014 | 12 | 0 | 17283 | 7475 | 0.433 | 828 | 378 | 0.111 | 0.051 | PASS |
| QQQ | 2015 | 12 | 0 | 21842 | 11865 | 0.543 | 1041 | 477 | 0.088 | 0.040 | PASS |
| QQQ | 2016* | 5 | 0 | 9424 | 5458 | 0.579 | 530 | 272 | 0.097 | 0.050 | PASS |
| SPY | 2009 | 12 | 0 | 28475 | 6562 | 0.230 | 5881 | 5506 | 0.896 | 0.839 | **FAIL (killed)** |
| SPY | 2010 | 12 | 0 | 24960 | 5468 | 0.219 | 2033 | 1482 | 0.372 | 0.271 | **FAIL (killed)** |
| SPY | 2011 | 12 | 0 | 27957 | 6096 | 0.218 | 883 | 416 | 0.145 | 0.068 | PASS |
| SPY | 2012 | 12 | 0 | 32119 | 3937 | 0.123 | 742 | 367 | 0.188 | 0.093 | PASS |
| SPY | 2013 | 12 | 0 | 34414 | 5163 | 0.150 | 851 | 496 | 0.165 | 0.096 | PASS |
| SPY | 2014 | 12 | 0 | 40745 | 8335 | 0.205 | 1215 | 724 | 0.146 | 0.087 | PASS |
| SPY | 2015 | 12 | 0 | 46991 | 11200 | 0.238 | 1692 | 959 | 0.151 | 0.086 | PASS |
| SPY | 2016* | 5 | 0 | 21342 | 5797 | 0.272 | 777 | 382 | 0.134 | 0.066 | PASS |
\*2016 covers Jan-May only. There are 89 sampled days per symbol, which matches 179 reader calls. SPY 2012 and SPY 2013 pass narrowly (0.093 and 0.096 against 0.10).
The largest exclusion is parity_fail (see coverage.csv). The symbol-year rates are not n-floored (I-2).

## 3. Usable cells (symbol × year × type × moneyness × DTE)
| Type | cells | reported (n>=20) | reported, non-killed | **usable** | usable / reported | usable / all cells | usable / reported non-killed |
|---|---|---|---|---|---|---|---|
| Pooled (ALL) | 660 | 609 | 468 | **319** | 0.524 | 0.483 | 0.682 |
| C | 608 | 518 | 400 | 312 | 0.602 | 0.513 | 0.780 |
| P | 651 | 561 | 433 | 341 | 0.608 | 0.524 | 0.788 |
The 4 killed symbol-years have 0 usable cells. In those symbol-years, 11 pooled cells have a drop rate <= 10% but are not usable under the kill rule.
Usable pooled cells per non-killed symbol-year are 18-31 (see usable_by_symbol_year.csv).

**Distribution of reported-cell rates (pooled; quartiles: min / p25 / median / p75 / max).** rate_distributions.csv also has the C and P breakdowns.
| Group | cells | flag rate | drop rate |
|---|---|---|---|
| non-killed symbol-years | 468 | 0 / 0 / 0.099 / 0.312 / 1 | 0 / 0 / 0.016 / 0.163 / 1 |
| killed symbol-years | 141 | 0 / 0.683 / 1.000 / 1 / 1 | 0 / 0.500 / 0.990 / 1 / 1 |

## 4. Flagged and dropped rows: how the prereg handles them
- Rule (§2 item 5, quoting VRP PREREG): "|vendor IV − desk IV| > 0.05 (absolute) is **flagged**, and > 0.10 is **dropped**.
  Flag and drop rates are reported by year." §3 applies this per contract; §2 says rates are "computed over legs (contracts)".
- **Handling.** Flagged and dropped legs are **not removed** from the kept set. They stay in each cell's and each symbol-year's denominator, and
  "drop" works as a *rate* (A-7: usable and kill booleans are not written; the rule is applied to the rates). Only the **drop** rate carries a decision (§7).
  The **flag** rate is reported and carries none. So a flag rate of 1.0 by itself would not kill a symbol-year. A symbol-year is killed only by its drop rate.
- **Review INFO-2 tie-in.** QQQ 2009 and 2010 have flag rate 1.000 and SPY 2009 has 0.896, all before the 2011-03-23 changeover (the review's label). In those same
  symbol-years the drop rates are 0.993, 0.997 and 0.839, so nearly every flagged leg also exceeds 0.10. The kill comes from the drop rate, as the prereg requires.
  SPY 2010 (flag 0.372, drop 0.271) is also killed. §7: a 2009 failure does not widen to other years, and 2011-2016 pass on their own rates.
  The prereg (§9 D3) labels 2009 findings as not blind discovery.
- **Hypothesis only, untested.** SPY has no ticker change and shows the same pre-2011 pattern, so a QQQQ mapping issue alone would not explain it.
  The pattern lines up in time with AV `mark` sitting outside [bid, ask]: 0.76-0.80 of contracts in 2009 and 0.30-0.31 in 2010, against <= 0.06 from 2011 on (§5 below).
  That fits a vendor convention or snapshot-timing difference in AV's pre-2011 IV and mark fields, but the hypothesis is not tested. The frozen run gets no fix, cut or variant.

## 5. Bid/ask/mark sanity (§4a; fractions of contracts seen)
| Sym | Yr | bid=0 | ask<bid | mark outside [bid, ask] | \|mark−mid\|>$0.005 | mark null |
|---|---|---|---|---|---|---|
| QQQ | 2009 / 2010 | 0.185 / 0.147 | 0 / 0 | **0.799 / 0.310** | 0.825 / 0.366 | 0 / 0 |
| QQQ | 2011-2016 range | 0.096-0.145 | 0 | 0.000-0.058 | 0.071-0.142 | 0 |
| SPY | 2009 / 2010 | 0.152 / 0.104 | 0 / 0 | **0.764 / 0.296** | 0.840 / 0.361 | 0 / 0 |
| SPY | 2011-2016 range | 0.096-0.109 | 0-0.00003 (1 in 2012) | 0.000-0.002 | 0.082-0.094 | 0 |

## 6. Put-call parity violations (§4b; summed over DTE buckets; per-bucket rows are in the raw parity_violations.csv)
| Sym | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 |
|---|---|---|---|---|---|---|---|---|
| QQQ rate | 0.024 | 0.032 | 0.022 | 0.081 | 0.188 | 0.048 | 0.011 | 0.014 |
| SPY rate | 0.254 | 0.243 | 0.144 | 0.304 | 0.134 | 0.135 | 0.165 | 0.102 |
This is a quote-consistency diagnostic with circularity (F and DF are fitted from the same quotes), not an arbitrage claim (§4b). No decision is attached.

## 7. Review INFO items
- **INFO-1 "SPY 2012 has no_date 1": not reproduced from coverage.csv.** SPY 2012 has no_date = **0** and sampled_days = 12.
  The 1 in that row is **excl_crossed = 1**, and sanity_bidask also shows ask<bid = 1 for SPY 2012. Every symbol-year has no_date = 0. This is stated factually
  and is for review to confirm. It may be a column reading in the RUNCHECK, but I have not resolved it.
- **INFO-2**: see §4.

## 8. Disclosures (restated)
- **A-3**: mny_out needs F, so the surviving legs of an expiry whose parity fit failed are counted as parity_fail.
- **A-9**: a zero-time-value mid returns sigma 1e-4 (a root on the §3 bracket), not iv_fail. This can only push gaps up, so it biases **against** AV use.
- **include_scale_flagged=False**: rows the reader withheld are not in "seen".
- **I-2**: symbol-year flag and drop rates are not n-floored. All symbol-years have kept >= 3937.
- AV IV is used as reported, with its convention unknown (A7). No greeks were computed (§4c). Black-76 on American options with dividends is an approximation (§3).

## 9. N ledger (§8)
F1 +1, F1b +1, F1c +1, F2 0, **F3 +1** (cross-check usability selection, counted on completion). **N = 4**, which matches run.log `n_ledger_total 4`.

## 10. Use and trade expression
Per §7, the only permitted use is AV IV as a cross-check on the desk's Black-76 IV in the usable cells. It is never alpha, a signal, a gate or a filter.
"the derivatives researcher's Black-76 IV is primary; AV IV is not used for gating" stands. This study tests no trade and makes no recommendation. Any later trade test that cites
it must be defined-risk only (verticals, iron condors, or flies with long wings), with no naked short vol and no leverage. Such a test needs its own prereg and
risk, cost and owner checks, and is paper only.

## 11. Ambiguities (listed, not resolved)
1. **Type granularity.** §7 names "symbol x year x moneyness x DTE cells", while §3 defines the cells with type (C/P separately and pooled). I report pooled as the
   headline and C/P alongside, and I chose neither as the decision level.
2. **Usable share denominator.** The prereg names none. Three are shown: of reported cells, of all cells, and of reported cells in non-killed symbol-years.
3. **No overall PASS/FAIL or net-after-cost metric** is defined. The verdict is the set of per-cell and per-symbol-year readings.
4. **INFO-1 discrepancy** (§7).
5. **Changeover date 2011-03-23** is the review's label and does not appear in the prereg. Year cells are calendar years, so QQQ 2011 mixes pre- and post-changeover days.
   It is not split, because that would be a new cut.
6. Flagged and dropped counts are derived as rate × kept and rounded, since the outputs carry rates, not counts.
