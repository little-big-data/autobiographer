"""Tests for GoogleLocationPlugin (issue #110): legacy Google Takeout Location History.

Covers both legacy Takeout formats, distinct from `google_timeline`'s modern
single-file `Timeline.json` export:
  - packages/localizer/src/localizer/plugins/google_location/parser.py
  - packages/localizer/src/localizer/plugins/google_location/loader.py
  - Registration in packages/localizer/src/localizer/plugins/__init__.py

Format 1 — Records.json (top level of the export directory): raw GPS pings,
``{"locations": [{"latitudeE7": ..., "longitudeE7": ..., "timestamp"|"timestampMs": ...}]}``.

Format 2 — Semantic Location History/<Year>/<Year>_<MONTH>.json: place visits
and activity segments, ``{"timelineObjects": [{"placeVisit": {...}} | {"activitySegment": {...}}]}``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write *data* as JSON to *path*, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _records_json_payload() -> dict[str, Any]:
    """Return a Records.json payload with an ISO-timestamp entry and an ms-timestamp entry."""
    return {
        "locations": [
            {
                "latitudeE7": 407128000,
                "longitudeE7": -740060000,
                "timestamp": "2020-01-01T12:00:00.000Z",
            },
            {
                "latitudeE7": 340522000,
                "longitudeE7": -1182437000,
                "timestampMs": "1580000000000",
            },
        ]
    }


def _semantic_month_payload() -> dict[str, Any]:
    """Return a Semantic Location History month file with one visit + one activity."""
    return {
        "timelineObjects": [
            {
                "placeVisit": {
                    "location": {
                        "latitudeE7": 407128000,
                        "longitudeE7": -740060000,
                        "name": "Home",
                    },
                    "semanticType": "HOME",
                    "duration": {
                        "startTimestamp": "2020-01-01T08:00:00.000Z",
                        "endTimestamp": "2020-01-01T09:00:00.000Z",
                    },
                }
            },
            {
                "activitySegment": {
                    "startLocation": {"latitudeE7": 407128000, "longitudeE7": -740060000},
                    "endLocation": {"latitudeE7": 407500000, "longitudeE7": -740500000},
                    "activityType": "WALKING",
                    "duration": {
                        "startTimestamp": "2020-01-04T11:00:00.000Z",
                        "endTimestamp": "2020-01-04T12:00:00.000Z",
                    },
                }
            },
        ]
    }


def _no_settings_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch LocalizerSettings.get_setting to always return its default."""
    from localizer.settings import LocalizerSettings

    monkeypatch.setattr(
        LocalizerSettings,
        "get_setting",
        lambda self, key, default=None: default,
    )


REQUIRED_KEYS = {
    "source_id",
    "timestamp",
    "lat",
    "lng",
    "place_name",
    "place_type",
    "raw_json",
    "fetched_at",
}


# ---------------------------------------------------------------------------
# Registration / class-attribute tests
# ---------------------------------------------------------------------------


def test_google_location_plugin_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['google_location'] must exist."""
    from localizer.plugins import REGISTRY, load_builtin_plugins

    REGISTRY.clear()
    load_builtin_plugins()
    assert "google_location" in REGISTRY, (
        f"'google_location' not in REGISTRY; keys: {list(REGISTRY)}"
    )


def test_google_location_plugin_plugin_id() -> None:
    """GoogleLocationPlugin.PLUGIN_ID must equal 'google_location'."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    assert GoogleLocationPlugin.PLUGIN_ID == "google_location"


def test_google_location_plugin_display_name_is_set() -> None:
    """GoogleLocationPlugin.DISPLAY_NAME must be a non-empty string."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    assert isinstance(GoogleLocationPlugin.DISPLAY_NAME, str)
    assert len(GoogleLocationPlugin.DISPLAY_NAME.strip()) > 0


def test_google_location_plugin_fetch_mode_manual() -> None:
    """GoogleLocationPlugin.FETCH_MODE must be FetchMode.MANUAL."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    assert GoogleLocationPlugin.FETCH_MODE == FetchMode.MANUAL


def test_google_location_plugin_output_tables_places() -> None:
    """OutputTable.PLACES must be in GoogleLocationPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    assert OutputTable.PLACES in GoogleLocationPlugin.OUTPUT_TABLES


def test_google_location_plugin_icon_is_set() -> None:
    """GoogleLocationPlugin.ICON must be a non-empty string."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    assert isinstance(GoogleLocationPlugin.ICON, str)
    assert len(GoogleLocationPlugin.ICON.strip()) > 0


def test_google_location_plugin_get_config_fields() -> None:
    """get_config_fields() must return a field with key 'google_location_dir'."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    plugin = GoogleLocationPlugin()
    fields = plugin.get_config_fields()
    assert isinstance(fields, list)
    assert len(fields) >= 1
    for field in fields:
        assert "key" in field
        assert "label" in field

    keys = [field["key"] for field in fields]
    assert "google_location_dir" in keys, (
        "Expected the settings key 'google_location_dir' so `localizer config set "
        "google_location_dir ...` and `--set-dir` (which derives '{source}_dir') work"
    )
    dir_field = next(f for f in fields if f["key"] == "google_location_dir")
    assert dir_field["type"] == "dir_path"


def test_google_location_plugin_manual_download_instructions() -> None:
    """get_manual_download_instructions() must return a non-empty string."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    plugin = GoogleLocationPlugin()
    instructions = plugin.get_manual_download_instructions()
    assert isinstance(instructions, str)
    assert len(instructions.strip()) > 0


# ---------------------------------------------------------------------------
# Records.json (legacy raw GPS ping format)
# ---------------------------------------------------------------------------


def test_fetch_records_parses_records_json(tmp_path: Path) -> None:
    """A Records.json with 2 entries yields exactly 2 dicts with required keys."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Records.json", _records_json_payload())

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    assert len(records) == 2
    for record in records:
        assert set(record.keys()) == REQUIRED_KEYS
        assert record["source_id"] == "google_location"
        assert isinstance(record["lat"], float)
        assert isinstance(record["lng"], float)
        assert isinstance(record["timestamp"], int)
        assert record["place_type"] == "location_ping"
        assert record["place_name"] == ""


def test_fetch_records_records_json_latitude_e7_conversion(tmp_path: Path) -> None:
    """latitudeE7/longitudeE7 must be divided by 1e7 to produce decimal degrees."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Records.json", _records_json_payload())

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = sorted(list(plugin.fetch_records()), key=lambda r: r["timestamp"])
    assert records[0]["lat"] == pytest.approx(40.7128, abs=1e-4)
    assert records[0]["lng"] == pytest.approx(-74.0060, abs=1e-4)
    assert records[1]["lat"] == pytest.approx(34.0522, abs=1e-4)
    assert records[1]["lng"] == pytest.approx(-118.2437, abs=1e-4)


def test_fetch_records_records_json_ms_timestamp_fallback(tmp_path: Path) -> None:
    """The 'timestampMs' field must be honored when 'timestamp' is absent."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Records.json", _records_json_payload())

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    timestamps = {r["timestamp"] for r in records}
    assert 1580000000 in timestamps


def test_fetch_records_records_json_raw_json_is_serializable(tmp_path: Path) -> None:
    """raw_json on each yielded record must be JSON-serializable."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Records.json", _records_json_payload())

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    for record in plugin.fetch_records():
        raw = record["raw_json"]
        if isinstance(raw, str):
            json.loads(raw)
        else:
            json.dumps(raw)


# ---------------------------------------------------------------------------
# Semantic Location History (legacy placeVisit/activitySegment format)
# ---------------------------------------------------------------------------


def test_fetch_records_parses_semantic_location_history(tmp_path: Path) -> None:
    """A month file with 1 visit + 1 activity yields exactly 2 dicts."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(
        export_dir / "Semantic Location History" / "2020" / "2020_JANUARY.json",
        _semantic_month_payload(),
    )

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    assert len(records) == 2
    for record in records:
        assert set(record.keys()) == REQUIRED_KEYS
        assert record["source_id"] == "google_location"


def test_fetch_records_place_visit_name_and_type(tmp_path: Path) -> None:
    """A placeVisit yields the place's name and lowercased semantic type."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(
        export_dir / "Semantic Location History" / "2020" / "2020_JANUARY.json",
        _semantic_month_payload(),
    )

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    visits = [r for r in records if not str(r["place_type"]).startswith("activity:")]
    assert len(visits) == 1
    assert visits[0]["place_name"] == "Home"
    assert visits[0]["place_type"] == "home"


def test_fetch_records_activity_segment_prefix(tmp_path: Path) -> None:
    """An activitySegment yields a place_type prefixed with 'activity:'."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(
        export_dir / "Semantic Location History" / "2020" / "2020_JANUARY.json",
        _semantic_month_payload(),
    )

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    activities = [r for r in records if str(r["place_type"]).startswith("activity:")]
    assert len(activities) == 1
    assert activities[0]["place_type"] == "activity:walking"
    assert activities[0]["place_name"] == "Walking"


def test_fetch_records_semantic_ms_timestamp_fallback(tmp_path: Path) -> None:
    """duration.startTimestampMs must be honored when startTimestamp is absent."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    payload = {
        "timelineObjects": [
            {
                "placeVisit": {
                    "location": {
                        "latitudeE7": 407128000,
                        "longitudeE7": -740060000,
                        "name": "Old Format Place",
                    },
                    "semanticType": "WORK",
                    "duration": {"startTimestampMs": "1577880000000"},
                }
            }
        ]
    }
    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Semantic Location History" / "2020" / "2020_JANUARY.json", payload)

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    assert len(records) == 1
    assert records[0]["timestamp"] == 1577880000
    assert records[0]["place_name"] == "Old Format Place"


def test_fetch_records_scans_multiple_year_and_month_files(tmp_path: Path) -> None:
    """Multiple year directories and month files are all scanned."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(
        export_dir / "Semantic Location History" / "2020" / "2020_JANUARY.json",
        _semantic_month_payload(),
    )
    _write_json(
        export_dir / "Semantic Location History" / "2021" / "2021_FEBRUARY.json",
        _semantic_month_payload(),
    )

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    assert len(records) == 4


# ---------------------------------------------------------------------------
# Combined formats + since filtering
# ---------------------------------------------------------------------------


def test_fetch_records_combines_both_formats(tmp_path: Path) -> None:
    """When both Records.json and Semantic Location History are present, both are yielded."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Records.json", _records_json_payload())
    _write_json(
        export_dir / "Semantic Location History" / "2020" / "2020_JANUARY.json",
        _semantic_month_payload(),
    )

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    assert len(records) == 4  # 2 from Records.json + 2 from Semantic Location History


def test_fetch_records_since_filtering_excludes_older_record(tmp_path: Path) -> None:
    """A record with timestamp <= since must be excluded."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Records.json", _records_json_payload())

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    all_records = list(plugin.fetch_records())
    assert len(all_records) == 2
    timestamps = sorted(r["timestamp"] for r in all_records)
    older_timestamp = timestamps[0]

    filtered = list(plugin.fetch_records(since=older_timestamp))
    assert len(filtered) == 1
    assert all(r["timestamp"] > older_timestamp for r in filtered)


def test_fetch_records_fetched_at_is_recent(tmp_path: Path) -> None:
    """fetched_at must be a Unix timestamp close to now."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Records.json", _records_json_payload())

    before = int(time.time())
    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    after = int(time.time())

    assert len(records) == 2
    for record in records:
        assert before - 5 <= record["fetched_at"] <= after + 5


# ---------------------------------------------------------------------------
# No-config / missing-directory / malformed-file edge cases
# ---------------------------------------------------------------------------


def test_fetch_records_no_dir_configured_yields_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No explicit dir and no settings entry -> fetch_records() yields [], no exception."""
    monkeypatch.setenv("LOCALIZER_CONFIG_PATH", str(tmp_path / "empty_config.toml"))

    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    plugin = GoogleLocationPlugin()
    records = list(plugin.fetch_records())
    assert records == []


def test_fetch_records_missing_dir_yields_nothing(tmp_path: Path) -> None:
    """A configured directory that does not exist -> fetch_records() yields [], no exception."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    plugin = GoogleLocationPlugin(google_location_dir=str(tmp_path / "does_not_exist"))
    try:
        records = list(plugin.fetch_records())
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"fetch_records() raised {type(exc).__name__} on missing dir: {exc}")
    assert records == []


def test_fetch_records_empty_dir_yields_nothing(tmp_path: Path) -> None:
    """An existing but empty directory (neither format present) yields nothing."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    export_dir.mkdir()

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    assert records == []


def test_fetch_records_malformed_records_json_skipped_gracefully(tmp_path: Path) -> None:
    """A Records.json that is not valid JSON must not raise, and yields nothing from it."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    export_dir.mkdir(parents=True)
    (export_dir / "Records.json").write_text("{not valid json", encoding="utf-8")

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    try:
        records = list(plugin.fetch_records())
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"fetch_records() raised {type(exc).__name__} on malformed JSON: {exc}")
    assert records == []


def test_fetch_records_malformed_month_file_skipped_other_files_still_processed(
    tmp_path: Path,
) -> None:
    """A malformed month file is skipped; other valid month files are still parsed."""
    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    export_dir = tmp_path / "Location History"
    semantic_dir = export_dir / "Semantic Location History" / "2020"
    semantic_dir.mkdir(parents=True)
    (semantic_dir / "2020_JANUARY.json").write_text("not valid json {{{", encoding="utf-8")
    _write_json(semantic_dir / "2020_FEBRUARY.json", _semantic_month_payload())

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    assert len(records) == 2, "Expected the valid month file's 2 records despite the bad one"


# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------


def test_init_reads_dir_from_localizer_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no explicit dir, __init__ must resolve it via LocalizerSettings."""
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("LOCALIZER_CONFIG_PATH", str(config_path))

    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Records.json", _records_json_payload())

    from localizer.settings import LocalizerSettings

    LocalizerSettings().set_setting("google_location_dir", str(export_dir))

    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    plugin = GoogleLocationPlugin()
    records = list(plugin.fetch_records())
    assert len(records) == 2


def test_explicit_dir_overrides_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit google_location_dir argument must take precedence over settings."""
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("LOCALIZER_CONFIG_PATH", str(config_path))

    from localizer.settings import LocalizerSettings

    LocalizerSettings().set_setting(
        "google_location_dir", str(tmp_path / "settings_does_not_exist")
    )

    export_dir = tmp_path / "Location History"
    _write_json(export_dir / "Records.json", _records_json_payload())

    from localizer.plugins.google_location.loader import GoogleLocationPlugin

    plugin = GoogleLocationPlugin(google_location_dir=str(export_dir))
    records = list(plugin.fetch_records())
    assert len(records) == 2
