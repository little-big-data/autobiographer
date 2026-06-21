"""Last.fm HTTP fetcher — extracted from autobiographer.py:Autobiographer."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any, Callable

import requests

from localizer.fetch_utils import retry_with_backoff

BASE_URL = "http://ws.audioscrobbler.com/2.0/"


class LastFmFetcher:
    """Fetches raw track dicts from the Last.fm API.

    Args:
        api_key: Last.fm API key.
        api_secret: Last.fm API secret.
        username: Last.fm username to fetch.
    """

    def __init__(self, api_key: str, api_secret: str, username: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.username = username

    def _fetch_page(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a single page from the Last.fm API.

        Args:
            method: Last.fm API method (e.g. ``"user.getrecenttracks"``).
            params: Additional query parameters.

        Returns:
            Parsed JSON response dict.

        Raises:
            requests.exceptions.HTTPError: On non-2xx responses.
            requests.exceptions.RequestException: On network errors.
        """
        params = dict(params)
        params.update(
            {
                "method": method,
                "api_key": self.api_key,
                "format": "json",
                "user": self.username,
            }
        )
        response = requests.get(BASE_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    def fetch_recent_tracks(
        self,
        since: int | None = None,
        progress_cb: Callable[[int, int], None] | None = None,
        limit: int = 200,
        pages: int | None = None,
        max_retries: int = 3,
    ) -> Iterator[dict[str, Any]]:
        """Yield raw track dicts from the Last.fm API.

        Iterates through all pages, skipping any "now playing" track that
        lacks a ``date`` field.

        Args:
            since: Optional Unix timestamp lower bound (``from`` parameter).
            progress_cb: Optional callback invoked with ``(current_page, total_pages)``
                after each page.
            limit: Tracks per API page (max 200).
            pages: Stop after this many pages; ``None`` fetches all.
            max_retries: Number of retry attempts per page on network error.

        Yields:
            Raw track dicts as returned by the Last.fm API (not normalized).

        Raises:
            requests.exceptions.RequestException: If a page fetch fails after
                all retries are exhausted.
        """
        current_page = 1

        while True:
            params: dict[str, Any] = {"limit": limit, "page": current_page}
            if since is not None:
                params["from"] = since

            def _do_fetch(p: dict[str, Any] = params) -> dict[str, Any]:
                return self._fetch_page("user.getrecenttracks", p)

            data = retry_with_backoff(_do_fetch, max_retries=max_retries)

            tracks = data.get("recenttracks", {}).get("track", [])
            if not tracks:
                break

            total_pages = int(data.get("recenttracks", {}).get("@attr", {}).get("totalPages", 1))

            for track in tracks:
                # Skip "now playing" tracks — they have no date
                if track.get("@attr", {}).get("nowplaying") == "true":
                    continue
                if "date" not in track:
                    continue
                yield track

            if progress_cb:
                progress_cb(current_page, total_pages)

            if pages is not None and current_page >= pages:
                break
            if current_page >= total_pages:
                break

            current_page += 1
            time.sleep(0.25)  # Rate limiting
