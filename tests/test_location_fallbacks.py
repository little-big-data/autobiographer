import unittest
from datetime import datetime, timezone

import pandas as pd

from analysis_utils import apply_location_context, get_assumption_location, load_assumptions


class TestLocationFallbacks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load the example assumptions for testing
        cls.assumptions = load_assumptions("default_assumptions.json.example")

    def test_perth_fallback(self):
        # May 10, 2022 (During Perth trip)
        dt = datetime(2022, 5, 10, 12, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        location = get_assumption_location(ts, self.assumptions)
        self.assertIsNotNone(location)
        self.assertEqual(location["city"], "Perth, AU")
        # Perth is UTC+8
        self.assertEqual(location["offset"], 480)

    def test_cairo_fallback(self):
        # March 25, 2022 (During Cairo trip)
        dt = datetime(2022, 3, 25, 12, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        location = get_assumption_location(ts, self.assumptions)
        self.assertIsNotNone(location)
        self.assertEqual(location["city"], "Cairo, EG")
        # Cairo is UTC+2
        self.assertEqual(location["offset"], 120)

    def test_oslo_svalbard_overlap(self):
        # Aug 14, 2020 - Should be Oslo (first in list)
        dt = datetime(2020, 8, 14, 12, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        location = get_assumption_location(ts, self.assumptions)
        self.assertIsNotNone(location)
        self.assertEqual(location["city"], "Oslo, NO")

        # Aug 15, 2020 - Should be Svalbard
        dt = datetime(2020, 8, 15, 12, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        location = get_assumption_location(ts, self.assumptions)
        self.assertIsNotNone(location)
        self.assertEqual(location["city"], "Svalbard, NO")

    def test_athens_fallback(self):
        # Nov 7, 2020
        dt = datetime(2020, 11, 7, 12, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        location = get_assumption_location(ts, self.assumptions)
        self.assertIsNotNone(location)
        self.assertEqual(location["city"], "Athens, GR")
        # Athens is UTC+2 in November
        self.assertEqual(location["offset"], 120)

    def test_residency_fallback_still_works(self):
        # Oct 12, 2020 (Monday)
        # 10:00 AM on a Monday -> Workplace
        # 2020-10-12 07:00 UTC is 10:00 AM EAT (UTC+3)
        dt = datetime(2020, 10, 12, 7, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        location = get_assumption_location(ts, self.assumptions)
        self.assertIsNotNone(location)
        self.assertEqual(location["city"], "Co-working Space")

    def test_apply_location_context_comprehensive(self):
        # Create a Last.fm df covering many cases
        test_cases = [
            # 1. Holiday: Midsummer
            {"dt": datetime(2022, 6, 21, 12, 0, tzinfo=timezone.utc), "expected": "Anchorage, AK"},
            # 2. Trip: Perth
            {"dt": datetime(2022, 5, 10, 12, 0, tzinfo=timezone.utc), "expected": "Perth, AU"},
            # 3. Residency Work Hours: Oct 12, 2020 10:00 AM EAT (07:00 UTC)
            {
                "dt": datetime(2020, 10, 12, 7, 0, tzinfo=timezone.utc),
                "expected": "Co-working Space",
            },
            # 4. Residency Home 1: Jan 3, 2016 (Nairobi) - SUNDAY to avoid work_hours
            {"dt": datetime(2016, 1, 3, 12, 0, tzinfo=timezone.utc), "expected": "Nairobi, KE"},
            # 5. Residency Home 2: Jan 5, 2020 (Sunday) (Mombasa)
            {"dt": datetime(2020, 1, 5, 12, 0, tzinfo=timezone.utc), "expected": "Mombasa, KE"},
            # 6. Default: 2026 (After residency ends)
            {"dt": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), "expected": "Reykjavik, IS"},
        ]

        df = pd.DataFrame(
            {
                "timestamp": [int(tc["dt"].timestamp()) for tc in test_cases],
                "date_text": [tc["dt"].strftime("%Y-%m-%d %H:%M") for tc in test_cases],
                "artist": ["A"] * len(test_cases),
                "track": ["T"] * len(test_cases),
            }
        )

        swarm_df = pd.DataFrame(columns=["timestamp", "offset", "city", "venue", "lat", "lng"])
        result_df = apply_location_context(df, swarm_df, self.assumptions)

        for i, tc in enumerate(test_cases):
            self.assertEqual(
                result_df.iloc[i]["city"], tc["expected"], f"Failed case {i}: {tc['expected']}"
            )

    def test_dublin_fallback(self):
        # Jul 17, 2021 (During Dublin trip)
        dt = datetime(2021, 7, 17, 12, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        location = get_assumption_location(ts, self.assumptions)
        self.assertIsNotNone(location)
        self.assertEqual(location["city"], "Dublin, IE")

    def test_stockholm_fallback(self):
        # May 17, 2023
        dt = datetime(2023, 5, 17, 15, 0, tzinfo=timezone.utc)
        ts = int(dt.timestamp())
        location = get_assumption_location(ts, self.assumptions)
        self.assertIsNotNone(location)
        self.assertEqual(location["city"], "Stockholm, SE")


if __name__ == "__main__":
    unittest.main()
