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
- Round 3 said one last-print definition (price present and > 0) was used everywhere. That was
  inaccurate: the H1 tau / suspension check also required volume > 0 and no forward-fill.

Review round 4 fixes (ported from #10):
- **One tradable-print rule.** `tradable_mask` (close > 0 AND volume > 0 AND not forward-filled;
  a missing FFILL flag counts as forward-filled) is the single definition used by fills, zero-ADV
  cuts, last print, tau, the suspension check, the H1 bound, H2 receipts / stress and settlement.
  A positive close with zero volume after the real last trade is not a print: a held remainder
  there is settled at the last real close at the stress cost, never sold at 1x, and earns no
  gross after the last print (or after the H1 bound).
- **Stress cost.** `STRESS_ONE_WAY_COST_MULT = 2.0` x the one-way cost of the forced trade, a
  desk choice pinned by a test; it is not the cost model's round-trip break-even multiple.
- Weights on sessions outside the price index fail closed.
- **Two design choices kept (both conservative).** (1) Past a name's last tradable print its
  return is blanked: the held position earns 0 gross, even where the input still carries stale
  nonzero returns on later zero-volume closes, so no gain can be booked on a name that no longer
  trades. (2) After the H1 -100% bound there is exactly one forced settlement of the held
  remainder at the last real close, charged at the 2x one-way stress cost. That cost comes on
  top of the bound and is never an exit credit, so it can only lower H1's result.
- **ADV20 counts non-print sessions as $0.** From a name's first tradable print on, a session in
  the t-1 window with zero or NaN volume, no close, or a forward-filled row adds $0 to ADV20
  rather than being skipped (skipping raised the cap). Before the first print the name has no
  history, so the 10-session minimum still applies. A test fails if this is reverted.
- **FFILL.** The AV sensitivity loader (`load_bars`) supplies FFILL from the bar file's
  `ffilled` column, so forward-filled rows are not prints there. The PRIMARY TR loader
  (`load_bars_tr`) returns R, TRI, PX and VOL only, so the forward-fill test is inert on the
  primary path. There, forward-filled rows are excluded only when they also have zero or NaN
  volume or no positive close. A missing flag counts as forward-filled only when FFILL is
  supplied.

## Results
- No returns computed.

## Code
- Entry point: `qr run statarb_bellwether` (`python -m quant_research.strategies.statarb_bellwether.backtest_h1_h2_v1_3f`)
- Config: `configs/statarb_bellwether.toml`

## Sources
Numbers above are copied from these documents:
- [reports/PREREG_v3.md](reports/PREREG_v3.md)
