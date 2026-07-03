"""Unit tests for the source plugin infrastructure and built-in plugins."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from plugins.sources import REGISTRY, load_builtin_plugins
from plugins.sources.assumptions.loader import AssumptionsPlugin
from plugins.sources.base import SourcePlugin, validate_schema
from plugins.sources.google_timeline.loader import GoogleTimelinePlugin
from plugins.sources.lastfm.loader import LastFmPlugin
from plugins.sources.swarm.loader import SwarmPlugin


class TestValidateSchema(unittest.TestCase):
    """Tests for the schema validation helper."""

    def test_valid_what_when_schema_passes(self):
        df = pd.DataFrame(
            {
                "timestamp": [1610000000],
                "label": ["Artist A"],
                "sublabel": ["Track A"],
                "category": ["Album A"],
                "source_id": ["lastfm"],
            }
        )
        # Should not raise.
        validate_schema(df, "what-when")

    def test_valid_where_when_schema_passes(self):
        df = pd.DataFrame(
            {
                "timestamp": [1610000000],
                "lat": [40.71],
                "lng": [-74.00],
                "place_name": ["New York"],
                "place_type": ["city"],
                "source_id": ["swarm"],
            }
        )
        validate_schema(df, "where-when")

    def test_missing_column_raises(self):
        df = pd.DataFrame({"timestamp": [1], "label": ["A"]})
        with self.assertRaises(ValueError) as ctx:
            validate_schema(df, "what-when")
        self.assertIn("sublabel", str(ctx.exception))

    def test_unknown_plugin_type_passes(self):
        # Unknown types have no required columns — should not raise.
        df = pd.DataFrame({"anything": [1]})
        validate_schema(df, "unknown-type")


class TestRegistry(unittest.TestCase):
    """Tests for the plugin registry."""

    def setUp(self):
        load_builtin_plugins()

    def test_lastfm_registered(self):
        self.assertIn("lastfm", REGISTRY)

    def test_swarm_registered(self):
        self.assertIn("swarm", REGISTRY)

    def test_assumptions_registered(self):
        self.assertIn("assumptions", REGISTRY)

    def test_google_timeline_registered(self):
        self.assertIn("google_timeline", REGISTRY)

    def test_registry_values_are_source_plugin_subclasses(self):
        for plugin_cls in REGISTRY.values():
            self.assertTrue(issubclass(plugin_cls, SourcePlugin))


class TestLastFmPlugin(unittest.TestCase):
    """Tests for the LastFmPlugin."""

    def setUp(self):
        self.plugin = LastFmPlugin()
        self.fixture_df = pd.DataFrame(
            {
                "artist": ["Radiohead", "Radiohead"],
                "album": ["OK Computer", "OK Computer"],
                "track": ["Karma Police", "Exit Music"],
                "timestamp": [1610000000, 1610000100],
                "date_text": pd.to_datetime(["2021-01-07 10:00", "2021-01-07 10:05"]),
            }
        )

    def test_plugin_type(self):
        self.assertEqual(self.plugin.PLUGIN_TYPE, "what-when")

    def test_plugin_id(self):
        self.assertEqual(self.plugin.PLUGIN_ID, "lastfm")

    def test_config_fields_returns_list(self):
        fields = self.plugin.get_config_fields()
        self.assertIsInstance(fields, list)
        self.assertTrue(any(f["key"] == "data_path" for f in fields))

    def test_config_field_type_is_file_path(self):
        fields = self.plugin.get_config_fields()
        data_path_field = next(f for f in fields if f["key"] == "data_path")
        self.assertEqual(data_path_field["type"], "file_path")

    def test_config_field_has_file_types(self):
        fields = self.plugin.get_config_fields()
        data_path_field = next(f for f in fields if f["key"] == "data_path")
        self.assertIn("file_types", data_path_field)
        self.assertIsInstance(data_path_field["file_types"], list)

    def test_load_adds_normalized_columns(self):
        with patch("analysis_utils.load_listening_data") as mock_load:
            mock_load.return_value = self.fixture_df.copy()
            df = self.plugin.load({"data_path": "fake/path.csv"})

        self.assertIn("label", df.columns)
        self.assertIn("sublabel", df.columns)
        self.assertIn("category", df.columns)
        self.assertIn("source_id", df.columns)
        self.assertEqual(df["label"].iloc[0], "Radiohead")
        self.assertEqual(df["sublabel"].iloc[0], "Karma Police")
        self.assertEqual(df["source_id"].iloc[0], "lastfm")

    def test_load_preserves_original_columns(self):
        with patch("analysis_utils.load_listening_data") as mock_load:
            mock_load.return_value = self.fixture_df.copy()
            df = self.plugin.load({"data_path": "fake/path.csv"})

        # Original columns must still be present for backward compat.
        self.assertIn("artist", df.columns)
        self.assertIn("track", df.columns)
        self.assertIn("album", df.columns)

    def test_load_returns_empty_df_when_source_empty(self):
        with patch("analysis_utils.load_listening_data") as mock_load:
            mock_load.return_value = pd.DataFrame()
            df = self.plugin.load({"data_path": "fake/path.csv"})

        self.assertTrue(df.empty)

    def test_get_schema_returns_dict(self):
        schema = self.plugin.get_schema()
        self.assertIsInstance(schema, dict)
        self.assertIn("label", schema)


class TestSwarmPlugin(unittest.TestCase):
    """Tests for the SwarmPlugin."""

    def setUp(self):
        self.plugin = SwarmPlugin()
        self.fixture_df = pd.DataFrame(
            {
                "timestamp": [1610000000, 1610000200],
                "lat": [40.71, 51.50],
                "lng": [-74.00, -0.12],
                "place_name": ["New York", "London"],
                "source": ["venue", "venue"],
                "city": ["New York", "London"],
                "country": ["US", "GB"],
            }
        )

    def test_plugin_type(self):
        self.assertEqual(self.plugin.PLUGIN_TYPE, "where-when")

    def test_plugin_id(self):
        self.assertEqual(self.plugin.PLUGIN_ID, "swarm")

    def test_config_fields_returns_list(self):
        fields = self.plugin.get_config_fields()
        self.assertIsInstance(fields, list)
        self.assertTrue(any(f["key"] == "swarm_dir" for f in fields))

    def test_swarm_dir_field_type_is_dir_path(self):
        fields = self.plugin.get_config_fields()
        swarm_dir_field = next(f for f in fields if f["key"] == "swarm_dir")
        self.assertEqual(swarm_dir_field["type"], "dir_path")

    def test_load_adds_normalized_columns(self):
        with patch("analysis_utils.load_swarm_data") as mock_load:
            mock_load.return_value = self.fixture_df.copy()
            df = self.plugin.load({"swarm_dir": "fake/swarm"})

        self.assertIn("place_type", df.columns)
        self.assertIn("source_id", df.columns)
        self.assertEqual(df["source_id"].iloc[0], "swarm")

    def test_load_returns_empty_df_when_no_swarm_dir(self):
        df = self.plugin.load({"swarm_dir": ""})
        self.assertTrue(df.empty)

    def test_load_returns_empty_df_when_source_empty(self):
        with patch("analysis_utils.load_swarm_data") as mock_load:
            mock_load.return_value = pd.DataFrame()
            df = self.plugin.load({"swarm_dir": "fake/swarm"})

        self.assertTrue(df.empty)

    def test_get_schema_returns_dict(self):
        schema = self.plugin.get_schema()
        self.assertIsInstance(schema, dict)
        self.assertIn("lat", schema)


class TestGoogleTimelinePlugin(unittest.TestCase):
    """Tests for the GoogleTimelinePlugin."""

    def setUp(self):
        self.plugin = GoogleTimelinePlugin()
        # Parser output shape: same columns as load_swarm_data.
        self.fixture_df = pd.DataFrame(
            {
                "timestamp": [1610000000, 1610000200],
                "offset": [-300, -300],
                "city": ["TestCity", "TestCity"],
                "state": ["TestState", "TestState"],
                "country": ["US", "US"],
                "venue": ["My Home Base", "Walking"],
                "venue_category": ["home", "activity:walking"],
                "lat": [40.0, 43.0],
                "lng": [-74.0, -77.0],
                "event_category": ["", ""],
                "shout": ["", ""],
            }
        )

    def test_plugin_type(self):
        self.assertEqual(self.plugin.PLUGIN_TYPE, "where-when")

    def test_plugin_id(self):
        self.assertEqual(self.plugin.PLUGIN_ID, "google_timeline")

    def test_not_fetchable(self):
        self.assertFalse(self.plugin.FETCHABLE)

    def test_fetch_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.plugin.fetch()

    def test_config_fields_returns_list(self):
        fields = self.plugin.get_config_fields()
        self.assertIsInstance(fields, list)
        self.assertTrue(any(f["key"] == "timeline_path" for f in fields))

    def test_timeline_path_field_type_is_file_path(self):
        fields = self.plugin.get_config_fields()
        field = next(f for f in fields if f["key"] == "timeline_path")
        self.assertEqual(field["type"], "file_path")
        self.assertIn("file_types", field)

    def test_load_adds_normalized_columns(self):
        with patch("analysis_utils.load_google_timeline") as mock_load:
            mock_load.return_value = self.fixture_df.copy()
            df = self.plugin.load({"timeline_path": "fake/Timeline.json"})

        self.assertIn("place_name", df.columns)
        self.assertIn("place_type", df.columns)
        self.assertIn("source_id", df.columns)
        self.assertEqual(df["place_name"].iloc[0], "My Home Base")
        self.assertEqual(df["place_type"].iloc[0], "home")
        self.assertEqual(df["source_id"].iloc[0], "google_timeline")

    def test_load_passes_schema_validation(self):
        with patch("analysis_utils.load_google_timeline") as mock_load:
            mock_load.return_value = self.fixture_df.copy()
            df = self.plugin.load({"timeline_path": "fake/Timeline.json"})
        # Should not raise — all where-when columns present.
        validate_schema(df, "where-when")

    def test_load_returns_empty_df_when_no_path(self):
        df = self.plugin.load({"timeline_path": ""})
        self.assertTrue(df.empty)

    def test_load_returns_empty_df_when_source_empty(self):
        with patch("analysis_utils.load_google_timeline") as mock_load:
            mock_load.return_value = pd.DataFrame()
            df = self.plugin.load({"timeline_path": "fake/Timeline.json"})
        self.assertTrue(df.empty)

    def test_get_schema_returns_dict(self):
        schema = self.plugin.get_schema()
        self.assertIsInstance(schema, dict)
        self.assertIn("lat", schema)

    def test_manual_download_instructions_mention_takeout(self):
        instructions = self.plugin.get_manual_download_instructions()
        self.assertIn("Takeout", instructions)
        self.assertIn("Timeline", instructions)


class TestAssumptionsPlugin(unittest.TestCase):
    """Tests for the AssumptionsPlugin."""

    def setUp(self):
        self.plugin = AssumptionsPlugin()
        self.fixture_data = {
            "defaults": {
                "city": "London, GB",
                "lat": 51.5074,
                "lng": -0.1278,
                "timezone": "Europe/London",
            },
            "trips": [
                {
                    "start": "2023-06-01",
                    "end": "2023-06-07",
                    "city": "Paris, FR",
                    "lat": 48.8566,
                    "lng": 2.3522,
                    "timezone": "Europe/Paris",
                }
            ],
            "holidays": [
                {
                    "name": "Christmas",
                    "month": 12,
                    "day_range": [24, 26],
                    "city": "Edinburgh, GB",
                    "lat": 55.9533,
                    "lng": -3.1883,
                    "timezone": "Europe/London",
                }
            ],
            "residency": [
                {
                    "start": "2020-01-01",
                    "end": "2025-12-31",
                    "city": "Home",
                    "sub_rules": [],
                }
            ],
        }

    def test_plugin_type(self):
        self.assertEqual(self.plugin.PLUGIN_TYPE, "location-context")

    def test_plugin_id(self):
        self.assertEqual(self.plugin.PLUGIN_ID, "assumptions")

    def test_config_fields_returns_list(self):
        fields = self.plugin.get_config_fields()
        self.assertIsInstance(fields, list)
        self.assertTrue(any(f["key"] == "assumptions_file" for f in fields))

    def test_config_field_type_is_file_path(self):
        fields = self.plugin.get_config_fields()
        field = next(f for f in fields if f["key"] == "assumptions_file")
        self.assertEqual(field["type"], "file_path")
        self.assertIn("file_types", field)

    def test_load_returns_dataframe(self):
        with patch("analysis_utils.load_assumptions") as mock_load:
            mock_load.return_value = self.fixture_data
            df = self.plugin.load({"assumptions_file": "fake/path.json"})
        self.assertIsInstance(df, pd.DataFrame)

    def test_load_includes_trip_row(self):
        with patch("analysis_utils.load_assumptions") as mock_load:
            mock_load.return_value = self.fixture_data
            df = self.plugin.load({"assumptions_file": "fake/path.json"})
        trips = df[df["type"] == "trip"]
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips.iloc[0]["city"], "Paris, FR")

    def test_load_includes_holiday_row(self):
        with patch("analysis_utils.load_assumptions") as mock_load:
            mock_load.return_value = self.fixture_data
            df = self.plugin.load({"assumptions_file": "fake/path.json"})
        holidays = df[df["type"] == "holiday"]
        self.assertEqual(len(holidays), 1)
        self.assertEqual(holidays.iloc[0]["city"], "Edinburgh, GB")

    def test_load_includes_default_row(self):
        with patch("analysis_utils.load_assumptions") as mock_load:
            mock_load.return_value = self.fixture_data
            df = self.plugin.load({"assumptions_file": "fake/path.json"})
        defaults = df[df["type"] == "default"]
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults.iloc[0]["city"], "London, GB")

    def test_load_includes_residency_row(self):
        with patch("analysis_utils.load_assumptions") as mock_load:
            mock_load.return_value = self.fixture_data
            df = self.plugin.load({"assumptions_file": "fake/path.json"})
        residency = df[df["type"] == "residency"]
        self.assertEqual(len(residency), 1)

    def test_load_returns_empty_df_when_no_data(self):
        with patch("analysis_utils.load_assumptions") as mock_load:
            mock_load.return_value = {"defaults": {}, "trips": [], "holidays": [], "residency": []}
            df = self.plugin.load({"assumptions_file": ""})
        self.assertTrue(df.empty)

    def test_get_schema_returns_dict(self):
        schema = self.plugin.get_schema()
        self.assertIsInstance(schema, dict)
        self.assertIn("type", schema)
        self.assertIn("city", schema)

    def test_get_manual_download_instructions_mentions_example_file(self):
        instructions = self.plugin.get_manual_download_instructions()
        self.assertIn("default_assumptions.json.example", instructions)


class TestFetchability(unittest.TestCase):
    """Tests for FETCHABLE, get_fetch_env_vars, fetch, and get_manual_download_instructions."""

    def setUp(self):
        load_builtin_plugins()

    # --- base class defaults --------------------------------------------------

    def test_base_fetchable_is_false_by_default(self):
        plugin = SwarmPlugin()
        self.assertFalse(plugin.FETCHABLE)

    def test_base_get_fetch_env_vars_returns_empty_list(self):
        plugin = SwarmPlugin()
        self.assertEqual(plugin.get_fetch_env_vars(), [])

    def test_base_fetch_raises_not_implemented(self):
        plugin = SwarmPlugin()
        with self.assertRaises(NotImplementedError):
            plugin.fetch()

    def test_base_get_manual_download_instructions_returns_string(self):
        plugin = SwarmPlugin()
        instructions = plugin.get_manual_download_instructions()
        self.assertIsInstance(instructions, str)
        self.assertTrue(len(instructions) > 0)

    # --- LastFmPlugin ---------------------------------------------------------

    def test_lastfm_fetchable_is_true(self):
        self.assertTrue(LastFmPlugin.FETCHABLE)

    def test_lastfm_get_fetch_env_vars_lists_three_vars(self):
        plugin = LastFmPlugin()
        env_vars = plugin.get_fetch_env_vars()
        var_names = [v["var"] for v in env_vars]
        self.assertIn("AUTOBIO_LASTFM_API_KEY", var_names)
        self.assertIn("AUTOBIO_LASTFM_API_SECRET", var_names)
        self.assertIn("AUTOBIO_LASTFM_USERNAME", var_names)

    def test_lastfm_fetch_env_var_dicts_have_description(self):
        plugin = LastFmPlugin()
        for entry in plugin.get_fetch_env_vars():
            self.assertIn("var", entry)
            self.assertIn("description", entry)
            self.assertTrue(entry["description"])

    def test_lastfm_fetch_raises_os_error_when_env_vars_missing(self):
        plugin = LastFmPlugin()
        with patch("os.getenv", return_value=None):
            with self.assertRaises(OSError) as ctx:
                plugin.fetch()
        self.assertIn("AUTOBIO_LASTFM_API_KEY", str(ctx.exception))

    def test_lastfm_fetch_calls_autobiographer_when_env_vars_set(self):
        plugin = LastFmPlugin()
        env = {
            "AUTOBIO_LASTFM_API_KEY": "key",
            "AUTOBIO_LASTFM_API_SECRET": "secret",
            "AUTOBIO_LASTFM_USERNAME": "user",
        }
        mock_client = MagicMock()
        mock_client.fetch_recent_tracks.return_value = []
        with (
            patch("os.getenv", side_effect=lambda k, default="": env.get(k, default)),
            patch("autobiographer.Autobiographer", return_value=mock_client),
        ):
            plugin.fetch(output_path="/tmp/out.csv", pages=2)

        mock_client.fetch_recent_tracks.assert_called_once_with(
            pages=2,
            from_ts=None,
            to_ts=None,
            progress_callback=None,
            checkpoint=None,
            resume=False,
            max_retries=3,
        )
        mock_client.save_tracks_to_csv.assert_called_once_with([], filename="/tmp/out.csv")

    def test_lastfm_get_manual_download_instructions_mentions_command(self):
        plugin = LastFmPlugin()
        instructions = plugin.get_manual_download_instructions()
        self.assertIn("autobiographer.py fetch lastfm", instructions)

    # --- SwarmPlugin ----------------------------------------------------------

    def test_swarm_get_manual_download_instructions_mentions_foursquare(self):
        plugin = SwarmPlugin()
        instructions = plugin.get_manual_download_instructions()
        self.assertIn("Foursquare", instructions)

    def test_swarm_get_manual_download_instructions_has_steps(self):
        plugin = SwarmPlugin()
        instructions = plugin.get_manual_download_instructions()
        # Instructions should walk the user through numbered steps.
        self.assertIn("1.", instructions)


if __name__ == "__main__":
    unittest.main()
