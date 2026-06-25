"""Plugin registry for localizer.

Plugins self-register by applying the ``@register`` decorator to their
``SourcePlugin`` subclass. The registry is keyed by ``PLUGIN_ID``.

Usage::

    from localizer.plugins import REGISTRY, register
    from localizer.plugins.base import SourcePlugin

    @register
    class MyPlugin(SourcePlugin):
        PLUGIN_ID = "my_plugin"
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from localizer.plugins.base import SourcePlugin

REGISTRY: dict[str, type[SourcePlugin]] = {}


def register(cls: type[SourcePlugin]) -> type[SourcePlugin]:
    """Register a SourcePlugin subclass in the global registry.

    Args:
        cls: SourcePlugin subclass to register.

    Returns:
        The class unchanged (decorator pattern).
    """
    REGISTRY[cls.PLUGIN_ID] = cls
    return cls


def load_builtin_plugins() -> None:
    """Import built-in plugins so they self-register via @register.

    Call this once at application startup before reading REGISTRY.
    Actual plugin imports are added in later subtasks (3+).
    """
    pass
