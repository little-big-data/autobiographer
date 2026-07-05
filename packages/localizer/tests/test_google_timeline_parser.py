"""Failing tests for Subtask 1: the ported Google Timeline parser module.

All tests here are expected to FAIL with ``ModuleNotFoundError`` until the
coder creates:
  - packages/localizer/src/localizer/plugins/google_timeline/parser.py

This module is a verbatim (behavior-identical) port of
``analysis_utils.load_google_timeline()`` and its four private dependents
(``_TIMELINE_SEMANTIC_LABELS``, ``_WHERE_WHEN_COLUMNS``, ``_parse_latlng``,
``_timeline_offset_minutes``). Test fixtures and helpers here are copy-adapted
from ``tests/test_google_timeline.py`` (23 tests) so the two suites stay easy
to diff against each other and prove the port is byte-for-byte behavior
identical, modulo the ``Optional[X]`` -> ``X | None`` style change.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
from localizer.plugins.google_timeline.parser import (
    _WHERE_WHEN_COLUMNS,
    _parse_latlng,
    load_google_timeline,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers — copy-adapted from tests/test_google_timeline.py so
# the two suites are easy to diff against each other.
# ---------------------------------------------------------------------------


def _write_timeline(tmp_path: Path, payload: dict[str, Any]) -> str:
    """Write a Timeline.json payload to *tmp_path* and return its path."""
    path = tmp_path / "Timeline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


# A representative new-format export: labeled frequent place, one visit per
# semantic type, an activity, and a raw-path segment that must be ignored.
_SAMPLE: dict[str, Any] = {
    "userLocationProfile": {
        "frequentPlaces": [
            {"placeId": "PID_HOME", "placeLocation": "40.0°, -74.0°", "label": "My Home Base"}
        ]
    },
    "semanticSegments": [
        {
            "startTime": "2025-01-01T08:00:00.000-05:00",
            "endTime": "2025-01-01T09:00:00.000-05:00",
            "startTimeTimezoneUtcOffsetMinutes": -300,
            "visit": {
                "topCandidate": {
                    "placeId": "PID_HOME",
                    "semanticType": "HOME",
                    "placeLocation": {"latLng": "40.0°, -74.0°"},
                }
            },
        },
        {
            # No explicit offset field — must fall back to the RFC3339 offset.
            "startTime": "2025-01-02T09:00:00.000-05:00",
            "endTime": "2025-01-02T10:00:00.000-05:00",
            "visit": {
                "topCandidate": {
                    "placeId": "PID_UNLABELED",
                    "semanticType": "WORK",
                    "placeLocation": {"latLng": "41.0°, -75.0°"},
                }
            },
        },
        {
            "startTime": "2025-01-03T10:00:00.000-05:00",
            "endTime": "2025-01-03T11:00:00.000-05:00",
            "startTimeTimezoneUtcOffsetMinutes": -300,
            "visit": {
                "topCandidate": {
                    "placeId": "PID_OTHER",
                    "semanticType": "UNKNOWN",
                    "placeLocation": {"latLng": "42.0°, -76.0°"},
                }
            },
        },
        {
            "startTime": "2025-01-04T11:00:00.000-05:00",
            "endTime": "2025-01-04T12:00:00.000-05:00",
            "startTimeTimezoneUtcOffsetMinutes": -300,
            "activity": {
                "start": {"latLng": "43.0°, -77.0°"},
                "end": {"latLng": "43.5°, -77.5°"},
                "topCandidate": {"type": "WALKING"},
            },
        },
        {
            "startTime": "2025-01-05T12:00:00.000-05:00",
            "endTime": "2025-01-05T13:00:00.000-05:00",
            "timelinePath": [{"point": "44.0°, -78.0°", "time": "2025-01-05T12:30:00.000-05:00"}],
        },
    ],
}


def _unix(iso_utc: str) -> int:
    """Return the unix timestamp for a naive UTC 'YYYY-MM-DD HH:MM' string."""
    dt = datetime.strptime(iso_utc, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


@pytest.fixture(autouse=True)
def _stub_reverse_geocoder():
    """Stub the optional offline reverse_geocoder dependency for every test.

    load_google_timeline() calls reverse_geocoder.search() to fill city/
    state/country columns. Stubbing keeps tests fast and deterministic and
    avoids a first-run dataset download, mirroring the setUp() patch in
    tests/test_google_timeline.py and the autouse fixture in
    test_google_timeline_plugin.py.
    """
    with patch(
        "reverse_geocoder.search",
        side_effect=lambda coords, verbose=False: [
            {"name": "TestCity", "admin1": "TestState", "cc": "US"} for _ in coords
        ],
    ):
        yield


def _load_sample(tmp_path: Path) -> pd.DataFrame:
    return load_google_timeline(_write_timeline(tmp_path, _SAMPLE))


# ---------------------------------------------------------------------------
# _parse_latlng
# ---------------------------------------------------------------------------


def test_parse_latlng_parses_degree_string() -> None:
    assert _parse_latlng("40.5°, -74.25°") == (40.5, -74.25)


def test_parse_latlng_parses_without_degree_symbol() -> None:
    assert _parse_latlng("40.5, -74.25") == (40.5, -74.25)


def test_parse_latlng_returns_none_on_empty() -> None:
    assert _parse_latlng("") is None


def test_parse_latlng_returns_none_on_malformed() -> None:
    assert _parse_latlng("not-a-coordinate") is None


def test_parse_latlng_returns_none_on_single_value() -> None:
    assert _parse_latlng("40.5") is None


# ---------------------------------------------------------------------------
# load_google_timeline
# ---------------------------------------------------------------------------


def test_returns_expected_columns(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    assert list(df.columns) == _WHERE_WHEN_COLUMNS


def test_ignores_timeline_path_segments(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    # 3 visits + 1 activity; the timelinePath-only segment is dropped.
    assert len(df) == 4


def test_rows_sorted_by_timestamp(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    assert df["timestamp"].is_monotonic_increasing


def test_visit_timestamp_is_utc_unix(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    # 08:00 at -05:00 == 13:00 UTC.
    assert df.iloc[0]["timestamp"] == _unix("2025-01-01 13:00")


def test_visit_coordinates_parsed(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    assert df.iloc[0]["lat"] == 40.0
    assert df.iloc[0]["lng"] == -74.0


def test_frequent_place_label_used_when_available(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    home = df[df["venue_category"] == "home"].iloc[0]
    assert home["venue"] == "My Home Base"


def test_semantic_type_humanized_when_no_label(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    work = df[df["venue_category"] == "work"].iloc[0]
    assert work["venue"] == "Work"


def test_unknown_semantic_type_humanized(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    unknown = df[df["venue_category"] == "unknown"].iloc[0]
    assert unknown["venue"] == "Unknown place"


def test_activity_row_uses_start_point(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    walk = df[df["venue_category"] == "activity:walking"].iloc[0]
    assert walk["venue"] == "Walking"
    assert walk["lat"] == 43.0
    assert walk["lng"] == -77.0


def test_activity_venue_category_has_activity_prefix(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    activity_rows = df[df["venue_category"].str.startswith("activity:")]
    assert len(activity_rows) == 1
    assert activity_rows.iloc[0]["venue_category"] == "activity:walking"


def test_explicit_offset_used(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    assert df.iloc[0]["offset"] == -300


def test_offset_falls_back_to_rfc3339(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    # The WORK visit has no explicit offset field; -05:00 -> -300 minutes.
    work = df[df["venue_category"] == "work"].iloc[0]
    assert work["offset"] == -300


def test_reverse_geocode_fills_location(tmp_path: Path) -> None:
    df = _load_sample(tmp_path)
    assert (df["city"] == "TestCity").all()
    assert (df["country"] == "US").all()


def test_missing_file_returns_empty_frame() -> None:
    df = load_google_timeline("does/not/exist.json")
    assert df.empty
    assert list(df.columns) == _WHERE_WHEN_COLUMNS


def test_empty_segments_returns_empty_frame(tmp_path: Path) -> None:
    df = load_google_timeline(_write_timeline(tmp_path, {"semanticSegments": []}))
    assert df.empty
    assert list(df.columns) == _WHERE_WHEN_COLUMNS


def test_legacy_records_format_raises(tmp_path: Path) -> None:
    path = _write_timeline(tmp_path, {"locations": [{"latitudeE7": 400000000}]})
    with pytest.raises(ValueError, match="semanticSegments"):
        load_google_timeline(path)


def test_legacy_semantic_format_raises(tmp_path: Path) -> None:
    path = _write_timeline(tmp_path, {"timelineObjects": [{"placeVisit": {}}]})
    with pytest.raises(ValueError):
        load_google_timeline(path)


def test_dedupes_segments_sharing_the_same_timestamp(tmp_path: Path) -> None:
    """Two segments with an identical startTime collapse to a single row."""
    payload = {
        "semanticSegments": [
            {
                "startTime": "2025-01-01T08:00:00.000-05:00",
                "endTime": "2025-01-01T09:00:00.000-05:00",
                "startTimeTimezoneUtcOffsetMinutes": -300,
                "visit": {
                    "topCandidate": {
                        "placeId": "PID_A",
                        "semanticType": "HOME",
                        "placeLocation": {"latLng": "40.0°, -74.0°"},
                    }
                },
            },
            {
                # Same startTime as above -> must be deduped to one row.
                "startTime": "2025-01-01T08:00:00.000-05:00",
                "endTime": "2025-01-01T09:30:00.000-05:00",
                "startTimeTimezoneUtcOffsetMinutes": -300,
                "visit": {
                    "topCandidate": {
                        "placeId": "PID_B",
                        "semanticType": "WORK",
                        "placeLocation": {"latLng": "41.0°, -75.0°"},
                    }
                },
            },
        ],
    }
    df = load_google_timeline(_write_timeline(tmp_path, payload))
    assert len(df) == 1
