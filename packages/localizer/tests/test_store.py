"""Tests for the DuckDB store layer (localizer.store).

All tests use tmp_path to avoid touching ~/.localizer/.
These tests must FAIL (RED) until the store module is implemented.
"""

from __future__ import annotations

import hashlib
import pathlib
import time

import pytest

# ---------------------------------------------------------------------------
# Import the module under test — will raise ModuleNotFoundError until the
# coder creates packages/localizer/src/localizer/store/db.py.
# ---------------------------------------------------------------------------
from localizer.store.db import LocalizerStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_events(n: int, source_id: str = "lastfm") -> list[dict]:
    """Return a list of n minimal event dicts."""
    return [
        {
            "source_id": source_id,
            "timestamp": 1000 + i,
            "label": f"Artist{i}",
            "sublabel": f"Track{i}",
            "category": f"Album{i}",
            "raw_json": None,
            "fetched_at": int(time.time()),
        }
        for i in range(n)
    ]


def _make_places(n: int, source_id: str = "swarm") -> list[dict]:
    """Return a list of n minimal place dicts."""
    return [
        {
            "source_id": source_id,
            "timestamp": 2000 + i,
            "lat": 37.7749 + i * 0.001,
            "lng": -122.4194 + i * 0.001,
            "place_name": f"Cafe {i}",
            "place_type": "coffee",
            "raw_json": None,
            "fetched_at": int(time.time()),
        }
        for i in range(n)
    ]


def _make_content(n: int, source_id: str = "feedly") -> list[dict]:
    """Return a list of n minimal content dicts."""
    return [
        {
            "source_id": source_id,
            "timestamp": 3000 + i,
            "title": f"Article {i}",
            "url": f"https://example.com/{i}",
            "feed_title": "Example Feed",
            "author": "Author",
            "raw_json": None,
            "fetched_at": int(time.time()),
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. Round-trip and idempotency
# ---------------------------------------------------------------------------


def test_upsert_and_query_events_round_trip(tmp_path):
    """Upsert 5 events, query back — exactly 5 rows, correct columns."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.upsert_events(_make_events(5))
        df = store.query_events()

    assert len(df) == 5
    expected_cols = {"timestamp", "label", "sublabel", "category", "source_id"}
    assert expected_cols.issubset(set(df.columns)), (
        f"Missing columns: {expected_cols - set(df.columns)}"
    )


def test_upsert_events_idempotent(tmp_path):
    """Upsert the same 5 records twice — query back returns exactly 5 rows, not 10."""
    db_path = tmp_path / "store.duckdb"
    records = _make_events(5)
    with LocalizerStore(db_path) as store:
        store.upsert_events(records)
        store.upsert_events(records)
        df = store.query_events()

    assert len(df) == 5, f"Expected 5 rows after double upsert, got {len(df)}"


def test_upsert_places_round_trip(tmp_path):
    """Upsert 3 places, query back — exactly 3 rows, correct columns."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.upsert_places(_make_places(3))
        df = store.query_places()

    assert len(df) == 3
    expected_cols = {"timestamp", "lat", "lng", "place_name", "place_type", "source_id"}
    assert expected_cols.issubset(set(df.columns)), (
        f"Missing columns: {expected_cols - set(df.columns)}"
    )


def test_upsert_content_round_trip(tmp_path):
    """Upsert 2 content records, query back — exactly 2 rows."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.upsert_content(_make_content(2))
        df = store.query_content()

    assert len(df) == 2


def test_query_events_filters_by_source_id(tmp_path):
    """Upsert events for two source_ids; query by one returns only that source's rows."""
    db_path = tmp_path / "store.duckdb"
    lastfm_events = _make_events(3, source_id="lastfm")
    github_events = _make_events(2, source_id="github")
    with LocalizerStore(db_path) as store:
        store.upsert_events(lastfm_events + github_events)
        df = store.query_events(source_id="lastfm")

    assert len(df) == 3
    assert (df["source_id"] == "lastfm").all()


def test_query_events_default_omits_raw_json(tmp_path):
    """query_events() without include_raw_json must not add a raw_json column."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.upsert_events(_make_events(1))
        df = store.query_events()

    assert "raw_json" not in df.columns


def test_query_events_include_raw_json_adds_column(tmp_path):
    """query_events(include_raw_json=True) must add a raw_json column with the stored value."""
    import json

    db_path = tmp_path / "store.duckdb"
    records = _make_events(1)
    records[0]["raw_json"] = json.dumps({"tags": ["a", "b"], "photopage": "https://example.com/1"})
    with LocalizerStore(db_path) as store:
        store.upsert_events(records)
        df = store.query_events(include_raw_json=True)

    assert "raw_json" in df.columns
    assert len(df) == 1
    parsed = json.loads(df.iloc[0]["raw_json"])
    assert parsed["tags"] == ["a", "b"]
    assert parsed["photopage"] == "https://example.com/1"


def test_query_events_filters_by_since(tmp_path):
    """Upsert 3 events at timestamps 1000, 2000, 3000; since=1500 returns 2 rows."""
    db_path = tmp_path / "store.duckdb"
    records = [
        {
            "source_id": "lastfm",
            "timestamp": ts,
            "label": "Artist",
            "sublabel": "Track",
            "category": "Album",
            "raw_json": None,
            "fetched_at": int(time.time()),
        }
        for ts in [1000, 2000, 3000]
    ]
    with LocalizerStore(db_path) as store:
        store.upsert_events(records)
        df = store.query_events(since=1500)

    assert len(df) == 2, f"Expected 2 rows with timestamp >= 1500, got {len(df)}"
    assert (df["timestamp"] >= 1500).all()


# ---------------------------------------------------------------------------
# 1b. query_events(include_raw_json=True) — issue #124, Drinking History view.
#
# pages/beer.py needs rating_score/venue_name/venue_lat/venue_lng, which the
# UntappdPlugin only ever writes into raw_json (events has no lat/lng columns).
# LocalizerBroker.get_events_frame() intentionally never exposes raw_json (it
# feeds the generic lastfm-shaped merge), so this opt-in flag is the only way
# to get raw_json back out of the events table without changing that default
# shape or touching core/broker.py.
# ---------------------------------------------------------------------------


def test_query_events_default_excludes_raw_json_column(tmp_path):
    """By default (include_raw_json unset), raw_json must not be in the result columns."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.upsert_events(_make_events(2))
        df = store.query_events()

    assert "raw_json" not in df.columns


def test_query_events_include_raw_json_preserves_standard_columns(tmp_path):
    """include_raw_json=True must add raw_json without dropping the usual columns."""
    db_path = tmp_path / "store.duckdb"
    records = _make_events(1)
    records[0]["raw_json"] = '{"rating": 4.5, "venue_lat": 40.7128}'
    with LocalizerStore(db_path) as store:
        store.upsert_events(records)
        df = store.query_events(include_raw_json=True)

    assert "raw_json" in df.columns
    expected_cols = {"timestamp", "label", "sublabel", "category", "source_id", "raw_json"}
    assert expected_cols.issubset(set(df.columns))


def test_query_events_include_raw_json_round_trips_content(tmp_path):
    """The raw_json column returned must contain the exact JSON that was upserted."""
    import json

    db_path = tmp_path / "store.duckdb"
    records = _make_events(1)
    records[0]["raw_json"] = json.dumps({"rating": 4.5, "venue_name": "The Tasting Room"})
    with LocalizerStore(db_path) as store:
        store.upsert_events(records)
        df = store.query_events(include_raw_json=True)

    parsed = json.loads(df.iloc[0]["raw_json"])
    assert parsed["rating"] == 4.5
    assert parsed["venue_name"] == "The Tasting Room"


def test_query_events_include_raw_json_still_filters_by_source_id(tmp_path):
    """include_raw_json must not interfere with the existing source_id filter."""
    db_path = tmp_path / "store.duckdb"
    lastfm_events = _make_events(2, source_id="lastfm")
    untappd_events = _make_events(3, source_id="untappd")
    with LocalizerStore(db_path) as store:
        store.upsert_events(lastfm_events + untappd_events)
        df = store.query_events(source_id="untappd", include_raw_json=True)

    assert len(df) == 3
    assert (df["source_id"] == "untappd").all()
    assert "raw_json" in df.columns


# ---------------------------------------------------------------------------
# 2. Re-open safety
# ---------------------------------------------------------------------------


def test_store_reopens_without_error(tmp_path):
    """Open store, insert 1 event, close; re-open same path, query returns 1 row."""
    db_path = tmp_path / "store.duckdb"

    with LocalizerStore(db_path) as store:
        store.upsert_events(_make_events(1))

    # Re-open — must not raise
    with LocalizerStore(db_path) as store2:
        df = store2.query_events()

    assert len(df) == 1


def test_store_does_not_duplicate_schema(tmp_path):
    """Two separate LocalizerStore instances on the same file don't duplicate schema."""
    db_path = tmp_path / "store.duckdb"

    store1 = LocalizerStore(db_path)
    store1.open()
    store1.upsert_events(_make_events(2))

    store2 = LocalizerStore(db_path)
    store2.open()  # Must not raise even though schema already exists
    df = store2.query_events()
    store1.close()
    store2.close()

    assert len(df) == 2


# ---------------------------------------------------------------------------
# 3. Default path
# ---------------------------------------------------------------------------


def test_default_path_returns_path_object():
    """LocalizerStore.default_path() returns a pathlib.Path instance."""
    result = LocalizerStore.default_path()
    assert isinstance(result, pathlib.Path)


def test_default_path_ends_with_store_duckdb():
    """The default path filename is 'store.duckdb'."""
    result = LocalizerStore.default_path()
    assert result.name == "store.duckdb"


def test_default_path_under_localizer_dir():
    """The parent directory of the default path is named '.localizer'."""
    result = LocalizerStore.default_path()
    assert result.parent.name == ".localizer"


# ---------------------------------------------------------------------------
# 4. Views
# ---------------------------------------------------------------------------


def test_v_what_when_view_exists(tmp_path):
    """After open, SELECT * FROM v_what_when LIMIT 0 executes without error."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        # Access the underlying connection to run raw SQL
        store.conn.execute("SELECT * FROM v_what_when LIMIT 0")


def test_v_where_when_view_exists(tmp_path):
    """After open, SELECT * FROM v_where_when LIMIT 0 executes without error."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.conn.execute("SELECT * FROM v_where_when LIMIT 0")


def test_v_what_when_columns(tmp_path):
    """v_what_when has exactly the expected columns."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        result = store.conn.execute("SELECT * FROM v_what_when LIMIT 0").df()

    expected = {"timestamp", "label", "sublabel", "category", "source_id"}
    assert set(result.columns) == expected, (
        f"v_what_when columns mismatch: got {set(result.columns)}"
    )


# ---------------------------------------------------------------------------
# 5. Schema version
# ---------------------------------------------------------------------------


def test_schema_version_set_after_open(tmp_path):
    """_localizer_meta has a non-empty schema_version after opening the store."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        rows = store.conn.execute(
            "SELECT value FROM _localizer_meta WHERE key = 'schema_version'"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0]  # non-empty string


# ---------------------------------------------------------------------------
# 6. Deterministic ID
# ---------------------------------------------------------------------------


def test_deterministic_id_same_inputs_same_id(tmp_path):
    """Two records with identical source_id+timestamp+label+sublabel share the same id."""
    db_path = tmp_path / "store.duckdb"
    record = {
        "source_id": "lastfm",
        "timestamp": 1000,
        "label": "Artist",
        "sublabel": "Track",
        "category": "Album",
        "raw_json": None,
        "fetched_at": int(time.time()),
    }
    with LocalizerStore(db_path) as store:
        store.upsert_events([record])
        store.upsert_events([record])  # second upsert — same id
        ids = store.conn.execute("SELECT id FROM events").fetchall()

    assert len(ids) == 1, f"Expected 1 unique id, got {len(ids)}"


def test_deterministic_id_known_value(tmp_path):
    """The generated id equals the first 16 hex chars of sha256 of the concatenated fields."""
    db_path = tmp_path / "store.duckdb"
    source_id = "lastfm"
    timestamp = 1000
    label = "Artist"
    sublabel = "Track"

    # Expected: sha256(source_id + str(timestamp) + label + sublabel)[:16]
    raw = (source_id + str(timestamp) + label + sublabel).encode()
    expected_id = hashlib.sha256(raw).hexdigest()[:16]

    record = {
        "source_id": source_id,
        "timestamp": timestamp,
        "label": label,
        "sublabel": sublabel,
        "category": "Album",
        "raw_json": None,
        "fetched_at": int(time.time()),
    }
    with LocalizerStore(db_path) as store:
        store.upsert_events([record])
        rows = store.conn.execute("SELECT id FROM events").fetchall()

    assert rows[0][0] == expected_id, f"Expected id {expected_id!r}, got {rows[0][0]!r}"


# ---------------------------------------------------------------------------
# 7. Context manager / resource cleanup
# ---------------------------------------------------------------------------


def test_context_manager_closes_on_exit(tmp_path):
    """After the with block, the store's connection is closed."""
    db_path = tmp_path / "store.duckdb"
    store = LocalizerStore(db_path)
    with store:
        pass  # normal exit

    # The connection must be None after __exit__
    assert store.conn is None


def test_context_manager_closes_on_exception(tmp_path):
    """Exception inside with block propagates AND connection is closed."""
    db_path = tmp_path / "store.duckdb"
    store = LocalizerStore(db_path)

    with pytest.raises(RuntimeError, match="test error"):
        with store:
            raise RuntimeError("test error")

    # Connection must be None after exception
    assert store.conn is None


# ---------------------------------------------------------------------------
# 8. Sync state
# ---------------------------------------------------------------------------


def test_get_sync_state_default_for_unknown_source(tmp_path):
    """get_sync_state for an unknown source returns status='never_run', record_count=0,
    last_synced_at=None, and last_cursor=None."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        state = store.get_sync_state("newplugin")

    assert state["status"] == "never_run"
    assert state["record_count"] == 0
    assert state["last_synced_at"] is None, (
        f"Expected last_synced_at to be None for unknown source, got {state['last_synced_at']!r}"
    )
    assert state["last_cursor"] is None, (
        f"Expected last_cursor to be None for unknown source, got {state['last_cursor']!r}"
    )


def test_get_sync_state_default_has_all_keys(tmp_path):
    """get_sync_state default response for an unknown source contains all four required keys."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        state = store.get_sync_state("brandnewsource")

    required_keys = {"status", "record_count", "last_synced_at", "last_cursor"}
    missing = required_keys - set(state.keys())
    assert not missing, (
        f"get_sync_state default is missing keys: {missing}. Got keys: {set(state.keys())}"
    )


# ---------------------------------------------------------------------------
# 9. Atomicity
# ---------------------------------------------------------------------------


def test_upsert_events_atomicity_on_failure(tmp_path):
    """A failed upsert_events batch leaves the store unchanged (atomic transaction).

    Strategy: use a proxy connection whose ``executemany`` first inserts 2 rows
    into DuckDB via the real connection, then raises an exception — simulating a
    mid-batch failure where some rows have already reached the database.

    Without an explicit ``BEGIN``/``COMMIT`` around the entire batch, those 2
    rows will be auto-committed before the exception propagates, leaving the
    store in a partially-written state (count == 2, not 0).

    The test asserts the store has 0 rows after the failed call.  This test is
    RED against the current production code (which does NOT wrap the executemany
    in an explicit transaction) and will turn GREEN once the coder adds a
    ``BEGIN``/``COMMIT`` block (or equivalent) around the executemany call.
    """
    db_path = tmp_path / "store.duckdb"

    class _PartialThenFailConnProxy:
        """Proxy that, on the first ``executemany`` call, inserts only the first
        2 rows via the real connection and then raises to simulate a mid-batch
        failure after partial data has been written."""

        def __init__(self, real_conn):
            object.__setattr__(self, "_real", real_conn)
            object.__setattr__(self, "_call_count", 0)

        def __getattr__(self, name):
            if name == "executemany":
                real_conn = object.__getattribute__(self, "_real")
                call_count = object.__getattribute__(self, "_call_count")

                def _partial_then_fail(sql, rows, *args, **kwargs):
                    # Insert only the first 2 rows to simulate partial progress
                    real_conn.executemany(sql, list(rows)[:2])
                    # Now raise — as if a network error or constraint hit row 3
                    raise RuntimeError("simulated mid-batch failure after 2 rows")

                object.__setattr__(self, "_call_count", call_count + 1)
                return _partial_then_fail

            return getattr(object.__getattribute__(self, "_real"), name)

    with LocalizerStore(db_path) as store:
        # Baseline: store is empty
        assert len(store.query_events()) == 0

        real_conn = store._conn
        store._conn = _PartialThenFailConnProxy(real_conn)  # type: ignore[assignment]
        try:
            with pytest.raises(RuntimeError, match="simulated mid-batch failure after 2 rows"):
                store.upsert_events(_make_events(3))
        finally:
            store._conn = real_conn

        # Atomicity: the entire batch must have been rolled back — 0 rows expected.
        # Without a transaction, 2 rows will have been auto-committed before the
        # exception, so this assertion will FAIL (count == 2) until the coder
        # wraps the executemany in BEGIN/COMMIT.
        count = len(store.query_events())
        assert count == 0, (
            f"Expected 0 rows after failed upsert (atomicity), got {count}. "
            "upsert_events must wrap its executemany call in an explicit transaction."
        )


def test_set_and_get_sync_state(tmp_path):
    """set_sync_state persists values that get_sync_state returns correctly."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.set_sync_state(
            "lastfm",
            last_cursor="page5",
            status="ok",
            record_count=42,
        )
        state = store.get_sync_state("lastfm")

    assert state["last_cursor"] == "page5"
    assert state["status"] == "ok"
    assert state["record_count"] == 42


# ---------------------------------------------------------------------------
# 10. get_latest_timestamp (resumable-sync support, issue #109)
# ---------------------------------------------------------------------------


def test_get_latest_timestamp_returns_max_for_source(tmp_path):
    """get_latest_timestamp returns the max timestamp among a source's events."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.upsert_events(_make_events(5, source_id="lastfm"))  # timestamps 1000..1004
        latest = store.get_latest_timestamp("lastfm", table="events")

    assert latest == 1004


def test_get_latest_timestamp_none_when_no_rows(tmp_path):
    """get_latest_timestamp returns None when the source has no rows in that table."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        latest = store.get_latest_timestamp("neversynced", table="events")

    assert latest is None


def test_get_latest_timestamp_scoped_to_source_id(tmp_path):
    """get_latest_timestamp for one source ignores rows belonging to another source."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.upsert_events(_make_events(3, source_id="lastfm"))  # 1000..1002
        store.upsert_events(
            [
                {
                    "source_id": "other",
                    "timestamp": 9999,
                    "label": "X",
                    "sublabel": None,
                    "category": None,
                    "raw_json": None,
                    "fetched_at": int(time.time()),
                }
            ]
        )
        latest = store.get_latest_timestamp("lastfm", table="events")

    assert latest == 1002


def test_get_latest_timestamp_supports_places_table(tmp_path):
    """get_latest_timestamp against table='places' reads from the places table."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.upsert_places(_make_places(4, source_id="swarm"))  # timestamps 2000..2003
        latest = store.get_latest_timestamp("swarm", table="places")

    assert latest == 2003


def test_get_latest_timestamp_supports_content_table(tmp_path):
    """get_latest_timestamp against table='content' reads from the content table."""
    db_path = tmp_path / "store.duckdb"
    with LocalizerStore(db_path) as store:
        store.upsert_content(_make_content(3, source_id="feedly"))
        latest = store.get_latest_timestamp("feedly", table="content")

    assert latest is not None
