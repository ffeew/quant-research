"""Parse SEC Insider Transactions Data Sets zips (raw/*_form345.zip) into trades.parquet.
Keeps Form 4 (original, not amendments) non-derivative open-market purchases (P) and sales (S).
One row per (transaction line x reporting owner). Dates: FILING_DATE (public) and TRANS_DATE.
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import glob, zipfile, csv, sys
import pandas as pd
sys.path.insert(0, f"{_QR.DESK_DIR}/equity")
out = []
for z in sorted(glob.glob("raw/*_form345.zip")):
    zf = zipfile.ZipFile(z)
    rd = lambda t, cols: pd.read_csv(zf.open(t), sep="\t", dtype=str, usecols=cols, quoting=csv.QUOTE_NONE, on_bad_lines="skip", encoding="latin-1")
    s = rd("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERTRADINGSYMBOL"])
    s = s[s.DOCUMENT_TYPE == "4"]
    o = rd("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"])
    t = rd("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"])
    t = t[t.TRANS_CODE.isin(["P", "S"])]
    d = t.merge(s, on="ACCESSION_NUMBER").merge(o, on="ACCESSION_NUMBER")
    d["src"] = z.split("/")[-1][:6]
    out.append(d); print(z, len(d), flush=True)
d = pd.concat(out, ignore_index=True)
d = d.rename(columns=str.lower)
d["filing_date"] = pd.to_datetime(d.filing_date, format="%d-%b-%Y", errors="coerce")
d["trans_date"] = pd.to_datetime(d.trans_date, format="%d-%b-%Y", errors="coerce")
d["issuercik"] = pd.to_numeric(d.issuercik, errors="coerce").astype("Int64")
d["rptownercik"] = pd.to_numeric(d.rptownercik, errors="coerce").astype("Int64")
for c in ("trans_shares", "trans_pricepershare"): d[c] = pd.to_numeric(d[c], errors="coerce")
d["issuertradingsymbol"] = d.issuertradingsymbol.str.upper().str.strip()
d = d.dropna(subset=["filing_date", "trans_date", "issuercik", "rptownercik"])
d = d.drop_duplicates(["accession_number", "rptownercik", "trans_date", "trans_code", "trans_shares", "trans_pricepershare"])
d.to_parquet("trades.parquet", index=False)
print("rows", len(d), d.filing_date.min(), d.filing_date.max(), d.trans_code.value_counts().to_dict())
