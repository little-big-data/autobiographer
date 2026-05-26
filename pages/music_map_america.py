"""Music Map of America — choropleth scrobble density per US state (issue #57)."""

from __future__ import annotations

import re

import pandas as pd
import plotly.express as px
import streamlit as st

from analysis_utils import get_top_entities
from components.share import render_share_button
from components.theme import SEQUENTIAL_SCALE, apply_dark_theme

# ---------------------------------------------------------------------------
# All valid US state abbreviations (50 states + DC)
# ---------------------------------------------------------------------------

_US_STATE_ABBREVS: frozenset[str] = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
    }
)


_CITY_STATE_RE = re.compile(r",\s*([A-Z]{2})$")

# Full US state/territory names → abbreviations (covers reverse_geocoder admin1 output
# and Foursquare GDPR exports that return the full state name).
_STATE_NAME_TO_ABBREV: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def _extract_state_abbrev(value: str) -> str:
    """Return the US state abbreviation from *value*.

    Handles three formats:
    - Bare abbreviation: ``"IL"``
    - Full state name (from ``reverse_geocoder`` admin1 or Foursquare GDPR export):
      ``"Oklahoma"``, ``"New York"``
    - City-state string (assumptions fallback when no explicit ``state`` key):
      ``"Anchorage, AK"``
    """
    if value in _US_STATE_ABBREVS:
        return value
    lower = value.lower()
    if lower in _STATE_NAME_TO_ABBREV:
        return _STATE_NAME_TO_ABBREV[lower]
    m = _CITY_STATE_RE.search(value)
    if m and m.group(1) in _US_STATE_ABBREVS:
        return m.group(1)
    return value


def _filter_us_states(df: pd.DataFrame) -> pd.DataFrame:
    """Return only rows whose ``state`` column matches a US state abbreviation.

    Normalises ``"City, ST"`` values (common when assumptions entries lack an
    explicit ``state`` key) before filtering, and rewrites the ``state`` column
    so downstream code always sees bare abbreviations.

    Args:
        df: Listening history DataFrame, optionally containing a ``state`` column.

    Returns:
        Filtered DataFrame with only US-state rows, or an empty DataFrame if
        the ``state`` column is absent or no US rows are found.
    """
    if df.empty or "state" not in df.columns:
        return pd.DataFrame()
    normalised = df["state"].astype(str).map(_extract_state_abbrev)
    mask = normalised.isin(_US_STATE_ABBREVS)
    result = df[mask].copy()
    result["state"] = normalised[mask]
    return result


def _build_state_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-state listening statistics.

    For each US state present in *df*, computes:

    - ``plays`` — total scrobble count.
    - ``top_artist`` — most-played artist in the state.
    - ``top_artists_list`` — ordered list of up to 5 top artists (with play counts).
    - ``top_track`` — most-played track name (for hover tooltip).
    - ``top_tracks_list`` — ordered list of up to 5 "Artist — Track (N)" strings.

    Args:
        df: Listening history filtered to US rows (via :func:`_filter_us_states`).

    Returns:
        DataFrame with one row per state, sorted by ``plays`` descending.
        Empty DataFrame when input is empty.
    """
    if df.empty or "state" not in df.columns:
        return pd.DataFrame()

    rows: list[dict] = []
    for state, group in df.groupby("state"):
        plays = len(group)

        top_artists_df = get_top_entities(group, "artist", limit=5)
        top_artist = top_artists_df.iloc[0]["artist"] if not top_artists_df.empty else "—"
        top_artists_list = (
            top_artists_df.apply(lambda r: f"{r['artist']} ({int(r['Plays'])})", axis=1).tolist()
            if not top_artists_df.empty
            else []
        )

        # Top tracks grouped by (artist, track) so each entry carries its artist.
        if "artist" in group.columns and "track" in group.columns:
            track_counts = group.groupby(["artist", "track"]).size().reset_index(name="plays_t")
            track_counts = track_counts.sort_values("plays_t", ascending=False).head(5)
            top_track = track_counts.iloc[0]["track"] if not track_counts.empty else "—"
            top_tracks_list = [
                f"{r['artist']} — {r['track']} ({int(r['plays_t'])})"
                for _, r in track_counts.iterrows()
            ]
        else:
            top_track = "—"
            top_tracks_list = []

        rows.append(
            {
                "state": str(state),
                "plays": plays,
                "top_artist": top_artist,
                "top_artists_list": top_artists_list,
                "top_track": top_track,
                "top_tracks_list": top_tracks_list,
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("plays", ascending=False).reset_index(drop=True)


def _build_share_html(stats: pd.DataFrame, total_plays: int) -> str:
    """Build a minimal HTML snapshot for the share button.

    Args:
        stats: Per-state stats produced by :func:`_build_state_stats`.
        total_plays: Total US scrobble count shown in the snapshot header.

    Returns:
        UTF-8–safe HTML string.
    """
    rows_html = "".join(
        f"<tr><td>{r['state']}</td><td>{r['plays']:,}</td>"
        f"<td>{r['top_artist']}</td>"
        f"<td>{r['top_tracks_list'][0] if r['top_tracks_list'] else '—'}</td></tr>"
        for _, r in stats.iterrows()
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<title>Music Map of America</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0c1120;color:#f0f4ff;padding:2rem}}
h1{{color:#6366f1}}
table{{border-collapse:collapse;width:100%}}
th,td{{text-align:left;padding:.4rem .8rem;border-bottom:1px solid #2d3a52}}
th{{color:#22d3ee}}
</style>
</head>
<body>
<h1>Music Map of America</h1>
<p>{total_plays:,} US scrobbles across {len(stats)} states</p>
<table>
<tr><th>State</th><th>Plays</th><th>Top Artist</th><th>Top Track</th></tr>
{rows_html}
</table>
</body></html>"""


def filter_us_states(df: pd.DataFrame) -> pd.DataFrame:
    """Public alias for :func:`_filter_us_states` (used by geo_explorer)."""
    return _filter_us_states(df)


def build_state_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Public alias for :func:`_build_state_stats` (used by geo_explorer)."""
    return _build_state_stats(df)


def render_music_map_america() -> None:
    """Render the Musical Map of America page.

    Reads the active DataFrame from ``st.session_state['df']``.  Filters to
    rows whose ``state`` column matches a US state abbreviation, then renders:

    1. A Plotly choropleth coloured by scrobble density.
    2. Clicking (selecting) a state shows its top-5 artists and top track.
    3. A sortable table of all visited states with play counts.

    Shows an informational empty state when no data or no US plays are found.
    """
    df: pd.DataFrame | None = st.session_state.get("df")

    if df is None or df.empty:
        st.info(
            "No music data loaded yet. "
            "Configure a Last.fm source in the sidebar and select a data file."
        )
        return

    if "state" not in df.columns:
        st.info(
            "No location data found. "
            "Link a Foursquare/Swarm export so that tracks can be assigned to states."
        )
        return

    us_df = _filter_us_states(df)

    if us_df.empty:
        st.info(
            "No US listening data found. "
            "This map only shows plays assigned to US states via Swarm check-ins "
            "or location assumptions."
        )
        return

    stats = _build_state_stats(us_df)
    total_us_plays = int(stats["plays"].sum())

    st.header("Musical Map of America")

    # Share button
    html_bytes = _build_share_html(stats, total_us_plays).encode("utf-8")
    render_share_button(html_bytes, "autobiographer-music-map-america.html")

    st.markdown(f"**{total_us_plays:,}** US scrobbles tracked across **{len(stats)}** states.")

    # ── Choropleth ────────────────────────────────────────────────────────────
    st.subheader("Scrobble Density by State")

    # Build colour scale list that px.choropleth accepts: [[0.0, "#hex"], ...]
    colorscale = [[v, c] for v, c in SEQUENTIAL_SCALE]

    fig = px.choropleth(
        stats,
        locations="state",
        locationmode="USA-states",
        color="plays",
        scope="usa",
        color_continuous_scale=colorscale,
        labels={"plays": "Scrobbles", "state": "State"},
        hover_data={
            "state": True,
            "plays": True,
            "top_artist": True,
            "top_track": True,
        },
        custom_data=["state", "plays", "top_artist", "top_track"],
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Plays: %{customdata[1]:,}<br>"
            "Top artist: %{customdata[2]}<br>"
            "Top track: %{customdata[3]}<extra></extra>"
        )
    )
    fig.update_layout(
        geo=dict(bgcolor="rgba(0,0,0,0)", lakecolor="rgba(0,0,0,0)"),
        coloraxis_colorbar=dict(title="Plays"),
        margin=dict(l=0, r=0, t=0, b=0),
    )
    apply_dark_theme(fig)
    st.plotly_chart(fig, width="stretch")

    # ── State detail panel ────────────────────────────────────────────────────
    st.subheader("State Detail")
    state_options = ["— select a state —"] + sorted(stats["state"].tolist())
    selected_state = st.selectbox("Select a state", state_options, label_visibility="collapsed")

    if selected_state and selected_state != "— select a state —":
        row = stats.loc[stats["state"] == selected_state].iloc[0]
        col_left, col_right = st.columns(2)
        with col_left:
            st.metric("Total Plays", f"{int(row['plays']):,}")
            st.markdown("**Top 5 Artists**")
            for entry in row["top_artists_list"]:
                st.markdown(f"- {entry}")
        with col_right:
            st.markdown("**Top 5 Tracks**")
            for entry in row["top_tracks_list"]:
                st.markdown(f"- {entry}")

    # ── Sortable state table ──────────────────────────────────────────────────
    st.subheader("All Visited States")
    display_df = stats[["state", "plays", "top_artist", "top_track"]].rename(
        columns={
            "state": "State",
            "plays": "Plays",
            "top_artist": "Top Artist",
            "top_track": "Top Track",
        }
    )
    st.dataframe(display_df, hide_index=True, width="stretch")
