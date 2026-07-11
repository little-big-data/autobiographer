"""Evolved SourcePlugin ABC for the localizer package.

Replaces autobiographer's ``plugins/sources/base.py`` ABC with an updated
interface that uses ``FetchMode`` and ``OutputTable`` enums, and introduces
``fetch_records()`` as the canonical data-production method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from enum import Enum
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    pass


class FetchMode(Enum):
    """How a plugin retrieves its data."""

    API = "api"
    PLAYWRIGHT = "playwright"
    MANUAL = "manual"


class OutputTable(Enum):
    """Which DuckDB table a plugin writes to."""

    EVENTS = "events"
    PLACES = "places"
    CONTENT = "content"


class SourcePlugin(ABC):
    """Evolved base class for all localizer data-source plugins.

    Subclasses must declare ``PLUGIN_ID`` and ``DISPLAY_NAME`` as class
    attributes, and implement ``get_config_fields()`` and ``fetch_records()``.

    Class attributes:
        PLUGIN_ID: Unique string identifier (e.g. ``"lastfm"``).
        DISPLAY_NAME: Human-readable name shown in the UI.
        OUTPUT_TABLES: DuckDB tables this plugin writes to.
        FETCH_MODE: How data is retrieved (API, Playwright, or manual export).
        ICON: Material icon token for the sidebar.
    """

    PLUGIN_ID: str
    DISPLAY_NAME: str
    OUTPUT_TABLES: list[OutputTable] = []
    FETCH_MODE: FetchMode = FetchMode.MANUAL
    ICON: str = ":material/database:"

    @abstractmethod
    def get_config_fields(self) -> list[dict[str, Any]]:
        """Declare sidebar config fields required by this plugin.

        Returns:
            List of field descriptor dicts, each with at minimum ``key``,
            ``label``, and ``type``.
        """

    @abstractmethod
    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized records from the source.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional callback invoked with ``(current, total)``
                for progress reporting.

        Yields:
            Dicts with keys matching the target ``OutputTable`` schema.
        """

    # ------------------------------------------------------------------
    # Optional (non-abstract) stubs — override in concrete plugins
    # ------------------------------------------------------------------

    def fetch_secondary_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield records for a plugin's *second* ``OUTPUT_TABLES`` entry.

        Most plugins declare exactly one entry in ``OUTPUT_TABLES`` and never
        need this — ``fetch_records()`` alone is their whole output. A
        dual-output plugin (e.g. ``FlickrPlugin``, which emits both
        ``PLACES`` and ``EVENTS`` from a single import: geotagged photos as
        places, every photo as a timeline event) overrides this to yield the
        second output table's records independently of ``fetch_records()``'s
        primary stream, so the two shapes never have to be interleaved into
        one generator.

        Args:
            since: Optional Unix timestamp; yield only records newer than this.
            progress_cb: Optional callback invoked with ``(current, total)``
                for progress reporting.

        Returns:
            Empty iterator by default.
        """
        return iter([])

    def get_playwright_script(self) -> str | None:
        """Return a Playwright script string for PLAYWRIGHT-mode plugins.

        Returns:
            Script source as a string, or None if not applicable.
        """
        return None

    def get_manual_download_instructions(self) -> str:
        """Return human-readable instructions for obtaining this plugin's data.

        Returns:
            Multi-line instruction string.
        """
        return (
            f"{self.DISPLAY_NAME} data must be obtained manually. "
            "Please refer to the source's documentation for export options, "
            "then point the plugin's config field at the downloaded file."
        )

    def get_fetch_env_vars(self) -> list[dict[str, str]]:
        """Return environment variables required to fetch data for this plugin.

        Returns:
            List of dicts with ``var`` and ``description`` keys.
        """
        return []

    def get_fetch_identity(self) -> str | None:
        """Return a short string identifying the account being fetched.

        Returns:
            Human-readable identity string (e.g. ``"@username"``), or None.
        """
        return None

    def get_health_status(self, sync_state: dict[str, Any]) -> dict[str, Any]:
        """Return health status derived from the current sync state.

        Args:
            sync_state: Dict from ``LocalizerStore.get_sync_state()``.

        Returns:
            Dict with at minimum a ``status`` key.
        """
        return {"status": "unknown"}

    def load(self, config: dict[str, Any]) -> pd.DataFrame:  # TODO(subtask-7): remove
        """Backwards-compat shim: return data from LocalizerStore when available.

        Falls back to an empty DataFrame when the store is not yet implemented.

        Args:
            config: Legacy config dict (ignored in the new path).

        Returns:
            DataFrame from DuckDB, or empty DataFrame if store unavailable.
        """
        try:
            from localizer.store.db import LocalizerStore  # noqa: PLC0415

            with LocalizerStore() as store:
                return store.query_events(source_id=self.PLUGIN_ID)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
