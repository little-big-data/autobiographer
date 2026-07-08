"""Google Maps Timeline source plugin for localizer.

FetchMode.MANUAL — the user must export a ``Timeline.json`` file from their
device or Google Takeout and point the plugin at it. Wraps
``localizer.plugins.google_timeline.parser.load_google_timeline()`` (the
existing parser, already tested in ``tests/test_google_timeline_parser.py``)
and yields ``OutputTable.PLACES`` records using that parser's
``venue``/``venue_category`` values verbatim as ``place_name``/``place_type``
— no new parsing or mapping logic is invented here (mirrors
``plugins/sources/google_timeline/loader.py`` lines 76-80).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin


@register
class GoogleTimelinePlugin(SourcePlugin):
    """Load Google Maps Timeline location history from a local Timeline.json export.

    Args:
        timeline_path: Path to the exported ``Timeline.json`` file. If None,
            falls back to ``LocalizerSettings().get_setting("google_timeline_path")``.
            The plugin yields nothing until a valid path is available.
    """

    PLUGIN_ID = "google_timeline"
    DISPLAY_NAME = "Google Maps Timeline"
    FETCH_MODE = FetchMode.MANUAL
    OUTPUT_TABLES = [OutputTable.PLACES]
    ICON = ":material/map:"

    def __init__(self, timeline_path: str | None = None) -> None:
        if timeline_path is None:
            try:
                from localizer.settings import LocalizerSettings  # noqa: PLC0415

                timeline_path = LocalizerSettings().get_setting("google_timeline_path") or None
            except ImportError:
                pass
        self._timeline_path = timeline_path

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Declare sidebar config fields for the Google Timeline plugin.

        Returns:
            List containing a single file-path field for the Timeline.json export.
        """
        return [
            {
                "key": "google_timeline_path",
                "label": "Google Timeline JSON file",
                "type": "file_path",
                "file_types": [("Google Timeline JSON", "*.json"), ("All files", "*.*")],
            }
        ]

    def get_manual_download_instructions(self) -> str:
        """Return instructions for exporting Google Maps Timeline data.

        Returns:
            Multi-line instruction string covering the on-device export and Takeout.
        """
        return (
            "Google Maps Timeline data is stored on your device and must be exported "
            "manually.\n\n"
            "Option A — export from your phone (recommended, gives the new format):\n"
            "  1. Open Settings on your Android phone\n"
            "  2. Go to Location -> Location Services -> Timeline\n"
            "  3. Tap 'Export Timeline data' and save the file\n"
            "  4. Copy the exported Timeline.json to your computer\n\n"
            "Option B — Google Takeout:\n"
            "  1. Visit https://takeout.google.com\n"
            "  2. Deselect all, then select only 'Location History (Timeline)'\n"
            "  3. Create the export and download the archive\n"
            "  4. Unzip it and locate the Timeline.json file\n\n"
            "Then point the 'Google Timeline JSON file' setting at the exported "
            "Timeline.json."
        )

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized place dicts from a Google Timeline JSON export.

        Reads and parses ``Timeline.json`` via
        ``localizer.plugins.google_timeline.parser.load_google_timeline()``,
        then yields one dict per visit/activity segment. Missing
        configuration or a nonexistent file
        yields nothing gracefully (the parser already returns an empty
        DataFrame in that case). An unsupported/legacy-format file causes the
        parser's ``ValueError`` to be translated to ``OSError`` so the
        localizer CLI's ``sync`` command can skip this plugin without killing
        the whole run.

        Args:
            since: Optional Unix timestamp; yield only segments newer than this.
            progress_cb: Optional progress callback (unused for manual plugins).

        Yields:
            Dicts with keys: source_id, timestamp, lat, lng, place_name,
            place_type, raw_json, fetched_at.

        Raises:
            OSError: If the configured file exists but is not a supported
                Timeline.json export (e.g. a legacy Records.json export).
        """
        if not self._timeline_path:
            return

        from localizer.plugins.google_timeline.parser import (  # noqa: PLC0415
            load_google_timeline,
        )

        try:
            df = load_google_timeline(self._timeline_path)
        except ValueError as exc:
            raise OSError(
                f"Failed to parse Google Timeline export at {self._timeline_path}: {exc}"
            ) from exc

        if df.empty:
            return

        fetched_at = int(time.time())

        for _, row in df.iterrows():
            timestamp = int(row["timestamp"])
            if since is not None and timestamp <= since:
                continue

            lat = float(row["lat"])
            lng = float(row["lng"])
            place_name = str(row["venue"])
            place_type = str(row["venue_category"])

            raw_json = {
                "timestamp": timestamp,
                "offset": int(row["offset"]),
                "city": str(row["city"]),
                "state": str(row["state"]),
                "country": str(row["country"]),
                "venue": place_name,
                "venue_category": place_type,
                "lat": lat,
                "lng": lng,
                "event_category": str(row["event_category"]),
                "shout": str(row["shout"]),
            }

            yield {
                "source_id": self.PLUGIN_ID,
                "timestamp": timestamp,
                "lat": lat,
                "lng": lng,
                "place_name": place_name,
                "place_type": place_type,
                "raw_json": raw_json,
                "fetched_at": fetched_at,
            }
