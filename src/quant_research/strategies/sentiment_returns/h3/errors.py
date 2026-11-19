"""Typed failures for the H3 library."""
from __future__ import annotations

from ..h2c.errors import ConfigError


class H3ConfigError(ConfigError):
    """A parameter is missing, unknown, or an unsettled design choice was used without a value."""
