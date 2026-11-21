# Statarb H1/H2 harness (bellwether lag, earnings peer read-through)

**Status:** in_progress  
**Verdict:** none. There is no Stage A verdict, and there will be none until the deflated Sharpe
ratio (DSR) and purged cross-validation land in a later PR. No DEV run yet; no results.

## Hypotheses
- **H1 (bellwether lag).** Within a GICS sub-industry with at least 4 eligible members, an unusual
  60-session return gap between the 2 most-traded names (leaders) and the rest (followers) closes
  over the next 4 weeks. Long the lagging side, short the leading side. Predicted sign: positive.
- **H2 (earnings peer read-through).** When a sub-industry's exact-timestamp reporters on d0 react
  strongly together (|N| >= 1.5 residual sigmas vs the sector ETF), peers that already reported this
  season drift in the direction of N over the next 40 sessions, hedged with beta x sector ETF.
  Predicted sign: positive.

## Pre-registered design (summary)
- Universe: point-in-time S&P 500 members, clipped to listing windows; reused tickers, names with
  no usable history, identity exclusions and ETFs removed. Eligibility: price >= $5, 20-day ADV >= $20M,
  no zero-volume print, no |daily return| > 40% in the last 20 sessions, 252 sessions of history.
- H1 primary: L = 60, |z| >= 1, 2 leaders, min group 4, 4 weekly tranches, no earnings event in the
  hold window (2-session margin), name cap 9.5% of equity at 58% gross.
- H2 primary: H = 40, |N| >= 1.5, already-reported window 50 sessions, unit 0.5%, at most 100 live
  positions; hedge = sector SPDR (SPY if it has < 252 sessions).
- Execution: signal at the close of t, fill at the close of t+1, first return t+1 -> t+2 (H1 and H2
  alike); each session trades at most 1% of 20-day ADV and the unfilled rest carries forward.
- Costs: every trade pays at least the standard's per-side minimum (5 bps large-cap, 10 bps
  mid-cap, 20 bps small-cap/thin, 2 bps liquid ETFs, each plus half-spread); required path uses >= 10%/yr borrow on every historically unknown short, ETF hedges included;
  impact k = 1.0 base (0.75 is a lighter sensitivity); 1%/yr general-collateral path is a labelled
  counterfactual only.
- Terminal treatments: H1 stranded positions in unresolved delistings take an adverse bound (long -100%,
  short max(last price, deal value)); H2 counted delisting stress is -30% long / 0% short.
- Trial count N = 212 for the deflated Sharpe ratio. Stage A (DEV) pass bar: net Sharpe > 0.85 on the
  required cost path with the predicted sign; a fail ends the idea and the holdout stays closed.

## Fixes after review (harness only; the sealed runner is unchanged)
- **B1, look-ahead in H1.** H1 used to hold each tranche on its own signal bar, so it effectively
  filled at the signal close. Each tranche is now held from the next session, the same as H2: a
  signal at t first earns t+1 -> t+2.
- **B2, ADV cap.** The 1% ADV cap used to trim only the shares used to price costs, while gross
  return was earned on the full target. The cap now limits the trade itself, the unfilled rest
  carries to later sessions, and gross, cost and borrow are all on the position actually held.
- **B3, borrow.** Borrow used to accrue one day per session on a 360-day basis (about 7%/yr at a
  10% rate). It now accrues the calendar days between sessions (a weekend counts 3 days), so a
  year held short costs the full rate (365/360 of it).
- Minor fixes: the universe receipt lists only rows dated on or before the DEV end (2021-12-31);
  H2 caps single-name legs first and re-solves each ETF hedge from the capped leg, so the book
  stays beta-neutral (H1 has no hedge leg; its name cap still trims without reallocating); the
  standard's cost floor is applied to every run.
- Second review: the H1 terminal bound and the H2 delisting stress now apply to the position
  actually held (a capped exit still open when a name delists is bound on what is left), and a
  name with no print can't trade. ADV20 is the trailing window ending the session before the fill
  day, and a name with no ADV history can't trade (cap 0). The cost-floor table cites its source,
  the validation STANDARD cost floor.
- Third review:
  - **Fill timing.** A fill at close j-1 used to be priced and print-checked on row j, so an
    exit at a name's real last print was settled without its cost and a name could trade on a
    no-print day. Every fill is now priced, print-checked and capped on its own fill row.
  - **Held position everywhere.** The H2 delisting receipts and the counted stress fire on any
    position still held past the last print (a capped exit remainder, or a last print the
    session before the planned exit), not only when the planned window spans the delisting.
    The H1 suspension-gap check tests the held position, not the target.
  - **Settlement after the last print is no longer free.** A held remainder closed at the last
    close pays the stress cost (2x the one-way cost at no ADV), gets an H2 receipt and is in the
    H2 stress and the H1 terminal bound. For an H1 bound this is conservative: the stress exit
    cost is charged on top of the -100% / liability bound.
  - **Zero-ADV cuts.** A name with no usable ADV (no history, 0 or NaN) can never grow, but can
    always be cut toward 0; those cuts pay the stress cost. Each run reports how many forced cuts
    and post-last-print settlements happened and the notional traded
    (`n_forced_cuts_zero_adv`, `forced_cut_notional_usd`, `n_post_last_print_settlements`,
    `post_last_print_settlement_notional_usd`). No DEV run yet, so no counts to report.
  - **Cost floor source.** The floor table is `backtest/engine.py:39-40`. One known difference:
    a thin ETF (L4 bucket) gets the 20 bp floor here but 2 bp in the engine, which floors every
    ETF at 2 bp.
  - The prior claim that there was one last-print definition was wrong: fills / last-print
    tested price only, but H1 tau also required volume and a non-forward-filled row.
- Fourth review:
  - **One tradable print helper.** `tradable_mask` requires close > 0 AND volume > 0 and no
    forward-fill (when the FFILL frame is supplied, missing flags fail closed). Fills, zero-ADV
    cuts, last-print, tau, the suspension check, H1 bound, H2 receipts / stress and settlement
    all use that rule. No normal fill is possible on a positive close with zero volume. Gross
    is explicitly zero past the last tradable print, even if the input return frame has stale
    nonzero returns. The forced settlement is charged at the stress cost at the last real close.
  - **Named one-way stress.** `STRESS_ONE_WAY_COST_MULT = 2.0` is an explicit choice:
    twice the one-way cost of a forced trade priced with no ADV. It is NOT borrowed from the
    cost model's round-trip break-even multiple. The L4 minimum plus half-spread holds only
    under `FlooredCostModel`, not the bare `SharedCostModel`. A numeric test pins 2.0 and the
    20 bp result of stressing a flat 10 bp one-way cost, so changing the constant to 1.0 fails.
  - Weights with an index outside the price index fail closed, rather than silently being
    unfillable. Tests use five trailing positive zero-volume closes, check tau == last-print,
    W_adj flat from tau+1, no gross after the -100% bound, and receipt / -30% stress / charged
    settlement for a capped H2 remainder. Reverting each fix makes its regression test fail.
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
  - **FFILL is inert with this loader.** `loaders.bars_from_long` returns R, TRI, PX and VOL
    only, and never an FFILL frame, so `tradable_mask` skips the forward-fill test for these
    bars. The rule that a missing flag counts as forward-filled applies only when a caller
    supplies FFILL, to its NaN cells. With this loader, forward-filled rows are excluded only when
    they also have zero or NaN volume or no positive close.
  - Synthetic checks only; no DEV run or real returns.
- **Borrow and session alignment.** The H1 short bound's tau -> tau+1 session is charged borrow
  once, at max(base, source-rate bound): the overlay adds only the excess above base on tau+1,
  then the full bound from tau+2. The weight index
  must equal the price index (same sessions, same order), not just be a subset.
- Not done yet: DSR and purged CV. Until they land there is no Stage A verdict, whatever a DEV
  Sharpe shows.

## Data window
| Split | Dates | Notes |
|---|---|---|
| DEV | 2017-01-03 to 2021-12-31 | positions must exit 2 sessions before the end |
| Embargo | 2022-01-03 to 2022-03-29 | nothing entered or evaluated |
| Holdout | 2022-03-30 to 2026-10-28 | read once, in a single sitting; not bound in this harness |

## Method
`quant_research.strategies.statarb_h1h2` is a config-driven port of the pre-registered runner, with
the review fixes above. All
input paths and sha256 pins come from a TOML config (`configs/statarb_h1h2.toml` is an all-PENDING
example). The harness fails closed: any PENDING or mismatched pin, a total-return cut holding rows
after the embargo end, or rows past the read-time end stops the run before any return is computed.

## Results
- None. No DEV run has been made; no returns computed.

## Code
- Entry point: `qr run statarb_h1h2` (`python -m quant_research.strategies.statarb_h1h2.run --syntax-check`)
- Config: `configs/statarb_h1h2.toml`
- Tests (synthetic fixtures only): `tests/strategies/statarb_h1h2/`
