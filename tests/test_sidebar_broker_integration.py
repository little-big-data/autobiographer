"""Subtask 4: end-to-end integration test for the broker-backed sidebar wiring.

Drives the *real* ``render_sidebar()`` against a real temporary DuckDB store
seeded via ``LocalizerStore.upsert_events``/``upsert_places``. Unlike the
Subtask 1-3 unit tests, nothing here mocks ``LocalizerBroker``,
``core.localizer_frames``, or ``LocalizerStore`` -- only ``streamlit`` (``st``)
is a ``MagicMock``, matching this repo's established sidebar-test convention
(see ``tests/test_sidebar.py``'s ``_make_st()``/``TestBrokerModeWiring``). The
point is proving the real Subtask 1 (broker frame accessors), Subtask 2
(column adapters), and Subtask 3 (sidebar wiring) pieces compose correctly,
not re-testing any of them in isolation.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from localizer.store.db import LocalizerStore
from test_localizer_broker import _seed_events, _seed_places

from components import sidebar


def _make_st() -> MagicMock:
    """Build a MagicMock streamlit stand-in with a real dict session_state.

    Mirrors ``tests/test_sidebar.py``'s ``_make_st()`` helper exactly, so this
    integration test follows the same mocking convention as every other
    sidebar test in this repo.
    """
    st = MagicMock()
    st.session_state = {}
    # st.columns([1, 2, 1]) -> (left, center, right); center is used as a context manager.
    st.columns.return_value = (MagicMock(), MagicMock(), MagicMock())
    return st


class TestSidebarBrokerIntegration(unittest.TestCase):
    """Real LocalizerBroker + core.localizer_frames + LocalizerStore, mocked st only."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "store.duckdb"
        self.assumptions_path = str(Path(self.tmp_dir.name) / "assumptions.json")
        with LocalizerStore(path=self.db_path) as store:
            _seed_events(store, n=2, source_id="lastfm")
            _seed_places(store, n=2, source_id="google_timeline")

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _run_render_sidebar(self) -> MagicMock:
        """Call the real render_sidebar() with no legacy config, store at self.db_path."""
        st = _make_st()
        with (
            patch.object(sidebar, "st", st),
            patch.object(sidebar, "load_builtin_plugins"),
            patch.object(sidebar, "load_config_into_session_state"),
            patch.object(
                sidebar,
                "_resolve_configs",
                return_value=("", "", self.assumptions_path, ""),
            ),
            patch(
                "localizer.store.db.LocalizerStore.default_path",
                return_value=self.db_path,
            ),
        ):
            sidebar.render_sidebar()
        return st

    def test_df_populated_with_seeded_event_values(self) -> None:
        """session_state['df'] contains the exact seeded lastfm rows, with lat/lng."""
        st = self._run_render_sidebar()
        df = st.session_state.get("df")
        self.assertIsNotNone(df, "session_state['df'] is None with a seeded broker store.")
        self.assertFalse(df.empty, "session_state['df'] was populated but empty.")
        self.assertEqual(len(df), 2, "Expected exactly the 2 seeded lastfm events.")
        self.assertIn("Artist0", df["artist"].tolist())
        self.assertIn("Artist1", df["artist"].tolist())
        self.assertIn("Track0", df["track"].tolist())
        self.assertIn("Track1", df["track"].tolist())
        self.assertTrue(df["lat"].notna().all(), "Expected every row to have a non-null lat.")
        self.assertTrue(df["lng"].notna().all(), "Expected every row to have a non-null lng.")

    def test_swarm_df_populated_with_seeded_place_values(self) -> None:
        """session_state['swarm_df'] contains the exact seeded place values."""
        st = self._run_render_sidebar()
        swarm_df = st.session_state.get("swarm_df")
        self.assertIsNotNone(
            swarm_df, "session_state['swarm_df'] is None with a seeded broker store."
        )
        self.assertFalse(swarm_df.empty, "session_state['swarm_df'] was populated but empty.")
        self.assertEqual(len(swarm_df), 2, "Expected exactly the 2 seeded google_timeline places.")
        self.assertIn("Place0", swarm_df["city"].tolist())
        self.assertIn("Place1", swarm_df["city"].tolist())
        lat_lng_pairs = list(zip(swarm_df["lat"].tolist(), swarm_df["lng"].tolist()))
        self.assertIn(
            (51.5074, -0.1278),
            lat_lng_pairs,
            "Expected the exact seeded (lat, lng) pair for Place0 to survive the "
            "broker -> adapter -> session_state round-trip.",
        )

    def test_date_text_is_genuine_usable_datetime64_column(self) -> None:
        """df['date_text'] is a real datetime64 column, usable via .dt.date."""
        st = self._run_render_sidebar()
        df = st.session_state.get("df")
        self.assertIsNotNone(df, "session_state['df'] is None with a seeded broker store.")
        self.assertEqual(
            df["date_text"].dtype.kind,
            "M",
            f"Expected a datetime64 dtype for date_text, got {df['date_text'].dtype!r}.",
        )
        # This is the exact operation render_sidebar()'s date-filter widget performs.
        dates = df["date_text"].dt.date
        self.assertEqual(len(dates), len(df))


if __name__ == "__main__":
    unittest.main()
