"""Failing tests for Subtask 2: pure column-shape adapters in core/localizer_frames.py.

All tests here are expected to FAIL until the coder implements:
  - events_to_lastfm_frame(events_df: pd.DataFrame) -> pd.DataFrame
  - places_to_swarm_frame(places_df: pd.DataFrame) -> pd.DataFrame

in a new module `core/localizer_frames.py`.

This subtask is flagged as the riskiest in the whole plan: a wrong column rename or a
silently-swapped city/venue assignment would not raise any exception anywhere downstream —
pages would just render an empty or mislabeled map. Every test below asserts on actual
values at specific row indices, not merely on column-set equality.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.localizer_frames import events_to_lastfm_frame, places_to_swarm_frame

# ---------------------------------------------------------------------------
# Expected column shapes (must match handoff.md's Subtask 2 acceptance criteria
# and analysis_utils.py::load_swarm_data()'s empty-input column declaration
# exactly, order included).
# ---------------------------------------------------------------------------
LASTFM_COLUMNS = ["timestamp", "date_text", "artist", "track", "album", "source_id"]
SWARM_COLUMNS = [
    "timestamp",
    "offset",
    "city",
    "state",
    "country",
    "venue",
    "venue_category",
    "lat",
    "lng",
    "event_category",
    "shout",
]


# ---------------------------------------------------------------------------
# events_to_lastfm_frame()
# ---------------------------------------------------------------------------


def _events_fixture() -> pd.DataFrame:
    """Three-row events fixture with a mixed source_id to prove passthrough."""
    return pd.DataFrame(
        {
            "timestamp": [1609495200, 1609498800, 1609502400],
            "label": ["Radiohead", "Boards of Canada", "Aphex Twin"],
            "sublabel": ["Idioteque", "Roygbiv", "Windowlicker"],
            "category": [
                "Kid A",
                "Music Has the Right to Children",
                "Windowlicker EP",
            ],
            "source_id": ["lastfm", "lastfm", "last_fm_import"],
        }
    )


def test_events_to_lastfm_frame_renames_columns_with_row_level_values():
    """label/sublabel/category rename to artist/track/album, values line up row-for-row."""
    result = events_to_lastfm_frame(_events_fixture())

    assert list(result.columns) == LASTFM_COLUMNS
    assert len(result) == 3

    assert result.iloc[0]["artist"] == "Radiohead"
    assert result.iloc[0]["track"] == "Idioteque"
    assert result.iloc[0]["album"] == "Kid A"

    assert result.iloc[1]["artist"] == "Boards of Canada"
    assert result.iloc[1]["track"] == "Roygbiv"
    assert result.iloc[1]["album"] == "Music Has the Right to Children"

    assert result.iloc[2]["artist"] == "Aphex Twin"
    assert result.iloc[2]["track"] == "Windowlicker"
    assert result.iloc[2]["album"] == "Windowlicker EP"


def test_events_to_lastfm_frame_preserves_timestamp_and_mixed_source_id():
    """timestamp and source_id pass through unchanged, including a differing source_id."""
    result = events_to_lastfm_frame(_events_fixture())

    assert result.iloc[0]["timestamp"] == 1609495200
    assert result.iloc[1]["timestamp"] == 1609498800
    assert result.iloc[2]["timestamp"] == 1609502400

    assert result.iloc[0]["source_id"] == "lastfm"
    assert result.iloc[2]["source_id"] == "last_fm_import"


def test_events_to_lastfm_frame_date_text_dtype_and_value():
    """date_text is a naive datetime64[ns] column computed via pd.to_datetime(unit='s')."""
    result = events_to_lastfm_frame(_events_fixture())

    # Naive datetime64[ns] - no timezone, matching load_listening_data()'s convention.
    assert pd.api.types.is_datetime64_ns_dtype(result["date_text"])
    assert result["date_text"].dt.tz is None

    # Cross-checked against a pd.to_datetime(..., unit="s") reference value, not against
    # load_listening_data() itself (there is no CSV involved here).
    expected_ts0 = pd.to_datetime(1609495200, unit="s")
    expected_ts1 = pd.to_datetime(1609498800, unit="s")
    expected_ts2 = pd.to_datetime(1609502400, unit="s")

    assert result.iloc[0]["date_text"] == expected_ts0
    assert result.iloc[1]["date_text"] == expected_ts1
    assert result.iloc[2]["date_text"] == expected_ts2


def test_events_to_lastfm_frame_single_row():
    """A single-row input produces a single-row output with correct values."""
    single = pd.DataFrame(
        {
            "timestamp": [1700000000],
            "label": ["Solo Artist"],
            "sublabel": ["Solo Track"],
            "category": ["Solo Album"],
            "source_id": ["google_timeline_music"],
        }
    )
    result = events_to_lastfm_frame(single)

    assert list(result.columns) == LASTFM_COLUMNS
    assert len(result) == 1
    assert result.iloc[0]["artist"] == "Solo Artist"
    assert result.iloc[0]["track"] == "Solo Track"
    assert result.iloc[0]["album"] == "Solo Album"
    assert result.iloc[0]["source_id"] == "google_timeline_music"
    assert result.iloc[0]["date_text"] == pd.to_datetime(1700000000, unit="s")


def test_events_to_lastfm_frame_empty_input_exact_columns():
    """Empty input returns an empty frame with the exact declared column list."""
    empty_input = pd.DataFrame(columns=["timestamp", "label", "sublabel", "category", "source_id"])
    result = events_to_lastfm_frame(empty_input)

    assert list(result.columns) == LASTFM_COLUMNS
    assert len(result) == 0


# ---------------------------------------------------------------------------
# places_to_swarm_frame()
# ---------------------------------------------------------------------------


def _places_fixture_out_of_order() -> pd.DataFrame:
    """Three-row places fixture, deliberately non-monotonic on timestamp.

    Row order as given: latest, earliest, middle. Includes an empty-string
    place_name (not missing/NaN) to prove no accidental NaN/None substitution,
    and mixed source_id values (swarm + google_timeline) to prove the adapter
    does not care about source lineage.
    """
    return pd.DataFrame(
        {
            "timestamp": [1609502400, 1609495200, 1609498800],
            "lat": [51.50735, 40.712776, 48.856613],
            "lng": [-0.12776, -74.005974, 2.352222],
            "place_name": ["Home", "Joe's Pizza", ""],
            "place_type": ["residence", "restaurant", "unknown"],
            "source_id": ["google_timeline", "swarm", "google_timeline"],
        }
    )


def test_places_to_swarm_frame_renames_and_fills_defaults():
    """city and venue both equal place_name; venue_category equals place_type; defaults filled."""
    result = places_to_swarm_frame(_places_fixture_out_of_order())

    assert set(result.columns) == set(SWARM_COLUMNS)
    assert len(result) == 3
    assert "source_id" not in result.columns
    assert "place_name" not in result.columns
    assert "place_type" not in result.columns

    for _, row in result.iterrows():
        assert row["state"] == ""
        assert row["country"] == ""
        assert row["offset"] == 0
        assert row["city"] == row["venue"]


def test_places_to_swarm_frame_sorted_ascending_by_timestamp():
    """Output is sorted ascending by timestamp even though the input is out of order."""
    result = places_to_swarm_frame(_places_fixture_out_of_order())

    timestamps = result["timestamp"].tolist()
    assert timestamps == sorted(timestamps)
    assert timestamps == [1609495200, 1609498800, 1609502400]

    # Row-for-row correctness after the reorder: earliest row is Joe's Pizza (swarm),
    # middle row is the empty-place_name row, latest row is Home.
    rows = result.reset_index(drop=True)
    assert rows.iloc[0]["city"] == "Joe's Pizza"
    assert rows.iloc[0]["venue"] == "Joe's Pizza"
    assert rows.iloc[0]["venue_category"] == "restaurant"

    assert rows.iloc[1]["city"] == ""
    assert rows.iloc[1]["venue"] == ""
    assert rows.iloc[1]["venue_category"] == "unknown"

    assert rows.iloc[2]["city"] == "Home"
    assert rows.iloc[2]["venue"] == "Home"
    assert rows.iloc[2]["venue_category"] == "residence"


def test_places_to_swarm_frame_empty_place_name_not_coerced_to_nan():
    """An explicit empty-string place_name must survive as '', never NaN/None."""
    result = places_to_swarm_frame(_places_fixture_out_of_order())
    empty_row = result[result["venue_category"] == "unknown"].iloc[0]

    assert pd.notna(empty_row["city"])
    assert pd.notna(empty_row["venue"])
    assert empty_row["city"] == ""
    assert empty_row["venue"] == ""


def test_places_to_swarm_frame_preserves_lat_lng_exact_precision():
    """lat/lng survive the rename with exact float precision (no dtype coercion)."""
    result = places_to_swarm_frame(_places_fixture_out_of_order())
    rows = result.reset_index(drop=True)

    # Sorted order: Joe's Pizza (40.712776/-74.005974), "" (48.856613/2.352222),
    # Home (51.50735/-0.12776).
    assert rows.iloc[0]["lat"] == 40.712776
    assert rows.iloc[0]["lng"] == -74.005974
    assert rows.iloc[1]["lat"] == 48.856613
    assert rows.iloc[1]["lng"] == 2.352222
    assert rows.iloc[2]["lat"] == 51.50735
    assert rows.iloc[2]["lng"] == -0.12776


def test_places_to_swarm_frame_single_row():
    """A single-row input produces a single-row output with correct values."""
    single = pd.DataFrame(
        {
            "timestamp": [1650000000],
            "lat": [35.6895],
            "lng": [139.6917],
            "place_name": ["Shibuya Crossing"],
            "place_type": ["landmark"],
            "source_id": ["google_timeline"],
        }
    )
    result = places_to_swarm_frame(single)

    assert set(result.columns) == set(SWARM_COLUMNS)
    assert len(result) == 1
    assert result.iloc[0]["city"] == "Shibuya Crossing"
    assert result.iloc[0]["venue"] == "Shibuya Crossing"
    assert result.iloc[0]["venue_category"] == "landmark"
    assert result.iloc[0]["lat"] == 35.6895
    assert result.iloc[0]["lng"] == 139.6917
    assert result.iloc[0]["state"] == ""
    assert result.iloc[0]["country"] == ""
    assert result.iloc[0]["offset"] == 0


def test_places_to_swarm_frame_empty_input_exact_columns():
    """Empty input returns an empty frame with exactly load_swarm_data()'s declared columns."""
    empty_input = pd.DataFrame(
        columns=["timestamp", "lat", "lng", "place_name", "place_type", "source_id"]
    )
    result = places_to_swarm_frame(empty_input)

    assert list(result.columns) == SWARM_COLUMNS
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Module purity: no Streamlit / DuckDB / localizer.store.db coupling.
# ---------------------------------------------------------------------------


def test_localizer_frames_module_has_no_forbidden_imports():
    """core/localizer_frames.py must stay a pure adapter: no streamlit/duckdb/store coupling.

    This is a source-inspection check rather than an import-time check, so it also fails
    cleanly (FileNotFoundError) before the module exists, and will keep working after the
    module exists regardless of how its functions are implemented.
    """
    module_path = Path(__file__).resolve().parents[1] / "core" / "localizer_frames.py"
    source = module_path.read_text(encoding="utf-8")

    assert "streamlit" not in source
    assert "duckdb" not in source
    assert "localizer.store.db" not in source
