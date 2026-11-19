# Rank-1 single-name harness

**Status:** in_progress  
**Verdict:** Synthetic harness only (no real-data results)

## Hypothesis
Single-name ranking pipeline with costs, sigma and inference kernels.

## Data window
Synthetic data only.

## Method
Unit-tested harness (core, cost, inference, gates, bootstrap).

## Results
- No real-data results.

## Code
- Entry point: `qr run rank1_single_name` (`python -m quant_research.strategies.rank1_single_name.rank1_pipeline`)
- Config: `configs/rank1_single_name.toml`

## Sources
Numbers above are copied from these documents:
- [reports/README.md](reports/README.md)
