"""Overview page — hero card and Time Machine ("this day in history") card."""

from __future__ import annotations

import datetime
import random
from datetime import timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pandas import DataFrame

from analysis_utils import get_daily_activity
from components.share import render_share_button
from components.theme import (
    ACCENT_CYAN,
    ACCENT_GREEN,
    ACCENT_INDIGO,
    ACCENT_ORANGE,
    ACCENT_PINK,
    ACCENT_PURPLE,
    ACCENT_YELLOW,
    CALENDAR_HEATMAP_SCALE,
    TEXT_DIM,
    TEXT_PRIMARY,
    apply_dark_theme,
    card_container,
)
from core.time_machine import TimeMachineEntry, get_time_machine_entry
from export_html import build_overview_page_html

# Source-selector options for the activity calendar (issue #27) — order matters,
# matches the `st.radio` display order and maps 1:1 to `get_daily_activity`'s
# `source` argument.
_ACTIVITY_SOURCE_OPTIONS = ["All activity", "Music", "Check-ins"]
_ACTIVITY_SOURCE_MAP = {"All activity": "all", "Music": "music", "Check-ins": "checkins"}


def _stat_html(value: str, label: str, color: str) -> str:
    """Return HTML for a single secondary stat inside the hero card."""
    return (
        f'<div style="text-align:center">'
        f'<p style="font-size:24px;font-weight:700;color:{color};margin:0;line-height:1">'
        f"{value}</p>"
        f'<p style="font-size:11px;color:{TEXT_DIM};margin:4px 0 0 0">{label}</p>'
        f"</div>"
    )


def _time_machine_location_html(entry: TimeMachineEntry) -> str:
    """Return HTML for the Time Machine card's location line, or "" if unknown."""
    if entry.location is None:
        return ""
    parts = [p for p in (entry.location.city, entry.location.state, entry.location.country) if p]
    if not parts:
        return ""
    return (
        f'<p style="font-size:13px;color:{TEXT_PRIMARY};margin:0 0 0.5rem 0">'
        f'<strong style="color:{ACCENT_CYAN}">Where you were —</strong> {", ".join(parts)}</p>'
    )


def _time_machine_listening_html(entry: TimeMachineEntry) -> str:
    """Return HTML for the Time Machine card's listening line, or "" if no scrobbles."""
    listening = entry.listening
    if listening is None or listening.scrobble_count == 0:
        return ""
    summary = f"{listening.scrobble_count:,} scrobble{'s' if listening.scrobble_count != 1 else ''}"
    if listening.top_artist:
        summary += f" &middot; top artist: {listening.top_artist}"
    lines = [
        f'<p style="font-size:13px;color:{TEXT_PRIMARY};margin:0 0 0.25rem 0">'
        f'<strong style="color:{ACCENT_INDIGO}">What you were listening to —</strong> {summary}</p>'
    ]
    if listening.sample_tracks:
        tracks = ", ".join(listening.sample_tracks)
        lines.append(f'<p style="font-size:12px;color:{TEXT_DIM};margin:0 0 0.5rem 0">{tracks}</p>')
    return "".join(lines)


def _time_machine_events_html(entry: TimeMachineEntry) -> str:
    """Return HTML for the Time Machine card's events line, or "" if none."""
    if not entry.events:
        return ""
    items = []
    for event in entry.events:
        label = " — ".join(p for p in (event.label, event.sublabel) if p)
        if not label:
            continue
        items.append(label)
    if not items:
        return ""
    return (
        f'<p style="font-size:13px;color:{TEXT_PRIMARY};margin:0 0 0.5rem 0">'
        f'<strong style="color:{ACCENT_PINK}">What you were doing —</strong> {", ".join(items)}</p>'
    )


def render_time_machine_card(
    df: DataFrame | None,
    swarm_df: DataFrame | None,
    today: datetime.date | None = None,
    rng: random.Random | None = None,
) -> None:
    """Render the "Time Machine" this-day-in-history card.

    Picks a random past year (relative to ``today``) that has at least one matching
    record on today's month/day across listening, location, or events data, and shows
    a compact card summarizing where the user was, what they were listening to, and
    what else they were doing (check-ins, photos, drinks, etc.). Degrades gracefully to
    an empty-state message when no historical data exists for any candidate year.

    Args:
        df: The Last.fm-shaped what-when frame from ``st.session_state['df']``.
        swarm_df: The where-when frame from ``st.session_state['swarm_df']``.
        today: The reference "today" date; defaults to the real current date. Callers
            (tests) can inject a fixed date for deterministic behavior.
        rng: A ``random.Random`` instance for deterministic year selection in tests;
            defaults to real wall-clock randomness.
    """
    resolved_today = today if today is not None else datetime.date.today()
    activity_df = df if df is not None else DataFrame()
    places_df = swarm_df if swarm_df is not None else DataFrame()

    entry = get_time_machine_entry(resolved_today, activity_df, places_df, rng=rng)

    st.markdown(
        f'<h2 style="font-size:16px;font-weight:700;margin:1.5rem 0 0.5rem 0;'
        f'color:{TEXT_PRIMARY}">Time Machine</h2>',
        unsafe_allow_html=True,
    )

    if entry is None:
        st.info("No historical data found for this day yet. Keep tracking, and check back later.")
        return

    body_parts = [
        _time_machine_location_html(entry),
        _time_machine_listening_html(entry),
        _time_machine_events_html(entry),
    ]
    body_html = "".join(p for p in body_parts if p)
    if not body_html:
        st.info("No historical data found for this day yet. Keep tracking, and check back later.")
        return

    years_label = f"{entry.years_ago} year{'s' if entry.years_ago != 1 else ''} ago"
    date_label = entry.target_date.strftime("%B %d, %Y")

    html = (
        '<div style="background:linear-gradient(135deg,#1e1b4b,#0c1120);'
        "border:1px solid #6366f1;border-radius:12px;padding:1.5rem 2rem;"
        'margin-bottom:1.5rem">'
        f'<p style="font-size:12px;color:{TEXT_DIM};margin:0 0 0.75rem 0;'
        f'text-transform:uppercase;letter-spacing:0.08em">'
        f"{years_label} today &middot; {date_label}</p>"
        f"{body_html}"
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def render_overview() -> None:
    """Render the Overview page: hero card and top-entity charts.

    Reads ``st.session_state['df']`` (Last.fm) and optionally
    ``st.session_state['swarm_df']`` (Foursquare/Swarm).  Shows an empty
    state when no data has been loaded.
    """
    df: DataFrame | None = st.session_state.get("df")
    swarm_df: DataFrame | None = st.session_state.get("swarm_df")

    year = (
        df["date_text"].dt.year.max()
        if df is not None and not df.empty
        else datetime.date.today().year
    )

    # ── Page header ──────────────────────────────────────────────────────────
    st.markdown(
        f"""
        <h1 style="font-size:22px;font-weight:700;margin-bottom:2px;color:#f0f4ff">Overview</h1>
        <p style="font-size:12px;color:{TEXT_DIM};margin-top:0;margin-bottom:1rem">
            Your complete personal data &middot; {year}
        </p>
        """,
        unsafe_allow_html=True,
    )

    if df is None or df.empty:
        st.info(
            "No music data loaded yet. "
            "Configure a Last.fm source in the sidebar and select a data file."
        )
        return

    generated_at = datetime.datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html_bytes = build_overview_page_html(df, swarm_df, generated_at).encode("utf-8")
    render_share_button(html_bytes, "autobiographer-overview.html")

    # ── Last.fm stats ─────────────────────────────────────────────────────────
    total_scrobbles = len(df)
    music_stats = "".join(
        [
            _stat_html(f"{df['artist'].nunique():,}", "artists", ACCENT_INDIGO),
            _stat_html(f"{df['album'].nunique():,}", "albums", ACCENT_CYAN),
            _stat_html(f"{df['track'].nunique():,}", "tracks", ACCENT_PINK),
            _stat_html(f"{df['date_text'].dt.date.nunique():,}", "days", ACCENT_PURPLE),
        ]
    )

    # ── Hero card — built as a flat joined string so the Markdown renderer
    # never sees indented lines (4+ spaces = code block in CommonMark).  ─────
    parts = [
        '<div class="autobio-hero-card">',
        '<div style="display:flex;justify-content:space-between;'
        'align-items:center;flex-wrap:wrap;gap:1.5rem">',
        "<div>",
        f'<p style="font-size:48px;font-weight:700;color:#f0f4ff;'
        f'margin:0;line-height:1">{total_scrobbles:,}</p>',
        f'<p style="font-size:13px;color:{TEXT_DIM};margin:4px 0 0.75rem 0">Last.fm scrobbles</p>',
        f'<div style="display:flex;gap:2rem;flex-wrap:wrap">{music_stats}</div>',
        "</div>",
    ]

    if swarm_df is not None and not swarm_df.empty:
        total_checkins = len(swarm_df)
        unique_venues = swarm_df["venue"].nunique() if "venue" in swarm_df.columns else 0
        unique_cities = swarm_df["city"].nunique() if "city" in swarm_df.columns else 0
        unique_countries = swarm_df["country"].nunique() if "country" in swarm_df.columns else 0
        swarm_stats = "".join(
            [
                _stat_html(f"{unique_venues:,}", "venues", ACCENT_GREEN),
                _stat_html(f"{unique_cities:,}", "cities", ACCENT_ORANGE),
                _stat_html(f"{unique_countries:,}", "countries", ACCENT_YELLOW),
            ]
        )
        parts += [
            '<div style="border-left:1px solid #2d3a52;padding-left:2.5rem;margin-left:1rem">',
            f'<p style="font-size:11px;font-weight:600;color:{TEXT_DIM};'
            f"letter-spacing:0.08em;text-transform:uppercase;"
            f'margin:0 0 0.75rem 0">Foursquare</p>',
            '<div style="display:flex;flex-direction:column;align-items:flex-start;gap:0.5rem">',
            '<div style="display:flex;align-items:baseline;gap:0.5rem">',
            f'<p style="font-size:32px;font-weight:700;color:#f0f4ff;'
            f'margin:0;line-height:1">{total_checkins:,}</p>',
            f'<p style="font-size:13px;color:{TEXT_DIM};margin:0">check-ins</p>',
            "</div>",
            f'<div style="display:flex;gap:1.5rem;flex-wrap:wrap">{swarm_stats}</div>',
            "</div>",
            "</div>",
        ]

    parts += ["</div>", "</div>"]
    st.markdown("".join(parts), unsafe_allow_html=True)

    # ── Time Machine — "this day in history" (issue #98) ───────────────────
    render_time_machine_card(df, swarm_df)

    # ── Activity calendar heatmap (issue #27) ───────────────────────────────
    render_activity_calendar(df, swarm_df)


def _build_calendar_heatmap_figure(activity_df: DataFrame) -> go.Figure:
    """Build a GitHub-contribution-graph-style calendar heatmap figure.

    Bins ``activity_df``'s ``date``/``value`` columns into a week-index
    (x-axis, integer week offset from the overall min date) by day-of-week
    (y-axis, Sunday-Saturday, GitHub convention) grid, and renders it as a
    single ``go.Heatmap`` trace.

    Args:
        activity_df: Two-column DataFrame (``date``, ``value``) as returned by
            ``analysis_utils.get_daily_activity`` — one row per calendar day,
            zero-filled across the full date range, no gaps.

    Returns:
        A themed ``go.Figure`` with one ``go.Heatmap`` trace. Cells outside the
        real date range (grid padding needed to complete whole weeks) are left
        as ``NaN`` so they render as blank rather than a false zero; every real
        day in ``activity_df`` lands in exactly one cell with its true value
        (including genuine zero-activity days).
    """
    dates = pd.to_datetime(activity_df["date"])
    values = activity_df["value"].to_numpy()

    # GitHub convention: Sunday=0 ... Saturday=6. pandas' dayofweek is
    # Monday=0 ... Sunday=6, so shift by one day and wrap.
    day_of_week = (dates.dt.dayofweek + 1) % 7
    grid_start = dates.iloc[0] - pd.Timedelta(days=int(day_of_week.iloc[0]))
    week_index = ((dates - grid_start).dt.days // 7).to_numpy()

    num_weeks = int(week_index.max()) + 1
    z: list[list[float]] = [[float("nan")] * num_weeks for _ in range(7)]
    text: list[list[str]] = [[""] * num_weeks for _ in range(7)]

    for date, value, dow, week in zip(dates, values, day_of_week, week_index):
        z[int(dow)][int(week)] = float(value)
        text[int(dow)][int(week)] = f"{date.strftime('%Y-%m-%d')}<br>{int(value)} activities"

    day_labels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            text=text,
            y=day_labels,
            colorscale=CALENDAR_HEATMAP_SCALE,
            zmin=0,
            hovertemplate="%{text}<extra></extra>",
            showscale=False,
            xgap=2,
            ygap=2,
        )
    )
    fig.update_layout(
        xaxis=dict(showticklabels=False, fixedrange=True),
        yaxis=dict(autorange="reversed", fixedrange=True),
        height=200,
        margin=dict(l=40, r=10, t=10, b=10),
    )
    apply_dark_theme(fig)
    return fig


def render_activity_calendar(df: DataFrame | None, swarm_df: DataFrame | None) -> None:
    """Render the full-year activity calendar heatmap card (issue #27).

    Shows a GitHub-contribution-graph-style heatmap of daily activity
    intensity, with an inline source selector (All activity / Music /
    Check-ins) shown only when Swarm/Foursquare data is genuinely loaded
    alongside the music data.

    Args:
        df: The Last.fm-shaped listening-history frame from
            ``st.session_state['df']``.
        swarm_df: The Foursquare/Swarm check-in frame from
            ``st.session_state['swarm_df']``, or None if not loaded.
    """
    if df is None or df.empty:
        return

    has_swarm = swarm_df is not None and not swarm_df.empty
    if has_swarm:
        selection = st.radio(
            "Activity source",
            _ACTIVITY_SOURCE_OPTIONS,
            index=0,
            horizontal=True,
        )
        source = _ACTIVITY_SOURCE_MAP[selection]
    else:
        source = "all"

    activity_df = get_daily_activity(df, swarm_df, source=source)
    if activity_df.empty:
        st.info("No activity data available for this selection yet.")
        return

    fig = _build_calendar_heatmap_figure(activity_df)
    with card_container():
        st.plotly_chart(fig, width="stretch")
