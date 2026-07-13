"""LocalizerStore: DuckDB-backed store for localizer data."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


class LocalizerStore:
    """Manages a DuckDB file store for localizer events, places, and content.

    Usage::

        with LocalizerStore(path) as store:
            store.upsert_events(records)
            df = store.query_events(source_id="lastfm")

    Args:
        path: Path to the DuckDB file. Defaults to ``~/.localizer/store.duckdb``.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path: Path = Path(path) if path else self.default_path()
        self._conn: duckdb.DuckDBPyConnection | None = None
        self.open()

    @classmethod
    def default_path(cls) -> Path:
        """Return the default DuckDB store path.

        Returns:
            ``~/.localizer/store.duckdb``
        """
        return Path.home() / ".localizer" / "store.duckdb"

    @property
    def conn(self) -> duckdb.DuckDBPyConnection | None:
        """The underlying DuckDB connection, or None if closed."""
        return self._conn

    def open(self) -> None:
        """Open the DuckDB connection and apply migrations."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._path))
        from localizer.store.migrations import apply_migrations  # noqa: PLC0415

        apply_migrations(self._conn)

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> LocalizerStore:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_id(source_id: str, timestamp: int, label: str, sublabel: str | None) -> str:
        """Generate a deterministic 16-hex-char ID.

        Formula: sha256(source_id + str(timestamp) + label + (sublabel or ""))[:16]

        Args:
            source_id: The plugin's source identifier.
            timestamp: Unix timestamp of the event.
            label: Primary label (e.g. artist name).
            sublabel: Secondary label (e.g. track name), or None.

        Returns:
            First 16 hex characters of the SHA-256 digest.
        """
        raw = source_id + str(timestamp) + label + (sublabel or "")
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Upsert methods
    # ------------------------------------------------------------------

    def upsert_events(self, records: list[dict[str, Any]]) -> None:
        """Insert or replace event records.

        Args:
            records: List of dicts with keys: source_id, timestamp, label,
                sublabel, category, raw_json, fetched_at.
        """
        if not records:
            return

        now = int(time.time())
        rows = []
        for rec in records:
            row_id = self._make_id(
                rec["source_id"],
                int(rec["timestamp"]),
                rec["label"],
                rec.get("sublabel"),
            )
            raw_json_val = rec.get("raw_json")
            if raw_json_val is None:
                raw_json_str = json.dumps({})
            elif isinstance(raw_json_val, str):
                raw_json_str = raw_json_val
            else:
                raw_json_str = json.dumps(raw_json_val)

            rows.append(
                (
                    row_id,
                    rec["source_id"],
                    int(rec["timestamp"]),
                    rec["label"],
                    rec.get("sublabel"),
                    rec.get("category"),
                    raw_json_str,
                    int(rec.get("fetched_at", now)),
                )
            )

        assert self._conn is not None
        try:
            self._conn.begin()
            self._conn.executemany(
                "INSERT OR REPLACE INTO events "
                "(id, source_id, timestamp, label, sublabel, category, raw_json, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def upsert_places(self, records: list[dict[str, Any]]) -> None:
        """Insert or replace place records.

        Args:
            records: List of dicts with keys: source_id, timestamp, lat, lng,
                place_name, place_type, raw_json, fetched_at.
        """
        if not records:
            return

        now = int(time.time())
        rows = []
        for rec in records:
            row_id = self._make_id(
                rec["source_id"],
                int(rec["timestamp"]),
                rec.get("place_name") or "",
                rec.get("place_type"),
            )
            raw_json_val = rec.get("raw_json")
            if raw_json_val is None:
                raw_json_str = json.dumps({})
            elif isinstance(raw_json_val, str):
                raw_json_str = raw_json_val
            else:
                raw_json_str = json.dumps(raw_json_val)

            rows.append(
                (
                    row_id,
                    rec["source_id"],
                    int(rec["timestamp"]),
                    float(rec["lat"]),
                    float(rec["lng"]),
                    rec.get("place_name"),
                    rec.get("place_type"),
                    raw_json_str,
                    int(rec.get("fetched_at", now)),
                )
            )

        assert self._conn is not None
        try:
            self._conn.begin()
            self._conn.executemany(
                "INSERT OR REPLACE INTO places "
                "(id, source_id, timestamp, lat, lng, place_name, place_type, "
                "raw_json, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def upsert_content(self, records: list[dict[str, Any]]) -> None:
        """Insert or replace content records.

        Args:
            records: List of dicts with keys: source_id, timestamp, title, url,
                feed_title, author, raw_json, fetched_at.
        """
        if not records:
            return

        now = int(time.time())
        rows = []
        for rec in records:
            row_id = self._make_id(
                rec["source_id"],
                int(rec["timestamp"]),
                rec.get("title") or "",
                rec.get("url"),
            )
            raw_json_val = rec.get("raw_json")
            if raw_json_val is None:
                raw_json_str = json.dumps({})
            elif isinstance(raw_json_val, str):
                raw_json_str = raw_json_val
            else:
                raw_json_str = json.dumps(raw_json_val)

            rows.append(
                (
                    row_id,
                    rec["source_id"],
                    int(rec["timestamp"]),
                    rec.get("title"),
                    rec.get("url"),
                    rec.get("feed_title"),
                    rec.get("author"),
                    raw_json_str,
                    int(rec.get("fetched_at", now)),
                )
            )

        assert self._conn is not None
        try:
            self._conn.begin()
            self._conn.executemany(
                "INSERT OR REPLACE INTO content "
                "(id, source_id, timestamp, title, url, feed_title, author, raw_json, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def query_events(
        self,
        source_id: str | None = None,
        since: int | None = None,
        include_raw_json: bool = False,
    ) -> pd.DataFrame:
        """Query events, returning the backwards-compat what-when schema.

        Args:
            source_id: Filter to this source only; None returns all sources.
            since: Return only rows with timestamp >= since; None returns all.
            include_raw_json: When True, also select the ``raw_json`` column.
                Some plugins (e.g. Untappd, Flickr) stash fields with no
                dedicated events column (rating, venue lat/lng, tags,
                photopage) inside raw_json; callers that need those must opt
                in here rather than via LocalizerBroker.get_events_frame(),
                which intentionally keeps the generic lastfm-shaped column
                set stable for the broader merge pipeline.

        Returns:
            DataFrame with columns [timestamp, label, sublabel, category,
            source_id], plus [raw_json] when include_raw_json is True.
        """
        assert self._conn is not None
        clauses: list[str] = []
        params: list[Any] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        columns = "timestamp, label, sublabel, category, source_id"
        if include_raw_json:
            columns += ", raw_json"
        sql = f"SELECT {columns} FROM events{where}"  # noqa: S608
        return self._conn.execute(sql, params).df()

    def query_places(
        self,
        source_id: str | None = None,
        since: int | None = None,
    ) -> pd.DataFrame:
        """Query places.

        Args:
            source_id: Filter to this source only; None returns all sources.
            since: Return only rows with timestamp >= since; None returns all.

        Returns:
            DataFrame with columns [timestamp, lat, lng, place_name, place_type, source_id].
        """
        assert self._conn is not None
        clauses: list[str] = []
        params: list[Any] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT timestamp, lat, lng, place_name, place_type, source_id FROM places{where}"  # noqa: S608
        return self._conn.execute(sql, params).df()

    def query_content(
        self,
        source_id: str | None = None,
        since: int | None = None,
    ) -> pd.DataFrame:
        """Query content records.

        Args:
            source_id: Filter to this source only; None returns all sources.
            since: Return only rows with timestamp >= since; None returns all.

        Returns:
            DataFrame with content columns.
        """
        assert self._conn is not None
        clauses: list[str] = []
        params: list[Any] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT timestamp, title, url, feed_title, author, source_id FROM content{where}"  # noqa: S608
        return self._conn.execute(sql, params).df()

    # ------------------------------------------------------------------
    # Resumable-sync support (issue #109)
    # ------------------------------------------------------------------

    _TIMESTAMP_TABLES = ("events", "places", "content")

    def get_latest_timestamp(self, source_id: str, table: str = "events") -> int | None:
        """Return the newest already-committed record timestamp for a source.

        Used to resume an interrupted or incremental sync from exactly what
        has actually landed in the store, instead of relying solely on
        ``sync_state.last_synced_at`` — which is only written after a run
        completes. A crash mid-write still leaves already-committed batches
        intact (each ``upsert_*`` call commits its own transaction), so
        re-querying the real data gives an accurate resume point even when
        ``set_sync_state`` was never reached.

        Args:
            source_id: The plugin's source identifier.
            table: Which table to query — one of "events", "places",
                "content". Falls back to "events" for any other value.

        Returns:
            The max ``timestamp`` among rows matching ``source_id`` in
            ``table``, or None if there are no such rows.
        """
        if table not in self._TIMESTAMP_TABLES:
            table = "events"
        assert self._conn is not None
        sql = f"SELECT MAX(timestamp) FROM {table} WHERE source_id = ?"  # noqa: S608
        row = self._conn.execute(sql, [source_id]).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    # ------------------------------------------------------------------
    # Sync state
    # ------------------------------------------------------------------

    def get_sync_state(self, source_id: str) -> dict[str, Any]:
        """Return the sync state for a source plugin.

        Args:
            source_id: The plugin's source identifier.

        Returns:
            Dict with keys: source_id, last_synced_at, last_cursor,
            record_count, status. Returns defaults if the source is unknown.
        """
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT source_id, last_synced_at, last_cursor, record_count, status "
            "FROM sync_state WHERE source_id = ?",
            [source_id],
        ).fetchall()

        if not rows:
            return {
                "status": "never_run",
                "record_count": 0,
                "last_synced_at": None,
                "last_cursor": None,
            }

        row = rows[0]
        return {
            "source_id": row[0],
            "last_synced_at": row[1],
            "last_cursor": row[2],
            "record_count": row[3] if row[3] is not None else 0,
            "status": row[4] if row[4] is not None else "never_run",
        }

    def set_sync_state(self, source_id: str, **kwargs: Any) -> None:
        """Upsert the sync state for a source plugin.

        Args:
            source_id: The plugin's source identifier.
            **kwargs: Any of last_synced_at, last_cursor, record_count, status.
        """
        assert self._conn is not None

        # Build column list from kwargs
        cols = ["source_id"]
        vals: list[Any] = [source_id]
        for key, val in kwargs.items():
            cols.append(key)
            vals.append(val)

        placeholders = ", ".join(["?"] * len(vals))
        col_str = ", ".join(cols)

        # Build ON CONFLICT update clause for all kwargs columns
        if kwargs:
            update_parts = [f"{k} = excluded.{k}" for k in kwargs]
            conflict_clause = f"ON CONFLICT (source_id) DO UPDATE SET {', '.join(update_parts)}"
        else:
            conflict_clause = "ON CONFLICT (source_id) DO NOTHING"

        sql = f"INSERT INTO sync_state ({col_str}) VALUES ({placeholders}) {conflict_clause}"  # noqa: S608
        self._conn.execute(sql, vals)
