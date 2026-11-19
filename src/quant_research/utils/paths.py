"""Filesystem roots, configured by environment variables (never hard-coded).

QR_DATA_DIR     root of the research data store (bars, fundamentals, AV pulls ...). Default: ./data
QR_DESK_DIR     root of the desk workspace some legacy scripts read/write (validation/, tca/ ...). Default: .
QR_SCRATCH_DIR  scratch area for staging runs. Default: <tmp>/qr_scratch
HOME_DIR        the user's home directory (e.g. FRED key-file fallback).

Values are plain strings, so path building in the (frozen) research code is byte-for-byte
unchanged when the variables point at the original desk locations.
"""

import os
import tempfile

DATA_DIR = os.environ.get("QR_DATA_DIR", os.path.abspath("data")).rstrip("/")
DESK_DIR = os.environ.get("QR_DESK_DIR", os.path.abspath(".")).rstrip("/")
SCRATCH_DIR = os.environ.get("QR_SCRATCH_DIR", os.path.join(tempfile.gettempdir(), "qr_scratch")).rstrip("/")
HOME_DIR = os.path.expanduser("~").rstrip("/")


def data_path(*parts: str) -> str:
    """Join parts under QR_DATA_DIR."""
    return os.path.join(DATA_DIR, *parts)


# Shared cost models live inside the package (formerly the desk's tca/tca_scripts folder).
COSTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest", "costs")
