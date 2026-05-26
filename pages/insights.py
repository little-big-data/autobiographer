"""Insights page — patterns, narrative, and granular filtering."""

from __future__ import annotations

from datetime import datetime, timezone

import plotly.express as px
import streamlit as st
from pandas import DataFrame

from analysis_utils import (
    get_day_hour_heatmap,
    get_forgotten_favorites,
    get_hourly_distribution,
    get_listening_streaks,
    get_milestones,
    get_top_entities,
    get_unique_entities,
)
from components.share import render_share_button
from components.theme import COLORWAY, SEQUENTIAL_SCALE, apply_dark_theme
from export_html import build_insights_page_html


def render_insights_and_narrative(df: DataFrame) -> None:
    """Render patterns, narrative, and granular filter views.

    Args:
        df: Loaded listening history DataFrame.
    """
    st.header("Insights & Narrative")

    st.subheader("Explore Patterns by Time & Location")

    years = ["All"] + sorted(df["date_text"].dt.year.unique().astype(str).tolist(), reverse=True)
    months = ["All"] + list(range(1, 13))
    countries = ["All"] + sorted(df["country"].dropna().unique().tolist())
    states = ["All"] + sorted(df["state"].dropna().unique().tolist())

    col_filter1, col_filter2, col_filter3, col_filter4 = st.columns(4)
    with col_filter1:
        selected_year = st.selectbox("Year", years)
    with col_filter2:
        selected_month = st.selectbox("Month", months)
    with col_filter3:
        selected_country = st.selectbox("Country", countries)
    with col_filter4:
        selected_state = st.selectbox("State", states)

    filtered_df = df.copy()
    if selected_year != "All":
        filtered_df = filtered_df[filtered_df["date_text"].dt.year == int(selected_year)]
    if selected_month != "All":
        filtered_df = filtered_df[filtered_df["date_text"].dt.month == int(selected_month)]
    if selected_country != "All":
        filtered_df = filtered_df[filtered_df["country"] == selected_country]
    if selected_state != "All":
        filtered_df = filtered_df[filtered_df["state"] == selected_state]

    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html_bytes = build_insights_page_html(filtered_df, generated_at).encode("utf-8")
    render_share_button(html_bytes, "autobiographer-insights.html")

    if filtered_df.empty:
        st.warning("No data found for the selected granular filters.")
    else:
        if "album" in filtered_df.columns:
            top_artists = get_top_entities(filtered_df, "artist", limit=12)["artist"].tolist()
            subset = filtered_df[filtered_df["artist"].isin(top_artists)].copy()
            grouped = subset.groupby(["artist", "album"]).size().reset_index(name="scrobbles")
            fig_sun = px.sunburst(
                grouped,
                path=["artist", "album"],
                values="scrobbles",
                title="Music Listening Hierarchy",
                color_discrete_sequence=COLORWAY,
            )
            fig_sun.update_traces(textinfo="label+percent parent")
            apply_dark_theme(fig_sun)
            st.plotly_chart(fig_sun, width="stretch")

        st.markdown("---")
        col_top1, col_top2 = st.columns(2)

        with col_top1:
            st.markdown("### Top Artists & Tracks")
            tabs_top = st.tabs(["Artists", "Tracks", "Albums"])
            with tabs_top[0]:
                st.dataframe(
                    get_top_entities(filtered_df, "artist"), hide_index=True, width="stretch"
                )
            with tabs_top[1]:
                st.dataframe(
                    get_top_entities(filtered_df, "track"), hide_index=True, width="stretch"
                )
            with tabs_top[2]:
                st.dataframe(
                    get_top_entities(filtered_df, "album"), hide_index=True, width="stretch"
                )

        with col_top2:
            st.markdown("### Most Unique to this Selection")
            st.caption(
                "Entities that are more characteristic of this filter "
                "compared to your overall history."
            )
            tabs_unique = st.tabs(["Artists", "Tracks"])
            with tabs_unique[0]:
                unique_artists = get_unique_entities(filtered_df, df, "artist")
                if not unique_artists.empty:
                    st.dataframe(unique_artists, hide_index=True, width="stretch")
                else:
                    st.info("Not enough data for uniqueness score.")
            with tabs_unique[1]:
                unique_tracks = get_unique_entities(filtered_df, df, "track")
                if not unique_tracks.empty:
                    st.dataframe(unique_tracks, hide_index=True, width="stretch")
                else:
                    st.info("Not enough data for uniqueness score.")

        st.markdown("---")
        st.subheader("Time-based Patterns")
        col_pat1, col_pat2 = st.columns(2)
        with col_pat1:
            hourly = get_hourly_distribution(filtered_df)
            fig_hourly = px.bar(hourly, x="hour", y="Plays", title="Listening by Hour of Day")
            apply_dark_theme(fig_hourly)
            st.plotly_chart(fig_hourly, width="stretch")
        with col_pat2:
            heatmap_pivot = get_day_hour_heatmap(filtered_df)
            fig_heatmap = px.imshow(
                heatmap_pivot,
                labels=dict(x="Hour of Day", y="Day of Week", color="Plays"),
                title="Listening Intensity (Day vs Hour)",
                aspect="auto",
                color_continuous_scale=SEQUENTIAL_SCALE,
            )
            apply_dark_theme(fig_heatmap)
            st.plotly_chart(fig_heatmap, width="stretch")

    st.markdown("---")
    st.subheader("Autobiographical Narrative")
    col_nar1, col_nar2 = st.columns(2)
    with col_nar1:
        st.markdown("#### Milestones")
        milestones = get_milestones(filtered_df)
        if not milestones.empty:
            st.dataframe(milestones, hide_index=True, width="stretch")
        else:
            st.info("No major milestones in this selection.")
    with col_nar2:
        st.markdown("#### Listening Streaks")
        streaks = get_listening_streaks(filtered_df)
        st.metric("Longest Streak", f"{streaks['longest_streak']} days")
        st.metric("Current Streak", f"{streaks['current_streak']} days")

    st.markdown("#### Forgotten Favorites")
    st.write("Artists you loved overall but haven't heard in this period (or recently):")
    forgotten = get_forgotten_favorites(filtered_df) if not filtered_df.empty else DataFrame()
    if not forgotten.empty:
        st.dataframe(forgotten, hide_index=True)
    else:
        st.info("No forgotten favorites identified.")


def render_insights() -> None:
    """Render the Insights page.

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

    with st.spinner("Loading insights..."):
        render_insights_and_narrative(df)
