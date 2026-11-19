# News sentiment (Loughran-McDonald, 5-day)

**Status:** failed  
**Verdict:** FAILED on seen data (2025-06..2026-10); 2016..2025-05 held out unused

## Hypothesis
Sector/stock news tone (LM dictionary, VADER, analyst actions) predicts 1- and 5-day returns.

## Data window
Seen data 2025-06..2026-10; 2016..2025-05 held out (never used).

## Method
Pre-registered specs; 72 statistics across two universes; gross and net long-short returns.

## Results
- FAIL on seen data. Example: text_lm_prev_open L/S r1 gross -0.7 bp, net -26.3 bp.

## Code
- Entry point: `qr run news_sentiment` (`python -m quant_research.strategies.news_sentiment.prereg_run`)
- Config: `configs/news_sentiment.toml`

## Sources
Numbers above are copied from these documents:
- [reports/PREREG_sector_lm_5d.md](reports/PREREG_sector_lm_5d.md)
- [reports/RESULTS.md](reports/RESULTS.md)
- [reports/README.md](reports/README.md)
- [reports/DATA_AUDIT.md](reports/DATA_AUDIT.md)
