#!/usr/bin/env python
"""Run a trial by name: `python scripts/run_trial.py <trial> [args...]` (same as `qr run`)."""

import sys

from quant_research.cli import main

if __name__ == "__main__":
    sys.exit(main(["run", *sys.argv[1:]]))
