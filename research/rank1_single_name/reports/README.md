# Rank1 v3.2 — FINAL small append-only synthetic delta

**NO REAL DATA / NOT A FREEZE / NO PRODUCTION OR CAPTURE AUTHORITY.**
Only G-1/R-1 changes. All89 pinned parent files preserved;15 inherited Python files copied byte-identically. No research parameters, scorer, dates,23-column card or family floor177 changed. No network/install/audit/outcomes/archive/scorer evaluation/RNG execution/freeze/capture/messages. Signed static definition bytes are config metadata, not market data.

## Reproduce
```sh
python3 -B -m unittest -v test_rank1_synthetic test_rank1_v2 test_rank1_v3 test_rank1_v3_1 test_rank1_v3_2
```
Run in this directory: **148 tests PASS =140 inherited +8 new.** Full log: `TEST_RESULTS_v3_2.txt`. Fabricated metadata fixtures created/removed; empty inherited fixtures directory removed before seal. No actual data path executed.

## G-1: tests can now fail for the intended reason
The new tests wrap `os.open` AND retain that wrapped function in `supports_dir_fd`. Positive control reaches secure open/read using the approved fabricated path. The unapproved path contains an independent exact1907-byte correctly hashed definition copy; approved file also exists. Negative cases require **unknown definition path**, zero opens, NOT missing/size/hash/capability errors. Alias/Path-object rejection also has a valid positive control.

Three actual in-memory mutants KILLED: remove allowlist; admit/read supplied arbitrary path; coerce Path-object aliases to strings. The original loader remains byte-identical. Historical vacuous tests remain preserved but new tests close that synthetic test gap.

## R-1: enforced mandatory entry route, production still absent/disabled
New `rank1_adapter_disk_guard.py` supplies an exact metadata-only adapter gate. Its sole shared route binds via `bind_sigma_contract_from_disk` on EVERY invocation before anything downstream. Its production-facing API accepts no caller definition bytes, prior receipt/prepared contract, canonical result, data rows, evaluator or alternative binder. No real-data evaluator/adapter implementation is enabled.

Explicit `synthetic_route_probe` shares that mandatory route, requires fabricated fixture ID + synthetic contract marker, and invokes only a test callback after valid disk binding. Positive controls actually reach that callback and verify fresh loader calls; negative tests are **not** satisfied by unconditional production disable. Caller buffers and receipts independently pass legacy synthetic validation, and direct canonical output is produced on fabricated inputs, yet all are refused as adapter inputs with the exact R-1 schema cause. Corrupt on-disk metadata must fail the exact hash check despite valid embedded bytes. Four semantic bypass mutants KILLED: embedded fallback instead of disk, trust caller bytes, trust caller receipt, direct-canonical-result shortcut.

This enforces the entry API route; it does not sandbox arbitrary Python or remove legacy pure synthetic functions. Those functions are NOT real-data routes. `RealDataAdapterGate.production_entrypoint` has only a metadata argument and always raises after guarded preflight; the existing production entrypoint and PCG64 hook remain always disabled. Tests execute only the fabricated shared-route seam, never an actual data route. Independent NB2/real-adapter acceptance remains required; no self-issued closure or new authority.

## Evidence and binding restrictions
TR basis is reported **NOT_AVAILABLE**, with corporate-actions/B7/PIT blockers. Verified decision section A identifies as NOT_AVAILABLE FYI, not a validation decision. No exact receipt path/full hash supplied there; receipt not searched for/read/independently certified. This is not merely a promised pending certificate; no acquisition/repair or completion promise. The static signed cost-estimator receipt remains SATISFIED but cannot solve actual TR basis.

Still blocked: accepted PCG64/runtime byte lock; independent full NB2/readback and real-adapter wiring approval; B1–B7/B11/B13/NB3/NB4/RIGHTS; matching sector freeze+RUNLOG; P1 rules re-pin at separately authorized freeze; explicit real-run approval. No audit/seen-map receipt invented. D3 still bars paper trading, promotion and allocation regardless numerical results. Optional H48 unchanged/inactive/unreviewed; +1 charged/floor177, no24th PBO column, O1–O3 unchanged. No earnings-control rework.

**fixed D3 claim limitation (not a test result)**

Addendum A incremental value NOT MET; may reflect post-earnings drift

CONDITIONAL HISTORICAL RESEARCH EVIDENCE: STANDARD Addendum A incremental value NOT MET (no earnings-surprise control); may reflect post-earnings-announcement drift.

## Integrity / stop
`SOURCE_PINS_v3_2.json` records full parent/source hashes, `HASH_DIFF_v3_2.md` the narrow delta, `MUTANT_KILL_RECEIPT_v3_2.json`7 actual semantic kills, `MANIFEST.sha256` all delivered files except itself. Parent v3_1 manifest21/21, v3 manifest24/24 verified (prior26 claim is corrected by decision). No parent changed. Final requested delta only; no further Rank1 work/actions/plans unless explicitly asked.
