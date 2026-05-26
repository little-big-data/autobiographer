"""Artist Geography page — where you fell in love with each artist.

Shows a scatter map of listening locations sized by play count and coloured per
artist, plus a summary table of each artist's home city (most-played location)
and the city where the first play was recorded.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from pandas import DataFrame

from components.theme import COLORWAY, apply_dark_theme

_TABLE_PAGE_SIZE = 25
_MAP_MAX_ARTISTS = 50  # scatter_mapbox slows badly beyond this many colour traces

# ---------------------------------------------------------------------------
# Pure data helpers (no Streamlit calls — easy to unit-test)
# ---------------------------------------------------------------------------


def build_artist_city_table(df: DataFrame) -> DataFrame:
    """Compute per-artist city statistics: home city and first-play city.

    Groups the listening history by artist and city to sum play counts, then
    derives:

    * **home_city** — the city with the most plays for each artist.
    * **first_play_city** — the city recorded at the artist's earliest
      timestamp.
    * **total_plays** — total scrobbles across all cities for the artist.
    * **cities_count** — number of distinct cities where the artist was heard.

    Args:
        df: Listening history DataFrame.  Must contain ``artist``, ``city``,
            ``timestamp``, and ``lat``/``lng`` columns.

    Returns:
        DataFrame with columns ``[artist, home_city, first_play_city,
        total_plays, cities_count]``, sorted by ``total_plays`` descending.
        Returns an empty DataFrame if required columns are missing.
    """
    required = {"artist", "city", "timestamp"}
    if not required.issubset(df.columns):
        return DataFrame(
            columns=["artist", "home_city", "first_play_city", "total_plays", "cities_count"]
        )

    # Drop rows with null artist/city so groupby is clean
    clean = df.dropna(subset=["artist", "city"])
    if clean.empty:
        return DataFrame(
            columns=["artist", "home_city", "first_play_city", "total_plays", "cities_count"]
        )

    # Plays per (artist, city)
    artist_city = clean.groupby(["artist", "city"]).size().reset_index(name="plays")

    # Home city = city with most plays per artist
    home = (
        artist_city.sort_values("plays", ascending=False)
        .groupby("artist", as_index=False)
        .first()
        .rename(columns={"city": "home_city", "plays": "home_plays"})
    )

    # First-play city: join min timestamp back to get the city at that moment
    first_ts = clean.groupby("artist")["timestamp"].min().reset_index(name="first_ts")
    first_rows = clean.merge(first_ts, on="artist").query("timestamp == first_ts")
    first_city = (
        first_rows.groupby("artist", as_index=False)["city"]
        .first()
        .rename(columns={"city": "first_play_city"})
    )

    # Total plays and city count per artist
    totals = artist_city.groupby("artist", as_index=False).agg(
        total_plays=("plays", "sum"), cities_count=("city", "nunique")
    )

    result = (
        totals.merge(home[["artist", "home_city"]], on="artist", how="left")
        .merge(first_city, on="artist", how="left")
        .sort_values("total_plays", ascending=False)
        .reset_index(drop=True)
    )

    return result[["artist", "home_city", "first_play_city", "total_plays", "cities_count"]]


def build_artist_city_detail(df: DataFrame, artist: str) -> DataFrame:
    """Return per-city listening stats for a single artist.

    Args:
        df: Full listening history DataFrame.
        artist: Exact artist name to filter to.

    Returns:
        DataFrame with columns ``[city, plays, first_listen]`` (first_listen is
        a ``datetime.date``), sorted by ``first_listen`` descending (most recently
        discovered city first).  Empty DataFrame if required columns are missing
        or the artist is not found.
    """
    required = {"artist", "city", "timestamp"}
    if not required.issubset(df.columns):
        return DataFrame(columns=["city", "plays", "first_listen"])

    artist_df = df[df["artist"] == artist].dropna(subset=["city"])
    if artist_df.empty:
        return DataFrame(columns=["city", "plays", "first_listen"])

    agg = (
        artist_df.groupby("city")
        .agg(
            plays=("city", "size"),
            first_ts=("timestamp", "min"),
        )
        .reset_index()
    )
    agg["first_listen"] = pd.to_datetime(agg["first_ts"], unit="s", utc=True).dt.date
    return (
        agg[["city", "plays", "first_listen"]]
        .sort_values("first_listen", ascending=False)
        .reset_index(drop=True)
    )


def build_map_data(df: DataFrame, selected_artist: str) -> DataFrame:
    """Aggregate play counts per (artist, city, lat, lng) for scatter map dots.

    Args:
        df: Listening history DataFrame with ``artist``, ``city``, ``lat``,
            ``lng`` columns.
        selected_artist: Artist name to filter to, or ``"All"`` for no filter.

    Returns:
        DataFrame with columns ``[artist, city, lat, lng, plays]`` aggregated
        by location.  Rows with null lat/lng are excluded.
    """
    required = {"artist", "city", "lat", "lng"}
    if not required.issubset(df.columns):
        return DataFrame(columns=["artist", "city", "lat", "lng", "plays"])

    geo = df.dropna(subset=["lat", "lng", "artist", "city"])
    if geo.empty:
        return DataFrame(columns=["artist", "city", "lat", "lng", "plays"])

    if selected_artist != "All":
        geo = geo[geo["artist"] == selected_artist]

    agg = (
        geo.groupby(["artist", "city", "lat", "lng"], as_index=False)
        .size()
        .rename(columns={"size": "plays"})
    )
    return agg


# ---------------------------------------------------------------------------
# Streamlit render function
# ---------------------------------------------------------------------------


def render_artist_geography() -> None:
    """Render the Artist Geography page.

    Reads the active DataFrame from ``st.session_state['df']``.
    Shows an empty state when no data has been loaded or when geographic
    columns are absent.

    Two views are available via a tab selector:

    * **Map** — ``px.scatter_mapbox`` dots at cities, sized by play count and
      coloured per artist.
    * **Table** — top-50 artists with home city, first-play city, total plays,
      and city count.
    """
    df: DataFrame | None = st.session_state.get("df")

    st.header("Artist Geography")
    st.caption("Where you fell in love with each artist")

    if df is None or df.empty:
        st.info(
            "No music data loaded yet. "
            "Configure a Last.fm source in the sidebar and select a data file."
        )
        return

    has_geo = "lat" in df.columns and not df["lat"].isna().all()
    if not has_geo:
        st.warning(
            "No geographic data found. "
            "Provide a Swarm data directory in the sidebar to enable this view."
        )
        return

    # ── Artist selector ───────────────────────────────────────────────────────
    artists = ["All"] + sorted(df["artist"].dropna().unique().tolist())
    selected_artist = st.selectbox(
        "Filter by Artist",
        artists,
        key="ag_artist_select",
        help="Select an artist to highlight their listening locations, or show all.",
    )

    map_tab, table_tab = st.tabs(["Map", "Table"])

    # ── Map view ──────────────────────────────────────────────────────────────
    with map_tab:
        map_data = build_map_data(df, selected_artist)

        if map_data.empty:
            st.info("No geographic plays found for the selected artist.")
        else:
            # When all artists are shown, cap to the top N by plays to keep
            # Plotly responsive (one colour trace per artist scales poorly).
            map_display = map_data
            if selected_artist == "All":
                top_artists = (
                    map_data.groupby("artist")["plays"].sum().nlargest(_MAP_MAX_ARTISTS).index
                )
                map_display = map_data[map_data["artist"].isin(top_artists)]
                if len(map_display) < len(map_data):
                    st.caption(
                        f"Map shows your top {_MAP_MAX_ARTISTS} artists by plays. "
                        "Select a specific artist to see their full map."
                    )

            fig = px.scatter_map(
                map_display,
                lat="lat",
                lon="lng",
                color="artist",
                size="plays",
                size_max=40,
                hover_name="city",
                hover_data={"plays": True, "artist": True, "lat": False, "lng": False},
                color_discrete_sequence=COLORWAY,
                zoom=1,
                title=(
                    f"Listening locations — {selected_artist}"
                    if selected_artist != "All"
                    else f"Listening locations — top {_MAP_MAX_ARTISTS} artists"
                ),
            )
            fig.update_layout(
                map_style="carto-darkmatter",
                height=550,
                margin={"r": 0, "t": 40, "l": 0, "b": 0},
            )
            apply_dark_theme(fig)
            st.plotly_chart(fig, width="stretch")

            total_dots = len(map_display)
            total_plays = int(map_display["plays"].sum())
            top_city_row = map_display.loc[map_display["plays"].idxmax()]
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Locations", f"{total_dots:,}")
            with c2:
                st.metric("Total Plays (mapped)", f"{total_plays:,}")
            with c3:
                st.metric("Top City", str(top_city_row["city"]))

            # For a single artist, show the top 3 cities with first-listen dates.
            if selected_artist != "All":
                city_detail = build_artist_city_detail(df, selected_artist)
                top3 = city_detail.sort_values("plays", ascending=False).head(3)
                if not top3.empty:
                    st.markdown("**Top cities**")
                    cols = st.columns(min(len(top3), 3))
                    for col, (_, row) in zip(cols, top3.iterrows()):
                        with col:
                            st.markdown(f"**{row['city']}**")
                            st.markdown(f"{int(row['plays']):,} plays")
                            st.markdown(f"First heard: {row['first_listen']}")

    # ── Table view ────────────────────────────────────────────────────────────
    with table_tab:
        if selected_artist != "All":
            # Per-city breakdown for the selected artist, newest city first.
            city_detail = build_artist_city_detail(df, selected_artist)
            if city_detail.empty:
                st.info("No data available for the selected artist.")
            else:
                st.caption(
                    f"{selected_artist} — {len(city_detail):,} "
                    f"{'city' if len(city_detail) == 1 else 'cities'}, "
                    "sorted by first listen (newest first)"
                )
                st.dataframe(
                    city_detail[["city", "plays", "first_listen"]].rename(
                        columns={
                            "city": "City",
                            "plays": "Plays",
                            "first_listen": "First Listen",
                        }
                    ),
                    width="stretch",
                )
        else:
            # All-artists view: paginated artist summary table.
            _cache_key = id(df)
            if st.session_state.get("_ag_table_key") != _cache_key:
                st.session_state["_ag_table_cache"] = build_artist_city_table(df)
                st.session_state["_ag_table_key"] = _cache_key
            table_df = st.session_state["_ag_table_cache"]

            if table_df.empty:
                st.info("No data available.")
            else:
                sort_by = st.radio(
                    "Sort by",
                    ["Plays", "Alphabetical"],
                    horizontal=True,
                    key="ag_sort",
                )
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
                    key="ag_page",
                )
                start = (page - 1) * _TABLE_PAGE_SIZE
                end = start + _TABLE_PAGE_SIZE
                display = table_df.iloc[start:end].reset_index(drop=True)
                display.index = range(start + 1, start + 1 + len(display))

                st.caption(
                    f"Showing {start + 1}–{min(end, total_artists)} of {total_artists:,} artists"
                )
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
