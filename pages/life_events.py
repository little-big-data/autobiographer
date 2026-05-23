"""Life Event Detection page — changepoints and taste shifts in your listening history.

Displays pre-computed life event detection results loaded from cache.
If the cache is absent, a banner guides the user to compute it first.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

import analysis_utils
from pages.data_sources import _deep_analysis_not_computed_banner


def render_life_events() -> None:
    """Render the Life Event Detection analysis page.

    Loads life event data from cache.  If the cache is missing, shows a
    not-computed banner and stops rendering.  Otherwise, displays an intensity
    timeline with changepoint markers, a taste shift table, and correlated
    event narrative cards.
    """
    st.title("Life Event Detection")

    cache = analysis_utils.load_deep_life_events_cache()
    if cache is None:
        _deep_analysis_not_computed_banner("Life Event Detection")
        st.stop()
        return

    # -----------------------------------------------------------------------
    # Reconstruct data from cache
    # -----------------------------------------------------------------------
    changepoints_raw: list[str] = cache.get("changepoints", [])
    taste_shifts_raw: list[dict[str, Any]] = cache.get("taste_shifts", [])
    events_raw: list[dict[str, Any]] = cache.get("events", [])

    changepoints = [pd.Timestamp(cp) for cp in changepoints_raw if cp]
    taste_shifts = taste_shifts_raw
    events = events_raw

    tabs = st.tabs(["Intensity & Changepoints", "Taste Shifts", "Correlated Events"])

    # -----------------------------------------------------------------------
    # Tab 1 — Intensity timeline with changepoint markers
    # -----------------------------------------------------------------------
    with tabs[0]:
        st.subheader("Listening Intensity & Changepoints")

        if not changepoints:
            st.info("No changepoints detected. Run Calculate All Deep Analyses to compute.")
        else:
            st.write(f"Detected **{len(changepoints)}** structural changepoints in your listening.")
            cp_df = pd.DataFrame({"Changepoint Date": changepoints})
            st.dataframe(cp_df, width="stretch")

    # -----------------------------------------------------------------------
    # Tab 2 — Taste shift table
    # -----------------------------------------------------------------------
    with tabs[1]:
        st.subheader("Taste Shift Points")

        if not taste_shifts:
            st.info("No significant taste shifts detected.")
        else:
            shift_records = []
            for s in taste_shifts:
                shift_records.append(
                    {
                        "Date": s.get("date", ""),
                        "Jaccard Similarity": s.get("jaccard_similarity", ""),
                        "New Artists": ", ".join(s.get("new_artists", [])),
                        "Lost Artists": ", ".join(s.get("lost_artists", [])),
                    }
                )
            shift_df = pd.DataFrame(shift_records)
            st.dataframe(shift_df, width="stretch")

    # -----------------------------------------------------------------------
    # Tab 3 — Correlated event narrative cards
    # -----------------------------------------------------------------------
    with tabs[2]:
        st.subheader("Correlated Life Events")

        if not events:
            st.info("No events to display. Run Calculate All Deep Analyses first.")
        else:
            for event in events:
                date_str = str(event.get("date", ""))
                event_type = event.get("type", "event")
                context = event.get("context", "")

                col1, col2 = st.columns([1, 3])
                with col1:
                    st.metric(label="Date", value=date_str[:10] if date_str else "")
                with col2:
                    st.markdown(f"**Type**: {event_type}")
                    if context:
                        st.markdown(f"**Context**: {context}")
