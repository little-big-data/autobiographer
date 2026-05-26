"""Deep Music Analysis page — Listening Session Analysis.

Displays pre-computed session analysis results loaded from cache.
If the cache is absent, a banner guides the user to compute it first.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import analysis_utils
from analysis_utils import (
    get_session_opening_tracks,
    get_session_time_distribution,
    load_deep_sessions_cache,
)
from pages.data_sources import _deep_analysis_not_computed_banner


def render_deep_music() -> None:
    """Render the Deep Music Analysis page.

    Loads session stats from cache.  If the cache is missing, shows a
    not-computed banner and stops rendering.  Otherwise, displays tabs for
    Sessions, Personality, and Temporal analysis.
    """
    st.title("Deep Music Analysis")

    cache = load_deep_sessions_cache()
    if cache is None:
        _deep_analysis_not_computed_banner("Session Analysis")
        st.stop()
        return

    # Reconstruct session_stats DataFrame from cache dict
    session_stats_records = cache.get("session_stats", [])
    session_stats = pd.DataFrame(session_stats_records)

    tabs = st.tabs(["Sessions", "Personality", "Artist Arcs", "Temporal"])

    # ------------------------------------------------------------------
    # Sessions tab
    # ------------------------------------------------------------------
    with tabs[0]:
        st.subheader("Listening Sessions")

        if session_stats.empty:
            st.info("No session data available.")
        else:
            # Session length histogram
            st.markdown("#### Session Length Distribution")
            if "track_count" in session_stats.columns:
                counts = session_stats["track_count"]
                counts = counts[counts >= 2]
                st.bar_chart(counts.value_counts().sort_index())

            # Time-of-day bar chart
            st.markdown("#### Sessions by Hour of Day")
            if "hour_of_day" in session_stats.columns:
                dist = get_session_time_distribution(session_stats)
                if not dist.empty:
                    chart_df = dist.set_index("hour")
                    st.bar_chart(chart_df["session_count"])

            # Opening tracks leaderboard
            st.markdown("#### Top Session Openers")
            opening_tracks = get_session_opening_tracks(session_stats, top_n=10)
            if not opening_tracks.empty:
                st.dataframe(opening_tracks, width="stretch")

    # ------------------------------------------------------------------
    # Personality tab
    # ------------------------------------------------------------------
    with tabs[1]:
        personality_cache = analysis_utils.load_deep_personality_cache()
        if personality_cache is None:
            _deep_analysis_not_computed_banner("Music Personality Metrics")
        else:
            st.subheader("Music Personality Metrics")

            gini = personality_cache.get("gini", 0.0)
            loyalty = personality_cache.get("loyalty_score", 0.0)
            st.metric("Gini Coefficient", f"{gini:.3f}", help="0 = equal, 1 = concentrated")
            st.metric(
                "Loyalty Score", f"{loyalty:.2%}", help="Fraction of old artists still played"
            )

            # Build year filter from available month data
            comfort_records = personality_cache.get("comfort_ratio", [])
            monthly_records = personality_cache.get("monthly_new_artists", [])
            all_months: list[str] = [r["month"] for r in comfort_records if "month" in r] + [
                r["month"] for r in monthly_records if "month" in r
            ]
            available_years = sorted(
                {m[:4] for m in all_months if isinstance(m, str) and len(m) >= 4}
            )
            year_options = ["All"] + available_years
            selected_year = st.selectbox("Year", year_options, key="personality_year")

            def _filter_by_year(df: pd.DataFrame, year: str) -> pd.DataFrame:
                if year == "All" or "month" not in df.columns:
                    return df
                return df[df["month"].astype(str).str.startswith(year)]

            def _month_label(df: pd.DataFrame) -> pd.DataFrame:
                """Replace the month column with a YYYY-MM string for clean axis labels."""
                df = df.copy()
                df["month"] = pd.to_datetime(df["month"], utc=True, errors="coerce").dt.strftime(
                    "%Y-%m"
                )
                return df

            if comfort_records:
                comfort_df = pd.DataFrame(comfort_records)
                st.markdown("#### Familiar vs New Plays by Month")
                if "month" in comfort_df.columns:
                    view = _month_label(_filter_by_year(comfort_df, selected_year))
                    chart_df = view.set_index("month")[["familiar_plays", "new_plays"]]
                    st.bar_chart(chart_df, width="stretch")

            if monthly_records:
                monthly_df = pd.DataFrame(monthly_records)
                st.markdown("#### New Artists Discovered per Month")
                if "month" in monthly_df.columns:
                    view = _month_label(_filter_by_year(monthly_df, selected_year))
                    st.bar_chart(view.set_index("month")["new_artists"], width="stretch")

            # Album tables split by familiarity
            familiarity_records = personality_cache.get("album_familiarity", [])
            if familiarity_records:
                fam_df = pd.DataFrame(familiarity_records)
                fam_view = _filter_by_year(fam_df, selected_year)

                familiar_albums = (
                    fam_view[fam_view["play_type"] == "familiar"]
                    .groupby(["artist", "album"], sort=False)["plays"]
                    .sum()
                    .reset_index()
                    .sort_values("plays", ascending=False)
                    .head(15)
                    .reset_index(drop=True)
                )
                new_albums = (
                    fam_view[fam_view["play_type"] == "new"]
                    .groupby(["artist", "album"], sort=False)["plays"]
                    .sum()
                    .reset_index()
                    .sort_values("plays", ascending=False)
                    .head(15)
                    .reset_index(drop=True)
                )

                col_fam, col_new = st.columns(2)
                with col_fam:
                    st.markdown("#### Top Familiar Album Listens")
                    if not familiar_albums.empty:
                        st.dataframe(familiar_albums, width="stretch")
                    else:
                        st.info("No familiar album data for this period.")
                with col_new:
                    st.markdown("#### New Artist Album Listens")
                    if not new_albums.empty:
                        st.dataframe(new_albums, width="stretch")
                    else:
                        st.info("No new artist album data for this period.")

            album_records = personality_cache.get("album_depth", [])
            if album_records:
                album_df = pd.DataFrame(album_records)
                st.markdown("#### Deep Album Listens")
                st.dataframe(album_df, width="stretch")

    # ------------------------------------------------------------------
    # Artist Arcs tab
    # ------------------------------------------------------------------
    with tabs[2]:
        arcs_cache = analysis_utils.load_deep_arcs_cache()
        if arcs_cache is None:
            _deep_analysis_not_computed_banner("Artist Arcs")
        else:
            st.subheader("Artist Lifecycle & Obsession Arcs")

            arcs_records = arcs_cache.get("arcs", [])
            arcs_df = pd.DataFrame(arcs_records)

            if arcs_df.empty:
                st.info("No artist arc data available.")
            else:
                # Arc type distribution bar chart
                st.markdown("#### Arc Type Distribution")
                arc_counts = arcs_df["arc_type"].value_counts()
                st.bar_chart(arc_counts, width="stretch")

                # Obsessions leaderboard
                st.markdown("#### Top Obsessions")
                obsessions = arcs_df[arcs_df["arc_type"] == "obsession"].sort_values(
                    "peak_ratio", ascending=False
                )
                if not obsessions.empty:
                    st.dataframe(
                        obsessions[
                            ["artist", "peak_plays", "peak_ratio", "discovery_date", "last_play"]
                        ],
                        width="stretch",
                    )
                else:
                    st.info("No obsession arcs found.")

                # Artist lifecycle selector
                st.markdown("#### Artist Monthly Plays")
                artist_options = arcs_df["artist"].tolist()
                selected_artist = st.selectbox("Select artist", artist_options)
                if selected_artist and "peak_month" in arcs_df.columns:
                    artist_row = arcs_df[arcs_df["artist"] == selected_artist]
                    if not artist_row.empty:
                        st.metric(
                            "Total Plays",
                            str(artist_row.iloc[0]["total_plays"]),
                        )

    # ------------------------------------------------------------------
    # Temporal tab
    # ------------------------------------------------------------------
    with tabs[3]:
        seasonal_cache = analysis_utils.load_deep_seasonal_cache()
        if seasonal_cache is None:
            _deep_analysis_not_computed_banner("Temporal Fingerprint")
        else:
            st.subheader("Temporal Fingerprint")

            seasonal_records = seasonal_cache.get("seasonal_affinity", [])
            if seasonal_records:
                seasonal_df = pd.DataFrame(seasonal_records)
                st.markdown("#### Seasonal Artist Affinity")
                if "season" in seasonal_df.columns and "artist" in seasonal_df.columns:
                    pivot = seasonal_df.pivot_table(
                        index="artist",
                        columns="season",
                        values="affinity_score",
                        fill_value=0.0,
                    )
                    st.dataframe(pivot, width="stretch")

            morning_records = seasonal_cache.get("morning_artists", [])
            night_records = seasonal_cache.get("night_artists", [])
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Morning Artists")
                if morning_records:
                    st.dataframe(pd.DataFrame(morning_records), width="stretch")
                else:
                    st.info("No morning listening data.")
            with col2:
                st.markdown("#### Night Artists")
                if night_records:
                    st.dataframe(pd.DataFrame(night_records), width="stretch")
                else:
                    st.info("No night listening data.")

            dow_records = seasonal_cache.get("day_of_week", [])
            if dow_records:
                st.markdown("#### Day-of-Week Personality")
                st.dataframe(pd.DataFrame(dow_records), width="stretch")

            holiday_records = seasonal_cache.get("holiday_identity", [])
            if holiday_records:
                st.markdown("#### Holiday Musical Identity")
                st.dataframe(pd.DataFrame(holiday_records), width="stretch")
