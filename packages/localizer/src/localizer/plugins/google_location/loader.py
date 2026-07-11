"""Google Location History (Takeout) source plugin for localizer.

FetchMode.MANUAL — the user must export their data from Google Takeout and
point the plugin at the unzipped "Location History" directory. Handles both
legacy Takeout formats via ``localizer.plugins.google_location.parser``:
``Records.json`` (raw GPS pings) and ``Semantic Location History/<Year>/
<Year>_<MONTH>.json`` (place visits and activity segments).

Distinct from ``localizer.plugins.google_timeline``, which handles the
current on-device single-file ``Timeline.json`` export.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin


@register
class GoogleLocationPlugin(SourcePlugin):
    """Load Google Location History from a local Google Takeout export directory.

    Args:
        google_location_dir: Path to the exported "Location History"
            directory. If None, falls back to
            ``LocalizerSettings().get_setting("google_location_dir")``. The
            plugin yields nothing until a valid directory is available.
    """

    PLUGIN_ID = "google_location"
    DISPLAY_NAME = "Google Location History"
    FETCH_MODE = FetchMode.MANUAL
    OUTPUT_TABLES = [OutputTable.PLACES]
    ICON = ":material/my_location:"

    def __init__(self, google_location_dir: str | None = None) -> None:
        if google_location_dir is None:
            try:
                from localizer.settings import LocalizerSettings  # noqa: PLC0415

                google_location_dir = LocalizerSettings().get_setting("google_location_dir") or None
            except ImportError:
                pass
        self._dir = google_location_dir

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Declare sidebar config fields for the Google Location History plugin.

        Returns:
            List with one field descriptor for the Takeout export directory.
        """
        return [
            {
                "key": "google_location_dir",
                "label": "Google Location History export directory",
                "type": "dir_path",
            }
        ]

    def get_manual_download_instructions(self) -> str:
        """Return instructions for exporting Google Location History via Takeout.

        Returns:
            Multi-line instruction string covering the Takeout export.
        """
        return (
            "Google Location History (legacy formats) is exported via Google Takeout:\n\n"
            "  1. Visit https://takeout.google.com\n"
            "  2. Deselect all, then select only 'Location History (Timeline)'\n"
            "  3. Create the export and download the archive\n"
            "  4. Unzip it and locate the 'Location History' folder — it may contain\n"
            "     a 'Records.json' file and/or a 'Semantic Location History' subfolder\n"
            "     of yearly folders with monthly JSON files\n\n"
            "Then point the 'Google Location History export directory' setting at that "
            "'Location History' folder (not an individual file).\n\n"
            "Note: if your export instead contains a single 'Timeline.json' file, use "
            "the 'Google Maps Timeline' source instead — that is the newer on-device "
            "export format."
        )

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized place dicts from a Google Takeout Location History export.

        Streams ``Records.json`` (if present) and every
        ``Semantic Location History/<Year>/<Year>_<MONTH>.json`` file (if
        present) one record at a time, so memory use stays bounded even for
        multi-year exports with millions of GPS pings — each source file is
        read and parsed in turn, and this generator is consumed by the
        localizer CLI in fixed-size batches (see ``cli.py``'s ``_BATCH_SIZE``
        write loop), rather than materializing the whole export in memory.
        Missing configuration, a nonexistent directory, or a directory with
        neither expected format yields nothing gracefully. Malformed
        individual files are skipped rather than aborting the whole fetch.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional progress callback (unused for manual plugins).

        Yields:
            Dicts with keys: source_id, timestamp, lat, lng, place_name,
            place_type, raw_json, fetched_at.
        """
        if not self._dir:
            return

        base_dir = Path(self._dir)
        if not base_dir.exists() or not base_dir.is_dir():
            return

        from localizer.plugins.google_location.parser import (  # noqa: PLC0415
            parse_records_json,
            parse_semantic_location_history,
        )

        fetched_at = int(time.time())

        def _to_output(record: dict[str, Any]) -> dict[str, Any]:
            return {
                "source_id": self.PLUGIN_ID,
                "timestamp": record["timestamp"],
                "lat": float(record["lat"]),
                "lng": float(record["lng"]),
                "place_name": record["place_name"],
                "place_type": record["place_type"],
                "raw_json": record["raw"],
                "fetched_at": fetched_at,
            }

        records_json = base_dir / "Records.json"
        if records_json.exists():
            for record in parse_records_json(records_json):
                if since is not None and record["timestamp"] <= since:
                    continue
                yield _to_output(record)

        semantic_dir = base_dir / "Semantic Location History"
        if semantic_dir.exists() and semantic_dir.is_dir():
            for year_dir in sorted(p for p in semantic_dir.iterdir() if p.is_dir()):
                for month_file in sorted(year_dir.glob("*.json")):
                    for record in parse_semantic_location_history(month_file):
                        if since is not None and record["timestamp"] <= since:
                            continue
                        yield _to_output(record)
