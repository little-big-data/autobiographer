"""Failing tests for Subtask 7: autobiographer full cutover and dead code removal.

All tests here are expected to FAIL until the coder implements:
  - plugins/sources/base.py becomes a one-line re-export from localizer.plugins.base
  - plugins/sources/lastfm/loader.py becomes a one-line re-export
  - plugins/sources/swarm/loader.py becomes a one-line re-export
  - core/broker.py DataBroker.__init__ emits DeprecationWarning
  - components/sidebar._make_broker() always returns LocalizerBroker when store exists
  - autobiographer.Autobiographer emits DeprecationWarning or is removed
  - All subtask-7 TODO markers are removed from source files
  - pages/ modules are all importable

Tests that may already pass (partial RED is acceptable):
  - test_fetch_utils_fetchcheckpoint_is_localizer_class (re-export was done in Subtask 3)
  - test_sidebar_make_broker_returns_localizer_broker_by_default (toggle already exists)
"""

from __future__ import annotations

import importlib
import pathlib
import subprocess
import sys
import warnings

import pytest

# ---------------------------------------------------------------------------
# Import / re-export identity tests
# ---------------------------------------------------------------------------


def test_plugins_base_sourceplugin_is_localizer_class() -> None:
    """plugins.sources.base.SourcePlugin must be the exact same class as localizer's."""
    from localizer.plugins.base import SourcePlugin as LocalizerSourcePlugin

    from plugins.sources.base import SourcePlugin

    assert SourcePlugin is LocalizerSourcePlugin, (
        "plugins.sources.base.SourcePlugin is not the same object as "
        "localizer.plugins.base.SourcePlugin — the re-export shim is missing or incomplete."
    )


def test_plugins_base_fetchmode_is_localizer_class() -> None:
    """plugins.sources.base.FetchMode must be the exact same enum as localizer's."""
    from localizer.plugins.base import FetchMode as LocalizerFetchMode

    from plugins.sources.base import FetchMode  # type: ignore[attr-defined]

    assert FetchMode is LocalizerFetchMode, (
        "plugins.sources.base.FetchMode is not the same object as "
        "localizer.plugins.base.FetchMode — the re-export shim is missing or incomplete."
    )


def test_plugins_base_outputtable_is_localizer_class() -> None:
    """plugins.sources.base.OutputTable must be the exact same enum as localizer's."""
    from localizer.plugins.base import OutputTable as LocalizerOutputTable

    from plugins.sources.base import OutputTable  # type: ignore[attr-defined]

    assert OutputTable is LocalizerOutputTable, (
        "plugins.sources.base.OutputTable is not the same object as "
        "localizer.plugins.base.OutputTable — the re-export shim is missing or incomplete."
    )


def test_fetch_utils_fetchcheckpoint_is_localizer_class() -> None:
    """core.fetch_utils.FetchCheckpoint must be the same class as localizer's."""
    from localizer.fetch_utils import FetchCheckpoint as LocalizerFetchCheckpoint

    from core.fetch_utils import FetchCheckpoint

    assert FetchCheckpoint is LocalizerFetchCheckpoint, (
        "core.fetch_utils.FetchCheckpoint is not the same object as "
        "localizer.fetch_utils.FetchCheckpoint — re-export is broken."
    )


# ---------------------------------------------------------------------------
# DataBroker deprecation
# ---------------------------------------------------------------------------


def test_databroker_instantiation_emits_deprecation_warning() -> None:
    """DataBroker() must emit a DeprecationWarning on instantiation."""
    from core.broker import DataBroker

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        DataBroker()

    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecation_warnings, (
        "DataBroker() did not emit any DeprecationWarning. "
        "The coder must add `warnings.warn(..., DeprecationWarning, stacklevel=2)` "
        "to DataBroker.__init__."
    )


# ---------------------------------------------------------------------------
# LocalizerBroker as canonical broker via sidebar
# ---------------------------------------------------------------------------


def test_sidebar_make_broker_returns_localizer_broker_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_make_broker() must return a LocalizerBroker when the DuckDB store exists."""
    from localizer.store.db import LocalizerStore

    from core.broker import LocalizerBroker

    # Ensure the store appears to exist so LocalizerBroker is chosen.
    monkeypatch.setattr(
        LocalizerStore,
        "default_path",
        classmethod(lambda cls: _FakePath(exists=True)),
    )

    # _make_broker() calls LocalizerStore.default_path() at runtime — no reload needed.
    import components.sidebar as sidebar_mod

    broker = sidebar_mod._make_broker()
    assert isinstance(broker, LocalizerBroker), (
        f"_make_broker() returned {type(broker).__name__!r} instead of LocalizerBroker "
        "when the DuckDB store exists. The cutover must make LocalizerBroker the default."
    )


def test_sidebar_never_returns_databroker_when_store_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_make_broker() must NOT return a DataBroker when the DuckDB store file exists."""
    from localizer.store.db import LocalizerStore

    from core.broker import DataBroker

    monkeypatch.setattr(
        LocalizerStore,
        "default_path",
        classmethod(lambda cls: _FakePath(exists=True)),
    )

    import components.sidebar as sidebar_mod

    broker = sidebar_mod._make_broker()
    assert not isinstance(broker, DataBroker), (
        "_make_broker() returned a DataBroker even though the DuckDB store exists. "
        "After the cutover, DataBroker must never be chosen when the store is present."
    )


# ---------------------------------------------------------------------------
# Helper: fake Path object for monkeypatching default_path()
# ---------------------------------------------------------------------------


class _FakePath:
    """Minimal Path-like object whose .exists() returns a fixed value."""

    def __init__(self, exists: bool) -> None:
        self._exists = exists

    def exists(self) -> bool:
        return self._exists


# ---------------------------------------------------------------------------
# No legacy grep patterns
# ---------------------------------------------------------------------------


def _grep_plugins(pattern: str) -> str:
    """Run grep for pattern under plugins/ and return stdout."""
    result = subprocess.run(
        ["grep", "-r", pattern, "plugins/"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_no_read_csv_in_plugins() -> None:
    """plugins/ must contain no direct pd.read_csv() calls after the cutover."""
    hits = _grep_plugins("read_csv")
    assert hits == "", (
        f"Found read_csv usage in plugins/:\n{hits}\n"
        "The cutover must remove all direct CSV loading from the plugins layer."
    )


def test_no_load_listening_data_in_plugins() -> None:
    """plugins/ must contain no references to load_listening_data after the cutover."""
    hits = _grep_plugins("load_listening_data")
    assert hits == "", (
        f"Found load_listening_data in plugins/:\n{hits}\n"
        "Legacy analysis_utils loader must be removed from the plugins layer."
    )


def test_no_load_swarm_data_in_plugins() -> None:
    """plugins/ must contain no references to load_swarm_data after the cutover."""
    hits = _grep_plugins("load_swarm_data")
    assert hits == "", (
        f"Found load_swarm_data in plugins/:\n{hits}\n"
        "Legacy analysis_utils loader must be removed from the plugins layer."
    )


def test_no_load_swarm_data_in_pages() -> None:
    """pages/ must contain no references to load_swarm_data after the cutover."""
    result = subprocess.run(
        ["grep", "-r", "load_swarm_data", "pages/"],
        capture_output=True,
        text=True,
    )
    hits = result.stdout.strip()
    assert hits == "", (
        f"Found load_swarm_data in pages/:\n{hits}\n"
        "Legacy analysis_utils loader must be removed from the pages layer."
    )


def test_no_todo_subtask7_markers() -> None:
    """No source file (outside venv, packages/, and tests/) should carry a subtask-7 TODO marker."""
    # The marker text is split here to prevent this test file from matching its own scan.
    marker = "TODO" + "(subtask-7)"
    src_root = pathlib.Path(".")
    py_files = [
        f
        for f in src_root.rglob("*.py")
        if "venv" not in str(f) and "packages" not in str(f) and "tests" not in str(f)
    ]
    hits = []
    for f in py_files:
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        if marker in text:
            hits.append(str(f))

    assert not hits, (
        "The following files still contain TODO(subtask-7) markers that must be removed:\n"
        + "\n".join(hits)
    )


# ---------------------------------------------------------------------------
# All page modules are importable
# ---------------------------------------------------------------------------


def test_cutover_modules_importable() -> None:
    """Core modules modified in Subtask 7 must be importable without ImportError.

    Checks non-Streamlit modules only — importing Streamlit page modules in-process
    contaminates st.cache_data registries and breaks unrelated page tests downstream.
    """
    modules_to_check = [
        "plugins.sources.base",
        "plugins.sources.lastfm.loader",
        "plugins.sources.swarm.loader",
        "plugins.sources.assumptions.loader",
        "core.broker",
        "core.fetch_utils",
        "core.analysis_loader",
    ]
    errors: list[str] = []
    for module_name in modules_to_check:
        try:
            if module_name in sys.modules:
                del sys.modules[module_name]
            importlib.import_module(module_name)
        except ImportError as exc:
            errors.append(f"  {module_name}: {exc}")

    assert not errors, "The following cutover modules raised ImportError:\n" + "\n".join(errors)


# ---------------------------------------------------------------------------
# Legacy autobiographer shim
# ---------------------------------------------------------------------------


def test_autobiographer_class_removed_or_warns() -> None:
    """Autobiographer class must either be gone or emit DeprecationWarning on instantiation.

    After the cutover:
      Option A — class is deleted: 'from autobiographer import Autobiographer' raises ImportError.
      Option B — class is kept as shim: instantiating it emits DeprecationWarning.

    Either option is acceptable. This test fails if the class exists and instantiates
    silently (without a warning), which is the current pre-cutover state.
    """
    try:
        from autobiographer import Autobiographer
    except ImportError:
        # Option A: class was removed. This is the preferred outcome.
        return

    # Option B: class still exists. It must warn on instantiation.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            Autobiographer(api_key="x", api_secret="y", username="z")
        except Exception:  # noqa: BLE001
            # If instantiation fails for any reason, treat as non-warning and fall through.
            pass

    deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprecation_warnings, (
        "Autobiographer class exists and instantiates without emitting DeprecationWarning. "
        "The cutover must either delete the class or add a DeprecationWarning in __init__."
    )


# ---------------------------------------------------------------------------
# AC3: no legacy patterns outside the designated bridge
# ---------------------------------------------------------------------------


def test_no_legacy_patterns_outside_bridge() -> None:
    """plugins/, pages/, and core/ (excluding analysis_loader.py) must have zero legacy calls.

    core/analysis_loader.py is the designated bridge — it is intentionally allowed
    to call load_listening_data, load_swarm_data, and read_csv on behalf of callers.
    Every other file in core/, plugins/, and pages/ must be clean.
    """
    patterns = ["read_csv", "load_listening_data", "load_swarm_data"]
    bridge = pathlib.Path("core/analysis_loader.py").resolve()
    roots = [pathlib.Path("plugins"), pathlib.Path("core"), pathlib.Path("pages")]
    hits: list[str] = []
    for root in roots:
        for py_file in root.rglob("*.py"):
            if py_file.resolve() == bridge:
                continue
            try:
                text = py_file.read_text(errors="ignore")
            except OSError:
                continue
            for pat in patterns:
                if pat in text:
                    hits.append(f"{py_file}: {pat}")
    assert not hits, (
        "Legacy analysis_utils patterns found outside the designated bridge "
        "(core/analysis_loader.py):\n" + "\n".join(hits)
    )


# ---------------------------------------------------------------------------
# localizer sync integration smoke test
# ---------------------------------------------------------------------------


def test_localizer_sync_writes_to_store(tmp_path: pathlib.Path) -> None:
    """localizer sync must write records to events and places tables.

    Uses mocked fetch_records() so no network calls are made.
    """
    import os
    from unittest.mock import patch

    from click.testing import CliRunner
    from localizer.cli import cli
    from localizer.store.db import LocalizerStore

    db_path = tmp_path / "store.duckdb"

    event_record = {
        "source_id": "lastfm",
        "timestamp": 1_700_000_000,
        "label": "Test Artist",
        "sublabel": "Test Track",
        "category": "Test Album",
        "raw_json": "{}",
        "fetched_at": 1_700_000_000,
    }
    place_record = {
        "source_id": "swarm",
        "timestamp": 1_700_000_001,
        "lat": 51.5,
        "lng": -0.1,
        "place_name": "Test Venue",
        "place_type": "bar",
        "raw_json": "{}",
        "fetched_at": 1_700_000_001,
    }

    with (
        patch(
            "localizer.plugins.lastfm.loader.LastFmPlugin.fetch_records",
            return_value=iter([event_record]),
        ),
        patch(
            "localizer.plugins.swarm.loader.SwarmPlugin.fetch_records",
            return_value=iter([place_record]),
        ),
    ):
        env = {**os.environ, "LOCALIZER_DB_PATH": str(db_path)}
        runner = CliRunner(env=env)
        result = runner.invoke(cli, ["sync"])

    assert result.exit_code == 0, f"localizer sync failed:\n{result.output}"

    store = LocalizerStore(path=db_path)
    events_df = store.query_events("lastfm")
    places_df = store.query_places("swarm")
    assert len(events_df) >= 1, "No events written to store after sync"
    assert len(places_df) >= 1, "No places written to store after sync"
