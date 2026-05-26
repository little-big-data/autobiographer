"""City Soundtracks page — top artists and tracks around each city visit.

Displays pre-computed city soundtrack results loaded from cache.
If the cache is absent, a banner guides the user to compute it first.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from analysis_utils import get_city_artist_affinity_matrix, load_deep_city_soundtracks_cache
from pages.data_sources import _deep_analysis_not_computed_banner


def render_city_soundtracks() -> None:
    """Render the City Soundtracks analysis page.

    Loads city soundtrack data from cache.  If the cache is missing, shows a
    not-computed banner and stops rendering.  Otherwise, displays per-city
    soundtrack cards and an artist-by-city affinity matrix.
    """
    st.title("City Soundtracks")

    cache = load_deep_city_soundtracks_cache()
    if cache is None:
        _deep_analysis_not_computed_banner("City Soundtracks")
        st.stop()
        return

    # -----------------------------------------------------------------------
    # Reconstruct data from cache
    # -----------------------------------------------------------------------
    soundtrack_records: list[dict] = cache.get("soundtracks", [])

    # Rebuild DataFrame fields from records
    soundtracks: list[dict] = []
    for s in soundtrack_records:
        top_artists = (
            pd.DataFrame(s["top_artists"])
            if s.get("top_artists")
            else pd.DataFrame(columns=["artist", "plays"])
        )
        top_tracks = (
            pd.DataFrame(s["top_tracks"])
            if s.get("top_tracks")
            else pd.DataFrame(columns=["track", "artist", "plays"])
        )
        soundtracks.append(
            {
                "city": s["city"],
                "top_artists": top_artists,
                "top_tracks": top_tracks,
                "play_count": s.get("play_count", 0),
            }
        )

    tabs = st.tabs(["City Soundtracks", "Artist Affinity Matrix"])

    # -----------------------------------------------------------------------
    # Tab 1 — Per-city soundtrack cards
    # -----------------------------------------------------------------------
    with tabs[0]:
        if not soundtracks:
            st.info("No city soundtracks available. Run Calculate All Deep Analyses first.")
        else:
            for soundtrack in soundtracks:
                city = soundtrack["city"]
                play_count = soundtrack["play_count"]
                top_artists = soundtrack["top_artists"]
                top_tracks = soundtrack["top_tracks"]

                with st.expander(f"{city} — {play_count:,} plays", expanded=False):
                    cols = st.columns(2)
                    with cols[0]:
                        st.subheader("Top Artists")
                        if not top_artists.empty:
                            st.dataframe(top_artists, width="stretch")
                        else:
                            st.info("No artist data.")
                    with cols[1]:
                        st.subheader("Top Tracks")
                        if not top_tracks.empty:
                            st.dataframe(top_tracks, width="stretch")
                        else:
                            st.info("No track data.")

    # -----------------------------------------------------------------------
    # Tab 2 — Artist × city affinity matrix
    # -----------------------------------------------------------------------
    with tabs[1]:
        st.subheader("Artist × City Affinity Matrix")
        if not soundtracks:
            st.info("No data available. Run Calculate All Deep Analyses first.")
        else:
            matrix = get_city_artist_affinity_matrix(soundtracks)
            if matrix.empty:
                st.info("No affinity data available.")
            else:
                st.dataframe(matrix, width="stretch")
