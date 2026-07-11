"""Unit tests for the DataBroker."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from core.broker import DataBroker
from plugins.sources.lastfm.loader import LastFmPlugin
from plugins.sources.swarm.loader import SwarmPlugin


def _make_lastfm_df() -> pd.DataFrame:
    """Return a minimal Last.fm-style DataFrame."""
    return pd.DataFrame(
        {
            "artist": ["Radiohead"],
            "album": ["OK Computer"],
            "track": ["Karma Police"],
            "timestamp": [1610000000],
            "date_text": pd.to_datetime(["2021-01-07 10:00"]),
            "label": ["Radiohead"],
            "sublabel": ["Karma Police"],
            "category": ["OK Computer"],
            "source_id": ["lastfm"],
        }
    )


def _make_swarm_df() -> pd.DataFrame:
    """Return a minimal Swarm-style DataFrame."""
    return pd.DataFrame(
        {
            "timestamp": [1610000000],
            "lat": [40.71],
            "lng": [-74.00],
            "place_name": ["New York"],
            "place_type": ["venue"],
            "source_id": ["swarm"],
        }
    )


class TestDataBrokerInit(unittest.TestCase):
    def test_empty_on_init(self):
        broker = DataBroker()
        self.assertEqual(broker.available_types, [])
        self.assertEqual(broker.get_frames(), {})

    def test_is_type_available_false_when_empty(self):
        broker = DataBroker()
        self.assertFalse(broker.is_type_available("what-when"))


class TestDataBrokerLoad(unittest.TestCase):
    def test_load_lastfm_registers_type(self):
        broker = DataBroker()
        plugin = LastFmPlugin()
        with patch.object(plugin, "load", return_value=_make_lastfm_df()):
            broker.load(plugin, {"data_path": "fake.csv"})

        self.assertIn("what-when", broker.available_types)
        self.assertIn("lastfm", broker.get_frames())

    def test_load_swarm_registers_type(self):
        broker = DataBroker()
        plugin = SwarmPlugin()
        with patch.object(plugin, "load", return_value=_make_swarm_df()):
            broker.load(plugin, {"swarm_dir": "fake/"})

        self.assertIn("where-when", broker.available_types)
        self.assertIn("swarm", broker.get_frames())

    def test_load_returns_dataframe(self):
        broker = DataBroker()
        plugin = LastFmPlugin()
        expected = _make_lastfm_df()
        with patch.object(plugin, "load", return_value=expected):
            result = broker.load(plugin, {"data_path": "fake.csv"})

        pd.testing.assert_frame_equal(result, expected)

    def test_duplicate_type_not_added_twice(self):
        broker = DataBroker()
        plugin = LastFmPlugin()
        with patch.object(plugin, "load", return_value=_make_lastfm_df()):
            broker.load(plugin, {"data_path": "fake.csv"})
            broker.load(plugin, {"data_path": "fake2.csv"})

        self.assertEqual(broker.available_types.count("what-when"), 1)


class TestDataBrokerGetFrame(unittest.TestCase):
    def test_get_frame_returns_loaded_df(self):
        broker = DataBroker()
        plugin = LastFmPlugin()
        df = _make_lastfm_df()
        with patch.object(plugin, "load", return_value=df):
            broker.load(plugin, {"data_path": "fake.csv"})

        pd.testing.assert_frame_equal(broker.get_frame("lastfm"), df)

    def test_get_frame_returns_empty_df_when_not_loaded(self):
        broker = DataBroker()
        result = broker.get_frame("nonexistent")
        self.assertTrue(result.empty)


class TestDataBrokerGetMergedFrame(unittest.TestCase):
    def test_returns_empty_when_no_lastfm(self):
        broker = DataBroker()
        result = broker.get_merged_frame()
        self.assertTrue(result.empty)

    def test_returns_lastfm_df_when_no_swarm(self):
        broker = DataBroker()
        plugin = LastFmPlugin()
        df = _make_lastfm_df()
        with patch.object(plugin, "load", return_value=df):
            broker.load(plugin, {"data_path": "fake.csv"})

        result = broker.get_merged_frame()
        pd.testing.assert_frame_equal(result, df)

    def test_returns_lastfm_df_when_assumptions_is_none(self):
        broker = DataBroker()
        lastfm_plugin = LastFmPlugin()
        swarm_plugin = SwarmPlugin()
        lastfm_df = _make_lastfm_df()
        swarm_df = _make_swarm_df()

        with patch.object(lastfm_plugin, "load", return_value=lastfm_df):
            broker.load(lastfm_plugin, {"data_path": "fake.csv"})
        with patch.object(swarm_plugin, "load", return_value=swarm_df):
            broker.load(swarm_plugin, {"swarm_dir": "fake/"})

        # No assumptions passed → skip merge, return raw Last.fm frame.
        result = broker.get_merged_frame(assumptions=None)
        pd.testing.assert_frame_equal(result, lastfm_df)

    def test_calls_apply_location_context_when_both_sources_loaded(self):
        broker = DataBroker()
        lastfm_plugin = LastFmPlugin()
        swarm_plugin = SwarmPlugin()
        lastfm_df = _make_lastfm_df()
        swarm_df = _make_swarm_df()
        assumptions = {"defaults": {}, "holidays": [], "trips": [], "residency": []}
        merged_df = lastfm_df.copy()
        merged_df["city"] = "New York"

        with patch.object(lastfm_plugin, "load", return_value=lastfm_df):
            broker.load(lastfm_plugin, {"data_path": "fake.csv"})
        with patch.object(swarm_plugin, "load", return_value=swarm_df):
            broker.load(swarm_plugin, {"swarm_dir": "fake/"})

        with patch("analysis_utils.apply_location_context", return_value=merged_df) as mock_merge:
            result = broker.get_merged_frame(assumptions=assumptions)

        mock_merge.assert_called_once()
        self.assertIn("city", result.columns)

    def test_unions_all_where_when_sources_when_multiple_loaded(self):
        """get_merged_frame() must union every loaded where-when source (Issue #110).

        Previously this hardcoded ``self._sources.get("swarm")``, silently
        dropping any other where-when plugin (e.g. Google Timeline) loaded
        alongside Swarm. It must now concatenate every source whose
        PLUGIN_TYPE is "where-when" before the temporal join.
        """
        from plugins.sources.google_timeline.loader import GoogleTimelinePlugin

        broker = DataBroker()
        lastfm_plugin = LastFmPlugin()
        swarm_plugin = SwarmPlugin()
        timeline_plugin = GoogleTimelinePlugin()

        lastfm_df = _make_lastfm_df()
        swarm_df = _make_swarm_df()
        timeline_df = pd.DataFrame(
            {
                "timestamp": [1620000000],
                "lat": [51.5],
                "lng": [-0.12],
                "place_name": ["London"],
                "place_type": ["visit"],
                "source_id": ["google_timeline"],
            }
        )
        assumptions = {"defaults": {}, "holidays": [], "trips": [], "residency": []}

        with patch.object(lastfm_plugin, "load", return_value=lastfm_df):
            broker.load(lastfm_plugin, {"data_path": "fake.csv"})
        with patch.object(swarm_plugin, "load", return_value=swarm_df):
            broker.load(swarm_plugin, {"swarm_dir": "fake/"})
        with patch.object(timeline_plugin, "load", return_value=timeline_df):
            broker.load(timeline_plugin, {"timeline_path": "fake.json"})

        with patch("analysis_utils.apply_location_context", return_value=lastfm_df) as mock_merge:
            broker.get_merged_frame(assumptions=assumptions)

        mock_merge.assert_called_once()
        combined_swarm_df = mock_merge.call_args[0][1]
        self.assertEqual(
            set(combined_swarm_df["source_id"]),
            {"swarm", "google_timeline"},
            "Expected get_merged_frame() to union all where-when sources' source_ids",
        )


class TestDataBrokerIsTypeAvailable(unittest.TestCase):
    def test_true_after_loading_matching_type(self):
        broker = DataBroker()
        plugin = LastFmPlugin()
        with patch.object(plugin, "load", return_value=_make_lastfm_df()):
            broker.load(plugin, {"data_path": "fake.csv"})

        self.assertTrue(broker.is_type_available("what-when"))
        self.assertFalse(broker.is_type_available("where-when"))


if __name__ == "__main__":
    unittest.main()
