"""Tests for the Check-in Insights page (``pages/places.py::render_checkin_insights``).

These tests exercise the wiring of a new "Source" filter (Swarm vs. Google
Timeline vs. All) into ``render_checkin_insights()``. The filter's own pure
logic (``core.source_filter.get_source_options`` /
``core.source_filter.filter_by_source``) is covered independently by
``tests/test_source_filter.py`` (Subtask 3) — that module does not exist yet
(Subtask 3 has not been implemented), so here we mock those two names at the
point ``pages.places`` will import them (``pages.places.get_source_options`` /
``pages.places.filter_by_source``), using ``create=True`` since the attributes
do not exist on the module until the coder wires the import in. This lets us
test the *integration* (does ``render_checkin_insights`` call these functions
correctly and thread their results through to the HTML export and the
country/city breakdowns) without depending on Subtask 3's implementation
existing yet.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from pages.places import render_checkin_insights


def _make_mixed_source_swarm_df() -> pd.DataFrame:
    """4-row swarm_df: 2 rows tagged "swarm", 2 tagged "google_timeline".

    Reykjavik/Iceland and Berlin/Germany are unique to "swarm"; London/UK and
    Paris/France are unique to "google_timeline" — so presence/absence
    assertions on country/city are meaningful, not just row counts.
    """
    return pd.DataFrame(
        {
            "city": ["Reykjavik", "Berlin", "London", "Paris"],
            "country": ["Iceland", "Germany", "UK", "France"],
            "source_id": ["swarm", "swarm", "google_timeline", "google_timeline"],
            "lat": [64.13, 52.52, 51.51, 48.85],
            "lng": [-21.82, 13.40, -0.13, 2.35],
        }
    )


def _swarm_only_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Return only the rows tagged "swarm" — mimics a correct filter_by_source."""
    return df[df["source_id"] == "swarm"].reset_index(drop=True)


def _make_col_mock() -> MagicMock:
    return MagicMock(
        __enter__=MagicMock(return_value=MagicMock()),
        __exit__=MagicMock(return_value=False),
    )


def _cols_side_effect(*args, **kwargs):
    """Return the right number of column mocks based on the call argument."""
    n = args[0] if args else 1
    count = len(n) if isinstance(n, (list, tuple)) else int(n)
    return [_make_col_mock() for _ in range(count)]


# ---------------------------------------------------------------------------
# Empty-state regression guard — must remain unchanged (AC #4)
# ---------------------------------------------------------------------------


class TestRenderCheckinInsightsEmptyState(unittest.TestCase):
    """Zero behavior change for the no-data case: no new selectbox is ever shown."""

    @patch("streamlit.selectbox")
    @patch("streamlit.info")
    @patch("streamlit.header")
    def test_none_swarm_df_shows_info_and_skips_selectbox(
        self, mock_hdr: MagicMock, mock_info: MagicMock, mock_sel: MagicMock
    ) -> None:
        with patch("streamlit.session_state", {"swarm_df": None}):
            render_checkin_insights()
        mock_info.assert_called_once()
        mock_sel.assert_not_called()

    @patch("streamlit.selectbox")
    @patch("streamlit.info")
    @patch("streamlit.header")
    def test_empty_swarm_df_shows_info_and_skips_selectbox(
        self, mock_hdr: MagicMock, mock_info: MagicMock, mock_sel: MagicMock
    ) -> None:
        with patch("streamlit.session_state", {"swarm_df": pd.DataFrame()}):
            render_checkin_insights()
        mock_info.assert_called_once()
        mock_sel.assert_not_called()


# ---------------------------------------------------------------------------
# Source filter wiring
# ---------------------------------------------------------------------------


class TestRenderCheckinInsightsSourceFilter(unittest.TestCase):
    @patch("pages.places.render_share_button")
    @patch("pages.places.build_checkin_insights_html")
    @patch("pages.places.filter_by_source", create=True)
    @patch("pages.places.get_source_options", create=True)
    @patch("pages.places.px")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.slider")
    @patch("streamlit.columns")
    @patch("streamlit.subheader")
    @patch("streamlit.selectbox")
    @patch("streamlit.header")
    def test_selectbox_populated_from_get_source_options(
        self,
        mock_hdr: MagicMock,
        mock_sel: MagicMock,
        mock_sub: MagicMock,
        mock_cols: MagicMock,
        mock_slider: MagicMock,
        mock_df: MagicMock,
        mock_plotly: MagicMock,
        mock_px: MagicMock,
        mock_get_options: MagicMock,
        mock_filter: MagicMock,
        mock_html: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        swarm_df = _make_mixed_source_swarm_df()
        mock_get_options.return_value = ["All", "Google Timeline", "Swarm"]
        mock_sel.return_value = "All"
        mock_filter.side_effect = lambda df, label: df
        mock_cols.side_effect = _cols_side_effect
        mock_slider.return_value = 20

        with patch("streamlit.session_state", {"swarm_df": swarm_df}):
            render_checkin_insights()

        mock_get_options.assert_called_once()
        pd.testing.assert_frame_equal(mock_get_options.call_args[0][0], swarm_df)

        source_calls = [c for c in mock_sel.call_args_list if c.args and c.args[0] == "Source"]
        self.assertEqual(len(source_calls), 1)
        self.assertEqual(source_calls[0].args[1], ["All", "Google Timeline", "Swarm"])

    @patch("pages.places.render_share_button")
    @patch("pages.places.build_checkin_insights_html")
    @patch("pages.places.filter_by_source", create=True)
    @patch("pages.places.get_source_options", create=True)
    @patch("pages.places.px")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.slider")
    @patch("streamlit.columns")
    @patch("streamlit.subheader")
    @patch("streamlit.selectbox")
    @patch("streamlit.header")
    def test_swarm_only_filter_narrows_country_and_city_breakdowns(
        self,
        mock_hdr: MagicMock,
        mock_sel: MagicMock,
        mock_sub: MagicMock,
        mock_cols: MagicMock,
        mock_slider: MagicMock,
        mock_df: MagicMock,
        mock_plotly: MagicMock,
        mock_px: MagicMock,
        mock_get_options: MagicMock,
        mock_filter: MagicMock,
        mock_html: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        swarm_df = _make_mixed_source_swarm_df()
        filtered = _swarm_only_rows(swarm_df)
        mock_get_options.return_value = ["All", "Google Timeline", "Swarm"]
        mock_sel.return_value = "Swarm"
        mock_filter.side_effect = lambda df, label: filtered if label == "Swarm" else df
        mock_cols.side_effect = _cols_side_effect
        mock_slider.return_value = 20

        with patch("streamlit.session_state", {"swarm_df": swarm_df}):
            render_checkin_insights()

        # filter_by_source must have been called with the *original* swarm_df
        # and the selected "Swarm" label.
        mock_filter.assert_called_once()
        pd.testing.assert_frame_equal(mock_filter.call_args[0][0], swarm_df)
        self.assertEqual(mock_filter.call_args[0][1], "Swarm")

        # Both px.bar calls (country breakdown, city breakdown) must only see
        # the swarm-tagged rows.
        self.assertEqual(mock_px.bar.call_count, 2)
        country_counts = mock_px.bar.call_args_list[0][0][0]
        city_counts = mock_px.bar.call_args_list[1][0][0]

        self.assertIn("Iceland", country_counts["country"].values)
        self.assertIn("Germany", country_counts["country"].values)
        self.assertNotIn("UK", country_counts["country"].values)
        self.assertNotIn("France", country_counts["country"].values)

        self.assertIn("Reykjavik", city_counts["city"].values)
        self.assertIn("Berlin", city_counts["city"].values)
        self.assertNotIn("London", city_counts["city"].values)
        self.assertNotIn("Paris", city_counts["city"].values)

    @patch("pages.places.render_share_button")
    @patch("pages.places.build_checkin_insights_html")
    @patch("pages.places.filter_by_source", create=True)
    @patch("pages.places.get_source_options", create=True)
    @patch("pages.places.px")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.slider")
    @patch("streamlit.columns")
    @patch("streamlit.subheader")
    @patch("streamlit.selectbox")
    @patch("streamlit.header")
    def test_html_export_receives_filtered_dataframe(
        self,
        mock_hdr: MagicMock,
        mock_sel: MagicMock,
        mock_sub: MagicMock,
        mock_cols: MagicMock,
        mock_slider: MagicMock,
        mock_df: MagicMock,
        mock_plotly: MagicMock,
        mock_px: MagicMock,
        mock_get_options: MagicMock,
        mock_filter: MagicMock,
        mock_html: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        swarm_df = _make_mixed_source_swarm_df()
        filtered = _swarm_only_rows(swarm_df)
        mock_get_options.return_value = ["All", "Google Timeline", "Swarm"]
        mock_sel.return_value = "Swarm"
        mock_filter.side_effect = lambda df, label: filtered if label == "Swarm" else df
        mock_cols.side_effect = _cols_side_effect
        mock_slider.return_value = 20
        mock_html.return_value = "<html></html>"

        with patch("streamlit.session_state", {"swarm_df": swarm_df}):
            render_checkin_insights()

        mock_html.assert_called_once()
        html_arg = mock_html.call_args[0][0]
        pd.testing.assert_frame_equal(
            html_arg.reset_index(drop=True), filtered.reset_index(drop=True)
        )
        self.assertEqual(len(html_arg), 2)

    @patch("pages.places.render_share_button")
    @patch("pages.places.build_checkin_insights_html")
    @patch("pages.places.filter_by_source", create=True)
    @patch("pages.places.get_source_options", create=True)
    @patch("pages.places.px")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.slider")
    @patch("streamlit.columns")
    @patch("streamlit.subheader")
    @patch("streamlit.selectbox")
    @patch("streamlit.header")
    def test_all_selection_keeps_full_dataset(
        self,
        mock_hdr: MagicMock,
        mock_sel: MagicMock,
        mock_sub: MagicMock,
        mock_cols: MagicMock,
        mock_slider: MagicMock,
        mock_df: MagicMock,
        mock_plotly: MagicMock,
        mock_px: MagicMock,
        mock_get_options: MagicMock,
        mock_filter: MagicMock,
        mock_html: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        swarm_df = _make_mixed_source_swarm_df()
        mock_get_options.return_value = ["All", "Google Timeline", "Swarm"]
        mock_sel.return_value = "All"
        # A correct filter_by_source is a no-op passthrough for "All".
        mock_filter.side_effect = lambda df, label: df
        mock_cols.side_effect = _cols_side_effect
        mock_slider.return_value = 20
        mock_html.return_value = "<html></html>"

        with patch("streamlit.session_state", {"swarm_df": swarm_df}):
            render_checkin_insights()

        # The wiring must actually call filter_by_source with "All" — proving
        # this is a real filter call, not a code path that only runs when a
        # specific source is chosen.
        mock_filter.assert_called_once()
        self.assertEqual(mock_filter.call_args[0][1], "All")

        self.assertEqual(mock_px.bar.call_count, 2)
        country_counts = mock_px.bar.call_args_list[0][0][0]
        city_counts = mock_px.bar.call_args_list[1][0][0]

        self.assertEqual(
            set(country_counts["country"].values), {"Iceland", "Germany", "UK", "France"}
        )
        self.assertEqual(
            set(city_counts["city"].values), {"Reykjavik", "Berlin", "London", "Paris"}
        )

        html_arg = mock_html.call_args[0][0]
        self.assertEqual(len(html_arg), 4)

    @patch("pages.places.render_share_button")
    @patch("pages.places.build_checkin_insights_html")
    @patch("pages.places.filter_by_source", create=True)
    @patch("pages.places.get_source_options", create=True)
    @patch("pages.places.px")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.slider")
    @patch("streamlit.columns")
    @patch("streamlit.subheader")
    @patch("streamlit.selectbox")
    @patch("streamlit.info")
    @patch("streamlit.header")
    def test_post_filter_empty_shows_info_and_skips_breakdowns(
        self,
        mock_hdr: MagicMock,
        mock_info: MagicMock,
        mock_sel: MagicMock,
        mock_sub: MagicMock,
        mock_cols: MagicMock,
        mock_slider: MagicMock,
        mock_df: MagicMock,
        mock_plotly: MagicMock,
        mock_px: MagicMock,
        mock_get_options: MagicMock,
        mock_filter: MagicMock,
        mock_html: MagicMock,
        mock_share: MagicMock,
    ) -> None:
        swarm_df = _make_mixed_source_swarm_df()
        empty_same_shape = swarm_df.iloc[0:0]
        mock_get_options.return_value = ["All", "Google Timeline", "Swarm"]
        mock_sel.return_value = "Google Timeline"
        # Simulate a source selection that (in this contrived scenario)
        # narrows the data to zero rows.
        mock_filter.return_value = empty_same_shape
        mock_cols.side_effect = _cols_side_effect
        mock_slider.return_value = 20

        with patch("streamlit.session_state", {"swarm_df": swarm_df}):
            render_checkin_insights()

        # An informative message must be shown for the post-filter-empty case
        # (distinct from the pre-filter empty-state check, since the original
        # swarm_df was non-empty).
        mock_info.assert_called_once()

        # The country/city groupby-driven breakdowns must not have run.
        mock_px.bar.assert_not_called()
        mock_html.assert_not_called()


if __name__ == "__main__":
    unittest.main()
