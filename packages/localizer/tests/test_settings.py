"""Failing tests for Subtask 5: LocalizerSettings.

All tests here are expected to FAIL (RED) until the coder implements:
  - packages/localizer/src/localizer/settings.py

Tests cover the LocalizerSettings class:
  - get_store_path() returns a Path
  - Default path ends with 'store.duckdb'
  - LOCALIZER_DB_PATH env var overrides the default store path
  - get_setting() returns None for unknown keys
  - set_setting() / get_setting() round-trip persists a value
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Import under test — will raise ImportError until settings.py is created.
# ---------------------------------------------------------------------------
from localizer.settings import LocalizerSettings  # type: ignore[import]

# ---------------------------------------------------------------------------
# 1. get_store_path returns a Path object
# ---------------------------------------------------------------------------


def test_get_store_path_returns_path_object(tmp_path: Path) -> None:
    """LocalizerSettings.get_store_path() must return a pathlib.Path instance."""
    settings = LocalizerSettings(config_path=tmp_path / "config.toml")
    result = settings.get_store_path()
    assert isinstance(result, Path), f"Expected a Path, got {type(result).__name__}: {result!r}"


# ---------------------------------------------------------------------------
# 2. Default store path ends with 'store.duckdb'
# ---------------------------------------------------------------------------


def test_get_store_path_default_ends_with_store_duckdb(tmp_path: Path) -> None:
    """Default store path must end with 'store.duckdb'."""
    settings = LocalizerSettings(config_path=tmp_path / "config.toml")
    # Ensure LOCALIZER_DB_PATH is not set so we get the default.
    env_without_db = {k: v for k, v in os.environ.items() if k != "LOCALIZER_DB_PATH"}
    with patch.dict(os.environ, env_without_db, clear=True):
        result = settings.get_store_path()
    assert str(result).endswith("store.duckdb"), (
        f"Default path must end with 'store.duckdb', got: {result}"
    )


# ---------------------------------------------------------------------------
# 3. LOCALIZER_DB_PATH env var overrides default
# ---------------------------------------------------------------------------


def test_localizer_db_path_env_override(tmp_path: Path) -> None:
    """LOCALIZER_DB_PATH env var must override the default store path."""
    custom_path = str(tmp_path / "override.duckdb")
    settings = LocalizerSettings(config_path=tmp_path / "config.toml")
    with patch.dict(os.environ, {"LOCALIZER_DB_PATH": custom_path}):
        result = settings.get_store_path()
    assert str(result) == custom_path, f"Expected LOCALIZER_DB_PATH={custom_path!r}, got: {result}"


# ---------------------------------------------------------------------------
# 4. get_setting returns None for unknown key
# ---------------------------------------------------------------------------


def test_get_setting_returns_none_for_unknown_key(tmp_path: Path) -> None:
    """get_setting() must return None for a key that has never been set."""
    settings = LocalizerSettings(config_path=tmp_path / "config.toml")
    result = settings.get_setting("definitely_not_a_real_key_xyz")
    assert result is None, f"Expected None for unknown key, got: {result!r}"


# ---------------------------------------------------------------------------
# 5. set_setting / get_setting round-trip
# ---------------------------------------------------------------------------


def test_set_and_get_setting_roundtrip(tmp_path: Path) -> None:
    """set_setting('k', 'v') followed by get_setting('k') must return 'v'."""
    config_path = tmp_path / "config.toml"
    settings = LocalizerSettings(config_path=config_path)
    settings.set_setting("mykey", "myval")
    result = settings.get_setting("mykey")
    assert result == "myval", f"Expected 'myval' after set_setting round-trip, got: {result!r}"
