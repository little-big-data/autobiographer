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

# Name-pattern rule table for `_infer_place_type_from_name()` (issue #93).
#
# Real Foursquare/Swarm exports frequently ship an empty `categories` array on
# venue objects, which makes the downstream `place_type` always `""`. As a
# fallback (used only when `categories` is empty/missing — see
# `fetch_records()`), this table matches lowercase substrings of the venue
# *name* against Foursquare/Swarm naming conventions and synthesizes a
# `place_type` string.
#
# Every synthesized value below intentionally reuses a substring from either
# `analysis_utils._CATEGORY_RULES` (dining/nightlife buckets) or
# `analysis_utils.TRANSIT_CATEGORY_KEYWORDS` (transit), so the existing
# downstream classifiers recognize the synthesized value unchanged with zero
# changes to `analysis_utils.py`.
#
# Rules are checked in order; the first match wins. Deliberately excludes a
# bare "port" rule (would false-positive on names like "Portland" or "Import
# Foods") and a bare "club" rule (too generic) — see handoff.md's Task
# Overview non-overlap constraint for issue #93.
_NAME_HEURISTIC_RULES: list[tuple[str, str]] = [
    # Transit (mirrors TRANSIT_CATEGORY_KEYWORDS)
    ("airport", "Airport"),
    ("train station", "Train Station"),
    ("metro station", "Metro Station"),
    ("subway station", "Subway Station"),
    ("bus station", "Bus Station"),
    ("ferry terminal", "Ferry"),
    ("rail station", "Rail Station"),
    ("gas station", "Gas Station"),
    ("truck stop", "Truck Stop"),
    ("rest area", "Rest Area"),
    ("rest stop", "Rest Stop"),
    ("travel plaza", "Travel Plaza"),
    ("service plaza", "Service Plaza"),
    ("turnpike", "Turnpike"),
    ("toll plaza", "Toll"),
    # Dining / nightlife (mirrors _CATEGORY_RULES buckets)
    ("pizza", "Pizza"),
    ("burger", "Burger"),
    ("fried chicken", "Fried Chicken"),
    ("hot dog", "Hot Dog"),
    ("sandwich", "Sandwich"),
    ("brewery", "Brewery"),
    ("nightclub", "Nightclub"),
    ("pub", "Pub"),
    ("wine bar", "Wine Bar"),
    ("cocktail", "Cocktail Bar"),
    ("lounge", "Lounge"),
    ("coffee", "Coffee"),
    ("café", "Cafe"),
    ("cafe", "Cafe"),
    ("tea room", "Tea Room"),
    ("bakery", "Bakery"),
    ("ice cream", "Ice Cream"),
    ("juice bar", "Juice Bar"),
    ("restaurant", "Restaurant"),
    ("diner", "Diner"),
    ("sushi", "Sushi"),
    ("ramen", "Ramen"),
    ("noodle", "Noodle"),
    ("steakhouse", "Steakhouse"),
    ("bbq", "BBQ"),
    ("seafood", "Seafood"),
    ("bistro", "Bistro"),
    ("brasserie", "Brasserie"),
    ("tapas", "Tapas"),
    ("dim sum", "Dim Sum"),
    ("buffet", "Buffet"),
    ("grill", "Grill"),
    ("kitchen", "Kitchen"),
    ("eatery", "Eatery"),
]


def _infer_place_type_from_name(venue_name: str) -> str:
    """Infer a synthesized ``place_type`` from a venue name via keyword heuristics.

    Used as a fallback when a Swarm/Foursquare export's ``categories`` array is
    empty or missing (issue #93). Checks ``venue_name`` (lower-cased) against
    ``_NAME_HEURISTIC_RULES`` in order and returns the first matching rule's
    synthesized value. Every synthesized value contains a substring already
    recognized by ``analysis_utils._CATEGORY_RULES`` or
    ``analysis_utils.TRANSIT_CATEGORY_KEYWORDS``, so downstream classifiers
    work unchanged.

    Args:
        venue_name: The raw venue name string from the Swarm export. May be
            empty or contain only punctuation/whitespace.

    Returns:
        The synthesized place_type string, or ``""`` if no rule matches (never
        ``None``, never raises).
    """
    if not venue_name:
        return ""

    name_lower = venue_name.lower()
    for needle, result in _NAME_HEURISTIC_RULES:
        if needle in name_lower:
            return result
    return ""


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

                # lat/lng may be on the checkin directly (newer Swarm exports)
                # or nested inside venue.location (older exports).
                lat = checkin.get("lat") or venue.get("location", {}).get("lat")
                lng = checkin.get("lng") or venue.get("location", {}).get("lng")
                if lat is None or lng is None:
                    continue

                place_name = venue.get("name", "")
                categories = venue.get("categories", [])
                if categories:
                    place_type = categories[0].get("name", "")
                else:
                    place_type = _infer_place_type_from_name(place_name)

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
