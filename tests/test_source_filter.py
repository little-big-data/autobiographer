"""Failing tests for Subtask 3: shared pure source-filter helper (core/source_filter.py).

All tests here are expected to FAIL until the coder implements, in a new module
`core/source_filter.py`:
  - source_label(source_id: str) -> str
  - get_source_options(swarm_df: pd.DataFrame | None) -> list[str]
  - filter_by_source(swarm_df: pd.DataFrame | None, selected_label: str) -> pd.DataFrame | None

This module is the single place source->label mapping and filtering logic lives, so both
consuming pages (Subtasks 4/5) agree on behavior. It must stay pure DataFrame-in/DataFrame-out
logic with no Streamlit/DuckDB/LocalizerBroker coupling, mirroring core/localizer_frames.py's
existing convention.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.source_filter import filter_by_source, get_source_options, source_label

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mixed_source_fixture() -> pd.DataFrame:
    """Four-row swarm_df-shaped fixture: 2 swarm rows, 2 google_timeline rows.

    Each row carries a distinguishing city/lat/lng so filtered-output assertions can check
    presence/absence of specific values, not just row counts.
    """
    return pd.DataFrame(
        {
            "timestamp": [1609495200, 1609498800, 1609502400, 1609505800],
            "city": ["Brooklyn", "Paris", "Home", "Work"],
            "lat": [40.6782, 48.8566, 40.7128, 40.7306],
            "lng": [-73.9442, 2.3522, -74.0060, -73.9352],
            "source_id": ["swarm", "google_timeline", "swarm", "google_timeline"],
        }
    )


def _no_source_id_fixture() -> pd.DataFrame:
    """A swarm_df-shaped frame that lacks a source_id column entirely (legacy edge case)."""
    return pd.DataFrame(
        {
            "timestamp": [1609495200, 1609498800],
            "city": ["Brooklyn", "Paris"],
            "lat": [40.6782, 48.8566],
            "lng": [-73.9442, 2.3522],
        }
    )


# ---------------------------------------------------------------------------
# source_label()
# ---------------------------------------------------------------------------


def test_source_label_known_swarm():
    assert source_label("swarm") == "Swarm"


def test_source_label_known_google_timeline():
    assert source_label("google_timeline") == "Google Timeline"


def test_source_label_unknown_humanized_fallback_first_example():
    """An unrecognized source_id falls back to a humanized label, not a crash or raw string."""
    assert source_label("some_future_plugin") == "Some Future Plugin"


def test_source_label_unknown_humanized_fallback_second_example():
    """A second, differently-shaped unknown source_id proves the formula generalizes."""
    assert source_label("custom_data_source") == "Custom Data Source"


# ---------------------------------------------------------------------------
# get_source_options()
# ---------------------------------------------------------------------------


def test_get_source_options_none_input_returns_all_only():
    assert get_source_options(None) == ["All"]


def test_get_source_options_empty_dataframe_returns_all_only():
    empty_df = pd.DataFrame(columns=["timestamp", "city", "lat", "lng", "source_id"])
    assert get_source_options(empty_df) == ["All"]


def test_get_source_options_missing_source_id_column_returns_all_only():
    assert get_source_options(_no_source_id_fixture()) == ["All"]


def test_get_source_options_mixed_sources_sorted_after_all():
    df = pd.DataFrame({"source_id": ["swarm", "google_timeline", "swarm"]})
    assert get_source_options(df) == ["All", "Google Timeline", "Swarm"]


def test_get_source_options_single_distinct_source_value():
    """A single-distinct-value source_id column still returns All plus that one label."""
    df = pd.DataFrame({"source_id": ["swarm", "swarm", "swarm"]})
    assert get_source_options(df) == ["All", "Swarm"]


# ---------------------------------------------------------------------------
# filter_by_source()
# ---------------------------------------------------------------------------


def test_filter_by_source_none_input_returns_none():
    assert filter_by_source(None, "Swarm") is None


def test_filter_by_source_empty_dataframe_returns_unchanged():
    empty_df = pd.DataFrame(columns=["timestamp", "city", "lat", "lng", "source_id"])
    result = filter_by_source(empty_df, "Swarm")
    assert result is not None
    assert len(result) == 0
    assert list(result.columns) == list(empty_df.columns)


def test_filter_by_source_all_label_mixed_source_row_count_unchanged():
    df = _mixed_source_fixture()
    result = filter_by_source(df, "All")
    assert len(result) == len(df)


def test_filter_by_source_all_label_no_source_id_row_count_unchanged():
    df = _no_source_id_fixture()
    result = filter_by_source(df, "All")
    assert len(result) == len(df)


def test_filter_by_source_missing_source_id_column_is_graceful_passthrough():
    """Even a non-'All' label must not raise or drop rows when source_id is absent."""
    df = _no_source_id_fixture()
    result = filter_by_source(df, "Swarm")
    assert len(result) == len(df)
    assert list(result.columns) == list(df.columns)


def test_filter_by_source_swarm_label_returns_only_swarm_rows_row_for_row():
    df = _mixed_source_fixture()
    result = filter_by_source(df, "Swarm")

    assert len(result) == 2
    assert set(result["city"]) == {"Brooklyn", "Home"}
    assert set(result["source_id"]) == {"swarm"}

    rows = result.reset_index(drop=True)
    brooklyn_row = rows[rows["city"] == "Brooklyn"].iloc[0]
    assert brooklyn_row["lat"] == 40.6782
    assert brooklyn_row["lng"] == -73.9442

    home_row = rows[rows["city"] == "Home"].iloc[0]
    assert home_row["lat"] == 40.7128
    assert home_row["lng"] == -74.0060

    # Google-Timeline-only values must be absent.
    assert "Paris" not in result["city"].values
    assert "Work" not in result["city"].values


def test_filter_by_source_google_timeline_label_returns_only_those_rows():
    df = _mixed_source_fixture()
    result = filter_by_source(df, "Google Timeline")

    assert len(result) == 2
    assert set(result["city"]) == {"Paris", "Work"}
    assert set(result["source_id"]) == {"google_timeline"}
    assert "Brooklyn" not in result["city"].values
    assert "Home" not in result["city"].values


def test_filter_by_source_nonexistent_label_returns_empty_but_correctly_shaped():
    df = _mixed_source_fixture()
    result = filter_by_source(df, "Nonexistent Label")

    assert result is not None
    assert len(result) == 0
    assert list(result.columns) == list(df.columns)


def test_filter_by_source_result_has_reset_index():
    df = _mixed_source_fixture()
    result = filter_by_source(df, "Swarm")

    assert list(result.index) == list(range(len(result)))


def test_filter_by_source_does_not_mutate_input_in_place():
    df = _mixed_source_fixture()
    original_len = len(df)
    original_cities = set(df["city"])

    filter_by_source(df, "Swarm")

    assert len(df) == original_len
    assert set(df["city"]) == original_cities


# ---------------------------------------------------------------------------
# Module purity: no Streamlit / DuckDB / LocalizerBroker coupling.
# ---------------------------------------------------------------------------


def test_source_filter_module_has_no_forbidden_imports():
    """core/source_filter.py must stay a pure helper: no streamlit/duckdb/broker coupling.

    Source-inspection check (not import-time), so it fails cleanly (FileNotFoundError)
    before the module exists and keeps working afterward regardless of implementation.
    """
    module_path = Path(__file__).resolve().parents[1] / "core" / "source_filter.py"
    source = module_path.read_text(encoding="utf-8")

    assert "streamlit" not in source
    assert "duckdb" not in source
    assert "LocalizerBroker" not in source
