"""Failing tests for Subtask 1 (issue #18): StoryGraphPlugin in the localizer package.

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/storygraph/__init__.py
  - packages/localizer/src/localizer/plugins/storygraph/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py (load_builtin_plugins)

StoryGraphPlugin is FetchMode.MANUAL, CSV-export only (no Playwright/API path).
The CSV format is the StoryGraph library export
(app.thestorygraph.com -> Manage Account -> Manage Your Data -> "Export StoryGraph Library").

Column names used by these fixtures follow the Task Overview's exact mapping:
``Title``, ``Authors``, ``Read Status``, ``Date Read``, ``Star Rating``,
``Number of Pages`` plus Title-Case ``Pace``, ``Genres``, ``Moods``, ``Format``
columns, matching the real StoryGraph library export format (issue #18).
The loader MUST rename these four Title-Case CSV columns to lowercase keys
(``pace``, ``genres``, ``moods``, ``format``) in the output ``raw_json`` —
this is NOT a straight ``dict(row)`` passthrough for these fields.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal StoryGraph library-export CSV content
# ---------------------------------------------------------------------------

STORYGRAPH_CSV_HEADER = (
    "Title,Authors,Read Status,Date Read,Star Rating,Number of Pages,Pace,Genres,Moods,Format"
)

# Row 1 ("The Left Hand of Darkness"): Read Status="read", well-formed -> INCLUDED.
#   Date Read uses YYYY/MM/DD format, calendar date 2022-03-10.
# Row 2 ("Some To-Read Book"): Read Status="to-read" -> EXCLUDED (status filter).
# Row 3 ("Currently Reading Book"): Read Status="currently-reading" -> EXCLUDED (status filter).
# Row 4 ("Capital Read Status Book"): Read Status="Read" (capital R) -> EXCLUDED
#   (case-sensitivity: must NOT be accidentally case-folded to match "read").
# Row 5 ("Missing Date Book"): Read Status="read" but Date Read is empty -> EXCLUDED.
# Row 6 ("Blank Rating Book"): Read Status="read", blank Star Rating, valid Number of Pages
#   -> INCLUDED, exercises rating=None-on-blank path.
# Row 7 ("Blank Pages Book"): Read Status="read", valid Star Rating, blank Number of Pages
#   -> INCLUDED, exercises pages=None-on-blank path.
STORYGRAPH_CSV_MULTI_ROW = f"""\
{STORYGRAPH_CSV_HEADER}
The Left Hand of Darkness,Ursula K. Le Guin,read,2022/03/10,4.5,304,medium,Science Fiction,reflective,hardcover
Some To-Read Book,Jane Doe,to-read,,,,,,,
Currently Reading Book,John Smith,currently-reading,2024/01/01,3.0,250,slow,Fantasy,dark,paperback
Capital Read Status Book,Case Sensitive Author,Read,2024/02/02,5.0,400,fast,Mystery,tense,audiobook
Missing Date Book,No Date Author,read,,4.0,200,fast,Horror,scary,ebook
Blank Rating Book,Blank Author,read,2023/07/01,,150,fast,Fiction,joyful,ebook
Blank Pages Book,Pages Author,read,2023/08/01,3.5,,slow,Nonfiction,calm,ebook
"""

# Two rows, same calendar date (2023-06-15), different Date Read formats.
# Both must parse to the identical, correct UTC-midnight epoch.
STORYGRAPH_CSV_DATE_FORMATS = f"""\
{STORYGRAPH_CSV_HEADER}
Format YMD Book,Format Author,read,2023/06/15,4.0,300,medium,Fiction,calm,ebook
Format MDY Book,Format Author,read,06/15/2023,4.0,300,medium,Fiction,calm,ebook
"""

STORYGRAPH_CSV_EMPTY = STORYGRAPH_CSV_HEADER + "\n"

# Hand-computed (independent of the loader) expected UTC-midnight epoch values.
EXPECTED_TS_2022_03_10 = int(datetime(2022, 3, 10, tzinfo=timezone.utc).timestamp())
EXPECTED_TS_2023_06_15 = int(datetime(2023, 6, 15, tzinfo=timezone.utc).timestamp())


def _make_plugin() -> Any:
    """Instantiate a StoryGraphPlugin."""
    from localizer.plugins.storygraph.loader import StoryGraphPlugin

    return StoryGraphPlugin()


def _write_csv(tmp_path: Path, content: str, filename: str = "storygraph_library.csv") -> Path:
    """Write CSV content to a temp file and return the path."""
    csv_path = tmp_path / filename
    csv_path.write_text(content, encoding="utf-8")
    return csv_path


# ---------------------------------------------------------------------------
# ABC / class attribute tests
# ---------------------------------------------------------------------------


def test_storygraph_plugin_id() -> None:
    """StoryGraphPlugin.PLUGIN_ID must equal 'storygraph'."""
    from localizer.plugins.storygraph.loader import StoryGraphPlugin

    assert StoryGraphPlugin.PLUGIN_ID == "storygraph"


def test_storygraph_fetch_mode() -> None:
    """StoryGraphPlugin.FETCH_MODE must be FetchMode.MANUAL."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.storygraph.loader import StoryGraphPlugin

    assert StoryGraphPlugin.FETCH_MODE == FetchMode.MANUAL


def test_storygraph_output_tables() -> None:
    """OutputTable.EVENTS must be in StoryGraphPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.storygraph.loader import StoryGraphPlugin

    assert OutputTable.EVENTS in StoryGraphPlugin.OUTPUT_TABLES


def test_storygraph_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['storygraph'] must be StoryGraphPlugin."""
    from localizer.plugins import REGISTRY, load_builtin_plugins
    from localizer.plugins.storygraph.loader import StoryGraphPlugin

    REGISTRY.clear()
    load_builtin_plugins()
    assert "storygraph" in REGISTRY, f"'storygraph' not in REGISTRY; keys: {list(REGISTRY)}"
    assert REGISTRY["storygraph"] is StoryGraphPlugin


# ---------------------------------------------------------------------------
# Basic field-mapping tests
# ---------------------------------------------------------------------------


def test_storygraph_fetch_records_basic_fields(tmp_path: Path) -> None:
    """fetch_records(export_csv=...) yields the required keys with correct core mapping."""
    required_keys = {
        "source_id",
        "timestamp",
        "label",
        "sublabel",
        "category",
        "raw_json",
        "fetched_at",
    }
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    assert len(records) > 0, "Expected at least one included record"
    for record in records:
        missing = required_keys - set(record.keys())
        assert not missing, f"Record missing required keys: {missing}"
        assert record["source_id"] == "storygraph"
        assert record["category"] == "book", (
            f"category {record['category']!r} != 'book' (must be a literal constant)"
        )

    left_hand = next(r for r in records if r["sublabel"] == "The Left Hand of Darkness")
    assert left_hand["label"] == "Ursula K. Le Guin", (
        f"label {left_hand['label']!r} != 'Ursula K. Le Guin'"
    )


def test_storygraph_timestamp_utc_midnight_ymd_format(tmp_path: Path) -> None:
    """Date Read in YYYY/MM/DD form must produce the exact UTC-midnight epoch."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    left_hand = next(r for r in records if r["sublabel"] == "The Left Hand of Darkness")
    assert isinstance(left_hand["timestamp"], int), (
        f"timestamp is {type(left_hand['timestamp'])}, expected int"
    )
    assert left_hand["timestamp"] == EXPECTED_TS_2022_03_10, (
        f"timestamp {left_hand['timestamp']} != hand-computed {EXPECTED_TS_2022_03_10} "
        "(possible local-tz regression instead of UTC-midnight)"
    )


def test_storygraph_date_formats_produce_identical_timestamp(tmp_path: Path) -> None:
    """YYYY/MM/DD and MM/DD/YYYY for the SAME calendar date must yield the identical epoch."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_DATE_FORMATS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    assert len(records) == 2, f"Expected 2 records, got {len(records)}"
    ymd_record = next(r for r in records if r["sublabel"] == "Format YMD Book")
    mdy_record = next(r for r in records if r["sublabel"] == "Format MDY Book")

    assert ymd_record["timestamp"] == EXPECTED_TS_2023_06_15, (
        f"YYYY/MM/DD timestamp {ymd_record['timestamp']} != {EXPECTED_TS_2023_06_15}"
    )
    assert mdy_record["timestamp"] == EXPECTED_TS_2023_06_15, (
        f"MM/DD/YYYY timestamp {mdy_record['timestamp']} != {EXPECTED_TS_2023_06_15}"
    )
    assert ymd_record["timestamp"] == mdy_record["timestamp"], (
        "Both Date Read formats for the same calendar date must produce identical timestamps"
    )


# ---------------------------------------------------------------------------
# Row-filtering tests
# ---------------------------------------------------------------------------


def test_storygraph_excludes_non_read_status(tmp_path: Path) -> None:
    """Rows with Read Status != 'read' (to-read, currently-reading) must be excluded."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    sublabels = {r["sublabel"] for r in records}
    assert "Some To-Read Book" not in sublabels, f"'to-read' row leaked through filter: {sublabels}"
    assert "Currently Reading Book" not in sublabels, (
        f"'currently-reading' row leaked through filter: {sublabels}"
    )


def test_storygraph_excludes_case_sensitive_capital_read(tmp_path: Path) -> None:
    """A row with Read Status == 'Read' (capital R) must be excluded — no case-folding."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    sublabels = {r["sublabel"] for r in records}
    assert "Capital Read Status Book" not in sublabels, (
        f"'Read' (capital R) row incorrectly included — filter is not case-sensitive: {sublabels}"
    )


def test_storygraph_excludes_missing_date_read(tmp_path: Path) -> None:
    """A row with Read Status == 'read' but empty Date Read must be excluded."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    sublabels = {r["sublabel"] for r in records}
    assert "Missing Date Book" not in sublabels, (
        f"row with empty Date Read incorrectly included: {sublabels}"
    )


# ---------------------------------------------------------------------------
# raw_json typed-field tests
# ---------------------------------------------------------------------------


def test_storygraph_raw_json_rating_float_when_present(tmp_path: Path) -> None:
    """raw_json['rating'] must be a float in [0.5, 5.0] when Star Rating is populated."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    left_hand = next(r for r in records if r["sublabel"] == "The Left Hand of Darkness")
    raw = json.loads(left_hand["raw_json"])
    assert isinstance(raw["rating"], float), f"rating is {type(raw['rating'])}, expected float"
    assert 0.5 <= raw["rating"] <= 5.0
    assert raw["rating"] == 4.5


def test_storygraph_raw_json_rating_none_when_blank(tmp_path: Path) -> None:
    """raw_json['rating'] must be None when Star Rating is blank, and must not raise."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    blank_rating = next(r for r in records if r["sublabel"] == "Blank Rating Book")
    raw = json.loads(blank_rating["raw_json"])
    assert raw["rating"] is None, f"rating {raw['rating']!r} != None for blank Star Rating"


def test_storygraph_raw_json_pages_int_when_present(tmp_path: Path) -> None:
    """raw_json['pages'] must be an int when Number of Pages is populated."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    left_hand = next(r for r in records if r["sublabel"] == "The Left Hand of Darkness")
    raw = json.loads(left_hand["raw_json"])
    assert isinstance(raw["pages"], int), f"pages is {type(raw['pages'])}, expected int"
    assert raw["pages"] == 304


def test_storygraph_raw_json_pages_none_when_blank(tmp_path: Path) -> None:
    """raw_json['pages'] must be None when Number of Pages is blank, and must not raise."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    blank_pages = next(r for r in records if r["sublabel"] == "Blank Pages Book")
    raw = json.loads(blank_pages["raw_json"])
    assert raw["pages"] is None, f"pages {raw['pages']!r} != None for blank Number of Pages"


def test_storygraph_raw_json_string_fields(tmp_path: Path) -> None:
    """raw_json must carry pace, genres, moods, format through unchanged as strings."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    left_hand = next(r for r in records if r["sublabel"] == "The Left Hand of Darkness")
    raw = json.loads(left_hand["raw_json"])
    assert raw["pace"] == "medium"
    assert raw["genres"] == "Science Fiction"
    assert raw["moods"] == "reflective"
    assert raw["format"] == "hardcover"
    for key in ("pace", "genres", "moods", "format"):
        assert isinstance(raw[key], str), f"raw_json[{key!r}] is {type(raw[key])}, expected str"


# ---------------------------------------------------------------------------
# Empty CSV / missing file tests
# ---------------------------------------------------------------------------


def test_storygraph_empty_csv_yields_zero_records(tmp_path: Path) -> None:
    """A header-only CSV (zero data rows) must yield zero records and raise nothing."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_EMPTY)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))

    assert records == []


def test_storygraph_missing_csv_raises_file_not_found(tmp_path: Path) -> None:
    """fetch_records(export_csv=<nonexistent path>) must raise FileNotFoundError."""
    plugin = _make_plugin()
    with pytest.raises(FileNotFoundError):
        list(
            plugin.fetch_records(
                export_csv=str(tmp_path / "nonexistent" / "storygraph_library.csv")
            )
        )


# ---------------------------------------------------------------------------
# CLI generic-call compatibility test
# ---------------------------------------------------------------------------


def test_storygraph_fetch_records_no_config_returns_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fetch_records(since=..., progress_cb=...) with no export_csv/config must yield []."""
    # Isolate LocalizerSettings from any real machine config by pointing its config
    # file at a fresh, nonexistent path within tmp_path (LocalizerSettings treats a
    # missing config file as an empty settings dict).
    monkeypatch.setenv("LOCALIZER_CONFIG_PATH", str(tmp_path / "empty_config.toml"))

    plugin = _make_plugin()
    records = list(plugin.fetch_records(since=123, progress_cb=lambda *_: None))

    assert records == [], f"Expected [] with no export_csv configured, got {records}"


# ---------------------------------------------------------------------------
# Config-field / instructions tests
# ---------------------------------------------------------------------------


def test_storygraph_get_config_fields_exactly_one_export_csv_field() -> None:
    """get_config_fields() must return exactly one field dict keyed 'export_csv'."""
    plugin = _make_plugin()
    fields = plugin.get_config_fields()

    assert isinstance(fields, list)
    assert len(fields) == 1, f"Expected exactly 1 config field, got {len(fields)}: {fields}"
    assert fields[0]["key"] == "export_csv", f"field key {fields[0].get('key')!r} != 'export_csv'"
    assert fields[0]["type"] == "file_path", f"field type {fields[0].get('type')!r} != 'file_path'"


def test_storygraph_get_manual_download_instructions_is_actionable() -> None:
    """get_manual_download_instructions() must mention storygraph and csv."""
    plugin = _make_plugin()
    instructions = plugin.get_manual_download_instructions()

    assert isinstance(instructions, str)
    assert len(instructions.strip()) > 0, "Expected non-empty manual download instructions"

    instructions_lower = instructions.lower()
    assert "thestorygraph.com" in instructions_lower or "storygraph" in instructions_lower, (
        f"'thestorygraph.com'/'storygraph' not found in instructions: {instructions!r}"
    )
    assert "csv" in instructions_lower, f"'csv' not found in instructions: {instructions!r}"


def test_storygraph_fetched_at_is_recent(tmp_path: Path) -> None:
    """fetched_at must be a Unix timestamp close to now."""
    csv_path = _write_csv(tmp_path, STORYGRAPH_CSV_MULTI_ROW)

    before = int(time.time())
    plugin = _make_plugin()
    records = list(plugin.fetch_records(export_csv=str(csv_path)))
    after = int(time.time())

    assert records, "Expected at least one record"
    for record in records:
        assert isinstance(record["fetched_at"], int)
        assert before - 5 <= record["fetched_at"] <= after + 5, (
            f"fetched_at {record['fetched_at']} not close to now ({before}-{after})"
        )


# ---------------------------------------------------------------------------
# Zero-coupling test
# ---------------------------------------------------------------------------


def test_storygraph_loader_has_no_network_or_cross_plugin_imports() -> None:
    """The loader module must not import network libs or reference other plugin modules."""
    loader_path = (
        Path(__file__).parent.parent / "src" / "localizer" / "plugins" / "storygraph" / "loader.py"
    )
    assert loader_path.exists(), f"Expected loader module at {loader_path}"
    source = loader_path.read_text(encoding="utf-8")

    forbidden_network_tokens = ["requests", "httpx", "urllib", "playwright", "socket"]
    for token in forbidden_network_tokens:
        assert token not in source, (
            f"Found forbidden network-related token {token!r} in storygraph/loader.py"
        )

    forbidden_plugin_names = [
        "letterboxd",
        "untappd",
        "swarm",
        "feedly",
        "github",
        "google_location",
        "google_timeline",
        "rss",
        "flickr",
    ]
    for name in forbidden_plugin_names:
        assert name not in source, (
            f"Found reference to other plugin module {name!r} in storygraph/loader.py"
        )
