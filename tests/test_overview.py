"""Tests for the Overview page's Time Machine card (``pages/overview.py``, issue #98).

Mocks Streamlit's ``markdown``/``info`` and injects a fixed ``today``/seeded
``random.Random`` into ``render_time_machine_card`` so these are fast, deterministic
smoke tests of the page's wiring — the actual "this day in history" data-shaping logic
is covered independently by ``tests/test_time_machine.py``.
"""

from __future__ import annotations

import math
import random
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from pages.overview import render_time_machine_card


def _ts(dt_str: str) -> int:
    """Return a unix int-seconds timestamp for the given ISO date string."""
    return int(pd.Timestamp(dt_str).timestamp())


TODAY = pd.Timestamp("2026-07-11").date()


class TestRenderTimeMachineCardEmptyState(unittest.TestCase):
    @patch("streamlit.info")
    @patch("streamlit.markdown")
    def test_no_data_at_all_shows_empty_state(
        self, mock_md: MagicMock, mock_info: MagicMock
    ) -> None:
        render_time_machine_card(None, None, today=TODAY)
        mock_info.assert_called_once()
        # No hero-style card div should be rendered when there's nothing to show.
        card_calls = [c for c in mock_md.call_args_list if "linear-gradient" in str(c)]
        self.assertEqual(len(card_calls), 0)

    @patch("streamlit.info")
    @patch("streamlit.markdown")
    def test_no_matching_historical_date_shows_empty_state(
        self, mock_md: MagicMock, mock_info: MagicMock
    ) -> None:
        df = pd.DataFrame(
            {
                "timestamp": [_ts("2025-01-01")],
                "date_text": pd.to_datetime(["2025-01-01"]),
                "artist": ["Off-day Artist"],
                "track": ["T"],
                "album": ["A"],
            }
        )
        render_time_machine_card(df, None, today=TODAY)
        mock_info.assert_called_once()


class TestRenderTimeMachineCardPopulated(unittest.TestCase):
    @patch("streamlit.markdown")
    def test_full_data_renders_card_with_all_sections(self, mock_md: MagicMock) -> None:
        df = pd.DataFrame(
            {
                "timestamp": [_ts("2019-07-11")],
                "date_text": pd.to_datetime(["2019-07-11"]),
                "artist": ["Radiohead"],
                "track": ["Idioteque"],
                "album": ["Kid A"],
                "source_id": ["lastfm"],
                "city": ["Lisbon"],
                "state": [""],
                "country": ["Portugal"],
            }
        )
        render_time_machine_card(df, None, today=TODAY, rng=random.Random(1))

        all_html = " ".join(str(c) for c in mock_md.call_args_list)
        self.assertIn("Where you were", all_html)
        self.assertIn("Lisbon", all_html)
        self.assertIn("What you were listening to", all_html)
        self.assertIn("Radiohead", all_html)

    @patch("streamlit.markdown")
    def test_listening_only_omits_other_sections(self, mock_md: MagicMock) -> None:
        df = pd.DataFrame(
            {
                "timestamp": [_ts("2019-07-11")],
                "date_text": pd.to_datetime(["2019-07-11"]),
                "artist": ["Boards of Canada"],
                "track": ["Roygbiv"],
                "album": ["MHTRTC"],
                "source_id": ["lastfm"],
            }
        )
        render_time_machine_card(df, None, today=TODAY, rng=random.Random(1))

        all_html = " ".join(str(c) for c in mock_md.call_args_list)
        self.assertIn("What you were listening to", all_html)
        self.assertNotIn("Where you were", all_html)
        self.assertNotIn("What you were doing", all_html)

    @patch("streamlit.markdown")
    def test_events_only_from_non_lastfm_source(self, mock_md: MagicMock) -> None:
        df = pd.DataFrame(
            {
                "timestamp": [_ts("2019-07-11")],
                "date_text": pd.to_datetime(["2019-07-11"]),
                "artist": ["Tasting Room Brewing"],
                "track": ["Hazy IPA"],
                "album": ["IPA"],
                "source_id": ["untappd"],
            }
        )
        render_time_machine_card(df, None, today=TODAY, rng=random.Random(1))

        all_html = " ".join(str(c) for c in mock_md.call_args_list)
        self.assertIn("What you were doing", all_html)
        self.assertIn("Tasting Room Brewing", all_html)
        self.assertNotIn("What you were listening to", all_html)

    @patch("streamlit.markdown")
    def test_swarm_only_location(self, mock_md: MagicMock) -> None:
        swarm_df = pd.DataFrame(
            {
                "timestamp": [_ts("2019-07-11")],
                "city": ["Berlin"],
                "state": [""],
                "country": ["Germany"],
                "venue": ["Cafe A"],
            }
        )
        render_time_machine_card(None, swarm_df, today=TODAY, rng=random.Random(1))

        all_html = " ".join(str(c) for c in mock_md.call_args_list)
        self.assertIn("Where you were", all_html)
        self.assertIn("Berlin", all_html)


# ---------------------------------------------------------------------------
# Issue #27 — activity calendar heatmap + source selector (Subtask 2).
#
# `CALENDAR_HEATMAP_SCALE` (components/theme.py) and `_build_calendar_heatmap_figure`
# / `render_activity_calendar` (pages/overview.py) do not exist yet as of this writing
# — Subtask 2's own production code has not been implemented. Every import of those
# names is deliberately deferred to inside each test body (not at module scope) so a
# missing name only fails its own test, rather than breaking collection of the
# existing TestRenderTimeMachineCard* classes above. `get_daily_activity` (Subtask 1,
# implemented in parallel) is mocked at the `pages.overview` boundary with
# ``create=True`` so these tests never depend on its real implementation.
# ---------------------------------------------------------------------------


def _music_df(dates: list[str]) -> pd.DataFrame:
    """Return a minimal synthetic Last.fm-shaped DataFrame spanning the given dates."""
    return pd.DataFrame(
        {
            "date_text": pd.to_datetime(dates),
            "artist": ["Artist"] * len(dates),
            "album": ["Album"] * len(dates),
            "track": ["Track"] * len(dates),
        }
    )


def _swarm_activity_df(dates: list[str]) -> pd.DataFrame:
    """Return a minimal synthetic Swarm-shaped DataFrame spanning the given dates."""
    return pd.DataFrame(
        {
            "timestamp": [_ts(d) for d in dates],
            "venue": ["Venue"] * len(dates),
            "city": ["City"] * len(dates),
            "country": ["Country"] * len(dates),
        }
    )


def _daily_activity_df(dates: list[str], values: list[int]) -> pd.DataFrame:
    """Return a synthetic two-column frame matching get_daily_activity's date/value contract."""
    return pd.DataFrame({"date": pd.to_datetime(dates), "value": values})


def _radio_options(call_args) -> list[str]:
    """Extract the ``options`` list passed to a mocked ``st.radio`` call, positional or keyword."""
    args, kwargs = call_args
    if "options" in kwargs:
        return list(kwargs["options"])
    if len(args) >= 2:
        return list(args[1])
    raise AssertionError(f"st.radio call had no discoverable options: {call_args!r}")


def _activity_source(call_args) -> object:
    """Extract the ``source`` kwarg (or 3rd positional arg) from a mocked get_daily_activity call."""
    args, kwargs = call_args
    if "source" in kwargs:
        return kwargs["source"]
    if len(args) >= 3:
        return args[2]
    raise AssertionError(f"get_daily_activity call had no discoverable source: {call_args!r}")


class TestCalendarHeatmapScaleConstant(unittest.TestCase):
    """``CALENDAR_HEATMAP_SCALE`` — the new 4-stop constant added to components/theme.py."""

    def test_calendar_heatmap_scale_matches_issue_stops(self) -> None:
        from components.theme import ACCENT_CYAN, ACCENT_INDIGO, CALENDAR_HEATMAP_SCALE, CARD_BG

        self.assertEqual(
            CALENDAR_HEATMAP_SCALE,
            [
                [0.0, CARD_BG],
                [0.3, "#312e81"],
                [0.7, ACCENT_INDIGO],
                [1.0, ACCENT_CYAN],
            ],
        )


class TestBuildCalendarHeatmapFigure(unittest.TestCase):
    """``_build_calendar_heatmap_figure`` — the hand-rolled go.Heatmap builder (issue #27)."""

    def test_colorscale_matches_calendar_heatmap_scale(self) -> None:
        from components.theme import CALENDAR_HEATMAP_SCALE
        from pages.overview import _build_calendar_heatmap_figure

        activity_df = _daily_activity_df(["2024-01-01", "2024-01-02", "2024-01-03"], [1, 2, 3])
        fig = _build_calendar_heatmap_figure(activity_df)

        trace = fig.data[0]
        actual_scale = [list(stop) for stop in trace.colorscale]
        expected_scale = [list(stop) for stop in CALENDAR_HEATMAP_SCALE]
        self.assertEqual(actual_scale, expected_scale)

    def test_zero_fill_cells_are_real_zeros_not_nan(self) -> None:
        from pages.overview import _build_calendar_heatmap_figure

        dates = [f"2024-01-{d:02d}" for d in range(1, 11)]
        values = [1, 0, 2, 0, 3, 0, 1, 2, 0, 1]
        activity_df = _daily_activity_df(dates, values)

        fig = _build_calendar_heatmap_figure(activity_df)
        z = fig.data[0].z
        flat = [cell for row in z for cell in row]
        non_nan = [
            cell
            for cell in flat
            if cell is not None and not (isinstance(cell, float) and math.isnan(cell))
        ]

        # Every real day in the input range must land in exactly one cell — zero-activity
        # days included, as genuine numeric 0s, never NaN/masked holes.
        self.assertEqual(len(non_nan), len(activity_df))
        self.assertIn(0, non_nan)

    def test_hover_includes_date_and_count(self) -> None:
        from pages.overview import _build_calendar_heatmap_figure

        dates = ["2024-03-01", "2024-03-02", "2024-03-03"]
        values = [5, 6, 7]
        activity_df = _daily_activity_df(dates, values)

        fig = _build_calendar_heatmap_figure(activity_df)
        trace = fig.data[0]
        combined = " ".join(
            str(part)
            for part in (trace.hovertemplate, trace.text, trace.customdata)
            if part is not None
        )

        self.assertIn("2024-03", combined)
        self.assertTrue(any(str(v) in combined for v in values))


class TestRenderActivityCalendarEmptyStates(unittest.TestCase):
    """Early-return / empty-state branches of ``render_activity_calendar``."""

    @patch("streamlit.plotly_chart")
    @patch("streamlit.info")
    @patch("streamlit.radio")
    @patch("pages.overview.get_daily_activity", create=True)
    def test_df_none_renders_nothing(
        self,
        mock_get_activity: MagicMock,
        mock_radio: MagicMock,
        mock_info: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        render_activity_calendar(None, None)

        mock_get_activity.assert_not_called()
        mock_radio.assert_not_called()
        mock_info.assert_not_called()
        mock_plotly.assert_not_called()

    @patch("streamlit.plotly_chart")
    @patch("streamlit.info")
    @patch("streamlit.radio")
    @patch("pages.overview.get_daily_activity", create=True)
    def test_df_empty_renders_nothing(
        self,
        mock_get_activity: MagicMock,
        mock_radio: MagicMock,
        mock_info: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        render_activity_calendar(pd.DataFrame(), None)

        mock_get_activity.assert_not_called()
        mock_radio.assert_not_called()
        mock_info.assert_not_called()
        mock_plotly.assert_not_called()

    @patch("streamlit.plotly_chart")
    @patch("streamlit.info")
    @patch("streamlit.container")
    @patch("streamlit.radio")
    @patch("pages.overview.get_daily_activity", create=True)
    def test_empty_activity_result_shows_info_not_chart(
        self,
        mock_get_activity: MagicMock,
        mock_radio: MagicMock,
        mock_container: MagicMock,
        mock_info: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        mock_get_activity.return_value = pd.DataFrame({"date": [], "value": []})
        df = _music_df(["2024-01-01"])

        render_activity_calendar(df, None)

        mock_info.assert_called_once()
        mock_plotly.assert_not_called()


class TestRenderActivityCalendarSourceSelector(unittest.TestCase):
    """Source-selector wiring: radio visibility + get_daily_activity source mapping."""

    @patch("streamlit.plotly_chart")
    @patch("streamlit.container")
    @patch("streamlit.radio")
    @patch("pages.overview._build_calendar_heatmap_figure", create=True)
    @patch("pages.overview.get_daily_activity", create=True)
    def test_no_swarm_data_no_radio_shown_uses_source_all(
        self,
        mock_get_activity: MagicMock,
        mock_build_fig: MagicMock,
        mock_radio: MagicMock,
        mock_container: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        mock_get_activity.return_value = _daily_activity_df(["2024-01-01"], [1])
        mock_build_fig.return_value = MagicMock()
        df = _music_df(["2024-01-01"])

        render_activity_calendar(df, None)

        mock_radio.assert_not_called()
        self.assertEqual(_activity_source(mock_get_activity.call_args), "all")

    @patch("streamlit.plotly_chart")
    @patch("streamlit.container")
    @patch("streamlit.radio")
    @patch("pages.overview._build_calendar_heatmap_figure", create=True)
    @patch("pages.overview.get_daily_activity", create=True)
    def test_swarm_present_but_empty_no_radio_uses_source_all(
        self,
        mock_get_activity: MagicMock,
        mock_build_fig: MagicMock,
        mock_radio: MagicMock,
        mock_container: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        mock_get_activity.return_value = _daily_activity_df(["2024-01-01"], [1])
        mock_build_fig.return_value = MagicMock()
        df = _music_df(["2024-01-01"])

        render_activity_calendar(df, pd.DataFrame())

        mock_radio.assert_not_called()
        self.assertEqual(_activity_source(mock_get_activity.call_args), "all")

    @patch("streamlit.plotly_chart")
    @patch("streamlit.container")
    @patch("streamlit.radio")
    @patch("pages.overview._build_calendar_heatmap_figure", create=True)
    @patch("pages.overview.get_daily_activity", create=True)
    def test_swarm_present_shows_radio_with_three_options(
        self,
        mock_get_activity: MagicMock,
        mock_build_fig: MagicMock,
        mock_radio: MagicMock,
        mock_container: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        mock_radio.return_value = "All activity"
        mock_get_activity.return_value = _daily_activity_df(["2024-01-01"], [1])
        mock_build_fig.return_value = MagicMock()
        df = _music_df(["2024-01-01"])
        swarm_df = _swarm_activity_df(["2024-01-01"])

        render_activity_calendar(df, swarm_df)

        mock_radio.assert_called_once()
        self.assertEqual(
            _radio_options(mock_radio.call_args),
            ["All activity", "Music", "Check-ins"],
        )

    @patch("streamlit.plotly_chart")
    @patch("streamlit.container")
    @patch("streamlit.radio")
    @patch("pages.overview._build_calendar_heatmap_figure", create=True)
    @patch("pages.overview.get_daily_activity", create=True)
    def test_selecting_music_maps_to_source_music(
        self,
        mock_get_activity: MagicMock,
        mock_build_fig: MagicMock,
        mock_radio: MagicMock,
        mock_container: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        mock_radio.return_value = "Music"
        mock_get_activity.return_value = _daily_activity_df(["2024-01-01"], [1])
        mock_build_fig.return_value = MagicMock()
        df = _music_df(["2024-01-01"])
        swarm_df = _swarm_activity_df(["2024-01-01"])

        render_activity_calendar(df, swarm_df)

        self.assertEqual(_activity_source(mock_get_activity.call_args), "music")

    @patch("streamlit.plotly_chart")
    @patch("streamlit.container")
    @patch("streamlit.radio")
    @patch("pages.overview._build_calendar_heatmap_figure", create=True)
    @patch("pages.overview.get_daily_activity", create=True)
    def test_selecting_checkins_maps_to_source_checkins(
        self,
        mock_get_activity: MagicMock,
        mock_build_fig: MagicMock,
        mock_radio: MagicMock,
        mock_container: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        mock_radio.return_value = "Check-ins"
        mock_get_activity.return_value = _daily_activity_df(["2024-01-01"], [1])
        mock_build_fig.return_value = MagicMock()
        df = _music_df(["2024-01-01"])
        swarm_df = _swarm_activity_df(["2024-01-01"])

        render_activity_calendar(df, swarm_df)

        self.assertEqual(_activity_source(mock_get_activity.call_args), "checkins")

    @patch("streamlit.plotly_chart")
    @patch("streamlit.container")
    @patch("streamlit.radio")
    @patch("pages.overview._build_calendar_heatmap_figure", create=True)
    @patch("pages.overview.get_daily_activity", create=True)
    def test_selecting_all_activity_maps_to_source_all(
        self,
        mock_get_activity: MagicMock,
        mock_build_fig: MagicMock,
        mock_radio: MagicMock,
        mock_container: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        mock_radio.return_value = "All activity"
        mock_get_activity.return_value = _daily_activity_df(["2024-01-01"], [1])
        mock_build_fig.return_value = MagicMock()
        df = _music_df(["2024-01-01"])
        swarm_df = _swarm_activity_df(["2024-01-01"])

        render_activity_calendar(df, swarm_df)

        self.assertEqual(_activity_source(mock_get_activity.call_args), "all")


class TestRenderActivityCalendarChartRendering(unittest.TestCase):
    """Chart-rendering path: figure built + ``st.plotly_chart(..., width="stretch")``."""

    @patch("streamlit.plotly_chart")
    @patch("streamlit.container")
    @patch("streamlit.radio")
    @patch("pages.overview._build_calendar_heatmap_figure", create=True)
    @patch("pages.overview.get_daily_activity", create=True)
    def test_renders_chart_with_width_stretch(
        self,
        mock_get_activity: MagicMock,
        mock_build_fig: MagicMock,
        mock_radio: MagicMock,
        mock_container: MagicMock,
        mock_plotly: MagicMock,
    ) -> None:
        from pages.overview import render_activity_calendar

        mock_get_activity.return_value = _daily_activity_df(["2024-01-01"], [1])
        sentinel_fig = MagicMock()
        mock_build_fig.return_value = sentinel_fig
        df = _music_df(["2024-01-01"])

        render_activity_calendar(df, None)

        mock_plotly.assert_called_once()
        args, kwargs = mock_plotly.call_args
        self.assertEqual(args[0], sentinel_fig)
        self.assertEqual(kwargs.get("width"), "stretch")
        self.assertNotIn("use_container_width", kwargs)


class TestRenderOverviewCallsActivityCalendar(unittest.TestCase):
    """Call-site wiring: render_overview() invokes render_activity_calendar (issue #27)."""

    @patch("pages.overview.render_activity_calendar", create=True)
    @patch("pages.overview.render_time_machine_card")
    @patch("pages.overview.render_share_button")
    @patch("pages.overview.build_overview_page_html", return_value="<html></html>")
    @patch("streamlit.markdown")
    def test_render_overview_calls_activity_calendar_after_time_machine(
        self,
        mock_markdown: MagicMock,
        mock_build_html: MagicMock,
        mock_share: MagicMock,
        mock_time_machine: MagicMock,
        mock_activity_cal: MagicMock,
    ) -> None:
        from pages.overview import render_overview

        df = _music_df(["2024-01-01", "2024-01-02"])
        swarm_df = _swarm_activity_df(["2024-01-01"])

        # Track relative call order across the two mocks via a shared manager.
        manager = MagicMock()
        manager.attach_mock(mock_time_machine, "time_machine")
        manager.attach_mock(mock_activity_cal, "activity_cal")

        with patch("streamlit.session_state", {"df": df, "swarm_df": swarm_df}):
            render_overview()

        mock_time_machine.assert_called_once_with(df, swarm_df)
        mock_activity_cal.assert_called_once_with(df, swarm_df)

        call_order = [call[0] for call in manager.mock_calls]
        self.assertEqual(call_order, ["time_machine", "activity_cal"])


if __name__ == "__main__":
    unittest.main()
