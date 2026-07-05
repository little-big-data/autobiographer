"""Parser for the Google Maps Timeline (new on-device) location export.

Verbatim (behavior-identical) port of ``analysis_utils.load_google_timeline()``
and its four private dependents (``_TIMELINE_SEMANTIC_LABELS``,
``_WHERE_WHEN_COLUMNS``, ``_parse_latlng``, ``_timeline_offset_minutes``).
This lets the localizer-side ``GoogleTimelinePlugin`` parse ``Timeline.json``
exports without depending on the top-level app's ``analysis_utils`` module
being importable (see ``analysis_utils.py``, which re-exports the three
publicly-referenced names from here as a shim).
"""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

# Human-readable names for Google Timeline visit semantic types.
_TIMELINE_SEMANTIC_LABELS = {
    "HOME": "Home",
    "WORK": "Work",
    "INFERRED_WORK": "Work (inferred)",
    "UNKNOWN": "Unknown place",
}

# Column schema shared with load_swarm_data so the two frames concatenate cleanly.
_WHERE_WHEN_COLUMNS = [
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
]


def _parse_latlng(raw: str) -> tuple[float, float] | None:
    """Parse a Google Timeline lat/lng string such as ``"41.96°, -87.70°"``.

    Args:
        raw: Coordinate string with degree symbols, comma-separated.

    Returns:
        ``(lat, lng)`` as floats, or None if the string cannot be parsed.
    """
    if not raw:
        return None
    try:
        parts = raw.replace("°", "").split(",")
        if len(parts) != 2:
            return None
        return float(parts[0].strip()), float(parts[1].strip())
    except (ValueError, AttributeError):
        return None


def _timeline_offset_minutes(segment: dict[str, Any], start_dt: pd.Timestamp) -> int:
    """Return the UTC offset in minutes for a Google Timeline segment.

    Prefers the explicit ``startTimeTimezoneUtcOffsetMinutes`` field, then the
    offset embedded in the parsed RFC3339 ``startTime``, defaulting to 0.

    Args:
        segment: A single ``semanticSegments`` entry.
        start_dt: The segment's ``startTime`` parsed to a tz-aware Timestamp.

    Returns:
        Offset from UTC in minutes.
    """
    raw = segment.get("startTimeTimezoneUtcOffsetMinutes")
    if raw is not None:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass
    utc_offset = start_dt.utcoffset() if start_dt is not None else None
    if utc_offset is not None:
        return int(utc_offset.total_seconds() // 60)
    return 0


def load_google_timeline(path: str) -> pd.DataFrame:
    """Load and normalize a Google Maps Timeline (new on-device) location export.

    Parses the modern single-file ``Timeline.json`` export, whose top-level
    ``semanticSegments`` array holds ``visit`` (place stays) and ``activity``
    (movements) records. Emits the same column schema as ``load_swarm_data``
    so the result concatenates into the app's location frame and flows through the
    timezone/offset join and every map/geo view. Raw ``timelinePath`` GPS segments
    are ignored (noisy). Makes no network calls; ``city``/``state``/``country`` are
    filled offline via the optional ``reverse_geocoder`` dataset when installed.

    Args:
        path: Path to a Google Timeline ``Timeline.json`` file.

    Returns:
        DataFrame with the columns listed in ``_WHERE_WHEN_COLUMNS``, sorted by
        ``timestamp`` and de-duplicated on it. Empty (with those columns) when the
        file is missing or contains no visits/activities.

    Raises:
        ValueError: If the file is not the new Timeline.json format (no top-level
            ``semanticSegments`` key) — e.g. a legacy ``Records.json`` or Semantic
            Location History export.
    """
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=_WHERE_WHEN_COLUMNS)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or "semanticSegments" not in data:
        raise ValueError(
            "Unsupported Google location file: expected the new on-device "
            "'Timeline.json' export with a top-level 'semanticSegments' array. "
            "Legacy 'Records.json' / Semantic Location History exports are not supported."
        )

    # placeId -> human label, from the frequent-places profile (used to name visits).
    place_labels: dict[str, str] = {}
    profile = data.get("userLocationProfile") or {}
    for freq in profile.get("frequentPlaces") or []:
        pid = freq.get("placeId")
        label = freq.get("label")
        if pid and label:
            place_labels[pid] = label

    rows: list[dict[str, Any]] = []
    for seg in data.get("semanticSegments") or []:
        start = seg.get("startTime")
        if not start:
            continue
        try:
            start_dt = pd.to_datetime(start)
            ts = int(start_dt.timestamp())
        except (ValueError, TypeError):
            continue
        offset = _timeline_offset_minutes(seg, start_dt)

        if "visit" in seg:
            top = (seg.get("visit") or {}).get("topCandidate") or {}
            coords = _parse_latlng((top.get("placeLocation") or {}).get("latLng", ""))
            if coords is None:
                continue
            semantic_type = top.get("semanticType") or "UNKNOWN"
            place_id = top.get("placeId", "")
            venue = place_labels.get(place_id) or _TIMELINE_SEMANTIC_LABELS.get(
                semantic_type, semantic_type.replace("_", " ").title()
            )
            venue_category = semantic_type.lower()
        elif "activity" in seg:
            activity = seg.get("activity") or {}
            coords = _parse_latlng((activity.get("start") or {}).get("latLng", ""))
            if coords is None:
                continue
            act_type = (activity.get("topCandidate") or {}).get("type") or "UNKNOWN"
            venue = act_type.replace("_", " ").capitalize()
            venue_category = "activity:" + act_type.lower()
        else:
            continue

        lat, lng = coords
        rows.append(
            {
                "timestamp": ts,
                "offset": offset,
                "city": "Unknown",
                "state": "Unknown",
                "country": "Unknown",
                "venue": venue,
                "venue_category": venue_category,
                "lat": lat,
                "lng": lng,
                "event_category": "",
                "shout": "",
            }
        )

    if not rows:
        return pd.DataFrame(columns=_WHERE_WHEN_COLUMNS)

    df = pd.DataFrame(rows)

    # Offline reverse-geocode every row from lat/lng — no network. Mirrors the
    # optional-dependency pattern in load_swarm_data; degrades to "Unknown".
    try:
        import reverse_geocoder as rg  # optional dependency  # noqa: PLC0415

        coords_list = list(zip(df["lat"], df["lng"]))
        results = rg.search(coords_list, verbose=False)
        df["city"] = [r["name"] for r in results]
        df["state"] = [r.get("admin1", r["cc"]) for r in results]
        df["country"] = [r["cc"] for r in results]
    except ImportError:
        pass

    df = df[_WHERE_WHEN_COLUMNS].sort_values("timestamp").drop_duplicates("timestamp")
    return df.reset_index(drop=True)
