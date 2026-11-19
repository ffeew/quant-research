# Implied-vol data validation (AV IV vs Black-76)

**Status:** dev  
**Verdict:** DEV only: AV IV usable as a cross-check in 2011-2016 only; no PASS/FAIL defined

## Hypothesis
Alpha Vantage historical implied vols are accurate enough to use alongside a Black-76 implied vol computed from option prices.

## Data window
2009-2016 (DEV).

## Method
Per-symbol-year cell comparisons with report and usability floors.

## Results
- 609/660 pooled cells reported; 319 usable cells, all in 2011-2016; not usable in 2009-2010. Black-76 stays primary. No overall PASS/FAIL is defined.

## Code
- Entry point: `qr run iv_gap` (`python -m quant_research.strategies.iv_gap.runner`)
- Config: `configs/iv_gap.toml`

## Sources
Numbers above are copied from these documents:
- [reports/PREREG_v2.md](reports/PREREG_v2.md)
  - Note: PREREG_v2.md lines 109 and 114 cite desk incident numbers (INC-96 for the run-constraint ruling, INC-99
    for the pinned venv). Those records are desk-internal and are not in this repo. The quoted rule and the venv path
    on those lines are the operative text. The prereg is frozen and is not edited.
- [reports/RESULTS_v2_DEV.md](reports/RESULTS_v2_DEV.md)
