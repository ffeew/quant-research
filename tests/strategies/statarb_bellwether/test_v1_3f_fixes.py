"""Synthetic tests for the review fixes to the bellwether runner (B1 look-ahead, B2 ADV cap,
B3 calendar-day borrow). Each test fails on the pre-fix runner and passes on the fixed one.

The runner is loaded with a config built from the pre-cleanup pins, exactly as in the
equivalence test, so no desk path or pin is needed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from .test_config_equivalence import bars, earnings, old_src, pair

__all__ = ["old_src"]  # re-exported pytest fixture


@pytest.fixture(scope="module")
def mod(old_src: str, tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp: Path = tmp_path_factory.mktemp("fixes")
    _, new = pair(old_src, tmp, {})
    return new


def _h1(mod: Any) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[Any]]:
    B = bars()
    d = pd.DatetimeIndex(B["R"].index)
    stocks = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    E = pd.DataFrame(True, index=d, columns=stocks)
    sub = pd.Series("Semis", index=stocks)
    evidx = mod.make_evidx(mod.earliest_possible_index(earnings(d), B["R"].index))
    W, tr = mod.signal_h1(B, E, sub, evidx, eval_start=mod.DEV0, eval_end=mod.DEV1, last_exit_i=len(d) - 1 - mod.MARGIN)
    return B, W, tr


def test_b1_h1_signal_at_t_first_earns_t1_to_t2(mod: Any) -> None:
    B, W, tr = _h1(mod)
    d = W.index
    nz = np.flatnonzero((W.abs().sum(axis=1) > 0).to_numpy())
    assert len(nz), "fixture must produce an H1 book"
    i = int(nz[0]) - 1
    assert d[i] in tr  # the bar before the first holding is a signal bar
    assert (W.iloc[: i + 1] == 0).all().all()  # nothing held on that signal bar
    deep = dict(B, VOL=B["VOL"] * 1e6)  # keep the ADV cap out of this timing check
    g = mod.apply_costs_and_returns(deep, W, mod.build_cost_config("unknown_borrow_required"), idea="H1")["daily"]
    gross = g["gross"]
    assert gross.loc[d[i + 1]] == 0
    R = deep["R"].iloc[i + 2].reindex(W.columns).fillna(0.0)
    assert np.isclose(gross.loc[d[i + 2]], float((W.iloc[i + 1] * R).sum())) and gross.loc[d[i + 2]] != 0
