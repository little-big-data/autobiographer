"""Discovery Zones page — where you first heard new artists.

Visualises the geographic context of musical discovery:

- **Discovery map** — city dots sized by total plays for artists first heard
  there, coloured by the year of discovery.
- **Discovery rate timeline** — new-artist discoveries per month/year.
- **Top discovery cities** — ranked by play-weighted impact.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analysis_utils import get_first_plays
from components.theme import (
    ACCENT_INDIGO,
    LIFTED_BG,
    apply_dark_theme,
)


def _discovery_map(city_stats: pd.DataFrame) -> None:
    """Render an interactive scatter map of discovery cities.

    Dots are sized by total-plays weight for artists first heard in that city
    and coloured by the year of discovery.

    Args:
        city_stats: DataFrame with columns ``city``, ``lat``, ``lng``,
            ``discovery_year``, ``artist_count``, ``total_plays``.
    """
    if city_stats.empty:
        st.info("No geographic data available for the discovery map.")
        return

    fig = px.scatter_geo(
        city_stats,
        lat="lat",
        lon="lng",
        size="total_plays",
        color="discovery_year",
        hover_name="city",
        hover_data={
            "artist_count": True,
            "total_plays": True,
            "lat": False,
            "lng": False,
        },
        size_max=40,
        color_continuous_scale=[
            [0.0, "#1e1b4b"],
            [0.5, ACCENT_INDIGO],
            [1.0, "#22d3ee"],
        ],
        title="Discovery Map — Cities Where You Found New Music",
        labels={
            "discovery_year": "Year",
            "artist_count": "Artists Discovered",
            "total_plays": "Play-Weighted Impact",
        },
        projection="natural earth",
    )
    fig.update_layout(
        geo=dict(
            bgcolor="rgba(0,0,0,0)",
            lakecolor="rgba(0,0,0,0)",
            landcolor="#141c2f",
            showland=True,
            showcountries=True,
            countrycolor="#2d3a52",
            showocean=True,
            oceancolor="#090e1a",
        ),
        coloraxis_colorbar=dict(title="Year"),
        margin={"r": 0, "t": 50, "l": 0, "b": 0},
    )
    apply_dark_theme(fig)
    st.plotly_chart(fig, width="stretch")


def _discovery_rate_chart(first_plays: pd.DataFrame, freq: str) -> None:
    """Render a bar chart of new-artist discoveries over time.

    Args:
        first_plays: First-play DataFrame with a ``date_text`` column.
        freq: Frequency string — ``"ME"`` for monthly, ``"YE"`` for yearly.
    """
    if first_plays.empty or "date_text" not in first_plays.columns:
        return

    period_freq = "M" if freq == "ME" else "Y"
    rate = (
        first_plays.assign(
            period=first_plays["date_text"].dt.to_period(period_freq).dt.to_timestamp()
        )
        .groupby("period")
        .size()
        .reset_index(name="New Artists")
        .rename(columns={"period": "date"})
    )

    label = "Month" if freq == "ME" else "Year"
    fig = px.bar(
        rate,
        x="date",
        y="New Artists",
        title=f"New Artist Discoveries per {label}",
        labels={"date": label, "New Artists": "Artists Discovered"},
    )
    fig.update_traces(marker_color=ACCENT_INDIGO)
    apply_dark_theme(fig)
    st.plotly_chart(fig, width="stretch")


def _top_discovery_cities_chart(city_stats: pd.DataFrame, limit: int) -> None:
    """Render a horizontal bar chart of top discovery cities by impact.

    Args:
        city_stats: DataFrame with columns ``city``, ``artist_count``,
            ``total_plays``, sorted descending by ``total_plays``.
        limit: Number of cities to show.
    """
    if city_stats.empty:
        st.info("No city data available.")
        return

    top = city_stats.head(limit).copy()
    top["label"] = top.apply(lambda r: f"{r['city']} ({int(r['artist_count'])} artists)", axis=1)

    colors = [ACCENT_INDIGO] + [LIFTED_BG] * (len(top) - 1)

    fig = go.Figure(
        go.Bar(
            x=top["total_plays"].tolist(),
            y=top["label"].tolist(),
            orientation="h",
            marker_color=colors,
            text=[f"{int(v):,}" for v in top["total_plays"]],
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.update_layout(
        title=f"Top {limit} Discovery Cities by Play-Weighted Impact",
        yaxis={"categoryorder": "total ascending"},
        xaxis_title="Total Plays (artists first heard here)",
        margin={"r": 80},
    )
    apply_dark_theme(fig)
    st.plotly_chart(fig, width="stretch")


def render_discovery_zones() -> None:
    """Render the Discovery Zones page.

    Shows where the user first heard each artist, visualised as a geographic
    map, a discovery-rate timeline, and a ranked city leaderboard.

    Reads ``st.session_state['df']``.  Shows an empty state when no data has
    been loaded, and degrades gracefully when no geographic data is present.
    """
    df: pd.DataFrame | None = st.session_state.get("df")
    if df is None or df.empty:
        st.info(
            "No music data loaded yet. "
            "Configure a Last.fm source in the sidebar and select a data file."
        )
        return

    st.header("Discovery Zones")
    st.caption("Where did you first hear new artists?")

    # ── Compute first plays ────────────────────────────────────────────────────
    first_plays = get_first_plays(df)
    if first_plays.empty:
        st.warning("Not enough data to compute discoveries.")
        return

    # Add a discovery-year column for colour encoding
    if "date_text" in first_plays.columns:
        first_plays = first_plays.copy()
        first_plays["discovery_year"] = first_plays["date_text"].dt.year
    else:
        first_plays["discovery_year"] = 0

    # ── Controls ───────────────────────────────────────────────────────────────
    ctrl_col1, ctrl_col2 = st.columns(2)
    with ctrl_col1:
        freq_label = st.selectbox("Discovery rate grouping", ["Monthly", "Yearly"])
    freq = "ME" if freq_label == "Monthly" else "YE"

    with ctrl_col2:
        limit = st.slider("Top cities to show", 5, 30, 15)

    st.divider()

    # ── Discovery rate timeline ────────────────────────────────────────────────
    st.subheader("Discovery Rate Over Time")
    _discovery_rate_chart(first_plays, freq)

    st.divider()

    # ── Geographic section — only when lat/lng are present ────────────────────
    has_geo = "lat" in first_plays.columns and first_plays["lat"].notna().any()

    if has_geo:
        # Total plays per artist across the full dataset
        artist_total_plays: pd.Series = df["artist"].value_counts()

        # Join total plays onto first_plays and aggregate to city level
        fp_with_plays = first_plays.copy()
        fp_with_plays["total_plays"] = (
            fp_with_plays["artist"].map(artist_total_plays).fillna(0).astype(int)
        )

        # Group by city only (not lat/lng) to avoid GPS-drift fragmentation from
        # Swarm check-ins producing slightly different coordinates each visit.
        # Median lat/lng gives a stable representative point per city.
        city_stats = (
            fp_with_plays.dropna(subset=["lat", "lng"])
            .groupby("city")
            .agg(
                lat=("lat", "median"),
                lng=("lng", "median"),
                artist_count=("artist", "count"),
                total_plays=("total_plays", "sum"),
                discovery_year=("discovery_year", "min"),
            )
            .reset_index()
            .sort_values("total_plays", ascending=False)
        )

        # ── Map ────────────────────────────────────────────────────────────────
        st.subheader("Discovery Map")
        _discovery_map(city_stats)

        st.divider()

        # ── Top cities leaderboard ─────────────────────────────────────────────
        st.subheader("Top Discovery Cities")
        col_chart, col_table = st.columns([2, 1])
        with col_chart:
            _top_discovery_cities_chart(city_stats, limit)
        with col_table:
            display_cols = ["city", "artist_count", "total_plays"]
            st.dataframe(
                city_stats[display_cols]
                .head(limit)
                .rename(
                    columns={
                        "city": "City",
                        "artist_count": "Artists",
                        "total_plays": "Play Impact",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
    else:
        st.info(
            "No geographic data found for the discovery map. "
            "Provide a Swarm export directory to see where you discovered new artists."
        )

    st.divider()

    # ── Per-artist discovery table with city & year filters ────────────────────
    st.subheader("Artist Discoveries")

    # Append total plays before filtering so sorting is consistent
    artist_total: pd.Series = df["artist"].value_counts()
    display_first = first_plays.copy()
    display_first["total_plays"] = display_first["artist"].map(artist_total).fillna(0).astype(int)

    # Build filter options
    filter_col1, filter_col2 = st.columns(2)

    city_options: list[str] = ["All cities"]
    if "city" in display_first.columns:
        city_options += sorted(display_first["city"].dropna().unique().tolist())
    selected_city: str = filter_col1.selectbox("Filter by city", city_options, key="dz_city")

    year_options: list[str] = ["All years"]
    if "discovery_year" in display_first.columns:
        year_options += [
            str(y)
            for y in sorted(display_first["discovery_year"].dropna().unique().astype(int).tolist())
        ]
    selected_year: str = filter_col2.selectbox("Filter by year", year_options, key="dz_year")

    # Apply filters
    filtered = display_first.copy()
    if selected_city != "All cities" and "city" in filtered.columns:
        filtered = filtered[filtered["city"] == selected_city]
    if selected_year != "All years" and "discovery_year" in filtered.columns:
        filtered = filtered[filtered["discovery_year"] == int(selected_year)]

    show_cols = [
        c for c in ["artist", "date_text", "city", "country", "track"] if c in filtered.columns
    ]
    if "date_text" in show_cols:
        filtered = filtered.copy()
        filtered["date_text"] = filtered["date_text"].dt.strftime("%Y-%m-%d")

    rename_map = {
        "artist": "Artist",
        "date_text": "First Heard",
        "city": "City",
        "country": "Country",
        "track": "Track",
        "total_plays": "Total Plays",
    }
    st.caption(f"{len(filtered):,} artists")
    st.dataframe(
        filtered[show_cols + ["total_plays"]]
        .rename(columns=rename_map)
        .sort_values("Total Plays", ascending=False),
        hide_index=True,
    )
