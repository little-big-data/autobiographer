"""Tests for the Photograph History page (issue #123).

Covers the pure DataFrame-in/DataFrame-out helpers (build_photo_table,
get_tag_options, get_album_options, filter_photos) with hand-built fixtures,
plus a Streamlit smoke test for render_photograph_history() with all st.*
calls mocked (mirroring the pattern in tests/test_life_events.py).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pages.photograph_history import (
    build_photo_table,
    filter_photos,
    get_album_options,
    get_tag_options,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _raw(
    tags: list[str] | None = None,
    albums: list[str] | None = None,
    photopage: str = "https://www.flickr.com/photos/testuser/1/",
) -> str:
    """Return a JSON-serialized raw_json blob matching the Flickr export shape."""
    return json.dumps(
        {
            "tags": tags if tags is not None else [],
            "albums": albums if albums is not None else [],
            "photopage": photopage,
        }
    )


def _events_fixture() -> pd.DataFrame:
    """Three flickr EVENTS rows: two share an album/tag, one has neither."""
    return pd.DataFrame(
        [
            {
                "timestamp": 1_686_849_000,  # 2023-06-15
                "label": "Sunset over the bay",
                "sublabel": "Summer Trip",
                "category": "photo",
                "source_id": "flickr",
                "raw_json": _raw(
                    tags=["travel", "sunset"],
                    albums=["Summer Trip"],
                    photopage="https://www.flickr.com/photos/testuser/1/",
                ),
            },
            {
                "timestamp": 1_700_000_000,  # later
                "label": "Mountain hike",
                "sublabel": "Alps 2023",
                "category": "photo",
                "source_id": "flickr",
                "raw_json": _raw(
                    tags=["travel", "hiking"],
                    albums=["Alps 2023"],
                    photopage="https://www.flickr.com/photos/testuser/2/",
                ),
            },
            {
                "timestamp": 1_650_000_000,  # earliest, no album/tags
                "label": "Untitled",
                "sublabel": "",
                "category": "photo",
                "source_id": "flickr",
                "raw_json": _raw(tags=[], albums=[], photopage=""),
            },
        ]
    )


# ---------------------------------------------------------------------------
# build_photo_table
# ---------------------------------------------------------------------------


class TestBuildPhotoTable:
    def test_empty_input_returns_empty_frame_with_expected_columns(self) -> None:
        result = build_photo_table(pd.DataFrame())
        assert result.empty
        assert list(result.columns) == ["date", "title", "album", "tags", "url"]

    def test_none_input_returns_empty_frame(self) -> None:
        result = build_photo_table(None)  # type: ignore[arg-type]
        assert result.empty

    def test_row_count_matches_input(self) -> None:
        result = build_photo_table(_events_fixture())
        assert len(result) == 3

    def test_sorted_descending_by_date_most_recent_first(self) -> None:
        result = build_photo_table(_events_fixture())
        assert result.iloc[0]["title"] == "Mountain hike"
        assert result.iloc[-1]["title"] == "Untitled"

    def test_title_comes_from_label(self) -> None:
        result = build_photo_table(_events_fixture())
        titles = set(result["title"])
        assert "Sunset over the bay" in titles
        assert "Mountain hike" in titles

    def test_album_comes_from_sublabel(self) -> None:
        result = build_photo_table(_events_fixture())
        row = result[result["title"] == "Sunset over the bay"].iloc[0]
        assert row["album"] == "Summer Trip"

    def test_tags_parsed_from_raw_json(self) -> None:
        result = build_photo_table(_events_fixture())
        row = result[result["title"] == "Mountain hike"].iloc[0]
        assert row["tags"] == ["travel", "hiking"]

    def test_url_parsed_from_raw_json_photopage(self) -> None:
        result = build_photo_table(_events_fixture())
        row = result[result["title"] == "Sunset over the bay"].iloc[0]
        assert row["url"] == "https://www.flickr.com/photos/testuser/1/"

    def test_photo_with_no_tags_or_album_yields_empty_values(self) -> None:
        result = build_photo_table(_events_fixture())
        row = result[result["title"] == "Untitled"].iloc[0]
        assert row["tags"] == []
        assert row["album"] == ""
        assert row["url"] == ""

    def test_handles_dict_raw_json_not_just_string(self) -> None:
        """raw_json may already be a parsed dict (not just a JSON string)."""
        df = pd.DataFrame(
            [
                {
                    "timestamp": 1_600_000_000,
                    "label": "Dict Photo",
                    "sublabel": "",
                    "category": "photo",
                    "source_id": "flickr",
                    "raw_json": {"tags": ["a"], "albums": [], "photopage": "https://x/1"},
                }
            ]
        )
        result = build_photo_table(df)
        assert result.iloc[0]["tags"] == ["a"]
        assert result.iloc[0]["url"] == "https://x/1"

    def test_malformed_raw_json_string_does_not_raise(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "timestamp": 1_600_000_000,
                    "label": "Bad JSON",
                    "sublabel": "",
                    "category": "photo",
                    "source_id": "flickr",
                    "raw_json": "{not valid json",
                }
            ]
        )
        result = build_photo_table(df)
        assert result.iloc[0]["tags"] == []
        assert result.iloc[0]["url"] == ""


# ---------------------------------------------------------------------------
# get_tag_options / get_album_options
# ---------------------------------------------------------------------------


class TestGetTagOptions:
    def test_empty_frame_returns_all_only(self) -> None:
        assert get_tag_options(pd.DataFrame()) == ["All"]

    def test_returns_all_distinct_tags_sorted_after_all(self) -> None:
        photo_df = build_photo_table(_events_fixture())
        options = get_tag_options(photo_df)
        assert options[0] == "All"
        assert set(options[1:]) == {"travel", "sunset", "hiking"}
        assert options[1:] == sorted(options[1:])


class TestGetAlbumOptions:
    def test_empty_frame_returns_all_only(self) -> None:
        assert get_album_options(pd.DataFrame()) == ["All"]

    def test_returns_distinct_nonempty_albums_sorted_after_all(self) -> None:
        photo_df = build_photo_table(_events_fixture())
        options = get_album_options(photo_df)
        assert options[0] == "All"
        assert set(options[1:]) == {"Summer Trip", "Alps 2023"}
        # The photo with no album ("") must not appear as a spurious option.
        assert "" not in options


# ---------------------------------------------------------------------------
# filter_photos
# ---------------------------------------------------------------------------


class TestFilterPhotos:
    def test_all_tag_all_album_returns_everything(self) -> None:
        photo_df = build_photo_table(_events_fixture())
        result = filter_photos(photo_df, "All", "All")
        assert len(result) == len(photo_df)

    def test_filter_by_specific_tag(self) -> None:
        photo_df = build_photo_table(_events_fixture())
        result = filter_photos(photo_df, "hiking", "All")
        assert len(result) == 1
        assert result.iloc[0]["title"] == "Mountain hike"

    def test_filter_by_specific_album(self) -> None:
        photo_df = build_photo_table(_events_fixture())
        result = filter_photos(photo_df, "All", "Summer Trip")
        assert len(result) == 1
        assert result.iloc[0]["title"] == "Sunset over the bay"

    def test_filter_by_tag_and_album_combined(self) -> None:
        photo_df = build_photo_table(_events_fixture())
        result = filter_photos(photo_df, "travel", "Summer Trip")
        assert len(result) == 1
        assert result.iloc[0]["title"] == "Sunset over the bay"

    def test_filter_shared_tag_returns_multiple_photos(self) -> None:
        photo_df = build_photo_table(_events_fixture())
        result = filter_photos(photo_df, "travel", "All")
        assert len(result) == 2

    def test_empty_frame_passthrough(self) -> None:
        empty = build_photo_table(pd.DataFrame())
        result = filter_photos(empty, "travel", "All")
        assert result.empty

    def test_result_has_reset_index(self) -> None:
        photo_df = build_photo_table(_events_fixture())
        result = filter_photos(photo_df, "travel", "All")
        assert list(result.index) == list(range(len(result)))

    def test_does_not_mutate_input(self) -> None:
        photo_df = build_photo_table(_events_fixture())
        original_len = len(photo_df)
        filter_photos(photo_df, "hiking", "All")
        assert len(photo_df) == original_len


# ---------------------------------------------------------------------------
# render_photograph_history — smoke tests
# ---------------------------------------------------------------------------


class TestRenderPhotographHistorySmoke:
    def test_empty_state_shown_when_no_flickr_data(self) -> None:
        """When no flickr events exist, an info banner is shown and rendering stops
        before any filter widgets are created."""
        with (
            patch("pages.photograph_history._load_flickr_events_df", return_value=pd.DataFrame()),
            patch("pages.photograph_history.st") as mock_st,
        ):
            mock_st.header = MagicMock()
            mock_st.caption = MagicMock()
            mock_st.info = MagicMock()
            mock_st.columns = MagicMock()
            mock_st.selectbox = MagicMock()
            mock_st.dataframe = MagicMock()

            from pages import photograph_history

            photograph_history.render_photograph_history()

            mock_st.info.assert_called_once()
            mock_st.columns.assert_not_called()
            mock_st.dataframe.assert_not_called()

    def test_renders_without_exception_with_data(self) -> None:
        """With real flickr event data, rendering must not raise (all st.* mocked)."""
        mock_col1, mock_col2 = MagicMock(), MagicMock()
        mock_col1.__enter__ = MagicMock(return_value=mock_col1)
        mock_col1.__exit__ = MagicMock(return_value=False)
        mock_col2.__enter__ = MagicMock(return_value=mock_col2)
        mock_col2.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "pages.photograph_history._load_flickr_events_df",
                return_value=_events_fixture(),
            ),
            patch("pages.photograph_history.st") as mock_st,
        ):
            mock_st.header = MagicMock()
            mock_st.caption = MagicMock()
            mock_st.info = MagicMock()
            mock_st.columns = MagicMock(return_value=[mock_col1, mock_col2])
            mock_st.selectbox = MagicMock(return_value="All")
            mock_st.dataframe = MagicMock()
            mock_st.column_config = MagicMock()
            mock_st.column_config.LinkColumn = MagicMock(return_value="link_column")

            from pages import photograph_history

            try:
                photograph_history.render_photograph_history()
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"render_photograph_history raised with data present: {exc}")

            mock_st.dataframe.assert_called_once()
            mock_st.info.assert_not_called()

    def test_load_flickr_events_df_returns_empty_on_store_error(self) -> None:
        """_load_flickr_events_df must swallow store errors (e.g. missing DB) gracefully."""
        with patch(
            "localizer.store.db.LocalizerStore.__init__",
            side_effect=Exception("no store"),
        ):
            from pages.photograph_history import _load_flickr_events_df

            result = _load_flickr_events_df()
            assert isinstance(result, pd.DataFrame)
            assert result.empty
