"""Feedly source plugin for the localizer package."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from typing import Any

import requests

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin

FEEDLY_STREAMS_URL = "https://cloud.feedly.com/v3/streams/contents"


@register
class FeedlyPlugin(SourcePlugin):
    """Fetch articles from Feedly via the Developer API.

    Credentials are read from environment variables:
    - ``LOCALIZER_FEEDLY_TOKEN``
    """

    PLUGIN_ID = "feedly"
    DISPLAY_NAME = "Feedly"
    FETCH_MODE = FetchMode.API
    OUTPUT_TABLES = [OutputTable.CONTENT]

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Return empty list — this plugin is env-var-driven.

        Returns:
            Empty list.
        """
        return []

    def get_fetch_env_vars(self) -> list[dict[str, str]]:
        """Return env vars required to fetch Feedly data.

        Returns:
            List of env var descriptor dicts.
        """
        return [
            {
                "var": "LOCALIZER_FEEDLY_TOKEN",
                "description": "Feedly Developer API access token",
            }
        ]

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized content dicts fetched from the Feedly Streams API.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional callback invoked with ``(current, total)``
                for progress reporting.

        Yields:
            Dicts with keys: ``source_id``, ``timestamp``, ``title``,
            ``url``, ``feed_title``, ``author``, ``raw_json``, ``fetched_at``.

        Raises:
            EnvironmentError: If ``LOCALIZER_FEEDLY_TOKEN`` is not set.
            requests.exceptions.HTTPError: On non-2xx responses.
            ValueError: If the response body is missing the ``items`` key.
        """
        token = os.environ.get("LOCALIZER_FEEDLY_TOKEN")
        if not token:
            raise OSError(
                "LOCALIZER_FEEDLY_TOKEN environment variable is not set. "
                "Set it to your Feedly Developer API token."
            )

        headers = {"Authorization": f"Bearer {token}"}
        params: dict[str, Any] = {"streamId": "user/me/category/global.all", "count": 250}

        response = requests.get(
            FEEDLY_STREAMS_URL,
            headers=headers,
            params=params,
            timeout=(10, 30),
        )
        response.raise_for_status()

        data = response.json()
        if "items" not in data:
            raise ValueError(
                f"feedly API response missing 'items' key. Raw response snippet: {str(data)[:200]}"
            )

        fetched_at = int(time.time())
        for item in data["items"]:
            # Feedly publishes timestamps in milliseconds; convert to seconds
            published_ms = item.get("published", 0)
            timestamp = int(published_ms // 1000)

            title = ""
            title_field = item.get("title")
            if isinstance(title_field, dict):
                title = title_field.get("content", "")
            elif isinstance(title_field, str):
                title = title_field

            url = ""
            alternate = item.get("alternate", [])
            if alternate:
                url = alternate[0].get("href", "")

            feed_title = ""
            origin = item.get("origin", {})
            if isinstance(origin, dict):
                feed_title = origin.get("title", "")

            yield {
                "source_id": "feedly",
                "timestamp": timestamp,
                "title": title,
                "url": url,
                "feed_title": feed_title,
                "author": item.get("author", ""),
                "raw_json": json.dumps(item),
                "fetched_at": fetched_at,
            }
