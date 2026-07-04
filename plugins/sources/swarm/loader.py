"""Foursquare/Swarm source plugin.

Normalizes Swarm check-in data to the "where-when" schema expected by the DataBroker.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pandas as pd

from plugins.sources import register
from plugins.sources.base import _LegacyAutoPlugin, validate_schema


@register
class SwarmPlugin(_LegacyAutoPlugin):
    """Load Foursquare/Swarm check-in history from a local JSON export directory."""

    PLUGIN_TYPE = "where-when"
    PLUGIN_ID = "swarm"
    DISPLAY_NAME = "Foursquare / Swarm Check-ins"
    ICON = ":material/location_on:"
    FETCHABLE = False

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Declare sidebar config fields for the Swarm plugin.

        Returns:
            List of field descriptors for swarm_dir and assumptions_file.
        """
        return [
            {
                "key": "swarm_dir",
                "label": "Swarm JSON export directory",
                "type": "dir_path",
            },
        ]

    def load(self, config: dict[str, Any]) -> pd.DataFrame:
        """Load Swarm check-ins and return a normalized where-when DataFrame.

        Reads check-in JSON files from swarm_dir via the analysis_loader bridge,
        then maps existing columns to the normalized schema (place_name, place_type).
        Original columns are preserved. The assumptions file is loaded but not
        applied here — temporal merging is the DataBroker's responsibility.

        Args:
            config: Must contain "swarm_dir". May contain "assumptions_file".

        Returns:
            DataFrame with original columns plus normalized schema columns.

        Raises:
            ValueError: If required schema columns cannot be produced.
        """
        from core.analysis_loader import load_swarm_history  # noqa: PLC0415

        swarm_dir: str = config.get("swarm_dir", "")
        if not swarm_dir:
            return pd.DataFrame()

        df = load_swarm_history(swarm_dir)

        if df.empty:
            return df

        # Normalize to where-when schema. Existing columns already include
        # lat, lng, and place_name. Map 'source' → place_type if present.
        if "place_type" not in df.columns:
            df = df.assign(place_type=df.get("source", "venue"))

        df = df.assign(source_id=self.PLUGIN_ID)

        validate_schema(df, self.PLUGIN_TYPE)
        return df

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized place records from the Swarm JSON export.

        Delegates to the localizer SwarmPlugin when invoked from the new
        fetch pipeline. For legacy CSV-based workflows use load() instead.

        Args:
            since: Optional Unix timestamp lower bound.
            progress_cb: Optional progress callback (unused for manual plugins).

        Yields:
            Normalized place dicts.
        """
        from localizer.plugins.swarm.loader import SwarmPlugin as _LocalizerPlugin  # noqa: PLC0415

        yield from _LocalizerPlugin().fetch_records(since=since, progress_cb=progress_cb)

    def fetch(self, output_path: str | None = None, **kwargs: Any) -> None:
        """Swarm does not support automatic fetching.

        Args:
            output_path: Unused.
            **kwargs: Unused.

        Raises:
            NotImplementedError: Always, since Swarm requires a manual export.
        """
        raise NotImplementedError(
            f"{self.PLUGIN_ID} does not support automatic fetching. "
            "Run `python autobiographer.py fetch "
            f"{self.PLUGIN_ID}` for manual download instructions."
        )

    def get_manual_download_instructions(self) -> str:
        """Return instructions for requesting a Foursquare/Swarm data export.

        Returns:
            Multi-line instruction string.
        """
        return (
            "Foursquare/Swarm does not offer a public API for bulk check-in export.\n\n"
            "To request your data:\n"
            "  1. Open the Foursquare City Guide app\n"
            "  2. Go to Settings → Privacy → Request My Data\n"
            "  3. Wait for the email from Foursquare with your download link\n"
            "  4. Download and unzip the archive\n"
            "  5. Point the 'Swarm JSON export directory' setting at the unzipped folder\n\n"
            "See: https://support.foursquare.com/hc/en-us/articles/360046927274"
        )

    def get_schema(self) -> dict[str, str]:
        """Return column descriptions for the Swarm plugin.

        Returns:
            Dict mapping column names to descriptions.
        """
        return {
            "timestamp": "Unix timestamp of the check-in (UTC)",
            "lat": "Latitude (WGS84)",
            "lng": "Longitude (WGS84)",
            "place_name": "Venue or location name",
            "place_type": "Location category (e.g. 'venue', 'city')",
            "source_id": "Plugin identifier ('swarm')",
        }
