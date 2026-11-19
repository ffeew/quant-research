"""Environment reads that fail closed on renamed (legacy) variable names."""

from __future__ import annotations

import os

# new name -> legacy name it replaced; setting the legacy name is an error, never a silent default
LEGACY = {"RESEARCH_SEC_RPS": "DAVE_SEC_RPS", "RESEARCH_TRIAL_LOG": "DAVE_TRIAL_LOG"}


def getenv[T](name: str, default: T) -> str | T:
    old = LEGACY.get(name)
    if old is not None and old in os.environ:
        raise RuntimeError(f"{old} is no longer read; set {name} instead")
    return os.environ.get(name, default)
