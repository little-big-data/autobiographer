"""Tests for Subtask 3 — Artist Lifecycle & Obsession Arcs.

Covers:
- get_artist_lifecycle: discovery_date, peak_month
- get_all_artist_arcs: one-hit, perennial, obsession arc types; min_plays filter
- get_top_obsessions: ordering by peak_ratio, empty-obsession case
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


def _make_df(
    artist: str,
    play_dates: list[str],
) -> pd.DataFrame:
    """Build a minimal Last.fm-style DataFrame for a single artist.

    Args:
        artist: Artist name for all rows.
        play_dates: List of ISO date strings (e.g. "2020-01-15") for each play.

    Returns:
        DataFrame with ``timestamp`` (unix int), ``artist``, ``track``, ``album`` columns.
    """
    timestamps = [_ts(d) for d in play_dates]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "artist": artist,
            "track": [f"Track {i}" for i in range(len(play_dates))],
            "album": "Album X",
        }
    )


def _combine(*dfs: pd.DataFrame) -> pd.DataFrame:
    """Concatenate DataFrames and reset index."""
    return pd.concat(list(dfs), ignore_index=True)


# ---------------------------------------------------------------------------
# get_artist_lifecycle
# ---------------------------------------------------------------------------


class TestGetArtistLifecycleDiscovery(unittest.TestCase):
    """test_get_artist_lifecycle_discovery: first play date is discovery_date."""

    def test_discovery_date_is_first_play(self) -> None:
        """Artist with plays in Jan and Feb 2020 → discovery_date is the Jan play's date."""
        from analysis_utils import get_artist_lifecycle

        df = _make_df("Artist A", ["2020-01-15", "2020-02-10", "2020-02-20"])
        result = get_artist_lifecycle(df, "Artist A")

        expected_discovery = pd.Timestamp(_ts("2020-01-15"), unit="s")
        # Normalise to date precision for the comparison
        self.assertEqual(
            result["discovery_date"].date(),
            expected_discovery.date(),
        )


class TestGetArtistLifecyclePeakMonth(unittest.TestCase):
    """test_get_artist_lifecycle_peak_month: month with most plays is peak_month."""

    def test_peak_month_is_february(self) -> None:
        """5 plays in Feb, 2 plays in Jan → peak_month is Feb 2020."""
        from analysis_utils import get_artist_lifecycle

        df = _make_df(
            "Artist A",
            [
                "2020-01-05",
                "2020-01-20",
                "2020-02-01",
                "2020-02-08",
                "2020-02-14",
                "2020-02-21",
                "2020-02-28",
            ],
        )
        result = get_artist_lifecycle(df, "Artist A")

        # peak_month should be a Period or Timestamp in February 2020
        peak = result["peak_month"]
        # Support both Period and Timestamp representations
        if hasattr(peak, "month"):
            self.assertEqual(peak.month, 2)
            self.assertEqual(peak.year, 2020)
        else:
            # Period-like with to_timestamp()
            ts = peak.to_timestamp()
            self.assertEqual(ts.month, 2)
            self.assertEqual(ts.year, 2020)


# ---------------------------------------------------------------------------
# get_all_artist_arcs
# ---------------------------------------------------------------------------


class TestGetAllArtistArcsOneHit(unittest.TestCase):
    """test_get_all_artist_arcs_one_hit: 20 plays concentrated in 1 month → one-hit."""

    def test_arc_type_is_one_hit(self) -> None:
        """20 plays all within January 2020 → arc_type == 'one-hit'."""
        from analysis_utils import get_all_artist_arcs

        play_dates = [f"2020-01-{d:02d}" for d in range(1, 21)]  # 20 plays in Jan
        df = _make_df("One Hit Wonder", play_dates)

        arcs = get_all_artist_arcs(df, min_plays=20)
        row = arcs[arcs["artist"] == "One Hit Wonder"]

        self.assertFalse(row.empty, "Expected 'One Hit Wonder' in arcs output")
        self.assertEqual(row.iloc[0]["arc_type"], "one-hit")


class TestGetAllArtistArcsPerennial(unittest.TestCase):
    """test_get_all_artist_arcs_perennial: plays spread across 10 years → perennial."""

    def test_arc_type_is_perennial(self) -> None:
        """One play per year from 2012–2021 (10 distinct years) → arc_type == 'perennial'."""
        from analysis_utils import get_all_artist_arcs

        play_dates = [f"{year}-06-15" for year in range(2012, 2022)]  # 10 years
        df = _make_df("Evergreen Artist", play_dates)

        arcs = get_all_artist_arcs(df, min_plays=10)
        row = arcs[arcs["artist"] == "Evergreen Artist"]

        self.assertFalse(row.empty, "Expected 'Evergreen Artist' in arcs output")
        self.assertEqual(row.iloc[0]["arc_type"], "perennial")


class TestGetAllArtistArcsObsession(unittest.TestCase):
    """test_get_all_artist_arcs_obsession: big spike then long silence → obsession."""

    def test_arc_type_is_obsession(self) -> None:
        """15 plays in Jan 2019, then silence, then 1 play in Jan 2022 → arc_type == 'obsession'."""
        from analysis_utils import get_all_artist_arcs

        # 15 plays concentrated in January 2019 (the spike)
        spike_dates = [f"2019-01-{d:02d}" for d in range(1, 16)]
        # 1 play 36 months later (well beyond the 6-month gap threshold)
        tail_dates = ["2022-01-10"]

        df = _make_df("Obsession Artist", spike_dates + tail_dates)

        arcs = get_all_artist_arcs(df, min_plays=16)
        row = arcs[arcs["artist"] == "Obsession Artist"]

        self.assertFalse(row.empty, "Expected 'Obsession Artist' in arcs output")
        self.assertEqual(row.iloc[0]["arc_type"], "obsession")


class TestGetAllArtistArcsMinPlaysFilter(unittest.TestCase):
    """test_get_all_artist_arcs_min_plays_filter: artist with 5 plays excluded when min_plays=20."""

    def test_low_play_artist_excluded(self) -> None:
        """Artist with only 5 plays must not appear in result when min_plays=20."""
        from analysis_utils import get_all_artist_arcs

        play_dates = [f"2020-0{m}-15" for m in range(1, 6)]  # 5 plays
        df = _make_df("Tiny Artist", play_dates)

        arcs = get_all_artist_arcs(df, min_plays=20)
        row = arcs[arcs["artist"] == "Tiny Artist"]

        self.assertTrue(row.empty, "Artist with 5 plays should be excluded when min_plays=20")


class TestGetAllArtistArcsColumns(unittest.TestCase):
    """Required columns are present in get_all_artist_arcs output."""

    def test_required_columns_present(self) -> None:
        """Output DataFrame must contain all required columns."""
        from analysis_utils import get_all_artist_arcs

        play_dates = [f"2020-01-{d:02d}" for d in range(1, 21)]
        df = _make_df("Col Check Artist", play_dates)

        arcs = get_all_artist_arcs(df, min_plays=20)

        required = {
            "artist",
            "discovery_date",
            "peak_month",
            "last_play",
            "total_plays",
            "arc_type",
            "peak_plays",
            "peak_ratio",
        }
        missing = required - set(arcs.columns)
        self.assertEqual(missing, set(), f"Missing columns: {missing}")


# ---------------------------------------------------------------------------
# get_top_obsessions
# ---------------------------------------------------------------------------


class TestGetTopObsessionsOrdering(unittest.TestCase):
    """test_get_top_obsessions_ordering: higher peak_ratio ranks first."""

    def test_higher_peak_ratio_ranks_first(self) -> None:
        """Two obsession artists; the one with higher peak_ratio must be first."""
        from analysis_utils import get_top_obsessions

        arc_df = pd.DataFrame(
            {
                "artist": ["Artist Low", "Artist High"],
                "arc_type": ["obsession", "obsession"],
                "peak_ratio": [3.0, 10.0],
                "discovery_date": [pd.Timestamp("2020-01-01")] * 2,
                "peak_month": [pd.Period("2020-01", freq="M")] * 2,
                "last_play": [pd.Timestamp("2022-01-01")] * 2,
                "total_plays": [20, 20],
                "peak_plays": [15, 15],
            }
        )

        result = get_top_obsessions(arc_df, top_n=10)

        self.assertFalse(result.empty, "Result should not be empty")
        self.assertEqual(result.iloc[0]["artist"], "Artist High")
        self.assertEqual(result.iloc[1]["artist"], "Artist Low")


class TestGetTopObsessionsEmptyWhenNoObsessions(unittest.TestCase):
    """test_get_top_obsessions_empty_when_no_obsessions: no obsession arcs → empty DataFrame."""

    def test_returns_empty_dataframe(self) -> None:
        """When no arc has arc_type=='obsession', result is an empty DataFrame without error."""
        from analysis_utils import get_top_obsessions

        arc_df = pd.DataFrame(
            {
                "artist": ["Artist A", "Artist B"],
                "arc_type": ["one-hit", "perennial"],
                "peak_ratio": [2.5, 1.5],
                "discovery_date": [pd.Timestamp("2020-01-01")] * 2,
                "peak_month": [pd.Period("2020-01", freq="M")] * 2,
                "last_play": [pd.Timestamp("2022-01-01")] * 2,
                "total_plays": [20, 20],
                "peak_plays": [15, 15],
            }
        )

        result = get_top_obsessions(arc_df, top_n=10)

        self.assertIsInstance(result, pd.DataFrame)
        self.assertTrue(result.empty, "Expected empty DataFrame when no obsession arcs present")


# ---------------------------------------------------------------------------
# Artist Arcs tab — must exist in deep_music page and not be a stub
# ---------------------------------------------------------------------------


class TestArtistArcsTabNotStub(unittest.TestCase):
    """The Artist Arcs tab must be present in render_deep_music and render real content.

    REVISION test: currently the page only has 3 tabs (Sessions, Personality,
    Temporal) with no Artist Arcs tab — this test must fail until the 4th tab
    is added.
    """

    def test_artist_arcs_tab_not_stub(self) -> None:
        """render_deep_music must expose an 'Artist Arcs' tab that renders arc data.

        When arcs cache is present (non-empty), the tab must call at least one
        chart or table widget (st.dataframe, st.bar_chart, or st.plotly_chart).
        The tab list passed to st.tabs must contain a string with "Artist Arcs"
        (case-insensitive match is not required — exact substring match is fine).
        """
        from pages.deep_music import render_deep_music

        # Minimal valid sessions cache so the page doesn't stop early
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

        # Minimal valid personality cache
        personality_cache = {
            "gini": 0.45,
            "monthly_new_artists": [],
            "loyalty_score": 0.75,
            "comfort_ratio": [],
            "album_depth": [],
        }

        # Minimal valid arcs cache — one obsession artist
        arcs_cache = {
            "arcs": [
                {
                    "artist": "Obsession Artist",
                    "arc_type": "obsession",
                    "discovery_date": "2019-01-01",
                    "peak_month": "2019-01",
                    "last_play": "2022-01-10",
                    "total_plays": 16,
                    "peak_plays": 15,
                    "peak_ratio": 9.5,
                }
            ]
        }

        # Capture tabs() call arguments and widget calls
        tabs_call_args: list[list[str]] = []
        dataframe_calls: list[object] = []
        bar_chart_calls: list[object] = []
        plotly_calls: list[object] = []

        def fake_tabs(tab_names: list[str]) -> list[MagicMock]:
            tabs_call_args.append(list(tab_names))
            # Return enough tab context managers for however many tabs are requested
            cms = []
            for _ in tab_names:
                cm = MagicMock()
                cm.__enter__ = MagicMock(return_value=cm)
                cm.__exit__ = MagicMock(return_value=False)
                cms.append(cm)
            return cms

        def fake_dataframe(*args: object, **kwargs: object) -> None:
            dataframe_calls.append(args)

        def fake_bar_chart(*args: object, **kwargs: object) -> None:
            bar_chart_calls.append(args)

        def fake_plotly_chart(*args: object, **kwargs: object) -> None:
            plotly_calls.append(args)

        patchers = [
            patch("pages.deep_music.load_deep_sessions_cache", return_value=sessions_cache),
            patch(
                "analysis_utils.load_deep_personality_cache",
                return_value=personality_cache,
            ),
            patch("analysis_utils.load_deep_arcs_cache", return_value=arcs_cache),
            patch("streamlit.title"),
            patch("streamlit.subheader"),
            patch("streamlit.markdown"),
            patch("streamlit.metric"),
            patch("streamlit.stop"),
            patch("streamlit.info"),
            patch("streamlit.selectbox", return_value="Obsession Artist"),
            patch("streamlit.tabs", side_effect=fake_tabs),
            patch("streamlit.dataframe", side_effect=fake_dataframe),
            patch("streamlit.bar_chart", side_effect=fake_bar_chart),
            patch("streamlit.plotly_chart", side_effect=fake_plotly_chart),
            patch("pages.deep_music._deep_analysis_not_computed_banner"),
            patch("pages.deep_music.get_session_opening_tracks", return_value=pd.DataFrame()),
            patch("pages.deep_music.get_session_time_distribution", return_value=pd.DataFrame()),
        ]
        for p in patchers:
            p.start()
        try:
            render_deep_music()
        finally:
            for p in patchers:
                p.stop()

        # Assert st.tabs was called with a list containing "Artist Arcs"
        self.assertTrue(
            len(tabs_call_args) > 0,
            "st.tabs was never called — render_deep_music did not reach tab rendering.",
        )
        all_tab_names = tabs_call_args[0] if tabs_call_args else []
        self.assertTrue(
            any("Artist Arcs" in name for name in all_tab_names),
            f"'Artist Arcs' not found in tab names passed to st.tabs: {all_tab_names}. "
            "The Artist Arcs tab must be added as a 4th tab to pages/deep_music.py.",
        )

        # Assert that at least one chart/table widget was rendered (real content)
        real_content = len(dataframe_calls) + len(bar_chart_calls) + len(plotly_calls)
        self.assertGreater(
            real_content,
            0,
            "No chart or table widget (st.dataframe, st.bar_chart, st.plotly_chart) "
            "was called. The Artist Arcs tab must render real content from arcs_cache.",
        )


# ---------------------------------------------------------------------------
# Arcs calculate step — must call get_all_artist_arcs and save non-empty result
# ---------------------------------------------------------------------------


class TestArcsCalculateStepSavesCache(unittest.TestCase):
    """The arcs calculate step in _render_deep_analysis_compute must call get_all_artist_arcs.

    REVISION test: currently the arcs branch calls save_deep_arcs_cache({}) with
    an empty dict without computing anything — this test must fail until the step
    is implemented.
    """

    def test_arcs_calculate_step_saves_cache(self) -> None:
        """_render_deep_analysis_compute must call get_all_artist_arcs and save its result.

        With get_all_artist_arcs patched to return a minimal DataFrame and the
        Calculate All Deep Analyses button returning True, save_deep_arcs_cache
        must be called with a non-empty argument (not an empty dict {}).
        """
        from pages.data_sources import _render_deep_analysis_compute

        # Minimal DataFrame representing loaded Last.fm data
        fake_df = pd.DataFrame(
            {
                "timestamp": [_ts("2020-01-01"), _ts("2020-01-02")],
                "date_text": pd.to_datetime(
                    [_ts("2020-01-01"), _ts("2020-01-02")], unit="s", utc=True
                ),
                "artist": ["Artist A", "Artist B"],
                "track": ["Track 1", "Track 2"],
                "album": ["Album X", "Album Y"],
            }
        )

        # Minimal arcs DataFrame returned by get_all_artist_arcs
        arcs_df = pd.DataFrame(
            {
                "artist": ["Artist A"],
                "arc_type": ["obsession"],
                "discovery_date": [pd.Timestamp("2020-01-01")],
                "peak_month": [pd.Period("2020-01", freq="M")],
                "last_play": [pd.Timestamp("2022-01-10")],
                "total_plays": [16],
                "peak_plays": [15],
                "peak_ratio": [9.5],
            }
        )

        arcs_save_calls: list[object] = []

        def fake_save_arcs(data: object, path: str = "") -> None:
            arcs_save_calls.append(data)

        # Status context manager mock
        status_cm = MagicMock()
        status_cm.__enter__ = MagicMock(return_value=status_cm)
        status_cm.__exit__ = MagicMock(return_value=False)

        col_mock = MagicMock()
        col_mock.caption = MagicMock()

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
            # Stub out all other steps so only arcs is exercised
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
            # The key patch: get_all_artist_arcs returns a real DataFrame
            patch("analysis_utils.get_all_artist_arcs", return_value=arcs_df),
            # Instrument save_deep_arcs_cache to capture calls
            patch("analysis_utils.save_deep_arcs_cache", side_effect=fake_save_arcs),
            patch("analysis_utils.save_deep_seasonal_cache", return_value=None),
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
            len(arcs_save_calls),
            0,
            "save_deep_arcs_cache was never called. "
            "The arcs compute step must call get_all_artist_arcs and save its result.",
        )

        saved = arcs_save_calls[0]
        self.assertNotEqual(
            saved,
            {},
            "save_deep_arcs_cache was called with an empty dict {}. "
            "The arcs step must compute real data via get_all_artist_arcs and pass "
            "a non-empty result (e.g. .to_dict(orient='records')) to save_deep_arcs_cache.",
        )
