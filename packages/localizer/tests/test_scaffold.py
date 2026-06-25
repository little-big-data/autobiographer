"""Scaffold tests for the localizer package skeleton (Subtask 1).

These tests verify the package version, the FetchMode and OutputTable enums,
the evolved SourcePlugin ABC enforcement, the @register decorator, and the
load_builtin_plugins stub. Every test in this file is expected to FAIL (RED)
until the coder agent creates the packages/localizer/ production code.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Version tests
# ---------------------------------------------------------------------------


def test_version_is_string() -> None:
    """localizer.__version__ must be a str."""
    import localizer  # type: ignore[import-not-found]

    assert isinstance(localizer.__version__, str)


def test_version_value() -> None:
    """localizer.__version__ must equal '0.1.0'."""
    import localizer  # type: ignore[import-not-found]

    assert localizer.__version__ == "0.1.0"


# ---------------------------------------------------------------------------
# FetchMode enum tests
# ---------------------------------------------------------------------------


def test_fetchmode_api_value() -> None:
    """FetchMode.API must have string value 'api'."""
    from localizer.plugins.base import FetchMode  # type: ignore[import-not-found]

    assert FetchMode.API.value == "api"


def test_fetchmode_playwright_value() -> None:
    """FetchMode.PLAYWRIGHT must have string value 'playwright'."""
    from localizer.plugins.base import FetchMode  # type: ignore[import-not-found]

    assert FetchMode.PLAYWRIGHT.value == "playwright"


def test_fetchmode_manual_value() -> None:
    """FetchMode.MANUAL must have string value 'manual'."""
    from localizer.plugins.base import FetchMode  # type: ignore[import-not-found]

    assert FetchMode.MANUAL.value == "manual"


def test_fetchmode_all_distinct() -> None:
    """All three FetchMode member values must be pairwise distinct strings."""
    from localizer.plugins.base import FetchMode  # type: ignore[import-not-found]

    values = [m.value for m in FetchMode]
    assert len(values) == len(set(values)), f"FetchMode members are not all distinct: {values}"
    # Also confirm the three expected members are present
    assert FetchMode.API.value != FetchMode.PLAYWRIGHT.value
    assert FetchMode.API.value != FetchMode.MANUAL.value
    assert FetchMode.PLAYWRIGHT.value != FetchMode.MANUAL.value


# ---------------------------------------------------------------------------
# OutputTable enum tests
# ---------------------------------------------------------------------------


def test_outputtable_events_value() -> None:
    """OutputTable.EVENTS must have string value 'events'."""
    from localizer.plugins.base import OutputTable  # type: ignore[import-not-found]

    assert OutputTable.EVENTS.value == "events"


def test_outputtable_places_value() -> None:
    """OutputTable.PLACES must have string value 'places'."""
    from localizer.plugins.base import OutputTable  # type: ignore[import-not-found]

    assert OutputTable.PLACES.value == "places"


def test_outputtable_content_value() -> None:
    """OutputTable.CONTENT must have string value 'content'."""
    from localizer.plugins.base import OutputTable  # type: ignore[import-not-found]

    assert OutputTable.CONTENT.value == "content"


# ---------------------------------------------------------------------------
# SourcePlugin ABC enforcement tests
# ---------------------------------------------------------------------------


def test_sourceplugin_abstract_fetch_records() -> None:
    """Concrete subclass missing fetch_records() must raise TypeError on instantiation."""
    from localizer.plugins.base import SourcePlugin  # type: ignore[import-not-found]

    class MissingFetchRecords(SourcePlugin):  # type: ignore[misc]
        PLUGIN_ID = "missing_fetch"
        DISPLAY_NAME = "Missing fetch_records"

        def get_config_fields(self):  # type: ignore[override]
            return []

        # fetch_records() intentionally NOT implemented

    with pytest.raises(TypeError):
        MissingFetchRecords()  # type: ignore[abstract]


def test_sourceplugin_abstract_get_config_fields() -> None:
    """Concrete subclass missing get_config_fields() must raise TypeError on instantiation."""
    from localizer.plugins.base import SourcePlugin  # type: ignore[import-not-found]

    class MissingConfigFields(SourcePlugin):  # type: ignore[misc]
        PLUGIN_ID = "missing_config"
        DISPLAY_NAME = "Missing get_config_fields"

        def fetch_records(self, since=None, progress_cb=None):  # type: ignore[override]
            return iter([])

        # get_config_fields() intentionally NOT implemented

    with pytest.raises(TypeError):
        MissingConfigFields()  # type: ignore[abstract]


def test_sourceplugin_concrete_instantiates() -> None:
    """A subclass implementing both abstract methods must instantiate successfully."""
    from localizer.plugins.base import SourcePlugin  # type: ignore[import-not-found]

    class ConcretePlugin(SourcePlugin):  # type: ignore[misc]
        PLUGIN_ID = "concrete_test"
        DISPLAY_NAME = "Concrete Test Plugin"

        def get_config_fields(self):  # type: ignore[override]
            return []

        def fetch_records(self, since=None, progress_cb=None):  # type: ignore[override]
            return iter([])

    plugin = ConcretePlugin()
    assert plugin is not None


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


def test_register_decorator_adds_to_registry() -> None:
    """@register on a concrete plugin class adds it to REGISTRY under its PLUGIN_ID."""
    from localizer.plugins import REGISTRY, register  # type: ignore[import-not-found]
    from localizer.plugins.base import SourcePlugin  # type: ignore[import-not-found]

    @register
    class RegistryTestPlugin(SourcePlugin):  # type: ignore[misc]
        PLUGIN_ID = "registry_test_plugin"
        DISPLAY_NAME = "Registry Test Plugin"

        def get_config_fields(self):  # type: ignore[override]
            return []

        def fetch_records(self, since=None, progress_cb=None):  # type: ignore[override]
            return iter([])

    assert "registry_test_plugin" in REGISTRY


def test_registry_lookup_returns_plugin_class() -> None:
    """REGISTRY['test_plugin'] must return the registered class itself (not an instance)."""
    from localizer.plugins import REGISTRY, register  # type: ignore[import-not-found]
    from localizer.plugins.base import SourcePlugin  # type: ignore[import-not-found]

    @register
    class LookupTestPlugin(SourcePlugin):  # type: ignore[misc]
        PLUGIN_ID = "lookup_test_plugin"
        DISPLAY_NAME = "Lookup Test Plugin"

        def get_config_fields(self):  # type: ignore[override]
            return []

        def fetch_records(self, since=None, progress_cb=None):  # type: ignore[override]
            return iter([])

    result = REGISTRY["lookup_test_plugin"]
    assert result is LookupTestPlugin
    # Must be the class, not an instance
    assert isinstance(result, type)


# ---------------------------------------------------------------------------
# load_builtin_plugins stub test
# ---------------------------------------------------------------------------


def test_load_builtin_plugins_is_callable() -> None:
    """load_builtin_plugins must be importable and callable."""
    from localizer.plugins import load_builtin_plugins  # type: ignore[import-not-found]

    assert callable(load_builtin_plugins)
