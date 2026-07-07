"""Shared sidebar component — config hydration, lazy data loading, global date filter.

Data is loaded at most once per session, the first time ``render_sidebar()`` runs
after the config (file paths) changes.  All subsequent reruns skip I/O and apply
the date filter directly to the already-loaded ``_raw_df`` in session state.

Session state contract
----------------------
``_current_config``  : ``(file_path, swarm_dir, assumptions_path, timeline_path)`` —
                        written by ``render_sidebar()`` every run so pages can inspect
                        it. ``timeline_path`` is appended last so existing index
                        access ([0]–[2]) stays valid.
``_loaded_config``   : same tuple — written after a successful data load to mark
                        that ``_raw_df`` is current for this config.
``_raw_df``          : unfiltered merged DataFrame (Last.fm + location offsets).
``swarm_df``         : combined location DataFrame (Swarm checkins + Google Timeline
                        visits/activities), sorted by timestamp, or None. Each row
                        carries a ``source_id`` of ``"swarm"`` or ``"google_timeline"``
                        identifying which loader produced it.
``df``               : date-filtered view of ``_raw_df`` for the active session.
``_cache_status``    : ``"hit"`` or ``"miss"`` for the legacy file-hash cache, or
                        ``"n/a"`` when data was loaded from the DuckDB store (see
                        broker mode below) — shown in Data Sources page.
``_loaded_store_identity`` : ``(store_path, store_mtime, assumptions_path)`` — the
                        broker-mode reload-identity tuple, written after a
                        successful broker-backed load. Kept separate from
                        ``_loaded_config`` so ``_current_config``'s 4-tuple shape
                        stays a stable contract for index-based readers.

Broker mode
-----------
When ``~/.localizer/store.duckdb`` (or ``LocalizerStore.default_path()``) exists,
``render_sidebar()`` loads data via ``LocalizerBroker`` instead of the legacy
CSV/JSON file paths: it fetches raw events/places frames, adapts them into the
legacy column shapes via ``core.localizer_frames``, and runs the same
``apply_swarm_offsets()`` used by the legacy path. ``_current_config`` is still
written as a 4-tuple (``("", "", assumptions_path, "")``) so index-based readers
elsewhere never see a shape change; the richer reload identity lives in
``_loaded_store_identity`` instead. The legacy file-hash cache
(``get_cache_key``/``get_cached_data``/``save_to_cache``) is not used in broker
mode, since its cache keys are derived from file mtimes that don't apply here.

External invalidation
---------------------
When ``data_sources.py`` saves a new file (fetch or "Use" button), it must call
``invalidate_data_cache()`` so the next ``render_sidebar()`` reloads from disk.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from analysis_utils import (
    apply_swarm_offsets,
    get_cache_key,
    get_cached_data,
    load_assumptions,
    load_google_timeline,
    load_listening_data,
    load_swarm_data,
    save_to_cache,
)
from components.plugin_config import (
    get_plugin_config_from_session,
    load_config_into_session_state,
)
from plugins.sources import REGISTRY, load_builtin_plugins

_DEFAULT_ASSUMPTIONS = "default_assumptions.json"


def _make_broker() -> object:
    """Return the appropriate broker based on whether the DuckDB store exists.

    Returns ``LocalizerBroker`` when the DuckDB file is present (opt-in path);
    falls back to ``DataBroker`` otherwise so behaviour is unchanged.

    Returns:
        A broker instance exposing ``get_merged_frame()``, ``get_frame()``,
        ``is_type_available()``, and ``available_types``.
    """
    try:
        from localizer.store.db import LocalizerStore  # noqa: PLC0415

        if LocalizerStore.default_path().exists():
            from core.broker import LocalizerBroker  # noqa: PLC0415

            return LocalizerBroker()
    except ImportError:
        pass

    from core.broker import DataBroker  # noqa: PLC0415

    return DataBroker()


def _broker_store_identity(assumptions_path: str) -> tuple[str, float, str] | None:
    """Return a reload-identity tuple for the DuckDB store, or None if absent.

    Mirrors ``_make_broker()``'s "opt-in when the DuckDB store exists" check.
    The returned tuple's mtime component changes whenever ``localizer sync``/
    ``fetch`` writes to the store, which is what lets ``render_sidebar()``
    detect staleness and skip redundant reloads without a separate caching
    layer (see the module docstring's "Broker mode" section).

    Args:
        assumptions_path: Path to the assumptions JSON file, included so a
            changed assumptions file also triggers a reload.

    Returns:
        ``(str(store_path), store_mtime, assumptions_path)`` when the store
        file exists, else ``None`` (localizer not installed, or the store has
        not been created yet).
    """
    try:
        from localizer.store.db import LocalizerStore  # noqa: PLC0415

        store_path = LocalizerStore.default_path()
        if store_path.exists():
            return (str(store_path), store_path.stat().st_mtime, assumptions_path)
    except ImportError:
        pass
    return None


def _load_data_from_broker(assumptions_path: str) -> None:
    """Load all data from the DuckDB store via LocalizerBroker; store in session state.

    Fetches raw events/places frames from ``LocalizerBroker``, adapts them into
    the legacy ``lastfm_df``/``swarm_df`` shapes via ``core.localizer_frames``,
    and runs the existing ``apply_swarm_offsets()`` logic on top — mirroring the
    legacy path's computation but sourced from the localizer DuckDB store
    instead of flat CSV/JSON files. The file-hash cache is intentionally not
    used here (see the module docstring's "Broker mode" section); instead
    ``_cache_status`` is set to the literal ``"n/a"``.

    The ``LocalizerBroker`` instance itself is cached in
    ``st.session_state["_broker_instance"]`` and reused across reloads within a
    session: its constructor performs its own store query (to populate
    ``available_types``), so rebuilding it on every reload would double-count
    store queries beyond the one genuinely new ``get_events_frame()``/
    ``get_places_frame()`` call each reload requires.

    Args:
        assumptions_path: Path to the assumptions JSON file.
    """
    from core.broker import LocalizerBroker  # noqa: PLC0415
    from core.localizer_frames import (  # noqa: PLC0415
        events_to_lastfm_frame,
        places_to_swarm_frame,
    )

    assumptions = load_assumptions(assumptions_path)

    broker = st.session_state.get("_broker_instance")
    if broker is None:
        broker = LocalizerBroker()
        st.session_state["_broker_instance"] = broker

    st.markdown("<div style='height:20vh;'></div>", unsafe_allow_html=True)
    _, center_col, _ = st.columns([1, 2, 1])
    with center_col:
        with st.status("Loading your data…", expanded=True) as status:
            st.write("Reading data from local store…")
            lastfm_df = events_to_lastfm_frame(broker.get_events_frame())
            swarm_df = places_to_swarm_frame(broker.get_places_frame())

            st.write("Applying timezone offsets…")
            merged_df = apply_swarm_offsets(lastfm_df, swarm_df, assumptions)

            status.update(label="Data ready.", state="complete", expanded=False)

    st.session_state["_raw_df"] = merged_df
    st.session_state["swarm_df"] = swarm_df if not swarm_df.empty else None
    st.session_state["_cache_status"] = "n/a"


def invalidate_data_cache() -> None:
    """Drop the in-session data cache so the next sidebar render reloads from disk.

    Call this from ``data_sources.py`` whenever a new file is fetched or the
    active file path is changed via the "Use" history button.
    """
    st.session_state.pop("_loaded_config", None)
    st.session_state.pop("_raw_df", None)


def _resolve_configs() -> tuple[str, str, str, str]:
    """Read plugin config paths from session state.

    Returns:
        ``(file_path, swarm_dir, assumptions_path, timeline_path)`` tuple. The
        Google Timeline path is appended last so existing index-based access to the
        first three elements remains valid.
    """
    configs: dict[str, dict[str, str]] = {}
    for plugin_id, plugin_cls in REGISTRY.items():
        plugin = plugin_cls()
        fields = plugin.get_config_fields()
        configs[plugin_id] = get_plugin_config_from_session(plugin_id, fields)

    file_path = configs.get("lastfm", {}).get("data_path", "")
    swarm_dir = configs.get("swarm", {}).get("swarm_dir", "")
    # Old assumptions plugin takes precedence; fall back to LocalizerSettings.
    assumptions_path = configs.get("assumptions", {}).get("assumptions_file", "")
    if not assumptions_path:
        try:
            from localizer.settings import LocalizerSettings  # noqa: PLC0415

            assumptions_path = LocalizerSettings().get_assumptions_path()
        except ImportError:
            assumptions_path = _DEFAULT_ASSUMPTIONS
    timeline_path = configs.get("google_timeline", {}).get("timeline_path", "")
    return file_path, swarm_dir, assumptions_path, timeline_path


def _load_data_with_progress(
    file_path: str,
    swarm_dir: str,
    assumptions_path: str,
    timeline_path: str = "",
) -> None:
    """Load all data sources with a visible progress widget; store in session state.

    Reads the Last.fm CSV, optionally reads Swarm JSONs and a Google Timeline
    export, checks the file cache, and runs ``apply_swarm_offsets`` on a cache
    miss.  Swarm and Timeline location records are concatenated into a single
    ``swarm_df`` (sorted by timestamp) so every geo view and the offset join
    consume them uniformly.  Results are stored in ``st.session_state`` keys
    defined in the module docstring.

    Args:
        file_path: Path to the Last.fm CSV file.
        swarm_dir: Directory containing Swarm JSON exports (may be empty).
        assumptions_path: Path to the assumptions JSON file.
        timeline_path: Path to a Google Timeline JSON export (may be empty).
    """
    assumptions = load_assumptions(assumptions_path)

    st.markdown("<div style='height:20vh;'></div>", unsafe_allow_html=True)
    _, center_col, _ = st.columns([1, 2, 1])
    with center_col:
        with st.status("Loading your data…", expanded=True) as status:
            st.write("Reading listening history…")
            raw_df = load_listening_data(file_path)

            if raw_df is None or raw_df.empty:
                status.update(label="No listening data found.", state="error", expanded=False)
                st.session_state["_raw_df"] = None
                st.session_state["swarm_df"] = None
                st.session_state["_cache_status"] = "miss"
                return

            swarm_df: pd.DataFrame
            if swarm_dir and os.path.exists(swarm_dir):
                st.write("Loading location data…")
                swarm_df = load_swarm_data(swarm_dir)
                if not swarm_df.empty:
                    swarm_df["source_id"] = "swarm"
            else:
                swarm_df = pd.DataFrame()

            # Fold in Google Timeline visits/activities, which share the swarm
            # column schema, so all downstream geo views see a single frame.
            if timeline_path and os.path.exists(timeline_path):
                st.write("Loading Google Timeline data…")
                timeline_df = load_google_timeline(timeline_path)
                if not timeline_df.empty:
                    timeline_df["source_id"] = "google_timeline"
                    swarm_df = pd.concat([swarm_df, timeline_df], ignore_index=True)
                    # Re-sort: apply_swarm_offsets relies on ascending timestamps.
                    swarm_df = swarm_df.sort_values("timestamp").reset_index(drop=True)

            cache_key = get_cache_key(file_path, swarm_dir, assumptions_path, timeline_path)
            cached = get_cached_data(cache_key)

            if cached is not None:
                merged_df = cached
                st.session_state["_cache_status"] = "hit"
                st.write("Restored from cache.")
            else:
                st.session_state["_cache_status"] = "miss"
                st.write("Applying timezone offsets — first-time setup, may take a minute…")
                merged_df = apply_swarm_offsets(raw_df, swarm_df, assumptions)
                save_to_cache(merged_df, cache_key)

            status.update(label="Data ready.", state="complete", expanded=False)

    st.session_state["_raw_df"] = merged_df
    st.session_state["swarm_df"] = swarm_df if not swarm_df.empty else None


def render_sidebar() -> None:
    """Hydrate config, load data if needed, and render the global date filter.

    Data is loaded (with a progress widget) the first time this runs after the
    configured file paths change.  On subsequent reruns the data is read from
    ``st.session_state['_raw_df']`` — no disk I/O — making filter interactions
    instant.

    Populates:
        ``st.session_state["_current_config"]`` — the active config tuple.
        ``st.session_state["df"]`` — date-filtered view of ``_raw_df``, or None.
    """
    load_builtin_plugins()
    load_config_into_session_state()

    file_path, swarm_dir, assumptions_path, timeline_path = _resolve_configs()

    broker_identity = _broker_store_identity(assumptions_path)

    if broker_identity is not None:
        # Broker mode: the DuckDB store exists, so it is the exclusive data
        # source for this session (see the module docstring's "Broker mode"
        # section). _current_config keeps its legacy 4-tuple shape for
        # index-based readers elsewhere; the real reload identity is the
        # richer broker_identity tuple, tracked separately.
        current_config = ("", "", assumptions_path, "")
        st.session_state["_current_config"] = current_config

        already_loaded = (
            st.session_state.get("_loaded_store_identity") == broker_identity
            and st.session_state.get("_raw_df") is not None
        )

        if not already_loaded:
            _load_data_from_broker(assumptions_path)
            if st.session_state.get("_raw_df") is not None:
                # Re-stat rather than reuse broker_identity: opening the store
                # during the load above can itself change the DuckDB file's
                # mtime (observed empirically — DuckDB touches the file on
                # connect even for reads), so the identity that marks this
                # load "current" must be captured *after* the load completes,
                # not the pre-load value, or every subsequent call would see
                # a mismatch and reload again.
                st.session_state["_loaded_store_identity"] = _broker_store_identity(
                    assumptions_path
                )
                st.session_state["_loaded_config"] = current_config
    else:
        # Legacy mode: no DuckDB store present, unchanged from prior behavior.
        current_config = (file_path, swarm_dir, assumptions_path, timeline_path)
        st.session_state["_current_config"] = current_config

        if not file_path or not os.path.exists(file_path):
            for key in ("_raw_df", "_loaded_config"):
                st.session_state.pop(key, None)
            st.session_state["df"] = None
            st.session_state["swarm_df"] = None
            return

        already_loaded = (
            st.session_state.get("_loaded_config") == current_config
            and st.session_state.get("_raw_df") is not None
        )

        if not already_loaded:
            _load_data_with_progress(file_path, swarm_dir, assumptions_path, timeline_path)
            if st.session_state.get("_raw_df") is not None:
                st.session_state["_loaded_config"] = current_config

    raw_df: pd.DataFrame | None = st.session_state.get("_raw_df")

    if raw_df is not None and not raw_df.empty:
        st.sidebar.markdown(
            '<p class="autobio-section-header">Global Filters</p>', unsafe_allow_html=True
        )
        min_date = raw_df["date_text"].min().date()
        max_date = raw_df["date_text"].max().date()
        date_range = st.sidebar.date_input("Filter by Date Range", [min_date, max_date])

        df: pd.DataFrame = raw_df
        if len(date_range) == 2:
            df = raw_df[
                (raw_df["date_text"].dt.date >= date_range[0])
                & (raw_df["date_text"].dt.date <= date_range[1])
            ]
        st.session_state["df"] = df
    else:
        st.session_state.setdefault("df", None)
