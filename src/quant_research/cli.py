"""`qr` command-line entry point.

    qr list                      list trials with status and verdict
    qr show <trial>              print a trial's config
    qr run <trial> [args...]     run a trial's entry module (as `python -m <module> args...`)
    qr datasets                  list dataset builders
    qr build-data <dataset> [args...]   run a dataset builder module
"""
from __future__ import annotations

import argparse
import json
import runpy
import sys
import tomllib

from quant_research.utils import config


def _run_module(module: str, args: list[str]) -> int:
    sys.argv = [module, *args]
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit as exc:  # scripts call sys.exit / raise SystemExit
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return 0


def _datasets() -> dict:
    path = config.CONFIG_DIR / "datasets.toml"
    with path.open("rb") as fh:
        return tomllib.load(fh)["datasets"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="qr", description="quant_research command line")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list trials")
    s = sub.add_parser("show", help="show a trial config")
    s.add_argument("trial")
    r = sub.add_parser("run", help="run a trial entry point")
    r.add_argument("trial")
    r.add_argument("args", nargs=argparse.REMAINDER)
    sub.add_parser("datasets", help="list dataset builders")
    b = sub.add_parser("build-data", help="run a dataset builder")
    b.add_argument("dataset")
    b.add_argument("args", nargs=argparse.REMAINDER)
    ns = p.parse_args(argv)

    if ns.cmd == "list":
        for name in config.list_trials():
            t = config.load_trial(name)["trial"]
            print(f"{name:28s} {t.get('status', ''):12s} {t.get('verdict', '')}")
        return 0
    if ns.cmd == "show":
        print(json.dumps(config.load_trial(ns.trial), indent=2, default=str))
        return 0
    if ns.cmd == "run":
        t = config.load_trial(ns.trial)["trial"]
        entry = t.get("entry")
        if not entry:
            print(f"trial {ns.trial!r} has no runnable code in this repo ({t.get('status')})", file=sys.stderr)
            return 2
        return _run_module(entry, ns.args)
    if ns.cmd == "datasets":
        for name, d in sorted(_datasets().items()):
            print(f"{name:28s} {d['module']}")
        return 0
    if ns.cmd == "build-data":
        ds = _datasets()
        if ns.dataset not in ds:
            print(f"unknown dataset {ns.dataset!r}; see `qr datasets`", file=sys.stderr)
            return 2
        return _run_module(ds[ns.dataset]["module"], ns.args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
