"""Tests for Subtask 2 — Music Personality Metrics.

Covers:
- get_gini_coefficient: perfect inequality, perfect equality, empty DataFrame
- get_monthly_new_artist_rate: first-discovery counting per month
- get_loyalty_score: fraction of old artists still active in top 100
- get_comfort_ratio: familiar vs new plays per month
- get_album_sequence_depth: detecting consecutive same-album runs
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Base timestamp: 2020-01-15 00:00:00 UTC (unix seconds)
BASE_TS = 1_578_873_600  # 2020-01-15
DAY = 86_400  # seconds
MONTH = 30 * DAY  # ~30-day month approximation
YEAR = 365 * DAY


def _ts(year: int, month: int, day: int = 15) -> int:
    """Return a unix timestamp for the given year/month/day (UTC noon)."""
    return int(pd.Timestamp(year=year, month=month, day=day, tz="UTC").timestamp())


def _make_df(
    timestamps: list[int],
    artists: list[str],
    tracks: list[str] | None = None,
    albums: list[str] | None = None,
) -> pd.DataFrame:
    """Build a minimal Last.fm-style DataFrame.

    Args:
        timestamps: Unix epoch seconds for each play.
        artists: Artist name per row.
        tracks: Track name per row; defaults to sequential "Track N".
        albums: Album name per row; defaults to "Album X" for all.

    Returns:
        DataFrame with ``timestamp`` (int), ``date_text`` (datetime, UTC),
        ``artist``, ``track``, ``album`` columns.
    """
    n = len(timestamps)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "date_text": pd.to_datetime(timestamps, unit="s", utc=True),
            "artist": artists,
            "track": tracks if tracks is not None else [f"Track {i}" for i in range(n)],
            "album": albums if albums is not None else ["Album X"] * n,
        }
    )


# ---------------------------------------------------------------------------
# get_gini_coefficient
# ---------------------------------------------------------------------------


class TestGiniPerfectInequality(unittest.TestCase):
    """One artist has all the plays — Gini should be close to 1.0."""

    def test_gini_perfect_inequality(self) -> None:
        """Single artist with all plays yields Gini coefficient ≈ 1.0."""
        from analysis_utils import get_gini_coefficient

        timestamps = [BASE_TS + i * DAY for i in range(10)]
        df = _make_df(timestamps, artists=["Artist A"] * 10)
        result = get_gini_coefficient(df, entity="artist")
        self.assertAlmostEqual(result, 1.0, delta=0.01)


class TestGiniPerfectEquality(unittest.TestCase):
    """N artists with exactly equal plays — Gini should be close to 0.0."""

    def test_gini_perfect_equality(self) -> None:
        """Five artists with equal play counts yields Gini coefficient ≈ 0.0."""
        from analysis_utils import get_gini_coefficient

        artists = ["Artist A", "Artist B", "Artist C", "Artist D", "Artist E"]
        timestamps = [BASE_TS + i * DAY for i in range(5)]
        df = _make_df(timestamps, artists=artists)
        result = get_gini_coefficient(df, entity="artist")
        self.assertAlmostEqual(result, 0.0, delta=0.01)


class TestGiniEmpty(unittest.TestCase):
    """Empty DataFrame should return 0.0 without raising."""

    def test_gini_empty(self) -> None:
        """Empty DataFrame returns 0.0."""
        from analysis_utils import get_gini_coefficient

        df = pd.DataFrame(columns=["timestamp", "date_text", "artist", "track", "album"])
        result = get_gini_coefficient(df, entity="artist")
        self.assertEqual(result, 0.0)


# ---------------------------------------------------------------------------
# get_monthly_new_artist_rate
# ---------------------------------------------------------------------------


class TestMonthlyNewArtistRateDiscoveryMonth(unittest.TestCase):
    """Artists heard for the first time are counted in their discovery month only."""

    def test_monthly_new_artist_rate_discovery_month(self) -> None:
        """3 artists all first heard in Jan; 1 new artist in Feb → Feb has new_artists=1."""
        from analysis_utils import get_monthly_new_artist_rate

        # Jan 2020: Artist A, B, C (all new)
        # Feb 2020: Artist A again (not new) + Artist D (new for first time)
        jan = _ts(2020, 1)
        feb = _ts(2020, 2)
        df = _make_df(
            timestamps=[jan, jan + DAY, jan + 2 * DAY, feb, feb + DAY],
            artists=["Artist A", "Artist B", "Artist C", "Artist A", "Artist D"],
        )
        result = get_monthly_new_artist_rate(df)

        # Should have a row for Feb with new_artists == 1
        self.assertIn("month", result.columns)
        self.assertIn("new_artists", result.columns)

        # Find the February row
        result["month_period"] = result["month"].dt.to_period("M")
        feb_period = pd.Period("2020-02", "M")
        feb_rows = result[result["month_period"] == feb_period]

        self.assertEqual(len(feb_rows), 1, "Expected exactly one row for February 2020")
        self.assertEqual(
            int(feb_rows.iloc[0]["new_artists"]),
            1,
            "February should have exactly 1 new artist (Artist D)",
        )


# ---------------------------------------------------------------------------
# get_loyalty_score
# ---------------------------------------------------------------------------


class TestLoyaltyScoreAllLoyal(unittest.TestCase):
    """Artists discovered 3+ years ago, all still in top 100 → score = 1.0."""

    def test_loyalty_score_all_loyal(self) -> None:
        """Old artists still in top 100 of recent plays → loyalty score = 1.0."""
        from analysis_utils import get_loyalty_score

        # max timestamp will be 2024-01.
        # "old" artists are discovered > 2 years before 2024-01 → before 2022-01.
        # Put discovery in 2020-01, then have many recent plays in 2024-01.
        old_ts = _ts(2020, 1)
        recent_ts = _ts(2024, 1)

        # 3 old artists each get 1 discovery play in 2020, then 10 plays each in 2024.
        ts_list = [old_ts, old_ts + DAY, old_ts + 2 * DAY] + [
            recent_ts + i * DAY for i in range(30)
        ]
        art_list = ["Artist A", "Artist B", "Artist C"] + (
            ["Artist A"] * 10 + ["Artist B"] * 10 + ["Artist C"] * 10
        )
        df = _make_df(timestamps=ts_list, artists=art_list)

        result = get_loyalty_score(df, min_years_ago=2)
        self.assertAlmostEqual(result, 1.0, delta=0.01)


class TestLoyaltyScoreNoneLoyal(unittest.TestCase):
    """Artists discovered 3+ years ago, none with recent plays → score = 0.0."""

    def test_loyalty_score_none_loyal(self) -> None:
        """Old artists with no recent plays → loyalty score = 0.0."""
        from analysis_utils import get_loyalty_score

        # Old artists discovered in 2018, only played in 2018 (no recent plays)
        # Recent artists (2024) are different artists entirely
        old_ts = _ts(2018, 1)
        recent_ts = _ts(2024, 1)

        old_artists = ["Old Artist A"] * 5 + ["Old Artist B"] * 5
        new_artists = ["New Artist X"] * 10 + ["New Artist Y"] * 10

        ts_list = [old_ts + i * DAY for i in range(10)] + [recent_ts + i * DAY for i in range(20)]
        art_list = old_artists + new_artists

        df = _make_df(timestamps=ts_list, artists=art_list)

        result = get_loyalty_score(df, min_years_ago=2)
        self.assertAlmostEqual(result, 0.0, delta=0.01)


# ---------------------------------------------------------------------------
# get_comfort_ratio
# ---------------------------------------------------------------------------


class TestComfortRatioColumns(unittest.TestCase):
    """Result DataFrame must have required columns."""

    def test_comfort_ratio_columns(self) -> None:
        """get_comfort_ratio returns DataFrame with expected columns."""
        from analysis_utils import get_comfort_ratio

        jan = _ts(2020, 1)
        feb = _ts(2020, 2)
        df = _make_df(
            timestamps=[jan, jan + DAY, feb, feb + DAY],
            artists=["Artist A", "Artist A", "Artist A", "Artist B"],
        )
        result = get_comfort_ratio(df)

        for col in ("month", "familiar_plays", "new_plays", "comfort_ratio"):
            self.assertIn(col, result.columns, f"Missing column: {col}")


# ---------------------------------------------------------------------------
# get_album_sequence_depth
# ---------------------------------------------------------------------------


class TestAlbumSequenceDepthDetectsRun(unittest.TestCase):
    """4 consecutive same-album tracks → 1 deep_listen_count for that album."""

    def test_album_sequence_depth_detects_run(self) -> None:
        """A run of 4 same-album tracks is counted as one deep listen."""
        from analysis_utils import get_album_sequence_depth

        # 4 consecutive tracks from "Album X" by "Artist A"
        df = _make_df(
            timestamps=[BASE_TS + i * 300 for i in range(4)],  # 5-min intervals
            artists=["Artist A"] * 4,
            tracks=["Track 1", "Track 2", "Track 3", "Track 4"],
            albums=["Album X"] * 4,
        )
        result = get_album_sequence_depth(df, min_sequence_length=3)

        self.assertIn("artist", result.columns)
        self.assertIn("album", result.columns)
        self.assertIn("deep_listen_count", result.columns)

        album_x_rows = result[result["album"] == "Album X"]
        self.assertEqual(len(album_x_rows), 1, "Expected one row for Album X")
        self.assertEqual(
            int(album_x_rows.iloc[0]["deep_listen_count"]),
            1,
            "Expected deep_listen_count = 1 for Album X",
        )


class TestAlbumSequenceDepthInterrupted(unittest.TestCase):
    """A run of 2 interrupted by different album is NOT counted (min_sequence_length=3)."""

    def test_album_sequence_depth_interrupted(self) -> None:
        """Run of 2 same-album tracks interrupted by a different album → not counted."""
        from analysis_utils import get_album_sequence_depth

        # Sequence: Album X, Album X, Album Y (interrupts), Album X, Album X
        # → longest Album X run is 2, which is < min_sequence_length=3
        df = _make_df(
            timestamps=[BASE_TS + i * 300 for i in range(5)],
            artists=["Artist A"] * 5,
            tracks=[f"Track {i}" for i in range(5)],
            albums=["Album X", "Album X", "Album Y", "Album X", "Album X"],
        )
        result = get_album_sequence_depth(df, min_sequence_length=3)

        # Album X should not appear in results (no run of length ≥ 3)
        if not result.empty:
            album_x_rows = result[result["album"] == "Album X"]
            if not album_x_rows.empty:
                self.assertEqual(
                    int(album_x_rows.iloc[0]["deep_listen_count"]),
                    0,
                    "Album X had no run of length ≥ 3, so deep_listen_count must be 0",
                )


# ---------------------------------------------------------------------------
# Personality tab — not a stub
# ---------------------------------------------------------------------------


class TestPersonalityTabNotStub(unittest.TestCase):
    """The Personality tab in render_deep_music must render real content, not a stub."""

    def test_personality_tab_not_stub(self) -> None:
        """When personality cache is present, the tab must not show a stub st.info message.

        The tab must call at least one of st.metric, st.bar_chart, or st.dataframe
        (real content), and must NOT call st.info with a message containing "coming"
        or "future update".
        """
        from pages.deep_music import render_deep_music

        # A minimal but valid personality cache payload
        personality_cache = {
            "gini": 0.45,
            "monthly_new_artists": [{"month": "2020-01-01", "new_artists": 3}],
            "loyalty_score": 0.75,
            "comfort_ratio": [
                {
                    "month": "2020-01-01",
                    "familiar_plays": 10,
                    "new_plays": 5,
                    "comfort_ratio": 0.67,
                }
            ],
            "album_depth": [{"artist": "Artist A", "album": "Album X", "deep_listen_count": 2}],
            "album_familiarity": [
                {
                    "month": "2020-01-01",
                    "play_type": "familiar",
                    "artist": "Artist A",
                    "album": "Album X",
                    "plays": 8,
                },
                {
                    "month": "2020-01-01",
                    "play_type": "new",
                    "artist": "New Artist",
                    "album": "Debut Album",
                    "plays": 5,
                },
            ],
        }

        # A minimal valid sessions cache (so the page doesn't stop at sessions banner)
        sessions_cache = {
            "session_stats": [
                {
                    "session_id": 0,
                    "session_start": "2020-01-01T10:00:00+00:00",
                    "session_end": "2020-01-01T10:30:00+00:00",
                    "track_count": 5,
                    "duration_minutes": 30,
                    "hour_of_day": 10,
                    "day_of_week": "Wednesday",
                    "opening_track": "Track 1",
                    "opening_artist": "Artist A",
                }
            ]
        }

        info_calls: list[str] = []
        metric_calls: list[tuple] = []
        bar_chart_calls: list[tuple] = []
        dataframe_calls: list[tuple] = []

        def fake_info(msg: str, **kwargs: object) -> None:
            info_calls.append(str(msg))

        def fake_metric(*args: object, **kwargs: object) -> None:
            metric_calls.append(args)

        def fake_bar_chart(*args: object, **kwargs: object) -> None:
            bar_chart_calls.append(args)

        def fake_dataframe(*args: object, **kwargs: object) -> None:
            dataframe_calls.append(args)

        # Build a tab context manager mock; tabs[0]=Sessions, tabs[1]=Personality,
        # tabs[2]=Temporal — all must be usable as context managers.
        def make_tab_cm() -> MagicMock:
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=cm)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        tab_mocks = [make_tab_cm(), make_tab_cm(), make_tab_cm(), make_tab_cm()]

        # Patch load_deep_personality_cache at the source so pages.deep_music
        # gets the return value whether or not it has been imported yet.
        patchers = [
            patch(
                "pages.deep_music.load_deep_sessions_cache",
                return_value=sessions_cache,
            ),
            patch(
                "analysis_utils.load_deep_personality_cache",
                return_value=personality_cache,
            ),
            patch("streamlit.title"),
            patch("streamlit.subheader"),
            patch("streamlit.markdown"),
            patch("streamlit.stop"),
            patch("streamlit.tabs", return_value=tab_mocks),
            patch("streamlit.info", side_effect=fake_info),
            patch("streamlit.metric", side_effect=fake_metric),
            patch("streamlit.bar_chart", side_effect=fake_bar_chart),
            patch("streamlit.dataframe", side_effect=fake_dataframe),
            patch("streamlit.selectbox", return_value="All"),
            patch("streamlit.columns", return_value=[make_tab_cm(), make_tab_cm()]),
            patch("pages.deep_music._deep_analysis_not_computed_banner"),
            patch(
                "pages.deep_music.get_session_opening_tracks",
                return_value=pd.DataFrame(),
            ),
            patch(
                "pages.deep_music.get_session_time_distribution",
                return_value=pd.DataFrame(),
            ),
        ]
        for p in patchers:
            p.start()
        try:
            render_deep_music()
        finally:
            for p in patchers:
                p.stop()

        # Assert no stub message was shown in the personality tab
        stub_messages = [
            m for m in info_calls if "coming" in m.lower() or "future update" in m.lower()
        ]
        self.assertEqual(
            stub_messages,
            [],
            f"Personality tab showed stub info message(s): {stub_messages}",
        )

        # Assert that at least one real content widget was called
        real_content_called = (
            len(metric_calls) > 0 or len(bar_chart_calls) > 0 or len(dataframe_calls) > 0
        )
        self.assertTrue(
            real_content_called,
            "Expected at least one call to st.metric, st.bar_chart, or st.dataframe "
            "in the Personality tab, but none were found.",
        )


# ---------------------------------------------------------------------------
# Calculate step wires personality functions and saves cache
# ---------------------------------------------------------------------------


class TestPersonalityCalculateStepSavesCache(unittest.TestCase):
    """When the Calculate button is clicked, the personality step must save a cache."""

    def test_personality_calculate_step_saves_cache(self) -> None:
        """_render_deep_analysis_compute with button clicked must call save_deep_personality_cache.

        The personality compute step must call the 5 analysis functions and persist
        results via save_deep_personality_cache, not skip them as placeholders.
        """
        from pages.data_sources import _render_deep_analysis_compute

        # A minimal non-empty DataFrame to represent loaded data
        fake_df = pd.DataFrame(
            {
                "timestamp": [BASE_TS, BASE_TS + DAY],
                "date_text": pd.to_datetime([BASE_TS, BASE_TS + DAY], unit="s", utc=True),
                "artist": ["Artist A", "Artist B"],
                "track": ["Track 1", "Track 2"],
                "album": ["Album X", "Album Y"],
            }
        )

        save_calls: list[object] = []

        def fake_save(data: object, path: str = "") -> None:
            save_calls.append(data)

        # Status context manager mock
        status_cm = MagicMock()
        status_cm.__enter__ = MagicMock(return_value=status_cm)
        status_cm.__exit__ = MagicMock(return_value=False)

        # st.columns returns a list of mocks for the status grid
        col_mock = MagicMock()
        col_mock.caption = MagicMock()

        gini_return = 0.4
        monthly_return = pd.DataFrame({"month": [], "new_artists": []})
        loyalty_return = 0.6
        comfort_return = pd.DataFrame(
            {"month": [], "familiar_plays": [], "new_plays": [], "comfort_ratio": []}
        )
        album_depth_return = pd.DataFrame({"artist": [], "album": [], "deep_listen_count": []})

        # Patch personality functions at analysis_utils level (they may not be
        # imported into pages.data_sources yet — that is exactly what we're testing
        # for).  save_deep_personality_cache is patched at analysis_utils too so
        # that any call path (direct or via import alias) is captured.
        patchers2 = [
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
            patch("analysis_utils.get_gini_coefficient", return_value=gini_return),
            patch(
                "analysis_utils.get_monthly_new_artist_rate",
                return_value=monthly_return,
            ),
            patch("analysis_utils.get_loyalty_score", return_value=loyalty_return),
            patch("analysis_utils.get_comfort_ratio", return_value=comfort_return),
            patch(
                "analysis_utils.get_album_sequence_depth",
                return_value=album_depth_return,
            ),
            patch(
                "analysis_utils.save_deep_personality_cache",
                side_effect=fake_save,
            ),
            patch("analysis_utils.save_deep_sessions_cache", return_value=None),
            patch("analysis_utils.save_deep_arcs_cache", return_value=None),
            patch("analysis_utils.save_deep_seasonal_cache", return_value=None),
            patch("analysis_utils.save_deep_taste_drift_cache", return_value=None),
            patch("analysis_utils.save_deep_city_soundtracks_cache", return_value=None),
            patch("analysis_utils.save_deep_venue_patterns_cache", return_value=None),
            patch("analysis_utils.save_deep_life_events_cache", return_value=None),
            patch("analysis_utils.detect_listening_sessions", return_value=fake_df),
            patch("analysis_utils.get_session_stats", return_value=pd.DataFrame()),
        ]
        for p in patchers2:
            p.start()
        try:
            _render_deep_analysis_compute(fake_df)
        finally:
            for p in patchers2:
                p.stop()

        self.assertGreater(
            len(save_calls),
            0,
            "save_deep_personality_cache was never called. "
            "The personality compute step is still a no-op placeholder.",
        )
        self.assertIsNotNone(
            save_calls[0],
            "save_deep_personality_cache was called with None — must receive real data.",
        )


if __name__ == "__main__":
    unittest.main()
