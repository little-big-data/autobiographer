"""Integration tests for the Discovery Zones page."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd


def _make_df(
    *,
    with_geo: bool = True,
    n_artists: int = 3,
) -> pd.DataFrame:
    """Build a minimal listening history DataFrame for testing.

    Args:
        with_geo: Include ``city``, ``lat``, ``lng``, ``country`` columns.
        n_artists: Number of distinct artists to include.

    Returns:
        DataFrame suitable for passing to ``render_discovery_zones``.
    """
    artists = [f"Artist {i}" for i in range(n_artists)]
    rows = []
    base_ts = 1_610_000_000
    for idx, artist in enumerate(artists):
        for play in range(idx + 1):  # artist 0 has 1 play, artist 1 has 2, etc.
            rows.append(
                {
                    "artist": artist,
                    "track": f"{artist} — Track {play}",
                    "album": f"{artist} Album",
                    "timestamp": base_ts + idx * 1000 + play * 10,
                    "date_text": pd.Timestamp("2021-01-01") + pd.Timedelta(days=idx * 30 + play),
                    "city": f"City {idx}" if with_geo else None,
                    "country": f"Country {idx}" if with_geo else None,
                    "lat": 51.5 + idx * 5.0 if with_geo else None,
                    "lng": -0.1 + idx * 5.0 if with_geo else None,
                }
            )
    df = pd.DataFrame(rows)
    return df


class TestRenderDiscoveryZones(unittest.TestCase):
    """Smoke-tests for render_discovery_zones under mocked Streamlit."""

    def _patch_st(self) -> dict:
        """Return a dict of patches for Streamlit surface area."""

        def _make_cm() -> MagicMock:
            m = MagicMock()
            m.__enter__ = MagicMock(return_value=m)
            m.__exit__ = MagicMock(return_value=False)
            return m

        # selectbox is called 3 times: rate-grouping, city filter, year filter
        selectbox_values = ["Monthly", "All cities", "All years"]
        selectbox_iter = iter(selectbox_values)

        return {
            "streamlit.info": patch("streamlit.info"),
            "streamlit.warning": patch("streamlit.warning"),
            "streamlit.header": patch("streamlit.header"),
            "streamlit.caption": patch("streamlit.caption"),
            "streamlit.subheader": patch("streamlit.subheader"),
            "streamlit.divider": patch("streamlit.divider"),
            "streamlit.plotly_chart": patch("streamlit.plotly_chart"),
            "streamlit.dataframe": patch("streamlit.dataframe"),
            "streamlit.columns": patch(
                "streamlit.columns",
                side_effect=lambda n: [
                    _make_cm() for _ in range(len(n) if isinstance(n, list) else n)
                ],
            ),
            "streamlit.selectbox": patch(
                "streamlit.selectbox",
                side_effect=lambda *a, **kw: next(selectbox_iter),
            ),
            "streamlit.slider": patch("streamlit.slider", return_value=15),
        }

    def test_empty_state_when_no_df(self) -> None:
        """Shows info message when no data is loaded."""
        patches = self._patch_st()
        ctx_managers = {k: p.start() for k, p in patches.items()}
        try:
            with patch("streamlit.session_state", {}):
                from pages.discovery_zones import render_discovery_zones

                render_discovery_zones()
            ctx_managers["streamlit.info"].assert_called_once()
        finally:
            for p in patches.values():
                p.stop()

    def test_renders_with_geo_data(self) -> None:
        """Renders discovery map and rate chart when geographic data is present."""
        df = _make_df(with_geo=True, n_artists=3)
        patches = self._patch_st()
        ctx_managers = {k: p.start() for k, p in patches.items()}
        try:
            with patch("streamlit.session_state", {"df": df}):
                from pages.discovery_zones import render_discovery_zones

                render_discovery_zones()
            # plotly_chart should be called at least twice
            # (discovery rate + discovery map)
            self.assertGreaterEqual(ctx_managers["streamlit.plotly_chart"].call_count, 2)
        finally:
            for p in patches.values():
                p.stop()

    def test_degrades_gracefully_without_geo(self) -> None:
        """Shows info when no lat/lng, but still renders rate chart."""
        df = _make_df(with_geo=False, n_artists=3)
        patches = self._patch_st()
        ctx_managers = {k: p.start() for k, p in patches.items()}
        try:
            with patch("streamlit.session_state", {"df": df}):
                from pages.discovery_zones import render_discovery_zones

                render_discovery_zones()
            # Rate chart should still render
            self.assertGreaterEqual(ctx_managers["streamlit.plotly_chart"].call_count, 1)
            # Info about missing geo should appear
            ctx_managers["streamlit.info"].assert_called()
        finally:
            for p in patches.values():
                p.stop()

    def test_yearly_grouping_option(self) -> None:
        """Yearly grouping option does not raise and renders a chart."""
        df = _make_df(with_geo=False, n_artists=2)
        patches = self._patch_st()
        # Override: rate grouping="Yearly", city="All cities", year="All years"
        yearly_vals = iter(["Yearly", "All cities", "All years"])
        patches["streamlit.selectbox"] = patch(
            "streamlit.selectbox",
            side_effect=lambda *a, **kw: next(yearly_vals),
        )
        ctx_managers = {k: p.start() for k, p in patches.items()}
        try:
            with patch("streamlit.session_state", {"df": df}):
                from pages.discovery_zones import render_discovery_zones

                render_discovery_zones()
            self.assertGreaterEqual(ctx_managers["streamlit.plotly_chart"].call_count, 1)
        finally:
            for p in patches.values():
                p.stop()


if __name__ == "__main__":
    unittest.main()
