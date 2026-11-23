# Implied-vol data validation (AV IV vs Black-76)

**Status:** closed  
**Verdict:** closed; vendor IV limited to the 2011-2016 cells as a cross-check; not usable 2009-2010; no rerun

## Hypothesis
Alpha Vantage historical implied vols are accurate enough to use alongside a Black-76 implied vol computed from option prices.

## Data window
2009-2016 (DEV).

## Method
Per-symbol-year cell comparisons with report and usability floors.

## Results
- 609/660 pooled cells reported; 319 usable cells, all in 2011-2016; not usable in 2009-2010. Black-76 stays primary. No overall PASS/FAIL is defined.
- Usable share: 319/609 of reported cells; 319/468 of reported cells in non-killed symbol-years.
- Trials counted: N = 4.

## Kills
Each kill is the pre-registered symbol-year kill: a symbol-year whose drop rate over all kept legs is above 0.10 gets no AV cross-check for that symbol-year, whatever its cells show.
4 of 16 symbol-years were killed:

| Symbol | Year | Drop rate | Why it fired |
|---|---|---|---|
| QQQ | 2009 | 0.993 | drop rate above 0.10 over all kept legs |
| QQQ | 2010 | 0.997 | drop rate above 0.10 over all kept legs |
| SPY | 2009 | 0.839 | drop rate above 0.10 over all kept legs |
| SPY | 2010 | 0.271 | drop rate above 0.10 over all kept legs |

The killed symbol-years have 0 usable cells. The other 12 symbol-years (2011-2016) pass on their own rates.

## Outcome
Closed as a negative result for 2009-2010: AV IV is limited to the 2011-2016 usable cells as a cross-check on Black-76, which stays primary. AV IV is never an alpha input or a gate. No rerun.

## Code
- Entry point: `qr run iv_gap` (`python -m quant_research.strategies.iv_gap.runner`)
- Config: `configs/iv_gap.toml`

## Sources
Numbers above are copied from these documents:
- [reports/PREREG_v2.md](reports/PREREG_v2.md)
  - Note: PREREG_v2.md lines 109 and 114 cite internal incident numbers (for the run-constraint ruling and the pinned
    venv). Those records are desk-internal and are not in this repo. The quoted rule and the venv path
    on those lines are the operative text. The prereg is frozen and is not edited.
- [reports/RESULTS_v2_DEV.md](reports/RESULTS_v2_DEV.md)
