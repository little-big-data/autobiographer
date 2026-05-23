"""Tests for Location Behavioral Patterns (Subtask 7).

Tests are RED by design — the functions under test do not exist yet.
All test DataFrames are built inline; no external files or fixtures required.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

import analysis_utils

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_swarm_df(**kwargs: Any) -> pd.DataFrame:
    """Build a minimal Swarm DataFrame from keyword column lists."""
    return pd.DataFrame(kwargs)


def _ts(dt_str: str) -> int:
    """Return a unix int-seconds timestamp for the given ISO date string."""
    return int(pd.Timestamp(dt_str).timestamp())


# ---------------------------------------------------------------------------
# get_venue_loyalty_scores
# ---------------------------------------------------------------------------


class TestVenueLoyaltyScoresOrdering:
    """Venue with more visits must rank above one with fewer visits."""

    def test_high_visit_venue_ranks_first(self) -> None:
        """Venue with 5 visits should appear before venue with 2 visits."""
        swarm_df = _make_swarm_df(
            timestamp=[_ts("2022-01-01")] * 5 + [_ts("2022-01-02")] * 2,
            venue=["Coffee Palace"] * 5 + ["Tea Garden"] * 2,
            venue_category=["Coffee Shop"] * 5 + ["Tea Room"] * 2,
        )
        result = analysis_utils.get_venue_loyalty_scores(swarm_df)

        assert not result.empty, "Result should not be empty"
        assert result.iloc[0]["venue"] == "Coffee Palace", "Venue with 5 visits should rank first"

    def test_loyalty_score_max_is_one(self) -> None:
        """The highest loyalty_score should be exactly 1.0 (normalized)."""
        swarm_df = _make_swarm_df(
            timestamp=[_ts("2022-01-01")] * 5 + [_ts("2022-01-02")] * 2,
            venue=["Coffee Palace"] * 5 + ["Tea Garden"] * 2,
            venue_category=["Coffee Shop"] * 5 + ["Tea Room"] * 2,
        )
        result = analysis_utils.get_venue_loyalty_scores(swarm_df)

        assert result["loyalty_score"].max() == pytest.approx(1.0), (
            "Max loyalty_score should be normalized to 1.0"
        )

    def test_required_columns_present(self) -> None:
        """Result must include venue, venue_category, visit_count, loyalty_score."""
        swarm_df = _make_swarm_df(
            timestamp=[_ts("2022-01-01")] * 3,
            venue=["Burger Barn"] * 3,
            venue_category=["Burger Joint"] * 3,
        )
        result = analysis_utils.get_venue_loyalty_scores(swarm_df)

        for col in ("venue", "venue_category", "visit_count", "loyalty_score"):
            assert col in result.columns, f"Column '{col}' missing from result"


class TestVenueLoyaltyScoresEmpty:
    """Empty input must return an empty DataFrame without raising."""

    def test_empty_swarm_returns_empty_dataframe(self) -> None:
        """Empty swarm_df should return an empty DataFrame, not raise."""
        swarm_df = pd.DataFrame(
            columns=["timestamp", "venue", "venue_category", "lat", "lng", "city"]
        )
        result = analysis_utils.get_venue_loyalty_scores(swarm_df)

        assert isinstance(result, pd.DataFrame), "Should return a DataFrame"
        assert result.empty, "Result should be empty for empty input"


# ---------------------------------------------------------------------------
# get_routine_venues
# ---------------------------------------------------------------------------


class TestRoutineVenuesDetectsMondayRitual:
    """Venue visited 5 times, all on Mondays → dominant_day = 'Monday'."""

    def test_dominant_day_is_monday(self) -> None:
        # pd.Timestamp("2020-01-06") is a Monday
        mondays = [
            int(pd.Timestamp("2020-01-06").timestamp()),
            int(pd.Timestamp("2020-01-13").timestamp()),
            int(pd.Timestamp("2020-01-20").timestamp()),
            int(pd.Timestamp("2020-01-27").timestamp()),
            int(pd.Timestamp("2020-02-03").timestamp()),
        ]
        swarm_df = _make_swarm_df(
            timestamp=mondays,
            venue=["Morning Grind"] * 5,
            venue_category=["Coffee Shop"] * 5,
        )
        result = analysis_utils.get_routine_venues(swarm_df)

        assert not result.empty, "Expected at least one routine venue"
        row = result[result["venue"] == "Morning Grind"]
        assert not row.empty, "Morning Grind should be in result"
        assert row.iloc[0]["dominant_day"] == "Monday", (
            "dominant_day should be 'Monday' for all-Monday visits"
        )

    def test_monday_ritual_venue_in_result(self) -> None:
        """Venue with 5 Monday visits should appear in the result."""
        mondays = [
            int(pd.Timestamp("2020-01-06").timestamp()),
            int(pd.Timestamp("2020-01-13").timestamp()),
            int(pd.Timestamp("2020-01-20").timestamp()),
            int(pd.Timestamp("2020-01-27").timestamp()),
            int(pd.Timestamp("2020-02-03").timestamp()),
        ]
        swarm_df = _make_swarm_df(
            timestamp=mondays,
            venue=["Morning Grind"] * 5,
            venue_category=["Coffee Shop"] * 5,
        )
        result = analysis_utils.get_routine_venues(swarm_df)

        assert "Morning Grind" in result["venue"].values

    def test_routine_venues_required_columns(self) -> None:
        """Result must include venue, venue_category, dominant_day, day_fraction, visit_count."""
        mondays = [
            int(pd.Timestamp("2020-01-06").timestamp()),
            int(pd.Timestamp("2020-01-13").timestamp()),
            int(pd.Timestamp("2020-01-20").timestamp()),
        ]
        swarm_df = _make_swarm_df(
            timestamp=mondays,
            venue=["Morning Grind"] * 3,
            venue_category=["Coffee Shop"] * 3,
        )
        result = analysis_utils.get_routine_venues(swarm_df, min_occurrences=3)

        for col in ("venue", "venue_category", "dominant_day", "day_fraction", "visit_count"):
            assert col in result.columns, f"Column '{col}' missing from result"


class TestRoutineVenuesMinOccurrencesFilter:
    """Venue with fewer visits than min_occurrences must be excluded."""

    def test_two_visits_excluded_when_min_is_three(self) -> None:
        # Two Monday visits — should be excluded when min_occurrences=3
        mondays = [
            int(pd.Timestamp("2020-01-06").timestamp()),
            int(pd.Timestamp("2020-01-13").timestamp()),
        ]
        swarm_df = _make_swarm_df(
            timestamp=mondays,
            venue=["Rare Spot"] * 2,
            venue_category=["Bar"] * 2,
        )
        result = analysis_utils.get_routine_venues(swarm_df, min_occurrences=3)

        if not result.empty:
            assert "Rare Spot" not in result["venue"].values, (
                "Venue with only 2 visits should be excluded when min_occurrences=3"
            )

    def test_meeting_min_occurrences_is_included(self) -> None:
        """Venue with exactly min_occurrences visits on the same day is included."""
        mondays = [
            int(pd.Timestamp("2020-01-06").timestamp()),
            int(pd.Timestamp("2020-01-13").timestamp()),
            int(pd.Timestamp("2020-01-20").timestamp()),
        ]
        swarm_df = _make_swarm_df(
            timestamp=mondays,
            venue=["Threshold Cafe"] * 3,
            venue_category=["Coffee Shop"] * 3,
        )
        result = analysis_utils.get_routine_venues(swarm_df, min_occurrences=3)

        assert "Threshold Cafe" in result["venue"].values, (
            "Venue with exactly 3 visits (=min_occurrences) should be included"
        )


# ---------------------------------------------------------------------------
# get_venue_exploration_rate
# ---------------------------------------------------------------------------


class TestVenueExplorationRateFirstMonth:
    """All check-ins in the first month, all to new venues → new_venues = total unique."""

    def test_all_venues_new_in_first_month(self) -> None:
        """All visits to distinct venues in the same month are all 'new'."""
        jan_ts = [
            int(pd.Timestamp("2021-01-05").timestamp()),
            int(pd.Timestamp("2021-01-10").timestamp()),
            int(pd.Timestamp("2021-01-15").timestamp()),
        ]
        swarm_df = _make_swarm_df(
            timestamp=jan_ts,
            venue=["Venue A", "Venue B", "Venue C"],
            venue_category=["Cat A", "Cat B", "Cat C"],
        )
        result = analysis_utils.get_venue_exploration_rate(swarm_df)

        assert not result.empty, "Result should not be empty"
        jan_row = result[result["month"].dt.month == 1]
        assert not jan_row.empty, "January row should exist"
        assert jan_row.iloc[0]["new_venues"] == 3, (
            "All 3 distinct venues should be counted as new in the first month"
        )

    def test_revisits_zero_when_all_new(self) -> None:
        """No revisits when every venue is seen for the first time."""
        jan_ts = [
            int(pd.Timestamp("2021-01-05").timestamp()),
            int(pd.Timestamp("2021-01-10").timestamp()),
        ]
        swarm_df = _make_swarm_df(
            timestamp=jan_ts,
            venue=["Venue A", "Venue B"],
            venue_category=["Cat A", "Cat B"],
        )
        result = analysis_utils.get_venue_exploration_rate(swarm_df)

        jan_row = result[result["month"].dt.month == 1]
        assert jan_row.iloc[0]["revisits"] == 0, "revisits should be 0 when all venues are new"

    def test_required_columns_present(self) -> None:
        """Result must have month, new_venues, revisits, exploration_ratio columns."""
        jan_ts = [int(pd.Timestamp("2021-01-05").timestamp())]
        swarm_df = _make_swarm_df(
            timestamp=jan_ts,
            venue=["Venue A"],
            venue_category=["Cat A"],
        )
        result = analysis_utils.get_venue_exploration_rate(swarm_df)

        for col in ("month", "new_venues", "revisits", "exploration_ratio"):
            assert col in result.columns, f"Column '{col}' missing from result"


class TestVenueExplorationRateRevisitCounted:
    """Venue visited in month 1 and month 2 → month 2 has revisits >= 1."""

    def test_revisit_increments_revisit_count(self) -> None:
        """Second visit to the same venue (in a later month) must appear in revisits."""
        timestamps = [
            int(pd.Timestamp("2021-01-10").timestamp()),  # first visit — January
            int(pd.Timestamp("2021-02-10").timestamp()),  # revisit — February
        ]
        swarm_df = _make_swarm_df(
            timestamp=timestamps,
            venue=["Regulars Bar", "Regulars Bar"],
            venue_category=["Bar", "Bar"],
        )
        result = analysis_utils.get_venue_exploration_rate(swarm_df)

        feb_row = result[result["month"].dt.month == 2]
        assert not feb_row.empty, "February row should exist"
        assert feb_row.iloc[0]["revisits"] >= 1, (
            "February revisit to a January venue should be counted as revisit"
        )

    def test_revisit_not_counted_as_new(self) -> None:
        """A revisit must NOT be counted in new_venues."""
        timestamps = [
            int(pd.Timestamp("2021-01-10").timestamp()),
            int(pd.Timestamp("2021-02-10").timestamp()),
        ]
        swarm_df = _make_swarm_df(
            timestamp=timestamps,
            venue=["Regulars Bar", "Regulars Bar"],
            venue_category=["Bar", "Bar"],
        )
        result = analysis_utils.get_venue_exploration_rate(swarm_df)

        feb_row = result[result["month"].dt.month == 2]
        assert feb_row.iloc[0]["new_venues"] == 0, (
            "A revisited venue must not be counted in new_venues"
        )


# ---------------------------------------------------------------------------
# get_music_around_venue_type
# ---------------------------------------------------------------------------


class TestMusicAroundVenueTypeWindow:
    """Play 45 min after check-in is within window; 90 min after is outside."""

    def _build_inputs(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Build minimal swarm_df (coffee) and lastfm_df with two listens."""
        checkin_ts = int(pd.Timestamp("2022-03-15 12:00:00").timestamp())

        swarm_df = _make_swarm_df(
            timestamp=[checkin_ts],
            venue=["Corner Coffee"],
            venue_category=["Coffee Shop"],
        )

        # play_within: 45 min = 2700 seconds after check-in → inside 60-min window
        # play_outside: 90 min = 5400 seconds after check-in → outside 60-min window
        play_within_ts = checkin_ts + 2700
        play_outside_ts = checkin_ts + 5400

        lastfm_df = pd.DataFrame(
            {
                "timestamp": [play_within_ts, play_outside_ts],
                "artist": ["Artist A", "Artist B"],
                "track": ["Track 1", "Track 2"],
                "album": ["Album X", "Album Y"],
            }
        )
        return swarm_df, lastfm_df

    def test_play_45min_after_is_included(self) -> None:
        """A listen 45 minutes after a matching check-in must be included."""
        swarm_df, lastfm_df = self._build_inputs()
        result = analysis_utils.get_music_around_venue_type(
            swarm_df,
            lastfm_df,
            category_keywords=["coffee"],
            window_minutes=60,
        )

        assert result["listen_count"] >= 1, (
            "Listen 45 min after check-in should be within the 60-min window"
        )

    def test_play_90min_after_is_excluded(self) -> None:
        """A listen 90 minutes after a matching check-in must NOT be included."""
        swarm_df, lastfm_df = self._build_inputs()
        result = analysis_utils.get_music_around_venue_type(
            swarm_df,
            lastfm_df,
            category_keywords=["coffee"],
            window_minutes=60,
        )

        # Artist B (90-min listen) should not appear in top_artists
        top_artists = result["top_artists"]
        if not top_artists.empty:
            assert "Artist B" not in top_artists["artist"].values, (
                "Artist B (90 min away) should not appear in top_artists"
            )

    def test_listen_count_equals_one(self) -> None:
        """Only the 45-min listen should be counted; total listen_count == 1."""
        swarm_df, lastfm_df = self._build_inputs()
        result = analysis_utils.get_music_around_venue_type(
            swarm_df,
            lastfm_df,
            category_keywords=["coffee"],
            window_minutes=60,
        )

        assert result["listen_count"] == 1, (
            "Only the 45-min listen should be inside the 60-min window"
        )

    def test_required_keys_present(self) -> None:
        """Result dict must contain top_artists, top_tracks, checkin_count, listen_count."""
        swarm_df, lastfm_df = self._build_inputs()
        result = analysis_utils.get_music_around_venue_type(
            swarm_df,
            lastfm_df,
            category_keywords=["coffee"],
            window_minutes=60,
        )

        for key in ("top_artists", "top_tracks", "checkin_count", "listen_count"):
            assert key in result, f"Key '{key}' missing from result dict"

    def test_checkin_count_matches_keyword_matches(self) -> None:
        """checkin_count should equal the number of check-ins matching the keywords."""
        swarm_df, lastfm_df = self._build_inputs()
        result = analysis_utils.get_music_around_venue_type(
            swarm_df,
            lastfm_df,
            category_keywords=["coffee"],
            window_minutes=60,
        )

        assert result["checkin_count"] == 1, "Only one check-in matches 'coffee' keyword"

    def test_unmatched_keyword_gives_empty_result(self) -> None:
        """Keywords that match no venue_category → checkin_count = 0."""
        swarm_df, lastfm_df = self._build_inputs()
        result = analysis_utils.get_music_around_venue_type(
            swarm_df,
            lastfm_df,
            category_keywords=["museum"],
            window_minutes=60,
        )

        assert result["checkin_count"] == 0, (
            "No check-ins matching 'museum' should yield checkin_count=0"
        )

    def test_top_artists_dataframe_has_correct_columns(self) -> None:
        """top_artists DataFrame must have 'artist' and 'plays' columns."""
        swarm_df, lastfm_df = self._build_inputs()
        result = analysis_utils.get_music_around_venue_type(
            swarm_df,
            lastfm_df,
            category_keywords=["coffee"],
            window_minutes=60,
        )

        top_artists = result["top_artists"]
        assert isinstance(top_artists, pd.DataFrame), "top_artists must be a DataFrame"
        if not top_artists.empty:
            assert "artist" in top_artists.columns, "'artist' column missing"
            assert "plays" in top_artists.columns, "'plays' column missing"

    def test_top_tracks_dataframe_has_correct_columns(self) -> None:
        """top_tracks DataFrame must have 'track', 'artist', and 'plays' columns."""
        swarm_df, lastfm_df = self._build_inputs()
        result = analysis_utils.get_music_around_venue_type(
            swarm_df,
            lastfm_df,
            category_keywords=["coffee"],
            window_minutes=60,
        )

        top_tracks = result["top_tracks"]
        assert isinstance(top_tracks, pd.DataFrame), "top_tracks must be a DataFrame"
        if not top_tracks.empty:
            for col in ("track", "artist", "plays"):
                assert col in top_tracks.columns, f"'{col}' column missing from top_tracks"

    def test_case_insensitive_keyword_matching(self) -> None:
        """Category keyword matching must be case-insensitive."""
        checkin_ts = int(pd.Timestamp("2022-03-15 12:00:00").timestamp())
        swarm_df = _make_swarm_df(
            timestamp=[checkin_ts],
            venue=["Corner Coffee"],
            venue_category=["COFFEE SHOP"],  # uppercase category
        )
        lastfm_df = pd.DataFrame(
            {
                "timestamp": [checkin_ts + 60],
                "artist": ["Artist X"],
                "track": ["Track Z"],
                "album": ["Album W"],
            }
        )
        result = analysis_utils.get_music_around_venue_type(
            swarm_df,
            lastfm_df,
            category_keywords=["coffee"],  # lowercase keyword
            window_minutes=60,
        )

        assert result["checkin_count"] == 1, (
            "Case-insensitive matching: 'coffee' keyword should match 'COFFEE SHOP' category"
        )
