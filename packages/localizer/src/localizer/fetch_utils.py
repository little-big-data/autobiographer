"""Utilities for resumable data fetches: checkpointing and retry logic."""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import requests

T = TypeVar("T")

CHECKPOINT_MAX_AGE_HOURS = 168  # 7 days


class FetchCheckpoint:
    """Manages incremental checkpoint state for resumable multi-page fetches.

    Two files are maintained per checkpoint:

    - ``{dir}/.checkpoint_{key}.json`` — page state (last completed page, totals)
    - ``{dir}/.checkpoint_{key}_tracks.csv`` — accumulated track rows for resume

    A checkpoint is stale (raises ``ValueError`` on ``load()``) if it was created
    more than ``CHECKPOINT_MAX_AGE_HOURS`` hours ago.

    Args:
        checkpoint_dir: Directory where checkpoint files are stored.
        plugin_id: Unique plugin identifier (e.g. ``"lastfm"``).
        identity: User identity string (e.g. ``"@username"``).
        from_ts: Fetch lower-bound timestamp (affects checkpoint key).
        to_ts: Fetch upper-bound timestamp (affects checkpoint key).
        pages_limit: Maximum pages to fetch (affects checkpoint key).
    """

    def __init__(
        self,
        checkpoint_dir: str,
        plugin_id: str,
        identity: str,
        from_ts: int | None = None,
        to_ts: int | None = None,
        pages_limit: int | None = None,
    ) -> None:
        self._dir = checkpoint_dir
        safe_identity = identity.lstrip("@").replace("/", "_").replace("\\", "_")
        from_part = str(from_ts) if from_ts is not None else "all"
        to_part = str(to_ts) if to_ts is not None else "all"
        pages_part = str(pages_limit) if pages_limit is not None else "all"
        key = f"{plugin_id}_{safe_identity}_{from_part}_{to_part}_{pages_part}"
        self._state_path = os.path.join(checkpoint_dir, f".checkpoint_{key}.json")
        self._tracks_path = os.path.join(checkpoint_dir, f".checkpoint_{key}_tracks.csv")
        self._tracks_fetched: int = 0

    @property
    def tracks_fetched(self) -> int:
        """Number of tracks accumulated so far (from checkpoint + current run)."""
        return self._tracks_fetched

    def load(self) -> tuple[int, list[dict[str, Any]]] | None:
        """Load checkpoint state and accumulated tracks.

        Returns:
            ``(last_completed_page, accumulated_tracks)`` or ``None`` if no
            checkpoint file exists.

        Raises:
            ValueError: If the checkpoint is older than ``CHECKPOINT_MAX_AGE_HOURS``
                hours (stale checkpoint).
        """
        if not os.path.exists(self._state_path):
            return None

        try:
            with open(self._state_path, encoding="utf-8") as fh:
                state: dict[str, Any] = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None

        created_at_str = state.get("created_at", "")
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
                age_hours = (datetime.now(tz=timezone.utc) - created_at).total_seconds() / 3600
                if age_hours > CHECKPOINT_MAX_AGE_HOURS:
                    max_h = CHECKPOINT_MAX_AGE_HOURS
                    raise ValueError(
                        f"Stale checkpoint: {age_hours:.0f}h old (max {max_h}h). "
                        "Run without --resume to start a fresh fetch."
                    )
            except (TypeError, AttributeError):
                return None

        last_page: int = int(state.get("last_completed_page", 0))

        tracks: list[dict[str, Any]] = []
        if os.path.exists(self._tracks_path):
            try:
                with open(self._tracks_path, newline="", encoding="utf-8") as fh:
                    tracks = [_unflatten_track(row) for row in csv.DictReader(fh)]
            except Exception:  # noqa: BLE001
                tracks = []

        self._tracks_fetched = len(tracks)
        return last_page, tracks

    def save(self, current_page: int, total_pages: int, new_tracks: list[dict[str, Any]]) -> None:
        """Persist checkpoint state and append new tracks.

        Args:
            current_page: The page that just completed successfully.
            total_pages: Total page count as reported by the API.
            new_tracks: Tracks fetched on ``current_page`` to append.
        """
        os.makedirs(self._dir, exist_ok=True)

        created_at: str
        if os.path.exists(self._state_path):
            try:
                with open(self._state_path, encoding="utf-8") as fh:
                    existing: dict[str, Any] = json.load(fh)
                fallback = datetime.now(tz=timezone.utc).isoformat()
                created_at = str(existing.get("created_at", fallback))
            except Exception:  # noqa: BLE001
                created_at = datetime.now(tz=timezone.utc).isoformat()
        else:
            created_at = datetime.now(tz=timezone.utc).isoformat()

        self._tracks_fetched += len(new_tracks)

        state: dict[str, Any] = {
            "created_at": created_at,
            "last_completed_page": current_page,
            "total_pages": total_pages,
            "tracks_fetched": self._tracks_fetched,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        tmp = self._state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, self._state_path)

        flat_tracks = [_flatten_track(t) for t in new_tracks]
        if flat_tracks:
            file_exists = os.path.exists(self._tracks_path)
            with open(self._tracks_path, "a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(flat_tracks[0].keys()))
                if not file_exists:
                    writer.writeheader()
                writer.writerows(flat_tracks)

    def clear(self) -> None:
        """Remove checkpoint files after a successful complete fetch."""
        for path in (self._state_path, self._tracks_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def _flatten_track(track: dict[str, Any]) -> dict[str, str]:
    """Flatten a nested Last.fm track dict to a flat string dict for CSV storage."""
    return {
        "artist__text": str((track.get("artist") or {}).get("#text") or ""),
        "album__text": str((track.get("album") or {}).get("#text") or ""),
        "name": str(track.get("name") or ""),
        "date__uts": str((track.get("date") or {}).get("uts") or ""),
        "date__text": str((track.get("date") or {}).get("#text") or ""),
    }


def _unflatten_track(flat: dict[str, str]) -> dict[str, Any]:
    """Restore nested Last.fm track structure from a flat CSV row."""
    return {
        "artist": {"#text": flat.get("artist__text", "")},
        "album": {"#text": flat.get("album__text", "")},
        "name": flat.get("name", ""),
        "date": {"uts": flat.get("date__uts", ""), "#text": flat.get("date__text", "")},
    }


def retry_with_backoff(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """Execute ``fn``, retrying with exponential backoff on ``RequestException``.

    Args:
        fn: Callable to execute (called with no arguments).
        max_retries: Maximum number of additional attempts after the first failure.
        base_delay: Initial retry delay in seconds; doubles with each attempt.
        on_retry: Optional callback invoked as ``on_retry(attempt, exc)`` before
            sleeping, where ``attempt`` is 1-based.

    Returns:
        Return value of a successful ``fn()`` call.

    Raises:
        requests.exceptions.RequestException: After all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            delay = base_delay * (2.0**attempt)
            if on_retry:
                on_retry(attempt + 1, exc)
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]
