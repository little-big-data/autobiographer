"""Tests for the Geo Explorer page."""

from __future__ import annotations

import datetime
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


if __name__ == "__main__":
    unittest.main()
