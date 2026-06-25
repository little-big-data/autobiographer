"""Swarm/Foursquare source plugin for localizer.

FetchMode.MANUAL — the user must export their data from the Swarm app and
point the plugin at the resulting JSON directory.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin


@register
class SwarmPlugin(SourcePlugin):
    """Load Foursquare/Swarm check-in history from a local JSON export directory.

    Args:
        swarm_dir: Path to the directory containing Swarm JSON export files.
            If None, the plugin yields nothing until a directory is supplied.
    """

    PLUGIN_ID = "swarm"
    DISPLAY_NAME = "Foursquare / Swarm Check-ins"
    FETCH_MODE = FetchMode.MANUAL
    OUTPUT_TABLES = [OutputTable.PLACES]
    ICON = ":material/location_on:"

    def __init__(self, swarm_dir: str | None = None) -> None:
        if swarm_dir is None:
            try:
                from localizer.settings import LocalizerSettings  # noqa: PLC0415

                swarm_dir = LocalizerSettings().get_setting("swarm_dir") or None
            except ImportError:
                pass
        self._swarm_dir = swarm_dir

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Declare sidebar config fields for the Swarm plugin.

        Returns:
            List with one field descriptor for the export directory path.
        """
        return [
            {
                "key": "swarm_dir",
                "label": "Swarm export directory",
                "type": "dir_path",
            }
        ]

    def get_manual_download_instructions(self) -> str:
        """Return instructions for exporting data from the Swarm app.

        Returns:
            Multi-line instruction string with export steps.
        """
        return (
            "Foursquare/Swarm does not offer a public API for bulk check-in export.\n\n"
            "To request your data:\n"
            "  1. Open the Foursquare City Guide app\n"
            "  2. Go to Settings → Privacy → Request My Data\n"
            "  3. Wait for the email from Foursquare with your download link\n"
            "  4. Download and unzip the archive\n"
            "  5. Point the 'Swarm export directory' setting at the unzipped folder\n\n"
            "See: https://support.foursquare.com/hc/en-us/articles/360046927274"
        )

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized place dicts from Swarm JSON export files.

        Reads all ``.json`` files in ``swarm_dir``, extracts checkins, and
        yields one dict per checkin. Checkins without venue data are skipped.
        Missing or non-existent directories yield nothing gracefully.

        Args:
            since: Optional Unix timestamp; yield only checkins newer than this.
            progress_cb: Optional progress callback (unused for manual plugins).

        Yields:
            Dicts with keys: source_id, timestamp, lat, lng, place_name,
            place_type, raw_json, fetched_at.
        """
        if not self._swarm_dir:
            return

        swarm_path = Path(self._swarm_dir)
        if not swarm_path.exists() or not swarm_path.is_dir():
            return

        fetched_at = int(time.time())

        for json_file in sorted(swarm_path.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            # The Swarm export may wrap checkins in various ways:
            #   {"items": [...]}                    — top-level items list
            #   {"checkins": {"items": [...]}}      — nested checkins dict
            #   {"checkins": [...]}                 — checkins as list
            #   [...]                               — bare list
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if "items" in data:
                    items = data["items"]
                elif "checkins" in data:
                    checkins = data["checkins"]
                    if isinstance(checkins, dict):
                        items = checkins.get("items", [])
                    elif isinstance(checkins, list):
                        items = checkins
                    else:
                        items = []
                else:
                    items = []
            else:
                continue

            for checkin in items:
                if not isinstance(checkin, dict):
                    continue

                venue = checkin.get("venue")
                if not venue:
                    continue

                created_at = checkin.get("createdAt")
                if created_at is None:
                    continue

                try:
                    timestamp = int(created_at)
                except (ValueError, TypeError):
                    from datetime import datetime  # noqa: PLC0415

                    try:
                        timestamp = int(
                            datetime.fromisoformat(str(created_at).replace(" ", "T")).timestamp()
                        )
                    except (ValueError, AttributeError):
                        continue
                if since is not None and timestamp <= since:
                    continue

                location = venue.get("location", {})
                lat = location.get("lat")
                lng = location.get("lng")
                if lat is None or lng is None:
                    continue

                place_name = venue.get("name", "")
                categories = venue.get("categories", [])
                place_type = ""
                if categories:
                    place_type = categories[0].get("name", "")

                yield {
                    "source_id": "swarm",
                    "timestamp": timestamp,
                    "lat": float(lat),
                    "lng": float(lng),
                    "place_name": place_name,
                    "place_type": place_type,
                    "raw_json": checkin,
                    "fetched_at": fetched_at,
                }

    def load(self, config: dict[str, Any]) -> Any:  # TODO(subtask-7): remove
        """Backwards-compat shim: return places from LocalizerStore when available.

        Args:
            config: Legacy config dict (ignored in the new path).

        Returns:
            DataFrame from DuckDB, or empty DataFrame if store unavailable.
        """
        import pandas as pd  # noqa: PLC0415

        try:
            from localizer.store.db import LocalizerStore  # noqa: PLC0415

            with LocalizerStore() as store:
                return store.query_places(source_id=self.PLUGIN_ID)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
