# Statarb bellwether H1/H2

**Status:** in_progress  
**Verdict:** v3 proposed; runner dry-pass only, no returns

## Hypothesis
Bellwether moves lead peers (H1/H2).

## Data window
n/a

## Method
Frozen runner v1.3f (refuses to run until unsealed; exits 17 on import).

Review round 3 fixes (ported from the H1/H2 harness, #10):
- **Fill timing.** A fill at close j-1 is priced, print-checked and ADV-capped on its own fill
  row, so an exit at a name's real last print pays its cost and nothing fills on a no-print day.
- **Held position everywhere.** H2 delisting receipts and the counted stress fire on any position
  still held past the last print (a capped exit remainder, or a last print the session before the
  planned exit). The H1 suspension-gap check tests the held position, not the target.
- **Settlement after the last print is no longer free.** A held remainder closed at the last close
  pays the stress cost (2x the one-way cost at no ADV) and is in the H2 stress / H1 bound.
- **Zero-ADV cuts.** A name with no usable ADV (no history, 0 or NaN) can never grow but can always
  be cut toward 0, at the stress cost. Each run reports `n_forced_cuts_zero_adv`,
  `forced_cut_notional_usd`, `n_post_last_print_settlements` and
  `post_last_print_settlement_notional_usd`. No DEV run yet, so no counts to report.
- **Costs.** This runner prices trades with the frozen `costs_original` model; the harness's
  standard floor table (`backtest/engine.py:39-40`) is not applied here.
- One last-print definition (price present and > 0) is used everywhere.

## Results
- No returns computed.

## Code
- Entry point: `qr run statarb_bellwether` (`python -m quant_research.strategies.statarb_bellwether.backtest_h1_h2_v1_3f`)
- Config: `configs/statarb_bellwether.toml`

## Sources
Numbers above are copied from these documents:
- [reports/PREREG_v3.md](reports/PREREG_v3.md)
