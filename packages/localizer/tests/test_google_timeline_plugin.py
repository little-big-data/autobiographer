"""Failing tests for Subtask 1: GoogleTimelinePlugin in the localizer package.

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/google_timeline/__init__.py
  - packages/localizer/src/localizer/plugins/google_timeline/loader.py

GoogleTimelinePlugin is FetchMode.MANUAL — the user points it at a single
exported Timeline.json file (not a directory, unlike Swarm). It wraps
analysis_utils.load_google_timeline() and reuses that parser's venue /
venue_category values verbatim as place_name / place_type.

This file intentionally does NOT test REGISTRY / load_builtin_plugins() —
that wiring is Subtask 2's responsibility and belongs in test_cli.py so this
subtask's test file stays independently RED/GREEN.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal Timeline.json payload matching tests/test_google_timeline.py
# ---------------------------------------------------------------------------


def _timeline_payload_with_visit_and_activity() -> dict[str, Any]:
    """Return a Timeline.json payload with one visit segment and one activity segment.

    Mirrors the fixture shape used in tests/test_google_timeline.py: a
    frequent-place label for the HOME visit, and a WALKING activity segment.
    """
    return {
        "userLocationProfile": {
            "frequentPlaces": [
                {
                    "placeId": "PID_HOME",
                    "placeLocation": "40.0°, -74.0°",
                    "label": "My Home Base",
                }
            ]
        },
        "semanticSegments": [
            {
                "startTime": "2025-01-01T08:00:00.000-05:00",
                "endTime": "2025-01-01T09:00:00.000-05:00",
                "startTimeTimezoneUtcOffsetMinutes": -300,
                "visit": {
                    "topCandidate": {
                        "placeId": "PID_HOME",
                        "semanticType": "HOME",
                        "placeLocation": {"latLng": "40.0°, -74.0°"},
                    }
                },
            },
            {
                "startTime": "2025-01-04T11:00:00.000-05:00",
                "endTime": "2025-01-04T12:00:00.000-05:00",
                "startTimeTimezoneUtcOffsetMinutes": -300,
                "activity": {
                    "start": {"latLng": "43.0°, -77.0°"},
                    "end": {"latLng": "43.5°, -77.5°"},
                    "topCandidate": {"type": "WALKING"},
                },
            },
        ],
    }


def _write_timeline(path: Path, payload: dict[str, Any]) -> str:
    """Write *payload* as JSON to *path* and return the path as a string."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _stub_reverse_geocoder():
    """Stub the optional offline reverse_geocoder dependency for every test.

    load_google_timeline() calls reverse_geocoder.search() to fill city/
    state/country columns (irrelevant to this plugin's output schema, which
    only surfaces place_name/place_type/lat/lng). Stubbing keeps tests fast
    and deterministic and avoids a first-run dataset download, mirroring the
    setUp() patch in tests/test_google_timeline.py.
    """
    from unittest.mock import patch

    with patch(
        "reverse_geocoder.search",
        side_effect=lambda coords, verbose=False: [
            {"name": "TestCity", "admin1": "TestState", "cc": "US"} for _ in coords
        ],
    ):
        yield


# ---------------------------------------------------------------------------
# Class-attribute tests
# ---------------------------------------------------------------------------


def test_google_timeline_plugin_plugin_id() -> None:
    """GoogleTimelinePlugin.PLUGIN_ID must equal 'google_timeline'."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    assert GoogleTimelinePlugin.PLUGIN_ID == "google_timeline"


def test_google_timeline_plugin_display_name_is_set() -> None:
    """GoogleTimelinePlugin.DISPLAY_NAME must be a non-empty string."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    assert isinstance(GoogleTimelinePlugin.DISPLAY_NAME, str)
    assert len(GoogleTimelinePlugin.DISPLAY_NAME.strip()) > 0


def test_google_timeline_plugin_fetch_mode_manual() -> None:
    """GoogleTimelinePlugin.FETCH_MODE must be FetchMode.MANUAL."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    assert GoogleTimelinePlugin.FETCH_MODE == FetchMode.MANUAL


def test_google_timeline_plugin_output_tables_places() -> None:
    """OutputTable.PLACES must be in GoogleTimelinePlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    assert OutputTable.PLACES in GoogleTimelinePlugin.OUTPUT_TABLES


def test_google_timeline_plugin_icon_is_set() -> None:
    """GoogleTimelinePlugin.ICON must be a non-empty string."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    assert isinstance(GoogleTimelinePlugin.ICON, str)
    assert len(GoogleTimelinePlugin.ICON.strip()) > 0


def test_google_timeline_plugin_get_config_fields() -> None:
    """get_config_fields() must return a non-empty list with a distinct settings key."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    plugin = GoogleTimelinePlugin()
    fields = plugin.get_config_fields()
    assert isinstance(fields, list)
    assert len(fields) >= 1, "Expected at least one config field (Timeline.json path)"
    for field in fields:
        assert "key" in field, f"Config field missing 'key': {field}"
        assert "label" in field, f"Config field missing 'label': {field}"

    keys = [field["key"] for field in fields]
    assert "google_timeline_path" in keys, (
        "Expected the localizer-side settings key 'google_timeline_path', distinct "
        "from the legacy plugin's Streamlit session-state key 'timeline_path'"
    )


def test_google_timeline_plugin_manual_download_instructions() -> None:
    """get_manual_download_instructions() must return a non-empty string."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    plugin = GoogleTimelinePlugin()
    instructions = plugin.get_manual_download_instructions()
    assert isinstance(instructions, str)
    assert len(instructions.strip()) > 0


# ---------------------------------------------------------------------------
# fetch_records normalization tests
# ---------------------------------------------------------------------------


def test_fetch_records_yields_one_dict_per_segment(tmp_path: Path) -> None:
    """A Timeline.json with 1 visit + 1 activity segment yields exactly 2 dicts."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    assert len(records) == 2, f"Expected 2 records (1 visit + 1 activity), got {len(records)}"


def test_fetch_records_dict_has_required_keys(tmp_path: Path) -> None:
    """Each yielded dict must have exactly the required place record keys."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    assert len(records) == 2

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
    for record in records:
        assert set(record.keys()) == required_keys, (
            f"Record keys {set(record.keys())} != expected {required_keys}"
        )


def test_fetch_records_source_id_is_google_timeline(tmp_path: Path) -> None:
    """Every yielded record's source_id must equal 'google_timeline'."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    assert len(records) == 2
    for record in records:
        assert record["source_id"] == "google_timeline"


def test_fetch_records_lat_lng_are_floats(tmp_path: Path) -> None:
    """lat and lng in each record must be Python floats."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    for record in records:
        assert isinstance(record["lat"], float), f"Expected float lat, got {type(record['lat'])}"
        assert isinstance(record["lng"], float), f"Expected float lng, got {type(record['lng'])}"


def test_fetch_records_timestamp_is_int(tmp_path: Path) -> None:
    """timestamp in each record must be a Python int (Unix seconds)."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    for record in records:
        assert isinstance(record["timestamp"], int), (
            f"Expected int timestamp, got {type(record['timestamp'])}"
        )


def test_fetch_records_visit_place_name_and_type_match_parser(tmp_path: Path) -> None:
    """For the visit segment, place_name/place_type must equal the parser's venue/venue_category.

    The HOME visit has a frequent-place label ("My Home Base") and semantic
    type "HOME" -> venue_category "home" (lowercased) per
    analysis_utils.load_google_timeline().
    """
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    visit_records = [r for r in records if not str(r["place_type"]).startswith("activity:")]
    assert len(visit_records) == 1
    visit = visit_records[0]
    assert visit["place_name"] == "My Home Base", (
        "place_name must equal the parser's venue value (frequent-place label), "
        "not be re-derived from raw JSON"
    )
    assert visit["place_type"] == "home", (
        "place_type must equal the parser's venue_category value verbatim"
    )


def test_fetch_records_activity_place_type_starts_with_activity_prefix(
    tmp_path: Path,
) -> None:
    """For the activity segment, place_type must start with 'activity:'."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    activity_records = [r for r in records if str(r["place_type"]).startswith("activity:")]
    assert len(activity_records) == 1
    activity = activity_records[0]
    assert activity["place_type"] == "activity:walking"
    assert activity["place_name"] == "Walking"


def test_fetch_records_fetched_at_is_recent(tmp_path: Path) -> None:
    """fetched_at must be a Unix timestamp close to now (within 60 seconds)."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    before = int(time.time())
    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    after = int(time.time())

    assert len(records) == 2
    for record in records:
        fetched_at = record["fetched_at"]
        assert isinstance(fetched_at, int)
        assert before - 5 <= fetched_at <= after + 5, (
            f"fetched_at {fetched_at} not close to now ({before}-{after})"
        )


def test_fetch_records_raw_json_is_serializable(tmp_path: Path) -> None:
    """raw_json on each yielded record must be JSON-serializable (str or dict)."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    assert len(records) == 2
    for record in records:
        raw = record["raw_json"]
        if isinstance(raw, str):
            json.loads(raw)  # must not raise
        else:
            json.dumps(raw)  # must not raise


def test_fetch_records_since_filtering_excludes_older_record(tmp_path: Path) -> None:
    """A record with timestamp <= since must be excluded from the results."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    all_records = list(plugin.fetch_records())
    assert len(all_records) == 2
    timestamps = sorted(r["timestamp"] for r in all_records)
    older_timestamp = timestamps[0]

    filtered = list(plugin.fetch_records(since=older_timestamp))
    assert len(filtered) == 1, "Expected the older-or-equal record to be excluded"
    assert all(r["timestamp"] > older_timestamp for r in filtered)


# ---------------------------------------------------------------------------
# No-path / missing-file / unsupported-format edge cases
# ---------------------------------------------------------------------------


def test_fetch_records_no_path_configured_yields_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No explicit path and no settings entry -> fetch_records() yields [], no exception."""
    # Point LocalizerSettings at a config file that doesn't exist, so
    # get_setting("google_timeline_path") resolves to None.
    monkeypatch.setenv("LOCALIZER_CONFIG_PATH", str(tmp_path / "empty_config.toml"))

    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    plugin = GoogleTimelinePlugin()
    records = list(plugin.fetch_records())
    assert records == [], f"Expected empty list when unconfigured, got {records}"


def test_fetch_records_missing_file_yields_nothing(tmp_path: Path) -> None:
    """A configured path that does not exist on disk -> fetch_records() yields [], no exception."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    nonexistent = tmp_path / "does_not_exist.json"
    plugin = GoogleTimelinePlugin(timeline_path=str(nonexistent))
    try:
        records = list(plugin.fetch_records())
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"fetch_records() raised {type(exc).__name__} on missing file: {exc}")
    assert records == [], f"Expected empty list for missing file, got {records}"


def test_fetch_records_unsupported_format_raises_oserror(tmp_path: Path) -> None:
    """A JSON file without top-level semanticSegments must raise OSError, not ValueError."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    bad_file = tmp_path / "Records.json"
    bad_file.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    plugin = GoogleTimelinePlugin(timeline_path=str(bad_file))
    with pytest.raises(OSError) as exc_info:
        list(plugin.fetch_records())
    # OSError and ValueError are unrelated exception types; if the underlying
    # ValueError from load_google_timeline() were allowed to leak instead of
    # being translated, pytest.raises(OSError) above would already fail with
    # the wrong exception type. This assertion documents the intent
    # explicitly so a future regression is caught with a clear message.
    assert not isinstance(exc_info.value, ValueError), (
        "fetch_records() must translate ValueError to OSError, not let it escape"
    )


def test_fetch_records_legacy_records_format_raises_oserror(tmp_path: Path) -> None:
    """A legacy Records.json-shaped export (locations key) must also raise OSError."""
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    legacy_file = tmp_path / "Records.json"
    legacy_file.write_text(json.dumps({"locations": [{"latitudeE7": 400000000}]}), encoding="utf-8")

    plugin = GoogleTimelinePlugin(timeline_path=str(legacy_file))
    with pytest.raises(OSError):
        list(plugin.fetch_records())


# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------


def test_init_reads_path_from_localizer_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no explicit path, __init__ must resolve the path via LocalizerSettings.

    Writes a real config.toml (via LOCALIZER_CONFIG_PATH, matching the
    pattern in packages/localizer/tests/test_settings.py) with
    google_timeline_path set, then confirms fetch_records() reads from it.
    """
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("LOCALIZER_CONFIG_PATH", str(config_path))

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    from localizer.settings import LocalizerSettings

    LocalizerSettings().set_setting("google_timeline_path", timeline_path)

    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    plugin = GoogleTimelinePlugin()
    records = list(plugin.fetch_records())
    assert len(records) == 2, (
        "Expected __init__ to resolve the path via "
        "LocalizerSettings().get_setting('google_timeline_path')"
    )


def test_explicit_path_overrides_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit timeline_path argument must take precedence over settings."""
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("LOCALIZER_CONFIG_PATH", str(config_path))

    from localizer.settings import LocalizerSettings

    # Settings points at a nonexistent file...
    LocalizerSettings().set_setting(
        "google_timeline_path", str(tmp_path / "settings_does_not_exist.json")
    )

    # ...but the explicit constructor arg points at a valid fixture.
    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    assert len(records) == 2, "Explicit timeline_path must override the settings-derived value"


# ---------------------------------------------------------------------------
# Subtask 2 — fetch_records() must not depend on analysis_utils being
# importable (the installed console-script entry point has no access to the
# top-level app's sys.path, so a lazy `from analysis_utils import ...` inside
# fetch_records() breaks it in production even though it "works" under
# pytest, which injects the repo root via pythonpath).
# ---------------------------------------------------------------------------


def test_fetch_records_does_not_require_analysis_utils_importable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fetch_records() must not raise if `analysis_utils` cannot be imported.

    Forces `sys.modules["analysis_utils"] = None`, which makes any
    `from analysis_utils import ...` raise
    `ImportError: import of analysis_utils halted; None in sys.modules` -
    simulating the real installed-console-script failure mode where
    `analysis_utils.py` (a bare top-level module, not part of any installed
    package) is not on `sys.path` at all.

    Pre-fix, loader.py's fetch_records() does a lazy
    `from analysis_utils import load_google_timeline`, so this test fails
    with that exact ImportError. Post-fix, the plugin must import its parser
    from `localizer.plugins.google_timeline.parser` instead, which has no
    dependency on `analysis_utils` being importable.
    """
    import sys

    monkeypatch.setitem(sys.modules, "analysis_utils", None)

    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin

    timeline_path = _write_timeline(
        tmp_path / "Timeline.json", _timeline_payload_with_visit_and_activity()
    )

    plugin = GoogleTimelinePlugin(timeline_path=timeline_path)
    records = list(plugin.fetch_records())
    assert len(records) > 0, (
        "Expected fetch_records() to yield records even when analysis_utils "
        "cannot be imported - it must not depend on that module at runtime"
    )
