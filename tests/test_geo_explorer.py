"""Tests for the Geo Explorer page."""

from __future__ import annotations

import datetime
import inspect
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from pages.geo_explorer import (
    _build_city_stats,
    _build_flythrough_filename,
    _spectrum_color,
    build_globe_data,
    render_geo_explorer,
)


def _make_music_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "artist": ["Sigur Ros", "Sigur Ros", "Radiohead", "Radiohead", "Sigur Ros"],
            "track": ["Hoppipolla", "Staralfur", "Creep", "Karma Police", "Festival"],
            "city": ["Reykjavik", "London", "London", "Paris", "Reykjavik"],
            "lat": [64.13, 51.51, 51.51, 48.85, 64.13],
            "lng": [-21.82, -0.13, -0.13, 2.35, -21.82],
            "state": ["IS", "ENG", "ENG", "IDF", "IS"],
            "country": ["Iceland", "UK", "UK", "France", "Iceland"],
            "timestamp": [1609459200, 1609545600, 1609545700, 1609632000, 1609718400],
            "date_text": pd.to_datetime(
                ["2021-01-01", "2021-01-02", "2021-01-02", "2021-01-03", "2021-01-04"]
            ),
        }
    )


def _make_us_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "artist": ["Artist A", "Artist A", "Artist B"],
            "track": ["Track 1", "Track 2", "Track 3"],
            "city": ["Chicago", "Chicago", "New York"],
            "lat": [41.8, 41.8, 40.7],
            "lng": [-87.6, -87.6, -74.0],
            "state": ["IL", "IL", "NY"],
            "country": ["US", "US", "US"],
            "timestamp": [1610000000, 1610000100, 1610000200],
            "date_text": pd.to_datetime(["2021-01-07", "2021-01-07", "2021-01-07"]),
        }
    )


def _make_swarm_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "city": ["Reykjavik", "London"],
            "country": ["Iceland", "UK"],
            "lat": [64.13, 51.51],
            "lng": [-21.82, -0.13],
        }
    )


# ---------------------------------------------------------------------------
# _spectrum_color
# ---------------------------------------------------------------------------


class TestSpectrumColor(unittest.TestCase):
    def test_zero_max_returns_default(self) -> None:
        from components.theme import MAP_COLUMN_DEFAULT_RGBA

        self.assertEqual(_spectrum_color(0.0, 0.0), MAP_COLUMN_DEFAULT_RGBA)

    def test_low_value_is_teal_ish(self) -> None:
        color = _spectrum_color(0.1, 1.0)
        self.assertEqual(len(color), 4)
        # Blue component should be high (teal)
        self.assertGreater(color[2], 100)

    def test_high_value_is_amber_ish(self) -> None:
        color = _spectrum_color(1.0, 1.0)
        self.assertEqual(len(color), 4)
        # Red component should be high (amber)
        self.assertGreater(color[0], 150)

    def test_midpoint_is_in_range(self) -> None:
        color = _spectrum_color(0.5, 1.0)
        for channel in color[:3]:
            self.assertGreaterEqual(channel, 0)
            self.assertLessEqual(channel, 255)


# ---------------------------------------------------------------------------
# _build_flythrough_filename
# ---------------------------------------------------------------------------


class TestBuildFlythroughFilename(unittest.TestCase):
    def test_no_artist_no_dates(self) -> None:
        name = _build_flythrough_filename("All", ())
        self.assertTrue(name.startswith("flythrough_"))
        self.assertTrue(name.endswith(".mp4"))

    def test_includes_artist_when_not_all(self) -> None:
        name = _build_flythrough_filename("Radiohead", ())
        self.assertIn("Radiohead", name)

    def test_includes_dates_when_provided(self) -> None:
        d1 = datetime.date(2021, 1, 1)
        d2 = datetime.date(2021, 12, 31)
        name = _build_flythrough_filename("All", (d1, d2))
        self.assertIn("20210101", name)
        self.assertIn("20211231", name)

    def test_special_chars_in_artist_sanitised(self) -> None:
        name = _build_flythrough_filename("Sigur Rós / Special!", ())
        # Should not raise; special chars replaced with underscores
        self.assertTrue(name.endswith(".mp4"))


# ---------------------------------------------------------------------------
# build_globe_data
# ---------------------------------------------------------------------------


class TestBuildGlobeData(unittest.TestCase):
    def test_returns_expected_columns(self) -> None:
        result = build_globe_data(_make_music_df())
        self.assertEqual(set(result.columns), {"city", "lat", "lng", "Plays"})

    def test_play_count_correct(self) -> None:
        result = build_globe_data(_make_music_df())
        rvk = result[result["city"] == "Reykjavik"]
        self.assertEqual(int(rvk["Plays"].iloc[0]), 2)

    def test_null_lat_excluded(self) -> None:
        df = _make_music_df().copy()
        df.loc[0, "lat"] = None  # type: ignore[call-overload]
        result = build_globe_data(df)
        self.assertTrue(result["lat"].notna().all())

    def test_missing_columns_returns_empty(self) -> None:
        result = build_globe_data(pd.DataFrame({"artist": ["X"]}))
        self.assertTrue(result.empty)

    def test_empty_df_returns_empty(self) -> None:
        result = build_globe_data(pd.DataFrame())
        self.assertTrue(result.empty)


# ---------------------------------------------------------------------------
# render_geo_explorer — smoke tests
# ---------------------------------------------------------------------------


class TestRenderGeoExplorer(unittest.TestCase):
    def _run(self, session: dict) -> None:
        with patch("streamlit.session_state", session):
            render_geo_explorer()

    @patch("streamlit.info")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_no_df_shows_info(
        self, mock_cap: MagicMock, mock_hdr: MagicMock, mock_info: MagicMock
    ) -> None:
        self._run({"df": None, "swarm_df": None})
        mock_info.assert_called_once()

    @patch("streamlit.warning")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_df_without_geo_shows_warning(
        self, mock_cap: MagicMock, mock_hdr: MagicMock, mock_warn: MagicMock
    ) -> None:
        df_no_geo = pd.DataFrame(
            {"artist": ["X"], "track": ["T"], "timestamp": [1], "date_text": ["2021-01-01"]}
        )
        self._run({"df": df_no_geo, "swarm_df": None})
        mock_warn.assert_called_once()

    def _make_col_mock(self) -> MagicMock:
        return MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )

    def _make_pop_mock(self) -> MagicMock:
        return MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )

    def _cols_side_effect(self, *args, **kwargs):
        """Return the right number of column mocks based on the call argument."""
        n = args[0] if args else 1
        count = len(n) if isinstance(n, (list, tuple)) else int(n)
        return [self._make_col_mock() for _ in range(count)]

    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.metric")
    @patch("streamlit.caption")
    @patch("streamlit.radio")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    def test_full_render_2d_map(
        self,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_radio: MagicMock,
        mock_cap: MagicMock,
        mock_metric: MagicMock,
        mock_plotly: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        mock_seg.return_value = "🗺 2D Map"
        mock_sel.return_value = "All"
        mock_radio.return_value = "By Artist"
        mock_cols.side_effect = self._cols_side_effect

        with patch("streamlit.popover", return_value=self._make_pop_mock()):
            with patch("streamlit.pills", return_value=["Scrobbles"]):
                with patch("streamlit.date_input", return_value=()):
                    self._run({"df": _make_music_df(), "swarm_df": None})

        mock_hdr.assert_called_with("Geo Explorer")
        mock_plotly.assert_called()

    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.container")
    @patch("streamlit.subheader")
    @patch("streamlit.dataframe")
    @patch("streamlit.caption")
    @patch("streamlit.radio")
    @patch("streamlit.number_input")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    def test_table_view_dispatches(
        self,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_num: MagicMock,
        mock_radio: MagicMock,
        mock_cap: MagicMock,
        mock_df: MagicMock,
        mock_sub: MagicMock,
        mock_container: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        mock_seg.return_value = "📋 Table"
        mock_sel.return_value = "All"
        # Radios: "Show" (By Artist/By City), "Sort by"
        mock_radio.side_effect = ["By Artist", "Plays"]
        mock_num.return_value = 1
        mock_cols.side_effect = self._cols_side_effect
        mock_container.return_value = self._make_col_mock()

        with patch("streamlit.popover", return_value=self._make_pop_mock()):
            with patch("streamlit.pills", return_value=["Scrobbles"]):
                with patch("streamlit.date_input", return_value=()):
                    self._run({"df": _make_music_df(), "swarm_df": None})

        mock_df.assert_called()

    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.caption")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    def test_us_states_view_dispatches(
        self,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_cap: MagicMock,
        mock_df: MagicMock,
        mock_plotly: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        mock_seg.return_value = "🇺🇸 US States"

        # Artist selectbox should return "All"; state detail selectbox should skip
        def _sel_side_effect(label, *a, **kw):
            if "Artist" in str(label):
                return "All"
            return "— select a state —"

        mock_sel.side_effect = _sel_side_effect
        mock_cols.side_effect = self._cols_side_effect

        with patch("streamlit.popover", return_value=self._make_pop_mock()):
            with patch("streamlit.pills", return_value=["Scrobbles"]):
                with patch("streamlit.date_input", return_value=()):
                    self._run({"df": _make_us_df(), "swarm_df": None})

        mock_plotly.assert_called()


def _make_atlas_df() -> pd.DataFrame:
    """Minimal listening-history DataFrame with geo columns for Atlas tests."""
    return pd.DataFrame(
        {
            "artist": ["Artist A", "Artist B", "Artist A", "Artist C", "Artist A"],
            "album": ["Album 1", "Album 2", "Album 1", "Album 3", "Album 1"],
            "track": ["Track 1", "Track 2", "Track 3", "Track 4", "Track 5"],
            "timestamp": [1610000000, 1610000100, 1610000200, 1610003600, 1610007200],
            "date_text": pd.to_datetime(
                [
                    "2021-01-07 10:00",
                    "2021-01-07 10:01",
                    "2021-01-07 11:02",
                    "2021-01-07 12:00",
                    "2021-01-07 13:00",
                ]
            ),
            "lat": [64.13, 51.51, 64.13, 48.85, 64.13],
            "lng": [-21.82, -0.13, -21.82, 2.35, -21.82],
            "city": ["Reykjavik", "London", "Reykjavik", "Paris", "Reykjavik"],
            "country": ["Iceland", "UK", "Iceland", "France", "Iceland"],
        }
    )


# ---------------------------------------------------------------------------
# _build_city_stats
# ---------------------------------------------------------------------------


class TestBuildCityStats(unittest.TestCase):
    def test_row_per_city(self) -> None:
        result = _build_city_stats(_make_atlas_df())
        self.assertEqual(len(result), 3)

    def test_required_columns_present(self) -> None:
        result = _build_city_stats(_make_atlas_df())
        for col in (
            "city",
            "country",
            "plays",
            "unique_artists",
            "top_artist",
            "top_track",
            "most_active_hour",
            "first_play",
            "last_play",
        ):
            self.assertIn(col, result.columns, f"Missing column: {col}")

    def test_play_counts_correct(self) -> None:
        result = _build_city_stats(_make_atlas_df()).set_index("city")
        self.assertEqual(result.loc["Reykjavik", "plays"], 3)
        self.assertEqual(result.loc["London", "plays"], 1)
        self.assertEqual(result.loc["Paris", "plays"], 1)

    def test_unique_artists_correct(self) -> None:
        result = _build_city_stats(_make_atlas_df()).set_index("city")
        self.assertEqual(result.loc["Reykjavik", "unique_artists"], 1)

    def test_top_artist_correct(self) -> None:
        result = _build_city_stats(_make_atlas_df()).set_index("city")
        self.assertEqual(result.loc["Reykjavik", "top_artist"], "Artist A")

    def test_most_active_hour_is_valid_int(self) -> None:
        result = _build_city_stats(_make_atlas_df()).set_index("city")
        hour = int(result.loc["Reykjavik", "most_active_hour"])
        self.assertGreaterEqual(hour, 0)
        self.assertLessEqual(hour, 23)

    def test_lat_lng_preserved(self) -> None:
        result = _build_city_stats(_make_atlas_df()).set_index("city")
        self.assertAlmostEqual(float(result.loc["Reykjavik", "lat"]), 64.13, places=1)

    def test_null_country_rows_included(self) -> None:
        df = _make_atlas_df().copy()
        df["country"] = None  # all country values missing
        result = _build_city_stats(df)
        # All three cities should still appear despite missing country
        self.assertEqual(len(result), 3)

    def test_missing_country_column_still_works(self) -> None:
        df = _make_atlas_df().drop(columns=["country"])
        result = _build_city_stats(df)
        self.assertEqual(len(result), 3)

    def test_empty_dataframe_returns_empty(self) -> None:
        self.assertTrue(_build_city_stats(pd.DataFrame()).empty)

    def test_missing_geo_columns_returns_empty(self) -> None:
        df = pd.DataFrame(
            {"artist": ["A"], "track": ["T"], "date_text": pd.to_datetime(["2021-01-01"])}
        )
        self.assertTrue(_build_city_stats(df).empty)


# ---------------------------------------------------------------------------
# 2D map city breakdown — smoke test
# ---------------------------------------------------------------------------


class TestCityBreakdown(unittest.TestCase):
    def _make_col_mock(self) -> MagicMock:
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        return col

    def _make_pop_mock(self) -> MagicMock:
        return MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )

    def _cols_side_effect(self, *args, **kwargs):
        n = args[0] if args else 1
        count = len(n) if isinstance(n, (list, tuple)) else int(n)
        return [self._make_col_mock() for _ in range(count)]

    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.container")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.caption")
    @patch("streamlit.radio")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    def test_by_city_breakdown_renders(
        self,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_radio: MagicMock,
        mock_cap: MagicMock,
        mock_df: MagicMock,
        mock_plotly: MagicMock,
        mock_container: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        mock_seg.return_value = "🗺 2D Map"
        mock_radio.return_value = "By City"
        # First selectbox = artist filter ("All"); second = city detail
        call_count: list[int] = [0]

        def _sel_side_effect(label: str, *a, **kw) -> str:
            call_count[0] += 1
            return "All" if call_count[0] == 1 else "Reykjavik"

        mock_sel.side_effect = _sel_side_effect
        mock_cols.side_effect = self._cols_side_effect
        mock_container.return_value = self._make_col_mock()

        with patch("streamlit.popover", return_value=self._make_pop_mock()):
            with patch("streamlit.pills", return_value=["Scrobbles"]):
                with patch("streamlit.date_input", return_value=()):
                    with patch(
                        "streamlit.session_state", {"df": _make_atlas_df(), "swarm_df": None}
                    ):
                        render_geo_explorer()

        mock_plotly.assert_called()


# ---------------------------------------------------------------------------
# Subtask 4 — source filter wiring (pages/geo_explorer.py x core/source_filter.py)
# ---------------------------------------------------------------------------


def _make_mixed_source_swarm_df() -> pd.DataFrame:
    """Two check-ins, one per source, each with a source-unique lat/lng.

    Reykjavik (64.13, -21.82) is tagged "swarm"; Berlin (52.52, 13.405) is
    tagged "google_timeline" — chosen so presence/absence assertions can check
    specific coordinates, not just row counts (per Test Guidance).
    """
    return pd.DataFrame(
        {
            "city": ["Reykjavik", "Berlin"],
            "country": ["Iceland", "Germany"],
            "lat": [64.13, 52.52],
            "lng": [-21.82, 13.405],
            "source_id": ["swarm", "google_timeline"],
        }
    )


def _stub_filter_by_source(df: pd.DataFrame | None, label: str) -> pd.DataFrame | None:
    """Local stand-in mirroring core.source_filter.filter_by_source's contract.

    Deliberately re-implemented here (not imported from core.source_filter) so
    these tests exercise pages.geo_explorer's *wiring* to the helper,
    independent of core/source_filter.py's own implementation — that module
    has its own dedicated, already-passing test coverage in
    tests/test_source_filter.py (Subtask 3).
    """
    if df is None or df.empty or label == "All":
        return df
    key = "swarm" if label == "Swarm" else "google_timeline"
    return df[df["source_id"] == key].reset_index(drop=True)


class TestGeoExplorerSourceFilterGating(unittest.TestCase):
    """AC #3 — the Source selectbox must never appear when there are no check-ins.

    Both tests here pass today (pre-implementation) by construction: the
    Source selectbox doesn't exist yet, so it is trivially "never called".
    They are regression/gating guards — once Subtask 4 is implemented they
    must keep passing, catching a future coder who wires the selectbox
    without the has_swarm gate (mirroring the has_music-gated Artist
    selectbox's existing pattern).
    """

    def _make_col_mock(self) -> MagicMock:
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        return col

    def _make_pop_mock(self) -> MagicMock:
        return MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )

    def _cols_side_effect(self, *args, **kwargs):
        n = args[0] if args else 1
        count = len(n) if isinstance(n, (list, tuple)) else int(n)
        return [self._make_col_mock() for _ in range(count)]

    def _assert_source_selectbox_never_called(self, mock_sel: MagicMock) -> None:
        for call in mock_sel.call_args_list:
            label = call.args[0] if call.args else None
            self.assertNotEqual(
                label,
                "Source",
                "st.selectbox('Source', ...) must not be called when has_swarm is False",
            )

    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.metric")
    @patch("streamlit.caption")
    @patch("streamlit.radio")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    def test_source_selectbox_not_called_when_swarm_df_none(
        self,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_radio: MagicMock,
        mock_cap: MagicMock,
        mock_metric: MagicMock,
        mock_plotly: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        mock_seg.return_value = "🗺 2D Map"
        mock_sel.return_value = "All"
        mock_radio.return_value = "By Artist"
        mock_cols.side_effect = self._cols_side_effect

        with patch("streamlit.popover", return_value=self._make_pop_mock()):
            with patch("streamlit.pills", return_value=["Scrobbles"]):
                with patch("streamlit.date_input", return_value=()):
                    with patch(
                        "streamlit.session_state", {"df": _make_music_df(), "swarm_df": None}
                    ):
                        render_geo_explorer()

        self._assert_source_selectbox_never_called(mock_sel)

    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.metric")
    @patch("streamlit.caption")
    @patch("streamlit.radio")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    def test_source_selectbox_not_called_when_swarm_df_empty(
        self,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_radio: MagicMock,
        mock_cap: MagicMock,
        mock_metric: MagicMock,
        mock_plotly: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        mock_seg.return_value = "🗺 2D Map"
        mock_sel.return_value = "All"
        mock_radio.return_value = "By Artist"
        mock_cols.side_effect = self._cols_side_effect

        with patch("streamlit.popover", return_value=self._make_pop_mock()):
            with patch("streamlit.pills", return_value=["Scrobbles"]):
                with patch("streamlit.date_input", return_value=()):
                    with patch(
                        "streamlit.session_state",
                        {"df": _make_music_df(), "swarm_df": pd.DataFrame()},
                    ):
                        render_geo_explorer()

        self._assert_source_selectbox_never_called(mock_sel)


class TestGeoExplorer2DMapSourceFilterWiring(unittest.TestCase):
    """AC #1 / #2 — filter_by_source()'s return value (not the raw swarm_df)
    must reach _render_2d_map, regardless of the By Artist / By City breakdown
    radio selection (AC #1's mode-independence claim: the "By City" mode only
    relabels the check-in dots, it doesn't change which rows are filtered).
    """

    def _make_col_mock(self) -> MagicMock:
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        return col

    def _make_pop_mock(self) -> MagicMock:
        return MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )

    def _cols_side_effect(self, *args, **kwargs):
        n = args[0] if args else 1
        count = len(n) if isinstance(n, (list, tuple)) else int(n)
        return [self._make_col_mock() for _ in range(count)]

    def _sel_side_effect_selecting(self, source_label: str):
        def _inner(label, *a, **kw):
            if label == "Source":
                return source_label
            return "All"  # Artist selectbox

        return _inner

    def _run(
        self,
        mock_filter: MagicMock,
        mock_get_opts: MagicMock,
        mock_sel: MagicMock,
        mock_cols: MagicMock,
        mock_radio: MagicMock,
        breakdown_mode: str,
        selected_source: str,
    ) -> None:
        mock_get_opts.return_value = ["All", "Google Timeline", "Swarm"]
        mock_filter.side_effect = _stub_filter_by_source
        mock_sel.side_effect = self._sel_side_effect_selecting(selected_source)
        mock_radio.return_value = breakdown_mode
        mock_cols.side_effect = self._cols_side_effect

        with patch("streamlit.popover", return_value=self._make_pop_mock()):
            with patch("streamlit.pills", return_value=["Scrobbles", "Check-ins"]):
                with patch("streamlit.date_input", return_value=()):
                    with patch(
                        "streamlit.session_state",
                        {"df": _make_music_df(), "swarm_df": _make_mixed_source_swarm_df()},
                    ):
                        render_geo_explorer()

    @patch("pages.geo_explorer._render_2d_map")
    @patch("pages.geo_explorer.filter_by_source", create=True)
    @patch("pages.geo_explorer.get_source_options", create=True)
    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.radio")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_swarm_selection_filters_checkin_dots_by_artist_mode(
        self,
        mock_cap: MagicMock,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_radio: MagicMock,
        mock_share: MagicMock,
        mock_get_opts: MagicMock,
        mock_filter: MagicMock,
        mock_render_2d: MagicMock,
    ) -> None:
        mock_seg.return_value = "🗺 2D Map"
        self._run(
            mock_filter,
            mock_get_opts,
            mock_sel,
            mock_cols,
            mock_radio,
            breakdown_mode="By Artist",
            selected_source="Swarm",
        )

        mock_filter.assert_called_once()
        filter_call_df, filter_call_label = mock_filter.call_args[0]
        self.assertEqual(len(filter_call_df), 2)  # original, unfiltered swarm_df
        self.assertEqual(filter_call_label, "Swarm")

        mock_render_2d.assert_called_once()
        passed_swarm_df = mock_render_2d.call_args[0][1]
        self.assertEqual(len(passed_swarm_df), 1)
        self.assertEqual(passed_swarm_df.iloc[0]["source_id"], "swarm")
        self.assertAlmostEqual(float(passed_swarm_df.iloc[0]["lat"]), 64.13, places=2)
        # The Google-Timeline-only coordinate must be absent from what reaches
        # _render_2d_map's ci groupby.
        self.assertNotIn(52.52, passed_swarm_df["lat"].tolist())

    @patch("pages.geo_explorer._render_2d_map")
    @patch("pages.geo_explorer.filter_by_source", create=True)
    @patch("pages.geo_explorer.get_source_options", create=True)
    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.radio")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_swarm_selection_filters_checkin_dots_by_city_mode(
        self,
        mock_cap: MagicMock,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_radio: MagicMock,
        mock_share: MagicMock,
        mock_get_opts: MagicMock,
        mock_filter: MagicMock,
        mock_render_2d: MagicMock,
    ) -> None:
        mock_seg.return_value = "🗺 2D Map"
        self._run(
            mock_filter,
            mock_get_opts,
            mock_sel,
            mock_cols,
            mock_radio,
            breakdown_mode="By City",
            selected_source="Swarm",
        )

        mock_render_2d.assert_called_once()
        passed_swarm_df = mock_render_2d.call_args[0][1]
        self.assertEqual(len(passed_swarm_df), 1)
        self.assertEqual(passed_swarm_df.iloc[0]["source_id"], "swarm")
        self.assertNotIn(52.52, passed_swarm_df["lat"].tolist())

    @patch("pages.geo_explorer._render_2d_map")
    @patch("pages.geo_explorer.filter_by_source", create=True)
    @patch("pages.geo_explorer.get_source_options", create=True)
    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.radio")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_all_selection_keeps_full_checkin_dataset(
        self,
        mock_cap: MagicMock,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_radio: MagicMock,
        mock_share: MagicMock,
        mock_get_opts: MagicMock,
        mock_filter: MagicMock,
        mock_render_2d: MagicMock,
    ) -> None:
        mock_seg.return_value = "🗺 2D Map"
        self._run(
            mock_filter,
            mock_get_opts,
            mock_sel,
            mock_cols,
            mock_radio,
            breakdown_mode="By Artist",
            selected_source="All",
        )

        # Wiring must exist even for the "All" passthrough case — otherwise
        # this assertion would pass vacuously pre-implementation (the
        # unfiltered swarm_df already has 2 rows), which is not a meaningful
        # RED test. Asserting the call happened proves the filter is actually
        # wired in, not merely coincidentally matching.
        mock_filter.assert_called_once()
        filter_call_df, filter_call_label = mock_filter.call_args[0]
        self.assertEqual(len(filter_call_df), 2)
        self.assertEqual(filter_call_label, "All")

        mock_render_2d.assert_called_once()
        passed_swarm_df = mock_render_2d.call_args[0][1]
        # "All" is a passthrough — row count reaching _render_2d_map must be
        # unchanged from the unfiltered swarm_df (AC #2).
        self.assertEqual(len(passed_swarm_df), 2)

    @patch("pages.geo_explorer._render_2d_map")
    @patch("pages.geo_explorer.filter_by_source", create=True)
    @patch("pages.geo_explorer.get_source_options", create=True)
    @patch("pages.geo_explorer.render_share_button")
    @patch("streamlit.radio")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_selectbox_populated_from_get_source_options(
        self,
        mock_cap: MagicMock,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_radio: MagicMock,
        mock_share: MagicMock,
        mock_get_opts: MagicMock,
        mock_filter: MagicMock,
        mock_render_2d: MagicMock,
    ) -> None:
        mock_seg.return_value = "🗺 2D Map"
        self._run(
            mock_filter,
            mock_get_opts,
            mock_sel,
            mock_cols,
            mock_radio,
            breakdown_mode="By Artist",
            selected_source="All",
        )

        mock_get_opts.assert_called_once()
        passed_df_to_get_opts = mock_get_opts.call_args[0][0]
        self.assertEqual(len(passed_df_to_get_opts), 2)  # unfiltered swarm_df

        source_calls = [c for c in mock_sel.call_args_list if c.args and c.args[0] == "Source"]
        self.assertEqual(len(source_calls), 1)
        self.assertEqual(source_calls[0].args[1], mock_get_opts.return_value)


class TestGeoExplorer3DGlobeSourceFilterWiring(unittest.TestCase):
    """AC #1 — the same filtered swarm_df must reach _render_3d_globe's
    checkin_geo groupby, the second independent consumption point besides
    _render_2d_map."""

    def _make_col_mock(self) -> MagicMock:
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        return col

    def _make_pop_mock(self) -> MagicMock:
        return MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )

    def _cols_side_effect(self, *args, **kwargs):
        n = args[0] if args else 1
        count = len(n) if isinstance(n, (list, tuple)) else int(n)
        return [self._make_col_mock() for _ in range(count)]

    def _sel_side_effect_selecting(self, source_label: str):
        def _inner(label, *a, **kw):
            if label == "Source":
                return source_label
            return "All"

        return _inner

    @patch("pages.geo_explorer._render_3d_globe")
    @patch("pages.geo_explorer.filter_by_source", create=True)
    @patch("pages.geo_explorer.get_source_options", create=True)
    @patch("streamlit.slider")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.segmented_control")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_swarm_selection_filters_checkin_dots_in_3d_view(
        self,
        mock_cap: MagicMock,
        mock_hdr: MagicMock,
        mock_seg: MagicMock,
        mock_cols: MagicMock,
        mock_sel: MagicMock,
        mock_slider: MagicMock,
        mock_get_opts: MagicMock,
        mock_filter: MagicMock,
        mock_render_3d: MagicMock,
    ) -> None:
        mock_seg.return_value = "🌐 3D Globe"
        mock_get_opts.return_value = ["All", "Google Timeline", "Swarm"]
        mock_filter.side_effect = _stub_filter_by_source
        mock_sel.side_effect = self._sel_side_effect_selecting("Swarm")
        mock_cols.side_effect = self._cols_side_effect
        mock_slider.return_value = 5.5

        with patch("streamlit.popover", return_value=self._make_pop_mock()):
            with patch("streamlit.pills", return_value=["Scrobbles", "Check-ins"]):
                with patch("streamlit.date_input", return_value=()):
                    with patch(
                        "streamlit.session_state",
                        {"df": _make_music_df(), "swarm_df": _make_mixed_source_swarm_df()},
                    ):
                        render_geo_explorer()

        mock_filter.assert_called_once()
        filter_call_df, filter_call_label = mock_filter.call_args[0]
        self.assertEqual(len(filter_call_df), 2)
        self.assertEqual(filter_call_label, "Swarm")

        mock_render_3d.assert_called_once()
        passed_swarm_df = mock_render_3d.call_args[0][1]
        self.assertEqual(len(passed_swarm_df), 1)
        self.assertEqual(passed_swarm_df.iloc[0]["source_id"], "swarm")
        self.assertNotIn(52.52, passed_swarm_df["lat"].tolist())


class TestCityStatsRemainMusicDfOnly(unittest.TestCase):
    """AC #5 regression guard — Subtask 4 must not wire swarm_df into the
    scrobble-only city-breakdown call path (_build_city_stats /
    _render_city_breakdown / _render_atlas_city_detail).

    These assertions describe today's (pre-Subtask-4) signatures and are
    expected to keep passing unmodified; they exist to catch a future coder
    who accidentally adds a swarm_df argument to this path, which would
    require columns (artist/track/date_text) swarm_df doesn't have.
    """

    def test_build_city_stats_takes_single_positional_df_argument(self) -> None:
        sig = inspect.signature(_build_city_stats)
        self.assertEqual(list(sig.parameters.keys()), ["df"])

    def test_render_city_breakdown_takes_single_music_df_argument(self) -> None:
        from pages.geo_explorer import _render_city_breakdown

        sig = inspect.signature(_render_city_breakdown)
        self.assertEqual(list(sig.parameters.keys()), ["music_df"])

    def test_render_atlas_city_detail_has_no_swarm_df_argument(self) -> None:
        from pages.geo_explorer import _render_atlas_city_detail

        sig = inspect.signature(_render_atlas_city_detail)
        self.assertNotIn("swarm_df", sig.parameters)


if __name__ == "__main__":
    unittest.main()
