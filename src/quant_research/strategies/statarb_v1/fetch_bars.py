"""Replacement for the retired fetch_alpaca.py (desk rule #5, 2026-10-30).
History is read from Dmitri's store ($QR_DATA_DIR) via the shared client; live Alpaca market-data calls, if any,
go ONLY through $QR_DATA_DIR/lib/desk_data_client.py (shared 150/min throttle, cache, no credential handling here).
Usage: python fetch_bars.py SYM1,SYM2 2020-01-01 [2026-10-29] [all|raw]  -> prints a coverage summary (writes nothing).
Note: statarb/.venv has no `requests`, so only local-store reads work from it; the research code never needs live data."""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys
sys.path.insert(0, f"{_QR.DATA_DIR}/lib")
from quant_research.data.client import desk_data_client as ddc  # noqa: E402

if __name__ == "__main__":
    syms = sys.argv[1].split(","); start = sys.argv[2] if len(sys.argv) > 2 else "2016-01-01"
    end = sys.argv[3] if len(sys.argv) > 3 else None; adj = sys.argv[4] if len(sys.argv) > 4 else "all"
    df = ddc.get_daily_bars(syms, start, end, adjustment=adj)
    print(df.groupby("symbol").agg(first=("session_date", "min"), last=("session_date", "max"), n=("session_date", "size"),
                                   source=("source", lambda s: ",".join(sorted(set(s))))))
    print("warnings:", df.attrs.get("warnings"))
