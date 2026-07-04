"""Last.fm source plugin for the localizer package."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from typing import Any

import pandas as pd

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin
from localizer.plugins.lastfm.fetcher import LastFmFetcher


@register
class LastFmPlugin(SourcePlugin):
    """Fetch Last.fm listening history via the Last.fm API.

    Credentials are read from environment variables:
    - ``AUTOBIO_LASTFM_API_KEY``
    - ``AUTOBIO_LASTFM_API_SECRET``
    - ``AUTOBIO_LASTFM_USERNAME``
    """

    PLUGIN_ID = "lastfm"
    DISPLAY_NAME = "Last.fm"
    FETCH_MODE = FetchMode.API
    OUTPUT_TABLES = [OutputTable.EVENTS]

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Return empty list — this plugin is env-var-driven.

        Returns:
            Empty list.
        """
        return []

    def get_fetch_env_vars(self) -> list[dict[str, str]]:
        """Return env vars required to fetch Last.fm data.

        Returns:
            List of env var descriptor dicts.
        """
        return [
            {"var": "AUTOBIO_LASTFM_API_KEY", "description": "Last.fm API key"},
            {"var": "AUTOBIO_LASTFM_API_SECRET", "description": "Last.fm API secret"},
            {"var": "AUTOBIO_LASTFM_USERNAME", "description": "Last.fm username to fetch"},
        ]

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized event dicts fetched from the Last.fm API.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional callback invoked with ``(current, total)``
                for progress reporting.

        Yields:
            Dicts with keys: ``source_id``, ``timestamp``, ``label``,
            ``sublabel``, ``category``, ``raw_json``, ``fetched_at``.
        """
        missing = [
            v
            for v in (
                "AUTOBIO_LASTFM_API_KEY",
                "AUTOBIO_LASTFM_API_SECRET",
                "AUTOBIO_LASTFM_USERNAME",
            )
            if not os.environ.get(v)
        ]
        if missing:
            raise OSError(
                f"{', '.join(missing)} environment variable(s) are not set. "
                "Set them to enable Last.fm sync."
            )
        fetcher = LastFmFetcher(
            api_key=os.environ["AUTOBIO_LASTFM_API_KEY"],
            api_secret=os.environ["AUTOBIO_LASTFM_API_SECRET"],
            username=os.environ["AUTOBIO_LASTFM_USERNAME"],
        )
        for track in fetcher.fetch_recent_tracks(since=since, progress_cb=progress_cb):
            yield self._normalize(track)

    def _normalize(self, track: dict[str, Any]) -> dict[str, Any]:
        """Convert a raw Last.fm track dict to a canonical event dict.

        Args:
            track: Raw track dict from the Last.fm API.

        Returns:
            Normalized event dict.
        """
        return {
            "source_id": "lastfm",
            "timestamp": int(track["date"]["uts"]),
            "label": track["artist"]["#text"],
            "sublabel": track["name"],
            "category": track["album"]["#text"],
            "raw_json": json.dumps(track),
            "fetched_at": int(time.time()),
        }

    def load(self, config: dict[str, Any]) -> pd.DataFrame:  # TODO(subtask-7): remove
        """Backwards-compat shim: read events from LocalizerStore.

        Args:
            config: Legacy config dict (ignored).

        Returns:
            DataFrame of Last.fm events from DuckDB, or empty DataFrame.
        """
        try:
            from localizer.store.db import LocalizerStore  # noqa: PLC0415

            store = LocalizerStore()
            df = store.query_events(source_id="lastfm")
            store.close()
            return df
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
