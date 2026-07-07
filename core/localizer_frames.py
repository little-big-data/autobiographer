"""Pure column-shape adapters: broker schema -> legacy lastfm_df/swarm_df shapes.

`LocalizerBroker.get_events_frame()` / `get_places_frame()` (see core/broker.py) return
generic columns (`timestamp, label, sublabel, category, source_id` and `timestamp, lat,
lng, place_name, place_type, source_id` respectively). The rest of the app —
`apply_swarm_offsets()`, `pages/geo_explorer.py`, `pages/places.py` — expects the legacy
Last.fm/Swarm column shapes instead. These two functions bridge that gap.

This module is intentionally Streamlit- and DuckDB-free: it is pure DataFrame-in/
DataFrame-out logic, independently testable with hand-built fixtures, with no coupling
to `LocalizerBroker` or the localizer store layer.
"""

from __future__ import annotations

import pandas as pd

LASTFM_COLUMNS = ["timestamp", "date_text", "artist", "track", "album", "source_id"]
SWARM_COLUMNS = [
    "timestamp",
    "offset",
    "city",
    "state",
    "country",
    "venue",
    "venue_category",
    "lat",
    "lng",
    "event_category",
    "shout",
    "source_id",
]


def events_to_lastfm_frame(events_df: pd.DataFrame) -> pd.DataFrame:
    """Adapt a broker events frame into the legacy lastfm_df column shape.

    Args:
        events_df: DataFrame with columns `timestamp, label, sublabel, category,
            source_id` (the shape returned by `LocalizerBroker.get_events_frame()`).

    Returns:
        DataFrame with columns `timestamp, date_text, artist, track, album, source_id`
        (matching the legacy Last.fm-derived frame shape). `label`/`sublabel`/`category`
        are renamed to `artist`/`track`/`album`; `date_text` is a naive `datetime64[ns]`
        column derived from `timestamp` via `pd.to_datetime(..., unit="s")`. An empty
        input returns an empty frame with exactly these columns, in this order.
    """
    if events_df.empty:
        return pd.DataFrame(columns=LASTFM_COLUMNS)

    result = events_df.rename(columns={"label": "artist", "sublabel": "track", "category": "album"})
    result["date_text"] = pd.to_datetime(events_df["timestamp"], unit="s")
    return result[LASTFM_COLUMNS]


def places_to_swarm_frame(places_df: pd.DataFrame) -> pd.DataFrame:
    """Adapt a broker places frame into the legacy swarm_df column shape.

    Args:
        places_df: DataFrame with columns `timestamp, lat, lng, place_name, place_type,
            source_id` (the shape returned by `LocalizerBroker.get_places_frame()`).

    Returns:
        DataFrame with columns `timestamp, offset, city, state, country, venue,
        venue_category, lat, lng, event_category, shout, source_id`, sorted ascending
        by `timestamp` (required by `apply_swarm_offsets`'s binary search over
        `swarm_df["timestamp"]`). `place_name` is copied into both `city` and `venue`;
        `place_type` is renamed to `venue_category`. `state`, `country`,
        `event_category`, `shout` default to `""` and `offset` defaults to `0`, since
        the DuckDB places schema does not carry these. `source_id` is passed through
        unchanged so downstream consumers can tell which source a row came from.
        `place_name` and `place_type` are dropped — the legacy swarm_df shape has
        neither of those. An empty input returns an empty frame with exactly these
        columns, in this order.
    """
    if places_df.empty:
        return pd.DataFrame(columns=SWARM_COLUMNS)

    result = pd.DataFrame(
        {
            "timestamp": places_df["timestamp"],
            "offset": 0,
            "city": places_df["place_name"],
            "state": "",
            "country": "",
            "venue": places_df["place_name"],
            "venue_category": places_df["place_type"],
            "lat": places_df["lat"],
            "lng": places_df["lng"],
            "event_category": "",
            "shout": "",
            "source_id": places_df["source_id"],
        }
    )
    return result.sort_values("timestamp", ascending=True).reset_index(drop=True)[SWARM_COLUMNS]
