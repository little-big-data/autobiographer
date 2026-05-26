"""Narrative text generation engine for Autobiographer.

Pure text functions — no ``st.*`` calls. Fully typed with Google-style docstrings.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Individual narrative functions
# ---------------------------------------------------------------------------


def narrative_artist_relationship(arc: dict[str, Any]) -> str:
    """Generate a narrative sentence or paragraph about a listener's relationship with an artist.

    Args:
        arc: Artist arc dict with keys: artist, arc_type, discovery_date, peak_month,
             last_play, total_plays, peak_plays, peak_ratio.

    Returns:
        A natural-language narrative string describing the relationship.
    """
    artist: str = arc.get("artist", "this artist")
    arc_type: str = arc.get("arc_type", "other")
    discovery_date: Any = arc.get("discovery_date")
    peak_month: Any = arc.get("peak_month")
    last_play: Any = arc.get("last_play")
    total_plays: int = int(arc.get("total_plays", 0))
    peak_plays: int = int(arc.get("peak_plays", 0))

    def _fmt_date(ts: Any) -> str:
        if isinstance(ts, pd.Timestamp):
            return str(ts.strftime("%B %Y"))
        return str(ts)

    if arc_type == "obsession":
        disc = _fmt_date(discovery_date)
        peak = _fmt_date(peak_month)
        last = _fmt_date(last_play)
        return (
            f"You first discovered {artist} around {disc}, and what followed was an intense "
            f"obsession. Plays peaked in {peak} with {peak_plays} listens that month alone — "
            f"a level of focus that left little room for anything else. "
            f"After that peak the plays faded into silence, with your last listen logged in {last}."
        )

    if arc_type == "perennial":
        disc = _fmt_date(discovery_date)
        last = _fmt_date(last_play)
        return (
            f"You discovered {artist} back in {disc}, and you have never stopped listening. "
            f"Across the years they have been a consistently reliable presence in your rotation — "
            f"still appearing through {last} with {total_plays} total plays. "
            f"Perennial artists like this are the backbone of a listening identity."
        )

    if arc_type == "rediscovery":
        disc = _fmt_date(discovery_date)
        last = _fmt_date(last_play)
        return (
            f"You first came across {artist} in {disc}, then life moved on and the listens "
            f"dropped away for a stretch. "
            f"But something brought you back — and by {last} they were part of the rotation again. "
            f"Rediscoveries like this often feel more meaningful than the first listen."
        )

    if arc_type == "one-hit":
        disc = _fmt_date(discovery_date)
        return (
            f"You discovered {artist} around {disc} and had a brief but intense period of "
            f"listening. The plays were concentrated into just a few months "
            f"— {total_plays} total — before you moved on. A passing infatuation."
        )

    # "other" / fallback
    return (
        f"You have {total_plays} plays of {artist} spread across your listening history. "
        f"They occupy a quiet corner of your musical world."
    )


def narrative_year_in_review(df: pd.DataFrame, year: int) -> str:
    """Generate a year-in-review paragraph for the given calendar year.

    Args:
        df: Full listening history DataFrame with ``timestamp`` (unix seconds) column.
        year: Calendar year to review.

    Returns:
        A 2–3 sentence narrative string mentioning the year, top artist, and peak month.
        Returns a graceful 'quiet year' sentence if there are no plays for that year.
    """
    if df.empty or "timestamp" not in df.columns:
        return f"{year} was a quiet year in your listening history — no plays recorded."

    year_df = df[pd.to_datetime(df["timestamp"], unit="s").dt.year == year]

    if year_df.empty:
        return f"{year} was a quiet year in your listening history — no plays recorded."

    total_plays: int = len(year_df)

    # Top artist
    top_artist_series = year_df.groupby("artist").size().sort_values(ascending=False)
    top_artist: str = str(top_artist_series.index[0]) if len(top_artist_series) > 0 else "Unknown"

    # Most active month
    months = pd.to_datetime(year_df["timestamp"], unit="s").dt.month
    month_counts = months.value_counts()
    peak_month_num: int = int(month_counts.index[0]) if len(month_counts) > 0 else 1
    peak_month_name: str = pd.Timestamp(f"{year}-{peak_month_num:02d}-01").strftime("%B")

    return (
        f"In {year} you logged {total_plays} plays, with {top_artist} topping your charts "
        f"as the most-listened-to artist of the year. "
        f"Your most active month was {peak_month_name}, when your listening really hit its stride. "
        f"It was a year worth remembering."
    )


def narrative_city_soundtrack(soundtrack: dict[str, Any]) -> str:
    """Generate a narrative sentence about the music associated with a city.

    Args:
        soundtrack: Dict with keys: city (str), top_artists (list of dicts or DataFrame
                    with artist col), play_count (int).

    Returns:
        A natural-language sentence mentioning the city name.
    """
    city: str = soundtrack.get("city", "this city")
    play_count: int = int(soundtrack.get("play_count", 0))
    top_artists_raw: Any = soundtrack.get("top_artists", [])

    # Resolve top artist name from either a DataFrame or a list of dicts
    top_artist_name: str = ""
    if isinstance(top_artists_raw, pd.DataFrame):
        if not top_artists_raw.empty and "artist" in top_artists_raw.columns:
            top_artist_name = str(top_artists_raw.iloc[0]["artist"])
    elif isinstance(top_artists_raw, list) and top_artists_raw:
        first = top_artists_raw[0]
        if isinstance(first, dict):
            top_artist_name = str(first.get("artist", ""))

    if top_artist_name:
        return (
            f"During your time in {city} your listening logged {play_count} plays, "
            f"with {top_artist_name} soundtracking the experience more than anyone else."
        )
    return (
        f"During your time in {city} your listening logged {play_count} plays — "
        f"a sonic snapshot of that chapter in your life."
    )


def narrative_era_comparison(
    era_tops: dict[str, pd.DataFrame],
    jaccard: pd.DataFrame,
    era_a: str,
    era_b: str,
) -> str:
    """Generate a narrative comparing the musical overlap between two listening eras.

    Args:
        era_tops: Mapping of era label → DataFrame of top artists with ``artist`` column.
        jaccard: Square DataFrame of pairwise Jaccard similarity indexed by era label.
        era_a: First era label.
        era_b: Second era label.

    Returns:
        A paragraph mentioning both era labels and the overlap percentage.
    """
    # Compute overlap percentage
    overlap_pct: float = 0.0
    try:
        if era_a in jaccard.index and era_b in jaccard.columns:
            overlap_pct = float(jaccard.loc[era_a, era_b]) * 100
    except (KeyError, TypeError, ValueError):
        pass

    overlap_str = f"{overlap_pct:.0f}%"

    # Find artists exclusive to era_a (appear in era_a but not era_b)
    artists_a: set[str] = set()
    artists_b: set[str] = set()
    if era_a in era_tops and not era_tops[era_a].empty and "artist" in era_tops[era_a].columns:
        artists_a = set(era_tops[era_a]["artist"].tolist())
    if era_b in era_tops and not era_tops[era_b].empty and "artist" in era_tops[era_b].columns:
        artists_b = set(era_tops[era_b]["artist"].tolist())

    exclusive_a = list(artists_a - artists_b)
    exclusive_b = list(artists_b - artists_a)

    parts: list[str] = [
        f"Comparing your {era_a} era to your {era_b} era, "
        f"you carried about {overlap_str} of your favourite artists across the transition."
    ]

    if exclusive_a:
        sample_a = ", ".join(exclusive_a[:3])
        parts.append(f"Artists like {sample_a} were distinctly part of the {era_a} chapter.")

    if exclusive_b:
        sample_b = ", ".join(exclusive_b[:3])
        parts.append(f"Meanwhile {sample_b} emerged as defining sounds of {era_b}.")

    if not exclusive_a and not exclusive_b:
        parts.append(
            f"The musical DNA of {era_a} and {era_b} overlapped considerably, "
            "suggesting continuity rather than a sharp break."
        )

    return " ".join(parts)


def narrative_life_event(event: dict[str, Any]) -> str:
    """Generate a narrative sentence about a detected life event or listening change.

    Args:
        event: Dict with keys: date (Timestamp or str), type, context.

    Returns:
        A sentence mentioning the month and/or year from the date, and the context if present.
    """
    raw_date: Any = event.get("date")
    event_type: str = str(event.get("type", "change"))
    context: str = str(event.get("context", "")).strip()

    # Parse date
    month_str: str = ""
    year_str: str = ""
    try:
        if isinstance(raw_date, pd.Timestamp):
            ts = raw_date
        else:
            ts = pd.Timestamp(str(raw_date))
        month_str = ts.strftime("%B")
        year_str = str(ts.year)
    except (ValueError, TypeError):
        pass

    if month_str and year_str:
        date_phrase = f"in {month_str} {year_str}"
    elif year_str:
        date_phrase = f"in {year_str}"
    else:
        date_phrase = "at some point"

    if event_type == "changepoint":
        base = (
            f"Something shifted in your listening {date_phrase} "
            "— a changepoint your data picked up."
        )
    elif event_type == "taste_shift":
        base = f"Your musical tastes underwent a notable shift {date_phrase}."
    else:
        base = f"A significant moment in your listening journey occurred {date_phrase}."

    if context:
        return f"{base} {context}."

    return base


# ---------------------------------------------------------------------------
# Autobiography orchestrator
# ---------------------------------------------------------------------------


def generate_full_autobiography(
    df: pd.DataFrame,
    assumptions: dict[str, Any],
    swarm_df: pd.DataFrame | None = None,
) -> str:
    """Orchestrate all narrative functions into a multi-section Markdown document.

    Args:
        df: Full listening history DataFrame.
        assumptions: User assumptions dict with residency, trips, holidays, defaults.
        swarm_df: Optional Swarm check-in DataFrame (may be None).

    Returns:
        A Markdown string with ``##`` section headers. Returns a graceful fallback
        string with a ``##`` header when ``df`` is empty.
    """
    if df is None or df.empty:
        return (
            "## Your Musical Story\n\n"
            "No listening data found. Load your Last.fm history and try again — "
            "your story is waiting to be told."
        )

    sections: list[str] = []

    # ---- Overview ----
    try:
        total_plays: int = len(df)
        unique_artists: int = df["artist"].nunique() if "artist" in df.columns else 0
        years: list[int] = []
        if "timestamp" in df.columns:
            years = sorted(pd.to_datetime(df["timestamp"], unit="s").dt.year.unique().tolist())
        year_range: str = (
            f"{years[0]}–{years[-1]}" if len(years) >= 2 else str(years[0]) if years else "unknown"
        )
        overview = (
            f"## Overview\n\n"
            f"Your listening history spans {year_range}, with {total_plays:,} plays "
            f"across {unique_artists:,} unique artists. "
            "This is the story that data tells."
        )
    except Exception:  # noqa: BLE001
        overview = "## Overview\n\nYour listening history tells a rich and varied story."

    sections.append(overview)

    # ---- Your Artists ----
    try:
        artists_section_lines: list[str] = ["## Your Artists\n"]
        if "artist" in df.columns:
            top = df.groupby("artist").size().sort_values(ascending=False).head(3)
            for rank, (artist, count) in enumerate(top.items(), 1):
                artists_section_lines.append(f"{rank}. **{artist}** — {count:,} plays")
        sections.append("\n".join(artists_section_lines))
    except Exception:  # noqa: BLE001
        sections.append("## Your Artists\n\nYou have listened to a wide variety of artists.")

    # ---- Your Places ----
    try:
        residency: list[dict[str, Any]] = assumptions.get("residency", [])
        places_lines: list[str] = ["## Your Places\n"]
        for era in residency[:3]:
            city: str = str(era.get("city", "Unknown"))
            start: str = str(era.get("start", ""))[:4]
            end: str = str(era.get("end", ""))[:4]
            places_lines.append(f"- **{city}** ({start}–{end})")
        if not residency:
            places_lines.append("Your listening history spans many places.")
        sections.append("\n".join(places_lines))
    except Exception:  # noqa: BLE001
        sections.append("## Your Places\n\nYour music followed you wherever you went.")

    # ---- Life Events ----
    try:
        import analysis_utils  # noqa: PLC0415

        changepoints = analysis_utils.load_deep_life_events_cache()
        events_lines: list[str] = ["## Life Events\n"]
        if changepoints and isinstance(changepoints, dict):
            events: list[dict[str, Any]] = changepoints.get("events", [])
            for ev in events[:3]:
                narrative_text = narrative_life_event(ev)
                events_lines.append(f"- {narrative_text}")
            if len(events_lines) == 1:
                events_lines.append("No significant events detected yet.")
        else:
            events_lines.append(
                "Run **Calculate All Deep Analyses** to detect life events from your data."
            )
        sections.append("\n".join(events_lines))
    except Exception:  # noqa: BLE001
        sections.append("## Life Events\n\nYour listening data holds many stories.")

    return "\n\n".join(sections)
