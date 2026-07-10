"""Untappd source plugin for the localizer package."""

from __future__ import annotations

import csv
import json
import time
from collections.abc import Iterator
from datetime import datetime
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


@register
class UntappdPlugin(SourcePlugin):
    """Fetch Untappd beer check-in history via CSV export.

    The Untappd check-in history CSV columns are:
    ``created_at,brewery_name,beer_name,beer_type,rating_score,venue_name,
    venue_lat,venue_lng,comment,flavor_profiles,serving_type,photo_url``.
    """

    PLUGIN_ID = "untappd"
    DISPLAY_NAME = "Untappd"
    FETCH_MODE = FetchMode.MANUAL
    OUTPUT_TABLES = [OutputTable.EVENTS]

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Return config fields required by this plugin.

        Returns:
            List with a single ``checkins_csv`` file-path field.
        """
        return [
            {
                "key": "checkins_csv",
                "label": "Untappd check-in history CSV path",
                "type": "file_path",
            }
        ]

    def get_manual_download_instructions(self) -> str:
        """Return instructions for obtaining the Untappd check-in history CSV.

        Returns:
            Multi-line instruction string.
        """
        return (
            "To export your Untappd check-in history:\n"
            "1. Log in at https://untappd.com\n"
            "2. Go to Settings → Export Data\n"
            "3. Request and download your check-in history as a CSV file.\n"
            "4. Point this plugin's 'checkins_csv' config field at that CSV file.\n"
            "\nThe exported CSV contains your full check-in history."
        )

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
        checkins_csv: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized event dicts from an Untappd check-in history CSV export.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional callback invoked with ``(current, total)``
                for progress reporting.
            checkins_csv: Path to the Untappd check-in history CSV file. When
                not provided, resolved from ``LocalizerSettings``.

        Yields:
            Dicts with keys: ``source_id``, ``timestamp``, ``label``,
            ``sublabel``, ``category``, ``raw_json``, ``fetched_at``.

        Raises:
            FileNotFoundError: If a ``checkins_csv`` path is configured but
                does not exist.
        """
        if checkins_csv is None:
            try:
                from localizer.settings import LocalizerSettings  # noqa: PLC0415

                checkins_csv = LocalizerSettings().get_setting("checkins_csv") or None
            except ImportError:
                pass
        if checkins_csv is not None:
            yield from self._parse_csv(checkins_csv, since)
        # else: no path configured, yield nothing

    def _parse_csv(self, checkins_csv: str, since: int | None) -> Iterator[dict[str, Any]]:
        """Parse an Untappd check-in history CSV export file.

        Args:
            checkins_csv: Path to the CSV file.
            since: Optional Unix timestamp; yield only records newer than this.

        Yields:
            Normalized event dicts.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        path = Path(checkins_csv)
        if not path.exists():
            raise FileNotFoundError(
                f"Untappd check-in history CSV not found: {checkins_csv!r}. "
                "Export your data from untappd.com/settings and select "
                "'Export Data' to download a CSV file."
            )

        fetched_at = int(time.time())

        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                created_at_str = (row.get("created_at", "") or "").strip()
                timestamp = fetched_at
                if created_at_str:
                    try:
                        dt = datetime.fromisoformat(created_at_str.replace(" ", "T"))
                        timestamp = int(dt.timestamp())
                    except ValueError:
                        timestamp = fetched_at

                if since is not None and timestamp <= since:
                    continue

                label = row.get("brewery_name", "") or ""
                sublabel = row.get("beer_name", "") or ""
                category = row.get("beer_type", "") or ""

                rating = _parse_optional_float(row.get("rating_score"))
                venue_name = row.get("venue_name", "") or ""
                venue_lat = _parse_optional_float(row.get("venue_lat"))
                venue_lng = _parse_optional_float(row.get("venue_lng"))

                raw = dict(row)
                raw["rating"] = rating
                raw["venue_name"] = venue_name
                raw["venue_lat"] = venue_lat
                raw["venue_lng"] = venue_lng

                yield {
                    "source_id": "untappd",
                    "timestamp": timestamp,
                    "label": label,
                    "sublabel": sublabel,
                    "category": category,
                    "raw_json": json.dumps(raw),
                    "fetched_at": fetched_at,
                }
