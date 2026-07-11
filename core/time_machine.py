"""Pure "this day in history" data-shaping logic for the Overview page's Time Machine
card (issue #98).

The Overview page already holds two merged DataFrames in session state:

- ``df`` — the Last.fm-shaped "what-when" frame. In legacy (flat-file) mode this is
  Last.fm scrobbles only. In broker mode (``components/sidebar.py::_load_data_from_broker``)
  it is *every* what-when source (Last.fm, Untappd, Flickr, Letterboxd, ...) run through
  ``core.localizer_frames.events_to_lastfm_frame`` and then
  ``analysis_utils.apply_location_context`` — so it carries a ``source_id`` column plus
  ``artist``/``track``/``album`` (renamed from the generic ``label``/``sublabel``/``category``
  columns) *and* the location columns (``city``/``state``/``country``/``lat``/``lng``) that
  the location-context pipeline already resolved for every row's timestamp. When
  ``source_id`` is absent (legacy CSV mode), every row is treated as an actual Last.fm listen.
- ``swarm_df`` — the where-when frame (Foursquare/Swarm, Google Timeline, ...) with
  ``timestamp, city, state, country, venue, venue_category, lat, lng, source_id`` columns.

This module reuses those two shapes directly rather than re-querying the DuckDB store, so
it stays a pure, dependency-free DataFrame-in/dataclass-out module — no Streamlit or DB
imports — mirroring the convention already established by ``core/drinking_history.py`` and
``core/localizer_frames.py``.

Design notes (documented per issue #98's request to record judgment calls):

- "This day in history" matches on **month + day** across all past years present in the
  data, not a single fixed N-years-back offset — a fixed offset would almost always land on
  a day with no data. Every past year with a qualifying record on today's month/day is a
  "candidate year"; one is picked at random (``pick_year``, seeded via an injectable
  ``random.Random`` so callers can make the choice deterministic for tests).
- Location, listening, and events are resolved **independently** — a missing source_id
  column, an empty frame, or no rows on the target date just leaves that field ``None``
  (or an empty tuple for events) rather than suppressing the whole entry.
- Location is read preferentially off the matched Last.fm/events rows (since
  ``apply_location_context`` already resolved the nearest known location for every listen
  timestamp); it falls back to the places/swarm frame's own rows for that date when no
  listen exists but a place record does.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date

import pandas as pd

LASTFM_SOURCE_ID = "lastfm"

# How many sample tracks / events to surface per category, to keep the card compact.
_MAX_SAMPLE_TRACKS = 5
_MAX_EVENTS = 5


@dataclass(frozen=True)
class LocationSnapshot:
    """Where the user was, resolved for a single historical date.

    Attributes:
        city: City name, or "" if unknown.
        state: State/region name, or "" if unknown.
        country: Country name, or "" if unknown.
    """

    city: str
    state: str
    country: str


@dataclass(frozen=True)
class ListeningSnapshot:
    """What the user was listening to, resolved for a single historical date.

    Attributes:
        scrobble_count: Total Last.fm scrobbles on the date.
        top_artist: The most-played artist that date ("" if unknown).
        sample_tracks: Up to ``_MAX_SAMPLE_TRACKS`` distinct "artist — track" strings,
            in listen order.
    """

    scrobble_count: int
    top_artist: str
    sample_tracks: tuple[str, ...]


@dataclass(frozen=True)
class EventSnapshot:
    """A single non-listening EVENTS-shaped record (check-in, photo, drink, ...).

    Attributes:
        label: The event's primary label (e.g. brewery name, photo title).
        sublabel: The event's secondary label (e.g. beer name).
        category: The event's category (e.g. beer style).
        source_id: Which source plugin produced this record (e.g. "untappd").
    """

    label: str
    sublabel: str
    category: str
    source_id: str


@dataclass(frozen=True)
class TimeMachineEntry:
    """A fully-resolved "this day in history" result for one historical date.

    Attributes:
        target_date: The historical date this entry describes.
        years_ago: How many years before ``today`` ``target_date`` falls.
        location: Where the user was, or None if unknown.
        listening: What the user was listening to, or None if no scrobbles that date.
        events: Non-listening EVENTS-shaped records that date (possibly empty).
    """

    target_date: date
    years_ago: int
    location: LocationSnapshot | None
    listening: ListeningSnapshot | None
    events: tuple[EventSnapshot, ...]


def candidate_years(today: date, activity_df: pd.DataFrame, places_df: pd.DataFrame) -> list[int]:
    """Return distinct past years with at least one record on today's month/day.

    Args:
        today: The reference "today" date (month/day drive the match).
        activity_df: The Last.fm-shaped what-when frame (``df`` in session state).
            Must have a ``date_text`` column to contribute; missing/empty is fine.
        places_df: The where-when frame (``swarm_df`` in session state). Must have a
            ``timestamp`` column (unix seconds) to contribute; missing/empty is fine.

    Returns:
        Sorted (descending) list of years strictly before ``today.year`` that have at
        least one matching row in either frame. Empty list if nothing matches.
    """
    years: set[int] = set()

    if activity_df is not None and not activity_df.empty and "date_text" in activity_df.columns:
        dates = pd.to_datetime(activity_df["date_text"])
        mask = (
            (dates.dt.month == today.month)
            & (dates.dt.day == today.day)
            & (dates.dt.year < today.year)
        )
        years.update(int(y) for y in dates[mask].dt.year.unique().tolist())

    if places_df is not None and not places_df.empty and "timestamp" in places_df.columns:
        place_dates = pd.to_datetime(places_df["timestamp"], unit="s")
        place_mask = (
            (place_dates.dt.month == today.month)
            & (place_dates.dt.day == today.day)
            & (place_dates.dt.year < today.year)
        )
        years.update(int(y) for y in place_dates[place_mask].dt.year.unique().tolist())

    return sorted(years, reverse=True)


def pick_year(years: list[int], rng: random.Random | None = None) -> int | None:
    """Pick one candidate year at random.

    Args:
        years: Candidate years, as returned by ``candidate_years``.
        rng: A ``random.Random`` instance to draw from. Pass a seeded instance for
            deterministic tests; defaults to a fresh, unseeded ``random.Random()``
            (real wall-clock randomness) when omitted.

    Returns:
        One of ``years``, chosen at random, or None if ``years`` is empty.
    """
    if not years:
        return None
    # Not a cryptographic use — just picking which past year's card to display.
    chooser = rng if rng is not None else random.Random()  # noqa: S311
    return chooser.choice(years)


def _rows_on_date(
    df: pd.DataFrame, date_col: str, target_date: date, unit: str | None
) -> pd.DataFrame:
    """Return the subset of `df` whose `date_col` falls on `target_date`."""
    if df is None or df.empty or date_col not in df.columns:
        return pd.DataFrame(columns=df.columns if df is not None else [])
    dates = pd.to_datetime(df[date_col], unit=unit) if unit else pd.to_datetime(df[date_col])
    return df[dates.dt.date == target_date]


def _location_from_rows(
    rows: pd.DataFrame, name_cols: tuple[str, str, str]
) -> LocationSnapshot | None:
    """Build a LocationSnapshot from the first row with a non-empty city/state/country."""
    city_col, state_col, country_col = name_cols
    if rows.empty or not {city_col, state_col, country_col}.issubset(rows.columns):
        return None
    row = rows.iloc[0]
    city = str(row.get(city_col) or "")
    state = str(row.get(state_col) or "")
    country = str(row.get(country_col) or "")
    if not (city or state or country):
        return None
    return LocationSnapshot(city=city, state=state, country=country)


def _listening_snapshot(rows: pd.DataFrame) -> ListeningSnapshot | None:
    """Build a ListeningSnapshot from Last.fm-only rows for a single date."""
    if rows.empty or "artist" not in rows.columns:
        return None

    top_artist = ""
    counts = rows["artist"].dropna()
    if not counts.empty:
        top_artist = str(counts.value_counts().idxmax())

    sample: list[str] = []
    for _, row in rows.iterrows():
        if len(sample) >= _MAX_SAMPLE_TRACKS:
            break
        artist = str(row.get("artist") or "")
        track = str(row.get("track") or "")
        label = f"{artist} — {track}" if artist and track else artist or track
        if label and label not in sample:
            sample.append(label)

    return ListeningSnapshot(
        scrobble_count=len(rows),
        top_artist=top_artist,
        sample_tracks=tuple(sample),
    )


def _event_snapshots(rows: pd.DataFrame) -> tuple[EventSnapshot, ...]:
    """Build EventSnapshots from non-Last.fm activity rows for a single date."""
    if rows.empty:
        return ()

    events: list[EventSnapshot] = []
    for _, row in rows.iterrows():
        if len(events) >= _MAX_EVENTS:
            break
        events.append(
            EventSnapshot(
                label=str(row.get("artist") or ""),
                sublabel=str(row.get("track") or ""),
                category=str(row.get("album") or ""),
                source_id=str(row.get("source_id") or ""),
            )
        )
    return tuple(events)


def build_entry(
    today: date,
    year: int,
    activity_df: pd.DataFrame,
    places_df: pd.DataFrame,
) -> TimeMachineEntry:
    """Build a fully-resolved TimeMachineEntry for a specific historical year.

    Args:
        today: The reference "today" date (month/day are combined with ``year``).
        year: The historical year to build an entry for (must be < today.year).
        activity_df: The Last.fm-shaped what-when frame (``df`` in session state).
        places_df: The where-when frame (``swarm_df`` in session state).

    Returns:
        A TimeMachineEntry. Each of ``location``/``listening``/``events`` is
        independently None/empty when that category has no data for the date.
    """
    target_date = date(year, today.month, today.day)

    activity_rows = _rows_on_date(activity_df, "date_text", target_date, unit=None)

    if "source_id" in activity_rows.columns:
        listening_rows = activity_rows[activity_rows["source_id"] == LASTFM_SOURCE_ID]
        event_rows = activity_rows[activity_rows["source_id"] != LASTFM_SOURCE_ID]
    else:
        listening_rows = activity_rows
        event_rows = activity_rows.iloc[0:0]

    places_rows = _rows_on_date(places_df, "timestamp", target_date, unit="s")

    location = _location_from_rows(listening_rows, ("city", "state", "country"))
    if location is None:
        location = _location_from_rows(places_rows, ("city", "state", "country"))
        if location is None and not places_rows.empty and "venue" in places_rows.columns:
            venue = str(places_rows.iloc[0].get("venue") or "")
            if venue:
                location = LocationSnapshot(city=venue, state="", country="")

    return TimeMachineEntry(
        target_date=target_date,
        years_ago=today.year - year,
        location=location,
        listening=_listening_snapshot(listening_rows),
        events=_event_snapshots(event_rows),
    )


def get_time_machine_entry(
    today: date,
    activity_df: pd.DataFrame,
    places_df: pd.DataFrame,
    rng: random.Random | None = None,
) -> TimeMachineEntry | None:
    """Pick a random past "this day in history" and build its TimeMachineEntry.

    This is the top-level entry point: find every past year with a matching record on
    today's month/day, pick one at random, and shape its location/listening/events data.

    Args:
        today: The reference "today" date.
        activity_df: The Last.fm-shaped what-when frame (``df`` in session state).
        places_df: The where-when frame (``swarm_df`` in session state).
        rng: A ``random.Random`` instance for deterministic year selection in tests.

    Returns:
        A TimeMachineEntry for a randomly-chosen candidate year, or None if there is no
        historical data at all for today's month/day (the caller should show an
        empty-state message in that case).
    """
    years = candidate_years(today, activity_df, places_df)
    year = pick_year(years, rng)
    if year is None:
        return None
    return build_entry(today, year, activity_df, places_df)
