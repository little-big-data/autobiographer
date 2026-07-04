"""Failing tests for Subtask 6: GitHubPlugin in the localizer package.

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/github/__init__.py
  - packages/localizer/src/localizer/plugins/github/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py (load_builtin_plugins)
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

# ---------------------------------------------------------------------------
# Helpers — minimal GitHub commit JSON matching the REST API schema
# ---------------------------------------------------------------------------

LONG_COMMIT_MSG = "A" * 150  # 150 chars — should be truncated to 100

MINIMAL_ONE_COMMIT_RESPONSE: list[dict[str, Any]] = [
    {
        "sha": "abcdef1234567890abcdef1234567890abcdef12",
        "commit": {
            "message": "Initial commit",
            "author": {
                "name": "Alice",
                "date": "2023-11-14T12:00:00Z",
            },
        },
        "html_url": "https://github.com/owner/repo/commit/abcdef1234567890",
    }
]

LONG_MESSAGE_COMMIT_RESPONSE: list[dict[str, Any]] = [
    {
        "sha": "deadbeef12345678deadbeef12345678deadbeef",
        "commit": {
            "message": LONG_COMMIT_MSG,
            "author": {
                "name": "Bob",
                "date": "2023-11-15T08:00:00Z",
            },
        },
        "html_url": "https://github.com/owner/repo/commit/deadbeef12345678",
    }
]

EMPTY_COMMITS_RESPONSE: list[dict[str, Any]] = []

REPO_FULL_NAME = "owner/repo"


def _make_plugin(repos: list[str] | None = None) -> Any:
    """Instantiate a GitHubPlugin with dummy credentials via env vars."""
    os.environ["LOCALIZER_GITHUB_TOKEN"] = "test_github_token"  # noqa: S105
    os.environ["LOCALIZER_GITHUB_USERNAME"] = "test_user"
    from localizer.plugins.github.loader import GitHubPlugin

    # Plugin may accept a repo list at init or read from env/config
    if repos is not None:
        try:
            return GitHubPlugin(repos=repos)
        except TypeError:
            pass
    return GitHubPlugin()


def _mock_response(data: Any, status: int = 200) -> MagicMock:
    """Build a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = data
    if status >= 400:
        mock.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status} Error", response=mock
        )
    else:
        mock.raise_for_status.return_value = None
    return mock


# ---------------------------------------------------------------------------
# ABC / registration tests
# ---------------------------------------------------------------------------


def test_github_plugin_id() -> None:
    """GitHubPlugin.PLUGIN_ID must equal 'github'."""
    from localizer.plugins.github.loader import GitHubPlugin

    assert GitHubPlugin.PLUGIN_ID == "github"


def test_github_fetch_mode() -> None:
    """GitHubPlugin.FETCH_MODE must be FetchMode.API."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.github.loader import GitHubPlugin

    assert GitHubPlugin.FETCH_MODE == FetchMode.API


def test_github_output_tables() -> None:
    """OutputTable.EVENTS must be in GitHubPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.github.loader import GitHubPlugin

    assert OutputTable.EVENTS in GitHubPlugin.OUTPUT_TABLES


def test_github_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['github'] must exist."""
    from localizer.plugins import REGISTRY, load_builtin_plugins

    REGISTRY.clear()
    load_builtin_plugins()
    assert "github" in REGISTRY, f"'github' not in REGISTRY; keys: {list(REGISTRY)}"


# ---------------------------------------------------------------------------
# fetch_records normalization tests
# ---------------------------------------------------------------------------


def test_github_fetch_records_normalized_shape() -> None:
    """fetch_records() must yield a dict with label, sublabel, category, timestamp, source_id."""
    required_keys = {
        "source_id",
        "timestamp",
        "label",
        "sublabel",
        "category",
        "raw_json",
        "fetched_at",
    }
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response(MINIMAL_ONE_COMMIT_RESPONSE)):
        records = list(plugin.fetch_records())

    assert len(records) >= 1, f"Expected at least 1 record, got {len(records)}"
    record = records[0]
    missing = required_keys - set(record.keys())
    assert not missing, f"Record missing required keys: {missing}"
    assert record["source_id"] == "github"


def test_github_label_is_repo_full_name() -> None:
    """label must equal the repo full name (owner/repo)."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response(MINIMAL_ONE_COMMIT_RESPONSE)):
        records = list(plugin.fetch_records())

    assert len(records) >= 1
    assert records[0]["label"] == REPO_FULL_NAME, (
        f"label {records[0]['label']!r} != {REPO_FULL_NAME!r}"
    )


def test_github_sublabel_is_commit_message() -> None:
    """sublabel must be the commit message (or its first 100 chars)."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response(MINIMAL_ONE_COMMIT_RESPONSE)):
        records = list(plugin.fetch_records())

    assert len(records) >= 1
    assert "Initial commit" in records[0]["sublabel"], (
        f"sublabel {records[0]['sublabel']!r} does not contain commit message"
    )


def test_github_sublabel_truncated_at_100_chars() -> None:
    """A commit message longer than 100 chars must be truncated to exactly 100 chars."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response(LONG_MESSAGE_COMMIT_RESPONSE)):
        records = list(plugin.fetch_records())

    assert len(records) >= 1
    sublabel = records[0]["sublabel"]
    assert len(sublabel) == 100, f"sublabel should be 100 chars, got {len(sublabel)}: {sublabel!r}"


def test_github_category_is_sha_prefix() -> None:
    """category must equal the first 8 characters of the commit SHA."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response(MINIMAL_ONE_COMMIT_RESPONSE)):
        records = list(plugin.fetch_records())

    assert len(records) >= 1
    sha = MINIMAL_ONE_COMMIT_RESPONSE[0]["sha"]
    assert records[0]["category"] == sha[:8], (
        f"category {records[0]['category']!r} != sha[:8] {sha[:8]!r}"
    )


def test_github_timestamp_is_int() -> None:
    """timestamp must be a Python int (Unix seconds)."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response(MINIMAL_ONE_COMMIT_RESPONSE)):
        records = list(plugin.fetch_records())

    assert len(records) >= 1
    assert isinstance(records[0]["timestamp"], int), (
        f"timestamp is {type(records[0]['timestamp'])}, expected int"
    )


def test_github_empty_events() -> None:
    """When the API returns an empty list, fetch_records() must yield nothing."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response(EMPTY_COMMITS_RESPONSE)):
        records = list(plugin.fetch_records())

    assert records == [], f"Expected empty list for empty commits, got {records}"


def test_github_missing_token_raises() -> None:
    """When LOCALIZER_GITHUB_TOKEN is not set, fetch_records() must raise EnvironmentError."""
    env_without_token = {
        k: v for k, v in os.environ.items() if k not in ("LOCALIZER_GITHUB_TOKEN",)
    }
    with patch.dict(os.environ, env_without_token, clear=True):
        from localizer.plugins.github.loader import GitHubPlugin

        plugin = GitHubPlugin()
        with pytest.raises((EnvironmentError, KeyError)):
            list(plugin.fetch_records())


def test_github_get_fetch_env_vars() -> None:
    """get_fetch_env_vars() must list LOCALIZER_GITHUB_TOKEN and LOCALIZER_GITHUB_USERNAME."""
    plugin = _make_plugin()
    env_vars = plugin.get_fetch_env_vars()
    assert isinstance(env_vars, list)
    # Accept list of strings or list of dicts with a 'var' key
    var_names: list[str] = []
    for item in env_vars:
        if isinstance(item, str):
            var_names.append(item)
        elif isinstance(item, dict) and "var" in item:
            var_names.append(item["var"])
    assert "LOCALIZER_GITHUB_TOKEN" in var_names, (
        f"'LOCALIZER_GITHUB_TOKEN' not found in {var_names}"
    )
    assert "LOCALIZER_GITHUB_USERNAME" in var_names, (
        f"'LOCALIZER_GITHUB_USERNAME' not found in {var_names}"
    )


# ---------------------------------------------------------------------------
# Round-trip test through DuckDB store
# ---------------------------------------------------------------------------


def test_github_commit_round_trips_through_store(tmp_path: Path) -> None:
    """A GitHub commit dict must survive upsert_events() / query_events() intact."""
    from localizer.store.db import LocalizerStore

    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response(MINIMAL_ONE_COMMIT_RESPONSE)):
        records = list(plugin.fetch_records())

    assert len(records) >= 1
    record = records[0]

    db_path = tmp_path / "test.duckdb"
    with LocalizerStore(path=str(db_path)) as store:
        store.upsert_events([record])
        df = store.query_events(source_id="github")

    assert len(df) == 1
    row = df.iloc[0]
    assert row["label"] == record["label"]
    assert row["sublabel"] == record["sublabel"]
    assert row["category"] == record["category"]


# ---------------------------------------------------------------------------
# Network I/O negative cases (mandatory per test guidance)
# ---------------------------------------------------------------------------


def test_github_connection_error_propagates() -> None:
    """A ConnectionError from requests must propagate, not hang."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
        with pytest.raises(requests.exceptions.ConnectionError):
            list(plugin.fetch_records())


def test_github_http_404_raises() -> None:
    """A 404 response (repo not found) must raise HTTPError with status code."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response({}, status=404)):
        with pytest.raises(requests.exceptions.HTTPError, match="404"):
            list(plugin.fetch_records())


def test_github_explicit_timeout_passed_to_requests() -> None:
    """requests.get calls must include an explicit timeout — not None."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    with patch("requests.get", return_value=_mock_response(EMPTY_COMMITS_RESPONSE)) as mock_get:
        list(plugin.fetch_records())

    assert mock_get.called, "Expected requests.get to be called"
    call_kwargs = mock_get.call_args[1] if mock_get.call_args[1] else {}
    timeout = call_kwargs.get("timeout")
    assert timeout is not None, (
        f"requests.get was called without an explicit timeout. call_args: {mock_get.call_args}"
    )


def test_github_fetched_at_is_recent() -> None:
    """fetched_at must be a Unix timestamp close to now."""
    plugin = _make_plugin(repos=[REPO_FULL_NAME])
    before = int(time.time())
    with patch("requests.get", return_value=_mock_response(MINIMAL_ONE_COMMIT_RESPONSE)):
        records = list(plugin.fetch_records())
    after = int(time.time())

    for record in records:
        assert isinstance(record["fetched_at"], int)
        assert before - 5 <= record["fetched_at"] <= after + 5, (
            f"fetched_at {record['fetched_at']} not close to now ({before}–{after})"
        )
