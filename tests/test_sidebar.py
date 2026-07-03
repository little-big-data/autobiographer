"""Tests for components.sidebar data loading — Google Timeline / Swarm combination."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

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
            patch.object(sidebar, "apply_swarm_offsets", return_value=self.raw_df),
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


if __name__ == "__main__":
    unittest.main()
