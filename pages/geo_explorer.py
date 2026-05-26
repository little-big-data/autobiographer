"""Geo Explorer — unified geographic visualization page.

Consolidates four views of the same location-enriched dataset:
* **3D Globe** — Pydeck ScatterplotLayer + ColumnLayer with country/state overlays
  and cinematic flythrough recording.
* **2D Map** — Plotly scatter_map (carto-darkmatter, no token required).  Includes
  a "By City" breakdown panel with a sortable city stats table and detail card.
* **US States** — Plotly choropleth coloured by scrobble density per US state.
* **Table** — Paginated artist-city summary table.

Filters (artist, date range, data layers) and 3D settings live in popovers so
the main canvas stays uncluttered.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st
from pandas import DataFrame

from analysis_utils import get_top_entities
from components.share import render_share_button
from components.theme import (
    ACCENT_CYAN,
    ACCENT_INDIGO,
    COLORWAY,
    MAP_COLUMN_DEFAULT_RGBA,
    MAP_COUNTRY_BORDER_RGB,
    MAP_COUNTRY_UNVISITED_RGBA,
    MAP_COUNTRY_VISITED_RGBA,
    MAP_STATE_BORDER_RGBA,
    SEQUENTIAL_SCALE,
    apply_dark_theme,
)
from pages.artist_geography import (
    build_artist_city_table,
    build_map_data,
)
from pages.music_map_america import build_state_stats, filter_us_states

_TABLE_PAGE_SIZE = 25
_MAP_MAX_ARTISTS = 50

_RECORD_SCRIPT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "record_flythrough.py")
)

_VIEW_3D = "🌐 3D Globe"
_VIEW_2D = "🗺 2D Map"
_VIEW_US = "🇺🇸 US States"
_VIEW_TABLE = "📋 Table"

# Assumed average track duration used for estimated listening time in city breakdown.
_AVG_TRACK_MINUTES: float = 3.5

_CHECKIN_RGBA = [34, 211, 238, 210]  # cyan — distinct from scrobble spectrum

# Indigo accent: subtle fill + bright border so state outlines glow without drowning city columns
_STATE_HIGHLIGHT_FILL_RGBA = [99, 102, 241, 35]
_STATE_HIGHLIGHT_LINE_RGBA = [99, 102, 241, 210]

_US_STATES_GEOJSON_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "us-states-polygons.geojson"
    )
)


def _load_us_states_geojson() -> dict[str, list[dict]] | None:
    """Load the bundled US states polygon GeoJSON, or return None if the file is absent."""
    if not os.path.exists(_US_STATES_GEOJSON_PATH):
        return None
    with open(_US_STATES_GEOJSON_PATH) as fh:
        data: dict[str, list[dict]] = json.load(fh)
    return data


def build_state_highlight_layer(active_states: list[str]) -> pdk.Layer | None:
    """Return a Pydeck GeoJsonLayer rendering the borders of the given US states.

    Loads the bundled ``assets/us-states-polygons.geojson`` (Polygon geometry,
    one feature per state with a ``state`` abbreviation property), filters to
    *active_states*, and returns a ``GeoJsonLayer`` drawn with an indigo outline
    and a very subtle indigo fill.

    Args:
        active_states: List of 2-letter US state abbreviations to highlight.

    Returns:
        A ``pdk.Layer`` or ``None`` when *active_states* is empty or the GeoJSON
        asset is not found.
    """
    if not active_states:
        return None
    geojson = _load_us_states_geojson()
    if geojson is None:
        return None
    active_set = set(active_states)
    filtered: dict[str, object] = {
        "type": "FeatureCollection",
        "features": [
            f
            for f in geojson.get("features", [])
            if f.get("properties", {}).get("state") in active_set
        ],
    }
    if not filtered["features"]:
        return None
    return pdk.Layer(
        "GeoJsonLayer",
        filtered,
        stroked=True,
        filled=True,
        get_fill_color=_STATE_HIGHLIGHT_FILL_RGBA,
        get_line_color=_STATE_HIGHLIGHT_LINE_RGBA,
        get_line_width=2,
        line_width_min_pixels=1,
        pickable=False,
    )


def build_state_polygon_layer(music_df: DataFrame) -> pdk.Layer | None:
    """Return a Pydeck GeoJsonLayer highlighting US state borders present in *music_df*.

    Convenience wrapper around :func:`build_state_highlight_layer` that
    extracts the active state abbreviations from *music_df* via
    :func:`~pages.music_map_america.filter_us_states`.

    Args:
        music_df: Filtered listening history DataFrame.

    Returns:
        A ``pdk.Layer`` or ``None`` when no US state data is found or the
        polygon GeoJSON asset is absent.
    """
    if "state" not in music_df.columns or music_df.empty:
        return None
    us_df = filter_us_states(music_df)
    if us_df.empty:
        return None
    active_states = sorted(us_df["state"].unique().tolist())
    return build_state_highlight_layer(active_states)


# ---------------------------------------------------------------------------
# Pure data helpers
# ---------------------------------------------------------------------------


def build_globe_data(df: DataFrame) -> DataFrame:
    """Aggregate scrobble counts per (city, lat, lng) for Pydeck layers.

    Args:
        df: Listening history DataFrame with ``lat``, ``lng``, ``city`` columns.

    Returns:
        DataFrame with columns ``[city, lat, lng, Plays]``.
        Empty DataFrame when required columns are absent.
    """
    required = {"lat", "lng", "city"}
    if not required.issubset(df.columns):
        return DataFrame(columns=["city", "lat", "lng", "Plays"])
    geo = df.dropna(subset=["lat", "lng", "city"])
    if geo.empty:
        return DataFrame(columns=["city", "lat", "lng", "Plays"])
    return geo.groupby(["lat", "lng", "city"]).size().reset_index(name="Plays")


# ---------------------------------------------------------------------------
# Internal view renderers
# ---------------------------------------------------------------------------


def _spectrum_color(val: float, max_val: float) -> list[int]:
    """Return RGBA from teal (low) to amber (high) for dark basemaps."""
    if max_val == 0:
        return MAP_COLUMN_DEFAULT_RGBA
    ratio = val / max_val
    if ratio < 0.5:
        t = ratio * 2
        r = int(0 + 100 * t)
        g = int(200 + 20 * t)
        b = int(200 - 80 * t)
    else:
        t = (ratio - 0.5) * 2
        r = int(100 + 155 * t)
        g = int(220 - 60 * t)
        b = int(120 - 100 * t)
    return [r, g, b, 220]


def _build_flythrough_filename(selected_artist: str, date_range: tuple) -> str:
    """Build a default .mp4 filename encoding the current recording settings."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [ts]
    if selected_artist != "All":
        safe = re.sub(r"[^\w\-]", "_", selected_artist, flags=re.ASCII)[:30]
        parts.append(safe)
    if len(date_range) == 2:
        parts.append(date_range[0].strftime("%Y%m%d"))
        parts.append(date_range[1].strftime("%Y%m%d"))
    return "flythrough_" + "_".join(parts) + ".mp4"


def _open_save_dialog(initial_filename: str) -> str | None:
    """Open a native file-save dialog and return the chosen path, or None."""
    try:
        import threading
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    result: list[str] = []

    def _run() -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            root.wm_attributes("-topmost", 1)
        except Exception:  # noqa: S110
            pass
        path = filedialog.asksaveasfilename(
            title="Save flythrough recording",
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4"), ("All files", "*.*")],
            initialfile=initial_filename,
        )
        root.destroy()
        if path:
            result.append(path)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    return result[0] if result else None


def _render_3d_globe(
    music_df: DataFrame | None,
    swarm_df: DataFrame | None,
    selected_layers: list[str],
    zoom_level: float,
    bearing: float,
    pitch: float,
    selected_artist: str,
    date_range: tuple,
) -> None:
    """Render Pydeck 3D globe with optional scrobble and check-in layers."""
    has_music = music_df is not None and not music_df.empty
    has_swarm = swarm_df is not None and not swarm_df.empty

    show_scrobbles = "Scrobbles" in selected_layers and has_music
    show_checkins = "Check-ins" in selected_layers and has_swarm

    if not show_scrobbles and not show_checkins:
        st.info("No data to display. Enable at least one data layer in the Filter panel.")
        return

    geo_data: DataFrame = DataFrame(columns=["city", "lat", "lng", "Plays"])
    if show_scrobbles and music_df is not None:
        geo_data = build_globe_data(music_df)

    checkin_geo: DataFrame = DataFrame()
    if show_checkins and swarm_df is not None:
        swarm_cols = {"lat", "lng", "city"}
        if swarm_cols.issubset(swarm_df.columns):
            checkin_geo = (
                swarm_df.dropna(subset=["lat", "lng", "city"])
                .groupby(["lat", "lng", "city"])
                .size()
                .reset_index(name="Plays")
            )

    if geo_data.empty and checkin_geo.empty:
        st.info("No geographic data found for the selected filters.")
        return

    # ── View state ────────────────────────────────────────────────────────────
    ref_df = geo_data if not geo_data.empty else checkin_geo
    if "geo_view_state" not in st.session_state:
        st.session_state["geo_view_state"] = pdk.ViewState(
            latitude=float(ref_df["lat"].mean()),
            longitude=float(ref_df["lng"].mean()),
            zoom=zoom_level,
            pitch=pitch,
            bearing=bearing,
        )
    vs = st.session_state["geo_view_state"]
    vs.zoom = zoom_level
    vs.bearing = bearing
    vs.pitch = pitch

    # ── Layer construction ────────────────────────────────────────────────────
    try:
        import geopandas as gpd
        from shapely.geometry import Point

        @st.cache_data
        def _get_overlay(points_json: str) -> tuple[object, str | None]:
            countries_path = os.path.join("assets", "countries.geojson")
            states_path = os.path.join("assets", "states.geojson")
            if not os.path.exists(countries_path):
                return None, None
            world = gpd.read_file(countries_path)
            pts_df = pd.read_json(io.StringIO(points_json))
            geom = [Point(xy) for xy in zip(pts_df["lng"], pts_df["lat"])]
            pts_gpd = gpd.GeoDataFrame(pts_df, geometry=geom, crs="EPSG:4326")
            visited = gpd.sjoin(world, pts_gpd, how="inner", predicate="intersects")

            world["fill_color"] = world.index.map(
                lambda i: (
                    MAP_COUNTRY_VISITED_RGBA if i in visited.index else MAP_COUNTRY_UNVISITED_RGBA
                )
            )
            return world, states_path if os.path.exists(states_path) else None

        world_gdf, states_path = _get_overlay(ref_df.to_json())
    except ImportError:
        world_gdf, states_path = None, None

    # ── State polygon outlines (drawn first so city columns sit on top) ──────────
    active_states: list[str] = []
    if music_df is not None and not music_df.empty:
        us_filtered = filter_us_states(music_df)
        if not us_filtered.empty:
            active_states = sorted(us_filtered["state"].unique().tolist())
        state_layer = build_state_polygon_layer(music_df)
        layers_before_geo: list = [state_layer] if state_layer is not None else []
    else:
        layers_before_geo = []

    layers: list = layers_before_geo
    if world_gdf is not None:
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                world_gdf,
                stroked=True,
                filled=True,
                get_fill_color="fill_color",
                get_line_color=MAP_COUNTRY_BORDER_RGB,
                get_line_width=1,
            )
        )
    if states_path and os.path.exists(states_path):
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                states_path,
                stroked=True,
                filled=False,
                get_line_color=MAP_STATE_BORDER_RGBA,
                get_line_width=1,
            )
        )

    # Scrobble ColumnLayer + ScatterplotLayer
    if not geo_data.empty:
        dynamic_radius = 50000 / (2 ** (zoom_level - 1))
        geo_data = geo_data.copy()
        geo_data["elevation_log"] = np.log1p(geo_data["Plays"])
        max_log = float(geo_data["elevation_log"].max())
        geo_data["elevation"] = (
            (geo_data["elevation_log"] / max_log) * (1.4 * dynamic_radius) if max_log > 0 else 0.0
        )
        geo_data["color"] = geo_data["elevation_log"].apply(lambda x: _spectrum_color(x, max_log))
        layers.extend(
            [
                pdk.Layer(
                    "ScatterplotLayer",
                    geo_data,
                    get_position=["lng", "lat"],
                    get_fill_color="color",
                    radius=dynamic_radius * 1.2,
                    pickable=True,
                ),
                pdk.Layer(
                    "ColumnLayer",
                    geo_data,
                    get_position=["lng", "lat"],
                    get_elevation="elevation",
                    elevation_scale=10,
                    radius=dynamic_radius,
                    get_fill_color="color",
                    pickable=True,
                    auto_highlight=True,
                ),
            ]
        )

    # Check-in ScatterplotLayer (cyan dots)
    if not checkin_geo.empty:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                checkin_geo,
                get_position=["lng", "lat"],
                get_fill_color=_CHECKIN_RGBA,
                radius=30000,
                pickable=True,
            )
        )

    r = pdk.Deck(
        layers=layers,
        initial_view_state=vs,
        tooltip={"text": "{city}: {Plays} plays"},
        map_style="dark",
    )
    st.pydeck_chart(r, key="geo_3d_map")

    # ── Metrics ───────────────────────────────────────────────────────────────
    m_cols = st.columns(3 if not geo_data.empty else 2)
    if not geo_data.empty:
        with m_cols[0]:
            st.metric("Scrobble Locations", f"{len(geo_data):,}")
        with m_cols[1]:
            st.metric("Total Scrobbles (mapped)", f"{int(geo_data['Plays'].sum()):,}")
        if not checkin_geo.empty:
            with m_cols[2]:
                st.metric("Check-in Locations", f"{len(checkin_geo):,}")
    elif not checkin_geo.empty:
        with m_cols[0]:
            st.metric("Check-in Locations", f"{len(checkin_geo):,}")
        with m_cols[1]:
            st.metric("Total Check-ins", f"{int(checkin_geo['Plays'].sum()):,}")

    # ── Flythrough recording ──────────────────────────────────────────────────
    st.subheader("Cinematic Fly-through")

    if "geo_flythrough_path" not in st.session_state:
        st.session_state["geo_flythrough_path"] = _build_flythrough_filename(
            selected_artist, date_range if date_range else ()
        )

    path_col, browse_col = st.columns([4, 1])
    with path_col:
        st.text_input("Output file", key="geo_flythrough_path")
    with browse_col:
        st.write("")
        if st.button("Browse…", key="geo_flythrough_browse"):
            chosen = _open_save_dialog(
                str(st.session_state.get("geo_flythrough_path", "flythrough.mp4"))
            )
            if chosen:
                st.session_state["geo_flythrough_path"] = chosen
                st.rerun()

    record_col, _ = st.columns([1, 3])
    with record_col:
        record_clicked = st.button("▶ Record Flythrough", type="primary")

    if record_clicked:
        out_path = str(st.session_state.get("geo_flythrough_path") or "flythrough.mp4")
        loaded_config = st.session_state.get("_loaded_config")
        csv_path = loaded_config[0] if loaded_config else None
        swarm_dir_cfg = loaded_config[1] if loaded_config else None
        assumptions_cfg = loaded_config[2] if loaded_config else None

        cmd: list[str] = [sys.executable, _RECORD_SCRIPT]
        if csv_path:
            cmd.append(csv_path)
        cmd.extend(["--output", out_path])
        cmd.extend(["--marker_size", str(zoom_level)])
        if selected_artist != "All":
            cmd.extend(["--artist", selected_artist])
        if date_range and len(date_range) == 2:
            cmd.extend(["--start_date", date_range[0].isoformat()])
            cmd.extend(["--end_date", date_range[1].isoformat()])
        if swarm_dir_cfg:
            cmd.extend(["--swarm_dir", swarm_dir_cfg])
        if assumptions_cfg:
            cmd.extend(["--assumptions", assumptions_cfg])
        if active_states:
            cmd.extend(["--highlight_states", ",".join(active_states)])

        with st.status("Recording flythrough…", expanded=True) as rec_status:
            log_container = st.empty()
            lines: list[str] = []
            with subprocess.Popen(  # noqa: S603 — cmd is constructed from sys.executable + known script
                cmd,  # noqa: S603
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            ) as proc:
                assert proc.stdout  # guaranteed by stdout=PIPE
                for raw in proc.stdout:
                    lines.append(raw.rstrip())
                    log_container.code("\n".join(lines[-50:]))
            if proc.returncode == 0:
                rec_status.update(label=f"Recording saved to: {out_path}", state="complete")
            else:
                rec_status.update(label="Recording failed — see log above.", state="error")


def _render_2d_map(
    music_df: DataFrame | None,
    swarm_df: DataFrame | None,
    selected_layers: list[str],
    selected_artist: str,
) -> None:
    """Render Plotly 2D scatter map with scrobble and/or check-in dots."""
    has_music = music_df is not None and not music_df.empty
    has_swarm = swarm_df is not None and not swarm_df.empty

    show_scrobbles = "Scrobbles" in selected_layers and has_music
    show_checkins = "Check-ins" in selected_layers and has_swarm

    if not show_scrobbles and not show_checkins:
        st.info("No data to display. Enable at least one data layer in the Filter panel.")
        return

    # Read breakdown selection set in the Filter popover on the previous render.
    breakdown = st.session_state.get("geo_breakdown", "By Artist")

    map_frames: list[DataFrame] = []

    if show_scrobbles and music_df is not None:
        if breakdown == "By City":
            city_stats = _build_city_stats(music_df)
            if not city_stats.empty:
                map_frames.append(
                    city_stats[["city", "lat", "lng", "plays"]].assign(layer="Scrobble")
                )
        else:
            # music_df is already artist-filtered by the caller; pass "All" so
            # build_map_data aggregates the pre-filtered data without re-filtering.
            scrobble_data = build_map_data(music_df, "All")
            if not scrobble_data.empty:
                if selected_artist == "All":
                    top_artists = (
                        scrobble_data.groupby("artist")["plays"]
                        .sum()
                        .nlargest(_MAP_MAX_ARTISTS)
                        .index
                    )
                    scrobble_data = scrobble_data[scrobble_data["artist"].isin(top_artists)]
                    if len(scrobble_data) < len(build_map_data(music_df, "All")):
                        st.caption(
                            f"Scrobble map shows top {_MAP_MAX_ARTISTS} artists. "
                            "Select a specific artist to see all locations."
                        )
                scrobble_data = scrobble_data.assign(layer="Scrobble")
                map_frames.append(scrobble_data)

    if show_checkins and swarm_df is not None:
        swarm_cols = {"lat", "lng", "city"}
        if swarm_cols.issubset(swarm_df.columns):
            ci = (
                swarm_df.dropna(subset=["lat", "lng", "city"])
                .groupby(["lat", "lng", "city"])
                .size()
                .reset_index(name="plays")
            )
            if not ci.empty:
                # In city mode, label check-ins distinctly so they don't merge with
                # scrobble city dots that happen to share the same city name.
                ci = ci.assign(
                    artist="Check-in",
                    city="Check-ins" if breakdown == "By City" else ci["city"],
                    layer="Check-in",
                )
                map_frames.append(ci)

    if not map_frames:
        st.info("No geographic data found for the selected filters.")
        return

    combined = pd.concat(map_frames, ignore_index=True)

    if breakdown == "By City":
        color_col = "city"
        title = (
            f"Plays by City — {selected_artist}" if selected_artist != "All" else "Plays by City"
        )
        hover_data: dict = {"plays": True, "city": False, "lat": False, "lng": False}
    else:
        color_col = "artist"
        title = (
            f"Listening locations — {selected_artist}"
            if selected_artist != "All"
            else "Listening locations"
        )
        hover_data = {"plays": True, "artist": True, "lat": False, "lng": False}

    fig = px.scatter_map(
        combined,
        lat="lat",
        lon="lng",
        color=color_col,
        size="plays",
        size_max=40,
        hover_name="city",
        hover_data=hover_data,
        color_discrete_sequence=COLORWAY,
        zoom=1,
        title=title,
    )
    fig.update_layout(
        map_style="carto-darkmatter",
        height=560,
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
    )
    apply_dark_theme(fig)
    st.plotly_chart(fig, width="stretch")

    total_plays = int(combined["plays"].sum())
    top_row = combined.loc[combined["plays"].idxmax()]
    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        st.metric("Cities" if breakdown == "By City" else "Locations", f"{len(combined):,}")
    with mc2:
        st.metric("Total Plays (mapped)", f"{total_plays:,}")
    with mc3:
        st.metric("Top City", str(top_row["city"]))


def _render_us_choropleth(music_df: DataFrame | None, selected_artist: str) -> None:
    """Render the US choropleth scrobble density map."""
    if music_df is None or music_df.empty:
        st.info("No scrobble data loaded.")
        return

    if "state" not in music_df.columns:
        st.info(
            "No location data found. "
            "Link a Foursquare/Swarm export so that tracks can be assigned to states."
        )
        return

    us_df = filter_us_states(music_df)
    if us_df.empty:
        st.info(
            "No US listening data found. "
            "This view only shows plays assigned to US states via Swarm check-ins "
            "or location assumptions."
        )
        return

    stats = build_state_stats(us_df)
    total_us_plays = int(stats["plays"].sum())

    st.markdown(f"**{total_us_plays:,}** US scrobbles tracked across **{len(stats)}** states.")

    colorscale = [[v, c] for v, c in SEQUENTIAL_SCALE]
    fig = px.choropleth(
        stats,
        locations="state",
        locationmode="USA-states",
        color="plays",
        scope="usa",
        color_continuous_scale=colorscale,
        labels={"plays": "Scrobbles", "state": "State"},
        hover_data={"state": True, "plays": True, "top_artist": True, "top_track": True},
        custom_data=["state", "plays", "top_artist", "top_track"],
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Plays: %{customdata[1]:,}<br>"
            "Top artist: %{customdata[2]}<br>"
            "Top track: %{customdata[3]}<extra></extra>"
        )
    )
    fig.update_layout(
        geo=dict(bgcolor="rgba(0,0,0,0)", lakecolor="rgba(0,0,0,0)"),
        coloraxis_colorbar=dict(title="Plays"),
        margin=dict(l=0, r=0, t=0, b=0),
    )
    apply_dark_theme(fig)
    st.plotly_chart(fig, width="stretch")

    st.subheader("State Detail")
    state_options = ["— select a state —"] + sorted(stats["state"].tolist())
    sel_state = st.selectbox("Select a state", state_options, label_visibility="collapsed")

    if sel_state and sel_state != "— select a state —":
        row = stats.loc[stats["state"] == sel_state].iloc[0]
        col_left, col_right = st.columns(2)
        with col_left:
            st.metric("Total Plays", f"{int(row['plays']):,}")
            st.markdown("**Top 5 Artists**")
            for entry in row["top_artists_list"]:
                st.markdown(f"- {entry}")
        with col_right:
            st.markdown("**Top 5 Tracks**")
            for entry in row["top_tracks_list"]:
                st.markdown(f"- {entry}")

    display_df = stats[["state", "plays", "top_artist", "top_track"]].rename(
        columns={
            "state": "State",
            "plays": "Plays",
            "top_artist": "Top Artist",
            "top_track": "Top Track",
        }
    )
    st.dataframe(display_df, hide_index=True, width="stretch")


def _render_table(music_df: DataFrame | None, selected_artist: str) -> None:
    """Render the paginated artist-city summary table."""
    if music_df is None or music_df.empty:
        st.info("No scrobble data loaded.")
        return

    show_mode = st.radio("Show", ["By Artist", "By City"], horizontal=True, key="geo_table_show")
    if show_mode == "By City":
        _render_city_breakdown(music_df)
        return

    # By Artist ──────────────────────────────────────────────────────────────
    _cache_key = id(music_df)
    if st.session_state.get("_geo_table_key") != _cache_key:
        st.session_state["_geo_table_cache"] = build_artist_city_table(music_df)
        st.session_state["_geo_table_key"] = _cache_key
    table_df: DataFrame = st.session_state["_geo_table_cache"]

    if table_df.empty:
        st.info("No data available.")
        return

    sort_by = st.radio("Sort by", ["Plays", "Alphabetical"], horizontal=True, key="geo_table_sort")
    if sort_by == "Alphabetical":
        table_df = table_df.sort_values("artist", key=lambda s: s.str.lower())

    total_artists = len(table_df)
    total_pages = max(1, (total_artists + _TABLE_PAGE_SIZE - 1) // _TABLE_PAGE_SIZE)
    page = st.number_input(
        f"Page (of {total_pages})",
        min_value=1,
        max_value=total_pages,
        value=1,
        step=1,
        key="geo_table_page",
    )
    start = (page - 1) * _TABLE_PAGE_SIZE
    end = start + _TABLE_PAGE_SIZE
    display = table_df.iloc[start:end].reset_index(drop=True)
    display.index = range(start + 1, start + 1 + len(display))

    st.caption(f"Showing {start + 1}–{min(end, total_artists)} of {total_artists:,} artists")
    st.dataframe(
        display.rename(
            columns={
                "artist": "Artist",
                "home_city": "Home City",
                "first_play_city": "First Play City",
                "total_plays": "Total Plays",
                "cities_count": "Cities",
            }
        ),
        width="stretch",
    )

    # Artist detail card
    st.subheader("Artist Detail")
    artist_options = music_df.groupby("artist").size().sort_values(ascending=False).index.tolist()
    default_idx = (
        artist_options.index(selected_artist)
        if selected_artist != "All" and selected_artist in artist_options
        else 0
    )
    selected_detail: str | None = st.selectbox(
        "Select an artist to explore",
        options=artist_options,
        index=default_idx,
        key="geo_table_artist_detail",
    )
    if selected_detail:
        with st.container(border=True):
            _render_artist_detail(selected_detail, music_df)


# ---------------------------------------------------------------------------
# 2D map city-breakdown helpers
# ---------------------------------------------------------------------------


def _build_city_stats(df: DataFrame) -> DataFrame:
    """Aggregate per-city listening statistics from the merged DataFrame.

    Groups rows by ``city`` + ``country`` and computes play counts, unique
    artist count, top artist/track, most active hour, date range, lat/lng
    centroid, and estimated listening time.

    Args:
        df: Merged listening-history DataFrame.  Must contain ``city``,
            ``country``, ``lat``, ``lng``, ``artist``, ``track``,
            ``date_text``, and ``album`` columns.

    Returns:
        DataFrame with one row per (city, country) pair and computed stat
        columns.  Returns an empty DataFrame when input is empty or missing
        required columns.
    """
    if df.empty:
        return pd.DataFrame()

    required = {"city", "lat", "lng", "artist", "track", "date_text"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    geo_df = df.dropna(subset=["lat", "lng", "city"]).copy()
    if geo_df.empty:
        return pd.DataFrame()

    # Fill missing country so groupby doesn't silently drop those rows.
    if "country" in geo_df.columns:
        geo_df["country"] = geo_df["country"].fillna("")
    else:
        geo_df["country"] = ""

    rows: list[dict] = []
    for (city, country), group in geo_df.groupby(["city", "country"], sort=False):
        plays = len(group)
        unique_artists = group["artist"].nunique()

        top_artist_series = group["artist"].value_counts()
        top_artist = str(top_artist_series.index[0]) if not top_artist_series.empty else ""

        top_track_series = group["track"].value_counts()
        top_track = str(top_track_series.index[0]) if not top_track_series.empty else ""

        top_album = ""
        if "album" in group.columns:
            top_album_series = group["album"].value_counts()
            top_album = str(top_album_series.index[0]) if not top_album_series.empty else ""

        most_active_hour = int(group["date_text"].dt.hour.value_counts().index[0])
        first_play = group["date_text"].min()
        last_play = group["date_text"].max()
        lat = float(group["lat"].mean())
        lng = float(group["lng"].mean())

        rows.append(
            {
                "city": city,
                "country": country,
                "plays": plays,
                "unique_artists": unique_artists,
                "top_artist": top_artist,
                "top_track": top_track,
                "top_album": top_album,
                "most_active_hour": most_active_hour,
                "est_listening_hrs": round(plays * _AVG_TRACK_MINUTES / 60, 1),
                "first_play": first_play,
                "last_play": last_play,
                "lat": lat,
                "lng": lng,
            }
        )

    return pd.DataFrame(rows).sort_values("plays", ascending=False).reset_index(drop=True)


def _render_atlas_city_detail(city: str, city_stats: DataFrame, full_df: DataFrame) -> None:
    """Render a detail card for a selected city with top-10 artists.

    Args:
        city: Name of the selected city.
        city_stats: Full city-stats table from ``_build_city_stats``.
        full_df: Raw (pre-filter) listening history DataFrame.
    """
    row = city_stats[city_stats["city"] == city]
    if row.empty:
        return

    r = row.iloc[0]
    st.subheader(f"{city}, {r['country']}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Plays", f"{r['plays']:,}")
    col2.metric("Est. Listening", f"{r['est_listening_hrs']} hrs")
    col3.metric("Unique Artists", f"{r['unique_artists']:,}")
    col4.metric("Most Active Hour", f"{int(r['most_active_hour']):02d}:00")

    col5, col6, col7 = st.columns(3)
    col5.metric("Top Artist", str(r["top_artist"]))
    col6.metric("Top Track", str(r["top_track"]))
    col7.metric("Top Album", str(r["top_album"]) if r["top_album"] else "—")

    first = r["first_play"]
    last = r["last_play"]
    if hasattr(first, "strftime"):
        st.caption(f"Date range: {first.strftime('%Y-%m-%d')} — {last.strftime('%Y-%m-%d')}")

    city_df = full_df[full_df["city"] == city]
    top10 = get_top_entities(city_df, entity="artist", limit=10)
    if not top10.empty:
        fig = px.bar(
            top10,
            x="Plays",
            y="artist",
            orientation="h",
            title=f"Top 10 Artists in {city}",
            labels={"artist": "Artist"},
            color="Plays",
            color_continuous_scale=[[0.0, ACCENT_INDIGO], [1.0, ACCENT_CYAN]],
        )
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            showlegend=False,
            coloraxis_showscale=False,
        )
        apply_dark_theme(fig)
        st.plotly_chart(fig, width="stretch")


def _render_artist_detail(artist: str, df: DataFrame) -> None:
    """Render a detail card for a selected artist with top-10 tracks.

    Args:
        artist: Name of the selected artist.
        df: Filtered listening history DataFrame.
    """
    artist_df = df[df["artist"] == artist]
    if artist_df.empty:
        return

    st.subheader(artist)

    plays = len(artist_df)
    est_hrs = round(plays * _AVG_TRACK_MINUTES / 60, 1)
    most_active_hour = int(artist_df["date_text"].dt.hour.value_counts().index[0])

    top_track = str(artist_df["track"].value_counts().index[0])

    top_album = "—"
    if "album" in artist_df.columns:
        non_null = artist_df["album"].dropna()
        if not non_null.empty:
            top_album = str(non_null.value_counts().index[0])

    top_city = "—"
    if "city" in artist_df.columns:
        non_null = artist_df["city"].dropna()
        if not non_null.empty:
            top_city = str(non_null.value_counts().index[0])

    first = artist_df["date_text"].min()
    last = artist_df["date_text"].max()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Plays", f"{plays:,}")
    col2.metric("Est. Listening", f"{est_hrs} hrs")
    col3.metric("Most Active Hour", f"{most_active_hour:02d}:00")
    col4.metric("Top City", top_city)

    col5, col6 = st.columns(2)
    col5.metric("Top Track", top_track)
    col6.metric("Top Album", top_album)

    if hasattr(first, "strftime"):
        st.caption(f"Date range: {first.strftime('%Y-%m-%d')} — {last.strftime('%Y-%m-%d')}")

    top10 = get_top_entities(artist_df, entity="track", limit=10)
    if not top10.empty:
        fig = px.bar(
            top10,
            x="Plays",
            y="track",
            orientation="h",
            title=f"Top 10 Tracks — {artist}",
            labels={"track": "Track"},
            color="Plays",
            color_continuous_scale=[[0.0, ACCENT_INDIGO], [1.0, ACCENT_CYAN]],
        )
        fig.update_layout(
            yaxis={"categoryorder": "total ascending"},
            showlegend=False,
            coloraxis_showscale=False,
        )
        apply_dark_theme(fig)
        st.plotly_chart(fig, width="stretch")


def _render_city_breakdown(music_df: DataFrame) -> None:
    """Render the city breakdown table and detail card within the 2D Map view.

    Args:
        music_df: Artist/date-filtered listening history DataFrame.
    """
    city_stats = _build_city_stats(music_df)
    if city_stats.empty:
        st.info("No per-city data could be computed from the current dataset.")
        return

    display_cols = [
        "city",
        "country",
        "plays",
        "est_listening_hrs",
        "unique_artists",
        "top_artist",
        "top_track",
    ]
    available_cols = [c for c in display_cols if c in city_stats.columns]
    col_config: dict[str, object] = {
        "city": st.column_config.TextColumn("City"),
        "country": st.column_config.TextColumn("Country"),
        "plays": st.column_config.NumberColumn("Plays", format="%d"),
        "est_listening_hrs": st.column_config.NumberColumn("Est. Hours", format="%.1f"),
        "unique_artists": st.column_config.NumberColumn("Unique Artists", format="%d"),
        "top_artist": st.column_config.TextColumn("Top Artist"),
        "top_track": st.column_config.TextColumn("Top Track"),
    }
    st.dataframe(
        city_stats[available_cols],
        hide_index=True,
        column_config=col_config,
        width="stretch",
    )

    city_names = city_stats["city"].tolist()
    selected_city: str | None = st.selectbox(
        "Select a city to explore",
        options=city_names,
        index=0,
        key="geo_2d_city_detail",
    )
    if selected_city:
        with st.container(border=True):
            _render_atlas_city_detail(selected_city, city_stats, music_df)


# ---------------------------------------------------------------------------
# Main render entry point
# ---------------------------------------------------------------------------


def render_geo_explorer() -> None:
    """Render the Geo Explorer page.

    Reads ``st.session_state['df']`` (scrobbles) and ``st.session_state['swarm_df']``
    (Foursquare/Swarm check-ins).  Shows an empty state when neither is loaded.

    Four view modes are available via a segmented control:

    * **3D Globe** — Pydeck globe with country/state overlays and flythrough recording.
    * **2D Map** — Plotly scatter_map dots sized by play count; "By City" radio below
      the map switches to a city breakdown table and detail card.
    * **US States** — Plotly choropleth coloured by scrobble density per state.
    * **Table** — Paginated artist-city summary table with sort options.

    Filters (artist, date range, data layers) and 3D camera settings are in
    popovers so the main canvas remains uncluttered.
    """
    df: DataFrame | None = st.session_state.get("df")
    swarm_df: DataFrame | None = st.session_state.get("swarm_df")

    st.header("Geo Explorer")
    st.caption("Your music and places — every angle")

    has_music = (
        df is not None and not df.empty and "lat" in df.columns and not df["lat"].isna().all()
    )
    has_swarm = (
        swarm_df is not None
        and not swarm_df.empty
        and "lat" in (swarm_df.columns if swarm_df is not None else [])
    )
    has_any = has_music or has_swarm

    if df is None or df.empty:
        st.info(
            "No music data loaded yet. "
            "Configure a Last.fm source in the sidebar and select a data file."
        )
        return

    if not has_any:
        st.warning(
            "No geographic data found. "
            "Provide a Swarm data directory in the sidebar to enable map views."
        )
        return

    # ── Top control bar ───────────────────────────────────────────────────────
    hdr_col, filt_col, set_col, help_col = st.columns([5, 1, 1, 1])

    with hdr_col:
        view: str = st.segmented_control(
            "View",
            options=[_VIEW_3D, _VIEW_2D, _VIEW_US, _VIEW_TABLE],
            default=_VIEW_2D,
            key="geo_view",
            label_visibility="collapsed",
        )

    # ── Filter popover ────────────────────────────────────────────────────────
    available_layers: list[str] = []
    if has_music:
        available_layers.append("Scrobbles")
    if has_swarm:
        available_layers.append("Check-ins")

    selected_layers: list[str] = []
    selected_artist = "All"
    date_range: tuple = ()

    with filt_col:
        with st.popover("⚡ Filter"):
            raw_layers = st.pills(
                "Data layers",
                available_layers,
                default=available_layers,
                selection_mode="multi",
                key="geo_layers",
            )
            selected_layers = list(raw_layers) if raw_layers else []

            if has_music and df is not None:
                artists = ["All"] + sorted(df["artist"].dropna().unique().tolist())
                selected_artist = st.selectbox("Artist", artists, key="geo_artist")

            if has_music and df is not None:
                min_date = df["date_text"].min().date()
                max_date = df["date_text"].max().date()
                raw_dr = st.date_input(
                    "Date range",
                    value=(min_date, max_date),
                    key="geo_date_range",
                )
                date_range = tuple(raw_dr) if raw_dr else ()

            if view == _VIEW_2D and has_music:
                st.radio(
                    "Map breakdown",
                    ["By Artist", "By City"],
                    horizontal=True,
                    key="geo_breakdown",
                )

    # ── Settings popover (3D only) ────────────────────────────────────────────
    with set_col:
        with st.popover("⚙ Settings"):
            if view == _VIEW_3D:
                # Values stored in session_state via key=; read below before dispatch
                st.slider("Marker Size", 1.0, 10.0, 5.5, 0.5, key="geo_marker_size")
                st.slider("Rotation", -180.0, 180.0, 0.0, 5.0, key="geo_bearing")
                st.slider("Tilt", 0.0, 90.0, 45.0, 5.0, key="geo_pitch")
            else:
                st.caption("Camera settings apply only to the 3D Globe view.")

    # ── Help popover ──────────────────────────────────────────────────────────
    with help_col:
        with st.popover("? Help"):
            if view == _VIEW_3D:
                st.markdown(
                    "**3D Globe gestures**\n"
                    "- **Pan**: left-click drag\n"
                    "- **Rotate / Tilt**: right-click drag, or use ⚙ Settings sliders\n"
                    "- **Zoom**: scroll wheel\n"
                    "- **Hover**: city name + play count tooltip"
                )
            elif view == _VIEW_2D:
                st.markdown(
                    "**2D Map gestures**\n"
                    "- **Pan**: click drag\n"
                    "- **Zoom**: scroll wheel or pinch\n"
                    "- **Hover**: city details\n"
                    "- Use **By City** breakdown for city stats and top-10 artists"
                )
            elif view == _VIEW_US:
                st.markdown(
                    "**US States**\n"
                    "- **Hover** a state for a quick summary\n"
                    "- Use the **State Detail** dropdown for top artists & tracks"
                )
            else:
                st.markdown(
                    "**Table**\n"
                    "- **Sort** by Plays or Alphabetical using the radio buttons\n"
                    "- **Page** through artists with the page number input"
                )

    # ── Apply filters to music data ───────────────────────────────────────────
    music_df: DataFrame | None = df.copy() if has_music and df is not None else None
    if music_df is not None and len(date_range) == 2:
        music_df = music_df[
            (music_df["date_text"].dt.date >= date_range[0])
            & (music_df["date_text"].dt.date <= date_range[1])
        ]
    if music_df is not None and selected_artist != "All":
        music_df = music_df[music_df["artist"] == selected_artist]

    # ── Share button (scrobble views only) ────────────────────────────────────
    if view in (_VIEW_2D, _VIEW_US) and music_df is not None and not music_df.empty:
        generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        from export_html import build_places_page_html

        html_bytes = build_places_page_html(df, generated_at).encode("utf-8")
        render_share_button(html_bytes, "autobiographer-geo-explorer.html")

    # ── Read 3D settings from session state (set inside popover) ─────────────
    zoom_level_val = float(st.session_state.get("geo_marker_size", 5.5))
    bearing_val = float(st.session_state.get("geo_bearing", 0.0))
    pitch_val = float(st.session_state.get("geo_pitch", 45.0))

    # ── View dispatch ─────────────────────────────────────────────────────────
    if view == _VIEW_3D:
        _render_3d_globe(
            music_df,
            swarm_df,
            selected_layers,
            zoom_level_val,
            bearing_val,
            pitch_val,
            selected_artist,
            date_range,
        )
    elif view == _VIEW_2D:
        _render_2d_map(music_df, swarm_df, selected_layers, selected_artist)
    elif view == _VIEW_US:
        _render_us_choropleth(music_df, selected_artist)
    else:
        _render_table(music_df, selected_artist)
