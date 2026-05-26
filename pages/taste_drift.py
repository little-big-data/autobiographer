"""Geographic Taste Drift page — how your music taste changed across cities.

Displays pre-computed geographic taste drift results loaded from cache.
If the cache is absent, a banner guides the user to compute it first.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analysis_utils import load_deep_taste_drift_cache
from pages.data_sources import _deep_analysis_not_computed_banner


def render_taste_drift() -> None:
    """Render the Geographic Taste Drift analysis page."""
    st.title("Geographic Taste Drift")

    cache = load_deep_taste_drift_cache()
    if cache is None:
        _deep_analysis_not_computed_banner("Geographic Taste Drift")
        st.stop()
        return

    # -----------------------------------------------------------------------
    # Reconstruct data from cache
    # -----------------------------------------------------------------------
    era_tops_raw: dict[str, list[dict]] = cache.get("era_tops", {})
    jaccard_raw: dict = cache.get("jaccard", {})
    defining_artists: dict[str, list[str]] = cache.get("defining_artists", {})
    timeline_records: list[dict] = cache.get("timeline", [])

    era_tops = {era: pd.DataFrame(records) for era, records in era_tops_raw.items()}
    timeline_df = (
        pd.DataFrame(timeline_records)
        if timeline_records
        else pd.DataFrame(columns=["month", "artist", "rank", "plays"])
    )

    # Normalise month to YYYY-MM strings for clean axis labels
    if not timeline_df.empty and "month" in timeline_df.columns:
        timeline_df["month"] = pd.to_datetime(timeline_df["month"], errors="coerce").dt.strftime(
            "%Y-%m"
        )

    # -----------------------------------------------------------------------
    # Year filter
    # -----------------------------------------------------------------------
    available_years = (
        sorted(timeline_df["month"].str[:4].dropna().unique()) if not timeline_df.empty else []
    )
    year_options = ["All"] + available_years
    selected_year = st.selectbox("Year", year_options, key="taste_drift_year")

    if selected_year == "All":
        year_df = timeline_df
    else:
        year_df = timeline_df[timeline_df["month"].str.startswith(selected_year)]

    # -----------------------------------------------------------------------
    # Taste Evolution Timeline
    # -----------------------------------------------------------------------
    st.subheader("Taste Evolution Timeline")

    if timeline_df.empty:
        st.info("No timeline data available.")
    else:
        # Top artists scoped to the selected period
        top_artists = year_df.groupby("artist")["plays"].sum().nlargest(10).index.tolist()
        filtered = year_df[year_df["artist"].isin(top_artists)]
        if not filtered.empty:
            pivot = filtered.pivot_table(
                index="month", columns="artist", values="plays", aggfunc="sum"
            ).fillna(0)
            st.area_chart(pivot, width="stretch")
        else:
            st.info("No play data for the selected year.")

    # -----------------------------------------------------------------------
    # All-time vs Year top artists (shown when a specific year is selected)
    # -----------------------------------------------------------------------
    if selected_year != "All" and not timeline_df.empty:
        st.subheader(f"Top Artists — All Time vs {selected_year}")
        col_all, col_year = st.columns(2)

        with col_all:
            st.markdown("#### All Time")
            all_time_top = (
                timeline_df.groupby("artist")["plays"]
                .sum()
                .nlargest(20)
                .reset_index()
                .rename(columns={"plays": "total_plays"})
            )
            st.dataframe(all_time_top, width="stretch")

        with col_year:
            st.markdown(f"#### {selected_year}")
            year_top = (
                year_df.groupby("artist")["plays"]
                .sum()
                .nlargest(20)
                .reset_index()
                .rename(columns={"plays": "plays"})
            )
            st.dataframe(year_top, width="stretch")

    # -----------------------------------------------------------------------
    # Era Comparison (collapsible)
    # -----------------------------------------------------------------------
    with st.expander("Era Comparison", expanded=False):
        st.subheader("Top Artists by Era")

        if not era_tops:
            st.info("No era data available. Run Calculate All Deep Analyses first.")
        else:
            era_list = list(era_tops.items())
            n_eras = len(era_list)
            cols = st.columns(min(n_eras, 3))
            for idx, (era_label, era_df) in enumerate(era_list):
                with cols[idx % len(cols)]:
                    st.markdown(f"**{era_label}**")
                    if era_df.empty:
                        st.caption("No plays in this era.")
                    else:
                        st.dataframe(era_df.head(10), width="stretch")

        st.subheader("Artist Overlap (Jaccard Similarity)")
        if jaccard_raw:
            jaccard_df = pd.DataFrame(jaccard_raw)
            if not jaccard_df.empty:
                st.dataframe(jaccard_df, width="stretch")
            else:
                st.info("No Jaccard similarity data available.")
        else:
            st.info("No similarity data available.")

        st.subheader("Era-Defining Artists")
        if defining_artists:
            for era_label, artists in defining_artists.items():
                if artists:
                    st.markdown(f"**{era_label}**: {', '.join(artists[:20])}")
                else:
                    st.markdown(f"**{era_label}**: *(no defining artists)*")
        else:
            st.info("No defining artists data available.")
