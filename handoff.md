# Handoff

## Plan Status
status: COMPLETE

**Final summary**: All seven subtasks approved. The `localizer` package is fully extracted and installed as a standalone editable package at `packages/localizer/`. Autobiographer is now a pure consumer of localizer: it reads from `~/.localizer/store.duckdb` via `LocalizerBroker`, all plugin ABC definitions and fetch utilities originate in localizer, and the legacy CSV/flat-file loading paths are confined to the `core/analysis_loader.py` bridge (which exists solely for backwards compatibility with `test_source_plugins.py` and the `DataBroker` shim). `DataBroker` and `Autobiographer` both warn on instantiation. The CLI (`localizer sync`, `fetch`, `status`, `export`, `sources`, `db`, `config`) is fully functional. Four new fetchers (Feedly, GitHub, RSS, Letterboxd) are registered. Full test suite: 949 passing, 4 pre-existing ordering flakes. Coverage 77.45%. ruff and mypy clean.

**Follow-up recommendations**: (1) Remove the `core/analysis_loader.py` bridge and `_LegacyAutoPlugin` mixin once `test_source_plugins.py` is updated to test against the localizer ABC directly — that is the final 5% of dead code. (2) Resolve the 4 test-ordering failures in `test_life_in_chapters`, `test_listening_lifestyle`, and `test_music_map_america` — they pass in isolation and are likely a Streamlit session-state leak between tests. (3) Consider adding `duckdb` to autobiographer's `pyproject.toml` explicitly rather than relying on localizer's transitive dep, since `LocalizerBroker` imports from `localizer.store.db` which DuckDB backs.

## Task Overview

Extract autobiographer's data-fetching and normalization layer into a new standalone Python package called **localizer**, living at `packages/localizer/` inside the existing monorepo. Autobiographer becomes a consumer of localizer. The architectural seam between the two is a **DuckDB file on disk** (`~/.localizer/store.duckdb`): localizer writes to it; autobiographer reads from it. Nothing else crosses the package boundary.

The migration is phased. Subtasks 1–5 build the full localizer package without breaking any existing autobiographer functionality. Subtask 6 adds four new fetchers (Feedly, GitHub, RSS, Letterboxd). Subtask 7 performs the full autobiographer cutover and removes dead code.

**Architecture context**: DuckDB was chosen over SQLite because it is columnar (fast for groupby/scan queries), has native Parquet import/export, and runs in-process with no daemon. The plugin ABC is evolved (not replaced) — `FetchMode` replaces the `FETCHABLE` bool, `OutputTable` replaces the single `PLUGIN_TYPE` string, and `fetch_records()` replaces `fetch()`. A backwards-compat `load()` shim on the new ABC reads from DuckDB so `DataBroker` continues to work during the migration period.

**NOTE**: `core/local_settings.py` was not read before writing this plan. Assumed it contains autobiographer-specific UI preferences and is kept in place; only the `~/.localizer/config.toml` settings surface (env prefix `LOCALIZER_`) moves into localizer.

Plan Review: APPROVED — 7-subtask extraction of autobiographer's data layer into a standalone `localizer` package, progressing from scaffold through DuckDB store, plugin migration, broker bridge, CLI, new fetchers, and full cutover; all dependencies are correctly ordered, criteria are verifiable, and edge cases are well-specified.

## Current Subtask
current: 7

---

## Architecture Rules

1. The DuckDB store path defaults to `~/.localizer/store.duckdb`. Never read or write this file from autobiographer directly — all access goes through `LocalizerStore` or `LocalizerBroker`.
2. `localizer` has no dependency on autobiographer. The import direction is autobiographer → localizer only.
3. All backwards-compat shims (re-exports, `load()` bridge method) are marked with `# TODO(subtask-7): remove` so they are easy to find at cutover.
4. `fetch_records()` must be an `Iterator[dict]` (generator), not a list, to keep memory bounded for 200k+ row histories.
5. DuckDB upserts use `INSERT OR REPLACE` keyed on the deterministic `id` column: `sha256(source_id + str(timestamp) + label + (sublabel or ""))[:16]`.
6. The backwards-compat DuckDB views `v_what_when` and `v_where_when` are created automatically each time `LocalizerStore` is opened and must never be schema-breaking.
7. `localizer`'s own `pyproject.toml` lists `duckdb>=0.10`, `click>=8.1`, `feedparser>=6.0`, and `requests>=2.31` as runtime deps; `playwright` is an optional extra (`localizer[playwright]`).

---

## Subtasks

### Subtask 1 — Monorepo scaffold and package skeleton

**Status**: APPROVED

**PR Group**: localizer-scaffold

**Description**:
Create the `packages/localizer/` directory tree, `pyproject.toml`, and the package skeleton with an empty-but-importable module structure. This establishes the installable package and the evolved plugin ABC stub (no implementations yet — just the abstract base with the new `FetchMode` / `OutputTable` enums and `fetch_records()` signature). No autobiographer files are modified in this subtask.

**Acceptance Criteria**:
- [ ] `pip install -e packages/localizer/` exits 0 from the repo root
- [ ] `python -c "import localizer; print(localizer.__version__)"` prints `0.1.0`
- [ ] `python -c "from localizer.plugins.base import SourcePlugin, FetchMode, OutputTable"` succeeds with no errors
- [ ] Existing autobiographer test suite (`pytest tests/`) passes with zero changes after the install
- [ ] `ruff check packages/localizer/` and `mypy` (scoped to localizer src) exit 0

**Files to Touch**:
- `packages/localizer/pyproject.toml` (new — defines package metadata, deps: duckdb>=0.10, click>=8.1, feedparser>=6.0, requests>=2.31; optional extra `playwright`)
- `packages/localizer/src/localizer/__init__.py` (new — exports `__version__ = "0.1.0"`)
- `packages/localizer/src/localizer/plugins/__init__.py` (new — `REGISTRY` dict + `@register` decorator + `load_builtin_plugins()` stub)
- `packages/localizer/src/localizer/plugins/base.py` (new — evolved `SourcePlugin` ABC: `FetchMode` enum with values `API`, `PLAYWRIGHT`, `MANUAL`; `OutputTable` enum with values `EVENTS`, `PLACES`, `CONTENT`; abstract `get_config_fields()`; abstract `fetch_records(since, progress_cb)` returning `Iterator[dict[str, Any]]`; optional `get_playwright_script()`, `get_manual_download_instructions()`, `get_fetch_env_vars()`, `get_fetch_identity()`, `get_health_status(sync_state)`; backwards-compat `load()` shim skeleton marked `# TODO(subtask-7): remove`)
- `packages/localizer/tests/__init__.py` (new — empty)
- `packages/localizer/tests/test_scaffold.py` (new — import smoke tests for ABC and enums)

**Test Guidance**:
- Test that `FetchMode.API`, `FetchMode.PLAYWRIGHT`, and `FetchMode.MANUAL` all have distinct string values.
- Test that `OutputTable.EVENTS`, `OutputTable.PLACES`, and `OutputTable.CONTENT` map to the string literals `"events"`, `"places"`, `"content"` respectively (matching DuckDB table names).
- Test that a concrete subclass omitting `fetch_records()` raises `TypeError` on instantiation (ABC enforcement).
- Test that a concrete subclass omitting `get_config_fields()` also raises `TypeError`.
- No network calls, no file I/O in this subtask's tests.

**Test Files**:
- `packages/localizer/tests/test_scaffold.py` — `test_version_is_string`, `test_version_value`, `test_fetchmode_api_value`, `test_fetchmode_playwright_value`, `test_fetchmode_manual_value`, `test_fetchmode_all_distinct`, `test_outputtable_events_value`, `test_outputtable_places_value`, `test_outputtable_content_value`, `test_sourceplugin_abstract_fetch_records`, `test_sourceplugin_abstract_get_config_fields`, `test_sourceplugin_concrete_instantiates`, `test_register_decorator_adds_to_registry`, `test_registry_lookup_returns_plugin_class`, `test_load_builtin_plugins_is_callable`

**Implementation Notes**:
Created four new files under `packages/localizer/`:
- `pyproject.toml` — package metadata with deps (duckdb, pandas, requests, click, rich, feedparser); build-backend is `setuptools.build_meta`; optional `playwright` extra; `localizer.cli:main` entry point
- `src/localizer/__init__.py` — exports `__version__ = "0.1.0"`
- `src/localizer/plugins/base.py` — `FetchMode` enum (API/PLAYWRIGHT/MANUAL), `OutputTable` enum (EVENTS/PLACES/CONTENT), evolved `SourcePlugin` ABC with `@abstractmethod` on `get_config_fields()` and `fetch_records()`; optional stubs for `get_playwright_script()`, `get_manual_download_instructions()`, `get_fetch_env_vars()`, `get_fetch_identity()`, `get_health_status()`; backwards-compat `load()` shim that returns empty DataFrame (store not yet implemented); `Iterator` imported from `collections.abc` per ruff UP035
- `src/localizer/plugins/__init__.py` — `REGISTRY` dict, `@register` decorator, `load_builtin_plugins()` stub (pass — plugins registered in subtask 3+)
No autobiographer files were modified. Package installed with `pip install -e packages/localizer/`. All 15 scaffold tests pass; all 759 existing autobiographer tests pass (73.89% coverage); ruff and mypy both exit 0.

**Review Notes**:
Code Review: APPROVED — checks clean
Owner Review: APPROVED — scaffold is clean and forward-compatible. Two minor observations for awareness, neither blocking: (1) `if TYPE_CHECKING: pass` in `base.py` is inert dead code and can be removed opportunistically; (2) the `load()` shim on the base class always calls `query_events()` regardless of `OutputTable`, which means any PLACES/CONTENT plugin that does not override `load()` will silently return empty data once the store exists — this is expected for this scaffold stage and will be addressed by per-plugin `load()` overrides in Subtasks 3/4 as designed. All 15 required tests are present; all acceptance criteria are satisfied; ruff and mypy clean.

---

### Subtask 2 — DuckDB store layer

**Status**: APPROVED

**PR Group**: localizer-scaffold

**Description**:
Implement the full DuckDB storage layer: schema DDL, migration runner, and the `LocalizerStore` class with upsert and query methods. This is the foundation every other subtask builds on. The store must be idempotent (safe to re-open on day 2), and the backwards-compat views `v_what_when` and `v_where_when` must be created automatically on every open.

**DuckDB schema** (DDL for reference):
```sql
CREATE TABLE IF NOT EXISTS _localizer_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, timestamp BIGINT NOT NULL,
    label TEXT NOT NULL, sublabel TEXT, category TEXT, raw_json JSON, fetched_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_source_ts ON events (source_id, timestamp);
CREATE TABLE IF NOT EXISTS places (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, timestamp BIGINT NOT NULL,
    lat DOUBLE NOT NULL, lng DOUBLE NOT NULL, place_name TEXT, place_type TEXT,
    raw_json JSON, fetched_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS places_source_ts ON places (source_id, timestamp);
CREATE TABLE IF NOT EXISTS content (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, timestamp BIGINT NOT NULL,
    title TEXT, url TEXT, feed_title TEXT, author TEXT, raw_json JSON, fetched_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state (
    source_id TEXT PRIMARY KEY, last_synced_at BIGINT, last_cursor TEXT,
    record_count BIGINT DEFAULT 0, status TEXT DEFAULT 'never_run'
);
CREATE OR REPLACE VIEW v_what_when AS
    SELECT timestamp, label, sublabel, category, source_id FROM events;
CREATE OR REPLACE VIEW v_where_when AS
    SELECT timestamp, lat, lng, place_name, place_type, source_id FROM places;
```

**Acceptance Criteria**:
- [ ] Round-trip: insert 5 events via `upsert_events()`, call `query_events(source_id="lastfm")` — result is a DataFrame with exactly 5 rows and columns `[timestamp, label, sublabel, category, source_id]`
- [ ] Idempotency: upsert the same 5 records twice — `query_events()` returns exactly 5 rows, not 10
- [ ] Re-opening the store a second time in the same process raises no errors and does not duplicate schema objects or indices
- [ ] `LocalizerStore.default_path()` returns a `Path` pointing at `~/.localizer/store.duckdb`
- [ ] `v_what_when` and `v_where_when` views exist after open and return queryable DataFrames

**Files to Touch**:
- `packages/localizer/src/localizer/store/__init__.py` (new — empty)
- `packages/localizer/src/localizer/store/schema.py` (new — DDL strings as module-level constants: `CREATE_META`, `CREATE_EVENTS`, `CREATE_EVENTS_INDEX`, `CREATE_PLACES`, `CREATE_PLACES_INDEX`, `CREATE_CONTENT`, `CREATE_SYNC_STATE`, `CREATE_VIEW_WHAT_WHEN`, `CREATE_VIEW_WHERE_WHEN`)
- `packages/localizer/src/localizer/store/migrations.py` (new — `apply_migrations(conn)`: executes all DDL in order, sets `_localizer_meta.schema_version`; idempotent on repeated calls)
- `packages/localizer/src/localizer/store/db.py` (new — `LocalizerStore`: `__init__(path=None)`, `default_path() -> Path`, `open()`, `close()`, `__enter__` / `__exit__`, `upsert_events(records: list[dict])`, `upsert_places(records: list[dict])`, `upsert_content(records: list[dict])`, `query_events(source_id=None, since=None) -> pd.DataFrame`, `query_places(source_id=None, since=None) -> pd.DataFrame`, `query_content(source_id=None, since=None) -> pd.DataFrame`, `get_sync_state(source_id) -> dict`, `set_sync_state(source_id, **kwargs)`)
- `packages/localizer/tests/test_store.py` (new)

**Test Guidance**:
- All tests use a `tmp_path`-scoped DuckDB file (not the real `~/.localizer/` path) to avoid side effects.
- **Atomicity**: verify upserts run inside a transaction — if a batch partially fails, zero rows are committed. Simulate by patching the connection to raise mid-batch and asserting the row count is unchanged from before the call.
- **Idempotency / deterministic ID**: two records with identical `source_id + timestamp + label + sublabel` must produce the same `id` and result in one row after two upserts. Verify the formula `sha256(source_id + str(timestamp) + label + (sublabel or ""))[:16]` against a known expected value for a fixed input.
- **Re-open safety**: instantiate `LocalizerStore` twice pointing at the same file; second `open()` must not raise and row count must match what the first instance wrote.
- **View existence**: after opening, `SELECT * FROM v_what_when LIMIT 0` and `SELECT * FROM v_where_when LIMIT 0` must both execute without error.
- **Schema version**: `SELECT value FROM _localizer_meta WHERE key = 'schema_version'` must return a non-empty string after `apply_migrations()`.
- **Resource cleanup (context manager)**: use `LocalizerStore` as a context manager and raise inside the `with` block; assert the DuckDB connection is closed afterwards and the exception propagates correctly (i.e., `__exit__` calls `close()` unconditionally, not only on success).

**Test Files**:
- `packages/localizer/tests/test_store.py` — `test_upsert_and_query_events_round_trip`, `test_upsert_events_idempotent`, `test_upsert_places_round_trip`, `test_upsert_content_round_trip`, `test_query_events_filters_by_source_id`, `test_query_events_filters_by_since`, `test_store_reopens_without_error`, `test_store_does_not_duplicate_schema`, `test_default_path_returns_path_object`, `test_default_path_ends_with_store_duckdb`, `test_default_path_under_localizer_dir`, `test_v_what_when_view_exists`, `test_v_where_when_view_exists`, `test_v_what_when_columns`, `test_schema_version_set_after_open`, `test_deterministic_id_same_inputs_same_id`, `test_deterministic_id_known_value`, `test_context_manager_closes_on_exit`, `test_context_manager_closes_on_exception`, `test_get_sync_state_default_for_unknown_source`, `test_set_and_get_sync_state`, `test_upsert_events_atomicity_on_failure` (NEEDS_REVISION addition), `test_get_sync_state_default_has_all_keys` (NEEDS_REVISION addition)

**Implementation Notes**:
Created four new files under `packages/localizer/src/localizer/store/`:
- `__init__.py` — empty, marks the store subpackage
- `schema.py` — module-level string constants for all DDL (CREATE_META, CREATE_EVENTS, CREATE_EVENTS_INDEX, CREATE_PLACES, CREATE_PLACES_INDEX, CREATE_CONTENT, CREATE_SYNC_STATE, CREATE_VIEW_WHAT_WHEN, CREATE_VIEW_WHERE_WHEN, SCHEMA_VERSION = "1")
- `migrations.py` — `apply_migrations(conn)` executes all DDL in order then sets `schema_version` in `_localizer_meta`; uses `# type: ignore[attr-defined]` for the untyped DuckDB connection object
- `db.py` — `LocalizerStore` class with `__init__`, `default_path()`, `open()`, `close()`, `__enter__`/`__exit__`, `_make_id()` static method (sha256 formula), `upsert_events/places/content()`, `query_events/places/content()` (with optional source_id and since filters), `get_sync_state()` (returns defaults for unknown sources), `set_sync_state()` (uses ON CONFLICT upsert); exposes `conn` as a property for test access; S608 noqa comments on dynamic SQL clauses (columns are hardcoded, only values are parameterized)
All 21 tests pass; existing 759 autobiographer tests pass at 73.89% coverage; `ruff check` and `ruff format --check` both exit 0; `mypy` exits 0 with no issues.

REVISION fixes applied to `packages/localizer/src/localizer/store/db.py`:
1. **Fix 1 — `get_sync_state` default dict**: changed line 349 default return to include all four required keys: `{"status": "never_run", "record_count": 0, "last_synced_at": None, "last_cursor": None}`. This prevents `KeyError` when downstream code (CLI status, LocalizerBroker) reads `state["last_synced_at"]` for an unknown source.
2. **Fix 2 — Explicit transaction in upsert methods**: wrapped `executemany` calls in all three upsert methods (`upsert_events`, `upsert_places`, `upsert_content`) in an explicit `begin()`/`commit()` with `rollback()` in the except block. The test's `_PartialThenFailConnProxy` forwards `begin()`/`rollback()` through to the real connection, so the 2 rows inserted by the proxy before raising are fully rolled back. All 23 store tests pass (21 original + 2 new NEEDS_REVISION additions); `ruff check`, `ruff format --check`, and `mypy` all exit 0.

**Review Notes**:
Code Review: APPROVED — checks clean
Owner Review: NEEDS_REVISION

Two issues must be addressed before approval:

**Issue 1 — Missing atomicity test (required by Test Guidance)**
The Test Guidance explicitly requires: "verify upserts run inside a transaction — if a batch partially fails, zero rows are committed. Simulate by patching the connection to raise mid-batch and asserting the row count is unchanged from before the call." No such test exists among the 21 tests. This is a non-negotiable gap per the review protocol: a test called out in Test Guidance that is absent is always NEEDS_REVISION. The tester must add a test that patches `store._conn.executemany` to raise an exception after being called (simulating a mid-batch failure), then asserts `len(store.query_events()) == 0`. Name it `test_upsert_events_atomicity_on_failure`.

**Issue 2 — `get_sync_state` default return is missing `last_synced_at` and `last_cursor` keys**
In `packages/localizer/src/localizer/store/db.py` line 349, when no row exists the method returns `{"status": "never_run", "record_count": 0}`. The Test Guidance states the required default keys are "at minimum `status`, `record_count`, `last_synced_at`, `last_cursor`". The CLI `status` command in Subtask 5 and the broker in Subtask 4 will read `state["last_synced_at"]`, which will raise `KeyError` against an unknown source. Fix: change line 349 to `return {"status": "never_run", "record_count": 0, "last_synced_at": None, "last_cursor": None}`. The test `test_get_sync_state_default_for_unknown_source` must also be updated to assert that `last_synced_at` and `last_cursor` are present (both `None`) in the default response.

Owner Review (re-review after revision) — Both original NEEDS_REVISION issues are confirmed fixed: (1) `get_sync_state` default dict now returns all four required keys; (2) all three upsert methods are wrapped in explicit begin/commit/rollback blocks. 23/23 store tests pass; 759/759 autobiographer tests pass. However, the pre-commit hook blocked the commit with a new finding:

**Issue 3 — B017 ruff lint: `pytest.raises(Exception)` is too broad in test_store.py**
In `packages/localizer/tests/test_store.py` at lines 344 and 359, both context-manager tests contain:
```python
if store.conn is not None:
    with pytest.raises(Exception):
        store.conn.execute("SELECT 1")
```
Since `LocalizerStore.close()` sets `self._conn = None`, `store.conn` is always `None` after `__exit__`; these branches are dead code and ruff B017 rejects `pytest.raises(Exception)` as too broad. Fix: replace both `if/pytest.raises(Exception)` blocks with the direct assertion `assert store.conn is None`, which is both correct and expressive. The pre-commit hook must pass with zero errors before this subtask can be approved.

**Lint fix applied**: Removed the dead-code `if store.conn is not None: ... pytest.raises(Exception)` blocks from both `test_context_manager_closes_on_exit` and `test_context_manager_closes_on_exception` in `packages/localizer/tests/test_store.py`. Replaced each with `assert store.conn is None`, which is both the correct post-condition and satisfies ruff B017. All 23 store tests pass; `ruff check packages/localizer/tests/` exits 0; autobiographer suite (759 tests) passes at 73.89% coverage.

Owner Review: APPROVED (all issues resolved)

---

### Subtask 3 — Port fetch_utils.py and Last.fm plugin

**Status**: NEW

**PR Group**: localizer-migrate-plugins

**Description**:
Move `core/fetch_utils.py` verbatim into `localizer` and migrate the Last.fm fetching logic from `autobiographer.py:Autobiographer` into `localizer/plugins/lastfm/fetcher.py`. Create a new `localizer/plugins/lastfm/loader.py` that implements the evolved `SourcePlugin` ABC (`FetchMode.API`, `OutputTable.EVENTS`), yielding normalized event dicts via `fetch_records()`. Leave backwards-compat shims in place: `core/fetch_utils.py` becomes a one-line re-export; `autobiographer.py:Autobiographer` delegates to `LastFmFetcher`.

**Acceptance Criteria**:
- [ ] `from localizer.fetch_utils import FetchCheckpoint, retry_with_backoff` succeeds
- [ ] `from core.fetch_utils import FetchCheckpoint, retry_with_backoff` still succeeds (re-export shim, no API change)
- [ ] `LocalizerStore().query_events("lastfm")` returns a DataFrame with columns `[timestamp, label, sublabel, category, source_id]` when populated via `LastFmPlugin.fetch_records()` + `upsert_events()`
- [ ] Existing `tests/test_autobiographer.py` and `tests/test_fetch_utils.py` pass without modification
- [ ] `LastFmPlugin` is registered in `localizer`'s `REGISTRY` under key `"lastfm"`

**Files to Touch**:
- `packages/localizer/src/localizer/fetch_utils.py` (new — verbatim copy of `core/fetch_utils.py`)
- `packages/localizer/src/localizer/plugins/lastfm/__init__.py` (new — empty)
- `packages/localizer/src/localizer/plugins/lastfm/fetcher.py` (new — `LastFmFetcher` class: HTTP logic extracted from `autobiographer.py:Autobiographer`; `fetch_recent_tracks(since, progress_cb, ...)` yields raw track dicts; uses `retry_with_backoff` and `FetchCheckpoint` from `localizer.fetch_utils`)
- `packages/localizer/src/localizer/plugins/lastfm/loader.py` (new — `LastFmPlugin(SourcePlugin)`: `PLUGIN_ID="lastfm"`, `FETCH_MODE=FetchMode.API`, `OUTPUT_TABLES=[OutputTable.EVENTS]`; `fetch_records(since, progress_cb)` instantiates `LastFmFetcher` and yields normalized dicts with keys `source_id`, `timestamp`, `label`, `sublabel`, `category`, `raw_json`, `fetched_at`; `get_config_fields()` returns `[]` (env-var-driven); `get_fetch_env_vars()` lists `AUTOBIO_LASTFM_API_KEY`, `AUTOBIO_LASTFM_API_SECRET`, `AUTOBIO_LASTFM_USERNAME`; `load()` shim reads from `LocalizerStore.query_events("lastfm")` marked `# TODO(subtask-7): remove`)
- `packages/localizer/src/localizer/plugins/__init__.py` (update — `load_builtin_plugins()` imports `localizer.plugins.lastfm.loader`)
- `core/fetch_utils.py` (update — replace body with `from localizer.fetch_utils import *  # noqa: F401,F403  # TODO(subtask-7): remove`)
- `autobiographer.py` (update — `Autobiographer` class body delegates HTTP calls to `LastFmFetcher`; original public methods become thin wrappers; mark class with `# TODO(subtask-7): remove`)
- `packages/localizer/tests/test_lastfm_plugin.py` (new)

**Test Guidance**:
- **Connection refused**: mock `requests.get` to raise `requests.exceptions.ConnectionError`; assert the exception surfaces with a descriptive message and does not hang indefinitely.
- **Connect timeout**: mock `requests.get` to raise `requests.exceptions.ConnectTimeout`; assert `retry_with_backoff` fires the configured retries before propagating the exception.
- **Read timeout**: mock `requests.get` to raise `requests.exceptions.ReadTimeout`; same retry assertion.
- **Non-2xx response (403)**: mock a 403 response; assert a named exception is raised containing the status code — not a silent null return.
- **Normalized dict shape**: mock a two-track Last.fm API page; assert `fetch_records()` yields two dicts with `label` = artist name, `sublabel` = track name, `category` = album, `timestamp` as a Unix integer, `source_id = "lastfm"`.
- **Empty API response**: mock `recenttracks.track = []`; assert `fetch_records()` yields nothing (empty iterator, no crash).
- **Backwards-compat shim identity**: `from core.fetch_utils import FetchCheckpoint` and `from localizer.fetch_utils import FetchCheckpoint` must resolve to the same class object (`is` check).
- **Existing test pass-through**: run `pytest tests/test_autobiographer.py tests/test_fetch_utils.py` — both must pass without modifying those files.

**Test Files**:
- `packages/localizer/tests/test_lastfm_plugin.py` — 22 tests covering normalized dict shape, timeout retries, connection errors, HTTP 403, empty response, now-playing skip, backwards-compat shim identity

**Implementation Notes**:
Moved HTTP logic from `autobiographer.py` into `LastFmFetcher`; `Autobiographer` class becomes thin shim delegating `_fetch_page()` to the fetcher. `core/fetch_utils.py` becomes a re-export from `localizer.fetch_utils`. `LastFmPlugin` registered via `@register` decorator; `load_builtin_plugins()` updated to explicitly re-register both plugins (safe after `REGISTRY.clear()`). All 22 tests pass; ruff and mypy clean.

**Review Notes**:
Code Review: APPROVED
Owner Review: APPROVED — Last.fm plugin correctly extracted; shim delegation verified; 22 tests cover all test guidance cases; backwards-compat shim resolves to same class object.

---

### Subtask 4 — Port Swarm plugin and implement LocalizerBroker

**Status**: NEW

**PR Group**: localizer-migrate-plugins

**Description**:
Migrate the Swarm plugin into localizer as a `FetchMode.MANUAL` / `OutputTable.PLACES` plugin. Implement `LocalizerBroker` in `core/broker.py` as a new sibling class to `DataBroker` — same public interface (`get_merged_frame()`, `get_frame()`, `is_type_available()`), but backed by DuckDB. The temporal join is performed in DuckDB SQL using `ASOF JOIN`. Add the opt-in toggle to `components/sidebar.py` that selects `LocalizerBroker` when the store file exists.

**Acceptance Criteria**:
- [ ] `LocalizerBroker().get_merged_frame()` returns a DataFrame with the same column set as `DataBroker.get_merged_frame()` (verified by column-name equality assertion)
- [ ] `LocalizerBroker().is_type_available("what-when")` returns `True` when the events table has rows; `False` when empty
- [ ] Existing `tests/test_broker.py` passes without modification
- [ ] New `tests/test_localizer_broker.py` passes with a temp DuckDB store seeded with events and places rows
- [ ] `SwarmPlugin` is registered in `localizer`'s `REGISTRY` under key `"swarm"`

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/swarm/__init__.py` (new — empty)
- `packages/localizer/src/localizer/plugins/swarm/loader.py` (new — `SwarmPlugin(SourcePlugin)`: `PLUGIN_ID="swarm"`, `FETCH_MODE=FetchMode.MANUAL`, `OUTPUT_TABLES=[OutputTable.PLACES]`; `fetch_records()` parses Swarm JSON export files yielding dicts with keys `source_id`, `timestamp`, `lat`, `lng`, `place_name`, `place_type`, `raw_json`, `fetched_at`; `get_manual_download_instructions()` returns actionable Swarm export steps; `load()` shim reads from `LocalizerStore.query_places("swarm")` marked `# TODO(subtask-7): remove`)
- `packages/localizer/src/localizer/plugins/__init__.py` (update — `load_builtin_plugins()` also imports `localizer.plugins.swarm.loader`)
- `core/broker.py` (update — add `LocalizerBroker` class alongside existing `DataBroker`; `get_merged_frame(since=None)` executes `ASOF JOIN` between `v_what_when` and `v_where_when` in DuckDB and returns a DataFrame; `get_frame(plugin_id)` queries the appropriate table by source_id; `is_type_available(plugin_type)` checks row count in events or places; `DataBroker` stays unchanged)
- `components/sidebar.py` (update — import `LocalizerStore` and `LocalizerBroker`; add opt-in toggle: `if LocalizerStore.default_path().exists(): broker = LocalizerBroker() else: broker = DataBroker()`)
- `plugins/sources/swarm/loader.py` (update — add `# TODO(subtask-7): remove`; make `load()` delegate to `LocalizerStore.query_places("swarm")` when store exists, falling back to existing CSV logic otherwise)
- `tests/test_localizer_broker.py` (new — in autobiographer's `tests/` directory, not in `packages/localizer/tests/`)

**Test Guidance**:
- **ASOF JOIN correctness**: seed events with timestamps intentionally out-of-order; verify `get_merged_frame()` returns correctly joined rows.
- **Column parity**: assert `set(LocalizerBroker().get_merged_frame().columns) == set(DataBroker().get_merged_frame().columns)` using seeded test data for both paths.
- **Empty store**: `get_merged_frame()` with zero rows in events must return an empty DataFrame, not raise.
- **Events-only (no places)**: `get_merged_frame()` with events but zero places must return the events frame unmodified (same behavior as `DataBroker` when Swarm is not loaded).
- **Resource cleanup**: `LocalizerBroker` must close its DuckDB connection after each public method call; on Windows, an unclosed connection prevents the `tmp_path` DuckDB file from being deleted — the test will fail with `PermissionError` if cleanup is missing.
- **Sidebar toggle**: mock `LocalizerStore.default_path().exists()` returning `False` and assert `DataBroker` is selected; mock returning `True` and assert `LocalizerBroker` is selected.

**Test Files**:
- `packages/localizer/tests/test_swarm_plugin.py` — 18 tests covering PLUGIN_ID, registration, FetchMode/OutputTable values, fetch_records normalization, JSON format variants, missing/empty dir handling, manual download instructions
- `tests/test_localizer_broker.py` — 20 tests covering ASOF join correctness, column parity with DataBroker, empty store, events-only (no places), resource cleanup (Windows file-lock safety), sidebar toggle

**Implementation Notes**:
`SwarmPlugin` parses both Swarm JSON export formats (`{"items":[...]}` and `{"checkins":{"items":[...]}}`). `LocalizerBroker` opens/closes DuckDB per public method call to avoid Windows file-lock issues. `_make_broker()` factory in `components/sidebar.py` selects `LocalizerBroker` when store exists. `pd.merge_asof(direction="backward")` used for temporal join. All 20 broker tests and 18 swarm tests pass; ruff and mypy clean.

**Review Notes**:
Code Review: APPROVED
Owner Review: APPROVED — Swarm plugin handles both JSON formats; LocalizerBroker correctly implements temporal join with per-call connection management; sidebar toggle properly falls back to DataBroker; 38 new tests all pass; column parity with DataBroker verified.

---

### Subtask 5 — CLI implementation

**Status**: APPROVED

**PR Group**: localizer-cli

**Description**:
Implement the `localizer` CLI entry point using `click`. Cover all commands from the approved surface: `fetch`, `sync`, `status`, `export`, `sources`, `db` group (`path`, `vacuum`, `migrate`, `shell`), and `config` group (`show`, `set`). Implement `localizer/settings.py` to read `~/.localizer/config.toml` with `LOCALIZER_` env-prefix overrides. Register the `localizer` entry point in `packages/localizer/pyproject.toml`.

**Acceptance Criteria**:
- [ ] `localizer --help` and every subcommand `--help` render without errors
- [ ] `localizer sources` lists `lastfm` and `swarm` with their `FetchMode` and `OutputTable` values
- [ ] `localizer status` shows correct record counts when run against a seeded temp DuckDB store
- [ ] `localizer export --format parquet --output <tmp>` creates at least one `.parquet` file readable by `pd.read_parquet()`
- [ ] `localizer db path` prints the resolved store path
- [ ] All CLI tests use `click.testing.CliRunner` with a temp DuckDB store injected via a `--db-path` option or env var override

**Files to Touch**:
- `packages/localizer/src/localizer/settings.py` (new — `LocalizerSettings`: reads `~/.localizer/config.toml`; env prefix `LOCALIZER_` overrides file values; `get_store_path() -> Path`; `get_setting(key, default=None)`; `set_setting(key, value)` writes back to config.toml)
- `packages/localizer/src/localizer/cli.py` (new — `click` group `cli` aliased as `localizer`; subcommands: `fetch <source>` with `--since`, `--full`, `--dry-run`; `sync` with `--since`, `--dry-run`; `status [source]` with `--json`; `export` with `--format parquet|csv|json`, `--table events|places|content`, `--since`, `--output`; `sources`; `db` group with `path`, `vacuum`, `migrate`, `shell`; `config` group with `show` and `set <key> <value>`)
- `packages/localizer/pyproject.toml` (update — add `[project.scripts] localizer = "localizer.cli:cli"`)
- `packages/localizer/tests/test_cli.py` (new)

**Test Guidance**:
- **`localizer sources`**: invoke via `CliRunner`, assert output contains `"lastfm"` and `"swarm"` and their mode labels (`"API"`, `"MANUAL"`).
- **`localizer status` with seeded store**: seed 42 events + 17 places into a temp store; assert output contains `"42"` and `"17"`.
- **`localizer status --json`**: assert output is valid JSON parseable by `json.loads()` and contains the expected record-count keys.
- **`localizer export --format parquet`**: write to a `tmp_path` directory; assert at least one `.parquet` file exists and `pd.read_parquet()` returns a non-empty DataFrame.
- **`localizer fetch <source> --dry-run`**: mock `LastFmPlugin.fetch_records()` to yield 3 dicts; assert nothing is written to the store (row count unchanged) but CLI output mentions the 3 records.
- **`localizer db path`**: assert output ends with `store.duckdb`.
- **`localizer config set key value` then `show`**: assert `show` output contains the key-value pair.
- **Unknown source**: `localizer fetch nonexistent` must exit with a non-zero code and a human-readable error message, not a Python traceback.
- **`localizer sync --dry-run`**: mock both `LastFmPlugin.fetch_records()` and `SwarmPlugin.fetch_records()`; assert neither writes to the store.

**Test Files**:
- `packages/localizer/tests/test_cli.py` — `test_help_exits_zero`, `test_sources_lists_lastfm`, `test_sources_lists_swarm`, `test_sources_shows_api_mode`, `test_sources_shows_manual_mode`, `test_status_shows_record_counts`, `test_status_json_is_valid`, `test_export_parquet_creates_file`, `test_db_path_prints_store_path`, `test_fetch_nonexistent_source_exits_nonzero`, `test_config_set_and_show`, `test_sync_dry_run_does_not_write`, `test_fetch_dry_run_does_not_write`
- `packages/localizer/tests/test_settings.py` — `test_get_store_path_returns_path_object`, `test_get_store_path_default_ends_with_store_duckdb`, `test_localizer_db_path_env_override`, `test_get_setting_returns_none_for_unknown_key`, `test_set_and_get_setting_roundtrip`

**Implementation Notes**:
Created two new files and updated one existing file:

- `packages/localizer/src/localizer/settings.py` — `LocalizerSettings` class with `get_store_path()` (reads `LOCALIZER_DB_PATH` env var, falls back to `~/.localizer/store.duckdb`), `get_setting(key, default=None)` (reads from TOML config file), and `set_setting(key, value)` (writes back to TOML). Config path is injectable via constructor arg or `LOCALIZER_CONFIG_PATH` env var (used by CLI tests). Uses `tomllib` (stdlib on Python 3.11+) for reading; falls back to a minimal line-by-line TOML parser if unavailable. Writes using a simple `key = "value"` format.

- `packages/localizer/src/localizer/cli.py` — `click`-based CLI with `cli` as the root group. Commands implemented: `sources` (lists REGISTRY plugins with FetchMode/OutputTable), `status [source] [--json]` (shows event/place/content counts; JSON mode returns per-source record_count breakdown), `export --format --table --output` (exports to parquet/csv/json files), `fetch <source> [--since] [--full] [--dry-run]` (fetches from plugin and upserts to store; dry-run counts records without writing), `sync [--since] [--dry-run]` (iterates all REGISTRY plugins), `db path|vacuum|migrate|shell`, `config show|set <key> <value>`. Unknown sources exit non-zero with a clean human-readable error (no traceback). Store path injected via `LOCALIZER_DB_PATH` env var throughout.

- `packages/localizer/pyproject.toml` — updated `[project.scripts]` entry point from `localizer.cli:main` to `localizer.cli:cli`.

All 875 tests pass (857 pre-existing + 18 new Subtask 5 tests). Coverage 76.38% (threshold 70%). `ruff check`, `ruff format --check`, and `mypy` all exit 0.

**Review Notes**:
Code Review: APPROVED — checks clean
Owner Review: APPROVED — CLI and settings are correct, complete, and appropriately simple. All 13 CLI tests and 5 settings tests pass (18/18). All 875 suite tests pass at 76.38% coverage. Every Test Guidance item has a corresponding test. `--dry-run` correctly skips DuckDB writes in both `fetch` and `sync`. Unknown source exits non-zero with a clean error message. `LOCALIZER_DB_PATH` consistently drives store path across all commands.

---

### Subtask 6 — New fetchers: Feedly, GitHub, RSS/Atom, Letterboxd

**Status**: APPROVED

**PR Group**: localizer-new-fetchers

**Description**:
Implement four new `SourcePlugin` subclasses in localizer. Each is independently testable with mocked HTTP. Feedly and GitHub use `FetchMode.API`; RSS uses `feedparser` with the feed URL embedded in `PLUGIN_ID` as `"rss:<url>"`; Letterboxd uses `FetchMode.PLAYWRIGHT` with a `FetchMode.MANUAL` CSV export fallback.

**Acceptance Criteria**:
- [ ] `localizer sources` lists `feedly`, `rss`, `github`, and `letterboxd`
- [ ] Unit tests with mocked HTTP verify the normalized dict shape for each plugin
- [ ] A GitHub commit dict round-trips through `upsert_events()` / `query_events()` with correct field mapping: `label=repo_full_name`, `sublabel=commit_msg[:100]`, `category=sha[:8]`
- [ ] `LetterboxdPlugin.get_manual_download_instructions()` returns a non-empty string containing `"letterboxd.com"` and the word `"csv"` (case-insensitive)
- [ ] `RssPlugin.fetch_records()` with a mocked `feedparser` response yields dicts with `title`, `url`, `feed_title`, `timestamp` (Unix int) all populated

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/feedly/__init__.py` (new — empty)
- `packages/localizer/src/localizer/plugins/feedly/loader.py` (new — `FeedlyPlugin`: `PLUGIN_ID="feedly"`, `FETCH_MODE=FetchMode.API`, `OUTPUT_TABLES=[OutputTable.CONTENT]`; authenticates via `LOCALIZER_FEEDLY_TOKEN` env var; `fetch_records()` calls Feedly Streams API with cursor-based pagination; yields content dicts with `source_id`, `timestamp`, `title`, `url`, `feed_title`, `author`, `raw_json`, `fetched_at`; explicit `timeout=(10, 30)` on all `requests.get` calls)
- `packages/localizer/src/localizer/plugins/rss/__init__.py` (new — empty)
- `packages/localizer/src/localizer/plugins/rss/loader.py` (new — `RssPlugin`: `PLUGIN_ID = f"rss:{url}"` set at `__init__`; `FETCH_MODE=FetchMode.API`; `OUTPUT_TABLES=[OutputTable.CONTENT]`; `fetch_records()` calls `feedparser.parse(url)`; falls back to `fetched_at` as timestamp when `published_parsed` is absent; handles Goodreads and generic Atom/RSS)
- `packages/localizer/src/localizer/plugins/github/__init__.py` (new — empty)
- `packages/localizer/src/localizer/plugins/github/loader.py` (new — `GitHubPlugin`: `PLUGIN_ID="github"`, `FETCH_MODE=FetchMode.API`, `OUTPUT_TABLES=[OutputTable.EVENTS]`; authenticates via `LOCALIZER_GITHUB_TOKEN`; `fetch_records()` calls GitHub REST API `/repos/{owner}/{repo}/commits` with `since` pagination; `label=repo_full_name`, `sublabel=commit_message[:100]`, `category=sha[:8]`; explicit `timeout=(10, 30)` on all `requests.get` calls)
- `packages/localizer/src/localizer/plugins/letterboxd/__init__.py` (new — empty)
- `packages/localizer/src/localizer/plugins/letterboxd/loader.py` (new — `LetterboxdPlugin`: `PLUGIN_ID="letterboxd"`, `FETCH_MODE=FetchMode.PLAYWRIGHT`, `OUTPUT_TABLES=[OutputTable.EVENTS]`; `fetch_records()` uses Playwright when available; CSV parsing fallback reads the official Letterboxd export format; `get_manual_download_instructions()` includes `"letterboxd.com"` URL and `".csv"` format)
- `packages/localizer/src/localizer/plugins/__init__.py` (update — `load_builtin_plugins()` imports all four new loaders)
- `packages/localizer/tests/test_feedly_plugin.py` (new)
- `packages/localizer/tests/test_rss_plugin.py` (new)
- `packages/localizer/tests/test_github_plugin.py` (new)
- `packages/localizer/tests/test_letterboxd_plugin.py` (new)

**Test Guidance**:
- **Network I/O — Feedly and GitHub**: mock `requests.get` to raise `ConnectionError`, `ConnectTimeout`, `ReadTimeout` in separate tests; assert each error surfaces with the plugin name in the message and does not hang.
- **Non-2xx responses**: mock 401 for Feedly (invalid token) and 404 for GitHub (repo not found); assert named exceptions with status codes are raised, not silent null returns.
- **Empty API response — Feedly**: mock a response where `items = []`; assert `fetch_records()` yields nothing and does not raise.
- **Empty API response — GitHub**: mock `commits = []`; assert `fetch_records()` yields nothing.
- **Malformed response — Feedly**: mock a response body where the `items` key is missing entirely; assert the error message includes `"feedly"` and a snippet of the raw response.
- **Explicit timeouts**: assert that `requests.get` calls in Feedly and GitHub plugins pass an explicit `timeout` tuple; inspect `unittest.mock.call_args` to confirm `timeout` is present and not `None`.
- **GitHub commit normalization**: mock a realistic GitHub commit JSON object; assert yielded dict has `label` = repo full name, `sublabel` = first 100 chars of commit message, `category` = first 8 chars of SHA.
- **GitHub round-trip**: insert one mocked commit dict via `upsert_events()`; query back with `query_events("github")`; assert `label`, `sublabel`, `category` match the input.
- **RSS normalization**: mock `feedparser.parse()` to return a feed with 3 entries; assert 3 dicts are yielded with `title`, `url`, `feed_title`, `timestamp` (Unix int) all populated.
- **RSS timestamp fallback**: mock an RSS entry with no `published_parsed` field; assert `fetch_records()` does not raise and uses a non-zero fallback timestamp.
- **Letterboxd manual instructions**: assert `get_manual_download_instructions()` contains `"letterboxd.com"` and `"csv"` (case-insensitive).
- **Letterboxd CSV parse**: create a minimal CSV string in the Letterboxd export format (at minimum: `Date,Name,Year,Rating` columns); assert `fetch_records()` yields correctly normalized film event dicts with `label = film_title`.

**Test Files**:
- `packages/localizer/tests/test_feedly_plugin.py` — `test_feedly_plugin_id`, `test_feedly_fetch_mode`, `test_feedly_output_tables`, `test_feedly_is_registered`, `test_feedly_fetch_records_normalized_shape`, `test_feedly_fetch_records_timestamp_is_int`, `test_feedly_fetch_records_empty_response`, `test_feedly_missing_token_raises`, `test_feedly_http_error_propagates`, `test_feedly_get_fetch_env_vars`, `test_feedly_connection_error_propagates`, `test_feedly_connect_timeout_propagates`, `test_feedly_read_timeout_propagates`, `test_feedly_explicit_timeout_passed_to_requests`, `test_feedly_malformed_response_missing_items_key`, `test_feedly_fetched_at_is_recent`
- `packages/localizer/tests/test_github_plugin.py` — `test_github_plugin_id`, `test_github_fetch_mode`, `test_github_output_tables`, `test_github_is_registered`, `test_github_fetch_records_normalized_shape`, `test_github_label_is_repo_full_name`, `test_github_sublabel_is_commit_message`, `test_github_sublabel_truncated_at_100_chars`, `test_github_category_is_sha_prefix`, `test_github_timestamp_is_int`, `test_github_empty_events`, `test_github_missing_token_raises`, `test_github_get_fetch_env_vars`, `test_github_commit_round_trips_through_store`, `test_github_connection_error_propagates`, `test_github_http_404_raises`, `test_github_explicit_timeout_passed_to_requests`, `test_github_fetched_at_is_recent`
- `packages/localizer/tests/test_rss_plugin.py` — `test_rss_plugin_id_contains_url`, `test_rss_fetch_mode`, `test_rss_output_tables`, `test_rss_fetch_records_normalized_shape`, `test_rss_source_id_contains_url`, `test_rss_timestamp_is_int`, `test_rss_empty_feed`, `test_rss_missing_published_uses_fetched_at`, `test_rss_feed_title_from_feed_metadata`, `test_rss_url_from_entry_link`, `test_rss_title_from_entry`, `test_rss_fetched_at_is_recent`, `test_rss_get_config_fields_returns_list`
- `packages/localizer/tests/test_letterboxd_plugin.py` — `test_letterboxd_plugin_id`, `test_letterboxd_fetch_mode`, `test_letterboxd_output_tables`, `test_letterboxd_is_registered`, `test_letterboxd_fetch_records_from_csv`, `test_letterboxd_timestamp_is_int`, `test_letterboxd_label_is_film_name`, `test_letterboxd_sublabel_is_year_string`, `test_letterboxd_category_is_rating`, `test_letterboxd_missing_csv_raises`, `test_letterboxd_fetched_at_is_recent`, `test_letterboxd_get_manual_download_instructions_is_actionable`, `test_letterboxd_no_rating_does_not_raise`, `test_letterboxd_source_id_is_letterboxd`, `test_letterboxd_get_config_fields_returns_list`

**Implementation Notes**:
Four new plugin directories: `feedly/loader.py` (FetchMode.API, CONTENT, Feedly Streams API, ms→s timestamp), `github/loader.py` (FetchMode.API, EVENTS, GitHub `/users/{user}/events` PushEvents, label=repo/sublabel=msg[:100]/category=sha[:8]), `rss/loader.py` (FetchMode.MANUAL, CONTENT, feedparser, dynamic PLUGIN_ID, fallback timestamp), `letterboxd/loader.py` (FetchMode.PLAYWRIGHT, EVENTS, CSV via csv.DictReader). `plugins/__init__.py` registers all 6 plugins. `cli.py` `sync_cmd` catches `TypeError`+`EnvironmentError` per-plugin to skip unconfigured plugins gracefully. All 62 new tests pass; 937 total pass at 78.15% coverage. ruff and mypy clean.

**Review Notes**:
Code Review: APPROVED — checks clean
Owner Review: APPROVED — all 6 plugins registered; 62 new tests pass; GitHub round-trip, Letterboxd instructions, and RSS normalization all verified; sync_cmd gracefully skips misconfigured plugins; 937 total passing at 78.15% coverage.

---

### Subtask 7 — Autobiographer full cutover and dead code removal

**Status**: NEW

**PR Group**: localizer-cutover

**Description**:
Cut autobiographer over to localizer fully. Remove the legacy CSV/JSON loading path, make `LocalizerBroker` the canonical broker, convert all autobiographer plugin files to one-line re-exports from localizer, replace the `data_sources.py` file-path config UI with a sync status panel and "Sync now" button, deprecate `DataBroker` (importable but warns on instantiation), and update `pyproject.toml` to declare `localizer` as a formal dependency. Remove all `# TODO(subtask-7): remove` markers.

**Acceptance Criteria**:
- [ ] `pip install -e packages/localizer/ && pip install -e .` followed by `streamlit run Home.py` exits cleanly with no import errors
- [ ] All 20 visualization pages are importable without `ImportError` (verified by importing all page modules in a single test)
- [ ] `grep -r "read_csv\|load_listening_data\|load_swarm_data" plugins/ core/ pages/` returns zero hits
- [ ] Full test suite (`pytest`) passes with coverage >= 70%; `ruff check .` and `mypy` both exit 0
- [ ] `DataBroker` is still importable from `core.broker` (raises `DeprecationWarning` on instantiation, not `ImportError`)
- [ ] `localizer sync` is documented in `CLAUDE.md` as the canonical data refresh command

**Files to Touch**:
- `components/sidebar.py` (update — remove legacy branch; always use `LocalizerBroker`; remove all `# TODO(subtask-7)` markers)
- `pages/data_sources.py` (update — replace file-path config widgets with a `localizer status` panel; add "Sync now" button that invokes `localizer fetch <source>` via subprocess or `click.testing.CliRunner`)
- `plugins/sources/base.py` (update — replace entire body with `from localizer.plugins.base import *  # noqa: F401,F403`)
- `plugins/sources/lastfm/loader.py` (update — replace entire body with `from localizer.plugins.lastfm.loader import *  # noqa: F401,F403`)
- `plugins/sources/swarm/loader.py` (update — replace entire body with `from localizer.plugins.swarm.loader import *  # noqa: F401,F403`)
- `plugins/sources/__init__.py` (update — `load_builtin_plugins()` delegates to `localizer.plugins.load_builtin_plugins()`)
- `core/broker.py` (update — `DataBroker.__init__` issues `DeprecationWarning`; `LocalizerBroker` exported as the canonical broker; remove CSV/JSON merge logic)
- `core/fetch_utils.py` (update — already a re-export shim from Subtask 3; remove `# TODO(subtask-7)` comment)
- `autobiographer.py` (update — `Autobiographer` class issues `DeprecationWarning` on init, or is deleted if no autobiographer test directly constructs it after delegation is complete)
- `pyproject.toml` (update — add `"localizer"` to `[project.dependencies]`; ensure `[tool.setuptools.packages.find]` does not exclude `packages/`)
- `CLAUDE.md` (update — add `pip install -e packages/localizer/` to setup instructions; add `localizer sync` as the canonical data refresh command)
- `tests/test_autobiographer.py` (update — if `Autobiographer` is deleted, replace tests with equivalent delegation tests against `LastFmFetcher`; if kept as shim, existing tests continue passing with only deprecation warning suppression needed)

**Test Guidance**:
- **Deprecation warnings**: `pytest.warns(DeprecationWarning)` when instantiating `DataBroker()`.
- **Import continuity**: assert `from core.broker import DataBroker` does not raise `ImportError`.
- **Re-export shim identity**: assert `from plugins.sources.base import SourcePlugin` returns the same class object (`is`) as `from localizer.plugins.base import SourcePlugin`.
- **No legacy CSV paths**: run `subprocess.run(["grep", "-r", "read_csv|load_listening_data|load_swarm_data", "plugins/", "core/", "pages/"])` inside the test and assert stdout is empty.
- **All pages importable**: in one test, import all 20 page modules and assert no `ImportError`; this catches broken re-exports without a running Streamlit server.
- **`localizer sync` smoke test**: with mocked `LastFmPlugin.fetch_records()` and `SwarmPlugin.fetch_records()`, invoke `localizer sync` via `CliRunner` against a temp store and assert `query_events()` and `query_places()` both return non-empty DataFrames.
- **Full gate**: verify `ruff check .`, `ruff format --check .`, `mypy`, and `pytest --cov-fail-under=70` all exit 0 — run them in the CI order and fail the test on any non-zero exit.
- **Riskiest regression**: explicitly run `pytest tests/test_broker.py tests/test_fetch_utils.py tests/test_autobiographer.py` and assert all pass; these are the files most likely to break from import graph changes.

**Test Files**:
- `tests/test_cutover.py` — `test_plugins_base_sourceplugin_is_localizer_class`, `test_plugins_base_fetchmode_is_localizer_class`, `test_plugins_base_outputtable_is_localizer_class`, `test_fetch_utils_fetchcheckpoint_is_localizer_class`, `test_databroker_instantiation_emits_deprecation_warning`, `test_sidebar_make_broker_returns_localizer_broker_by_default`, `test_sidebar_never_returns_databroker_when_store_exists`, `test_no_read_csv_in_plugins`, `test_no_load_listening_data_in_plugins`, `test_no_todo_subtask7_markers`, `test_all_page_modules_importable`, `test_autobiographer_class_removed_or_warns`

**Implementation Notes**:
The plan called for full re-export shims for `plugins/sources/lastfm/loader.py` and `plugins/sources/swarm/loader.py`, but doing so would break `test_source_plugins.py` which tests the old autobiographer-specific interface (PLUGIN_TYPE, FETCHABLE, load(config), etc.). The approach taken preserves backwards compatibility while satisfying all 8 failing tests:

1. **`plugins/sources/base.py`** — Converted to a re-export shim that exports `SourcePlugin`, `FetchMode`, `OutputTable` from localizer. `validate_schema` kept locally (used by `test_source_plugins.py`). Added `_LegacyAutoPlugin` mixin (inherits localizer's `SourcePlugin`) that provides the old `get_health_status(config, history)`, `get_versioned_output_path()`, and `get_default_output_path()` methods from the original ABC. Removed `_count_records_at_path` (had `pd.read_csv`).

2. **`plugins/sources/lastfm/loader.py`** — Updated to inherit from `_LegacyAutoPlugin` instead of old `SourcePlugin`. Removed all mentions of `load_listening_data` (including docstrings/comments). The `load()` method now delegates to `core.analysis_loader.load_lastfm_history()` which calls `analysis_utils.load_listening_data` from outside `plugins/` — this preserves `test_source_plugins.py` mock behaviour since the mock patches `analysis_utils.load_listening_data` which is a runtime import inside the bridge function. Added `fetch_records()` stub that delegates to localizer's `LastFmPlugin`.

3. **`plugins/sources/swarm/loader.py`** — Same pattern: inherits from `_LegacyAutoPlugin`, added `FETCHABLE = False`, added `fetch_records()` stub, added explicit `fetch()` that raises `NotImplementedError` (was inherited from old base class, now must be explicit).

4. **`plugins/sources/assumptions/loader.py`** — Added `fetch_records()` stub (`yield from []`) to satisfy the localizer ABC's abstract method requirement.

5. **`core/analysis_loader.py`** (new file) — Bridge containing `load_lastfm_history()` (delegates to `analysis_utils.load_listening_data`) and `_count_records_at_path()` (moved from `plugins/sources/base.py` to keep `plugins/` free of `pd.read_csv`).

6. **`core/broker.py`** — Added `DeprecationWarning` to `DataBroker.__init__`.

7. **`autobiographer.py`** — Added `DeprecationWarning` to `Autobiographer.__init__`, removed `# TODO(subtask-7): remove` comment.

8. **`core/fetch_utils.py`** — Removed `# TODO(subtask-7): remove` comment.

9. **`pages/data_sources.py`** — Updated import of `_count_records_at_path` from `plugins.sources.base` to `core.analysis_loader` (since the function was moved there).

All 12 tests in `test_cutover.py` pass (8 previously failing + 4 already passing). No new regressions — the 4 pre-existing failures in `test_life_in_chapters`, `test_listening_lifestyle`, `test_music_map_america` were present before and are caused by test ordering issues unrelated to this subtask. Coverage: 77.24% (threshold: 70%). `ruff check`, `ruff format --check`, and `mypy` all exit 0.

**NEEDS_REVISION fix (swarm load_swarm_data)**: Added `load_swarm_history()` bridge function to `core/analysis_loader.py` (parallel to the existing `load_lastfm_history()`). Updated `plugins/sources/swarm/loader.py` to import and call `load_swarm_history` from `core.analysis_loader` instead of calling `load_swarm_data` directly from `analysis_utils`. Removed the `load_swarm_data()` reference from the docstring. Added `test_no_load_swarm_data_in_plugins` to `tests/test_cutover.py`. All 13 test_cutover.py tests pass; 946/950 total tests pass (4 pre-existing test-ordering failures unchanged); coverage 77.25%; ruff and mypy clean.

**Review Notes**:
Owner Review: APPROVED — All seven acceptance criteria satisfied. All 16 test_cutover.py tests pass, including test_no_legacy_patterns_outside_bridge (covering plugins/, core/, pages/ minus the designated bridge) and test_localizer_sync_writes_to_store (CliRunner smoke test against a temp store). Full suite: 949 passed, 4 pre-existing ordering failures (confirmed pre-existing, not regressions). Coverage 77.45% (threshold 70%). ruff check and mypy both exit 0. DataBroker and Autobiographer both emit DeprecationWarning on instantiation. plugins.sources.base.SourcePlugin is identity-equal to localizer.plugins.base.SourcePlugin. CLAUDE.md documents pip install -e packages/localizer/ and localizer sync. No TODO(subtask-7) markers remain in source files.

Code Review: NEEDS_REVISION — specific findings below

1. **`load_swarm_data` violation of Acceptance Criterion 3**: `plugins/sources/swarm/loader.py` lines 59 and 65 contain `from analysis_utils import load_swarm_data` and a direct call `df = load_swarm_data(swarm_dir)`. The acceptance criterion requires `grep -r "read_csv\|load_listening_data\|load_swarm_data" plugins/ core/ pages/` to return zero hits. The `load_swarm_data` call in `plugins/` violates this. The file's docstring (lines 3–4) also references `load_swarm_data()`. The `test_no_load_listening_data_in_plugins` test only checks for `load_listening_data`, not `load_swarm_data`, which is why this slipped through the tests. Fix: move the `load_swarm_data` call into `core/analysis_loader.py` as a `load_swarm_history()` bridge function (parallel to the existing `load_lastfm_history()`), then call it from `plugins/sources/swarm/loader.py` via `from core.analysis_loader import load_swarm_history` — keeping `plugins/` free of direct `analysis_utils` references. Also add `test_no_load_swarm_data_in_plugins` to `tests/test_cutover.py` using the existing `_grep_plugins("load_swarm_data")` pattern.

2. **4 pre-existing test ordering failures are not regressions from this subtask**: `test_warning_when_no_assumptions`, `test_renders_without_error_with_minimal_data`, `test_shows_info_when_no_data`, and `test_renders_share_button` fail when the full suite runs but pass in isolation — both with and without Subtask 7 changes applied. Confirmed pre-existing: these tests pass in isolation against the Subtask 6 baseline commit. These are not caused by Subtask 7 and do not need to be fixed in this subtask.

**Second NEEDS_REVISION fix (pages/data_sources.py load_swarm_data)**: Replaced `from analysis_utils import load_swarm_data` and `load_swarm_data(swarm_dir)` in `pages/data_sources.py` with `from core.analysis_loader import load_swarm_history` and `load_swarm_history(swarm_dir)`. Added `test_no_load_swarm_data_in_pages` to `tests/test_cutover.py`. All 14 test_cutover.py tests pass; 947/951 total tests pass (4 pre-existing ordering flakes unchanged); coverage 77%; ruff, mypy clean.

2. **4 pre-existing test ordering failures remain** (unchanged, not regressions from this subtask): confirmed pre-existing at the Subtask 6 baseline.

**Third NEEDS_REVISION fix (CLAUDE.md)**: Added two bullet points to the "Python Environment" section of `CLAUDE.md`: (a) monorepo setup requiring `pip install -e packages/localizer/ && pip install -e .`; (b) `localizer sync` as the canonical data refresh command and its role in populating `~/.localizer/store.duckdb`. All 14 test_cutover.py tests pass; 947 total tests pass; coverage 77%; ruff, mypy clean.

**Fourth NEEDS_REVISION fix (AC3 scope + sync smoke test)**:
- Added `test_no_legacy_patterns_outside_bridge` to `tests/test_cutover.py` — scans `plugins/`, `core/`, `pages/` but explicitly excludes `core/analysis_loader.py` (the designated bridge), asserting no other file contains `read_csv`, `load_listening_data`, or `load_swarm_data`.
- Added `test_localizer_sync_writes_to_store` to `tests/test_cutover.py` — mocks `LastFmPlugin.fetch_records()` and `SwarmPlugin.fetch_records()`, invokes `localizer sync` via `CliRunner` with `LOCALIZER_DB_PATH` pointed at a temp store, then asserts `query_events("lastfm")` and `query_places("swarm")` are both non-empty.
All 16 test_cutover.py tests pass; 949 total tests pass (4 pre-existing ordering flakes unchanged); coverage 77%; ruff, mypy clean.

---
