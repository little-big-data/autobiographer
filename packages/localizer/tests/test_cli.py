"""Failing tests for Subtask 5: localizer CLI.

All tests here are expected to FAIL (RED) until the coder implements:
  - packages/localizer/src/localizer/cli.py
  - packages/localizer/src/localizer/settings.py
  - Updated packages/localizer/pyproject.toml (entry point)

All CLI tests use click.testing.CliRunner and inject a temp DuckDB store
path via the LOCALIZER_DB_PATH environment variable.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Import under test — will raise ImportError until cli.py is created.
# ---------------------------------------------------------------------------
from localizer.cli import cli  # type: ignore[import]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_events(n: int, source_id: str = "lastfm") -> list[dict[str, Any]]:
    """Return n minimal event dicts suitable for upsert_events()."""
    return [
        {
            "source_id": source_id,
            "timestamp": 1_000_000 + i,
            "label": f"Artist{i}",
            "sublabel": f"Track{i}",
            "category": f"Album{i}",
            "raw_json": None,
            "fetched_at": int(time.time()),
        }
        for i in range(n)
    ]


def _make_places(n: int, source_id: str = "swarm") -> list[dict[str, Any]]:
    """Return n minimal place dicts suitable for upsert_places()."""
    return [
        {
            "source_id": source_id,
            "timestamp": 2_000_000 + i,
            "lat": 37.7749 + i * 0.001,
            "lng": -122.4194 + i * 0.001,
            "place_name": f"Cafe {i}",
            "place_type": "coffee",
            "raw_json": None,
            "fetched_at": int(time.time()),
        }
        for i in range(n)
    ]


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Return a path to a fresh DuckDB file in a temp directory."""
    return tmp_path / "store.duckdb"


@pytest.fixture()
def seeded_db(tmp_db: Path) -> Path:
    """Seed the temp store with 42 events and 17 places, return its path."""
    from localizer.store.db import LocalizerStore

    with LocalizerStore(tmp_db) as store:
        store.upsert_events(_make_events(42))
        store.upsert_places(_make_places(17))
    return tmp_db


# ---------------------------------------------------------------------------
# 1. Help exits zero
# ---------------------------------------------------------------------------


def test_help_exits_zero(tmp_db: Path) -> None:
    """localizer --help must exit with code 0."""
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}
    result = runner.invoke(cli, ["--help"], env=env)
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# 2-5. sources command
# ---------------------------------------------------------------------------


def test_sources_lists_lastfm(tmp_db: Path) -> None:
    """localizer sources output must contain 'lastfm'."""
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}
    result = runner.invoke(cli, ["sources"], env=env)
    assert result.exit_code == 0, result.output
    assert "lastfm" in result.output


def test_sources_lists_swarm(tmp_db: Path) -> None:
    """localizer sources output must contain 'swarm'."""
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}
    result = runner.invoke(cli, ["sources"], env=env)
    assert result.exit_code == 0, result.output
    assert "swarm" in result.output


def test_sources_shows_api_mode(tmp_db: Path) -> None:
    """localizer sources must show 'API' for Last.fm (FetchMode.API)."""
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}
    result = runner.invoke(cli, ["sources"], env=env)
    assert result.exit_code == 0, result.output
    assert "API" in result.output


def test_sources_shows_manual_mode(tmp_db: Path) -> None:
    """localizer sources must show 'MANUAL' for Swarm (FetchMode.MANUAL)."""
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}
    result = runner.invoke(cli, ["sources"], env=env)
    assert result.exit_code == 0, result.output
    assert "MANUAL" in result.output


# ---------------------------------------------------------------------------
# Subtask 2: GoogleTimelinePlugin registration in load_builtin_plugins()
# ---------------------------------------------------------------------------
#
# These tests are expected to FAIL (RED) until the coder:
#   - imports GoogleTimelinePlugin in
#     packages/localizer/src/localizer/plugins/__init__.py::load_builtin_plugins()
#   - assigns REGISTRY[GoogleTimelinePlugin.PLUGIN_ID] = GoogleTimelinePlugin
#
# They depend on Subtask 1's GoogleTimelinePlugin class
# (packages/localizer/src/localizer/plugins/google_timeline/loader.py) existing,
# which is implemented separately. Until that module exists, the REGISTRY-level
# test below fails with ModuleNotFoundError (an acceptable RED reason at this
# stage) rather than an assertion failure.


def test_sources_lists_google_timeline(tmp_db: Path) -> None:
    """localizer sources output must list google_timeline as MANUAL / places.

    Mirrors test_sources_lists_swarm / test_sources_shows_manual_mode. Asserts
    the exact "{plugin_id}  {mode_name}  {table_names}" line format used by
    sources_cmd() in cli.py, so both the fetch mode and output table acceptance
    criteria are covered in one test.
    """
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}
    result = runner.invoke(cli, ["sources"], env=env)
    assert result.exit_code == 0, result.output
    assert "google_timeline" in result.output
    assert "google_timeline  MANUAL  places" in result.output


def test_google_timeline_plugin_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['google_timeline'] must map to GoogleTimelinePlugin.

    Mirrors test_swarm_plugin_is_registered in test_swarm_plugin.py.
    """
    from localizer.plugins import REGISTRY, load_builtin_plugins
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    REGISTRY.clear()
    load_builtin_plugins()
    assert "google_timeline" in REGISTRY, (
        "Expected 'google_timeline' key in REGISTRY after load_builtin_plugins()"
    )
    assert REGISTRY["google_timeline"] is GoogleTimelinePlugin


def test_other_plugins_still_registered_alongside_google_timeline() -> None:
    """Registering google_timeline must not disturb any existing plugin's entry.

    Regression check called out in Subtask 2's Test Guidance: every other
    builtin plugin must still be present in REGISTRY, unmodified, once
    google_timeline is wired in.
    """
    from localizer.plugins import REGISTRY, load_builtin_plugins

    REGISTRY.clear()
    load_builtin_plugins()
    for expected_id in (
        "swarm",
        "lastfm",
        "github",
        "feedly",
        "rss",
        "letterboxd",
        "google_timeline",
    ):
        assert expected_id in REGISTRY, f"Expected {expected_id!r} in REGISTRY"


# ---------------------------------------------------------------------------
# 6. status shows record counts
# ---------------------------------------------------------------------------


def test_status_shows_record_counts(seeded_db: Path) -> None:
    """localizer status against a seeded store must output '42' and '17'."""
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(seeded_db)}
    result = runner.invoke(cli, ["status"], env=env)
    assert result.exit_code == 0, result.output
    assert "42" in result.output
    assert "17" in result.output


# ---------------------------------------------------------------------------
# 7. status --json produces valid JSON
# ---------------------------------------------------------------------------


def test_status_json_is_valid(seeded_db: Path) -> None:
    """localizer status --json must emit valid JSON with event and place counts."""
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(seeded_db)}
    result = runner.invoke(cli, ["status", "--json"], env=env)
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    assert isinstance(data, dict), "Output must be a JSON object"

    # The JSON must contain event and place counts with the expected values.
    # Accept either top-level keys or nested under a 'counts' / 'tables' key.
    flat = json.dumps(data)
    assert "42" in flat, f"Expected event count 42 in JSON: {result.output}"
    assert "17" in flat, f"Expected place count 17 in JSON: {result.output}"


# ---------------------------------------------------------------------------
# 8. export parquet creates a readable file
# ---------------------------------------------------------------------------


def test_export_parquet_creates_file(seeded_db: Path, tmp_path: Path) -> None:
    """localizer export --format parquet must create a .parquet file readable by pandas."""
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(seeded_db)}
    result = runner.invoke(
        cli,
        ["export", "--format", "parquet", "--output", str(output_dir)],
        env=env,
    )
    assert result.exit_code == 0, result.output

    parquet_files = list(output_dir.glob("*.parquet"))
    assert len(parquet_files) >= 1, (
        f"Expected at least one .parquet file in {output_dir}; got none. "
        f"CLI output: {result.output}"
    )

    df = pd.read_parquet(parquet_files[0])
    assert len(df) > 0, "Parquet file must contain at least one row"


# ---------------------------------------------------------------------------
# 9. db path prints store path
# ---------------------------------------------------------------------------


def test_db_path_prints_store_path(tmp_db: Path) -> None:
    """localizer db path must print a path ending with 'store.duckdb'."""
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}
    result = runner.invoke(cli, ["db", "path"], env=env)
    assert result.exit_code == 0, result.output
    assert result.output.strip().endswith("store.duckdb"), (
        f"Expected output ending with 'store.duckdb', got: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# 10. fetch nonexistent source exits non-zero with readable error
# ---------------------------------------------------------------------------


def test_fetch_nonexistent_source_exits_nonzero(tmp_db: Path) -> None:
    """localizer fetch nonexistent must exit non-zero with a human-readable error."""
    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}
    result = runner.invoke(cli, ["fetch", "nonexistent"], env=env)
    assert result.exit_code != 0, (
        f"Expected non-zero exit for unknown source, got 0. Output: {result.output}"
    )
    # Must not be a raw Python traceback
    assert "Traceback" not in result.output, (
        f"Expected a clean error message, not a traceback: {result.output}"
    )
    # Must contain something human-readable about the unknown source
    lower_output = result.output.lower()
    found_mention = (
        "nonexistent" in lower_output or "unknown" in lower_output or "not found" in lower_output
    )
    assert found_mention, f"Expected error mentioning the unknown source, got: {result.output}"


# ---------------------------------------------------------------------------
# 11. config set and show
# ---------------------------------------------------------------------------


def test_config_set_and_show(tmp_db: Path, tmp_path: Path) -> None:
    """localizer config set mykey myval then config show must include 'mykey' and 'myval'."""
    runner = CliRunner()
    # Use a temp config file so we don't pollute ~/.localizer/config.toml.
    config_path = tmp_path / "config.toml"
    env = {
        **os.environ,
        "LOCALIZER_DB_PATH": str(tmp_db),
        "LOCALIZER_CONFIG_PATH": str(config_path),
    }

    set_result = runner.invoke(cli, ["config", "set", "mykey", "myval"], env=env)
    assert set_result.exit_code == 0, set_result.output

    show_result = runner.invoke(cli, ["config", "show"], env=env)
    assert show_result.exit_code == 0, show_result.output
    assert "mykey" in show_result.output
    assert "myval" in show_result.output


# ---------------------------------------------------------------------------
# 12. sync --dry-run does not write to store
# ---------------------------------------------------------------------------


def test_sync_dry_run_does_not_write(tmp_db: Path) -> None:
    """localizer sync --dry-run must not write any rows to the store."""
    # Yield one dict from LastFmPlugin.fetch_records and one from SwarmPlugin.fetch_records.
    fake_event = {
        "source_id": "lastfm",
        "timestamp": 1_500_000,
        "label": "DryArtist",
        "sublabel": "DryTrack",
        "category": "DryAlbum",
        "raw_json": None,
        "fetched_at": int(time.time()),
    }
    fake_place = {
        "source_id": "swarm",
        "timestamp": 1_600_000,
        "lat": 40.7128,
        "lng": -74.006,
        "place_name": "DryPlace",
        "place_type": "park",
        "raw_json": None,
        "fetched_at": int(time.time()),
    }

    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}

    with (
        patch(
            "localizer.plugins.lastfm.loader.LastFmPlugin.fetch_records",
            return_value=iter([fake_event]),
        ),
        patch(
            "localizer.plugins.swarm.loader.SwarmPlugin.fetch_records",
            return_value=iter([fake_place]),
        ),
    ):
        result = runner.invoke(cli, ["sync", "--dry-run"], env=env)

    assert result.exit_code == 0, result.output

    # Verify zero rows were written.
    from localizer.store.db import LocalizerStore

    with LocalizerStore(tmp_db) as store:
        assert len(store.query_events()) == 0, (
            f"--dry-run must not write events; found rows after sync --dry-run. "
            f"CLI output: {result.output}"
        )
        assert len(store.query_places()) == 0, (
            f"--dry-run must not write places; found rows after sync --dry-run. "
            f"CLI output: {result.output}"
        )


# ---------------------------------------------------------------------------
# 13. fetch --dry-run does not write but mentions record count
# ---------------------------------------------------------------------------


def test_fetch_dry_run_does_not_write(tmp_db: Path) -> None:
    """localizer fetch lastfm --dry-run must not write rows but mention the 3 records."""
    fake_events = [
        {
            "source_id": "lastfm",
            "timestamp": 1_700_000 + i,
            "label": f"DryArtist{i}",
            "sublabel": f"DryTrack{i}",
            "category": "DryAlbum",
            "raw_json": None,
            "fetched_at": int(time.time()),
        }
        for i in range(3)
    ]

    runner = CliRunner()
    env = {
        **os.environ,
        "LOCALIZER_DB_PATH": str(tmp_db),
        # Provide dummy credentials so fetch_records doesn't fail on env lookup.
        "AUTOBIO_LASTFM_API_KEY": "dummy_key",
        "AUTOBIO_LASTFM_API_SECRET": "dummy_secret",
        "AUTOBIO_LASTFM_USERNAME": "dummy_user",
    }

    with patch(
        "localizer.plugins.lastfm.loader.LastFmPlugin.fetch_records",
        return_value=iter(fake_events),
    ):
        result = runner.invoke(cli, ["fetch", "lastfm", "--dry-run"], env=env)

    assert result.exit_code == 0, result.output

    # Must mention that 3 records were found / would be written.
    assert "3" in result.output, (
        f"Expected CLI to mention the 3 dry-run records, got: {result.output}"
    )

    # Must not have written anything to the store.
    from localizer.store.db import LocalizerStore

    with LocalizerStore(tmp_db) as store:
        assert len(store.query_events()) == 0, (
            f"--dry-run must not write events; store has rows after fetch --dry-run. "
            f"CLI output: {result.output}"
        )


# ---------------------------------------------------------------------------
# 14. Dual-output plugin (FlickrPlugin) routes to both PLACES and EVENTS
# ---------------------------------------------------------------------------


def test_sync_writes_dual_output_plugin_to_both_tables(tmp_db: Path) -> None:
    """A plugin with OUTPUT_TABLES=[PLACES, EVENTS] (FlickrPlugin) must write its
    primary fetch_records() stream to places AND its fetch_secondary_records()
    stream to events — not collapse both into one table."""
    fake_place = {
        "source_id": "flickr",
        "timestamp": 1_800_000,
        "lat": 51.5074,
        "lng": -0.1278,
        "place_name": "Geotagged Photo",
        "place_type": "photo",
        "raw_json": None,
        "fetched_at": int(time.time()),
    }
    fake_events = [
        {
            "source_id": "flickr",
            "timestamp": 1_800_000 + i,
            "label": f"Photo {i}",
            "sublabel": "Album",
            "category": "photo",
            "raw_json": None,
            "fetched_at": int(time.time()),
        }
        for i in range(2)
    ]

    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}

    # Scope the registry to just FlickrPlugin so `sync` never touches the
    # real (network-calling) API plugins — this test only cares about
    # dual-output dispatch, not the other plugins' fetch behavior.
    from localizer.plugins.flickr.loader import FlickrPlugin

    def _fake_load_builtin_plugins() -> None:
        from localizer.plugins import REGISTRY  # noqa: PLC0415

        REGISTRY.clear()
        REGISTRY["flickr"] = FlickrPlugin

    with (
        patch(
            "localizer.plugins.flickr.loader.FlickrPlugin.fetch_records",
            return_value=iter([fake_place]),
        ),
        patch(
            "localizer.plugins.flickr.loader.FlickrPlugin.fetch_secondary_records",
            return_value=iter(fake_events),
        ),
        patch("localizer.plugins.load_builtin_plugins", _fake_load_builtin_plugins),
    ):
        result = runner.invoke(cli, ["sync"], env=env)

    assert result.exit_code == 0, result.output

    from localizer.store.db import LocalizerStore

    with LocalizerStore(tmp_db) as store:
        places_df = store.query_places(source_id="flickr")
        events_df = store.query_events(source_id="flickr")

    assert len(places_df) == 1, (
        f"Expected 1 place row from FlickrPlugin's primary stream, got {len(places_df)}. "
        f"CLI output: {result.output}"
    )
    assert len(events_df) == 2, (
        f"Expected 2 event rows from FlickrPlugin's secondary stream, got {len(events_df)}. "
        f"CLI output: {result.output}"
    )


def test_fetch_writes_dual_output_plugin_to_both_tables(tmp_db: Path) -> None:
    """localizer fetch flickr must also route primary/secondary streams to
    places/events respectively (same guarantee as sync, single-source path)."""
    fake_place = {
        "source_id": "flickr",
        "timestamp": 1_900_000,
        "lat": 40.0,
        "lng": -74.0,
        "place_name": "Geotagged Photo 2",
        "place_type": "photo",
        "raw_json": None,
        "fetched_at": int(time.time()),
    }
    fake_event = {
        "source_id": "flickr",
        "timestamp": 1_900_001,
        "label": "Photo X",
        "sublabel": "",
        "category": "photo",
        "raw_json": None,
        "fetched_at": int(time.time()),
    }

    runner = CliRunner()
    env = {**os.environ, "LOCALIZER_DB_PATH": str(tmp_db)}

    with (
        patch(
            "localizer.plugins.flickr.loader.FlickrPlugin.fetch_records",
            return_value=iter([fake_place]),
        ),
        patch(
            "localizer.plugins.flickr.loader.FlickrPlugin.fetch_secondary_records",
            return_value=iter([fake_event]),
        ),
    ):
        result = runner.invoke(cli, ["fetch", "flickr"], env=env)

    assert result.exit_code == 0, result.output

    from localizer.store.db import LocalizerStore

    with LocalizerStore(tmp_db) as store:
        places_df = store.query_places(source_id="flickr")
        events_df = store.query_events(source_id="flickr")

    assert len(places_df) == 1
    assert len(events_df) == 1
