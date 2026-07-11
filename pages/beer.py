"""Drinking History page — Untappd check-in exploration (issue #124).

Surfaces the beer check-in history emitted by ``UntappdPlugin``
(``packages/localizer/src/localizer/plugins/untappd/loader.py``) as
``OutputTable.EVENTS`` rows: a chronological timeline, brewery/style
breakdowns, a rating distribution/trend, and a secondary map of check-ins that
have venue coordinates.

Data loading bypasses ``LocalizerBroker``/``components.sidebar``'s merged
``df``/``swarm_df`` session state on purpose: rating/venue_name/venue_lat/
venue_lng live only inside each event's ``raw_json`` (the events table has no
lat/lng columns of its own), and ``LocalizerBroker.get_events_frame()``
intentionally never exposes ``raw_json`` — it feeds the generic lastfm-shaped
merge used elsewhere. This page instead opens ``LocalizerStore`` directly with
``query_events(include_raw_json=True)`` and shapes the result via
``core.drinking_history``.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from components.theme import COLORWAY, apply_dark_theme
from core.drinking_history import (
    build_checkins_frame,
    checkins_with_venue,
    rating_distribution,
    rating_trend,
    top_breweries,
    top_styles,
)

_TOP_N = 10


def _load_untappd_checkins() -> pd.DataFrame:
    """Load and shape Untappd check-in history from the local DuckDB store.

    Returns:
        A checkins frame (see ``core.drinking_history.build_checkins_frame``),
        or an empty frame if the store/plugin has no data yet or the query
        fails for any reason (e.g. localizer not installed, store unreadable).
    """
    try:
        from localizer.store.db import LocalizerStore  # noqa: PLC0415

        with LocalizerStore() as store:
            events_df = store.query_events(source_id="untappd", include_raw_json=True)
    except Exception:  # noqa: BLE001
        return build_checkins_frame(pd.DataFrame())

    return build_checkins_frame(events_df)


def _render_timeline(checkins: pd.DataFrame) -> None:
    """Render a chronological list of check-ins, most recent first."""
    st.subheader("Check-in Timeline")
    timeline = checkins.sort_values("timestamp", ascending=False)
    display = timeline[["date", "brewery", "beer", "style", "rating", "venue_name"]].copy()
    display["date"] = display["date"].dt.strftime("%Y-%m-%d")
    display["rating"] = display["rating"].map(lambda r: "" if pd.isna(r) else f"{r:.2f}")
    display["venue_name"] = display["venue_name"].replace("", "—")
    display.columns = ["Date", "Brewery", "Beer", "Style", "Rating", "Venue"]
    st.dataframe(display, width="stretch", hide_index=True)


def _render_breakdown(checkins: pd.DataFrame) -> None:
    """Render top-breweries and top-beer-styles bar charts side by side."""
    breweries = top_breweries(checkins, top_n=_TOP_N)
    styles = top_styles(checkins, top_n=_TOP_N)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Top Breweries")
        if breweries.empty:
            st.info("No brewery data available.")
        else:
            st.bar_chart(breweries.set_index("brewery")["checkins"], width="stretch")

    with col2:
        st.subheader("Top Beer Styles")
        if styles.empty:
            st.info("No beer style data available.")
        else:
            st.bar_chart(styles.set_index("style")["checkins"], width="stretch")


def _render_ratings(checkins: pd.DataFrame) -> None:
    """Render the rating distribution and the monthly average-rating trend."""
    distribution = rating_distribution(checkins)
    trend = rating_trend(checkins)

    st.subheader("Rating Distribution")
    if distribution.empty:
        st.info("No rated check-ins yet.")
    else:
        st.bar_chart(distribution.set_index("rating")["checkins"], width="stretch")

    st.subheader("Rating Trend Over Time")
    if trend.empty:
        st.info("No rated check-ins yet.")
    else:
        st.line_chart(trend.set_index("month")["avg_rating"], width="stretch")


def _render_venue_map(checkins: pd.DataFrame) -> None:
    """Render a map of check-ins that have known venue coordinates."""
    st.subheader("Venue Map")
    mapped = checkins_with_venue(checkins)
    if mapped.empty:
        st.info("No check-ins with venue location data yet.")
        return

    fig = px.scatter_map(
        mapped,
        lat="venue_lat",
        lon="venue_lng",
        color="brewery",
        hover_name="venue_name",
        hover_data={"beer": True, "rating": True, "venue_lat": False, "venue_lng": False},
        color_discrete_sequence=COLORWAY,
        zoom=1,
        title="Check-in Venues",
    )
    fig.update_layout(
        map_style="carto-darkmatter",
        height=560,
        margin={"r": 0, "t": 40, "l": 0, "b": 0},
    )
    apply_dark_theme(fig)
    st.plotly_chart(fig, width="stretch")

    st.caption(f"{len(mapped):,} of {len(checkins):,} check-ins have venue location data.")


def render_beer() -> None:
    """Render the Drinking History page: summary metrics + four exploration tabs.

    Shows an empty-state banner until Untappd check-in data has been
    configured and synced (see ``pages/data_sources.py``); otherwise renders a
    chronological timeline, brewery/style breakdowns, rating distribution and
    trend, and a secondary venue map for check-ins with known coordinates.
    """
    st.header("Drinking History")

    checkins = _load_untappd_checkins()
    if checkins.empty:
        st.info(
            "No beer data loaded yet. Add the Untappd source plugin and configure it "
            "in the sidebar, then sync your check-in history."
        )
        return

    metric_cols = st.columns(3)
    with metric_cols[0]:
        st.metric("Total Check-ins", f"{len(checkins):,}")
    with metric_cols[1]:
        rated = checkins["rating"].dropna()
        st.metric("Average Rating", f"{rated.mean():.2f}" if not rated.empty else "—")
    with metric_cols[2]:
        st.metric("Unique Breweries", f"{checkins['brewery'].nunique():,}")

    tabs = st.tabs(["Timeline", "Breakdown", "Ratings", "Venue Map"])

    with tabs[0]:
        _render_timeline(checkins)
    with tabs[1]:
        _render_breakdown(checkins)
    with tabs[2]:
        _render_ratings(checkins)
    with tabs[3]:
        _render_venue_map(checkins)
