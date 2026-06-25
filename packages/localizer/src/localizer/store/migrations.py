"""Migration runner for the localizer DuckDB store.

Applies all DDL in order; safe to call on an existing store (idempotent).
"""

from __future__ import annotations

from localizer.store.schema import (
    CREATE_CONTENT,
    CREATE_EVENTS,
    CREATE_EVENTS_INDEX,
    CREATE_META,
    CREATE_PLACES,
    CREATE_PLACES_INDEX,
    CREATE_SYNC_STATE,
    CREATE_VIEW_WHAT_WHEN,
    CREATE_VIEW_WHERE_WHEN,
    SCHEMA_VERSION,
)

_DDL_STATEMENTS = [
    CREATE_META,
    CREATE_EVENTS,
    CREATE_EVENTS_INDEX,
    CREATE_PLACES,
    CREATE_PLACES_INDEX,
    CREATE_CONTENT,
    CREATE_SYNC_STATE,
    CREATE_VIEW_WHAT_WHEN,
    CREATE_VIEW_WHERE_WHEN,
]


def apply_migrations(conn: object) -> None:
    """Run all DDL in order; safe to call on an existing store (idempotent).

    Args:
        conn: An open DuckDB connection.
    """
    for statement in _DDL_STATEMENTS:
        conn.execute(statement)  # type: ignore[attr-defined]

    # Set schema version in meta table
    conn.execute(  # type: ignore[attr-defined]
        "INSERT OR REPLACE INTO _localizer_meta (key, value) VALUES ('schema_version', ?)",
        [SCHEMA_VERSION],
    )
