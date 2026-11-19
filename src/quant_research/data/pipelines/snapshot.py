"""Snapshot manifest: sha256 over the sorted list of (relative path, size, sha256) of every data file under
$QR_DATA_DIR (parquet files; excludes logs/, raw source caches, *.tmp*, snapshots/, .venv/).
Writes snapshots/<UTC timestamp>_<version>.json and prints the top-level hash.
Usage: python snapshot.py --version v1.1 --note "what changed" """

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

DATA = Path(f"{_QR.DATA_DIR}")
EXCL = ("logs/", "snapshots/", ".venv/", "/raw/", "pipelines/", "lib/")


def sha(p: Path, bs: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(bs), b""):
            h.update(b)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    files: list[dict[str, Any]] = []
    for p in sorted(DATA.rglob("*.parquet")):
        rel = p.relative_to(DATA).as_posix()
        if ".tmp" in rel or any(x in "/" + rel for x in EXCL):
            continue
        files.append({"path": rel, "size": p.stat().st_size, "sha256": sha(p)})
    files.sort(key=lambda x: x["path"])
    top = hashlib.sha256("\n".join(f"{f['path']}\t{f['size']}\t{f['sha256']}" for f in files).encode()).hexdigest()
    now = dt.datetime.now(dt.UTC)
    out = {
        "version": a.version,
        "created_utc": now.isoformat(timespec="seconds"),
        "created_sgt": now.astimezone(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
        "note": a.note,
        "n_files": len(files),
        "total_bytes": sum(f["size"] for f in files),
        "hash_method": "sha256 of '\\n'.join(path\\tsize\\tsha256) over files sorted by path",
        "top_hash": top,
        "files": files,
    }
    f = DATA / "snapshots" / f"{now.strftime('%Y%m%dT%H%M%SZ')}_{a.version}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1))
    os.replace(tmp, f)
    (DATA / "VERSION").write_text(f"{a.version} {top} {out['created_sgt']}\n")
    print(json.dumps({"version": a.version, "top_hash": top, "file": str(f), "n_files": len(files)}))


if __name__ == "__main__":
    main()
