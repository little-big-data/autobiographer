"""Tests for Subtask 6 — Cross-Domain City Soundtracks.

Covers:
- get_city_soundtrack: window filtering, empty lastfm_df
- get_all_city_soundtracks: deduplication by city name, swarm_df=None
- get_city_artist_affinity_matrix: shape and values
- render_city_soundtracks: smoke test (banner when cache is None, no error with cache)
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
        date_str: ISO date string (e.g. "2010-06-01").
        track: Track title.
        album: Album title.

    Returns:
        Dict with ``timestamp``, ``artist``, ``track``, ``album`` keys.
    """
    return {"timestamp": _ts(date_str), "artist": artist, "track": track, "album": album}


def _df(*rows: dict) -> pd.DataFrame:
    """Build a DataFrame from a sequence of row dicts."""
    return pd.DataFrame(list(rows))


def _rome_assumptions() -> dict:
    """Return a minimal assumptions dict with one trip to Rome.

    Returns:
        Dict with ``trips`` key containing one Rome trip entry.
    """
    return {
        "trips": [
            {
                "start": "2010-06-01",
                "end": "2010-06-14",
                "city": "Rome",
                "lat": 41.9,
                "lng": 12.5,
                "timezone": "Europe/Rome",
            }
        ]
    }


# ---------------------------------------------------------------------------
# get_city_soundtrack — window filtering
# ---------------------------------------------------------------------------


class TestGetCitySoundtrackWindow(unittest.TestCase):
    """Plays within [city_start - window_days, city_end + window_days] are included."""

    def setUp(self) -> None:
        from analysis_utils import get_city_soundtrack

        self.func = get_city_soundtrack
        # Trip: 2010-06-01 to 2010-06-14, window_days=7
        # Window: 2010-05-25 to 2010-06-21 inclusive
        self.city_start = pd.Timestamp("2010-06-01")
        self.city_end = pd.Timestamp("2010-06-14")

    def test_play_5_days_before_start_is_included(self) -> None:
        """A play 5 days before trip start is within the 7-day window and must be counted."""
        # 5 days before 2010-06-01 → 2010-05-27 — inside window (window extends to 2010-05-25)
        inside_row = _make_play("WindowArtist", "2010-05-27")
        df = pd.DataFrame([inside_row])

        result = self.func(
            df,
            "Rome",
            self.city_start,
            self.city_end,
            window_days=7,
            top_n=10,
        )

        self.assertIn("top_artists", result, "Result must have 'top_artists' key")
        top_artists = result["top_artists"]
        self.assertIsInstance(top_artists, pd.DataFrame, "'top_artists' must be a DataFrame")
        artist_names = top_artists["artist"].tolist() if "artist" in top_artists.columns else []
        self.assertIn(
            "WindowArtist",
            artist_names,
            "Play 5 days before trip start must be included (window_days=7)",
        )

    def test_play_10_days_before_start_is_excluded(self) -> None:
        """A play 10 days before trip start is outside the 7-day window and must NOT be counted."""
        # 10 days before 2010-06-01 → 2010-05-22 — outside window
        outside_row = _make_play("OutsideArtist", "2010-05-22")
        df = pd.DataFrame([outside_row])

        result = self.func(
            df,
            "Rome",
            self.city_start,
            self.city_end,
            window_days=7,
            top_n=10,
        )

        self.assertIn("top_artists", result, "Result must have 'top_artists' key")
        top_artists = result["top_artists"]
        artist_names = top_artists["artist"].tolist() if "artist" in top_artists.columns else []
        self.assertNotIn(
            "OutsideArtist",
            artist_names,
            "Play 10 days before trip start must NOT be included (window_days=7)",
        )

    def test_result_has_required_keys(self) -> None:
        """Result dict must contain all required keys."""
        inside_row = _make_play("SomeArtist", "2010-06-05")
        df = pd.DataFrame([inside_row])

        result = self.func(df, "Rome", self.city_start, self.city_end)

        for key in (
            "city",
            "top_artists",
            "top_tracks",
            "play_count",
            "period_start",
            "period_end",
        ):
            self.assertIn(key, result, f"Result must have '{key}' key")

    def test_result_city_matches_input(self) -> None:
        """The 'city' value in result must match the city argument passed in."""
        df = pd.DataFrame([_make_play("AnyArtist", "2010-06-05")])
        result = self.func(df, "Rome", self.city_start, self.city_end)
        self.assertEqual(result["city"], "Rome", "result['city'] must equal the input city name")

    def test_play_count_counts_included_plays(self) -> None:
        """play_count must equal the number of plays within the window."""
        rows = [
            _make_play("ArtistA", "2010-06-03"),  # inside
            _make_play("ArtistB", "2010-06-07"),  # inside
            _make_play("ArtistC", "2010-05-20"),  # outside (11 days before)
        ]
        df = pd.DataFrame(rows)
        result = self.func(df, "Rome", self.city_start, self.city_end, window_days=7)
        self.assertEqual(
            result["play_count"],
            2,
            "play_count must equal the number of plays within the window",
        )


# ---------------------------------------------------------------------------
# get_city_soundtrack — empty lastfm_df
# ---------------------------------------------------------------------------


class TestGetCitySoundtrackEmptyLastfm(unittest.TestCase):
    """Empty lastfm_df must return top_artists as an empty DataFrame."""

    def test_empty_lastfm_df_gives_empty_top_artists(self) -> None:
        from analysis_utils import get_city_soundtrack

        empty_df = pd.DataFrame(columns=["timestamp", "artist", "track", "album"])
        city_start = pd.Timestamp("2010-06-01")
        city_end = pd.Timestamp("2010-06-14")

        result = get_city_soundtrack(empty_df, "Rome", city_start, city_end)

        self.assertIn("top_artists", result)
        top_artists = result["top_artists"]
        self.assertIsInstance(top_artists, pd.DataFrame)
        self.assertTrue(
            top_artists.empty,
            "top_artists must be an empty DataFrame when lastfm_df is empty",
        )

    def test_empty_lastfm_df_gives_zero_play_count(self) -> None:
        from analysis_utils import get_city_soundtrack

        empty_df = pd.DataFrame(columns=["timestamp", "artist", "track", "album"])
        city_start = pd.Timestamp("2010-06-01")
        city_end = pd.Timestamp("2010-06-14")

        result = get_city_soundtrack(empty_df, "Rome", city_start, city_end)

        self.assertEqual(result["play_count"], 0, "play_count must be 0 for empty lastfm_df")


# ---------------------------------------------------------------------------
# get_all_city_soundtracks — deduplication
# ---------------------------------------------------------------------------


class TestGetAllCitySoundtracksDeduplication(unittest.TestCase):
    """Same city name in two trips → only one result entry returned."""

    def test_same_city_in_two_trips_yields_one_result(self) -> None:
        from analysis_utils import get_all_city_soundtracks

        # Two trips both to "Rome"
        assumptions = {
            "trips": [
                {
                    "start": "2010-06-01",
                    "end": "2010-06-14",
                    "city": "Rome",
                    "lat": 41.9,
                    "lng": 12.5,
                    "timezone": "Europe/Rome",
                },
                {
                    "start": "2012-09-01",
                    "end": "2012-09-10",
                    "city": "Rome",
                    "lat": 41.9,
                    "lng": 12.5,
                    "timezone": "Europe/Rome",
                },
            ]
        }

        rows = [
            _make_play("ArtistA", "2010-06-05"),
            _make_play("ArtistB", "2012-09-05"),
        ]
        df = pd.DataFrame(rows)

        result = get_all_city_soundtracks(df, assumptions, swarm_df=None)

        self.assertIsInstance(result, list, "Result must be a list")
        city_names = [entry["city"] for entry in result]
        self.assertEqual(
            city_names.count("Rome"),
            1,
            "Two trips to 'Rome' must be deduplicated to a single result entry",
        )

    def test_different_cities_each_have_their_own_entry(self) -> None:
        from analysis_utils import get_all_city_soundtracks

        assumptions = {
            "trips": [
                {
                    "start": "2010-06-01",
                    "end": "2010-06-14",
                    "city": "Rome",
                    "lat": 41.9,
                    "lng": 12.5,
                    "timezone": "Europe/Rome",
                },
                {
                    "start": "2011-07-01",
                    "end": "2011-07-10",
                    "city": "Paris",
                    "lat": 48.85,
                    "lng": 2.35,
                    "timezone": "Europe/Paris",
                },
            ]
        }

        rows = [
            _make_play("ArtistA", "2010-06-05"),
            _make_play("ArtistB", "2011-07-05"),
        ]
        df = pd.DataFrame(rows)

        result = get_all_city_soundtracks(df, assumptions, swarm_df=None)

        city_names = {entry["city"] for entry in result}
        self.assertIn("Rome", city_names, "'Rome' must appear in results")
        self.assertIn("Paris", city_names, "'Paris' must appear in results")


# ---------------------------------------------------------------------------
# get_all_city_soundtracks — no swarm
# ---------------------------------------------------------------------------


class TestGetAllCitySoundtracksNoSwarm(unittest.TestCase):
    """get_all_city_soundtracks must work correctly when swarm_df=None."""

    def test_no_swarm_returns_list(self) -> None:
        from analysis_utils import get_all_city_soundtracks

        assumptions = _rome_assumptions()
        rows = [_make_play("SomeArtist", "2010-06-05")]
        df = pd.DataFrame(rows)

        result = get_all_city_soundtracks(df, assumptions, swarm_df=None)

        self.assertIsInstance(result, list, "Result must be a list when swarm_df=None")

    def test_no_swarm_rome_trip_is_in_results(self) -> None:
        from analysis_utils import get_all_city_soundtracks

        assumptions = _rome_assumptions()
        rows = [_make_play("SomeArtist", "2010-06-05")]
        df = pd.DataFrame(rows)

        result = get_all_city_soundtracks(df, assumptions, swarm_df=None)

        city_names = [entry["city"] for entry in result]
        self.assertIn("Rome", city_names, "Rome trip must appear in results when swarm_df=None")

    def test_no_swarm_does_not_raise(self) -> None:
        from analysis_utils import get_all_city_soundtracks

        assumptions = _rome_assumptions()
        df = pd.DataFrame(columns=["timestamp", "artist", "track", "album"])

        try:
            get_all_city_soundtracks(df, assumptions, swarm_df=None)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"get_all_city_soundtracks raised an exception with swarm_df=None: {exc}")


# ---------------------------------------------------------------------------
# get_city_artist_affinity_matrix — shape
# ---------------------------------------------------------------------------


class TestCityArtistAffinityMatrixShape(unittest.TestCase):
    """Rows = unique artists across all cities; columns = unique cities."""

    def _make_soundtracks(self) -> list[dict]:
        """Build two city soundtrack dicts with known artists."""
        rome_artists = pd.DataFrame({"artist": ["Radiohead", "Massive Attack"], "plays": [10, 5]})
        rome_tracks = pd.DataFrame(
            {
                "track": ["Karma Police", "Teardrop"],
                "artist": ["Radiohead", "Massive Attack"],
                "plays": [10, 5],
            }
        )
        paris_artists = pd.DataFrame({"artist": ["Daft Punk", "Radiohead"], "plays": [8, 3]})
        paris_tracks = pd.DataFrame(
            {
                "track": ["Get Lucky", "Karma Police"],
                "artist": ["Daft Punk", "Radiohead"],
                "plays": [8, 3],
            }
        )
        return [
            {
                "city": "Rome",
                "top_artists": rome_artists,
                "top_tracks": rome_tracks,
                "play_count": 15,
                "period_start": pd.Timestamp("2010-05-25"),
                "period_end": pd.Timestamp("2010-06-21"),
            },
            {
                "city": "Paris",
                "top_artists": paris_artists,
                "top_tracks": paris_tracks,
                "play_count": 11,
                "period_start": pd.Timestamp("2011-06-24"),
                "period_end": pd.Timestamp("2011-07-17"),
            },
        ]

    def test_columns_are_unique_cities(self) -> None:
        from analysis_utils import get_city_artist_affinity_matrix

        soundtracks = self._make_soundtracks()
        result = get_city_artist_affinity_matrix(soundtracks, top_artists_n=20)

        self.assertIsInstance(result, pd.DataFrame, "Result must be a DataFrame")
        expected_cities = {"Rome", "Paris"}
        actual_cities = set(result.columns.tolist())
        self.assertEqual(
            actual_cities,
            expected_cities,
            f"Columns must be the unique city names; got {actual_cities}",
        )

    def test_index_contains_all_artists(self) -> None:
        from analysis_utils import get_city_artist_affinity_matrix

        soundtracks = self._make_soundtracks()
        result = get_city_artist_affinity_matrix(soundtracks, top_artists_n=20)

        # All three unique artists across both cities must appear as rows
        for artist in ("Radiohead", "Massive Attack", "Daft Punk"):
            self.assertIn(
                artist,
                result.index.tolist(),
                f"Artist '{artist}' must appear as a row in the affinity matrix",
            )

    def test_matrix_is_a_dataframe(self) -> None:
        from analysis_utils import get_city_artist_affinity_matrix

        soundtracks = self._make_soundtracks()
        result = get_city_artist_affinity_matrix(soundtracks, top_artists_n=20)

        self.assertIsInstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# get_city_artist_affinity_matrix — values
# ---------------------------------------------------------------------------


class TestCityArtistAffinityMatrixValues(unittest.TestCase):
    """Known play counts must appear in the correct (artist, city) cells."""

    def _make_soundtracks(self) -> list[dict]:
        """Build two city soundtrack dicts with known play counts."""
        rome_artists = pd.DataFrame({"artist": ["Radiohead", "Massive Attack"], "plays": [10, 5]})
        rome_tracks = pd.DataFrame(
            {
                "track": ["Karma Police", "Teardrop"],
                "artist": ["Radiohead", "Massive Attack"],
                "plays": [10, 5],
            }
        )
        paris_artists = pd.DataFrame({"artist": ["Daft Punk", "Radiohead"], "plays": [8, 3]})
        paris_tracks = pd.DataFrame(
            {
                "track": ["Get Lucky", "Karma Police"],
                "artist": ["Daft Punk", "Radiohead"],
                "plays": [8, 3],
            }
        )
        return [
            {
                "city": "Rome",
                "top_artists": rome_artists,
                "top_tracks": rome_tracks,
                "play_count": 15,
                "period_start": pd.Timestamp("2010-05-25"),
                "period_end": pd.Timestamp("2010-06-21"),
            },
            {
                "city": "Paris",
                "top_artists": paris_artists,
                "top_tracks": paris_tracks,
                "play_count": 11,
                "period_start": pd.Timestamp("2011-06-24"),
                "period_end": pd.Timestamp("2011-07-17"),
            },
        ]

    def test_radiohead_rome_play_count(self) -> None:
        """Radiohead plays in Rome must equal 10."""
        from analysis_utils import get_city_artist_affinity_matrix

        soundtracks = self._make_soundtracks()
        result = get_city_artist_affinity_matrix(soundtracks, top_artists_n=20)

        self.assertIn("Radiohead", result.index)
        self.assertIn("Rome", result.columns)
        value = result.loc["Radiohead", "Rome"]
        self.assertEqual(
            value,
            10,
            f"Radiohead plays in Rome should be 10 but got {value}",
        )

    def test_massive_attack_paris_is_zero_or_nan(self) -> None:
        """Massive Attack has no plays in Paris — cell must be 0 (NaN → 0 per spec)."""
        from analysis_utils import get_city_artist_affinity_matrix

        soundtracks = self._make_soundtracks()
        result = get_city_artist_affinity_matrix(soundtracks, top_artists_n=20)

        self.assertIn("Massive Attack", result.index)
        self.assertIn("Paris", result.columns)
        value = result.loc["Massive Attack", "Paris"]
        self.assertEqual(
            value,
            0,
            f"Massive Attack plays in Paris should be 0 (NaN → 0) but got {value}",
        )

    def test_daft_punk_paris_play_count(self) -> None:
        """Daft Punk plays in Paris must equal 8."""
        from analysis_utils import get_city_artist_affinity_matrix

        soundtracks = self._make_soundtracks()
        result = get_city_artist_affinity_matrix(soundtracks, top_artists_n=20)

        self.assertIn("Daft Punk", result.index)
        self.assertIn("Paris", result.columns)
        value = result.loc["Daft Punk", "Paris"]
        self.assertEqual(
            value,
            8,
            f"Daft Punk plays in Paris should be 8 but got {value}",
        )

    def test_no_nan_values_in_result(self) -> None:
        """The spec says NaN → 0; no NaN values must appear in the matrix."""
        from analysis_utils import get_city_artist_affinity_matrix

        soundtracks = self._make_soundtracks()
        result = get_city_artist_affinity_matrix(soundtracks, top_artists_n=20)

        has_nan = result.isnull().any().any()
        self.assertFalse(has_nan, "NaN values must be replaced with 0 per spec")


# ---------------------------------------------------------------------------
# render_city_soundtracks smoke test
# ---------------------------------------------------------------------------


class TestRenderCitySoundtracksSmoke(unittest.TestCase):
    """render_city_soundtracks() must run without exception."""

    def test_render_shows_banner_when_no_cache(self) -> None:
        """When load_deep_city_soundtracks_cache returns None, banner is called."""
        from pages.city_soundtracks import render_city_soundtracks

        banner_mock = MagicMock()

        with (
            patch(
                "pages.city_soundtracks.load_deep_city_soundtracks_cache",
                return_value=None,
            ),
            patch(
                "pages.city_soundtracks._deep_analysis_not_computed_banner",
                banner_mock,
            ),
            patch("pages.city_soundtracks.st") as mock_st,
        ):
            mock_st.stop = MagicMock()
            render_city_soundtracks()

        banner_mock.assert_called_once()
        call_args = banner_mock.call_args
        first_arg = call_args[0][0] if call_args[0] else ""
        self.assertIn(
            "City Soundtracks",
            first_arg,
            "Banner must be called with 'City Soundtracks' as the analysis name",
        )

    def test_render_calls_st_stop_when_no_cache(self) -> None:
        """When cache is None, st.stop() must be called."""
        from pages.city_soundtracks import render_city_soundtracks

        with (
            patch(
                "pages.city_soundtracks.load_deep_city_soundtracks_cache",
                return_value=None,
            ),
            patch("pages.city_soundtracks._deep_analysis_not_computed_banner"),
            patch("pages.city_soundtracks.st") as mock_st,
        ):
            mock_st.stop = MagicMock()
            render_city_soundtracks()

        mock_st.stop.assert_called()

    def test_render_runs_without_exception_with_cache(self) -> None:
        """When cache is present (even empty), render_city_soundtracks() must not raise."""
        from pages.city_soundtracks import render_city_soundtracks

        minimal_cache: dict = {"soundtracks": [], "affinity_matrix": {}}

        tab_mocks = [MagicMock() for _ in range(4)]
        for tm in tab_mocks:
            tm.__enter__ = MagicMock(return_value=None)
            tm.__exit__ = MagicMock(return_value=False)

        expander_mock = MagicMock()
        expander_mock.__enter__ = MagicMock(return_value=None)
        expander_mock.__exit__ = MagicMock(return_value=False)

        col_mocks = [MagicMock() for _ in range(3)]
        for cm in col_mocks:
            cm.__enter__ = MagicMock(return_value=None)
            cm.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "pages.city_soundtracks.load_deep_city_soundtracks_cache",
                return_value=minimal_cache,
            ),
            patch("pages.city_soundtracks.st") as mock_st,
        ):
            mock_st.tabs.return_value = tab_mocks
            mock_st.columns.return_value = col_mocks
            mock_st.expander.return_value = expander_mock
            mock_st.stop = MagicMock()

            # Must not raise
            render_city_soundtracks()


if __name__ == "__main__":
    unittest.main()
