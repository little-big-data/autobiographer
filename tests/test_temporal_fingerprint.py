"""Tests for Subtask 4 — Seasonal & Temporal Fingerprinting.

Covers:
- get_seasonal_artist_affinity: winter skew, balanced artist, empty DataFrame
- get_morning_vs_night_artists: correct hour buckets, empty DataFrame
- get_day_of_week_personality: seven rows for seven days
- get_holiday_musical_identity: window inclusion/exclusion
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(date_str: str) -> int:
    """Convert an ISO date string to a unix timestamp integer (seconds)."""
    return int(pd.Timestamp(date_str).timestamp())


def _ts_at_hour(date_str: str, hour: int) -> int:
    """Convert a date string plus an explicit hour to a unix timestamp integer."""
    return int(pd.Timestamp(f"{date_str} {hour:02d}:00:00").timestamp())


def _make_play(
    artist: str,
    date_str: str,
    track: str = "Track A",
    album: str = "Album X",
    hour: int | None = None,
) -> dict:
    """Return a dict row for a single play.

    Args:
        artist: Artist name.
        date_str: ISO date string (e.g. "2020-01-15").
        track: Track title.
        album: Album title.
        hour: If provided, the timestamp is pinned to that hour of the day;
              otherwise midnight is used.

    Returns:
        Dict with ``timestamp``, ``artist``, ``track``, ``album`` keys.
    """
    ts = _ts_at_hour(date_str, hour) if hour is not None else _ts(date_str)
    return {"timestamp": ts, "artist": artist, "track": track, "album": album}


def _df(*rows: dict) -> pd.DataFrame:
    """Build a DataFrame from a sequence of row dicts."""
    return pd.DataFrame(list(rows))


# ---------------------------------------------------------------------------
# get_seasonal_artist_affinity
# ---------------------------------------------------------------------------


class TestSeasonalAffinityWinterSkew(unittest.TestCase):
    """Artist with all plays in Dec/Jan/Feb should have high Winter affinity."""

    def setUp(self) -> None:
        from analysis_utils import get_seasonal_artist_affinity

        self.func = get_seasonal_artist_affinity

        # Build an artist with 30 plays — all in winter months
        winter_dates = (
            [f"2020-12-{d:02d}" for d in range(1, 11)]
            + [f"2020-01-{d:02d}" for d in range(1, 11)]
            + [f"2020-02-{d:02d}" for d in range(1, 11)]
        )
        rows = [_make_play("WinterBand", d) for d in winter_dates]
        self.df = pd.DataFrame(rows)

    def test_winter_affinity_substantially_above_one(self) -> None:
        result = self.func(self.df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertIn("affinity_score", result.columns)
        self.assertIn("season", result.columns)
        self.assertIn("artist", result.columns)

        winter_row = result[(result["artist"] == "WinterBand") & (result["season"] == "Winter")]
        self.assertFalse(winter_row.empty, "Expected a Winter row for WinterBand")
        self.assertGreater(
            winter_row.iloc[0]["affinity_score"],
            1.5,
            "Winter affinity score should be substantially > 1.5 for an artist with all plays in winter",
        )

    def test_summer_affinity_near_zero(self) -> None:
        result = self.func(self.df)
        summer_row = result[(result["artist"] == "WinterBand") & (result["season"] == "Summer")]
        if not summer_row.empty:
            self.assertAlmostEqual(
                summer_row.iloc[0]["affinity_score"],
                0.0,
                places=5,
                msg="Summer affinity should be ~0 for an artist with no summer plays",
            )

    def test_result_has_play_count_column(self) -> None:
        result = self.func(self.df)
        self.assertIn("play_count", result.columns)


class TestSeasonalAffinityBalancedArtist(unittest.TestCase):
    """Artist with plays evenly across all 12 months → all season affinity scores near 1.0."""

    def setUp(self) -> None:
        from analysis_utils import get_seasonal_artist_affinity

        self.func = get_seasonal_artist_affinity

        # 3 plays per month over 2 years → 72 plays total, perfectly balanced
        rows = []
        for year in [2019, 2020]:
            for month in range(1, 13):
                for day in [5, 15, 25]:
                    date_str = f"{year}-{month:02d}-{day:02d}"
                    rows.append(_make_play("BalancedArtist", date_str))
        self.df = pd.DataFrame(rows)

    def test_all_season_scores_near_one(self) -> None:
        result = self.func(self.df)
        artist_rows = result[result["artist"] == "BalancedArtist"]
        self.assertEqual(len(artist_rows), 4, "Expected exactly 4 season rows for BalancedArtist")

        for _, row in artist_rows.iterrows():
            self.assertAlmostEqual(
                row["affinity_score"],
                1.0,
                delta=0.3,
                msg=f"Season '{row['season']}' affinity_score {row['affinity_score']:.3f} is not near 1.0",
            )


class TestSeasonalAffinityEmptyDf(unittest.TestCase):
    """Empty DataFrame → returns empty DataFrame, no crash."""

    def test_empty_df_returns_empty_dataframe(self) -> None:
        from analysis_utils import get_seasonal_artist_affinity

        empty = pd.DataFrame(columns=["timestamp", "artist", "track", "album"])
        result = get_seasonal_artist_affinity(empty)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty)


# ---------------------------------------------------------------------------
# get_morning_vs_night_artists
# ---------------------------------------------------------------------------


class TestMorningVsNightArtistsCorrectBuckets(unittest.TestCase):
    """Play at hour 7 → morning; play at hour 22 → night."""

    def setUp(self) -> None:
        from analysis_utils import get_morning_vs_night_artists

        self.func = get_morning_vs_night_artists

        morning_row = _make_play("MorningBand", "2020-06-15", hour=7)
        night_row = _make_play("NightOwl", "2020-06-15", hour=22)
        self.df = pd.DataFrame([morning_row, night_row])

    def test_morning_artist_appears_in_morning_key(self) -> None:
        result = self.func(self.df)
        self.assertIn("morning", result)
        morning_df = result["morning"]
        self.assertIsInstance(morning_df, pd.DataFrame)
        self.assertIn("artist", morning_df.columns)
        self.assertIn(
            "MorningBand",
            morning_df["artist"].values,
            "Artist with hour-7 play should appear in morning bucket",
        )

    def test_night_artist_appears_in_night_key(self) -> None:
        result = self.func(self.df)
        self.assertIn("night", result)
        night_df = result["night"]
        self.assertIsInstance(night_df, pd.DataFrame)
        self.assertIn("artist", night_df.columns)
        self.assertIn(
            "NightOwl",
            night_df["artist"].values,
            "Artist with hour-22 play should appear in night bucket",
        )

    def test_morning_artist_not_in_night(self) -> None:
        result = self.func(self.df)
        night_df = result["night"]
        self.assertNotIn(
            "MorningBand",
            night_df["artist"].values,
            "Morning artist should not appear in night bucket",
        )

    def test_result_has_plays_column(self) -> None:
        result = self.func(self.df)
        for key in ("morning", "night"):
            if not result[key].empty:
                self.assertIn("plays", result[key].columns)


class TestMorningVsNightArtistsEmpty(unittest.TestCase):
    """Empty DataFrame → both keys present, both DataFrames empty."""

    def test_empty_df_both_keys_present(self) -> None:
        from analysis_utils import get_morning_vs_night_artists

        empty = pd.DataFrame(columns=["timestamp", "artist", "track", "album"])
        result = get_morning_vs_night_artists(empty)
        self.assertIn("morning", result)
        self.assertIn("night", result)

    def test_empty_df_both_dataframes_empty(self) -> None:
        from analysis_utils import get_morning_vs_night_artists

        empty = pd.DataFrame(columns=["timestamp", "artist", "track", "album"])
        result = get_morning_vs_night_artists(empty)
        self.assertIsInstance(result["morning"], pd.DataFrame)
        self.assertIsInstance(result["night"], pd.DataFrame)
        self.assertTrue(result["morning"].empty)
        self.assertTrue(result["night"].empty)


# ---------------------------------------------------------------------------
# get_day_of_week_personality
# ---------------------------------------------------------------------------


class TestDayOfWeekPersonalitySevenRows(unittest.TestCase):
    """Data spanning all 7 days → exactly 7 rows in result."""

    def setUp(self) -> None:
        from analysis_utils import get_day_of_week_personality

        self.func = get_day_of_week_personality

        # 2020-06-01 is a Monday; 2020-06-07 is a Sunday → covers all 7 days
        rows = []
        day_dates = [
            "2020-06-01",  # Monday
            "2020-06-02",  # Tuesday
            "2020-06-03",  # Wednesday
            "2020-06-04",  # Thursday
            "2020-06-05",  # Friday
            "2020-06-06",  # Saturday
            "2020-06-07",  # Sunday
        ]
        for i, date_str in enumerate(day_dates):
            # 3 plays per day, 2 for the same artist to create a top artist
            rows.append(_make_play(f"Artist{i}", date_str, track="Track 1"))
            rows.append(_make_play(f"Artist{i}", date_str, track="Track 2"))
            rows.append(_make_play("OtherArtist", date_str, track="Track 3"))
        self.df = pd.DataFrame(rows)

    def test_seven_rows_returned(self) -> None:
        result = self.func(self.df)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(
            len(result),
            7,
            f"Expected exactly 7 rows (one per day), got {len(result)}",
        )

    def test_required_columns_present(self) -> None:
        result = self.func(self.df)
        for col in ("day_of_week", "top_artist", "play_count", "unique_artists"):
            self.assertIn(col, result.columns, f"Column '{col}' missing from result")


# ---------------------------------------------------------------------------
# get_holiday_musical_identity
# ---------------------------------------------------------------------------


class TestHolidayMusicalIdentityWindow(unittest.TestCase):
    """Play 2 days before a holiday is included; play 10 days before is excluded."""

    def setUp(self) -> None:
        from analysis_utils import get_holiday_musical_identity

        self.func = get_holiday_musical_identity

        # Holiday: Christmas, month=12, day=25
        self.assumptions = {
            "holidays": [
                {
                    "name": "Christmas",
                    "month": 12,
                    "day": 25,
                }
            ]
        }

        # Play 2 days before Christmas 2020 (Dec 23) → within default window_days=3
        inside_ts = _ts("2020-12-23")
        # Play 10 days before Christmas 2020 (Dec 15) → outside window
        outside_ts = _ts("2020-12-15")

        self.df = pd.DataFrame(
            [
                {
                    "timestamp": inside_ts,
                    "artist": "HolidayArtist",
                    "track": "Holiday Song",
                    "album": "Christmas Album",
                },
                {
                    "timestamp": outside_ts,
                    "artist": "OutsideArtist",
                    "track": "Unrelated Song",
                    "album": "Other Album",
                },
            ]
        )

    def test_inside_window_play_included(self) -> None:
        result = self.func(self.df, self.assumptions, window_days=3)
        self.assertIsInstance(result, pd.DataFrame)
        # Christmas row should exist and HolidayArtist should be the top artist
        christmas_rows = result[result["holiday_name"] == "Christmas"]
        self.assertFalse(
            christmas_rows.empty,
            "Expected a Christmas row in the result",
        )
        self.assertEqual(
            christmas_rows.iloc[0]["top_artist"],
            "HolidayArtist",
            "HolidayArtist (2 days before Christmas) should be the top artist",
        )

    def test_outside_window_play_excluded(self) -> None:
        result = self.func(self.df, self.assumptions, window_days=3)
        # OutsideArtist (10 days before) must not appear as top artist for Christmas
        christmas_rows = result[result["holiday_name"] == "Christmas"]
        if not christmas_rows.empty:
            top = christmas_rows.iloc[0]["top_artist"]
            self.assertNotEqual(
                top,
                "OutsideArtist",
                "OutsideArtist (10 days before Christmas) should not be within the 3-day window",
            )

    def test_result_has_required_columns(self) -> None:
        result = self.func(self.df, self.assumptions, window_days=3)
        for col in ("holiday_name", "top_artist", "top_track", "play_count"):
            self.assertIn(col, result.columns, f"Column '{col}' missing from result")


# ---------------------------------------------------------------------------
# Temporal tab smoke test
# ---------------------------------------------------------------------------


class TestTemporalTabSmoke(unittest.TestCase):
    """Temporal tab in render_deep_music should consult seasonal cache and show banner when None."""

    def test_temporal_tab_calls_load_deep_seasonal_cache(self) -> None:
        """render_deep_music must call analysis_utils.load_deep_seasonal_cache() for the Temporal tab."""
        from pages.deep_music import render_deep_music

        # Build minimal cache so sessions tab renders without issue
        session_cache = {"session_stats": []}

        # Create 4 tab context managers matching the current 4-tab layout
        tab_mocks = [MagicMock() for _ in range(4)]
        for tm in tab_mocks:
            tm.__enter__ = MagicMock(return_value=None)
            tm.__exit__ = MagicMock(return_value=False)

        with (
            patch("pages.deep_music.load_deep_sessions_cache", return_value=session_cache),
            patch("analysis_utils.load_deep_personality_cache", return_value=None),
            patch("analysis_utils.load_deep_arcs_cache", return_value=None),
            patch("analysis_utils.load_deep_seasonal_cache", return_value=None) as mock_seasonal,
            patch("pages.deep_music.st") as mock_st,
        ):
            mock_st.tabs.return_value = tab_mocks
            mock_st.stop = MagicMock()

            render_deep_music()

            # The Temporal tab implementation must call load_deep_seasonal_cache()
            mock_seasonal.assert_called_once()

    def test_temporal_tab_name_present(self) -> None:
        """st.tabs must be called with 'Temporal' in its tab name list."""
        from pages.deep_music import render_deep_music

        session_cache = {"session_stats": []}
        tab_mocks = [MagicMock() for _ in range(4)]
        for tm in tab_mocks:
            tm.__enter__ = MagicMock(return_value=None)
            tm.__exit__ = MagicMock(return_value=False)

        with (
            patch("pages.deep_music.load_deep_sessions_cache", return_value=session_cache),
            patch("analysis_utils.load_deep_personality_cache", return_value=None),
            patch("analysis_utils.load_deep_arcs_cache", return_value=None),
            patch("analysis_utils.load_deep_seasonal_cache", return_value=None),
            patch("pages.deep_music.st") as mock_st,
        ):
            mock_st.tabs.return_value = tab_mocks
            mock_st.stop = MagicMock()

            render_deep_music()

            tab_call_args = mock_st.tabs.call_args
            self.assertIsNotNone(tab_call_args, "st.tabs should have been called")
            tab_names = tab_call_args[0][0]
            self.assertIn(
                "Temporal",
                tab_names,
                "Expected 'Temporal' to be one of the tab names",
            )


# ---------------------------------------------------------------------------
# Seasonal calculate step — must call get_holiday_musical_identity and include
# "holiday_identity" key in save_deep_seasonal_cache argument
# ---------------------------------------------------------------------------

_BASE_TS = int(pd.Timestamp("2020-01-01").timestamp())
_DAY = 86400


class TestSeasonalCalculateStepSavesCache(unittest.TestCase):
    """The seasonal calculate step must call get_holiday_musical_identity.

    REVISION test: currently the seasonal branch in _render_deep_analysis_compute
    never calls get_holiday_musical_identity, so "holiday_identity" is absent
    from the dict passed to save_deep_seasonal_cache.  This test must fail until
    the step is fixed.
    """

    def test_seasonal_calculate_step_includes_holiday_identity(self) -> None:
        """_render_deep_analysis_compute must call get_holiday_musical_identity.

        With the Calculate All Deep Analyses button returning True and
        get_holiday_musical_identity patched to return a minimal DataFrame,
        save_deep_seasonal_cache must be called with a dict that contains the
        key "holiday_identity".
        """
        from pages.data_sources import _render_deep_analysis_compute

        # Minimal non-empty DataFrame representing loaded Last.fm data
        fake_df = pd.DataFrame(
            {
                "timestamp": [_BASE_TS, _BASE_TS + _DAY],
                "date_text": pd.to_datetime([_BASE_TS, _BASE_TS + _DAY], unit="s", utc=True),
                "artist": ["Artist A", "Artist B"],
                "track": ["Track 1", "Track 2"],
                "album": ["Album X", "Album Y"],
            }
        )

        # Minimal DataFrame returned by get_holiday_musical_identity
        holiday_df = pd.DataFrame(
            {
                "holiday_name": ["Christmas"],
                "top_artist": ["Holiday Artist"],
                "top_track": ["Holiday Song"],
                "play_count": [5],
            }
        )

        seasonal_save_calls: list[object] = []

        def fake_save_seasonal(data: object, path: str = "") -> None:
            seasonal_save_calls.append(data)

        # Status context manager mock
        status_cm = MagicMock()
        status_cm.__enter__ = MagicMock(return_value=status_cm)
        status_cm.__exit__ = MagicMock(return_value=False)

        col_mock = MagicMock()
        col_mock.caption = MagicMock()

        # Minimal assumptions dict that get_holiday_musical_identity would receive
        minimal_assumptions = {"holidays": [{"name": "Christmas", "month": 12, "day": 25}]}

        patchers = [
            patch("streamlit.subheader"),
            patch("streamlit.write"),
            patch("streamlit.info"),
            patch("streamlit.divider"),
            patch("streamlit.rerun"),
            patch("streamlit.columns", return_value=[col_mock] * 8),
            patch(
                "streamlit.button",
                side_effect=lambda label, **kw: label == "Calculate All Deep Analyses",
            ),
            patch("streamlit.status", return_value=status_cm),
            patch(
                "pages.data_sources.get_deep_analysis_status",
                return_value={
                    "sessions": False,
                    "personality": False,
                    "arcs": False,
                    "seasonal": False,
                    "taste_drift": False,
                    "city_soundtracks": False,
                    "venue_patterns": False,
                    "life_events": False,
                },
            ),
            # Stub _loaded_config in session state so assumptions can be loaded
            patch(
                "streamlit.session_state",
                new_callable=lambda: (
                    lambda: {"_loaded_config": (None, None, "dummy_assumptions.json")}
                ),
            ),
            # Stub load_assumptions so it returns our minimal assumptions dict
            patch(
                "pages.data_sources.load_assumptions",
                return_value=minimal_assumptions,
            ),
            # Stub all other steps
            patch("analysis_utils.detect_listening_sessions", return_value=fake_df),
            patch("analysis_utils.get_session_stats", return_value=pd.DataFrame()),
            patch("analysis_utils.save_deep_sessions_cache", return_value=None),
            patch("analysis_utils.get_gini_coefficient", return_value=0.4),
            patch(
                "analysis_utils.get_monthly_new_artist_rate",
                return_value=pd.DataFrame({"month": [], "new_artists": []}),
            ),
            patch("analysis_utils.get_loyalty_score", return_value=0.6),
            patch(
                "analysis_utils.get_comfort_ratio",
                return_value=pd.DataFrame(
                    {"month": [], "familiar_plays": [], "new_plays": [], "comfort_ratio": []}
                ),
            ),
            patch(
                "analysis_utils.get_album_sequence_depth",
                return_value=pd.DataFrame({"artist": [], "album": [], "deep_listen_count": []}),
            ),
            patch("analysis_utils.save_deep_personality_cache", return_value=None),
            patch(
                "analysis_utils.get_all_artist_arcs",
                return_value=pd.DataFrame(
                    {
                        "artist": [],
                        "arc_type": [],
                        "discovery_date": [],
                        "peak_month": [],
                        "last_play": [],
                        "total_plays": [],
                        "peak_plays": [],
                        "peak_ratio": [],
                    }
                ),
            ),
            patch("analysis_utils.save_deep_arcs_cache", return_value=None),
            # The key patches for the seasonal step
            patch(
                "analysis_utils.get_seasonal_artist_affinity",
                return_value=pd.DataFrame(
                    {"artist": [], "season": [], "affinity_score": [], "play_count": []}
                ),
            ),
            patch(
                "analysis_utils.get_morning_vs_night_artists",
                return_value={
                    "morning": pd.DataFrame({"artist": [], "plays": []}),
                    "night": pd.DataFrame({"artist": [], "plays": []}),
                },
            ),
            patch(
                "analysis_utils.get_day_of_week_personality",
                return_value=pd.DataFrame(
                    {
                        "day_of_week": [],
                        "top_artist": [],
                        "play_count": [],
                        "unique_artists": [],
                    }
                ),
            ),
            # Instrument get_holiday_musical_identity to capture calls
            patch(
                "analysis_utils.get_holiday_musical_identity",
                return_value=holiday_df,
            ),
            # Instrument save_deep_seasonal_cache to capture its argument
            patch(
                "analysis_utils.save_deep_seasonal_cache",
                side_effect=fake_save_seasonal,
            ),
            patch("analysis_utils.save_deep_taste_drift_cache", return_value=None),
            patch("analysis_utils.save_deep_city_soundtracks_cache", return_value=None),
            patch("analysis_utils.save_deep_venue_patterns_cache", return_value=None),
            patch("analysis_utils.save_deep_life_events_cache", return_value=None),
        ]
        for p in patchers:
            p.start()
        try:
            _render_deep_analysis_compute(fake_df)
        finally:
            for p in patchers:
                p.stop()

        self.assertGreater(
            len(seasonal_save_calls),
            0,
            "save_deep_seasonal_cache was never called — the seasonal compute step did not run.",
        )

        saved = seasonal_save_calls[0]
        self.assertIsInstance(
            saved,
            dict,
            f"save_deep_seasonal_cache was called with a non-dict argument: {type(saved)}",
        )
        self.assertIn(
            "holiday_identity",
            saved,
            "save_deep_seasonal_cache was called without a 'holiday_identity' key. "
            "The seasonal step must call get_holiday_musical_identity and include its "
            "result in the dict passed to save_deep_seasonal_cache.",
        )


if __name__ == "__main__":
    unittest.main()
