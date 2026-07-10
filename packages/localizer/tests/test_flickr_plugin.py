"""Failing tests for Subtask 2: FlickrPlugin in the localizer package (issue #19).

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/flickr/__init__.py
  - packages/localizer/src/localizer/plugins/flickr/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py (load_builtin_plugins)

FlickrPlugin is FetchMode.MANUAL, OutputTable.PLACES — it reads a directory of
``photo_*.json`` export files (mirroring swarm/loader.py's directory-glob,
graceful-empty-on-missing-directory, per-file try/except shape) and never makes
any network call itself.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal Flickr photo export JSON
# ---------------------------------------------------------------------------

GEOTAGGED = {"latitude": 51.5074, "longitude": -0.1278}


def _make_photo_data(
    name: str | None = "Test Photo",
    date_taken: str = "2023-06-15 18:30:00",
    geo: dict[str, float] | None = None,
    tags: list[str] | None = None,
    albums: list[str] | None = None,
    description: str = "A test photo.",
    photopage: str = "https://www.flickr.com/photos/testuser/1/",
) -> dict[str, Any]:
    """Return a single photo dict matching the Flickr JSON export shape."""
    data: dict[str, Any] = {
        "date_taken": date_taken,
        "geo": geo,
        "tags": tags if tags is not None else ["travel", "sunset"],
        "albums": albums if albums is not None else ["Summer Trip"],
        "description": description,
        "photopage": photopage,
    }
    if name is not None:
        data["name"] = name
    return data


def _write_photo(dir_path: Path, filename: str, data: dict[str, Any]) -> Path:
    """Write a photo JSON dict to *dir_path/filename* and return the path."""
    file_path = dir_path / filename
    file_path.write_text(json.dumps(data), encoding="utf-8")
    return file_path


def _raw_json(record: dict[str, Any]) -> dict[str, Any]:
    """Return record['raw_json'] as a dict, parsing it if it is a JSON string."""
    raw = record["raw_json"]
    if isinstance(raw, str):
        parsed: dict[str, Any] = json.loads(raw)
        return parsed
    return raw  # type: ignore[no-any-return]


def _no_settings_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch LocalizerSettings.get_setting to always return its default.

    Simulates a machine with no config.toml/env overrides, so fallback tests
    are deterministic regardless of the developer's local ~/.localizer state.
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


def test_flickr_plugin_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['flickr'] must exist."""
    from localizer.plugins import REGISTRY, load_builtin_plugins

    REGISTRY.clear()
    load_builtin_plugins()
    assert "flickr" in REGISTRY, f"'flickr' not in REGISTRY; keys: {list(REGISTRY)}"


def test_flickr_plugin_plugin_id() -> None:
    """FlickrPlugin.PLUGIN_ID must equal 'flickr'."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    assert FlickrPlugin.PLUGIN_ID == "flickr"


def test_flickr_plugin_fetch_mode_manual() -> None:
    """FlickrPlugin.FETCH_MODE must be FetchMode.MANUAL."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.flickr.loader import FlickrPlugin

    assert FlickrPlugin.FETCH_MODE == FetchMode.MANUAL


def test_flickr_plugin_output_tables_places() -> None:
    """OutputTable.PLACES must be in FlickrPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.flickr.loader import FlickrPlugin

    assert OutputTable.PLACES in FlickrPlugin.OUTPUT_TABLES


def test_flickr_plugin_get_config_fields() -> None:
    """get_config_fields() must return the export_dir and geotagged_only fields."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    plugin = FlickrPlugin()
    fields = plugin.get_config_fields()
    assert isinstance(fields, list)
    assert len(fields) == 2, f"Expected exactly 2 config fields, got {len(fields)}: {fields}"

    by_key = {field["key"]: field for field in fields}
    assert "export_dir" in by_key, f"'export_dir' field missing: {fields}"
    assert "geotagged_only" in by_key, f"'geotagged_only' field missing: {fields}"
    for field in fields:
        assert "key" in field, f"Config field missing 'key': {field}"
        assert "label" in field, f"Config field missing 'label': {field}"

    assert by_key["export_dir"]["type"] == "dir_path", (
        f"export_dir field type {by_key['export_dir'].get('type')!r} != 'dir_path'"
    )


def test_flickr_plugin_geotagged_only_field_is_bool_type_default_true() -> None:
    """The geotagged_only field must be type='bool' with a default of True."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    plugin = FlickrPlugin()
    fields = plugin.get_config_fields()
    by_key = {field["key"]: field for field in fields}

    geotagged_field = by_key["geotagged_only"]
    assert geotagged_field["type"] == "bool", (
        f"geotagged_only field type {geotagged_field.get('type')!r} != 'bool'"
    )
    assert geotagged_field.get("default") is True, (
        f"geotagged_only field default {geotagged_field.get('default')!r} is not True"
    )


def test_flickr_plugin_manual_download_instructions() -> None:
    """get_manual_download_instructions() must be a non-empty string mentioning flickr.com."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    plugin = FlickrPlugin()
    instructions = plugin.get_manual_download_instructions()

    assert isinstance(instructions, str)
    assert len(instructions.strip()) > 0, "Expected non-empty manual download instructions"

    instructions_lower = instructions.lower()
    assert "flickr.com" in instructions_lower, (
        f"'flickr.com' not found in instructions: {instructions!r}"
    )


# ---------------------------------------------------------------------------
# fetch_records normalization tests
# ---------------------------------------------------------------------------


def test_fetch_records_geotagged_photo_yields_float_lat_lng(tmp_path: Path) -> None:
    """A geotagged photo must yield exactly one record with float lat/lng and place_type=='photo'."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=GEOTAGGED))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 1, f"Expected 1 record, got {len(records)}"
    record = records[0]
    assert isinstance(record["lat"], float), f"Expected float lat, got {type(record['lat'])}"
    assert isinstance(record["lng"], float), f"Expected float lng, got {type(record['lng'])}"
    assert record["lat"] == pytest.approx(GEOTAGGED["latitude"])
    assert record["lng"] == pytest.approx(GEOTAGGED["longitude"])
    assert record["place_type"] == "photo"


def test_fetch_records_non_geotagged_geotagged_only_true_yields_zero(tmp_path: Path) -> None:
    """A non-geotagged photo with geotagged_only=True must yield zero records."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path), geotagged_only=True)
    records = list(plugin.fetch_records())

    assert records == [], f"Expected 0 records with geotagged_only=True, got {len(records)}"


def test_fetch_records_non_geotagged_geotagged_only_false_yields_nan(tmp_path: Path) -> None:
    """A non-geotagged photo with geotagged_only=False must yield 1 record with NaN lat/lng."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path), geotagged_only=False)
    records = list(plugin.fetch_records())

    assert len(records) == 1, (
        f"Expected exactly 1 record with geotagged_only=False, got {len(records)}"
    )
    record = records[0]
    assert math.isnan(record["lat"]), f"Expected NaN lat, got {record['lat']!r}"
    assert math.isnan(record["lng"]), f"Expected NaN lng, got {record['lng']!r}"


def test_fetch_records_geotagged_only_default_is_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When geotagged_only is not passed, it must default to True (excluding un-geotagged photos)."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _no_settings_override(monkeypatch)
    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert records == [], "geotagged_only should default to True, excluding non-geotagged photos"


@pytest.mark.parametrize("geotagged_only", [True, False])
def test_fetch_records_geotagged_photo_always_included_regardless_of_toggle(
    tmp_path: Path, geotagged_only: bool
) -> None:
    """A geotagged photo must always be yielded, regardless of the geotagged_only toggle."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=GEOTAGGED))

    plugin = FlickrPlugin(export_dir=str(tmp_path), geotagged_only=geotagged_only)
    records = list(plugin.fetch_records())

    assert len(records) == 1, (
        f"Geotagged photo excluded with geotagged_only={geotagged_only}: got {len(records)} records"
    )
    assert records[0]["lat"] == pytest.approx(GEOTAGGED["latitude"])
    assert records[0]["lng"] == pytest.approx(GEOTAGGED["longitude"])


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("false", False),
        ("False", False),
        ("0", False),
        ("", False),
        ("no", False),
        ("No", False),
        ("true", True),
        ("1", True),
        ("yes", True),
    ],
)
def test_geotagged_only_string_coercion_from_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
    expected: bool,
) -> None:
    """A string value from LocalizerSettings must coerce to the correct bool.

    Verified indirectly (black-box) via fetch_records() behavior against a
    non-geotagged photo fixture, rather than by inspecting a private attribute.
    """
    from localizer.plugins.flickr.loader import FlickrPlugin
    from localizer.settings import LocalizerSettings

    def fake_get_setting(self: Any, key: str, default: Any = None) -> Any:
        if key == "geotagged_only":
            return raw_value
        return default

    monkeypatch.setattr(LocalizerSettings, "get_setting", fake_get_setting)

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    if expected is True:
        assert records == [], (
            f"raw settings value {raw_value!r} should coerce to True (exclude), "
            f"got {len(records)} records"
        )
    else:
        assert len(records) == 1, (
            f"raw settings value {raw_value!r} should coerce to False (include as NaN), "
            f"got {len(records)} records"
        )
        assert math.isnan(records[0]["lat"])
        assert math.isnan(records[0]["lng"])


def test_fetch_records_missing_title_yields_empty_place_name(tmp_path: Path) -> None:
    """A photo JSON with no 'name' key must yield place_name == '' (not KeyError/None)."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(name=None, geo=GEOTAGGED))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 1
    assert records[0]["place_name"] == "", f"Expected '', got {records[0]['place_name']!r}"


def test_fetch_records_raw_json_preserves_tags_albums_description_photopage(
    tmp_path: Path,
) -> None:
    """raw_json must preserve tags/albums/description/photopage verbatim, and be JSON-serializable."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    data = _make_photo_data(
        geo=GEOTAGGED,
        tags=["mountains", "hiking", "summer"],
        albums=["Alps 2023"],
        description="A hike in the Alps.",
        photopage="https://www.flickr.com/photos/testuser/42/",
    )
    _write_photo(tmp_path, "photo_1.json", data)

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert len(records) == 1

    raw = _raw_json(records[0])
    assert raw["tags"] == ["mountains", "hiking", "summer"]
    assert raw["albums"] == ["Alps 2023"]
    assert raw["description"] == "A hike in the Alps."
    assert raw["photopage"] == "https://www.flickr.com/photos/testuser/42/"


def test_fetch_records_empty_export_dir_yields_empty_list(tmp_path: Path) -> None:
    """An empty export directory (exists, zero matching files) must yield []."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert records == [], f"Expected empty list from empty dir, got {records}"


def test_fetch_records_nonexistent_export_dir_yields_empty_list(tmp_path: Path) -> None:
    """A nonexistent export directory path must yield [] without raising."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    nonexistent = tmp_path / "does_not_exist"

    plugin = FlickrPlugin(export_dir=str(nonexistent))
    try:
        records = list(plugin.fetch_records())
        assert records == [], f"Expected empty list for missing dir, got {records}"
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"fetch_records() raised {type(exc).__name__} on missing dir: {exc}")


def test_fetch_records_unconfigured_export_dir_yields_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FlickrPlugin() with no export_dir and no settings override must yield [] without raising."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _no_settings_override(monkeypatch)

    plugin = FlickrPlugin()
    records = list(plugin.fetch_records())

    assert records == [], f"Expected empty list when unconfigured, got {records}"


def test_fetch_records_multiple_files_all_parsed(tmp_path: Path) -> None:
    """Multiple photo_*.json files in the directory must all be read."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=GEOTAGGED))
    _write_photo(
        tmp_path,
        "photo_2.json",
        _make_photo_data(geo={"latitude": 40.0, "longitude": -74.0}),
    )
    _write_photo(
        tmp_path,
        "photo_3.json",
        _make_photo_data(geo={"latitude": 35.0, "longitude": 139.0}),
    )

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 3, f"Expected 3 records across 3 files, got {len(records)}"


def test_fetch_records_ignores_non_matching_files(tmp_path: Path) -> None:
    """Files not matching the photo_*.json glob pattern must be ignored."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=GEOTAGGED))
    (tmp_path / "notes.txt").write_text("not a photo", encoding="utf-8")
    (tmp_path / "other_1.json").write_text(
        json.dumps(_make_photo_data(geo=GEOTAGGED)), encoding="utf-8"
    )

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 1, (
        f"Expected only the photo_*.json file to be parsed, got {len(records)} records"
    )


def test_fetch_records_malformed_json_file_skipped_valid_still_yielded(tmp_path: Path) -> None:
    """A malformed photo_*.json file must be skipped; the valid file must still be yielded."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    (tmp_path / "photo_bad.json").write_text("{not valid json", encoding="utf-8")
    _write_photo(tmp_path, "photo_good.json", _make_photo_data(geo=GEOTAGGED))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 1, (
        f"Expected the malformed file to be skipped and the valid one yielded, got {len(records)}"
    )


def test_fetch_records_date_taken_parses_to_expected_timestamp(tmp_path: Path) -> None:
    """A space-separated date_taken must parse to the correct Unix timestamp."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    date_taken = "2023-06-15 18:30:00"
    _write_photo(tmp_path, "photo_1.json", _make_photo_data(date_taken=date_taken, geo=GEOTAGGED))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert len(records) == 1

    expected_ts = int(datetime.fromisoformat(date_taken.replace(" ", "T")).timestamp())
    assert records[0]["timestamp"] == expected_ts


def test_fetch_records_unparseable_date_taken_falls_back_to_fetched_at(tmp_path: Path) -> None:
    """An unparseable date_taken must fall back to this batch's fetched_at, not raise."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(
        tmp_path,
        "photo_1.json",
        _make_photo_data(date_taken="not-a-real-date", geo=GEOTAGGED),
    )

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 1
    record = records[0]
    assert record["timestamp"] == record["fetched_at"], (
        f"Expected fallback to fetched_at ({record['fetched_at']}), got {record['timestamp']}"
    )


def test_fetch_records_since_cursor_excludes_older_photo(tmp_path: Path) -> None:
    """A photo older than 'since' must be excluded; a newer one must be included."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    older_date = "2023-01-01 00:00:00"
    newer_date = "2023-06-15 18:30:00"
    _write_photo(tmp_path, "photo_old.json", _make_photo_data(date_taken=older_date, geo=GEOTAGGED))
    _write_photo(tmp_path, "photo_new.json", _make_photo_data(date_taken=newer_date, geo=GEOTAGGED))

    older_ts = int(datetime.fromisoformat(older_date.replace(" ", "T")).timestamp())

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records(since=older_ts))

    assert len(records) == 1, f"Expected only the newer photo, got {len(records)} records"
    newer_ts = int(datetime.fromisoformat(newer_date.replace(" ", "T")).timestamp())
    assert records[0]["timestamp"] == newer_ts


def test_fetch_records_dict_has_required_keys(tmp_path: Path) -> None:
    """Each yielded dict must have the required place record keys."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=GEOTAGGED))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert len(records) == 1

    required_keys = {
        "source_id",
        "timestamp",
        "lat",
        "lng",
        "place_name",
        "place_type",
        "raw_json",
        "fetched_at",
    }
    missing = required_keys - set(records[0].keys())
    assert not missing, f"Record missing required keys: {missing}"


def test_fetch_records_source_id_is_flickr(tmp_path: Path) -> None:
    """Each record's source_id must equal 'flickr'."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=GEOTAGGED))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert records[0]["source_id"] == "flickr"


def test_fetch_records_fetched_at_is_recent(tmp_path: Path) -> None:
    """fetched_at must be a Unix timestamp close to now."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=GEOTAGGED))

    before = int(time.time())
    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    after = int(time.time())

    fetched_at = records[0]["fetched_at"]
    assert isinstance(fetched_at, int)
    assert before - 5 <= fetched_at <= after + 5, (
        f"fetched_at {fetched_at} not close to now ({before}-{after})"
    )


# ---------------------------------------------------------------------------
# OUTPUT_TABLES dual-output (issue #123)
# ---------------------------------------------------------------------------


def test_flickr_plugin_output_tables_includes_events() -> None:
    """OutputTable.EVENTS must now also be in FlickrPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.flickr.loader import FlickrPlugin

    assert OutputTable.EVENTS in FlickrPlugin.OUTPUT_TABLES


def test_flickr_plugin_output_tables_still_includes_places() -> None:
    """OutputTable.PLACES must remain in FlickrPlugin.OUTPUT_TABLES (unchanged)."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.flickr.loader import FlickrPlugin

    assert OutputTable.PLACES in FlickrPlugin.OUTPUT_TABLES


# ---------------------------------------------------------------------------
# fetch_secondary_records — EVENTS output (issue #123)
# ---------------------------------------------------------------------------


def test_fetch_secondary_records_non_geotagged_photo_is_yielded(tmp_path: Path) -> None:
    """A non-geotagged photo, dropped by fetch_records(geotagged_only=True), must
    still appear via fetch_secondary_records() — the whole point of the EVENTS pipeline."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path), geotagged_only=True)
    place_records = list(plugin.fetch_records())
    event_records = list(plugin.fetch_secondary_records())

    assert place_records == [], "Sanity check: PLACES pipeline still drops non-geotagged photos"
    assert len(event_records) == 1, (
        f"Expected the non-geotagged photo to appear via EVENTS, got {len(event_records)}"
    )


def test_fetch_secondary_records_geotagged_photo_also_yielded(tmp_path: Path) -> None:
    """A geotagged photo must also appear via fetch_secondary_records() (EVENTS)."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=GEOTAGGED))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    event_records = list(plugin.fetch_secondary_records())

    assert len(event_records) == 1


def test_fetch_secondary_records_label_is_photo_title(tmp_path: Path) -> None:
    """label must equal the photo's 'name' (title)."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(name="Sunset over the bay", geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())

    assert len(records) == 1
    assert records[0]["label"] == "Sunset over the bay"


def test_fetch_secondary_records_missing_title_yields_empty_label(tmp_path: Path) -> None:
    """A photo with no 'name' key must yield label == '' (not KeyError/None)."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(name=None, geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())

    assert len(records) == 1
    assert records[0]["label"] == ""


def test_fetch_secondary_records_sublabel_is_first_album(tmp_path: Path) -> None:
    """sublabel must equal the first album title when albums are present."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(
        tmp_path,
        "photo_1.json",
        _make_photo_data(albums=["Alps 2023", "Best Of"], geo=None),
    )

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())

    assert len(records) == 1
    assert records[0]["sublabel"] == "Alps 2023"


def test_fetch_secondary_records_no_albums_yields_empty_sublabel(tmp_path: Path) -> None:
    """sublabel must be '' when the photo has no albums."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(albums=[], geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())

    assert len(records) == 1
    assert records[0]["sublabel"] == ""


def test_fetch_secondary_records_category_is_photo(tmp_path: Path) -> None:
    """category must be 'photo' for every EVENTS record."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())

    assert records[0]["category"] == "photo"


def test_fetch_secondary_records_raw_json_preserves_tags_and_photopage(tmp_path: Path) -> None:
    """raw_json must preserve tags/albums/photopage verbatim for the EVENTS record."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    data = _make_photo_data(
        geo=None,
        tags=["mountains", "hiking"],
        albums=["Alps 2023"],
        photopage="https://www.flickr.com/photos/testuser/42/",
    )
    _write_photo(tmp_path, "photo_1.json", data)

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())
    assert len(records) == 1

    raw = _raw_json(records[0])
    assert raw["tags"] == ["mountains", "hiking"]
    assert raw["albums"] == ["Alps 2023"]
    assert raw["photopage"] == "https://www.flickr.com/photos/testuser/42/"


def test_fetch_secondary_records_source_id_is_flickr(tmp_path: Path) -> None:
    """Each EVENTS record's source_id must equal 'flickr'."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())

    assert records[0]["source_id"] == "flickr"


def test_fetch_secondary_records_dict_has_required_keys(tmp_path: Path) -> None:
    """Each EVENTS record must have the required event record keys."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())
    assert len(records) == 1

    required_keys = {
        "source_id",
        "timestamp",
        "label",
        "sublabel",
        "category",
        "raw_json",
        "fetched_at",
    }
    missing = required_keys - set(records[0].keys())
    assert not missing, f"EVENTS record missing required keys: {missing}"


def test_fetch_secondary_records_empty_export_dir_yields_empty_list(tmp_path: Path) -> None:
    """An empty export directory must yield [] from fetch_secondary_records()."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())

    assert records == []


def test_fetch_secondary_records_malformed_json_file_skipped(tmp_path: Path) -> None:
    """A malformed photo_*.json file must be skipped; the valid one still yielded."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    (tmp_path / "photo_bad.json").write_text("{not valid json", encoding="utf-8")
    _write_photo(tmp_path, "photo_good.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())

    assert len(records) == 1


def test_fetch_secondary_records_since_cursor_excludes_older_photo(tmp_path: Path) -> None:
    """A photo older than 'since' must be excluded from fetch_secondary_records()."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    older_date = "2023-01-01 00:00:00"
    newer_date = "2023-06-15 18:30:00"
    _write_photo(tmp_path, "photo_old.json", _make_photo_data(date_taken=older_date, geo=None))
    _write_photo(tmp_path, "photo_new.json", _make_photo_data(date_taken=newer_date, geo=None))

    older_ts = int(datetime.fromisoformat(older_date.replace(" ", "T")).timestamp())

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records(since=older_ts))

    assert len(records) == 1


def test_fetch_secondary_records_multiple_files_all_parsed(tmp_path: Path) -> None:
    """Multiple photo_*.json files (mixed geotagged status) must all appear as events."""
    from localizer.plugins.flickr.loader import FlickrPlugin

    _write_photo(tmp_path, "photo_1.json", _make_photo_data(geo=GEOTAGGED))
    _write_photo(tmp_path, "photo_2.json", _make_photo_data(geo=None))
    _write_photo(tmp_path, "photo_3.json", _make_photo_data(geo=None))

    plugin = FlickrPlugin(export_dir=str(tmp_path))
    records = list(plugin.fetch_secondary_records())

    assert len(records) == 3


# ---------------------------------------------------------------------------
# Network-isolation test
# ---------------------------------------------------------------------------


def test_flickr_loader_has_no_network_imports() -> None:
    """loader.py must contain no network-related imports (issue #19's zero-network requirement)."""
    import localizer.plugins.flickr.loader as loader_module

    source = Path(loader_module.__file__).read_text(encoding="utf-8")
    forbidden_patterns = [
        "import requests",
        "import urllib",
        "from urllib",
        "import httpx",
        "from httpx",
        "import socket",
        "from socket",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in source, (
            f"Found forbidden network-related import pattern {pattern!r} in loader.py"
        )
