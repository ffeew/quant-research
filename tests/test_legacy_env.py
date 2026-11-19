"""Renamed env vars fail closed: setting the legacy name raises and names its replacement."""

from __future__ import annotations

import pytest

from quant_research.utils import env


def test_legacy_sec_rps_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_SEC_RPS", raising=False)
    assert env.getenv("RESEARCH_SEC_RPS", "8") == "8"
    monkeypatch.setenv("DAVE_SEC_RPS", "2")
    with pytest.raises(RuntimeError, match="RESEARCH_SEC_RPS"):
        env.getenv("RESEARCH_SEC_RPS", "8")


def test_legacy_trial_log_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_TRIAL_LOG", "smoke.csv")
    assert env.getenv("RESEARCH_TRIAL_LOG", "TRIAL_LOG.csv") == "smoke.csv"
    monkeypatch.setenv("DAVE_TRIAL_LOG", "smoke.csv")
    with pytest.raises(RuntimeError, match="RESEARCH_TRIAL_LOG"):
        env.getenv("RESEARCH_TRIAL_LOG", "TRIAL_LOG.csv")
