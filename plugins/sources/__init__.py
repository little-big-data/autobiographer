"""Source plugin registry.

Plugins self-register by applying the @register decorator to their
SourcePlugin subclass. The registry is keyed by PLUGIN_ID.

Usage::

    from plugins.sources import REGISTRY, register
    from plugins.sources.base import SourcePlugin

    @register
    class MyPlugin(SourcePlugin):
        PLUGIN_ID = "my_plugin"
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins.sources.base import SourcePlugin

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
    """
    import plugins.sources.assumptions.loader  # noqa: F401
    import plugins.sources.google_timeline.loader  # noqa: F401
    import plugins.sources.lastfm.loader  # noqa: F401
    import plugins.sources.swarm.loader  # noqa: F401
