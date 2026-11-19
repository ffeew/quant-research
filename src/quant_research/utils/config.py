"""Load per-trial configs from configs/<trial>.toml."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = Path(os.environ.get("QR_CONFIG_DIR", REPO_ROOT / "configs"))
NON_TRIAL_CONFIGS = {"datasets"}


def list_trials() -> list[str]:
    return sorted(p.stem for p in CONFIG_DIR.glob("*.toml") if p.stem not in NON_TRIAL_CONFIGS)


def load_trial(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / f"{name}.toml"
    if not path.exists():
        raise KeyError(f"unknown trial {name!r}; known: {', '.join(list_trials())}")
    with path.open("rb") as fh:
        cfg = tomllib.load(fh)
    cfg.setdefault("trial", {})["name"] = name
    return cfg
