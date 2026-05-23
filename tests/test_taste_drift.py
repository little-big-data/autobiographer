"""Tests for Subtask 5 — Geographic Taste Drift.

Covers:
- get_era_top_artists: date filtering, empty era
- get_era_jaccard_similarity: identical sets, disjoint sets, partial overlap
- get_era_defining_artists: exclusivity threshold, min_plays filter
- get_taste_evolution_timeline: column presence
- render_taste_drift: smoke test (banner when cache is None)
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(date_str: str) -> int:
    """Convert an ISO date string to a unix timestamp integer (seconds)."""
    return int(pd.Timestamp(date_str).timestamp())


def _make_play(
    artist: str,
    date_str: str,
    track: str = "Track A",
    album: str = "Album X",
) -> dict:
    """Return a dict row for a single play.

    Args:
        artist: Artist name.
        date_str: ISO date string (e.g. "2020-01-15").
        track: Track title.
        album: Album title.

    Returns:
        Dict with ``timestamp``, ``artist``, ``track``, ``album`` keys.
    """
    return {"timestamp": _ts(date_str), "artist": artist, "track": track, "album": album}


def _df(*rows: dict) -> pd.DataFrame:
    """Build a DataFrame from a sequence of row dicts."""
    return pd.DataFrame(list(rows))


def _minimal_assumptions(
    start: str = "2010-01-01",
    end: str = "2012-12-31",
    city: str = "TestCity",
) -> dict:
    """Return a minimal assumptions dict with one residency period.

    Args:
        start: Residency start date as "YYYY-MM-DD".
        end: Residency end date as "YYYY-MM-DD".
        city: City name.

    Returns:
        Dict with ``residency`` key containing one period.
    """
    return {
        "residency": [
            {
                "start": start,
                "end": end,
                "city": city,
                "state": "TC",
                "country": "US",
                "lat": 0,
                "lng": 0,
            }
        ]
    }


# ---------------------------------------------------------------------------
# get_era_top_artists
# ---------------------------------------------------------------------------


class TestEraTopArtistsDateFiltering(unittest.TestCase):
    """Plays outside the residency date range must be excluded."""

    def setUp(self) -> None:
        from analysis_utils import get_era_top_artists

        self.func = get_era_top_artists
        self.assumptions = _minimal_assumptions(
            start="2010-01-01", end="2012-12-31", city="TestCity"
        )

        # Inside the era (2011-06-15) — should be counted
        inside_row = _make_play("InsideArtist", "2011-06-15")
        # Outside the era (2015-03-01) — should be excluded
        outside_row = _make_play("OutsideArtist", "2015-03-01")
        self.df = pd.DataFrame([inside_row, outside_row])

    def test_outside_era_artist_excluded(self) -> None:
        result = self.func(self.df, self.assumptions)
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 1, "Expected exactly one era key")
        era_df = next(iter(result.values()))
        self.assertIsInstance(era_df, pd.DataFrame)
        artist_names = era_df["artist"].tolist() if "artist" in era_df.columns else []
        self.assertNotIn(
            "OutsideArtist",
            artist_names,
            "OutsideArtist (play in 2015) must not appear in the 2010-2012 era",
        )

    def test_inside_era_artist_included(self) -> None:
        result = self.func(self.df, self.assumptions)
        era_df = next(iter(result.values()))
        artist_names = era_df["artist"].tolist() if "artist" in era_df.columns else []
        self.assertIn(
            "InsideArtist",
            artist_names,
            "InsideArtist (play in 2011) must appear in the 2010-2012 era",
        )

    def test_result_dataframe_has_required_columns(self) -> None:
        result = self.func(self.df, self.assumptions)
        era_df = next(iter(result.values()))
        for col in ("artist", "plays"):
            self.assertIn(col, era_df.columns, f"Column '{col}' missing from era DataFrame")

    def test_era_label_contains_city_and_years(self) -> None:
        result = self.func(self.df, self.assumptions)
        era_label = next(iter(result.keys()))
        self.assertIn("TestCity", era_label, "Era label must contain the city name")
        self.assertIn("2010", era_label, "Era label must contain the start year")
        self.assertIn("2012", era_label, "Era label must contain the end year")


class TestEraTopArtistsEmptyEra(unittest.TestCase):
    """A residency period with zero plays must return an empty DataFrame."""

    def test_empty_era_returns_empty_dataframe(self) -> None:
        from analysis_utils import get_era_top_artists

        # All plays are before the era window
        df = pd.DataFrame(
            [
                _make_play("SomeArtist", "2005-06-01"),
                _make_play("OtherArtist", "2006-03-15"),
            ]
        )
        assumptions = _minimal_assumptions(start="2010-01-01", end="2012-12-31")
        result = get_era_top_artists(df, assumptions)

        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 1, "Expected exactly one era key")
        era_df = next(iter(result.values()))
        self.assertIsInstance(era_df, pd.DataFrame)
        self.assertTrue(era_df.empty, "Era with no plays must return an empty DataFrame")


# ---------------------------------------------------------------------------
# get_era_jaccard_similarity
# ---------------------------------------------------------------------------


class TestJaccardSimilarityIdenticalSets(unittest.TestCase):
    """Two eras with identical artist sets → Jaccard similarity = 1.0."""

    def test_identical_sets_give_similarity_one(self) -> None:
        from analysis_utils import get_era_jaccard_similarity

        shared_artists = ["Artist A", "Artist B", "Artist C"]
        era_a = pd.DataFrame({"artist": shared_artists, "plays": [10, 8, 6]})
        era_b = pd.DataFrame({"artist": shared_artists, "plays": [5, 7, 3]})

        era_tops = {"Era A (2010-2012)": era_a, "Era B (2013-2015)": era_b}
        result = get_era_jaccard_similarity(era_tops)

        self.assertIsInstance(result, pd.DataFrame)
        sim = result.loc["Era A (2010-2012)", "Era B (2013-2015)"]
        self.assertAlmostEqual(
            float(sim),
            1.0,
            places=5,
            msg="Identical artist sets must have Jaccard similarity = 1.0",
        )


class TestJaccardSimilarityDisjointSets(unittest.TestCase):
    """Two eras with no overlapping artists → Jaccard similarity = 0.0."""

    def test_disjoint_sets_give_similarity_zero(self) -> None:
        from analysis_utils import get_era_jaccard_similarity

        era_a = pd.DataFrame({"artist": ["Artist A", "Artist B"], "plays": [10, 8]})
        era_b = pd.DataFrame({"artist": ["Artist C", "Artist D"], "plays": [5, 7]})

        era_tops = {"Era A (2010-2012)": era_a, "Era B (2013-2015)": era_b}
        result = get_era_jaccard_similarity(era_tops)

        self.assertIsInstance(result, pd.DataFrame)
        sim = result.loc["Era A (2010-2012)", "Era B (2013-2015)"]
        self.assertAlmostEqual(
            float(sim),
            0.0,
            places=5,
            msg="Completely disjoint artist sets must have Jaccard similarity = 0.0",
        )


class TestJaccardSimilarityPartialOverlap(unittest.TestCase):
    """Two eras sharing half their artists → Jaccard similarity = 0.5."""

    def test_half_overlap_gives_similarity_point_five(self) -> None:
        from analysis_utils import get_era_jaccard_similarity

        # Era A: {A, B}; Era B: {B, C}
        # Intersection = {B}; Union = {A, B, C} → Jaccard = 1/3
        # Use {A, B, C} vs {B, C, D}: intersection={B,C}, union={A,B,C,D} → Jaccard = 2/4 = 0.5
        era_a = pd.DataFrame({"artist": ["A", "B", "C"], "plays": [10, 8, 6]})
        era_b = pd.DataFrame({"artist": ["B", "C", "D"], "plays": [5, 7, 9]})

        era_tops = {"Era A": era_a, "Era B": era_b}
        result = get_era_jaccard_similarity(era_tops)

        sim = float(result.loc["Era A", "Era B"])
        self.assertAlmostEqual(
            sim,
            0.5,
            places=5,
            msg=f"Expected Jaccard similarity 0.5 but got {sim}",
        )

    def test_result_is_square_dataframe(self) -> None:
        from analysis_utils import get_era_jaccard_similarity

        era_a = pd.DataFrame({"artist": ["A", "B"], "plays": [10, 8]})
        era_b = pd.DataFrame({"artist": ["B", "C"], "plays": [5, 7]})
        era_tops = {"Era A": era_a, "Era B": era_b}
        result = get_era_jaccard_similarity(era_tops)

        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(
            list(result.index),
            list(result.columns),
            "Result must be a square DataFrame with matching index and columns",
        )

    def test_diagonal_is_one(self) -> None:
        from analysis_utils import get_era_jaccard_similarity

        era_a = pd.DataFrame({"artist": ["A", "B"], "plays": [10, 8]})
        era_b = pd.DataFrame({"artist": ["C", "D"], "plays": [5, 7]})
        era_tops = {"Era A": era_a, "Era B": era_b}
        result = get_era_jaccard_similarity(era_tops)

        for label in result.index:
            diag_val = float(result.loc[label, label])
            self.assertAlmostEqual(
                diag_val,
                1.0,
                places=5,
                msg=f"Diagonal entry for '{label}' must be 1.0 (era vs itself)",
            )


# ---------------------------------------------------------------------------
# get_era_defining_artists
# ---------------------------------------------------------------------------


class TestEraDefiningArtistsExclusivity(unittest.TestCase):
    """Artist with 90% of plays in one era appears in that era's defining artists."""

    def setUp(self) -> None:
        from analysis_utils import get_era_defining_artists

        self.func = get_era_defining_artists

        # Two eras: 2010-2012 and 2013-2015
        self.assumptions = {
            "residency": [
                {
                    "start": "2010-01-01",
                    "end": "2012-12-31",
                    "city": "CityA",
                    "state": "CA",
                    "country": "US",
                    "lat": 0,
                    "lng": 0,
                },
                {
                    "start": "2013-01-01",
                    "end": "2015-12-31",
                    "city": "CityB",
                    "state": "CB",
                    "country": "US",
                    "lat": 0,
                    "lng": 0,
                },
            ]
        }

        # "ExclusiveArtist" has 18 plays in era 1 (2010-2012) and 2 in era 2 (2013-2015)
        # → 90% in era 1, above the 0.8 threshold
        rows = [_make_play("ExclusiveArtist", f"201{y}-06-01") for y in range(3) for _ in range(6)]
        rows += [
            _make_play("ExclusiveArtist", "2013-06-01"),
            _make_play("ExclusiveArtist", "2014-06-01"),
        ]
        # "SharedArtist" has 50/50 split — should NOT be defining for either era
        rows += [_make_play("SharedArtist", "2011-06-01") for _ in range(5)]
        rows += [_make_play("SharedArtist", "2014-06-01") for _ in range(5)]
        self.df = pd.DataFrame(rows)

    def test_exclusive_artist_in_era1_defining_list(self) -> None:
        result = self.func(self.df, self.assumptions, exclusivity_threshold=0.8, min_plays=10)
        self.assertIsInstance(result, dict)

        era1_keys = [k for k in result if "CityA" in k]
        self.assertTrue(len(era1_keys) > 0, "Expected at least one era key containing 'CityA'")
        era1_artists = result[era1_keys[0]]

        self.assertIn(
            "ExclusiveArtist",
            era1_artists,
            "ExclusiveArtist (90% plays in era 1) must appear in era 1 defining artists",
        )

    def test_shared_artist_not_in_any_defining_list(self) -> None:
        result = self.func(self.df, self.assumptions, exclusivity_threshold=0.8, min_plays=10)
        for era_label, artists in result.items():
            self.assertNotIn(
                "SharedArtist",
                artists,
                f"SharedArtist (50/50 split) must not appear in '{era_label}' defining artists",
            )


class TestEraDefiningArtistsMinPlaysFilter(unittest.TestCase):
    """Artist with only 5 total plays is excluded when min_plays=10."""

    def test_low_play_artist_excluded(self) -> None:
        from analysis_utils import get_era_defining_artists

        assumptions = _minimal_assumptions(start="2010-01-01", end="2012-12-31")

        # Artist with 5 plays — all in the era (100% concentration)
        rows = [_make_play("RareArtist", f"2010-0{m}-01") for m in range(1, 6)]
        df = pd.DataFrame(rows)

        result = get_era_defining_artists(df, assumptions, exclusivity_threshold=0.8, min_plays=10)

        all_defining = [a for artists in result.values() for a in artists]
        self.assertNotIn(
            "RareArtist",
            all_defining,
            "RareArtist (only 5 total plays) must be excluded when min_plays=10",
        )


# ---------------------------------------------------------------------------
# get_taste_evolution_timeline
# ---------------------------------------------------------------------------


class TestTasteEvolutionTimelineColumns(unittest.TestCase):
    """Result DataFrame must have columns: month, artist, rank, plays."""

    def test_required_columns_present(self) -> None:
        from analysis_utils import get_taste_evolution_timeline

        assumptions = _minimal_assumptions(start="2010-01-01", end="2014-12-31")

        # Build 2 years of play data so rolling windows can compute
        rows = []
        for year in range(2010, 2013):
            for month in range(1, 13):
                for i in range(1, 6):
                    rows.append(_make_play(f"Artist{i}", f"{year}-{month:02d}-15"))
        df = pd.DataFrame(rows)

        result = get_taste_evolution_timeline(df, assumptions, window_months=6)

        self.assertIsInstance(result, pd.DataFrame)
        for col in ("month", "artist", "rank", "plays"):
            self.assertIn(
                col,
                result.columns,
                f"Column '{col}' missing from taste evolution timeline",
            )

    def test_result_is_not_empty_for_sufficient_data(self) -> None:
        from analysis_utils import get_taste_evolution_timeline

        assumptions = _minimal_assumptions(start="2010-01-01", end="2014-12-31")

        rows = []
        for year in range(2010, 2013):
            for month in range(1, 13):
                for i in range(1, 6):
                    rows.append(_make_play(f"Artist{i}", f"{year}-{month:02d}-15"))
        df = pd.DataFrame(rows)

        result = get_taste_evolution_timeline(df, assumptions, window_months=6)
        self.assertFalse(result.empty, "Timeline must not be empty when there is sufficient data")

    def test_rank_column_contains_positive_integers(self) -> None:
        from analysis_utils import get_taste_evolution_timeline

        assumptions = _minimal_assumptions(start="2010-01-01", end="2014-12-31")

        rows = []
        for year in range(2010, 2013):
            for month in range(1, 13):
                for i in range(1, 6):
                    rows.append(_make_play(f"Artist{i}", f"{year}-{month:02d}-15"))
        df = pd.DataFrame(rows)

        result = get_taste_evolution_timeline(df, assumptions, window_months=6)
        if not result.empty:
            self.assertTrue(
                (result["rank"] >= 1).all(),
                "All rank values must be >= 1",
            )


# ---------------------------------------------------------------------------
# render_taste_drift smoke test
# ---------------------------------------------------------------------------


class TestRenderTasteDriftSmoke(unittest.TestCase):
    """render_taste_drift() must run without exception; calls banner when cache is None."""

    def test_render_taste_drift_shows_banner_when_no_cache(self) -> None:
        """When load_deep_taste_drift_cache returns None, banner function is called."""
        from pages.taste_drift import render_taste_drift

        banner_mock = MagicMock()

        with (
            patch(
                "pages.taste_drift.load_deep_taste_drift_cache",
                return_value=None,
            ),
            patch(
                "pages.taste_drift._deep_analysis_not_computed_banner",
                banner_mock,
            ),
            patch("pages.taste_drift.st") as mock_st,
        ):
            mock_st.stop = MagicMock()
            render_taste_drift()

        banner_mock.assert_called_once()
        call_args = banner_mock.call_args
        first_arg = call_args[0][0] if call_args[0] else ""
        self.assertIn(
            "Geographic Taste Drift",
            first_arg,
            "Banner must be called with the analysis name 'Geographic Taste Drift'",
        )

    def test_render_taste_drift_calls_st_stop_when_no_cache(self) -> None:
        """When cache is None, st.stop() must be called to halt rendering."""
        from pages.taste_drift import render_taste_drift

        with (
            patch(
                "pages.taste_drift.load_deep_taste_drift_cache",
                return_value=None,
            ),
            patch("pages.taste_drift._deep_analysis_not_computed_banner"),
            patch("pages.taste_drift.st") as mock_st,
        ):
            mock_st.stop = MagicMock()
            render_taste_drift()

        mock_st.stop.assert_called()

    def test_render_taste_drift_runs_without_exception_with_cache(self) -> None:
        """When cache is present, render_taste_drift() runs without raising."""
        from pages.taste_drift import render_taste_drift

        minimal_cache: dict = {
            "era_tops": {},
            "jaccard": {},
            "defining_artists": {},
            "timeline": [],
        }

        # Provide enough tab mocks for whatever tab structure the page uses
        tab_mocks = [MagicMock() for _ in range(4)]
        for tm in tab_mocks:
            tm.__enter__ = MagicMock(return_value=None)
            tm.__exit__ = MagicMock(return_value=False)

        col_mocks = [MagicMock() for _ in range(2)]
        for cm in col_mocks:
            cm.__enter__ = MagicMock(return_value=None)
            cm.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "pages.taste_drift.load_deep_taste_drift_cache",
                return_value=minimal_cache,
            ),
            patch("pages.taste_drift.st") as mock_st,
        ):
            mock_st.tabs.return_value = tab_mocks
            mock_st.columns.return_value = col_mocks
            mock_st.stop = MagicMock()

            # Should not raise
            render_taste_drift()


if __name__ == "__main__":
    unittest.main()
