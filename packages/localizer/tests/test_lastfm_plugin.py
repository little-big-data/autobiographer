"""Failing tests for Subtask 3: fetch_utils.py port and LastFm plugin.

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/fetch_utils.py
  - packages/localizer/src/localizer/plugins/lastfm/__init__.py
  - packages/localizer/src/localizer/plugins/lastfm/fetcher.py
  - packages/localizer/src/localizer/plugins/lastfm/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py
  - core/fetch_utils.py re-export shim
  - autobiographer.py delegation to LastFmFetcher
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
import requests
import responses as responses_lib

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LASTFM_BASE_URL = "http://ws.audioscrobbler.com/2.0/"

MINIMAL_TWO_TRACK_RESPONSE: dict[str, Any] = {
    "recenttracks": {
        "track": [
            {
                "name": "Track1",
                "artist": {"#text": "Artist1"},
                "album": {"#text": "Album1"},
                "date": {"uts": "1000"},
            },
            {
                "name": "Track2",
                "artist": {"#text": "Artist2"},
                "album": {"#text": "Album2"},
                "date": {"uts": "2000"},
            },
        ],
        "@attr": {"totalPages": "1"},
    }
}

MINIMAL_EMPTY_RESPONSE: dict[str, Any] = {
    "recenttracks": {
        "track": [],
        "@attr": {"totalPages": "1"},
    }
}


def _make_plugin() -> Any:
    """Instantiate a LastFmPlugin with dummy credentials via env vars."""
    import os

    os.environ.setdefault("AUTOBIO_LASTFM_API_KEY", "test_key")
    os.environ.setdefault("AUTOBIO_LASTFM_API_SECRET", "test_secret")
    os.environ.setdefault("AUTOBIO_LASTFM_USERNAME", "test_user")

    from localizer.plugins.lastfm.loader import LastFmPlugin

    return LastFmPlugin()


# ===========================================================================
# Group 1 — fetch_utils import and identity tests
# ===========================================================================


def test_fetch_utils_importable_from_localizer() -> None:
    """FetchCheckpoint and retry_with_backoff must be importable from localizer.fetch_utils."""
    from localizer.fetch_utils import FetchCheckpoint, retry_with_backoff  # noqa: F401


def test_fetch_checkpoint_class_exists() -> None:
    """FetchCheckpoint must be a class."""
    from localizer.fetch_utils import FetchCheckpoint

    assert isinstance(FetchCheckpoint, type)


def test_retry_with_backoff_callable() -> None:
    """retry_with_backoff must be callable."""
    from localizer.fetch_utils import retry_with_backoff

    assert callable(retry_with_backoff)


# ===========================================================================
# Group 2 — LastFmPlugin ABC compliance
# ===========================================================================


def test_lastfm_plugin_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['lastfm'] must exist."""
    from localizer.plugins import REGISTRY, load_builtin_plugins

    load_builtin_plugins()
    assert "lastfm" in REGISTRY, f"'lastfm' not in REGISTRY; keys: {list(REGISTRY)}"


def test_lastfm_plugin_plugin_id() -> None:
    """LastFmPlugin.PLUGIN_ID must equal 'lastfm'."""
    from localizer.plugins.lastfm.loader import LastFmPlugin

    assert LastFmPlugin.PLUGIN_ID == "lastfm"


def test_lastfm_plugin_fetch_mode_api() -> None:
    """LastFmPlugin.FETCH_MODE must be FetchMode.API."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.lastfm.loader import LastFmPlugin

    assert LastFmPlugin.FETCH_MODE == FetchMode.API


def test_lastfm_plugin_output_tables_events() -> None:
    """OutputTable.EVENTS must appear in LastFmPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.lastfm.loader import LastFmPlugin

    assert OutputTable.EVENTS in LastFmPlugin.OUTPUT_TABLES


def test_lastfm_plugin_get_config_fields_returns_list() -> None:
    """get_config_fields() must return a list (may be empty for env-var-driven plugins)."""
    plugin = _make_plugin()
    result = plugin.get_config_fields()
    assert isinstance(result, list)


def test_lastfm_plugin_get_fetch_env_vars() -> None:
    """get_fetch_env_vars() must include at least one dict with a 'var' key mentioning LASTFM."""
    plugin = _make_plugin()
    env_vars = plugin.get_fetch_env_vars()
    assert isinstance(env_vars, list)
    assert len(env_vars) >= 1, "Expected at least one env var descriptor"
    var_names = [v["var"] for v in env_vars if "var" in v]
    matching = [v for v in var_names if "LASTFM" in v or "AUTOBIO_LASTFM" in v]
    assert matching, f"No LASTFM env var found among: {var_names}"


# ===========================================================================
# Group 3 — fetch_records normalization
# ===========================================================================


@responses_lib.activate
def test_fetch_records_yields_dicts() -> None:
    """fetch_records() must yield exactly 2 dicts for a 2-track mocked response."""
    responses_lib.add(
        responses_lib.GET,
        LASTFM_BASE_URL,
        json=MINIMAL_TWO_TRACK_RESPONSE,
        status=200,
    )
    plugin = _make_plugin()
    records = list(plugin.fetch_records())
    assert len(records) == 2, f"Expected 2 records, got {len(records)}"


@responses_lib.activate
def test_fetch_records_dict_has_required_keys() -> None:
    """Each yielded dict must contain all required keys."""
    required_keys = {
        "source_id",
        "timestamp",
        "label",
        "sublabel",
        "category",
        "raw_json",
        "fetched_at",
    }
    responses_lib.add(
        responses_lib.GET,
        LASTFM_BASE_URL,
        json=MINIMAL_TWO_TRACK_RESPONSE,
        status=200,
    )
    plugin = _make_plugin()
    for record in plugin.fetch_records():
        missing = required_keys - set(record.keys())
        assert not missing, f"Record missing keys: {missing}. Got: {set(record.keys())}"


@responses_lib.activate
def test_fetch_records_source_id_is_lastfm() -> None:
    """Each record's source_id must equal 'lastfm'."""
    responses_lib.add(
        responses_lib.GET,
        LASTFM_BASE_URL,
        json=MINIMAL_TWO_TRACK_RESPONSE,
        status=200,
    )
    plugin = _make_plugin()
    for record in plugin.fetch_records():
        assert record["source_id"] == "lastfm", f"source_id was {record['source_id']!r}"


@responses_lib.activate
def test_fetch_records_label_is_artist() -> None:
    """record['label'] must match the artist name from the API response."""
    responses_lib.add(
        responses_lib.GET,
        LASTFM_BASE_URL,
        json=MINIMAL_TWO_TRACK_RESPONSE,
        status=200,
    )
    plugin = _make_plugin()
    records = list(plugin.fetch_records())
    artist_names = {"Artist1", "Artist2"}
    for record in records:
        assert record["label"] in artist_names, f"label {record['label']!r} not in {artist_names}"


@responses_lib.activate
def test_fetch_records_sublabel_is_track() -> None:
    """record['sublabel'] must match the track name from the API response."""
    responses_lib.add(
        responses_lib.GET,
        LASTFM_BASE_URL,
        json=MINIMAL_TWO_TRACK_RESPONSE,
        status=200,
    )
    plugin = _make_plugin()
    records = list(plugin.fetch_records())
    track_names = {"Track1", "Track2"}
    for record in records:
        assert record["sublabel"] in track_names, (
            f"sublabel {record['sublabel']!r} not in {track_names}"
        )


@responses_lib.activate
def test_fetch_records_timestamp_is_int() -> None:
    """record['timestamp'] must be an int (Unix timestamp)."""
    responses_lib.add(
        responses_lib.GET,
        LASTFM_BASE_URL,
        json=MINIMAL_TWO_TRACK_RESPONSE,
        status=200,
    )
    plugin = _make_plugin()
    for record in plugin.fetch_records():
        assert isinstance(record["timestamp"], int), (
            f"timestamp is {type(record['timestamp'])}, expected int"
        )


@responses_lib.activate
def test_fetch_records_empty_when_no_tracks() -> None:
    """fetch_records() must yield nothing when the API returns an empty track list."""
    responses_lib.add(
        responses_lib.GET,
        LASTFM_BASE_URL,
        json=MINIMAL_EMPTY_RESPONSE,
        status=200,
    )
    plugin = _make_plugin()
    records = list(plugin.fetch_records())
    assert records == [], f"Expected empty list, got {records}"


# ===========================================================================
# Group 4 — Error handling
# ===========================================================================


def test_fetch_records_connection_error_propagates() -> None:
    """A ConnectionError from requests must propagate — not be silently swallowed."""
    plugin = _make_plugin()
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
        with patch("time.sleep"):
            with pytest.raises(requests.exceptions.ConnectionError):
                next(iter(plugin.fetch_records()))


@responses_lib.activate
def test_fetch_records_non_200_response() -> None:
    """A 403 response from the API must raise HTTPError containing the status code."""
    responses_lib.add(
        responses_lib.GET,
        LASTFM_BASE_URL,
        json={"error": 10, "message": "Invalid API key"},
        status=403,
    )
    plugin = _make_plugin()
    with pytest.raises(requests.exceptions.HTTPError, match="403"):
        next(iter(plugin.fetch_records()))


def test_fetch_records_connect_timeout_retries() -> None:
    """ConnectTimeout must trigger retry_with_backoff retries before propagating."""
    plugin = _make_plugin()
    with patch(
        "requests.get", side_effect=requests.exceptions.ConnectTimeout("timeout")
    ) as mock_get:
        with patch("time.sleep"):
            with pytest.raises(requests.exceptions.ConnectTimeout):
                list(plugin.fetch_records())
    # retry_with_backoff calls fn() max_retries+1 times (default max_retries=3 → 4 calls)
    assert mock_get.call_count > 1, (
        f"Expected more than 1 call (retries should fire), got {mock_get.call_count}"
    )


def test_fetch_records_read_timeout_retries() -> None:
    """ReadTimeout must trigger retry_with_backoff retries before propagating."""
    plugin = _make_plugin()
    with patch("requests.get", side_effect=requests.exceptions.ReadTimeout("timeout")) as mock_get:
        with patch("time.sleep"):
            with pytest.raises(requests.exceptions.ReadTimeout):
                list(plugin.fetch_records())
    # retry_with_backoff calls fn() max_retries+1 times (default max_retries=3 → 4 calls)
    assert mock_get.call_count > 1, (
        f"Expected more than 1 call (retries should fire), got {mock_get.call_count}"
    )


# ===========================================================================
# Group 5 — Backwards-compat re-export shim
# ===========================================================================


def test_core_fetch_utils_re_exports_fetchcheckpoint() -> None:
    """'from core.fetch_utils import FetchCheckpoint' must work after the shim is in place."""
    from core.fetch_utils import FetchCheckpoint  # noqa: F401


def test_re_export_is_same_class() -> None:
    """FetchCheckpoint from core.fetch_utils and localizer.fetch_utils must be the same object."""
    from localizer.fetch_utils import FetchCheckpoint as LocalizerFC

    from core.fetch_utils import FetchCheckpoint as CoreFC

    assert CoreFC is LocalizerFC, (
        "core.fetch_utils.FetchCheckpoint is not the same object as "
        "localizer.fetch_utils.FetchCheckpoint — re-export shim is broken"
    )
