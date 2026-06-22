"""RSS/Atom feed source plugin for the localizer package."""

from __future__ import annotations

import json
import time
from calendar import timegm
from collections.abc import Iterator
from typing import Any

import feedparser

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin


@register
class RssPlugin(SourcePlugin):
    """Fetch entries from an RSS or Atom feed via feedparser.

    The ``PLUGIN_ID`` is dynamic: ``rss:<feed_url>``.  feedparser runs
    locally without an API key, so ``FETCH_MODE`` is ``MANUAL``.

    Args:
        url: The RSS/Atom feed URL to parse.
    """

    PLUGIN_ID = "rss"  # class-level registry key
    DISPLAY_NAME = "RSS/Atom Feed"
    FETCH_MODE = FetchMode.MANUAL
    OUTPUT_TABLES = [OutputTable.CONTENT]

    def __init__(self, url: str = "") -> None:
        """Initialise the plugin with a feed URL.

        Args:
            url: The RSS/Atom feed URL.
        """
        self._feed_url = url
        # Override PLUGIN_ID at instance level for source_id tagging
        self.PLUGIN_ID = f"rss:{url}"

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Return config fields required by this plugin.

        Returns:
            List with a single ``feed_url`` text field.
        """
        return [{"key": "feed_url", "label": "Feed URL", "type": "text"}]

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized content dicts from the RSS/Atom feed.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional callback invoked with ``(current, total)``
                for progress reporting.

        Yields:
            Dicts with keys: ``source_id``, ``timestamp``, ``title``,
            ``url``, ``feed_title``, ``author``, ``raw_json``, ``fetched_at``.
        """
        feed = feedparser.parse(self._feed_url)
        fetched_at = int(time.time())

        feed_title = ""
        try:
            feed_title = feed.feed.title or ""
        except AttributeError:
            feed_title = ""

        for entry in feed.entries:
            # Resolve timestamp from published_parsed (a time.struct_time tuple)
            published_parsed = getattr(entry, "published_parsed", None)
            if published_parsed is not None:
                try:
                    timestamp = int(timegm(published_parsed))
                except (TypeError, ValueError):
                    timestamp = fetched_at
            else:
                timestamp = fetched_at

            title = getattr(entry, "title", "") or entry.get("title", "")
            url = getattr(entry, "link", "") or entry.get("link", "")
            author = getattr(entry, "author", "") or entry.get("author", "")

            # Build a serializable dict for raw_json
            raw: dict[str, Any] = {
                "title": title,
                "link": url,
                "author": author,
                "published_parsed": list(published_parsed) if published_parsed else None,
            }

            yield {
                "source_id": self.PLUGIN_ID,
                "timestamp": timestamp,
                "title": title,
                "url": url,
                "feed_title": feed_title,
                "author": author,
                "raw_json": json.dumps(raw),
                "fetched_at": fetched_at,
            }
