"""Places page — geographic listening history map and check-in insights."""

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

from components.share import render_share_button
from components.theme import (
    MAP_COLUMN_DEFAULT_RGBA,
    MAP_COUNTRY_BORDER_RGB,
    MAP_COUNTRY_UNVISITED_RGBA,
    MAP_COUNTRY_VISITED_RGBA,
    MAP_STATE_BORDER_RGBA,
    apply_dark_theme,
)
from export_html import build_checkin_insights_html, build_places_page_html

_RECORD_SCRIPT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "record_flythrough.py")
)


def _build_flythrough_filename(selected_artist: str, date_range: tuple) -> str:
    """Build a default .mp4 filename encoding the current recording settings.

    Args:
        selected_artist: Currently selected artist filter, or ``"All"``.
        date_range: Tuple/list of one or two ``datetime.date`` values.

    Returns:
        Filename string of the form
        ``flythrough_YYYYMMDD_HHMMSS[_artist][_start_end].mp4``.
    """
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
    """Open a native file-save dialog and return the chosen path.

    Uses tkinter in a background thread so the Streamlit server thread is not
    permanently blocked.  Returns ``None`` when the user cancels or tkinter is
    unavailable.

    Args:
        initial_filename: Pre-filled filename shown in the dialog.

    Returns:
        Absolute path chosen by the user, or ``None``.
    """
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
        except Exception:  # noqa: S110 — not available on all platforms
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


def render_spatial_analysis(df: DataFrame) -> None:
    """Render 3D geographical visualization of listening history.

    Args:
        df: Listening history DataFrame with lat/lng/city columns.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    st.header("Spatial Music Explorer")

    if "lat" not in df.columns or df["lat"].isna().all():
        st.warning(
            "No geographic data found. Please provide a Swarm data directory to enable this view."
        )
        return

    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html_bytes = build_places_page_html(df, generated_at).encode("utf-8")
    render_share_button(html_bytes, "autobiographer-places.html")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        artists = ["All"] + sorted(df["artist"].dropna().unique().tolist())
        selected_artist = st.selectbox("Filter by Artist", artists)
    with col_f2:
        min_date = df["date_text"].min().date()
        max_date = df["date_text"].max().date()
        date_range = st.date_input(
            "Filter by Date Range", [min_date, max_date], key="spatial_date_range"
        )

    map_df = df.copy()
    if selected_artist != "All":
        map_df = map_df[map_df["artist"] == selected_artist]

    if len(date_range) == 2:
        map_df = map_df[
            (map_df["date_text"].dt.date >= date_range[0])
            & (map_df["date_text"].dt.date <= date_range[1])
        ]

    if map_df.empty:
        st.info("No data matches the selected filters.")
        return

    geo_data = map_df.groupby(["lat", "lng", "city"]).size().reset_index(name="Plays")

    if "spatial_view_state" not in st.session_state:
        st.session_state.spatial_view_state = pdk.ViewState(
            latitude=geo_data["lat"].mean(),
            longitude=geo_data["lng"].mean(),
            zoom=3,
            pitch=45,
            bearing=0,
        )

    col_a, col_b, col_c = st.columns(3)

    def get_view_val(attr: str, default: float) -> float:
        """Return a float view state attribute with a safe fallback."""
        val = getattr(st.session_state.spatial_view_state, attr, default)
        return float(val) if val is not None else float(default)

    with col_a:
        zoom_level = st.slider(
            "Marker Zoom",
            min_value=1.0,
            max_value=15.0,
            value=get_view_val("zoom", 3.0),
            step=0.5,
            key="zoom_slider",
        )
    with col_b:
        bearing = st.slider(
            "Rotation",
            min_value=-180.0,
            max_value=180.0,
            value=get_view_val("bearing", 0.0),
            step=5.0,
            key="bearing_slider",
        )
    with col_c:
        pitch = st.slider(
            "Tilt",
            min_value=0.0,
            max_value=90.0,
            value=get_view_val("pitch", 45.0),
            step=5.0,
            key="pitch_slider",
        )

    st.session_state.spatial_view_state.zoom = zoom_level
    st.session_state.spatial_view_state.bearing = bearing
    st.session_state.spatial_view_state.pitch = pitch

    st.subheader("Cinematic Fly-through")

    # ── Output path ────────────────────────────────────────────────────────────
    if "flythrough_output_path" not in st.session_state:
        st.session_state["flythrough_output_path"] = _build_flythrough_filename(
            selected_artist, date_range
        )

    path_col, browse_col = st.columns([4, 1])
    with path_col:
        st.text_input(
            "Output file",
            key="flythrough_output_path",
            help="Full path where the .mp4 recording will be saved.",
        )
    with browse_col:
        st.write("")
        if st.button("Browse…", key="flythrough_browse"):
            chosen = _open_save_dialog(
                str(st.session_state.get("flythrough_output_path", "flythrough.mp4"))
            )
            if chosen:
                st.session_state["flythrough_output_path"] = chosen
                st.rerun()

    # ── Action buttons ─────────────────────────────────────────────────────────
    rec_col, exp_col = st.columns([1, 1])
    with rec_col:
        record_clicked = st.button("▶ Record Flythrough", type="primary")
    with exp_col:
        if st.button("Export Recording HTML"):
            top_cities = geo_data.sort_values("Plays", ascending=False).head(8)
            export_keyframes: list[dict[str, float | int]] = [
                {
                    "latitude": geo_data["lat"].mean(),
                    "longitude": geo_data["lng"].mean(),
                    "zoom": 2,
                    "pitch": 0,
                    "bearing": 0,
                    "duration": 2000,
                }
            ]
            for _, row in top_cities.iterrows():
                export_keyframes.append(
                    {
                        "latitude": row["lat"],
                        "longitude": row["lng"],
                        "zoom": 11,
                        "pitch": 60,
                        "bearing": 45,
                        "duration": 4000,
                    }
                )
            export_keyframes.append(
                {
                    "latitude": geo_data["lat"].mean(),
                    "longitude": geo_data["lng"].mean(),
                    "zoom": 3,
                    "pitch": 45,
                    "bearing": 0,
                    "duration": 4000,
                }
            )

            export_deck = pdk.Deck(
                layers=[
                    pdk.Layer(
                        "ColumnLayer",
                        geo_data,
                        get_position=["lng", "lat"],
                        get_elevation="elevation",
                        elevation_scale=10,
                        radius=5000,
                        get_fill_color="color",
                    )
                ],
                initial_view_state=pdk.ViewState(
                    latitude=export_keyframes[0]["latitude"],
                    longitude=export_keyframes[0]["longitude"],
                    zoom=export_keyframes[0]["zoom"],
                ),
                map_style="dark",
            )

            html_content = export_deck.to_html(as_string=True)
            animation_script = f"""
            <script>
            const keyframes = {json.dumps(export_keyframes)};
            let currentStep = 0;
            function nextStep() {{
                if (currentStep >= keyframes.length) return;
                const kf = keyframes[currentStep];
                const deckgl = window.deck.deck;
                deckgl.setProps({{
                    initialViewState: {{
                        ...kf,
                        transitionDuration: kf.duration,
                        transitionInterpolator: new window.deck.FlyToInterpolator()
                    }}
                }});
                currentStep++;
                setTimeout(nextStep, kf.duration + 500);
            }}
            setTimeout(nextStep, 2000);
            </script>
            """
            html_content = html_content.replace("</body>", f"{animation_script}</body>")

            st.download_button(
                label="Download Fly-through HTML",
                data=html_content,
                file_name="music_flythrough.html",
                mime="text/html",
            )

    # ── Subprocess recording with live log ─────────────────────────────────────
    if record_clicked:
        out_path = str(st.session_state.get("flythrough_output_path") or "flythrough.mp4")
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
        if len(date_range) == 2:
            cmd.extend(["--start_date", date_range[0].isoformat()])
            cmd.extend(["--end_date", date_range[1].isoformat()])
        if swarm_dir_cfg:
            cmd.extend(["--swarm_dir", swarm_dir_cfg])
        if assumptions_cfg:
            cmd.extend(["--assumptions", assumptions_cfg])

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

    def get_spectrum_color(val: float, max_val: float) -> list[int]:
        """Return an RGBA color interpolated from teal to amber for dark basemaps.

        Low-play locations render as deep teal; high-play locations render as
        warm amber, both of which read clearly against the dark map background.
        """
        if max_val == 0:
            return MAP_COLUMN_DEFAULT_RGBA
        ratio = val / max_val
        if ratio < 0.5:
            # Deep teal [0, 200, 200] → cyan-green [100, 220, 120]
            t = ratio * 2
            r = int(0 + 100 * t)
            g = int(200 + 20 * t)
            b = int(200 - 80 * t)
        else:
            # Cyan-green [100, 220, 120] → warm amber [255, 160, 20]
            t = (ratio - 0.5) * 2
            r = int(100 + 155 * t)
            g = int(220 - 60 * t)
            b = int(120 - 100 * t)
        return [r, g, b, 220]

    dynamic_radius = 50000 / (2 ** (zoom_level - 1))

    geo_data["elevation_log"] = np.log1p(geo_data["Plays"])
    max_log = geo_data["elevation_log"].max()

    geo_data["elevation"] = (
        (geo_data["elevation_log"] / max_log) * (1.4 * dynamic_radius) if max_log > 0 else 0
    )
    geo_data["color"] = geo_data["elevation_log"].apply(lambda x: get_spectrum_color(x, max_log))

    @st.cache_data
    def get_highlighted_map(geo_points_json: str) -> tuple[object, str | None]:
        """Load world/states GeoJSON and mark countries with listening history."""
        countries_path = os.path.join("assets", "countries.geojson")
        states_path = os.path.join("assets", "states.geojson")
        if not os.path.exists(countries_path):
            return None, None
        world = gpd.read_file(countries_path)
        points_df = __import__("pandas").read_json(io.StringIO(geo_points_json))
        geometry = [Point(xy) for xy in zip(points_df.lng, points_df.lat)]
        points_gpd = gpd.GeoDataFrame(points_df, geometry=geometry, crs="EPSG:4326")
        countries_with_points = gpd.sjoin(world, points_gpd, how="inner", predicate="intersects")

        def country_color_logic(country_idx: int) -> list[int]:
            if country_idx in countries_with_points.index:
                return MAP_COUNTRY_VISITED_RGBA
            return MAP_COUNTRY_UNVISITED_RGBA

        world["fill_color"] = world.index.map(country_color_logic)
        return world, states_path if os.path.exists(states_path) else None

    world_gdf, states_geojson_path = get_highlighted_map(geo_data.to_json())

    layers = []
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
    if states_geojson_path and os.path.exists(states_geojson_path):
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                states_geojson_path,
                stroked=True,
                filled=False,
                get_line_color=MAP_STATE_BORDER_RGBA,
                get_line_width=1,
            )
        )

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

    r = pdk.Deck(
        layers=layers,
        initial_view_state=st.session_state.spatial_view_state,
        tooltip={"text": "{city}: {Plays} plays"},
        map_style="dark",
    )
    st.pydeck_chart(r, key="spatial_map")

    st.markdown("""
    **Map Navigation Gestures:**
    - **Pan**: Left-click and drag.
    - **Rotate/Tilt**: Right-click and drag (or use the sliders above).
    - **Zoom**: Mouse wheel or pinch gesture.
    """)

    st.dataframe(geo_data.sort_values("Plays", ascending=False), hide_index=True)


def render_checkin_insights() -> None:
    """Render the Places Insights page: country and city breakdown of Swarm check-ins.

    Reads ``st.session_state['swarm_df']``.  Shows an empty state when no
    Foursquare/Swarm data has been loaded.
    """
    swarm_df: DataFrame | None = st.session_state.get("swarm_df")

    st.header("Check-in Insights")

    if swarm_df is None or swarm_df.empty:
        st.info(
            "No Foursquare/Swarm data loaded yet. "
            "Configure the Swarm export directory in the sidebar."
        )
        return

    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html_bytes = build_checkin_insights_html(swarm_df, generated_at).encode("utf-8")
    render_share_button(html_bytes, "autobiographer-checkin-insights.html")

    # ── Countries ─────────────────────────────────────────────────────────────
    st.subheader("By Country")
    country_counts = (
        swarm_df.groupby("country").size().reset_index(name="Check-ins")
        if "country" in swarm_df.columns
        else pd.DataFrame(columns=["country", "Check-ins"])
    )
    country_counts = country_counts.sort_values("Check-ins", ascending=False).reset_index(drop=True)

    col1, col2 = st.columns([2, 1])
    with col1:
        fig = px.bar(
            country_counts,
            x="country",
            y="Check-ins",
            title=f"Check-ins across {len(country_counts)} countries",
        )
        apply_dark_theme(fig)
        st.plotly_chart(fig, width="stretch")
    with col2:
        st.dataframe(country_counts, hide_index=True, width="stretch")

    # ── Cities ────────────────────────────────────────────────────────────────
    st.subheader("Top Cities")
    if "city" in swarm_df.columns:
        city_counts = (
            swarm_df.groupby(["city", "country"]).size().reset_index(name="Check-ins")
            if "country" in swarm_df.columns
            else swarm_df.groupby("city").size().reset_index(name="Check-ins")
        )
        city_counts = city_counts.sort_values("Check-ins", ascending=False).reset_index(drop=True)
        limit = st.slider("Cities to show", 10, 50, 20)
        fig2 = px.bar(
            city_counts.head(limit),
            x="Check-ins",
            y="city",
            orientation="h",
            color="country" if "country" in city_counts.columns else None,
            title=f"Top {limit} cities",
        )
        fig2.update_layout(yaxis={"categoryorder": "total ascending"})
        apply_dark_theme(fig2)
        st.plotly_chart(fig2, width="stretch")


def render_places() -> None:
    """Render the Places page: 3D geographic listening history map.

    Reads the active DataFrame from ``st.session_state['df']``.
    Shows an empty state when no data has been loaded.
    """
    df = st.session_state.get("df")
    if df is None or df.empty:
        st.info(
            "No music data loaded yet. "
            "Configure a Last.fm source in the sidebar and select a data file."
        )
        return

    with st.spinner("Loading map..."):
        render_spatial_analysis(df)
