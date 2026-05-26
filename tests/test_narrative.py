"""Tests for Subtask 9 — Narrative Text Generation Engine.

Tests are RED by design — narrative.py does not exist yet.
All test DataFrames and fixture dicts are built inline; no external files needed.

Covers:
- narrative_artist_relationship: obsession arc (spike-then-fade language),
  perennial arc (longevity language)
- narrative_year_in_review: year number appears in output
- narrative_city_soundtrack: city name appears in output
- narrative_era_comparison: both era labels appear in output
- narrative_life_event: month name (or year) appears in output
- generate_full_autobiography: returns Markdown with ## headers,
  gracefully handles empty DataFrame
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Lazy import helper — keeps tests collectable even when narrative.py is absent
# ---------------------------------------------------------------------------


def _get_narrative() -> Any:
    """Import and return the narrative module, raising ImportError if missing."""
    if "narrative" in sys.modules:
        return sys.modules["narrative"]
    return importlib.import_module("narrative")


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
    album: str = "Album X",
) -> dict[str, Any]:
    """Return a single-play row dict with date_text as Timestamp."""
    return {
        "timestamp": _ts(date_str),
        "date_text": pd.Timestamp(date_str),
        "artist": artist,
        "track": track,
        "album": album,
        "country": "US",
        "state": "CA",
    }


def _obsession_arc() -> dict[str, Any]:
    """Return an arc dict representing an obsession arc_type."""
    return {
        "artist": "TestBand",
        "arc_type": "obsession",
        "discovery_date": pd.Timestamp("2018-03-01"),
        "peak_month": pd.Timestamp("2018-06-01"),
        "last_play": pd.Timestamp("2019-01-15"),
        "total_plays": 150,
        "peak_plays": 80,
        "peak_ratio": 4.5,
    }


def _perennial_arc() -> dict[str, Any]:
    """Return an arc dict representing a perennial arc_type."""
    return {
        "artist": "LongRunnerBand",
        "arc_type": "perennial",
        "discovery_date": pd.Timestamp("2010-01-01"),
        "peak_month": pd.Timestamp("2015-07-01"),
        "last_play": pd.Timestamp("2024-11-01"),
        "total_plays": 900,
        "peak_plays": 120,
        "peak_ratio": 1.4,
    }


def _minimal_2019_df() -> pd.DataFrame:
    """Build a small DataFrame with plays concentrated in 2019."""
    dates_and_artists = [
        ("2019-01-10", "Artist Alpha"),
        ("2019-01-20", "Artist Alpha"),
        ("2019-02-14", "Artist Beta"),
        ("2019-04-01", "Artist Alpha"),
        ("2019-04-05", "Artist Alpha"),
        ("2019-04-10", "Artist Alpha"),
        ("2019-04-15", "Artist Alpha"),
        ("2019-07-04", "Artist Beta"),
        ("2019-09-18", "Artist Gamma"),
        ("2019-12-25", "Artist Alpha"),
    ]
    return pd.DataFrame([_make_play(artist, d) for d, artist in dates_and_artists])


def _minimal_full_df() -> pd.DataFrame:
    """Build a minimal multi-year DataFrame for autobiography orchestration tests."""
    rows = []
    for year in range(2015, 2020):
        for month in [1, 4, 7, 10]:
            for day in [5, 15, 25]:
                rows.append(_make_play("BandA", f"{year}-{month:02d}-{day:02d}"))
                rows.append(_make_play("BandB", f"{year}-{month:02d}-{day:02d}", track="Track B"))
    return pd.DataFrame(rows)


def _minimal_assumptions() -> dict[str, Any]:
    """Return a minimal assumptions dict suitable for generate_full_autobiography."""
    return {
        "defaults": {"city": "London"},
        "residency": [
            {
                "city": "London",
                "start": "2015-01-01",
                "end": "2017-12-31",
                "country": "UK",
            }
        ],
        "trips": [],
        "holidays": [],
    }


def _soundtrack_dict(city: str = "Rome") -> dict[str, Any]:
    """Return a minimal city soundtrack dict."""
    return {
        "city": city,
        "top_artists": pd.DataFrame({"artist": ["Radiohead", "Portishead"], "plays": [30, 15]}),
        "play_count": 45,
        "period_start": pd.Timestamp("2016-06-01"),
        "period_end": pd.Timestamp("2016-06-30"),
    }


def _event_dict(date: pd.Timestamp) -> dict[str, Any]:
    """Return a minimal life event dict."""
    return {
        "date": date,
        "type": "changepoint",
        "context": "Moved to London",
    }


def _make_era_tops() -> dict[str, pd.DataFrame]:
    return {
        "Maryland": pd.DataFrame({"artist": ["Radiohead", "Portishead"], "plays": [50, 30]}),
        "London": pd.DataFrame({"artist": ["Radiohead", "LCD Soundsystem"], "plays": [60, 40]}),
    }


def _make_jaccard() -> pd.DataFrame:
    return pd.DataFrame(
        {"Maryland": [1.0, 0.5], "London": [0.5, 1.0]},
        index=["Maryland", "London"],
    )


# ---------------------------------------------------------------------------
# narrative_artist_relationship — obsession arc
# ---------------------------------------------------------------------------


class TestNarrativeArtistRelationshipObsession:
    def test_output_is_string(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_artist_relationship(_obsession_arc())
        assert isinstance(result, str)

    def test_output_nonempty(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_artist_relationship(_obsession_arc())
        assert len(result.strip()) > 0

    def test_contains_artist_name(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_artist_relationship(_obsession_arc())
        assert "TestBand" in result

    def test_obsession_rise_or_fade_language(self) -> None:
        """Output must contain language indicating discovery and/or spike-then-fade."""
        nar = _get_narrative()
        result = nar.narrative_artist_relationship(_obsession_arc()).lower()
        discovery_words = {"discover", "found", "first", "began", "started", "came across"}
        fade_words = {"fade", "faded", "declined", "silence", "quiet", "peak", "obsess", "intense"}
        has_discovery = any(w in result for w in discovery_words)
        has_fade = any(w in result for w in fade_words)
        assert has_discovery or has_fade, (
            f"Expected obsession language (discovery or fade) in: {result!r}"
        )


# ---------------------------------------------------------------------------
# narrative_artist_relationship — perennial arc
# ---------------------------------------------------------------------------


class TestNarrativeArtistRelationshipPerennial:
    def test_output_is_string(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_artist_relationship(_perennial_arc())
        assert isinstance(result, str)

    def test_contains_artist_name(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_artist_relationship(_perennial_arc())
        assert "LongRunnerBand" in result

    def test_perennial_longevity_language(self) -> None:
        """Output must contain language indicating consistent long-term loyalty."""
        nar = _get_narrative()
        result = nar.narrative_artist_relationship(_perennial_arc()).lower()
        longevity_words = {
            "never stopped",
            "consistently",
            "year",
            "always",
            "constant",
            "loyal",
            "decade",
            "long",
            "throughout",
            "still",
            "enduring",
            "perennial",
        }
        has_longevity = any(w in result for w in longevity_words)
        assert has_longevity, f"Expected longevity language in perennial narrative: {result!r}"


# ---------------------------------------------------------------------------
# narrative_year_in_review — year appears in output
# ---------------------------------------------------------------------------


class TestNarrativeYearInReview:
    def test_output_is_string(self) -> None:
        nar = _get_narrative()
        df = _minimal_2019_df()
        result = nar.narrative_year_in_review(df, 2019)
        assert isinstance(result, str)

    def test_output_nonempty(self) -> None:
        nar = _get_narrative()
        df = _minimal_2019_df()
        result = nar.narrative_year_in_review(df, 2019)
        assert len(result.strip()) > 0

    def test_mentions_year(self) -> None:
        nar = _get_narrative()
        df = _minimal_2019_df()
        result = nar.narrative_year_in_review(df, 2019)
        assert "2019" in result, f"Expected '2019' in: {result!r}"

    def test_year_argument_is_used(self) -> None:
        """The year passed in must appear in the output (not some other year)."""
        nar = _get_narrative()
        df = _minimal_2019_df()
        result = nar.narrative_year_in_review(df, 2019)
        assert "2019" in result


# ---------------------------------------------------------------------------
# narrative_city_soundtrack — city appears in output
# ---------------------------------------------------------------------------


class TestNarrativeCitySoundtrack:
    def test_output_is_string(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_city_soundtrack(_soundtrack_dict("Rome"))
        assert isinstance(result, str)

    def test_output_nonempty(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_city_soundtrack(_soundtrack_dict("Rome"))
        assert len(result.strip()) > 0

    def test_mentions_rome(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_city_soundtrack(_soundtrack_dict("Rome"))
        assert "Rome" in result, f"Expected 'Rome' in: {result!r}"

    def test_mentions_different_city(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_city_soundtrack(_soundtrack_dict("Tokyo"))
        assert "Tokyo" in result, f"Expected 'Tokyo' in: {result!r}"


# ---------------------------------------------------------------------------
# narrative_era_comparison — both era labels appear
# ---------------------------------------------------------------------------


class TestNarrativeEraComparison:
    def test_output_is_string(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_era_comparison(
            _make_era_tops(), _make_jaccard(), "Maryland", "London"
        )
        assert isinstance(result, str)

    def test_mentions_era_a(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_era_comparison(
            _make_era_tops(), _make_jaccard(), "Maryland", "London"
        )
        assert "Maryland" in result, f"Expected 'Maryland' in: {result!r}"

    def test_mentions_era_b(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_era_comparison(
            _make_era_tops(), _make_jaccard(), "Maryland", "London"
        )
        assert "London" in result, f"Expected 'London' in: {result!r}"

    def test_mentions_both_eras(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_era_comparison(
            _make_era_tops(), _make_jaccard(), "Maryland", "London"
        )
        assert "Maryland" in result and "London" in result, (
            f"Expected both era labels in: {result!r}"
        )


# ---------------------------------------------------------------------------
# narrative_life_event — month name or year appears in output
# ---------------------------------------------------------------------------


class TestNarrativeLifeEvent:
    def test_output_is_string(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_life_event(_event_dict(pd.Timestamp("2015-03-01")))
        assert isinstance(result, str)

    def test_output_nonempty(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_life_event(_event_dict(pd.Timestamp("2015-03-01")))
        assert len(result.strip()) > 0

    def test_mentions_march_or_2015(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_life_event(_event_dict(pd.Timestamp("2015-03-01")))
        has_month = "March" in result
        has_year = "2015" in result
        assert has_month or has_year, f"Expected 'March' or '2015' in: {result!r}"

    def test_mentions_november_or_2018(self) -> None:
        nar = _get_narrative()
        result = nar.narrative_life_event(_event_dict(pd.Timestamp("2018-11-15")))
        has_month = "November" in result
        has_year = "2018" in result
        assert has_month or has_year, f"Expected 'November' or '2018' in: {result!r}"


# ---------------------------------------------------------------------------
# generate_full_autobiography — Markdown output with ## headers
# ---------------------------------------------------------------------------


class TestGenerateFullAutobiography:
    def test_output_is_string(self) -> None:
        nar = _get_narrative()
        result = nar.generate_full_autobiography(_minimal_full_df(), _minimal_assumptions())
        assert isinstance(result, str)

    def test_output_nonempty(self) -> None:
        nar = _get_narrative()
        result = nar.generate_full_autobiography(_minimal_full_df(), _minimal_assumptions())
        assert len(result.strip()) > 0

    def test_returns_markdown_with_section_headers(self) -> None:
        """Output must contain at least one ## Markdown section header."""
        nar = _get_narrative()
        result = nar.generate_full_autobiography(_minimal_full_df(), _minimal_assumptions())
        assert "##" in result, (
            f"Expected '##' Markdown headers in autobiography output. Got:\n{result[:500]!r}"
        )

    def test_empty_data_does_not_raise(self) -> None:
        """An empty DataFrame must not raise an exception."""
        nar = _get_narrative()
        empty_df = pd.DataFrame(
            columns=["timestamp", "date_text", "artist", "track", "album", "country", "state"]
        )
        try:
            result = nar.generate_full_autobiography(empty_df, _minimal_assumptions())
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"generate_full_autobiography raised with empty df: {exc}")
        else:
            assert isinstance(result, str)
            assert len(result.strip()) > 0, "Expected a non-empty fallback string for empty data"

    def test_empty_data_returns_graceful_string(self) -> None:
        """Fallback for empty df must be a meaningful non-empty string."""
        nar = _get_narrative()
        empty_df = pd.DataFrame(
            columns=["timestamp", "date_text", "artist", "track", "album", "country", "state"]
        )
        result = nar.generate_full_autobiography(empty_df, _minimal_assumptions())
        assert len(result.strip()) >= 10, f"Fallback string too short for empty data: {result!r}"

    def test_swarm_df_none_is_accepted(self) -> None:
        """swarm_df=None must not raise and output must contain ## headers."""
        nar = _get_narrative()
        try:
            result = nar.generate_full_autobiography(
                _minimal_full_df(), _minimal_assumptions(), swarm_df=None
            )
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"generate_full_autobiography raised with swarm_df=None: {exc}")
        else:
            assert "##" in result
