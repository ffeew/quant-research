# News-sentiment prototype: results

Returns are per daily cohort, in bp: r1 = open(d)→open(d+1); r5 = open(d)→open(d+5), an overlapping 5-day return, not per day. Net uses Tomas v1.1 at the open by liquidity bucket, one round trip per leg per cohort, plus borrow. t-stats are clustered by calendar month. FF5+Mom alpha uses daily factors for d and d+1 and Newey-West(5).
X posts are excluded: X has no history (archive-forward only).

## A. Point-in-time S&P 500 universe (PROVISIONAL)

**Provisional.** This uses Dmitri's PIT membership, which has the known issues in the validation `data_issues.json` (SNDK reuse is dropped here). Former members also have no GICS sector, so they drop out of the sector scores.

Sample: 16 months of news, 2025-06 to 2026-10. Articles with ≤3 tagged symbols: 102307. Symbols: 533. Analyst-headline share: 0.333. Spec families: 9.

| component / spec | test | N days | hit rate | mean gross | t | mean net | FF5+Mom alpha (t) |
|---|---|---|---|---|---|---|---|
| text_lm_prev_open | LS_pos_minus_neg_r1 | 330 | 52.4% | -0.7 bp | -0.16 | -26.3 bp | -0.7 bp (-0.13) |
| text_lm_prev_open | D10_minus_D1_r1 | 330 | 49.7% | -2.6 bp | -0.43 | -30.9 bp | -2.0 bp (-0.31) |
| text_lm_prev_open | LS_pos_minus_neg_r5 | 326 | 47.9% | -5.0 bp | -0.43 | -30.8 bp |  |
| text_lm_prev_open | D10_minus_D1_r5 | 326 | 50.0% | +3.4 bp | 0.26 | -25.1 bp |  |
| text_vader_prev_open | LS_pos_minus_neg_r1 | 330 | 47.0% | -5.5 bp | -1.08 | -32.0 bp | -6.8 bp (-1.46) |
| text_vader_prev_open | D10_minus_D1_r1 | 330 | 51.8% | +0.3 bp | 0.04 | -27.3 bp | +0.3 bp (0.04) |
| text_vader_prev_open | LS_pos_minus_neg_r5 | 326 | 50.0% | -7.3 bp | -0.64 | -34.1 bp |  |
| text_vader_prev_open | D10_minus_D1_r5 | 326 | 50.9% | +6.4 bp | 0.37 | -21.5 bp |  |
| text_lm_overnight | LS_pos_minus_neg_r1 | 330 | 50.9% | +8.6 bp | 1.41 | -16.7 bp | +9.3 bp (1.25) |
| text_lm_overnight | D10_minus_D1_r1 | 328 | 51.5% | +5.7 bp | 0.68 | -21.6 bp | +6.7 bp (0.75) |
| text_lm_overnight | LS_pos_minus_neg_r5 | 326 | 49.4% | +2.6 bp | 0.19 | -22.9 bp |  |
| text_lm_overnight | D10_minus_D1_r5 | 324 | 49.4% | +9.9 bp | 0.46 | -17.6 bp |  |
| text_vader_overnight | LS_pos_minus_neg_r1 | 330 | 47.3% | -3.8 bp | -0.66 | -29.9 bp | -6.2 bp (-1.09) |
| text_vader_overnight | D10_minus_D1_r1 | 328 | 50.3% | -2.2 bp | -0.22 | -28.9 bp | -2.0 bp (-0.23) |
| text_vader_overnight | LS_pos_minus_neg_r5 | 326 | 49.4% | -7.5 bp | -0.57 | -33.8 bp |  |
| text_vader_overnight | D10_minus_D1_r5 | 324 | 47.2% | -4.0 bp | -0.23 | -31.0 bp |  |
| analyst_rating_chg | LS_pos_minus_neg_r1 | 273 | 46.5% | -3.6 bp | -0.3 | -36.3 bp | -6.7 bp (-0.56) |
| analyst_rating_chg | LS_pos_minus_neg_r5 | 269 | 49.8% | -6.6 bp | -0.18 | -39.7 bp |  |
| analyst_pt_chg | LS_pos_minus_neg_r1 | 327 | 49.5% | -4.9 bp | -0.59 | -38.3 bp | -8.1 bp (-1.35) |
| analyst_pt_chg | LS_pos_minus_neg_r5 | 323 | 47.7% | -6.3 bp | -0.32 | -39.9 bp |  |
| sector_text_lm | top3_minus_bottom3_r1 | 329 | 49.2% | +3.0 bp | 0.68 | -12.3 bp |  |
| sector_text_lm | top3_minus_bottom3_r5 | 325 | 56.3% | +23.2 bp | 1.94 | +7.6 bp |  |
| sector_rating_chg | top3_minus_bottom3_r1 | 229 | 43.7% | -12.6 bp | -1.68 | -28.0 bp |  |
| sector_rating_chg | top3_minus_bottom3_r5 | 225 | 48.9% | +13.0 bp | 0.79 | -2.7 bp |  |
| sector_pt_chg | top3_minus_bottom3_r1 | 289 | 45.3% | -11.4 bp | -2.5 | -26.7 bp |  |
| sector_pt_chg | top3_minus_bottom3_r5 | 285 | 48.4% | -17.8 bp | -1.12 | -33.4 bp |  |

## B. Current constituents (SURVIVOR-BIASED comparison)



Sample: 16 months of news, 2025-06 to 2026-10. Articles with ≤3 tagged symbols: 102307. Symbols: 501. Analyst-headline share: 0.333. Spec families: 9.

| component / spec | test | N days | hit rate | mean gross | t | mean net | FF5+Mom alpha (t) |
|---|---|---|---|---|---|---|---|
| text_lm_prev_open | LS_pos_minus_neg_r1 | 330 | 52.1% | +2.3 bp | 0.46 | -22.9 bp | +2.6 bp (0.47) |
| text_lm_prev_open | D10_minus_D1_r1 | 330 | 49.7% | +2.3 bp | 0.41 | -25.5 bp | +3.6 bp (0.58) |
| text_lm_prev_open | LS_pos_minus_neg_r5 | 326 | 50.3% | +1.8 bp | 0.14 | -23.7 bp |  |
| text_lm_prev_open | D10_minus_D1_r5 | 326 | 49.7% | +8.1 bp | 0.62 | -20.0 bp |  |
| text_vader_prev_open | LS_pos_minus_neg_r1 | 330 | 48.2% | -3.6 bp | -0.68 | -29.8 bp | -4.7 bp (-1.06) |
| text_vader_prev_open | D10_minus_D1_r1 | 330 | 51.2% | +6.2 bp | 0.63 | -21.1 bp | +6.2 bp (0.73) |
| text_vader_prev_open | LS_pos_minus_neg_r5 | 326 | 54.0% | -2.6 bp | -0.23 | -29.0 bp |  |
| text_vader_prev_open | D10_minus_D1_r5 | 326 | 52.5% | +14.4 bp | 0.71 | -13.1 bp |  |
| text_lm_overnight | LS_pos_minus_neg_r1 | 330 | 54.5% | +12.4 bp | 1.68 | -12.7 bp | +13.2 bp (1.69) |
| text_lm_overnight | D10_minus_D1_r1 | 329 | 55.0% | +12.0 bp | 1.29 | -14.8 bp | +12.8 bp (1.47) |
| text_lm_overnight | LS_pos_minus_neg_r5 | 326 | 49.7% | +5.5 bp | 0.38 | -19.8 bp |  |
| text_lm_overnight | D10_minus_D1_r5 | 325 | 52.6% | +8.6 bp | 0.42 | -18.5 bp |  |
| text_vader_overnight | LS_pos_minus_neg_r1 | 330 | 50.0% | -1.3 bp | -0.22 | -27.1 bp | -4.1 bp (-0.72) |
| text_vader_overnight | D10_minus_D1_r1 | 329 | 50.8% | +0.0 bp | 0.0 | -26.5 bp | +1.0 bp (0.11) |
| text_vader_overnight | LS_pos_minus_neg_r5 | 326 | 50.6% | -1.2 bp | -0.1 | -27.3 bp |  |
| text_vader_overnight | D10_minus_D1_r5 | 325 | 47.7% | -3.0 bp | -0.18 | -29.8 bp |  |
| analyst_rating_chg | LS_pos_minus_neg_r1 | 270 | 46.7% | +9.0 bp | 0.77 | -23.1 bp | +6.6 bp (0.49) |
| analyst_rating_chg | LS_pos_minus_neg_r5 | 266 | 49.6% | -0.0 bp | -0.0 | -32.4 bp |  |
| analyst_pt_chg | LS_pos_minus_neg_r1 | 327 | 48.6% | -1.4 bp | -0.16 | -34.1 bp | -4.7 bp (-0.7) |
| analyst_pt_chg | LS_pos_minus_neg_r5 | 323 | 49.5% | +0.8 bp | 0.04 | -32.2 bp |  |
| sector_text_lm | top3_minus_bottom3_r1 | 329 | 49.8% | +1.2 bp | 0.29 | -14.2 bp |  |
| sector_text_lm | top3_minus_bottom3_r5 | 325 | 56.6% | +23.3 bp | 1.84 | +7.6 bp |  |
| sector_rating_chg | top3_minus_bottom3_r1 | 230 | 43.5% | -9.4 bp | -1.24 | -24.7 bp |  |
| sector_rating_chg | top3_minus_bottom3_r5 | 226 | 50.0% | +21.3 bp | 1.3 | +5.6 bp |  |
| sector_pt_chg | top3_minus_bottom3_r1 | 290 | 46.9% | -11.5 bp | -2.43 | -26.9 bp |  |
| sector_pt_chg | top3_minus_bottom3_r5 | 286 | 48.3% | -17.1 bp | -1.15 | -32.8 bp |  |

Statistics reported per universe: 4 text specs × (2 tests × 2 horizons + 2 alphas) + 2 analyst × (2 horizons + 1 alpha) + 3 sector × 2 horizons = 36. Across both universes that is 72. One or two |t| near 2 are expected by chance.
