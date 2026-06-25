"""Failing tests for Subtask 6: RssPlugin in the localizer package.

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/rss/__init__.py
  - packages/localizer/src/localizer/plugins/rss/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py (load_builtin_plugins)

RssPlugin is FetchMode.MANUAL — feedparser runs locally with no API key.
The PLUGIN_ID is dynamic: f"rss:{feed_url}".
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

FEED_URL = "https://example.com/feed.xml"

# ---------------------------------------------------------------------------
# Helpers — minimal feedparser-shaped return values
# ---------------------------------------------------------------------------


def _make_feedparser_result(entries: list[dict[str, Any]], feed_title: str = "Test Feed") -> Any:
    """Build a minimal object resembling a feedparser result."""
    result = MagicMock()
    result.feed.title = feed_title
    result.entries = [_make_entry(**e) for e in entries]
    result.bozo = False
    return result


def _make_entry(
    title: str = "Test Entry",
    link: str = "https://example.com/entry",
    author: str = "Test Author",
    published_parsed: tuple | None = (2023, 11, 14, 12, 0, 0, 1, 318, 0),
) -> Any:
    """Build a minimal feedparser entry object."""
    entry = MagicMock()
    entry.title = title
    entry.link = link
    entry.author = author
    entry.published_parsed = published_parsed
    # Simulate absence of attribute when published_parsed is None
    if published_parsed is None:
        del entry.published_parsed
        entry.configure_mock(**{"get.return_value": None})
        # Make hasattr(entry, 'published_parsed') return False
        type(entry).__contains__ = lambda self, item: item != "published_parsed"
    return entry


TWO_ENTRIES = [
    {
        "title": "First Entry",
        "link": "https://example.com/first",
        "author": "Alice",
        "published_parsed": (2023, 11, 14, 12, 0, 0, 1, 318, 0),
    },
    {
        "title": "Second Entry",
        "link": "https://example.com/second",
        "author": "Bob",
        "published_parsed": (2023, 11, 15, 8, 0, 0, 2, 319, 0),
    },
]


def _make_plugin(url: str = FEED_URL) -> Any:
    """Instantiate an RssPlugin with the given feed URL."""
    from localizer.plugins.rss.loader import RssPlugin

    return RssPlugin(url=url)


# ---------------------------------------------------------------------------
# ABC / class attribute tests
# ---------------------------------------------------------------------------


def test_rss_plugin_id_contains_url() -> None:
    """PLUGIN_ID must equal 'rss:<url>' for the given feed URL."""
    plugin = _make_plugin(FEED_URL)
    assert plugin.PLUGIN_ID == f"rss:{FEED_URL}", (
        f"PLUGIN_ID {plugin.PLUGIN_ID!r} != 'rss:{FEED_URL}'"
    )


def test_rss_fetch_mode() -> None:
    """RssPlugin.FETCH_MODE must be FetchMode.MANUAL."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.rss.loader import RssPlugin

    assert RssPlugin.FETCH_MODE == FetchMode.MANUAL


def test_rss_output_tables() -> None:
    """OutputTable.CONTENT must be in RssPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.rss.loader import RssPlugin

    assert OutputTable.CONTENT in RssPlugin.OUTPUT_TABLES


# ---------------------------------------------------------------------------
# fetch_records normalization tests
# ---------------------------------------------------------------------------


def test_rss_fetch_records_normalized_shape() -> None:
    """fetch_records() must yield 2 dicts with all required keys for a 2-entry feed."""
    required_keys = {
        "source_id",
        "timestamp",
        "title",
        "url",
        "feed_title",
        "author",
        "raw_json",
        "fetched_at",
    }
    mock_result = _make_feedparser_result(TWO_ENTRIES)

    plugin = _make_plugin()
    with patch("feedparser.parse", return_value=mock_result):
        records = list(plugin.fetch_records())

    assert len(records) == 2, f"Expected 2 records, got {len(records)}"
    for record in records:
        missing = required_keys - set(record.keys())
        assert not missing, f"Record missing required keys: {missing}"


def test_rss_source_id_contains_url() -> None:
    """source_id in each record must equal the plugin's PLUGIN_ID (rss:<url>)."""
    mock_result = _make_feedparser_result(TWO_ENTRIES)

    plugin = _make_plugin()
    with patch("feedparser.parse", return_value=mock_result):
        records = list(plugin.fetch_records())

    for record in records:
        assert record["source_id"] == f"rss:{FEED_URL}", (
            f"source_id {record['source_id']!r} != 'rss:{FEED_URL}'"
        )


def test_rss_timestamp_is_int() -> None:
    """timestamp in each record must be a Python int (Unix seconds)."""
    mock_result = _make_feedparser_result(TWO_ENTRIES)

    plugin = _make_plugin()
    with patch("feedparser.parse", return_value=mock_result):
        records = list(plugin.fetch_records())

    for record in records:
        assert isinstance(record["timestamp"], int), (
            f"timestamp is {type(record['timestamp'])}, expected int"
        )


def test_rss_empty_feed() -> None:
    """When the feed has no entries, fetch_records() must yield nothing."""
    mock_result = _make_feedparser_result([])

    plugin = _make_plugin()
    with patch("feedparser.parse", return_value=mock_result):
        records = list(plugin.fetch_records())

    assert records == [], f"Expected empty list for feed with no entries, got {records}"


def test_rss_missing_published_uses_fetched_at() -> None:
    """An entry with no published_parsed must fall back to a non-zero int timestamp."""
    # Build entry without published_parsed
    entry_without_date = MagicMock()
    entry_without_date.title = "No Date Entry"
    entry_without_date.link = "https://example.com/no-date"
    entry_without_date.author = "Ghost"
    # Make hasattr(entry, 'published_parsed') return False
    # feedparser stores dates as tuples; absence can be tested via getattr
    entry_without_date.published_parsed = None

    mock_result = MagicMock()
    mock_result.feed.title = "Test Feed"
    mock_result.entries = [entry_without_date]
    mock_result.bozo = False

    before = int(time.time())
    plugin = _make_plugin()
    with patch("feedparser.parse", return_value=mock_result):
        records = list(plugin.fetch_records())
    after = int(time.time())

    assert len(records) == 1
    ts = records[0]["timestamp"]
    assert isinstance(ts, int), f"Expected int timestamp, got {type(ts)}"
    assert ts > 0, "Expected non-zero fallback timestamp"
    # The fallback should be close to now
    assert before - 5 <= ts <= after + 5, (
        f"Fallback timestamp {ts} not close to now ({before}–{after})"
    )


def test_rss_feed_title_from_feed_metadata() -> None:
    """feed_title must come from feedparser result's feed.title, not entry metadata."""
    mock_result = _make_feedparser_result(TWO_ENTRIES, feed_title="My Podcast")

    plugin = _make_plugin()
    with patch("feedparser.parse", return_value=mock_result):
        records = list(plugin.fetch_records())

    for record in records:
        assert record["feed_title"] == "My Podcast", (
            f"feed_title {record['feed_title']!r} != 'My Podcast'"
        )


def test_rss_url_from_entry_link() -> None:
    """url must come from entry.link, not entry.id or any other field."""
    mock_result = _make_feedparser_result(
        [
            {
                "title": "Link Test",
                "link": "https://specific-url.example.com/article",
                "author": "Writer",
                "published_parsed": (2023, 11, 14, 12, 0, 0, 1, 318, 0),
            }
        ]
    )

    plugin = _make_plugin()
    with patch("feedparser.parse", return_value=mock_result):
        records = list(plugin.fetch_records())

    assert len(records) == 1
    assert records[0]["url"] == "https://specific-url.example.com/article", (
        f"url {records[0]['url']!r} != expected link"
    )


def test_rss_title_from_entry() -> None:
    """title must come from the entry, not the feed metadata."""
    mock_result = _make_feedparser_result(
        [
            {
                "title": "Specific Article Title",
                "link": "https://example.com/article",
                "author": "Author",
                "published_parsed": (2023, 11, 14, 12, 0, 0, 1, 318, 0),
            }
        ]
    )

    plugin = _make_plugin()
    with patch("feedparser.parse", return_value=mock_result):
        records = list(plugin.fetch_records())

    assert len(records) == 1
    assert records[0]["title"] == "Specific Article Title", (
        f"title {records[0]['title']!r} != 'Specific Article Title'"
    )


def test_rss_fetched_at_is_recent() -> None:
    """fetched_at must be a Unix timestamp close to now."""
    mock_result = _make_feedparser_result(TWO_ENTRIES)

    before = int(time.time())
    plugin = _make_plugin()
    with patch("feedparser.parse", return_value=mock_result):
        records = list(plugin.fetch_records())
    after = int(time.time())

    for record in records:
        assert isinstance(record["fetched_at"], int)
        assert before - 5 <= record["fetched_at"] <= after + 5, (
            f"fetched_at {record['fetched_at']} not close to now ({before}–{after})"
        )


def test_rss_get_config_fields_returns_list() -> None:
    """get_config_fields() must return a list (may be empty or contain url field)."""
    plugin = _make_plugin()
    result = plugin.get_config_fields()
    assert isinstance(result, list)
