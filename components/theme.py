"""Shared dark-theme palette, Plotly template, and layout helpers.

All visual components — Plotly charts, pydeck maps, and page layout — pull
their colours from this module so the application looks consistent.

Deep Space Indigo palette
--------------------------
The primary accent is indigo (#6366f1).  Charts rotate through a seven-colour
categorical sequence that contrasts clearly against the near-black backgrounds.
Map overlays retain the legacy teal/amber pair which reads well on the pydeck
dark basemap.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---------------------------------------------------------------------------
# Deep Space Indigo palette
# ---------------------------------------------------------------------------

APP_BG = "#0c1120"
CARD_BG = "#141c2f"
SIDEBAR_BG = "#090e1a"
LIFTED_BG = "#1e293b"
BORDER = "#2d3a52"
TEXT_PRIMARY = "#f0f4ff"
TEXT_DIM = "#8895a7"
TEXT_MUTED = "#4b5a72"

ACCENT_INDIGO = "#6366f1"
ACCENT_CYAN = "#22d3ee"
ACCENT_PINK = "#f472b6"
ACCENT_PURPLE = "#a855f7"
ACCENT_GREEN = "#22c55e"
ACCENT_ORANGE = "#f97316"
ACCENT_YELLOW = "#facc15"

# Categorical colour sequence — used by bar, pie, line, and scatter charts.
COLORWAY: list[str] = [
    ACCENT_INDIGO,
    ACCENT_CYAN,
    ACCENT_PINK,
    ACCENT_PURPLE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_YELLOW,
]

# Sequential scale for continuous heatmaps (dark → indigo → cyan).
SEQUENTIAL_SCALE: list[list[object]] = [
    [0.0, "#1e1b4b"],
    [0.5, ACCENT_INDIGO],
    [1.0, ACCENT_CYAN],
]

# Calendar heatmap scale (GitHub-contribution-graph style, issue #27) —
# dark card background → dark-indigo → indigo → cyan.
CALENDAR_HEATMAP_SCALE: list[list[object]] = [
    [0.0, CARD_BG],
    [0.3, "#312e81"],
    [0.7, ACCENT_INDIGO],
    [1.0, ACCENT_CYAN],
]

# ---------------------------------------------------------------------------
# Backward-compatible aliases — used by music.py traces and record_flythrough
# ---------------------------------------------------------------------------

TEAL = ACCENT_CYAN
AMBER = ACCENT_ORANGE

# ---------------------------------------------------------------------------
# Map colours (for pydeck layers in places.py)
# ---------------------------------------------------------------------------

MAP_COUNTRY_VISITED_RGBA: list[int] = [99, 102, 241, 70]
MAP_COUNTRY_UNVISITED_RGBA: list[int] = [20, 28, 47, 30]
MAP_COUNTRY_BORDER_RGB: list[int] = [45, 58, 82]
MAP_STATE_BORDER_RGBA: list[int] = [45, 58, 82, 100]
MAP_COLUMN_DEFAULT_RGBA: list[int] = [99, 102, 241, 180]

# ---------------------------------------------------------------------------
# Plotly template — registered globally at import time
# ---------------------------------------------------------------------------

_AUTOBIO_TEMPLATE = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_PRIMARY, family="Inter, system-ui, sans-serif"),
        colorway=COLORWAY,
        xaxis=dict(
            gridcolor=BORDER,
            zerolinecolor=BORDER,
            linecolor=BORDER,
        ),
        yaxis=dict(
            gridcolor=BORDER,
            zerolinecolor=BORDER,
            linecolor=BORDER,
        ),
        hoverlabel=dict(
            bgcolor=CARD_BG,
            bordercolor=BORDER,
            font_color=TEXT_PRIMARY,
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor=BORDER,
            font_color=TEXT_DIM,
        ),
    )
)

pio.templates["autobio_dark"] = _AUTOBIO_TEMPLATE
pio.templates.default = "autobio_dark"

PLOTLY_TEMPLATE = "autobio_dark"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def apply_dark_theme(fig: go.Figure) -> go.Figure:
    """Apply the autobio_dark template to a Plotly figure.

    In most cases this is unnecessary because ``pio.templates.default``
    is already set at import time.  Use it explicitly for figures that
    need the transparent background override regardless of template state.

    Args:
        fig: Any Plotly Figure object.

    Returns:
        The same figure, mutated in place and returned for chaining.
    """
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        colorway=COLORWAY,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


@contextmanager
def card_container() -> Iterator[None]:
    """Yield a Streamlit container styled as a dark card.

    Wraps the yielded block in a bordered ``st.container()`` whose visual
    style is controlled by the CSS injected in ``visualize.py``.

    Usage::

        with card_container():
            st.plotly_chart(fig, width="stretch")
    """
    with st.container(border=True):
        yield
