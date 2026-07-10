"""Tests for the Drinking History page (``pages/beer.py::render_beer``), issue #124.

Mocks Streamlit and ``pages.beer._load_untappd_checkins`` so these are fast,
deterministic smoke tests of the page's wiring — the actual data-shaping logic
(top breweries/styles, rating trend/distribution, venue filtering) is covered
independently by ``tests/test_drinking_history.py``.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from core.drinking_history import CHECKIN_COLUMNS
from pages.beer import render_beer


def _ts(dt_str: str) -> int:
    """Return a unix int-seconds timestamp for the given ISO date string."""
    return int(pd.Timestamp(dt_str).timestamp())


def _make_checkins_df() -> pd.DataFrame:
    """A small, already-shaped checkins frame (as build_checkins_frame would return)."""
    return pd.DataFrame(
        {
            "timestamp": [_ts("2023-06-01"), _ts("2023-06-15"), _ts("2023-07-01")],
            "date": pd.to_datetime(["2023-06-01", "2023-06-15", "2023-07-01"]),
            "brewery": ["Test Brewery Co.", "Test Brewery Co.", "Other Brewery"],
            "beer": ["Hazy IPA", "Pilsner", "Pale Ale"],
            "style": ["IPA", "Pilsner", "American Pale Ale"],
            "rating": [4.5, 3.75, float("nan")],
            "venue_name": ["The Tasting Room", "", ""],
            "venue_lat": [40.7128, float("nan"), float("nan")],
            "venue_lng": [-74.0060, float("nan"), float("nan")],
        }
    )


def _empty_checkins_df() -> pd.DataFrame:
    return pd.DataFrame(columns=CHECKIN_COLUMNS)


def _make_col_mock() -> MagicMock:
    return MagicMock(
        __enter__=MagicMock(return_value=MagicMock()),
        __exit__=MagicMock(return_value=False),
    )


def _cols_side_effect(*args, **kwargs):
    n = args[0] if args else 1
    count = len(n) if isinstance(n, (list, tuple)) else int(n)
    return [_make_col_mock() for _ in range(count)]


def _tabs_side_effect(labels, **kwargs):
    return [_make_col_mock() for _ in labels]


# ---------------------------------------------------------------------------
# Empty state — no Untappd data configured/synced yet
# ---------------------------------------------------------------------------


class TestRenderBeerEmptyState(unittest.TestCase):
    @patch("pages.beer._load_untappd_checkins")
    @patch("streamlit.info")
    @patch("streamlit.header")
    def test_empty_checkins_shows_info_and_stops(
        self, mock_hdr: MagicMock, mock_info: MagicMock, mock_load: MagicMock
    ) -> None:
        mock_load.return_value = _empty_checkins_df()
        render_beer()
        mock_info.assert_called_once()

    @patch("pages.beer._load_untappd_checkins")
    @patch("streamlit.info")
    @patch("streamlit.header")
    @patch("streamlit.columns")
    def test_empty_checkins_skips_metrics(
        self,
        mock_cols: MagicMock,
        mock_hdr: MagicMock,
        mock_info: MagicMock,
        mock_load: MagicMock,
    ) -> None:
        mock_load.return_value = _empty_checkins_df()
        render_beer()
        mock_cols.assert_not_called()


# ---------------------------------------------------------------------------
# Full render — populated check-ins
# ---------------------------------------------------------------------------


class TestRenderBeerFullRender(unittest.TestCase):
    @patch("pages.beer._load_untappd_checkins")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.line_chart")
    @patch("streamlit.bar_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.subheader")
    @patch("streamlit.tabs")
    @patch("streamlit.metric")
    @patch("streamlit.columns")
    @patch("streamlit.header")
    def test_full_render_calls_header_and_tabs(
        self,
        mock_hdr: MagicMock,
        mock_cols: MagicMock,
        mock_metric: MagicMock,
        mock_tabs: MagicMock,
        mock_sub: MagicMock,
        mock_df: MagicMock,
        mock_bar: MagicMock,
        mock_line: MagicMock,
        mock_plotly: MagicMock,
        mock_load: MagicMock,
    ) -> None:
        mock_load.return_value = _make_checkins_df()
        mock_cols.side_effect = _cols_side_effect
        mock_tabs.side_effect = _tabs_side_effect

        render_beer()

        mock_hdr.assert_called_with("Drinking History")
        mock_tabs.assert_called_once()
        # Timeline table must be rendered.
        mock_df.assert_called()

    @patch("pages.beer._load_untappd_checkins")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.line_chart")
    @patch("streamlit.bar_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.subheader")
    @patch("streamlit.tabs")
    @patch("streamlit.metric")
    @patch("streamlit.columns")
    @patch("streamlit.header")
    def test_full_render_computes_metrics_without_error(
        self,
        mock_hdr: MagicMock,
        mock_cols: MagicMock,
        mock_metric: MagicMock,
        mock_tabs: MagicMock,
        mock_sub: MagicMock,
        mock_df: MagicMock,
        mock_bar: MagicMock,
        mock_line: MagicMock,
        mock_plotly: MagicMock,
        mock_load: MagicMock,
    ) -> None:
        mock_load.return_value = _make_checkins_df()
        mock_cols.side_effect = _cols_side_effect
        mock_tabs.side_effect = _tabs_side_effect

        render_beer()

        # 3 summary metrics: total check-ins, average rating, unique breweries.
        self.assertEqual(mock_metric.call_count, 3)


# ---------------------------------------------------------------------------
# Venue map tab — graceful handling when no venue coordinates are present
# ---------------------------------------------------------------------------


class TestVenueMapTab(unittest.TestCase):
    @patch("pages.beer._load_untappd_checkins")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.line_chart")
    @patch("streamlit.bar_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.info")
    @patch("streamlit.subheader")
    @patch("streamlit.tabs")
    @patch("streamlit.metric")
    @patch("streamlit.columns")
    @patch("streamlit.header")
    def test_no_venue_data_skips_map_render(
        self,
        mock_hdr: MagicMock,
        mock_cols: MagicMock,
        mock_metric: MagicMock,
        mock_tabs: MagicMock,
        mock_sub: MagicMock,
        mock_info: MagicMock,
        mock_df: MagicMock,
        mock_bar: MagicMock,
        mock_line: MagicMock,
        mock_plotly: MagicMock,
        mock_load: MagicMock,
    ) -> None:
        # No rows have venue coordinates.
        checkins = _make_checkins_df()
        checkins["venue_lat"] = float("nan")
        checkins["venue_lng"] = float("nan")
        mock_load.return_value = checkins
        mock_cols.side_effect = _cols_side_effect
        mock_tabs.side_effect = _tabs_side_effect

        render_beer()

        mock_plotly.assert_not_called()

    @patch("pages.beer._load_untappd_checkins")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.line_chart")
    @patch("streamlit.bar_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.caption")
    @patch("streamlit.subheader")
    @patch("streamlit.tabs")
    @patch("streamlit.metric")
    @patch("streamlit.columns")
    @patch("streamlit.header")
    def test_venue_data_renders_map(
        self,
        mock_hdr: MagicMock,
        mock_cols: MagicMock,
        mock_metric: MagicMock,
        mock_tabs: MagicMock,
        mock_sub: MagicMock,
        mock_cap: MagicMock,
        mock_df: MagicMock,
        mock_bar: MagicMock,
        mock_line: MagicMock,
        mock_plotly: MagicMock,
        mock_load: MagicMock,
    ) -> None:
        mock_load.return_value = _make_checkins_df()
        mock_cols.side_effect = _cols_side_effect
        mock_tabs.side_effect = _tabs_side_effect

        render_beer()

        mock_plotly.assert_called_once()


if __name__ == "__main__":
    unittest.main()
