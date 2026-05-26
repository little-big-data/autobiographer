"""Tests for the Life in Chapters page and the build_life_chapters utility."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from analysis_utils import (
    build_life_chapters,
    compute_vacation_stats,
    detect_trip_periods,
    label_listening_context,
)
from pages.life_in_chapters import (
    _duration_label,
    _format_date_range,
    _render_on_the_road,
    render_life_in_chapters,
)


def _make_df(
    artists: list[str] | None = None,
    dates: list[str] | None = None,
) -> pd.DataFrame:
    """Return a minimal listening-history DataFrame for testing."""
    if artists is None:
        artists = ["Alpha", "Beta", "Alpha", "Gamma", "Delta"]
    if dates is None:
        dates = [
            "2020-03-10",
            "2020-03-15",
            "2020-06-01",
            "2021-01-05",
            "2021-01-20",
        ]
    df = pd.DataFrame(
        {
            "artist": artists,
            "album": [f"Album {a}" for a in artists],
            "track": [f"Track {i}" for i in range(len(artists))],
            "timestamp": list(range(len(artists))),
            "date_text": pd.to_datetime(dates),
        }
    )
    return df


def _make_assumptions(include_trips: bool = True) -> dict:
    """Return a minimal assumptions dict for testing."""
    assumptions: dict = {
        "defaults": {},
        "holidays": [],
        "residency": [
            {
                "start": "2020-01-01",
                "end": "2020-12-31",
                "city": "Reykjavik",
                "country": "Iceland",
            }
        ],
        "trips": [],
    }
    if include_trips:
        assumptions["trips"] = [
            {
                "start": "2021-01-01",
                "end": "2021-03-31",
                "city": "Berlin",
                "country": "Germany",
            }
        ]
    return assumptions


class TestFormatDateRange(unittest.TestCase):
    """Unit tests for the _format_date_range helper."""

    def test_same_year_uses_short_format(self) -> None:
        start = pd.Timestamp("2024-01-15")
        end = pd.Timestamp("2024-03-20")
        result = _format_date_range(start, end)
        self.assertIn("2024", result)
        self.assertIn("Jan", result)
        self.assertIn("Mar", result)

    def test_different_years_uses_month_year(self) -> None:
        start = pd.Timestamp("2023-11-01")
        end = pd.Timestamp("2024-02-28")
        result = _format_date_range(start, end)
        self.assertIn("2023", result)
        self.assertIn("2024", result)


class TestDurationLabel(unittest.TestCase):
    """Unit tests for the _duration_label helper."""

    def test_less_than_one_day(self) -> None:
        start = pd.Timestamp("2024-01-01 08:00")
        end = pd.Timestamp("2024-01-01 10:00")
        self.assertEqual(_duration_label(start, end), "< 1 day")

    def test_single_day(self) -> None:
        start = pd.Timestamp("2024-01-01")
        end = pd.Timestamp("2024-01-01")
        result = _duration_label(start, end)
        self.assertIn("day", result)

    def test_multiple_days(self) -> None:
        start = pd.Timestamp("2024-01-01")
        end = pd.Timestamp("2024-01-20")
        result = _duration_label(start, end)
        self.assertIn("day", result)
        self.assertIn("19", result)

    def test_months(self) -> None:
        start = pd.Timestamp("2024-01-01")
        end = pd.Timestamp("2024-04-30")
        result = _duration_label(start, end)
        self.assertIn("month", result)

    def test_years(self) -> None:
        # 2 years 6 months → uses "yr mo" abbreviated form
        start = pd.Timestamp("2020-01-01")
        end = pd.Timestamp("2022-07-15")
        result = _duration_label(start, end)
        self.assertIn("yr", result)

    def test_exactly_one_year(self) -> None:
        start = pd.Timestamp("2020-01-01")
        end = pd.Timestamp("2020-12-31")
        result = _duration_label(start, end)
        self.assertIn("year", result)


class TestBuildLifeChapters(unittest.TestCase):
    """Unit tests for build_life_chapters in analysis_utils."""

    def test_returns_empty_list_for_empty_df(self) -> None:
        result = build_life_chapters(pd.DataFrame(), _make_assumptions())
        self.assertEqual(result, [])

    def test_returns_empty_list_for_no_assumptions(self) -> None:
        df = _make_df()
        assumptions = {"residency": [], "trips": [], "holidays": [], "defaults": {}}
        result = build_life_chapters(df, assumptions)
        self.assertEqual(result, [])

    def test_returns_one_chapter_per_period(self) -> None:
        df = _make_df()
        assumptions = _make_assumptions(include_trips=True)
        chapters = build_life_chapters(df, assumptions)
        # 1 residency + 1 trip
        self.assertEqual(len(chapters), 2)

    def test_chapters_sorted_chronologically(self) -> None:
        df = _make_df()
        assumptions = _make_assumptions(include_trips=True)
        chapters = build_life_chapters(df, assumptions)
        starts = [c["start"] for c in chapters]
        self.assertEqual(starts, sorted(starts))

    def test_chapter_has_required_keys(self) -> None:
        df = _make_df()
        assumptions = _make_assumptions(include_trips=False)
        chapters = build_life_chapters(df, assumptions)
        required_keys = {
            "label",
            "location",
            "start",
            "end",
            "kind",
            "total_plays",
            "top_artists",
            "top_album",
            "discovery_count",
            "exclusive_artists",
        }
        for chapter in chapters:
            self.assertTrue(required_keys.issubset(chapter.keys()), chapter.keys())

    def test_residency_chapter_has_kind_residency(self) -> None:
        df = _make_df()
        assumptions = _make_assumptions(include_trips=False)
        chapters = build_life_chapters(df, assumptions)
        self.assertEqual(chapters[0]["kind"], "residency")

    def test_trip_chapter_has_kind_trip(self) -> None:
        df = _make_df()
        assumptions = _make_assumptions(include_trips=True)
        chapters = build_life_chapters(df, assumptions)
        trip_chapter = next(c for c in chapters if "Berlin" in c["label"])
        self.assertEqual(trip_chapter["kind"], "trip")

    def test_total_plays_counts_filtered_rows(self) -> None:
        df = _make_df()
        assumptions = _make_assumptions(include_trips=False)
        # Only 2020 data: dates 2020-03-10, 2020-03-15, 2020-06-01
        chapters = build_life_chapters(df, assumptions)
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0]["total_plays"], 3)

    def test_top_artists_respects_limit(self) -> None:
        artists = [f"Artist{i}" for i in range(10)]
        dates = [f"2020-0{i + 1}-01" for i in range(9)] + ["2020-10-01"]
        df = _make_df(artists=artists, dates=dates)
        assumptions = _make_assumptions(include_trips=False)
        chapters = build_life_chapters(df, assumptions)
        self.assertLessEqual(len(chapters[0]["top_artists"]), 5)

    def test_discovery_count_for_first_heard_in_chapter(self) -> None:
        # All plays are in the 2020 residency — every artist is first-heard there
        df = _make_df()
        assumptions = _make_assumptions(include_trips=False)
        chapters = build_life_chapters(df, assumptions)
        # Artists heard in 2020 chapter: Alpha, Beta, Gamma (dates 2020-03-10,
        # 2020-03-15, 2020-06-01) — Delta is in 2021
        self.assertGreater(chapters[0]["discovery_count"], 0)

    def test_zero_plays_chapter_has_empty_top_artists(self) -> None:
        # No plays in the trip period (2021 artists not in df)
        df = _make_df(
            artists=["Alpha", "Beta"],
            dates=["2020-03-10", "2020-03-15"],
        )
        assumptions = _make_assumptions(include_trips=True)
        chapters = build_life_chapters(df, assumptions)
        trip_chapter = next(c for c in chapters if "Berlin" in c["label"])
        self.assertEqual(trip_chapter["total_plays"], 0)
        self.assertEqual(trip_chapter["top_artists"], [])
        self.assertIsNone(trip_chapter["top_album"])

    def test_exclusive_artists_high_concentration(self) -> None:
        # Artist "Solo" appears only in the trip period with many plays
        artists = ["Solo"] * 10 + ["Common"] * 3
        dates = (
            ["2021-01-05"] * 10  # all in trip period
            + ["2020-03-10", "2020-06-01", "2021-01-10"]  # Common across periods
        )
        df = _make_df(artists=artists, dates=dates)
        assumptions = _make_assumptions(include_trips=True)
        chapters = build_life_chapters(df, assumptions, min_plays_exclusive=5)
        trip_chapter = next(c for c in chapters if "Berlin" in c["label"])
        # "Solo" plays 10 out of 10 total — uniqueness = 1.0 >= 0.8
        self.assertIn("Solo", trip_chapter["exclusive_artists"])

    def test_location_includes_city_and_country(self) -> None:
        df = _make_df()
        assumptions = _make_assumptions(include_trips=True)
        chapters = build_life_chapters(df, assumptions)
        residency_chapter = chapters[0]
        self.assertIn("Reykjavik", residency_chapter["location"])
        self.assertIn("Iceland", residency_chapter["location"])

    def test_trip_label_prefixed_with_trip_to(self) -> None:
        df = _make_df()
        assumptions = _make_assumptions(include_trips=True)
        chapters = build_life_chapters(df, assumptions)
        trip_chapter = next(c for c in chapters if "Berlin" in c["label"])
        self.assertTrue(trip_chapter["label"].startswith("Trip to"))

    def test_top_album_is_most_played(self) -> None:
        artists = ["A", "A", "A", "B"]
        dates = ["2020-03-01", "2020-04-01", "2020-05-01", "2020-06-01"]
        df = _make_df(artists=artists, dates=dates)
        # Override albums so "Popular Album" dominates
        df["album"] = ["Popular Album", "Popular Album", "Popular Album", "Other Album"]
        assumptions = _make_assumptions(include_trips=False)
        chapters = build_life_chapters(df, assumptions)
        self.assertEqual(chapters[0]["top_album"], "Popular Album")

    def test_missing_residency_only_trips(self) -> None:
        df = _make_df()
        assumptions = {
            "residency": [],
            "trips": [
                {"start": "2021-01-01", "end": "2021-03-31", "city": "Paris", "country": "France"}
            ],
            "holidays": [],
            "defaults": {},
        }
        chapters = build_life_chapters(df, assumptions)
        self.assertEqual(len(chapters), 1)
        self.assertIn("Paris", chapters[0]["label"])


class TestRenderLifeInChapters(unittest.TestCase):
    """Integration tests for the render_life_in_chapters Streamlit page function."""

    def _make_full_df(self) -> pd.DataFrame:
        """Return a listening DataFrame with 2020 and 2021 data."""
        return _make_df()

    @patch("streamlit.info")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_empty_state_when_no_df(
        self,
        mock_caption: MagicMock,
        mock_header: MagicMock,
        mock_info: MagicMock,
    ) -> None:
        with patch("streamlit.session_state", {"df": None}):
            render_life_in_chapters()
        mock_info.assert_called_once()

    @patch("streamlit.warning")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_warning_when_no_assumptions(
        self,
        mock_caption: MagicMock,
        mock_header: MagicMock,
        mock_warning: MagicMock,
    ) -> None:
        df = self._make_full_df()
        assumptions_no_periods = {
            "residency": [],
            "trips": [],
            "holidays": [],
            "defaults": {},
        }
        with (
            patch("streamlit.session_state", {"df": df, "_loaded_config": None}),
            patch("pages.life_in_chapters.load_assumptions", return_value=assumptions_no_periods),
            patch("pages.life_in_chapters.load_detected_trips_cache", return_value=[]),
        ):
            render_life_in_chapters()
        mock_warning.assert_called_once()

    @patch("streamlit.button")
    @patch("streamlit.metric")
    @patch("streamlit.columns")
    @patch("streamlit.expander")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    @patch("streamlit.divider")
    @patch("streamlit.markdown")
    @patch("streamlit.subheader")
    @patch("streamlit.container")
    @patch("streamlit.slider")
    def test_renders_chapters_with_data(
        self,
        mock_slider: MagicMock,
        mock_container: MagicMock,
        mock_subheader: MagicMock,
        mock_markdown: MagicMock,
        mock_divider: MagicMock,
        mock_caption: MagicMock,
        mock_header: MagicMock,
        mock_expander: MagicMock,
        mock_columns: MagicMock,
        mock_metric: MagicMock,
        mock_button: MagicMock,
    ) -> None:
        df = self._make_full_df()
        assumptions = _make_assumptions(include_trips=True)

        expander_cm = MagicMock()
        expander_cm.__enter__ = MagicMock(return_value=expander_cm)
        expander_cm.__exit__ = MagicMock(return_value=False)
        mock_expander.return_value = expander_cm

        container_cm = MagicMock()
        container_cm.__enter__ = MagicMock(return_value=container_cm)
        container_cm.__exit__ = MagicMock(return_value=False)
        mock_container.return_value = container_cm

        col_mock = MagicMock()

        def _columns_side_effect(spec: object) -> list[MagicMock]:
            """Return correct number of column mocks based on the spec argument."""
            if isinstance(spec, int):
                return [col_mock] * spec
            if isinstance(spec, (list, tuple)):
                return [col_mock] * len(spec)
            return [col_mock, col_mock]

        mock_columns.side_effect = _columns_side_effect
        mock_slider.return_value = 0

        with (
            patch("streamlit.session_state", {"df": df, "_loaded_config": (None, None, None)}),
            patch("pages.life_in_chapters.load_assumptions", return_value=assumptions),
            patch("pages.life_in_chapters._render_home_vs_trip_summary"),
            patch("pages.life_in_chapters._render_chapter_map"),
            patch("pages.life_in_chapters.load_detected_trips_cache", return_value=[]),
        ):
            render_life_in_chapters()

        mock_header.assert_called_with("Life in Chapters")
        self.assertTrue(mock_metric.called)

    @patch("streamlit.button")
    @patch("streamlit.metric")
    @patch("streamlit.columns")
    @patch("streamlit.expander")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    @patch("streamlit.divider")
    @patch("streamlit.markdown")
    @patch("streamlit.subheader")
    @patch("streamlit.container")
    @patch("streamlit.slider")
    @patch("streamlit.info")
    def test_filter_hides_low_play_chapters(
        self,
        mock_info: MagicMock,
        mock_slider: MagicMock,
        mock_container: MagicMock,
        mock_subheader: MagicMock,
        mock_markdown: MagicMock,
        mock_divider: MagicMock,
        mock_caption: MagicMock,
        mock_header: MagicMock,
        mock_expander: MagicMock,
        mock_columns: MagicMock,
        mock_metric: MagicMock,
        mock_button: MagicMock,
    ) -> None:
        """Chapters with plays below filter threshold are hidden."""
        df = self._make_full_df()
        assumptions = _make_assumptions(include_trips=True)

        expander_cm = MagicMock()
        expander_cm.__enter__ = MagicMock(return_value=expander_cm)
        expander_cm.__exit__ = MagicMock(return_value=False)
        mock_expander.return_value = expander_cm

        container_cm = MagicMock()
        container_cm.__enter__ = MagicMock(return_value=container_cm)
        container_cm.__exit__ = MagicMock(return_value=False)
        mock_container.return_value = container_cm

        col_mock = MagicMock()

        def _columns_side_effect(spec: object) -> list[MagicMock]:
            if isinstance(spec, int):
                return [col_mock] * spec
            if isinstance(spec, (list, tuple)):
                return [col_mock] * len(spec)
            return [col_mock, col_mock]

        mock_columns.side_effect = _columns_side_effect

        # Set filter high enough to exclude all chapters
        mock_slider.return_value = 9999

        with (
            patch("streamlit.session_state", {"df": df, "_loaded_config": (None, None, None)}),
            patch("pages.life_in_chapters.load_assumptions", return_value=assumptions),
            patch("pages.life_in_chapters._render_home_vs_trip_summary"),
            patch("pages.life_in_chapters._render_chapter_map"),
            patch("pages.life_in_chapters.load_detected_trips_cache", return_value=[]),
        ):
            render_life_in_chapters()

        # st.info should be called because no chapters pass the filter
        mock_info.assert_called()


class TestDetectTripPeriods(unittest.TestCase):
    """Tests for detect_trip_periods."""

    def _assumptions(self, trips: list | None = None) -> dict:
        return {
            "trips": trips or [],
            "defaults": {"city": "Reykjavik, IS"},
        }

    def test_returns_assumption_trips(self) -> None:
        assumptions = self._assumptions(
            [{"start": "2021-03-01", "end": "2021-03-07", "city": "Paris"}]
        )
        periods = detect_trip_periods(assumptions)
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0][0], pd.Timestamp("2021-03-01"))
        self.assertEqual(periods[0][1], pd.Timestamp("2021-03-07"))

    def test_empty_trips_returns_empty(self) -> None:
        self.assertEqual(detect_trip_periods(self._assumptions()), [])

    def test_malformed_trip_skipped(self) -> None:
        assumptions = self._assumptions(
            [
                {"start": "not-a-date", "end": "2021-03-07"},
                {"start": "2021-05-01", "end": "2021-05-05", "city": "London"},
            ]
        )
        periods = detect_trip_periods(assumptions)
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0][0], pd.Timestamp("2021-05-01"))

    def test_swarm_away_days_detected(self) -> None:
        swarm_df = pd.DataFrame(
            {
                "timestamp": [
                    int(pd.Timestamp("2021-04-01").timestamp()),
                    int(pd.Timestamp("2021-04-02").timestamp()),
                    int(pd.Timestamp("2021-04-03").timestamp()),
                ],
                "city": ["Amsterdam", "Amsterdam", "Amsterdam"],
            }
        )
        periods = detect_trip_periods(
            self._assumptions(), swarm_df=swarm_df, home_city="Reykjavik, IS"
        )
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0][0], pd.Timestamp("2021-04-01"))

    def test_single_away_day_excluded(self) -> None:
        swarm_df = pd.DataFrame(
            {
                "timestamp": [int(pd.Timestamp("2021-04-01").timestamp())],
                "city": ["Amsterdam"],
            }
        )
        periods = detect_trip_periods(
            self._assumptions(), swarm_df=swarm_df, home_city="Reykjavik, IS"
        )
        self.assertEqual(periods, [])

    def test_sorted_output(self) -> None:
        assumptions = self._assumptions(
            [
                {"start": "2021-06-10", "end": "2021-06-15", "city": "Tokyo"},
                {"start": "2021-03-01", "end": "2021-03-07", "city": "Paris"},
            ]
        )
        periods = detect_trip_periods(assumptions)
        self.assertLessEqual(periods[0][0], periods[1][0])


class TestLabelListeningContext(unittest.TestCase):
    """Tests for label_listening_context."""

    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "artist": ["A", "B", "C"],
                "date_text": pd.to_datetime(["2021-03-01", "2021-04-01", "2021-05-01"]),
            }
        )

    def test_all_home_when_no_trips(self) -> None:
        df = label_listening_context(self._make_df(), [])
        self.assertTrue((df["context"] == "home").all())

    def test_trip_rows_labelled_trip(self) -> None:
        trips = [(pd.Timestamp("2021-04-01"), pd.Timestamp("2021-04-01"))]
        df = label_listening_context(self._make_df(), trips)
        self.assertEqual(df[df["date_text"] == "2021-04-01"]["context"].iloc[0], "trip")
        self.assertEqual(df[df["date_text"] == "2021-03-01"]["context"].iloc[0], "home")

    def test_empty_df_returns_empty(self) -> None:
        result = label_listening_context(pd.DataFrame(), [])
        self.assertTrue(result.empty)


class TestComputeVacationStats(unittest.TestCase):
    """Tests for compute_vacation_stats."""

    def _make_labeled_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "artist": ["A", "B", "C", "D", "A"],
                "date_text": pd.to_datetime(
                    ["2021-01-01", "2021-01-02", "2021-01-03", "2021-01-04", "2021-01-05"]
                ),
                "context": ["home", "home", "trip", "trip", "home"],
            }
        )

    def test_returns_home_and_trip_keys(self) -> None:
        stats = compute_vacation_stats(self._make_labeled_df())
        self.assertIn("home", stats)
        self.assertIn("trip", stats)

    def test_home_stats_not_empty(self) -> None:
        stats = compute_vacation_stats(self._make_labeled_df())
        self.assertTrue(stats["home"])

    def test_empty_df_returns_empty(self) -> None:
        self.assertEqual(compute_vacation_stats(pd.DataFrame()), {})

    def test_avg_daily_scrobbles_is_numeric(self) -> None:
        stats = compute_vacation_stats(self._make_labeled_df())
        self.assertIsInstance(stats["home"]["avg_daily_scrobbles"], float)


class TestRenderOnTheRoad(unittest.TestCase):
    """Tests for _render_on_the_road."""

    def _make_labeled_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "artist": ["A", "B", "C", "A"],
                "date_text": pd.to_datetime(
                    ["2021-01-05", "2021-01-10", "2021-01-15", "2021-02-01"]
                ),
                "context": ["home", "trip", "trip", "home"],
            }
        )

    @patch("streamlit.metric")
    @patch("streamlit.markdown")
    @patch("streamlit.columns")
    @patch("streamlit.expander")
    def test_renders_expander_when_trip_data_present(
        self,
        mock_expander: MagicMock,
        mock_columns: MagicMock,
        mock_markdown: MagicMock,
        mock_metric: MagicMock,
    ) -> None:
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_expander.return_value = ctx
        mock_columns.return_value = [ctx, ctx]

        df = self._make_labeled_df()
        chapter_trips = [(pd.Timestamp("2021-01-10"), pd.Timestamp("2021-01-15"))]
        _render_on_the_road(
            df,
            pd.Timestamp("2021-01-01"),
            pd.Timestamp("2021-02-28"),
            chapter_trips,
        )
        mock_expander.assert_called_once()

    def test_no_render_when_no_trip_rows_in_chapter(self) -> None:
        df = pd.DataFrame(
            {
                "artist": ["A", "B"],
                "date_text": pd.to_datetime(["2021-01-05", "2021-01-10"]),
                "context": ["home", "home"],
            }
        )
        with patch("streamlit.expander") as mock_expander:
            _render_on_the_road(
                df,
                pd.Timestamp("2021-01-01"),
                pd.Timestamp("2021-01-31"),
                [(pd.Timestamp("2021-01-08"), pd.Timestamp("2021-01-09"))],
            )
            mock_expander.assert_not_called()


class TestDetectedTripsCache(unittest.TestCase):
    """Tests for _load_detected_trips_cache and _save_detected_trips_cache."""

    def test_load_returns_empty_for_missing_file(self) -> None:
        from analysis_utils import load_detected_trips_cache

        result = load_detected_trips_cache("/nonexistent/path/trips.json")
        self.assertEqual(result, [])

    def test_save_and_load_roundtrip(self) -> None:
        import tempfile

        from analysis_utils import load_detected_trips_cache, save_detected_trips_cache

        trips = [{"start": "2021-01-01", "end": "2021-01-07", "city": "Paris"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "trips.json")
            save_detected_trips_cache(trips, path)
            loaded = load_detected_trips_cache(path)
        self.assertEqual(loaded, trips)

    def test_load_returns_empty_for_invalid_json(self) -> None:
        import tempfile

        from analysis_utils import load_detected_trips_cache

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            fh.write("not valid json{")
            path = fh.name
        result = load_detected_trips_cache(path)
        os.unlink(path)
        self.assertEqual(result, [])


class TestHaversineAndDetectTripsFromSwarm(unittest.TestCase):
    """Tests for _haversine_km and detect_trips_from_swarm in analysis_utils."""

    def test_haversine_same_point_is_zero(self) -> None:
        from analysis_utils import _haversine_km  # type: ignore[attr-defined]

        self.assertAlmostEqual(_haversine_km(64.0, -22.0, 64.0, -22.0), 0.0, places=5)

    def test_haversine_known_distance(self) -> None:
        from analysis_utils import _haversine_km  # type: ignore[attr-defined]

        # Reykjavik to London ≈ 1887 km
        dist = _haversine_km(64.13, -21.82, 51.51, -0.13)
        self.assertGreater(dist, 1700)
        self.assertLess(dist, 2100)

    def _assumptions_with_home(self) -> dict:
        return {
            "residency": [
                {
                    "start": "2020-01-01",
                    "end": "2025-12-31",
                    "city": "Reykjavik",
                    "country": "IS",
                    "lat": 64.13,
                    "lng": -21.82,
                }
            ],
            "trips": [],
            "holidays": [],
            "defaults": {"city": "Reykjavik"},
        }

    def test_detect_trips_empty_swarm_returns_empty(self) -> None:
        from analysis_utils import detect_trips_from_swarm

        result = detect_trips_from_swarm(pd.DataFrame(), self._assumptions_with_home())
        self.assertEqual(result, [])

    def test_detect_trips_missing_columns_returns_empty(self) -> None:
        from analysis_utils import detect_trips_from_swarm

        df = pd.DataFrame({"city": ["London"]})
        result = detect_trips_from_swarm(df, self._assumptions_with_home())
        self.assertEqual(result, [])

    def test_detect_trips_finds_away_cluster(self) -> None:
        from analysis_utils import detect_trips_from_swarm

        # Two consecutive check-ins in London (>80 km from Reykjavik)
        swarm_df = pd.DataFrame(
            {
                "timestamp": [
                    int(pd.Timestamp("2021-06-01").timestamp()),
                    int(pd.Timestamp("2021-06-02").timestamp()),
                ],
                "lat": [51.51, 51.52],
                "lng": [-0.13, -0.12],
                "city": ["London", "London"],
                "country": ["GB", "GB"],
            }
        )
        result = detect_trips_from_swarm(swarm_df, self._assumptions_with_home(), radius_km=80)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["city"], "London")
        self.assertIn("start", result[0])
        self.assertIn("end", result[0])


class TestRenderChapterMap(unittest.TestCase):
    """Tests for _render_chapter_map."""

    def _make_chapter(self) -> dict:
        return {
            "label": "Reykjavik",
            "start": pd.Timestamp("2020-01-01"),
            "end": pd.Timestamp("2020-12-31"),
            "lat": 64.13,
            "lng": -21.82,
        }

    def test_skips_when_no_swarm_and_no_lat_lng(self) -> None:
        from pages.life_in_chapters import _render_chapter_map

        chapter = {
            "label": "X",
            "start": pd.Timestamp("2020-01-01"),
            "end": pd.Timestamp("2020-12-31"),
        }
        with patch("streamlit.plotly_chart") as mock_chart:
            _render_chapter_map(chapter, None, "key_0", "#6366f1")
            mock_chart.assert_not_called()

    @patch("streamlit.plotly_chart")
    def test_renders_fallback_marker_when_no_swarm(self, mock_chart: MagicMock) -> None:
        from pages.life_in_chapters import _render_chapter_map

        _render_chapter_map(self._make_chapter(), None, "key_1", "#6366f1")
        mock_chart.assert_called_once()


if __name__ == "__main__":
    unittest.main()
