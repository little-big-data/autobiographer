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
    """Ensure all built-in plugins are present in REGISTRY.

    Safe to call multiple times and after REGISTRY.clear() — always
    re-registers, because @register only fires on first module import.
    """
    from localizer.plugins.feedly.loader import FeedlyPlugin
    from localizer.plugins.github.loader import GitHubPlugin
    from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin
    from localizer.plugins.lastfm.loader import LastFmPlugin
    from localizer.plugins.letterboxd.loader import LetterboxdPlugin
    from localizer.plugins.rss.loader import RssPlugin
    from localizer.plugins.swarm.loader import SwarmPlugin

    REGISTRY[LastFmPlugin.PLUGIN_ID] = LastFmPlugin
    REGISTRY[SwarmPlugin.PLUGIN_ID] = SwarmPlugin
    REGISTRY[FeedlyPlugin.PLUGIN_ID] = FeedlyPlugin
    REGISTRY[GitHubPlugin.PLUGIN_ID] = GitHubPlugin
    REGISTRY[RssPlugin.PLUGIN_ID] = RssPlugin
    REGISTRY[LetterboxdPlugin.PLUGIN_ID] = LetterboxdPlugin
    REGISTRY[GoogleTimelinePlugin.PLUGIN_ID] = GoogleTimelinePlugin
