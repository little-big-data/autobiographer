import os
import tempfile
import unittest

import pandas as pd

from analysis_utils import (
    get_artist_monthly_ranks,
    get_cumulative_plays,
    get_day_hour_heatmap,
    get_first_plays,
    get_forgotten_favorites,
    get_genre_weekly,
    get_hourly_distribution,
    get_listening_intensity,
    get_listening_streaks,
    get_milestones,
    get_top_entities,
    load_listening_data,
)


class TestAnalysisUtils(unittest.TestCase):
    def setUp(self):
        fd, self.test_csv = tempfile.mkstemp(prefix="test_analysis_utils_", suffix=".csv")
        os.close(fd)
        self.df = pd.DataFrame(
            {
                "artist": ["Artist 1", "Artist 2", "Artist 1"],
                "album": ["Album 1", "Album 2", "Album 1"],
                "track": ["Track 1", "Track 2", "Track 3"],
                "timestamp": [1610000000, 1610000100, 1610000200],
                "date_text": ["2021-01-01 10:00", "2021-01-01 10:01", "2021-01-01 11:02"],
            }
        )
        self.df.to_csv(self.test_csv, index=False)

    def tearDown(self):
        if os.path.exists(self.test_csv):
            os.remove(self.test_csv)

    def test_load_listening_data(self):
        df = load_listening_data(self.test_csv)
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 3)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(df["date_text"]))

    def test_get_top_entities(self):
        top_artists = get_top_entities(self.df, entity="artist")
        self.assertEqual(len(top_artists), 2)
        self.assertEqual(top_artists.iloc[0]["artist"], "Artist 1")
        self.assertEqual(top_artists.iloc[0]["Plays"], 2)

    def test_get_listening_intensity(self):
        df_loaded = load_listening_data(self.test_csv)
        intensity_day = get_listening_intensity(df_loaded, freq="D")
        self.assertEqual(len(intensity_day), 1)
        self.assertEqual(intensity_day.iloc[0]["Plays"], 3)

        intensity_week = get_listening_intensity(df_loaded, freq="W")
        self.assertEqual(len(intensity_week), 1)

    def test_get_listening_intensity_empty(self):
        empty_df = pd.DataFrame(columns=["artist", "date_text"])
        intensity = get_listening_intensity(empty_df)
        self.assertTrue(intensity.empty)

    def test_get_milestones(self):
        # Create a df with enough tracks for a milestone
        data = []
        for i in range(1001):
            data.append(
                {
                    "artist": f"Artist {i}",
                    "track": f"Track {i}",
                    "date_text": pd.Timestamp("2021-01-01") + pd.Timedelta(minutes=i),
                }
            )
        df = pd.DataFrame(data)
        milestones = get_milestones(df, intervals=[1000])
        self.assertEqual(len(milestones), 1)
        self.assertEqual(milestones.iloc[0]["Milestone"], "1,000 Tracks")

    def test_get_listening_streaks(self):
        # 3 consecutive days
        dates = [
            "2021-01-01 10:00",
            "2021-01-02 10:00",
            "2021-01-03 10:00",
            "2021-01-05 10:00",  # Gap
        ]
        df = pd.DataFrame({"date_text": pd.to_datetime(dates)})
        streaks = get_listening_streaks(df)
        self.assertEqual(streaks["longest_streak"], 3)

    def test_get_forgotten_favorites(self):
        # Artist 1 played 6 months ago, not recently
        now = pd.Timestamp.now()
        past = now - pd.DateOffset(months=7)
        recent = now - pd.DateOffset(days=1)

        df = pd.DataFrame({"artist": ["Artist 1", "Artist 2"], "date_text": [past, recent]})
        forgotten = get_forgotten_favorites(df, months_threshold=6)
        self.assertEqual(len(forgotten), 1)
        self.assertEqual(forgotten.iloc[0]["Artist"], "Artist 1")

    def test_get_cumulative_plays(self):
        df_loaded = load_listening_data(self.test_csv)
        cumulative = get_cumulative_plays(df_loaded)
        self.assertEqual(len(cumulative), 1)
        self.assertEqual(cumulative.iloc[0]["CumulativePlays"], 3)

    def test_get_hourly_distribution(self):
        df_loaded = load_listening_data(self.test_csv)
        hourly = get_hourly_distribution(df_loaded)
        self.assertEqual(len(hourly), 2)  # Hour 10 and 11
        self.assertEqual(hourly[hourly["hour"] == 10].iloc[0]["Plays"], 2)
        self.assertEqual(hourly[hourly["hour"] == 11].iloc[0]["Plays"], 1)

    def test_get_listening_streaks_single_date(self):
        df = pd.DataFrame({"date_text": pd.to_datetime(["2021-06-15"])})
        streaks = get_listening_streaks(df)
        self.assertEqual(streaks["longest_streak"], 1)
        self.assertEqual(streaks["last_active"].isoformat(), "2021-06-15")

    def test_get_listening_streaks_current_active(self):
        today = pd.Timestamp.now().normalize()
        dates = pd.to_datetime([today - pd.Timedelta(days=1), today])
        df = pd.DataFrame({"date_text": dates})
        streaks = get_listening_streaks(df)
        self.assertEqual(streaks["longest_streak"], 2)
        self.assertEqual(streaks["current_streak"], 2)

    def test_get_day_hour_heatmap_shape(self):
        df = load_listening_data(self.test_csv)
        pivot = get_day_hour_heatmap(df)
        self.assertFalse(pivot.empty)
        self.assertIn(10, pivot.columns)
        self.assertIn(11, pivot.columns)

    def test_get_genre_weekly_returns_expected_columns(self):
        dates = pd.to_datetime(["2021-01-04", "2021-01-04", "2021-01-11", "2021-01-11"])
        df = pd.DataFrame(
            {
                "artist": ["Artist A", "Artist B", "Artist A", "Artist A"],
                "date_text": dates,
            }
        )
        result = get_genre_weekly(df, n=5)
        self.assertListEqual(list(result.columns), ["date", "genre", "scrobbles"])

    def test_get_genre_weekly_aggregates_correctly(self):
        dates = pd.to_datetime(["2021-01-04", "2021-01-04", "2021-01-11"])
        df = pd.DataFrame({"artist": ["Artist A", "Artist A", "Artist A"], "date_text": dates})
        result = get_genre_weekly(df, n=2)
        self.assertEqual(result["scrobbles"].sum(), 3)
        self.assertEqual(len(result), 2)  # two distinct weeks

    def test_get_genre_weekly_empty(self):
        empty = pd.DataFrame(columns=["artist", "date_text"])
        result = get_genre_weekly(empty)
        self.assertTrue(result.empty)

    def test_get_genre_weekly_limits_to_top_n(self):
        dates = pd.to_datetime(["2021-01-04"] * 5)
        df = pd.DataFrame({"artist": ["A", "B", "C", "D", "E"], "date_text": dates})
        result = get_genre_weekly(df, n=3)
        self.assertLessEqual(result["genre"].nunique(), 3)

    def test_get_artist_monthly_ranks_columns(self):
        dates = pd.to_datetime(["2021-01-15", "2021-01-20", "2021-02-10"])
        df = pd.DataFrame({"artist": ["Artist A", "Artist B", "Artist A"], "date_text": dates})
        result = get_artist_monthly_ranks(df, n=5)
        self.assertListEqual(list(result.columns), ["month", "artist", "rank"])

    def test_get_artist_monthly_ranks_rank_1_is_highest_plays(self):
        dates = pd.to_datetime(["2021-01-01"] * 3 + ["2021-01-02"])
        df = pd.DataFrame(
            {"artist": ["Artist A", "Artist A", "Artist A", "Artist B"], "date_text": dates}
        )
        result = get_artist_monthly_ranks(df, n=2)
        jan = result[result["month"].dt.month == 1]
        rank1_artist = jan.loc[jan["rank"] == 1, "artist"].values[0]
        self.assertEqual(rank1_artist, "Artist A")

    def test_get_artist_monthly_ranks_empty(self):
        empty = pd.DataFrame(columns=["artist", "date_text"])
        result = get_artist_monthly_ranks(empty)
        self.assertTrue(result.empty)

    # ── get_first_plays ───────────────────────────────────────────────────────

    def test_get_first_plays_returns_one_row_per_artist(self):
        df = pd.DataFrame(
            {
                "artist": ["Artist A", "Artist A", "Artist B"],
                "track": ["Song 1", "Song 2", "Song 3"],
                "timestamp": [1000, 2000, 1500],
                "date_text": pd.to_datetime(["2021-01-01", "2021-01-02", "2021-01-01"]),
            }
        )
        result = get_first_plays(df)
        self.assertEqual(len(result), 2)
        self.assertIn("Artist A", result["artist"].values)
        self.assertIn("Artist B", result["artist"].values)

    def test_get_first_plays_selects_earliest_timestamp(self):
        df = pd.DataFrame(
            {
                "artist": ["Artist A", "Artist A"],
                "track": ["Early Song", "Later Song"],
                "timestamp": [1000, 9000],
                "date_text": pd.to_datetime(["2021-01-01", "2021-06-01"]),
            }
        )
        result = get_first_plays(df)
        self.assertEqual(len(result), 1)
        # The first play row should carry the earliest track
        self.assertEqual(result.iloc[0]["track"], "Early Song")

    def test_get_first_plays_sorted_by_timestamp(self):
        df = pd.DataFrame(
            {
                "artist": ["Artist B", "Artist A"],
                "track": ["B Song", "A Song"],
                "timestamp": [2000, 1000],
                "date_text": pd.to_datetime(["2021-02-01", "2021-01-01"]),
            }
        )
        result = get_first_plays(df)
        self.assertEqual(result.iloc[0]["artist"], "Artist A")
        self.assertEqual(result.iloc[1]["artist"], "Artist B")

    def test_get_first_plays_empty_input_returns_empty(self):
        empty = pd.DataFrame(columns=["artist", "timestamp"])
        result = get_first_plays(empty)
        self.assertTrue(result.empty)

    def test_get_first_plays_missing_timestamp_returns_empty(self):
        df = pd.DataFrame({"artist": ["Artist A"], "track": ["Song"]})
        result = get_first_plays(df)
        self.assertTrue(result.empty)

    def test_get_first_plays_missing_artist_returns_empty(self):
        df = pd.DataFrame({"timestamp": [1000], "track": ["Song"]})
        result = get_first_plays(df)
        self.assertTrue(result.empty)

    def test_get_first_plays_preserves_extra_columns(self):
        df = pd.DataFrame(
            {
                "artist": ["Artist A"],
                "track": ["Song"],
                "timestamp": [1000],
                "date_text": pd.to_datetime(["2021-01-01"]),
                "city": ["Reykjavik"],
                "lat": [64.1],
                "lng": [-21.8],
            }
        )
        result = get_first_plays(df)
        self.assertIn("city", result.columns)
        self.assertIn("lat", result.columns)
        self.assertEqual(result.iloc[0]["city"], "Reykjavik")

    def test_setup_uses_unique_per_invocation_csv_path(self):
        """self.test_csv must be a unique per-invocation path, not a
        hardcoded shared path, so parallel pytest-xdist workers running
        different test methods of this TestCase never race on the same file
        (handoff.md Subtask 1)."""
        other = TestAnalysisUtils("test_load_listening_data")
        other.setUp()
        try:
            self.assertNotEqual(
                self.test_csv,
                other.test_csv,
                "self.test_csv must be a unique per-invocation path, not a "
                "shared hardcoded path reused across invocations",
            )
            # tearing down one invocation's fixture must never remove the
            # other invocation's still-in-use fixture file.
            other.tearDown()
            self.assertTrue(
                os.path.exists(self.test_csv),
                "tearing down a different TestAnalysisUtils invocation must "
                "not delete this invocation's still-in-use test_csv",
            )
        finally:
            if os.path.exists(other.test_csv):
                os.remove(other.test_csv)


class TestSwarmAnalysisCaches(unittest.TestCase):
    """Tests for transit-days, dining, and detected-trips cache persistence."""

    def test_transit_days_roundtrip(self) -> None:
        import tempfile

        from analysis_utils import load_transit_days_cache, save_transit_days_cache

        days = {"2024-01-01", "2024-06-15", "2024-12-25"}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "transit.json")
            save_transit_days_cache(days, path)
            loaded = load_transit_days_cache(path)
        self.assertEqual(loaded, days)

    def test_transit_days_missing_file_returns_empty_set(self) -> None:
        from analysis_utils import load_transit_days_cache

        result = load_transit_days_cache("/nonexistent/path.json")
        self.assertEqual(result, set())

    def test_transit_days_invalid_json_returns_empty_set(self) -> None:
        import tempfile

        from analysis_utils import load_transit_days_cache

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            fh.write("not json[{")
            path = fh.name
        result = load_transit_days_cache(path)
        os.unlink(path)
        self.assertEqual(result, set())

    def test_dining_cache_roundtrip(self) -> None:
        import tempfile

        from analysis_utils import load_dining_cache, save_dining_cache

        artists_df = pd.DataFrame({"artist": ["Artist A", "Artist B"], "Plays": [10, 5]})
        albums_df = pd.DataFrame({"album": ["Album X"], "Plays": [3]})
        data = {
            "Restaurants": {
                "top_artists": artists_df,
                "top_albums": albums_df,
                "checkin_count": 4,
                "listen_count": 15,
                "peak_hour": 19,
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "dining.json")
            save_dining_cache(data, path)
            loaded = load_dining_cache(path)

        self.assertIn("Restaurants", loaded)
        self.assertEqual(loaded["Restaurants"]["checkin_count"], 4)
        self.assertEqual(loaded["Restaurants"]["listen_count"], 15)
        self.assertEqual(loaded["Restaurants"]["peak_hour"], 19)
        self.assertEqual(
            list(loaded["Restaurants"]["top_artists"]["artist"]), ["Artist A", "Artist B"]
        )

    def test_dining_cache_missing_file_returns_empty(self) -> None:
        from analysis_utils import load_dining_cache

        self.assertEqual(load_dining_cache("/nonexistent/path.json"), {})

    def test_dining_cache_peak_hour_none_roundtrips(self) -> None:
        import tempfile

        from analysis_utils import load_dining_cache, save_dining_cache

        data = {
            "Cafes": {
                "top_artists": pd.DataFrame(),
                "top_albums": pd.DataFrame(),
                "checkin_count": 1,
                "listen_count": 0,
                "peak_hour": None,
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "dining.json")
            save_dining_cache(data, path)
            loaded = load_dining_cache(path)
        self.assertIsNone(loaded["Cafes"]["peak_hour"])


class TestGetTransitDays(unittest.TestCase):
    """Tests for get_transit_days."""

    def test_returns_dates_with_airport_checkin(self) -> None:
        from analysis_utils import get_transit_days

        swarm = pd.DataFrame(
            {"venue_category": ["Airport", "Coffee Shop"], "timestamp": [1700000000, 1700003600]}
        )
        days = get_transit_days(swarm)
        self.assertEqual(len(days), 1)

    def test_empty_swarm_returns_empty_set(self) -> None:
        from analysis_utils import get_transit_days

        self.assertEqual(get_transit_days(pd.DataFrame()), set())

    def test_no_transit_category_returns_empty(self) -> None:
        from analysis_utils import get_transit_days

        swarm = pd.DataFrame({"venue_category": ["Museum", "Park"], "timestamp": [1, 2]})
        self.assertEqual(get_transit_days(swarm), set())

    def test_case_insensitive_matching(self) -> None:
        from analysis_utils import get_transit_days

        swarm = pd.DataFrame({"venue_category": ["airport"], "timestamp": [1700000000]})
        self.assertEqual(len(get_transit_days(swarm)), 1)


class TestSplitTransitListens(unittest.TestCase):
    """Tests for split_transit_listens."""

    def _make_df(self, days: list[str]) -> pd.DataFrame:
        ts = [1700000000 + i * 86400 for i in range(len(days))]
        return pd.DataFrame(
            {
                "date_text": pd.to_datetime(days),
                "timestamp": ts,
                "artist": ["A"] * len(days),
            }
        )

    def test_partitions_into_two_sets(self) -> None:
        from analysis_utils import split_transit_listens

        df = self._make_df(["2024-01-01", "2024-01-02"])
        transit, non = split_transit_listens(df, {"2024-01-01"})
        self.assertEqual(len(transit), 1)
        self.assertEqual(len(non), 1)

    def test_empty_transit_days_yields_all_non_transit(self) -> None:
        from analysis_utils import split_transit_listens

        df = self._make_df(["2024-01-01", "2024-01-02"])
        transit, non = split_transit_listens(df, set())
        self.assertEqual(len(transit), 0)
        self.assertEqual(len(non), 2)

    def test_empty_df_returns_two_empty_dfs(self) -> None:
        from analysis_utils import split_transit_listens

        transit, non = split_transit_listens(pd.DataFrame(), {"2024-01-01"})
        self.assertTrue(transit.empty)
        self.assertTrue(non.empty)


class TestClassifyVenueCategory(unittest.TestCase):
    """Tests for _classify_venue_category."""

    def test_restaurant_maps_correctly(self) -> None:
        from analysis_utils import _classify_venue_category

        self.assertEqual(_classify_venue_category("Italian Restaurant"), "Restaurants")

    def test_bar_maps_correctly(self) -> None:
        from analysis_utils import _classify_venue_category

        self.assertEqual(_classify_venue_category("Dive Bar"), "Bars & Nightlife")

    def test_cafe_maps_correctly(self) -> None:
        from analysis_utils import _classify_venue_category

        self.assertEqual(_classify_venue_category("Coffee Shop"), "Cafes")

    def test_fast_food_maps_correctly(self) -> None:
        from analysis_utils import _classify_venue_category

        self.assertEqual(_classify_venue_category("Burger Joint"), "Fast Food")

    def test_unknown_category_returns_none(self) -> None:
        from analysis_utils import _classify_venue_category

        self.assertIsNone(_classify_venue_category("Museum"))

    def test_empty_string_returns_none(self) -> None:
        from analysis_utils import _classify_venue_category

        self.assertIsNone(_classify_venue_category(""))


class TestGetDiningSoundtrackData(unittest.TestCase):
    """Tests for get_dining_soundtrack_data."""

    def test_returns_dict_with_bucket_keys(self) -> None:
        from analysis_utils import get_dining_soundtrack_data

        base_ts = 1700000000
        swarm = pd.DataFrame({"venue_category": ["Italian Restaurant"], "timestamp": [base_ts]})
        listens = pd.DataFrame(
            {
                "timestamp": [base_ts - 1800, base_ts, base_ts + 1800],
                "artist": ["Artist A", "Artist A", "Artist B"],
                "date_text": pd.to_datetime(
                    ["2023-11-14 10:00", "2023-11-14 11:00", "2023-11-14 12:00"]
                ),
            }
        )
        result = get_dining_soundtrack_data(swarm, listens)
        self.assertIn("Restaurants", result)

    def test_empty_inputs_return_empty_dict(self) -> None:
        from analysis_utils import get_dining_soundtrack_data

        self.assertEqual(get_dining_soundtrack_data(pd.DataFrame(), pd.DataFrame()), {})

    def test_missing_required_columns_returns_empty(self) -> None:
        from analysis_utils import get_dining_soundtrack_data

        bad_swarm = pd.DataFrame({"venue": ["Italian Restaurant"]})
        listens = pd.DataFrame(
            {
                "timestamp": [1700000000],
                "artist": ["A"],
                "date_text": pd.to_datetime(["2023-01-01"]),
            }
        )
        self.assertEqual(get_dining_soundtrack_data(bad_swarm, listens), {})


class TestGetDailyActivity(unittest.TestCase):
    """Tests for get_daily_activity (issue #27 — activity calendar heatmap prep).

    Subtask 1 of the activity-calendar-heatmap plan. get_daily_activity does not
    exist yet in analysis_utils.py, so each test imports it locally (matching this
    file's established convention for functions under active TDD, e.g.
    TestClassifyVenueCategory / TestGetDiningSoundtrackData above) so that a
    missing symbol only fails the tests that need it, not the whole module.
    """

    @staticmethod
    def _unix_seconds(date_str: str) -> int:
        """Convert a calendar-day string to Unix seconds at noon UTC.

        Noon (not midnight) avoids any accidental day-boundary flip when the
        implementation's tz-normalization path (unit="s", utc=True) is applied.
        """
        return int(pd.Timestamp(f"{date_str} 12:00:00", tz="UTC").timestamp())

    def _music_df(self, date_texts: list) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "artist": [f"Artist {i}" for i in range(len(date_texts))],
                "date_text": pd.to_datetime(date_texts),
            }
        )

    def _swarm_df(self, date_strs: list) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "venue": [f"Venue {i}" for i in range(len(date_strs))],
                "timestamp": [self._unix_seconds(d) for d in date_strs],
            }
        )

    # -- zero-fill correctness -------------------------------------------------

    def test_music_source_zero_fills_internal_gap(self) -> None:
        from analysis_utils import get_daily_activity

        df = self._music_df(["2024-01-01 10:00", "2024-01-03 09:00"])
        result = get_daily_activity(df, source="music")

        self.assertEqual(len(result), 3)
        self.assertListEqual(
            list(result["date"].dt.strftime("%Y-%m-%d")),
            ["2024-01-01", "2024-01-02", "2024-01-03"],
        )
        self.assertListEqual(list(result["value"]), [1, 0, 1])

    def test_music_source_single_day_range_returns_one_row(self) -> None:
        from analysis_utils import get_daily_activity

        df = self._music_df(["2024-06-15 08:00"])
        result = get_daily_activity(df, source="music")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["date"].strftime("%Y-%m-%d"), "2024-06-15")
        self.assertEqual(int(result.iloc[0]["value"]), 1)

    def test_music_source_duplicate_day_counts_correctly(self) -> None:
        from analysis_utils import get_daily_activity

        df = self._music_df(["2024-01-01 08:00", "2024-01-01 09:00", "2024-01-01 20:00"])
        result = get_daily_activity(df, source="music")

        self.assertEqual(len(result), 1)
        self.assertEqual(int(result.iloc[0]["value"]), 3)

    # -- multi-source summation and source-filter isolation --------------------

    def test_all_source_sums_multiple_sources(self) -> None:
        from analysis_utils import get_daily_activity

        df = self._music_df(["2024-01-01 09:00", "2024-01-01 10:00"])
        swarm_df = self._swarm_df(["2024-01-01", "2024-01-02"])
        result = get_daily_activity(df, swarm_df, source="all")

        by_date = dict(zip(result["date"].dt.strftime("%Y-%m-%d"), result["value"]))
        self.assertEqual(int(by_date["2024-01-01"]), 3)
        self.assertEqual(int(by_date["2024-01-02"]), 1)

    def test_checkins_source_ignores_df_changes(self) -> None:
        from analysis_utils import get_daily_activity

        swarm_df = self._swarm_df(["2024-01-01", "2024-01-02"])
        df_a = self._music_df(["2024-01-01 09:00"])
        df_b = self._music_df(["2024-05-05 09:00", "2024-05-06 10:00", "2024-05-07 11:00"])

        result_a = get_daily_activity(df_a, swarm_df, source="checkins")
        result_b = get_daily_activity(df_b, swarm_df, source="checkins")

        pd.testing.assert_frame_equal(
            result_a.reset_index(drop=True), result_b.reset_index(drop=True)
        )

    def test_music_source_ignores_swarm_df(self) -> None:
        from analysis_utils import get_daily_activity

        df = self._music_df(["2024-01-01 09:00", "2024-01-02 10:00"])
        swarm_a = self._swarm_df(["2024-09-01"])
        swarm_b = self._swarm_df(["2024-09-01", "2024-09-02", "2024-09-03"])

        result_a = get_daily_activity(df, swarm_a, source="music")
        result_b = get_daily_activity(df, swarm_b, source="music")

        pd.testing.assert_frame_equal(
            result_a.reset_index(drop=True), result_b.reset_index(drop=True)
        )

    # -- empty / None input handling --------------------------------------------

    def _assert_empty_result(self, result: pd.DataFrame) -> None:
        self.assertListEqual(list(result.columns), ["date", "value"])
        self.assertEqual(len(result), 0)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(result["date"]))

    def test_none_inputs_all_source_returns_empty(self) -> None:
        from analysis_utils import get_daily_activity

        result = get_daily_activity(None, None, source="all")
        self._assert_empty_result(result)

    def test_none_df_music_source_returns_empty(self) -> None:
        from analysis_utils import get_daily_activity

        result = get_daily_activity(None, source="music")
        self._assert_empty_result(result)

    def test_none_swarm_df_checkins_source_returns_empty(self) -> None:
        from analysis_utils import get_daily_activity

        result = get_daily_activity(None, None, source="checkins")
        self._assert_empty_result(result)

    def test_empty_dataframes_return_empty(self) -> None:
        from analysis_utils import get_daily_activity

        empty_music = pd.DataFrame(columns=["artist", "date_text"])
        empty_swarm = pd.DataFrame(columns=["venue", "timestamp"])

        self._assert_empty_result(get_daily_activity(empty_music, source="music"))
        self._assert_empty_result(get_daily_activity(None, empty_swarm, source="checkins"))
        self._assert_empty_result(get_daily_activity(empty_music, empty_swarm, source="all"))

    # -- invalid source ----------------------------------------------------------

    def test_invalid_source_raises_value_error_with_bad_value(self) -> None:
        from analysis_utils import get_daily_activity

        df = self._music_df(["2024-01-01 09:00"])
        with self.assertRaises(ValueError) as ctx:
            get_daily_activity(df, source="bogus")
        self.assertIn("bogus", str(ctx.exception))

    # -- tz handling ---------------------------------------------------------------

    def test_date_column_tz_naive_when_only_swarm_df(self) -> None:
        from analysis_utils import get_daily_activity

        swarm_df = self._swarm_df(["2024-02-01", "2024-02-02"])
        result = get_daily_activity(None, swarm_df, source="checkins")

        self.assertTrue(pd.api.types.is_datetime64_any_dtype(result["date"]))
        self.assertIsNone(result["date"].dt.tz)


if __name__ == "__main__":
    unittest.main()
