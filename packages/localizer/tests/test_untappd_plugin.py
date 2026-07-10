"""Failing tests for Subtask 3: UntappdPlugin in the localizer package (issue #20).

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/untappd/__init__.py
  - packages/localizer/src/localizer/plugins/untappd/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py (load_builtin_plugins)

UntappdPlugin is FetchMode.MANUAL, OutputTable.EVENTS — it reads a single
check-in history CSV export file (mirroring letterboxd/loader.py's
single-CSV-file, FileNotFoundError-on-configured-missing-path shape) and
never makes any network call itself.

Field mapping (per handoff.md Subtask 3, translated from issue #20 into the
new events schema): label=brewery_name, sublabel=beer_name,
category=beer_type. rating_score/venue_name/venue_lat/venue_lng are NOT
promoted to real DB columns (events has no lat/lng at all) — they live only
inside raw_json, using None (not NaN) for "missing" so raw_json stays valid
JSON.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal Untappd check-in history CSV content
# ---------------------------------------------------------------------------

UNTAPPD_CSV_HEADER = (
    "created_at,brewery_name,beer_name,beer_type,rating_score,"
    "venue_name,venue_lat,venue_lng,comment,flavor_profiles,serving_type,photo_url"
)

# Row 1: rated check-in, with venue, space-separated created_at.
# Row 2: unrated check-in, no venue.
UNTAPPD_CSV_TWO_ROWS = f"""\
{UNTAPPD_CSV_HEADER}
2023-06-15 18:30:00,Test Brewery Co.,Hazy IPA,IPA,4.5,The Tasting Room,40.7128,-74.0060,Great beer!,citrus;piney,Draft,https://example.com/photo1.jpg
2023-06-16 12:00:00,Other Brewery,Pale Ale,American Pale Ale,,,,,,,Bottle,
"""

UNTAPPD_CSV_HEADER_ONLY = f"{UNTAPPD_CSV_HEADER}\n"

UNTAPPD_CSV_T_SEPARATED = f"""\
{UNTAPPD_CSV_HEADER}
2023-06-15T18:30:00,Test Brewery Co.,Hazy IPA,IPA,4.5,The Tasting Room,40.7128,-74.0060,Great beer!,citrus;piney,Draft,https://example.com/photo1.jpg
"""

UNTAPPD_CSV_SINCE_CURSOR = f"""\
{UNTAPPD_CSV_HEADER}
2023-01-01 08:00:00,Old Brewery,Old Ale,Ale,3.0,,,,,,,
2023-06-15 18:30:00,Test Brewery Co.,Hazy IPA,IPA,4.5,The Tasting Room,40.7128,-74.0060,Great beer!,citrus;piney,Draft,https://example.com/photo1.jpg
"""


def _make_plugin() -> Any:
    """Instantiate an UntappdPlugin."""
    from localizer.plugins.untappd.loader import UntappdPlugin

    return UntappdPlugin()


def _write_csv(tmp_path: Path, content: str, filename: str = "checkins.csv") -> Path:
    """Write CSV content to a temp file and return the path."""
    csv_path = tmp_path / filename
    csv_path.write_text(content, encoding="utf-8")
    return csv_path


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


def test_untappd_plugin_id() -> None:
    """UntappdPlugin.PLUGIN_ID must equal 'untappd'."""
    from localizer.plugins.untappd.loader import UntappdPlugin

    assert UntappdPlugin.PLUGIN_ID == "untappd"


def test_untappd_fetch_mode_manual() -> None:
    """UntappdPlugin.FETCH_MODE must be FetchMode.MANUAL."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.untappd.loader import UntappdPlugin

    assert UntappdPlugin.FETCH_MODE == FetchMode.MANUAL


def test_untappd_output_tables_events() -> None:
    """OutputTable.EVENTS must be in UntappdPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.untappd.loader import UntappdPlugin

    assert OutputTable.EVENTS in UntappdPlugin.OUTPUT_TABLES


def test_untappd_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['untappd'] must exist."""
    from localizer.plugins import REGISTRY, load_builtin_plugins

    REGISTRY.clear()
    load_builtin_plugins()
    assert "untappd" in REGISTRY, f"'untappd' not in REGISTRY; keys: {list(REGISTRY)}"


def test_untappd_get_config_fields_shape() -> None:
    """get_config_fields() must return one file_path field keyed 'checkins_csv'."""
    plugin = _make_plugin()
    fields = plugin.get_config_fields()

    assert isinstance(fields, list)
    assert len(fields) == 1, f"Expected exactly 1 config field, got {len(fields)}"
    field = fields[0]
    assert field["key"] == "checkins_csv"
    assert "label" in field
    assert field["type"] == "file_path"


def test_untappd_manual_download_instructions() -> None:
    """get_manual_download_instructions() must mention 'untappd.com' and 'csv'."""
    plugin = _make_plugin()
    instructions = plugin.get_manual_download_instructions()

    assert isinstance(instructions, str)
    assert len(instructions.strip()) > 0, "Expected non-empty manual download instructions"

    instructions_lower = instructions.lower()
    assert "untappd.com" in instructions_lower, (
        f"'untappd.com' not found in instructions: {instructions!r}"
    )
    assert "csv" in instructions_lower, f"'csv' not found in instructions: {instructions!r}"


# ---------------------------------------------------------------------------
# CSV parsing — basic shape / required keys
# ---------------------------------------------------------------------------


def test_untappd_fetch_records_from_csv_count(tmp_path: Path) -> None:
    """fetch_records(checkins_csv=...) must yield 2 records from a 2-row CSV."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    assert len(records) == 2, f"Expected 2 records, got {len(records)}"


def test_untappd_required_keys_present(tmp_path: Path) -> None:
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
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    for record in records:
        missing = required_keys - set(record.keys())
        assert not missing, f"Record missing required keys: {missing}"


def test_untappd_source_id_is_untappd(tmp_path: Path) -> None:
    """source_id in each record must equal 'untappd'."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    for record in records:
        assert record["source_id"] == "untappd", f"source_id {record['source_id']!r} != 'untappd'"


def test_untappd_fetched_at_is_recent(tmp_path: Path) -> None:
    """fetched_at must be a Unix timestamp close to now."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    before = int(time.time())
    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))
    after = int(time.time())

    for record in records:
        assert isinstance(record["fetched_at"], int)
        assert before - 5 <= record["fetched_at"] <= after + 5, (
            f"fetched_at {record['fetched_at']} not close to now ({before}-{after})"
        )


# ---------------------------------------------------------------------------
# label / sublabel / category mapping
# ---------------------------------------------------------------------------


def test_untappd_label_sublabel_category_mapping(tmp_path: Path) -> None:
    """label/sublabel/category must equal brewery_name/beer_name/beer_type exactly."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    hazy_ipa = next(r for r in records if r["sublabel"] == "Hazy IPA")
    assert hazy_ipa["label"] == "Test Brewery Co.", (
        f"label {hazy_ipa['label']!r} != 'Test Brewery Co.'"
    )
    assert hazy_ipa["sublabel"] == "Hazy IPA", f"sublabel {hazy_ipa['sublabel']!r} != 'Hazy IPA'"
    assert hazy_ipa["category"] == "IPA", f"category {hazy_ipa['category']!r} != 'IPA'"

    pale_ale = next(r for r in records if r["sublabel"] == "Pale Ale")
    assert pale_ale["label"] == "Other Brewery"
    assert pale_ale["category"] == "American Pale Ale"


# ---------------------------------------------------------------------------
# created_at timestamp parsing
# ---------------------------------------------------------------------------


def test_untappd_created_at_space_separated_parses(tmp_path: Path) -> None:
    """A space-separated created_at ('2023-06-15 18:30:00') must parse to a positive int."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    hazy_ipa = next(r for r in records if r["sublabel"] == "Hazy IPA")
    assert isinstance(hazy_ipa["timestamp"], int)
    assert hazy_ipa["timestamp"] > 0


def test_untappd_created_at_t_separated_parses(tmp_path: Path) -> None:
    """A T-separated ISO created_at ('2023-06-15T18:30:00') must parse to a positive int."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_T_SEPARATED)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    assert len(records) == 1
    assert isinstance(records[0]["timestamp"], int)
    assert records[0]["timestamp"] > 0


def test_untappd_created_at_formats_are_equivalent(tmp_path: Path) -> None:
    """Space-separated and T-separated forms of the same instant must yield the same timestamp."""
    space_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS, filename="space.csv")
    t_path = _write_csv(tmp_path, UNTAPPD_CSV_T_SEPARATED, filename="t_sep.csv")

    plugin = _make_plugin()
    space_records = list(plugin.fetch_records(checkins_csv=str(space_path)))
    t_records = list(plugin.fetch_records(checkins_csv=str(t_path)))

    space_hazy = next(r for r in space_records if r["sublabel"] == "Hazy IPA")
    t_hazy = next(r for r in t_records if r["sublabel"] == "Hazy IPA")

    assert space_hazy["timestamp"] == t_hazy["timestamp"], (
        f"space-separated timestamp {space_hazy['timestamp']} != "
        f"T-separated timestamp {t_hazy['timestamp']}"
    )


def test_untappd_unparseable_created_at_falls_back_to_fetched_at(tmp_path: Path) -> None:
    """An unparseable created_at value must not raise; timestamp falls back to fetched_at."""
    bad_csv = f"""\
{UNTAPPD_CSV_HEADER}
not-a-real-date,Test Brewery Co.,Hazy IPA,IPA,4.5,,,,,,,
"""
    csv_path = _write_csv(tmp_path, bad_csv)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    assert len(records) == 1
    assert records[0]["timestamp"] == records[0]["fetched_at"]


# ---------------------------------------------------------------------------
# rating parsing
# ---------------------------------------------------------------------------


def test_untappd_rated_checkin_rating_is_float(tmp_path: Path) -> None:
    """A rated check-in's raw_json['rating'] must be a Python float equal to the CSV value."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    hazy_ipa = next(r for r in records if r["sublabel"] == "Hazy IPA")
    rating = _raw_json(hazy_ipa)["rating"]
    assert isinstance(rating, float), f"rating is {type(rating)}, expected float"
    assert rating == 4.5


def test_untappd_unrated_checkin_rating_is_none(tmp_path: Path) -> None:
    """An unrated check-in's raw_json['rating'] must be None, not 0.0 or a string."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    pale_ale = next(r for r in records if r["sublabel"] == "Pale Ale")
    assert _raw_json(pale_ale)["rating"] is None


# ---------------------------------------------------------------------------
# venue lat/lng/name in raw_json
# ---------------------------------------------------------------------------


def test_untappd_checkin_with_venue_has_float_lat_lng_in_raw_json(tmp_path: Path) -> None:
    """A check-in with a venue must have raw_json['venue_lat']/['venue_lng'] as the exact floats."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    hazy_ipa = next(r for r in records if r["sublabel"] == "Hazy IPA")
    raw = _raw_json(hazy_ipa)
    assert isinstance(raw["venue_lat"], float)
    assert isinstance(raw["venue_lng"], float)
    assert raw["venue_lat"] == 40.7128
    assert raw["venue_lng"] == -74.0060
    assert raw["venue_name"] == "The Tasting Room"


def test_untappd_checkin_without_venue_has_none_lat_lng_in_raw_json(tmp_path: Path) -> None:
    """A check-in without a venue must have raw_json['venue_lat']/['venue_lng'] as None."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    pale_ale = next(r for r in records if r["sublabel"] == "Pale Ale")
    raw = _raw_json(pale_ale)
    assert raw["venue_lat"] is None, f"venue_lat {raw['venue_lat']!r} is not None"
    assert raw["venue_lng"] is None, f"venue_lng {raw['venue_lng']!r} is not None"


def test_untappd_no_top_level_venue_lat_lng_keys(tmp_path: Path) -> None:
    """venue_lat/venue_lng must not leak as top-level record keys (events has no lat/lng columns)."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    for record in records:
        assert "venue_lat" not in record
        assert "venue_lng" not in record


# ---------------------------------------------------------------------------
# raw_json preservation / round-trip
# ---------------------------------------------------------------------------


def test_untappd_raw_json_round_trips_and_preserves_fields(tmp_path: Path) -> None:
    """raw_json must be JSON-serializable and preserve comment/flavor_profiles/serving_type/photo_url."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    for record in records:
        raw = record["raw_json"]
        # Must be JSON-serializable regardless of whether the plugin hands back
        # a dict or an already-dumped string.
        if isinstance(raw, str):
            json.loads(raw)  # must not raise
        else:
            json.dumps(raw)  # must not raise

    hazy_ipa = next(r for r in records if r["sublabel"] == "Hazy IPA")
    raw = _raw_json(hazy_ipa)
    assert raw["comment"] == "Great beer!"
    assert raw["flavor_profiles"] == "citrus;piney"
    assert raw["serving_type"] == "Draft"
    assert raw["photo_url"] == "https://example.com/photo1.jpg"


def test_untappd_raw_json_none_values_round_trip(tmp_path: Path) -> None:
    """raw_json containing None values (unrated, no-venue row) must still round-trip through json."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    pale_ale = next(r for r in records if r["sublabel"] == "Pale Ale")
    raw = pale_ale["raw_json"]
    if isinstance(raw, str):
        parsed = json.loads(raw)
    else:
        parsed = json.loads(json.dumps(raw))

    assert parsed["rating"] is None
    assert parsed["venue_lat"] is None
    assert parsed["venue_lng"] is None


# ---------------------------------------------------------------------------
# empty CSV / missing file / unconfigured
# ---------------------------------------------------------------------------


def test_untappd_empty_csv_yields_empty_list(tmp_path: Path) -> None:
    """A CSV with only a header row (zero data rows) must yield an empty list, not raise."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_HEADER_ONLY)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(checkins_csv=str(csv_path)))

    assert records == []


def test_untappd_missing_csv_raises_file_not_found(tmp_path: Path) -> None:
    """A configured but nonexistent checkins_csv path must raise FileNotFoundError."""
    plugin = _make_plugin()
    missing_path = tmp_path / "nonexistent" / "checkins.csv"

    with pytest.raises(FileNotFoundError):
        list(plugin.fetch_records(checkins_csv=str(missing_path)))


def test_untappd_missing_csv_error_mentions_untappd(tmp_path: Path) -> None:
    """The FileNotFoundError message should name the path and point at untappd.com."""
    plugin = _make_plugin()
    missing_path = tmp_path / "nonexistent" / "checkins.csv"

    with pytest.raises(FileNotFoundError) as exc_info:
        list(plugin.fetch_records(checkins_csv=str(missing_path)))

    message = str(exc_info.value).lower()
    assert "untappd.com" in message


def test_untappd_unconfigured_yields_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """With checkins_csv=None and no LocalizerSettings override, fetch_records() yields nothing."""
    _no_settings_override(monkeypatch)

    plugin = _make_plugin()
    records = list(plugin.fetch_records())

    assert records == []


# ---------------------------------------------------------------------------
# since cursor
# ---------------------------------------------------------------------------


def test_untappd_since_cursor_excludes_older_row(tmp_path: Path) -> None:
    """A row whose timestamp is <= since must be excluded; a newer row must be included."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_SINCE_CURSOR)

    plugin = _make_plugin()
    all_records = list(plugin.fetch_records(checkins_csv=str(csv_path)))
    assert len(all_records) == 2, f"Expected 2 records with no cursor, got {len(all_records)}"

    old_record = next(r for r in all_records if r["sublabel"] == "Old Ale")
    since = old_record["timestamp"]

    filtered_records = list(plugin.fetch_records(checkins_csv=str(csv_path), since=since))

    assert len(filtered_records) == 1, (
        f"Expected 1 record after since-cursor filtering, got {len(filtered_records)}"
    )
    assert filtered_records[0]["sublabel"] == "Hazy IPA"


# ---------------------------------------------------------------------------
# no-network-imports guard
# ---------------------------------------------------------------------------


def test_untappd_loader_has_no_network_imports() -> None:
    """loader.py must not import requests/urllib/httpx/socket — zero network code."""
    import localizer.plugins.untappd.loader as loader_module

    source = Path(loader_module.__file__).read_text(encoding="utf-8")

    for forbidden in ("import requests", "import urllib", "import httpx", "import socket"):
        assert forbidden not in source, f"Found forbidden network import: {forbidden!r}"


# ---------------------------------------------------------------------------
# CSV parsing correctness sanity check (csv.DictReader convention)
# ---------------------------------------------------------------------------


def test_untappd_parses_header_columns_via_dictreader(tmp_path: Path) -> None:
    """Sanity check: the fixture CSV itself is well-formed per csv.DictReader."""
    csv_path = _write_csv(tmp_path, UNTAPPD_CSV_TWO_ROWS)

    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["brewery_name"] == "Test Brewery Co."
