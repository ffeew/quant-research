# H1b OOS single sitting - PASS/FAIL decision under(d) - the validator, 2026-11-11 ~15:55 SGT
Outcome: H1b FAILS OOS under v5 section 5. Criterion (iv), the economic gate, fails under both UTC and ET. No re-specification after OOS (v5). The holdout sitting is consumed.
Run: one sitting at 15:08 SGT, exit 0 (sentiment researcher relay). Output $QR_DESK_DIR/research/original/sentiment_returns_oos_run_20261111/; sidecar SUMS, 6/6 OK; OOS_RAW.json; RUNNER_LOG; STDOUT; C8 0 (L3 W192).
Env as pinned: python 3.13.5, pandas 3.1.0, numpy 2.5.4, xcals 4.13.2, flags isolated=1 and dont_write_bytecode=1, so no flag deviation. Release, runner, config (STDOUT).
UTC (OOS_RAW): 433 periods; mean IC 0.020664 (DEV 0.001252); NW t 2.405; p 0.00829; Holm adj p 0.0166. (i), (ii) and (iii) met. (iv) raw L/S net at 10 bps/side is -0.001591 per period (gross 0.001154): FAIL.
ET (OOS_RAW): 432 periods; mean IC 0.018029 (DEV 0.002562); NW t 1.979; p 0.02422; Holm adj p 0.0484. (i), (ii) and (iii) met. (iv) net at 10 bps is -0.001793 (gross 0.000928): FAIL.
Runner pass_bars: all_met false under both readings; PASS_both_readings false. My decision agrees.
Reading (INFO, not a re-test): the rank signal held up out of sample, but daily turnover costs exceed the gross L/S spread. Net at 20 bps is -0.004335 (UTC) and -0.004514 (ET). H1a: DEV FAIL (A2), not run OOS. H2: exploratory, DEV only.
(e): nothing goes toward paper trading. Any follow-up idea, such as a lower-turnover variant, is a new hypothesis needing new data and the fund manager's approval, never this holdout.
Deviations: OOS_RAW fields read via a tr/grep extract and lines 370-450 only; the period TSVs and RUNNER_LOG body not read; no stats recomputed.
