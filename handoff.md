# Handoff

## Plan Status
status: IN_PROGRESS

## Task Overview

**The problem**: the user ran `localizer fetch google_timeline`, which correctly wrote 3,076
`google_timeline` rows into `~/.localizer/store.duckdb`'s `places` table (confirmed via
`LocalizerStore().query_places(source_id="google_timeline")`). But the Streamlit app's map/geo
pages never show this data. Root cause, confirmed by reading the code: `core/broker.py`'s
`LocalizerBroker` (DuckDB-backed, fully unit-tested in isolation) is never actually called from the
live data-loading path. `components/sidebar.py::_make_broker()` exists and correctly chooses
`LocalizerBroker` vs `DataBroker`, but its only callers are test files — `render_sidebar()` and
`_load_data_with_progress()` call `load_listening_data()` / `load_swarm_data()` /
`load_google_timeline()` directly against legacy REGISTRY-driven file-path config, and gate the
entire load on a Last.fm CSV file existing on disk. When only the DuckDB store is populated (no CSV
configured), `render_sidebar()` bails out immediately and `st.session_state["df"]` /
`["swarm_df"]` are never populated from the store at all.

**The fix**: make `render_sidebar()` branch into a DuckDB-backed load path when
`~/.localizer/store.duckdb` exists (reusing `_make_broker()`'s existing "opt-in when store exists"
selection logic, which is currently correct but dead code), adapt the broker's generic
events/places schema into the exact column shapes the rest of the app already depends on, and run
the existing `apply_swarm_offsets()` timezone/location-assumption logic on top — mirroring how
`DataBroker.get_merged_frame()` itself works today (it calls `apply_swarm_offsets`, not a raw join).

**Five design decisions**, resolved by reading `core/broker.py`, `analysis_utils.py`,
`packages/localizer/src/localizer/store/db.py`, and every localizer plugin's `fetch_records()`
in full:

1. **Column/shape parity — the highest-risk finding.** `LocalizerBroker.get_merged_frame()`
   returns generic columns (`timestamp, label, sublabel, category, source_id, lat, lng,
   place_name, place_type`) via a plain ASOF join — completely different from what
   `st.session_state["_raw_df"]` (produced by `apply_swarm_offsets`) and `["swarm_df"]` (produced
   by `load_swarm_data`) contain today: `artist, track, album, date_text, city, state, country,
   lat, lng, tz_offset_min` and `timestamp, offset, city, state, country, venue, venue_category,
   lat, lng, event_category, shout` respectively. Worse: the DuckDB `places` table schema
   (`SELECT timestamp, lat, lng, place_name, place_type, source_id FROM places`) has **no
   structured city/state/country columns at all** — `place_name` is a venue/label name (e.g. a
   Swarm business name, or a Google Timeline semantic label like "Home"/"Work"), not an
   administrative city name. The old `load_swarm_data()` got city/state/country either from
   Swarm's `venue.location` fields or by reverse-geocoding lat/lng — neither of which
   `SwarmPlugin.fetch_records()` in the localizer package currently preserves or performs.
   **Resolution**: do not attempt reverse-geocoding in this plan (that is a real gap in the
   localizer Swarm/Timeline ingestion layer, called out below as an explicit out-of-scope
   limitation, not silently worked around). Instead, build a small, pure adapter module
   (`core/localizer_frames.py`, Subtask 2) that renames the broker's generic columns into the
   app's expected names (`label→artist`, `sublabel→track`, `category→album`, `place_name→city`
   *and* `venue`, `place_type→venue_category`) and fills `state`/`country` with `""` and
   `offset` with `0` when not derivable. This is safe because every page that reads `state`,
   `country`, or `tz_offset_min` already guards for their absence/emptiness (verified by reading
   `pages/geo_explorer.py`'s `_render_us_choropleth` — checks `"state" not in music_df.columns` —
   and `_build_city_stats`, which only requires `city, lat, lng, artist, track, date_text`).
   `lat`/`lng` (the actual map-plotting requirement) are always present and accurate, since the DB
   schema stores them faithfully for every source.

2. **`apply_swarm_offsets` is *not* superseded by the ASOF join.** Read
   `LocalizerBroker.get_merged_frame()`'s implementation in full: its `pd.merge_asof(...,
   direction="backward")` only carries `lat/lng/place_name/place_type` onto the nearest prior
   place row — it does not touch timezone offsets, does not apply the assumptions file's
   holidays/trips/residency/default-location fallback, and produces no `tz_offset_min` column.
   **Resolution**: the wiring must *not* call `get_merged_frame()` for the final `_raw_df`. It
   must fetch raw events and raw places separately (new `LocalizerBroker.get_events_frame()` /
   `get_places_frame()` methods, Subtask 1), adapt them into the legacy `lastfm_df`/`swarm_df`
   shapes (Subtask 2), and then call the existing, already-tested `apply_swarm_offsets(events_df,
   places_df, assumptions)` exactly as `DataBroker.get_merged_frame()` already does — reusing
   proven logic instead of re-deriving it.

3. **Legacy plugin config coexistence.** `_make_broker()`'s existing docstring intent — "opt-in
   when the DuckDB store exists, else fall back to legacy per-session file config, unchanged" — is
   preserved as-is and made the actual live switch. When `~/.localizer/store.duckdb` exists,
   `render_sidebar()` uses the broker path exclusively for that session (the legacy
   `file_path`/`swarm_dir`/`timeline_path` REGISTRY config becomes inert for data loading, though
   the Data Sources page's plugin config UI itself is untouched — configuring/fetching still writes
   to the DuckDB store via `localizer fetch`, so there is no competing write path). When the store
   does not exist, behavior is byte-for-byte unchanged from today. Rationale: this matches the
   pre-existing, already-tested `_make_broker()` contract exactly, requires no new user-facing
   toggle, and avoids the correctness risk of two data sources disagreeing silently.

4. **`swarm_df` consumers.** `pages/places.py::render_checkin_insights()` and
   `pages/geo_explorer.py`'s map views read `st.session_state["swarm_df"]` directly and use only
   `lat`, `lng`, `city`, `country` (both guard for `country`'s absence). `LocalizerBroker` gets a
   new `get_places_frame()` method (all sources, unfiltered — mirrors the internal
   `store.query_places()` call already made inside `get_merged_frame()`) and Subtask 2's
   `places_to_swarm_frame()` adapter produces a frame with the *exact* column set
   `load_swarm_data()`'s empty-frame declares (`timestamp, offset, city, state, country, venue,
   venue_category, lat, lng, event_category, shout`) so no consumer, present or future, sees a
   narrower shape than it does today.

5. **Caching.** The existing cache (`get_cache_key`/`get_cached_data`/`save_to_cache`) keys on
   file **mtimes** of the Last.fm CSV / Swarm dir / assumptions file / Timeline path — none of
   which exist in broker mode, and a stale key would silently show data from before the last
   `localizer sync`, which is exactly the correctness risk flagged for this decision.
   **Resolution**: do not reuse the file-hash cache for the broker path at all. Instead, reuse the
   *existing* `_current_config`/`_loaded_config` reload-detection mechanism already in
   `render_sidebar()` (it already skips reloading when `_loaded_config == current_config`) with a
   broker-mode identity tuple of `(store_path, store_mtime, assumptions_path)`. Since `localizer
   sync` / `localizer fetch` write to the DuckDB file, its mtime changes on every sync, so this
   tuple naturally invalidates the in-session cache exactly when the underlying data changes — no
   new caching layer, no staleness window, reusing a mechanism already proven correct for the
   legacy path.

**Explicit out-of-scope limitation (documented, not fixed here)**: the "Cinematic Fly-through"
recording feature in `pages/places.py` / `pages/geo_explorer.py` shells out to
`record_flythrough.py <csv_path> --swarm_dir ... --assumptions ...`, reading `csv_path` from
`st.session_state["_loaded_config"][0]`. In broker mode there is no CSV file to pass.
`_current_config`/`_loaded_config` keeps its existing 4-tuple shape in broker mode with index 0
(`file_path`) set to `""`, so index-based reads in `places.py`/`geo_explorer.py` keep working
without a `KeyError`/`IndexError`; the flythrough subprocess will simply fail to record (the
existing `rec_status.update(label="Recording failed...", state="error")` error path already
handles this gracefully — verified by reading that code — so the app does not crash). Making
`record_flythrough.py` itself DuckDB-aware is out of scope for this plan, since the user's ask is
specifically about the map/geo *display* path. Subtask 4's manual verification step confirms this
degrades gracefully rather than crashing.

**Files never touched by this plan** (confirmed via investigation, listed so later agents don't
re-litigate): `core/analysis_loader.py` (unrelated CSV/plugin bridge), `pages/data_sources.py`
(legacy plugin config UI — remains visually present; whether to add "using DuckDB store" messaging
there is a reasonable follow-up but is feature creep beyond this task's ask), and
`record_flythrough.py` (see limitation above).

**Architecture context**: no prior `/feature-dev` or `/plan-feature` run occurred for this task;
the user supplied a fully diagnosed root cause and asked for investigation-driven planning. The
five design decisions above were made during this planning pass by reading the actual
implementations of `core/broker.py`, `analysis_utils.py`, `packages/localizer/src/localizer/store/db.py`,
and all three localizer plugin loaders (`lastfm`, `swarm`, `google_timeline`) in full — not by
inference from names alone.

Plan Review: APPROVED — all five design decisions verified line-for-line against core/broker.py, analysis_utils.py, packages/localizer/src/localizer/store/schema.py, db.py, components/sidebar.py, and pages/geo_explorer.py/places.py (column shapes, ASOF-join scope, places-table schema, _make_broker's zero production callers, state/column guards, load_swarm_data's empty-frame columns, and the flythrough error path all match the plan's claims exactly); the 4-subtask DAG is acyclic with current:1 a valid topological order, Files-to-Touch and Test-Files are fully disjoint across subtasks, and every subtask has ≥5 falsifiable, value-level acceptance criteria plus concrete Test Guidance covering edge cases.

## Current Subtask
current: 3

---

## Subtasks

### Subtask 1 — Add raw frame accessors to `LocalizerBroker`

**Status**: APPROVED

**PR Group**: localizer-broker-frame-adapters

**Depends On**: none

**Description**:
Add two new public methods to `core/broker.py::LocalizerBroker`: `get_events_frame() ->
pd.DataFrame` and `get_places_frame() -> pd.DataFrame`, each returning **all** rows (unfiltered by
`source_id`) from the events/places tables respectively — i.e. exactly what
`get_merged_frame()` already fetches internally via `store.query_events()` /
`store.query_places()` before joining them. These are the raw inputs Subtask 3 needs to run
`apply_swarm_offsets()` instead of relying on the ASOF join (see Task Overview design decision 2).
Follow the exact resource-management pattern already used by every other method in this class:
open the store via `self._open_store()` inside a `with` block, catch `Exception` narrowly around
the query, and return an empty `pd.DataFrame()` on any failure — never leave a connection open on
an error path.

**Acceptance Criteria**:
- [ ] `LocalizerBroker(store_path=...).get_events_frame()` on a store seeded with N event rows
  (any source) returns a DataFrame with exactly N rows and columns `timestamp, label, sublabel,
  category, source_id`.
- [ ] `LocalizerBroker(store_path=...).get_places_frame()` on a store seeded with M place rows
  (mixed sources, e.g. `swarm` and `google_timeline`) returns a DataFrame with exactly M rows and
  columns `timestamp, lat, lng, place_name, place_type, source_id` — i.e. it is **not**
  filtered to a single `source_id` the way `get_frame(plugin_id)` is.
- [ ] Both methods return an empty `pd.DataFrame()` (not `None`, not a raised exception) on a
  fresh/empty store.
- [ ] After calling either method, a second process/connection can immediately reopen the same
  DuckDB file (mirrors the existing `test_localizer_broker_closes_connection_after_get_frame`
  pattern) — no lingering file lock.
- [ ] `DataBroker` and all pre-existing `LocalizerBroker` methods are untouched — this subtask is
  purely additive.

**Files to Touch**:
- `core/broker.py` (edit: add `get_events_frame()`, `get_places_frame()` to `LocalizerBroker`)
- `tests/test_localizer_broker.py` (extended — new tests only)

**Test Guidance**:
- **Resource cleanup (required — this subtask touches DuckDB connection acquisition):** add a
  test mirroring the existing `test_localizer_broker_closes_connection_after_get_merged_frame` /
  `..._after_get_frame` pair for both new methods — after calling `get_events_frame()` /
  `get_places_frame()`, open a second `LocalizerStore` on the same `tmp_path` file and confirm it
  does not raise/hang. This is Windows-critical (an unclosed DuckDB handle blocks `tmp_path`
  teardown) and this repo already has the pattern to copy.
- Also verify cleanup happens even when the query raises: monkeypatch `store.query_events` (or
  `query_places`) to raise inside the `with` block and confirm the method still returns an empty
  DataFrame (per the existing `except Exception: return pd.DataFrame()` pattern) rather than
  propagating, and that the store's context manager still exits (connection released) — do not
  rely on the happy path alone.
- Seed places from two different `source_id`s (`swarm` and `google_timeline`) in one test and
  assert `get_places_frame()` returns rows from both — this is the behavior that distinguishes it
  from `get_frame(plugin_id)`, which filters to one source.
- Reuse the `_seed_events`/`_seed_places` helpers already defined at the top of
  `tests/test_localizer_broker.py` rather than duplicating fixture-building code.

**Test Files**:
- `tests/test_localizer_broker.py` (extended, 9 new tests, RED-confirmed with
  `AttributeError: 'LocalizerBroker' object has no attribute 'get_events_frame'`, 20 pre-existing
  tests unaffected): `test_get_events_frame_returns_all_rows_with_expected_columns`,
  `test_get_places_frame_returns_all_rows_with_expected_columns`,
  `test_get_events_frame_empty_store_returns_empty_dataframe`,
  `test_get_places_frame_empty_store_returns_empty_dataframe`,
  `test_get_places_frame_unfiltered_across_multiple_source_ids`,
  `test_get_events_frame_closes_connection_after_call`,
  `test_get_places_frame_closes_connection_after_call`,
  `test_get_events_frame_returns_empty_and_releases_connection_on_query_exception`,
  `test_get_places_frame_returns_empty_and_releases_connection_on_query_exception`.
- Tester's notes for the coder: mirror `get_frame()`'s exact shape (lines 220-238 of
  `core/broker.py`) — `try: with self._open_store() as store: df = store.query_events(...);
  return df` / `except Exception: return pd.DataFrame()` (keep the `# noqa: BLE001` comment for
  ruff consistency). Do not touch `_available_types`/`_refresh_available_types()` bookkeeping —
  the new methods are pure query passthroughs, unlike `get_merged_frame()`/`load()`.

**Implementation Notes**:
Added `get_events_frame()` and `get_places_frame()` to `LocalizerBroker` in `core/broker.py`,
directly after the existing `get_frames()` method. Both mirror `get_frame()`'s exact
try/with/except shape: open the store via `self._open_store()`, call `store.query_events()` /
`store.query_places()` with no `source_id` filter (returning all rows across every source), and
`except Exception: return pd.DataFrame()` with the `# noqa: BLE001` comment for ruff consistency.
Neither method touches `_available_types`/`_refresh_available_types()` — purely additive query
passthroughs, no side effects, no changes to `DataBroker` or any pre-existing method.

Verification:
- `pytest tests/test_localizer_broker.py -v --no-cov` — 29 passed (20 pre-existing + 9 new), 0
  failed.
- `ruff check core/broker.py tests/test_localizer_broker.py` — all checks passed.
- `ruff format --check core/broker.py tests/test_localizer_broker.py` — both files already
  formatted.
- `mypy` (unscoped) — Success: no issues found in 14 source files.
- `pytest tests/ --no-cov -q` (full suite, regression check) — 846 passed, 4 failed, 1 collection
  error. All four failures are in `tests/test_sidebar.py::TestBrokerModeWiring` (Subtask 3, still
  RED — no broker branch exists yet in `components/sidebar.py`); the collection error is
  `tests/test_localizer_frames.py` failing to import `core.localizer_frames` (Subtask 2, still
  RED — module not yet created). Both are pre-existing, expected RED states for not-yet-implemented
  subtasks, not regressions introduced by this change. No other test in the suite was affected.

**Review Notes**:
Code Review: APPROVED — checks clean. `get_events_frame()`/`get_places_frame()` (core/broker.py
lines 248-276) mirror `get_frame()`'s exact try/with(`self._open_store()`)/except Exception (with
`# noqa: BLE001`)/return `pd.DataFrame()` pattern; neither is filtered by `source_id`; neither
touches `_available_types`/`_refresh_available_types()`. Scoped tests: `pytest
tests/test_localizer_broker.py -v --no-cov` — 29 passed, 0 failed. `ruff check core/broker.py
tests/test_localizer_broker.py` — all checks passed. `ruff format --check .` — only
`tests/test_localizer_frames.py` (Subtask 2, out of scope) needs reformatting; Subtask 1's files
are clean. `mypy` (unscoped) — Success, no issues in 14 source files. Full suite `pytest tests/
--no-cov -q` — 846 passed, 4 failed (all `tests/test_sidebar.py::TestBrokerModeWiring`, Subtask 3,
still RED by design) plus 1 collection error (`tests/test_localizer_frames.py`, Subtask 2, still
RED by design) — no other regressions. No dead code, secrets, or N+1 patterns found in the diff.

Owner Review: APPROVED — independently re-read core/broker.py's `get_events_frame()`/
`get_places_frame()` (lines 248-276) and confirmed the diff against `main` is a clean, purely
additive 30-line insertion (git diff main -- core/broker.py: "1 file changed, 30 insertions(+)")
touching nothing else — `DataBroker` and every pre-existing `LocalizerBroker` method untouched.
Both methods are minimal passthroughs mirroring `get_frame()`'s exact
try/with(`self._open_store()`)/except Exception(`# noqa: BLE001`)/return `pd.DataFrame()` shape;
neither filters by `source_id` (satisfies the criterion distinguishing them from `get_frame()`);
the exception path is caught outside the `with` block so the context manager's `__exit__` (and
thus connection release) runs before the `except` clause returns the empty frame on both the
happy and failure paths. Independently re-ran: `pytest tests/test_localizer_broker.py -v --no-cov`
— 29 passed, 0 failed; `mypy` (unscoped) — Success, no issues in 14 source files; `ruff check .` —
2 errors, both in `tests/test_localizer_frames.py` (Subtask 2, out of scope), zero in Subtask 1's
files (confirmed separately: `ruff check core/broker.py tests/test_localizer_broker.py` — all
checks passed); `ruff format --check .` — only `tests/test_localizer_frames.py` needs
reformatting, as expected. Verified all 5 acceptance criteria against the 9 new tests
(row-count + column-shape, empty-store, multi-source-id unfiltered query, connection-release on
both happy and exception paths) — every Test Guidance item has a corresponding test, using the
existing `_seed_events`/`_seed_places` helpers as instructed. No naming, simplicity, or best-practice
issues found.

---

### Subtask 2 — Column-shape adapters: broker schema → legacy `lastfm_df`/`swarm_df` shapes

**Status**: APPROVED

**PR Group**: localizer-broker-frame-adapters

**Depends On**: none

**Description**:
Create `core/localizer_frames.py` with two pure, Streamlit-free functions:

- `events_to_lastfm_frame(events_df: pd.DataFrame) -> pd.DataFrame` — renames
  `label→artist`, `sublabel→track`, `category→album`; adds a `date_text` column via
  `pd.to_datetime(events_df["timestamp"], unit="s")` (naive datetime64, matching
  `load_listening_data()`'s output — confirmed via `tests/test_analysis_utils.py`, which builds
  `date_text` fixtures as naive `pd.to_datetime(["2021-01-01 10:00", ...])` with no `utc=True`);
  keeps `timestamp` and `source_id`. Empty input returns an empty frame with columns
  `timestamp, date_text, artist, track, album, source_id`.
- `places_to_swarm_frame(places_df: pd.DataFrame) -> pd.DataFrame` — renames `place_name→city`
  (also copied into a separate `venue` column — see Task Overview decision 1 for why `place_name`
  stands in for both), `place_type→venue_category`; adds `state=""`, `country=""`, `offset=0`,
  `event_category=""`, `shout=""` (the DuckDB places schema does not carry these — see Task
  Overview decision 1); keeps `timestamp`, `lat`, `lng`. Sorts by `timestamp` ascending (required
  by `apply_swarm_offsets`'s `np.searchsorted` binary search over `swarm_df["timestamp"]`, and
  matches `load_swarm_data()`'s and `_load_data_with_progress()`'s existing sort convention).
  Empty input returns an empty frame with **exactly** the same column list `load_swarm_data()`
  declares on its empty-input path: `timestamp, offset, city, state, country, venue,
  venue_category, lat, lng, event_category, shout`.

This module has no dependency on `LocalizerBroker`, DuckDB, or Streamlit — it is pure
DataFrame-in/DataFrame-out logic, independently testable with hand-built fixtures.

**Acceptance Criteria**:
- [ ] `events_to_lastfm_frame()` on a 3-row events DataFrame produces exactly the renamed
  columns with values matching the input row-for-row (e.g. `label="Radiohead"` →
  `artist="Radiohead"` at the same row index) — not just "columns exist," but value-level
  correctness.
- [ ] `events_to_lastfm_frame()`'s `date_text` column has dtype `datetime64[ns]` (no timezone)
  and, for a known unix timestamp, produces the exact same wall-clock value
  `load_listening_data()` would produce for an equivalent CSV row (cross-checked against a
  `pd.to_datetime(..., unit="s")` reference value in the test, not against `load_listening_data`
  itself, since there is no CSV involved).
- [ ] `places_to_swarm_frame()` on a 3-row places DataFrame produces `city` and `venue` both
  equal to the input's `place_name`, `venue_category` equal to `place_type`, `state == ""`,
  `country == ""`, `offset == 0`, `lat`/`lng` preserved exactly (no float precision loss).
- [ ] `places_to_swarm_frame()`'s output is sorted ascending by `timestamp` even when the input is
  out of order.
- [ ] Both functions return an empty DataFrame with the exact column list specified above (not a
  subset, not extra columns) when given an empty input DataFrame — this is directly consumed by
  `apply_swarm_offsets`, which branches on `swarm_df.empty`, so an empty-but-wrong-shaped frame
  would silently degrade rather than error.
- [ ] Neither function imports `streamlit`, `duckdb`, or `localizer.store.db` — grep-checkable,
  proving this module stays a pure adapter layer independent of the broker's I/O.

**Files to Touch**:
- `core/localizer_frames.py` (new)
- `tests/test_localizer_frames.py` (new)

**Test Guidance**:
- This is **the riskiest subtask in the plan** — a wrong column rename or a silently-swapped
  `city`/`venue` assignment would not raise any exception anywhere downstream; pages would just
  render an empty or mislabeled map, exactly the kind of silent breakage the user flagged as the
  top risk. Write tests that assert on actual values at specific row indices, not just
  `set(df.columns) == expected`.
- Test both functions with realistic multi-row fixtures built by hand (do not go through
  `LocalizerBroker`/DuckDB here — that coupling belongs to Subtask 3's integration test).
- Cover: empty-input column-shape-preservation (both functions), single-row, multi-row with mixed
  `source_id` values (function must not care about `source_id` beyond passing it through), a place
  row with `place_name=""` (empty string, not missing) to confirm no accidental `NaN`/`None`
  substitution occurs where an empty string is the correct passthrough value, and non-monotonic
  input timestamps for the sort-order assertion.
- Verify float precision: use lat/lng values with several decimal places (e.g. `51.50735`) and
  assert exact equality after the round-trip, not `pytest.approx` — renaming columns must not
  coerce dtypes.

**Test Files**:
- `tests/test_localizer_frames.py` (new, 12 tests, RED-confirmed with
  `ModuleNotFoundError: No module named 'core.localizer_frames'`):
  `test_events_to_lastfm_frame_renames_columns_with_row_level_values`,
  `test_events_to_lastfm_frame_preserves_timestamp_and_mixed_source_id`,
  `test_events_to_lastfm_frame_date_text_dtype_and_value`, `test_events_to_lastfm_frame_single_row`,
  `test_events_to_lastfm_frame_empty_input_exact_columns`,
  `test_places_to_swarm_frame_renames_and_fills_defaults`,
  `test_places_to_swarm_frame_sorted_ascending_by_timestamp`,
  `test_places_to_swarm_frame_empty_place_name_not_coerced_to_nan`,
  `test_places_to_swarm_frame_preserves_lat_lng_exact_precision`,
  `test_places_to_swarm_frame_single_row`, `test_places_to_swarm_frame_empty_input_exact_columns`,
  `test_localizer_frames_module_has_no_forbidden_imports` (source-inspection test reading the
  module's text directly, so it stays meaningful post-implementation too). Also hard-asserts
  `source_id`/`place_name`/`place_type` do NOT leak into `places_to_swarm_frame`'s output, since
  the legacy `swarm_df` shape has no `source_id` column.
- Tester's notes: `load_swarm_data()`'s empty-input column list (`timestamp, offset, city, state,
  country, venue, venue_category, lat, lng, event_category, shout`) matches the plan 1:1 — mirror
  it literally. `load_listening_data()` is NOT a usable model for `events_to_lastfm_frame`'s
  empty-frame shape (it returns `None` on missing file, and its columns are raw-CSV-shaped, never
  `label/sublabel/category`-renamed) — build the empty-frame column list directly from this
  subtask's Acceptance Criteria text instead. `core/` is a plain package with `__init__.py`, so
  `from core.localizer_frames import ...` is the correct import path.

**Implementation Notes**:
Created `core/localizer_frames.py` with two pure, Streamlit/DuckDB-free functions:

- `events_to_lastfm_frame(events_df)`: empty input returns
  `pd.DataFrame(columns=LASTFM_COLUMNS)` where `LASTFM_COLUMNS = ["timestamp",
  "date_text", "artist", "track", "album", "source_id"]`. Non-empty path renames
  `label→artist`, `sublabel→track`, `category→album` via `.rename()`, adds `date_text
  = pd.to_datetime(events_df["timestamp"], unit="s")` (naive datetime64[ns]), then
  reindexes to the exact `LASTFM_COLUMNS` order.
- `places_to_swarm_frame(places_df)`: empty input returns
  `pd.DataFrame(columns=SWARM_COLUMNS)` matching `analysis_utils.py::load_swarm_data()`'s
  literal empty-frame column list (confirmed by reading lines 142-160 of that file).
  Non-empty path builds a fresh `pd.DataFrame` with `city` and `venue` both copied from
  `place_name` (not derived from each other, so an empty-string `place_name` survives as
  `""` in both, never coerced to `NaN`), `venue_category` from `place_type`, `state`/
  `country`/`event_category`/`shout` hardcoded to `""`, `offset` hardcoded to `0`,
  `lat`/`lng` passed through unchanged (no dtype coercion), then sorts ascending by
  `timestamp` and resets the index before reindexing to `SWARM_COLUMNS`. `source_id`,
  `place_name`, `place_type` are never included in the output frame.
- One deviation caught by the source-inspection test
  (`test_localizer_frames_module_has_no_forbidden_imports`): my first draft's module
  docstring mentioned "localizer.store.db" in prose, which the test's substring grep
  correctly flagged since it checks raw file text, not imports. Reworded the docstring
  to describe the same thing without using that literal string.

No deviations from Files to Touch; no files added beyond the plan.

Verification:
- `pytest tests/test_localizer_frames.py -v --no-cov` — 12 passed, 0 failed (all
  acceptance criteria covered: row-level rename correctness, timestamp/source_id
  passthrough with mixed source_id, date_text dtype+value, single-row, empty-input
  exact column shape for both functions, sort-order correctness, empty-string
  place_name not coerced to NaN, exact float precision on lat/lng, and the
  forbidden-imports source-inspection check).
- `ruff check core/localizer_frames.py` — all checks passed.
- `ruff format core/localizer_frames.py` then `ruff format --check core/localizer_frames.py`
  — reformatted once (line-length wrap on the `.rename()` call), then clean. Did not
  touch `tests/test_localizer_frames.py` (pre-existing unused `pytest` import flagged by
  `ruff check .` at repo root belongs to the tester's file, out of scope for this
  subtask's Files to Touch).
- `mypy` (unscoped) — Success: no issues found in 15 source files.
- `pytest tests/ -v --no-cov -q` (full suite) — 858 passed, 4 failed. All 4 failures are
  in `tests/test_sidebar.py::TestBrokerModeWiring` (Subtask 3, still RED by design — no
  broker branch exists yet in `components/sidebar.py`). The prior collection error for
  `tests/test_localizer_frames.py` is now gone since the module exists. No other
  regressions; 858 = 846 pre-existing passed + 12 new Subtask 2 tests.

**Review Notes**:
Code Review: NEEDS_REVISION — independently verified all four value-level correctness items
(rename correctness, date_text naive-datetime64 derivation and empty-column shape, city/venue
both copied from place_name with state/country/offset/lat/lng/sort correctness cross-checked
byte-for-byte against `analysis_utils.py::load_swarm_data()`'s literal empty-column list at
lines 146-160, and a case-sensitive re-grep confirming no literal `streamlit`/`duckdb`/
`localizer.store.db` substrings anywhere in `core/localizer_frames.py` — the docstring's
capitalized "Streamlit-" / "DuckDB-free" prose does not collide with the test's lowercase-only
check, so that part is fine). No correctness bugs found in `core/localizer_frames.py` itself.
However, the unscoped mandatory gate fails on this subtask's own Files-to-Touch:
- `ruff check .` → 1 error: `F401 'pytest' imported but unused` in
  `tests/test_localizer_frames.py:20` (the import is never referenced anywhere in the file —
  confirmed via grep for `pytest\.` with zero hits).
- `ruff format --check .` → `tests/test_localizer_frames.py` would be reformatted (1 of 131
  files).
Both are in a file explicitly listed under this subtask's own "Files to Touch". CLAUDE.md
Section 7 requires `ruff check .`/`ruff format --check .` to exit 0 with "no exceptions" before
any commit/push; the Implementation Notes' rationale ("tester's file, out of scope") does not
override that mandate since the file is part of this subtask's deliverable set. Fix: remove the
unused `import pytest` line (or replace with a `# noqa: F401` only if there's a real reason to
keep it — there isn't one visible here) and run `ruff format .`. Scoped tests
(`pytest tests/test_localizer_frames.py -v --no-cov`, 12 passed), `mypy` (unscoped, success on 15
files), and the full suite (`pytest tests/ --no-cov -q`, 858 passed / 4 failed, all 4 the expected
Subtask 3 `TestBrokerModeWiring` RED tests, no other regressions) all otherwise pass cleanly.
Status flipped back to RED for this one mechanical lint fix; no changes needed to
`core/localizer_frames.py` itself.

**Lint-fix follow-up (coder)**: Removed the unused `import pytest` line from
`tests/test_localizer_frames.py` (no `pytest.` usages existed anywhere in the file) and ran
`ruff format .`, which reformatted that same file (line-length rewrap of the empty-input
column-list literal). No changes made to `core/localizer_frames.py`. Re-verified the full gate:
`ruff check .` — no issues found; `ruff format --check .` — 131 files already formatted; `mypy`
(unscoped) — no issues found; `pytest tests/test_localizer_frames.py -v --no-cov` — 12 passed, 0
failed; full suite `pytest --no-cov -q` — 858 passed, 4 failed (all four are the expected
pre-existing `tests/test_sidebar.py::TestBrokerModeWiring` RED tests for not-yet-implemented
Subtask 3, no other regressions). Status flipped back to GREEN.

Code Review: APPROVED — re-ran the full unscoped gate from a clean venv activation: `ruff check .`
— no issues found; `ruff format --check .` — 131 files already formatted; `mypy` (unscoped) — no
issues found; `pytest tests/test_localizer_frames.py -v --no-cov` — 12 passed, 0 failed; full suite
`pytest --no-cov -q` — 858 passed, 4 failed, all four in `tests/test_sidebar.py::
TestBrokerModeWiring` (Subtask 3, still RED by design — no broker branch exists yet in
`components/sidebar.py`), no other regressions and no collection errors. Independently re-read
`core/localizer_frames.py` and `tests/test_localizer_frames.py` in full: `events_to_lastfm_frame`
correctly renames `label→artist`/`sublabel→track`/`category→album`, derives `date_text` via
`pd.to_datetime(events_df["timestamp"], unit="s")` (naive, no `utc=True`), and returns exactly
`LASTFM_COLUMNS` (`timestamp, date_text, artist, track, album, source_id`) including on the
empty-input path. `places_to_swarm_frame` copies `place_name` into both `city` and `venue`
independently (not derived from each other, so an empty-string `place_name` survives as `""` in
both rather than being coerced to `NaN`), renames `place_type→venue_category`, hardcodes
`state`/`country`/`event_category`/`shout` to `""` and `offset` to `0`, preserves `lat`/`lng`
verbatim (no dtype coercion), sorts ascending by `timestamp`, and drops `source_id`/`place_name`/
`place_type` from the output — matching `SWARM_COLUMNS` exactly, which I cross-checked byte-for-
byte and in the same order against `analysis_utils.py::load_swarm_data()`'s literal empty-frame
column list (lines 146-160: `timestamp, offset, city, state, country, venue, venue_category, lat,
lng, event_category, shout`). Grepped the module source directly for `streamlit`, `duckdb`, and
`localizer.store.db` — zero hits; the module is a pure DataFrame-in/DataFrame-out adapter with no
I/O coupling, as required. The lint-fix follow-up only touched `tests/test_localizer_frames.py`
(removed unused `import pytest`, reformatted); `core/localizer_frames.py` itself is unchanged from
the version already verified correct in the prior review round. No remaining issues found.

Owner Review: APPROVED — independently re-read `core/localizer_frames.py` and
`tests/test_localizer_frames.py` in full against Subtask 2's Description/Acceptance Criteria in
this handoff. Confirmed: (1) value-level correctness — `events_to_lastfm_frame` renames
`label/sublabel/category` to `artist/track/album` with row-for-row values verified, derives
`date_text` via naive `pd.to_datetime(timestamp, unit="s")` matching `test_analysis_utils.py`'s
naive-datetime fixture convention; `places_to_swarm_frame` copies `place_name` independently into
both `city` and `venue` (confirmed an empty-string `place_name` survives as `""` in both, not
coerced to `NaN`), renames `place_type→venue_category`, hardcodes `state/country/event_category/
shout` to `""` and `offset` to `0`, preserves `lat`/`lng` with exact float precision, and sorts
ascending by `timestamp`. (2) Simplicity — two flat functions plus two module-level column-order
constants (`LASTFM_COLUMNS`/`SWARM_COLUMNS`); no classes, no premature abstraction, no dead code;
docstrings are Google-style and explain purpose/params/returns rather than narrating "what" the
code does line-by-line, matching CLAUDE.md's documentation convention. (3) Architectural
constraint — grepped `core/localizer_frames.py` directly for `streamlit`, `duckdb`, and
`localizer.store.db`: zero hits; the module imports only `pandas` and `__future__.annotations`,
confirming it stays the pure, I/O-free adapter layer this subtask (flagged as the plan's riskiest)
requires for independent testability. (4) Independently re-ran `pytest
tests/test_localizer_frames.py -v --no-cov` — 12 passed, 0 failed — and `ruff check
core/localizer_frames.py tests/test_localizer_frames.py` — no issues found. No naming,
simplicity, correctness, or best-practice issues found beyond what the reviewer already caught and
the coder already fixed (the unused-import lint issue). Approved; advancing `current` to 3.

---

### Subtask 3 — Wire the broker + adapters into `components/sidebar.py`

**Status**: RED

**PR Group**: wire-localizer-broker-into-app

**Depends On**: 1, 2

**Description**:
Restructure `render_sidebar()` / `_load_data_with_progress()` so that when
`LocalizerStore.default_path().exists()` is true (the same check `_make_broker()` already makes),
the entire data-loading path branches to a new broker-backed loader instead of the legacy
CSV-gated path — fixing the actual reported bug. Concretely:

1. Add a private helper, e.g. `_broker_store_identity() -> tuple[str, float, str] | None`, that
   returns `(str(store_path), store_path.stat().st_mtime, assumptions_path)` when the store
   exists, else `None`. This becomes the broker-mode `current_config` value (see Task Overview
   decision 5) — reusing the *existing* `_current_config`/`_loaded_config` skip-reload mechanism
   in `render_sidebar()` rather than adding a second one.
2. When in broker mode: instantiate `LocalizerBroker()` (default store path), call
   `get_events_frame()` / `get_places_frame()`, adapt them via
   `events_to_lastfm_frame()` / `places_to_swarm_frame()` (Subtask 2), then call the existing
   `apply_swarm_offsets(events_frame, places_frame, assumptions)` — do **not** call
   `get_merged_frame()` (see Task Overview decision 2). Do not call `get_cache_key` /
   `get_cached_data` / `save_to_cache` in this branch at all (see Task Overview decision 5); set
   `st.session_state["_cache_status"]` to a new literal, e.g. `"n/a"`, so the Data Sources page's
   existing cache-status display does not misreport a legacy cache hit/miss that never happened.
   Store the adapted places frame into `st.session_state["swarm_df"]` and the
   `apply_swarm_offsets` result into `st.session_state["_raw_df"]`, exactly like the legacy path
   does today.
3. Keep `st.session_state["_current_config"]` as a **4-tuple** in both modes so
   index-based readers elsewhere (`pages/places.py`, `pages/geo_explorer.py`'s flythrough code,
   which read `loaded_config[0]`/`[1]`/`[2]`) never hit an `IndexError`. In broker mode, use
   `("", "", assumptions_path, "")` for `_current_config`/`_loaded_config`'s *displayed* tuple
   while the *reload-detection* comparison uses the richer `_broker_store_identity()` value
   stored under a separate session-state key (e.g. `_loaded_store_identity`) — do not conflate the
   two, since `_current_config`'s shape is a public-ish contract read by other modules.
4. When the store does not exist, fall through to exactly today's legacy behavior — no change to
   that code path's logic, only its position (now inside an `else` branch).

**Acceptance Criteria**:
- [ ] With a `tmp_path`-scoped DuckDB store seeded with `lastfm` events and `google_timeline`
  places (mocking `LocalizerStore.default_path()` to point at it, following
  `tests/test_cutover.py`'s `_FakePath` pattern), calling `render_sidebar()` populates
  `st.session_state["df"]` with non-empty `lat`/`lng` values sourced from the seeded
  `google_timeline` rows, and `st.session_state["swarm_df"]` with the corresponding place rows.
- [ ] When the store does not exist, `render_sidebar()`'s behavior (including the early-return
  when no legacy `file_path` is configured) is byte-for-byte unchanged — run the full existing
  `tests/test_sidebar.py` suite unmodified and confirm it still passes.
- [ ] Calling `render_sidebar()` twice in the same session with the store's mtime unchanged
  performs the broker query/`apply_swarm_offsets` computation exactly once (reload-skip works);
  touching the store file's mtime between calls (e.g. `os.utime`) triggers a second load — this is
  the load-bearing proof that Task Overview decision 5's mtime-based reload-identity actually
  prevents both staleness *and* redundant recomputation.
- [ ] `st.session_state["_current_config"]` remains a 4-element tuple in both broker and legacy
  modes (index-checkable), so `pages/places.py`'s `loaded_config[0]`/`[1]`/`[2]` reads never raise.
- [ ] In broker mode, `st.session_state["_cache_status"]` is never `"hit"` or `"miss"` (those
  literals only apply to the legacy file-hash cache) — confirms the file-hash cache path is
  genuinely not exercised in broker mode, not just skipped-but-still-reachable.

**Files to Touch**:
- `components/sidebar.py` (edit: branch `render_sidebar()`/`_load_data_with_progress()` on store
  existence; add `_broker_store_identity()`; wire in `LocalizerBroker` +
  `core.localizer_frames` adapters)
- `tests/test_sidebar.py` (extended — new tests for the broker branch; zero edits to the existing
  `TestLoadDataCombination` tests, which must keep proving the legacy path is untouched)

**Test Guidance**:
- Follow this file's existing mocking convention exactly: `_make_st()` helper building a
  `MagicMock()` with a real dict `session_state`, `st.columns.return_value` set to a tuple of
  `MagicMock()`s matching however many columns the broker-mode status widget uses (re-check the
  actual `st.columns([...])` call count/shape inside the new branch and size the mock tuple to
  match — per this repo's documented convention of keeping `side_effect`/`return_value` column
  counts in sync with the real call), and `patch.object(sidebar, "st", st)` plus
  `patch.object(sidebar.os.path, "exists", ...)` as needed.
- Mock `LocalizerStore.default_path()` via `patch("localizer.store.db.LocalizerStore.default_path",
  ...)` returning a real `tmp_path` file (not a `MagicMock` with `.exists()` stubbed) for the
  integration-style tests that need a real mtime to manipulate; use the lighter `_FakePath`
  pattern from `tests/test_cutover.py` only for tests that merely need `.exists()` to return
  True/False and don't touch mtime.
- Test the reload-skip / reload-trigger behavior directly: seed a store, call `render_sidebar()`,
  patch/spy on `LocalizerBroker.get_events_frame` (or the module-level adapter calls) to count
  invocations, call `render_sidebar()` again unchanged (expect 0 additional calls), bump the
  store file's mtime with `os.utime`, call a third time (expect 1 additional call).
- Test the `_cache_status` acceptance criterion directly by asserting the literal value after a
  broker-mode `render_sidebar()` call.
- Test that when `LocalizerStore.default_path()` raises `ImportError` (localizer package not
  installed — mirrors `_make_broker()`'s existing `try/except ImportError` guard), `render_sidebar()`
  falls back to legacy behavior rather than crashing.
- This subtask is the second-riskiest in the plan (most files touched, most branching): after
  writing the broker-mode tests, re-run the *entire* `tests/test_sidebar.py` file and diff the
  pass count against pre-change HEAD to catch any accidental regression in the legacy branch
  introduced while restructuring the `if`/`else`.

**Test Files**:
- `tests/test_sidebar.py` (extended with a new `TestBrokerModeWiring` class; zero edits to the
  existing `TestLoadDataCombination` tests). RED-confirmed, 4 tests, all failing for the correct
  reason (no broker branch exists yet, so `render_sidebar()` always takes the legacy early-return
  with no `file_path` configured):
  - `test_render_sidebar_populates_df_from_seeded_broker_store` — fails: `session_state['df']` is
    `None`, expected non-empty with seeded `"Artist0"` in `artist` column.
  - `test_render_sidebar_populates_swarm_df_from_seeded_broker_store` — fails:
    `session_state['swarm_df']` is `None`, expected non-empty with seeded `51.5074` in `lat`/`lng`.
  - `test_cache_status_is_na_literal_in_broker_mode` — fails: `_cache_status` is `None`, expected
    `"n/a"`.
  - `test_render_sidebar_reload_skip_and_trigger_on_store_mtime` — fails:
    `LocalizerStore.query_events` call count is 0, expected >0 (store never queried).
  - Design choice: tests seed a *real* tmp-dir `LocalizerStore` and drive the *real*
    `render_sidebar()` through a mocked `st` only, rather than patching not-yet-existing symbols
    (`get_events_frame`, `events_to_lastfm_frame`, etc.) — robust to the coder's exact internal
    call-site choices while still failing for the right reason today.
  - Three Test Guidance items could not get standalone new tests (documented as a NOTE docstring
    inside `TestBrokerModeWiring` in the test file): (1) "store absent → unchanged legacy
    behavior" is already covered by the untouched `TestLoadDataCombination` tests continuing to
    pass; (2) "`_current_config` stays a 4-tuple" is already true unconditionally today (code
    always writes a 4-tuple), so cannot be made to fail pre-implementation — reviewer should
    verify by inspection; (3) "`ImportError` on `LocalizerStore.default_path()` falls back to
    legacy" has no import site inside `render_sidebar()` yet (only the currently-uncalled
    `_make_broker()` has that guard) — recommend the reviewer add a companion test once the coder
    adds the actual import, verifying it reuses `_make_broker()`'s existing `try/except
    ImportError` pattern.

**Implementation Notes**:
(filled by coder agent)

**Review Notes**:
(filled by owner agent)

---

### Subtask 4 — End-to-end integration test and manual visual verification

**Status**: NEW

**PR Group**: wire-localizer-broker-into-app

**Depends On**: 3

**Description**:
Add one integration test that drives the wired path end-to-end against a **real** temporary
DuckDB store (no mocking of `LocalizerBroker` or the adapter functions — only `streamlit` itself
is mocked, following this repo's established Streamlit-testing convention), seeded with both
`lastfm` events and `google_timeline` places via `LocalizerStore.upsert_events`/`upsert_places`
(reusing the seeding helper patterns from `tests/test_localizer_broker.py`). Then perform and
record the results of the manual visual check the user explicitly asked for: running the real
Streamlit app against a real populated `~/.localizer/store.duckdb` (or a copy pointed at via
`LOCALIZER_DB_PATH`) with no legacy config paths set, and confirming Google Timeline points render
on a map page.

**Acceptance Criteria**:
- [ ] The integration test seeds a `tmp_path` DuckDB store with >=2 `lastfm` events and >=2
  `google_timeline` places, points `LocalizerStore.default_path()` at it, calls
  `render_sidebar()` through a mocked `st`, and asserts `st.session_state["df"]` contains exactly
  the expected number of rows with non-null `lat`/`lng` and `artist`/`track` values matching the
  seeded event data.
- [ ] The same test asserts `st.session_state["swarm_df"]` contains the seeded place rows with
  `city` populated from `place_name` and correct `lat`/`lng`.
- [ ] The test also asserts `st.session_state["df"]["date_text"]` is a proper `datetime64` column
  usable by `.dt.date` (i.e., the exact operation `render_sidebar()`'s date-filter widget performs
  today), proving the adapter's `date_text` column is not just present but genuinely usable by
  existing downstream code, not merely shape-compatible.
- [ ] **Manual verification (recorded in Implementation Notes, not automatable)**: with only
  `~/.localizer/store.duckdb` populated (the user's actual real data — 3,076 `google_timeline`
  rows) and no legacy Last.fm/Swarm/Timeline file paths configured in the session, running
  `streamlit run visualize.py` and opening the Geo Explorer / Places page shows Google Timeline
  location points on the map. Record the exact page(s) checked, the view mode used (3D Globe / 2D
  Map), and whether points appeared, in this subtask's Implementation Notes.
- [ ] **Manual verification of the documented flythrough limitation**: in the same broker-mode
  session, clicking "Record Flythrough" on the Places or Geo Explorer page does not crash the
  Streamlit app (an error is shown in the recording status widget, per the existing error-handling
  path) — confirms Task Overview's explicit out-of-scope limitation degrades gracefully rather
  than raising an unhandled exception that takes down the page.
- [ ] Full existing test suite (`pytest`) passes with zero regressions.

**Files to Touch**:
- `tests/test_sidebar_broker_integration.py` (new)

**Test Guidance**:
- Do not stub `LocalizerBroker`, `core.localizer_frames`, or `LocalizerStore` in this test — the
  whole point is proving the real pieces from Subtasks 1-3 compose correctly end-to-end. Only
  `streamlit` (`st`) is a `MagicMock`, matching every other sidebar test in this repo.
- Reuse `_seed_events`/`_seed_places` from `tests/test_localizer_broker.py` if importable, or
  inline equivalent minimal seeding — do not reinvent a third seeding helper shape.
- Assert on **values**, not just presence: e.g. assert a specific artist name from the seeded
  event appears in `df["artist"].tolist()`, and a specific lat/lng pair from the seeded place
  appears in `swarm_df[["lat", "lng"]]` — silent column-shape drift (Subtask 2's top risk) would
  otherwise pass a presence-only check while showing wrong/blank data on the actual map.
- For the manual verification steps: since this repo's CLAUDE.md documents `localizer sync` /
  `pip install -e packages/localizer/` as prerequisites, note in Implementation Notes whether the
  local dev environment already has `~/.localizer/store.duckdb` populated (per the task
  description, it does — 3,076 rows) or whether a fresh sync was needed to verify.
- After this subtask, do a final read-through of `components/sidebar.py`'s module docstring
  (lines 1-25) — it documents the session-state contract (`_current_config`, `_loaded_config`,
  `_raw_df`, `swarm_df`, `df`, `_cache_status`) and must be updated to describe the new
  broker-mode branch and the `_loaded_store_identity` key, so the contract stays accurate for the
  next person who reads it (this is documentation upkeep, not a new test, but the coder should not
  skip it).

**Test Files**:
HALT (test-ahead phase) — tester correctly declined to write a forced/fragile RED test. Reason:
Subtask 4's Test Guidance explicitly forbids mocking `LocalizerBroker`, `core.localizer_frames`,
or `LocalizerStore` (the whole point is exercising the real Subtask 1-3 composition), but none of
that composition exists yet — `core/broker.py` has no `get_events_frame`/`get_places_frame`,
`core/localizer_frames.py` doesn't exist, and `components/sidebar.py` has no broker-mode branch.
A test written now would either fail for the wrong reason (the unmodified legacy early-return
path, not the intended broker composition) or duplicate Subtask 1/2's own isolated tests without
covering the actual integration surface. **Re-run the tester for Subtask 4 once Subtask 3 reaches
`APPROVED`.** Left at `Status: NEW` per this halt.

**Implementation Notes**:
(filled by coder agent)

**Review Notes**:
(filled by owner agent)

---
