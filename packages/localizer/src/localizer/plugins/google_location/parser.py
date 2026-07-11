"""Parsers for legacy Google Location History (Google Takeout) exports.

Google Takeout has offered location history in two now-superseded formats,
both distinct from the newer on-device ``Timeline.json`` export handled by
``localizer.plugins.google_timeline.parser`` (see that module for the modern
format):

  - **Records.json** (older format): a single file at the top level of the
    "Location History" export directory, shaped
    ``{"locations": [{"latitudeE7": ..., "longitudeE7": ..., "timestamp": ...}, ...]}``.
    Each entry is a raw GPS ping (no place name/semantic info).
  - **Semantic Location History** (newer legacy format): one JSON file per
    month, at ``Semantic Location History/<Year>/<Year>_<MONTH>.json``,
    shaped
    ``{"timelineObjects": [{"placeVisit": {...}} | {"activitySegment": {...}}, ...]}``.
    Each entry is either a place visit (with a place name/semantic type) or
    a movement between two locations (an activity segment).

Both parsers are pure functions: given a file path, they yield normalized
dicts with ``timestamp`` (Unix seconds), ``lat``/``lng`` (floats),
``place_name``, ``place_type``, and ``raw`` (the original JSON entry, kept
for full-fidelity storage). Malformed files/entries are skipped rather than
raising, mirroring ``localizer.plugins.swarm.loader``'s per-file resilience.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def _parse_iso_or_ms_timestamp(entry: dict[str, Any], iso_key: str, ms_key: str) -> int | None:
    """Return a Unix-seconds timestamp from an entry with an ISO or millisecond field.

    Args:
        entry: Dict potentially containing `iso_key` (RFC3339 string) and/or
            `ms_key` (string or int of Unix milliseconds).
        iso_key: Key for the ISO 8601 timestamp string (preferred).
        ms_key: Key for the millisecond-epoch fallback.

    Returns:
        Unix timestamp in seconds, or None if neither field parses.
    """
    iso_value = entry.get(iso_key)
    if iso_value:
        try:
            import pandas as pd  # noqa: PLC0415

            return int(pd.Timestamp(iso_value).timestamp())
        except (ValueError, TypeError):
            pass

    ms_value = entry.get(ms_key)
    if ms_value is not None:
        try:
            return int(ms_value) // 1000
        except (ValueError, TypeError):
            pass

    return None


def parse_records_json(path: str | Path) -> Iterator[dict[str, Any]]:
    """Parse a legacy Google Takeout ``Records.json`` export.

    Args:
        path: Path to the `Records.json` file.

    Yields:
        Dicts with keys `timestamp`, `lat`, `lng`, `place_name`, `place_type`,
        `raw`. Entries missing coordinates or a parseable timestamp are
        skipped. `place_name` is always `""` and `place_type` is always
        `"location_ping"` — Records.json entries are raw GPS pings with no
        semantic place information (unlike Semantic Location History).

    Notes:
        Yields nothing (rather than raising) if the file is missing, is not
        valid JSON, or has no top-level `locations` list.
    """
    file_path = Path(path)
    if not file_path.exists():
        return

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if not isinstance(data, dict):
        return
    locations = data.get("locations")
    if not isinstance(locations, list):
        return

    for entry in locations:
        if not isinstance(entry, dict):
            continue

        lat_e7 = entry.get("latitudeE7")
        lng_e7 = entry.get("longitudeE7")
        if lat_e7 is None or lng_e7 is None:
            continue

        timestamp = _parse_iso_or_ms_timestamp(entry, "timestamp", "timestampMs")
        if timestamp is None:
            continue

        try:
            lat = float(lat_e7) / 1e7
            lng = float(lng_e7) / 1e7
        except (TypeError, ValueError):
            continue

        yield {
            "timestamp": timestamp,
            "lat": lat,
            "lng": lng,
            "place_name": "",
            "place_type": "location_ping",
            "raw": entry,
        }


def parse_semantic_location_history(path: str | Path) -> Iterator[dict[str, Any]]:
    """Parse a single Semantic Location History month file.

    Args:
        path: Path to a `<Year>_<MONTH>.json` file under
            `Semantic Location History/<Year>/`.

    Yields:
        Dicts with keys `timestamp`, `lat`, `lng`, `place_name`, `place_type`,
        `raw`. Place visits yield the visited place's name (or "Unknown
        place") and its semantic type, lowercased, as `place_type`. Activity
        segments (movement between places) yield the activity type as
        `place_name` and `"activity:<type>"` (lowercased) as `place_type`,
        matching the convention used by
        `localizer.plugins.google_timeline.parser`.

    Notes:
        Yields nothing (rather than raising) if the file is missing, is not
        valid JSON, or has no top-level `timelineObjects` list. Entries
        missing coordinates or a parseable timestamp are skipped.
    """
    file_path = Path(path)
    if not file_path.exists():
        return

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if not isinstance(data, dict):
        return
    objects = data.get("timelineObjects")
    if not isinstance(objects, list):
        return

    for obj in objects:
        if not isinstance(obj, dict):
            continue

        if "placeVisit" in obj:
            record = _parse_place_visit(obj)
        elif "activitySegment" in obj:
            record = _parse_activity_segment(obj)
        else:
            continue

        if record is not None:
            yield record


def _parse_place_visit(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a single `placeVisit` timeline object.

    Args:
        obj: A `timelineObjects` entry containing a `placeVisit` key.

    Returns:
        Normalized dict, or None if coordinates/timestamp cannot be parsed.
    """
    visit = obj.get("placeVisit") or {}
    location = visit.get("location") or {}
    lat_e7 = location.get("latitudeE7")
    lng_e7 = location.get("longitudeE7")
    if lat_e7 is None or lng_e7 is None:
        return None

    duration = visit.get("duration") or {}
    timestamp = _parse_iso_or_ms_timestamp(duration, "startTimestamp", "startTimestampMs")
    if timestamp is None:
        return None

    try:
        lat = float(lat_e7) / 1e7
        lng = float(lng_e7) / 1e7
    except (TypeError, ValueError):
        return None

    place_name = location.get("name") or "Unknown place"
    semantic_type = visit.get("semanticType") or location.get("semanticType") or "visit"

    return {
        "timestamp": timestamp,
        "lat": lat,
        "lng": lng,
        "place_name": place_name,
        "place_type": str(semantic_type).lower(),
        "raw": obj,
    }


def _parse_activity_segment(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a single `activitySegment` timeline object.

    Args:
        obj: A `timelineObjects` entry containing an `activitySegment` key.

    Returns:
        Normalized dict, or None if coordinates/timestamp cannot be parsed.
    """
    segment = obj.get("activitySegment") or {}
    start_location = segment.get("startLocation") or {}
    lat_e7 = start_location.get("latitudeE7")
    lng_e7 = start_location.get("longitudeE7")
    if lat_e7 is None or lng_e7 is None:
        return None

    duration = segment.get("duration") or {}
    timestamp = _parse_iso_or_ms_timestamp(duration, "startTimestamp", "startTimestampMs")
    if timestamp is None:
        return None

    try:
        lat = float(lat_e7) / 1e7
        lng = float(lng_e7) / 1e7
    except (TypeError, ValueError):
        return None

    activity_type = segment.get("activityType") or "UNKNOWN"

    return {
        "timestamp": timestamp,
        "lat": lat,
        "lng": lng,
        "place_name": str(activity_type).replace("_", " ").capitalize(),
        "place_type": "activity:" + str(activity_type).lower(),
        "raw": obj,
    }
