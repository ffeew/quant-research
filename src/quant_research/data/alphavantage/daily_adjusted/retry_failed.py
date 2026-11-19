"""One retry pass for FAILED symbols after main loop finished. Same limiter/no-clobber/key rules. Appends superseding records."""

from __future__ import annotations

import importlib.util
import json
import sys

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

TS = sys.argv[1]
spec = importlib.util.spec_from_file_location("f", f"{_QR.DESK_DIR}/statarb/av_rebuild_20261110/fetch_av_h1h2.py")
sys.argv = ["x", TS]
F = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # file location spec is a ModuleSpec
spec.loader.exec_module(F)  # type: ignore[union-attr]  # file location loader is set
prog = F.WORK / f"PROGRESS_SOFIA_{TS}.jsonl"
last = {}
for l in prog.read_text().splitlines():
    r = json.loads(l)
    last[r["symbol"]] = r
assert "FETCH_LOOP_COMPLETE" in F.LOGF.read_text()
for sym, rec in last.items():
    if not rec["status"].startswith("FAILED"):
        continue
    new = dict(rec)
    new["retry_of_status"] = rec["status"]
    new["retry_of_detail"] = rec.get("detail")
    final = F.EQ / f"{sym}.csv"
    if F.existing_for(sym):
        new.update(status="SKIPPED_EXISTING", existing=F.existing_for(sym))
    else:
        kind, body, det = F.call(rec["params"])
        new["fetch_utc"] = F.utc()
        new["detail"] = det
        if kind == "ERROR_MESSAGE":
            new["status"] = "NOT_AVAILABLE"
        elif kind == "FAILED":
            new["status"] = "FAILED"
        else:
            try:
                n, f0, f1 = F.validate_series(body)
            except Exception as ex:
                new.update(status="FAILED_VALIDATION", detail=F.redact(f"{type(ex).__name__}:{ex}")[:200])
            else:
                if F.KEY.encode() in body:
                    new["status"] = "FAILED_KEY_IN_BODY"
                elif not F.excl_write(final, body):
                    new["status"] = "SKIPPED_EXISTING_RACE"
                else:
                    new.update(
                        status="FETCHED",
                        path=str(final),
                        sha256=F.sha(body),
                        bytes=len(body),
                        rows=n,
                        first_date=f0,
                        last_date=f1,
                    )
    with open(prog, "a") as f:
        f.write(json.dumps(new, default=str) + "\n")
    F.log(f"RETRY {sym} {rec['status']} -> {new['status']}")
F.log("RETRY_PASS_COMPLETE")
