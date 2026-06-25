"""DDL string constants for the localizer DuckDB schema."""

CREATE_META = (
    "CREATE TABLE IF NOT EXISTS _localizer_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
)

CREATE_EVENTS = """CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    label TEXT NOT NULL,
    sublabel TEXT,
    category TEXT,
    raw_json JSON,
    fetched_at BIGINT NOT NULL
)"""

CREATE_EVENTS_INDEX = "CREATE INDEX IF NOT EXISTS events_source_ts ON events (source_id, timestamp)"

CREATE_PLACES = """CREATE TABLE IF NOT EXISTS places (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    lat DOUBLE NOT NULL,
    lng DOUBLE NOT NULL,
    place_name TEXT,
    place_type TEXT,
    raw_json JSON,
    fetched_at BIGINT NOT NULL
)"""

CREATE_PLACES_INDEX = "CREATE INDEX IF NOT EXISTS places_source_ts ON places (source_id, timestamp)"

CREATE_CONTENT = """CREATE TABLE IF NOT EXISTS content (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    title TEXT,
    url TEXT,
    feed_title TEXT,
    author TEXT,
    raw_json JSON,
    fetched_at BIGINT NOT NULL
)"""

CREATE_SYNC_STATE = """CREATE TABLE IF NOT EXISTS sync_state (
    source_id TEXT PRIMARY KEY,
    last_synced_at BIGINT,
    last_cursor TEXT,
    record_count BIGINT DEFAULT 0,
    status TEXT DEFAULT 'never_run'
)"""

CREATE_VIEW_WHAT_WHEN = """CREATE OR REPLACE VIEW v_what_when AS
    SELECT timestamp, label, sublabel, category, source_id FROM events"""

CREATE_VIEW_WHERE_WHEN = """CREATE OR REPLACE VIEW v_where_when AS
    SELECT timestamp, lat, lng, place_name, place_type, source_id FROM places"""

SCHEMA_VERSION = "1"
