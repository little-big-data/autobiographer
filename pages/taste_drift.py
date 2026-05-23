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
    """Render the Geographic Taste Drift analysis page.

    Loads taste drift data from cache.  If the cache is missing, shows a
    not-computed banner and stops rendering.  Otherwise, displays era
    comparisons, Jaccard similarity heatmap, defining artists, and a taste
    evolution chart.
    """
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

    tabs = st.tabs(["Era Comparison", "Taste Evolution"])

    # -----------------------------------------------------------------------
    # Tab 1 — Era Comparison
    # -----------------------------------------------------------------------
    with tabs[0]:
        st.subheader("Top Artists by Era")

        if not era_tops:
            st.info("No era data available. Run Calculate All Deep Analyses first.")
        else:
            # Side-by-side era columns
            era_list = list(era_tops.items())
            n_eras = len(era_list)
            cols = st.columns(min(n_eras, 3))
            for idx, (era_label, era_df) in enumerate(era_list):
                col = cols[idx % len(cols)]
                with col:
                    st.markdown(f"**{era_label}**")
                    if era_df.empty:
                        st.caption("No plays in this era.")
                    else:
                        display_df = era_df.head(10)
                        st.dataframe(display_df, width="stretch")

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

    # -----------------------------------------------------------------------
    # Tab 2 — Taste Evolution
    # -----------------------------------------------------------------------
    with tabs[1]:
        st.subheader("Taste Evolution Timeline")

        if timeline_df.empty:
            st.info("No timeline data available.")
        else:
            # Show rank-over-time for top artists
            top_artists = timeline_df.groupby("artist")["plays"].sum().nlargest(10).index.tolist()
            filtered = timeline_df[timeline_df["artist"].isin(top_artists)]
            if not filtered.empty:
                pivot = filtered.pivot_table(
                    index="month", columns="artist", values="rank", aggfunc="min"
                )
                st.line_chart(pivot, width="stretch")
            else:
                st.dataframe(timeline_df, width="stretch")
