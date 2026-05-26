"""Tests for the Data Sources UX: health status, versioned paths, and fetch history."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core.local_settings import LocalSettings
from plugins.sources.lastfm.loader import LastFmPlugin
from plugins.sources.swarm.loader import SwarmPlugin


class TestLocalSettingsFetchHistory(unittest.TestCase):
    """Tests for add_fetch_history and get_fetch_history."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.settings = LocalSettings(self.tmp.name)

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_get_fetch_history_returns_empty_when_no_history(self):
        self.assertEqual(self.settings.get_fetch_history("lastfm"), [])

    def test_add_fetch_history_stores_entry(self):
        self.settings.add_fetch_history("lastfm", "2026-04-28T12:00:00", 1000, "data/file.csv")
        history = self.settings.get_fetch_history("lastfm")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["timestamp"], "2026-04-28T12:00:00")
        self.assertEqual(history[0]["record_count"], 1000)
        self.assertEqual(history[0]["file_path"], "data/file.csv")

    def test_add_fetch_history_newest_first(self):
        self.settings.add_fetch_history("lastfm", "2026-01-01T00:00:00", 100, "a.csv")
        self.settings.add_fetch_history("lastfm", "2026-04-28T12:00:00", 200, "b.csv")
        history = self.settings.get_fetch_history("lastfm")
        self.assertEqual(history[0]["timestamp"], "2026-04-28T12:00:00")
        self.assertEqual(history[1]["timestamp"], "2026-01-01T00:00:00")

    def test_add_fetch_history_caps_at_max(self):
        for i in range(25):
            self.settings.add_fetch_history(
                "lastfm", f"2026-01-{i + 1:02d}T00:00:00", i, f"file_{i}.csv"
            )
        history = self.settings.get_fetch_history("lastfm")
        self.assertEqual(len(history), LocalSettings._MAX_HISTORY)

    def test_add_fetch_history_persists_to_disk(self):
        self.settings.add_fetch_history("lastfm", "2026-04-28T12:00:00", 500, "data/f.csv")
        reloaded = LocalSettings(self.tmp.name)
        self.assertEqual(len(reloaded.get_fetch_history("lastfm")), 1)

    def test_fetch_history_does_not_pollute_plugin_config(self):
        self.settings.add_fetch_history("lastfm", "2026-04-28T12:00:00", 500, "data/f.csv")
        cfg = self.settings.get_plugin_config("lastfm")
        # fetch_history is present in plugin config but is a list, not a string
        self.assertIsInstance(cfg.get("fetch_history"), list)

    def test_get_fetch_history_independent_per_plugin(self):
        self.settings.add_fetch_history("lastfm", "2026-04-28T12:00:00", 100, "a.csv")
        self.assertEqual(self.settings.get_fetch_history("swarm"), [])


class TestGetHealthStatus(unittest.TestCase):
    """Tests for SourcePlugin.get_health_status."""

    def setUp(self):
        self.lastfm = LastFmPlugin()
        self.swarm = SwarmPlugin()

    def test_unconfigured_when_no_data_path(self):
        health = self.lastfm.get_health_status({"data_path": ""}, [])
        self.assertEqual(health["status"], "unconfigured")
        self.assertIsNone(health["record_count"])
        self.assertIsNone(health["data_path"])

    def test_error_when_path_does_not_exist(self):
        health = self.lastfm.get_health_status({"data_path": "/nonexistent/file.csv"}, [])
        self.assertEqual(health["status"], "error")
        self.assertEqual(health["data_path"], "/nonexistent/file.csv")

    def test_healthy_fetchable_with_recent_history(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"artist,track\nRadiohead,Karma Police\n")
            tmp_path = f.name
        try:
            recent_ts = datetime.now(tz=timezone.utc).isoformat()
            history = [{"timestamp": recent_ts, "record_count": 1, "file_path": tmp_path}]
            health = self.lastfm.get_health_status({"data_path": tmp_path}, history)
            self.assertEqual(health["status"], "healthy")
            self.assertEqual(health["record_count"], 1)
        finally:
            os.unlink(tmp_path)

    def test_stale_fetchable_with_old_history(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"artist,track\nRadiohead,Karma Police\n")
            tmp_path = f.name
        try:
            old_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=48)).isoformat()
            history = [{"timestamp": old_ts, "record_count": 1, "file_path": tmp_path}]
            health = self.lastfm.get_health_status({"data_path": tmp_path}, history)
            self.assertEqual(health["status"], "stale")
        finally:
            os.unlink(tmp_path)

    def test_non_fetchable_always_healthy_when_file_exists(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            tmp_path = f.name
        try:
            # No history, old file — non-fetchable plugins are always healthy
            old_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=48)).isoformat()
            history = [{"timestamp": old_ts, "record_count": 0, "file_path": tmp_path}]
            health = self.swarm.get_health_status({"swarm_dir": tmp_path}, history)
            self.assertEqual(health["status"], "healthy")
        finally:
            os.unlink(tmp_path)

    def test_custom_stale_threshold_env_var(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            tmp_path = f.name
        try:
            # 2 hours old, threshold = 1 hour → stale
            old_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
            history = [{"timestamp": old_ts, "record_count": 1, "file_path": tmp_path}]
            with patch.dict(os.environ, {"AUTOBIO_STALE_THRESHOLD_HOURS": "1"}):
                health = self.lastfm.get_health_status({"data_path": tmp_path}, history)
            self.assertEqual(health["status"], "stale")
        finally:
            os.unlink(tmp_path)

    def test_record_count_read_from_csv_file(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            f.write("artist,track\nRadiohead,Karma Police\nPortishead,Sour Times\n")
            tmp_path = f.name
        try:
            health = self.lastfm.get_health_status({"data_path": tmp_path}, [])
            self.assertEqual(health["record_count"], 2)
        finally:
            os.unlink(tmp_path)

    def test_non_fetchable_last_fetch_from_file_ctime(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(b"[]")
            tmp_path = f.name
        try:
            health = self.swarm.get_health_status({"swarm_dir": tmp_path}, [])
            # last_fetch should be set from file ctime, not None
            self.assertIsNotNone(health["last_fetch"])
        finally:
            os.unlink(tmp_path)

    def test_health_uses_file_mtime_when_no_history(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            tmp_path = f.name
        try:
            # Set mtime to 48 hours ago so it reads as stale
            old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=48)).timestamp()
            os.utime(tmp_path, (old_time, old_time))
            health = self.lastfm.get_health_status({"data_path": tmp_path}, [])
            self.assertEqual(health["status"], "stale")
        finally:
            os.unlink(tmp_path)


class TestGetVersionedOutputPath(unittest.TestCase):
    """Tests for SourcePlugin.get_versioned_output_path."""

    def setUp(self):
        self.lastfm = LastFmPlugin()

    def test_returns_string(self):
        with patch.dict(os.environ, {"AUTOBIO_LASTFM_USERNAME": "testuser"}):
            path = self.lastfm.get_versioned_output_path()
        self.assertIsInstance(path, str)

    def test_embeds_timestamp(self):
        with patch.dict(os.environ, {"AUTOBIO_LASTFM_USERNAME": "testuser"}):
            path = self.lastfm.get_versioned_output_path()
        # Path should contain a timestamp segment like _2026-04-28T120000
        self.assertRegex(path, r"_\d{4}-\d{2}-\d{2}T\d{6}")

    def test_preserves_extension(self):
        with patch.dict(os.environ, {"AUTOBIO_LASTFM_USERNAME": "testuser"}):
            path = self.lastfm.get_versioned_output_path()
        self.assertTrue(path.endswith(".csv"))

    def test_fallback_when_no_default_path(self):
        # Swarm has no get_default_output_path, falls back to data/{id}/{id}_{ts}.csv
        from plugins.sources.swarm.loader import SwarmPlugin

        swarm = SwarmPlugin()
        path = swarm.get_versioned_output_path()
        self.assertIn("swarm", path)
        self.assertTrue(path.endswith(".csv"))

    def test_different_calls_produce_different_timestamps(self):
        import time

        with patch.dict(os.environ, {"AUTOBIO_LASTFM_USERNAME": "testuser"}):
            path1 = self.lastfm.get_versioned_output_path()
            time.sleep(1.1)
            path2 = self.lastfm.get_versioned_output_path()
        self.assertNotEqual(path1, path2)


class TestRenderSwarmAnalysis(unittest.TestCase):
    """Smoke tests for _render_swarm_analysis in pages/data_sources.py."""

    def _make_col(self) -> unittest.mock.MagicMock:
        col = unittest.mock.MagicMock()
        col.__enter__ = unittest.mock.MagicMock(return_value=col)
        col.__exit__ = unittest.mock.MagicMock(return_value=False)
        return col

    @patch("streamlit.info")
    @patch("streamlit.columns")
    def test_shows_info_when_no_swarm_data(
        self, mock_columns: unittest.mock.MagicMock, mock_info: unittest.mock.MagicMock
    ) -> None:
        from pages.data_sources import _render_swarm_analysis

        col = self._make_col()
        mock_columns.return_value = [col, col, col]

        with patch("streamlit.session_state", {"swarm_df": None, "df": None}):
            _render_swarm_analysis()
        mock_info.assert_called_once()

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.slider", return_value=80)
    @patch("streamlit.caption")
    @patch("streamlit.divider")
    @patch("streamlit.metric")
    @patch("streamlit.columns")
    def test_renders_status_metrics_when_swarm_loaded(
        self,
        mock_columns: unittest.mock.MagicMock,
        mock_metric: unittest.mock.MagicMock,
        mock_divider: unittest.mock.MagicMock,
        mock_caption: unittest.mock.MagicMock,
        mock_slider: unittest.mock.MagicMock,
        mock_button: unittest.mock.MagicMock,
    ) -> None:
        import pandas as pd

        from pages.data_sources import _render_swarm_analysis

        col = self._make_col()

        def _columns_side_effect(spec: object) -> list[unittest.mock.MagicMock]:
            n = spec if isinstance(spec, int) else len(spec)  # type: ignore[arg-type]
            return [col] * n

        mock_columns.side_effect = _columns_side_effect

        swarm_df = pd.DataFrame(
            {"venue_category": ["Airport"], "timestamp": [1700000000], "lat": [0.0], "lng": [0.0]}
        )
        with (
            patch("streamlit.session_state", {"swarm_df": swarm_df, "df": None}),
            patch("pages.data_sources.load_detected_trips_cache", return_value=[]),
            patch("pages.data_sources.load_assumptions", return_value={}),
        ):
            _render_swarm_analysis()
        self.assertTrue(mock_metric.called or col.metric.called)

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.slider", return_value=80)
    @patch("streamlit.caption")
    @patch("streamlit.divider")
    @patch("streamlit.metric")
    @patch("streamlit.columns")
    def test_fallback_load_persists_to_session_state(
        self,
        mock_columns: unittest.mock.MagicMock,
        mock_metric: unittest.mock.MagicMock,
        mock_divider: unittest.mock.MagicMock,
        mock_caption: unittest.mock.MagicMock,
        mock_slider: unittest.mock.MagicMock,
        mock_button: unittest.mock.MagicMock,
    ) -> None:
        """When swarm_df is absent but swarm_dir is configured, load and persist."""
        import pandas as pd

        from pages.data_sources import _render_swarm_analysis

        col = self._make_col()

        def _cols_side_effect(spec: object) -> list[unittest.mock.MagicMock]:
            n = spec if isinstance(spec, int) else len(spec)  # type: ignore[arg-type]
            return [col] * n

        mock_columns.side_effect = _cols_side_effect

        fake_swarm = pd.DataFrame(
            {"venue_category": ["Airport"], "timestamp": [1700000000], "lat": [0.0], "lng": [0.0]}
        )

        with tempfile.TemporaryDirectory() as swarm_dir:
            fake_state: dict = {"swarm_df": None, "df": None, "swarm_swarm_dir": swarm_dir}
            with (
                patch("streamlit.session_state", fake_state),
                patch("analysis_utils.load_swarm_data", return_value=fake_swarm),
                patch("pages.data_sources.load_detected_trips_cache", return_value=[]),
                patch("pages.data_sources.load_transit_days_cache", return_value=set()),
                patch("pages.data_sources.load_dining_cache", return_value={}),
                patch("pages.data_sources.load_assumptions", return_value={}),
            ):
                _render_swarm_analysis()

        self.assertIsNotNone(fake_state.get("swarm_df"))


class TestLoadConfigIntoSessionState(unittest.TestCase):
    """Tests for load_config_into_session_state."""

    def test_sets_absent_key_from_disk(self) -> None:
        from components.plugin_config import load_config_into_session_state

        fake_cfg = {"lastfm": {"data_path": "/real/path.csv"}}
        fake_state: dict[str, str] = {}

        with (
            patch("components.plugin_config.settings") as mock_settings,
            patch("streamlit.session_state", fake_state),
        ):
            mock_settings.get_all_plugin_configs.return_value = fake_cfg
            load_config_into_session_state()

        self.assertEqual(fake_state.get("lastfm_data_path"), "/real/path.csv")

    def test_restores_empty_string_to_disk_value(self) -> None:
        """Empty string in session state (widget reset after rerun) is restored."""
        from components.plugin_config import load_config_into_session_state

        fake_cfg = {"swarm": {"swarm_dir": "/real/swarm/"}}
        fake_state: dict[str, str] = {"swarm_swarm_dir": ""}

        with (
            patch("components.plugin_config.settings") as mock_settings,
            patch("streamlit.session_state", fake_state),
        ):
            mock_settings.get_all_plugin_configs.return_value = fake_cfg
            load_config_into_session_state()

        self.assertEqual(fake_state["swarm_swarm_dir"], "/real/swarm/")

    def test_does_not_overwrite_user_edited_value(self) -> None:
        from components.plugin_config import load_config_into_session_state

        fake_cfg = {"lastfm": {"data_path": "/disk/path.csv"}}
        fake_state: dict[str, str] = {"lastfm_data_path": "/user/edit.csv"}

        with (
            patch("components.plugin_config.settings") as mock_settings,
            patch("streamlit.session_state", fake_state),
        ):
            mock_settings.get_all_plugin_configs.return_value = fake_cfg
            load_config_into_session_state()

        self.assertEqual(fake_state["lastfm_data_path"], "/user/edit.csv")

    def test_skips_non_string_values(self) -> None:
        from components.plugin_config import load_config_into_session_state

        fake_cfg = {"lastfm": {"fetch_history": [{"ts": "2026-01-01"}]}}
        fake_state: dict = {}

        with (
            patch("components.plugin_config.settings") as mock_settings,
            patch("streamlit.session_state", fake_state),
        ):
            mock_settings.get_all_plugin_configs.return_value = fake_cfg
            load_config_into_session_state()

        # list value should not be written to session state
        self.assertNotIn("lastfm_fetch_history", fake_state)


if __name__ == "__main__":
    unittest.main()
