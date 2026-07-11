"""Tests for components.sidebar data loading — Google Timeline / Swarm combination."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from localizer.store.db import LocalizerStore

from components import sidebar


def _make_st() -> MagicMock:
    """Build a MagicMock streamlit stand-in with a real dict session_state."""
    st = MagicMock()
    st.session_state = {}
    # st.columns([1, 2, 1]) -> (left, center, right); center is used as a context manager.
    st.columns.return_value = (MagicMock(), MagicMock(), MagicMock())
    return st


class TestLoadDataCombination(unittest.TestCase):
    """The sidebar must merge Swarm and Google Timeline into one sorted swarm_df."""

    def setUp(self):
        self.raw_df = pd.DataFrame({"timestamp": [1, 2], "date_text": ["2021-01-01", "2021-01-02"]})
        self.swarm_df = pd.DataFrame(
            {"timestamp": [100, 300], "lat": [40.0, 41.0], "lng": [-74.0, -75.0]}
        )
        self.timeline_df = pd.DataFrame(
            {"timestamp": [200, 400], "lat": [42.0, 43.0], "lng": [-76.0, -77.0]}
        )

    def _run(self, timeline_path: str) -> dict:
        st = _make_st()
        with (
            patch.object(sidebar, "st", st),
            patch.object(sidebar.os.path, "exists", return_value=True),
            patch.object(sidebar, "load_assumptions", return_value={}),
            patch.object(sidebar, "load_listening_data", return_value=self.raw_df),
            patch.object(sidebar, "load_swarm_data", return_value=self.swarm_df),
            patch.object(sidebar, "load_google_timeline", return_value=self.timeline_df),
            patch.object(sidebar, "get_cache_key", return_value="k"),
            patch.object(sidebar, "get_cached_data", return_value=None),
            patch.object(sidebar, "apply_location_context", return_value=self.raw_df),
            patch.object(sidebar, "save_to_cache"),
        ):
            sidebar._load_data_with_progress(
                "lastfm.csv", "swarm_dir", "assume.json", timeline_path
            )
        return st.session_state

    def test_timeline_rows_appended_to_swarm(self):
        state = self._run("Timeline.json")
        combined = state["swarm_df"]
        self.assertEqual(len(combined), 4)

    def test_combined_frame_sorted_by_timestamp(self):
        state = self._run("Timeline.json")
        combined = state["swarm_df"]
        self.assertEqual(list(combined["timestamp"]), [100, 200, 300, 400])
        self.assertTrue(combined["timestamp"].is_monotonic_increasing)

    def test_no_timeline_leaves_swarm_only(self):
        state = self._run("")
        combined = state["swarm_df"]
        self.assertEqual(list(combined["timestamp"]), [100, 300])

    def test_source_id_tagged_per_row_when_both_sources_present(self):
        """Subtask 2 AC #1: each row's source_id matches its origin loader.

        Cross-references specific timestamp values from each mocked loader's
        fixture (self.swarm_df has timestamps 100/300, self.timeline_df has
        timestamps 200/400) rather than just checking two distinct values
        exist somewhere in the column.
        """
        state = self._run("Timeline.json")
        combined = state["swarm_df"]
        self.assertIn(
            "source_id",
            combined.columns,
            "swarm_df has no 'source_id' column — sidebar._load_data_with_progress() "
            "must tag rows with their origin before concatenation.",
        )
        by_timestamp = combined.set_index("timestamp")["source_id"]
        self.assertEqual(by_timestamp[100], "swarm")
        self.assertEqual(by_timestamp[300], "swarm")
        self.assertEqual(by_timestamp[200], "google_timeline")
        self.assertEqual(by_timestamp[400], "google_timeline")

    def test_source_id_all_swarm_when_only_swarm_dir_configured(self):
        """Subtask 2 AC #2: with no timeline_path, every row is tagged 'swarm'."""
        state = self._run("")
        combined = state["swarm_df"]
        self.assertIn(
            "source_id",
            combined.columns,
            "swarm_df has no 'source_id' column when only swarm_dir is configured.",
        )
        self.assertEqual(list(combined["source_id"]), ["swarm", "swarm"])


class TestBrokerModeWiring(unittest.TestCase):
    """Subtask 3: render_sidebar() must branch into a DuckDB-backed load path when
    ~/.localizer/store.duckdb (here, a tmp_path stand-in) exists, instead of the
    legacy CSV-gated path.

    None of these tests mock away LocalizerBroker, core.localizer_frames, or
    render_sidebar()'s internals — they seed a real DuckDB store and drive the
    real render_sidebar() through a mocked ``st`` only, exactly like
    TestLoadDataCombination does for the legacy path above. This keeps the tests
    valid regardless of how Subtask 3 names its internal helpers (the plan does
    not fix an exact private-function surface), and means every test here is
    expected to fail today: render_sidebar() has no broker branch yet, so with no
    legacy file_path configured it always takes the early-return path, leaving
    ``df``/``swarm_df`` as None and never touching the store at all.

    NOTE on Test Guidance items not covered by a new test here:
      - "store does not exist -> byte-for-byte unchanged legacy behavior" is
        already proven by TestLoadDataCombination and the rest of this file's
        untouched suite continuing to pass; no new test is needed (and one
        asserting today's behavior would pass vacuously, which is not a valid
        RED test).
      - "_current_config remains a 4-tuple in broker mode" cannot be made to
        fail today: render_sidebar() already always writes a 4-tuple to
        `_current_config` regardless of branch, so a standalone test of tuple
        shape alone would pass before any Subtask 3 code exists. The coder/
        reviewer should re-check this by inspection; it does not need its own
        failing test.
      - "LocalizerStore.default_path() raises ImportError -> falls back to
        legacy" cannot be made to fail today either: render_sidebar() does not
        yet attempt to import localizer.store.db anywhere in its own body (only
        the already-tested, currently-uncalled `_make_broker()` does), so there
        is no import for an ImportError to interrupt yet, and simulating one
        would not exercise any code path that doesn't already trivially "fall
        back" by doing nothing broker-related. This should be covered once the
        import is actually added to render_sidebar()'s body — recommend the
        coder add a companion test at that point, or the reviewer verify by
        inspection that the new import site reuses `_make_broker()`'s existing
        try/except ImportError pattern.
    """

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "store.duckdb"
        self.assumptions_path = str(Path(self.tmp_dir.name) / "assumptions.json")
        self._seed_store()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _seed_store(self, event_count: int = 2, place_count: int = 2) -> None:
        """Seed self.db_path with lastfm events and google_timeline places."""
        now = 1_700_000_000
        events = [
            {
                "source_id": "lastfm",
                "timestamp": now + i * 60,
                "label": f"Artist{i}",
                "sublabel": f"Track{i}",
                "category": f"Album{i}",
                "raw_json": "{}",
                "fetched_at": now,
            }
            for i in range(event_count)
        ]
        places = [
            {
                "source_id": "google_timeline",
                "timestamp": now + i * 30,
                "lat": 51.5074 + i * 0.01,
                "lng": -0.1278 + i * 0.01,
                "place_name": f"Place{i}",
                "place_type": "visit",
                "raw_json": "{}",
                "fetched_at": now,
            }
            for i in range(place_count)
        ]
        with LocalizerStore(path=self.db_path) as store:
            store.upsert_events(events)
            store.upsert_places(places)

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

    def test_render_sidebar_populates_df_from_seeded_broker_store(self):
        """Acceptance criterion: a seeded store populates st.session_state['df']."""
        st = self._run_render_sidebar()
        df = st.session_state.get("df")
        self.assertIsNotNone(
            df,
            "render_sidebar() left session_state['df'] as None with a seeded "
            "DuckDB store and no legacy config — the broker-mode branch is not "
            "wired into render_sidebar() yet.",
        )
        self.assertFalse(df.empty, "session_state['df'] was populated but empty.")
        self.assertIn("artist", df.columns)
        self.assertIn("Artist0", df["artist"].tolist())

    def test_render_sidebar_populates_swarm_df_from_seeded_broker_store(self):
        """Acceptance criterion: a seeded store populates st.session_state['swarm_df']."""
        st = self._run_render_sidebar()
        swarm_df = st.session_state.get("swarm_df")
        self.assertIsNotNone(
            swarm_df,
            "render_sidebar() left session_state['swarm_df'] as None with a "
            "seeded DuckDB store — the broker-mode branch is not wired in.",
        )
        self.assertFalse(swarm_df.empty, "session_state['swarm_df'] was populated but empty.")
        self.assertIn("lat", swarm_df.columns)
        self.assertIn("lng", swarm_df.columns)
        self.assertIn(51.5074, swarm_df["lat"].tolist())

    def test_cache_status_is_na_literal_in_broker_mode(self):
        """Task Overview decision 5: broker mode must never report hit/miss."""
        st = self._run_render_sidebar()
        self.assertEqual(
            st.session_state.get("_cache_status"),
            "n/a",
            "In broker mode, session_state['_cache_status'] must be the literal "
            "'n/a' (the file-hash cache is not exercised at all); got "
            f"{st.session_state.get('_cache_status')!r}.",
        )

    def test_render_sidebar_reload_skip_and_trigger_on_store_mtime(self):
        """Reload-skip/trigger: only re-query the store when its mtime changes.

        Spies on the real LocalizerStore.query_events()/query_places() (existing
        methods, not new Subtask 1/2 surface) so this test doesn't depend on the
        exact internal helper names Subtask 3 chooses.
        """
        call_counts = {"events": 0, "places": 0}
        original_query_events = LocalizerStore.query_events
        original_query_places = LocalizerStore.query_places

        def counted_query_events(self, *args, **kwargs):
            call_counts["events"] += 1
            return original_query_events(self, *args, **kwargs)

        def counted_query_places(self, *args, **kwargs):
            call_counts["places"] += 1
            return original_query_places(self, *args, **kwargs)

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
            patch.object(LocalizerStore, "query_events", counted_query_events),
            patch.object(LocalizerStore, "query_places", counted_query_places),
        ):
            sidebar.render_sidebar()
            self.assertGreater(
                call_counts["events"],
                0,
                "render_sidebar() with a seeded broker store never queried events "
                "via LocalizerStore.query_events() — the broker-mode load path is "
                "not wired in.",
            )
            after_first = dict(call_counts)

            # Second call, store unchanged: reload-skip means zero additional queries.
            sidebar.render_sidebar()
            self.assertEqual(
                call_counts["events"],
                after_first["events"],
                "render_sidebar() re-queried the store on an unchanged mtime — "
                "reload-skip is not implemented.",
            )

            # Bump the store file's mtime; a third call must trigger exactly one
            # more query (proving the mtime-based identity actually invalidates).
            current_mtime = self.db_path.stat().st_mtime
            os.utime(self.db_path, (current_mtime + 5, current_mtime + 5))
            sidebar.render_sidebar()
            self.assertEqual(
                call_counts["events"],
                after_first["events"] + 1,
                "render_sidebar() did not reload after the store's mtime changed.",
            )


if __name__ == "__main__":
    unittest.main()
