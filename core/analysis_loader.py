"""Bridge to analysis_utils for backwards-compatible plugin loading.

This module exists so that the plugin layer (plugins/) can load data without
directly importing analysis_utils functions that have been moved to localizer.
Keeping this bridge in core/ (not plugins/) means the plugins/ directory
contains no direct references to legacy loading functions.

Also contains ``_count_records_at_path`` which was moved here from
``plugins.sources.base`` to keep the plugins/ tree free of CSV-reading code.
"""

from __future__ import annotations

import json
import os

import pandas as pd


def load_lastfm_history(data_path: str) -> pd.DataFrame | None:
    """Load Last.fm listening history from a CSV file.

    Delegates to analysis_utils.load_listening_data. Kept in core/ so the
    plugins/ layer stays free of direct analysis_utils references.

    Args:
        data_path: Path to the Last.fm CSV file.

    Returns:
        DataFrame of listening history, or None if the file is missing.
    """
    from analysis_utils import load_listening_data  # noqa: PLC0415

    return load_listening_data(data_path)


def load_swarm_history(swarm_dir: str) -> pd.DataFrame:
    """Load Swarm check-in history from a directory of JSON files.

    Delegates to analysis_utils.load_swarm_data. Kept in core/ so the
    plugins/ layer stays free of direct analysis_utils references.

    Args:
        swarm_dir: Path to the directory containing Swarm JSON export files.

    Returns:
        DataFrame of check-in history.
    """
    from analysis_utils import load_swarm_data  # noqa: PLC0415

    return load_swarm_data(swarm_dir)


def _count_records_at_path(path: str) -> int | None:
    """Return a record count for a file or directory.

    CSV → row count; JSON file → top-level list length; directory → total
    items across all .json files in the directory.  Returns None on any error.

    Moved from ``plugins.sources.base`` to keep plugins/ free of CSV-reading
    code. Import from here instead of from ``plugins.sources.base``.

    Args:
        path: File or directory path to count records for.

    Returns:
        Integer record count, or None if the path cannot be read.
    """
    try:
        if os.path.isdir(path):
            total = 0
            for fname in os.listdir(path):
                if fname.lower().endswith(".json"):
                    with open(os.path.join(path, fname)) as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        total += len(data)
            return total or None
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            return len(pd.read_csv(path))
        with open(path) as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else None
    except Exception:  # noqa: BLE001
        return None
