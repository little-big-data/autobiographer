from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pydeck as pdk
from moviepy import ImageSequenceClip
from playwright.async_api import async_playwright

from components.theme import (
    MAP_COLUMN_DEFAULT_RGBA,
    MAP_COUNTRY_BORDER_RGB,
    MAP_COUNTRY_UNVISITED_RGBA,
    MAP_COUNTRY_VISITED_RGBA,
    MAP_STATE_BORDER_RGBA,
)
from pages.geo_explorer import build_state_highlight_layer


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points in kilometers."""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def filter_data(
    df: pd.DataFrame,
    artist: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Apply filters to the dataframe."""
    filtered_df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(filtered_df["date_text"]):
        filtered_df["date_text"] = pd.to_datetime(filtered_df["date_text"])
    if artist and artist != "All":
        filtered_df = filtered_df[filtered_df["artist"] == artist]
    if start_date:
        filtered_df = filtered_df[filtered_df["date_text"] >= pd.to_datetime(start_date)]
    if end_date:
        filtered_df = filtered_df[filtered_df["date_text"] <= pd.to_datetime(end_date)]
    return filtered_df


def interpolate_views(start: dict, end: dict, n_frames: int, easing: str = "sine") -> list[dict]:
    """Interpolate between two view states, including timestamp."""
    if n_frames <= 0:
        return []
    t = np.linspace(0, 1, n_frames)
    if easing == "sine":
        t_eased = (1 - np.cos(t * np.pi)) / 2
    elif easing == "cubic":
        t_eased = np.where(t < 0.5, 4 * t**3, 1 - np.power(-2 * t + 2, 3) / 2)
    else:
        t_eased = t

    res = []
    for i in range(n_frames):
        view = {
            "latitude": start["latitude"] + t_eased[i] * (end["latitude"] - start["latitude"]),
            "longitude": start["longitude"] + t_eased[i] * (end["longitude"] - start["longitude"]),
            "zoom": start["zoom"] + t_eased[i] * (end["zoom"] - start["zoom"]),
            "pitch": start["pitch"] + t_eased[i] * (end["pitch"] - start["pitch"]),
            "bearing": start["bearing"] + t_eased[i] * (end["bearing"] - start["bearing"]),
        }
        # Interpolate timestamp linearly
        if "timestamp" in start and "timestamp" in end:
            view["timestamp"] = start["timestamp"] + t[i] * (end["timestamp"] - start["timestamp"])
        res.append(view)
    return res


async def capture_frames(
    html_path: str,
    frames_dir: str,
    view_states: list[dict],
    viewport: tuple[int, int] = (1920, 1080),
) -> None:
    """Capture PNG frames using Playwright."""
    os.makedirs(frames_dir, exist_ok=True)
    with open(html_path, encoding="utf-8") as f:
        html_content = f.read()

    # Hijack script + Overlay setup
    hijack_script = """
    <script>
    (function() {
        window.deckglInstance = undefined;
        let _realCreateDeck = window.createDeck;
        Object.defineProperty(window, 'createDeck', {
            get: function() {
                return function(props) {
                    if (typeof _realCreateDeck !== 'function') return null;
                    const instance = _realCreateDeck(props);
                    window.deckglInstance = instance;
                    return instance;
                };
            },
            set: function(val) { _realCreateDeck = val; },
            configurable: true
        });

        // Add overlay div
        window.addEventListener('DOMContentLoaded', () => {
            const overlay = document.createElement('div');
            overlay.id = 'date-overlay';
            overlay.style.position = 'absolute';
            overlay.style.bottom = '40px';
            overlay.style.left = '40px';
            overlay.style.color = 'white';
            overlay.style.fontSize = '32px';
            overlay.style.fontFamily = 'sans-serif';
            overlay.style.fontWeight = 'bold';
            overlay.style.textShadow = '2px 2px 4px rgba(0,0,0,0.8)';
            overlay.style.zIndex = '9999';
            overlay.style.pointerEvents = 'none';
            document.body.appendChild(overlay);
        });
    })();
    </script>
    """
    html_content = html_content.replace("<head>", f"<head>{hijack_script}")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print("Starting frame capture...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=[
                "--disable-web-security",
                "--allow-file-access-from-files",
                "--use-gl=angle",
                "--use-angle=gl",
                "--ignore-gpu-blocklist",
                "--disable-gpu-allowlist",
            ]
        )
        page = await browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})

        abs_html_path = f"file:///{os.path.abspath(html_path)}".replace("\\", "/")
        await page.goto(abs_html_path, wait_until="networkidle")

        try:
            await page.wait_for_function("window.deckglInstance !== undefined", timeout=30000)
        except Exception:
            print("Error: Map instance not found.")

        await asyncio.sleep(10)  # Wait for tiles
        await page.add_style_tag(content=".deck-tooltip { display: none !important; }")

        for i, vs in enumerate(view_states):
            if i % 50 == 0:
                print(f"Capturing frame {i}/{len(view_states)}...")

            # Format date string for the overlay
            date_str = ""
            if "timestamp" in vs:
                dt = datetime.fromtimestamp(int(vs["timestamp"]))
                date_str = dt.strftime("%A, %B %d, %Y")

            await page.evaluate(f"""
                if(window.deckglInstance) window.deckglInstance.setProps({{viewState: {json.dumps(vs)}}});
                const overlay = document.getElementById('date-overlay');
                if(overlay) overlay.innerText = {json.dumps(date_str)};
            """)

            await asyncio.sleep(0.05)
            await page.screenshot(path=os.path.join(frames_dir, f"frame_{i:04d}.png"), type="png")

        await browser.close()


def sanitize_native(val: Any) -> Any:
    """Convert numpy types to native Python types for JSON serializability."""
    if hasattr(val, "item"):
        return val.item()
    if isinstance(val, dict):
        return {k: sanitize_native(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [sanitize_native(x) for x in val]
    return val


def create_recording_assets(
    csv_path: str | None = None,
    artist: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    marker_size: float = 5.5,
    swarm_dir: str | None = None,
    assumptions_path: str | None = None,
    highlight_states: list[str] | None = None,
) -> tuple | None:
    """Load data and prepare the PyDeck object and keyframes."""
    if not csv_path:
        data_dir = os.getenv("AUTOBIO_LASTFM_DATA_DIR", "data")
        if os.path.exists(data_dir):
            files = [f for f in os.listdir(data_dir) if f.endswith("_tracks.csv")]
            if files:
                csv_path = os.path.join(data_dir, files[0])
            else:
                return None, None
        else:
            return None, None

    from analysis_utils import (
        apply_swarm_offsets,
        load_assumptions,
        load_listening_data,
        load_swarm_data,
    )

    df = load_listening_data(csv_path)
    if df is None:
        return None, None

    if "lat" not in df.columns or df["lat"].isna().all():
        swarm_dir = swarm_dir or os.getenv("AUTOBIO_SWARM_DIR")
        assumptions_path = assumptions_path or os.getenv(
            "AUTOBIO_ASSUMPTIONS_FILE", "default_assumptions.json"
        )
        swarm_df = (
            load_swarm_data(swarm_dir)
            if swarm_dir and os.path.exists(swarm_dir)
            else pd.DataFrame()
        )
        assumptions = load_assumptions(assumptions_path)
        df = apply_swarm_offsets(df, swarm_df, assumptions)

    df = filter_data(df, artist, start_date, end_date)
    if df.empty:
        return None, None

    geo_data = df.groupby(["lat", "lng", "city"]).size().reset_index(name="Plays")
    geo_data["elevation_log"] = np.log1p(geo_data["Plays"])
    max_log = geo_data["elevation_log"].max()

    dynamic_radius = 50000 / (2 ** (marker_size - 1))
    geo_data["elevation"] = (
        (geo_data["elevation_log"] / max_log) * (1.4 * dynamic_radius) if max_log > 0 else 0
    )

    def get_color(val: float, max_val: float) -> list[int]:
        """Interpolate teal → amber to match the application's dark-map palette."""
        if max_val == 0:
            return MAP_COLUMN_DEFAULT_RGBA
        ratio = val / max_val
        if ratio < 0.5:
            # Deep teal [0, 200, 200] → cyan-green [100, 220, 120]
            t = ratio * 2
            r, g, b = int(100 * t), int(200 + 20 * t), int(200 - 80 * t)
        else:
            # Cyan-green [100, 220, 120] → warm amber [255, 160, 20]
            t = (ratio - 0.5) * 2
            r, g, b = int(100 + 155 * t), int(220 - 60 * t), int(120 - 100 * t)
        return [r, g, b, 220]

    geo_data["color"] = geo_data["elevation_log"].apply(lambda x: get_color(x, max_log))

    # Ensure geodata uses standard Python types for serializability (Issue #46 refinement)
    # pd.DataFrame.to_dict('records') helps convert to native types
    records = geo_data.to_dict("records")
    records = [sanitize_native(r) for r in records]

    layer = pdk.Layer(
        "ColumnLayer",
        records,
        get_position=["lng", "lat"],
        get_elevation="elevation",
        elevation_scale=10,
        radius=float(dynamic_radius),
        get_fill_color="color",
        pickable=True,
    )

    # Sort locations chronologically based on first visit
    first_visits = df.groupby(["lat", "lng", "city"])["timestamp"].min().reset_index()
    ordered_locations = first_visits.sort_values("timestamp")

    keyframes = []
    # Start Global
    keyframes.append(
        sanitize_native(
            {
                "latitude": geo_data["lat"].mean(),
                "longitude": geo_data["lng"].mean(),
                "zoom": 2,
                "pitch": 0,
                "bearing": 0,
                "timestamp": ordered_locations["timestamp"].iloc[0],
            }
        )
    )

    # Tour through locations
    for i, (_, row) in enumerate(ordered_locations.iterrows()):
        angle = (i * 45) % 360
        keyframes.append(
            sanitize_native(
                {
                    "latitude": row["lat"],
                    "longitude": row["lng"],
                    "zoom": 11,
                    "pitch": 45 + (i % 3) * 5,
                    "bearing": angle - 180,
                    "timestamp": row["timestamp"],
                }
            )
        )
    # End Global
    keyframes.append(
        sanitize_native(
            {
                "latitude": geo_data["lat"].mean(),
                "longitude": geo_data["lng"].mean(),
                "zoom": 3,
                "pitch": 45,
                "bearing": 0,
                "timestamp": ordered_locations["timestamp"].iloc[-1],
            }
        )
    )

    # Remove timestamp for ViewState but keep it in our keyframes list for interpolation
    vs_init = keyframes[0].copy()
    if "timestamp" in vs_init:
        del vs_init["timestamp"]

    # Build country/state overlay layers matching the render_places map appearance
    geo_layers: list[pdk.Layer] = []
    countries_path = os.path.join("assets", "countries.geojson")
    if os.path.exists(countries_path):
        import geopandas as gpd
        from shapely.geometry import Point

        world = gpd.read_file(countries_path)
        geometry = [Point(xy) for xy in zip(geo_data["lng"], geo_data["lat"])]
        points_gpd = gpd.GeoDataFrame(geo_data[["lat", "lng"]], geometry=geometry, crs="EPSG:4326")
        visited_idx = set(gpd.sjoin(world, points_gpd, how="inner", predicate="intersects").index)
        world["fill_color"] = world.index.map(
            lambda i: MAP_COUNTRY_VISITED_RGBA if i in visited_idx else MAP_COUNTRY_UNVISITED_RGBA
        )
        geo_layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                world,
                stroked=True,
                filled=True,
                get_fill_color="fill_color",
                get_line_color=MAP_COUNTRY_BORDER_RGB,
                get_line_width=1,
            )
        )
        states_path = os.path.join("assets", "states.geojson")
        if os.path.exists(states_path):
            geo_layers.append(
                pdk.Layer(
                    "GeoJsonLayer",
                    states_path,
                    stroked=True,
                    filled=False,
                    get_line_color=MAP_STATE_BORDER_RGBA,
                    get_line_width=1,
                )
            )

    # State polygon outlines (match Geo Explorer 3D Globe appearance)
    if highlight_states:
        state_layer = build_state_highlight_layer(highlight_states)
        if state_layer is not None:
            geo_layers.insert(0, state_layer)

    deck = pdk.Deck(
        layers=[*geo_layers, layer],
        initial_view_state=pdk.ViewState(**vs_init),
        map_style="dark",
    )
    return deck, keyframes


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a cinematic fly-through video.")
    parser.add_argument(
        "csv",
        nargs="?",
        help="Path to Last.fm tracks CSV (required; script exits silently if omitted and no *_tracks.csv exists in the data/ directory)",
    )
    parser.add_argument(
        "--output",
        default="flythrough.mp4",
        help="Output path; use .mp4 for video or .html for an interactive animation (default: flythrough.mp4)",
    )
    parser.add_argument("--artist", help="Filter to a single artist name")
    parser.add_argument("--start_date", help="Inclusive start date filter (YYYY-MM-DD)")
    parser.add_argument("--end_date", help="Inclusive end date filter (YYYY-MM-DD)")
    parser.add_argument(
        "--marker_size",
        type=float,
        default=5.5,
        help="Marker size scaling: higher values produce smaller, more precise markers (default: 5.5)",
    )
    parser.add_argument("--fps", type=int, default=30, help="Video frame rate (default: 30)")
    parser.add_argument(
        "--width", type=int, default=1920, help="Video width in pixels (default: 1920)"
    )
    parser.add_argument(
        "--height", type=int, default=1080, help="Video height in pixels (default: 1080)"
    )
    parser.add_argument(
        "--assumptions",
        help="Path to location assumptions JSON (default: default_assumptions.json or AUTOBIO_ASSUMPTIONS_FILE env var)",
    )
    parser.add_argument(
        "--swarm_dir",
        help="Path to Foursquare/Swarm export directory; used to geocode listening data when lat/lng is absent",
    )
    parser.add_argument(
        "--keep_frames",
        action="store_true",
        help="Retain the temporary per-frame PNG files after encoding",
    )
    parser.add_argument(
        "--highlight_states",
        help="Comma-separated US state abbreviations to highlight (e.g. 'IL,MD')",
    )

    args = parser.parse_args()
    highlight_states = (
        [s.strip() for s in args.highlight_states.split(",") if s.strip()]
        if args.highlight_states
        else None
    )
    result = create_recording_assets(
        args.csv,
        artist=args.artist,
        start_date=args.start_date,
        end_date=args.end_date,
        marker_size=args.marker_size,
        swarm_dir=args.swarm_dir,
        assumptions_path=args.assumptions,
        highlight_states=highlight_states,
    )

    if result is None:
        return
    deck, keyframes = result
    if not deck:
        return
    if args.output.endswith(".html"):
        deck.to_html(args.output)
        return

    html_temp, frames_dir = "temp_render.html", "temp_frames"
    deck.to_html(html_temp)

    full_path = []
    for i in range(len(keyframes) - 1):
        p1, p2 = keyframes[i], keyframes[i + 1]
        dist = haversine(p1["latitude"], p1["longitude"], p2["latitude"], p2["longitude"])

        if dist < 10:
            duration = 1.0
        elif dist > 50:
            duration = 5.0
        else:
            duration = 3.0

        segment = interpolate_views(p1, p2, int(args.fps * duration))
        full_path.extend(segment[(1 if i > 0 else 0) :])

        if dist > 50:
            full_path.extend([p2] * (args.fps * 2))

    try:
        asyncio.run(
            capture_frames(html_temp, frames_dir, full_path, viewport=(args.width, args.height))
        )
        frames = [
            os.path.join(frames_dir, f)
            for f in sorted(os.listdir(frames_dir))
            if f.endswith(".png")
        ]
        if frames:
            clip = ImageSequenceClip(frames, fps=args.fps)
            clip.write_videofile(args.output, codec="libx264", audio=False)
    finally:
        if os.path.exists(html_temp):
            os.remove(html_temp)
        if not args.keep_frames and os.path.exists(frames_dir):
            import shutil

            shutil.rmtree(frames_dir)


if __name__ == "__main__":
    main()
