"""Tests for Subtask 1 — infer_residency_periods in analysis_utils.py.

Covers:
- Empty DataFrame input returns []
- Single city with 4+ months produces one period with correct start/end
- Two geographically separate cities (>48 km apart) each with 4+ months → two periods
- Two nearby cities (<48 km) merged into one cluster under dominant city name
- A 2-month blip surrounded by a long home-cluster run does NOT produce a period
- Sparse months with no check-ins are forward-filled from the prior cluster
- Returned dicts have exactly the keys ``city``, ``start``, ``end`` as ISO date strings
- lat/lng columns absent → returns []
- All lat/lng values are NaN → returns []
- City column empty/None → falls back to "Unknown"
- Fewer than 3 months total in data → returns []
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd


def _ts(date_str: str) -> int:
    """Return unix timestamp (int seconds) for the given ISO date string."""
    return int(pd.Timestamp(date_str).timestamp())


def _make_swarm_df(
    rows: list[dict],
) -> pd.DataFrame:
    """Build a minimal Swarm-style DataFrame.

    Each element in *rows* should be a dict with keys: timestamp (str or int),
    lat, lng, city.  Pass a date string for timestamp and it will be converted.
    """
    processed = []
    for r in rows:
        ts = r["timestamp"]
        if isinstance(ts, str):
            ts = _ts(ts)
        processed.append(
            {
                "timestamp": ts,
                "lat": r.get("lat", np.nan),
                "lng": r.get("lng", np.nan),
                "city": r.get("city", ""),
            }
        )
    return pd.DataFrame(processed)


# ---------------------------------------------------------------------------
# Chicago and NYC reference coordinates
# ---------------------------------------------------------------------------
# Chicago: 41.8781, -87.6298
# NYC: 40.7128, -74.0060
# Distance: ~1,200 km — well outside the 48 km merge radius

CHI_LAT, CHI_LNG = 41.8781, -87.6298
NYC_LAT, NYC_LNG = 40.7128, -74.0060

# Evanston, IL — ~17 km north of downtown Chicago (within 48 km)
EVA_LAT, EVA_LNG = 42.0451, -87.6877


# ---------------------------------------------------------------------------
# Helper to generate a sequence of monthly check-ins
# ---------------------------------------------------------------------------


def _monthly_checkins(
    start_month: str,
    n_months: int,
    lat: float,
    lng: float,
    city: str,
    checkins_per_month: int = 5,
) -> list[dict]:
    """Return a list of row dicts, one per check-in, spread across n_months."""
    rows: list[dict] = []
    period_start = pd.Period(start_month, freq="M")
    for i in range(n_months):
        period = period_start + i
        # Place check-ins on consecutive days starting on the 1st
        for day in range(checkins_per_month):
            date_str = period.to_timestamp().strftime("%Y-%m-") + f"{day + 1:02d}"
            rows.append({"timestamp": date_str, "lat": lat, "lng": lng, "city": city})
    return rows


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestInferResidencyEmpty(unittest.TestCase):
    """Edge cases that return an empty list without raising."""

    def test_empty_dataframe_returns_empty_list(self) -> None:
        """An empty DataFrame must produce an empty list."""
        from analysis_utils import infer_residency_periods

        df = pd.DataFrame(columns=["timestamp", "lat", "lng", "city"])
        result = infer_residency_periods(df)
        self.assertEqual(result, [])

    def test_missing_lat_lng_columns_returns_empty_list(self) -> None:
        """DataFrame without lat/lng columns must return []."""
        from analysis_utils import infer_residency_periods

        df = pd.DataFrame({"timestamp": [_ts("2020-01-15")], "city": ["Chicago"]})
        result = infer_residency_periods(df)
        self.assertEqual(result, [])

    def test_all_nan_lat_lng_returns_empty_list(self) -> None:
        """If every row has NaN lat/lng after dropping nulls, return []."""
        from analysis_utils import infer_residency_periods

        df = pd.DataFrame(
            {
                "timestamp": [_ts("2020-01-15"), _ts("2020-02-15")],
                "lat": [np.nan, np.nan],
                "lng": [np.nan, np.nan],
                "city": ["Chicago", "Chicago"],
            }
        )
        result = infer_residency_periods(df)
        self.assertEqual(result, [])

    def test_fewer_than_3_months_returns_empty_list(self) -> None:
        """Data spanning fewer than 3 distinct months → no qualifying run."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-01", 2, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(result, [])


class TestInferResidencySingleCity(unittest.TestCase):
    """Single-cluster scenarios."""

    def test_single_city_returns_one_period(self) -> None:
        """4 months of check-ins in one city → exactly one period dict."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-01", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 1)

    def test_single_city_correct_city_name(self) -> None:
        """Returned dict uses the city name from the check-ins."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-01", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(result[0]["city"], "Chicago")

    def test_single_city_start_date(self) -> None:
        """Start date must be the first day of the first month."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-03", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(result[0]["start"], "2020-03-01")

    def test_single_city_end_date(self) -> None:
        """End date must be the last day of the last month."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-03", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        # 4 months: Mar, Apr, May, Jun 2020 — last day of June is 2020-06-30
        self.assertEqual(result[0]["end"], "2020-06-30")

    def test_single_city_12_months_one_period(self) -> None:
        """12 months in one city collapses into a single period, not 12."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2019-01", 12, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 1)


class TestInferResidencyTwoCities(unittest.TestCase):
    """Two-cluster scenarios with geographically distinct cities."""

    def test_two_cities_returns_two_periods(self) -> None:
        """12 months Chicago then 12 months NYC → 2 period dicts."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2018-01", 12, CHI_LAT, CHI_LNG, "Chicago")
        rows += _monthly_checkins("2019-01", 12, NYC_LAT, NYC_LNG, "New York")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 2)

    def test_two_cities_correct_city_names(self) -> None:
        """Each period dict carries the correct city label."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2018-01", 12, CHI_LAT, CHI_LNG, "Chicago")
        rows += _monthly_checkins("2019-01", 12, NYC_LAT, NYC_LNG, "New York")
        df = _make_swarm_df(rows)
        result = sorted(infer_residency_periods(df), key=lambda d: d["start"])
        self.assertEqual(result[0]["city"], "Chicago")
        self.assertEqual(result[1]["city"], "New York")

    def test_two_cities_sorted_by_start(self) -> None:
        """Periods are returned in chronological order (sorted by start)."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2018-01", 12, CHI_LAT, CHI_LNG, "Chicago")
        rows += _monthly_checkins("2019-01", 12, NYC_LAT, NYC_LNG, "New York")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertLess(result[0]["start"], result[1]["start"])

    def test_two_cities_boundary_dates(self) -> None:
        """First period ends last day of December, second starts January 1st."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2018-01", 12, CHI_LAT, CHI_LNG, "Chicago")
        rows += _monthly_checkins("2019-01", 12, NYC_LAT, NYC_LNG, "New York")
        df = _make_swarm_df(rows)
        result = sorted(infer_residency_periods(df), key=lambda d: d["start"])
        self.assertEqual(result[0]["start"], "2018-01-01")
        self.assertEqual(result[0]["end"], "2018-12-31")
        self.assertEqual(result[1]["start"], "2019-01-01")
        self.assertEqual(result[1]["end"], "2019-12-31")


class TestInferResidencyNearbyMerge(unittest.TestCase):
    """Coordinates within 48 km must be merged into a single cluster."""

    def test_nearby_cities_merged_into_one_period(self) -> None:
        """Evanston (17 km from Chicago) and Chicago merge into one period."""
        from analysis_utils import infer_residency_periods

        # 6 months Chicago, then 6 months Evanston — same metro, same cluster
        rows = _monthly_checkins("2020-01", 6, CHI_LAT, CHI_LNG, "Chicago")
        rows += _monthly_checkins("2020-07", 6, EVA_LAT, EVA_LNG, "Evanston")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 1)

    def test_nearby_cities_dominant_name_used(self) -> None:
        """Cluster label is the more-frequent city name (Chicago > Evanston)."""
        from analysis_utils import infer_residency_periods

        # 8 months Chicago (more frequent) vs 4 months Evanston
        rows = _monthly_checkins("2020-01", 8, CHI_LAT, CHI_LNG, "Chicago")
        rows += _monthly_checkins("2020-09", 4, EVA_LAT, EVA_LNG, "Evanston")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["city"], "Chicago")

    def test_far_cities_not_merged(self) -> None:
        """Chicago and NYC (>48 km apart) remain separate clusters."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-01", 6, CHI_LAT, CHI_LNG, "Chicago")
        rows += _monthly_checkins("2020-07", 6, NYC_LAT, NYC_LNG, "New York")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 2)


class TestInferResidencyStabilityFilter(unittest.TestCase):
    """2-month blips must not produce their own period."""

    def test_two_month_blip_not_returned(self) -> None:
        """A 2-month visit to NYC inside a long Chicago residency → 1 period."""
        from analysis_utils import infer_residency_periods

        rows = []
        # 8 months Chicago
        rows += _monthly_checkins("2019-01", 8, CHI_LAT, CHI_LNG, "Chicago")
        # 2 month blip in NYC
        rows += _monthly_checkins("2019-09", 2, NYC_LAT, NYC_LNG, "New York")
        # 4 more months Chicago
        rows += _monthly_checkins("2019-11", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        cities = [d["city"] for d in result]
        self.assertNotIn("New York", cities)

    def test_two_month_blip_does_not_split_home_residency(self) -> None:
        """The home residency is not split into two separate periods by the blip."""
        from analysis_utils import infer_residency_periods

        rows = []
        rows += _monthly_checkins("2019-01", 8, CHI_LAT, CHI_LNG, "Chicago")
        rows += _monthly_checkins("2019-09", 2, NYC_LAT, NYC_LNG, "New York")
        rows += _monthly_checkins("2019-11", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        chicago_periods = [d for d in result if d["city"] == "Chicago"]
        # Must be exactly one contiguous Chicago period (the blip is swallowed)
        self.assertEqual(len(chicago_periods), 1)

    def test_one_month_run_not_returned(self) -> None:
        """A single-month run at any cluster is always excluded."""
        from analysis_utils import infer_residency_periods

        rows = []
        rows += _monthly_checkins("2019-01", 5, CHI_LAT, CHI_LNG, "Chicago")
        # 1-month blip
        rows += _monthly_checkins("2019-06", 1, NYC_LAT, NYC_LNG, "New York")
        rows += _monthly_checkins("2019-07", 5, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        cities = [d["city"] for d in result]
        self.assertNotIn("New York", cities)


class TestInferResidencyForwardFill(unittest.TestCase):
    """Gaps in check-ins must be forward-filled, not back-filled."""

    def test_gap_month_filled_from_prior_cluster(self) -> None:
        """A month with zero check-ins is filled from the preceding month's cluster."""
        from analysis_utils import infer_residency_periods

        # 3 months Chicago, 1 month gap, 3 more months Chicago
        # Without forward-fill the gap month might break the qualifying run.
        # With it the run remains 7 months and produces one period.
        rows = []
        rows += _monthly_checkins("2020-01", 3, CHI_LAT, CHI_LNG, "Chicago")
        # deliberately skip 2020-04 (no check-ins that month)
        rows += _monthly_checkins("2020-05", 3, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["city"], "Chicago")

    def test_leading_gap_excluded(self) -> None:
        """Months before the first check-in are excluded (no back-fill)."""
        from analysis_utils import infer_residency_periods

        # All check-ins start in March; January and February have no data.
        # The period should start in March, not January.
        rows = _monthly_checkins("2020-03", 5, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 1)
        # Start must be in March 2020 (not some earlier back-filled month)
        self.assertTrue(result[0]["start"].startswith("2020-03"))


class TestInferResidencyDictShape(unittest.TestCase):
    """All returned dicts must have exactly the keys city, start, end."""

    def test_dict_has_exactly_three_keys(self) -> None:
        """Each returned dict has exactly {city, start, end}."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-01", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0].keys()), {"city", "start", "end"})

    def test_start_is_iso_date_string(self) -> None:
        """start value matches YYYY-MM-DD format."""

        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-01", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertRegex(result[0]["start"], r"^\d{4}-\d{2}-\d{2}$")

    def test_end_is_iso_date_string(self) -> None:
        """end value matches YYYY-MM-DD format."""

        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-01", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertRegex(result[0]["end"], r"^\d{4}-\d{2}-\d{2}$")

    def test_all_values_are_strings(self) -> None:
        """city, start, and end must all be str instances."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-01", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        for key in ("city", "start", "end"):
            self.assertIsInstance(result[0][key], str)


class TestInferResidencyFallbackCityName(unittest.TestCase):
    """When city column is empty or None, label falls back to 'Unknown'."""

    def test_empty_city_string_falls_back_to_unknown(self) -> None:
        """Rows with empty string city produce cluster label 'Unknown'."""
        from analysis_utils import infer_residency_periods

        rows = []
        for month_offset in range(4):
            period = pd.Period("2020-01", freq="M") + month_offset
            date_str = period.to_timestamp().strftime("%Y-%m-01")
            rows.append({"timestamp": date_str, "lat": CHI_LAT, "lng": CHI_LNG, "city": ""})
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["city"], "Unknown")

    def test_none_city_falls_back_to_unknown(self) -> None:
        """Rows with None city value produce cluster label 'Unknown'."""
        from analysis_utils import infer_residency_periods

        rows = []
        for month_offset in range(4):
            period = pd.Period("2020-01", freq="M") + month_offset
            date_str = period.to_timestamp().strftime("%Y-%m-01")
            rows.append({"timestamp": date_str, "lat": CHI_LAT, "lng": CHI_LNG, "city": None})
        df = pd.DataFrame(rows)
        df["timestamp"] = df["timestamp"].apply(lambda s: int(pd.Timestamp(s).timestamp()))
        result = infer_residency_periods(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["city"], "Unknown")


class TestInferResidencyMinMonthsParam(unittest.TestCase):
    """min_months parameter controls the stability filter threshold."""

    def test_custom_min_months_1_accepts_single_month_run(self) -> None:
        """With min_months=1, even a single-month run qualifies."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-06", 1, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df, min_months=1)
        self.assertEqual(len(result), 1)

    def test_custom_min_months_5_rejects_4_month_run(self) -> None:
        """With min_months=5, a 4-month run returns []."""
        from analysis_utils import infer_residency_periods

        rows = _monthly_checkins("2020-01", 4, CHI_LAT, CHI_LNG, "Chicago")
        df = _make_swarm_df(rows)
        result = infer_residency_periods(df, min_months=5)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
