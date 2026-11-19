#!/usr/bin/env python
"""Build a dataset: `python scripts/build_data.py <dataset> [args...]` (same as `qr build-data`).

Needs ALPHAVANTAGE_API_KEY (and, for some builders, ALPACA_* / FRED_API_KEY / SEC_USER_AGENT)
in the environment, and writes under $QR_DATA_DIR. Run `qr datasets` for the list.
"""

import sys

from quant_research.cli import main

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(main(["datasets"]))
    sys.exit(main(["build-data", *sys.argv[1:]]))
