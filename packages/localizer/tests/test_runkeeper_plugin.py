"""Failing tests for RunkeeperPlugin in the localizer package (issue #21).

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/runkeeper/__init__.py
  - packages/localizer/src/localizer/plugins/runkeeper/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py (load_builtin_plugins)

RunkeeperPlugin is FetchMode.MANUAL, OutputTable.EVENTS — it reads a single
``cardioActivities.csv`` summary file from an unzipped Runkeeper export
directory (mirroring flickr/loader.py's directory-based ``export_dir``
config field, and untappd/loader.py's FileNotFoundError-on-configured-
missing-file convention). Individual per-activity GPX files in the same
export directory are never parsed — Phase 1 only reads the summary CSV.

Field mapping (per issue #21): label=Route Name (falls back to Type when
blank), sublabel=Type, category="fitness". distance_km/duration_s/avg_hr
and the remaining CSV columns (Average Pace, Average Speed (km/h),
Calories Burned, Notes, GPX File) live only inside raw_json — events has
no dedicated columns for them, following Untappd's precedent.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal Runkeeper cardioActivities.csv content
# ---------------------------------------------------------------------------

RUNKEEPER_CSV_HEADER = (
    "Date,Type,Route Name,Distance (km),Duration,Average Pace,"
    "Average Speed (km/h),Calories Burned,Average Heart Rate (bpm),Notes,GPX File"
)

# Row 1: named route, full data including heart rate.
# Row 2: unnamed route (blank Route Name), missing heart rate.
RUNKEEPER_CSV_TWO_ROWS = f"""\
{RUNKEEPER_CSV_HEADER}
2023-06-15 07:30:00,Running,Morning Run,5.2,00:32:15,6:12 min/km,9.67,420,145,Felt great,2023-06-15-073000.gpx
2023-06-16 18:00:00,Cycling,,15.0,00:45:00,,20.0,600,,,2023-06-16-180000.gpx
"""

RUNKEEPER_CSV_HEADER_ONLY = f"{RUNKEEPER_CSV_HEADER}\n"

RUNKEEPER_CSV_ZERO_DISTANCE = f"""\
{RUNKEEPER_CSV_HEADER}
2023-06-17 08:00:00,Walking,Quick Walk,0,00:05:00,,0,10,90,,2023-06-17-080000.gpx
"""

RUNKEEPER_CSV_SINCE_CURSOR = f"""\
{RUNKEEPER_CSV_HEADER}
2023-01-01 08:00:00,Running,Old Run,3.0,00:20:00,,9.0,200,140,,2023-01-01-080000.gpx
2023-06-15 07:30:00,Running,Morning Run,5.2,00:32:15,6:12 min/km,9.67,420,145,Felt great,2023-06-15-073000.gpx
"""

RUNKEEPER_CSV_MALFORMED_DURATION = f"""\
{RUNKEEPER_CSV_HEADER}
2023-06-15 07:30:00,Running,Morning Run,5.2,not-a-duration,6:12 min/km,9.67,420,145,Felt great,2023-06-15-073000.gpx
"""


def _make_plugin() -> Any:
    """Instantiate a RunkeeperPlugin."""
    from localizer.plugins.runkeeper.loader import RunkeeperPlugin

    return RunkeeperPlugin()


def _write_export(tmp_path: Path, content: str, filename: str = "cardioActivities.csv") -> Path:
    """Write CSV content into *tmp_path* as an export dir and return the dir path."""
    csv_path = tmp_path / filename
    csv_path.write_text(content, encoding="utf-8")
    return tmp_path


def _raw_json(record: dict[str, Any]) -> dict[str, Any]:
    """Return record['raw_json'] as a dict, parsing it if it is a JSON string."""
    raw = record["raw_json"]
    if isinstance(raw, str):
        parsed: dict[str, Any] = json.loads(raw)
        return parsed
    return raw  # type: ignore[no-any-return]


def _no_settings_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch LocalizerSettings.get_setting to always return its default.

    Simulates a machine with no config.toml/env overrides, so the
    unconfigured-plugin test is deterministic regardless of the developer's
    local ~/.localizer state.
    """
    from localizer.settings import LocalizerSettings

    monkeypatch.setattr(
        LocalizerSettings,
        "get_setting",
        lambda self, key, default=None: default,
    )


# ---------------------------------------------------------------------------
# ABC / class attribute / registration tests
# ---------------------------------------------------------------------------


def test_runkeeper_plugin_id() -> None:
    """RunkeeperPlugin.PLUGIN_ID must equal 'runkeeper'."""
    from localizer.plugins.runkeeper.loader import RunkeeperPlugin

    assert RunkeeperPlugin.PLUGIN_ID == "runkeeper"


def test_runkeeper_fetch_mode_manual() -> None:
    """RunkeeperPlugin.FETCH_MODE must be FetchMode.MANUAL."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.runkeeper.loader import RunkeeperPlugin

    assert RunkeeperPlugin.FETCH_MODE == FetchMode.MANUAL


def test_runkeeper_output_tables_events() -> None:
    """OutputTable.EVENTS must be in RunkeeperPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.runkeeper.loader import RunkeeperPlugin

    assert OutputTable.EVENTS in RunkeeperPlugin.OUTPUT_TABLES


def test_runkeeper_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['runkeeper'] must exist."""
    from localizer.plugins import REGISTRY, load_builtin_plugins

    REGISTRY.clear()
    load_builtin_plugins()
    assert "runkeeper" in REGISTRY, f"'runkeeper' not in REGISTRY; keys: {list(REGISTRY)}"


def test_runkeeper_get_config_fields_shape() -> None:
    """get_config_fields() must return one dir_path field keyed 'export_dir'."""
    plugin = _make_plugin()
    fields = plugin.get_config_fields()

    assert isinstance(fields, list)
    assert len(fields) == 1, f"Expected exactly 1 config field, got {len(fields)}"
    field = fields[0]
    assert field["key"] == "export_dir"
    assert "label" in field
    assert field["type"] == "dir_path"


def test_runkeeper_manual_download_instructions() -> None:
    """get_manual_download_instructions() must mention 'runkeeper.com' and 'cardioActivities'."""
    plugin = _make_plugin()
    instructions = plugin.get_manual_download_instructions()

    assert isinstance(instructions, str)
    assert len(instructions.strip()) > 0, "Expected non-empty manual download instructions"

    assert "runkeeper.com" in instructions.lower(), (
        f"'runkeeper.com' not found in instructions: {instructions!r}"
    )
    assert "cardioActivities" in instructions, (
        f"'cardioActivities' not found in instructions: {instructions!r}"
    )


# ---------------------------------------------------------------------------
# CSV parsing — basic shape / required keys
# ---------------------------------------------------------------------------


def test_runkeeper_fetch_records_from_export_dir_count(tmp_path: Path) -> None:
    """fetch_records(export_dir=...) must yield 2 records from a 2-row CSV."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    assert len(records) == 2, f"Expected 2 records, got {len(records)}"


def test_runkeeper_required_keys_present(tmp_path: Path) -> None:
    """Each record must have exactly the events-schema keys."""
    required_keys = {
        "source_id",
        "timestamp",
        "label",
        "sublabel",
        "category",
        "raw_json",
        "fetched_at",
    }
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    for record in records:
        missing = required_keys - set(record.keys())
        assert not missing, f"Record missing required keys: {missing}"


def test_runkeeper_source_id_is_runkeeper(tmp_path: Path) -> None:
    """source_id in each record must equal 'runkeeper'."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    for record in records:
        assert record["source_id"] == "runkeeper", (
            f"source_id {record['source_id']!r} != 'runkeeper'"
        )


def test_runkeeper_fetched_at_is_recent(tmp_path: Path) -> None:
    """fetched_at must be a Unix timestamp close to now."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    before = int(time.time())
    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))
    after = int(time.time())

    for record in records:
        assert isinstance(record["fetched_at"], int)
        assert before - 5 <= record["fetched_at"] <= after + 5, (
            f"fetched_at {record['fetched_at']} not close to now ({before}-{after})"
        )


# ---------------------------------------------------------------------------
# label / sublabel / category mapping
# ---------------------------------------------------------------------------


def test_runkeeper_named_route_used_as_label(tmp_path: Path) -> None:
    """label must be the 'Route Name' column when non-blank."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    morning_run = next(r for r in records if r["label"] == "Morning Run")
    assert morning_run["sublabel"] == "Running"


def test_runkeeper_unnamed_route_falls_back_to_type(tmp_path: Path) -> None:
    """A blank 'Route Name' must fall back to the 'Type' column for label."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    cycling = next(r for r in records if r["sublabel"] == "Cycling")
    assert cycling["label"] == "Cycling", f"label {cycling['label']!r} != 'Cycling'"


def test_runkeeper_category_is_fitness(tmp_path: Path) -> None:
    """category must always be the literal string 'fitness'."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    for record in records:
        assert record["category"] == "fitness"


# ---------------------------------------------------------------------------
# Date -> timestamp parsing
# ---------------------------------------------------------------------------


def test_runkeeper_date_parses_to_positive_int_timestamp(tmp_path: Path) -> None:
    """The 'Date' column (YYYY-MM-DD HH:MM:SS) must parse to a positive int timestamp."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    for record in records:
        assert isinstance(record["timestamp"], int)
        assert record["timestamp"] > 0


def test_runkeeper_unparseable_date_falls_back_to_fetched_at(tmp_path: Path) -> None:
    """An unparseable Date value must not raise; timestamp falls back to fetched_at."""
    bad_csv = f"""\
{RUNKEEPER_CSV_HEADER}
not-a-real-date,Running,Morning Run,5.2,00:32:15,,9.67,420,145,,2023-06-15-073000.gpx
"""
    export_dir = _write_export(tmp_path, bad_csv)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    assert len(records) == 1
    assert records[0]["timestamp"] == records[0]["fetched_at"]


# ---------------------------------------------------------------------------
# Duration -> duration_s parsing
# ---------------------------------------------------------------------------


def test_runkeeper_duration_converts_to_integer_seconds(tmp_path: Path) -> None:
    """Duration '00:32:15' must convert to raw_json['duration_s'] == 1935 (int)."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    morning_run = next(r for r in records if r["label"] == "Morning Run")
    duration_s = _raw_json(morning_run)["duration_s"]
    assert isinstance(duration_s, int), f"duration_s is {type(duration_s)}, expected int"
    assert duration_s == 1935


def test_runkeeper_malformed_duration_does_not_raise(tmp_path: Path) -> None:
    """A malformed Duration value must not raise; duration_s becomes None."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_MALFORMED_DURATION)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    assert len(records) == 1
    assert _raw_json(records[0])["duration_s"] is None


# ---------------------------------------------------------------------------
# distance_km / avg_hr in raw_json
# ---------------------------------------------------------------------------


def test_runkeeper_distance_km_is_float_in_raw_json(tmp_path: Path) -> None:
    """raw_json['distance_km'] must be a Python float equal to the CSV value."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    morning_run = next(r for r in records if r["label"] == "Morning Run")
    distance_km = _raw_json(morning_run)["distance_km"]
    assert isinstance(distance_km, float)
    assert distance_km == 5.2


def test_runkeeper_zero_distance_activity_preserves_zero(tmp_path: Path) -> None:
    """A zero-distance activity must have raw_json['distance_km'] == 0.0, not None."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_ZERO_DISTANCE)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    assert len(records) == 1
    distance_km = _raw_json(records[0])["distance_km"]
    assert distance_km == 0.0
    assert distance_km is not None


def test_runkeeper_present_heart_rate_is_float_in_raw_json(tmp_path: Path) -> None:
    """A row with a heart rate value must have raw_json['avg_hr'] as a float."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    morning_run = next(r for r in records if r["label"] == "Morning Run")
    avg_hr = _raw_json(morning_run)["avg_hr"]
    assert isinstance(avg_hr, float)
    assert avg_hr == 145.0


def test_runkeeper_missing_heart_rate_is_none_in_raw_json(tmp_path: Path) -> None:
    """A row with a blank heart rate column must have raw_json['avg_hr'] as None."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    cycling = next(r for r in records if r["sublabel"] == "Cycling")
    assert _raw_json(cycling)["avg_hr"] is None


# ---------------------------------------------------------------------------
# raw_json preservation / round-trip
# ---------------------------------------------------------------------------


def test_runkeeper_raw_json_round_trips_and_preserves_fields(tmp_path: Path) -> None:
    """raw_json must be JSON-serializable and preserve pace/speed/calories/notes/gpx_file."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    for record in records:
        raw = record["raw_json"]
        if isinstance(raw, str):
            json.loads(raw)  # must not raise
        else:
            json.dumps(raw)  # must not raise

    morning_run = next(r for r in records if r["label"] == "Morning Run")
    raw = _raw_json(morning_run)
    assert raw["Average Pace"] == "6:12 min/km"
    assert raw["Average Speed (km/h)"] == "9.67"
    assert raw["Calories Burned"] == "420"
    assert raw["Notes"] == "Felt great"
    assert raw["gpx_file"] == "2023-06-15-073000.gpx"


def test_runkeeper_raw_json_none_values_round_trip(tmp_path: Path) -> None:
    """raw_json containing None values (missing HR, blank route) must still round-trip."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    cycling = next(r for r in records if r["sublabel"] == "Cycling")
    raw = cycling["raw_json"]
    if isinstance(raw, str):
        parsed = json.loads(raw)
    else:
        parsed = json.loads(json.dumps(raw))

    assert parsed["avg_hr"] is None


# ---------------------------------------------------------------------------
# empty CSV / missing file / unconfigured
# ---------------------------------------------------------------------------


def test_runkeeper_empty_csv_yields_empty_list(tmp_path: Path) -> None:
    """A CSV with only a header row (zero data rows) must yield an empty list, not raise."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_HEADER_ONLY)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    assert records == []


def test_runkeeper_missing_export_file_raises_file_not_found(tmp_path: Path) -> None:
    """A configured export_dir without a cardioActivities.csv inside it must raise."""
    plugin = _make_plugin()

    with pytest.raises(FileNotFoundError):
        list(plugin.fetch_records(export_dir=str(tmp_path)))


def test_runkeeper_missing_export_dir_raises_file_not_found(tmp_path: Path) -> None:
    """A configured export_dir that does not exist at all must raise FileNotFoundError."""
    plugin = _make_plugin()
    missing_dir = tmp_path / "nonexistent_export"

    with pytest.raises(FileNotFoundError):
        list(plugin.fetch_records(export_dir=str(missing_dir)))


def test_runkeeper_missing_export_error_mentions_runkeeper(tmp_path: Path) -> None:
    """The FileNotFoundError message should point at runkeeper.com."""
    plugin = _make_plugin()

    with pytest.raises(FileNotFoundError) as exc_info:
        list(plugin.fetch_records(export_dir=str(tmp_path)))

    assert "runkeeper.com" in str(exc_info.value).lower()


def test_runkeeper_unconfigured_yields_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """With export_dir=None and no LocalizerSettings override, fetch_records() yields nothing."""
    _no_settings_override(monkeypatch)

    plugin = _make_plugin()
    records = list(plugin.fetch_records())

    assert records == []


# ---------------------------------------------------------------------------
# since cursor
# ---------------------------------------------------------------------------


def test_runkeeper_since_cursor_excludes_older_row(tmp_path: Path) -> None:
    """A row whose timestamp is <= since must be excluded; a newer row must be included."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_SINCE_CURSOR)

    plugin = _make_plugin()
    all_records = list(plugin.fetch_records(export_dir=str(export_dir)))
    assert len(all_records) == 2, f"Expected 2 records with no cursor, got {len(all_records)}"

    old_record = next(r for r in all_records if r["label"] == "Old Run")
    since = old_record["timestamp"]

    filtered_records = list(plugin.fetch_records(export_dir=str(export_dir), since=since))

    assert len(filtered_records) == 1, (
        f"Expected 1 record after since-cursor filtering, got {len(filtered_records)}"
    )
    assert filtered_records[0]["label"] == "Morning Run"


# ---------------------------------------------------------------------------
# no-network-imports guard
# ---------------------------------------------------------------------------


def test_runkeeper_loader_has_no_network_imports() -> None:
    """loader.py must not import requests/urllib/httpx/socket — zero network code."""
    import localizer.plugins.runkeeper.loader as loader_module

    source = Path(loader_module.__file__).read_text(encoding="utf-8")

    for forbidden in ("import requests", "import urllib", "import httpx", "import socket"):
        assert forbidden not in source, f"Found forbidden network import: {forbidden!r}"


def test_runkeeper_loader_no_other_plugin_references() -> None:
    """loader.py must not reference other source plugins, their schemas, or join keys."""
    import localizer.plugins.runkeeper.loader as loader_module

    source = Path(loader_module.__file__).read_text(encoding="utf-8")

    for forbidden in ("swarm", "lastfm", "letterboxd", "untappd", "flickr", "feedly", "github"):
        assert forbidden not in source.lower(), (
            f"Found forbidden cross-plugin reference: {forbidden!r}"
        )


# ---------------------------------------------------------------------------
# GPX files present in export dir must never be parsed
# ---------------------------------------------------------------------------


def test_runkeeper_ignores_gpx_files_in_export_dir(tmp_path: Path) -> None:
    """A .gpx file sitting alongside cardioActivities.csv must be ignored entirely."""
    export_dir = _write_export(tmp_path, RUNKEEPER_CSV_TWO_ROWS)
    (export_dir / "2023-06-15-073000.gpx").write_text(
        "<gpx>not real gpx content</gpx>", encoding="utf-8"
    )

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_dir=str(export_dir)))

    assert len(records) == 2
