"""Tests for Subtask 8 — Life Event Detection.

Tests are RED by design — the functions under test do not exist yet.
All test DataFrames are built inline; no external files or fixtures required.

Covers:
- detect_listening_changepoints: returns Timestamps, empty df, ImportError graceful
- detect_taste_shift_points: high turnover flagged, stable period silent
- correlate_events_with_assumptions: nearby trip injects context, distant yields empty
- render_life_events: smoke test (banner when cache is None)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import analysis_utils

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(date_str: str) -> int:
    """Return unix int-seconds timestamp for an ISO date string."""
    return int(pd.Timestamp(date_str).timestamp())


def _make_play(
    artist: str,
    date_str: str,
    track: str = "Track A",
) -> dict[str, Any]:
    """Return a dict row for a single play with date_text as Timestamp."""
    return {
        "timestamp": _ts(date_str),
        "date_text": pd.Timestamp(date_str),
        "artist": artist,
        "track": track,
        "album": "Album X",
    }


def _make_df(*rows: dict[str, Any]) -> pd.DataFrame:
    """Build a DataFrame from row dicts."""
    return pd.DataFrame(list(rows))


def _weekly_df(
    start: str, end: str, artist: str = "Artist A", plays_per_week: int = 5
) -> pd.DataFrame:
    """Build a DataFrame with ``plays_per_week`` plays every 7 days between start and end."""
    rows = []
    current = pd.Timestamp(start)
    stop = pd.Timestamp(end)
    while current <= stop:
        for _ in range(plays_per_week):
            rows.append(_make_play(artist, current.strftime("%Y-%m-%d")))
        current += pd.Timedelta(days=7)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# detect_listening_changepoints
# ---------------------------------------------------------------------------


class TestDetectChangepointsReturnsTimestamps:
    """detect_listening_changepoints must return a list of pd.Timestamp."""

    def test_result_is_a_list(self) -> None:
        """Return type is list."""
        df = _weekly_df("2018-01-01", "2022-12-31")
        result = analysis_utils.detect_listening_changepoints(df)
        assert isinstance(result, list)

    def test_each_element_is_timestamp(self) -> None:
        """Every element in the non-empty result is a pd.Timestamp."""
        df = _weekly_df("2018-01-01", "2022-12-31")
        result = analysis_utils.detect_listening_changepoints(df)
        for item in result:
            assert isinstance(item, pd.Timestamp), f"Expected pd.Timestamp, got {type(item)}"


class TestDetectChangepointsEmptyDf:
    """detect_listening_changepoints on an empty DataFrame must return []."""

    def test_empty_df_returns_empty_list(self) -> None:
        """Empty DataFrame → []."""
        df = pd.DataFrame(columns=["timestamp", "date_text", "artist", "track", "album"])
        result = analysis_utils.detect_listening_changepoints(df)
        assert result == []

    def test_empty_df_no_exception(self) -> None:
        """Empty DataFrame must not raise any exception."""
        df = pd.DataFrame(columns=["timestamp", "date_text", "artist", "track", "album"])
        try:
            analysis_utils.detect_listening_changepoints(df)
        except Exception as exc:
            pytest.fail(f"Unexpected exception on empty df: {exc}")


class TestDetectChangepointsNoRuptures:
    """When ruptures is not installed, must return [] without propagating ImportError."""

    def test_importerror_returns_empty_list(self) -> None:
        """If the ruptures module is unavailable, return [] gracefully."""
        with patch.object(analysis_utils, "_get_ruptures", return_value=None):
            df = _weekly_df("2018-01-01", "2022-12-31")
            result = analysis_utils.detect_listening_changepoints(df)
        assert result == [], "Expected [] when ruptures is None/unavailable"

    def test_no_exception_propagated(self) -> None:
        """No ImportError or AttributeError may escape when ruptures is absent."""
        with patch.object(analysis_utils, "_get_ruptures", return_value=None):
            df = _weekly_df("2018-01-01", "2022-12-31")
            try:
                analysis_utils.detect_listening_changepoints(df)
            except Exception as exc:
                pytest.fail(f"Exception propagated when ruptures unavailable: {exc}")


# ---------------------------------------------------------------------------
# detect_taste_shift_points
# ---------------------------------------------------------------------------


class TestDetectTasteShiftHighTurnover:
    """Completely different artist sets in alternating windows → at least one shift detected."""

    def test_high_turnover_detected(self) -> None:
        """Top-10 artists replaced entirely → at least one shift dict returned."""
        # Block A: artists 1-10, months 1-3
        rows: list[dict[str, Any]] = []
        for month in range(1, 4):  # Jan–Mar
            for i in range(1, 11):  # 10 distinct artists
                date_str = f"2021-{month:02d}-15"
                for _ in range(10):  # 10 plays each → firmly top-10
                    rows.append(_make_play(f"Artist_A_{i}", date_str))

        # Block B: artists 11-20 (completely different), months 4-6
        for month in range(4, 7):  # Apr–Jun
            for i in range(11, 21):  # 10 completely different artists
                date_str = f"2021-{month:02d}-15"
                for _ in range(10):
                    rows.append(_make_play(f"Artist_B_{i}", date_str))

        # Block C: back to A artists, months 7-9
        for month in range(7, 10):
            for i in range(1, 11):
                date_str = f"2021-{month:02d}-15"
                for _ in range(10):
                    rows.append(_make_play(f"Artist_A_{i}", date_str))

        df = pd.DataFrame(rows)
        result = analysis_utils.detect_taste_shift_points(df)
        assert isinstance(result, list), "Result must be a list"
        assert len(result) >= 1, "Expected at least one taste shift to be detected"

    def test_each_shift_has_required_keys(self) -> None:
        """Each shift dict must contain 'date', 'jaccard_similarity', 'new_artists', 'lost_artists'."""
        rows: list[dict[str, Any]] = []
        for month in range(1, 4):
            for i in range(1, 11):
                date_str = f"2021-{month:02d}-15"
                for _ in range(10):
                    rows.append(_make_play(f"Artist_A_{i}", date_str))
        for month in range(4, 7):
            for i in range(11, 21):
                date_str = f"2021-{month:02d}-15"
                for _ in range(10):
                    rows.append(_make_play(f"Artist_B_{i}", date_str))

        df = pd.DataFrame(rows)
        result = analysis_utils.detect_taste_shift_points(df)
        if result:
            shift = result[0]
            for key in ("date", "jaccard_similarity", "new_artists", "lost_artists"):
                assert key in shift, f"Missing key '{key}' in shift dict: {shift}"

    def test_jaccard_similarity_is_float(self) -> None:
        """jaccard_similarity value must be a float between 0.0 and 1.0."""
        rows: list[dict[str, Any]] = []
        for month in range(1, 4):
            for i in range(1, 11):
                date_str = f"2021-{month:02d}-15"
                for _ in range(10):
                    rows.append(_make_play(f"Artist_A_{i}", date_str))
        for month in range(4, 7):
            for i in range(11, 21):
                date_str = f"2021-{month:02d}-15"
                for _ in range(10):
                    rows.append(_make_play(f"Artist_B_{i}", date_str))

        df = pd.DataFrame(rows)
        result = analysis_utils.detect_taste_shift_points(df)
        if result:
            sim = result[0]["jaccard_similarity"]
            assert isinstance(sim, float), f"jaccard_similarity should be float, got {type(sim)}"
            assert 0.0 <= sim <= 1.0, f"jaccard_similarity {sim} out of [0,1] range"


class TestDetectTasteShiftStablePeriod:
    """Same top-10 artists for 6 months → no shifts detected."""

    def test_stable_period_returns_empty_list(self) -> None:
        """When the same 5 artists dominate all 6 months, result must be []."""
        rows: list[dict[str, Any]] = []
        for month in range(1, 7):
            for i in range(1, 6):  # same 5 artists every month
                date_str = f"2021-{month:02d}-15"
                for _ in range(20):  # high play count per artist
                    rows.append(_make_play(f"StableArtist_{i}", date_str))

        df = pd.DataFrame(rows)
        result = analysis_utils.detect_taste_shift_points(df)
        assert isinstance(result, list), "Result must be a list"
        assert result == [], f"Expected no shifts for stable period, got {result}"


# ---------------------------------------------------------------------------
# correlate_events_with_assumptions
# ---------------------------------------------------------------------------


def _make_assumptions_with_trip(city: str, trip_start: str, trip_end: str) -> dict[str, Any]:
    """Build a minimal assumptions dict with one trip."""
    return {
        "trips": [
            {
                "city": city,
                "start": trip_start,
                "end": trip_end,
            }
        ],
        "residency": [],
        "holidays": [],
        "defaults": {
            "city": "Unknown",
            "state": "XX",
            "country": "Unknown",
            "lat": 0.0,
            "lng": 0.0,
            "timezone": "UTC",
        },
    }


class TestCorrelateEventsWithTrip:
    """A changepoint within 25 days of a trip start → context references city."""

    def test_context_is_nonempty_for_nearby_changepoint(self) -> None:
        """Changepoint 10 days before trip start is within correlation window → non-empty context."""
        trip_start = "2021-06-01"
        changepoint_date = "2021-05-22"  # 10 days before trip start

        changepoints = [pd.Timestamp(changepoint_date)]
        taste_shifts: list[dict[str, Any]] = []
        assumptions = _make_assumptions_with_trip("Paris", trip_start, "2021-06-15")

        result = analysis_utils.correlate_events_with_assumptions(
            changepoints, taste_shifts, assumptions, correlation_days=30
        )

        assert isinstance(result, list), "Result must be a list"
        assert len(result) >= 1, "Expected at least one event in result"
        event = result[0]
        assert "context" in event, "Event must have 'context' key"
        context = event["context"]
        # context should reference the city name or be truthy
        assert context, f"Expected non-empty context for nearby trip, got: {context!r}"

    def test_context_references_city_name(self) -> None:
        """Context string/value contains the trip city name."""
        trip_start = "2021-06-01"
        changepoint_date = "2021-05-22"

        changepoints = [pd.Timestamp(changepoint_date)]
        taste_shifts: list[dict[str, Any]] = []
        assumptions = _make_assumptions_with_trip("Paris", trip_start, "2021-06-15")

        result = analysis_utils.correlate_events_with_assumptions(
            changepoints, taste_shifts, assumptions, correlation_days=30
        )

        event = result[0]
        context = event["context"]
        # Context is either a string or list — check city name presence
        if isinstance(context, str):
            assert "Paris" in context, f"City 'Paris' not found in context: {context!r}"
        elif isinstance(context, list):
            city_mentioned = any("Paris" in str(item) for item in context)
            assert city_mentioned, f"City 'Paris' not referenced in context list: {context}"

    def test_event_has_required_keys(self) -> None:
        """Each returned event must have 'date', 'type', and 'context' keys."""
        changepoints = [pd.Timestamp("2021-05-22")]
        taste_shifts: list[dict[str, Any]] = []
        assumptions = _make_assumptions_with_trip("Tokyo", "2021-06-01", "2021-06-15")

        result = analysis_utils.correlate_events_with_assumptions(
            changepoints, taste_shifts, assumptions, correlation_days=30
        )

        assert result, "Expected at least one event"
        event = result[0]
        for key in ("date", "type", "context"):
            assert key in event, f"Missing key '{key}' in event dict: {event}"

    def test_changepoint_event_type(self) -> None:
        """Events derived from changepoints have type == 'changepoint'."""
        changepoints = [pd.Timestamp("2021-05-22")]
        taste_shifts: list[dict[str, Any]] = []
        assumptions = _make_assumptions_with_trip("Berlin", "2021-06-01", "2021-06-15")

        result = analysis_utils.correlate_events_with_assumptions(
            changepoints, taste_shifts, assumptions, correlation_days=30
        )

        changepoint_events = [e for e in result if e.get("type") == "changepoint"]
        assert changepoint_events, "Expected at least one event with type == 'changepoint'"


class TestCorrelateEventsNoContext:
    """Changepoint far from any assumption → context is empty string or empty list."""

    def test_distant_changepoint_has_empty_context(self) -> None:
        """Changepoint 200 days from any trip → context is falsy."""
        # Trip is far in the future relative to changepoint
        trip_start = "2022-01-01"
        changepoint_date = "2021-01-01"  # ~365 days before trip

        changepoints = [pd.Timestamp(changepoint_date)]
        taste_shifts: list[dict[str, Any]] = []
        assumptions = _make_assumptions_with_trip("Sydney", trip_start, "2022-01-15")

        result = analysis_utils.correlate_events_with_assumptions(
            changepoints, taste_shifts, assumptions, correlation_days=30
        )

        assert isinstance(result, list), "Result must be a list"
        assert len(result) >= 1, "Expected at least one event for the changepoint"
        event = result[0]
        assert "context" in event, "Event must have 'context' key"
        context = event["context"]
        # context must be falsy when nothing is nearby
        assert not context, f"Expected empty context for distant changepoint, got: {context!r}"

    def test_empty_assumptions_gives_empty_context(self) -> None:
        """With no trips or residency assumptions, all events have empty context."""
        changepoints = [pd.Timestamp("2021-06-01")]
        taste_shifts: list[dict[str, Any]] = []
        assumptions: dict[str, Any] = {
            "trips": [],
            "residency": [],
            "holidays": [],
            "defaults": {
                "city": "Unknown",
                "state": "XX",
                "country": "Unknown",
                "lat": 0.0,
                "lng": 0.0,
                "timezone": "UTC",
            },
        }

        result = analysis_utils.correlate_events_with_assumptions(
            changepoints, taste_shifts, assumptions, correlation_days=30
        )

        for event in result:
            context = event.get("context", "")
            assert not context, f"Expected empty context with no assumptions, got: {context!r}"


# ---------------------------------------------------------------------------
# render_life_events — smoke test
# ---------------------------------------------------------------------------


class TestRenderLifeEventsSmoke:
    """render_life_events must run without exceptions (all st.* calls mocked)."""

    def test_render_shows_banner_when_no_cache(self) -> None:
        """When load_deep_life_events_cache returns None, the banner is shown."""
        with (
            patch("analysis_utils.load_deep_life_events_cache", return_value=None),
            patch("pages.life_events.st") as mock_st,
        ):
            mock_st.stop = MagicMock(side_effect=SystemExit("st.stop"))
            mock_st.title = MagicMock()
            mock_st.info = MagicMock()

            from pages import life_events

            try:
                life_events.render_life_events()
            except SystemExit:
                pass  # st.stop() is expected when cache is None
            except Exception as exc:
                pytest.fail(f"Unexpected exception during render with no cache: {exc}")

    def test_render_calls_st_stop_when_no_cache(self) -> None:
        """When cache is None, st.stop() must be called."""
        stop_called = False

        def fake_stop() -> None:
            nonlocal stop_called
            stop_called = True
            raise SystemExit("st.stop")

        with (
            patch("analysis_utils.load_deep_life_events_cache", return_value=None),
            patch("pages.life_events.st") as mock_st,
        ):
            mock_st.stop = fake_stop
            mock_st.title = MagicMock()
            mock_st.info = MagicMock()

            from pages import life_events

            try:
                life_events.render_life_events()
            except SystemExit:
                pass

            assert stop_called, "st.stop() must be called when cache is None"

    def test_render_runs_without_exception_with_cache(self) -> None:
        """When a valid (empty) cache is present, render_life_events runs without raising."""
        fake_cache: dict[str, Any] = {
            "changepoints": [],
            "taste_shifts": [],
            "events": [],
        }

        mock_tab = MagicMock()
        mock_tab.__enter__ = MagicMock(return_value=mock_tab)
        mock_tab.__exit__ = MagicMock(return_value=False)

        with (
            patch("analysis_utils.load_deep_life_events_cache", return_value=fake_cache),
            patch("pages.life_events.st") as mock_st,
        ):
            mock_st.title = MagicMock()
            mock_st.tabs = MagicMock(return_value=[mock_tab, mock_tab, mock_tab])
            mock_st.subheader = MagicMock()
            mock_st.info = MagicMock()
            mock_st.dataframe = MagicMock()
            mock_st.line_chart = MagicMock()
            mock_st.stop = MagicMock()
            mock_st.columns = MagicMock(return_value=[MagicMock(), MagicMock()])

            from pages import life_events

            try:
                life_events.render_life_events()
            except Exception as exc:
                pytest.fail(f"render_life_events raised with valid cache: {exc}")
