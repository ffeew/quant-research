"""Daily snapshot of Alpaca asset flags (shortable, easy_to_borrow, marginable, tradable, fractionable, status)
for ALL us_equity assets -> data/assets/snapshots/assets_<YYYY-MM-DD ET>.parquet (one file per ET date; re-running
the same day overwrites that day only). History only exists from the first run onward (no backfill possible).
Knowledge time = snapshot_utc. Run once a day, ideally pre-open (e.g. 08:00-09:00 ET).
Also rebuilds assets/universe_asset_flags_history.parquet (universe symbols x snapshot dates, bool flags).
One command (from anywhere):  $QR_DATA_DIR/.venv/bin/python $QR_DATA_DIR/pipelines/assets_snapshot.py"""

from __future__ import annotations

import pandas as pd

from quant_research.data.pipelines.common import DATA, TRADING_URL, get, log, update_manifest, write_parquet
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)


def main() -> None:
    a = pd.DataFrame(get(TRADING_URL + "/v2/assets", {"status": "all", "asset_class": "us_equity"}))
    now = pd.Timestamp.now(tz="UTC")
    a["snapshot_utc"] = now
    a["snapshot_date_et"] = now.tz_convert("America/New_York").date()
    f = DATA / "assets" / "snapshots" / f"assets_{a['snapshot_date_et'].iloc[0]}.parquet"
    a = a.astype({c: str for c in a.columns if a[c].dtype == object and c not in ("snapshot_date_et",)})
    write_parquet(a, f)
    u = pd.read_parquet(DATA / "universe" / "universe.parquet")
    m = a[a.symbol.isin(set(u.symbol))]
    info = {
        "file": str(f),
        "assets": len(a),
        "universe_matched": len(m),
        "universe_shortable": int((m.shortable.astype(str) == "True").sum()),
        "universe_easy_to_borrow": int((m.easy_to_borrow.astype(str) == "True").sum()),
    }
    # rebuild the universe flag history from all daily snapshots (idempotent)
    cols = [
        "symbol",
        "snapshot_date_et",
        "snapshot_utc",
        "status",
        "tradable",
        "shortable",
        "easy_to_borrow",
        "marginable",
        "fractionable",
        "exchange",
    ]
    snaps = sorted((DATA / "assets" / "snapshots").glob("assets_*.parquet"))
    h = pd.concat([pd.read_parquet(x, columns=[c for c in cols if c in pd.read_parquet(x).columns]) for x in snaps])
    h = h[h.symbol.isin(set(u.symbol))]
    for c in ("tradable", "shortable", "easy_to_borrow", "marginable", "fractionable"):
        if c in h:
            h[c] = h[c].astype(str).eq("True")
    write_parquet(
        h.sort_values(["symbol", "snapshot_date_et"]).reset_index(drop=True),
        DATA / "assets" / "universe_asset_flags_history.parquet",
    )
    info["history_snapshots"] = len(snaps)
    info["history_rows"] = len(h)
    update_manifest("assets_snapshot", info)
    log.info("%s", info)


def _staleness(*names: str) -> None:
    """Write data/staleness/<name>.json from on-disk observation maxima (lib/staleness.py). Never changes exit code."""
    try:
        import sys as _s

        _s.path.insert(0, f"{_QR.DATA_DIR}/lib")
        from quant_research.data.client import staleness

        for n in names:
            staleness.record(n)
    except Exception as e:
        print(f"STALENESS record failed: {e}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
    _staleness("assets_borrow")
