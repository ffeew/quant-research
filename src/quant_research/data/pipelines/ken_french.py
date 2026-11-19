"""Ken French Data Library factors -> data/factors/ken_french/<name>_{daily,monthly}.parquet
Values converted from percent to DECIMAL returns. Only the first (value-weighted main) table of each
CSV is kept (annual sub-tables dropped). Raw zips cached in factors/ken_french/raw/.
PIT note: the library is revised/rebuilt (CRSP vintage updates) and published with a lag of ~1-2 months;
historical values can change between vintages -> keep dated raw zips.
Usage: python ken_french.py"""
import io, re, zipfile, datetime as dt
import pandas as pd, requests
from quant_research.data.pipelines.common import DATA, write_parquet, update_manifest, log

OUT = DATA / "factors" / "ken_french"
BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip"
SETS = {"ff3": "F-F_Research_Data_Factors", "ff5": "F-F_Research_Data_5_Factors_2x3",
        "mom": "F-F_Momentum_Factor", "st_rev": "F-F_ST_Reversal_Factor", "lt_rev": "F-F_LT_Reversal_Factor"}


def parse(text, daily):
    lines = text.splitlines()
    hdr = next(i for i, l in enumerate(lines) if re.match(r"^\s*,", l) and re.search(r"[A-Za-z]", l))
    rows = []
    for l in lines[hdr + 1:]:
        parts = [p.strip() for p in l.split(",")]
        if not parts[0] or not parts[0].isdigit() or len(parts[0]) != (8 if daily else 6): break
        rows.append(parts)
    cols = ["date"] + [c.strip() for c in lines[hdr].split(",")[1:]]
    df = pd.DataFrame(rows, columns=cols[:len(rows[0])])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d" if daily else "%Y%m")
    if not daily: df["date"] = df["date"] + pd.offsets.MonthEnd(0)
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce") / 100.0
        df.loc[df[c] <= -0.9999, c] = pd.NA  # -99.99 missing code
    df["date"] = df["date"].dt.date
    return df


def main():
    raw = OUT / "raw"; raw.mkdir(parents=True, exist_ok=True)
    info = {}
    for key, name in SETS.items():
        for freq, suffix in (("monthly", ""), ("daily", "_daily")):
            fn = name + suffix
            r = requests.get(BASE.format(fn), timeout=120, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                info[f"{key}_{freq}"] = f"HTTP {r.status_code}"; log.warning("%s HTTP %s", fn, r.status_code); continue
            (raw / f"{fn}_{dt.date.today()}.zip").write_bytes(r.content)
            z = zipfile.ZipFile(io.BytesIO(r.content))
            text = z.read(z.namelist()[0]).decode("latin-1")
            df = parse(text, freq == "daily")
            df.insert(1, "source_file", fn)
            write_parquet(df, OUT / f"{key}_{freq}.parquet")
            info[f"{key}_{freq}"] = {"rows": len(df), "first": df.date.min(), "last": df.date.max(), "columns": list(df.columns[2:])}
            log.info("%s_%s: %s", key, freq, info[f"{key}_{freq}"])
    update_manifest("factors_ken_french", info)


if __name__ == "__main__":
    main()
