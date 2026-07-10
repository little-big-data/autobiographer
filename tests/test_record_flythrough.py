import os
import shutil
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd
import pydeck as pdk

from pages.places import _build_flythrough_filename
from record_flythrough import create_recording_assets, filter_data


class TestRecordFlythrough(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="record_flythrough_test_")
        self.test_csv = os.path.join(self.test_dir, "test_tracks.csv")

        self.df = pd.DataFrame(
            {
                "artist": ["Artist A", "Artist B", "Artist A"],
                "album": ["Album 1", "Album 2", "Album 1"],
                "track": ["Track 1", "Track 2", "Track 3"],
                "timestamp": [1610000000, 1610000100, 1610000200],
                "date_text": ["2021-01-01 10:00", "2021-01-01 10:01", "2021-01-01 11:02"],
                "lat": [41.0, 42.0, 41.0],
                "lng": [-87.0, -88.0, -87.0],
                "city": ["Reykjavik", "Perth", "Reykjavik"],
            }
        )
        self.df["date_text"] = pd.to_datetime(self.df["date_text"])
        self.df.to_csv(self.test_csv, index=False)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_filter_data_artist(self):
        filtered = filter_data(self.df, artist="Artist A")
        self.assertEqual(len(filtered), 2)
        self.assertTrue((filtered["artist"] == "Artist A").all())

    def test_filter_data_dates(self):
        # All tracks are in 2021-01-01
        filtered = filter_data(self.df, start_date="2021-01-01 10:30")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["track"], "Track 3")

    def test_create_recording_assets_success(self):
        deck, keyframes = create_recording_assets(self.test_csv)
        self.assertIsNotNone(deck)
        self.assertIsInstance(deck, pdk.Deck)
        self.assertIsNotNone(keyframes)
        self.assertTrue(len(keyframes) >= 2)

    @patch("analysis_utils.load_swarm_data")
    @patch("analysis_utils.apply_swarm_offsets")
    @patch("os.path.exists")
    def test_create_recording_assets_geocoding_trigger(
        self, mock_exists, mock_apply, mock_load_swarm
    ):
        # Create CSV without geodata
        no_geo_csv = os.path.join(self.test_dir, "no_geo.csv")
        self.df.drop(columns=["lat", "lng", "city"]).to_csv(no_geo_csv, index=False)

        mock_load_swarm.return_value = pd.DataFrame({"timestamp": [1]})
        mock_apply.return_value = self.df  # Return the one with geodata

        # Configure mock_exists to return True for the CSV and the swarm_dir
        def exists_side_effect(path):
            if path in [no_geo_csv, "mock_swarm", "default_assumptions.json"]:
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        create_recording_assets(no_geo_csv, swarm_dir="mock_swarm")

        self.assertTrue(mock_load_swarm.called)
        self.assertTrue(mock_apply.called)

    def test_setup_uses_unique_per_invocation_dir(self):
        """self.test_dir must be a unique per-invocation path, not a
        hardcoded shared path, so parallel pytest-xdist workers running
        different test methods of this TestCase never race on the same
        directory (handoff.md Subtask 1)."""
        other = TestRecordFlythrough("test_filter_data_artist")
        other.setUp()
        try:
            self.assertNotEqual(
                self.test_dir,
                other.test_dir,
                "self.test_dir must be a unique per-invocation path, not a "
                "shared hardcoded path reused across invocations",
            )
            # tearing down one invocation's fixtures must never remove the
            # other invocation's still-in-use fixtures.
            other.tearDown()
            self.assertTrue(
                os.path.exists(self.test_dir),
                "tearing down a different TestRecordFlythrough invocation "
                "must not delete this invocation's still-in-use test_dir",
            )
        finally:
            if os.path.exists(other.test_dir):
                shutil.rmtree(other.test_dir)


class TestBuildFlythroughFilename(unittest.TestCase):
    def test_all_artist_no_dates(self) -> None:
        name = _build_flythrough_filename("All", [])
        self.assertTrue(name.startswith("flythrough_"))
        self.assertTrue(name.endswith(".mp4"))
        # No artist segment, no date segment
        parts = name[len("flythrough_") : -len(".mp4")].split("_")
        # Only timestamp: YYYYMMDD + HHMMSS = 2 parts
        self.assertEqual(len(parts), 2)

    def test_specific_artist_included(self) -> None:
        name = _build_flythrough_filename("Radiohead", [])
        self.assertIn("Radiohead", name)

    def test_artist_sanitised(self) -> None:
        name = _build_flythrough_filename("AC/DC & Friends!", [])
        self.assertNotIn("/", name)
        self.assertNotIn("&", name)
        self.assertNotIn("!", name)

    def test_date_range_included(self) -> None:
        name = _build_flythrough_filename("All", [date(2022, 1, 1), date(2022, 12, 31)])
        self.assertIn("20220101", name)
        self.assertIn("20221231", name)

    def test_artist_and_dates(self) -> None:
        name = _build_flythrough_filename("Björk", [date(2023, 6, 1), date(2023, 6, 30)])
        self.assertIn("Bj_rk", name)
        self.assertIn("20230601", name)
        self.assertIn("20230630", name)


if __name__ == "__main__":
    unittest.main()
