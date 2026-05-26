"""Tests for Subtask 0 — Pre-compute Infrastructure.

Covers:
- save/load roundtrip for deep analysis cache functions
- load returns None for missing or corrupt files
- get_deep_analysis_status reports correct presence/absence per file
- _render_deep_analysis_compute smoke test (all st.* calls mocked)
"""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch


class TestSaveLoadRoundtrip(unittest.TestCase):
    """test_save_and_load_roundtrip: write a dict via save, read it back via load."""

    def test_save_and_load_roundtrip(self, tmp_path=None) -> None:
        import tempfile

        from analysis_utils import load_deep_sessions_cache, save_deep_sessions_cache

        data = {"sessions": [{"id": 1, "tracks": 5}], "version": "1.0"}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "deep_sessions.json")
            save_deep_sessions_cache(data, path)
            loaded = load_deep_sessions_cache(path)
        self.assertEqual(loaded, data)

    def test_save_and_load_roundtrip_personality(self) -> None:
        import tempfile

        from analysis_utils import load_deep_personality_cache, save_deep_personality_cache

        data = {"gini": 0.75, "loyalty": 0.6}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "deep_personality.json")
            save_deep_personality_cache(data, path)
            loaded = load_deep_personality_cache(path)
        self.assertEqual(loaded, data)


class TestLoadMissingFileReturnsNone(unittest.TestCase):
    """test_load_missing_file_returns_none: path that does not exist -> returns None."""

    def test_load_missing_file_returns_none_sessions(self) -> None:
        from analysis_utils import load_deep_sessions_cache

        result = load_deep_sessions_cache("/nonexistent/path/deep_sessions.json")
        self.assertIsNone(result)

    def test_load_missing_file_returns_none_personality(self) -> None:
        from analysis_utils import load_deep_personality_cache

        result = load_deep_personality_cache("/nonexistent/path/deep_personality.json")
        self.assertIsNone(result)

    def test_load_missing_file_returns_none_arcs(self) -> None:
        from analysis_utils import load_deep_arcs_cache

        result = load_deep_arcs_cache("/nonexistent/path/deep_arcs.json")
        self.assertIsNone(result)

    def test_load_missing_file_returns_none_seasonal(self) -> None:
        from analysis_utils import load_deep_seasonal_cache

        result = load_deep_seasonal_cache("/nonexistent/path/deep_seasonal.json")
        self.assertIsNone(result)

    def test_load_missing_file_returns_none_taste_drift(self) -> None:
        from analysis_utils import load_deep_taste_drift_cache

        result = load_deep_taste_drift_cache("/nonexistent/path/deep_taste_drift.json")
        self.assertIsNone(result)

    def test_load_missing_file_returns_none_city_soundtracks(self) -> None:
        from analysis_utils import load_deep_city_soundtracks_cache

        result = load_deep_city_soundtracks_cache("/nonexistent/path/deep_city_soundtracks.json")
        self.assertIsNone(result)

    def test_load_missing_file_returns_none_venue_patterns(self) -> None:
        from analysis_utils import load_deep_venue_patterns_cache

        result = load_deep_venue_patterns_cache("/nonexistent/path/deep_venue_patterns.json")
        self.assertIsNone(result)

    def test_load_missing_file_returns_none_life_events(self) -> None:
        from analysis_utils import load_deep_life_events_cache

        result = load_deep_life_events_cache("/nonexistent/path/deep_life_events.json")
        self.assertIsNone(result)

    def test_load_corrupt_json_returns_none(self) -> None:
        """Corrupt JSON file should also return None."""
        import tempfile

        from analysis_utils import load_deep_sessions_cache

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            fh.write("not valid json{{{")
            path = fh.name
        try:
            result = load_deep_sessions_cache(path)
        finally:
            os.unlink(path)
        self.assertIsNone(result)


class TestGetDeepAnalysisStatusAllMissing(unittest.TestCase):
    """test_get_deep_analysis_status_all_missing: no cache files -> all values False."""

    def test_get_deep_analysis_status_all_missing(self) -> None:
        from analysis_utils import (
            DEEP_ARCS_CACHE,
            DEEP_CITY_SOUNDTRACKS_CACHE,
            DEEP_LIFE_EVENTS_CACHE,
            DEEP_PERSONALITY_CACHE,
            DEEP_SEASONAL_CACHE,
            DEEP_SESSIONS_CACHE,
            DEEP_TASTE_DRIFT_CACHE,
            DEEP_VENUE_PATTERNS_CACHE,
            get_deep_analysis_status,
        )

        # Patch os.path.exists to return False for all deep analysis cache paths
        deep_paths = {
            DEEP_SESSIONS_CACHE,
            DEEP_PERSONALITY_CACHE,
            DEEP_ARCS_CACHE,
            DEEP_SEASONAL_CACHE,
            DEEP_TASTE_DRIFT_CACHE,
            DEEP_CITY_SOUNDTRACKS_CACHE,
            DEEP_VENUE_PATTERNS_CACHE,
            DEEP_LIFE_EVENTS_CACHE,
        }

        original_exists = os.path.exists

        def fake_exists(p: str) -> bool:
            if p in deep_paths:
                return False
            return original_exists(p)

        with patch("os.path.exists", side_effect=fake_exists):
            status = get_deep_analysis_status()

        self.assertIsInstance(status, dict)
        self.assertEqual(len(status), 8)
        for key, present in status.items():
            self.assertFalse(present, f"Expected {key} to be False but got True")


class TestGetDeepAnalysisStatusSomePresent(unittest.TestCase):
    """test_get_deep_analysis_status_some_present: two files created -> those two True."""

    def test_get_deep_analysis_status_some_present(self) -> None:
        import tempfile

        from analysis_utils import (
            DEEP_ARCS_CACHE,
            DEEP_CITY_SOUNDTRACKS_CACHE,
            DEEP_LIFE_EVENTS_CACHE,
            DEEP_PERSONALITY_CACHE,
            DEEP_SEASONAL_CACHE,
            DEEP_SESSIONS_CACHE,
            DEEP_TASTE_DRIFT_CACHE,
            DEEP_VENUE_PATTERNS_CACHE,
            get_deep_analysis_status,
            save_deep_personality_cache,
            save_deep_sessions_cache,
        )

        all_cache_paths = [
            DEEP_SESSIONS_CACHE,
            DEEP_PERSONALITY_CACHE,
            DEEP_ARCS_CACHE,
            DEEP_SEASONAL_CACHE,
            DEEP_TASTE_DRIFT_CACHE,
            DEEP_CITY_SOUNDTRACKS_CACHE,
            DEEP_VENUE_PATTERNS_CACHE,
            DEEP_LIFE_EVENTS_CACHE,
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write two of the eight cache files into tmpdir
            sessions_path = os.path.join(tmpdir, "deep_sessions.json")
            personality_path = os.path.join(tmpdir, "deep_personality.json")
            save_deep_sessions_cache({"ok": True}, sessions_path)
            save_deep_personality_cache({"ok": True}, personality_path)

            original_exists = os.path.exists

            def fake_exists(p: str) -> bool:
                # Redirect the two "present" cache paths to our temp files
                if p == DEEP_SESSIONS_CACHE:
                    return original_exists(sessions_path)
                if p == DEEP_PERSONALITY_CACHE:
                    return original_exists(personality_path)
                # All other deep cache paths: not present
                if p in all_cache_paths:
                    return False
                return original_exists(p)

            with patch("os.path.exists", side_effect=fake_exists):
                status = get_deep_analysis_status()

        self.assertEqual(len(status), 8)
        # Determine which keys map to sessions and personality
        true_keys = [k for k, v in status.items() if v]
        false_keys = [k for k, v in status.items() if not v]
        self.assertEqual(len(true_keys), 2, f"Expected 2 True, got: {status}")
        self.assertEqual(len(false_keys), 6, f"Expected 6 False, got: {status}")


class TestRenderDataSourcesSmoke(unittest.TestCase):
    """test_render_data_sources_smoke: _render_deep_analysis_compute runs without raising."""

    def test_render_data_sources_smoke_no_data(self) -> None:
        """When broker has no merged DataFrame, shows info message and returns."""
        from pages.data_sources import _render_deep_analysis_compute

        mock_broker = MagicMock()
        mock_broker.get_merged_frame.return_value = None

        col_mock = MagicMock()
        col_mock.__enter__ = MagicMock(return_value=col_mock)
        col_mock.__exit__ = MagicMock(return_value=False)

        with (
            patch("streamlit.subheader"),
            patch("streamlit.write"),
            patch("streamlit.info"),
            patch("streamlit.button", return_value=False),
            patch("streamlit.columns", return_value=[col_mock, col_mock]),
            patch("streamlit.status"),
            patch("streamlit.rerun"),
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
        ):
            # Should not raise — broker has no data, so info banner shown
            _render_deep_analysis_compute(mock_broker)

    def test_render_data_sources_smoke_with_empty_df(self) -> None:
        """When broker returns an empty DataFrame, shows info message."""
        import pandas as pd

        from pages.data_sources import _render_deep_analysis_compute

        mock_broker = MagicMock()
        mock_broker.get_merged_frame.return_value = pd.DataFrame()

        col_mock = MagicMock()
        col_mock.__enter__ = MagicMock(return_value=col_mock)
        col_mock.__exit__ = MagicMock(return_value=False)

        with (
            patch("streamlit.subheader"),
            patch("streamlit.write"),
            patch("streamlit.info"),
            patch("streamlit.button", return_value=False),
            patch("streamlit.columns", return_value=[col_mock, col_mock]),
            patch("streamlit.status"),
            patch("streamlit.rerun"),
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
        ):
            _render_deep_analysis_compute(mock_broker)

    def test_render_data_sources_smoke_with_data_button_not_clicked(self) -> None:
        """When broker has data and button is not clicked, renders status grid."""
        import pandas as pd

        from pages.data_sources import _render_deep_analysis_compute

        mock_broker = MagicMock()
        df = pd.DataFrame({"artist": ["A", "B"], "track": ["x", "y"]})
        mock_broker.get_merged_frame.return_value = df

        col_mock = MagicMock()
        col_mock.__enter__ = MagicMock(return_value=col_mock)
        col_mock.__exit__ = MagicMock(return_value=False)

        with (
            patch("streamlit.subheader"),
            patch("streamlit.write"),
            patch("streamlit.info"),
            patch("streamlit.caption"),
            patch("streamlit.button", return_value=False),
            patch(
                "streamlit.columns",
                return_value=[
                    col_mock,
                    col_mock,
                    col_mock,
                    col_mock,
                    col_mock,
                    col_mock,
                    col_mock,
                    col_mock,
                ],
            ),
            patch("streamlit.status"),
            patch("streamlit.rerun"),
            patch(
                "pages.data_sources.get_deep_analysis_status",
                return_value={
                    "sessions": True,
                    "personality": False,
                    "arcs": False,
                    "seasonal": False,
                    "taste_drift": False,
                    "city_soundtracks": False,
                    "venue_patterns": False,
                    "life_events": False,
                },
            ),
        ):
            _render_deep_analysis_compute(mock_broker)


class TestRenderDataSourcesCallSite(unittest.TestCase):
    """Verify render_data_sources() passes a real broker (not None) to _render_deep_analysis_compute.

    This is the RED signal for the call-site bug: render_data_sources() currently
    calls _render_deep_analysis_compute(None), which means the Calculate button is
    never shown in production.  The fix must pass an actual broker sourced from
    session state (or equivalent) so users can reach the Calculate button.
    """

    def test_render_data_sources_does_not_pass_none_to_compute(self) -> None:
        """render_data_sources() must not call _render_deep_analysis_compute(None).

        We intercept the call to _render_deep_analysis_compute and assert that
        the broker argument is never None.  The fix must source a real broker
        (or merged DataFrame) from session state instead of hardcoding None.
        """
        import pandas as pd

        received_args: list[Any] = []

        def capture_compute(broker: Any) -> None:
            received_args.append(broker)

        # A context-manager-compatible mock for st.tabs / st.columns / st.empty
        ctx_mock = MagicMock()
        ctx_mock.__enter__ = MagicMock(return_value=ctx_mock)
        ctx_mock.__exit__ = MagicMock(return_value=False)
        ctx_mock.container.return_value.__enter__ = MagicMock(return_value=ctx_mock)
        ctx_mock.container.return_value.__exit__ = MagicMock(return_value=False)

        fake_df = pd.DataFrame({"artist": ["A"], "track": ["x"]})

        with (
            patch("pages.data_sources.load_builtin_plugins"),
            patch("pages.data_sources.load_config_into_session_state"),
            # Empty registry so the plugin loop body never executes
            patch("pages.data_sources.REGISTRY", {}),
            patch("pages.data_sources.settings"),
            patch("pages.data_sources._render_cache_tab"),
            patch(
                "pages.data_sources._render_deep_analysis_compute",
                side_effect=capture_compute,
            ),
            patch("streamlit.title"),
            patch("streamlit.caption"),
            patch("streamlit.tabs", return_value=[ctx_mock, ctx_mock]),
            patch("streamlit.columns", return_value=[ctx_mock, ctx_mock, ctx_mock]),
            patch("streamlit.empty", return_value=ctx_mock),
            patch("streamlit.divider"),
            patch("streamlit.metric"),
            patch("streamlit.session_state", {"df": fake_df, "swarm_df": pd.DataFrame()}),
        ):
            from pages.data_sources import render_data_sources

            render_data_sources()

        self.assertGreater(
            len(received_args),
            0,
            "_render_deep_analysis_compute was never called — test setup error",
        )
        for i, broker_arg in enumerate(received_args):
            self.assertIsNotNone(
                broker_arg,
                f"_render_deep_analysis_compute call #{i} received None as broker. "
                "Fix: pass the actual broker from session state instead of None.",
            )


class TestDeepAnalysisNotComputedBanner(unittest.TestCase):
    """Tests for the _deep_analysis_not_computed_banner helper."""

    def test_banner_calls_st_info_with_analysis_name(self) -> None:
        from pages.data_sources import _deep_analysis_not_computed_banner

        with patch("streamlit.info") as mock_info:
            _deep_analysis_not_computed_banner("Session Analysis")

        mock_info.assert_called_once()
        call_args = mock_info.call_args
        # The first positional argument should contain the analysis name
        info_text = call_args[0][0] if call_args[0] else str(call_args)
        self.assertIn("Session Analysis", info_text)

    def test_banner_references_data_sources(self) -> None:
        from pages.data_sources import _deep_analysis_not_computed_banner

        with patch("streamlit.info") as mock_info:
            _deep_analysis_not_computed_banner("City Soundtracks")

        call_args = mock_info.call_args
        info_text = call_args[0][0] if call_args[0] else str(call_args)
        self.assertIn("Data Sources", info_text)


class TestDeepCacheConstants(unittest.TestCase):
    """Verify all 8 cache path constants are defined in analysis_utils."""

    def test_all_cache_constants_exist(self) -> None:
        from analysis_utils import (
            DEEP_ARCS_CACHE,
            DEEP_CITY_SOUNDTRACKS_CACHE,
            DEEP_LIFE_EVENTS_CACHE,
            DEEP_PERSONALITY_CACHE,
            DEEP_SEASONAL_CACHE,
            DEEP_SESSIONS_CACHE,
            DEEP_TASTE_DRIFT_CACHE,
            DEEP_VENUE_PATTERNS_CACHE,
        )

        constants = [
            DEEP_SESSIONS_CACHE,
            DEEP_PERSONALITY_CACHE,
            DEEP_ARCS_CACHE,
            DEEP_SEASONAL_CACHE,
            DEEP_TASTE_DRIFT_CACHE,
            DEEP_CITY_SOUNDTRACKS_CACHE,
            DEEP_VENUE_PATTERNS_CACHE,
            DEEP_LIFE_EVENTS_CACHE,
        ]

        for const in constants:
            self.assertIsInstance(const, str)
            self.assertIn("deep_", const)
            self.assertTrue(const.endswith(".json"))

    def test_cache_constants_are_in_data_cache_dir(self) -> None:
        from analysis_utils import (
            DEEP_ARCS_CACHE,
            DEEP_CITY_SOUNDTRACKS_CACHE,
            DEEP_LIFE_EVENTS_CACHE,
            DEEP_PERSONALITY_CACHE,
            DEEP_SEASONAL_CACHE,
            DEEP_SESSIONS_CACHE,
            DEEP_TASTE_DRIFT_CACHE,
            DEEP_VENUE_PATTERNS_CACHE,
        )

        for const in [
            DEEP_SESSIONS_CACHE,
            DEEP_PERSONALITY_CACHE,
            DEEP_ARCS_CACHE,
            DEEP_SEASONAL_CACHE,
            DEEP_TASTE_DRIFT_CACHE,
            DEEP_CITY_SOUNDTRACKS_CACHE,
            DEEP_VENUE_PATTERNS_CACHE,
            DEEP_LIFE_EVENTS_CACHE,
        ]:
            # Path should contain data/cache or data\cache
            normalized = const.replace("\\", "/")
            self.assertIn("data/cache", normalized, f"{const} not in data/cache dir")
