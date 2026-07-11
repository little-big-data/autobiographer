"""Flickr source plugin for localizer.

FetchMode.MANUAL — the user must export their data from Flickr and point the
plugin at the resulting directory of ``photo_*.json`` files.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin

_FALSY_STRINGS = {"false", "0", "", "no"}


def _coerce_bool(value: Any) -> bool:
    """Coerce a settings-layer value (bool or string) to a real bool.

    Args:
        value: Either an actual ``bool`` or a string round-tripped through
            the settings layer (e.g. ``"false"``, ``"0"``, ``"no"``).

    Returns:
        ``False`` when ``value`` is a string matching (case-insensitively)
        one of ``"false"``/``"0"``/``""``/``"no"``; ``True`` otherwise.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in _FALSY_STRINGS
    return bool(value)


@register
class FlickrPlugin(SourcePlugin):
    """Load Flickr photo history from a local JSON export directory.

    Args:
        export_dir: Path to the directory containing ``photo_*.json`` export
            files. If None, resolved from ``LocalizerSettings``.
        geotagged_only: When True (the default), photos without valid
            latitude/longitude are skipped. When False, they are yielded
            with NaN lat/lng. If None, resolved from ``LocalizerSettings``.
    """

    PLUGIN_ID = "flickr"
    DISPLAY_NAME = "Flickr Photos"
    FETCH_MODE = FetchMode.MANUAL
    OUTPUT_TABLES = [OutputTable.PLACES, OutputTable.EVENTS]
    ICON = ":material/photo_camera:"

    def __init__(
        self,
        export_dir: str | None = None,
        geotagged_only: bool | None = None,
    ) -> None:
        if export_dir is None:
            try:
                from localizer.settings import LocalizerSettings  # noqa: PLC0415

                export_dir = LocalizerSettings().get_setting("export_dir") or None
            except ImportError:
                pass
        self._export_dir = export_dir

        if geotagged_only is None:
            try:
                from localizer.settings import LocalizerSettings  # noqa: PLC0415

                geotagged_only = LocalizerSettings().get_setting("geotagged_only", True)
            except ImportError:
                geotagged_only = True
        self._geotagged_only = _coerce_bool(geotagged_only)

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Declare sidebar config fields for the Flickr plugin.

        Returns:
            List with the export directory path field and the
            geotagged-only boolean toggle field.
        """
        return [
            {
                "key": "export_dir",
                "label": "Flickr export directory",
                "type": "dir_path",
            },
            {
                "key": "geotagged_only",
                "label": "Only include geotagged photos",
                "type": "bool",
                "default": True,
            },
        ]

    def get_manual_download_instructions(self) -> str:
        """Return instructions for exporting photo data from Flickr.

        Returns:
            Multi-line instruction string with export steps.
        """
        return (
            "To export your Flickr photo data:\n"
            "1. Log in at https://www.flickr.com\n"
            "2. Go to Account Settings → Your Flickr Data\n"
            "3. Request a full data export and wait for the download email.\n"
            "4. Download and unzip the archive.\n"
            "5. Point the 'Flickr export directory' setting at the unzipped\n"
            "   folder containing the 'photo_*.json' files.\n"
        )

    def _iter_photo_records(self, since: int | None) -> Iterator[tuple[dict[str, Any], int, int]]:
        """Glob, parse, and timestamp every ``photo_*.json`` export file once.

        Shared by :meth:`fetch_records` (PLACES output) and
        :meth:`fetch_secondary_records` (EVENTS output) so the file-reading,
        malformed-file skipping, and ``date_taken`` parsing logic lives in
        exactly one place.

        Args:
            since: Optional Unix timestamp; only photos newer than this are
                yielded.

        Yields:
            Tuples of ``(data, timestamp, fetched_at)`` for every valid,
            since-filtered photo — geotagged or not.
        """
        if not self._export_dir:
            return

        export_path = Path(self._export_dir)
        if not export_path.exists() or not export_path.is_dir():
            return

        fetched_at = int(time.time())

        for json_file in sorted(export_path.glob("photo_*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            if not isinstance(data, dict):
                continue

            date_taken = data.get("date_taken")
            timestamp = fetched_at
            if date_taken:
                try:
                    timestamp = int(
                        datetime.fromisoformat(str(date_taken).replace(" ", "T")).timestamp()
                    )
                except (ValueError, AttributeError):
                    timestamp = fetched_at

            if since is not None and timestamp <= since:
                continue

            yield data, timestamp, fetched_at

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized place dicts from Flickr JSON export files.

        Reads all ``photo_*.json`` files in ``export_dir`` and yields one
        record per geotagged photo (or every photo, with NaN lat/lng, when
        ``geotagged_only`` is False). Missing or non-existent directories
        yield nothing gracefully; a malformed file is skipped without
        aborting the rest.

        Args:
            since: Optional Unix timestamp; yield only photos newer than this.
            progress_cb: Optional progress callback (unused for manual plugins).

        Yields:
            Dicts with keys: source_id, timestamp, lat, lng, place_name,
            place_type, raw_json, fetched_at.
        """
        for data, timestamp, fetched_at in self._iter_photo_records(since):
            geo = data.get("geo")
            geotagged = False
            lat = float("nan")
            lng = float("nan")
            if isinstance(geo, dict) and geo:
                try:
                    lat = float(geo["latitude"])
                    lng = float(geo["longitude"])
                    geotagged = True
                except (KeyError, TypeError, ValueError):
                    geotagged = False

            if not geotagged and self._geotagged_only:
                continue

            yield {
                "source_id": "flickr",
                "timestamp": timestamp,
                "lat": lat,
                "lng": lng,
                "place_name": data.get("name") or "",
                "place_type": "photo",
                "raw_json": data,
                "fetched_at": fetched_at,
            }

    def fetch_secondary_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield every photo as a timeline event, geotagged or not.

        A photograph is fundamentally an event too — a moment in time with a
        shareable URL, independent of whether it happened to carry GPS
        coordinates. Unlike :meth:`fetch_records`, this is never filtered by
        ``geotagged_only``: every photo in the export directory becomes one
        event record, so photos dropped from the PLACES pipeline are still
        visible via the EVENTS pipeline (e.g. the Photograph History page).

        Args:
            since: Optional Unix timestamp; yield only photos newer than this.
            progress_cb: Optional progress callback (unused for manual plugins).

        Yields:
            Dicts with keys: source_id, timestamp, label, sublabel, category,
            raw_json, fetched_at. ``label`` is the photo title, ``sublabel``
            is its first album (if any). ``raw_json`` preserves the full
            export record, including ``tags``, ``albums``, and ``photopage``.
        """
        for data, timestamp, fetched_at in self._iter_photo_records(since):
            albums = data.get("albums")
            sublabel = albums[0] if isinstance(albums, list) and albums else ""

            yield {
                "source_id": "flickr",
                "timestamp": timestamp,
                "label": data.get("name") or "",
                "sublabel": sublabel,
                "category": "photo",
                "raw_json": data,
                "fetched_at": fetched_at,
            }
