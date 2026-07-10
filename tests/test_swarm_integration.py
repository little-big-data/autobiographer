import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from analysis_utils import apply_location_context, load_swarm_data


class TestSwarmIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

        # Create a mock Swarm checkins file
        self.swarm_data = {
            "items": [
                {
                    "createdAt": "2026-01-01 12:00:00.000000",
                    "timeZoneOffset": 540,  # JST (UTC+9)
                    "venue": {"name": "Ramen Shop", "location": {"city": "Tokyo"}},
                    "lat": 35.6762,
                    "lng": 139.6503,
                },
                {
                    "createdAt": "2026-01-02 12:00:00.000000",
                    "timeZoneOffset": 660,  # AEDT (UTC+11)
                    "venue": {"name": "Opera House", "location": {"city": "Sydney"}},
                    "lat": -33.8568,
                    "lng": 151.2153,
                },
            ]
        }

        with open(os.path.join(self.test_dir, "checkins1.json"), "w") as f:
            json.dump(self.swarm_data, f)

        # Mock assumptions
        self.assumptions = {
            "defaults": {
                "city": "Reykjavik, IS",
                "lat": 64.1265,
                "lng": -21.8174,
                "timezone": "Atlantic/Reykjavik",
            }
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_load_swarm_data(self):
        df = load_swarm_data(self.test_dir)
        self.assertEqual(len(df), 2)
        self.assertIn("offset", df.columns)
        self.assertEqual(df.iloc[0]["city"], "Tokyo")
        self.assertEqual(df.iloc[1]["city"], "Sydney")
        self.assertEqual(df.iloc[0]["offset"], 540)

    def test_apply_location_context(self):
        swarm_df = load_swarm_data(self.test_dir)

        # Last.fm tracks in UTC
        tracks = [
            # 1 hour after first checkin (2026-01-01 12:00 UTC)
            {
                "timestamp": int(pd.to_datetime("2026-01-01 13:00:00", utc=True).timestamp()),
                "date_text": "2026-01-01 13:00:00",
            },
            # 1 hour after second checkin (2026-01-02 12:00 UTC)
            {
                "timestamp": int(pd.to_datetime("2026-01-02 13:00:00", utc=True).timestamp()),
                "date_text": "2026-01-02 13:00:00",
            },
        ]
        lastfm_df = pd.DataFrame(tracks)
        lastfm_df["date_text"] = pd.to_datetime(lastfm_df["date_text"])

        adjusted_df = apply_location_context(lastfm_df, swarm_df, self.assumptions)

        # Check first track: 13:00 UTC + 9 hours (JST) = 22:00
        self.assertEqual(adjusted_df.iloc[0]["date_text"].hour, 22)
        self.assertEqual(adjusted_df.iloc[0]["city"], "Tokyo")

        # Check second track: 13:00 UTC + 11 hours (AEDT) = 00:00 next day (hour 0)
        self.assertEqual(adjusted_df.iloc[1]["date_text"].hour, 0)
        self.assertEqual(adjusted_df.iloc[1]["city"], "Sydney")

    def test_swarm_location_fallbacks(self):
        # Mock data with missing city but has state
        json_data = {
            "items": [
                {
                    "createdAt": 1334000000,
                    "timeZoneOffset": 480,
                    "venue": {
                        "name": "Western Australia Venue",
                        "location": {
                            "state": "Western Australia",
                            "lat": -31.9505,
                            "lng": 115.8605,
                        },
                    },
                }
            ]
        }

        with open(os.path.join(self.test_dir, "checkins_fallback.json"), "w") as f:
            json.dump(json_data, f)

        df = load_swarm_data(self.test_dir)
        self.assertEqual(df.iloc[0]["city"], "Western Australia")
        self.assertEqual(df.iloc[0]["lat"], -31.9505)
        # Ensure timestamp is correct (1334000000)
        self.assertEqual(df.iloc[0]["timestamp"], 1334000000)

    def test_swarm_venue_fallback_with_geocoder(self):
        # When coordinates are present but no city/state/country in location,
        # reverse_geocoder fills in city and country from lat/lng.
        json_data = {
            "items": [
                {
                    "createdAt": 1335000000,
                    "timeZoneOffset": 0,
                    "venue": {
                        "name": "Greenwich Observatory",
                        "location": {"lat": 51.4769, "lng": 0.0005},
                    },
                }
            ]
        }

        with open(os.path.join(self.test_dir, "checkins_venue.json"), "w") as f:
            json.dump(json_data, f)

        mock_rg = unittest.mock.MagicMock()
        # Only the venue item lacks city/state/country; the 2 setUp items have
        # location.city set and are not passed to the geocoder.
        mock_rg.search.return_value = [{"name": "London", "cc": "GB", "admin1": "England"}]
        with patch.dict("sys.modules", {"reverse_geocoder": mock_rg}):
            df = load_swarm_data(self.test_dir)

        venue_row = df[df["venue"] == "Greenwich Observatory"].iloc[0]
        self.assertEqual(venue_row["city"], "London")
        self.assertEqual(venue_row["country"], "GB")
        self.assertEqual(venue_row["lat"], 51.4769)

    def test_swarm_venue_fallback_without_geocoder(self):
        # When reverse_geocoder is absent, falls back to venue name / "Unknown".
        json_data = {
            "items": [
                {
                    "createdAt": 1335000000,
                    "timeZoneOffset": 0,
                    "venue": {
                        "name": "Greenwich Observatory",
                        "location": {"lat": 51.4769, "lng": 0.0005},
                    },
                }
            ]
        }

        with open(os.path.join(self.test_dir, "checkins_venue.json"), "w") as f:
            json.dump(json_data, f)

        with patch.dict("sys.modules", {"reverse_geocoder": None}):
            df = load_swarm_data(self.test_dir)

        venue_row = df[df["venue"] == "Greenwich Observatory"].iloc[0]
        self.assertEqual(venue_row["city"], "Greenwich Observatory")
        self.assertEqual(venue_row["country"], "Unknown")
        self.assertEqual(venue_row["lat"], 51.4769)


if __name__ == "__main__":
    unittest.main()
