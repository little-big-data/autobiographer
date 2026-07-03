"""Google Maps Timeline source plugin.

Wraps the existing load_google_timeline() parser and normalizes the resulting
DataFrame to the "where-when" schema expected by the DataBroker. The plugin reads
only a previously-exported local Timeline.json file — no network calls are made at
Streamlit runtime (FETCHABLE is False).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from plugins.sources import register
from plugins.sources.base import SourcePlugin, validate_schema


@register
class GoogleTimelinePlugin(SourcePlugin):
    """Load Google Maps Timeline location history from a local Timeline.json export."""

    PLUGIN_TYPE = "where-when"
    PLUGIN_ID = "google_timeline"
    DISPLAY_NAME = "Google Maps Timeline"
    ICON = ":material/map:"

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Declare sidebar config fields for the Google Timeline plugin.

        Returns:
            List containing a single file-path field for the Timeline.json export.
        """
        return [
            {
                "key": "timeline_path",
                "label": "Google Timeline JSON file",
                "type": "file_path",
                "file_types": [("Google Timeline JSON", "*.json"), ("All files", "*.*")],
            }
        ]

    def load(self, config: dict[str, Any]) -> pd.DataFrame:
        """Load Google Timeline data and return a normalized where-when DataFrame.

        Reads Timeline.json via load_google_timeline(), then maps the swarm-shaped
        columns it produces onto the normalized schema (place_name, place_type).
        Original columns are preserved so the same frame can also feed the Places/Geo
        views. No network I/O occurs here.

        Args:
            config: Must contain "timeline_path" pointing at a Timeline.json file.

        Returns:
            DataFrame with original columns plus normalized schema columns, or an
            empty DataFrame when unconfigured or the export has no usable records.

        Raises:
            ValueError: If required schema columns cannot be produced.
        """
        from analysis_utils import load_google_timeline

        timeline_path: str = config.get("timeline_path", "")
        if not timeline_path:
            return pd.DataFrame()

        df = load_google_timeline(timeline_path)

        if df.empty:
            return df

        # Normalize to the validated where-when schema. venue/venue_category already
        # carry the place name and type produced by the parser.
        df = df.assign(
            place_name=df["venue"],
            place_type=df["venue_category"],
            source_id=self.PLUGIN_ID,
        )

        validate_schema(df, self.PLUGIN_TYPE)
        return df

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

    def get_schema(self) -> dict[str, str]:
        """Return column descriptions for the Google Timeline plugin.

        Returns:
            Dict mapping column names to descriptions.
        """
        return {
            "timestamp": "Unix timestamp of the visit or activity start (UTC)",
            "lat": "Latitude (WGS84)",
            "lng": "Longitude (WGS84)",
            "place_name": "Frequent-place label, or humanized visit/activity type",
            "place_type": "Semantic visit type (e.g. 'home', 'work') or 'activity:<type>'",
            "source_id": "Plugin identifier ('google_timeline')",
        }
