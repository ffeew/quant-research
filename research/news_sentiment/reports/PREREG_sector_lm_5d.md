# Pre-registration: sector-level news tone, 5-day hold (SPDR sector ETFs). LM research primary + VADER tradeable twin

**Status: DRAFT, NOT FROZEN.** Revised 2026-10-30 ~02:20 SGT (UTC+8) for Victor's final batch ruling (`validation/prereg_rulings/2026-10-30-ethan-batch-review.md`), the CIO LM licence ruling and Tomas's execution/cost inputs. Prior text: `audit/prior_versions/PREREG_sector_lm_5d.2026-10-30T0206.md`.
- Freeze requires all of: (i) fetch complete, `PREREG_manifest.txt` regenerated with `make_manifest.py --final` and its DATA_HASH pasted into §3; (ii) the §5 SUE/event tables exist and their hashes are pasted into §3; (iii) `prereg_run.py` completed for §5 wiring and its hash pasted into §3; (iv) the §3 coverage floor table is complete from 2016; (v) Victor signs off.
- At freeze, `make_manifest.py --final --freeze` writes `PREREG_sector_lm_5d.sha256` = sha256(this file). The run is unlocked with `NEWS_OOS_UNLOCK=<that hash>`. Any edit after freeze changes the hash and re-locks.
- **Freeze-file note:** `PREREG_sector_lm_5d.sha256` is deliberately NOT created now. It is the unlock key, so creating it would be a freeze. `make_manifest.py --freeze` creates it at sign-off.
- Author: Ethan (Equity Analyst). Standard: `validation/STANDARD.md` v1.0 plus Addendum A.
- Origin: one cell from the seen-sample exploration (`RESULTS.md`): `sector_text_lm top3_minus_bottom3_r5`, +23 bp gross / +7.6 bp net per 5-day cohort, month-clustered t 1.94 (PIT), 2025-06 to 2026-10. It was the only one of 36 statistics per universe that was positive after costs, which is consistent with chance.
- **Verdict ceiling: CONDITIONAL PASS** (Victor ruling 3, S7). The best possible outcome is half size **plus** forward paper probation of at least 60 trades **or** 3 months, on archive data collected *after* registration (`equity/sentiment/` daily archive, `ARCHIVE_SPEC.md`).

## 0. Scorer and licence (CIO ruling, 2026-10-30 02:07; Victor final X8; parent resolution 02:12)
| role | scorer | version / hash | licence | gating? |
|---|---|---|---|---|
| **Research primary** (the hypothesis being replicated) | Loughran-McDonald word lists (via `pysentiment2` 0.1.1) | `lexicon/lm_positive.txt` 354 words, sha256 `6fb159d5a3b69e553edbc237c8d14551eafa5f71bb819a3807153489b7f6ab75`; `lexicon/lm_negative.txt` 2,355 words, sha256 `58fb732dd47af8b95a62abaa417039681b1c4d61035fa2b06022dc08c559d564` | "free for use in academic research. For commercial licenses, please contact" the authors. https://sraf.nd.edu/loughranmcdonald-master-dictionary/. **CIO: our use is not academic → LM is not licensed for anything tradeable.** | Gates the **research verdict** only |
| **Tradeable twin** (pre-registered now) | VADER, `vaderSentiment` 3.3.2, compound score, with the finance-domain neutralisation list (below) | `vader_lexicon.txt` sha256 `1ec9c6e9ee19aade328f8beb393a6afa71a5bb3acf7d3cc22d4ef568df374bf5` (7,519 lines); `vaderSentiment.py` sha256 `25cd814d23000b41c0e242d99960832c6620b3f1b844469173404500ce63206b` | **MIT.** https://github.com/cjhutto/vaderSentiment/blob/master/LICENSE.txt | **Go-live requires the twin to pass G1–G10 as well** |

- **Conflict resolution (Victor accepted the twin ~02:24 SGT, with the two conditions below).** Victor X8 keeps LM primary; the CIO ruled LM cannot underpin anything tradeable. Resolution: LM stays primary for the **research verdict**; VADER is pre-registered as the **tradeable twin** with identical rules (§4, only step 2 changes); **any go-live requires the twin to pass too**. If LM passes and the twin fails, the record reads "research PASS/CONDITIONAL, not tradeable".
- **Why VADER (chosen on licence and look-ahead, not on results):**
  - MIT licence, clearly commercial.
  - The lexicon was built and published in 2014 (Hutto & Gilbert, ICWSM 2014), before the 2016 hold-out. It is rule-based and was never fitted to returns.
  - FinBERT (ProsusAI/finbert): rejected. Weights CC BY-NC-SA 4.0 (non-commercial); Financial PhraseBank CC BY-NC-SA 3.0; TRC2 under NIST terms. Its training data and release (BERT base ~2018, FinBERT 2019) sit **inside** the hold-out, an Addendum A problem.
  - Harvard General Inquirer: rejected; commercial use needs permission (inquirer@wjh.harvard.edu, https://inquirer.sites.fas.harvard.edu/spreadsheet_guide.htm).
  - A self-built list: possible, but building one now would mean designing on seen text; not needed.
  - **Disclosure:** VADER was computed as a seen-sample diagnostic (2025-06 to 2026-10) and was near zero. That was **not** used in the choice. **No hold-out text was scored to choose the scorer.**
- **Victor accepted the twin (2026-10-30 ~02:24 SGT)** on two conditions, both applied: it counts as a trial (§1), and finance-domain handling is pre-registered (below).
- **Disclosure: VADER is a general-purpose lexicon built for social-media text, not for finance.** Words that are neutral or industry labels in financial text can carry negative scores in it.
- **Finance-domain handling (one approach, chosen now, with no hold-out text read or scored):** neutralise (remove from VADER's lexicon) exactly the words Loughran & McDonald (2011, *Journal of Finance* 66(1):35-65, doi:10.1111/j.1540-6261.2010.01625.x, Introduction) name as misclassified by a general-purpose lexicon in financial text: *tax, cost, capital, board, liability, foreign, vice* ("often do no more than name a board of directors or a company's vice-presidents") and *mine, cancer, crude (oil), tire* ("more likely to identify a specific industry segment than reveal a negative financial event"), plus their regular plural forms.
  - Pinned list: `lexicon/vader_finance_neutral_v1.txt`, sha256 `4e1ff542f8f3b4f38c10839679637c6597c7fb9d61f66a8689f6952c945d7632` (20 entries). Applied by `vader_fin.py` (sha256 `0b8506ea47193fac39b93b3022bdb7d7dfff827d99a19ded0b219360e279a6ca`), which refuses to run on a hash mismatch.
  - Effect on VADER 3.3.2 (checked against the lexicon file only): 4 entries are present and removed: *liability* (−0.8), *liabilities* (−0.8), *cancer* (−3.4), *crude* (−2.7). The other words are not in VADER's lexicon.
  - **Why this approach:** the list comes from a published, cited source written for exactly this problem, is fixed in advance, and needs no data to build. It does not derive words from the LM dictionary file itself, which would carry LM's licence restriction into the tradeable scorer. A data-driven list (e.g. from word frequencies in our archive) was rejected because building it would mean reading archive text.
  - **Known residual, declared now:** *risk/risks* (VADER −1.1) is **not** neutralised. Victor named it as an example, but LM (2011) does not list it among the misclassified words; neutralising it would be a choice without a cited source. It stays as shipped, and this is a disclosed limitation. **Ruled by Victor 2026-10-30:** leave risk/risks out of v1 and keep exactly the pinned LM 2011 list; any risk-neutralised variant would count as +1 trial.
- **Case-folding:** LM entries are UPPERCASE; tokens are `[A-Za-z]+` upper-cased before matching. VADER uses its own case handling (its ALL-CAPS emphasis rule applies as shipped).
- **LM vintage (Victor ruling 2 / X8).** Reconstructed from the current SRAF master dictionary (`lexicon/lm_vintage_research/Loughran-McDonald_MasterDictionary_1993-2025.csv`, sha256 `e2d13286…4859d`), whose Positive/Negative columns record the year a word was added (negative year = removed):
  - Positive: 345 words flagged 2009, 1 flagged 2011, 1 flagged 2012, plus 7 removed in 2020 = 354, **all added by 2012**.
  - Negative: 2,305 (2009), 13 (2011), 1 (2012), 26 (2014), plus 10 removed in 2020 = 2,355.
  - **The pinned lists equal the 2014 vintage word for word**; no word added after 2014. The counts also match quanteda's documented "2014 version" (354 / 2,355).
  - SRAF lists only the 1993-2025 file today; older dated releases are not listed. This is a reconstruction from flags, not a diff against a dated release, so Victor may still treat the vintage as unverified. **G9 (2019+ gate) is therefore kept** as a conservative gate whatever he rules.

## 1. Trial count (Victor X3)
- Family: news/sentiment. Insider is a separate family and is parked.
- **N carried in = 95** = 72 (seen-sample prototype statistics, 36 × 2 universes) + 1 (this primary) + 22 (card variants: revision-breadth 8, spillover 7, hype-fade 7).
- **+ 7 secondary series (§9)**, each a trial. The VADER twin is one of them (it was §9.4 before the swap), and Victor additionally counts each VADER twin as its own trial (+4, §1 below). LM stays the primary; no extra benchmark row is needed here.
- **+ 24 neighbourhood runs (G6)**, listed exactly:
  - One at a time (8): hold 4, hold 6; top/bottom k 2, k 4; min stocks per sector 2, 4; min eligible sectors 5, 7.
  - Jointly (16): every corner of {hold 4, 6} × {k 2, 4} × {min stocks 2, 4} × {min sectors 5, 7}.
- **+ 23 card neighbourhood runs** (Victor X3/X5; listed in each card): revision-breadth 7 (incl. R151, Victor ruling 4), spillover 8, hype-fade 8.
- **+ 4 VADER-twin trials** (Victor ruling 1, 2026-10-30 ~02:24 SGT: each of the 4 twins counts as a trial; added on top even though this document's twin is also one of the 7 secondaries, a conservative double count kept as ruled).
- **Family DSR N = 95 + 7 + 24 + 23 + 4 = 153** for sector-LM, revision-breadth and spillover. **Hype-fade uses N = 153 + 192 PEAD = 345** (Victor ruling 2). Also reported here at N = 73 and 95 for reference. N never goes down after a result.
- Cost stresses (2×, half-spread 1.0×, 10%/yr unknown borrow) re-price the same series and are not trials; the 10%/yr run is a required gate (G11). The 2× stress is a condition inside G2 on the same series, so it adds no trial either. **Tomas's cost inputs (02:30 SGT) change N by 0.**
- **PEAD (ruled):** the 192 PEAD trials stay out of this family's N; they enter only hype-fade's DSR.

## 2. Samples (strictly separate)
| sample | formation dates | status |
|---|---|---|
| **OOS hold-out (gating)** | first session of the first month meeting the §3 coverage floor (target 2016-01-05) to 2025-05-22 | never examined; locked in code |
| **2021-01 to 2025-05 sub-report** | 2021-01-04 to 2025-05-22 | reported separately (Victor ruling 1); part of the gating window |
| Embargo | 2025-05-23 to 2025-05-31 | dropped |
| Seen sample | 2025-06-02 to 2026-10 | already examined; reported separately, **non-gating** |

- OOS ≈ 9.4 y if 2016 meets the floor (about 470 non-overlapping 5-day periods); history from 2016-01 ≈ 10.8 y (STANDARD §2: ≥ 10 y).
- **If 2016 fails the floor**, the OOS starts at the first month that meets it, and the OOS and history lengths are restated before the run. The §2 10-year history requirement is then at risk and is reported as failed if not met.
- Possible Benzinga gap Feb 2015 to Oct 2016 (Alpaca forum report, not verified): see §3 coverage.
- The regression (§6) starts at the first session with 252 prior ETF bars, ≈ 2017-01-04.

## 3. Data (Addendum A)
- **News:** Alpaca `v1beta1/news` (Benzinga), fetched by `fetch_news.py` into `raw/` and `raw_alias/` through the desk throttled client (`$QR_DATA_DIR/lib/desk_data_client.py`, desk rule 5).
  - **Manifest scope = ALL fetched months** (Victor X6 iv): Alpaca's start/end filter follows `updated_at`, so an article created in 2016 and edited in 2023 sits in a 2023 file.
  - **DATA_HASH: `<from make_manifest.py --final at freeze>`**. A PROVISIONAL manifest exists now; its hash changes as each fetched month lands and is not a registration value.
- **Timestamp = first public availability, ET:** Alpaca `created_at` converted to America/New_York. `DATA_AUDIT.md` matched it to Benzinga `datePublished` on 4 of 4 pages plus an id-neighbour test over 193k articles. **Pre-unseal step:** raise the page check to ≥ 30 pages stratified by year (≥ 10 from 2016-2020) after the unseal, or with metadata only (Victor S2).
- **Edited articles (Victor X6).** The API serves only the latest revision. Primary rule: **drop an article if `updated_at` ≥ 09:25 ET of the session it would trade.**
  - **Measured drop share under this rule** (`audit/edited_share.py`, metadata only, ≤3-symbol member articles): 2024 (Jun–Dec fetched) **0.68%**, 2025 **0.32%**, 2026 **0.15%**. Pre-2024 values are not yet measurable (fetch incomplete; rows from 2016-2023 currently come only from later-edited files and read 100% by construction).
  - **The earlier "about 2.4%" was the share with updated_at > 1 minute after created_at, not the drop share.** The measured drop share is much lower in 2024-26.
  - **Ceiling:** any OOS year (or sector-year with ≥ 100 articles) above 5% is reported flagged.
  - **Dropping is a selection on future information** (whether a story was later edited, a proxy for newsworthiness or a developing story). Keeping is text look-ahead. Neither is clean; direction of bias is unknown.
  - **Bound (gating, G10):** the no-filter run (§9.7) is computed. If V1 and no-filter disagree on the G1 or G4 outcome, the verdict is capped at CONDITIONAL and a stability flag is recorded.
- **Coverage (Victor X7).** Before *any* freeze, coverage by year × sector and former vs current members, from 2016, is attached (`audit/edited_share.py` → `audit/coverage_floor_by_month.csv`; `audit/coverage.py`).
  - **Floor:** the first OOS month is the first month where ≥ 90% of PIT members have ≥ 1 member-tagged article. 2025-26 measured: monthly minimum 91.9-93.5%, mean 96.5-97.0%. **2016-2024-05: pending fetch.** The possible 2015-16 gap is tested by this floor.
- **Scorers:** §0 (LM research primary; VADER tradeable twin). No vendor sentiment scores. **No LLM.**
- **Universe:** S&P 500 members at session d (`universe/sp500_membership.parquet`), aliases via `aliases.csv`, old SanDisk excluded.
  - Sectors: today's GICS (`universe/universe.parquet`). **If Dmitri's PIT GICS exists at freeze it is the primary (Victor X9)**; otherwise current GICS is primary with the 20% OOS Sharpe haircut and a CONDITIONAL cap, and the PIT-GICS run (if any later) is a counted diagnostic.
- **Prices:** `bars/daily/adjusted/` (SIP, adjustment=all) for the 11 SPDRs and SPY.
- **Earnings control inputs (§5)**, referenced by path; hashes pasted at freeze:
  - 8-K Item 2.02 event table: `$QR_DESK_DIR/equity/earnings_events/` (in build). sha256 `<at freeze>`.
  - Desk SUE: `$QR_DATA_DIR/derived/sue_xbrl.parquet` (Dave; each value stamped at its 10-Q/10-K acceptance time; first-reported values). sha256 `<at freeze>`.
- **Code (hashes at freeze; current values for reference):**
  - `news_signal.py` (OOS lock + sequencing guard) sha256 `b77a6c8118973a509b072ddeff7ff54fa6c02074b14a8ae612c86cde105ff099`.
  - `prereg_run.py` sha256 `<at freeze>`; current draft `60fa1a33…033b6a` (2026-11-06 ~22:30 SGT: §5 control adapters wired and input-ready, see `CONTROLS_WIRING.md`; v1 event table pinned by explicit path for ANNSHARE; SUE adapter against a proposed contract pending Dave; synthetic tests only; not executed; prior draft `1f5749ab…685c49`: adds COST_MULT_STRESS = 2× primary and HTB_GATE_APPLIES = True (G11); pins the VADER override list and `vader_fin.py`, N_FAMILY = 153 / N_HYPEFADE = 345, and Tomas's cost inputs: `ethan_cost_inputs.md` + 11 files in `tca/ethan_inputs/`; whole-share rounding, continuous-cost stop exits, borrow 1%/yr on calendar/360) (draft exists; §5 control wiring and the gate computations complete when the input tables exist; not executed).
  - `$QR_DESK_DIR/equity/holdout_guard.py` sha256 `<at freeze>`; current `9c1c69d2…cfa5cd1e4`.
  - `make_manifest.py` sha256 `<at freeze>`; current `ea9504a8…079e1ae`.

## 4. Primary rule (zero discretion)
1. **Articles.** Benzinga articles tagging **≤ 3** symbols. Exclude analyst-action headlines `\b(Upgrades|Downgrades|Initiates Coverage|Reinstates|Maintains|Reiterates|Price Target)\b`. Text = html-unescaped `headline + ". " + summary`.
2. **Article tone.**
   - LM (research primary): tokenise `[A-Za-z]+`, upper-case, P/N = positive/negative hits; tone = (P−N)/(P+N), 0 if no hits.
   - VADER (tradeable twin): `vader_fin.analyzer().polarity_scores(text)["compound"]` (VADER 3.3.2 minus the pinned neutralisation list, §0).
3. **Session assignment.** Article counts toward session d if `created_at` ∈ [09:30 ET of d−1, 09:25 ET of d) and `updated_at` < 09:25 ET of d.
4. **Stock score** S_{i,d} = mean tone of member i's assigned articles.
5. **Sector score** L_{k,d} = mean S_{i,d} over members with a score. Eligible if ≥ 3 stocks scored and the ETF has an open at d and d+5. XLC/XLRE ineligible before their first bars.
6. **Trade.** Cohort formed only if ≥ 6 sectors are eligible. At the open of d: long the 3 highest-L ETFs, short the 3 lowest, equal weight, dollar-neutral; ties by ticker. Exit at the open of d+5.
7. **Portfolio and sizing (LIMITS v0.3.5, Victor S4).** Five overlapping sleeves.
   - Per-sleeve gross **11.4% of equity** (1.9% per ETF leg), so total gross ≤ **57%** (H3 buffer 58%) and any one ETF across all sleeves ≤ 5 × 1.9% = **9.5%** (H1 buffer).
   - **Stops (H6):** every leg carries a 2×ATR(14) protective stop from its entry open (ATR known before the open of d). If touched intraday the leg exits at the stop level; a gap through the stop at a later open exits at that open.
   - H7 (earnings) is not applicable to sector ETFs.
   - **Intended notional:** at today's equity (~$100,000) that is ≈ $57,000 gross, ≈ $1,900 per leg per sleeve, ≤ $9,500 per ETF aggregate.
   - Strategy return is the daily P&L on equity (so Sharpe is size-invariant; dollar figures use the notional above).
8. **Orders (Tomas, 2026-10-30).** Market-on-open (`time_in_force=opg`) submitted at **09:25 ET**. Alpaca rejects opg orders 09:28-19:00 ET, so **no retries after 09:27 ET**; a leg not accepted by then is not traded that day (logged). *Caveat:* whether Alpaca paper fills at the real auction price is **unverified**; Tomas's SPY auction pilot runs 2-9 Nov 2026. The backtest fills at the official open.
9. **Costs (net is primary).** Tomas cost model **v1.1** pinned: `$QR_DESK_DIR/tca/cost_model.md` sha256 `684daa3946a75a2193071616e7710d8ccb691fcdef3a7877d45456af22f4378c`; `src/quant_research/backtest/costs/cost_model.py` sha256 `df67d604489583d36bb1a16dc7ed30c5568b9a17526f450e4c1a335f9fe8eebf`.
   - **Tomas cost inputs wired (2026-10-30 ~02:35 SGT):** `$QR_DESK_DIR/tca/ethan_cost_inputs.md` sha256 `67d0ab41e8ba268fbcfcd159b7af288a7d40f76e86e7811610cfddd50f409432`; `tca/ethan_inputs/per_side_costs.csv` sha256 `82e3ffda3904e84f28220d9f8c81ecb10d4d9ac8a3ca4fbd69d9fda41a48712a`; `card_costs.json` sha256 `beed6c07eee1210d2d7ec4ab2d4b2a1f8763aeaae78b754335e1b824207e7096`; `asset_flags_paper.json` sha256 `99b4feaeae3e3bb6b9044428014557b3ad938e7f357332a164ffbbb4910e2a7d` (all 11 files in `tca/ethan_inputs/` are hash-pinned in `equity/news_sentiment/prereg_run.py` `TOMAS_FILE_SHA`).
   - Per side, per leg: max(Tomas `trade_cost(..., venue='open')`, STANDARD §5 liquid-ETF floor 2 bp + **full** normal half-spread, Tomas's measured per-ETF "Base" from `per_side_costs.csv`). Tomas Base: SPY 2.3; SPDRs 2.5-5.1 bps (average **3.6**; XLY 4.7, XLB 5.0, XLRE 5.1, XLC 4.8 higher via the L2 paper buffer). Each sleeve pays one full round trip on every leg per cohort; **exits are at the open** like entries (a venue change would be a new variant, +1 N).
   - **MOO costs stay at the floor** (max(model, floor)) until the SPY pilot reports; the pilot does not cover sector ETFs, so their auction cost stays unmeasured.
   - **Stop exits (H6)** are costed at the continuous-session cost (Tomas's marketable-limit Base per ETF, or the model at `venue='continuous'` if higher) plus the gap already in the stop fill price.
   - **Whole shares only** (no fractional on `opg`): each leg rounds down to whole shares at the entry open (≈ $1,900 per leg per sleeve; SPDR prices are well below that today, so the effect is small but modelled).
   - Cost expectations (Tomas §2, NOT results): sector-ETF round trip **7.1 bps**; break-even 7.1 bps long / 9.1 bps short per position; drag about 1.0-1.7% of equity a year at the breadth card's turnover. This document's turnover (5 overlapping weekly sleeves, full replacement possible each cohort) differs, so its drag is not taken from that figure.
   - Tomas's sample is small (10 sessions, 25 names); the daily-bar open is a proxy for the official opening print.
   - The open half-spread multiplier 0.5× is Tomas's **assumption**; **stress at 1.0×**.
   - **Borrow (Tomas §3, Victor look-ahead ruling):** primary **1%/yr** on every short leg (STANDARD GC floor), **2× stress 2%/yr**, calendar days / 360. 25 bp/yr is a reference only. SPY and all 11 SPDRs are shortable and ETB on 2026-10-30 (`asset_flags_paper.json`), but that is **not assumed historically**; ETB status before 2026-10-30 is unknown, so the **10%/yr unknown-borrow run is a REQUIRED gate (G11)**: net Sharpe > 0, otherwise FAIL on costs (Victor 2026-11-06 06:09 SGT). Live/paper: check `easy_to_borrow` each morning before the 09:25 ET opg and skip a short leg that is not ETB.
   - **2× stress** doubles the **primary** cost (this document has no uplift, so primary = Base) and borrow (Victor ruling 2, 2026-11-06).

## 5. Controls (incremental value, Addendum A), built before any OOS look
All are dollar-neutral sector-ETF portfolios with the §4 machinery (same eligible sectors, top-3 minus bottom-3, 5 sleeves, gross). Only the ranking variable changes.
- **REV5:** ETF open(d−5)→open(d) return; long the 3 lowest.
- **MOM12-1:** ETF open(d−252)→open(d−21) return; long the 3 highest.
- **SUE (earnings surprise, desk control; replaces the former EAR proxy, Victor S10 / parent ruling).**
  - Input: `data/derived/sue_xbrl.parquet` (Dave), first-reported values, each usable only after its 10-Q/10-K **acceptance** time (ET).
  - SUE_{k,d} = mean over sector-k PIT members of the most recent SUE whose acceptance is before 09:25 ET of d and within the last 63 sessions; sectors with none get 0. Long top 3, short bottom 3.
  - Reported: the share of 8-K 2.02 events in the window whose own-quarter SUE was not yet public at d (10-Q lags the 8-K).
- **ANNSHARE:** from the 8-K Item 2.02 event table (`equity/earnings_events/`, acceptance time τ in ET; first tradable session s(τ) = first session whose 09:25 cutoff is after τ). ANNSHARE_{k,d} = share of sector-k members with s(τ) ∈ [d−5, d]; enters as the long-minus-short leg difference.
- **FF5 + UMD** (`factors/ken_french/`) at d and d+1 (returns run open to open).
- The EAR control is dropped; it is not run (no trial).

## 6. Primary statistics (stated up front)
- (a) Annualised Sharpe of the **net** daily strategy return over the OOS window.
- (b) Incremental alpha: OLS of the net daily return on REV5, MOM12-1, SUE (gross), ΔANNSHARE, FF5+UMD at d and d+1, plus α. NW t with 5 lags.
- **Which sample the t-test gates on:** G4 is gated on the **OOS window only**. The full-history t (OOS + seen) is also reported, non-gating.

## 7. Pass gates (all must hold; STANDARD §3–§8)
| # | bar | threshold |
|---|---|---|
| G1 | OOS net Sharpe (after 20% haircut if PIT GICS missing) | > 0.5 |
| G2 | Net Sharpe at 2× costs > 0; break-even cost ≥ 2× assumed | both |
| G3 | DSR at **N = 153** (§1) | ≥ 0.95. SR₀ from σ(trial SR) of the logged seen-sample matrix (T × 72), floor 0.5. Report SR₀, N, T, skew, kurtosis; also at N = 73 and 95 |
| G4 | t(α), §6(b), NW, **OOS window** | α > 0 and t ≥ 3.0 |
| G5 | Sample | OOS ≥ 3 y and ≥ 30 **non-overlapping** 5-day periods with a formed cohort, counted from signal inputs before the unseal |
| G6 | Stability | No calendar year > 40% of PnL; no regime Sharpe < −0.5 (SPY vs 200-dma; VIX above/below median and > 25); each of the 24 §1 neighbourhood runs keeps OOS Sharpe > 0 and ≥ 50% of primary. ≤ 2 flags → CONDITIONAL; > 2 → FAIL |
| G7 | Capacity | ≤ 1% of 20-day ETF ADV at the §4.7 notional |
| G8 | **PBO** (CSCV, S = 16) over primary + twin + 24 neighbourhood runs + §9.2, §9.3, §9.7 (29 series) | ≤ 0.05 for PASS; 0.05-0.20 caps at CONDITIONAL; > 0.20 FAIL |
| G9 | 2019+ sub-window (LM vintage, Victor ruling 2 / X8; **kept by ruling 3**) | net Sharpe > 0 on 2019-01-02 to 2025-05-22 alone |
| G10 | Edited-article bound (X6 ii) | V1 and no-filter (§9.7) agree on G1 and G4; disagreement → CONDITIONAL + stability flag |
| — | Cost stresses (reported; flag if negative; **not trials**) | half-spread 1.0×: net Sharpe > 0 else stability flag |
| G11 | **Unknown-borrow gate** (Victor 2026-11-06 06:09 SGT; STANDARD §5) | net Sharpe > 0 with **10%/yr borrow on every ETF short leg**, else **FAIL on costs**. Not a trial |
| — | 2021-01-04 to 2025-05-22 sub-report | reported separately (non-gating here; a gate in the revision-breadth card) |

- The §6 haircut for sizing: OOS SR × 0.74 (no clean in-sample SR).
- **Coverage floor before OOS (Victor ~02:24 SGT):** no pre-2024 year counts as OOS until the ≥ 90% floor (§3) is shown for it from the completed fetch; unshown years are excluded and lengths restated.
- **Auction-pilot cap:** the verdict is capped at CONDITIONAL until Tomas's opening-auction pilot data (SPY, 2-9 Nov 2026) is in.
- **G9 (2019+ gate) stays** (Victor ruling 3).
- **Verdict ceiling CONDITIONAL PASS** (half size + ≥ 60 trades or 3 months forward paper probation on post-registration archive data). **Go-live also requires the VADER twin to pass G1–G10.**
- Binary on the gates. No re-specification after the look; any change is a new trial and a new pre-registration.

## 8. Reporting (whatever the outcome)
- Equity curve, trade list (incl. stop exits), legs separately, Sharpe by year, regime table, correlation to the book, LM and twin side by side.
- Coverage by year × sector and former vs current members; drop share by year × sector; 2021-01..2025-05 split; full-history t.
- Every number regenerates with one command: `NEWS_OOS_UNLOCK=<sha> python prereg_run.py`. On completion it writes `PREREG_sector_lm_5d.RUNLOG.json`, which (with the frozen hash) is what unseals the three cards' pre-2025-06 archive access in `holdout_guard.py`.

## 9. Secondary series (NON-GATING except where a gate references them; each a counted trial)
1. Seen sample 2025-06 to 2026-10, same rule.
2. 1-day hold.
3. Overnight-only window [16:00 ET d−1, 09:25 ET d).
4. **VADER tradeable twin** (§0): non-gating for the research verdict, **required for go-live**.
5. Gross Sharpe.
6. Fama-MacBeth of 11-sector 5-day ETF returns on standardised L, REV5, MOM, SUE, ANNSHARE.
7. No `updated_at` filter (feeds G10).

## 10. Sequencing (Victor interim ruling 4, final X1), enforced in code
- No exploration of pre-2025-06 archive tone, text or returns (including 2016-2020) by any design or card script until this pre-registration is **frozen and its single gating run is logged**, or all four specs are frozen together (joint unseal, `JOINT_UNSEAL.json` listing all four hashes).
- Enforced by `$QR_DESK_DIR/equity/holdout_guard.py` (refuses sealed months), by the OOS lock in `news_signal.py` (which also stays on the seen sample until the gating run is logged), and by `prereg_run.py` refusing to run twice for the same hash. Metadata-only audits (counts and timestamps; no text, tone or returns) are allowed.

## 11. Known limitations (declared now)
- Current GICS applied back in time (2018 Communication Services reclassification; GOOGL/META mapped to XLC throughout, so out before 2018-06-19), unless PIT GICS arrives (§3).
- Former members drop out of sector scores (no GICS).
- Benzinga feed survivorship and possible 2015-16 gap (§3 floor).
- Edited-article selection (§3, G10).
- Opening-auction fill fidelity in paper is unverified until Tomas's pilot (2-9 Nov).
- Ticker reuse (FB → ProShares ETF on Benzinga; S/X/M), handled by PIT membership and aliases; audited in `DATA_AUDIT.md`.

## Ruling log
**A11. Ruling log 2026-11-06 (Victor's 6 Nov 2026 rulings, relayed ~06:04 SGT; applied ~06:10 SGT).**
1. Tomas's post-earnings open uplift is the **primary** entry-cost assumption for spillover and hype-fade (conservative base, in the gates), **not a trial**; the normal-base series is a **diagnostic**.
2. The **2× cost run = 2× the chosen primary cost** (including the uplift where primary has it), not 2× the normal base. Break-even and 2× figures are stated on that basis.
3. Cost multipliers and sensitivity columns on an unchanged signal configuration add **no trials**: **N stays 153 (345 for hype-fade)**. This supersedes any earlier blanket statement that every stress run counts; a changed venue, signal, universe or configuration still counts.
4. The full-half-spread floor correction and the removal of today's ETB flags from history are **model corrections, not trials**.
5. STANDARD §5 needs a quoted borrow rate or ≥ 10%/yr when unknown, so for **historically unknown single-name shorts the 10%/yr HTB run is a REQUIRED robustness gate: net Sharpe > 0, otherwise FAIL on costs.** 1%/yr GC base and 2%/yr sensitivity stay alongside. Live exclusion of non-ETB names does not repair unknown historical borrowability.
- **CONDITIONAL cap kept** until opening-auction fills are evidenced. Tomas's SPY-only pilot does not establish single-name auction costs.
- The uplift-as-primary question is **closed** (no longer awaiting Victor).
- **Applied here (sector-LM):** no uplift, so 2× primary = 2× Base (code: `COST_MULT_STRESS = 2.0` on the primary cost). **HTB gate: superseded by the 06:09 SGT ruling below (now applies, G11).** N unchanged at 153.

**Ruling log 2026-11-06 06:09 SGT (Victor, relayed ~06:13 SGT): unknown-borrow gate extended to ETF shorts.**
- The required **10%/yr unknown-borrow gate applies to this configuration too** (SPDR ETF shorts): the primary configuration re-priced with 10%/yr borrow on every short leg must have **OOS net Sharpe > 0, otherwise FAIL on costs**. It is no longer report-only or a stability flag.
- Today's ETB status (SPY and all 11 SPDRs ETB on 2026-10-30) and general ETF liquidity are **not historical evidence** of borrowability.
- The 1%/yr GC base and 2%/yr sensitivity remain alongside as diagnostics; no other cost change (the primary net-Sharpe gate G1/gate 1 is still computed at the existing primary costs, as before).
- If Tomas later supplies historical quoted borrow rates, they must be pinned and pre-registered **before any results are seen**; none are requested now.
- Supersedes the earlier "does not apply (no single-name shorts)" text. **N unchanged: 153 (345 hype-fade)**; a cost gate on an unchanged configuration is not a trial (ruling 3).
