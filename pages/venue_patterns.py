"""Venue Patterns page — loyalty leaderboard, routine venues, exploration rate.

Displays pre-computed venue pattern results loaded from cache.
If the cache is absent, a banner guides the user to compute it first.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import analysis_utils
from pages.data_sources import _deep_analysis_not_computed_banner


def render_venue_patterns() -> None:
    """Render the Venue Patterns analysis page.

    Loads venue pattern data from cache.  If the cache is missing, shows a
    not-computed banner and stops rendering.  Otherwise, displays:
    - Loyalty leaderboard bar chart
    - Routine venues table
    - Exploration rate line chart
    - Music around venue type section
    """
    st.title("Venue Patterns")

    cache = analysis_utils.load_deep_venue_patterns_cache()
    if cache is None:
        _deep_analysis_not_computed_banner("Venue Patterns")
        st.stop()
        return

    # -----------------------------------------------------------------------
    # Reconstruct DataFrames from cache records
    # -----------------------------------------------------------------------
    loyalty_records = cache.get("loyalty", [])
    loyalty_df = (
        pd.DataFrame(loyalty_records)
        if loyalty_records
        else pd.DataFrame(columns=["venue", "venue_category", "visit_count", "loyalty_score"])
    )

    routine_records = cache.get("routine", [])
    routine_df = (
        pd.DataFrame(routine_records)
        if routine_records
        else pd.DataFrame(
            columns=["venue", "venue_category", "dominant_day", "day_fraction", "visit_count"]
        )
    )

    exploration_records = cache.get("exploration", [])
    exploration_df = (
        pd.DataFrame(exploration_records)
        if exploration_records
        else pd.DataFrame(columns=["month", "new_venues", "revisits", "exploration_ratio"])
    )
    if not exploration_df.empty and "month" in exploration_df.columns:
        exploration_df["month"] = pd.to_datetime(exploration_df["month"])

    music_around_cafes_records = cache.get("music_around_cafes", [])
    music_around_cafes = (
        pd.DataFrame(music_around_cafes_records)
        if music_around_cafes_records
        else pd.DataFrame(columns=["artist", "plays"])
    )

    tabs = st.tabs(["Loyalty", "Routines", "Exploration", "Music & Venues"])

    # -----------------------------------------------------------------------
    # Tab 1 — Loyalty leaderboard
    # -----------------------------------------------------------------------
    with tabs[0]:
        st.subheader("Venue Loyalty Leaderboard")
        if loyalty_df.empty:
            st.info("No loyalty data available. Run Calculate All Deep Analyses first.")
        else:
            st.bar_chart(
                loyalty_df.set_index("venue")["visit_count"],
                width="stretch",
            )
            st.dataframe(loyalty_df, width="stretch")

    # -----------------------------------------------------------------------
    # Tab 2 — Routine venues
    # -----------------------------------------------------------------------
    with tabs[1]:
        st.subheader("Routine Venues")
        if routine_df.empty:
            st.info("No routine venue data available. Run Calculate All Deep Analyses first.")
        else:
            st.dataframe(routine_df, width="stretch")

    # -----------------------------------------------------------------------
    # Tab 3 — Exploration rate
    # -----------------------------------------------------------------------
    with tabs[2]:
        st.subheader("Venue Exploration Rate")
        if exploration_df.empty:
            st.info("No exploration data available. Run Calculate All Deep Analyses first.")
        else:
            st.line_chart(
                exploration_df.set_index("month")["exploration_ratio"],
                width="stretch",
            )
            st.dataframe(exploration_df, width="stretch")

    # -----------------------------------------------------------------------
    # Tab 4 — Music around venue type
    # -----------------------------------------------------------------------
    with tabs[3]:
        st.subheader("Music Around Cafes & Coffee Shops")
        if music_around_cafes.empty:
            st.info("No music-around-venue data available. Run Calculate All Deep Analyses first.")
        else:
            st.dataframe(music_around_cafes, width="stretch")
