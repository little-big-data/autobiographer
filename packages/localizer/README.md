# localizer

A local-first personal data platform. Fetches, normalises, and stores your life data — music history, location check-ins, reading, film watching, and more — in an open DuckDB file on your machine. No cloud account required; your data stays yours.

Autobiographer uses localizer as its data layer, but localizer is a standalone package you can use independently.

---

## Functional architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  FETCH PHASE  (localizer sync / localizer fetch <source>)       │
│                                                                 │
│  API sources:    Last.fm, GitHub, Feedly — pull via HTTP        │
│  Manual sources: Swarm, Letterboxd — parse a local export file  │
│                                                                 │
│  All plugins write to ~/.localizer/store.duckdb                 │
└────────────────────────────────┬────────────────────────────────┘
                                 │ one-way write
                                 ▼
              ~/.localizer/store.duckdb
              ┌──────────┬──────────┬──────────┐
              │  events  │  places  │  content  │
              └──────────┴──────────┴──────────┘
                                 │ read-only
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  DISPLAY PHASE  (streamlit run visualize.py)                    │
│                                                                 │
│  LocalizerBroker reads DataFrames from DuckDB                   │
│  apply_swarm_offsets() enriches Last.fm events with location    │
│    — reads default_assumptions.json at runtime (not in DuckDB)  │
│                                                                 │
│  Zero outbound network calls at render time                     │
└─────────────────────────────────────────────────────────────────┘
```

### The places layer and location assumptions

The `places` table stores timestamped GPS check-ins from sources like Foursquare/Swarm. These are used to infer where you were when you listened to music, watched a film, etc.

**`default_assumptions.json` is not stored in DuckDB.** It is a runtime configuration file that describes where you were during periods *not covered* by check-ins — home residency rules, recurring holidays, long trips. The dashboard reads it from disk at render time via `LocalizerSettings.get_assumptions_path()` and passes it to `apply_swarm_offsets()`, which joins it against Last.fm events to assign locations.

This means:
- Editing `default_assumptions.json` takes effect the next time you open the dashboard — no sync needed.
- The `places` table only contains explicit check-ins; inferred locations are computed on the fly.

---

## Installation

```bash
# From the autobiographer monorepo root:
pip install -e packages/localizer/
pip install -e .
```

The `localizer` CLI is registered as a script entry point after install.

---

## Quickstart

```bash
# Copy credentials template and fill in your API keys
cp .env.example .env

# localizer loads .env automatically — no `source` or `export` needed
localizer sync

# Inspect what landed in DuckDB
localizer status
```

---

## CLI reference

### `localizer sources`

List every registered plugin with its fetch mode and output table.

```
$ localizer sources
feedly           API      content
github           API      events
google_timeline  MANUAL   places
lastfm           API      events
letterboxd       MANUAL   events
rss              MANUAL   content
swarm            MANUAL   places
```

Fetch modes:
- `API` — downloads automatically when credentials are set.
- `MANUAL` — reads a local export file you supply; prints download instructions when unconfigured.
- `PLAYWRIGHT` — browser-driven; requires `localizer[playwright]`.

---

### `localizer sync`

Fetch all registered sources and write records to DuckDB. The canonical data-refresh command.

```bash
localizer sync              # all sources, incremental (skips already-seen records)
localizer sync --full       # ignore cursors, re-fetch everything from scratch
localizer sync --dry-run    # count what would be written without touching the store
```

Plugins that fail (missing credentials, bad config) are skipped with a warning; other sources continue.

---

### `localizer fetch <source>`

Fetch a single source.

```bash
localizer fetch lastfm
localizer fetch lastfm --full           # force full re-fetch, ignore cursor
localizer fetch lastfm --dry-run

# Set a path and fetch in one step (no separate config set needed):
localizer fetch swarm --set-dir "G:/My Drive/Foursquare Export"
localizer fetch letterboxd --set-file "/path/to/diary.csv"
```

The `--full` flag is important after fixing a configuration error — if previous runs fetched 0 records the cursor was not advanced, but use `--full` to be safe.

---

### `localizer status`

Show record counts per table.

```bash
localizer status            # totals across all sources
localizer status swarm      # one source
localizer status --json     # machine-readable
```

---

### `localizer export`

Export DuckDB tables to Parquet, CSV, or JSON.

```bash
localizer export --format parquet --output ./export/
localizer export --format csv --table events --output ./export/
```

Options: `--format parquet|csv|json`, `--table events|places|content`, `--since <unix-timestamp>`, `--output PATH`.

---

### `localizer db`

Utilities for the underlying DuckDB file.

```bash
localizer db path       # print path to store.duckdb
localizer db vacuum     # compact the file
localizer db migrate    # apply pending schema migrations
```

---

### `localizer config`

Read and write settings in `~/.localizer/config.toml`.

```bash
localizer config show

# File-based sources:
localizer config set swarm_dir     "/path/to/foursquare-export/"
localizer config set csv_path      "/path/to/letterboxd/diary.csv"
localizer config set assumptions_path "/path/to/default_assumptions.json"
```

---

## Configuration

### API credentials

Copy `.env.example` to `.env` and fill in your keys. `localizer` loads `.env` automatically on every command.

| Source | Required env vars |
|---|---|
| Last.fm | `AUTOBIO_LASTFM_API_KEY`, `AUTOBIO_LASTFM_API_SECRET`, `AUTOBIO_LASTFM_USERNAME` |
| GitHub | `LOCALIZER_GITHUB_TOKEN` |
| Feedly | `LOCALIZER_FEEDLY_TOKEN` |
| Swarm | *(manual export — no credentials)* |
| Letterboxd | *(manual export or Playwright login)* |

### System env vars

| Env var | Purpose |
|---|---|
| `LOCALIZER_DB_PATH` | Override the store path (default: `~/.localizer/store.duckdb`) |
| `LOCALIZER_CONFIG_PATH` | Override the config file path |
| `LOCALIZER_ASSUMPTIONS_PATH` | Override the assumptions JSON path at runtime |

---

## Sources

### Last.fm

Full listening history via the Last.fm API. Records land in `events` (`label` = artist, `sublabel` = track, `category` = album). Syncs incrementally — only new scrobbles on subsequent runs.

### Foursquare / Swarm

Check-ins land in `places`. Requires a manual data export from [foursquare.com](https://foursquare.com/download). Unzip the export and point localizer at the directory:

```bash
localizer fetch swarm --set-dir "/path/to/foursquare-export/"

# First-time or after fixing config issues, use --full to bypass the cursor:
localizer fetch swarm --full
```

The export contains `checkins1.json`, `checkins2.json`, etc. The loader handles both the newer format (lat/lng on the checkin) and the older format (lat/lng nested inside `venue.location`).

### Google Maps Timeline

Check-ins land in `places`. Manual, local-file-only source — no network calls are made; the plugin only reads a `Timeline.json` file you export yourself.

Google Maps Timeline data is stored on your device and must be exported manually, using either:

- **Your phone** (recommended, gives the new format): Settings → Location → Location Services → Timeline → "Export Timeline data", then copy the exported `Timeline.json` to your computer.
- **Google Takeout**: visit [takeout.google.com](https://takeout.google.com), deselect all, then select only "Location History (Timeline)", create the export, download the archive, and unzip it to find `Timeline.json`.

Point localizer at the exported file:

```bash
localizer config set google_timeline_path "/path/to/Timeline.json"
localizer fetch google_timeline
```

### GitHub

Commit history across repos you own or contribute to. Records land in `events` (`label` = repo, `sublabel` = commit message, `category` = short SHA).

```bash
export LOCALIZER_GITHUB_TOKEN="ghp_..."
localizer fetch github
```

### Feedly

Articles from your Feedly reading list. Records land in `content`.

```bash
export LOCALIZER_FEEDLY_TOKEN="..."
localizer fetch feedly
```

### RSS / Atom

Parses any RSS or Atom feed (including Goodreads shelf feeds). Records land in `content`. Configure feeds through the Streamlit sidebar or by constructing `RssPlugin` directly.

### Letterboxd

Film diary. Download your export from letterboxd.com → Settings → Import & Export, then:

```bash
localizer fetch letterboxd --set-file "/path/to/diary.csv"
```

Records land in `events` (`label` = film title, `category` = release year).

---

## Storage schema

All data lives in one DuckDB file at `~/.localizer/store.duckdb`. Upserts are idempotent — running `localizer sync` twice produces exactly N rows, not 2N.

### `events` — what happened when

| Column | Type | Description |
|---|---|---|
| `id` | TEXT PK | `sha256(source_id + timestamp + label + sublabel)[:16]` |
| `source_id` | TEXT | `"lastfm"`, `"github"`, `"letterboxd"` |
| `timestamp` | BIGINT | Unix epoch UTC |
| `label` | TEXT | Primary entity (artist, repo, film title) |
| `sublabel` | TEXT | Secondary entity (track, commit message, director) |
| `category` | TEXT | Album, language, genre |
| `raw_json` | JSON | Original record for forward-compatibility |
| `fetched_at` | BIGINT | When this record was last written |

### `places` — where you were

| Column | Type | Description |
|---|---|---|
| `id` | TEXT PK | Deterministic hash |
| `source_id` | TEXT | `"swarm"`, `"google_timeline"`, … |
| `timestamp` | BIGINT | Unix epoch UTC |
| `lat` / `lng` | DOUBLE | Coordinates |
| `place_name` | TEXT | Venue name (empty for GPS-only sources) |
| `place_type` | TEXT | Category (bar, restaurant, …) |
| `raw_json` | JSON | Original record |
| `fetched_at` | BIGINT | When this record was last written |

### `content` — things you read

| Column | Type | Description |
|---|---|---|
| `id` | TEXT PK | Deterministic hash |
| `source_id` | TEXT | `"feedly"`, `"rss:<url>"` |
| `timestamp` | BIGINT | Unix epoch UTC |
| `title` | TEXT | Article title |
| `url` | TEXT | Article URL |
| `feed_title` | TEXT | Feed name |
| `author` | TEXT | Author |

---

## Reading data from Python

```python
from localizer.store.db import LocalizerStore

with LocalizerStore() as store:
    events = store.query_events(source_id="lastfm")         # → pd.DataFrame
    places = store.query_places(source_id="swarm")
    content = store.query_content(source_id="feedly")

    # Filter by time
    recent = store.query_events(since=1_700_000_000)
```

---

## Writing a plugin

### 1. Choose a table and fetch mode

| Your data is… | Target table | `FetchMode` |
|---|---|---|
| Time-stamped activities (scrobbles, commits, films) | `events` | `API` or `MANUAL` |
| GPS check-ins or location visits | `places` | `API` or `MANUAL` |
| Articles, posts, feed items | `content` | `API` or `MANUAL` |

### 2. Implement `SourcePlugin`

```python
# packages/localizer/src/localizer/plugins/myplugin/loader.py
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from localizer.plugins import register
from localizer.plugins.base import FetchMode, OutputTable, SourcePlugin


@register
class MyPlugin(SourcePlugin):
    PLUGIN_ID = "myplugin"
    DISPLAY_NAME = "My Data Source"
    FETCH_MODE = FetchMode.API          # or FetchMode.MANUAL
    OUTPUT_TABLES = [OutputTable.EVENTS]  # or PLACES, CONTENT

    def get_config_fields(self) -> list[dict[str, Any]]:
        """Declare config fields shown in the Streamlit sidebar."""
        return []

    def fetch_records(
        self,
        since: int | None = None,
        progress_cb: Any | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield one dict per record. Must be a generator, not a list."""
        import time
        yield {
            "source_id": self.PLUGIN_ID,
            "timestamp": int(time.time()),
            "label": "example",
            "sublabel": "detail",
            "category": "misc",
            "raw_json": {},
            "fetched_at": int(time.time()),
        }
```

For a `places` plugin, yield this shape instead:

```python
yield {
    "source_id": self.PLUGIN_ID,
    "timestamp": int(timestamp),
    "lat": float(lat),
    "lng": float(lng),
    "place_name": "Coffee Shop",   # empty string if unknown
    "place_type": "cafe",          # empty string if unknown
    "raw_json": original_dict,
    "fetched_at": int(time.time()),
}
```

### 3. Read config from `LocalizerSettings`

If your plugin needs a file path or directory set via `localizer config set`, read it in `__init__`:

```python
def __init__(self, my_dir: str | None = None) -> None:
    if my_dir is None:
        from localizer.settings import LocalizerSettings
        my_dir = LocalizerSettings().get_setting("myplugin_dir") or None
    self._my_dir = my_dir
```

This lets `localizer fetch myplugin --set-dir /path` work in a single step.

### 4. Register the plugin

Add an import to `load_builtin_plugins()` in `packages/localizer/src/localizer/plugins/__init__.py`:

```python
def load_builtin_plugins() -> None:
    from localizer.plugins.myplugin import loader as _  # noqa: F401
    ...
```

### Rules

- `fetch_records()` must be a **generator** (`yield`), never a list — histories can exceed 200k rows.
- The `id` field is computed automatically by the store; do not supply it.
- Never make network calls in `__init__` — only in `fetch_records()`.
- `FetchMode.MANUAL` means `fetch_records()` reads a local file; it never calls the network.
- Respect the `since` parameter: skip records with `timestamp <= since` when provided.
- Raise `OSError` (not `KeyError` or `ValueError`) when required credentials or paths are missing — the CLI catches `OSError` and skips the plugin gracefully.

---

## License

GNU General Public License v3.0
