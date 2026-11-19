"""ALFRED real-time vintage store for Maya's curve / carry / credit specs. Uses lib/desk_data_client (FRED throttle +
cache). Writes FROZEN dated files (read-only, 0444) plus SHA256SUMS per group; never overwrites an existing dated file.

Groups (priority order):
  treasury        -> macro/treasury/        DGS3MO DGS2 DGS5 DGS10 DGS30 T10Y2Y
  g10_3m          -> macro/carry/g10_3m/    IR3TIB01{US,EZ,GB,JP,CH,CA,AU,NZ,SE,NO}M156N  (OECD, monthly)
  credit          -> sentiment/credit/      BAMLC0A0CM BAMLH0A0HYM2 (ICE BofA OAS)
  treasury_extra  -> macro/treasury/        DGS1MO DGS6MO DGS1 DGS3 DGS7 DGS20 (optional)
Per group: <g>_vintages_<YYYYMMDD>.parquet, <g>_pit_first_available_<YYYYMMDD>.parquet, <g>_series_meta_<YYYYMMDD>.parquet,
           SHA256SUMS_<g>_<YYYYMMDD>.txt, and qa/fred_<g>_qa_<YYYYMMDD>.md.
Usage: python alfred_store.py treasury [g10_3m credit treasury_extra]
The FRED key is read by the client (env FRED_API_KEY or the key file) and never logged or written.
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys, io, json, hashlib, logging, math, os, datetime as dt
from pathlib import Path
import numpy as np, pandas as pd, requests

sys.path.insert(0, f"{_QR.DATA_DIR}/lib")
from quant_research.data.client import desk_data_client as ddc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alfred_store")
DATA = ddc.DATA_DIR
OBS_START = "2004-01-01"
ET, SGT = "America/New_York", "Asia/Singapore"
GROUPS = {
    "treasury": (DATA / "macro/treasury", ["DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30", "T10Y2Y"]),
    "g10_3m": (DATA / "macro/carry/g10_3m", [f"IR3TIB01{c}M156N" for c in ["US", "EZ", "GB", "JP", "CH", "CA", "AU", "NZ", "SE", "NO"]]),
    "credit": (DATA / "sentiment/credit", ["BAMLC0A0CM", "BAMLH0A0HYM2"]),
    "treasury_extra": (DATA / "macro/treasury", ["DGS1MO", "DGS6MO", "DGS1", "DGS3", "DGS7", "DGS20"]),
}
PRE_ALFRED_MIN_LAG_DAYS = {"D": 10, "M": 120}   # first-vintage rows lagging more than this predate ALFRED tracking


def last_updated_et(s):
    """FRED last_updated is US Central time with an explicit offset, e.g. '2026-10-28 15:16:34-05'."""
    return pd.Timestamp(s).tz_convert(ET)


def availability(v, meta, first_vintage_date):
    """Add availability columns. Date = ALFRED realtime_start (date-only). Time of day = FRED last_updated of the
    current vintage converted to ET and rounded UP to the next 30 min (one empirical sample per series).
    Rows whose first vintage is the series' first ALFRED vintage date and that lag the observation by more than the
    PRE_ALFRED threshold predate ALFRED's tracking: their realtime_start is NOT the publication date. For those,
    available_at_et is an ESTIMATE = observation_date + the series' median genuine first-release lag (business days
    for daily, calendar days for monthly), at the same time of day; availability_method says which rule applied.
    available_at_et_strict always uses realtime_start (never earlier than ALFRED shows)."""
    sid, freq = meta["id"], meta["frequency_short"]
    # Empirical publication offset: FRED last_updated (exact timestamp, Central time) of the newest vintage vs that
    # vintage's date. E.g. DGS10: vintage 2026-10-28, updated 2026-10-28 15:16 CT = 16:16 ET -> +0 bd, 16:30 ET.
    # ICE BofA OAS: vintage dated 2026-10-28 (= observation date) but updated 2026-10-29 09:26 CT -> +1 bd, 10:30 ET,
    # i.e. FRED back-dates ICE vintages to the observation date, so realtime_start alone would be look-ahead.
    lu = last_updated_et(meta["last_updated"])
    lv = pd.Timestamp(meta["last_vintage_date"]).date()
    off_bd = int(np.busday_count(lv, lu.date()))
    tod = lu.ceil("30min")
    hh, mm = tod.hour, tod.minute
    meta["availability_offset_bdays"] = off_bd
    v = v.sort_values(["observation_date", "realtime_start"]).reset_index(drop=True)
    obs = pd.to_datetime(v["observation_date"].astype(str))
    rts = pd.to_datetime(v["realtime_start"].astype(str))
    v["lag_days"] = (rts - obs).dt.days
    if freq == "D":
        v["lag_bdays"] = [np.busday_count(o.date(), r.date()) for o, r in zip(obs, rts)]
    first = ~v["observation_date"].duplicated()
    v["is_first_vintage"] = first
    first_vd = pd.Timestamp(first_vintage_date)   # the series' first ALFRED vintage date (vintagedates endpoint)
    thr = PRE_ALFRED_MIN_LAG_DAYS.get(freq, 30)
    v["pre_alfred"] = first & (rts == first_vd) & (v["lag_days"] > thr)
    # later vintages of a pre-ALFRED observation are genuine revisions with genuine dates
    genuine = first & ~v["pre_alfred"]
    off = pd.Timedelta(hours=hh, minutes=mm)

    def at(dates):   # date -> (date + off_bd business days, rolled forward to a business day) at hh:mm ET
        d = np.busday_offset(pd.DatetimeIndex(dates).values.astype("datetime64[D]"), off_bd, roll="forward")
        return pd.DatetimeIndex(d).tz_localize(ET) + off
    strict = pd.Series(at(rts), index=v.index)
    v["available_at_et_strict"] = strict
    est = strict.copy()
    if v["pre_alfred"].any():
        # estimate from the EARLIEST genuine first releases (closest era; conservative because early ALFRED
        # vintages were less frequent): first 250 daily / 24 monthly genuine observations
        if freq == "D":
            med = int(np.ceil(np.median(v.loc[genuine, "lag_bdays"].head(250)))) if genuine.any() else 1
            d = pd.to_datetime(np.busday_offset(obs[v["pre_alfred"]].dt.date.values.astype("datetime64[D]"), med, roll="forward"))
        else:
            # monthly: the overall median genuine first-release lag (early genuine rows include series
            # re-basings that first appeared years late, so the 'earliest era' rule is not meaningful here)
            med = int(np.ceil(np.median(v.loc[genuine, "lag_days"]))) if genuine.any() else 45
            d = obs[v["pre_alfred"]] + pd.Timedelta(days=med)
        est.loc[v["pre_alfred"]] = at(d)
        meta["pre_alfred_est_lag"] = f"{med} {'business days' if freq == 'D' else 'days'}"
    v["available_at_et"] = est
    v["available_at_sgt"] = v["available_at_et"].dt.tz_convert(SGT)
    v["availability_method"] = np.where(v["pre_alfred"], "estimated_pre_alfred_median_lag",
                                        "alfred_realtime_start+last_updated_time")
    v["availability_time_et"] = f"+{off_bd}bd {hh:02d}:{mm:02d}"
    n = v.groupby("observation_date")["observation_date"].transform("size")
    v["n_vintages"] = n
    v["revised"] = n > 1
    v["is_current"] = v["realtime_end"] == dt.date(9999, 12, 31)
    meta["availability_time_et"] = f"realtime_start +{off_bd} business day(s) at {hh:02d}:{mm:02d} ET"
    g = v[genuine]
    lagcol = "lag_bdays" if freq == "D" else "lag_days"
    meta["first_release_lag_median"] = float(g[lagcol].median()) if len(g) else None
    meta["first_release_lag_p90"] = float(g[lagcol].quantile(0.9)) if len(g) else None
    meta["first_release_lag_unit"] = "business days" if freq == "D" else "calendar days"
    recent = g[pd.to_datetime(g["observation_date"].astype(str)) >= pd.Timestamp.now() - pd.Timedelta(days=3 * 365)]
    meta["first_release_lag_median_last3y"] = float(recent[lagcol].median()) if len(recent) else None
    return v


def fredgraph_latest(sid):
    ddc.fred_throttle().acquire("/graph/fredgraph.csv")
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": sid}, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["observation_date", "value"]
    df["value"] = pd.to_numeric(df["value"].replace(".", np.nan), errors="coerce")
    df["observation_date"] = pd.to_datetime(df["observation_date"]).dt.date
    return df


def qa(v, meta):
    sid, freq = meta["id"], meta["frequency_short"]
    cur = v[v["is_current"]]
    out = {"series_id": sid, "rows": len(v), "observations": v["observation_date"].nunique(),
           "dup_rows": int(v.duplicated(["series_id", "observation_date", "realtime_start"]).sum()),
           "dup_current": int(cur["observation_date"].duplicated().sum()),
           "nan_current": int(cur["value"].isna().sum())}
    d = pd.to_datetime(cur["observation_date"].astype(str))
    if freq == "D":
        exp = pd.bdate_range(d.min(), d.max())
    else:
        exp = pd.date_range(d.min(), d.max(), freq="MS")
    missing = exp.difference(pd.DatetimeIndex(d))
    out["expected_periods"] = len(exp); out["missing_periods"] = len(missing)
    out["missing_sample"] = ",".join(x.date().isoformat() for x in missing[:8])
    try:
        fg = fredgraph_latest(sid)
        m = cur.merge(fg, on="observation_date", suffixes=("", "_fg"))
        m = m.tail(60)
        diff = (m["value"] - m["value_fg"]).abs()
        out["fredgraph_compared"] = len(m)
        out["fredgraph_max_abs_diff"] = float(diff.max()) if len(m) else None
        out["fredgraph_nan_mismatch"] = int((m["value"].isna() != m["value_fg"].isna()).sum())
        out["fredgraph_last_date"] = fg.dropna()["observation_date"].max().isoformat()
        out["alfred_last_date"] = cur.dropna(subset=["value"])["observation_date"].max().isoformat()
    except Exception as e:
        out["fredgraph_error"] = type(e).__name__
    return out


def write_frozen(df, path):
    if path.exists():
        raise SystemExit(f"refusing to overwrite frozen file {path}")
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    os.chmod(path, 0o444)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_group(g):
    outdir, ids = GROUPS[g]
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().strftime("%Y%m%d")   # box clock = SGT
    frames, metas, qas = [], [], []
    for sid in ids:
        try:
            meta = ddc.fred_series_info(sid)
        except ddc.FredError as e:
            log.warning("%s does not resolve (%s); flagged, NOT substituted", sid, e.status)
            metas.append({"id": sid, "resolved": False, "error": str(e)[:200]}); continue
        meta = dict(meta); meta["resolved"] = True
        v = ddc.alfred_vintages(sid, OBS_START)
        vds = ddc.fred_vintage_dates(sid)
        meta["n_vintage_dates"] = len(vds); meta["first_vintage_date"] = vds[0] if vds else None
        meta["last_vintage_date"] = vds[-1] if vds else None
        v = availability(v, meta, vds[0])
        meta["store_obs_start"] = v["observation_date"].min().isoformat() if len(v) else None
        meta["store_obs_end"] = v["observation_date"].max().isoformat() if len(v) else None
        meta["rows"] = len(v); meta["observations"] = int(v["observation_date"].nunique())
        meta["revised_observations"] = int(v.loc[v["is_first_vintage"], "revised"].sum())
        meta["pre_alfred_observations"] = int(v["pre_alfred"].sum())
        frames.append(v); metas.append(meta); qas.append(qa(v, meta))
        log.info("%s: %d rows, %d obs %s..%s, revised %d, pre-ALFRED %d", sid, len(v), meta["observations"],
                 meta["store_obs_start"], meta["store_obs_end"], meta["revised_observations"], meta["pre_alfred_observations"])
    cols = ["series_id", "observation_date", "value", "realtime_start", "realtime_end", "is_current", "is_first_vintage",
            "n_vintages", "revised", "lag_days", "lag_bdays", "pre_alfred", "available_at_et", "available_at_sgt",
            "available_at_et_strict", "availability_method", "availability_time_et"]
    V = pd.concat(frames, ignore_index=True)
    V = V[[c for c in cols if c in V.columns]]
    F = V[V["is_first_vintage"]].reset_index(drop=True)
    M = pd.DataFrame(metas).astype(str)
    sums = {}
    for name, df in [(f"{g}_vintages_{stamp}.parquet", V), (f"{g}_pit_first_available_{stamp}.parquet", F),
                     (f"{g}_series_meta_{stamp}.parquet", M)]:
        sums[name] = write_frozen(df, outdir / name)
    sp = outdir / f"SHA256SUMS_{g}_{stamp}.txt"
    sp.write_text("".join(f"{h}  {n}\n" for n, h in sums.items())); os.chmod(sp, 0o444)
    Q = pd.DataFrame(qas)
    (DATA / "qa").mkdir(exist_ok=True)
    qp = DATA / "qa" / f"fred_{g}_qa_{stamp}.md"
    qp.write_text(f"# FRED/ALFRED QA: {g} ({stamp}, SGT)\n\n" + Q.to_markdown(index=False) + "\n\n## Series meta\n\n" +
                  M[[c for c in ["id", "resolved", "title", "frequency_short", "units_short", "observation_start",
                                 "observation_end", "last_updated", "n_vintage_dates", "first_vintage_date",
                                 "availability_time_et", "first_release_lag_median", "first_release_lag_median_last3y",
                                 "first_release_lag_p90", "first_release_lag_unit", "pre_alfred_observations",
                                 "pre_alfred_est_lag", "revised_observations", "rows", "error"] if c in M.columns]].to_markdown(index=False) + "\n")
    summary = {"group": g, "dir": str(outdir), "files": sums, "qa": str(qp), "rows_vintages": len(V), "rows_first": len(F),
               "series": {m["id"]: {k: m.get(k) for k in ["resolved", "store_obs_start", "store_obs_end", "rows",
                                                          "observations", "revised_observations", "pre_alfred_observations",
                                                          "first_vintage_date", "availability_time_et",
                                                          "first_release_lag_median", "first_release_lag_median_last3y",
                                                          "first_release_lag_unit", "pre_alfred_est_lag", "observation_start"]}
                          for m in metas}}
    (outdir / f"summary_{g}_{stamp}.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))
    print(Q.to_string())


def _staleness(*names):
    """Write data/staleness/<name>.json from on-disk observation maxima (lib/staleness.py). Never changes exit code."""
    try:
        import sys as _s; _s.path.insert(0, f"{_QR.DATA_DIR}/lib"); from quant_research.data.client import staleness
        for n in names: staleness.record(n)
    except Exception as e:
        print(f"STALENESS record failed: {e}", file=__import__("sys").stderr)


if __name__ == "__main__":
    for g in sys.argv[1:] or ["treasury"]:
        run_group(g)
        if g == "credit": _staleness("credit_oas")
