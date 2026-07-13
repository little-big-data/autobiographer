"""Failing tests for Subtask 4: SwarmPlugin in the localizer package.

All tests here are expected to FAIL until the coder implements:
  - packages/localizer/src/localizer/plugins/swarm/__init__.py
  - packages/localizer/src/localizer/plugins/swarm/loader.py
  - Updated packages/localizer/src/localizer/plugins/__init__.py (load_builtin_plugins)

SwarmPlugin is FetchMode.MANUAL — the data directory is provided at instantiation
time (e.g. SwarmPlugin(swarm_dir=...)) or via an env var so that fetch_records()
can satisfy the standard ABC signature fetch_records(since, progress_cb).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal Swarm checkin JSON matching the export schema
# ---------------------------------------------------------------------------


def _make_checkin(
    created_at: int = 1_700_000_000,
    lat: float = 51.5074,
    lng: float = -0.1278,
    venue_name: str = "The Test Pub",
    category_name: str = "Bar",
) -> dict[str, Any]:
    """Return a single checkin dict in the Foursquare/Swarm JSON export format."""
    return {
        "id": "abc123",
        "createdAt": created_at,
        "lat": lat,
        "lng": lng,
        "venue": {
            "id": "venue001",
            "name": venue_name,
            "location": {
                "lat": lat,
                "lng": lng,
                "city": "London",
                "country": "United Kingdom",
            },
            "categories": [{"id": "cat001", "name": category_name, "primary": True}],
        },
        "timeZoneOffset": 0,
    }


def _write_checkins_json(path: Path, checkins: list[dict[str, Any]]) -> None:
    """Write a Swarm-format checkins*.json file to *path*."""
    path.write_text(json.dumps({"items": checkins}), encoding="utf-8")


def _make_swarm_plugin(swarm_dir: Path) -> Any:
    """Instantiate SwarmPlugin with the given directory, trying plausible signatures."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    # The plugin may accept the directory at __init__ or via get_config_fields pattern.
    # Try SwarmPlugin(swarm_dir=str(swarm_dir)) first, then SwarmPlugin() fallback.
    try:
        return SwarmPlugin(swarm_dir=str(swarm_dir))
    except TypeError:
        # Plugin may use a different constructor; accept a no-arg form that we
        # configure via a keyword argument named after the field key.
        return SwarmPlugin()


def _fetch_records(plugin: Any, swarm_dir: Path | None = None) -> list[dict[str, Any]]:
    """Call fetch_records() on the plugin, supplying swarm_dir if needed."""
    # Try the standard ABC signature first: fetch_records(since=None)
    # If the plugin was initialised with the directory, no extra arg is needed.
    # If it wasn't, try passing it as a keyword for flexibility.
    try:
        return list(plugin.fetch_records())
    except TypeError:
        # Some implementations may accept swarm_dir as a positional/keyword arg.
        if swarm_dir is not None:
            return list(plugin.fetch_records(swarm_dir=str(swarm_dir)))
        raise


# ---------------------------------------------------------------------------
# ABC / registration tests
# ---------------------------------------------------------------------------


def test_swarm_plugin_is_registered() -> None:
    """After load_builtin_plugins(), REGISTRY['swarm'] must exist."""
    from localizer.plugins import REGISTRY, load_builtin_plugins

    REGISTRY.clear()
    load_builtin_plugins()
    assert "swarm" in REGISTRY, "Expected 'swarm' key in REGISTRY after load_builtin_plugins()"


def test_swarm_plugin_plugin_id() -> None:
    """SwarmPlugin.PLUGIN_ID must equal 'swarm'."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    assert SwarmPlugin.PLUGIN_ID == "swarm"


def test_swarm_plugin_fetch_mode_manual() -> None:
    """SwarmPlugin.FETCH_MODE must be FetchMode.MANUAL."""
    from localizer.plugins.base import FetchMode
    from localizer.plugins.swarm.loader import SwarmPlugin

    assert SwarmPlugin.FETCH_MODE == FetchMode.MANUAL


def test_swarm_plugin_output_tables_places() -> None:
    """OutputTable.PLACES must be in SwarmPlugin.OUTPUT_TABLES."""
    from localizer.plugins.base import OutputTable
    from localizer.plugins.swarm.loader import SwarmPlugin

    assert OutputTable.PLACES in SwarmPlugin.OUTPUT_TABLES


def test_swarm_plugin_get_config_fields() -> None:
    """get_config_fields() must return a non-empty list (at least the directory field)."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    # A no-arg instantiation should work for inspecting config fields.
    plugin = SwarmPlugin()
    fields = plugin.get_config_fields()
    assert isinstance(fields, list)
    assert len(fields) >= 1, "Expected at least one config field (swarm directory path)"
    for field in fields:
        assert "key" in field, f"Config field missing 'key': {field}"
        assert "label" in field, f"Config field missing 'label': {field}"


def test_swarm_plugin_manual_download_instructions() -> None:
    """get_manual_download_instructions() must return a non-empty string."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    plugin = SwarmPlugin()
    instructions = plugin.get_manual_download_instructions()
    assert isinstance(instructions, str)
    assert len(instructions.strip()) > 0, "Expected non-empty manual download instructions"


# ---------------------------------------------------------------------------
# fetch_records normalization tests
# ---------------------------------------------------------------------------


def test_fetch_records_yields_place_dicts(tmp_path: Path) -> None:
    """A directory with one checkin JSON file should yield exactly 1 dict."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    _write_checkins_json(tmp_path / "checkins_20231101.json", [_make_checkin()])

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert len(records) == 1, f"Expected 1 record, got {len(records)}"


def test_fetch_records_dict_has_required_keys(tmp_path: Path) -> None:
    """Each yielded dict must have the required place record keys."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    _write_checkins_json(tmp_path / "checkins_20231101.json", [_make_checkin()])

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert len(records) == 1

    record = records[0]
    required_keys = {
        "source_id",
        "timestamp",
        "lat",
        "lng",
        "place_name",
        "place_type",
        "raw_json",
        "fetched_at",
    }
    missing = required_keys - set(record.keys())
    assert not missing, f"Record missing required keys: {missing}"


def test_fetch_records_source_id_is_swarm(tmp_path: Path) -> None:
    """Each record's source_id must equal 'swarm'."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    _write_checkins_json(tmp_path / "checkins_20231101.json", [_make_checkin()])

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert records[0]["source_id"] == "swarm"


def test_fetch_records_lat_lng_are_floats(tmp_path: Path) -> None:
    """lat and lng in each record must be Python floats."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    _write_checkins_json(
        tmp_path / "checkins_20231101.json",
        [_make_checkin(lat=51.5074, lng=-0.1278)],
    )

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    record = records[0]
    assert isinstance(record["lat"], float), f"Expected float lat, got {type(record['lat'])}"
    assert isinstance(record["lng"], float), f"Expected float lng, got {type(record['lng'])}"


def test_fetch_records_timestamp_is_int(tmp_path: Path) -> None:
    """timestamp in each record must be a Python int (Unix seconds)."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    ts = 1_700_000_000
    _write_checkins_json(tmp_path / "checkins_20231101.json", [_make_checkin(created_at=ts)])

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    record = records[0]
    assert isinstance(record["timestamp"], int), (
        f"Expected int timestamp, got {type(record['timestamp'])}"
    )


def test_fetch_records_place_name_matches_venue(tmp_path: Path) -> None:
    """place_name must equal the venue name from the JSON."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    _write_checkins_json(
        tmp_path / "checkins_20231101.json",
        [_make_checkin(venue_name="Specific Venue Name")],
    )

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert records[0]["place_name"] == "Specific Venue Name"


def test_fetch_records_place_type_from_category(tmp_path: Path) -> None:
    """place_type must come from the first venue category."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    _write_checkins_json(
        tmp_path / "checkins_20231101.json",
        [_make_checkin(category_name="Coffee Shop")],
    )

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert records[0]["place_type"] == "Coffee Shop"


def test_fetch_records_multiple_files(tmp_path: Path) -> None:
    """Multiple checkins*.json files in the directory should all be read."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    _write_checkins_json(
        tmp_path / "checkins_202310.json",
        [_make_checkin(created_at=1_696_000_000)],
    )
    _write_checkins_json(
        tmp_path / "checkins_202311.json",
        [_make_checkin(created_at=1_700_000_000)],
    )

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert len(records) == 2, f"Expected 2 records across 2 files, got {len(records)}"


def test_fetch_records_empty_dir(tmp_path: Path) -> None:
    """An empty directory (no JSON files) must yield nothing and not crash."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    assert records == [], f"Expected empty list from empty dir, got {records}"


def test_fetch_records_missing_dir(tmp_path: Path) -> None:
    """A non-existent directory path must yield nothing and not crash (graceful)."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    nonexistent = tmp_path / "does_not_exist"

    plugin = SwarmPlugin(swarm_dir=str(nonexistent))
    try:
        records = list(plugin.fetch_records())
        assert records == [], f"Expected empty list for missing dir, got {records}"
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"fetch_records() raised {type(exc).__name__} on missing dir: {exc}")


def test_fetch_records_raw_json_is_serializable(tmp_path: Path) -> None:
    """raw_json must be JSON-serializable (str or dict)."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    _write_checkins_json(tmp_path / "checkins_20231101.json", [_make_checkin()])

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    raw = records[0]["raw_json"]
    if isinstance(raw, str):
        json.loads(raw)  # must not raise
    else:
        json.dumps(raw)  # must not raise


def test_fetch_records_fetched_at_is_recent(tmp_path: Path) -> None:
    """fetched_at must be a Unix timestamp close to now (within 60 seconds)."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    _write_checkins_json(tmp_path / "checkins_20231101.json", [_make_checkin()])

    before = int(time.time())
    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())
    after = int(time.time())

    fetched_at = records[0]["fetched_at"]
    assert isinstance(fetched_at, int)
    assert before - 5 <= fetched_at <= after + 5, (
        f"fetched_at {fetched_at} not close to now ({before}–{after})"
    )


# ---------------------------------------------------------------------------
# Subtask 1 (issue #93): name-based venue-category heuristic
#
# These tests target `_infer_place_type_from_name(venue_name: str) -> str`,
# a new private, pure module-level function in
# `packages/localizer/src/localizer/plugins/swarm/loader.py`. It is not wired
# into `fetch_records()` yet (that is Subtask 2) — these tests call the
# function directly.
#
# Reference vocabulary (copied from handoff.md's Task Overview, itself copied
# from analysis_utils.py, so these tests do not depend on analysis_utils
# imports and stay isolated per CLAUDE.md's test-isolation conventions):
#   _CATEGORY_RULES buckets (lowercase substrings):
#     Fast Food:  fast food, burger, pizza, fried chicken, hot dog, sandwich
#     Bars:       bar, nightclub, pub, brewery, wine, cocktail, lounge, club
#     Cafes:      cafe, café, coffee, tea room, bakery, dessert, ice cream,
#                 juice bar
#     Restaurant: restaurant, diner, food, sushi, ramen, noodle, steakhouse,
#                 bbq, seafood, bistro, brasserie, tapas, dim sum, buffet,
#                 grill, kitchen, eatery
#   TRANSIT_CATEGORY_KEYWORDS (matched case-insensitively):
#     Airport, Train Station, Transit, Bus Station, Metro, Subway, Ferry,
#     Port, Rail, Rest Area, Rest Stop, Travel Plaza, Service Plaza,
#     Turnpike, Toll, Gas Station, Truck Stop
# ---------------------------------------------------------------------------

_TRANSIT_KEYWORDS_LOWER = frozenset(
    {
        "airport",
        "train station",
        "transit",
        "bus station",
        "metro",
        "subway",
        "ferry",
        "port",
        "rail",
        "rest area",
        "rest stop",
        "travel plaza",
        "service plaza",
        "turnpike",
        "toll",
        "gas station",
        "truck stop",
    }
)


def _contains_any(haystack_lower: str, needles: set[str]) -> bool:
    """Return True if any needle substring is present in haystack_lower."""
    return any(needle in haystack_lower for needle in needles)


def test_infer_place_type_from_name_airport() -> None:
    """An airport-style venue name must synthesize a place_type containing 'Airport'."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name("O'Hare International Airport")
    assert "Airport" in result, f"Expected 'Airport' substring, got {result!r}"


def test_infer_place_type_from_name_train_or_metro_station() -> None:
    """A metro/train-station-style venue name must synthesize a transit-keyword place_type."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name("Downtown Metro Station")
    assert result != "", "Expected a non-empty synthesized place_type"
    assert _contains_any(result.lower(), _TRANSIT_KEYWORDS_LOWER), (
        f"Expected a transit keyword substring (e.g. 'Metro'), got {result!r}"
    )


def test_infer_place_type_from_name_pizza() -> None:
    """A pizza-style venue name must synthesize a place_type containing 'pizza' (lowercased)."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name("Joe's Pizza Place")
    assert "pizza" in result.lower(), f"Expected 'pizza' substring, got {result!r}"


def test_infer_place_type_from_name_coffee() -> None:
    """A coffee/cafe-style venue name must synthesize a place_type containing 'coffee'."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name("Downtown Coffee Roasters")
    assert "coffee" in result.lower(), f"Expected 'coffee' substring, got {result!r}"


def test_infer_place_type_from_name_bar_or_pub() -> None:
    """A bar/pub-style venue name must synthesize a place_type from the Bars & Nightlife bucket."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    bars_bucket = {
        "bar",
        "nightclub",
        "pub",
        "brewery",
        "wine",
        "cocktail",
        "lounge",
        "club",
    }
    result = _infer_place_type_from_name("The Rusty Anchor Pub")
    assert result != "", "Expected a non-empty synthesized place_type"
    assert _contains_any(result.lower(), bars_bucket), (
        f"Expected a Bars & Nightlife keyword substring (e.g. 'pub'), got {result!r}"
    )


def test_infer_place_type_from_name_restaurant() -> None:
    """A restaurant-style venue name must synthesize a place_type from the Restaurants bucket."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    restaurant_bucket = {
        "restaurant",
        "diner",
        "food",
        "sushi",
        "ramen",
        "noodle",
        "steakhouse",
        "bbq",
        "seafood",
        "bistro",
        "brasserie",
        "tapas",
        "dim sum",
        "buffet",
        "grill",
        "kitchen",
        "eatery",
    }
    result = _infer_place_type_from_name("Golden Dragon Restaurant")
    assert result != "", "Expected a non-empty synthesized place_type"
    assert _contains_any(result.lower(), restaurant_bucket), (
        f"Expected a Restaurants keyword substring (e.g. 'restaurant'), got {result!r}"
    )


@pytest.mark.parametrize(
    "venue_name",
    ["Generic City Museum", "Downtown Art Gallery"],
)
def test_infer_place_type_from_name_no_match_returns_empty_string(venue_name: str) -> None:
    """A non-food/non-transit venue name must return exactly '' (never None, never raises)."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name(venue_name)
    assert result == "", f"Expected exactly '', got {result!r}"
    assert result is not None


def test_infer_place_type_from_name_false_positive_portland_pizza() -> None:
    """'Portland Pizza Co.' must classify as pizza/dining, not trip a bare 'port' transit rule.

    This guards the Task Overview's non-overlap constraint: the rule table must
    not contain a bare "port" name-pattern rule, since "Portland" would then
    false-positive as transit ("Port").
    """
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name("Portland Pizza Co.")
    assert "pizza" in result.lower(), (
        f"Expected 'pizza' substring (dining classification), got {result!r}"
    )
    assert "port" not in result.lower(), (
        f"Synthesized place_type must not contain a bare 'port' transit false-positive, "
        f"got {result!r}"
    )


def test_infer_place_type_from_name_case_insensitive_all_lowercase() -> None:
    """Matching must be case-insensitive: an all-lowercase venue name still matches."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name("downtown metro station")
    assert result != "", "Expected all-lowercase input to still match the transit heuristic"
    assert _contains_any(result.lower(), _TRANSIT_KEYWORDS_LOWER), (
        f"Expected a transit keyword substring, got {result!r}"
    )


def test_infer_place_type_from_name_case_insensitive_mixed_case() -> None:
    """Matching must be case-insensitive: a mixed/upper-case venue name still matches."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name("DOWNTOWN COFFEE ROASTERS")
    assert "coffee" in result.lower(), f"Expected 'coffee' substring, got {result!r}"


def test_infer_place_type_from_name_empty_string_returns_empty_and_does_not_raise() -> None:
    """An empty venue name must return '' and must not raise."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name("")
    assert result == "", f"Expected '', got {result!r}"


@pytest.mark.parametrize("venue_name", ["   ", "!!!", "...,", "---"])
def test_infer_place_type_from_name_punctuation_only_returns_empty_and_does_not_raise(
    venue_name: str,
) -> None:
    """A venue name containing only punctuation/whitespace must return '' and not raise."""
    from localizer.plugins.swarm.loader import _infer_place_type_from_name

    result = _infer_place_type_from_name(venue_name)
    assert result == "", f"Expected '', got {result!r}"
