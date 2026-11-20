# Insider prototype: results (run 30 Oct 2026, SGT)

Filings 2016-01 to 2026-09. Portfolios are equal-weighted and gross of costs. A round trip is about 8–15 bp a month under TCA owner v1.1 for L1/L2 names, which is immaterial next to these means. Research only.
xr = excess vs SPY. xe = excess vs the equal-weighted PIT S&P 500. Suffix 1 or 3 = months held.

## A. Point-in-time S&P 500 universe (PROVISIONAL)

**Provisional.** This depends on former members and delisting returns, which have known issues in the data owner's store (validation `data_issues.json`): 59 members have days without bars; terminal returns were matched for only 47 of 120 delisted names, and the rest use the last close; SNDK ticker reuse is dropped (old SanDisk interval removed; new Sandisk is mapped by CIK).

Trade rows: {"('P', 'opportunistic')": 1310, "('P', 'routine')": 2445, "('P', 'unclassified')": 11738, "('S', 'opportunistic')": 41885, "('S', 'routine')": 75849, "('S', 'unclassified')": 109789}. Symbols: 689. Mapping: {'dmitri_ticker_cik_map': 238616, 'issuer_ticker_fallback': 4400}. Statistics reported: 38.

| series | N stock-months | N months | hit rate | mean (event) | t (month-clustered) | mean (EW monthly portfolio) | portfolio hit rate | t (portfolio; NW(2) for 3M) |
|---|---|---|---|---|---|---|---|---|
| opp_buy_xr1 | 363 | 115 | 44.9% | -0.62% | -1.09 | -0.95% | 41.7% | -1.86 |
| opp_buy_xr3 | 361 | 114 | 42.7% | -1.77% | -2.16 | -1.86% | 40.4% | -1.87 |
| routine_buy_xr1 | 300 | 128 | 46.3% | -0.49% | -0.84 | -0.48% | 43.8% | -0.92 |
| routine_buy_xr3 | 294 | 126 | 44.6% | -2.15% | -2.08 | -1.71% | 42.1% | -1.67 |
| all_buy_xr1 | 3812 | 128 | 49.2% | +0.04% | 0.13 | -0.16% | 50.0% | -0.68 |
| all_buy_xr3 | 3769 | 126 | 48.2% | -0.37% | -0.75 | -0.52% | 47.6% | -0.91 |
| opp_sell_xr1 | 9988 | 128 | 48.0% | -0.30% | -2.43 | -0.20% | 42.2% | -1.62 |
| opp_sell_xr3 | 9858 | 126 | 46.6% | -0.74% | -3.02 | -0.68% | 41.3% | -2.16 |
| routine_sell_xr1 | 8428 | 128 | 49.5% | +0.07% | 0.56 | +0.06% | 57.8% | 0.49 |
| routine_sell_xr3 | 8297 | 126 | 49.2% | -0.00% | -0.0 | +0.00% | 49.2% | 0.01 |
| opp_buy_xe1 | 363 | 115 | 44.9% | -0.52% | -1.13 | -0.79% | 36.5% | -1.69 |
| opp_buy_xe3 | 361 | 114 | 43.2% | -1.12% | -1.5 | -1.27% | 41.2% | -1.49 |
| routine_buy_xe1 | 300 | 128 | 49.7% | -0.29% | -0.63 | -0.30% | 43.0% | -0.64 |
| routine_buy_xe3 | 294 | 126 | 47.6% | -1.59% | -1.88 | -1.14% | 46.0% | -1.29 |
| all_buy_xe1 | 3812 | 128 | 49.7% | +0.14% | 0.97 | +0.02% | 51.6% | 0.13 |
| all_buy_xe3 | 3769 | 126 | 49.3% | +0.11% | 0.44 | +0.05% | 50.8% | 0.18 |
| opp_sell_xe1 | 9988 | 128 | 49.0% | -0.06% | -0.58 | -0.02% | 49.2% | -0.14 |
| opp_sell_xe3 | 9858 | 126 | 48.9% | -0.06% | -0.3 | -0.11% | 49.2% | -0.44 |
| routine_sell_xe1 | 8428 | 128 | 51.0% | +0.33% | 1.7 | +0.25% | 57.0% | 1.26 |
| routine_sell_xe3 | 8297 | 126 | 51.2% | +0.72% | 2.18 | +0.58% | 58.7% | 1.32 |

| long-short / subperiod | N months | mean | hit rate | t |
|---|---|---|---|---|
| LS_opp_buy_minus_routine_buy_1m | 115 | -0.41% | 47.0% | -0.64 |
| LS_opp_buy_minus_routine_buy_3m | 114 | -0.01% | 44.7% | -0.01 |
| LS_opp_buy_minus_opp_sell_1m | 115 | -0.73% | 43.5% | -1.51 |
| LS_opp_buy_minus_opp_sell_3m | 114 | -1.19% | 45.6% | -1.28 |
| opp_buy_xr1_2016-2020 | 54 | -0.55% | nan% | -0.89 |
| opp_buy_xr1_2021-2026 | 61 | -1.31% | nan% | -1.66 |
| opp_buy_xe1_2016-2020 | 54 | -0.42% | nan% | -0.71 |
| opp_buy_xe1_2021-2026 | 61 | -1.11% | nan% | -1.59 |
| opp_buy_xr3_2016-2020 | 54 | -0.07% | nan% | -0.05 |
| opp_buy_xr3_2021-2026 | 60 | -3.47% | nan% | -2.84 |
| opp_buy_xe3_2016-2020 | 54 | +0.17% | nan% | 0.14 |
| opp_buy_xe3_2021-2026 | 60 | -2.57% | nan% | -2.29 |

| FF5+Mom regression (monthly; long-only portfolios use returns minus RF) | N | alpha/month | t (NW2) | betas |
|---|---|---|---|---|
| FF5Mom_alpha_opp_buy_1m | 115 | -0.75% | -1.65 | {'Mkt-RF': 0.929, 'SMB': 0.489, 'HML': 0.165, 'RMW': 0.087, 'CMA': 0.185, 'Mom': -0.172} |
| FF5Mom_alpha_routine_buy_1m | 128 | -0.35% | -0.77 | {'Mkt-RF': 0.834, 'SMB': 0.325, 'HML': 0.242, 'RMW': 0.501, 'CMA': 0.289, 'Mom': 0.157} |
| FF5Mom_alpha_all_buy_1m | 128 | -0.10% | -0.49 | {'Mkt-RF': 0.959, 'SMB': 0.228, 'HML': 0.182, 'RMW': 0.226, 'CMA': 0.146, 'Mom': -0.162} |
| FF5Mom_alpha_opp_sell_1m | 128 | -0.16% | -1.12 | {'Mkt-RF': 0.956, 'SMB': 0.099, 'HML': 0.093, 'RMW': 0.082, 'CMA': -0.023, 'Mom': 0.011} |
| FF5Mom_alpha_LS_opp_buy_minus_routine_buy_1m | 115 | -0.34% | -0.57 | {'Mkt-RF': 0.049, 'SMB': 0.23, 'HML': 0.005, 'RMW': -0.327, 'CMA': -0.14, 'Mom': -0.259} |
| FF5Mom_alpha_LS_opp_buy_minus_opp_sell_1m | 115 | -0.64% | -1.47 | {'Mkt-RF': -0.02, 'SMB': 0.355, 'HML': 0.074, 'RMW': -0.042, 'CMA': 0.208, 'Mom': -0.19} |

## B. Current-constituent universe (SURVIVOR-BIASED comparison)

Today's 503 constituents are treated as members for the whole sample. This is upward-biased by construction.

Trade rows: {"('P', 'opportunistic')": 1303, "('P', 'routine')": 3523, "('P', 'unclassified')": 18005, "('S', 'opportunistic')": 44678, "('S', 'routine')": 90196, "('S', 'unclassified')": 142806}. Symbols: 498. Mapping: {'dmitri_ticker_cik_map': 296446, 'issuer_ticker_fallback': 4065}. Statistics reported: 38.

| series | N stock-months | N months | hit rate | mean (event) | t (month-clustered) | mean (EW monthly portfolio) | portfolio hit rate | t (portfolio; NW(2) for 3M) |
|---|---|---|---|---|---|---|---|---|
| opp_buy_xr1 | 353 | 114 | 48.2% | -0.10% | -0.19 | -0.21% | 48.2% | -0.4 |
| opp_buy_xr3 | 351 | 113 | 47.6% | -0.18% | -0.22 | -0.02% | 48.7% | -0.02 |
| routine_buy_xr1 | 332 | 128 | 50.3% | +0.04% | 0.07 | -0.14% | 51.6% | -0.26 |
| routine_buy_xr3 | 326 | 126 | 47.9% | -0.02% | -0.02 | +0.05% | 50.0% | 0.04 |
| all_buy_xr1 | 3682 | 128 | 50.6% | +0.41% | 1.71 | +0.37% | 60.9% | 1.69 |
| all_buy_xr3 | 3639 | 126 | 51.4% | +1.02% | 2.24 | +0.95% | 61.9% | 1.86 |
| opp_sell_xr1 | 10095 | 128 | 49.4% | +0.05% | 0.4 | +0.22% | 56.2% | 1.58 |
| opp_sell_xr3 | 9964 | 126 | 49.1% | +0.42% | 1.64 | +0.57% | 59.5% | 1.7 |
| routine_sell_xr1 | 8920 | 128 | 50.4% | +0.42% | 2.81 | +0.44% | 57.0% | 2.69 |
| routine_sell_xr3 | 8787 | 126 | 51.3% | +1.09% | 4.23 | +1.08% | 62.7% | 3.13 |
| opp_buy_xe1 | 353 | 114 | 47.3% | -0.31% | -0.67 | -0.43% | 44.7% | -0.87 |
| opp_buy_xe3 | 351 | 113 | 44.4% | -0.85% | -1.13 | -0.73% | 46.9% | -0.83 |
| routine_buy_xe1 | 332 | 128 | 50.3% | -0.16% | -0.35 | -0.35% | 50.8% | -0.7 |
| routine_buy_xe3 | 326 | 126 | 43.6% | -0.76% | -0.89 | -0.63% | 42.9% | -0.58 |
| all_buy_xe1 | 3682 | 128 | 49.8% | +0.20% | 1.36 | +0.16% | 51.6% | 1.05 |
| all_buy_xe3 | 3639 | 126 | 48.0% | +0.27% | 1.03 | +0.26% | 54.8% | 0.84 |
| opp_sell_xe1 | 10095 | 128 | 47.9% | -0.08% | -0.78 | +0.01% | 45.3% | 0.07 |
| opp_sell_xe3 | 9964 | 126 | 46.8% | -0.17% | -0.85 | -0.11% | 46.8% | -0.41 |
| routine_sell_xe1 | 8920 | 128 | 49.3% | +0.30% | 1.49 | +0.23% | 50.0% | 1.12 |
| routine_sell_xe3 | 8787 | 126 | 49.1% | +0.55% | 1.56 | +0.40% | 57.9% | 0.85 |

| long-short / subperiod | N months | mean | hit rate | t |
|---|---|---|---|---|
| LS_opp_buy_minus_routine_buy_1m | 114 | -0.08% | 47.4% | -0.12 |
| LS_opp_buy_minus_routine_buy_3m | 113 | -0.28% | 46.9% | -0.18 |
| LS_opp_buy_minus_opp_sell_1m | 114 | -0.41% | 43.9% | -0.8 |
| LS_opp_buy_minus_opp_sell_3m | 113 | -0.62% | 45.1% | -0.66 |
| opp_buy_xr1_2016-2020 | 53 | -0.43% | nan% | -0.73 |
| opp_buy_xr1_2021-2026 | 61 | -0.02% | nan% | -0.02 |
| opp_buy_xe1_2016-2020 | 53 | -0.76% | nan% | -1.35 |
| opp_buy_xe1_2021-2026 | 61 | -0.14% | nan% | -0.18 |
| opp_buy_xr3_2016-2020 | 53 | -0.09% | nan% | -0.07 |
| opp_buy_xr3_2021-2026 | 60 | +0.04% | nan% | 0.03 |
| opp_buy_xe3_2016-2020 | 53 | -1.27% | nan% | -1.09 |
| opp_buy_xe3_2021-2026 | 60 | -0.25% | nan% | -0.2 |

| FF5+Mom regression (monthly; long-only portfolios use returns minus RF) | N | alpha/month | t (NW2) | betas |
|---|---|---|---|---|
| FF5Mom_alpha_opp_buy_1m | 114 | -0.03% | -0.05 | {'Mkt-RF': 0.93, 'SMB': 0.253, 'HML': 0.081, 'RMW': -0.144, 'CMA': 0.191, 'Mom': -0.411} |
| FF5Mom_alpha_routine_buy_1m | 128 | -0.05% | -0.1 | {'Mkt-RF': 0.881, 'SMB': 0.241, 'HML': 0.161, 'RMW': 0.434, 'CMA': 0.009, 'Mom': 0.002} |
| FF5Mom_alpha_all_buy_1m | 128 | +0.43% | 2.07 | {'Mkt-RF': 0.951, 'SMB': 0.154, 'HML': 0.211, 'RMW': 0.212, 'CMA': -0.022, 'Mom': -0.188} |
| FF5Mom_alpha_opp_sell_1m | 128 | +0.24% | 1.53 | {'Mkt-RF': 0.985, 'SMB': 0.129, 'HML': 0.056, 'RMW': 0.049, 'CMA': -0.088, 'Mom': 0.02} |
| FF5Mom_alpha_LS_opp_buy_minus_routine_buy_1m | 114 | -0.02% | -0.03 | {'Mkt-RF': -0.026, 'SMB': 0.049, 'HML': 0.094, 'RMW': -0.482, 'CMA': -0.003, 'Mom': -0.351} |
| FF5Mom_alpha_LS_opp_buy_minus_opp_sell_1m | 114 | -0.35% | -0.7 | {'Mkt-RF': -0.04, 'SMB': 0.092, 'HML': 0.007, 'RMW': -0.222, 'CMA': 0.313, 'Mom': -0.435} |

