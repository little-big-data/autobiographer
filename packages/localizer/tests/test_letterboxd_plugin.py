"""Failing tests for Subtask 6: LetterboxdPlugin in the localizer package.

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/letterboxd/__init__.py
  - packages/localizer/src/localizer/plugins/letterboxd/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py (load_builtin_plugins)

LetterboxdPlugin is FetchMode.PLAYWRIGHT with a CSV export fallback.
The CSV format is the official Letterboxd diary export:
  Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal Letterboxd diary CSV content
# ---------------------------------------------------------------------------

LETTERBOXD_CSV_HEADER = "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date"

LETTERBOXD_CSV_TWO_ROWS = """\
Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date
2023-11-14,The Godfather,1972,https://letterboxd.com/film/the-godfather/,4.5,,crime,2023-11-14
2023-11-15,Pulp Fiction,1994,https://letterboxd.com/film/pulp-fiction/,5.0,,crime,2023-11-15
"""

LETTERBOXD_CSV_ONE_ROW_NO_RATING = """\
Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date
2023-11-16,Amélie,2001,https://letterboxd.com/film/amelie/,,,romance,2023-11-16
"""


def _make_plugin() -> Any:
    """Instantiate a LetterboxdPlugin."""
    from localizer.plugins.letterboxd.loader import LetterboxdPlugin

    return LetterboxdPlugin()


def _write_csv(tmp_path: Path, content: str, filename: str = "diary.csv") -> Path:
    """Write CSV content to a temp file and return the path."""
    csv_path = tmp_path / filename
    csv_path.write_text(content, encoding="utf-8")
    return csv_path


# ---------------------------------------------------------------------------
# ABC / class attribute tests
# ---------------------------------------------------------------------------


def test_letterboxd_plugin_id() -> None:
    """LetterboxdPlugin.PLUGIN_ID must equal 'letterboxd'."""
    from localizer.plugins.letterboxd.loader import LetterboxdPlugin

    assert LetterboxdPlugin.PLUGIN_ID == "letterboxd"


def test_letterboxd_fetch_mode() -> None:
    """LetterboxdPlugin.FETCH_MODE must be FetchMode.PLAYWRIGHT."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.letterboxd.loader import LetterboxdPlugin

    assert LetterboxdPlugin.FETCH_MODE == FetchMode.PLAYWRIGHT


def test_letterboxd_output_tables() -> None:
    """OutputTable.EVENTS must be in LetterboxdPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.letterboxd.loader import LetterboxdPlugin

    assert OutputTable.EVENTS in LetterboxdPlugin.OUTPUT_TABLES


def test_letterboxd_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['letterboxd'] must exist."""
    from localizer.plugins import REGISTRY, load_builtin_plugins

    REGISTRY.clear()
    load_builtin_plugins()
    assert "letterboxd" in REGISTRY, f"'letterboxd' not in REGISTRY; keys: {list(REGISTRY)}"


# ---------------------------------------------------------------------------
# CSV parsing tests
# ---------------------------------------------------------------------------


def test_letterboxd_fetch_records_from_csv(tmp_path: Path) -> None:
    """fetch_records(csv_path=...) must yield 2 correctly normalized dicts from the CSV."""
    required_keys = {
        "source_id",
        "timestamp",
        "label",
        "sublabel",
        "category",
        "raw_json",
        "fetched_at",
    }
    csv_path = _write_csv(tmp_path, LETTERBOXD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(csv_path=str(csv_path)))

    assert len(records) == 2, f"Expected 2 records, got {len(records)}"
    for record in records:
        missing = required_keys - set(record.keys())
        assert not missing, f"Record missing required keys: {missing}"
        assert record["source_id"] == "letterboxd"


def test_letterboxd_timestamp_is_int(tmp_path: Path) -> None:
    """timestamp must be a Python int (Unix seconds from the Watched Date column)."""
    csv_path = _write_csv(tmp_path, LETTERBOXD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(csv_path=str(csv_path)))

    for record in records:
        assert isinstance(record["timestamp"], int), (
            f"timestamp is {type(record['timestamp'])}, expected int"
        )
        assert record["timestamp"] > 0, "Expected positive Unix timestamp"


def test_letterboxd_label_is_film_name(tmp_path: Path) -> None:
    """label must be the film name from the CSV 'Name' column."""
    csv_path = _write_csv(tmp_path, LETTERBOXD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(csv_path=str(csv_path)))

    labels = {r["label"] for r in records}
    assert "The Godfather" in labels, f"'The Godfather' not in labels: {labels}"
    assert "Pulp Fiction" in labels, f"'Pulp Fiction' not in labels: {labels}"


def test_letterboxd_sublabel_is_year_string(tmp_path: Path) -> None:
    """sublabel must be the film year as a string from the CSV 'Year' column."""
    csv_path = _write_csv(tmp_path, LETTERBOXD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(csv_path=str(csv_path)))

    # Both films should have their year as sublabel
    sublabels = {r["sublabel"] for r in records}
    assert "1972" in sublabels, f"'1972' not in sublabels: {sublabels}"
    assert "1994" in sublabels, f"'1994' not in sublabels: {sublabels}"


def test_letterboxd_category_is_rating(tmp_path: Path) -> None:
    """category must be the rating string from the CSV 'Rating' column."""
    csv_path = _write_csv(tmp_path, LETTERBOXD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(csv_path=str(csv_path)))

    # Verify rating values are preserved as strings
    godfather = next(r for r in records if r["label"] == "The Godfather")
    assert godfather["category"] == "4.5", f"category {godfather['category']!r} != '4.5'"


def test_letterboxd_missing_csv_raises(tmp_path: Path) -> None:
    """fetch_records(csv_path='/nonexistent/path.csv') must raise FileNotFoundError."""
    plugin = _make_plugin()
    with pytest.raises(FileNotFoundError):
        list(plugin.fetch_records(csv_path=str(tmp_path / "nonexistent" / "diary.csv")))


def test_letterboxd_fetched_at_is_recent(tmp_path: Path) -> None:
    """fetched_at must be a Unix timestamp close to now."""
    csv_path = _write_csv(tmp_path, LETTERBOXD_CSV_TWO_ROWS)

    before = int(time.time())
    plugin = _make_plugin()
    records = list(plugin.fetch_records(csv_path=str(csv_path)))
    after = int(time.time())

    for record in records:
        assert isinstance(record["fetched_at"], int)
        assert before - 5 <= record["fetched_at"] <= after + 5, (
            f"fetched_at {record['fetched_at']} not close to now ({before}–{after})"
        )


def test_letterboxd_get_manual_download_instructions_is_actionable() -> None:
    """get_manual_download_instructions() must mention 'letterboxd.com' and 'csv'."""
    plugin = _make_plugin()
    instructions = plugin.get_manual_download_instructions()

    assert isinstance(instructions, str)
    assert len(instructions.strip()) > 0, "Expected non-empty manual download instructions"

    instructions_lower = instructions.lower()
    assert "letterboxd.com" in instructions_lower, (
        f"'letterboxd.com' not found in instructions: {instructions!r}"
    )
    assert "csv" in instructions_lower, f"'csv' not found in instructions: {instructions!r}"


def test_letterboxd_no_rating_does_not_raise(tmp_path: Path) -> None:
    """A CSV row with no rating must not raise — category can be empty string or None."""
    csv_path = _write_csv(tmp_path, LETTERBOXD_CSV_ONE_ROW_NO_RATING)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(csv_path=str(csv_path)))

    assert len(records) == 1
    # category should be an empty string or None — not an error
    assert "category" in records[0]


def test_letterboxd_source_id_is_letterboxd(tmp_path: Path) -> None:
    """source_id in each record must equal 'letterboxd'."""
    csv_path = _write_csv(tmp_path, LETTERBOXD_CSV_TWO_ROWS)

    plugin = _make_plugin()
    records = list(plugin.fetch_records(csv_path=str(csv_path)))

    for record in records:
        assert record["source_id"] == "letterboxd", (
            f"source_id {record['source_id']!r} != 'letterboxd'"
        )


def test_letterboxd_get_config_fields_returns_list() -> None:
    """get_config_fields() must return a list."""
    plugin = _make_plugin()
    result = plugin.get_config_fields()
    assert isinstance(result, list)
