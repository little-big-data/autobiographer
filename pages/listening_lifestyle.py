"""Listening Lifestyle page — a multi-faceted portrait of how you listen to music.

Synthesises three listening contexts into a single narrative page:

- **Your Week**          Home vs. away, weekday vs. weekend patterns
- **After Dark**         Late-night listening, midnight–4 AM
- **Year's Traditions**  Holiday listening patterns

A Persona Banner at the top derives lifestyle trait badges from the data.
Each section is a collapsed expander: key metrics visible immediately, full
chart revealed on expansion.

All analysis runs once and is cached in ``st.session_state`` keyed by
``(id(df), id(swarm_df), hash(assumptions))``.  UI interactions (expanding
sections, scrolling) never re-trigger computation.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analysis_utils import (
    load_assumptions,
)
from components.theme import (
    ACCENT_CYAN,
    ACCENT_GREEN,
    ACCENT_INDIGO,
    ACCENT_ORANGE,
    ACCENT_PINK,
    ACCENT_PURPLE,
    ACCENT_YELLOW,
    COLORWAY,
    apply_dark_theme,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LATE_NIGHT_START = 0
_LATE_NIGHT_END = 4  # hours 0, 1, 2, 3 (exclusive upper bound)
_SESSION_GAP_MINUTES = 30

# Built-in seasons always computed regardless of assumptions
_BUILTIN_SEASONS: list[dict[str, Any]] = [
    {"name": "Halloween Season", "month": 10, "day_range": [1, 31]},
    {"name": "Thanksgiving Season", "month": 11, "day_range": [1, 30]},
]

# Weekend context display order and styling
_CONTEXT_LABELS: dict[tuple[bool, bool], str] = {
    (False, True): "Home Weekday",
    (True, True): "Home Weekend",
    (False, False): "Away Weekday",
    (True, False): "Away Weekend",
}
_CONTEXT_COLORS: dict[tuple[bool, bool], str] = {
    (False, True): ACCENT_INDIGO,
    (True, True): ACCENT_CYAN,
    (False, False): ACCENT_ORANGE,
    (True, False): ACCENT_GREEN,
}
_GRID_ORDER: list[tuple[bool, bool]] = [
    (False, True),
    (True, True),
    (False, False),
    (True, False),
]

# Persona badge definitions: (label, accent_color, signal_key)
_PERSONA_BADGES: list[tuple[str, str, str]] = [
    ("Night Owl", ACCENT_INDIGO, "late_rate"),
    ("Weekend Listener", ACCENT_CYAN, "weekend_boost"),
    ("Globe Trotter", ACCENT_ORANGE, "away_share"),
    ("Holiday Traditionalist", ACCENT_YELLOW, "holiday_count"),
]


# ---------------------------------------------------------------------------
# Week / weekend helpers
# ---------------------------------------------------------------------------


def _add_weekend_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``day_of_week`` and ``is_weekend`` columns from ``date_text``.

    Args:
        df: Listening history with a datetime ``date_text`` column.

    Returns:
        Copy of ``df`` with two additional columns.
    """
    out = df.copy()
    out["day_of_week"] = out["date_text"].dt.day_name()
    out["is_weekend"] = out["date_text"].dt.weekday >= 5
    return out


def _add_location_context(df: pd.DataFrame, home_city: str) -> pd.DataFrame:
    """Add ``is_home`` column — True when the city matches *home_city*.

    Args:
        df: Listening history with a ``city`` column.
        home_city: Home city from assumptions (may include ", CC" suffix).

    Returns:
        Copy of ``df`` with ``is_home`` column added.
    """
    out = df.copy()
    bare_home = home_city.split(",")[0].strip().lower()
    out["is_home"] = out["city"].str.split(",").str[0].str.strip().str.lower() == bare_home
    return out


_DAY_ORDER: list[str] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _compute_week_stats(df: pd.DataFrame, home_city: str) -> list[dict[str, Any]]:
    """Compute per-context statistics for the four (is_weekend × is_home) cells.

    Args:
        df: Enriched listening history with ``date_text``, ``artist``, ``city``.
        home_city: The user's home city string.

    Returns:
        List of four stat dicts in ``_GRID_ORDER`` order, each with a
        ``subset`` key for the raw rows and a ``peak_hour`` key.
    """
    enriched = _add_weekend_columns(_add_location_context(df, home_city))
    stats: list[dict[str, Any]] = []

    for is_weekend, is_home in _GRID_ORDER:
        mask = (enriched["is_weekend"] == is_weekend) & (enriched["is_home"] == is_home)
        subset = enriched[mask]
        play_count = len(subset)

        if not subset.empty:
            top_artists = subset["artist"].value_counts().head(3).index.tolist()
            hour_counts = subset.groupby(subset["date_text"].dt.hour).size()
            peak_hour = int(hour_counts.idxmax()) if not hour_counts.empty else None
        else:
            top_artists, peak_hour = [], None

        stats.append(
            {
                "is_weekend": is_weekend,
                "is_home": is_home,
                "label": _CONTEXT_LABELS[(is_weekend, is_home)],
                "color": _CONTEXT_COLORS[(is_weekend, is_home)],
                "play_count": play_count,
                "top_artists": top_artists,
                "peak_hour": peak_hour,
                "subset": subset,
            }
        )

    return stats


def _compute_week_by_day(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Compute top-10 artists and albums for each day of the week.

    Args:
        df: Listening history with ``date_text``, ``artist``, ``album`` columns.

    Returns:
        Dict mapping day name (e.g. ``"Monday"``) to a dict with keys
        ``play_count`` (int), ``top_artists`` (DataFrame), ``top_albums`` (DataFrame).
    """
    by_day: dict[str, dict[str, Any]] = {}
    if df.empty or "date_text" not in df.columns:
        for day in _DAY_ORDER:
            by_day[day] = {
                "play_count": 0,
                "top_artists": pd.DataFrame(),
                "top_albums": pd.DataFrame(),
            }
        return by_day

    enriched = df.copy()
    enriched["day_of_week"] = enriched["date_text"].dt.day_name()

    for day in _DAY_ORDER:
        subset = enriched[enriched["day_of_week"] == day]
        by_day[day] = {
            "play_count": len(subset),
            "top_artists": subset["artist"]
            .value_counts()
            .head(10)
            .reset_index()
            .rename(columns={"artist": "Artist", "count": "Plays"})
            if not subset.empty and "artist" in subset.columns
            else pd.DataFrame(),
            "top_albums": subset["album"]
            .value_counts()
            .head(10)
            .reset_index()
            .rename(columns={"album": "Album", "count": "Plays"})
            if not subset.empty and "album" in subset.columns
            else pd.DataFrame(),
        }
    return by_day


# ---------------------------------------------------------------------------
# Late night helpers
# ---------------------------------------------------------------------------


def _filter_late_night(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows where the local hour falls in the midnight–4 AM window.

    Args:
        df: Listening history with a ``date_text`` datetime column.

    Returns:
        Filtered DataFrame; empty when no late-night rows exist.
    """
    if df.empty or "date_text" not in df.columns:
        return pd.DataFrame()
    mask = (df["date_text"].dt.hour >= _LATE_NIGHT_START) & (
        df["date_text"].dt.hour < _LATE_NIGHT_END
    )
    return df[mask].copy()


def get_top_late_night_artists(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    """Return the top ``limit`` artists by late-night play count.

    Args:
        df: Full listening history with ``date_text`` and ``artist``.
        limit: Maximum number of artists to return.

    Returns:
        DataFrame with columns ``artist`` and ``plays``.
    """
    late = _filter_late_night(df)
    if late.empty or "artist" not in late.columns:
        return pd.DataFrame(columns=["artist", "plays"])
    counts = late["artist"].value_counts().head(limit).reset_index()
    counts.columns = pd.Index(["artist", "plays"])
    return counts


def get_late_night_by_hour(df: pd.DataFrame, top_n: int = 10) -> dict[int, dict[str, Any]]:
    """Compute top artists and albums for each late-night hour (0–3).

    Args:
        df: Full listening history with ``date_text``, ``artist``, ``album``.
        top_n: Maximum top artists/albums to return per hour.

    Returns:
        Dict keyed by hour integer (0, 1, 2, 3).  Each value has
        ``play_count``, ``top_artists`` (DataFrame), ``top_albums`` (DataFrame).
    """
    late = _filter_late_night(df)
    result: dict[int, dict[str, Any]] = {}
    for hour in range(_LATE_NIGHT_START, _LATE_NIGHT_END):
        subset = late[late["date_text"].dt.hour == hour] if not late.empty else late
        top_artists = (
            subset["artist"]
            .value_counts()
            .head(top_n)
            .reset_index()
            .rename(columns={"artist": "Artist", "count": "Plays"})
            if not subset.empty and "artist" in subset.columns
            else pd.DataFrame()
        )
        top_albums = (
            subset["album"]
            .value_counts()
            .head(top_n)
            .reset_index()
            .rename(columns={"album": "Album", "count": "Plays"})
            if not subset.empty and "album" in subset.columns
            else pd.DataFrame()
        )
        result[hour] = {
            "play_count": len(subset),
            "top_artists": top_artists,
            "top_albums": top_albums,
        }
    return result


def get_late_night_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Return hourly play counts for all 24 hours with a late-night flag.

    Args:
        df: Listening history with ``date_text``.

    Returns:
        DataFrame with columns ``hour`` (0–23), ``plays`` (int),
        ``is_late_night`` (bool).
    """
    all_hours = pd.DataFrame({"hour": range(24)})
    if df.empty or "date_text" not in df.columns:
        all_hours["plays"] = 0
        all_hours["is_late_night"] = all_hours["hour"] < _LATE_NIGHT_END
        return all_hours
    hourly = (
        df.assign(hour=df["date_text"].dt.hour).groupby("hour").size().reset_index(name="plays")
    )
    merged = all_hours.merge(hourly, on="hour", how="left").fillna(0)
    merged["plays"] = merged["plays"].astype(int)
    merged["is_late_night"] = (merged["hour"] >= _LATE_NIGHT_START) & (
        merged["hour"] < _LATE_NIGHT_END
    )
    return merged


def find_latest_session(df: pd.DataFrame) -> dict[str, Any] | None:
    """Find the most extreme consecutive late-night listening session.

    A session is consecutive plays within the midnight–4 AM window with
    inter-play gaps under :data:`_SESSION_GAP_MINUTES`.  The longest session
    wins; ties broken by most recent start time.

    Args:
        df: Listening history with ``date_text``, ``timestamp``, ``artist``.

    Returns:
        Dict with ``start``, ``end``, ``track_count``, ``artists``;
        or ``None`` when no late-night plays exist.
    """
    late = _filter_late_night(df)
    if late.empty or "timestamp" not in late.columns:
        return None

    late = late.sort_values("timestamp").reset_index(drop=True)
    gap_sec = _SESSION_GAP_MINUTES * 60

    sessions: list[dict[str, Any]] = []
    session_start = 0

    for i in range(1, len(late)):
        gap = late.loc[i, "timestamp"] - late.loc[i - 1, "timestamp"]
        if gap > gap_sec:
            sessions.append(
                {
                    "start": late.loc[session_start, "date_text"],
                    "end": late.loc[i - 1, "date_text"],
                    "track_count": i - session_start,
                    "artists": late.loc[session_start : i - 1, "artist"].dropna().unique().tolist(),
                }
            )
            session_start = i

    sessions.append(
        {
            "start": late.loc[session_start, "date_text"],
            "end": late.loc[len(late) - 1, "date_text"],
            "track_count": len(late) - session_start,
            "artists": late.loc[session_start:, "artist"].dropna().unique().tolist(),
        }
    )

    return max(sessions, key=lambda s: (s["track_count"], s["start"]))


# ---------------------------------------------------------------------------
# Holiday helpers
# ---------------------------------------------------------------------------


def _build_holiday_windows(df: pd.DataFrame, holiday: dict[str, Any]) -> list[dict[str, Any]]:
    """Build per-year date windows for a recurring holiday.

    Args:
        df: Listening history with a ``date_text`` column.
        holiday: Holiday definition dict with ``month`` and ``day_range`` keys.

    Returns:
        List of dicts with ``year``, ``start``, ``end`` per calendar year in ``df``.
    """
    if df.empty or "date_text" not in df.columns:
        return []
    month: int = holiday.get("month", 1)
    day_range: list[int] = holiday.get("day_range", [1, 1])
    day_start, day_end = day_range[0], day_range[1]
    windows: list[dict[str, Any]] = []
    for year in sorted(df["date_text"].dt.year.unique()):
        try:
            start = pd.Timestamp(year=int(year), month=month, day=day_start)
            end = pd.Timestamp(
                year=int(year), month=month, day=day_end, hour=23, minute=59, second=59
            )
        except ValueError:
            continue
        windows.append({"year": int(year), "start": start, "end": end})
    return windows


def _filter_holiday(df: pd.DataFrame, window: dict[str, Any]) -> pd.DataFrame:
    """Return rows within a holiday window.

    Args:
        df: Listening history with a ``date_text`` column.
        window: Dict with ``start`` and ``end`` Timestamp keys.

    Returns:
        Filtered sub-DataFrame (may be empty).
    """
    mask = (df["date_text"] >= window["start"]) & (df["date_text"] <= window["end"])
    return df[mask]


def _signature_song(df: pd.DataFrame, windows: list[dict[str, Any]]) -> str | None:
    """Find the most-played track (name only) across all holiday windows.

    Args:
        df: Full listening history.
        windows: All per-year windows for a holiday.

    Returns:
        Track name string, or ``None`` when no data exists.
    """
    if not windows or df.empty:
        return None
    subsets = [_filter_holiday(df, w) for w in windows]
    combined = pd.concat(subsets, ignore_index=True)
    if combined.empty or "track" not in combined.columns:
        return None
    tracks = combined["track"].dropna()
    tracks = tracks[tracks.str.strip() != ""]
    if tracks.empty:
        return None
    return str(tracks.value_counts().index[0])


def _top_n_table(combined: pd.DataFrame, col: str, n: int = 10) -> pd.DataFrame:
    """Return a top-N plays table for *col* from *combined*.

    Args:
        combined: DataFrame with the column *col*.
        col: Column name to count (``"artist"``, ``"album"``, or ``"track"``).
        n: Number of top entries to return.

    Returns:
        DataFrame with columns ``[col, "Plays"]``; empty when *col* is absent.
    """
    if combined.empty or col not in combined.columns:
        return pd.DataFrame(columns=[col, "Plays"])
    counts = combined[col].value_counts().head(n).reset_index()
    counts.columns = pd.Index([col, "Plays"])
    return counts


def _compute_holiday_stats(
    df: pd.DataFrame, holidays: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compute per-holiday statistics across all years.

    Args:
        df: Full listening history.
        holidays: List of holiday dicts from assumptions (``name``, ``month``,
            ``day_range``).

    Returns:
        List of dicts; one per holiday that has at least one year of data.
        Each dict has: ``name``, ``windows``, ``total_plays``, ``years_with_data``,
        ``top_artist``, ``signature_song``, ``yoy_plays`` (DataFrame),
        ``top_artists`` (DataFrame), ``top_albums`` (DataFrame),
        ``top_songs`` (DataFrame).
    """
    results = []
    for holiday in holidays:
        windows = _build_holiday_windows(df, holiday)
        if not windows:
            continue
        yoy_rows = []
        for w in windows:
            subset = _filter_holiday(df, w)
            yoy_rows.append({"year": w["year"], "plays": len(subset)})
        yoy = pd.DataFrame(yoy_rows)
        years_with_data = int((yoy["plays"] > 0).sum())
        if years_with_data == 0:
            continue
        all_subsets = [_filter_holiday(df, w) for w in windows]
        combined = pd.concat(all_subsets, ignore_index=True)
        top_artist = (
            combined["artist"].value_counts().index[0]
            if not combined.empty and "artist" in combined.columns
            else None
        )
        results.append(
            {
                "name": holiday.get("name", "Holiday"),
                "windows": windows,
                "total_plays": int(yoy["plays"].sum()),
                "years_with_data": years_with_data,
                "top_artist": top_artist,
                "signature_song": _signature_song(df, windows),
                "yoy_plays": yoy,
                "top_artists": _top_n_table(combined, "artist"),
                "top_albums": _top_n_table(combined, "album"),
                "top_songs": _top_n_table(combined, "track"),
            }
        )
    return sorted(results, key=lambda h: h["total_plays"], reverse=True)


# ---------------------------------------------------------------------------
# Data computation — cached in session state
# ---------------------------------------------------------------------------


def _compute_lifestyle_data(
    df: pd.DataFrame,
    swarm_df: pd.DataFrame,
    assumptions: dict[str, Any],
) -> dict[str, Any]:
    """Run lifestyle analyses for week, late night, and holidays.

    Args:
        df: Full listening history.
        swarm_df: Swarm check-in DataFrame (may be empty, unused currently).
        assumptions: Parsed assumptions dict.

    Returns:
        Dict with keys ``week``, ``late_night``, ``holiday`` and their computed values.
    """
    home_city: str = assumptions.get("defaults", {}).get("city", "")

    # Week / weekend context
    week_stats = _compute_week_stats(df, home_city) if home_city else []
    week_by_day = _compute_week_by_day(df)

    # Late night
    late_df = _filter_late_night(df)
    late_rate = len(late_df) / len(df) if len(df) > 0 else 0.0
    top_late_night = get_top_late_night_artists(df, limit=10)
    late_hourly = get_late_night_hourly(df)
    late_by_hour = get_late_night_by_hour(df)
    latest_session = find_latest_session(df)

    # Holiday — merge user-defined holidays with built-in seasons (user names win)
    holidays_def = assumptions.get("holidays", [])
    assumption_names = {h.get("name", "").lower() for h in holidays_def}
    merged_holidays = list(holidays_def) + [
        s for s in _BUILTIN_SEASONS if s["name"].lower() not in assumption_names
    ]
    holiday_stats = _compute_holiday_stats(df, merged_holidays)

    # Persona signal values (used by badge synthesis)
    home_weekend_plays = next(
        (s["play_count"] for s in week_stats if s["is_weekend"] and s["is_home"]), 0
    )
    home_weekday_plays = next(
        (s["play_count"] for s in week_stats if not s["is_weekend"] and s["is_home"]), 0
    )
    away_plays = sum(s["play_count"] for s in week_stats if not s["is_home"])
    total_week_plays = sum(s["play_count"] for s in week_stats)
    away_share = away_plays / total_week_plays if total_week_plays > 0 else 0.0
    weekend_boost = (
        (home_weekend_plays - home_weekday_plays) / home_weekday_plays
        if home_weekday_plays > 0
        else 0.0
    )

    return {
        "week": week_stats,
        "week_by_day": week_by_day,
        "late_night": {
            "late_rate": late_rate,
            "top_artists": top_late_night,
            "hourly": late_hourly,
            "by_hour": late_by_hour,
            "latest_session": latest_session,
        },
        "holiday": holiday_stats,
        "persona_signals": {
            "late_rate": late_rate,
            "weekend_boost": weekend_boost,
            "away_share": away_share,
            "holiday_count": len(holiday_stats),
        },
    }


def _synthesize_persona(signals: dict[str, Any]) -> list[dict[str, str]]:
    """Derive lifestyle badge labels from the persona signal values.

    Args:
        signals: Dict of metric values from ``_compute_lifestyle_data``.

    Returns:
        List of dicts with ``label`` and ``color`` keys, at most 4 badges.
    """
    badges = []
    if signals.get("late_rate", 0) >= 0.10:
        badges.append({"label": "Night Owl", "color": ACCENT_INDIGO})
    if signals.get("weekend_boost", 0) >= 0.20:
        badges.append({"label": "Weekend Listener", "color": ACCENT_CYAN})
    if signals.get("away_share", 0) >= 0.20:
        badges.append({"label": "Globe Trotter", "color": ACCENT_ORANGE})
    if signals.get("holiday_count", 0) >= 2:
        badges.append({"label": "Holiday Traditionalist", "color": ACCENT_YELLOW})
    return badges if badges else [{"label": "Music Lover", "color": ACCENT_CYAN}]


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_persona_banner(data: dict[str, Any]) -> None:
    """Render the top-of-page persona banner with badges and key stats.

    Args:
        data: The full lifestyle data dict from ``_compute_lifestyle_data``.
    """
    badges = _synthesize_persona(data["persona_signals"])

    badge_html = " ".join(
        f"<span style='background:{b['color']}22; color:{b['color']}; "
        f"border:1px solid {b['color']}55; border-radius:999px; "
        f"padding:2px 12px; font-size:0.85rem; font-weight:600; "
        f"margin-right:6px;'>{b['label']}</span>"
        for b in badges
    )
    st.markdown(
        f"<div style='margin-bottom:0.5rem;'>{badge_html}</div>",
        unsafe_allow_html=True,
    )

    signals = data["persona_signals"]
    cols = st.columns(3)
    with cols[0]:
        late_pct = signals["late_rate"] * 100
        st.metric("Late-Night Plays", f"{late_pct:.1f}%")
    with cols[1]:
        boost_pct = signals["weekend_boost"] * 100
        st.metric("Weekend Boost", f"{boost_pct:+.0f}%", help="Weekend vs. weekday plays at home")
    with cols[2]:
        st.metric("Holidays Tracked", f"{signals['holiday_count']:,}")
    st.divider()


def _render_your_week(
    week_stats: list[dict[str, Any]], week_by_day: dict[str, dict[str, Any]]
) -> None:
    """Render the Your Week section.

    Args:
        week_stats: Output of ``_compute_week_stats`` (4-context summary).
        week_by_day: Output of ``_compute_week_by_day`` (per-day top-10 tables).
    """
    if not week_stats and not week_by_day:
        st.info("No music data available for weekly breakdown.")
        return

    if week_stats:
        total = sum(s["play_count"] for s in week_stats)
        home_wknd = next((s for s in week_stats if s["is_weekend"] and s["is_home"]), None)
        home_wkdy = next((s for s in week_stats if not s["is_weekend"] and s["is_home"]), None)

        cols = st.columns(4)
        for i, stat in enumerate(week_stats):
            with cols[i]:
                pct = stat["play_count"] / total * 100 if total > 0 else 0
                st.markdown(
                    f"<span style='color:{stat['color']}; font-weight:700;'>{stat['label']}</span>",
                    unsafe_allow_html=True,
                )
                st.metric("Plays", f"{stat['play_count']:,}", delta=f"{pct:.0f}% of total")
                if stat["top_artists"]:
                    st.caption(" · ".join(stat["top_artists"][:2]))

    with st.expander("Top 10 artists & albums by day", expanded=False):
        if week_stats:
            home_wknd = next((s for s in week_stats if s["is_weekend"] and s["is_home"]), None)
            home_wkdy = next((s for s in week_stats if not s["is_weekend"] and s["is_home"]), None)
            if home_wknd and home_wkdy and home_wkdy["play_count"] > 0:
                boost = (
                    (home_wknd["play_count"] - home_wkdy["play_count"])
                    / home_wkdy["play_count"]
                    * 100
                )
                st.caption(
                    f"Weekend listening is **{abs(boost):.0f}%** "
                    f"{'higher' if boost >= 0 else 'lower'} than weekdays at home."
                )

        if week_by_day:
            # Day-of-week play count bar
            day_rows = [{"Day": day, "Plays": week_by_day[day]["play_count"]} for day in _DAY_ORDER]
            day_df = pd.DataFrame(day_rows)
            fig = px.bar(
                day_df,
                x="Day",
                y="Plays",
                color_discrete_sequence=[ACCENT_INDIGO],
            )
            fig = apply_dark_theme(fig)
            fig.update_layout(height=240, showlegend=False)
            st.plotly_chart(fig, width="stretch", key="lifestyle_week_bar")

            # Per-day tabs with top 10 artists and albums
            tab_labels = [f"{day[:3]} ({week_by_day[day]['play_count']:,})" for day in _DAY_ORDER]
            tabs = st.tabs(tab_labels)
            for tab, day in zip(tabs, _DAY_ORDER):
                with tab:
                    day_data = week_by_day[day]
                    if day_data["play_count"] == 0:
                        st.caption("No plays recorded on this day.")
                        continue
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(
                            f"<span style='color:{ACCENT_INDIGO}; font-weight:600;'>"
                            f"Top Artists</span>",
                            unsafe_allow_html=True,
                        )
                        artists_df = day_data["top_artists"]
                        if not artists_df.empty:
                            st.dataframe(artists_df, hide_index=True, width="stretch")
                    with col_b:
                        st.markdown(
                            f"<span style='color:{ACCENT_CYAN}; font-weight:600;'>"
                            f"Top Albums</span>",
                            unsafe_allow_html=True,
                        )
                        albums_df = day_data["top_albums"]
                        if not albums_df.empty:
                            st.dataframe(albums_df, hide_index=True, width="stretch")


def _render_after_dark(late_data: dict[str, Any]) -> None:
    """Render the After Dark section.

    Args:
        late_data: Late-night facet dict from ``_compute_lifestyle_data``.
    """
    late_rate = late_data["late_rate"]
    top_artists = late_data["top_artists"]
    hourly = late_data["hourly"]
    session = late_data["latest_session"]

    top_artist = str(top_artists.iloc[0]["artist"]) if not top_artists.empty else "—"

    cols = st.columns(3)
    with cols[0]:
        st.metric(
            "Late-Night Rate",
            f"{late_rate * 100:.1f}%",
            help="% of plays between midnight and 4 AM",
        )
    with cols[1]:
        st.metric("Top Night Artist", top_artist)
    with cols[2]:
        if session:
            st.metric(
                "Longest Late Session",
                f"{session['track_count']} tracks",
                delta=str(session["start"].date()),
            )
        else:
            st.metric("Longest Late Session", "—")

    with st.expander("Hour-by-hour breakdown & top artists", expanded=False):
        if not hourly.empty:
            hourly_copy = hourly.copy()
            hourly_copy["color"] = hourly_copy["is_late_night"].map(
                {True: ACCENT_INDIGO, False: "rgba(139,148,167,0.35)"}
            )
            fig = go.Figure(
                go.Bar(
                    x=hourly_copy["hour"],
                    y=hourly_copy["plays"],
                    marker_color=hourly_copy["color"].tolist(),
                    hovertemplate="%{x:02d}:00 — %{y} plays<extra></extra>",
                )
            )
            fig = apply_dark_theme(fig)
            fig.update_layout(
                height=260,
                xaxis={"tickmode": "linear", "dtick": 3},
                showlegend=False,
            )
            st.plotly_chart(fig, width="stretch", key="lifestyle_late_hourly")

        # Per-hour tabs (midnight, 1 AM, 2 AM, 3 AM) with top 10 artists and albums
        by_hour = late_data.get("by_hour", {})
        if by_hour:
            hour_labels = [
                f"{'Midnight' if h == 0 else f'{h} AM'} ({by_hour[h]['play_count']:,})"
                for h in range(_LATE_NIGHT_START, _LATE_NIGHT_END)
            ]
            hour_tabs = st.tabs(hour_labels)
            for tab, hour in zip(hour_tabs, range(_LATE_NIGHT_START, _LATE_NIGHT_END)):
                with tab:
                    hd = by_hour[hour]
                    if hd["play_count"] == 0:
                        st.caption("No plays in this hour.")
                        continue
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(
                            f"<span style='color:{ACCENT_INDIGO}; font-weight:600;'>"
                            f"Top Artists</span>",
                            unsafe_allow_html=True,
                        )
                        if not hd["top_artists"].empty:
                            st.dataframe(hd["top_artists"], hide_index=True, width="stretch")
                    with col_b:
                        st.markdown(
                            f"<span style='color:{ACCENT_CYAN}; font-weight:600;'>"
                            f"Top Albums</span>",
                            unsafe_allow_html=True,
                        )
                        if not hd["top_albums"].empty:
                            st.dataframe(hd["top_albums"], hide_index=True, width="stretch")


def _render_years_traditions(holiday_stats: list[dict[str, Any]]) -> None:
    """Render the Year's Traditions section.

    Args:
        holiday_stats: Holiday facet list from ``_compute_holiday_stats``.
    """
    if not holiday_stats:
        st.info(
            "No holiday data available. "
            "Add ``holidays`` entries to your assumptions file to see this section."
        )
        return

    top_holiday = holiday_stats[0]
    total_plays = sum(h["total_plays"] for h in holiday_stats)

    cols = st.columns(3)
    with cols[0]:
        st.metric("Holidays Tracked", f"{len(holiday_stats):,}")
    with cols[1]:
        st.metric("Most Listened", top_holiday["name"])
    with cols[2]:
        sig = top_holiday.get("signature_song") or "—"
        st.metric("#1 Song", sig[:40] + ("…" if len(sig) > 40 else ""))

    with st.expander("Year-over-year plays & full breakdowns", expanded=False):
        st.caption(
            f"Total holiday listens: {total_plays:,} plays across {len(holiday_stats)} holidays."
        )

        # YoY line chart for top 4 holidays
        if holiday_stats:
            frames = []
            for h in holiday_stats[:4]:
                yoy = h["yoy_plays"].copy()
                yoy["holiday"] = h["name"]
                frames.append(yoy)
            combined_yoy = pd.concat(frames, ignore_index=True)
            fig = px.line(
                combined_yoy,
                x="year",
                y="plays",
                color="holiday",
                markers=True,
                color_discrete_sequence=COLORWAY,
                labels={"year": "Year", "plays": "Plays", "holiday": "Holiday"},
            )
            fig = apply_dark_theme(fig)
            fig.update_layout(height=280)
            st.plotly_chart(fig, width="stretch", key="lifestyle_holiday_yoy")

        # Per-holiday tabs: plays, top 10 artists, albums, songs
        holiday_tab_labels = [f"{h['name']} ({h['total_plays']:,})" for h in holiday_stats]
        if holiday_tab_labels:
            holiday_tabs = st.tabs(holiday_tab_labels)
            accent_cycle = [
                ACCENT_INDIGO,
                ACCENT_CYAN,
                ACCENT_ORANGE,
                ACCENT_GREEN,
                ACCENT_PINK,
                ACCENT_YELLOW,
                ACCENT_PURPLE,
            ]
            for tab, h in zip(holiday_tabs, holiday_stats):
                with tab:
                    accent = accent_cycle[holiday_stats.index(h) % len(accent_cycle)]
                    sig = h.get("signature_song") or "—"
                    meta_cols = st.columns(3)
                    meta_cols[0].metric("Total Plays", f"{h['total_plays']:,}")
                    meta_cols[1].metric("Years with Data", h["years_with_data"])
                    meta_cols[2].metric("#1 Song", sig[:35] + ("…" if len(sig) > 35 else ""))

                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        st.markdown(
                            f"<span style='color:{accent}; font-weight:600;'>Top Artists</span>",
                            unsafe_allow_html=True,
                        )
                        if not h["top_artists"].empty:
                            st.dataframe(h["top_artists"], hide_index=True, width="stretch")
                    with col_b:
                        st.markdown(
                            f"<span style='color:{ACCENT_CYAN}; "
                            f"font-weight:600;'>Top Albums</span>",
                            unsafe_allow_html=True,
                        )
                        if not h["top_albums"].empty:
                            st.dataframe(h["top_albums"], hide_index=True, width="stretch")
                    with col_c:
                        st.markdown(
                            f"<span style='color:{ACCENT_GREEN}; "
                            f"font-weight:600;'>Top Songs</span>",
                            unsafe_allow_html=True,
                        )
                        if not h["top_songs"].empty:
                            st.dataframe(h["top_songs"], hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_listening_lifestyle() -> None:
    """Render the Listening Lifestyle multi-facet insights page.

    Reads listening history from ``st.session_state['df']``, Swarm check-ins
    from ``st.session_state['swarm_df']``, and the assumptions file path from
    ``st.session_state['_loaded_config']``.  Shows an empty state when no
    listening data has been loaded.

    All analysis is cached in session state keyed by ``(id(df), id(swarm_df),
    hash(assumptions))``.  UI interactions (expanding sections) never re-trigger
    the computation.
    """
    st.header("Listening Lifestyle")
    st.caption(
        "A portrait of how music fits into the different moments of your life — "
        "your week, your late nights, and your annual traditions."
    )

    df: pd.DataFrame | None = st.session_state.get("df")
    if df is None or df.empty:
        st.info(
            "No music data loaded yet. "
            "Configure a Last.fm source in the sidebar and select a data file."
        )
        return

    _swarm = st.session_state.get("swarm_df")
    swarm_df: pd.DataFrame = _swarm if isinstance(_swarm, pd.DataFrame) else pd.DataFrame()
    loaded_config = st.session_state.get("_loaded_config")
    assumptions_path: str | None = loaded_config[2] if loaded_config else None
    assumptions = load_assumptions(assumptions_path)

    _ll_key = (
        id(df),
        hash(json.dumps(assumptions, sort_keys=True, default=str)),
    )
    if st.session_state.get("_ll_cache_key") != _ll_key:
        with st.spinner("Analysing your listening lifestyle…"):
            _data = _compute_lifestyle_data(df, swarm_df, assumptions)
        st.session_state["_ll_data"] = _data
        st.session_state["_ll_cache_key"] = _ll_key

    data: dict[str, Any] = st.session_state["_ll_data"]

    _render_persona_banner(data)

    st.subheader(":material/calendar_view_week: Your Week")
    _render_your_week(data["week"], data["week_by_day"])

    st.subheader(":material/nights_stay: After Dark")
    _render_after_dark(data["late_night"])

    st.subheader(":material/celebration: Year's Traditions")
    _render_years_traditions(data["holiday"])
