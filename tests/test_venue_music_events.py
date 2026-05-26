"""Tests for Subtasks 1-3: load_swarm_data enrichment, get_music_around_events,
and the Music & Venues tab UI.

All tests are RED by design — the functions/columns under test do not yet exist.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

import analysis_utils

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(dt_str: str) -> int:
    """Return a unix int-seconds timestamp for an ISO datetime string."""
    return int(pd.Timestamp(dt_str, tz="UTC").timestamp())


def _make_swarm_df(**kwargs: Any) -> pd.DataFrame:
    """Build a minimal Swarm DataFrame from keyword column lists."""
    return pd.DataFrame(kwargs)


def _make_lastfm_df(timestamps: list[int], artists: list[str]) -> pd.DataFrame:
    """Build a minimal Last.fm DataFrame."""
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "artist": artists,
            "track": [f"Track {i}" for i in range(len(timestamps))],
            "album": [f"Album {i}" for i in range(len(timestamps))],
        }
    )


# ---------------------------------------------------------------------------
# Subtask 1 — load_swarm_data enrichment
# ---------------------------------------------------------------------------


class TestLoadSwarmDataEventFields:
    """Tests for the new event_category and shout columns in load_swarm_data."""

    def _write_checkins_json(self, tmp_path: Any, items: list[dict]) -> str:
        """Write a checkins_test.json file and return the directory path."""
        data = {"items": items}
        file_path = tmp_path / "checkins_test.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")
        return str(tmp_path)

    def _minimal_item(self, **kwargs: Any) -> dict:
        """Return a minimal valid checkin item, optionally overriding fields."""
        base: dict = {
            "createdAt": _ts("2023-06-01 20:00:00"),
            "venue": {
                "name": "Test Venue",
                "location": {"city": "Chicago", "state": "IL", "country": "US"},
                "categories": [],
            },
        }
        base.update(kwargs)
        return base

    # -----------------------------------------------------------------------
    # event_category extraction
    # -----------------------------------------------------------------------

    def test_event_category_extracted_from_full_path(self, tmp_path: Any) -> None:
        """Item with event.categories[0].name='Concert' produces event_category='Concert'."""
        item = self._minimal_item(
            event={"categories": [{"name": "Concert"}]},
        )
        swarm_dir = self._write_checkins_json(tmp_path, [item])
        df = analysis_utils.load_swarm_data(swarm_dir)

        assert "event_category" in df.columns, "event_category column must exist"
        assert df.iloc[0]["event_category"] == "Concert", (
            "event_category should be 'Concert' from event.categories[0].name"
        )

    def test_event_category_empty_when_no_event_key(self, tmp_path: Any) -> None:
        """Item with no 'event' key produces event_category == ''."""
        item = self._minimal_item()
        swarm_dir = self._write_checkins_json(tmp_path, [item])
        df = analysis_utils.load_swarm_data(swarm_dir)

        assert df.iloc[0]["event_category"] == "", (
            "event_category should be '' when there is no 'event' key"
        )

    def test_event_category_empty_when_event_has_no_categories(self, tmp_path: Any) -> None:
        """Item with event key but empty categories list produces event_category == ''."""
        item = self._minimal_item(event={"categories": []})
        swarm_dir = self._write_checkins_json(tmp_path, [item])
        df = analysis_utils.load_swarm_data(swarm_dir)

        assert df.iloc[0]["event_category"] == "", (
            "event_category should be '' when event.categories is empty"
        )

    # -----------------------------------------------------------------------
    # shout extraction
    # -----------------------------------------------------------------------

    def test_shout_extracted_when_present(self, tmp_path: Any) -> None:
        """Item with shout='Drinking a beer' produces shout=='Drinking a beer'."""
        item = self._minimal_item(shout="Drinking a beer")
        swarm_dir = self._write_checkins_json(tmp_path, [item])
        df = analysis_utils.load_swarm_data(swarm_dir)

        assert "shout" in df.columns, "shout column must exist"
        assert df.iloc[0]["shout"] == "Drinking a beer", (
            "shout should equal the value from the item"
        )

    def test_shout_empty_when_absent(self, tmp_path: Any) -> None:
        """Item with no 'shout' key produces shout == ''."""
        item = self._minimal_item()
        swarm_dir = self._write_checkins_json(tmp_path, [item])
        df = analysis_utils.load_swarm_data(swarm_dir)

        assert df.iloc[0]["shout"] == "", "shout should be '' when the 'shout' key is absent"

    # -----------------------------------------------------------------------
    # Both columns on multi-item file
    # -----------------------------------------------------------------------

    def test_multiple_items_mixed_event_and_shout(self, tmp_path: Any) -> None:
        """Mixed items all produce correct event_category and shout values."""
        items = [
            self._minimal_item(
                createdAt=_ts("2023-06-01 18:00:00"),
                event={"categories": [{"name": "Jazz Concert"}]},
                shout="Amazing show",
            ),
            self._minimal_item(
                createdAt=_ts("2023-06-02 18:00:00"),
                event={"categories": []},
            ),
            self._minimal_item(createdAt=_ts("2023-06-03 18:00:00")),
        ]
        swarm_dir = self._write_checkins_json(tmp_path, items)
        df = analysis_utils.load_swarm_data(swarm_dir)
        df = df.sort_values("timestamp").reset_index(drop=True)

        assert df.iloc[0]["event_category"] == "Jazz Concert"
        assert df.iloc[0]["shout"] == "Amazing show"
        assert df.iloc[1]["event_category"] == ""
        assert df.iloc[1]["shout"] == ""
        assert df.iloc[2]["event_category"] == ""
        assert df.iloc[2]["shout"] == ""

    # -----------------------------------------------------------------------
    # Empty sentinel DataFrames include both columns
    # -----------------------------------------------------------------------

    def test_empty_result_has_event_category_column(self) -> None:
        """load_swarm_data with nonexistent dir returns df with event_category column."""
        df = analysis_utils.load_swarm_data("/nonexistent/path/that/does/not/exist")
        assert "event_category" in df.columns, (
            "Empty-sentinel DataFrame must include event_category column"
        )

    def test_empty_result_has_shout_column(self) -> None:
        """load_swarm_data with nonexistent dir returns df with shout column."""
        df = analysis_utils.load_swarm_data("/nonexistent/path/that/does/not/exist")
        assert "shout" in df.columns, "Empty-sentinel DataFrame must include shout column"

    def test_no_valid_items_sentinel_has_both_columns(self, tmp_path: Any) -> None:
        """When all items are invalid (no createdAt), the sentinel still has both columns."""
        bad_item = {"venue": {"name": "No Time Venue"}}  # no createdAt
        swarm_dir = self._write_checkins_json(tmp_path, [bad_item])
        df = analysis_utils.load_swarm_data(swarm_dir)

        assert df.empty, "Should return empty DataFrame for items with no createdAt"
        assert "event_category" in df.columns
        assert "shout" in df.columns


# ---------------------------------------------------------------------------
# Subtask 2 — get_music_around_events
# ---------------------------------------------------------------------------


class TestGetMusicAroundEvents:
    """Tests for the new get_music_around_events function in analysis_utils."""

    # Base timestamps
    CONCERT_TS = _ts("2023-07-15 20:00:00")
    MOVIE_TS = _ts("2023-07-16 19:00:00")
    SPORTS_TS = _ts("2023-07-17 14:00:00")

    def _make_swarm(self) -> pd.DataFrame:
        return _make_swarm_df(
            timestamp=[self.CONCERT_TS, self.MOVIE_TS, self.SPORTS_TS],
            venue=["Jazz Hall", "Cinema 7", "Wrigley Field"],
            venue_category=["Music Venue", "Theater", "Stadium"],
            event_category=["Jazz Concert", "Movie", "Baseball Game"],
        )

    def _make_lastfm(self) -> pd.DataFrame:
        return _make_lastfm_df(
            timestamps=[
                self.CONCERT_TS + 60 * 60,  # 60 min after Concert — inside 2h window
                self.CONCERT_TS + 180 * 60,  # 180 min after Concert — outside 2h window
                self.MOVIE_TS + 60 * 60,  # 60 min after Movie — inside 2h window
                self.SPORTS_TS + 60 * 60,  # 60 min after Sports — inside 2h window
            ],
            artists=["Concert Artist", "Outside Artist", "Movie Artist", "Sports Artist"],
        )

    # -----------------------------------------------------------------------
    # Return shape
    # -----------------------------------------------------------------------

    def test_returns_dict_with_three_keys(self) -> None:
        """Result must have exactly the keys 'Concert', 'Movie', 'Sports'."""
        result = analysis_utils.get_music_around_events(self._make_swarm(), self._make_lastfm())
        assert set(result.keys()) == {"Concert", "Movie", "Sports"}, (
            f"Expected keys Concert/Movie/Sports, got {set(result.keys())}"
        )

    def test_each_value_is_dataframe(self) -> None:
        """Every value in the result dict must be a pandas DataFrame."""
        result = analysis_utils.get_music_around_events(self._make_swarm(), self._make_lastfm())
        for key, val in result.items():
            assert isinstance(val, pd.DataFrame), f"Value for '{key}' must be a DataFrame"

    def test_each_dataframe_has_artist_and_plays_columns(self) -> None:
        """Every result DataFrame must have 'artist' and 'plays' columns."""
        result = analysis_utils.get_music_around_events(self._make_swarm(), self._make_lastfm())
        for key, df in result.items():
            assert "artist" in df.columns, f"'artist' column missing from '{key}'"
            assert "plays" in df.columns, f"'plays' column missing from '{key}'"

    # -----------------------------------------------------------------------
    # Concert matching
    # -----------------------------------------------------------------------

    def test_concert_key_includes_play_within_window(self) -> None:
        """Play 60 min after a 'Jazz Concert' checkin appears in Concert results."""
        result = analysis_utils.get_music_around_events(self._make_swarm(), self._make_lastfm())
        concert_df = result["Concert"]
        assert "Concert Artist" in concert_df["artist"].values, (
            "Play within 60 min of Concert checkin must appear under 'Concert'"
        )

    def test_concert_key_excludes_play_outside_window(self) -> None:
        """Play 180 min after a 'Jazz Concert' checkin does NOT appear in Concert results."""
        result = analysis_utils.get_music_around_events(
            self._make_swarm(), self._make_lastfm(), window_hours=2.0
        )
        concert_df = result["Concert"]
        assert "Outside Artist" not in concert_df["artist"].values, (
            "Play 180 min away must NOT appear under 'Concert' with 2-hour window"
        )

    def test_concert_keyword_case_insensitive(self) -> None:
        """event_category='JAZZ CONCERT' (uppercase) still matches Concert bucket."""
        swarm_df = _make_swarm_df(
            timestamp=[self.CONCERT_TS],
            venue=["Jazz Hall"],
            venue_category=["Music Venue"],
            event_category=["JAZZ CONCERT"],
        )
        lastfm_df = _make_lastfm_df(
            timestamps=[self.CONCERT_TS + 30 * 60],
            artists=["Case Test Artist"],
        )
        result = analysis_utils.get_music_around_events(swarm_df, lastfm_df)
        assert "Case Test Artist" in result["Concert"]["artist"].values, (
            "Keyword matching for 'concert' must be case-insensitive"
        )

    # -----------------------------------------------------------------------
    # Movie matching
    # -----------------------------------------------------------------------

    def test_movie_key_matches_movie_category(self) -> None:
        """Play 60 min after a 'Movie' checkin appears in Movie results."""
        result = analysis_utils.get_music_around_events(self._make_swarm(), self._make_lastfm())
        movie_df = result["Movie"]
        assert "Movie Artist" in movie_df["artist"].values, (
            "Play within window of Movie checkin must appear under 'Movie'"
        )

    def test_movie_keyword_substring_match(self) -> None:
        """event_category='Dramatic Movie' (substring) matches Movie bucket."""
        swarm_df = _make_swarm_df(
            timestamp=[self.MOVIE_TS],
            venue=["Art House"],
            venue_category=["Theater"],
            event_category=["Dramatic Movie"],
        )
        lastfm_df = _make_lastfm_df(
            timestamps=[self.MOVIE_TS + 30 * 60],
            artists=["Drama Artist"],
        )
        result = analysis_utils.get_music_around_events(swarm_df, lastfm_df)
        assert "Drama Artist" in result["Movie"]["artist"].values, (
            "'Dramatic Movie' should match via 'movie' substring"
        )

    def test_horror_movie_matches_movie_bucket(self) -> None:
        """event_category='Horror Movie' matches Movie bucket."""
        swarm_df = _make_swarm_df(
            timestamp=[self.MOVIE_TS],
            venue=["Multiplex"],
            venue_category=["Theater"],
            event_category=["Horror Movie"],
        )
        lastfm_df = _make_lastfm_df(
            timestamps=[self.MOVIE_TS + 45 * 60],
            artists=["Horror Artist"],
        )
        result = analysis_utils.get_music_around_events(swarm_df, lastfm_df)
        assert "Horror Artist" in result["Movie"]["artist"].values

    # -----------------------------------------------------------------------
    # Sports matching
    # -----------------------------------------------------------------------

    def test_sports_key_matches_baseball_game(self) -> None:
        """event_category='Baseball Game' (keyword 'game') appears in Sports results."""
        result = analysis_utils.get_music_around_events(self._make_swarm(), self._make_lastfm())
        sports_df = result["Sports"]
        assert "Sports Artist" in sports_df["artist"].values, (
            "Play within window of 'Baseball Game' checkin must appear under 'Sports'"
        )

    def test_sports_keyword_sport_matches(self) -> None:
        """event_category='Sporting Event' (keyword 'sport') matches Sports bucket."""
        swarm_df = _make_swarm_df(
            timestamp=[self.SPORTS_TS],
            venue=["United Center"],
            venue_category=["Stadium"],
            event_category=["Sporting Event"],
        )
        lastfm_df = _make_lastfm_df(
            timestamps=[self.SPORTS_TS + 30 * 60],
            artists=["Sporting Artist"],
        )
        result = analysis_utils.get_music_around_events(swarm_df, lastfm_df)
        assert "Sporting Artist" in result["Sports"]["artist"].values, (
            "'Sporting Event' should match via 'sport' keyword"
        )

    # -----------------------------------------------------------------------
    # Sorting
    # -----------------------------------------------------------------------

    def test_results_sorted_descending_by_plays(self) -> None:
        """Result DataFrames are sorted by plays descending."""
        concert_ts = self.CONCERT_TS
        swarm_df = _make_swarm_df(
            timestamp=[concert_ts, concert_ts + 1, concert_ts + 2],
            venue=["Hall A", "Hall B", "Hall C"],
            venue_category=["Venue", "Venue", "Venue"],
            event_category=["Concert", "Concert", "Concert"],
        )
        # Artist B appears at 3 events, Artist A at 1 — B must rank first
        lastfm_df = _make_lastfm_df(
            timestamps=[
                concert_ts + 30 * 60,
                concert_ts + 1 + 30 * 60,
                concert_ts + 2 + 30 * 60,
                concert_ts + 60 * 60,
            ],
            artists=["Artist B", "Artist B", "Artist B", "Artist A"],
        )
        result = analysis_utils.get_music_around_events(swarm_df, lastfm_df)
        concert_df = result["Concert"]
        if len(concert_df) >= 2:
            assert concert_df.iloc[0]["plays"] >= concert_df.iloc[1]["plays"], (
                "Rows must be sorted by plays descending"
            )

    # -----------------------------------------------------------------------
    # top_n parameter
    # -----------------------------------------------------------------------

    def test_top_n_limits_rows(self) -> None:
        """top_n=2 returns at most 2 rows per DataFrame even with more artists."""
        concert_ts = self.CONCERT_TS
        # Three distinct artists all within the window
        swarm_df = _make_swarm_df(
            timestamp=[concert_ts],
            venue=["Jazz Hall"],
            venue_category=["Venue"],
            event_category=["Concert"],
        )
        lastfm_df = _make_lastfm_df(
            timestamps=[
                concert_ts + 10 * 60,
                concert_ts + 20 * 60,
                concert_ts + 30 * 60,
            ],
            artists=["Artist X", "Artist Y", "Artist Z"],
        )
        result = analysis_utils.get_music_around_events(swarm_df, lastfm_df, top_n=2)
        assert len(result["Concert"]) <= 2, "top_n=2 must limit Concert results to at most 2 rows"

    # -----------------------------------------------------------------------
    # Empty-input guards
    # -----------------------------------------------------------------------

    def test_empty_swarm_df_returns_all_empty_dataframes(self) -> None:
        """Empty swarm_df returns dict with empty DataFrames for all three keys."""
        empty_swarm = pd.DataFrame(
            columns=["timestamp", "venue", "venue_category", "event_category"]
        )
        lastfm_df = self._make_lastfm()
        result = analysis_utils.get_music_around_events(empty_swarm, lastfm_df)

        assert set(result.keys()) == {"Concert", "Movie", "Sports"}
        for key in ("Concert", "Movie", "Sports"):
            assert result[key].empty, f"Result['{key}'] should be empty for empty swarm_df"

    def test_swarm_df_without_event_category_column_does_not_raise(self) -> None:
        """swarm_df missing 'event_category' column returns empty DataFrames without raising."""
        swarm_df = _make_swarm_df(
            timestamp=[self.CONCERT_TS],
            venue=["Hall"],
            venue_category=["Venue"],
            # no event_category column
        )
        lastfm_df = self._make_lastfm()
        result = analysis_utils.get_music_around_events(swarm_df, lastfm_df)

        assert set(result.keys()) == {"Concert", "Movie", "Sports"}
        for key in ("Concert", "Movie", "Sports"):
            assert isinstance(result[key], pd.DataFrame)

    def test_empty_lastfm_df_returns_all_empty_dataframes(self) -> None:
        """Empty lastfm_df returns dict with empty DataFrames for all three keys."""
        swarm_df = self._make_swarm()
        empty_lastfm = pd.DataFrame(columns=["timestamp", "artist", "track", "album"])
        result = analysis_utils.get_music_around_events(swarm_df, empty_lastfm)

        for key in ("Concert", "Movie", "Sports"):
            assert result[key].empty, f"Result['{key}'] should be empty when lastfm_df is empty"


# ---------------------------------------------------------------------------
# Subtask 3 — UI: Music & Venues tab and cache computation
# ---------------------------------------------------------------------------


class TestVenuePatternsTab4UI:
    """Tests for the Music & Venues tab 4 showing concerts, movies, sports, shouts."""

    def _make_cache(
        self,
        concerts: list[dict] | None = None,
        movies: list[dict] | None = None,
        sports: list[dict] | None = None,
        shouts: list[dict] | None = None,
    ) -> dict:
        """Build a mock cache dict with all existing + new keys."""
        return {
            "loyalty": [],
            "routine": [],
            "exploration": [],
            "music_around_cafes": [],
            "music_around_concerts": concerts if concerts is not None else [],
            "music_around_movies": movies if movies is not None else [],
            "music_around_sports": sports if sports is not None else [],
            "recent_shouts": shouts if shouts is not None else [],
        }

    def _render(self, cache: dict) -> None:
        """Call render_venue_patterns with the given cache mocked in."""
        from pages import venue_patterns

        with patch.object(analysis_utils, "load_deep_venue_patterns_cache", return_value=cache):
            venue_patterns.render_venue_patterns()

    def test_concerts_subheader_rendered(self) -> None:
        """render_venue_patterns must call st.subheader with 'Music Around Concerts'."""
        cache = self._make_cache()
        with (
            patch("streamlit.subheader") as mock_subheader,
            patch(
                "streamlit.tabs",
                return_value=[
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                ],
            ),
            patch("streamlit.title"),
            patch("streamlit.info"),
            patch("streamlit.dataframe"),
            patch("streamlit.bar_chart"),
            patch("streamlit.line_chart"),
            patch.object(analysis_utils, "load_deep_venue_patterns_cache", return_value=cache),
        ):
            from pages import venue_patterns

            venue_patterns.render_venue_patterns()
            subheader_calls = [c.args[0] for c in mock_subheader.call_args_list if c.args]
            assert any("Concert" in s for s in subheader_calls), (
                f"Expected subheader containing 'Concert'. Got: {subheader_calls}"
            )

    def test_movies_subheader_rendered(self) -> None:
        """render_venue_patterns must call st.subheader with 'Music Around Movies'."""
        cache = self._make_cache()
        with (
            patch("streamlit.subheader") as mock_subheader,
            patch(
                "streamlit.tabs",
                return_value=[
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                ],
            ),
            patch("streamlit.title"),
            patch("streamlit.info"),
            patch("streamlit.dataframe"),
            patch("streamlit.bar_chart"),
            patch("streamlit.line_chart"),
            patch.object(analysis_utils, "load_deep_venue_patterns_cache", return_value=cache),
        ):
            from pages import venue_patterns

            venue_patterns.render_venue_patterns()
            subheader_calls = [c.args[0] for c in mock_subheader.call_args_list if c.args]
            assert any("Movie" in s for s in subheader_calls), (
                f"Expected subheader containing 'Movie'. Got: {subheader_calls}"
            )

    def test_sports_subheader_rendered(self) -> None:
        """render_venue_patterns must call st.subheader with 'Music Around Sports Events'."""
        cache = self._make_cache()
        with (
            patch("streamlit.subheader") as mock_subheader,
            patch(
                "streamlit.tabs",
                return_value=[
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                ],
            ),
            patch("streamlit.title"),
            patch("streamlit.info"),
            patch("streamlit.dataframe"),
            patch("streamlit.bar_chart"),
            patch("streamlit.line_chart"),
            patch.object(analysis_utils, "load_deep_venue_patterns_cache", return_value=cache),
        ):
            from pages import venue_patterns

            venue_patterns.render_venue_patterns()
            subheader_calls = [c.args[0] for c in mock_subheader.call_args_list if c.args]
            assert any("Sport" in s for s in subheader_calls), (
                f"Expected subheader containing 'Sport'. Got: {subheader_calls}"
            )

    def test_shouts_subheader_rendered(self) -> None:
        """render_venue_patterns must call st.subheader with 'Recent Event Shouts'."""
        cache = self._make_cache()
        with (
            patch("streamlit.subheader") as mock_subheader,
            patch(
                "streamlit.tabs",
                return_value=[
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                ],
            ),
            patch("streamlit.title"),
            patch("streamlit.info"),
            patch("streamlit.dataframe"),
            patch("streamlit.bar_chart"),
            patch("streamlit.line_chart"),
            patch.object(analysis_utils, "load_deep_venue_patterns_cache", return_value=cache),
        ):
            from pages import venue_patterns

            venue_patterns.render_venue_patterns()
            subheader_calls = [c.args[0] for c in mock_subheader.call_args_list if c.args]
            assert any("Shout" in s for s in subheader_calls), (
                f"Expected subheader containing 'Shout'. Got: {subheader_calls}"
            )

    def test_dataframe_shown_when_concerts_records_present(self) -> None:
        """st.dataframe is called in tab 4 when music_around_concerts has records."""
        concerts = [{"artist": "Miles Davis", "plays": 5}]
        cache = self._make_cache(concerts=concerts)
        with (
            patch("streamlit.dataframe") as mock_df,
            patch(
                "streamlit.tabs",
                return_value=[
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                ],
            ),
            patch("streamlit.title"),
            patch("streamlit.subheader"),
            patch("streamlit.info"),
            patch("streamlit.bar_chart"),
            patch("streamlit.line_chart"),
            patch.object(analysis_utils, "load_deep_venue_patterns_cache", return_value=cache),
        ):
            from pages import venue_patterns

            venue_patterns.render_venue_patterns()
            assert mock_df.called, "st.dataframe should be called when concert records exist"

    def test_info_shown_when_concerts_empty(self) -> None:
        """st.info is called at least 4 times when all four new sections are empty."""
        # All four new sections empty: concerts, movies, sports, shouts
        cache = self._make_cache(concerts=[], movies=[], sports=[], shouts=[])
        with (
            patch("streamlit.info") as mock_info,
            patch(
                "streamlit.tabs",
                return_value=[
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                ],
            ),
            patch("streamlit.title"),
            patch("streamlit.subheader"),
            patch("streamlit.dataframe"),
            patch("streamlit.bar_chart"),
            patch("streamlit.line_chart"),
            patch.object(analysis_utils, "load_deep_venue_patterns_cache", return_value=cache),
        ):
            from pages import venue_patterns

            venue_patterns.render_venue_patterns()
            # After implementation there should be at least 7 st.info calls:
            # 3 for existing empty tabs (loyalty, routine, exploration)
            # + 4 for the new empty sections (concerts, movies, sports, shouts)
            # The pre-implementation code yields 4 (3 tabs + 1 cafe), so this is a strict test.
            assert mock_info.call_count >= 7, (
                f"Expected at least 7 st.info calls for 3 existing + 4 new empty sections, "
                f"got {mock_info.call_count}"
            )

    def test_shouts_dataframe_shown_when_records_present(self) -> None:
        """st.dataframe is called for recent_shouts when records exist."""
        shouts = [
            {"venue": "Jazz Club", "shout": "Amazing!", "date": "2023-07-15"},
        ]
        cache = self._make_cache(shouts=shouts)
        with (
            patch("streamlit.dataframe") as mock_df,
            patch(
                "streamlit.tabs",
                return_value=[
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                ],
            ),
            patch("streamlit.title"),
            patch("streamlit.subheader"),
            patch("streamlit.info"),
            patch("streamlit.bar_chart"),
            patch("streamlit.line_chart"),
            patch.object(analysis_utils, "load_deep_venue_patterns_cache", return_value=cache),
        ):
            from pages import venue_patterns

            venue_patterns.render_venue_patterns()
            assert mock_df.called, "st.dataframe should be called when shout records exist"

    def test_info_shown_when_shouts_empty(self) -> None:
        """st.info is called for shouts specifically — its call args must mention 'shout' or similar."""
        # Only shouts is empty; concerts populated so info count gives signal
        concerts = [{"artist": "Miles Davis", "plays": 5}]
        movies = [{"artist": "Morricone", "plays": 3}]
        sports = [{"artist": "Queen", "plays": 8}]
        cache = self._make_cache(concerts=concerts, movies=movies, sports=sports, shouts=[])
        with (
            patch("streamlit.info") as mock_info,
            patch(
                "streamlit.tabs",
                return_value=[
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=None),
                        __exit__=MagicMock(return_value=False),
                    ),
                ],
            ),
            patch("streamlit.title"),
            patch("streamlit.subheader"),
            patch("streamlit.dataframe"),
            patch("streamlit.bar_chart"),
            patch("streamlit.line_chart"),
            patch.object(analysis_utils, "load_deep_venue_patterns_cache", return_value=cache),
        ):
            from pages import venue_patterns

            venue_patterns.render_venue_patterns()
            # With concerts/movies/sports populated, only shouts triggers st.info in tab 4
            # The existing cafe section also calls st.info (cafe key is empty in our cache)
            # After implementation, at least 1 st.info call must relate to shouts
            # We check that st.info is called at least once (the shouts section)
            # AND that the total info count for this page is at least 2
            # (tab1/2/3 loyalty/routine/exploration are empty → their info + shouts info)
            assert mock_info.called, "st.info should be called when shout records are empty"
            # The shouts-specific info must appear — check that one call's arg mentions shout or event
            shout_info_calls = [
                c
                for c in mock_info.call_args_list
                if c.args and ("shout" in c.args[0].lower() or "event" in c.args[0].lower())
            ]
            assert len(shout_info_calls) >= 1, (
                "At least one st.info call must reference shouts/events when shouts list is empty. "
                f"Got info calls: {[c.args for c in mock_info.call_args_list]}"
            )


class TestDataSourcesVenuePatternsCompute:
    """Tests for the cache computation step in data_sources.py."""

    def test_save_called_with_music_around_concerts_key(self) -> None:
        """save_deep_venue_patterns_cache must receive music_around_concerts key."""

        concert_df = pd.DataFrame({"artist": ["Miles Davis"], "plays": [5]})
        movie_df = pd.DataFrame({"artist": ["Ennio Morricone"], "plays": [3]})
        sports_df = pd.DataFrame({"artist": ["Queen"], "plays": [8]})

        events_result = {
            "Concert": concert_df,
            "Movie": movie_df,
            "Sports": sports_df,
        }

        swarm_df = _make_swarm_df(
            timestamp=[_ts("2023-07-15 20:00:00")],
            venue=["Jazz Hall"],
            venue_category=["Music Venue"],
            event_category=["Concert"],
            shout=["Great show"],
        )
        lastfm_df = _make_lastfm_df(
            timestamps=[_ts("2023-07-15 21:00:00")],
            artists=["Miles Davis"],
        )

        saved_payload: dict = {}

        def _capture_save(data: dict, **kwargs: Any) -> None:
            saved_payload.update(data)

        with (
            patch.object(analysis_utils, "get_music_around_events", return_value=events_result),
            patch.object(
                analysis_utils, "save_deep_venue_patterns_cache", side_effect=_capture_save
            ),
            patch.object(
                analysis_utils,
                "get_venue_loyalty_scores",
                return_value=pd.DataFrame(
                    columns=["venue", "venue_category", "visit_count", "loyalty_score"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_routine_venues",
                return_value=pd.DataFrame(
                    columns=[
                        "venue",
                        "venue_category",
                        "dominant_day",
                        "day_fraction",
                        "visit_count",
                    ]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_venue_exploration_rate",
                return_value=pd.DataFrame(
                    columns=["month", "new_venues", "revisits", "exploration_ratio"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_music_around_venue_type",
                return_value={
                    "top_artists": pd.DataFrame(columns=["artist", "plays"]),
                    "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
                    "checkin_count": 0,
                    "listen_count": 0,
                },
            ),
            patch("streamlit.session_state", {"swarm_df": swarm_df, "lastfm_df": lastfm_df}),
            patch("streamlit.write"),
            patch("streamlit.success"),
            patch("streamlit.error"),
        ):
            # Trigger the venue_patterns compute branch directly
            from pages import data_sources

            # Simulate the compute call
            data_sources._compute_venue_patterns(swarm_df, lastfm_df)

        assert "music_around_concerts" in saved_payload, (
            "save_deep_venue_patterns_cache must be called with 'music_around_concerts' key"
        )

    def test_save_called_with_music_around_movies_key(self) -> None:
        """save_deep_venue_patterns_cache must receive music_around_movies key."""
        concert_df = pd.DataFrame({"artist": ["Miles Davis"], "plays": [5]})
        movie_df = pd.DataFrame({"artist": ["Ennio Morricone"], "plays": [3]})
        sports_df = pd.DataFrame({"artist": ["Queen"], "plays": [8]})
        events_result = {"Concert": concert_df, "Movie": movie_df, "Sports": sports_df}

        swarm_df = _make_swarm_df(
            timestamp=[_ts("2023-07-15 20:00:00")],
            venue=["Jazz Hall"],
            venue_category=["Music Venue"],
            event_category=["Concert"],
            shout=[""],
        )
        lastfm_df = _make_lastfm_df(timestamps=[_ts("2023-07-15 21:00:00")], artists=["Artist"])

        saved_payload: dict = {}

        def _capture_save(data: dict, **kwargs: Any) -> None:
            saved_payload.update(data)

        with (
            patch.object(analysis_utils, "get_music_around_events", return_value=events_result),
            patch.object(
                analysis_utils, "save_deep_venue_patterns_cache", side_effect=_capture_save
            ),
            patch.object(
                analysis_utils,
                "get_venue_loyalty_scores",
                return_value=pd.DataFrame(
                    columns=["venue", "venue_category", "visit_count", "loyalty_score"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_routine_venues",
                return_value=pd.DataFrame(
                    columns=[
                        "venue",
                        "venue_category",
                        "dominant_day",
                        "day_fraction",
                        "visit_count",
                    ]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_venue_exploration_rate",
                return_value=pd.DataFrame(
                    columns=["month", "new_venues", "revisits", "exploration_ratio"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_music_around_venue_type",
                return_value={
                    "top_artists": pd.DataFrame(columns=["artist", "plays"]),
                    "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
                    "checkin_count": 0,
                    "listen_count": 0,
                },
            ),
        ):
            from pages import data_sources

            data_sources._compute_venue_patterns(swarm_df, lastfm_df)

        assert "music_around_movies" in saved_payload, (
            "save_deep_venue_patterns_cache must be called with 'music_around_movies' key"
        )

    def test_save_called_with_music_around_sports_key(self) -> None:
        """save_deep_venue_patterns_cache must receive music_around_sports key."""
        events_result = {
            "Concert": pd.DataFrame({"artist": [], "plays": []}),
            "Movie": pd.DataFrame({"artist": [], "plays": []}),
            "Sports": pd.DataFrame({"artist": ["Queen"], "plays": [8]}),
        }

        swarm_df = _make_swarm_df(
            timestamp=[_ts("2023-07-15 20:00:00")],
            venue=["Stadium"],
            venue_category=["Stadium"],
            event_category=["Baseball Game"],
            shout=[""],
        )
        lastfm_df = _make_lastfm_df(timestamps=[_ts("2023-07-15 21:00:00")], artists=["Queen"])

        saved_payload: dict = {}

        def _capture_save(data: dict, **kwargs: Any) -> None:
            saved_payload.update(data)

        with (
            patch.object(analysis_utils, "get_music_around_events", return_value=events_result),
            patch.object(
                analysis_utils, "save_deep_venue_patterns_cache", side_effect=_capture_save
            ),
            patch.object(
                analysis_utils,
                "get_venue_loyalty_scores",
                return_value=pd.DataFrame(
                    columns=["venue", "venue_category", "visit_count", "loyalty_score"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_routine_venues",
                return_value=pd.DataFrame(
                    columns=[
                        "venue",
                        "venue_category",
                        "dominant_day",
                        "day_fraction",
                        "visit_count",
                    ]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_venue_exploration_rate",
                return_value=pd.DataFrame(
                    columns=["month", "new_venues", "revisits", "exploration_ratio"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_music_around_venue_type",
                return_value={
                    "top_artists": pd.DataFrame(columns=["artist", "plays"]),
                    "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
                    "checkin_count": 0,
                    "listen_count": 0,
                },
            ),
        ):
            from pages import data_sources

            data_sources._compute_venue_patterns(swarm_df, lastfm_df)

        assert "music_around_sports" in saved_payload, (
            "save_deep_venue_patterns_cache must be called with 'music_around_sports' key"
        )

    def test_save_called_with_recent_shouts_key(self) -> None:
        """save_deep_venue_patterns_cache must receive recent_shouts key."""
        events_result = {
            "Concert": pd.DataFrame({"artist": [], "plays": []}),
            "Movie": pd.DataFrame({"artist": [], "plays": []}),
            "Sports": pd.DataFrame({"artist": [], "plays": []}),
        }

        swarm_df = _make_swarm_df(
            timestamp=[_ts("2023-07-15 20:00:00")],
            venue=["Jazz Hall"],
            venue_category=["Music Venue"],
            event_category=["Concert"],
            shout=["Great show!"],
        )
        lastfm_df = _make_lastfm_df(timestamps=[_ts("2023-07-15 21:00:00")], artists=["Artist"])

        saved_payload: dict = {}

        def _capture_save(data: dict, **kwargs: Any) -> None:
            saved_payload.update(data)

        with (
            patch.object(analysis_utils, "get_music_around_events", return_value=events_result),
            patch.object(
                analysis_utils, "save_deep_venue_patterns_cache", side_effect=_capture_save
            ),
            patch.object(
                analysis_utils,
                "get_venue_loyalty_scores",
                return_value=pd.DataFrame(
                    columns=["venue", "venue_category", "visit_count", "loyalty_score"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_routine_venues",
                return_value=pd.DataFrame(
                    columns=[
                        "venue",
                        "venue_category",
                        "dominant_day",
                        "day_fraction",
                        "visit_count",
                    ]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_venue_exploration_rate",
                return_value=pd.DataFrame(
                    columns=["month", "new_venues", "revisits", "exploration_ratio"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_music_around_venue_type",
                return_value={
                    "top_artists": pd.DataFrame(columns=["artist", "plays"]),
                    "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
                    "checkin_count": 0,
                    "listen_count": 0,
                },
            ),
        ):
            from pages import data_sources

            data_sources._compute_venue_patterns(swarm_df, lastfm_df)

        assert "recent_shouts" in saved_payload, (
            "save_deep_venue_patterns_cache must be called with 'recent_shouts' key"
        )

    def test_recent_shouts_at_most_20_entries(self) -> None:
        """recent_shouts must contain at most 20 entries even if swarm_df has more."""
        events_result = {
            "Concert": pd.DataFrame({"artist": [], "plays": []}),
            "Movie": pd.DataFrame({"artist": [], "plays": []}),
            "Sports": pd.DataFrame({"artist": [], "plays": []}),
        }

        # 25 checkins all with shouts
        base_ts = _ts("2023-07-15 20:00:00")
        swarm_df = _make_swarm_df(
            timestamp=[base_ts + i * 3600 for i in range(25)],
            venue=[f"Venue {i}" for i in range(25)],
            venue_category=["Music Venue"] * 25,
            event_category=["Concert"] * 25,
            shout=[f"Shout {i}" for i in range(25)],
        )
        lastfm_df = _make_lastfm_df(timestamps=[base_ts + 3600], artists=["Artist"])

        saved_payload: dict = {}

        def _capture_save(data: dict, **kwargs: Any) -> None:
            saved_payload.update(data)

        with (
            patch.object(analysis_utils, "get_music_around_events", return_value=events_result),
            patch.object(
                analysis_utils, "save_deep_venue_patterns_cache", side_effect=_capture_save
            ),
            patch.object(
                analysis_utils,
                "get_venue_loyalty_scores",
                return_value=pd.DataFrame(
                    columns=["venue", "venue_category", "visit_count", "loyalty_score"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_routine_venues",
                return_value=pd.DataFrame(
                    columns=[
                        "venue",
                        "venue_category",
                        "dominant_day",
                        "day_fraction",
                        "visit_count",
                    ]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_venue_exploration_rate",
                return_value=pd.DataFrame(
                    columns=["month", "new_venues", "revisits", "exploration_ratio"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_music_around_venue_type",
                return_value={
                    "top_artists": pd.DataFrame(columns=["artist", "plays"]),
                    "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
                    "checkin_count": 0,
                    "listen_count": 0,
                },
            ),
        ):
            from pages import data_sources

            data_sources._compute_venue_patterns(swarm_df, lastfm_df)

        assert len(saved_payload.get("recent_shouts", [])) <= 20, (
            "recent_shouts must be capped at 20 entries"
        )

    def test_no_shout_column_does_not_raise(self) -> None:
        """If swarm_df has no 'shout' column, recent_shouts degrades to empty list without raising."""
        events_result = {
            "Concert": pd.DataFrame({"artist": [], "plays": []}),
            "Movie": pd.DataFrame({"artist": [], "plays": []}),
            "Sports": pd.DataFrame({"artist": [], "plays": []}),
        }

        # swarm_df without shout column (pre-Subtask-1 cached data)
        swarm_df = _make_swarm_df(
            timestamp=[_ts("2023-07-15 20:00:00")],
            venue=["Hall"],
            venue_category=["Venue"],
            event_category=["Concert"],
            # no shout column
        )
        lastfm_df = _make_lastfm_df(timestamps=[_ts("2023-07-15 21:00:00")], artists=["Artist"])

        saved_payload: dict = {}

        def _capture_save(data: dict, **kwargs: Any) -> None:
            saved_payload.update(data)

        # Must not raise
        with (
            patch.object(analysis_utils, "get_music_around_events", return_value=events_result),
            patch.object(
                analysis_utils, "save_deep_venue_patterns_cache", side_effect=_capture_save
            ),
            patch.object(
                analysis_utils,
                "get_venue_loyalty_scores",
                return_value=pd.DataFrame(
                    columns=["venue", "venue_category", "visit_count", "loyalty_score"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_routine_venues",
                return_value=pd.DataFrame(
                    columns=[
                        "venue",
                        "venue_category",
                        "dominant_day",
                        "day_fraction",
                        "visit_count",
                    ]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_venue_exploration_rate",
                return_value=pd.DataFrame(
                    columns=["month", "new_venues", "revisits", "exploration_ratio"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_music_around_venue_type",
                return_value={
                    "top_artists": pd.DataFrame(columns=["artist", "plays"]),
                    "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
                    "checkin_count": 0,
                    "listen_count": 0,
                },
            ),
        ):
            from pages import data_sources

            data_sources._compute_venue_patterns(swarm_df, lastfm_df)

        assert saved_payload.get("recent_shouts", []) == [], (
            "recent_shouts should be empty list when swarm_df has no shout column"
        )

    def test_recent_shouts_entries_have_date_not_timestamp(self) -> None:
        """Each recent_shouts entry must have a 'date' string key, not 'timestamp'."""
        events_result = {
            "Concert": pd.DataFrame({"artist": [], "plays": []}),
            "Movie": pd.DataFrame({"artist": [], "plays": []}),
            "Sports": pd.DataFrame({"artist": [], "plays": []}),
        }

        swarm_df = _make_swarm_df(
            timestamp=[_ts("2023-07-15 20:00:00"), _ts("2023-08-10 18:00:00")],
            venue=["Jazz Hall", "Cinema"],
            venue_category=["Music Venue", "Movie Theater"],
            event_category=["Concert", "Movie"],
            shout=["Great show!", "Loved it!"],
        )
        lastfm_df = _make_lastfm_df(timestamps=[_ts("2023-07-15 21:00:00")], artists=["Artist"])

        saved_payload: dict = {}

        def _capture_save(data: dict, **kwargs: Any) -> None:
            saved_payload.update(data)

        with (
            patch.object(analysis_utils, "get_music_around_events", return_value=events_result),
            patch.object(
                analysis_utils, "save_deep_venue_patterns_cache", side_effect=_capture_save
            ),
            patch.object(
                analysis_utils,
                "get_venue_loyalty_scores",
                return_value=pd.DataFrame(
                    columns=["venue", "venue_category", "visit_count", "loyalty_score"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_routine_venues",
                return_value=pd.DataFrame(
                    columns=[
                        "venue",
                        "venue_category",
                        "dominant_day",
                        "day_fraction",
                        "visit_count",
                    ]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_venue_exploration_rate",
                return_value=pd.DataFrame(
                    columns=["month", "new_venues", "revisits", "exploration_ratio"]
                ),
            ),
            patch.object(
                analysis_utils,
                "get_music_around_venue_type",
                return_value={
                    "top_artists": pd.DataFrame(columns=["artist", "plays"]),
                    "top_tracks": pd.DataFrame(columns=["track", "artist", "plays"]),
                    "checkin_count": 0,
                    "listen_count": 0,
                },
            ),
        ):
            from pages import data_sources

            data_sources._compute_venue_patterns(swarm_df, lastfm_df)

        shouts = saved_payload.get("recent_shouts", [])
        assert len(shouts) > 0, "Expected at least one recent_shout entry"
        for entry in shouts:
            assert "date" in entry, f"Entry missing 'date' key: {entry}"
            assert "timestamp" not in entry, f"Entry must not have 'timestamp' key: {entry}"
            assert isinstance(entry["date"], str), f"'date' must be a string: {entry['date']!r}"
            # Verify it looks like YYYY-MM-DD
            parts = entry["date"].split("-")
            assert len(parts) == 3, f"'date' must be YYYY-MM-DD format: {entry['date']!r}"  # noqa: PLR2004
