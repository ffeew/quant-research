# PRE-REGISTRATION v3: Stat Arb original ideas
_Public copy; internal audit references removed. Pre-registration content unchanged._

H1 is the sub-industry bellwether catch-up; H2 is the earnings read-through to already-reported peers.

- **Owner:** Stat Arb desk.
- **v3 written:** Fri 6 Nov 2026 SGT (UTC+8), from the box clock. v2 (archived) was returned for amendment by validation review on 6 Nov 2026. v1 is archived.
- **Status:** v3 PROPOSED. This answers the validation review's "RETURN FOR AMENDMENT" on B1 and B2.
  - The registration is **not frozen** until validation review accepts this file at a recorded sha256.
  - **No DEV return trial of any kind** will run before that acceptance.
  - After acceptance, any change is logged in §12 and counts toward N.
- **Returns computed so far: none.** No return, P&L or Sharpe of either rule has been computed on any period.
  - One script, `stops_dev.py`, read DEV price paths. It ran and its output was **never opened** (§11).
  - **Validation review expressly waives opening the quarantined `stops_dev` outputs** (2026-11-06); they remain unread.
  - Everything else is signal construction on DEV only: turnover, cost, counts and capacity. The Stage A / sealed-holdout runner exists but has **not** been executed on any returns (syntax-check / `--help` only).
- **Cards** (amended to v3 in the same sitting; sha256 pinned internally):
  - H1 card: sub-industry bellwether lag
  - H2 card: earnings peer read-through
- **Governing documents:**
  - `validation/STANDARD.md`, including Addendum A;
  - `risk/LIMITS.md` (H1–H3, H6–H9, §4, panic flag);
  - the desk risk decision on stops (`risk/decisions-log.md`);
  - `DESK_RULES.md` #1, #3, #4, #5.
- **LLM disclosure (Addendum A):**
  - Both ideas, the rules, the code and this text were produced by an AI research assistant (an LLM-based agent acting as the desk's stat-arb researcher), from desk data and its literature knowledge.
  - No LLM output is used as a trading input or signal. No text or sentiment data are used.
  - The assistant's training knowledge may include the 2022–2026 period. This is one reason the holdout is treated as quasi-OOS (§9).

## 1. Hypotheses (unchanged in substance from v1)
- **H1.** Within a GICS sub-industry (≥ 4 eligible members), an unusual L-session return gap between the 2 most-traded names (leaders) and the rest (followers) closes over the next 4 weeks. The book is long the lagging side and short the leading side, dollar-neutral per group.
  - **Predicted sign:** positive return on that long/short spread.
- **H2.** When a sub-industry's EDGAR-timestamped reporters on d0 react strongly together (|N| ≥ 1.5), members that already reported this season drift in the direction of N over the hold, against their sector ETF.
  - **Predicted sign:** positive return on sign(N) × (follower − β·ETF).

## 2. Data, pinned by snapshot hash (desk rule #5; no Alpaca calls; desk data store only)
- **Primary pin: frozen release v1.2** (top hash and per-file sha256 values pinned in the internal release manifest). Files used:

| File (under `releases/v1.2/`) | sha256 |
|---|---|
| `bars/daily/total_return/daily_total_return.parquet` | pinned (internal manifest) |
| `universe/sp500_membership.parquet` | pinned (internal manifest) |
| `universe/universe.parquet` (current GICS, as of 2026-10-30) | pinned (internal manifest) |
| `universe/sp500_member_days.parquet` (security master v1.2b) | pinned (internal manifest) |
| `reference/security_master.parquet` | pinned (internal manifest) |
| `earnings/earnings_events.parquet` (v12b, mid-fix; 30,236 rows, 722 symbols) | pinned (internal manifest) |
| `factors/ken_french/ff5_daily.parquet` / `mom_daily` / `st_rev_daily` | pinned (internal manifest) |
| `sentiment/vix/vix_vix3m_daily_20261030.parquet` (VIX regime split only) | pinned (internal manifest) |
| `bars/daily/adjusted/SPY.parquet` (SPY 200-dma regime split only) | pinned (internal manifest) |
| `tca/tca_scripts/cost_model.py` (TCA v1.1; outside the release) | pinned (internal manifest) |
| `statarb/original/turnover_dev.py` (signal construction, v4) | pinned (internal manifest) |
| `statarb/original/backtest_h1_h2.py` (Stage A / sealed-holdout runner; v3) | pinned (internal manifest) |
| `statarb/original/costs_original.py` (cost overlay; required ≥10%/yr borrow) | pinned (internal manifest) |
| H1 card v3 | pinned (internal manifest) |
| H2 card v3 | pinned (internal manifest) |

- **Stage A dependency (hard).** Stage A waits for two things:
  1. **The data store's next frozen snapshot (v1.3)**, which carries the final earnings fixes. The v1.2 earnings file is explicitly mid-fix.
  2. The **desk-wide 8-K 2.02 SUE factor**, frozen.

  At Stage A, the turnover and counts in §8 are re-run on v1.3 with the same script. The new hashes are recorded in §12 before any return is computed. If v1.3 adds the PIT sub-industry map, the delisting returns or the pre-announcement `event_type` flag, §5 says how each is used. Using them is not a choice made after seeing returns.
- **Read-time filtering (X14).** Every script reads with pyarrow row filters (`filters=[("session_date","<=",2021-12-31)]`, and `announce_date_et <= 2021-12-31` for earnings). No row after 2021-12-31 is loaded during DEV work. The sealed holdout run loads the holdout only in the single sitting of §9. Target weights are shifted one session in the backtest: signal at t, fill at t+1.
- **First-availability timestamps (Addendum A):**

| Input | First publicly available | First session it can affect |
|---|---|---|
| SIP close, volume, total return | Official close after 16:00 ET on t; store pipeline ≈ 07:30 SGT on t+1 | MOC at close t+1 (primary); MOO t+1 is a sensitivity |
| EDGAR 8-K 2.02 acceptance (H2 trigger) | `knowledge_time_utc`, exact for 28,540 rows (`exact_acceptance_time`) | `reaction_session` d0 (BMO / INTRADAY same day, AMC next); signal at close d0, fill close d0+1 |
| Earnings dates for H7 and "already reported" | Backtest: realised dates moved to the **earliest possible session** (§5.3) plus a 2-session margin. Live: Nasdaq calendar plus the 2-session margin (no historical vintages) | Exclusion decided at signal time |
| S&P 500 membership | Wikipedia change table, effective at the open of `effective_date`; revisable source | Same session |
| GICS | Current snapshot, first available 2026-10-30, **not PIT** | Look-ahead (§10) |
| Ken French factors, desk SUE, VIX, SPY 200-dma | Controls and regime labels only; vintages pinned | Not trading inputs |
| Sentiment, text, LLM scores | **Not used** | — |

## 3. Named primaries (X4; no selection rule)
Each idea has exactly one primary, fixed now from turnover, cost and LIMITS fit. No return information was used. `stops_dev` outputs were never opened.

| Idea | Primary | Why (ex ante) |
|---|---|---|
| H1 | **L = 60**, \|z\| ≥ 1.0, 2 leaders, groups ≥ 4, 4 overlapping weekly tranches held 4 weeks, **execution close_t1 (MOC at t+1)** | Lower DEV turnover than L = 20 (v1 counts: 21.9× vs 25.7×). MOC costs less than MOO in the TCA cost model (6.69 vs 11.73 bps per side, TCA, v4). |
| H2 | **H = 40 sessions**, \|N\| ≥ 1.5, already-reported window 50 sessions, 0.5% unit, at most 100 concurrent, **execution close_t1** | About half the turnover of H = 20 (v1: 16.4× vs 30.9×). Lower drag. MOC is cheaper. |

- `open_t1` is **not** a candidate. It is run once in the sealed sitting as a reported execution sensitivity only (§7).
- L = 20 and H = 20 are dropped. They are never run, but they stay in N (§7).

## 4. Exact rules: primaries
The full text is in each card's "Exact rule" section. The summary here must match the cards.

**H1.**
- Weekly signal at the last session of each week.
- ELIG on t: PIT S&P 500 member; raw close ≥ $5; 20-session mean $volume ≥ $20M; volume > 0; no |ret| > 40% in the last 20 sessions; ≥ 252 return observations; current GICS sub-industry.
- Groups: sub-industries with ≥ 4 ELIG members.
- Leaders: the top 2 by 60-session median $volume.
- d = EW(leaders) − EW(followers). z = Σ_60 d / (sd(d over the prior 192 sessions) × √60).
- If |z| ≥ 1: z > 0 → long followers, short leaders; z < 0 → the reverse.
- Each leg is 0.5 of the group budget, equal-weight within the leg. Groups get equal gross within a tranche. The 4 tranches each carry 1/4 of sleeve gross.
- H7 name filter (§5.3) is applied after the leader/follower split. If a leg is empty, the group is skipped for that tranche.
- Entry MOC at t+1. Exit MOC on the session after the week-end 4 weeks later.

**H2.**
- **Reporters on d0:** ELIG at d0−1, current GICS, with `reaction_session` = d0 and `timing_quality` = `exact_acceptance_time`.
  - Acceptance times within ±5 min of 09:30, 13:00 (early close) or 16:00 ET are **excluded** from triggers as timing-ambiguous.
  - Reaction = residual against the sector SPDR, or SPY if the SPDR has < 252 sessions. β is OLS over the 252 sessions before d0. The residual is standardised by its σ over the last 60 sessions.
  - N_g = the mean reaction over g's reporters. Trigger when |N_g| ≥ 1.5.
- **Followers:** ELIG members of g at d0−1, not reporting on d0, whose earliest-possible own release session (§5.3) lies in [d0−50, d0−2], **and with no own earnings row of any source in [d0−1, exit+2]**.
- **Follower β excludes d0:** OLS over sessions d0−252 … d0−1.
- **Position:** sign(N) × 0.5% of sleeve in the follower, and −sign(N) × β_f × 0.5% in its sector ETF (SPY fallback).
- Entry MOC at d0+1. Fixed hold of 40 sessions, exit MOC.
- At most 100 concurrent positions. The strongest |N| goes first (ties by symbol). A name that is already live is not opened again.

## 5. Common rules: stops, LIMITS and data handling
**5.1 Stops: fixed ex ante (X2, desk risk decision).**
- **Leg stops.** Every leg, including H2 ETF hedges, carries a resting full-quantity broker stop at **3 × ATR(14)** from the entry fill.
  - It is set at entry and never loosened.
  - ATR(14) uses the 14 sessions to t, which are known before the order.
- **Basket spread stop (primary exit).** The basket is an H1 group-tranche or an H2 follower-plus-hedge pair. If its mark-to-close loss reaches **1.0% of equity**, all its legs are flattened at the next session's MOC (the close-t print is only final after the 15:50 ET MOC cutoff).
- **Why 3×ATR.** It is the risk function's maximum allowed width. Spread legs need room because the basket stop, not the leg stop, is the intended exit, and the leg stop is catastrophic protection.
  - The choice was **not** made from stop-hit rates. The `stops_dev` output was never read (§11).
  - No stop-width grid is registered. One 2×ATR rerun per idea is a counted sensitivity (§7), not a candidate.
- **Fill convention (H6).**
  - A leg stop fills at the stop price if the session's range touches it, or at the **open** if the open gaps through it.
  - After a leg stop, the remaining legs of that basket are flattened at the next session's MOC.
  - No re-entry within that tranche or position.
- **Per-leg sizing (H2 limit):** |w_leg| ≤ min(rule weight, 0.95% of equity / (3·ATR14/price)).
- **Costs and turnover.** Stop-out and spread-stop trades are costed with the same cost model and included in realised turnover. They are measured only in the sealed runs.

**5.2 LIMITS (X12).**
- **H1, per name.**
  - Exposure is netted across tranches and hedges, and trimmed to **≤ 9.5% of equity**, taking 1.0 sleeve gross = 58% of equity (H3 buffer). The excess is not reallocated.
  - DEV, signal-only (v4): H1-idea uncapped max 15.95% of equity (NVDA), so the cap is needed. It binds on 0.21% of held name-days.
  - The H2 idea's max netted name is 5.35% of equity (XLV hedge), so the cap does not bind.
- **H2 hedge aggregation.** Each position owns its hedge quantity. Orders are netted per symbol only at execution, and P&L is accounted per position. When a position exits or is stopped, its own hedge quantity is unwound in the same MOC.
  - Aggregate notional per hedge ETF is ≤ 9.5% of equity. A new position that would breach this is skipped, not scaled.
- **H3.** Sleeve gross ≤ 58% of equity, with both legs and hedges counted. Combined desk H3 across sleeves is unknown to me and is the risk owner's call.
- **H6:** see §5.1.
- **H7.** Live rule simulated:
  - no position (long or short) is held through its own release;
  - a name is excluded if any own earnings row's earliest-possible session falls in (entry − 2, exit + 2], i.e. with a 2-session margin.
- **§4 short-gap stress.** Computed daily in the simulation at sleeve level: Σ|short| × 2 × |stop − last|. Above 5% of equity is flagged; above 7%, new short entries are blocked that day.
- **H8/H9.** Drawdown breakers are simulated at sleeve level exactly as LIMITS specifies.
- **Panic flag "no new loser-shorts".** Classification is for risk to decide (question raised). Until decided, the simulation blocks new H2 short-follower entries while the flag is on. H1 shorts are always the relatively outperforming side, and risk should confirm this classification.

**5.3 Earnings timing (X1, H1 fix).**
- **d0 for triggers:** `reaction_session`, exact rows only.
- **Earliest-possible session** for H7 and "already reported":

| Row type | Count | Earliest-possible session |
|---|---|---|
| `exact_acceptance_time` | 28,540 | `reaction_session` |
| `unknown_assumed_amc` | 1,137 | min(`reaction_session`, `announce_date_et` session), i.e. as if BMO |
| 10-Q/10-K fallback (`edgar_10q10k_fallback`) | 307 | 5 sessions before the filing session |
| `nasdaq_label` | 252 | `reaction_session` |

**5.4 Survivorship and PIT handling (X13, citing STANDARD §2).**
- **21.6% of DEV member-month rows have no current GICS.** These rows are **excluded from all groups**, as reporters, followers, leaders and followers alike. They are not imputed.
  - The 20% Sharpe haircut stays live until the data store's PIT sub-industry map lands.
  - When it lands, one PIT-sector rerun per idea is a counted sensitivity.
- **Reclassification look-ahead is disclosed:**
  - the 2018 Communication Services reshuffle (XLC exists from 2018-06; SPY is the hedge before it has 252 sessions);
  - the 2023-03 move of payments names to Financials.
- **Membership** comes from the Wikipedia change table, which is revisable. The v1.2 pin is used.
- **Null delisting returns.**
  - Base: a position in a name that delists without a return is closed at its last close.
  - Delisting stress (counted): −30% for longs and 0% for shorts on any null delisting return.
  - If v1.3 supplies delisting returns, base uses them.
- **Member-days without bars (security master v1.2b):** 54 in DEV 2017–2021 (14 / 13 / 8 / 12 / 7), 104 across all years. These names drop out of groups on those days. The v1 counts (1,304 → 405 per year) were stale and are withdrawn.
- **Borrow (no PIT history before 2026-10-29).** Validation review 2026-11-06 + TCA `cost_model.md` §8 and the TCA cost check:
  - **REQUIRED gate (pass bar):** while historical borrow is unknown, EVERY historically unknown short is costed at **≥ 10%/yr** — H1 single-name shorts, H2 follower shorts, **and H2 sector-ETF hedge shorts; no ETF exemption; not limited to L3/L4**. Applied via explicit `annual_rate >= 0.10` in both daily `borrow_cost` and `annual_cost_drag` (overrides `BORROW_RATE_ETB_DEFAULT = 0.0025` so the default cannot silently apply). **Net Sharpe > 0 else FAIL on costs.**
  - **GC counterfactual 1%/yr:** labelled general-collateral path; **never the pass bar** while rates are unknown.
  - TCA references (report-only): 25 bps/yr model ETB default; 50 bps/yr ordinary sensitivity.
  - A narrower L3/L4-only 10% diagnostic remains a counted sensitivity (§7); the required all-shorts ≥10% path re-prices the primary and does not add to N.

## 6. Gates (all required; evaluated once, in the sealed holdout sitting)
**Cost path for all pass bars below.** While no PIT borrow history exists, the pass bar uses the **REQUIRED unknown-borrow ≥ 10%/yr** path on every historically unknown short (H1 single-name shorts, H2 follower shorts, **and H2 sector-ETF hedge shorts; no ETF exemption**), plus STANDARD MOC floors (`max(model close, floor+hs)`; L3 = 10 bps + hs). The **1%/yr GC path is a labelled counterfactual only and is never the pass bar** (B1, 2026-11-06; TCA cost_model.md §8).

**Stage A (DEV, after validation acceptance, v1.3 and the desk SUE).**
- Primary only, on DEV 2017-01-03 → 2021-12-29 exits.
- Pass: **raw DEV net Sharpe > 0.85** at the required unknown-borrow ≥10%/yr + STANDARD floor path, with the predicted sign. The 0.85 applies because the current-only GICS map is kept (0.68 / 0.8). If v1.3 delivers the PIT map before Stage A, the primary uses it and the bar is 0.68.
- A fail kills the idea and the holdout is not opened.
- Stage A is reported in full: by year, long and short legs, turnover; GC 1%/yr counterfactual reported alongside.

**Holdout (Stage B), primary:**
1. **Unknown-borrow cost gate (REQUIRED; B1).** Net Sharpe > 0 at ≥ 10%/yr borrow on every historically unknown short (incl. H2 ETF hedges), else **FAIL on costs**.
2. **Sharpe.**
   - Net Sharpe after the 20% survivorship haircut > 0.5, i.e. **raw holdout net Sharpe > 0.625**, at the required unknown-borrow ≥10%/yr + STANDARD floor path (L3 floor 10 bps + half-spread).
   - Net Sharpe > 0 at 2× trading costs on that same path.
3. **DSR ≥ 0.95** at N = 212 (§7).
   - V[SR] = the cross-sectional variance of **net** annualised Sharpe across all logged trials of the family.
   - T = holdout sessions (1,150 planned).
   - Skew and kurtosis are those of the primary's daily net returns.
4. **t ≥ 3.** Use the Newey-West t-stat of daily sleeve net returns over the holdout, with 20 lags for H1 and 40 lags for H2.
5. **Alpha t ≥ 3.** Holdout daily sleeve net returns regressed on FF5 + Mom + ST_Rev + the **desk 8-K 2.02 SUE factor**.
   - Newey-West as above. The sample runs to 2026-09-30 (factor end).
   - SUE factor: acceptance-time based, XBRL fallback share logged, frozen before Stage A, months with < 300 names dropped. More than 10% of months dropped caps the verdict at CONDITIONAL.
   - The same SUE is used in the cross-sectional tests (card §incremental): Fama-MacBeth for H1, event level for H2. Each also needs t ≥ 3 on the rule's variable.
6. **PBO < 0.20.** Computed by CSCV with **S = 16** (STANDARD §4) over the idea's configs in the single sitting: **H1 = 9 configs** (primary + 8 neighbours); **H2 = 11 configs** (primary + 10 neighbours, incl. unit ±20%).
7. **Neighbourhood.** Every ±20% neighbour has holdout net Sharpe > 0 and ≥ 50% of the primary's (H2 includes unit 0.4%/0.6%).
8. **Regimes.**
   - SPY above/below its 200-dma (from v1.2 `SPY.parquet`).
   - VIX below/above its holdout median, and VIX > 25 (from `vix_vix3m_daily_20261030` only).
   - **Any regime net Sharpe < −0.5 fails.**
9. **Year cap.** No single calendar year contributes > 40% of holdout P&L.
10. **Break-even cost ≥ 2×** the assumed trading cost on the required path.
11. **Capacity.** ≤ 1% of ADV per order, with participation capped at 1% of 20-day ADV in the simulation (unfilled remainder carried to the next MOC). At $100M capacity stress: exclude or hard-cap L4; TCA notes I1_L20 had 6.09% of L3 trades above 1% ADV (max 19.4%) without the cap — L60 $100M not independently re-run by TCA.
12. **Sample.** H1 ≥ 30 independent 4-week periods (the holdout has 1,150 / 20 ≈ 57). H2 ≥ 100 OOS positions.
13. **Survivorship.** 20% haircut (STANDARD §2), as in gate 2.
14. **Publication haircut.**
    - STANDARD §6 applies **0.40**, given the prior art Hou 2007 (H1) and Thomas & Zhang 2008 (H2). **Stands** per validation review 2026-11-06.
    - The novelty case for 0.74 is in the cards: the late→early direction for H2, and the bellwether-gap construction with the H7 filter for H1. Validation review decides it; the owner accepts 0.40 as default.
15. **Verdict ceiling.** **CONDITIONAL PASS**: 9.8 years of history, current-only GICS, no PIT borrow.
16. **Reported, not gated:**
    - long and short legs separately;
    - correlation with the desk book;
    - realised vs estimated turnover, including stop-outs;
    - **k = 1.0 is the model base** (`K_IMPACT_DEFAULT = 1.0`; TCA written confirmation 6 Nov 2026); **k = 0.75 is a lighter sensitivity, not a stress**;
    - GC 1%/yr counterfactual drag and Sharpe;
    - open_t1.

**Overlap with the desk's megacap spillover-reversal idea.**
- If the holdout daily-return |ρ| between H2 (or H1) and that idea's sleeve is > 0.5, the two are treated as one family (combined N), and only one trades: the one with the higher DSR at the combined N.
- DEV position overlap from signal inputs is **not yet computed**. It needs that idea's frozen heavyweight and peer code, and its heavyweight rule uses market cap, which has the Q1-2016 defect. **Hard pre-Stage A commitment:** it will be computed from signal inputs before Stage A and logged in §12.

## 7. Trial count N (X1, X8, X9): **N = 212**
| Component | Trials |
|---|---|
| Validation floor: 80 (v1 `dsr.json`) + 96 (v1 data-rerun sensitivities) + 8 (this programme's v1 grid: H1 L20/L60 × close/open, H2 H20/H40 × close/open) | **184** |
| H1 ±20% neighbourhood, one-at-a-time: L 48/72; z 0.8/1.2; hold 3/5 weeks (3/5 tranches); min group 3/5. n_leaders = 2 has no integer ±20% neighbour and is not varied. | **8** |
| H2 ±20% neighbourhood: H 32/48; \|N\| 1.2/1.8; already-reported window 40/60; max concurrent 80/120; **unit 0.4%/0.6%** (v3; B2) | **10** |
| Per idea: 2×ATR stop rerun, L3/L4-only 10% borrow diagnostic, delisting-stress rerun, PIT-sector rerun (when the map lands), 8-K-SUE-variant run: 5 × 2 | **10** |
| **Total** | **212** |

- `open_t1` for each primary is already inside the floor's 8.
- Cost-multiplier / re-price columns on an unchanged path do **not** count: 2× costs, k = 1.0 (base) vs 0.75 (lighter sensitivity), TCA 25/50 bps, GC 1%/yr counterfactual, and the **required all-shorts ≥10%/yr borrow gate** (re-prices the primary; not a trial).
- The dropped L20 and H20 cells stay counted.
- Any further rerun adds to N and is logged in §12.
- PBO (CSCV **S = 16**): **H1 = 9 configs** (primary + 8); **H2 = 11 configs** (primary + 10). Sensitivities are counted in N but not in PBO.

## 8. DEV signal-construction statistics (v4; no returns; v3 cost arithmetic restated)
- **Run:** `turnover_dev.py` v4, on frozen v1.2 data (v1.2 earnings file).
- **Settings:** $10M sleeve gross; impact k = `cost_model.K_IMPACT_DEFAULT` = **1.0** (model **base**; TCA written confirmation 6 Nov 2026; k = 0.75 is a lighter sensitivity only); L3 floor 10 bps; name cap on.
- **Outputs:** `turnover_dev_v4_primaries_capped.json` and log `run_v4_primaries_capped.log` (hashed internally).
- **v3 borrow restatement** uses the same frozen turnover and cost-per-side numbers; only the borrow rate in `annual_cost_drag` changes. No returns.

| Primary (close_t1) | Turnover × deployed gross | Cost/side TCA / STD (bps) | Drag TCA / TCA×2 / GC-1% / GC-1%×2 / **REQUIRED-10%** / REQUIRED-10%×2 | Break-even bps/$, TCA / GC-1% / GC-1%×2 / **REQUIRED-10%** / REQUIRED-10%×2 |
|---|---|---|---|---|
| H1 L60 | 22.46× | 6.69 / 13.45 | 1.63% / 3.13% / 3.52% / 6.54% / **8.02%** / 11.04% | 7.24 / 15.68 / 29.14 / **35.71** / 49.16 |
| H2 H40 | 16.20× (7.37× sleeve capital) | 5.31 / 10.51 | 0.98% / 1.85% / 2.20% / 3.90% / **6.68%** / 8.38% | 6.08 / 13.58 / 24.09 / **41.22** / 51.73 |

- **GC-1%** = labelled general-collateral counterfactual (never the pass bar). **REQUIRED-10%** = unknown-borrow ≥10%/yr on all shorts incl. H2 ETF hedges (pass bar).
- **open_t1 (sensitivity):**
  - H1: 11.73 / 13.98 bps per side; TCA drag 2.76%; GC-1% drag 3.64%; REQUIRED-10% drag 8.14%.
  - H2: 9.15 / 10.85 bps; 1.61% / 2.25% / 6.73%.
- **Capacity (share of trades above 1% of 20-day ADV):**
  - H1: 0 at $58k, $1M and $10M; 3.15% at $100M; max participation 0.89% at $10M.
  - H2: 0 up to $10M; 0.48% at $100M; max 0.27% at $10M.
- **H1:**
  - 260 weekly rebalances;
  - 7.55 active groups per tranche;
  - average utilisation 0.92;
  - 78.9 names held on average;
  - average hold 22.5 sessions;
  - the H7 filter removes 36.7% of name slots, and 827 signalled group-weeks are skipped;
  - bucket mix L1 / L2 / L3 / L4 = 14.1 / 55.4 / 30.2 / 0.3%;
  - about 65 non-overlapping 4-week blocks in DEV.
- **H2:**
  - 4,316 triggers, of which 2,098 have no eligible follower;
  - 2,073 positions (414.6/yr);
  - 3,607 candidates removed by the own-row window [d0−1, exit+2];
  - 1,878 already live and 1,672 at capacity;
  - average utilisation 0.45;
  - 74.1 names held;
  - 48.1% long;
  - bucket mix 27.1 / 53.1 / 19.4 / 0.3%;
  - 230 of 4,840 trigger reporter-events (4.8%) were accepted within ±5 min of 09:30, 13:00 or 16:00 ET. They are counted above but are excluded under §4, so the true trigger count is slightly lower and is restated at Stage A.
- **Not in these numbers:** stop-out turnover, drift, and the ATR-based H2-limit sizing. All three need price paths and are measured only in the sealed runs.
- **TCA cost-check notes folded in (6 Nov 2026):**
  - Validation MOC cost = `max(model close, STANDARD floor)`; mid-caps 10 + hs (not 5); measured post-floor ~7 bps L2 / ~12 bps L3; H1 $10M blend ~8.8 bps/side.
  - Sector-ETF MOC hedges ~2.7–3 bps/side; net one order per ETF per day (ETF turnover −24% for H40); keep per-position hedge accounting.
  - At $100M uncapped model close (k=1.0) ~7.35–10.42 bps/side (H40/L20); simulate 1% ADV cap with carry; exclude/hard-cap L4. I1_L20: 6.09% of L3 trades >1% ADV (max 19.4%). I1_L60 $100M not independently re-run by TCA.
  - Early closes 27 Nov and 24 Dec 2026 at 13:00 ET; provisional MOC cutoff **12:50 ET** (ASSUMPTION pending Alpaca docs).
  - Limitations: Oct-2026-only spread sample; no stop-out turnover data; no post-earnings close-spread study; Alpaca paper MOC realism unverified; SPY auction pilot produced no fills and is parked.
- **Reading.**
  - On the **required unknown-borrow ≥10%/yr** path the book needs about **36 bps per $ traded (H1)** and **41 bps per $ (H2)** just to clear zero net after costs (~8.0% / ~6.7% of deployed gross per year).
  - The GC-1%×2 counterfactual figures (~29 / ~24 bps) are retained for reading only and are not the pass bar.
  - The first sprint's daily books earned about 1–2 bps per $.
  - This is the main failure risk, and it is stated before any run.

## 9. Splits and embargo (X3)
Session counts come from `exchange_calendars` (XNYS), with no price data.

| Split | Dates | Sessions | Notes |
|---|---|---|---|
| DEV | 2017-01-03 → 2021-12-31 | 1,259 | A position counts only if it **exits by 2021-12-29** (last DEV session − 2-session H7 margin). Positions that would straddle the end are not taken. |
| Embargo | 2022-01-03 → 2022-03-29 | **60** | ≥ longest hold (H2 neighbour 48 sessions; H1 neighbour 5 weeks ≈ 26) + buffer. Nothing is entered or evaluated. |
| HOLDOUT | 2022-03-30 → 2026-10-28 | **1,150** | Entries on or after 2022-03-30. Positions that cannot exit by 2026-10-28 are not taken. Read **once**, in a single sitting, for primary + neighbours (H1: 8; H2: 10) + sensitivities. |

- **Prior exposure (quasi-OOS).** I have seen statarb v1's holdout results, which are different families. The assistant's general knowledge may cover 2022–2026. A forward paper record is the only fully blind test.

## 10. Data-defect exposure (summary; detail in the cards)
- Current-only GICS (21.6% of rows excluded; reclassification look-ahead).
- Earnings file mid-fix (v1.3 pending).
- 1,137 unknown-timing and 307 fallback rows, handled by the earliest-possible rule.
- Item 2.02 pre-announcements are not yet flagged.
- Earnings coverage for former members is thin.
- Null delisting returns are mostly pre-2020.
- 54 DEV member-days without bars.
- Spin-off and corporate-action jumps (40% filter).
- No intraday data, so the stop and MOC fills are modelled.
- No PIT borrow.
- Ken French vintages are pinned.

## 11. Disclosure log (X1, X2, H1, steering 3)
Everything below was signal construction or descriptive work on DEV, unless marked otherwise.

| # | Script | Earnings input | Runs, outputs | Returns used? |
|---|---|---|---|---|
| 1 | `turnover_dev_preH7.py` | store file before the 02:08 rebuild, then mixed (the file changed mid-run at 02:08) | `turnover_dev_123_v0.json`, `_1`, `_2`, `_12`, `_12_h7` + `run*.log` (01:53–02:09 SGT) | Returns entered only the signal formation (gaps, residual reactions), as in every version. No P&L. |
| 2 | `obs_dev.py` | — | `obs_dev.json` (volume shares, release clustering) | No |
| 3 | `turnover_dev_v2pre_reaction.py` (the v1-registered code) | 02:08 rebuild | `turnover_dev_2_h7ts.json`, `turnover_dev_1_h7ts.json` (02:10–02:11) | No P&L |
| 4 | `turnover_dev.py` (renamed, d0 changed to `reaction_session`, after registration) | v1.2 | **never run**; archived as the v3 script | — |
| 5 | **`stops_dev.py`** (not registered) | v1.2 copy | Ran to completion 02:24:52 SGT, before the validation stop order reached me. It loaded DEV adjusted OHLC paths to mark basket spread paths and stop hits for 2× and 3× ATR. Output `stops_dev_v3.json` (99,109 bytes) and `run_stops_v3.log` (29 bytes) were **never opened**. They are moved, together with the script, to a quarantine directory, chmod 000, hashed as bytes only. Nothing in this registration uses them. | **Yes, DEV price paths** (counted as return information by validation review); unread |
| 6 | `turnover_dev.py` v4 | v1.2 | IndexError, no output | No |
| 7 | `turnover_dev.py` v4 (no name cap) | v1.2 | `turnover_dev_v4_primaries.json` / `_uncapped.json` (02:29–02:30); also recomputed the parked share-class idea (turnover only) | No P&L |
| 8 | `turnover_dev.py` v4 (9.5% name cap) | v1.2 | `turnover_dev_v4_primaries_capped.json` (02:31) = §8 | No P&L |

- **Holdout rows in memory (runs 1–5).** These scripts loaded the full parquets (total return 2016 → 2026-10-28, earnings, membership; in run 5, the adjusted per-symbol OHLC) and filtered to ≤ 2021-12-31 **in memory**. No computation used a post-2021 row, but the rows were in memory.
  - Runs 6–8 use read-time filters and never load them.
  - The sealed holdout run will use read-time filters bounded to its own window.
- **Earnings input changed during work.** 02:08 rebuild → v12b (02:16–02:17; frozen in release v1.2). The v1 counts were on the 02:08 rebuild and are superseded by §8.
- **Specification changes after v1 registration**, all disclosed and none made after seeing returns:
  1. d0 is `reaction_session` instead of `first_tradable_session`, per the data store's v1.1 semantics.
  2. Stops go from 2×ATR exit-at-next-close to 3×ATR resting stops plus the −1%-of-equity basket spread stop, per the desk risk decision on stops.
  3. The embargo is lengthened from 39 to 60 sessions.
  4. There are named primaries instead of a DEV-Sharpe selection rule.
  5. H2 follower β excludes d0, and followers have no own row in [d0−1, exit+2].
  6. H7 uses earliest-possible sessions plus a 2-session margin.
  7. The L3 floor is 10 bps.
  8. Impact k is the model base (1.0) instead of a hard-coded 0.75; TCA confirmed 6 Nov 2026 that k=1.0 is base and k=0.75 is a lighter sensitivity only.
  9. The 9.5% netted per-name cap is added.
  10. The ±5-min boundary releases are excluded.
  11. (v3) Unknown-borrow ≥10%/yr required gate on all historically unknown shorts incl. H2 ETF hedges; 1%/yr demoted to labelled GC counterfactual.
  12. (v3) H2 unit ±20% neighbours (0.4%/0.6%); N = 212; PBO S = 16.
- **Earlier forking paths (v1 §7, still disclosed):**
  - H2 v0 (not-yet-reported followers, 103× turnover) and v1 (held through own release, breaches H7);
  - H1 uses $ADV instead of market cap (Q1-2016 defect);
  - the exact-timestamp trigger restriction for H2 came after runs `_2` / `_2_h7ts`.
- **Prior count source.** `statarb/PREREG.md` does not exist. The 80 comes from `statarb/results/v1/dsr.json`.


## 11b. Pre-run checklist (hard; before any return is computed)
1. Validation review has accepted this PREREG at a recorded sha256; that hash is passed as `--acceptance-hash` to `backtest_h1_h2.py`.
2. **Stage A / sealed-holdout backtest entrypoint sha256 is logged in §12 before any return is computed:** current pins for `backtest_h1_h2.py` and the costs overlay `costs_original.py` are held in the internal log. Re-hash and re-log if either file changes.
3. Data release v1.3 (final earnings) and the desk-wide 8-K 2.02 SUE factor are frozen; their hashes are logged in §12.
4. The megacap-idea DEV position-overlap check from signal inputs is completed and logged (hard pre-Stage A commitment).
5. Quarantine `QUARANTINE_stops_dev_DO_NOT_USE/` remains unread (validation waiver 2026-11-06).
6. `--stage holdout` refuses to run without a matching `--acceptance-hash`; DEV return runs likewise require it. Read-time pyarrow filters only.
7. Required cost path: `costs_original.build_cost_config("unknown_borrow_required")` with `borrow_rate >= 0.10` on every unknown short including H2 ETF hedges; GC 1%/yr is never the pass bar.
8. Impact k = 1.0 base; k = 0.75 lighter sensitivity only (TCA 6 Nov 2026).

## 12. Change log
- 2026-10-30 02:15 SGT (mtime; the text said ~02:30): v1 created.
- 2026-10-30: validation review returned it for amendment (review header says 02:52 SGT, file mtime 02:26:11 SGT, so one of the two is mislabelled).
- 2026-10-30 02:33–02:45 SGT: v2 (archived).
- **2026-11-06 SGT: v3 (this file).** Answers the validation review (RETURN FOR AMENDMENT on B1 and B2; 0.40 haircut stands; CONDITIONAL PASS ceiling; opening the quarantined stops_dev outputs expressly waived).
  - **B1:** unknown-borrow ≥10%/yr required gate on every historically unknown short (H1 names, H2 followers, H2 sector-ETF hedges; no ETF exemption); net Sharpe > 0 else FAIL on costs; 1%/yr retained only as labelled GC counterfactual.
  - **B2:** H2 unit ±20% neighbours (0.4%, 0.6%); H2 neighbours 8→10; H2 PBO configs 9→11 (H1 stays 9); N 210→212; PBO CSCV S = 16 stated.
  - Card sha256 values pinned; Stage A / sealed-holdout runner `backtest_h1_h2.py` + `costs_original.py` written and hashed (no returns computed; `--help` / `--syntax-check` only).
  - TCA written confirmation 6 Nov 2026: k = 1.0 is the model base; k = 0.75 is a lighter sensitivity only (TCA cost check, `tca/cost_model.md` §8). Cost-table drag/BE arithmetic restated for the required 10% path.
  - Megacap-idea DEV position-overlap check kept as a hard pre-Stage A commitment.
  - Awaits validation acceptance at a recorded sha256. Freezing is the validator's step. **Returns computed this sitting: none.**
