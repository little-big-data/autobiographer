"""Failing tests for Subtask 6: FeedlyPlugin in the localizer package.

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/feedly/__init__.py
  - packages/localizer/src/localizer/plugins/feedly/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py (load_builtin_plugins)
"""

from __future__ import annotations

import os
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FEEDLY_API_URL = "https://cloud.feedly.com/v3/streams/contents"

MINIMAL_TWO_ARTICLE_RESPONSE: dict[str, Any] = {
    "id": "user/abc/category/global.all",
    "items": [
        {
            "id": "article_001",
            "title": {"content": "Article One"},
            "alternate": [{"href": "https://example.com/article-one"}],
            "origin": {"title": "Example Feed"},
            "author": "Alice",
            "published": 1_700_000_000_000,  # Feedly uses milliseconds
        },
        {
            "id": "article_002",
            "title": {"content": "Article Two"},
            "alternate": [{"href": "https://example.com/article-two"}],
            "origin": {"title": "Example Feed"},
            "author": "Bob",
            "published": 1_700_001_000_000,
        },
    ],
}

EMPTY_ARTICLE_RESPONSE: dict[str, Any] = {
    "id": "user/abc/category/global.all",
    "items": [],
}


def _make_plugin() -> Any:
    """Instantiate a FeedlyPlugin with a dummy token via env var."""
    os.environ["LOCALIZER_FEEDLY_TOKEN"] = "test_feedly_token"  # noqa: S105
    from localizer.plugins.feedly.loader import FeedlyPlugin

    return FeedlyPlugin()


# ---------------------------------------------------------------------------
# ABC / registration tests
# ---------------------------------------------------------------------------


def test_feedly_plugin_id() -> None:
    """FeedlyPlugin.PLUGIN_ID must equal 'feedly'."""
    from localizer.plugins.feedly.loader import FeedlyPlugin

    assert FeedlyPlugin.PLUGIN_ID == "feedly"


def test_feedly_fetch_mode() -> None:
    """FeedlyPlugin.FETCH_MODE must be FetchMode.API."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.feedly.loader import FeedlyPlugin

    assert FeedlyPlugin.FETCH_MODE == FetchMode.API


def test_feedly_output_tables() -> None:
    """OutputTable.CONTENT must be in FeedlyPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.feedly.loader import FeedlyPlugin

    assert OutputTable.CONTENT in FeedlyPlugin.OUTPUT_TABLES


def test_feedly_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['feedly'] must exist."""
    from localizer.plugins import REGISTRY, load_builtin_plugins

    REGISTRY.clear()
    load_builtin_plugins()
    assert "feedly" in REGISTRY, f"'feedly' not in REGISTRY; keys: {list(REGISTRY)}"


# ---------------------------------------------------------------------------
# fetch_records normalization tests
# ---------------------------------------------------------------------------


def test_feedly_fetch_records_normalized_shape() -> None:
    """fetch_records() must yield 2 dicts with all required keys for a 2-article response."""
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
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = MINIMAL_TWO_ARTICLE_RESPONSE
    mock_response.raise_for_status.return_value = None

    plugin = _make_plugin()
    with patch("requests.get", return_value=mock_response):
        records = list(plugin.fetch_records())

    assert len(records) == 2, f"Expected 2 records, got {len(records)}"
    for record in records:
        missing = required_keys - set(record.keys())
        assert not missing, f"Record missing required keys: {missing}"
    assert records[0]["source_id"] == "feedly"


def test_feedly_fetch_records_timestamp_is_int() -> None:
    """timestamp in each yielded dict must be a Unix epoch integer (seconds)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = MINIMAL_TWO_ARTICLE_RESPONSE
    mock_response.raise_for_status.return_value = None

    plugin = _make_plugin()
    with patch("requests.get", return_value=mock_response):
        records = list(plugin.fetch_records())

    for record in records:
        assert isinstance(record["timestamp"], int), (
            f"timestamp is {type(record['timestamp'])}, expected int"
        )
        # Feedly publishes in milliseconds; the plugin must convert to seconds
        # A reasonable Unix timestamp in seconds is less than 2^32
        assert record["timestamp"] < 2**32, (
            f"timestamp {record['timestamp']} looks like milliseconds, not seconds"
        )


def test_feedly_fetch_records_empty_response() -> None:
    """When items is an empty list, fetch_records() must yield nothing."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = EMPTY_ARTICLE_RESPONSE
    mock_response.raise_for_status.return_value = None

    plugin = _make_plugin()
    with patch("requests.get", return_value=mock_response):
        records = list(plugin.fetch_records())

    assert records == [], f"Expected empty list for empty items, got {records}"


def test_feedly_missing_token_raises() -> None:
    """When LOCALIZER_FEEDLY_TOKEN is not set, fetch_records() must raise EnvironmentError."""
    # Remove the env var
    env_without_token = {k: v for k, v in os.environ.items() if k != "LOCALIZER_FEEDLY_TOKEN"}
    with patch.dict(os.environ, env_without_token, clear=True):
        from localizer.plugins.feedly.loader import FeedlyPlugin

        plugin = FeedlyPlugin()
        with pytest.raises((EnvironmentError, KeyError)):
            list(plugin.fetch_records())


def test_feedly_http_error_propagates() -> None:
    """A 401 HTTP response must raise an HTTPError, not return None or empty."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "401 Unauthorized", response=mock_response
    )

    plugin = _make_plugin()
    with patch("requests.get", return_value=mock_response):
        with pytest.raises(requests.exceptions.HTTPError):
            list(plugin.fetch_records())


def test_feedly_get_fetch_env_vars() -> None:
    """get_fetch_env_vars() must return a list containing 'LOCALIZER_FEEDLY_TOKEN'."""
    plugin = _make_plugin()
    env_vars = plugin.get_fetch_env_vars()
    assert isinstance(env_vars, list)
    # Accept either a list of strings or a list of dicts with a 'var' key
    var_names: list[str] = []
    for item in env_vars:
        if isinstance(item, str):
            var_names.append(item)
        elif isinstance(item, dict) and "var" in item:
            var_names.append(item["var"])
    assert "LOCALIZER_FEEDLY_TOKEN" in var_names, (
        f"'LOCALIZER_FEEDLY_TOKEN' not found in env var names: {var_names}"
    )


# ---------------------------------------------------------------------------
# Network I/O negative cases (mandatory per test guidance)
# ---------------------------------------------------------------------------


def test_feedly_connection_error_propagates() -> None:
    """A ConnectionError from requests must propagate, not hang."""
    plugin = _make_plugin()
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
        with pytest.raises(requests.exceptions.ConnectionError):
            list(plugin.fetch_records())


def test_feedly_connect_timeout_propagates() -> None:
    """A ConnectTimeout from requests must propagate promptly."""
    plugin = _make_plugin()
    with patch("requests.get", side_effect=requests.exceptions.ConnectTimeout("timeout")):
        with patch("time.sleep"):
            with pytest.raises((requests.exceptions.ConnectTimeout, requests.exceptions.Timeout)):
                list(plugin.fetch_records())


def test_feedly_read_timeout_propagates() -> None:
    """A ReadTimeout from requests must propagate promptly."""
    plugin = _make_plugin()
    with patch("requests.get", side_effect=requests.exceptions.ReadTimeout("timeout")):
        with patch("time.sleep"):
            with pytest.raises((requests.exceptions.ReadTimeout, requests.exceptions.Timeout)):
                list(plugin.fetch_records())


def test_feedly_explicit_timeout_passed_to_requests() -> None:
    """requests.get calls must include an explicit timeout — not None."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = EMPTY_ARTICLE_RESPONSE
    mock_response.raise_for_status.return_value = None

    plugin = _make_plugin()
    with patch("requests.get", return_value=mock_response) as mock_get:
        list(plugin.fetch_records())

    assert mock_get.called, "Expected requests.get to be called"
    call_kwargs = mock_get.call_args[1] if mock_get.call_args[1] else {}
    # timeout may be a positional arg or keyword arg
    timeout = call_kwargs.get("timeout")
    assert timeout is not None, (
        f"requests.get was called without an explicit timeout. call_args: {mock_get.call_args}"
    )


def test_feedly_malformed_response_missing_items_key() -> None:
    """When 'items' key is missing from the response body, the error must mention 'feedly'."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "user/abc/category/global.all"}  # no 'items'
    mock_response.raise_for_status.return_value = None

    plugin = _make_plugin()
    with patch("requests.get", return_value=mock_response):
        with pytest.raises(Exception, match="(?i)feedly"):
            list(plugin.fetch_records())


def test_feedly_fetched_at_is_recent() -> None:
    """fetched_at must be a Unix timestamp close to now."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = MINIMAL_TWO_ARTICLE_RESPONSE
    mock_response.raise_for_status.return_value = None

    before = int(time.time())
    plugin = _make_plugin()
    with patch("requests.get", return_value=mock_response):
        records = list(plugin.fetch_records())
    after = int(time.time())

    for record in records:
        assert isinstance(record["fetched_at"], int)
        assert before - 5 <= record["fetched_at"] <= after + 5, (
            f"fetched_at {record['fetched_at']} not close to now ({before}–{after})"
        )
