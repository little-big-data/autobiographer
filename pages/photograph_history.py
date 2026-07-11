"""Photograph History page — chronological browsing of Flickr photo events.

Reads the ``flickr`` source's EVENTS-shaped rows directly from the localizer
DuckDB store (bypassing ``core/broker.py``, which stays untouched here) so
every photo — geotagged or not — shows up as a timeline entry with a
clickable link to its original Flickr photo page.

The geotagged subset already has its own dedicated view: Geo Explorer, fed by
the unchanged PLACES pipeline. This page cross-links there rather than
duplicating any map rendering.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

_ALL = "All"


def _load_flickr_events_df() -> pd.DataFrame:
    """Query the localizer store for flickr EVENTS rows, including raw_json.

    Returns:
        DataFrame with columns [timestamp, label, sublabel, category,
        source_id, raw_json], or an empty DataFrame if the store is missing,
        unreadable, or has no flickr event rows.
    """
    try:
        from localizer.store.db import LocalizerStore  # noqa: PLC0415

        with LocalizerStore() as store:
            return store.query_events(source_id="flickr", include_raw_json=True)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


def _parse_raw_json(raw: Any) -> dict[str, Any]:
    """Parse a raw_json cell (JSON string, dict, or missing) into a dict.

    Args:
        raw: The raw_json cell value — a JSON string, an already-parsed
            dict, or a falsy/NaN value.

    Returns:
        Parsed dict, or {} when raw is empty or unparsable.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_photo_table(events_df: pd.DataFrame) -> pd.DataFrame:
    """Adapt raw flickr EVENTS rows into a display-ready photo table.

    Args:
        events_df: DataFrame with columns [timestamp, label, sublabel,
            category, source_id, raw_json] — the shape returned by
            :func:`_load_flickr_events_df`.

    Returns:
        DataFrame with columns [date, title, album, tags, url], sorted by
        date descending (most recent photo first). ``tags`` is a list of
        strings per row. Empty input returns an empty frame with these
        columns.
    """
    columns = ["date", "title", "album", "tags", "url"]
    if events_df is None or events_df.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for _, row in events_df.iterrows():
        raw = _parse_raw_json(row.get("raw_json"))
        tags = raw.get("tags")
        rows.append(
            {
                "date": pd.to_datetime(row["timestamp"], unit="s"),
                "title": row.get("label") or "",
                "album": row.get("sublabel") or "",
                "tags": list(tags) if isinstance(tags, list) else [],
                "url": raw.get("photopage") or "",
            }
        )

    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values("date", ascending=False)
        .reset_index(drop=True)
    )


def get_tag_options(photo_df: pd.DataFrame) -> list[str]:
    """Return the sorted, de-duplicated set of tags across all photos.

    Args:
        photo_df: A photo table from :func:`build_photo_table`.

    Returns:
        ``["All"]`` when empty or lacking a ``tags`` column, else ``["All"]``
        followed by every distinct tag, alphabetically sorted.
    """
    if photo_df is None or photo_df.empty or "tags" not in photo_df.columns:
        return [_ALL]
    all_tags: set[str] = set()
    for tags in photo_df["tags"]:
        if isinstance(tags, list):
            all_tags.update(tags)
    return [_ALL, *sorted(all_tags)]


def get_album_options(photo_df: pd.DataFrame) -> list[str]:
    """Return the sorted, de-duplicated set of non-empty albums.

    Args:
        photo_df: A photo table from :func:`build_photo_table`.

    Returns:
        ``["All"]`` when empty or lacking an ``album`` column, else
        ``["All"]`` followed by every distinct non-empty album name.
    """
    if photo_df is None or photo_df.empty or "album" not in photo_df.columns:
        return [_ALL]
    albums = sorted({a for a in photo_df["album"] if a})
    return [_ALL, *albums]


def filter_photos(photo_df: pd.DataFrame, tag: str, album: str) -> pd.DataFrame:
    """Filter a photo table down to a selected tag and/or album.

    Args:
        photo_df: A photo table from :func:`build_photo_table`.
        tag: A tag previously returned by :func:`get_tag_options`, or "All".
        album: An album previously returned by :func:`get_album_options`, or "All".

    Returns:
        ``photo_df`` unchanged when both filters are "All" (or the frame is
        empty). Otherwise the subset of rows matching both filters, with a
        reset index. The input frame is never mutated.
    """
    if photo_df is None or photo_df.empty:
        return photo_df

    mask = pd.Series(True, index=photo_df.index)
    if tag != _ALL:
        mask &= photo_df["tags"].apply(lambda tags: isinstance(tags, list) and tag in tags)
    if album != _ALL:
        mask &= photo_df["album"] == album

    return photo_df[mask].reset_index(drop=True)


def render_photograph_history() -> None:
    """Render the Photograph History page.

    Shows a chronological timeline of every Flickr photo (geotagged or not)
    with a clickable link to its original Flickr photo page, filterable by
    tag and album. Shows an empty-state banner when no Flickr data has been
    configured/synced yet.
    """
    st.header("Photograph History")
    st.caption("Every photo from your Flickr export, in chronological order.")

    events_df = _load_flickr_events_df()
    photo_df = build_photo_table(events_df)

    if photo_df.empty:
        st.info(
            "No Flickr photo data loaded yet. "
            "Configure the Flickr Photos source under Sources and run a sync "
            "to populate your photograph history."
        )
        return

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        selected_tag = st.selectbox("Tag", get_tag_options(photo_df), key="photo_history_tag")
    with filter_col2:
        selected_album = st.selectbox(
            "Album", get_album_options(photo_df), key="photo_history_album"
        )

    filtered = filter_photos(photo_df, selected_tag, selected_album)

    st.caption(f"Showing {len(filtered):,} of {len(photo_df):,} photos")

    display = filtered.copy()
    display["tags"] = display["tags"].apply(lambda tags: ", ".join(tags) if tags else "")

    st.dataframe(
        display.rename(
            columns={
                "date": "Date",
                "title": "Title",
                "album": "Album",
                "tags": "Tags",
                "url": "Link",
            }
        ),
        column_config={
            "Link": st.column_config.LinkColumn("Link", display_text="Open on Flickr"),
        },
        hide_index=True,
        width="stretch",
    )

    st.caption(
        "Tip: geotagged photos from this same Flickr export also appear on the "
        "**Geo Explorer** map (Overview → Geo Explorer)."
    )
