"""Tests for the Music Map of America page (issue #57)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from pages.music_map_america import (
    _build_state_stats,
    _filter_us_states,
    render_music_map_america,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

US_STATES = [
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
]


def _make_df() -> pd.DataFrame:
    """Return a minimal DataFrame with the columns produced by apply_swarm_offsets."""
    return pd.DataFrame(
        {
            "artist": ["Artist A", "Artist A", "Artist B", "Artist C", "Artist A"],
            "album": ["Album 1", "Album 1", "Album 2", "Album 3", "Album 1"],
            "track": ["Track 1", "Track 2", "Track 3", "Track 4", "Track 1"],
            "timestamp": [1610000000, 1610000100, 1610000200, 1610000300, 1610000400],
            "date_text": pd.to_datetime(
                ["2021-01-07", "2021-01-07", "2021-01-07", "2021-01-07", "2021-01-07"]
            ),
            "state": ["IL", "IL", "NY", "CA", "IL"],
            "country": ["US", "US", "US", "US", "US"],
            "lat": [41.8, 41.8, 40.7, 34.0, 41.8],
            "lng": [-87.6, -87.6, -74.0, -118.2, -87.6],
            "city": ["Chicago", "Chicago", "New York", "Los Angeles", "Chicago"],
        }
    )


def _make_df_with_non_us() -> pd.DataFrame:
    """Return a DataFrame that mixes US states with non-US state codes."""
    df = _make_df()
    extra = pd.DataFrame(
        {
            "artist": ["Artist D", "Artist E"],
            "album": ["Album X", "Album Y"],
            "track": ["Track X", "Track Y"],
            "timestamp": [1610001000, 1610002000],
            "date_text": pd.to_datetime(["2021-01-08", "2021-01-08"]),
            "state": ["ON", "IS"],  # Ontario (Canada) and Iceland — not US states
            "country": ["Canada", "Iceland"],
            "lat": [43.7, 64.1],
            "lng": [-79.4, -21.8],
            "city": ["Toronto", "Reykjavik"],
        }
    )
    return pd.concat([df, extra], ignore_index=True)


# ---------------------------------------------------------------------------
# Unit tests for _filter_us_states
# ---------------------------------------------------------------------------


class TestFilterUsStates:
    def test_keeps_known_us_abbreviations(self) -> None:
        df = _make_df()
        result = _filter_us_states(df)
        assert set(result["state"].unique()).issubset(set(US_STATES))

    def test_removes_non_us_codes(self) -> None:
        df = _make_df_with_non_us()
        result = _filter_us_states(df)
        assert "ON" not in result["state"].values
        assert "IS" not in result["state"].values

    def test_returns_empty_for_no_us_rows(self) -> None:
        df = pd.DataFrame(
            {
                "state": ["ON", "IS"],
                "artist": ["A", "B"],
                "track": ["t1", "t2"],
                "album": ["x", "y"],
                "timestamp": [1, 2],
                "date_text": pd.to_datetime(["2021-01-01", "2021-01-01"]),
                "country": ["Canada", "Iceland"],
                "lat": [43.7, 64.1],
                "lng": [-79.4, -21.8],
                "city": ["Toronto", "Reykjavik"],
            }
        )
        result = _filter_us_states(df)
        assert result.empty

    def test_handles_empty_dataframe(self) -> None:
        result = _filter_us_states(pd.DataFrame())
        assert result.empty

    def test_normalises_city_state_strings(self) -> None:
        """'City, ST' values produced by the city fallback should be recognised."""
        df = pd.DataFrame(
            {
                "artist": ["A", "B"],
                "album": ["X", "Y"],
                "track": ["t1", "t2"],
                "timestamp": [1610000000, 1610000100],
                "date_text": pd.to_datetime(["2021-01-01", "2021-01-01"]),
                "state": ["Anchorage, AK", "Chicago, IL"],
                "country": ["US", "US"],
                "lat": [61.2, 41.8],
                "lng": [-149.9, -87.6],
                "city": ["Anchorage, AK", "Chicago, IL"],
            }
        )
        result = _filter_us_states(df)
        assert len(result) == 2
        assert set(result["state"].tolist()) == {"AK", "IL"}

    def test_normalises_full_state_names(self) -> None:
        """Full state names from reverse_geocoder admin1 should be normalised."""
        df = pd.DataFrame(
            {
                "artist": ["A", "B", "C"],
                "album": ["X", "Y", "Z"],
                "track": ["t1", "t2", "t3"],
                "timestamp": [1610000000, 1610000100, 1610000200],
                "date_text": pd.to_datetime(["2021-01-01"] * 3),
                "state": ["Oklahoma", "New York", "Ontario"],
                "country": ["US", "US", "Canada"],
                "lat": [35.5, 40.7, 43.7],
                "lng": [-97.5, -74.0, -79.4],
                "city": ["Oklahoma City", "New York", "Toronto"],
            }
        )
        result = _filter_us_states(df)
        assert len(result) == 2
        assert set(result["state"].tolist()) == {"OK", "NY"}
        assert "Ontario" not in result["state"].values


# ---------------------------------------------------------------------------
# Unit tests for _build_state_stats
# ---------------------------------------------------------------------------


class TestBuildStateStats:
    def test_returns_all_us_states_present(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        assert "IL" in stats["state"].values
        assert "NY" in stats["state"].values
        assert "CA" in stats["state"].values

    def test_play_counts_are_correct(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        il_plays = stats.loc[stats["state"] == "IL", "plays"].iloc[0]
        ny_plays = stats.loc[stats["state"] == "NY", "plays"].iloc[0]
        assert il_plays == 3
        assert ny_plays == 1

    def test_top_artist_column_present(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        assert "top_artist" in stats.columns

    def test_top_artist_is_most_played(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        il_top = stats.loc[stats["state"] == "IL", "top_artist"].iloc[0]
        assert il_top == "Artist A"

    def test_top_track_column_present(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        assert "top_track" in stats.columns

    def test_returns_empty_for_empty_input(self) -> None:
        result = _build_state_stats(pd.DataFrame())
        assert result.empty

    def test_top_artists_list_column_present(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        assert "top_artists_list" in stats.columns

    def test_top_artists_list_contains_top_5_or_fewer(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        il_row = stats.loc[stats["state"] == "IL"].iloc[0]
        # IL has 3 plays all by Artist A — list should have at most 5 entries
        assert len(il_row["top_artists_list"]) <= 5

    def test_top_tracks_list_column_present(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        assert "top_tracks_list" in stats.columns

    def test_top_tracks_list_contains_artist_and_track(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        il_row = stats.loc[stats["state"] == "IL"].iloc[0]
        assert len(il_row["top_tracks_list"]) >= 1
        # Each entry should contain " — " separating artist from track
        assert " — " in il_row["top_tracks_list"][0]

    def test_top_tracks_list_at_most_five(self) -> None:
        df = _make_df()
        stats = _build_state_stats(df)
        for _, row in stats.iterrows():
            assert len(row["top_tracks_list"]) <= 5


# ---------------------------------------------------------------------------
# Integration test for render_music_map_america
# ---------------------------------------------------------------------------


class TestRenderMusicMapAmerica:
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.subheader")
    @patch("streamlit.header")
    @patch("streamlit.info")
    def test_empty_state_shown_when_no_df(
        self,
        mock_info: MagicMock,
        mock_header: MagicMock,
        mock_subheader: MagicMock,
        mock_dataframe: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        with patch("streamlit.session_state", {"df": None}):
            render_music_map_america()
        mock_info.assert_called_once()
        mock_plotly.assert_not_called()

    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.subheader")
    @patch("streamlit.header")
    @patch("streamlit.info")
    def test_no_us_data_shows_warning(
        self,
        mock_info: MagicMock,
        mock_header: MagicMock,
        mock_subheader: MagicMock,
        mock_dataframe: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        df = pd.DataFrame(
            {
                "artist": ["A"],
                "album": ["X"],
                "track": ["t1"],
                "timestamp": [1610000000],
                "date_text": pd.to_datetime(["2021-01-01"]),
                "state": ["ON"],  # non-US
                "country": ["Canada"],
                "lat": [43.7],
                "lng": [-79.4],
                "city": ["Toronto"],
            }
        )
        with patch("streamlit.session_state", {"df": df}):
            render_music_map_america()
        mock_info.assert_called_once()

    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.subheader")
    @patch("streamlit.header")
    @patch("streamlit.markdown")
    def test_renders_choropleth_and_table_for_us_data(
        self,
        mock_md: MagicMock,
        mock_header: MagicMock,
        mock_subheader: MagicMock,
        mock_dataframe: MagicMock,
        mock_plotly: MagicMock,
        mock_cols: MagicMock,
        mock_select: MagicMock,
    ) -> None:
        df = _make_df()
        col_mock = MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )
        mock_cols.return_value = [col_mock, col_mock]
        # Return the sentinel "no selection" value so state detail panel is skipped
        mock_select.return_value = "— select a state —"

        with patch("streamlit.session_state", {"df": df}):
            render_music_map_america()

        # Choropleth chart should be rendered
        mock_plotly.assert_called()
        # State breakdown table should be rendered
        mock_dataframe.assert_called()

    @patch("streamlit.selectbox")
    @patch("streamlit.columns")
    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.subheader")
    @patch("streamlit.header")
    @patch("streamlit.markdown")
    def test_renders_share_button(
        self,
        mock_md: MagicMock,
        mock_header: MagicMock,
        mock_subheader: MagicMock,
        mock_dataframe: MagicMock,
        mock_plotly: MagicMock,
        mock_cols: MagicMock,
        mock_select: MagicMock,
    ) -> None:
        df = _make_df()
        col_mock = MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )
        mock_cols.return_value = [col_mock, col_mock]
        mock_select.return_value = "— select a state —"

        with patch("streamlit.session_state", {"df": df}):
            with patch("pages.music_map_america.render_share_button") as mock_share:
                render_music_map_america()

        mock_share.assert_called_once()

    @patch("streamlit.plotly_chart")
    @patch("streamlit.dataframe")
    @patch("streamlit.subheader")
    @patch("streamlit.header")
    @patch("streamlit.markdown")
    def test_df_missing_state_column_shows_info(
        self,
        mock_md: MagicMock,
        mock_header: MagicMock,
        mock_subheader: MagicMock,
        mock_dataframe: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        """A DataFrame without a state column should show the empty/info state."""
        df = pd.DataFrame(
            {
                "artist": ["A"],
                "album": ["X"],
                "track": ["t"],
                "timestamp": [1610000000],
                "date_text": pd.to_datetime(["2021-01-01"]),
            }
        )
        with patch("streamlit.session_state", {"df": df}):
            with patch("streamlit.info") as mock_info:
                render_music_map_america()
        mock_info.assert_called_once()
