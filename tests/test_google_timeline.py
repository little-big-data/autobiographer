"""Unit tests for the Google Maps Timeline parser (load_google_timeline)."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from analysis_utils import _WHERE_WHEN_COLUMNS, _parse_latlng, load_google_timeline


def _write_timeline(tmp: str, payload: dict) -> str:
    """Write a Timeline.json payload to a temp dir and return its path."""
    path = Path(tmp) / "Timeline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


# A representative new-format export: labeled frequent place, one visit per
# semantic type, an activity, and a raw-path segment that must be ignored.
_SAMPLE = {
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


class TestParseLatLng(unittest.TestCase):
    """Tests for the _parse_latlng helper."""

    def test_parses_degree_string(self):
        self.assertEqual(_parse_latlng("40.5°, -74.25°"), (40.5, -74.25))

    def test_parses_without_degree_symbol(self):
        self.assertEqual(_parse_latlng("40.5, -74.25"), (40.5, -74.25))

    def test_returns_none_on_empty(self):
        self.assertIsNone(_parse_latlng(""))

    def test_returns_none_on_malformed(self):
        self.assertIsNone(_parse_latlng("not-a-coordinate"))

    def test_returns_none_on_single_value(self):
        self.assertIsNone(_parse_latlng("40.5"))


class TestLoadGoogleTimeline(unittest.TestCase):
    """Tests for the load_google_timeline parser."""

    def setUp(self):
        # Patch offline reverse geocoding so tests are fast and deterministic.
        self._rg_patch = patch(
            "reverse_geocoder.search",
            side_effect=lambda coords, verbose=False: [
                {"name": "TestCity", "admin1": "TestState", "cc": "US"} for _ in coords
            ],
        )
        self._rg_patch.start()
        self.addCleanup(self._rg_patch.stop)

    def _load_sample(self) -> pd.DataFrame:
        with TemporaryDirectory() as tmp:
            return load_google_timeline(_write_timeline(tmp, _SAMPLE))

    def test_returns_expected_columns(self):
        df = self._load_sample()
        self.assertEqual(list(df.columns), _WHERE_WHEN_COLUMNS)

    def test_ignores_timeline_path_segments(self):
        df = self._load_sample()
        # 3 visits + 1 activity; the timelinePath-only segment is dropped.
        self.assertEqual(len(df), 4)

    def test_rows_sorted_by_timestamp(self):
        df = self._load_sample()
        self.assertTrue(df["timestamp"].is_monotonic_increasing)

    def test_visit_timestamp_is_utc_unix(self):
        df = self._load_sample()
        # 08:00 at -05:00 == 13:00 UTC.
        self.assertEqual(df.iloc[0]["timestamp"], _unix("2025-01-01 13:00"))

    def test_visit_coordinates_parsed(self):
        df = self._load_sample()
        self.assertEqual(df.iloc[0]["lat"], 40.0)
        self.assertEqual(df.iloc[0]["lng"], -74.0)

    def test_frequent_place_label_used_when_available(self):
        df = self._load_sample()
        home = df[df["venue_category"] == "home"].iloc[0]
        self.assertEqual(home["venue"], "My Home Base")

    def test_semantic_type_humanized_when_no_label(self):
        df = self._load_sample()
        work = df[df["venue_category"] == "work"].iloc[0]
        self.assertEqual(work["venue"], "Work")

    def test_unknown_semantic_type_humanized(self):
        df = self._load_sample()
        unknown = df[df["venue_category"] == "unknown"].iloc[0]
        self.assertEqual(unknown["venue"], "Unknown place")

    def test_activity_row_uses_start_point(self):
        df = self._load_sample()
        walk = df[df["venue_category"] == "activity:walking"].iloc[0]
        self.assertEqual(walk["venue"], "Walking")
        self.assertEqual(walk["lat"], 43.0)
        self.assertEqual(walk["lng"], -77.0)

    def test_explicit_offset_used(self):
        df = self._load_sample()
        self.assertEqual(df.iloc[0]["offset"], -300)

    def test_offset_falls_back_to_rfc3339(self):
        df = self._load_sample()
        # The WORK visit has no explicit offset field; -05:00 -> -300 minutes.
        work = df[df["venue_category"] == "work"].iloc[0]
        self.assertEqual(work["offset"], -300)

    def test_reverse_geocode_fills_location(self):
        df = self._load_sample()
        self.assertTrue((df["city"] == "TestCity").all())
        self.assertTrue((df["country"] == "US").all())

    def test_missing_file_returns_empty_frame(self):
        df = load_google_timeline("does/not/exist.json")
        self.assertTrue(df.empty)
        self.assertEqual(list(df.columns), _WHERE_WHEN_COLUMNS)

    def test_empty_segments_returns_empty_frame(self):
        with TemporaryDirectory() as tmp:
            df = load_google_timeline(_write_timeline(tmp, {"semanticSegments": []}))
        self.assertTrue(df.empty)
        self.assertEqual(list(df.columns), _WHERE_WHEN_COLUMNS)

    def test_legacy_records_format_raises(self):
        with TemporaryDirectory() as tmp:
            path = _write_timeline(tmp, {"locations": [{"latitudeE7": 400000000}]})
            with self.assertRaises(ValueError) as ctx:
                load_google_timeline(path)
        self.assertIn("semanticSegments", str(ctx.exception))

    def test_legacy_semantic_format_raises(self):
        with TemporaryDirectory() as tmp:
            path = _write_timeline(tmp, {"timelineObjects": [{"placeVisit": {}}]})
            with self.assertRaises(ValueError):
                load_google_timeline(path)


if __name__ == "__main__":
    unittest.main()
