"""DataBroker: loads, aligns, and merges data from registered source plugins.

The DataBroker is the central data coordinator. It holds loaded DataFrames
from each plugin, tracks which source types are available, and provides a
merged DataFrame that combines what-when and where-when sources via temporal
join (powered by apply_swarm_offsets for the Swarm/Last.fm case).

Typical usage::

    from plugins.sources import load_builtin_plugins, REGISTRY
    from plugins.sources.base import SourcePlugin
    from core.broker import DataBroker

    load_builtin_plugins()

    broker = DataBroker()
    broker.load(REGISTRY["lastfm"], {"data_path": "data/tracks.csv"})
    broker.load(REGISTRY["swarm"], {"swarm_dir": "data/swarm"})

    df = broker.get_merged_frame(assumptions=assumptions)
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from plugins.sources.base import SourcePlugin


class DataBroker:
    """Coordinates loading and merging of multiple source plugins.

    Attributes:
        _sources: Loaded DataFrames keyed by plugin PLUGIN_ID.
        _available_types: Distinct PLUGIN_TYPE values of loaded sources.
    """

    def __init__(self) -> None:
        warnings.warn(
            "DataBroker is deprecated and will be removed in a future version. "
            "Use LocalizerBroker instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._sources: dict[str, pd.DataFrame] = {}
        self._available_types: list[str] = []

    @property
    def available_types(self) -> list[str]:
        """Return list of distinct plugin types currently loaded.

        Returns:
            List of strings, each either "what-when" or "where-when".
        """
        return list(self._available_types)

    def load(self, plugin: SourcePlugin, config: dict[str, Any]) -> pd.DataFrame:
        """Load a source plugin and store the resulting DataFrame.

        Args:
            plugin: An instantiated SourcePlugin subclass.
            config: Config dict matching the plugin's get_config_fields() keys.

        Returns:
            The DataFrame returned by the plugin (may be empty on failure).
        """
        df = plugin.load(config)
        self._sources[plugin.PLUGIN_ID] = df
        if plugin.PLUGIN_TYPE not in self._available_types:
            self._available_types.append(plugin.PLUGIN_TYPE)
        return df

    def get_frame(self, plugin_id: str) -> pd.DataFrame:
        """Return the raw loaded DataFrame for a given plugin.

        Args:
            plugin_id: The PLUGIN_ID of the desired source.

        Returns:
            The loaded DataFrame, or an empty DataFrame if not loaded.
        """
        return self._sources.get(plugin_id, pd.DataFrame())

    def get_frames(self) -> dict[str, pd.DataFrame]:
        """Return all loaded DataFrames keyed by plugin ID.

        Returns:
            Dict of {plugin_id: DataFrame}.
        """
        return dict(self._sources)

    def get_merged_frame(self, assumptions: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return a merged DataFrame combining what-when and where-when sources.

        If both a what-when source (Last.fm) and a where-when source (Swarm)
        are loaded, applies temporal merging via apply_swarm_offsets() to
        annotate what-when records with location and timezone data.

        If only a what-when source is loaded, returns it unmodified.
        If no what-when source is loaded, returns an empty DataFrame.

        Args:
            assumptions: Location assumptions dict from load_assumptions().
                         Required for the Swarm temporal join; pass None to
                         skip location enrichment.

        Returns:
            Merged DataFrame, or the raw what-when frame if no where-when
            source is available.
        """
        lastfm_df = self._sources.get("lastfm", pd.DataFrame())

        if lastfm_df.empty:
            return lastfm_df

        swarm_df = self._sources.get("swarm", pd.DataFrame())

        if swarm_df.empty or assumptions is None:
            return lastfm_df

        from analysis_utils import apply_swarm_offsets

        return apply_swarm_offsets(lastfm_df, swarm_df, assumptions)

    def is_type_available(self, plugin_type: str) -> bool:
        """Check whether any loaded source provides the given plugin type.

        Args:
            plugin_type: Either "what-when" or "where-when".

        Returns:
            True if at least one loaded source has the given type.
        """
        return plugin_type in self._available_types


class LocalizerBroker:
    """DataBroker backed by localizer's DuckDB store instead of flat files.

    Exposes the same public interface as DataBroker so callers can be switched
    transparently when the DuckDB store is present.

    Args:
        store_path: Path to the DuckDB file. Defaults to
            ``~/.localizer/store.duckdb``.
    """

    def __init__(self, store_path: str | Path | None = None) -> None:
        self._store_path: Path | None = Path(store_path) if store_path else None
        self._available_types: list[str] = []
        # Populate available_types eagerly so is_type_available() works without
        # calling load() first.
        self._refresh_available_types()

    def _open_store(self) -> Any:
        """Open and return a LocalizerStore instance.

        Returns:
            An open ``LocalizerStore`` context manager.
        """
        from localizer.store.db import LocalizerStore  # noqa: PLC0415

        return LocalizerStore(path=self._store_path)

    def _refresh_available_types(self) -> None:
        """Query the store to discover which type categories have data."""
        try:
            with self._open_store() as store:
                events = store.query_events()
                places = store.query_places()
        except Exception:  # noqa: BLE001
            return

        self._available_types = []
        if not events.empty and "what-when" not in self._available_types:
            self._available_types.append("what-when")
        if not places.empty and "where-when" not in self._available_types:
            self._available_types.append("where-when")

    @property
    def available_types(self) -> list[str]:
        """Return list of distinct plugin types with data in the store.

        Returns:
            List of strings, each either ``"what-when"`` or ``"where-when"``.
        """
        return list(self._available_types)

    def load(self, plugin: Any, config: dict[str, Any]) -> pd.DataFrame:
        """Load plugin data from DuckDB (config file paths are ignored).

        Args:
            plugin: An instantiated localizer ``SourcePlugin`` subclass.
            config: Config dict (ignored — all data comes from DuckDB).

        Returns:
            DataFrame queried from the appropriate DuckDB table.
        """
        from localizer.plugins.base import OutputTable  # noqa: PLC0415

        try:
            with self._open_store() as store:
                if hasattr(plugin, "OUTPUT_TABLES") and OutputTable.PLACES in plugin.OUTPUT_TABLES:
                    df = store.query_places(source_id=plugin.PLUGIN_ID)
                    if not df.empty and "where-when" not in self._available_types:
                        self._available_types.append("where-when")
                else:
                    df = store.query_events(source_id=getattr(plugin, "PLUGIN_ID", None))
                    if not df.empty and "what-when" not in self._available_types:
                        self._available_types.append("what-when")
            return df
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def get_frame(self, plugin_id: str) -> pd.DataFrame:
        """Return events or places for a plugin_id, auto-detecting the table.

        Tries the events table first; falls back to places if events is empty.

        Args:
            plugin_id: The source plugin identifier (e.g. ``"lastfm"``).

        Returns:
            DataFrame from DuckDB, or empty DataFrame if not found.
        """
        try:
            with self._open_store() as store:
                df = store.query_events(source_id=plugin_id)
                if df.empty:
                    df = store.query_places(source_id=plugin_id)
            return df
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def get_frames(self) -> dict[str, pd.DataFrame]:
        """Return an empty dict (not needed for LocalizerBroker).

        Returns:
            Empty dict.
        """
        return {}

    def get_events_frame(self) -> pd.DataFrame:
        """Return all event rows from the store, unfiltered by source_id.

        Returns:
            DataFrame with columns timestamp, label, sublabel, category,
            source_id, or an empty DataFrame if the store is empty or the
            query fails.
        """
        try:
            with self._open_store() as store:
                df = store.query_events()
            return df
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def get_places_frame(self) -> pd.DataFrame:
        """Return all place rows from the store, unfiltered by source_id.

        Returns:
            DataFrame with columns timestamp, lat, lng, place_name,
            place_type, source_id, or an empty DataFrame if the store is
            empty or the query fails.
        """
        try:
            with self._open_store() as store:
                df = store.query_places()
            return df
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def get_merged_frame(self, assumptions: dict[str, Any] | None = None) -> pd.DataFrame:
        """Return merged events + places via pandas ASOF JOIN on timestamp.

        Each event is joined to the most recent preceding place record
        (backward temporal join). Falls back to events-only if no places are
        available; returns an empty DataFrame if no events exist.

        Args:
            assumptions: Ignored (kept for interface parity with DataBroker).

        Returns:
            DataFrame with event columns plus lat, lng, place_name, place_type
            columns added from the nearest prior place record.
        """
        try:
            with self._open_store() as store:
                events = store.query_events()
                if events.empty:
                    return events
                places = store.query_places()
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

        # Update available_types based on what we found
        if not events.empty and "what-when" not in self._available_types:
            self._available_types.append("what-when")
        if not places.empty and "where-when" not in self._available_types:
            self._available_types.append("where-when")

        if places.empty:
            return events

        events_sorted = events.sort_values("timestamp").reset_index(drop=True)
        places_sorted = places.sort_values("timestamp").reset_index(drop=True)

        merged = pd.merge_asof(
            events_sorted,
            places_sorted[["timestamp", "lat", "lng", "place_name", "place_type"]],
            on="timestamp",
            direction="backward",
        )
        return merged

    def is_type_available(self, plugin_type: str) -> bool:
        """Check whether any data of the given plugin type is in the store.

        Args:
            plugin_type: Either ``"what-when"`` or ``"where-when"``.

        Returns:
            True if the store has rows of the given type.
        """
        return plugin_type in self._available_types
