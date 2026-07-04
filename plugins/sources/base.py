"""Re-export shim — localizer is now the canonical source of SourcePlugin.

All autobiographer code should import from ``localizer.plugins.base`` directly.
This module is kept for backwards compatibility with external code that
imports from ``plugins.sources.base``.

``validate_schema``, ``_LegacyAutoPlugin``, and related helpers are
autobiographer-specific and remain here for backwards compatibility.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin

# Required columns per legacy plugin type. Validated at load time.
_REQUIRED_COLUMNS: dict[str, list[str]] = {
    "what-when": ["timestamp", "label", "sublabel", "category", "source_id"],
    "where-when": ["timestamp", "lat", "lng", "place_name", "place_type", "source_id"],
}


def validate_schema(df: pd.DataFrame, plugin_type: str) -> None:
    """Raise ValueError if df is missing required columns for plugin_type.

    Args:
        df: DataFrame returned by a plugin's load() method.
        plugin_type: Either "what-when" or "where-when".

    Raises:
        ValueError: If any required column is absent from df.
    """
    required = _REQUIRED_COLUMNS.get(plugin_type, [])
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Plugin type '{plugin_type}' is missing required columns: {missing}")


class _LegacyAutoPlugin(SourcePlugin):
    """Base class that adds autobiographer-era helper methods to localizer SourcePlugin.

    These methods (get_health_status, get_versioned_output_path) were part of
    the original autobiographer SourcePlugin ABC. They remain here so that
    legacy autobiographer plugins continue to work during the migration period.

    Concrete subclasses must still implement ``get_config_fields()`` and
    ``fetch_records()`` to satisfy the localizer SourcePlugin ABC.
    """

    FETCHABLE: bool = False
    """True if this plugin can programmatically retrieve data from its source."""

    def get_health_status(  # noqa: PLR0912
        self, config: dict[str, Any], history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Return health status derived from the current config and fetch history.

        Args:
            config: Dict of field_key → value from the plugin's config fields.
            history: Fetch history list from ``LocalSettings.get_fetch_history()``.

        Returns:
            Dict with keys ``status``, ``record_count`` (int or None),
            ``last_fetch`` (ISO string or None), ``data_path`` (str or None).
        """
        from core.analysis_loader import _count_records_at_path  # noqa: PLC0415

        fields = self.get_config_fields()
        primary_key = fields[0]["key"] if fields else None
        data_path = config.get(primary_key, "").strip() if primary_key else ""

        def _result(status: str, rc: int | None = None, lf: str | None = None) -> dict[str, Any]:
            return {
                "status": status,
                "record_count": rc,
                "last_fetch": lf,
                "data_path": data_path,
            }

        if not data_path:
            return {
                "status": "unconfigured",
                "record_count": None,
                "last_fetch": None,
                "data_path": None,
            }

        if not os.path.exists(data_path):
            return _result("error")

        record_count: int | None = _count_records_at_path(data_path)
        last_fetch: str | None = None
        if history:
            last_fetch = history[0].get("timestamp")

        if not self.FETCHABLE:
            if not last_fetch:
                try:
                    ctime = os.path.getctime(data_path)
                    last_fetch = datetime.fromtimestamp(ctime, tz=timezone.utc).isoformat()
                except OSError:
                    pass
            return _result("healthy", record_count, last_fetch)

        stale_seconds = int(os.getenv("AUTOBIO_STALE_THRESHOLD_HOURS", "24")) * 3600
        now = datetime.now(tz=timezone.utc)

        if last_fetch:
            try:
                last_dt = datetime.fromisoformat(last_fetch)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                elapsed = (now - last_dt).total_seconds()
                status = "stale" if elapsed > stale_seconds else "healthy"
            except ValueError:
                status = "healthy"
        else:
            try:
                mtime = os.path.getmtime(data_path)
                last_mtime = datetime.fromtimestamp(mtime, tz=timezone.utc)
                last_fetch = last_mtime.isoformat()
                elapsed = (now - last_mtime).total_seconds()
                status = "stale" if elapsed > stale_seconds else "healthy"
            except OSError:
                status = "healthy"

        return _result(status, record_count, last_fetch)

    def get_default_output_path(self) -> str | None:
        """Return the default path where fetched data will be saved.

        Override in subclasses that write to a fixed default location.

        Returns:
            Absolute or project-relative path string, or None.
        """
        return None

    def get_versioned_output_path(self) -> str:
        """Return a timestamped file path for a new fetch snapshot.

        Returns:
            Path string with format ``<base>_<YYYY-MM-DDTHHMMSS><ext>``.
        """
        ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        default = self.get_default_output_path()
        if default:
            base, ext = os.path.splitext(default)
            return f"{base}_{ts}{ext or '.csv'}"
        return f"data/{self.PLUGIN_ID}/{self.PLUGIN_ID}_{ts}.csv"


__all__ = [
    "FetchMode",
    "OutputTable",
    "SourcePlugin",
    "_LegacyAutoPlugin",
    "validate_schema",
]
