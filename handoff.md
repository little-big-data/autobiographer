# Handoff

## Plan Status
status: COMPLETE

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
current: 4

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

**Status**: APPROVED

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
Implemented the design exactly as specified:

- Added `_broker_store_identity(assumptions_path) -> tuple[str, float, str] | None`
  in `components/sidebar.py`: mirrors `_make_broker()`'s `try/except ImportError`
  guard around `from localizer.store.db import LocalizerStore`, returns
  `(str(store_path), store_path.stat().st_mtime, assumptions_path)` when
  `store_path.exists()`, else `None`.
- Added `_load_data_from_broker(assumptions_path)`: instantiates `LocalizerBroker()`
  (cached in `st.session_state["_broker_instance"]` — see deviation note below),
  calls `get_events_frame()`/`get_places_frame()`, adapts via
  `events_to_lastfm_frame()`/`places_to_swarm_frame()`, then calls the existing
  `apply_swarm_offsets(lastfm_df, swarm_df, assumptions)` — never
  `get_merged_frame()`. Does not touch `get_cache_key`/`get_cached_data`/
  `save_to_cache` at all. Sets `st.session_state["_cache_status"] = "n/a"`.
  Stores the adapted places frame into `swarm_df` and the offset result into
  `_raw_df`, matching the legacy path's session-state keys.
- Rewired `render_sidebar()`: computes `broker_identity =
  _broker_store_identity(assumptions_path)` once per call. When not `None`
  (broker mode), writes `_current_config = ("", "", assumptions_path, "")` (still
  a 4-tuple), compares a separate `_loaded_store_identity` session-state key
  against `broker_identity` to decide whether to skip the reload, and — critically
  — re-computes and stores `_broker_store_identity(assumptions_path)` **after**
  the load completes rather than reusing the pre-load value (see deviation note).
  When `broker_identity` is `None`, falls through to the legacy branch, which is
  byte-for-byte the prior code, now indented under `else`.
- Updated the module docstring's session-state contract to document `"n/a"` for
  `_cache_status` and the new `_loaded_store_identity` key and "Broker mode"
  section.

Two deviations from the plan's literal description, both discovered empirically
while making the reload-skip/trigger test pass (`test_render_sidebar_reload_skip_and_trigger_on_store_mtime`):

1. **DuckDB touches the file's mtime merely by opening a connection for a read
   query** (verified empirically: opening `LocalizerStore` and calling
   `query_events()` changes `store_path.stat().st_mtime` even with no writes).
   This means an identity captured *before* triggering a load is stale by the
   time the next `render_sidebar()` call re-stats the file — every call would
   see a "changed" mtime and reload again, forever. Fix: `render_sidebar()`
   re-computes `_broker_store_identity(assumptions_path)` a second time
   *after* `_load_data_from_broker()` returns, and stores that post-load value
   as `_loaded_store_identity`, not the pre-load value.
2. **`LocalizerBroker()`'s constructor itself performs one `query_events()`/
   `query_places()` call** (via `_refresh_available_types()`, pre-existing
   Subtask-1-adjacent code, untouched here). Reconstructing a new
   `LocalizerBroker()` on every reload would therefore add a second,
   redundant `query_events()` call per reload beyond the one
   `get_events_frame()` call the test expects (it asserts the query count
   increases by *exactly* 1 on a genuine mtime-triggered reload). Fix: cache
   the `LocalizerBroker` instance in `st.session_state["_broker_instance"]`
   and reuse it across reloads within a session, only re-invoking
   `get_events_frame()`/`get_places_frame()` on each reload rather than
   rebuilding the broker.

A third, unplanned fix was required in `tests/test_visualize.py`'s
`TestSidebarDataLoading` class (4 tests: `test_render_sidebar_sets_df_none_when_no_file_path`,
`test_render_sidebar_publishes_current_config`,
`test_render_sidebar_skips_load_when_already_loaded`,
`test_render_sidebar_loads_when_config_changed`). These pre-existing tests call
`render_sidebar()` without mocking `LocalizerStore.default_path()` (they predate
broker-mode wiring and only ever needed to exercise the legacy path). On this
dev machine, `~/.localizer/store.duckdb` genuinely exists (the user's real
3,076-row Google Timeline sync mentioned in the Task Overview), so once
`_broker_store_identity()` became live inside `render_sidebar()`, these 4 tests
started taking the broker branch for real and crashed on the real (unmocked)
`streamlit.status()`/`streamlit.columns()` outside an actual Streamlit script
run (`AttributeError: 'NoneType' object has no attribute 'update'`). This is an
environment-dependent test-isolation gap, not a logic bug: in a clean CI
checkout with no local store, these tests would have passed unmodified. Fixed
by adding `patch("components.sidebar._broker_store_identity", return_value=None)`
to each of the 4 tests' `with` blocks, forcing the legacy branch deterministically
regardless of what real data exists on the machine running the suite — matching
the existing `_FakePath`/`default_path`-mocking convention used elsewhere
(`tests/test_cutover.py`, `tests/test_sidebar.py`'s new `TestBrokerModeWiring`).
No assertions in those 4 tests were changed, only the mock setup.

No changes to `core/broker.py` or `core/localizer_frames.py` (Subtasks 1/2,
already `APPROVED`) — this subtask's diff is confined to `components/sidebar.py`
and the one deviation fix in `tests/test_visualize.py`.

Verification:
- `pytest tests/test_sidebar.py -v --no-cov` — 7 passed, 0 failed: the 3
  pre-existing `TestLoadDataCombination` tests (unchanged, proving the legacy
  path is untouched) plus the 4 new `TestBrokerModeWiring` tests, all now
  passing. No regression in the legacy-path test count (3 before, 3 after).
- `ruff check .` — all checks passed.
- `ruff format --check .` — 131 files already formatted.
- `mypy` (unscoped) — Success: no issues found in 15 source files.
- `pytest --no-cov -q` (full suite) — 862 passed, 0 failed (858 pre-existing +
  4 flipped `TestBrokerModeWiring` tests to GREEN, matching the plan's expected
  count exactly; no other regressions after the `test_visualize.py` mock fix).

Environment note: this worktree's editable installs of `localizer` and
`autobiographer` had drifted to point at the main repo checkout instead of this
worktree (`pip show localizer` showed `Editable project location:
C:\Users\johns\Code\autobiographer\packages\localizer`, missing this branch's
`google_timeline` plugin module and causing a collection-time
`ModuleNotFoundError`). Re-ran `pip install -e packages/localizer/ && pip
install -e .` from this worktree's root (per CLAUDE.md's monorepo setup
instructions) to repoint both editable installs at this worktree before any
tests could collect.

**Review Notes**:
Code Review: APPROVED — full unscoped gate re-run from a clean venv activation: `ruff check .` —
no issues found; `ruff format --check .` — 131 files already formatted; `mypy` (unscoped) —
Success, no issues in 15 source files; `pytest tests/test_sidebar.py -v --no-cov` — exactly 7
passed (3 pre-existing `TestLoadDataCombination` + 4 new `TestBrokerModeWiring`), 0 failed; full
suite `pytest --no-cov -q` — 862 passed, 0 failed, no regressions, matching the plan's expected
count exactly.

Independently read `components/sidebar.py` in full and diffed it against the pre-subtask-3 commit
(`8e9b1b5`, the actual parent — not `main`, which includes unrelated branch history) to isolate
this subtask's real change: `git diff 8e9b1b5 -- components/sidebar.py` is +150/-17 (the -17 is
purely the legacy block's re-indentation under the new `else:`; `_load_data_with_progress()`'s own
body has zero diff hunks inside it — byte-for-byte unchanged, only its position moved). Verified
against spec:
- `_current_config` is a 4-tuple in both modes (`("", "", assumptions_path, "")` in broker mode,
  `(file_path, swarm_dir, assumptions_path, timeline_path)` in legacy mode). Grepped every
  index-based reader (`pages/places.py:317-320`, `pages/geo_explorer.py:467-470`,
  `pages/life_in_chapters.py:525-526`, `pages/listening_lifestyle.py:963-964`,
  `pages/data_sources.py:316-317,460-462`) — all read `_loaded_config` (not `_current_config`,
  a naming nuance in the plan's prose, not a bug), which `render_sidebar()` also sets to the same
  4-tuple `current_config` on every successful load in both branches, so index `[0]`/`[1]`/`[2]`
  reads never raise `IndexError`. `data_sources.py`'s deep-analysis-cache call sites additionally
  guard with `isinstance(..., dict)` before indexing — pre-existing defensive code, unaffected.
- Broker mode never calls `get_cache_key`/`get_cached_data`/`save_to_cache` (grepped
  `core/broker.py` and `_load_data_from_broker()` — those three names appear only inside
  `_load_data_with_progress()`, the legacy function) and never calls `get_merged_frame()` (uses
  `get_events_frame()` + `get_places_frame()` + `apply_swarm_offsets()` per Task Overview decision
  2, confirmed at lines 166-170).
- `_cache_status` is set to exactly `"n/a"` in broker mode (line 176) and only ever `"hit"`/`"miss"`
  inside the legacy function — confirmed by the passing
  `test_cache_status_is_na_literal_in_broker_mode` test and by reading both code paths directly.
- ImportError fallback: `_broker_store_identity()` wraps `from localizer.store.db import
  LocalizerStore` in the same `try/except ImportError: pass` shape as the pre-existing
  `_make_broker()`, returning `None` on failure, which routes `render_sidebar()` straight to the
  `else` (legacy) branch. Confirmed by inspection this is correct. Confirmed the gap is
  intentionally undocumented by a standalone test — `tests/test_sidebar.py`'s
  `TestBrokerModeWiring` docstring explains why (no live import site existed pre-subtask-3 for an
  `ImportError` to interrupt). This is a real but narrow, low-value-to-close coverage gap (the code
  path mirrors an already-tested pattern verbatim); flagging it here rather than blocking on it.
- Scrutinized both empirically-discovered deviations against `core/broker.py`'s actual
  implementation (lines 153-276): `get_events_frame()`/`get_places_frame()` each open a **fresh**
  `self._open_store()` connection and re-query on every call — caching the `LocalizerBroker`
  instance in session state does *not* cache the event/place data itself, only the broker object's
  `_store_path`/`_available_types` bookkeeping (set once by `_refresh_available_types()` in
  `__init__`, unused by the sidebar wiring). So deviation 2 carries no staleness risk — every
  reload still issues a live query against the current file state. Deviation 1 (capturing
  `_loaded_store_identity` post-load rather than pre-load) is the *correct* fix, not a workaround: capturing pre-load would cause every subsequent call to see a perpetually "changed" mtime (since
  opening the store for the load itself bumps mtime) and reload forever; post-load capture is the
  only way to make the existing mtime-based skip mechanism (Task Overview decision 5, unchanged by
  this subtask) actually stabilize. Both are reasonable, well-reasoned responses to real,
  verified environment behavior, not masks of latent bugs.
- Verified the `tests/test_visualize.py` patch is narrowly scoped: `git diff 8e9b1b5 --
  tests/test_visualize.py` is exactly `+13/-0` — four additions of
  `patch("components.sidebar._broker_store_identity", return_value=None)` inside
  `TestSidebarDataLoading`'s four pre-existing tests, zero assertion changes, zero other edits.
  This forces the legacy branch deterministically regardless of this dev machine's real
  `~/.localizer/store.duckdb`, which is a legitimate environment-isolation fix, not a weakening of
  what those tests verify.
- Confirmed `tests/test_sidebar.py`'s `TestLoadDataCombination` class is untouched:
  `git diff 8e9b1b5 -- tests/test_sidebar.py` is `+211/-0` (purely additive: new imports plus the
  new `TestBrokerModeWiring` class) — no deletions, renames, or weakened assertions in the 3
  pre-existing legacy-path tests.

No correctness issues found. Design holds up under independent re-derivation of both deviations.
Status remains GREEN; owner may advance.

Owner Review: APPROVED — independently read `components/sidebar.py` in full (all 379 lines) and
cross-checked against Subtask 3's Description/Acceptance Criteria. Confirmed: (1) the broker/legacy
branch in `render_sidebar()` is a single clean `if broker_identity is not None: ... else: ...` with
no logic duplicated between the two branches beyond the unavoidable "compute config tuple → store
it → check already_loaded → load if needed" shape, which differs enough between the two paths
(different reload-identity source, different session-state keys, different cache semantics) to
justify not being unified into one code path — forcing a shared abstraction here would trade clarity
for cleverness, contrary to CLAUDE.md's Core Philosophy. (2) `_current_config` is written as a
4-tuple in both branches (`("", "", assumptions_path, "")` broker / `(file_path, swarm_dir,
assumptions_path, timeline_path)` legacy), satisfying the index-based-reader contract. (3) Docstrings
are Google-style, present on every new/changed function (`_broker_store_identity`,
`_load_data_from_broker`), and the module docstring (lines 1-45) was genuinely updated with a new
"Broker mode" section and `_loaded_store_identity` contract entry — not just left stale. Type hints
are complete and precise (`tuple[str, float, str] | None`).

One real but non-blocking observation: `_broker_store_identity()` re-implements the same
`try: from localizer.store.db import LocalizerStore; ... except ImportError: pass` /
`store_path.exists()` shape already present in `_make_broker()` (lines 73-95), and `_make_broker()`
itself remains dead code in production (grepped the full repo — its only callers are
`tests/test_cutover.py` and `tests/test_localizer_broker.py`; still zero production call sites after
this subtask, same as before). This is ~5 lines of duplicated guard logic, not a correctness issue,
and the plan's own Subtask 3 description explicitly directs adding a *new* helper
(`_broker_store_identity`) rather than reusing `_make_broker()` — reasonable, since `_make_broker()`
returns a broker instance while the wiring needs a plain identity tuple for reload-detection, a
different return shape. Consolidating the two would be a legitimate future cleanup (e.g. extracting
the existence-check into a shared `_store_path_if_exists()` helper) but is out of this subtask's
scope and not worth blocking APPROVED status over — flagging for a future pass, not sending back.

ImportError-fallback test-coverage gap: accepted as-is, not sent back for a test. Reasoning: (a) the
exact same guard shape has shipped untested in `_make_broker()` since before this plan with no
incident, so there is direct in-repo precedent for accepting inspection-level confidence on this
narrow defensive branch; (b) the branch is three lines with no computation — `try: import X; use X
except ImportError: pass` — where the only way to falsify it would be to monkeypatch Python's import
machinery (e.g. `sys.modules` poisoning) for marginal assurance beyond what two independent code
reads have already confirmed; (c) both the automated reviewer and this owner review independently
traced the control flow by inspection and confirmed `_broker_store_identity()` returning `None` on
`ImportError` correctly routes `render_sidebar()` to the legacy `else` branch. Net: real but narrow
gap, consistent with existing repo precedent, not worth the disproportionate test-authoring effort
for this pass.

Verified full-suite result reported by the reviewer (862 passed, 0 failed) is consistent with the
diff scope reviewed; per instructions, did not re-run the suite myself.

Ready to precede Subtask 4: Subtask 3 is the last blocking dependency for Subtask 4 (`Depends On: 3`),
whose tester previously HALTed specifically pending this APPROVED status. No outstanding concerns
that would require revisiting Subtask 3 once Subtask 4's integration test and manual verification are
underway.

Subtask 3 Status: APPROVED. Advancing `current` to 4.

---

### Subtask 4 — End-to-end integration test and manual visual verification

**Status**: APPROVED

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
`tests/test_sidebar_broker_integration.py` (new) — re-run by the tester now that Subtasks 1-3 are
`APPROVED` (the earlier halt above no longer applies). No mocking of `LocalizerBroker`,
`core.localizer_frames`, or `LocalizerStore` — only `streamlit` (`st`) is a `MagicMock`, matching
`tests/test_sidebar.py`'s convention. Seeds a real `tmp_path`-scoped DuckDB store via
`LocalizerStore.upsert_events`/`upsert_places`, reusing `_seed_events`/`_seed_places` imported
directly from `tests/test_localizer_broker.py`. `TestSidebarBrokerIntegration`, 3 tests:
- `test_df_populated_with_seeded_event_values` — seeds 2 `lastfm` events + 2 `google_timeline`
  places, calls the real `render_sidebar()`, asserts `session_state["df"]` has exactly 2 rows,
  contains `"Artist0"`/`"Artist1"` in `artist` and `"Track0"`/`"Track1"` in `track`, non-null
  `lat`/`lng` on every row.
- `test_swarm_df_populated_with_seeded_place_values` — asserts `session_state["swarm_df"]` has
  exactly 2 rows, `"Place0"`/`"Place1"` in `city`, and the exact seeded `(51.5074, -0.1278)`
  lat/lng pair for Place0 survives the broker → adapter → session_state round-trip.
- `test_date_text_is_genuine_usable_datetime64_column` — asserts `df["date_text"].dtype.kind ==
  "M"` and that `.dt.date` (the exact operation `render_sidebar()`'s own date-filter widget
  performs) works without raising.

**Outcome — not a RED state**: all 3 tests passed immediately on first run against the real
Subtask 1-3 implementations (no code changes needed to make them pass); `ruff check` on the new
file is clean. Per the tester's report, assertions were not weakened to force a failure — this
demonstrates the real composition (`get_events_frame`/`get_places_frame` → adapters →
`apply_swarm_offsets` → session_state) is correct end-to-end, and the test file now serves as a
regression guard rather than a RED-then-GREEN test. Status set directly to `GREEN` (skipping RED)
to reflect this. The coder's remaining job for this subtask is the **manual verification**
acceptance criteria (visual check of the running app, flythrough graceful-degradation check),
the module-docstring update called out in Test Guidance, and a final full-suite regression run —
none of which are covered by the automated test file above.

**Implementation Notes**:

**Store state**: `~/.localizer/store.duckdb` was already populated on this dev machine — no
`localizer sync`/`localizer fetch` needed. Confirmed via
`LocalizerStore.default_path()` → `C:\Users\johns\.localizer\store.duckdb`, `.exists()` → `True`.
Row counts confirmed directly against the store: `query_places(source_id="google_timeline")` →
3,076 rows (matches the task description exactly); `LocalizerBroker().get_places_frame()` → 10,905
rows total (7,829 `swarm` + 3,076 `google_timeline`); `LocalizerBroker().get_events_frame()` →
290,392 rows, all `source_id="lastfm"`. Also re-confirmed the editable-install fix from Subtask 3
is still intact in this session: `import localizer` resolves to
`.../agent-adb530a22a6adcac5/packages/localizer/src/localizer` (this worktree), not the main
checkout.

**The `>=1 lastfm event` question, resolved**: this store has 290,392 real `lastfm` events, so
`_raw_df`/`df` populate normally through `apply_swarm_offsets` — the zero-lastfm-events
degradation scenario flagged in the task prompt does not apply on this machine. Ran the adapter
pipeline directly (`get_events_frame` → `events_to_lastfm_frame`, `get_places_frame` →
`places_to_swarm_frame`, then `apply_swarm_offsets`) outside of Streamlit to get a value-level
fix on what the map actually plots: `raw_df` has 290,392 rows and 3,548 unique `(lat, lng)` pairs;
1,421 of those unique pairs come from `google_timeline` places; **838 of the unique points that
actually appear in `raw_df` (the scrobble-map data) are `google_timeline`-sourced points** — i.e.
Google Timeline data measurably changes what renders on the map, not just what's nominally in the
store.

**Which page(s) I checked, and why**: investigated both candidates named in the task.
`pages/geo_explorer.py::render_geo_explorer()` reads **both** `df` (`music_df`, scrobbles) and
`swarm_df` (`has_swarm` gate) and plots both as layers — this is the primary "map" page and the
one the task's own Acceptance Criteria point at. `pages/places.py::render_checkin_insights()`
("Check-in Insights" in the nav — labeled "Places" in code comments but not in the UI) reads
`swarm_df` directly and is the more direct consumer of adapted `google_timeline` place data,
since `google_timeline` never appears in `df`/events at all (it's places-only, no lastfm overlap
by source). Checked both:
- **Geo Explorer, 2D Map view** (default): "Listening locations" scrobble map rendered with
  13,168 locations, 77,886 total plays, Top City "Laurel, MD (APL)". Both `Scrobbles` and
  `Check-ins` data-layer pills were active by default in the Filter popover (`available_layers`
  includes `"Check-ins"` since `has_swarm` is true).
- **Geo Explorer, 3D Globe view**: stat row showed "Scrobble Locations: 4,972", "Total Scrobbles
  (mapped): 290,392" (exact match to the `raw_df` row count computed independently above), and
  **"Check-in Locations: 8,806"** — a real, non-zero count of place markers rendered, sourced from
  `swarm_df` (which is `swarm` + `google_timeline` combined).
- **Check-in Insights page** (reads `swarm_df` only, no scrobble data at all): "Check-ins across 1
  countries" showed **10,905** — an exact match to `get_places_frame()`'s total unfiltered row
  count (7,829 swarm + 3,076 google_timeline). The "Top 20 cities" bar chart's top two entries
  were **"In passenger vehicle"** and **"Home"** — these are literally Google Timeline's
  `place_type`/`place_name` activity labels (e.g. `activity:in_passenger_vehicle`, `home`) flowing
  through `places_to_swarm_frame()`'s `place_name→city` rename and appearing as top-ranked "cities"
  on a real rendered page. This is unambiguous, page-level, non-synthetic proof that Google
  Timeline data specifically (not just Swarm) is present and visible on rendered UI — and it's a
  live instance of Task Overview decision 1's already-accepted limitation (activity labels are not
  administrative city names), observed for real rather than just reasoned about.

**View mode used**: both 2D Map and 3D Globe were checked (see above); 2D Map is the default. Both
render check-in/place data alongside scrobbles. Points genuinely appeared in both.

**How I drove the app**: `chromium-cli` was not available in this environment (`which chromium-cli`
found nothing). This repo already depends on `playwright` (used by `record_flythrough.py` itself,
declared in `pyproject.toml`) and had Chromium already installed for it, so I used Playwright
directly — a first-party tool already in this project's dependency tree, not a new one — to drive
a real headless Chromium session against `streamlit run visualize.py --server.headless true
--server.port 8501`, navigate the actual page-nav links, click the actual segmented-control/filter
widgets, and take full-page screenshots at each step. `console` "error"-type messages and
`pageerror` events were captured for the whole session. This was genuine browser-level visual
verification, not a Python-level session_state inspection substitute (though I also did the
latter, independently, to get exact adapter-level numbers — see above). The one-off driver script
and all screenshots were deleted after use; they were not committed (`git status --short` after
cleanup shows only the expected source/test files, confirmed clean).

**Console errors observed (pre-existing, unrelated to this plan)**: switching to the 3D Globe view
logged two `deck: loading data of GeoJsonLayer(...)` console errors — `Unexpected token '<' ...
SyntaxError: is not valid JSON` — consistent with a country/state boundary GeoJSON fetch getting an
HTML (likely 404) response back instead of JSON in this environment. This is unrelated to
`google_timeline`/broker-mode data (it's an overlay-boundary asset fetch, not scrobble/check-in
data) and did not prevent the scrobble/check-in layers themselves from rendering with correct
counts — flagging for awareness, not treating as a Subtask 4 blocker since it's outside this plan's
files-to-touch and pre-dates this work.

**Flythrough graceful-degradation check — result differs from the plan's prediction, in a way
worth flagging but not blocking on**: clicked "▶ Record Flythrough" on the Geo Explorer 3D Globe
view in the same broker-mode session (no legacy CSV/Swarm/Timeline paths configured).
**The app did not crash** — confirmed the page remained fully interactive and responsive
immediately after the click (all controls still clickable, no Python traceback, no blank/500
page). However, the *specific* degradation differs from what Task Overview's documented limitation
predicted: instead of `rec_status.update(label="Recording failed...", state="error")`, the widget
showed **"Recording saved to: flythrough_<timestamp>.mp4"** (a false-positive success message) —
and no such file was actually created on disk (`ls` confirmed). Root cause, traced by reading
`record_flythrough.py`: `geo_explorer.py` passes `csv_path=""` (falsy) in broker mode, so
`cmd` omits the positional csv argument entirely; `record_flythrough.py`'s own `main()` has a
**pre-existing, independent fallback**: when no csv is given, `create_recording_assets()` searches
`os.getenv("AUTOBIO_LASTFM_DATA_DIR", "data")` for a `*_tracks.csv` file (this worktree's `data/`
dir has none — only `.gitkeep`), and when neither the file nor the fallback dir/file exists, it
returns `(None, None)`. `main()`'s handling of that result — `if result is None: return` (never
true, since `(None, None)` is a 2-tuple, not `None`) then `deck, keyframes = result; if not deck:
return` — exits with return code 0 and prints nothing, so the subprocess's exit code alone (which
`geo_explorer.py` uses to decide success vs failure) reports success even though nothing was
recorded. **This is a pre-existing bug in `record_flythrough.py`'s `main()`, not something
introduced by Subtasks 1-4** — it would reproduce identically today on `main` in the legacy path
too, any time `create_recording_assets()` returns `(None, None)` for *any* reason (missing CSV,
empty data dir, etc.), independent of broker mode. It is also explicitly out of this plan's scope
per Task Overview ("Files never touched by this plan" lists `record_flythrough.py`). Net: the
*required* acceptance criterion — the app does not crash — is satisfied; the *literal wording*
about "an error is shown" is not, because the real failure mode is a silent false-positive success
message rather than a visible error. Not fixing this (out of scope, pre-existing, no crash), but
flagging clearly per instructions rather than silently treating the AC as fully met: **recommend a
follow-up issue against `record_flythrough.py`'s `main()` to check `os.path.exists(args.output)`
before reporting success, independent of this plan.**

**Full-suite regression run**: `pytest --no-cov -q` (plain pytest collected normally — the
documented `rtk proxy` fallback for "No tests collected" was not needed) — **865 passed, 0
failed** (862 pre-existing + 3 new `TestSidebarBrokerIntegration` tests from this subtask, already
GREEN per the tester's report — no regressions from the manual-verification work, which touched no
source files, only a one-off script deleted before this run).

No source files were modified for this subtask beyond what Subtasks 1-3 already delivered — the
work here was verification only (per the Description's split: automated integration test already
GREEN from the tester; this pass covered the remaining manual/non-automatable acceptance criteria).
`components/sidebar.py`'s module docstring (Test Guidance's documentation-upkeep item) was already
updated during Subtask 3 (verified: the "Broker mode" section and `_loaded_store_identity` session-
state contract entry are both present at lines 1-45) — no further edit needed here.

Status left at `GREEN` (not flipped to `APPROVED` — that's the owner's call) since no bug was found
in the code delivered by this plan; the one real finding (record_flythrough.py's silent
false-success) is a pre-existing, out-of-scope issue, not a defect in Subtasks 1-4's deliverable.

**Review Notes**:
Code Review: APPROVED — full unscoped gate re-run from a clean venv activation: `ruff check .` —
no issues found; `ruff format --check .` — 132 files already formatted; `mypy` (unscoped) —
Success, no issues found; `pytest tests/test_sidebar_broker_integration.py -v --no-cov` — 3
passed, 0 failed; full suite `rtk proxy python -m pytest --no-cov -q` — 865 passed, 0 failed (the
plain `pytest` invocation hit the documented "No tests collected" rtk-hook quirk, so the `rtk
proxy` fallback was used, matching the coder's own note that this fallback exists for that reason).

Read `tests/test_sidebar_broker_integration.py` in full and cross-checked its assertions against
`tests/test_localizer_broker.py`'s `_seed_events`/`_seed_places` helpers: `_seed_events` produces
`label="Artist{i}"`/`sublabel="Track{i}"`, and `_seed_places` produces `place_name="Place{i}"` with
`lat=51.5074 + i*0.01`/`lng=-0.1278 + i*0.01` — so Place0 is exactly `(51.5074, -0.1278)`, the
literal pair the test asserts appears in `swarm_df[["lat", "lng"]]`. All three tests assert
specific values (`"Artist0"`/`"Artist1"` in `artist`, `"Track0"`/`"Track1"` in `track`, the exact
`(51.5074, -0.1278)` tuple, `date_text.dtype.kind == "M"` plus a working `.dt.date` call) rather
than shape/presence checks — satisfies Subtask 4's Test Guidance directive to assert on values, not
just column existence.

Independently re-derived the row-count claims in Implementation Notes against the real
`~/.localizer/store.duckdb` rather than trusting them: ran
`LocalizerBroker().get_places_frame()`/`get_events_frame()` directly — got `places` = 10,905 total
(7,829 `swarm` + 3,076 `google_timeline`) and `events` = 290,392 (all `lastfm`), an exact match to
every number cited in Implementation Notes (the "10,905"/"7,829 swarm + 3,076 google_timeline" page
count on Check-in Insights, the "290,392" scrobble count on the 3D Globe stat row, and the task's
own "3,076 google_timeline rows" premise). The numbers are internally consistent and independently
reproducible, not fabricated or misremembered.

**Flythrough finding, scrutinized**: read `record_flythrough.py` in full. Confirmed the root-cause
diagnosis is accurate: `main()`'s `result = create_recording_assets(...)` can return the 2-tuple
`(None, None)` (lines 213/215/226/243 of `create_recording_assets`), so `if result is None: return`
(line 455) never fires for that case; `deck, keyframes = result` unpacks to `(None, None)`, and
`if not deck: return` (line 458) exits silently with code 0 and no printed output — meaning
`pages/geo_explorer.py`'s `if proc.returncode == 0: rec_status.update(label=f"Recording saved to:
{out_path}", state="complete")` (geo_explorer.py:503-504) reports false success. Confirmed via
`git diff 8e9b1b5 -- record_flythrough.py` → empty diff: this file has zero changes on this branch,
so the bug is not introduced by Subtasks 1-4. Confirmed `csv_path=""` in broker mode is itself
expected, documented behavior — `geo_explorer.py:468`, `csv_path = loaded_config[0] if
loaded_config else None`, and Task Overview's own "Explicit out-of-scope limitation" paragraph
states index 0 is deliberately set to `""` in broker mode. The bug is a pure result-unpacking defect
inside `main()` that reproduces identically in legacy mode any time `create_recording_assets()`
returns `(None, None)` for any reason (e.g. a `data/` dir with no `*_tracks.csv`, independent of
broker mode) — confirmed by reading `create_recording_assets()`'s four `return None, None` sites,
none of which are broker-mode-specific. Root-cause diagnosis and pre-existing/out-of-scope framing
both hold up under independent re-derivation.

**Severity assessment**: the required acceptance criterion — "does not crash the Streamlit app" —
is genuinely satisfied (confirmed via the coder's Playwright-driven check and the code reading
above: the exception never propagates past `main()`, so the subprocess just exits 0 with no
output). The *literal wording* of "an error is shown" is not satisfied — the real behavior is a
misleading false-positive success message. This is a legitimate UX bug (a user could believe a
video was saved when it wasn't) that is one severity notch worse than the plan's original
prediction, but it does not rise to a defect in Subtask 4's own deliverables: the automated test
file's claims are accurate, and Implementation Notes describe the actual observed behavior
precisely rather than glossing over the mismatch with the plan's prediction. Recommend the
orchestrator/owner have a follow-up GitHub issue filed against `record_flythrough.py::main()`
(check `os.path.exists(args.output)`, or equivalently treat a `(None, None)` result as a nonzero
exit code, before reporting success) — this is a judgment call for the orchestrator/owner, not a
blocker on Subtask 4.

No defects found in Subtask 4's own deliverables (test file or Implementation Notes claims).
Status remains GREEN; owner may advance.

**Owner Review**: APPROVED. The deliverable genuinely satisfies the user's original ask: independent
browser-driven verification (Playwright) against the real populated store confirms Google Timeline
data renders on live pages, with exact row-count cross-checks against the live DuckDB store and
unambiguous evidence (Google Timeline's own activity labels appearing on-screen). Gate is clean
(865/865). The record_flythrough.py false-success finding is accepted as a pre-existing,
out-of-scope bug (confirmed via `git diff` showing zero changes to that file on this branch, and
Task Overview explicitly lists it as never touched by this plan) — shipping with a documented
follow-up recommendation rather than blocking on it, since the plan's actual scope (wiring
LocalizerBroker into the app) is fully and correctly delivered. Recommend the orchestrator open a
follow-up GitHub issue against `record_flythrough.py::main()`'s silent-false-success bug after this
plan's PR is merged.

**Plan-wide loose ends for the orchestrator's final commit/PR step**: PR #113 already merged
Subtasks 1-2 (`localizer-broker-frame-adapters` PR group). Subtasks 3-4 (`wire-localizer-broker-into-app`
PR group) are both now APPROVED but not yet committed or PR'd — `components/sidebar.py`,
`tests/test_sidebar.py`, `tests/test_visualize.py`, and the new `tests/test_sidebar_broker_integration.py`
are all still uncommitted in the worktree. All 4 subtasks across both PR groups are now APPROVED;
`Plan Status` is being set to `COMPLETE` below. Next step: full-suite integration gate (already
confirmed 865/865 clean), commit this second PR group, open its PR, and spawn the polisher.

Status: APPROVED. Plan Status: COMPLETE.

---
