# DRAFT v0.2 — Treasury bullet/barbell inventory-pressure reversion

**7 November 2026 SGT · the stat-arb researcher → the fund manager → the validator · outcome-blind documentary revision.**
**REVISE / NO RUN AUTHORISATION.** H1 remains parked; the data owner owns its repairs. No data pulls, DEV/diagnostic backtest, first signal, forward observation clock, paper order or agent message is authorised. Daniel has **not approved** paying for the prospective horizon. If declined, park this idea; do not relax the validation bar.

## 1. Hypothesis and distinct mechanism

Duration-specific mandates and dealer inventory constraints can transiently make an intermediate Treasury bullet rich/cheap relative to a short/long Treasury barbell. Fade recent **IEF versus (2/3 SHY + 1/3 TLT)** relative pressure by shifting cash-funded long exposure toward the cheaper side for the next week. Counterparties are preferred-habitat flows, not earnings-information traders.

One in-house implementation hypothesis, not a claim to have invented Treasury butterflies/reversal. The fixed barbell is approximately intermediate maturity exposure, **not DV01-neutral**. Curve slope, duration, convexity, carry and permanent repricing can overwhelm reversion; no arbitrage identity is assumed. Long-only allocation avoids borrow but retains bond beta. Both NAV performance and incremental P&L against the exact static benchmark must validate.

The prior bounded inventory check found stock pairs/residual reversal, H1/H2, Treasury carry, macro trend, sector curve/oil RV and VIX rebound, but not this exact fixed bullet/barbell rule. No exhaustive novelty claim or generic pairs sweep. No performance evidence informed this revision.

## 2. Universe, source and owner audit — before DEV

| Fixed ETF | Design role | Issuer-reported inception | Issuer benchmark |
|---|---|---|---|
| IEF | 7–10-year Treasury bullet | 22 July 2002 | ICE US Treasury 7–10 Year Bond Index |
| SHY | 1–3-year Treasury barbell leg | 22 July 2002 | ICE U.S. Treasury 1–3 Year Bond Index |
| TLT | 20+-year Treasury barbell leg | 22 July 2002 | ICE US Treasury 20+ Year Bond Index |

Ordinary unlevered US-listed bond ETFs only; no substitution, shorts, inverse/leveraged products, crypto, options, derivatives or leverage. The three inception/benchmark identities were checked during v0.1 metadata work. Instrument history remains **unaudited**, not “survivorship-free.” This is a design-selected set of 2026 survivors; explicitly apply STANDARD's **20% OOS Sharpe haircut** to NAV and active Sharpe gates. The accepted haircut route caps any eventual verdict at **CONDITIONAL PASS**, even if statistical full-pass thresholds are met. Do not generalise to all ETFs.

Candidate historical source is **v1.3 raw SIP**, `$QR_DATA_DIR/releases/v1.3/`, catalog top hash `d137eea39928ec8d27b4e8ace5266c01bf74a81ca7e6d07a9d84f9a71b6dc13a`. Catalog pin is not ETF acceptance. **The data owner, not the stat-arb researcher, must produce** the following immutable audit and manifest; the validator must accept it through a single exact-hash readback before any DEV return run:

1. Only IEF/SHY/TLT raw SIP bars, **2016-01-04–2026-10-28**; actual paths/SHA256, feed, fetch/correction vintage, per-symbol session coverage/gaps, zero-volume/halts and early closes. Require >=10 years common valid history including warm-up. Date/symbol selectors must prevent opening unrelated broad tables. **Yahoo trend-sleeve data is not an accepted source.** No duplicate historical download or shared-store alteration by the stat-arb researcher.
2. Continuous fund identity/CUSIP, issuer and benchmark, with every mandate/benchmark change source-dated from iShares/SEC. Resolve **2016–2020** explicitly through issuer/SEC history; Alpaca's merger catalog beginning April 2020 is inadequate by itself. No ticker alias/survivor substitution.
3. Full monthly distribution and split schedules with amounts, ex/record/payable dates, reconciled across Alpaca, iShares and SEC filings. Build effective-date entitlement total returns from raw prices; retain dividend receivables and enforce payable-date cash for executable sizing. No latest-adjusted price levels, ex-dividend-drop reversal, future distribution predictors or presumed historical announcement time from `min(ex_date,process_date)`. Unexplained mismatches are zero-tolerance blockers, not rows dropped/zero-filled to pass.
4. Named-source reconciliation of **official closing-auction prints for every MOC fill**. Consolidated daily SIP closes alone are insufficient; the cost addendum's mandatory official-auction reconciliation governs. No assumed auction equivalence or unapproved proxy.
5. Conservative original bar/action availability supporting the 21:30 New York signal cutoff. Midnight bar timestamps and current fetch dates are not historical publication proof. Liquidity requires lagged ADV and the 1% cap.
6. Reproducible compile/synthetic tests using separately labelled fictitious observations before run sign-off; this revision runs none.

If a fund liquidates/terminates/changes mandate, stop new entries on its first genuinely public notice. Retain executed exit or authoritative legal final distributions/receivables, correct dates and all costs. Never infer terminal value from last close or substitute another fund. Unresolved terms/identity block the affected evaluation. Missing/halting observations are neither executable nor zero returns. This ETF audit is separate from, and does not wait on or waive, H1's company-level delisting repair.

## 3. One exact causal rule, execution and funding

Use NYSE exchange sessions, timezone-aware actual/early closes, and decimal effective-entitlement total returns constructed **only after approvals**. For u:

`b_u=(2/3)r_SHY,u+(1/3)r_TLT,u`; `e_u=r_IEF,u-b_u`.

b is a mathematical relative-value reference, not an uncosted executable daily-rebalanced portfolio. At final NYSE session t of each ISO week:

- `D_t=sum(e_u, u=t-L+1,...,t)`; **L=20** sessions.
- `s_t=sample_sd(e_u, u=t-S+1,...,t)`; **S=60**, sample denominator S−1.
- `z_t=D_t/(sqrt(L)*s_t)`; dimensionless sizing statistic, not a normal-probability estimate.
- `a_t=A*tanh(z_t)`; **A=.20 NAV**.
- Targets: `IEF=.45-a_t`; `SHY=(2/3)*(.45+a_t)`; `TLT=(1/3)*(.45+a_t)`; cash **.10**. Positive z reduces IEF; negative z increases it. ETF gross target **90% NAV**, all ETF weights positive.

No hedge fitting, optimiser, pair selection, threshold, vol target or half-life fit. Undefined/zero sd, missing input or unresolved action means no new target, failed data QA and halt pending review; never silently continue a successful-looking subset.

Signal cutoff **21:30 New York time on t**, after all required inputs have actually become available (09:30 SGT following calendar day in US daylight time; 10:30 SGT in US standard time). Earliest primary execution is **broker-native MOC at the next actual NYSE session's close**. Submit at least ten minutes before Alpaca's cutoff, observing early-close rules. Never fill t's close. Hold until next weekly target executes, normally five sessions; include the entire decision-to-fill gap. The sole delay stress executes every primary target MOC one additional exchange session later; no venue choice or favourable-price selection.

Simulation starts each scored window flat in cash. Reference NAV **$100,000**, not the actual account. Whole-share sells settle/release usable cash before funded buys; round buys down. Cap by settled/unrestricted cash after fees and receivables restrictions; pro-rata scale all buys down if necessary, never borrow. Residual cash earns zero and remains cash; no short-proceeds credit. Nonnegative cash and long holdings ensure actual gross **<=100% NAV** despite price drift. Apply actual cash/receivable constraints in historical and prospective shadow accounting alike. Every order <=1% lagged 20-session consolidated dollar ADV, with stricter regular-session participation constraint if available. Oversized orders/fill rejects are execution failures reported without outcome-based exclusion. Validate current tradable/active identity before any eventual paper order.

No shorts, margin debit or collateral dependence: borrow is **N/A**, not evidence of free historical borrow. Introducing any short is outside this prereg and requires a new trial/spec, collateral feasibility, contemporaneous shortability and the desk **>=10% unknown-history borrow** gate.

## 4. Cost rule — verified signed TCA owner pin plus validator cost addendum

Verified signed TCA owner cost decision: the internal review record, SHA256 **b46b52c033f1217ab91df599d867cd9404dcc0b9fa3b877806e1ab02c78bb9d1**, read in full and exact-hash verified. The validator's cost addendum remains binding: the internal review record, SHA256 **3281296b5b68947d3b70108166c7bafd25e5eef105549cbf89442e78fd7ed3b2**. Its earlier relay-only provenance is now supplemented by the verified signed memo, not silently relabelled. **Where this draft, the TCA owner's memo, the validator's addendum or desk minima differ, the stricter/higher cost requirement wins.** The common 8-bps floor and full component sum remain; the memo's discussion of a possible six-bps floor for IEF/TLT does not lower this draft. This pins cost methodology only, not data acceptance, freeze acceptance or DEV authorisation.

For every traded dollar and each side, in bps:

`c=max(8, f + max(2, documented_lagged_half_spread_bps) + 1.0*sigma60*sqrt(Q/ADV20)*10^4 + buffer)`.

Buffers: **SHY 4 bps; IEF 2 bps; TLT 2 bps**. sigma60 is daily-return volatility in decimal units; Q is order dollar notional and ADV20 is lagged 20-session dollar ADV, using information available at the signal cutoff. f includes applicable SEC/TAF/CAT fees and conservative rounding; do not extend a temporary fee holiday to all history. Missing spread history uses **at least 2 bps half-spread**, never a backfilled October 2026 sample. Higher documented lagged spreads/desk minima govern. k=1.0; **no auction discount**. Primary reference must reconcile to the official close auction, not the SIP daily close.

Base floor **8 bps/side, 16 bps round trip per ETF notional**. Sole 2× stress doubles **every component and the floor**, so floor **16 bps/side, 32 bps round trip**. Both portfolio and active stress Sharpe must exceed zero in confirmation. Break-even bps/side after other expenses must be >=2× base all-in notional-weighted cost. Count absolute actual share changes, initial entry, all rebalances, rounding, final liquidation, rejects/partial executions and risk exits; report NAV and traded-notional denominators. Expense ratios are embedded in fund NAV, not subtracted twice. Delay/gap returns are realised, not replaced by a flat favourable cost. Paper accounting must shadow-reconcile distributions, impact, fees and liquidity: Alpaca paper simulation omits these features and fill realism is not proof of tradeability.

## 5. DEV, contaminated diagnostics and prospective-only confirmation

**Historical classification is final, not a selectable split:**

| Window | Permitted status after explicit authorisation |
|---|---|
| 2016 sessions | Warm-up only, no scored performance |
| 2017 first NYSE session–2021-12-31 | DEV; all inference exploratory, not confirmation |
| All 2022 sessions–2026-10-28 | **Contaminated historical diagnostic ONLY**; never OOS, confirmation, or a pass/fail gate |

There is **no untouched historical holdout**. Validator documents prior evaluation of these ETFs by `validation/backtests/trend_sleeve/` (2016–2026), portfolio/FRAMEWORK OOS work (2017–2026), and 2026 targets/shadows/TCA caches. Neither agent isolation nor directory changes reseal outcomes. No alternate historical window, pseudo-OOS folds, early unseal or selection from diagnostic performance. Any previously described 2022 historical embargo does **not** create a clean holdout: that entire later history is contaminated. Historical diagnostic statistics and stress outputs, if separately authorised, are labelled descriptive and cannot make or break confirmation; unmet source integrity still blocks computation. No such diagnostic read/run is authorised now.

**Only prospective sealed confirmation can satisfy STANDARD.** Before the first live signal: Daniel must approve the horizon/resource commitment; the fund manager/validator must sign the exact forward calendar and sealing/observation plan; freeze rule, executable code, tests, costs, immutable historical warm-up manifest, prospective data schema/source/availability contract and all hashes, including the 19 reservations and cumulative trial ledger. New future inputs receive append-only timestamped provenance/content hashes as they arrive; impossible future data hashes are not fabricated at freeze. No signal generation, forward collection/observation clock or paper simulation starts under this draft.

The future protocol must prescribe its first eligible signal/scored start **in advance**, never choose it after seeing markets. Require an embargo >=**72 NYSE sessions** (maximum S across locked neighbours, longer than the holding period; >=STANDARD's overlap rule) between the last outcome-informed development/diagnostic or design-change session and first prospective decision. Historical warm-up/embargo inputs may support causal trailing statistics under the signed selector, but are unscored and never count as prospective observations. No retrospective trading of those dates. All fifteen variants use the same prospective scored window, data-availability contract and embargo; no parameter-specific favourable starts.

Score forward only after the signed seal and that predeclared eligible start; conservatively require **>=3 full calendar years of actual scored prospective time AND >=100 distinct allocation-change weekly episodes** before a validation decision. Embargo, warm-up, delayed activation, cash waiting before the eligible start, or historical diagnostics do not satisfy either minimum. Start flat; charge initial execution and all subsequent costs. Freeze a future evaluation end/close-liquidation rule before activation: no performance-triggered stop date; if 100 episodes have not accrued at the scheduled three-year review, continue unchanged to the predeclared subsequent annual review(s), without interim result-driven redesign. Risk halts remain in results; do not reset the clock. The fund manager/validator must approve the specific dates, custody/access sealing and review schedule before any first signal. They are **UNSET / NOT APPROVED** now, not permission to begin.

Theoretical earliest three-year statistical maturity is roughly late 2029 **only if promptly authorised**, and later with a later start/embargo or insufficient episodes. No historical full PASS; even prospective success remains subject to the accepted selection-bias CONDITIONAL PASS cap. If Daniel rejects this horizon, park rather than alter standards. Freeze DEV conclusions before any prospective observation; outcome-driven amendments invalidate the sealed candidate, need a new prereg/higher N and cannot reuse seen forward observations as untouched confirmation.

## 6. Sentiment — locked diagnostic, not a tuned filter

Flight-to-quality sentiment can turn true curve repricing into apparent inventory reversion. No justified sentiment direction filter is established, so **no sentiment variable changes weights or entry**. No LLM/historical rescoring. Fixed diagnostics: VIX >25 versus <=25; above/below expanding median of prior eligible observations; and STANDARD's ex-post whole-window sample-median split, never called a causal predictor.

Use pinned Cboe archive metadata and NYSE sessions. An as-available diagnostic requires independently established first publication <=signal cutoff and VIX observation at least two exchange sessions earlier. Missing availability stays unknown; no inferred SLA from the README's one late CSV update or 16:15 options close. Without proof, report revised-history descriptive regimes only, explicitly noncausal. Pin future availability before prospective activation. Historical regime figures are contaminated diagnostics only; prospective regime bars below apply only at authorised confirmation. Never add an ex-post filter to rescue a failed regime. No FRED/ALFRED input; future macro use needs new spec with pinned vintages/release timestamps, not latest revised observations.

## 7. Validation bars and kill rules — confirmation means prospective only

Executable **static benchmark only**: IEF .45, SHY .30, TLT .15, cash .10, identical weekly schedule, execution/cash/liquidity constraints and its own costs. Active daily return is primary NAV return minus benchmark NAV return, not an executable financed short book. Benchmark stays counted but is never a selectable strategy. All historical statistics below are **DEV/contaminated diagnostics only**; numerical confirmation thresholds apply solely to the sealed prospective window, except the explicitly labelled full-history exploratory t statistic.

- >=10 years audited historical source coverage; >=3 genuinely untouched scored prospective years **and >=100 actual weekly allocation-change episodes**. Do not count ETF legs, partial fills or overlapping daily observations as separate episodes. Report 60-session blocks/effective sample size too.
- Prospective annualised daily net NAV and active Sharpe, each after the **20% haircut, >.5**. Both unhaircuted stressed Sharpes >0 at 2× all costs. Positive bond beta without active edge fails.
- New-signal HAC/Newey–West t>=3.0 on prospective NAV and active means, fixed lag60. Also report STANDARD's full-scored-history t>=3 requirement with that history's contamination explicit; it is exploratory and cannot replace prospective t. DSR>=.95 on prospective evidence with **global N>=412, raised** as §8 requires; disclose SR0, N, T, skew, kurtosis and variance of trial Sharpes. Missing reconciled ledger/statistics = insufficient evidence, never local N or fabricated DSR pass. Use correlation-implied effective N only with the full justified trial matrix.
- **PBO CSCV S=16 over exactly the 15 parameter variants** (primary +6 neighbours +8 corners). Cost/delay stresses, benchmark and abandoned concept never pad this matrix. DEV PBO is a diagnostic only. Prospective PBO <.20 required, <=.05 statistical full-pass threshold (the bias cap still binds). Fifteen strongly correlated neighbours make PBO weak evidence; disclose that, not PBO=0 by construction. No contaminated historical PBO used as a confirmation gate.
- Prospective yearly, lagged-SPY200-day-MA and fixed VIX regimes: no single year >40% positive total net P&L; nonpositive total fails; no regime Sharpe<−.5 (no preregistered regime hedge). Report exposure, duration/convexity mismatch, turnover, leg holdings, costs, rejects and break-even>=2× base all-in cost. Any missing required evidence is insufficient, not omitted.
- All 14 locked parameter neighbours must retain prospective NAV and active Sharpe >0 and >=50% primary. No selecting a neighbour. Fixed incremental-mean regression controls: IEF−SHY, TLT−IEF, SPY−cash, FF momentum and short-term reversal; active intercept positive with HAC t>=3. Revised FF factors are ex-post controls only. Rank defects = insufficient evidence, not favourable dropping.
- Existing-family **holdout |rho|>.5** check must explicitly include the **trend-sleeve family at documentary identity `validation/backtests/trend_sleeve/`**, which already uses IEF/SHY/TLT, plus the existing book. No claim it is currently authorised to trade. Obtain the validator's disposition before any allocation; this draft reads no family/book return series. Prospective overlap must be compared on matching approved observations, not treat a contaminated historical correlation as independent confirmation.
- Maximum daily-close NAV and compounded-active-index drawdown <=10% in confirmation. At 8% NAV high-water drawdown, cancel new targets and liquidate at next executable MOC with costs; remain cash for that entire scored window. Include gaps/costs that can breach10% and fail; no truncation/reset. Apply identically to all executable configurations and benchmark. Required independent risk-stop/limit integration must be reconciled **before** freeze; no discretionary or unlogged stop variants.
- Post-approval sizing expectation=min(prospective SR,.74×DEV SR), then the selection haircut. Re-review/halt for data/identity failures, rule/source/cost changes, realised costs>1.5× assumed, paper DD>2× validated max DD, or >=60 completed paper episodes with net SR<max(0,.5×haircut expectation). No automatic retuning.

Historical underperformance can be described but cannot be presented as prospective FAIL/PASS. This does not waive prospective hard bars, source-integrity blockers, risk halts or the option to park before activation. No numerical evidence is computed by this draft.

## 8. Lock all 19 reservations; no cuts, substitutions or extra runs

Binding review: the internal review record, SHA256 **aae200e9b0000eed531ce891099d5fae9f0f5b0b5a7efba79ac6860255380c40**, read in full. The review accepts no data and authorises no DEV run. Its reservation lock/count is incorporated exactly; outcome-blind v0.2 compliance edits do not erase any reservation. No extra configuration is authorised by this revision.

| Locked reservation IDs | Specification | Count | Permitted role only after authorisation |
|---|---|---:|---|
| P01 | L20/S60/A.20; base costs; next-session MOC | 1 | Sole primary |
| P02–P07 | One-at-a-time L16/24, S48/72, A.16/.24; other primary settings fixed | 6 | Neighbour checks, not selectable |
| P08–P15 | All eight Cartesian corners L∈{16,24}, S∈{48,72}, A∈{.16,.24}; primary cost/execution | 8 | Joint checks, not selectable |
| C16 | P01 only, 2× ALL costs; floor16bps/side | 1 | Cost stress only |
| D17 | P01 only, +1 NYSE-session MOC delay; base costs | 1 | Execution stress only |
| B18 | Static IEF.45/SHY.30/TLT.15/cash.10 | 1 | Executable **benchmark only**, never an alternative |
| X19 | Abandoned NAV-discount idea, source-feasibility screen only | 1 | **Never run or revive** under this prereg |
| **Total locked** | | **19** | No sweeps/threshold shopping |

Only P01–P15, C16 and D17 are allowed strategy execution configurations; B18 can be simulated only as the prescribed benchmark. X19 is an accounting reservation, not code/data permission. No other universe, parameter, cost level, venue, threshold, filter or optimiser. Changing structural constants/risk rules is also a new prereg/higher N, not a free “diagnostic.” No selecting best DEV or prospective variant; primary remains P01. Keep stress/control outputs separate from the 15-column PBO matrix.

Global DSR floor is **N>=412 (=max(212,393,80)+19)**, **raised by reconciled Treasury-ETF trend-sleeve and portfolio trials** and any later unique desk trials not already included. Never substitute stat-arb-researcher-local231 or19. Earlier stat-arb-researcher48 trials remain included; exact cross-ledger overlaps and cumulative Treasury trial count are unresolved. The fund manager must publish the reconciled ledger; until then DSR is insufficient evidence. Do not sum overlapping ledgers blindly or reduce N due to missing return series. Reconcile required global statistics/matrices without padding the 15-variant PBO matrix with incompatible controls/costs. No shared ledger is edited here; these are locked local reservations awaiting that reconciliation.

## 9. Remaining gates and provenance

Before **DEV**: the validator accepts this revised spec; fund manager reconciles global ledger; data owner delivers/obtains the validator's single-hash acceptance of §2 v1.3 SIP identity/distribution/availability/official-auction audit; the verified TCA owner signed cost pin in §4 is incorporated into the validator's final freeze acceptance; risk/execution/cash rules and code/tests are pinned and authorised. No data acceptance is implied by a document hash.

Before **prospective activation**: all above; **Daniel approves multi-year horizon**; signed start/end/review calendar, >=72-session embargo, future append-only source/availability and custody/sealing plan; frozen code/rule/cost/manifests before first signal; no clock or first observations until explicit activation. Confirmation cannot finish before >=3 scored forward years and100 allocation-change episodes; accepted20%haircut/CONDITIONAL PASS cap remains.

Read-only sources for this revision: the two validator documents cited/hashed in §§4/8; prior v0.1 draft; and the subsequently supplied exact-hash-verified signed TCA owner memo in §4. The initial v0.2 search's missing-memo state is preserved in the pre-pin archive, not retained as a current blocker. No broad review, new source lookup/data pull, data observations or results/return-series reads. An unrelated H1 cost-floor line appeared in a bounded metadata search, not an H1 return or data observation; no H1 file was changed. Earlier v0.1 documentation/search incidental market-number exposures remain disclosed in its preserved §5; this revision neither conceals them nor reopens those sources.

v0.1 remains byte-for-byte at `$QR_DESK_DIR/statarb/etf_original/PREREG_TREASURY_BULLET_BARBELL_v0.1_DRAFT.md`, SHA256 **167e706ee193657cb76ee303579eee379fb13e6d87654119658be749bb8566e5**. Before this cost-pin-only amendment, the initial v0.2 bytes were archived unchanged at `$QR_DESK_DIR/statarb/etf_original/archive/PREREG_TREASURY_BULLET_BARBELL_v0.2_PRE_TOMAS_PIN_b19e2c28.md`, SHA256 **b19e2c28ecf8a489f19941e1452446718854c2e0b7b27b7ecd3add4cca79297f**. No H1/frozen prereg/sidecar, shared data, quarantine, holdings, agent messages, signals, clock or trading changed. This file is a draft only.
