"""Stage 6: assemble earnings_events_8k202.parquet (v1) = events_core + exhibit columns. No prices/returns.

Dedupes events_core on accession before the merge. The same EDGAR accession can appear under two
related CIKs (parent/sub or holdco/opco both listing the filing in submissions): EXC/POM,
SO/Southern Co Gas, XRX/Xerox Holdings, Baker Hughes Co/Holdings LLC, Mylan Inc/Mylan II.
Keep the in_sp500 row when exactly one is in-index; otherwise keep the lower CIK. Dropped rows
are written to work/events_dup_accessions_dropped.parquet for audit.
"""

import pandas as pd

k = pd.read_parquet("work/events_core.parquet")
x = pd.read_parquet("work/exhibits.parquet")

# ---- dedupe accession (one event = one EDGAR filing) ----
k = k.sort_values(["accession", "in_sp500", "cik"], ascending=[True, False, True])
dup_mask = k.accession.duplicated(keep="first")
dropped = k.loc[dup_mask].copy()
dropped.to_parquet("work/events_dup_accessions_dropped.parquet", index=False)
print("dedupe: kept", (~dup_mask).sum(), "dropped", int(dup_mask.sum()), "dup accessions", dropped.accession.nunique())
k = k.loc[~dup_mask].reset_index(drop=True)
assert k.accession.is_unique

e = k.merge(x, on="accession", how="left", validate="one_to_one")
# exhibits fetched only for in_sp500 (v1); outside-index events stay null with an explicit rule
miss = e.ex99_rule.isna()
e.loc[miss & ~e.in_sp500, "ex99_rule"] = "not fetched in v1 (event outside S&P 500 membership)"
e.loc[miss & e.in_sp500, "ex99_rule"] = "exhibit fetch missing (should not happen after top-up)"
e["acceptance_et"] = e.acceptance_et.dt.tz_localize("America/New_York")
for c in ["filing_date", "session_date", "session_date_0925"]:
    e[c] = pd.to_datetime(e[c]).dt.date
e["exhibit_count"] = e.exhibit_count.astype("Int64")
e["dataset_version"] = "earnings_events_8k202 v1 (the sentiment researcher, 2026-11-06)"
cols = [
    "cik",
    "ticker_at_event",
    "ticker_source",
    "accession",
    "form",
    "items",
    "filing_date",
    "acceptance_utc",
    "acceptance_et",
    "session_date",
    "pre_open",
    "intraday",
    "post_close",
    "non_session_day",
    "timing",
    "session_date_0925",
    "is_amendment",
    "cluster_n_filings",
    "cluster_has_amendment",
    "cluster_accessions",
    "in_sp500",
    "index_symbols",
    "map_source",
    "sec_name",
    "ex99_url",
    "ex99_filename",
    "exhibit_count",
    "ex99_type",
    "ex99_description",
    "ex99_rule",
    "primary_doc",
    "filing_index_url",
    "acceptance_raw",
    "dataset_version",
]
e = e[cols].sort_values(["acceptance_utc", "cik"]).reset_index(drop=True)
e.to_parquet("earnings_events_8k202.parquet", index=False, compression="zstd")
ins = e[e.in_sp500]
print(
    "final",
    len(e),
    "in_sp500",
    int(e.in_sp500.sum()),
    "ex99_url rate (in_sp500)",
    round(ins.ex99_url.notna().mean(), 4),
    "no EX-99 (in_sp500)",
    int((ins.ex99_rule == "no EX-99 exhibit").sum()),
    "missing fetch (in_sp500)",
    int((ins.ex99_rule == "exhibit fetch missing (should not happen after top-up)").sum()),
)
