# Macro event studies (oil shock, VIX backwardation, curve slope)

**Status:** failed  
**Verdict:** Oil-shock and curve-slope FAILED episode gates; VIX backwardation reclassified as risk overlay

## Hypothesis
Macro regime events predict relative sector/ETF returns.

## Data window
Episode counts only; no outcome series computed.

## Method
Pre-registered episode-count gate (>= 30 projected episodes) before any return is looked at.

## Results
- Oil-shock: FAILED the gate (15.1 projected < 30).
- Curve-slope v1.2: FAILED the gate (17.0 projected; v1.1 22.4); blocked on ALFRED vintages.
- VIX backwardation: candidate, reclassified as a risk-overlay, not an alpha signal.

## Code
- Entry point: `qr run macro_event_studies` (`python -m quant_research.strategies.macro_event_studies.count_episodes`)
- Config: `configs/macro_event_studies.toml`

## Sources
Numbers above are copied from these documents:
- [reports/PREREG_oil-shock-energy-vs-discretionary.md](reports/PREREG_oil-shock-energy-vs-discretionary.md)
- [reports/PREREG_curve-slope-financials-vs-utilities.md](reports/PREREG_curve-slope-financials-vs-utilities.md)
- [reports/PREREG_vix-backwardation-spy-rebound.md](reports/PREREG_vix-backwardation-spy-rebound.md)
