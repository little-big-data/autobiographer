"""Shared sidebar component — config hydration, lazy data loading, global date filter.

Data is loaded at most once per session, the first time ``render_sidebar()`` runs
after the config (file paths) changes.  All subsequent reruns skip I/O and apply
the date filter directly to the already-loaded ``_raw_df`` in session state.

Session state contract
----------------------
``_current_config``  : ``(file_path, swarm_dir, assumptions_path)`` — written by
                        ``render_sidebar()`` every run so pages can inspect it.
``_loaded_config``   : same tuple — written after a successful data load to mark
                        that ``_raw_df`` is current for this config.
``_raw_df``          : unfiltered merged DataFrame (Last.fm + Swarm offsets).
``swarm_df``         : raw Swarm checkins DataFrame, or None.
``df``               : date-filtered view of ``_raw_df`` for the active session.
``_cache_status``    : ``"hit"`` or ``"miss"`` — shown in Data Sources page.

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


def invalidate_data_cache() -> None:
    """Drop the in-session data cache so the next sidebar render reloads from disk.

    Call this from ``data_sources.py`` whenever a new file is fetched or the
    active file path is changed via the "Use" history button.
    """
    st.session_state.pop("_loaded_config", None)
    st.session_state.pop("_raw_df", None)


def _resolve_configs() -> tuple[str, str, str]:
    """Read plugin config paths from session state.

    Returns:
        ``(file_path, swarm_dir, assumptions_path)`` tuple.
    """
    configs: dict[str, dict[str, str]] = {}
    for plugin_id, plugin_cls in REGISTRY.items():
        plugin = plugin_cls()
        fields = plugin.get_config_fields()
        configs[plugin_id] = get_plugin_config_from_session(plugin_id, fields)

    file_path = configs.get("lastfm", {}).get("data_path", "")
    swarm_dir = configs.get("swarm", {}).get("swarm_dir", "")
    assumptions_path = configs.get("assumptions", {}).get("assumptions_file", _DEFAULT_ASSUMPTIONS)
    return file_path, swarm_dir, assumptions_path


def _load_data_with_progress(
    file_path: str,
    swarm_dir: str,
    assumptions_path: str,
) -> None:
    """Load all data sources with a visible progress widget; store in session state.

    Reads the Last.fm CSV, optionally reads Swarm JSONs, checks the file
    cache, and runs ``apply_swarm_offsets`` on a cache miss.  Results are
    stored in ``st.session_state`` keys defined in the module docstring.

    Args:
        file_path: Path to the Last.fm CSV file.
        swarm_dir: Directory containing Swarm JSON exports (may be empty).
        assumptions_path: Path to the assumptions JSON file.
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
            else:
                swarm_df = pd.DataFrame()

            cache_key = get_cache_key(file_path, swarm_dir, assumptions_path)
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

    file_path, swarm_dir, assumptions_path = _resolve_configs()

    current_config = (file_path, swarm_dir, assumptions_path)
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
        _load_data_with_progress(file_path, swarm_dir, assumptions_path)
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
