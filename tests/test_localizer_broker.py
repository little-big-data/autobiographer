"""Failing tests for Subtask 4: LocalizerBroker in core/broker.py.

All tests here are expected to FAIL until the coder implements:
  - LocalizerBroker class in core/broker.py (sibling to DataBroker)

LocalizerBroker must expose the same public interface as DataBroker:
  - get_merged_frame(since=None) -> pd.DataFrame
  - get_frame(plugin_id: str) -> pd.DataFrame
  - load(plugin, config) -> pd.DataFrame
  - is_type_available(plugin_type: str) -> bool
  - available_types: list[str]

All tests use tmp_path-scoped DuckDB files to avoid touching ~/.localizer/.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest
from localizer.store.db import LocalizerStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_MERGED_COLUMNS = {"timestamp", "label", "sublabel", "category", "source_id"}


def _seed_events(store: LocalizerStore, n: int = 3, source_id: str = "lastfm") -> None:
    """Insert *n* synthetic event records into *store*."""
    now = int(time.time())
    records = [
        {
            "source_id": source_id,
            "timestamp": now - i * 60,
            "label": f"Artist{i}",
            "sublabel": f"Track{i}",
            "category": f"Album{i}",
            "raw_json": "{}",
            "fetched_at": now,
        }
        for i in range(n)
    ]
    store.upsert_events(records)


def _seed_places(store: LocalizerStore, n: int = 2, source_id: str = "swarm") -> None:
    """Insert *n* synthetic place records into *store*."""
    now = int(time.time())
    records = [
        {
            "source_id": source_id,
            "timestamp": now - i * 3600,
            "lat": 51.5074 + i * 0.01,
            "lng": -0.1278 + i * 0.01,
            "place_name": f"Place{i}",
            "place_type": "Bar",
            "raw_json": "{}",
            "fetched_at": now,
        }
        for i in range(n)
    ]
    store.upsert_places(records)


# ---------------------------------------------------------------------------
# Import / instantiation tests
# ---------------------------------------------------------------------------


def test_localizer_broker_importable() -> None:
    """'from core.broker import LocalizerBroker' must succeed."""
    from core.broker import LocalizerBroker  # noqa: F401

    assert LocalizerBroker is not None


def test_localizer_broker_instantiates_with_store_path(tmp_path: Path) -> None:
    """LocalizerBroker must accept a store path and not raise on construction."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"
    broker = LocalizerBroker(store_path=db_path)
    assert broker is not None


# ---------------------------------------------------------------------------
# get_frame tests
# ---------------------------------------------------------------------------


def test_localizer_broker_get_frame_empty_when_no_data(tmp_path: Path) -> None:
    """get_frame() on a fresh (empty) store must return an empty DataFrame."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"
    broker = LocalizerBroker(store_path=db_path)
    result = broker.get_frame("lastfm")
    assert isinstance(result, pd.DataFrame)
    assert result.empty


# ---------------------------------------------------------------------------
# load tests
# ---------------------------------------------------------------------------


def test_localizer_broker_load_returns_dataframe(tmp_path: Path) -> None:
    """load(plugin, config) must return a DataFrame without raising."""
    from localizer.plugins.lastfm.loader import LastFmPlugin

    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"
    broker = LocalizerBroker(store_path=db_path)
    plugin = LastFmPlugin()
    result = broker.load(plugin, {})
    assert isinstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# get_merged_frame tests
# ---------------------------------------------------------------------------


def test_localizer_broker_get_merged_frame_empty(tmp_path: Path) -> None:
    """get_merged_frame() on an empty store must return an empty DataFrame, not raise."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"
    broker = LocalizerBroker(store_path=db_path)
    result = broker.get_merged_frame()
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_localizer_broker_get_merged_frame_with_events(tmp_path: Path) -> None:
    """get_merged_frame() returns >= 3 rows when 3 events are seeded."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"

    with LocalizerStore(path=db_path) as store:
        _seed_events(store, n=3)

    broker = LocalizerBroker(store_path=db_path)
    result = broker.get_merged_frame()
    assert isinstance(result, pd.DataFrame)
    assert len(result) >= 3, f"Expected >= 3 rows, got {len(result)}"


def test_localizer_broker_get_merged_frame_has_required_columns(tmp_path: Path) -> None:
    """get_merged_frame() result must contain the what-when schema columns."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"

    with LocalizerStore(path=db_path) as store:
        _seed_events(store, n=1)

    broker = LocalizerBroker(store_path=db_path)
    result = broker.get_merged_frame()
    missing = REQUIRED_MERGED_COLUMNS - set(result.columns)
    assert not missing, f"get_merged_frame() result missing required columns: {missing}"


def test_localizer_broker_get_merged_frame_events_only_no_places(tmp_path: Path) -> None:
    """get_merged_frame() with events but no places must return events unmodified."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"

    with LocalizerStore(path=db_path) as store:
        _seed_events(store, n=2)

    broker = LocalizerBroker(store_path=db_path)
    result = broker.get_merged_frame()
    assert len(result) >= 2, "Expected events returned even when no places are loaded"


def test_localizer_broker_get_merged_frame_asof_join_ordering(tmp_path: Path) -> None:
    """ASOF JOIN must correctly match events to nearest prior place, not fail on unsorted input."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"
    now = int(time.time())

    # Insert events intentionally out-of-order
    with LocalizerStore(path=db_path) as store:
        events = [
            {
                "source_id": "lastfm",
                "timestamp": now - 3600,  # 1 hour ago
                "label": "ArtistA",
                "sublabel": "TrackA",
                "category": "AlbumA",
                "raw_json": "{}",
                "fetched_at": now,
            },
            {
                "source_id": "lastfm",
                "timestamp": now - 7200,  # 2 hours ago — inserted second (out of order)
                "label": "ArtistB",
                "sublabel": "TrackB",
                "category": "AlbumB",
                "raw_json": "{}",
                "fetched_at": now,
            },
        ]
        store.upsert_events(events)

        places = [
            {
                "source_id": "swarm",
                "timestamp": now - 7500,  # check-in before both events
                "lat": 51.5074,
                "lng": -0.1278,
                "place_name": "Old Place",
                "place_type": "Bar",
                "raw_json": "{}",
                "fetched_at": now,
            },
        ]
        store.upsert_places(places)

    broker = LocalizerBroker(store_path=db_path)
    # Must not raise — ASOF JOIN handles unsorted input gracefully
    result = broker.get_merged_frame()
    assert isinstance(result, pd.DataFrame)
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# is_type_available tests
# ---------------------------------------------------------------------------


def test_localizer_broker_is_type_available_false_when_empty(tmp_path: Path) -> None:
    """is_type_available('what-when') must return False on a fresh empty store."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"
    broker = LocalizerBroker(store_path=db_path)
    assert broker.is_type_available("what-when") is False


def test_localizer_broker_is_type_available_true_after_events(tmp_path: Path) -> None:
    """is_type_available('what-when') must return True once events are in the store."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"

    with LocalizerStore(path=db_path) as store:
        _seed_events(store, n=1)

    broker = LocalizerBroker(store_path=db_path)
    assert broker.is_type_available("what-when") is True


def test_localizer_broker_is_type_available_where_when_with_places(tmp_path: Path) -> None:
    """is_type_available('where-when') must return True once places are in the store."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"

    with LocalizerStore(path=db_path) as store:
        _seed_places(store, n=1)

    broker = LocalizerBroker(store_path=db_path)
    assert broker.is_type_available("where-when") is True


# ---------------------------------------------------------------------------
# available_types property tests
# ---------------------------------------------------------------------------


def test_localizer_broker_available_types_empty_store(tmp_path: Path) -> None:
    """available_types must be an empty list on a fresh store."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"
    broker = LocalizerBroker(store_path=db_path)
    assert broker.available_types == []


def test_localizer_broker_available_types_after_events(tmp_path: Path) -> None:
    """available_types must contain 'what-when' after events are loaded."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"

    with LocalizerStore(path=db_path) as store:
        _seed_events(store, n=1)

    broker = LocalizerBroker(store_path=db_path)
    assert "what-when" in broker.available_types


# ---------------------------------------------------------------------------
# Resource cleanup test (Windows-critical)
# ---------------------------------------------------------------------------


def test_localizer_broker_closes_connection_after_get_merged_frame(tmp_path: Path) -> None:
    """LocalizerBroker must close its DuckDB connection after get_merged_frame().

    On Windows, an unclosed DuckDB connection holds a file lock that prevents
    tmp_path cleanup, causing a PermissionError in pytest teardown.
    """
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"

    with LocalizerStore(path=db_path) as store:
        _seed_events(store, n=1)

    broker = LocalizerBroker(store_path=db_path)
    broker.get_merged_frame()

    # After the call, the broker should not hold an open connection.
    # We verify by opening a second connection to the same file — this would
    # fail or hang if the broker held an exclusive lock.
    try:
        with LocalizerStore(path=db_path) as store2:
            df = store2.query_events()
            assert len(df) >= 1
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"Could not re-open DuckDB after get_merged_frame() — broker may have "
            f"left connection open: {exc}"
        )


def test_localizer_broker_closes_connection_after_get_frame(tmp_path: Path) -> None:
    """LocalizerBroker must close its DuckDB connection after get_frame()."""
    from core.broker import LocalizerBroker

    db_path = tmp_path / "test.duckdb"
    broker = LocalizerBroker(store_path=db_path)
    broker.get_frame("lastfm")

    # Verify re-open works (connection was released)
    try:
        with LocalizerStore(path=db_path) as store2:
            store2.query_events()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"Could not re-open DuckDB after get_frame() — broker may have "
            f"left connection open: {exc}"
        )


# ---------------------------------------------------------------------------
# DataBroker must remain unchanged (regression guard)
# ---------------------------------------------------------------------------


def test_databroker_still_importable() -> None:
    """DataBroker must remain importable from core.broker — no regressions."""
    from core.broker import DataBroker  # noqa: F401

    assert DataBroker is not None


def test_databroker_interface_unchanged() -> None:
    """DataBroker must still expose its original public interface unchanged."""
    from core.broker import DataBroker

    broker = DataBroker()
    assert hasattr(broker, "get_merged_frame")
    assert hasattr(broker, "get_frame")
    assert hasattr(broker, "load")
    assert hasattr(broker, "is_type_available")
    assert hasattr(broker, "available_types")


# ---------------------------------------------------------------------------
# Sidebar toggle tests (_make_broker)
# ---------------------------------------------------------------------------


def test_make_broker_returns_data_broker_when_no_store() -> None:
    """_make_broker() returns DataBroker when ~/.localizer/store.duckdb does not exist."""
    from unittest.mock import MagicMock, patch

    from components.sidebar import _make_broker
    from core.broker import DataBroker

    mock_path = MagicMock()
    mock_path.exists.return_value = False
    with patch("localizer.store.db.LocalizerStore.default_path", return_value=mock_path):
        broker = _make_broker()
    assert isinstance(broker, DataBroker)


def test_make_broker_returns_localizer_broker_when_store_exists() -> None:
    """_make_broker() returns LocalizerBroker when ~/.localizer/store.duckdb exists."""
    from unittest.mock import MagicMock, patch

    from components.sidebar import _make_broker
    from core.broker import LocalizerBroker

    mock_path = MagicMock()
    mock_path.exists.return_value = True
    with patch("localizer.store.db.LocalizerStore.default_path", return_value=mock_path):
        with patch("core.broker.LocalizerBroker") as mock_broker_cls:
            mock_broker_cls.return_value = MagicMock(spec=LocalizerBroker)
            _make_broker()
    assert mock_broker_cls.called
