"""Runkeeper source plugin for the localizer package."""

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

_EXPORT_FILENAME = "cardioActivities.csv"


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


def _parse_duration_to_seconds(value: str | None) -> int | None:
    """Convert an ``HH:MM:SS`` (or ``MM:SS``/``SS``) duration string to seconds.

    Args:
        value: Raw ``Duration`` CSV cell, e.g. ``"00:32:15"``.

    Returns:
        Total seconds as an int, or None when blank/malformed (never raises).
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None

    parts = stripped.split(":")
    try:
        numeric_parts = [int(part) for part in parts]
    except ValueError:
        return None

    if len(numeric_parts) == 3:
        hours, minutes, seconds = numeric_parts
    elif len(numeric_parts) == 2:
        hours = 0
        minutes, seconds = numeric_parts
    elif len(numeric_parts) == 1:
        hours, minutes = 0, 0
        seconds = numeric_parts[0]
    else:
        return None

    return hours * 3600 + minutes * 60 + seconds


@register
class RunkeeperPlugin(SourcePlugin):
    """Load Runkeeper activity history from a local ``cardioActivities.csv`` export.

    ``FETCH_MODE`` is ``MANUAL`` — the user must export their data from
    Runkeeper (Settings -> Export Data) and point this plugin's
    ``export_dir`` config field at the unzipped export directory. The
    export also contains individual per-activity ``.gpx`` files, which this
    plugin never reads; only the ``cardioActivities.csv`` summary is parsed.

    The Runkeeper ``cardioActivities.csv`` columns are:
    ``Date,Type,Route Name,Distance (km),Duration,Average Pace,
    Average Speed (km/h),Calories Burned,Average Heart Rate (bpm),Notes,
    GPX File``.
    """

    PLUGIN_ID = "runkeeper"
    DISPLAY_NAME = "Runkeeper"
    FETCH_MODE = FetchMode.MANUAL
    OUTPUT_TABLES = [OutputTable.EVENTS]

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Return config fields required by this plugin.

        Returns:
            List with a single ``export_dir`` directory-path field.
        """
        return [
            {
                "key": "export_dir",
                "label": "Runkeeper export directory",
                "type": "dir_path",
            }
        ]

    def get_manual_download_instructions(self) -> str:
        """Return instructions for obtaining the Runkeeper data export.

        Returns:
            Multi-line instruction string.
        """
        return (
            "To export your Runkeeper activity history:\n"
            "1. Log in at https://runkeeper.com\n"
            "2. Go to Settings -> Export Data.\n"
            "3. Click 'Export Data' to download a ZIP file immediately.\n"
            "4. Extract the ZIP; it contains 'cardioActivities.csv' plus a\n"
            "   '.gpx' file per activity (the GPX files are not used here).\n"
            "5. Point this plugin's 'export_dir' config field at the\n"
            "   extracted folder containing 'cardioActivities.csv'.\n"
        )

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
        export_dir: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized event dicts from a Runkeeper export directory.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional callback invoked with ``(current, total)``
                for progress reporting.
            export_dir: Path to the unzipped Runkeeper export directory
                containing ``cardioActivities.csv``. When not provided,
                resolved from ``LocalizerSettings``.

        Yields:
            Dicts with keys: ``source_id``, ``timestamp``, ``label``,
            ``sublabel``, ``category``, ``raw_json``, ``fetched_at``.

        Raises:
            FileNotFoundError: If ``export_dir`` is configured but does not
                contain a ``cardioActivities.csv`` file.
        """
        if export_dir is None:
            try:
                from localizer.settings import LocalizerSettings  # noqa: PLC0415

                export_dir = LocalizerSettings().get_setting("export_dir") or None
            except ImportError:
                pass
        if export_dir is not None:
            yield from self._parse_export(export_dir, since)
        # else: no export directory configured, yield nothing

    def _parse_export(self, export_dir: str, since: int | None) -> Iterator[dict[str, Any]]:
        """Parse the ``cardioActivities.csv`` summary in a Runkeeper export directory.

        Args:
            export_dir: Path to the export directory.
            since: Optional Unix timestamp; yield only records newer than this.

        Yields:
            Normalized event dicts.

        Raises:
            FileNotFoundError: If ``cardioActivities.csv`` does not exist
                inside ``export_dir``.
        """
        csv_path = Path(export_dir) / _EXPORT_FILENAME
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Runkeeper 'cardioActivities.csv' not found in export dir: {export_dir!r}. "
                "Export your data from runkeeper.com/settings and select 'Export Data' "
                "to download and unzip an export containing cardioActivities.csv."
            )

        fetched_at = int(time.time())

        with csv_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                date_str = (row.get("Date", "") or "").strip()
                timestamp = fetched_at
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace(" ", "T"))
                        timestamp = int(dt.timestamp())
                    except ValueError:
                        timestamp = fetched_at

                if since is not None and timestamp <= since:
                    continue

                activity_type = row.get("Type", "") or ""
                route_name = row.get("Route Name", "") or ""
                label = route_name if route_name else activity_type

                raw = dict(row)
                raw["distance_km"] = _parse_optional_float(row.get("Distance (km)"))
                raw["duration_s"] = _parse_duration_to_seconds(row.get("Duration"))
                raw["avg_hr"] = _parse_optional_float(row.get("Average Heart Rate (bpm)"))
                raw["gpx_file"] = row.get("GPX File", "") or ""

                yield {
                    "source_id": "runkeeper",
                    "timestamp": timestamp,
                    "label": label,
                    "sublabel": activity_type,
                    "category": "fitness",
                    "raw_json": json.dumps(raw),
                    "fetched_at": fetched_at,
                }
