"""Unit tests for the Autobiographer dashboard pages."""

from __future__ import annotations

import os
import shutil
import unittest
from unittest.mock import ANY, MagicMock, patch

import pandas as pd

from components.plugin_config import (
    load_config_into_session_state as _load_config_into_session_state,
)
from components.plugin_config import (
    path_input as _path_input,
)
from components.plugin_config import (
    render_plugin_config_fields as _render_plugin_config,
)
from core.local_settings import LocalSettings
from pages.insights import render_insights_and_narrative
from pages.life_in_chapters import render_life_in_chapters
from pages.music import (
    _filter_by_date,
    _pct_delta,
    _prev_period,
    render_activity_over_time,
    render_daily_chart,
    render_entity_columns,
    render_listening_clock,
    render_music,
    render_plays_growth,
    render_quick_facts,
    render_top_charts,
)
from pages.overview import render_overview
from pages.places import render_spatial_analysis
from visualize import main


class TestPathInput(unittest.TestCase):
    """Tests for the _path_input and _render_plugin_config sidebar helpers."""

    def _make_st_mocks(
        self, mock_columns: MagicMock, mock_button: MagicMock
    ) -> tuple[MagicMock, MagicMock]:
        """Return (col1, col2) column mocks with browse button not clicked."""
        col1, col2 = MagicMock(), MagicMock()
        mock_columns.return_value = [col1, col2]
        mock_button.return_value = False
        col2.button.return_value = False
        return col1, col2

    @patch("components.plugin_config._TKINTER_AVAILABLE", True)
    @patch("streamlit.columns")
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.session_state", {})
    def test_path_input_uses_default_when_no_session_state(
        self, mock_button: MagicMock, mock_columns: MagicMock
    ) -> None:
        self._make_st_mocks(mock_columns, mock_button)
        result = _path_input(
            "My Label", "test_key", on_persist=lambda _: None, default="/some/default"
        )
        self.assertEqual(result, "/some/default")

    @patch("components.plugin_config._TKINTER_AVAILABLE", True)
    @patch("streamlit.columns")
    @patch("streamlit.button", return_value=False)
    def test_path_input_returns_existing_session_state(
        self, mock_button: MagicMock, mock_columns: MagicMock
    ) -> None:
        self._make_st_mocks(mock_columns, mock_button)
        with patch("streamlit.session_state", {"test_key2": "/existing/path"}):
            result = _path_input(
                "My Label", "test_key2", on_persist=lambda _: None, default="/default"
            )
        self.assertEqual(result, "/existing/path")

    @patch("components.plugin_config._TKINTER_AVAILABLE", False)
    @patch("streamlit.text_input")
    @patch("streamlit.session_state", {})
    def test_path_input_fallback_without_tkinter(self, mock_text_input: MagicMock) -> None:
        # Without tkinter, renders a plain st.text_input (no browse button).
        _path_input("Label", "nontk_key", on_persist=lambda _: None, default="")
        mock_text_input.assert_called_once()
        call_kwargs = mock_text_input.call_args
        self.assertEqual(call_kwargs[1]["key"], "nontk_key")

    @patch("components.plugin_config._TKINTER_AVAILABLE", True)
    @patch("streamlit.columns")
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.session_state", {})
    def test_render_plugin_config_collects_all_fields(
        self, mock_button: MagicMock, mock_columns: MagicMock
    ) -> None:
        col1, col2 = MagicMock(), MagicMock()
        mock_columns.return_value = [col1, col2]
        col2.button.return_value = False

        fields = [
            {"key": "data_path", "label": "CSV file", "type": "file_path"},
        ]
        with patch("components.plugin_config.settings") as mock_settings:
            mock_settings.set_plugin_value = MagicMock()
            result = _render_plugin_config("myplugin", fields)
        self.assertIn("data_path", result)


class TestSidebarDataLoading(unittest.TestCase):
    """Tests for render_sidebar and ensure_data_loaded session state management."""

    def test_render_sidebar_sets_df_none_when_no_file_path(self) -> None:
        """render_sidebar sets df=None when no Last.fm file is configured."""
        plugin_cls = MagicMock(return_value=MagicMock())
        plugin_cls.return_value.get_config_fields.return_value = [
            {"key": "data_path", "label": "CSV", "type": "file_path"}
        ]
        session: dict = {}
        with (
            patch("streamlit.session_state", session),
            patch("components.sidebar.REGISTRY", {"lastfm": plugin_cls}),
            patch("components.sidebar.load_builtin_plugins"),
            patch("components.sidebar.load_config_into_session_state"),
            patch("components.sidebar.get_plugin_config_from_session", return_value={}),
        ):
            from components.sidebar import render_sidebar

            render_sidebar()

        self.assertIsNone(session.get("df"))

    def test_render_sidebar_publishes_current_config(self) -> None:
        """render_sidebar stores _current_config so ensure_data_loaded can read it."""
        plugin_cls = MagicMock(return_value=MagicMock())
        plugin_cls.return_value.get_config_fields.return_value = [
            {"key": "data_path", "label": "CSV", "type": "file_path"}
        ]
        session: dict = {}
        with (
            patch("streamlit.session_state", session),
            patch("components.sidebar.REGISTRY", {"lastfm": plugin_cls}),
            patch("components.sidebar.load_builtin_plugins"),
            patch("components.sidebar.load_config_into_session_state"),
            patch("components.sidebar.get_plugin_config_from_session", return_value={}),
        ):
            from components.sidebar import render_sidebar

            render_sidebar()

        self.assertIn("_current_config", session)

    def test_render_sidebar_skips_load_when_already_loaded(self) -> None:
        """render_sidebar skips _load_data_with_progress when session cache is valid."""
        import pandas as pd

        raw_df = pd.DataFrame({"date_text": pd.to_datetime(["2024-01-01"])})
        config = ("/path/to/file.csv", "", "default_assumptions.json")
        plugin_cls = MagicMock(return_value=MagicMock())
        plugin_cls.return_value.get_config_fields.return_value = [
            {"key": "data_path", "label": "CSV", "type": "file_path"}
        ]
        session: dict = {
            "_loaded_config": config,
            "_raw_df": raw_df,
        }
        with (
            patch("streamlit.session_state", session),
            patch("components.sidebar.REGISTRY", {"lastfm": plugin_cls}),
            patch("components.sidebar.load_builtin_plugins"),
            patch("components.sidebar.load_config_into_session_state"),
            patch(
                "components.sidebar.get_plugin_config_from_session",
                return_value={"data_path": "/path/to/file.csv"},
            ),
            patch("components.sidebar.os.path.exists", return_value=True),
            patch("components.sidebar._load_data_with_progress") as mock_load,
            patch("streamlit.sidebar") as mock_sidebar,
        ):
            mock_sidebar.date_input.return_value = [
                raw_df["date_text"].min().date(),
                raw_df["date_text"].max().date(),
            ]
            from components.sidebar import render_sidebar

            render_sidebar()

        mock_load.assert_not_called()

    def test_render_sidebar_loads_when_config_changed(self) -> None:
        """render_sidebar calls _load_data_with_progress when config differs from _loaded_config."""
        import pandas as pd

        raw_df = pd.DataFrame({"date_text": pd.to_datetime(["2024-01-01"])})
        old_config = ("/old/file.csv", "", "default_assumptions.json")
        new_path = "/new/file.csv"
        plugin_cls = MagicMock(return_value=MagicMock())
        plugin_cls.return_value.get_config_fields.return_value = [
            {"key": "data_path", "label": "CSV", "type": "file_path"}
        ]
        session: dict = {
            "_loaded_config": old_config,
            "_raw_df": raw_df,
        }

        def fake_load(*_args: object) -> None:
            session["_raw_df"] = raw_df

        with (
            patch("streamlit.session_state", session),
            patch("components.sidebar.REGISTRY", {"lastfm": plugin_cls}),
            patch("components.sidebar.load_builtin_plugins"),
            patch("components.sidebar.load_config_into_session_state"),
            patch(
                "components.sidebar.get_plugin_config_from_session",
                return_value={"data_path": new_path},
            ),
            patch("components.sidebar.os.path.exists", return_value=True),
            patch(
                "components.sidebar._load_data_with_progress", side_effect=fake_load
            ) as mock_load,
            patch("streamlit.sidebar") as mock_sidebar,
        ):
            mock_sidebar.date_input.return_value = [
                raw_df["date_text"].min().date(),
                raw_df["date_text"].max().date(),
            ]
            from components.sidebar import render_sidebar

            render_sidebar()

        mock_load.assert_called_once()

    def test_load_data_with_progress_sets_cache_hit_status(self) -> None:
        """_load_data_with_progress sets _cache_status='hit' when cached data is found."""
        import pandas as pd

        cached_df = pd.DataFrame({"date_text": pd.to_datetime(["2024-01-01"])})
        session: dict = {}

        with (
            patch("streamlit.session_state", session),
            patch("components.sidebar.load_assumptions", return_value={}),
            patch("components.sidebar.load_listening_data", return_value=cached_df),
            patch("components.sidebar.os.path.exists", return_value=False),
            patch("components.sidebar.get_cache_key", return_value="key"),
            patch("components.sidebar.get_cached_data", return_value=cached_df),
            patch("streamlit.status") as mock_status,
            patch("streamlit.write"),
        ):
            mock_status.return_value.__enter__ = MagicMock(return_value=mock_status.return_value)
            mock_status.return_value.__exit__ = MagicMock(return_value=False)

            from components.sidebar import _load_data_with_progress

            _load_data_with_progress("/some/file.csv", "", "default_assumptions.json")

        self.assertEqual(session.get("_cache_status"), "hit")


class TestConfigPersistence(unittest.TestCase):
    """Tests for LocalSettings-backed session state hydration."""

    def _make_settings(self, plugin_configs: dict[str, object]) -> MagicMock:
        """Return a mock LocalSettings with get_all_plugin_configs returning plugin_configs."""
        mock_settings = MagicMock(spec=LocalSettings)
        mock_settings.get_all_plugin_configs.return_value = plugin_configs
        return mock_settings

    def test_load_config_hydrates_session_state(self) -> None:
        mock_settings = self._make_settings({"lastfm": {"data_path": "/hydrated/path"}})
        session: dict[str, object] = {}
        with patch("components.plugin_config.settings", mock_settings):
            with patch("streamlit.session_state", session):
                _load_config_into_session_state()
        self.assertEqual(session.get("lastfm_data_path"), "/hydrated/path")

    def test_load_config_does_not_overwrite_existing_session_state(self) -> None:
        mock_settings = self._make_settings({"lastfm": {"data_path": "/from/disk"}})
        session: dict[str, object] = {"lastfm_data_path": "/already/set"}
        with patch("components.plugin_config.settings", mock_settings):
            with patch("streamlit.session_state", session):
                _load_config_into_session_state()
        self.assertEqual(session["lastfm_data_path"], "/already/set")

    def test_load_config_restores_cleared_widget_state(self) -> None:
        # Simulates Streamlit clearing widget-bound keys during page navigation.
        # On return to the page the key is absent, so load_config should restore it.
        mock_settings = self._make_settings({"lastfm": {"data_path": "/saved/path"}})
        session: dict[str, object] = {}  # key absent — as if Streamlit cleared it
        with patch("components.plugin_config.settings", mock_settings):
            with patch("streamlit.session_state", session):
                _load_config_into_session_state()
        self.assertEqual(session.get("lastfm_data_path"), "/saved/path")

    def test_load_config_hydrates_multiple_plugins(self) -> None:
        mock_settings = self._make_settings(
            {
                "lastfm": {"data_path": "/tracks.csv"},
                "swarm": {"swarm_dir": "/swarm/"},
            }
        )
        session: dict[str, object] = {}
        with patch("components.plugin_config.settings", mock_settings):
            with patch("streamlit.session_state", session):
                _load_config_into_session_state()
        self.assertEqual(session.get("lastfm_data_path"), "/tracks.csv")
        self.assertEqual(session.get("swarm_swarm_dir"), "/swarm/")


class TestVisualize(unittest.TestCase):
    """Tests for page render functions and the dashboard entrypoint."""

    def setUp(self) -> None:
        self.test_dir = "data_test"
        os.makedirs(self.test_dir, exist_ok=True)
        self.test_csv = os.path.join(self.test_dir, "test_user_tracks.csv")

        self.df = pd.DataFrame(
            {
                "artist": ["Artist 1", "Artist 2", "Artist 1"],
                "album": ["Album 1", "Album 2", "Album 1"],
                "track": ["Track 1", "Track 2", "Track 3"],
                "timestamp": [1610000000, 1610000100, 1610000200],
                "date_text": ["2021-01-01 10:00", "2021-01-01 10:01", "2021-01-01 11:02"],
                "lat": [41.0, 42.0, 41.0],
                "lng": [-87.0, -88.0, -87.0],
                "city": ["Reykjavik", "Perth", "Reykjavik"],
                "state": ["IS", "WA", "IS"],
                "country": ["Iceland", "Australia", "Iceland"],
            }
        )
        self.df["date_text"] = pd.to_datetime(self.df["date_text"])
        self.df.to_csv(self.test_csv, index=False)

    def tearDown(self) -> None:
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    @patch("streamlit.header")
    @patch("streamlit.selectbox")
    @patch("streamlit.date_input")
    @patch("streamlit.columns")
    @patch("streamlit.pydeck_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.slider")
    def test_render_spatial_analysis(
        self,
        mock_slider: MagicMock,
        mock_df: MagicMock,
        mock_deck: MagicMock,
        mock_cols: MagicMock,
        mock_date: MagicMock,
        mock_select: MagicMock,
        mock_header: MagicMock,
    ) -> None:
        mock_select.return_value = "All"
        mock_date.return_value = [
            self.df["date_text"].min().date(),
            self.df["date_text"].max().date(),
        ]
        mock_cols.side_effect = [
            [MagicMock(), MagicMock()],  # share button (render_share_button)
            [MagicMock(), MagicMock()],  # col_f1, col_f2 (artist/date filters)
            [MagicMock(), MagicMock(), MagicMock()],  # col_a, col_b, col_c (sliders)
            [MagicMock(), MagicMock()],  # path_col, browse_col (output path + browse)
            [MagicMock(), MagicMock()],  # rec_col, exp_col (record + export buttons)
        ]
        mock_slider.return_value = 3.0

        mock_state = MagicMock()
        mock_state.__contains__.return_value = False

        with patch("streamlit.session_state", mock_state):
            render_spatial_analysis(self.df)

        mock_header.assert_called_with("Spatial Music Explorer")
        mock_deck.assert_called_once()
        mock_df.assert_called_once()

    @patch("streamlit.header")
    @patch("streamlit.radio")
    @patch("streamlit.slider")
    @patch("streamlit.columns")
    @patch("streamlit.plotly_chart")
    def test_render_top_charts(
        self,
        mock_plotly: MagicMock,
        mock_columns: MagicMock,
        mock_slider: MagicMock,
        mock_radio: MagicMock,
        mock_header: MagicMock,
    ) -> None:
        mock_radio.return_value = "artist"
        mock_slider.return_value = 10
        mock_columns.return_value = [MagicMock(), MagicMock()]

        render_top_charts(self.df)

        mock_header.assert_called_with("Top Charts")
        self.assertEqual(mock_plotly.call_count, 2)
        mock_plotly.assert_any_call(ANY, width="stretch")

    @patch("streamlit.selectbox")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.subheader")
    def test_render_activity_over_time(
        self,
        mock_subheader: MagicMock,
        mock_plotly: MagicMock,
        mock_selectbox: MagicMock,
    ) -> None:
        mock_selectbox.return_value = "Daily"

        render_activity_over_time(self.df)

        mock_subheader.assert_called_with("Activity Over Time")
        self.assertEqual(mock_plotly.call_count, 2)
        mock_plotly.assert_any_call(ANY, width="stretch")

    @patch("streamlit.header")
    @patch("streamlit.subheader")
    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.tabs")
    @patch("streamlit.metric")
    def test_render_insights_and_narrative(
        self,
        mock_metric: MagicMock,
        mock_tabs: MagicMock,
        mock_df: MagicMock,
        mock_plotly: MagicMock,
        mock_cols: MagicMock,
        mock_select: MagicMock,
        mock_subheader: MagicMock,
        mock_header: MagicMock,
    ) -> None:
        mock_select.return_value = "All"
        mock_cols.side_effect = [
            [MagicMock()] * 4,  # filter columns
            [MagicMock()] * 2,  # share button (render_share_button)
            [MagicMock()] * 2,  # col_top1, col_top2
            [MagicMock()] * 2,  # col_pat1, col_pat2
            [MagicMock()] * 2,  # col_nar1, col_nar2
        ]
        mock_tabs.return_value = [MagicMock(), MagicMock(), MagicMock()]

        render_insights_and_narrative(self.df)

        mock_header.assert_called_with("Insights & Narrative")
        self.assertTrue(mock_select.called)

    @patch("streamlit.set_page_config")
    @patch("streamlit.navigation")
    def test_main_configures_page_and_runs_navigation(
        self,
        mock_nav: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        mock_pg = MagicMock()
        mock_nav.return_value = mock_pg

        with (
            patch("visualize.render_sidebar"),
            patch("visualize._load_plugins_once"),
            patch("visualize._build_plugin_nav_pages", return_value=[]),
        ):
            main()

        mock_config.assert_called_once_with(page_title="Autobiographer", layout="wide")
        mock_nav.assert_called_once()
        mock_pg.run.assert_called_once()

    @patch("streamlit.info")
    @patch("streamlit.markdown")
    def test_render_overview_empty_state(self, mock_md: MagicMock, mock_info: MagicMock) -> None:
        with patch("streamlit.session_state", {"df": None}):
            render_overview()
        mock_info.assert_called_once()

    @patch("streamlit.markdown")
    def test_render_overview_with_lastfm_only(self, mock_md: MagicMock) -> None:
        with patch("streamlit.session_state", {"df": self.df, "swarm_df": None}):
            render_overview()

        # Hero card is rendered via st.markdown; no charts on overview page
        self.assertTrue(mock_md.called)
        calls_html = [c for c in mock_md.call_args_list if "autobio-hero-card" in str(c)]
        self.assertEqual(len(calls_html), 1)

    @patch("streamlit.markdown")
    def test_render_overview_with_swarm_data(self, mock_md: MagicMock) -> None:
        swarm_df = pd.DataFrame(
            {
                "venue": ["Café A", "Café B", "Café A"],
                "city": ["London", "Paris", "London"],
                "country": ["UK", "France", "UK"],
                "lat": [51.5, 48.8, 51.5],
                "lng": [-0.1, 2.3, -0.1],
            }
        )

        with patch("streamlit.session_state", {"df": self.df, "swarm_df": swarm_df}):
            render_overview()

        # Foursquare section should appear in the hero card HTML
        all_html = " ".join(str(c) for c in mock_md.call_args_list)
        self.assertIn("Foursquare", all_html)
        self.assertIn("check-ins", all_html)


class TestMusicHelpers(unittest.TestCase):
    """Tests for pure helper functions in pages.music."""

    def _make_df(self) -> pd.DataFrame:
        df = pd.DataFrame(
            {
                "artist": ["A", "B", "A", "C"],
                "album": ["X", "Y", "X", "Z"],
                "track": ["t1", "t2", "t3", "t4"],
                "timestamp": [1609459200, 1609545600, 1609632000, 1609718400],
                "date_text": ["2021-01-01", "2021-01-02", "2021-01-03", "2021-01-04"],
            }
        )
        df["date_text"] = pd.to_datetime(df["date_text"])
        return df

    def test_filter_by_date_inclusive(self) -> None:
        import datetime

        df = self._make_df()
        result = _filter_by_date(df, datetime.date(2021, 1, 2), datetime.date(2021, 1, 3))
        self.assertEqual(len(result), 2)

    def test_filter_by_date_empty_range(self) -> None:
        import datetime

        df = self._make_df()
        result = _filter_by_date(df, datetime.date(2020, 1, 1), datetime.date(2020, 1, 2))
        self.assertTrue(result.empty)

    def test_prev_period_same_duration(self) -> None:
        import datetime

        start = datetime.date(2021, 1, 8)
        end = datetime.date(2021, 1, 14)
        ps, pe = _prev_period(start, end)
        self.assertEqual(pe, datetime.date(2021, 1, 7))
        self.assertEqual(ps, datetime.date(2021, 1, 1))

    def test_pct_delta_positive(self) -> None:
        result = _pct_delta(120, 100)
        assert result is not None
        self.assertAlmostEqual(result, 20.0)

    def test_pct_delta_negative(self) -> None:
        result = _pct_delta(80, 100)
        assert result is not None
        self.assertAlmostEqual(result, -20.0)

    def test_pct_delta_zero_previous(self) -> None:
        self.assertIsNone(_pct_delta(10, 0))

    @patch("streamlit.metric")
    @patch("streamlit.columns")
    def test_render_quick_facts_calls_metric(
        self, mock_cols: MagicMock, mock_metric: MagicMock
    ) -> None:
        df = self._make_df()
        mock_cols.return_value = [MagicMock()] * 4
        render_quick_facts(df, pd.DataFrame())
        self.assertTrue(mock_metric.called)

    @patch("streamlit.markdown")
    @patch("streamlit.metric")
    @patch("streamlit.subheader")
    @patch("streamlit.columns")
    def test_render_entity_columns(
        self,
        mock_cols: MagicMock,
        mock_subheader: MagicMock,
        mock_metric: MagicMock,
        mock_md: MagicMock,
    ) -> None:
        df = self._make_df()
        ctx_mocks = [
            MagicMock(
                __enter__=MagicMock(return_value=MagicMock()),
                __exit__=MagicMock(return_value=False),
            )
            for _ in range(3)
        ]
        mock_cols.return_value = ctx_mocks
        render_entity_columns(df, df)
        mock_cols.assert_called_once_with(3)

    @patch("streamlit.plotly_chart")
    def test_render_daily_chart(self, mock_plotly: MagicMock) -> None:
        render_daily_chart(self._make_df())
        mock_plotly.assert_called_once()

    @patch("streamlit.plotly_chart")
    def test_render_listening_clock(self, mock_plotly: MagicMock) -> None:
        render_listening_clock(self._make_df())
        mock_plotly.assert_called_once()

    @patch("streamlit.plotly_chart")
    def test_render_plays_growth(self, mock_plotly: MagicMock) -> None:
        render_plays_growth(self._make_df())
        mock_plotly.assert_called_once()

    @patch("streamlit.plotly_chart")
    def test_render_daily_chart_empty(self, mock_plotly: MagicMock) -> None:
        render_daily_chart(pd.DataFrame())
        mock_plotly.assert_not_called()

    @patch("streamlit.plotly_chart")
    def test_render_listening_clock_empty(self, mock_plotly: MagicMock) -> None:
        render_listening_clock(pd.DataFrame())
        mock_plotly.assert_not_called()

    @patch("streamlit.plotly_chart")
    def test_render_plays_growth_empty(self, mock_plotly: MagicMock) -> None:
        render_plays_growth(pd.DataFrame())
        mock_plotly.assert_not_called()

    @patch("streamlit.info")
    def test_render_music_empty_state(self, mock_info: MagicMock) -> None:
        import streamlit as st

        st.session_state["df"] = None
        render_music()
        mock_info.assert_called_once()

    @patch("streamlit.info")
    @patch("streamlit.header")
    @patch("streamlit.caption")
    def test_render_life_in_chapters_empty_state(
        self,
        mock_caption: MagicMock,
        mock_header: MagicMock,
        mock_info: MagicMock,
    ) -> None:
        """render_life_in_chapters shows empty state info when df is None."""
        with patch("streamlit.session_state", {"df": None}):
            render_life_in_chapters()
        mock_info.assert_called_once()
        mock_header.assert_called_with("Life in Chapters")


if __name__ == "__main__":
    unittest.main()
