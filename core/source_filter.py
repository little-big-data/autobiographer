"""Pure source->label mapping and filtering helper for `swarm_df`-shaped frames.

Both `swarm_df` pipelines (the broker/DuckDB path via `core/localizer_frames.py` and the
legacy flat-file path via `components/sidebar.py`) now tag each row with a `source_id`
(`"swarm"` or `"google_timeline"`, with room for future plugins). This module is the
single place the source->label mapping and the corresponding filtering logic live, so
the two consuming pages (`pages/geo_explorer.py`, `pages/places.py`) never duplicate or
drift from each other.

This module is intentionally Streamlit- and DuckDB-free: it is pure DataFrame-in/
DataFrame-out logic, independently testable with hand-built fixtures, mirroring
`core/localizer_frames.py`'s existing convention.
"""

from __future__ import annotations

import pandas as pd

SOURCE_LABELS = {"swarm": "Swarm", "google_timeline": "Google Timeline"}


def source_label(source_id: str) -> str:
    """Map a raw `source_id` value to a human-readable label.

    Args:
        source_id: The raw source identifier (e.g. `"swarm"`, `"google_timeline"`).

    Returns:
        The known label from `SOURCE_LABELS` if present, otherwise a humanized
        fallback (`source_id.replace("_", " ").title()`) so unrecognized/future
        source ids never crash or get hidden.
    """
    return SOURCE_LABELS.get(source_id, source_id.replace("_", " ").title())


def get_source_options(swarm_df: pd.DataFrame | None) -> list[str]:
    """Compute the selectbox options for a `swarm_df`-shaped frame's `source_id` column.

    Args:
        swarm_df: A `swarm_df`-shaped frame, or `None`.

    Returns:
        `["All"]` when `swarm_df` is `None`, empty, or lacks a `source_id` column.
        Otherwise `["All"]` followed by the sorted, de-duplicated human labels of every
        distinct `source_id` present.
    """
    if swarm_df is None or swarm_df.empty or "source_id" not in swarm_df.columns:
        return ["All"]

    labels = sorted({source_label(source_id) for source_id in swarm_df["source_id"]})
    return ["All", *labels]


def filter_by_source(swarm_df: pd.DataFrame | None, selected_label: str) -> pd.DataFrame | None:
    """Filter a `swarm_df`-shaped frame down to rows matching a selected source label.

    Args:
        swarm_df: A `swarm_df`-shaped frame, or `None`.
        selected_label: A label previously returned by `get_source_options()` (e.g.
            `"All"`, `"Swarm"`, `"Google Timeline"`).

    Returns:
        `swarm_df` unchanged when it is `None`/empty, when `selected_label == "All"`,
        or when the `source_id` column is absent (graceful passthrough, never an
        exception). Otherwise the subset of rows whose `source_label(row.source_id) ==
        selected_label`, with a reset index. The input frame is never mutated.
    """
    if swarm_df is None or swarm_df.empty:
        return swarm_df
    if selected_label == "All" or "source_id" not in swarm_df.columns:
        return swarm_df

    mask = swarm_df["source_id"].map(source_label) == selected_label
    return swarm_df[mask].reset_index(drop=True)
