# Statarb bellwether H1/H2

**Status:** in_progress  
**Verdict:** v3 proposed; runner dry-pass only, no returns

## Hypothesis
Bellwether moves lead peers (H1/H2).

## Data window
n/a

## Method
Frozen runner v1.3f (refuses to run until unsealed; exits 17 on import).

## Successor
Config-driven harness for further work: [../statarb_h1h2/FINDINGS.md](../statarb_h1h2/FINDINGS.md).

## Results
- No returns computed.

## Code
- Entry point: `qr run statarb_bellwether` (`python -m quant_research.strategies.statarb_bellwether.backtest_h1_h2_v1_3f`)
- Config: `configs/statarb_bellwether.toml`

## Sources
Numbers above are copied from these documents:
- [reports/PREREG_v3.md](reports/PREREG_v3.md)
