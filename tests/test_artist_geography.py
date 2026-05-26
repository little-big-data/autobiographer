"""Tests for the Artist Geography page (issue #62)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from pages.artist_geography import (
    build_artist_city_detail,
    build_artist_city_table,
    build_map_data,
    render_artist_geography,
)


def _make_df() -> pd.DataFrame:
    """Return a minimal listening history DataFrame with geographic data."""
    return pd.DataFrame(
        {
            "artist": ["Sigur Ros", "Sigur Ros", "Radiohead", "Radiohead", "Sigur Ros"],
            "track": ["Hoppipolla", "Staralfur", "Creep", "Karma Police", "Festival"],
            "city": ["Reykjavik", "London", "London", "Paris", "Reykjavik"],
            "lat": [64.13, 51.51, 51.51, 48.85, 64.13],
            "lng": [-21.82, -0.13, -0.13, 2.35, -21.82],
            "timestamp": [1609459200, 1609545600, 1609545700, 1609632000, 1609718400],
            "date_text": pd.to_datetime(
                ["2021-01-01", "2021-01-02", "2021-01-02", "2021-01-03", "2021-01-04"]
            ),
        }
    )


# ---------------------------------------------------------------------------
# build_artist_city_table
# ---------------------------------------------------------------------------


class TestBuildArtistCityTable(unittest.TestCase):
    """Unit tests for the build_artist_city_table helper."""

    def test_returns_expected_columns(self) -> None:
        table = build_artist_city_table(_make_df())
        expected = {"artist", "home_city", "first_play_city", "total_plays", "cities_count"}
        self.assertEqual(set(table.columns), expected)

    def test_sorted_by_total_plays_descending(self) -> None:
        table = build_artist_city_table(_make_df())
        plays = table["total_plays"].tolist()
        self.assertEqual(plays, sorted(plays, reverse=True))

    def test_sigur_ros_home_city_is_reykjavik(self) -> None:
        table = build_artist_city_table(_make_df())
        row = table[table["artist"] == "Sigur Ros"].iloc[0]
        # 2 plays in Reykjavik vs 1 in London → home city is Reykjavik
        self.assertEqual(row["home_city"], "Reykjavik")

    def test_radiohead_first_play_city_is_london(self) -> None:
        table = build_artist_city_table(_make_df())
        row = table[table["artist"] == "Radiohead"].iloc[0]
        # timestamp 1609545700 (London) < 1609632000 (Paris)
        self.assertEqual(row["first_play_city"], "London")

    def test_cities_count_correct(self) -> None:
        table = build_artist_city_table(_make_df())
        sigur = table[table["artist"] == "Sigur Ros"].iloc[0]
        self.assertEqual(sigur["cities_count"], 2)  # Reykjavik + London
        radio = table[table["artist"] == "Radiohead"].iloc[0]
        self.assertEqual(radio["cities_count"], 2)  # London + Paris

    def test_missing_required_columns_returns_empty(self) -> None:
        bad_df = pd.DataFrame({"artist": ["X"]})
        result = build_artist_city_table(bad_df)
        self.assertTrue(result.empty)

    def test_null_city_rows_excluded(self) -> None:
        df = _make_df().copy()
        df.loc[0, "city"] = None  # type: ignore[call-overload]
        # Should not raise; still returns rows for non-null entries
        result = build_artist_city_table(df)
        self.assertFalse(result.empty)

    def test_empty_dataframe_returns_empty(self) -> None:
        result = build_artist_city_table(pd.DataFrame())
        self.assertTrue(result.empty)


# ---------------------------------------------------------------------------
# build_artist_city_detail
# ---------------------------------------------------------------------------


class TestBuildArtistCityDetail(unittest.TestCase):
    """Unit tests for the per-city detail helper."""

    def test_returns_expected_columns(self) -> None:
        result = build_artist_city_detail(_make_df(), "Sigur Ros")
        self.assertEqual(set(result.columns), {"city", "plays", "first_listen"})

    def test_filters_to_single_artist(self) -> None:
        result = build_artist_city_detail(_make_df(), "Sigur Ros")
        # Sigur Ros was heard in Reykjavik (×2) and London (×1)
        self.assertEqual(set(result["city"]), {"Reykjavik", "London"})

    def test_play_count_correct(self) -> None:
        result = build_artist_city_detail(_make_df(), "Sigur Ros")
        rvk = result[result["city"] == "Reykjavik"].iloc[0]
        self.assertEqual(int(rvk["plays"]), 2)

    def test_sorted_by_first_listen_descending(self) -> None:
        # Sigur Ros: London ts=1609545600, Reykjavik ts=1609459200 (older)
        # Descending → London first (more recent first-listen)
        result = build_artist_city_detail(_make_df(), "Sigur Ros")
        self.assertEqual(result.iloc[0]["city"], "London")

    def test_unknown_artist_returns_empty(self) -> None:
        result = build_artist_city_detail(_make_df(), "Unknown")
        self.assertTrue(result.empty)

    def test_missing_columns_returns_empty(self) -> None:
        result = build_artist_city_detail(pd.DataFrame({"artist": ["X"]}), "X")
        self.assertTrue(result.empty)


# ---------------------------------------------------------------------------
# Pagination and sort helpers (exercised at the data layer)
# ---------------------------------------------------------------------------


class TestPaginationAndSort(unittest.TestCase):
    """Verify the sort and pagination logic applied in the table view."""

    def _make_large_df(self) -> pd.DataFrame:
        """Return 30 artists so we can test page boundaries."""
        artists = [f"Artist {i:02d}" for i in range(30)]
        rows = []
        for i, a in enumerate(artists):
            for _ in range(30 - i):  # artist 0 has 30 plays, artist 29 has 1
                rows.append(
                    {
                        "artist": a,
                        "city": "London",
                        "lat": 51.51,
                        "lng": -0.13,
                        "timestamp": 1609459200 + i,
                    }
                )
        return pd.DataFrame(rows)

    def test_plays_order_is_descending(self) -> None:
        table = build_artist_city_table(self._make_large_df())
        plays = table["total_plays"].tolist()
        self.assertEqual(plays, sorted(plays, reverse=True))

    def test_alphabetical_sort(self) -> None:
        table = build_artist_city_table(self._make_large_df())
        alpha = table.sort_values("artist", key=lambda s: s.str.lower())
        self.assertEqual(alpha["artist"].iloc[0], "Artist 00")
        self.assertEqual(alpha["artist"].iloc[-1], "Artist 29")

    def test_page_1_has_25_rows(self) -> None:
        table = build_artist_city_table(self._make_large_df())
        page1 = table.iloc[0:25]
        self.assertEqual(len(page1), 25)

    def test_page_2_has_remaining_rows(self) -> None:
        table = build_artist_city_table(self._make_large_df())
        page2 = table.iloc[25:50]
        self.assertEqual(len(page2), 5)  # 30 artists total → 5 on page 2

    def test_total_pages_calculation(self) -> None:
        from pages.artist_geography import _TABLE_PAGE_SIZE

        for total, expected_pages in [(25, 1), (26, 2), (50, 2), (51, 3)]:
            result = max(1, (total + _TABLE_PAGE_SIZE - 1) // _TABLE_PAGE_SIZE)
            self.assertEqual(result, expected_pages)


# ---------------------------------------------------------------------------
# build_map_data
# ---------------------------------------------------------------------------


class TestBuildMapData(unittest.TestCase):
    """Unit tests for the build_map_data helper."""

    def test_all_artists_returns_all_rows(self) -> None:
        result = build_map_data(_make_df(), "All")
        # Reykjavik×Sigur Ros, London×Sigur Ros, London×Radiohead, Paris×Radiohead
        self.assertEqual(len(result), 4)

    def test_filter_to_single_artist(self) -> None:
        result = build_map_data(_make_df(), "Radiohead")
        self.assertEqual(set(result["artist"].unique()), {"Radiohead"})

    def test_plays_sum_correct_for_reykjavik(self) -> None:
        result = build_map_data(_make_df(), "Sigur Ros")
        rvk = result[result["city"] == "Reykjavik"]
        self.assertEqual(int(rvk["plays"].iloc[0]), 2)

    def test_missing_lat_lng_returns_empty(self) -> None:
        df = pd.DataFrame({"artist": ["X"], "city": ["Y"]})
        result = build_map_data(df, "All")
        self.assertTrue(result.empty)

    def test_null_lat_rows_excluded(self) -> None:
        df = _make_df().copy()
        df.loc[0, "lat"] = None  # type: ignore[call-overload]
        result = build_map_data(df, "All")
        # Row with null lat should be dropped
        self.assertFalse(result.empty)
        self.assertTrue(result["lat"].notna().all())

    def test_unknown_artist_returns_empty(self) -> None:
        result = build_map_data(_make_df(), "Unknown Artist")
        self.assertTrue(result.empty)


# ---------------------------------------------------------------------------
# render_artist_geography (Streamlit integration)
# ---------------------------------------------------------------------------


class TestRenderArtistGeography(unittest.TestCase):
    """Smoke tests for the Streamlit render function."""

    def _run_render(self, session: dict) -> None:
        """Execute render_artist_geography with a patched session_state."""
        with patch("streamlit.session_state", session):
            render_artist_geography()

    @patch("streamlit.info")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_empty_state_no_data(
        self, mock_caption: MagicMock, mock_header: MagicMock, mock_info: MagicMock
    ) -> None:
        self._run_render({"df": None})
        mock_info.assert_called_once()

    @patch("streamlit.warning")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_no_geo_columns_shows_warning(
        self, mock_caption: MagicMock, mock_header: MagicMock, mock_warning: MagicMock
    ) -> None:
        df_no_geo = pd.DataFrame(
            {"artist": ["X"], "city": ["Y"], "timestamp": [1], "date_text": ["2021-01-01"]}
        )
        self._run_render({"df": df_no_geo})
        mock_warning.assert_called_once()

    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.metric")
    @patch("streamlit.subheader")
    @patch("streamlit.info")
    @patch("streamlit.tabs")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.caption")
    @patch("streamlit.header")
    def test_full_render_with_geo_data(
        self,
        mock_header: MagicMock,
        mock_caption: MagicMock,
        mock_columns: MagicMock,
        mock_selectbox: MagicMock,
        mock_tabs: MagicMock,
        mock_info: MagicMock,
        mock_subheader: MagicMock,
        mock_metric: MagicMock,
        mock_df_widget: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        # Set up tabs to return two context manager mocks (map_tab, table_tab)
        map_ctx = MagicMock(
            __enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False)
        )
        table_ctx = MagicMock(
            __enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False)
        )
        mock_tabs.return_value = [map_ctx, table_ctx]
        mock_selectbox.return_value = "All"
        mock_columns.return_value = [MagicMock(), MagicMock(), MagicMock()]

        self._run_render({"df": _make_df()})

        mock_header.assert_called_with("Artist Geography")
        mock_tabs.assert_called_once_with(["Map", "Table"])

    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.metric")
    @patch("streamlit.subheader")
    @patch("streamlit.info")
    @patch("streamlit.tabs")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.caption")
    @patch("streamlit.header")
    def test_artist_filter_applied(
        self,
        mock_header: MagicMock,
        mock_caption: MagicMock,
        mock_columns: MagicMock,
        mock_selectbox: MagicMock,
        mock_tabs: MagicMock,
        mock_info: MagicMock,
        mock_subheader: MagicMock,
        mock_metric: MagicMock,
        mock_df_widget: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        map_ctx = MagicMock(
            __enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False)
        )
        table_ctx = MagicMock(
            __enter__=MagicMock(return_value=None), __exit__=MagicMock(return_value=False)
        )
        mock_tabs.return_value = [map_ctx, table_ctx]
        mock_selectbox.return_value = "Radiohead"
        mock_columns.return_value = [MagicMock(), MagicMock(), MagicMock()]

        # Should not raise even when a specific artist is selected
        self._run_render({"df": _make_df()})
        mock_header.assert_called_with("Artist Geography")


if __name__ == "__main__":
    unittest.main()
