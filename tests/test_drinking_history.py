"""Tests for core.drinking_history — pure Untappd check-in shaping helpers.

Covers issue #124 (Drinking History exploration view). These functions are
Streamlit- and DuckDB-free: pure DataFrame-in/DataFrame-out logic, mirroring
the convention established by core/localizer_frames.py and core/source_filter.py.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from core.drinking_history import (
    build_checkins_frame,
    checkins_with_venue,
    rating_distribution,
    rating_trend,
    top_breweries,
    top_styles,
)


def _ts(dt_str: str) -> int:
    """Return a unix int-seconds timestamp for the given ISO date string."""
    return int(pd.Timestamp(dt_str).timestamp())


def _raw(**kwargs: object) -> str:
    """Build a JSON raw_json string with rating/venue defaults matching the loader's shape."""
    base = {
        "rating": None,
        "venue_name": "",
        "venue_lat": None,
        "venue_lng": None,
    }
    base.update(kwargs)
    return json.dumps(base)


def _make_events_df() -> pd.DataFrame:
    """Four untappd rows plus one lastfm row that must be filtered out."""
    return pd.DataFrame(
        {
            "timestamp": [
                _ts("2023-06-01"),
                _ts("2023-06-15"),
                _ts("2023-07-01"),
                _ts("2023-07-02"),
                _ts("2023-06-10"),
            ],
            "label": [
                "Test Brewery Co.",
                "Test Brewery Co.",
                "Other Brewery",
                "Other Brewery",
                "Radiohead",
            ],
            "sublabel": ["Hazy IPA", "Pilsner", "Pale Ale", "Stout", "Creep"],
            "category": ["IPA", "Pilsner", "American Pale Ale", "Stout", "Rock"],
            "raw_json": [
                _raw(
                    rating=4.5, venue_name="The Tasting Room", venue_lat=40.7128, venue_lng=-74.0060
                ),
                _raw(rating=3.75),
                _raw(rating=None),
                _raw(rating=4.0, venue_name="Brew Pub", venue_lat=41.0, venue_lng=-73.0),
                None,
            ],
            "source_id": ["untappd", "untappd", "untappd", "untappd", "lastfm"],
        }
    )


# ---------------------------------------------------------------------------
# build_checkins_frame
# ---------------------------------------------------------------------------


class TestBuildCheckinsFrame:
    def test_filters_to_untappd_only(self) -> None:
        result = build_checkins_frame(_make_events_df())
        assert len(result) == 4, f"Expected 4 untappd rows, got {len(result)}"
        assert "Radiohead" not in result["brewery"].tolist()

    def test_expected_columns_present(self) -> None:
        result = build_checkins_frame(_make_events_df())
        expected = {
            "timestamp",
            "date",
            "brewery",
            "beer",
            "style",
            "rating",
            "venue_name",
            "venue_lat",
            "venue_lng",
        }
        assert expected.issubset(set(result.columns))

    def test_label_sublabel_category_mapped(self) -> None:
        result = build_checkins_frame(_make_events_df())
        hazy = result[result["beer"] == "Hazy IPA"].iloc[0]
        assert hazy["brewery"] == "Test Brewery Co."
        assert hazy["style"] == "IPA"

    def test_rating_is_float_when_present(self) -> None:
        result = build_checkins_frame(_make_events_df())
        hazy = result[result["beer"] == "Hazy IPA"].iloc[0]
        assert hazy["rating"] == 4.5

    def test_rating_is_nan_when_missing(self) -> None:
        result = build_checkins_frame(_make_events_df())
        pale_ale = result[result["beer"] == "Pale Ale"].iloc[0]
        assert pd.isna(pale_ale["rating"])

    def test_venue_lat_lng_present_when_given(self) -> None:
        result = build_checkins_frame(_make_events_df())
        hazy = result[result["beer"] == "Hazy IPA"].iloc[0]
        assert hazy["venue_lat"] == 40.7128
        assert hazy["venue_lng"] == -74.0060
        assert hazy["venue_name"] == "The Tasting Room"

    def test_venue_lat_lng_nan_when_missing(self) -> None:
        result = build_checkins_frame(_make_events_df())
        pilsner = result[result["beer"] == "Pilsner"].iloc[0]
        assert pd.isna(pilsner["venue_lat"])
        assert pd.isna(pilsner["venue_lng"])

    def test_date_column_is_datetime(self) -> None:
        result = build_checkins_frame(_make_events_df())
        assert pd.api.types.is_datetime64_any_dtype(result["date"])

    def test_sorted_ascending_by_timestamp(self) -> None:
        result = build_checkins_frame(_make_events_df())
        assert result["timestamp"].is_monotonic_increasing

    def test_empty_input_returns_empty_frame_with_columns(self) -> None:
        result = build_checkins_frame(pd.DataFrame())
        assert result.empty
        assert "brewery" in result.columns

    def test_none_source_id_column_treated_as_all_rows(self) -> None:
        """A frame without a source_id column (e.g. already pre-filtered) passes through."""
        df = pd.DataFrame(
            {
                "timestamp": [_ts("2023-06-01")],
                "label": ["Test Brewery Co."],
                "sublabel": ["Hazy IPA"],
                "category": ["IPA"],
                "raw_json": [_raw(rating=4.5)],
            }
        )
        result = build_checkins_frame(df)
        assert len(result) == 1

    def test_dict_raw_json_also_supported(self) -> None:
        """raw_json may already be a parsed dict (not just a JSON string)."""
        df = pd.DataFrame(
            {
                "timestamp": [_ts("2023-06-01")],
                "label": ["Test Brewery Co."],
                "sublabel": ["Hazy IPA"],
                "category": ["IPA"],
                "raw_json": [
                    {"rating": 4.5, "venue_name": "", "venue_lat": None, "venue_lng": None}
                ],
                "source_id": ["untappd"],
            }
        )
        result = build_checkins_frame(df)
        assert result.iloc[0]["rating"] == 4.5


# ---------------------------------------------------------------------------
# top_breweries / top_styles
# ---------------------------------------------------------------------------


class TestTopBreweries:
    def test_counts_and_orders_descending(self) -> None:
        checkins = build_checkins_frame(_make_events_df())
        result = top_breweries(checkins)
        # Both breweries have 2 check-ins each in the fixture (a tie); every row
        # must report the correct count regardless of tie-break ordering.
        assert set(result["brewery"]) == {"Test Brewery Co.", "Other Brewery"}
        assert (result["checkins"] == 2).all()

    def test_respects_top_n(self) -> None:
        checkins = build_checkins_frame(_make_events_df())
        result = top_breweries(checkins, top_n=1)
        assert len(result) == 1

    def test_empty_input_returns_empty_frame(self) -> None:
        result = top_breweries(pd.DataFrame())
        assert result.empty
        assert "brewery" in result.columns


class TestTopStyles:
    def test_counts_and_orders_descending(self) -> None:
        checkins = build_checkins_frame(_make_events_df())
        result = top_styles(checkins)
        assert set(result["style"]) == {"IPA", "Pilsner", "American Pale Ale", "Stout"}
        assert (result["checkins"] == 1).all()

    def test_empty_input_returns_empty_frame(self) -> None:
        result = top_styles(pd.DataFrame())
        assert result.empty
        assert "style" in result.columns


# ---------------------------------------------------------------------------
# rating_trend
# ---------------------------------------------------------------------------


class TestRatingTrend:
    def test_groups_by_month_and_averages(self) -> None:
        checkins = build_checkins_frame(_make_events_df())
        result = rating_trend(checkins)
        # June has 4.5 and 3.75 rated checkins -> mean 4.125; July has 4.0 rated (Pale Ale
        # unrated is excluded).
        june_row = result[result["month"] == pd.Timestamp("2023-06-01")].iloc[0]
        assert june_row["avg_rating"] == pytest.approx(4.125)
        assert june_row["rated_checkins"] == 2

    def test_unrated_checkins_excluded(self) -> None:
        checkins = build_checkins_frame(_make_events_df())
        result = rating_trend(checkins)
        july_row = result[result["month"] == pd.Timestamp("2023-07-01")].iloc[0]
        assert july_row["rated_checkins"] == 1  # only Stout (4.0), Pale Ale unrated excluded

    def test_empty_input_returns_empty_frame(self) -> None:
        result = rating_trend(pd.DataFrame())
        assert result.empty
        assert "avg_rating" in result.columns

    def test_all_unrated_returns_empty_frame(self) -> None:
        df = build_checkins_frame(_make_events_df())
        df = df.assign(rating=float("nan"))
        result = rating_trend(df)
        assert result.empty


# ---------------------------------------------------------------------------
# rating_distribution
# ---------------------------------------------------------------------------


class TestRatingDistribution:
    def test_counts_per_rating_value(self) -> None:
        checkins = build_checkins_frame(_make_events_df())
        result = rating_distribution(checkins)
        assert set(result.columns) == {"rating", "checkins"}
        assert result["checkins"].sum() == 3  # 4.5, 3.75, 4.0 rated; Pale Ale unrated excluded

    def test_empty_input_returns_empty_frame(self) -> None:
        result = rating_distribution(pd.DataFrame())
        assert result.empty


# ---------------------------------------------------------------------------
# checkins_with_venue
# ---------------------------------------------------------------------------


class TestCheckinsWithVenue:
    def test_filters_to_rows_with_venue_coords(self) -> None:
        checkins = build_checkins_frame(_make_events_df())
        result = checkins_with_venue(checkins)
        assert len(result) == 2
        assert set(result["brewery"]) == {"Test Brewery Co.", "Other Brewery"}

    def test_rows_without_venue_excluded(self) -> None:
        checkins = build_checkins_frame(_make_events_df())
        result = checkins_with_venue(checkins)
        assert "Pilsner" not in result["beer"].tolist()

    def test_empty_input_returns_empty_frame(self) -> None:
        result = checkins_with_venue(pd.DataFrame())
        assert result.empty

    def test_missing_venue_columns_returns_empty_frame(self) -> None:
        result = checkins_with_venue(pd.DataFrame({"brewery": ["X"]}))
        assert result.empty
