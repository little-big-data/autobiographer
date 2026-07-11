"""StoryGraph source plugin for the localizer package."""

from __future__ import annotations

import csv
import json
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin


def _parse_optional_float(value: str | None) -> float | None:
    """Parse a string to a float, returning None when blank/unparseable.

    Args:
        value: Raw string value from a CSV cell (may be None or empty).

    Returns:
        The parsed float, or None when the value is blank or not a valid
        float (never raises, never returns NaN).
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _parse_optional_int(value: str | None) -> int | None:
    """Parse a string to an int, returning None when blank/unparseable.

    Args:
        value: Raw string value from a CSV cell (may be None or empty).

    Returns:
        The parsed int, or None when the value is blank or not a valid
        int (never raises).
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(float(stripped))
    except ValueError:
        return None


@register
class StoryGraphPlugin(SourcePlugin):
    """Fetch StoryGraph reading history via CSV export.

    The StoryGraph library export CSV columns include:
    ``Title,Authors,Read Status,Date Read,Star Rating,Number of Pages,
    Pace,Genres,Moods,Format``.
    """

    PLUGIN_ID = "storygraph"
    DISPLAY_NAME = "StoryGraph"
    FETCH_MODE = FetchMode.MANUAL
    OUTPUT_TABLES = [OutputTable.EVENTS]

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Return config fields required by this plugin.

        Returns:
            List with a single ``export_csv`` file-path field.
        """
        return [
            {
                "key": "export_csv",
                "label": "StoryGraph library export CSV path",
                "type": "file_path",
            }
        ]

    def get_manual_download_instructions(self) -> str:
        """Return instructions for obtaining the StoryGraph library CSV export.

        Returns:
            Multi-line instruction string.
        """
        return (
            "To export your StoryGraph reading history:\n"
            "1. Log in at https://app.thestorygraph.com\n"
            "2. Go to Manage Account → Manage Your Data.\n"
            "3. Click 'Export StoryGraph Library' to download a CSV file.\n"
            "4. Point this plugin's 'export_csv' config field at that CSV file.\n"
            "\nThe exported CSV contains your full reading history."
        )

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
        export_csv: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized event dicts from a StoryGraph library CSV export.

        Args:
            since: Optional Unix timestamp; accepted for interface
                compatibility with the generic CLI sync call, unused.
            progress_cb: Optional callback; accepted for interface
                compatibility with the generic CLI sync call, unused.
            export_csv: Path to the StoryGraph library export CSV file. When
                not provided, resolved from ``LocalizerSettings``.

        Yields:
            Dicts with keys: ``source_id``, ``timestamp``, ``label``,
            ``sublabel``, ``category``, ``raw_json``, ``fetched_at``.

        Raises:
            FileNotFoundError: If an ``export_csv`` path is configured but
                does not exist.
        """
        if export_csv is None:
            try:
                from localizer.settings import LocalizerSettings  # noqa: PLC0415

                export_csv = LocalizerSettings().get_setting("export_csv") or None
            except ImportError:
                pass
        if export_csv is not None:
            yield from self._parse_csv(export_csv)
        # else: no path configured, yield nothing

    def _parse_csv(self, export_csv: str) -> Iterator[dict[str, Any]]:
        """Parse a StoryGraph library CSV export file.

        Args:
            export_csv: Path to the CSV file.

        Yields:
            Normalized event dicts.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        path = Path(export_csv)
        if not path.exists():
            raise FileNotFoundError(
                f"StoryGraph library CSV not found: {export_csv!r}. "
                "Export your library from app.thestorygraph.com under "
                "Manage Account → Manage Your Data → 'Export StoryGraph Library'."
            )

        fetched_at = int(time.time())

        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                # Case-sensitive exact match is intentional per issue #18 —
                # not an oversight to "fix" by case-folding later.
                if row.get("Read Status") != "read":
                    continue

                date_read_str = (row.get("Date Read") or "").strip()
                if not date_read_str:
                    continue

                try:
                    dt = datetime.strptime(date_read_str, "%Y/%m/%d")
                except ValueError:
                    dt = datetime.strptime(date_read_str, "%m/%d/%Y")

                # Deliberate deviation from Letterboxd/Untappd's local-tz
                # `.timestamp()` idiom: StoryGraph's Date Read has no time
                # component, so it is interpreted at UTC midnight explicitly.
                timestamp = int(dt.replace(tzinfo=timezone.utc).timestamp())

                label = row.get("Authors", "") or ""
                sublabel = row.get("Title", "") or ""

                raw = dict(row)
                raw["rating"] = _parse_optional_float(row.get("Star Rating"))
                raw["pages"] = _parse_optional_int(row.get("Number of Pages"))
                raw["pace"] = row.get("Pace", "")
                raw["genres"] = row.get("Genres", "")
                raw["moods"] = row.get("Moods", "")
                raw["format"] = row.get("Format", "")

                yield {
                    "source_id": "storygraph",
                    "timestamp": timestamp,
                    "label": label,
                    "sublabel": sublabel,
                    "category": "book",
                    "raw_json": json.dumps(raw),
                    "fetched_at": fetched_at,
                }
