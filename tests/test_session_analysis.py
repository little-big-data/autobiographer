"""Tests for Subtask 1 — Listening Session Detection.

Covers:
- detect_listening_sessions: basic gap logic, single-track, empty DataFrame
- get_session_stats: required columns, duration calculation
- get_session_opening_tracks: ordering by frequency
- get_session_time_distribution: all hours appear in output
- render_deep_music: smoke test with all st.* mocked
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TS = 1_700_000_000  # arbitrary unix epoch second (2023-11-14 ~22:13 UTC)
MINUTE = 60  # seconds


def _make_df(
    offsets_minutes: list[int], artists: list[str] | None = None, tracks: list[str] | None = None
) -> pd.DataFrame:
    """Build a minimal Last.fm-style DataFrame from minute offsets.

    Args:
        offsets_minutes: Each entry is minutes from BASE_TS for one play.
        artists: Optional artist name per row; defaults to "Artist A" for all.
        tracks: Optional track name per row; defaults to "Track N" pattern.

    Returns:
        DataFrame with ``timestamp`` (unix int), ``date_text`` (datetime),
        ``artist``, ``track``, ``album`` columns.
    """
    n = len(offsets_minutes)
    timestamps = [BASE_TS + m * MINUTE for m in offsets_minutes]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "date_text": pd.to_datetime(timestamps, unit="s", utc=True),
            "artist": artists if artists is not None else ["Artist A"] * n,
            "track": tracks if tracks is not None else [f"Track {i}" for i in range(n)],
            "album": ["Album X"] * n,
        }
    )


# ---------------------------------------------------------------------------
# detect_listening_sessions
# ---------------------------------------------------------------------------


class TestDetectSessionsBasic(unittest.TestCase):
    """test_detect_sessions_basic: gap logic produces correct session boundaries."""

    def test_two_tracks_close_together_same_session(self) -> None:
        """Tracks 10 minutes apart share the same session_id."""
        from analysis_utils import detect_listening_sessions

        df = _make_df([0, 10])
        result = detect_listening_sessions(df, gap_minutes=30)
        self.assertIn("session_id", result.columns)
        self.assertEqual(result.iloc[0]["session_id"], result.iloc[1]["session_id"])

    def test_two_tracks_far_apart_different_sessions(self) -> None:
        """Tracks 40 minutes apart (> 30-min gap) get different session_ids."""
        from analysis_utils import detect_listening_sessions

        df = _make_df([0, 40])
        result = detect_listening_sessions(df, gap_minutes=30)
        self.assertIn("session_id", result.columns)
        self.assertNotEqual(result.iloc[0]["session_id"], result.iloc[1]["session_id"])

    def test_session_ids_are_integers(self) -> None:
        """session_id column must contain integer values."""
        from analysis_utils import detect_listening_sessions

        df = _make_df([0, 10, 50, 60])
        result = detect_listening_sessions(df, gap_minutes=30)
        self.assertTrue(pd.api.types.is_integer_dtype(result["session_id"]))

    def test_session_ids_start_at_zero(self) -> None:
        """First session_id should be 0."""
        from analysis_utils import detect_listening_sessions

        df = _make_df([0, 10])
        result = detect_listening_sessions(df, gap_minutes=30)
        self.assertEqual(result["session_id"].min(), 0)


class TestDetectSessionsSingleTrack(unittest.TestCase):
    """test_detect_sessions_single_track: 1-row DataFrame must not crash."""

    def test_single_track_gets_session_id_zero(self) -> None:
        """A DataFrame with exactly one row returns session_id = 0."""
        from analysis_utils import detect_listening_sessions

        df = _make_df([0])
        result = detect_listening_sessions(df, gap_minutes=30)
        self.assertIn("session_id", result.columns)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["session_id"], 0)


class TestDetectSessionsEmpty(unittest.TestCase):
    """test_detect_sessions_empty: empty DataFrame returns empty with session_id column."""

    def test_empty_df_has_session_id_column(self) -> None:
        """detect_listening_sessions on empty df must return df with session_id column."""
        from analysis_utils import detect_listening_sessions

        df = pd.DataFrame(columns=["timestamp", "date_text", "artist", "track", "album"])
        result = detect_listening_sessions(df, gap_minutes=30)
        self.assertIn("session_id", result.columns)
        self.assertEqual(len(result), 0)


# ---------------------------------------------------------------------------
# get_session_stats
# ---------------------------------------------------------------------------


class TestGetSessionStatsColumns(unittest.TestCase):
    """test_get_session_stats_columns: all required columns present in output."""

    def test_required_columns_present(self) -> None:
        """get_session_stats output must contain every specified column."""
        from analysis_utils import detect_listening_sessions, get_session_stats

        df = _make_df([0, 10, 20])
        df_sessions = detect_listening_sessions(df, gap_minutes=30)
        stats = get_session_stats(df_sessions)

        required = {
            "session_start",
            "session_end",
            "track_count",
            "duration_minutes",
            "hour_of_day",
            "day_of_week",
            "opening_track",
            "opening_artist",
        }
        missing = required - set(stats.columns)
        self.assertSetEqual(missing, set(), f"Missing columns: {missing}")


class TestGetSessionStatsDuration(unittest.TestCase):
    """test_get_session_stats_duration: 3 tracks at 5-min intervals → duration ≈ 10.0."""

    def test_three_tracks_five_min_intervals(self) -> None:
        """Three tracks at t=0, t=5, t=10 minutes → duration_minutes ≈ 10.0."""
        from analysis_utils import detect_listening_sessions, get_session_stats

        df = _make_df([0, 5, 10])
        df_sessions = detect_listening_sessions(df, gap_minutes=30)
        stats = get_session_stats(df_sessions)
        self.assertEqual(len(stats), 1)
        self.assertAlmostEqual(stats.iloc[0]["duration_minutes"], 10.0, places=1)


# ---------------------------------------------------------------------------
# get_session_opening_tracks
# ---------------------------------------------------------------------------


class TestGetSessionOpeningTracksOrder(unittest.TestCase):
    """test_get_session_opening_tracks_order: most common opener ranks first."""

    def test_most_common_opening_track_ranks_first(self) -> None:
        """Opening track repeated across 3 sessions ranks above track appearing once."""
        from analysis_utils import (
            detect_listening_sessions,
            get_session_opening_tracks,
            get_session_stats,
        )

        # Session 1: opener = "Song Alpha"  (t=0..10 min)
        # Session 2: opener = "Song Alpha"  (t=60..70 min — new session after 50-min gap)
        # Session 3: opener = "Song Beta"   (t=120..130 min)
        artists = ["Artist A", "Artist A", "Artist A", "Artist A", "Artist A", "Artist A"]
        tracks = ["Song Alpha", "Track 2", "Song Alpha", "Track 4", "Song Beta", "Track 6"]
        df = _make_df([0, 10, 60, 70, 120, 130], artists=artists, tracks=tracks)
        df_sessions = detect_listening_sessions(df, gap_minutes=30)
        stats = get_session_stats(df_sessions)
        opening_tracks = get_session_opening_tracks(stats, top_n=10)

        self.assertIn("opening_track", opening_tracks.columns)
        self.assertIn("count", opening_tracks.columns)
        self.assertEqual(opening_tracks.iloc[0]["opening_track"], "Song Alpha")

    def test_output_has_required_columns(self) -> None:
        """get_session_opening_tracks must return opening_artist, opening_track, count."""
        from analysis_utils import (
            detect_listening_sessions,
            get_session_opening_tracks,
            get_session_stats,
        )

        df = _make_df([0, 10])
        df_sessions = detect_listening_sessions(df, gap_minutes=30)
        stats = get_session_stats(df_sessions)
        result = get_session_opening_tracks(stats, top_n=10)

        for col in ("opening_artist", "opening_track", "count"):
            self.assertIn(col, result.columns, f"Missing column: {col}")


# ---------------------------------------------------------------------------
# get_session_time_distribution
# ---------------------------------------------------------------------------


class TestGetSessionTimeDistributionAllHours(unittest.TestCase):
    """test_get_session_time_distribution_all_hours: each distinct hour appears in output."""

    def test_sessions_at_different_hours_all_appear(self) -> None:
        """Sessions starting at hour 8 and hour 22 both appear in distribution."""
        from analysis_utils import (
            detect_listening_sessions,
            get_session_stats,
            get_session_time_distribution,
        )

        # Craft two sessions whose start times land on different UTC hours.
        # BASE_TS = 1_700_000_000 → 2023-11-14 22:13:20 UTC
        # Offset 0 → hour 22, offset 600 min (10 h) → hour 08
        df = _make_df([0, 10, 600, 610])
        df_sessions = detect_listening_sessions(df, gap_minutes=30)
        stats = get_session_stats(df_sessions)
        dist = get_session_time_distribution(stats)

        self.assertIn("hour", dist.columns)
        self.assertIn("session_count", dist.columns)

        hours_in_output = set(dist["hour"].tolist())
        # Both session-start hours must appear
        self.assertTrue(
            len(hours_in_output) >= 2, f"Expected ≥2 distinct hours, got: {hours_in_output}"
        )

    def test_all_rows_have_positive_session_count(self) -> None:
        """Every row returned must have session_count ≥ 1."""
        from analysis_utils import (
            detect_listening_sessions,
            get_session_stats,
            get_session_time_distribution,
        )

        df = _make_df([0, 10, 600, 610])
        df_sessions = detect_listening_sessions(df, gap_minutes=30)
        stats = get_session_stats(df_sessions)
        dist = get_session_time_distribution(stats)

        self.assertTrue((dist["session_count"] >= 1).all())


# ---------------------------------------------------------------------------
# render_deep_music smoke test
# ---------------------------------------------------------------------------


class TestRenderDeepMusicSmoke(unittest.TestCase):
    """test_render_deep_music_smoke: render_deep_music runs without raising an exception."""

    def _make_session_stats_dict(self) -> dict:
        """Build a minimal serialisable session_stats dict for the cache."""
        stats_df = pd.DataFrame(
            {
                "session_start": [pd.Timestamp("2023-01-01 10:00", tz="UTC")],
                "session_end": [pd.Timestamp("2023-01-01 10:30", tz="UTC")],
                "track_count": [3],
                "duration_minutes": [30.0],
                "hour_of_day": [10],
                "day_of_week": [0],
                "opening_track": ["Song A"],
                "opening_artist": ["Artist A"],
            }
        )
        # Simulate what the cache would store: orient="records" serialisation
        return {"session_stats": stats_df.to_dict(orient="records")}

    @patch("pages.deep_music.st")
    @patch("pages.deep_music.load_deep_sessions_cache")
    def test_render_deep_music_runs_without_exception(
        self, mock_load_cache: MagicMock, mock_st: MagicMock
    ) -> None:
        """render_deep_music() must not raise when cache returns valid data."""
        # Provide a valid non-None cache so the page proceeds past the banner
        mock_load_cache.return_value = self._make_session_stats_dict()

        # Stub common st.* calls that render_deep_music is likely to make
        mock_st.tabs.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        mock_st.columns.return_value = [MagicMock(), MagicMock()]
        mock_st.session_state = {}
        mock_st.stop = MagicMock()

        from pages.deep_music import render_deep_music

        try:
            render_deep_music()
        except Exception as exc:
            self.fail(f"render_deep_music() raised an exception: {exc}")

    @patch("pages.deep_music.st")
    @patch("pages.deep_music.load_deep_sessions_cache")
    def test_render_deep_music_shows_banner_when_no_cache(
        self, mock_load_cache: MagicMock, mock_st: MagicMock
    ) -> None:
        """render_deep_music() must call st.stop() when cache is None."""
        mock_load_cache.return_value = None
        # st.stop() is not really called; it's mocked.  We check it was invoked.
        mock_st.stop = MagicMock()
        mock_st.info = MagicMock()
        mock_st.session_state = {}

        from pages.deep_music import render_deep_music

        # Should not raise — the banner + st.stop() path must be graceful
        try:
            render_deep_music()
        except Exception as exc:
            self.fail(f"render_deep_music() raised on missing cache: {exc}")

        mock_st.stop.assert_called()


if __name__ == "__main__":
    unittest.main()
