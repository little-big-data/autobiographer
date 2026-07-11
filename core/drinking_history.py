"""Pure Untappd check-in shaping helpers for the Drinking History page (issue #124).

``UntappdPlugin`` (packages/localizer/src/localizer/plugins/untappd/loader.py) emits
beer check-ins as ``OutputTable.EVENTS`` rows: ``label``/``sublabel``/``category`` hold
``brewery_name``/``beer_name``/``beer_type``, while ``rating_score``/``venue_name``/
``venue_lat``/``venue_lng`` live only inside ``raw_json`` (the events table has no
lat/lng columns of its own). ``pages/beer.py`` needs those ``raw_json`` fields, which
``LocalizerBroker.get_events_frame()`` does not expose — so this module works from a
raw events frame (``timestamp, label, sublabel, category, raw_json, source_id``)
fetched directly via ``LocalizerStore.query_events(include_raw_json=True)``.

This module is intentionally Streamlit- and DuckDB-free: it is pure DataFrame-in/
DataFrame-out logic, independently testable with hand-built fixtures, mirroring the
convention already established by ``core/localizer_frames.py`` and
``core/source_filter.py``.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

UNTAPPD_SOURCE_ID = "untappd"

CHECKIN_COLUMNS = [
    "timestamp",
    "date",
    "brewery",
    "beer",
    "style",
    "rating",
    "venue_name",
    "venue_lat",
    "venue_lng",
]


def _parse_raw_json(raw: Any) -> dict[str, Any]:
    """Parse a raw_json cell into a dict, tolerating dicts, JSON strings, or None.

    Args:
        raw: The raw_json value as stored/queried — may already be a dict (e.g. in
            hand-built test fixtures), a JSON string (as returned by DuckDB), or
            None/NaN.

    Returns:
        A dict. Unparseable or missing values return an empty dict rather than
        raising, so a single malformed row never crashes the page.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_checkins_frame(events_df: pd.DataFrame) -> pd.DataFrame:
    """Shape a raw events frame into an Untappd check-ins frame.

    Args:
        events_df: DataFrame with columns ``timestamp, label, sublabel, category,
            raw_json`` and, optionally, ``source_id``. When ``source_id`` is
            present, rows are filtered to ``source_id == "untappd"``; when absent,
            every row is treated as already-filtered Untappd data.

    Returns:
        DataFrame with columns ``timestamp, date, brewery, beer, style, rating,
        venue_name, venue_lat, venue_lng``, sorted ascending by ``timestamp``.
        ``rating``/``venue_lat``/``venue_lng`` are floats (``NaN`` when absent from
        ``raw_json``). Empty/missing input returns an empty frame with exactly
        these columns.
    """
    if events_df is None or events_df.empty:
        return pd.DataFrame(columns=CHECKIN_COLUMNS)

    subset = events_df
    if "source_id" in subset.columns:
        subset = subset[subset["source_id"] == UNTAPPD_SOURCE_ID]

    if subset.empty:
        return pd.DataFrame(columns=CHECKIN_COLUMNS)

    if "raw_json" in subset.columns:
        raw_dicts = [_parse_raw_json(raw) for raw in subset["raw_json"]]
    else:
        raw_dicts = [{} for _ in range(len(subset))]

    result = pd.DataFrame(
        {
            "timestamp": subset["timestamp"].astype(int).to_numpy(),
            "brewery": subset["label"].fillna("").to_numpy(),
            "beer": subset["sublabel"].fillna("").to_numpy(),
            "style": subset["category"].fillna("").to_numpy(),
            "rating": [d.get("rating") for d in raw_dicts],
            "venue_name": [d.get("venue_name") or "" for d in raw_dicts],
            "venue_lat": [d.get("venue_lat") for d in raw_dicts],
            "venue_lng": [d.get("venue_lng") for d in raw_dicts],
        }
    )
    result["rating"] = pd.to_numeric(result["rating"], errors="coerce")
    result["venue_lat"] = pd.to_numeric(result["venue_lat"], errors="coerce")
    result["venue_lng"] = pd.to_numeric(result["venue_lng"], errors="coerce")
    result["date"] = pd.to_datetime(result["timestamp"], unit="s")

    return result.sort_values("timestamp").reset_index(drop=True)[CHECKIN_COLUMNS]


def top_breweries(checkins_df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Return the most-visited breweries by check-in count.

    Args:
        checkins_df: A checkins frame as returned by ``build_checkins_frame``.
        top_n: Maximum number of breweries to return.

    Returns:
        DataFrame with columns ``[brewery, checkins]``, sorted descending by
        ``checkins``. Empty input (or a frame missing the ``brewery`` column)
        returns an empty frame with these columns.
    """
    if checkins_df is None or checkins_df.empty or "brewery" not in checkins_df.columns:
        return pd.DataFrame(columns=["brewery", "checkins"])

    named = checkins_df[checkins_df["brewery"] != ""]
    if named.empty:
        return pd.DataFrame(columns=["brewery", "checkins"])

    counts = named.groupby("brewery").size().reset_index(name="checkins")
    return counts.sort_values("checkins", ascending=False).head(top_n).reset_index(drop=True)


def top_styles(checkins_df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Return the most-checked-in beer styles by check-in count.

    Args:
        checkins_df: A checkins frame as returned by ``build_checkins_frame``.
        top_n: Maximum number of styles to return.

    Returns:
        DataFrame with columns ``[style, checkins]``, sorted descending by
        ``checkins``. Empty input (or a frame missing the ``style`` column)
        returns an empty frame with these columns.
    """
    if checkins_df is None or checkins_df.empty or "style" not in checkins_df.columns:
        return pd.DataFrame(columns=["style", "checkins"])

    named = checkins_df[checkins_df["style"] != ""]
    if named.empty:
        return pd.DataFrame(columns=["style", "checkins"])

    counts = named.groupby("style").size().reset_index(name="checkins")
    return counts.sort_values("checkins", ascending=False).head(top_n).reset_index(drop=True)


def rating_trend(checkins_df: pd.DataFrame) -> pd.DataFrame:
    """Compute the monthly average rating trend from rated check-ins.

    Args:
        checkins_df: A checkins frame as returned by ``build_checkins_frame``.

    Returns:
        DataFrame with columns ``[month, avg_rating, rated_checkins]``, one row
        per calendar month that has at least one rated check-in, sorted
        ascending by ``month``. Unrated check-ins (``rating`` is ``NaN``) are
        excluded from both the average and the count. Empty input, a frame
        missing the ``rating``/``date`` columns, or a frame with no rated
        check-ins at all returns an empty frame with these columns.
    """
    columns = ["month", "avg_rating", "rated_checkins"]
    if checkins_df is None or checkins_df.empty:
        return pd.DataFrame(columns=columns)
    if "rating" not in checkins_df.columns or "date" not in checkins_df.columns:
        return pd.DataFrame(columns=columns)

    rated = checkins_df.dropna(subset=["rating"])
    if rated.empty:
        return pd.DataFrame(columns=columns)

    rated = rated.assign(month=rated["date"].dt.to_period("M").dt.to_timestamp())
    trend = rated.groupby("month")["rating"].agg(["mean", "count"]).reset_index()
    trend.columns = columns
    return trend.sort_values("month").reset_index(drop=True)


def rating_distribution(checkins_df: pd.DataFrame) -> pd.DataFrame:
    """Compute the count of check-ins at each distinct rating value.

    Args:
        checkins_df: A checkins frame as returned by ``build_checkins_frame``.

    Returns:
        DataFrame with columns ``[rating, checkins]``, one row per distinct
        rating value present, sorted ascending by ``rating``. Unrated check-ins
        are excluded. Empty input, or a frame with no rated check-ins, returns
        an empty frame with these columns.
    """
    columns = ["rating", "checkins"]
    if checkins_df is None or checkins_df.empty or "rating" not in checkins_df.columns:
        return pd.DataFrame(columns=columns)

    rated = checkins_df.dropna(subset=["rating"])
    if rated.empty:
        return pd.DataFrame(columns=columns)

    counts = rated["rating"].value_counts().sort_index().reset_index()
    counts.columns = columns
    return counts


def checkins_with_venue(checkins_df: pd.DataFrame) -> pd.DataFrame:
    """Filter check-ins down to those with known venue coordinates, for map display.

    Args:
        checkins_df: A checkins frame as returned by ``build_checkins_frame``.

    Returns:
        The subset of rows where both ``venue_lat`` and ``venue_lng`` are
        present, with a reset index. Empty input, or a frame missing either
        column, returns an empty frame (preserving ``checkins_df``'s columns
        when present).
    """
    if checkins_df is None or checkins_df.empty:
        return pd.DataFrame(columns=CHECKIN_COLUMNS)
    if "venue_lat" not in checkins_df.columns or "venue_lng" not in checkins_df.columns:
        return pd.DataFrame(columns=checkins_df.columns)

    return checkins_df.dropna(subset=["venue_lat", "venue_lng"]).reset_index(drop=True)
