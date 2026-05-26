"""Shared 'Share this view' download button component."""

from __future__ import annotations

import streamlit as st


def render_share_button(html_bytes: bytes, filename: str) -> None:
    """Render a right-aligned 'Share this view' download button.

    Uses a two-column layout so the button floats to the top-right of the page
    content area without displacing other elements.

    Args:
        html_bytes: UTF-8-encoded self-contained HTML to offer as a download.
        filename: Suggested download filename (e.g.
            ``"autobiographer-music-2024-01-01-to-2024-01-07.html"``).
    """
    _, btn_col = st.columns([8, 2])
    with btn_col:
        st.download_button(
            label="Share this view",
            data=html_bytes,
            file_name=filename,
            mime="text/html",
            width="stretch",
            help="Download a self-contained HTML snapshot of this page",
        )
