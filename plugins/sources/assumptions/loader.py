"""Location assumptions source plugin.

Loads a user-authored JSON file that describes where the user was during
periods not covered by Swarm check-ins — trips, recurring holidays, and
home residency rules. This data is consumed by apply_swarm_offsets() to
assign locations and timezone offsets to Last.fm listens.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pandas as pd

from plugins.sources import register
from plugins.sources.base import SourcePlugin


@register
class AssumptionsPlugin(SourcePlugin):
    """Load location assumptions from a user-authored JSON file.

    The JSON file describes where the user was during periods not recorded
    by Swarm: long trips, annually recurring holidays, and home/work
    residency rules. The sidebar passes the file path to load_assumptions()
    so apply_swarm_offsets() can fill in locations for Last.fm listens.
    """

    PLUGIN_TYPE = "location-context"
    PLUGIN_ID = "assumptions"
    DISPLAY_NAME = "Location Assumptions"
    ICON = ":material/map:"

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Declare sidebar config fields for the assumptions plugin.

        Returns:
            List containing a single path field for the JSON file.
        """
        return [
            {
                "key": "assumptions_file",
                "label": "Location assumptions JSON",
                "type": "file_path",
                "file_types": [("JSON files", "*.json"), ("All files", "*.*")],
            }
        ]

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield nothing — assumptions are a static config source, not fetchable.

        Args:
            since: Unused.
            progress_cb: Unused.

        Yields:
            Nothing.
        """
        yield from []

    def load(self, config: dict[str, Any]) -> pd.DataFrame:
        """Load the assumptions file and return a flat DataFrame of location periods.

        Normalizes trips, holidays, and the default location into rows so the
        data can be inspected or displayed like any other plugin output.
        Residency entries (which have complex sub-rules) are included as a
        single summary row each.

        Args:
            config: Must contain "assumptions_file" key with path to JSON file.
                If the file is absent or empty the built-in defaults are used.

        Returns:
            DataFrame with columns: type, city, lat, lng, timezone, start, end.
            Returns an empty DataFrame if no assumptions are defined.
        """
        from analysis_utils import load_assumptions

        assumptions_file = config.get("assumptions_file", "")
        data = load_assumptions(assumptions_file or None)

        rows: list[dict[str, Any]] = []

        defaults = data.get("defaults", {})
        if defaults:
            rows.append(
                {
                    "type": "default",
                    "city": defaults.get("city", ""),
                    "lat": defaults.get("lat"),
                    "lng": defaults.get("lng"),
                    "timezone": defaults.get("timezone", ""),
                    "start": "",
                    "end": "",
                }
            )

        for trip in data.get("trips", []):
            rows.append(
                {
                    "type": "trip",
                    "city": trip.get("city", ""),
                    "lat": trip.get("lat"),
                    "lng": trip.get("lng"),
                    "timezone": trip.get("timezone", ""),
                    "start": trip.get("start", ""),
                    "end": trip.get("end", ""),
                }
            )

        for holiday in data.get("holidays", []):
            month = holiday.get("month", "")
            day_range = holiday.get("day_range", [])
            day_str = f"{day_range[0]}–{day_range[1]}" if len(day_range) == 2 else ""
            rows.append(
                {
                    "type": "holiday",
                    "city": holiday.get("city", ""),
                    "lat": holiday.get("lat"),
                    "lng": holiday.get("lng"),
                    "timezone": holiday.get("timezone", ""),
                    "start": f"month {month} day {day_str}",
                    "end": "",
                }
            )

        for res in data.get("residency", []):
            rows.append(
                {
                    "type": "residency",
                    "city": res.get("city", ""),
                    "lat": res.get("lat"),
                    "lng": res.get("lng"),
                    "timezone": "",
                    "start": res.get("start", ""),
                    "end": res.get("end", ""),
                }
            )

        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def get_manual_download_instructions(self) -> str:
        """Return instructions for creating a location assumptions file.

        Returns:
            Multi-line instruction string.
        """
        return (
            "Location assumptions are defined in a JSON file you create yourself.\n\n"
            "Copy the example file to get started:\n"
            "  cp default_assumptions.json.example default_assumptions.json\n\n"
            "Edit it to describe:\n"
            "  • defaults — your home city and timezone (used when nothing else matches)\n"
            "  • trips    — date-range trips with city, lat/lng, and timezone\n"
            "  • holidays — recurring annual events (e.g. a family visit every December)\n"
            "  • residency — long-term home or work periods with optional sub-rules\n\n"
            "See default_assumptions.json.example for the full format reference."
        )

    def get_schema(self) -> dict[str, str]:
        """Return column descriptions for the assumptions plugin.

        Returns:
            Dict mapping column names to descriptions.
        """
        return {
            "type": "Entry type: 'default', 'trip', 'holiday', or 'residency'",
            "city": "City name (used for display and geocoding fallback)",
            "lat": "Latitude (WGS84)",
            "lng": "Longitude (WGS84)",
            "timezone": "IANA timezone string (e.g. 'Europe/London')",
            "start": "Start date (YYYY-MM-DD) or recurring pattern for holidays",
            "end": "End date (YYYY-MM-DD); empty for defaults and holidays",
        }
