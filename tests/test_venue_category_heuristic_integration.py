"""Failing tests for Subtask 3 (issue #93): end-to-end proof that the venue-category
name heuristic (Subtasks 1-2) actually fixes ``get_transit_days()`` /
``get_dining_soundtrack_data()`` for real-shaped Foursquare/Swarm exports where
``categories`` is empty on every venue.

This test exercises the full previously-broken pipeline:

    SwarmPlugin.fetch_records()  (synthetic empty-``categories`` checkins)
        -> a places_df shaped like fetch_records()'s output
        -> core.localizer_frames.places_to_swarm_frame()
        -> analysis_utils.get_transit_days() / get_dining_soundtrack_data()

All venue names are synthetic/generic, per CLAUDE.md Section 3 (no real personal data).

Until Subtasks 1-2 are implemented, ``SwarmPlugin.fetch_records()`` leaves
``place_type`` as ``""`` whenever ``categories`` is empty (today's documented bug),
so the "after fix" assertions below are expected to FAIL (RED) right now. The
"before fix" control-case assertions are expected to PASS already -- they document
the bug directly, not the fix, so they establish the necessary before/after contrast
rather than accidentally validating the whole file as vacuously green.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from localizer.plugins.swarm.loader import SwarmPlugin

from analysis_utils import get_dining_soundtrack_data, get_transit_days
from core.localizer_frames import places_to_swarm_frame

# ---------------------------------------------------------------------------
# Synthetic fixture helpers
# ---------------------------------------------------------------------------

# Fixed, arbitrary Unix timestamps (seconds) -- deterministic across runs/timezones.
AIRPORT_CHECKIN_TS = 1_700_000_000  # 2023-11-14 22:13:20 UTC
DINING_CHECKIN_TS = 1_700_100_000  # ~ a day later; well clear of the airport check-in
DINING_LISTEN_TS = DINING_CHECKIN_TS + 5 * 60  # 5 minutes after the dining check-in


def _make_empty_category_checkin(
    created_at: int,
    venue_name: str,
    lat: float = 51.5074,
    lng: float = -0.1278,
) -> dict[str, Any]:
    """Build a checkin dict with an empty ``categories`` list.

    This mirrors the real, previously-broken Foursquare/Swarm export shape
    described in the Task Overview: every venue's ``categories`` array is empty.
    """
    return {
        "id": "synthetic-checkin",
        "createdAt": created_at,
        "lat": lat,
        "lng": lng,
        "venue": {
            "id": "synthetic-venue",
            "name": venue_name,
            "location": {"lat": lat, "lng": lng},
            "categories": [],
        },
        "timeZoneOffset": 0,
    }


def _write_checkins(path: Path, checkins: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"items": checkins}), encoding="utf-8")


def _fetch_places_df(swarm_dir: Path) -> pd.DataFrame:
    """Run the real SwarmPlugin.fetch_records() pipeline and shape a places_df.

    Columns match the shape ``places_to_swarm_frame()`` expects (the same shape
    documented as ``LocalizerBroker.get_places_frame()``'s output): timestamp, lat,
    lng, place_name, place_type, source_id.
    """
    plugin = SwarmPlugin(swarm_dir=str(swarm_dir))
    records = list(plugin.fetch_records())
    assert records, "expected fetch_records() to yield the synthetic checkins"
    return pd.DataFrame(records)[
        ["timestamp", "lat", "lng", "place_name", "place_type", "source_id"]
    ]


def _lastfm_fixture_for_dining_window() -> pd.DataFrame:
    """One synthetic Last.fm listen inside the dining check-in's ±30 min window."""
    return pd.DataFrame(
        {
            "timestamp": [DINING_LISTEN_TS],
            "date_text": [pd.to_datetime(DINING_LISTEN_TS, unit="s")],
            "artist": ["Synthetic Artist"],
            "track": ["Synthetic Track"],
            "album": ["Synthetic Album"],
            "source_id": ["lastfm"],
        }
    )


# ---------------------------------------------------------------------------
# "After" fixture: real fetch_records() pipeline over empty-categories checkins
# ---------------------------------------------------------------------------


@pytest.fixture
def swarm_df_from_real_pipeline(tmp_path: Path) -> pd.DataFrame:
    """swarm_df built end-to-end from SwarmPlugin.fetch_records(), empty categories.

    One airport-style venue (should trip TRANSIT_CATEGORY_KEYWORDS via the name
    heuristic once Subtasks 1-2 land) and one restaurant-style venue (should trip
    _CATEGORY_RULES' "Restaurants" bucket via the name heuristic).
    """
    checkins = [
        _make_empty_category_checkin(
            created_at=AIRPORT_CHECKIN_TS,
            venue_name="O'Hare International Airport",
            lat=41.9742,
            lng=-87.9073,
        ),
        _make_empty_category_checkin(
            created_at=DINING_CHECKIN_TS,
            venue_name="Corner City Diner",
            lat=51.5074,
            lng=-0.1278,
        ),
    ]
    _write_checkins(tmp_path / "checkins_synthetic.json", checkins)
    places_df = _fetch_places_df(tmp_path)
    return places_to_swarm_frame(places_df)


# ---------------------------------------------------------------------------
# "Before" control fixture: place_type forced to "" (documented pre-fix behavior)
# ---------------------------------------------------------------------------


@pytest.fixture
def swarm_df_pre_fix_control() -> pd.DataFrame:
    """swarm_df with place_type/venue_category explicitly forced to "".

    This does NOT call the name heuristic at all -- it hand-constructs the exact
    shape SwarmPlugin.fetch_records() produces *today*, before any fix, for
    empty-categories venues (place_type stays "" unconditionally). It exists to
    prove the "before" half of the before/after contrast is real, not incidental.
    """
    places_df = pd.DataFrame(
        {
            "timestamp": [AIRPORT_CHECKIN_TS, DINING_CHECKIN_TS],
            "lat": [41.9742, 51.5074],
            "lng": [-87.9073, -0.1278],
            "place_name": ["O'Hare International Airport", "Corner City Diner"],
            "place_type": ["", ""],
            "source_id": ["swarm", "swarm"],
        }
    )
    return places_to_swarm_frame(places_df)


# ---------------------------------------------------------------------------
# "After fix" assertions -- expected RED until Subtasks 1-2 are implemented
# ---------------------------------------------------------------------------


def test_transit_days_populate_after_fix(swarm_df_from_real_pipeline: pd.DataFrame) -> None:
    """get_transit_days() must be non-empty once the name heuristic infers 'Airport'."""
    transit_days = get_transit_days(swarm_df_from_real_pipeline)

    assert transit_days != set(), (
        "get_transit_days() returned empty for a synthetic airport-style check-in "
        "with empty categories -- the name-based place_type heuristic "
        "(_infer_place_type_from_name, Subtasks 1-2) is not yet wired up, or is not "
        "producing a value containing a TRANSIT_CATEGORY_KEYWORDS substring."
    )
    expected_date = pd.to_datetime(AIRPORT_CHECKIN_TS, unit="s").strftime("%Y-%m-%d")
    assert expected_date in transit_days


def test_dining_soundtrack_data_populates_after_fix(
    swarm_df_from_real_pipeline: pd.DataFrame,
) -> None:
    """get_dining_soundtrack_data() must be non-empty and bucket the diner as Restaurants."""
    lastfm_df = _lastfm_fixture_for_dining_window()

    result = get_dining_soundtrack_data(swarm_df_from_real_pipeline, lastfm_df)

    assert result != {}, (
        "get_dining_soundtrack_data() returned empty for a synthetic diner-style "
        "check-in with empty categories -- the name-based place_type heuristic "
        "(_infer_place_type_from_name, Subtasks 1-2) is not yet wired up, or is not "
        "producing a value containing a _CATEGORY_RULES substring (e.g. 'diner')."
    )
    assert "Restaurants" in result
    assert result["Restaurants"]["checkin_count"] >= 1
    assert result["Restaurants"]["listen_count"] >= 1


def test_dining_soundtrack_data_top_artists_include_synthetic_listen(
    swarm_df_from_real_pipeline: pd.DataFrame,
) -> None:
    """The single synthetic listen inside the dining window must surface in top_artists."""
    lastfm_df = _lastfm_fixture_for_dining_window()

    result = get_dining_soundtrack_data(swarm_df_from_real_pipeline, lastfm_df)

    assert "Restaurants" in result
    top_artists = result["Restaurants"]["top_artists"]
    assert not top_artists.empty
    assert "Synthetic Artist" in top_artists["artist"].values


# ---------------------------------------------------------------------------
# "Before fix" control-case assertions -- expected to PASS already (they assert
# the documented pre-fix bug, not the fix), establishing the explicit contrast.
# ---------------------------------------------------------------------------


def test_transit_days_empty_before_fix_control(swarm_df_pre_fix_control: pd.DataFrame) -> None:
    """Control: with place_type forced to "", get_transit_days() returns empty (the bug)."""
    assert get_transit_days(swarm_df_pre_fix_control) == set()


def test_dining_soundtrack_data_empty_before_fix_control(
    swarm_df_pre_fix_control: pd.DataFrame,
) -> None:
    """Control: with place_type forced to "", get_dining_soundtrack_data() returns empty."""
    lastfm_df = _lastfm_fixture_for_dining_window()

    assert get_dining_soundtrack_data(swarm_df_pre_fix_control, lastfm_df) == {}


# ---------------------------------------------------------------------------
# Documentation acceptance criterion: README's "places layer" section must
# describe the name-based fallback and its approximation limitation.
# ---------------------------------------------------------------------------


def test_readme_documents_name_based_fallback_limitation() -> None:
    """README's places-layer section must mention the name-based fallback + limitation.

    Durable assertion: checks for the presence of the *concept* (name-based
    inference is a fallback, and it is an approximation subordinate to real
    Foursquare category data) via loose, case-insensitive keyword checks -- not a
    pinned exact sentence -- so future wording tweaks don't spuriously fail this.
    """
    readme_path = Path(__file__).resolve().parents[1] / "packages" / "localizer" / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8").lower()

    places_layer_idx = readme_text.find("places layer")
    assert places_layer_idx != -1, "README is missing its 'places layer' section"

    # Look for the doc note anywhere in the README (coder may place it in or near
    # the places-layer section) -- the presence of both concept keywords is what
    # we assert, not their exact location or wording.
    assert "name" in readme_text and ("fallback" in readme_text or "heuristic" in readme_text), (
        "README does not document the name-based place_type fallback/heuristic"
    )
    assert "approximat" in readme_text or "limitation" in readme_text, (
        "README does not document the approximation/limitation of the name-based "
        "fallback (i.e. that real Foursquare category data is preferred when present)"
    )
