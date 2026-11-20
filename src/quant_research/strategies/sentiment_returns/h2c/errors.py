"""Typed failures. ``code`` mirrors the frozen runner's coded STOPs so callers can map them to exit codes."""

from __future__ import annotations


class H2CError(Exception):
    code = 1

    def __init__(self, msg: str, code: int | None = None) -> None:
        super().__init__(msg)
        if code is not None:
            self.code = code


class IntegrityError(H2CError):  # sha mismatch
    code = 2


class MappingError(H2CError):  # transcript -> earnings mapping cross-check
    code = 3


class SchemaError(H2CError):
    code = 4


class ConfigError(H2CError):  # unfilled required runtime inputs
    code = 5


class PathError(H2CError):  # listing escapes its root
    code = 6


class PurgeMismatch(H2CError):
    code = 7


class PartitionError(H2CError):  # row outside the partition
    code = 8


class HoldoutRefusedError(PartitionError):  # the HOLDOUT partition is spent; this library never runs it
    code = 8
