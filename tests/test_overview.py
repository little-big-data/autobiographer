"""Tests for the Overview page's Time Machine card (``pages/overview.py``, issue #98).

Mocks Streamlit's ``markdown``/``info`` and injects a fixed ``today``/seeded
``random.Random`` into ``render_time_machine_card`` so these are fast, deterministic
smoke tests of the page's wiring — the actual "this day in history" data-shaping logic
is covered independently by ``tests/test_time_machine.py``.
"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
