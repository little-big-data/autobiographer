"""Tests for core.time_machine — pure "this day in history" data-shaping (issue #98).

Covers the Time Machine card's acceptance criteria: exact-date matches, no data at all,
one-of-three-categories-only data, deterministic multi-year picking (seeded ``random.Random``
rather than real wall-clock randomness), and each of location/listening/events degrading
independently.
"""

from __future__ import annotations

import random

import pandas as pd
import pytest

from core.time_machine import (
    EventSnapshot,
    ListeningSnapshot,
    LocationSnapshot,
    TimeMachineEntry,
    build_entry,
    candidate_years,
    get_time_machine_entry,
    pick_year,
)


def _ts(dt_str: str) -> int:
    """Return a unix int-seconds timestamp for the given ISO date string."""
    return int(pd.Timestamp(dt_str).timestamp())


def _activity_row(
    date_str: str,
    artist: str,
    track: str = "",
    album: str = "",
    source_id: str = "lastfm",
    city: str | None = "Reykjavik",
    state: str | None = "IS",
    country: str | None = "Iceland",
) -> dict:
    row = {
        "timestamp": _ts(date_str),
        "date_text": pd.Timestamp(date_str),
        "artist": artist,
        "track": track,
        "album": album,
        "source_id": source_id,
    }
    if city is not None:
        row["city"] = city
        row["state"] = state
        row["country"] = country
    return row


def _activity_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _places_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _place_row(
    date_str: str, city: str = "", state: str = "", country: str = "", venue: str = ""
) -> dict:
    return {
        "timestamp": _ts(date_str),
        "city": city,
        "state": state,
        "country": country,
        "venue": venue,
    }


EMPTY_ACTIVITY = pd.DataFrame(
    columns=["timestamp", "date_text", "artist", "track", "album", "source_id"]
)
EMPTY_PLACES = pd.DataFrame(columns=["timestamp", "city", "state", "country", "venue"])


# ---------------------------------------------------------------------------
# candidate_years
# ---------------------------------------------------------------------------


def test_candidate_years_matches_month_and_day_across_multiple_past_years() -> None:
    activity = _activity_df(
        [
            _activity_row("2019-07-11", "Artist A"),
            _activity_row("2021-07-11", "Artist B"),
            _activity_row("2021-08-01", "Artist Off-Day"),  # different day, must not match
        ]
    )
    years = candidate_years(pd.Timestamp("2026-07-11").date(), activity, EMPTY_PLACES)
    assert years == [2021, 2019]


def test_candidate_years_excludes_current_year_and_future() -> None:
    activity = _activity_df(
        [
            _activity_row("2026-07-11", "Today, not history"),
        ]
    )
    years = candidate_years(pd.Timestamp("2026-07-11").date(), activity, EMPTY_PLACES)
    assert years == []


def test_candidate_years_includes_places_only_years() -> None:
    places = _places_df([_place_row("2018-07-11", city="Lisbon")])
    years = candidate_years(pd.Timestamp("2026-07-11").date(), EMPTY_ACTIVITY, places)
    assert years == [2018]


def test_candidate_years_empty_when_no_data_at_all() -> None:
    years = candidate_years(pd.Timestamp("2026-07-11").date(), EMPTY_ACTIVITY, EMPTY_PLACES)
    assert years == []


def test_candidate_years_tolerates_missing_columns() -> None:
    """A frame missing date_text/timestamp altogether must not raise."""
    activity = pd.DataFrame({"artist": ["A"]})
    places = pd.DataFrame({"city": ["X"]})
    assert candidate_years(pd.Timestamp("2026-07-11").date(), activity, places) == []


def test_candidate_years_tolerates_none_frames() -> None:
    assert candidate_years(pd.Timestamp("2026-07-11").date(), None, None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# pick_year
# ---------------------------------------------------------------------------


def test_pick_year_returns_none_for_empty_list() -> None:
    assert pick_year([]) is None


def test_pick_year_is_deterministic_with_seeded_rng() -> None:
    years = [2018, 2019, 2020, 2021]
    picked_a = pick_year(years, rng=random.Random(42))
    picked_b = pick_year(years, rng=random.Random(42))
    assert picked_a == picked_b
    assert picked_a in years


def test_pick_year_single_candidate_returns_it() -> None:
    assert pick_year([2020], rng=random.Random(0)) == 2020


# ---------------------------------------------------------------------------
# build_entry — full entry (all three categories present)
# ---------------------------------------------------------------------------


def test_build_entry_full_data_all_categories_present() -> None:
    activity = _activity_df(
        [
            _activity_row(
                "2019-07-11",
                "Radiohead",
                "Idioteque",
                "Kid A",
                city="Lisbon",
                state="",
                country="Portugal",
            ),
            _activity_row("2019-07-11", "Radiohead", "Everything In Its Right Place", "Kid A"),
            _activity_row(
                "2019-07-11",
                "Tasting Room Brewing",
                "Hazy IPA",
                "IPA",
                source_id="untappd",
            ),
        ]
    )
    places = _places_df(
        [_place_row("2019-07-11", city="Lisbon", country="Portugal", venue="Cafe A")]
    )

    entry = build_entry(pd.Timestamp("2026-07-11").date(), 2019, activity, places)

    assert entry.target_date == pd.Timestamp("2019-07-11").date()
    assert entry.years_ago == 7

    assert entry.location is not None
    assert entry.location.city == "Lisbon"
    assert entry.location.country == "Portugal"

    assert entry.listening is not None
    assert entry.listening.scrobble_count == 2
    assert entry.listening.top_artist == "Radiohead"
    assert "Radiohead — Idioteque" in entry.listening.sample_tracks

    assert len(entry.events) == 1
    assert entry.events[0].label == "Tasting Room Brewing"
    assert entry.events[0].sublabel == "Hazy IPA"
    assert entry.events[0].source_id == "untappd"


# ---------------------------------------------------------------------------
# build_entry — independent optionality: only one of three categories has data
# ---------------------------------------------------------------------------


def test_build_entry_listening_only_leaves_location_and_events_absent() -> None:
    activity = _activity_df(
        [
            _activity_row(
                "2020-03-05", "Boards of Canada", "Roygbiv", city=None, state=None, country=None
            )
        ]
    )
    entry = build_entry(pd.Timestamp("2026-03-05").date(), 2020, activity, EMPTY_PLACES)

    assert entry.listening is not None
    assert entry.listening.scrobble_count == 1
    assert entry.location is None
    assert entry.events == ()


def test_build_entry_events_only_leaves_location_and_listening_absent() -> None:
    activity = _activity_df(
        [
            _activity_row(
                "2020-03-05",
                "Some Brewery",
                "Stout",
                "Stout",
                source_id="untappd",
                city=None,
                state=None,
                country=None,
            )
        ]
    )
    entry = build_entry(pd.Timestamp("2026-03-05").date(), 2020, activity, EMPTY_PLACES)

    assert entry.listening is None
    assert entry.location is None
    assert len(entry.events) == 1
    assert entry.events[0].label == "Some Brewery"


def test_build_entry_location_only_from_places_leaves_listening_and_events_absent() -> None:
    places = _places_df([_place_row("2020-03-05", city="Berlin", country="Germany")])
    entry = build_entry(pd.Timestamp("2026-03-05").date(), 2020, EMPTY_ACTIVITY, places)

    assert entry.location is not None
    assert entry.location.city == "Berlin"
    assert entry.listening is None
    assert entry.events == ()


def test_build_entry_location_falls_back_to_venue_when_places_lack_city() -> None:
    places = _places_df([_place_row("2020-03-05", venue="The Loft")])
    entry = build_entry(pd.Timestamp("2026-03-05").date(), 2020, EMPTY_ACTIVITY, places)

    assert entry.location is not None
    assert entry.location.city == "The Loft"


def test_build_entry_no_matching_rows_on_date_returns_all_absent() -> None:
    activity = _activity_df([_activity_row("2020-03-06", "Off by one day")])
    entry = build_entry(pd.Timestamp("2026-03-05").date(), 2020, activity, EMPTY_PLACES)

    assert entry.location is None
    assert entry.listening is None
    assert entry.events == ()


def test_build_entry_missing_source_id_treats_all_rows_as_listening() -> None:
    """Legacy (flat-file) mode has no source_id column at all — every row is a real listen."""
    activity = pd.DataFrame(
        [
            {
                "timestamp": _ts("2020-03-05"),
                "date_text": pd.Timestamp("2020-03-05"),
                "artist": "Aphex Twin",
                "track": "Windowlicker",
                "album": "Windowlicker EP",
                "city": "Perth",
                "state": "WA",
                "country": "Australia",
            }
        ]
    )
    entry = build_entry(pd.Timestamp("2026-03-05").date(), 2020, activity, EMPTY_PLACES)

    assert entry.listening is not None
    assert entry.listening.scrobble_count == 1
    assert entry.events == ()
    assert entry.location is not None
    assert entry.location.city == "Perth"


# ---------------------------------------------------------------------------
# get_time_machine_entry — top-level orchestration
# ---------------------------------------------------------------------------


def test_get_time_machine_entry_no_data_at_all_returns_none() -> None:
    result = get_time_machine_entry(pd.Timestamp("2026-07-11").date(), EMPTY_ACTIVITY, EMPTY_PLACES)
    assert result is None


def test_get_time_machine_entry_exact_date_match_returns_entry() -> None:
    activity = _activity_df([_activity_row("2022-07-11", "Artist X", "Track X")])
    result = get_time_machine_entry(
        pd.Timestamp("2026-07-11").date(), activity, EMPTY_PLACES, rng=random.Random(1)
    )
    assert result is not None
    assert result.target_date == pd.Timestamp("2022-07-11").date()
    assert result.years_ago == 4


def test_get_time_machine_entry_picks_deterministically_among_multiple_years() -> None:
    activity = _activity_df(
        [
            _activity_row("2018-07-11", "Artist 2018"),
            _activity_row("2020-07-11", "Artist 2020"),
            _activity_row("2022-07-11", "Artist 2022"),
        ]
    )
    today = pd.Timestamp("2026-07-11").date()

    result_a = get_time_machine_entry(today, activity, EMPTY_PLACES, rng=random.Random(7))
    result_b = get_time_machine_entry(today, activity, EMPTY_PLACES, rng=random.Random(7))

    assert result_a is not None
    assert result_b is not None
    assert result_a.target_date == result_b.target_date
    assert result_a.target_date.year in (2018, 2020, 2022)


def test_get_time_machine_entry_tries_multiple_candidates_not_just_fixed_offset() -> None:
    """Data exists 3 years ago but not exactly 1 year ago — must still find it."""
    activity = _activity_df([_activity_row("2023-07-11", "Old Artist")])
    today = pd.Timestamp("2026-07-11").date()  # "1 year ago" (2025) has nothing

    result = get_time_machine_entry(today, activity, EMPTY_PLACES)
    assert result is not None
    assert result.target_date.year == 2023


# ---------------------------------------------------------------------------
# Dataclass sanity (construction / equality used elsewhere, e.g. page rendering)
# ---------------------------------------------------------------------------


def test_dataclasses_are_constructible_and_comparable() -> None:
    loc = LocationSnapshot(city="Lisbon", state="", country="Portugal")
    listening = ListeningSnapshot(
        scrobble_count=2, top_artist="Radiohead", sample_tracks=("A — B",)
    )
    event = EventSnapshot(label="Brewery", sublabel="IPA", category="IPA", source_id="untappd")
    entry = TimeMachineEntry(
        target_date=pd.Timestamp("2019-07-11").date(),
        years_ago=7,
        location=loc,
        listening=listening,
        events=(event,),
    )
    assert entry.location == loc
    assert entry.listening == listening
    assert entry.events == (event,)


if __name__ == "__main__":
    pytest.main([__file__])
