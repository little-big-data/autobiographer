"""Letterboxd source plugin for the localizer package."""

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


@register
class LetterboxdPlugin(SourcePlugin):
    """Fetch Letterboxd film diary entries via CSV export.

    ``FETCH_MODE`` is ``PLAYWRIGHT`` (for automated scraping), but the
    primary path in practice is the CSV export fallback.

    The Letterboxd diary CSV columns are:
    ``Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date``
    """

    PLUGIN_ID = "letterboxd"
    DISPLAY_NAME = "Letterboxd"
    FETCH_MODE = FetchMode.PLAYWRIGHT
    OUTPUT_TABLES = [OutputTable.EVENTS]

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Return config fields required by this plugin.

        Returns:
            List with a single ``csv_path`` file-path field.
        """
        return [
            {
                "key": "csv_path",
                "label": "Letterboxd diary CSV path",
                "type": "file_path",
            }
        ]

    def get_manual_download_instructions(self) -> str:
        """Return instructions for obtaining the Letterboxd diary CSV export.

        Returns:
            Multi-line instruction string.
        """
        return (
            "To export your Letterboxd diary:\n"
            "1. Log in at https://letterboxd.com\n"
            "2. Go to Settings → Import & Export\n"
            "3. Click 'Export your data' to download a ZIP file.\n"
            "4. Extract the ZIP and locate the 'diary.csv' file.\n"
            "5. Point this plugin's 'csv_path' config field at that CSV file.\n"
            "\nThe exported CSV contains your full diary history in chronological order."
        )

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
        csv_path: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized event dicts from a Letterboxd diary CSV export.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional callback invoked with ``(current, total)``
                for progress reporting.
            csv_path: Path to the Letterboxd diary CSV file. When provided,
                the CSV is parsed directly without Playwright.

        Yields:
            Dicts with keys: ``source_id``, ``timestamp``, ``label``,
            ``sublabel``, ``category``, ``raw_json``, ``fetched_at``.

        Raises:
            FileNotFoundError: If ``csv_path`` is provided but does not exist.
        """
        if csv_path is None:
            try:
                from localizer.settings import LocalizerSettings  # noqa: PLC0415

                csv_path = LocalizerSettings().get_setting("csv_path") or None
            except ImportError:
                pass
        if csv_path is not None:
            yield from self._parse_csv(csv_path)
        # else: no path configured, yield nothing

    def _parse_csv(self, csv_path: str) -> Iterator[dict[str, Any]]:
        """Parse a Letterboxd diary CSV export file.

        Args:
            csv_path: Path to the CSV file.

        Yields:
            Normalized event dicts.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Letterboxd diary CSV not found: {csv_path!r}. "
                "Export your diary from letterboxd.com/settings/data/"
            )

        fetched_at = int(time.time())

        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                watched_date_str = row.get("Watched Date", "") or row.get("Date", "")
                timestamp = 0
                if watched_date_str:
                    try:
                        dt = datetime.strptime(watched_date_str.strip(), "%Y-%m-%d")
                        timestamp = int(dt.timestamp())
                    except ValueError:
                        timestamp = fetched_at

                name = row.get("Name", "")
                year = str(row.get("Year", "") or "")

                rating_str = (row.get("Rating", "") or "").strip()
                rating: float | None
                try:
                    rating = float(rating_str) if rating_str else None
                except ValueError:
                    rating = None

                rewatch = (row.get("Rewatch", "") or "").strip() == "Yes"

                raw = dict(row)
                raw["rating"] = rating
                raw["rewatch"] = rewatch

                yield {
                    "source_id": "letterboxd",
                    "timestamp": timestamp,
                    "label": name,
                    "sublabel": name,
                    "category": year,
                    "raw_json": json.dumps(raw),
                    "fetched_at": fetched_at,
                }
