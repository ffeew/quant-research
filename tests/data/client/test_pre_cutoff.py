import datetime as dt
import hashlib
import json
from typing import Any

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest

from quant_research.data.client import pre_cutoff
from quant_research.data.client.pre_cutoff import CUTOFF, CutoffError, read_json_pre_cutoff, read_pre_cutoff

D = dt.date


def _write(tmp_path, table, name="t.parquet", **kw):
    p = tmp_path / name
    pq.write_table(table, p, **kw)
    return p


def _basic(tmp_path):
    t = pa.table(
        {
            "id": pa.array([1, 2, 3, 4, 5], pa.int64()),
            "start": pa.array(
                [D(2017, 1, 3), D(2022, 3, 29), D(2022, 3, 30), D(2026, 10, 1), D(2020, 5, 5)], pa.date32()
            ),
            "end": pa.array([None, D(2021, 1, 1), None, None, D(2026, 1, 2)], pa.date32()),
        }
    )
    return _write(tmp_path, t)


def test_cutoff_constant():
    assert D(2022, 3, 30) == CUTOFF


def test_post_cutoff_rows_never_appear(tmp_path):
    t = read_pre_cutoff(_basic(tmp_path), ["id", "start", "end"], ["start"], ["end"])
    assert sorted(t["id"].to_pylist()) == [1, 2, 5]
    assert t.num_rows == 3


def test_day_before_cutoff_kept(tmp_path):
    t = read_pre_cutoff(_basic(tmp_path), ["id", "start", "end"], ["start"], ["end"])
    assert 2 in t["id"].to_pylist()


def test_post_cutoff_mask_col_nulled_row_kept(tmp_path):
    t = read_pre_cutoff(_basic(tmp_path), ["id", "start", "end"], ["start"], ["end"])
    rows = dict(zip(t["id"].to_pylist(), t["end"].to_pylist()))
    assert 5 in rows
    assert rows[5] is None
    assert rows[2] == D(2021, 1, 1)


def test_only_named_columns_read(tmp_path):
    t = read_pre_cutoff(_basic(tmp_path), ["id", "start"], ["start"])
    assert t.column_names == ["id", "start"]


def test_unnamed_date_column_refused(tmp_path):
    with pytest.raises(CutoffError):
        read_pre_cutoff(_basic(tmp_path), ["id", "start", "end"], ["start"])


def test_role_outside_columns_refused(tmp_path):
    with pytest.raises(ValueError, match="not in columns"):
        read_pre_cutoff(_basic(tmp_path), ["id", "start"], ["start"], ["end"])


def test_empty_columns_refused(tmp_path):
    with pytest.raises(ValueError, match="at least one"):
        read_pre_cutoff(_basic(tmp_path), [], [])


def test_sha_mismatch_refused(tmp_path):
    p = _basic(tmp_path)
    with pytest.raises(CutoffError, match="sha256 mismatch"):
        read_pre_cutoff(p, ["id", "start"], ["start"], expect_sha256="0" * 64)


def test_sha_match_accepted(tmp_path):
    p = _basic(tmp_path)
    full = hashlib.sha256(p.read_bytes()).hexdigest()
    assert read_pre_cutoff(p, ["id", "start"], ["start"], expect_sha256=full).num_rows == 3
    assert read_pre_cutoff(p, ["id", "start"], ["start"], expect_sha256=full[:8]).num_rows == 3


@pytest.mark.parametrize(
    ("typ", "tz"),
    [
        (pa.timestamp("us"), None),
        (pa.timestamp("ns", tz="UTC"), "UTC"),
        (pa.timestamp("ms", tz="America/New_York"), "America/New_York"),
        (pa.timestamp("s", tz="+08:00"), "+08:00"),
    ],
)
def test_timestamps(tmp_path, typ, tz):
    tzinfo = pre_cutoff._tzinfo(tz) if tz else None
    vals = [
        dt.datetime(2022, 3, 29, 23, 59, tzinfo=tzinfo),
        dt.datetime(2022, 3, 30, 0, 0, tzinfo=tzinfo),
        dt.datetime(2026, 1, 1, tzinfo=tzinfo),
        dt.datetime(2019, 1, 1, tzinfo=tzinfo),
    ]
    t = pa.table(
        {"id": [1, 2, 3, 4], "ts": pa.array(vals, typ), "te": pa.array([vals[2], vals[1], vals[0], vals[0]], typ)}
    )
    p = _write(tmp_path, t)
    out = read_pre_cutoff(p, ["id", "ts", "te"], ["ts"], ["te"])
    assert sorted(out["id"].to_pylist()) == [1, 4]
    te = dict(zip(out["id"].to_pylist(), out["te"].to_pylist()))
    assert te[1] is None
    assert te[4] == vals[0]
    out2 = read_pre_cutoff(p, ["id", "ts"], ["ts"])
    assert out2.num_rows == 2


def test_timestamp_column_unnamed_refused(tmp_path):
    t = pa.table({"id": [1], "ts": pa.array([dt.datetime(2019, 1, 1)], pa.timestamp("us"))})  # noqa: DTZ001
    with pytest.raises(CutoffError):
        read_pre_cutoff(_write(tmp_path, t), ["id", "ts"], [])


def test_date64(tmp_path):
    t = pa.table({"id": [1, 2], "d": pa.array([D(2021, 1, 1), D(2022, 3, 30)], pa.date64())})
    out = read_pre_cutoff(_write(tmp_path, t), ["id", "d"], ["d"])
    assert out["id"].to_pylist() == [1]


def test_iso_string_dates(tmp_path):
    t = pa.table(
        {
            "id": [1, 2, 3],
            "vf": pa.array(["2018-01-01", "2022-03-30", "2022-03-29"], pa.large_string()),
            "vt": pa.array([None, None, "2024-01-01"], pa.string()),
        }
    )
    out = read_pre_cutoff(_write(tmp_path, t), ["id", "vf", "vt"], ["vf"], ["vt"])
    assert sorted(out["id"].to_pylist()) == [1, 3]
    assert out["vt"].null_count == 2
    assert out.schema.field("vf").type == pa.date32()


def test_nullable_date_cols_keep_nulls_drop_post(tmp_path):
    t = pa.table({"id": [1, 2, 3, 4], "s": pa.array([None, D(2020, 1, 1), D(2022, 3, 30), None], pa.date32())})
    p = _write(tmp_path, t)
    out = read_pre_cutoff(p, ["id", "s"], [], nullable_date_cols=["s"])
    assert sorted(out["id"].to_pylist()) == [1, 2, 4]
    strict = read_pre_cutoff(p, ["id", "s"], ["s"])
    assert strict["id"].to_pylist() == [2]


def test_single_post_cutoff_row_group_returns_zero_rows(tmp_path):
    t = pa.table({"id": [1, 2], "d": pa.array([D(2022, 3, 30), D(2026, 10, 28)], pa.date32())})
    p = _write(tmp_path, t)
    assert pq.ParquetFile(p).metadata.num_row_groups == 1
    out = read_pre_cutoff(p, ["id", "d"], ["d"])
    assert out.num_rows == 0
    assert out.column_names == ["id", "d"]


def test_post_cutoff_row_group_pruned_by_statistics(tmp_path):
    t = pa.table(
        {"id": [1, 2, 3, 4], "d": pa.array([D(2018, 1, 1), D(2019, 1, 1), D(2023, 1, 1), D(2024, 1, 1)], pa.date32())}
    )
    p = _write(tmp_path, t, row_group_size=2)
    frag = next(iter(ds.dataset(p, format="parquet").get_fragments()))
    kept = frag.split_by_row_group(filter=ds.field("d") < pa.scalar(CUTOFF, pa.date32()))
    assert len(kept) == 1
    assert sorted(read_pre_cutoff(p, ["id", "d"], ["d"])["id"].to_pylist()) == [1, 2]


def test_filter_pushed_into_dataset_scan(tmp_path, monkeypatch):
    p = _basic(tmp_path)
    calls: list[dict[str, Any]] = []
    real_dataset = ds.dataset

    class Spy:
        def __init__(self, inner):
            self._inner = inner
            self.schema = inner.schema

        def to_table(self, **kwargs):
            calls.append(kwargs)
            return self._inner.to_table(**kwargs)

    monkeypatch.setattr(pre_cutoff.ds, "dataset", lambda *a, **k: Spy(real_dataset(*a, **k)))

    def _no_read_table(*a, **k):
        raise AssertionError("pq.read_table must not be used")

    monkeypatch.setattr(pq, "read_table", _no_read_table)
    out = read_pre_cutoff(p, ["id", "start", "end"], ["start"], ["end"])
    assert out.num_rows == 3
    assert len(calls) == 1
    filt = calls[0]["filter"]
    assert isinstance(filt, ds.Expression)
    assert "start" in str(filt)
    assert "<" in str(filt)
    cols = calls[0]["columns"]
    assert isinstance(cols, dict)
    assert set(cols) == {"id", "start", "end"}
    assert "if_else" in str(cols["end"])


def test_post_scan_assert_catches_leak(tmp_path, monkeypatch):
    p = _basic(tmp_path)
    real_dataset = ds.dataset

    class Leaky:
        def __init__(self, inner):
            self._inner = inner
            self.schema = inner.schema

        def to_table(self, **kwargs):
            kwargs["filter"] = None
            return self._inner.to_table(**kwargs)

    monkeypatch.setattr(pre_cutoff.ds, "dataset", lambda *a, **k: Leaky(real_dataset(*a, **k)))
    with pytest.raises(CutoffError, match="after the scan"):
        read_pre_cutoff(p, ["id", "start"], ["start"])


def test_all_null_mask_col_ok(tmp_path):
    t = pa.table({"id": [1], "s": pa.array([D(2019, 1, 1)], pa.date32()), "e": pa.array([None], pa.date32())})
    out = read_pre_cutoff(_write(tmp_path, t), ["id", "s", "e"], ["s"], ["e"])
    assert out.num_rows == 1


def test_json_reader_prunes_keys_and_drops_post_cutoff(tmp_path):
    recs = [
        {"symbol": "AAA", "d": "2019-01-01", "secret": 1},
        {"symbol": "BBB", "d": "2022-03-30T00:00:00", "secret": 2},
        {"symbol": "CCC", "d": None, "secret": 3},
        {"symbol": "DDD", "d": "2022-03-29", "secret": 4},
    ]
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"files": recs, "other": "x"}))
    out = read_json_pre_cutoff(p, ["symbol", "d"], ["d"], records_key="files")
    assert [r["symbol"] for r in out] == ["AAA", "CCC", "DDD"]
    assert all(set(r) == {"symbol", "d"} for r in out)
    p2 = tmp_path / "l.json"
    p2.write_text(json.dumps(recs))
    assert [r["symbol"] for r in read_json_pre_cutoff(p2, ["symbol"])] == ["AAA", "BBB", "CCC", "DDD"]
    with pytest.raises(CutoffError):
        read_json_pre_cutoff(p2, ["symbol"], expect_sha256="f" * 8)
    with pytest.raises(ValueError):
        read_json_pre_cutoff(p2, [])
