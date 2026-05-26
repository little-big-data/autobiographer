"""Data Sources management page.

``render_data_sources`` is the overview hub: summary health metrics and
Cache Management.  Each plugin has its own dedicated page rendered by
``render_plugin_page``, which is wired into ``st.navigation`` by
``visualize.py``.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st

from analysis_utils import (
    DETECTED_TRIPS_CACHE,
    DINING_CACHE,
    TRANSIT_DAYS_CACHE,
    detect_trips_from_swarm,
    get_dining_soundtrack_data,
    get_transit_days,
    load_assumptions,
    load_detected_trips_cache,
    load_dining_cache,
    load_transit_days_cache,
    save_detected_trips_cache,
    save_dining_cache,
    save_transit_days_cache,
)
from components.plugin_config import (
    load_config_into_session_state,
    render_plugin_config_fields,
    settings,
)
from components.sidebar import invalidate_data_cache
from core.fetch_utils import FetchCheckpoint
from plugins.sources import REGISTRY, load_builtin_plugins
from plugins.sources.base import _count_records_at_path

_STATUS_META: dict[str, tuple[str, str]] = {
    "healthy": ("✅", "Healthy"),
    "stale": ("⚠️", "Stale"),
    "error": ("❌", "Error"),
    "unconfigured": ("◻️", "Not configured"),
}


def _render_plugin_tab(plugin_id: str, plugin: Any) -> dict[str, Any]:
    """Render status, config, fetch, and history UI for one plugin.

    Health is computed *after* ``render_plugin_config_fields`` runs so that the
    browse-button pending-key is processed before the status card is filled in.
    An ``st.empty()`` placeholder keeps Status visually at the top even though
    it is filled after Configuration is rendered.

    Args:
        plugin_id: Plugin identifier string.
        plugin: Instantiated SourcePlugin.

    Returns:
        Health dict from ``plugin.get_health_status()``.
    """
    # Reserve a slot at the top — filled after config fields process any pending keys.
    status_ph = st.empty()

    # ── Configuration ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Configuration")
    fields = plugin.get_config_fields()
    config = render_plugin_config_fields(plugin_id, fields)

    primary_path_missing = False
    if fields:
        primary_val = config.get(fields[0]["key"], "").strip()
        primary_type = fields[0].get("type", "text")
        is_path_field = primary_type in ("file_path", "dir_path")
        if primary_val and is_path_field and not os.path.exists(primary_val):
            st.warning("Configured path no longer exists — please select a new location.")
            primary_path_missing = True

    # Health is accurate now because render_plugin_config_fields has processed
    # any pending browse-button result into session state.
    history = settings.get_fetch_history(plugin_id)
    health: dict[str, Any] = plugin.get_health_status(config, history)

    # ── Status (fills the placeholder at the top) ────────────────────────────
    with status_ph.container():
        st.subheader("Status")
        icon, label = _STATUS_META.get(health["status"], ("◻️", health["status"]))
        c1, c2, c3 = st.columns(3)
        c1.metric("Health", f"{icon} {label}")
        rc = health["record_count"]
        c2.metric("Records", f"{rc:,}" if isinstance(rc, int) else "—")
        last = health.get("last_fetch") or ""
        c3.metric("Last Fetch", last[:10] if last else "—")

    st.divider()

    # ── Fetch ────────────────────────────────────────────────────────────────
    st.subheader("Fetch Data")

    pending_fetch: tuple[str, bool] | None = None  # (versioned_path, resume)
    checkpoint: FetchCheckpoint | None = None

    if plugin.FETCHABLE:
        env_vars = plugin.get_fetch_env_vars()
        missing_vars = [v for v in env_vars if not os.getenv(v["var"])]
        if missing_vars:
            st.warning("Auto-fetch requires these environment variables:")
            for v in missing_vars:
                st.code(f'{v["var"]}="…"', language="bash")
                st.caption(v["description"])
        else:
            identity = plugin.get_fetch_identity()
            if identity:
                st.caption(f"Fetching as **{identity}**")
            versioned_path = plugin.get_versioned_output_path()
            st.caption(f"Will save to `{versioned_path}`")

            checkpoint = FetchCheckpoint(
                checkpoint_dir="data/cache",
                plugin_id=plugin_id,
                identity=identity or plugin_id,
            )

            resume_state = None
            stale_checkpoint = False
            try:
                resume_state = checkpoint.load()
            except ValueError:
                stale_checkpoint = True

            if stale_checkpoint:
                st.caption("⚠️ A previous checkpoint was found but is too old (>7 days) — ignored.")

            if resume_state is not None:
                last_page, _ = resume_state
                col_fetch, col_resume = st.columns(2)
                if col_fetch.button("Fetch Latest Data", key=f"fetch_{plugin_id}"):
                    pending_fetch = (versioned_path, False)
                col_resume.info(
                    f"Checkpoint found: page {last_page}, "
                    f"~{checkpoint.tracks_fetched:,} tracks already fetched"
                )
                if col_resume.button("Resume Interrupted Fetch", key=f"resume_{plugin_id}"):
                    pending_fetch = (versioned_path, True)
            else:
                if st.button("Fetch Latest Data", key=f"fetch_{plugin_id}"):
                    pending_fetch = (versioned_path, False)
    else:
        primary_value = next(iter(config.values()), "").strip() if config else ""
        if not primary_value or not os.path.exists(primary_value) or primary_path_missing:
            st.info(plugin.get_manual_download_instructions())
        else:
            st.caption("Data loaded from manual export. No auto-fetch available for this source.")

    # Execute pending fetch after button block so progress renders correctly.
    if pending_fetch is not None:
        versioned_path, do_resume = pending_fetch
        fetch_status_ph = st.empty()

        def _on_progress(page: int, total: int) -> None:
            frac = page / total if total > 0 else 0.0
            fetch_status_ph.progress(
                frac,
                text=f"Page {page} of {total} · ~{page * 200:,} estimated tracks",
            )

        fetch_status_ph.progress(0.0, text="Starting fetch…")
        try:
            parent = os.path.dirname(versioned_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            plugin.fetch(
                output_path=versioned_path,
                progress_callback=_on_progress,
                checkpoint=checkpoint,
                resume=do_resume,
            )

            record_count = _count_records_at_path(versioned_path) or 0
            ts = datetime.now(tz=timezone.utc).isoformat()
            settings.add_fetch_history(plugin_id, ts, record_count, versioned_path)

            # Point the active config path at the new versioned file.
            if fields:
                primary_key = fields[0]["key"]
                session_key = f"{plugin_id}_{primary_key}"
                st.session_state[session_key] = versioned_path
                settings.set_plugin_value(plugin_id, primary_key, versioned_path)

            invalidate_data_cache()
            fetch_status_ph.success(
                f"Fetch complete — {record_count:,} records saved to `{versioned_path}`"
            )
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            fetch_status_ph.error(f"Fetch failed: {exc}")

    st.divider()

    # ── Fetch History ────────────────────────────────────────────────────────
    st.subheader("Fetch History")
    history = settings.get_fetch_history(plugin_id)
    if not history:
        st.caption("No fetch history recorded yet.")
    else:
        header_cols = st.columns([3, 2, 5, 1])
        header_cols[0].caption("**Timestamp**")
        header_cols[1].caption("**Records**")
        header_cols[2].caption("**File**")
        header_cols[3].caption("**Use**")

        for i, entry in enumerate(history):
            ts = str(entry.get("timestamp", ""))[:19]
            rc = entry.get("record_count", "?")
            fp = str(entry.get("file_path", ""))
            row = st.columns([3, 2, 5, 1])
            row[0].text(ts or "—")
            row[1].text(f"{rc:,}" if isinstance(rc, int) else str(rc))
            row[2].text(fp)
            if row[3].button("→", key=f"use_{plugin_id}_{i}", help="Set as active version"):
                if fields and fp:
                    primary_key = fields[0]["key"]
                    st.session_state[f"{plugin_id}_{primary_key}"] = fp
                    settings.set_plugin_value(plugin_id, primary_key, fp)
                    invalidate_data_cache()
                    st.rerun()

    return health


def _render_swarm_analysis() -> None:
    """Render the Swarm analysis section on the Foursquare/Swarm plugin page.

    Detects trips, computes transit days, and builds the dining soundtrack
    cache — all in one button click.  Results are persisted to disk so that
    the Listening Lifestyle and Life in Chapters pages read pre-built caches
    instead of recomputing on every page visit.
    """
    swarm_df: pd.DataFrame | None = st.session_state.get("swarm_df")
    df: pd.DataFrame | None = st.session_state.get("df")

    # If session state doesn't have swarm data yet, try loading directly from
    # the configured directory so the cache can be built even before Last.fm
    # data is loaded (which is required for the sidebar data pipeline to run).
    if swarm_df is None or (isinstance(swarm_df, pd.DataFrame) and swarm_df.empty):
        from analysis_utils import load_swarm_data
        from components.plugin_config import get_plugin_config_from_session

        cfg = get_plugin_config_from_session(
            "swarm", [{"key": "swarm_dir", "label": "", "type": "dir_path"}]
        )
        swarm_dir = cfg.get("swarm_dir", "")
        if swarm_dir and os.path.exists(swarm_dir):
            swarm_df = load_swarm_data(swarm_dir)
            if swarm_df is not None and not swarm_df.empty:
                # Persist so the sidebar's already_loaded check stays valid
                # across the st.rerun() triggered by the build button.
                st.session_state["swarm_df"] = swarm_df

    if swarm_df is None or (isinstance(swarm_df, pd.DataFrame) and swarm_df.empty):
        st.info(
            "No Swarm check-in data loaded. "
            "Select your Swarm export directory above, then reload data in the sidebar."
        )
        return

    # ── Cache status ──────────────────────────────────────────────────────────
    trips_cached = load_detected_trips_cache()
    transit_days_cached = load_transit_days_cache()
    dining_cached_data = load_dining_cache()

    if transit_days_cached:
        transit_label = f"{len(transit_days_cached)} days"
    elif os.path.exists(TRANSIT_DAYS_CACHE):
        transit_label = "Empty — rebuild"
    else:
        transit_label = "Not built"

    if dining_cached_data:
        dining_label = f"{len(dining_cached_data)} categories"
    elif os.path.exists(DINING_CACHE):
        dining_label = "Empty — rebuild"
    elif df is None:
        dining_label = "Needs Last.fm data"
    else:
        dining_label = "Not built"

    status_cols = st.columns(3)
    status_cols[0].metric(
        "Detected Trips",
        f"{len(trips_cached)} trip(s)" if trips_cached else "Not built",
    )
    status_cols[1].metric("Transit Days Cache", transit_label)
    status_cols[2].metric("Dining Cache", dining_label)

    st.divider()

    # ── Detection parameters ──────────────────────────────────────────────────
    loaded_config = st.session_state.get("_loaded_config")
    assumptions_path: str | None = loaded_config[2] if loaded_config else None
    assumptions = load_assumptions(assumptions_path)

    col_a, col_b = st.columns(2)
    with col_a:
        radius_km = st.slider(
            "Distance from home to count as a trip (km)",
            min_value=20,
            max_value=300,
            value=80,
            step=10,
            key="swarm_trip_radius_km",
        )
    with col_b:
        gap_days = st.slider(
            "Days gap between trips",
            min_value=1,
            max_value=14,
            value=2,
            step=1,
            key="swarm_trip_gap_days",
        )

    # ── Build button ──────────────────────────────────────────────────────────
    building = st.session_state.get("_swarm_building", False)
    if st.button(
        ":material/travel_explore: Build Swarm Analysis Cache",
        key="build_swarm_cache_btn",
        disabled=building,
        type="primary",
    ):
        st.session_state["_swarm_building"] = True
        errors: list[str] = []

        with st.spinner("Detecting trips from check-ins…"):
            try:
                trips = detect_trips_from_swarm(
                    swarm_df,
                    assumptions,
                    radius_km=float(radius_km),
                    gap_days=int(gap_days),
                )
                if trips or not load_detected_trips_cache():
                    save_detected_trips_cache(trips)
                elif not trips:
                    st.warning(
                        "Trip detection found 0 trips — existing cache preserved. "
                        "Check that your assumptions file has a home location."
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Trip detection failed: {exc}")

        with st.spinner("Computing transit days…"):
            try:
                transit_days = get_transit_days(swarm_df)
                if transit_days or not load_transit_days_cache():
                    save_transit_days_cache(transit_days)
                elif not transit_days:
                    st.warning(
                        "No transit check-ins found — existing cache preserved. "
                        "Transit days require airport, train, or bus check-ins."
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Transit days failed: {exc}")

        if df is not None and not df.empty:
            with st.spinner("Building dining soundtrack data…"):
                try:
                    dining = get_dining_soundtrack_data(swarm_df, df)
                    if dining or not load_dining_cache():
                        save_dining_cache(dining)
                    elif not dining:
                        st.warning(
                            "No dining check-ins found — existing cache preserved. "
                            "Dining data requires restaurant, bar, or café check-ins."
                        )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Dining cache failed: {exc}")
        else:
            st.caption(
                "Last.fm data not loaded — dining cache skipped. "
                "Load your music data in the sidebar and re-run to include dining."
            )

        st.session_state["_swarm_building"] = False

        if errors:
            for err in errors:
                st.error(err)
        else:
            st.success(
                f"Cache built: {len(trips)} trip(s) detected, "
                f"{len(transit_days)} transit day(s) indexed."
            )
        st.rerun()

    if trips_cached:
        st.caption(
            f"Detected trips cache: `{DETECTED_TRIPS_CACHE}` · "
            f"Transit: `{TRANSIT_DAYS_CACHE}` · Dining: `{DINING_CACHE}`"
        )


def render_plugin_page(plugin_id: str) -> None:
    """Render the standalone management page for a single plugin.

    Called by ``st.Page`` entries in ``visualize.py`` — one page per plugin
    under the Sources nav group.

    Streamlit widgets read their display value from the session state snapshot
    taken at the *start* of each script run, not from values set *during* that
    run.  When page navigation clears widget-bound keys, we must hydrate
    session state and trigger one extra rerun so the widgets in the following
    run see the correct values.

    Args:
        plugin_id: The plugin's PLUGIN_ID string (registry key).
    """
    load_builtin_plugins()

    plugin_cls = REGISTRY.get(plugin_id)
    if plugin_cls is None:
        st.error(f"Plugin '{plugin_id}' not found in registry.")
        return

    plugin = plugin_cls()
    fields = plugin.get_config_fields()

    # Check BEFORE hydration whether any config field is blank in session state
    # but has a saved value on disk.
    saved_cfg = settings.get_plugin_config(plugin_id)
    needs_rerun = any(
        saved_cfg.get(f["key"]) and not st.session_state.get(f"{plugin_id}_{f['key']}")
        for f in fields
    )

    load_config_into_session_state()

    if needs_rerun:
        # Values were just written into session state this run; rerun so the
        # next script execution's widget snapshot includes them.
        st.rerun()

    st.title(plugin.DISPLAY_NAME)
    _render_plugin_tab(plugin_id, plugin)

    if plugin_id == "swarm":
        st.divider()
        st.subheader(":material/travel_explore: Swarm Analysis Cache")
        st.caption(
            "Pre-compute trips, transit days, and dining soundtrack data from your check-ins. "
            "These caches power the **Life in Chapters** and **Listening Lifestyle** pages."
        )
        _render_swarm_analysis()


def _render_cache_tab() -> None:
    """Render the Cache Management tab content."""
    cache_dir = "data/cache"

    st.subheader("Cache Status")
    cache_status = st.session_state.get("_cache_status", "unknown")
    if cache_status == "hit":
        st.success("Active dataset loaded from local cache.")
    elif cache_status == "miss":
        st.info("Dataset was processed fresh and saved to cache.")
    else:
        st.caption("Load the app with a configured Last.fm file to populate cache status.")

    st.divider()
    st.subheader("Cached Files")

    if os.path.exists(cache_dir):
        files = [f for f in os.listdir(cache_dir) if not f.startswith(".")]
        if files:
            total_bytes = sum(
                os.path.getsize(os.path.join(cache_dir, f))
                for f in files
                if os.path.isfile(os.path.join(cache_dir, f))
            )
            st.caption(f"{len(files)} file(s) — {total_bytes / 1024:.1f} KB total")
            for fname in sorted(files):
                st.text(fname)
        else:
            st.caption("Cache directory is empty.")
    else:
        st.caption("No cache directory found.")

    st.divider()
    if st.button("Clear Local Cache", type="primary"):
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            st.session_state.pop("_cache_status", None)
            st.success("Cache cleared.")
            st.rerun()
        else:
            st.info("Nothing to clear — cache directory does not exist.")


def render_data_sources() -> None:
    """Render the Data Sources overview page (summary metrics + Cache tab)."""
    load_builtin_plugins()
    load_config_into_session_state()

    st.title("Data Sources")
    st.caption("Health summary across all configured sources.")

    overview_tab, cache_tab = st.tabs(["Overview", "Cache Management"])

    with overview_tab:
        plugins_list = [(pid, cls()) for pid, cls in REGISTRY.items()]

        # Summary metric row — filled after all plugins report health.
        summary_ph = st.empty()
        st.divider()

        all_health: list[dict[str, Any]] = []
        for plugin_id, plugin in plugins_list:
            fields = plugin.get_config_fields()
            from components.plugin_config import get_plugin_config_from_session

            config = get_plugin_config_from_session(plugin_id, fields)
            history = settings.get_fetch_history(plugin_id)
            health: dict[str, Any] = plugin.get_health_status(config, history)
            all_health.append(health)

            icon, label = _STATUS_META.get(health["status"], ("◻️", health["status"]))
            rc = health["record_count"]
            last = (health.get("last_fetch") or "")[:10]

            cols = st.columns([3, 1, 2, 2])
            cols[0].markdown(f"**{plugin.DISPLAY_NAME}**")
            cols[1].markdown(f"{icon} {label}")
            cols[2].caption(f"{rc:,} records" if isinstance(rc, int) else "—")
            cols[3].caption(last or "—")

        counts: dict[str, int] = {"healthy": 0, "stale": 0, "error": 0, "unconfigured": 0}
        for h in all_health:
            counts[h["status"]] = counts.get(h["status"], 0) + 1

        with summary_ph.container():
            c1, c2, c3 = st.columns(3)
            c1.metric("Healthy", counts["healthy"])
            c2.metric("Stale", counts["stale"])
            c3.metric("Issues", counts["error"] + counts["unconfigured"])

    with cache_tab:
        _render_cache_tab()
