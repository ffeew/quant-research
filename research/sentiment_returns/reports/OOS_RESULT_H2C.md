# H2-C holdout result: earnings-call tone surprise and post-call drift

**Verdict: HOLDOUT FAIL.** H2-C is closed under its pre-registered kill rule. The holdout is spent, and there will be no reruns.

## Hypothesis
Earnings-call tone surprise predicts post-call return drift. This was a confirmatory test of the H2 specification. Pre-registration: [PREREG_H2C_r3.md](PREREG_H2C_r3.md).

## Holdout window
- 2011Q1 to 2013Q4: 12 quarters, with 2010 as warm-up and the 2013 boundary purge applied.
- One run of the frozen code.
- All 12 quarters met the minimum event count. The smallest quarter had 39 events.

## Results
| Metric | Value | Gate | Outcome |
|---|---|---|---|
| Mean IC over 12 quarters (sd 0.145201) | 0.048020 | IC ≥ 0.0274 (half the DEV-period IC) | Pass |
| Newey-West (lag 1) t, one-sided p (df 11) | t 1.0848, p 0.1506 | p at most 0.01 | Fail |
| Long/short, beta-adjusted, gross per quarter | 0.000540 | n/a | n/a |
| Long/short net of 10 bp per quarter | -0.003688 | above 0 | Fail |
| Net of 10 bp after 10%/yr borrow, per quarter | -0.011617 | above 0 | Fail |
| Net of 20 bp per quarter (information) | -0.007915 | n/a | n/a |

The gate fails on significance and on net-of-cost return.

## Consequences
- Under the preregistered kill rule, this holdout is not reused for any H2 variant, and the 2011-2013 transcript holdout is treated as spent for all transcript-based hypotheses.
- Holdout spent; no reruns.
