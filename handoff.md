# Handoff

## Plan Status
status: IN_PROGRESS

## Task Overview

**The problem**: `~/.localizer/store.duckdb`'s `places` table has a `source_id` column
distinguishing `swarm` (Foursquare/Swarm check-ins, 7,829 rows) from `google_timeline` (Google
Maps Timeline, 3,076 rows) — but `core/localizer_frames.py::places_to_swarm_frame()` drops
`source_id` when adapting the broker's raw places frame into the legacy `swarm_df` shape used
throughout the app. The legacy flat-file loading path (`components/sidebar.py`) has the same gap:
it concatenates Swarm and Google Timeline rows with no source tag at all. Once data reaches
`swarm_df`, there is no way to tell which source a given point came from, and no UI lets the user
isolate one. Google Timeline rows currently populate `venue`/`city` with activity-segment labels
(`home`, `work`, `activity:in_bus`, etc.) rather than real venue categories, so the two sources look
visibly different today, but there is no filter control.

**The fix**, four parts:

1. **Preserve `source_id` through the broker (DuckDB) pipeline** — extend `SWARM_COLUMNS` in
   `core/localizer_frames.py` and stop dropping `source_id` in `places_to_swarm_frame()`
   (Subtask 1).
2. **Preserve `source_id` through the legacy flat-file pipeline** — tag rows with `"swarm"` /
   `"google_timeline"` at the point `components/sidebar.py::_load_data_with_progress()` calls
   `load_swarm_data()` / `load_google_timeline()`, immediately before the existing
   `pd.concat()` (Subtask 2).
3. **A shared, pure, Streamlit-free filtering helper** (`core/source_filter.py`) that computes
   selectbox options from whatever `source_id` values are present (or gracefully falls back to a
   single `"All"` option when the column is absent or empty) and filters a `swarm_df` by a chosen
   label. This mirrors `core/localizer_frames.py`'s existing pure-adapter convention and avoids
   duplicating source→label mapping logic across the two consuming pages (Subtask 3).
4. **Wire a `st.selectbox("Source", …)` widget into `pages/geo_explorer.py`** (inside the existing
   "⚡ Filter" popover, alongside the Artist selectbox) and **into `pages/places.py`'s
   `render_checkin_insights()`** (the "Check-in Insights" page — confirmed via `visualize.py` line
   163, which registers `render_checkin_insights` under the page title "Check-in Insights"),
   filtering `swarm_df` before it reaches map plotting, aggregation, or the shareable HTML export
   in both pages (Subtasks 4 and 5).

**Design decisions**:

- **Widget choice — `st.selectbox`, not `st.radio`.** `tests/test_geo_explorer.py` has several
  tests with exact-length `mock_radio.side_effect` lists (e.g. `test_table_view_dispatches` expects
  exactly two `st.radio` calls: "By Artist"/"By City" then "Sort by"). An unconditional third radio
  call would exhaust those lists and break passing tests. A selectbox mirrors the existing "Artist"
  selectbox pattern and, gated behind `has_swarm`, never executes in any currently-passing test —
  every existing test in `test_geo_explorer.py` passes `swarm_df: None`.
- **Label wording is a judgment call, resolved as**: `"All"`, `"Swarm"`, `"Google Timeline"` — a
  `SOURCE_LABELS` dict in `core/source_filter.py` maps known `source_id` values to these labels,
  falling back to `source_id.replace("_", " ").title()` for any future/unknown source so the
  filter never crashes on new plugins.
- **Legacy-path parity is in scope.** Both `load_swarm_data()` and `load_google_timeline()` are
  called as two separate steps in `_load_data_with_progress()` immediately before the existing
  `pd.concat()` — tagging `source_id` there is a small, additive change requiring no modification
  to `analysis_utils.py` itself (both loader functions stay untouched and reusable elsewhere).
- **`apply_swarm_offsets()` is unaffected.** Read in full (`analysis_utils.py` lines 538+): it only
  reads `swarm_df["timestamp"/"offset"/"city"/"state"/"country"/"lat"/"lng"]` via positional
  `.values` indexing — it never iterates over "all columns," so adding `source_id` to the frame it
  receives is safe and was verified by reading the function, not assumed.
- **Filter placement**: the filter must apply to `swarm_df` before any consumption — map plotting,
  groupby aggregation, and the shareable HTML export alike — so all downstream views/exports agree
  on what's currently selected. In both pages, the filter is applied once, immediately after
  reading `swarm_df` from session state (mirroring how `geo_explorer.py` already filters `music_df`
  once, right after its own popover, before view dispatch).

**Explicit out-of-scope pages (documented so they aren't re-litigated later)**: `pages/data_sources.py`
(the config/loader page — not a display consumer), `pages/overview.py`, `pages/life_in_chapters.py`,
`pages/listening_lifestyle.py`, and `pages/insights.py` all read `swarm_df`, but only for derived
analytics (residency inference, venue-pattern scoring, chapter maps, transit-day computation,
AI-generated narrative text) rather than the direct map/breakdown display this task targets. The
task's own framing ("at minimum" Geo Explorer and Check-in Insights) permits but does not require
expanding scope to these; keeping the diff focused on the two named pages avoids scope creep. A
reasonable follow-up would extend the same `core/source_filter.py` helper to these pages later.

**Files never touched by this plan**: `analysis_utils.py` (both `load_swarm_data()` and the
localizer-side `load_google_timeline()` parser stay byte-for-byte unchanged — tagging happens at
the call site in `sidebar.py`, not inside the loaders), `core/broker.py` (its `get_places_frame()`
already returns `source_id` — confirmed by reading Subtask 1 of the prior `handoff.md`, now
`Plan Status: COMPLETE`), `record_flythrough.py`.

**Architecture context**: no prior `/feature-dev` or `/plan-feature` run occurred for this task. The
user supplied a fully diagnosed problem statement and asked for investigation-driven planning. All
findings above were verified by reading `core/localizer_frames.py`, `components/sidebar.py`,
`analysis_utils.py` (`load_swarm_data`, `apply_swarm_offsets`), `pages/geo_explorer.py`,
`pages/places.py`, `visualize.py`, and the existing test files (`tests/test_localizer_frames.py`,
`tests/test_sidebar.py`, `tests/test_geo_explorer.py`) in full — not inferred from names alone.

Plan Review: APPROVED — Four-part fix to preserve `source_id` through both the broker and legacy
data pipelines and expose a shared, pure source filter in Geo Explorer and Check-in Insights,
implemented via 5 falsifiable, dependency-ordered, file-disjoint subtasks (2 independent
pipeline-tagging subtasks, a shared pure helper, and two consuming-page wiring subtasks that both
depend on the helper).

Re-review after revision: Subtask 4's Description, AC #1, and AC #5 were rewritten by the planner to
fix the two defects flagged in the prior review round, and both fixes were verified directly against
`pages/geo_explorer.py` rather than trusting the planner's self-report:
- AC #1 now correctly attributes the check-in groupby variable named `ci` to `_render_2d_map` (lines
  562-576, confirmed by reading the file) and `checkin_geo` to the separate `_render_3d_globe`
  function (lines 275-284, confirmed). The "By City" mode only relabels `city` → `"Check-ins"`
  (line 573) without changing which rows are included, matching AC #1's claim that filtering is
  identical across "By Artist"/"By City" modes.
- AC #5 was rewritten from the factually-wrong claim about a swarm-driven "By City" breakdown table
  into a regression guard: `_build_city_stats()`/`_render_city_breakdown()`/`_render_atlas_city_detail()`
  (lines 793-1037) must remain untouched and `music_df`-only. Verified by grepping every `swarm_df`
  reference in the file (lines 262, 280, 517, 563, 1063-1227) — none fall inside that line range —
  and by reading `_build_city_stats(df)`'s docstring/signature directly, which requires
  `city`/`country`/`lat`/`lng`/`artist`/`track` (scrobble-only fields absent from `swarm_df`).
- The filter-placement description (apply `filter_by_source()` right after `music_df`'s existing
  date/artist filtering, lines 1191-1199, before the Share button section at line 1201) and the
  `has_swarm`-gating pattern (mirroring the existing `has_music`-gated Artist selectbox, lines
  1106-1128) were both confirmed against the live code.

Nothing else regressed: DAG edges (4→3, 5→3) remain acyclic and `current: 1,2,3,4,5` is still a
valid topological order; all 5 subtasks still carry ≥2 falsifiable ACs and Test Guidance; file and
test-file disjointness across the batch is unchanged (`core/localizer_frames.py`+
`tests/test_localizer_frames.py`, `components/sidebar.py`+`tests/test_sidebar.py`,
`core/source_filter.py`+`tests/test_source_filter.py`, `pages/geo_explorer.py`+
`tests/test_geo_explorer.py`, `pages/places.py`+`tests/test_places.py` all touch disjoint files).
Subtasks 1, 2, 3, and 5 were untouched by this revision and remain accurate per the prior review
round. The out-of-scope rationale (excluding overview.py, life_in_chapters.py,
listening_lifestyle.py, insights.py, data_sources.py) still holds. Plan is ready to proceed.

## Current Subtask
current: 3

---

## Subtasks

### Subtask 1 — Preserve `source_id` through the broker column-shape adapter

**Status**: APPROVED

**PR Group**: preserve-source-id

**Depends On**: none

**Description**:
Modify `core/localizer_frames.py::places_to_swarm_frame()` so `source_id` survives the adapter
from the broker's generic places schema into the legacy `swarm_df` shape, instead of being dropped.
Add `source_id` to the `SWARM_COLUMNS` module-level constant (at the end, mirroring
`LASTFM_COLUMNS`'s existing `source_id`-last convention) and pass it through unchanged in the
non-empty path. Update the function's docstring, which currently states `source_id` is dropped, to
reflect the new behavior. The existing test suite (`tests/test_localizer_frames.py`) has assertions
that explicitly check `source_id` is **absent** — these must be inverted to check it is present and
correct, not merely relaxed, since a silently-wrong inversion would reintroduce exactly the "silent
breakage" risk this module's own docstring warns about.

**Acceptance Criteria**:
- [ ] `places_to_swarm_frame()` on a 3-row input with mixed `source_id` values (`"swarm"`,
  `"google_timeline"`, `"swarm"`) produces an output where each row's `source_id` matches its input
  row's `source_id` **after** the timestamp-based sort reorders rows (i.e. verified row-for-row
  post-sort, not just "the values exist somewhere").
- [ ] `list(places_to_swarm_frame(df).columns) == SWARM_COLUMNS` where `SWARM_COLUMNS` now ends
  with `"source_id"` — both for a non-empty and an empty input.
- [ ] `place_name` and `place_type` remain absent from the output (unchanged from today) — only
  `source_id`'s drop behavior changes, nothing else.
- [ ] `events_to_lastfm_frame()` is untouched and its existing tests pass with zero modification
  (it already preserves `source_id`; this subtask must not touch it).
- [ ] `core/localizer_frames.py` still contains no `streamlit`, `duckdb`, or `localizer.store.db`
  substrings (the existing `test_localizer_frames_module_has_no_forbidden_imports` source-inspection
  test must keep passing unmodified).

**Files to Touch**:
- `core/localizer_frames.py` (edit: add `"source_id"` to `SWARM_COLUMNS`; stop excluding it in
  `places_to_swarm_frame()`'s result construction; update docstring)
- `tests/test_localizer_frames.py` (edit: update the module-level `SWARM_COLUMNS` test fixture list
  to include `"source_id"`; invert `test_places_to_swarm_frame_renames_and_fills_defaults`'s
  `assert "source_id" not in result.columns` into a row-level correctness assertion; update
  `test_places_to_swarm_frame_empty_input_exact_columns`'s expected column list; update
  `test_places_to_swarm_frame_sorted_ascending_by_timestamp`'s and `..._single_row`'s assertions to
  also check `source_id` survives the sort correctly)

**Test Guidance**:
- This is the riskiest subtask in the plan (per the module's own docstring: "a wrong column rename
  or a silently-swapped assignment would not raise any exception anywhere downstream"). Assert on
  actual `source_id` values at specific row indices after sorting, not on set membership alone.
- Cover: 3-row mixed-source input (existing `_places_fixture_out_of_order()` fixture already has
  mixed `source_id` values — reuse it rather than building a new fixture), single-row input,
  empty input (exact column list, in order, including `source_id` at the end), and a fixture where
  every row shares the same `source_id` (proving the passthrough doesn't accidentally collapse or
  dedupe by source).
- Explicitly re-assert that `place_name`/`place_type` are still dropped — this subtask changes only
  `source_id`'s fate, and a test should catch a coder accidentally also passing through `place_name`.
- Do not weaken the existing forbidden-imports source-inspection test; it must keep passing as-is.

**Test Files**:
`tests/test_localizer_frames.py` — RED-confirmed (`python -m pytest tests/test_localizer_frames.py -v`: 5 failed / 8 passed; failures are `KeyError: 'source_id'`/column-set mismatches, the correct pre-implementation failure mode).
- `test_places_to_swarm_frame_renames_and_fills_defaults` (inverted from "absent" to row-level post-sort correctness)
- `test_places_to_swarm_frame_sorted_ascending_by_timestamp` (added source_id-survives-sort assertions)
- `test_places_to_swarm_frame_single_row` (added source_id assertion)
- `test_places_to_swarm_frame_empty_input_exact_columns` (exercises updated `SWARM_COLUMNS` fixture)
- `test_places_to_swarm_frame_same_source_id_not_collapsed` (new — proves passthrough doesn't dedupe by source)

**Revision (NEEDS_REVISION cycle, owner finding on AC #2)**: tightened
`test_places_to_swarm_frame_renames_and_fills_defaults` (line 178) from
`assert set(result.columns) == set(SWARM_COLUMNS)` to
`assert list(result.columns) == SWARM_COLUMNS`, matching the exact-order check
AC #2 requires for the non-empty-input path (the empty-input counterpart,
`test_places_to_swarm_frame_empty_input_exact_columns`, already asserted exact
order and was untouched). No implementation edit was made — the owner's finding
noted the current implementation's unconditional `result[SWARM_COLUMNS]`
re-index already satisfies exact order; this was a test-strength gap only.
Confirmed the tightened assertion passes against the current (unchanged)
implementation: `python -m pytest tests/test_localizer_frames.py -v --no-cov`
— 13 passed, 0 failed (including
`test_places_to_swarm_frame_renames_and_fills_defaults` individually, 1 passed).

**Implementation Notes**:
Added `"source_id"` as the last entry in the module-level `SWARM_COLUMNS` constant and
added `"source_id": places_df["source_id"]` as the last key in the dict passed to
`pd.DataFrame(...)` inside `places_to_swarm_frame()`, so it passes through unchanged
(no rename, no default-fill) exactly like the pre-existing `lat`/`lng` passthrough
columns. Updated the function's docstring to state `source_id` is preserved instead of
dropped, and to list it as the final column in the returned shape. `place_name` and
`place_type` remain dropped — only `source_id`'s fate changed, matching AC #3.

The test file (`tests/test_localizer_frames.py`) was already written by the tester
agent in the RED phase with `SWARM_COLUMNS` (test-local copy) ending in `"source_id"`
and with inverted/augmented assertions checking `source_id` presence and row-for-row
correctness post-sort; no test-file edits were needed or made in this GREEN phase.

Ran `python -m pytest tests/test_localizer_frames.py -v`: 13 passed, 0 failed.
Ran `ruff check core/localizer_frames.py`: no issues found.
Ran `ruff format --check core/localizer_frames.py`: already formatted, no changes needed.

No deviations from the plan; no files touched beyond `core/localizer_frames.py` (the
`Files to Touch` list's test-file edits were already done by the tester, so only the
source file required a coder edit).

**Post-revision confirmation (second GREEN pass)**: Re-verified the owner's NEEDS_REVISION
finding. The tester already tightened
`test_places_to_swarm_frame_renames_and_fills_defaults` (line 178,
`tests/test_localizer_frames.py`) from `assert set(result.columns) ==
set(SWARM_COLUMNS)` to `assert list(result.columns) == SWARM_COLUMNS`, closing the
exact-order gap the owner flagged for the non-empty-input path. Confirmed via
`Grep` that line 178 (and the empty-input counterpart at line 286) both now use
the exact-list-order assertion. Ran `python -m pytest tests/test_localizer_frames.py
-v --no-cov`: 13 passed, 0 failed, exit code 0 — the tightened assertion passes
against the current, unmodified `core/localizer_frames.py` implementation (its
unconditional `result[SWARM_COLUMNS]` re-index at the end of
`places_to_swarm_frame()` already enforces column order deterministically). No
implementation change was required or made in this pass; only the test file was
touched, and it was touched by the tester agent, not this coder pass. Ran
`python -m ruff check core/localizer_frames.py tests/test_localizer_frames.py` —
all checks passed. Ran `python -m ruff format --check core/localizer_frames.py
tests/test_localizer_frames.py` — 2 files already formatted, no new lint/format
violations introduced.

**Review Notes**:
Code Review: APPROVED — checks clean

Automated checks (all run scoped to `tests/test_localizer_frames.py`, the current
subtask's only Test Files entry; no other subtask is yet GREEN/APPROVED):
- `python -m ruff check core/localizer_frames.py tests/test_localizer_frames.py` — All checks passed!
- `python -m ruff format --check core/localizer_frames.py tests/test_localizer_frames.py` — 2 files already formatted
- `python -m mypy core/localizer_frames.py` — no issues found (this file is in `[tool.mypy] files`)
- `python -m pytest tests/test_localizer_frames.py -v` — 13 passed, 0 failed

Diff review (`git diff HEAD -- core/localizer_frames.py`, +9/-5, only touches
`SWARM_COLUMNS`, the docstring, and the one new dict key): matches the plan exactly —
`"source_id"` appended to `SWARM_COLUMNS`, `"source_id": places_df["source_id"]` added
as the final key in the `pd.DataFrame(...)` construction (straight passthrough, no
rename/default-fill, consistent with the existing `lat`/`lng` passthrough style), and
the docstring updated to describe preservation instead of dropping. No dead code, no
commented-out blocks, no secrets/tokens, no N+1 or hot-path synchronous-call concerns
(pure in-memory DataFrame construction). `events_to_lastfm_frame()` is untouched, and
`place_name`/`place_type` remain excluded from the result dict — matching AC #3 and
AC #4.

All 5 Acceptance Criteria verified:
- AC #1 (row-for-row post-sort `source_id` correctness) — covered by
  `test_places_to_swarm_frame_renames_and_fills_defaults` and
  `test_places_to_swarm_frame_sorted_ascending_by_timestamp`, both passing.
- AC #2 (`list(...columns) == SWARM_COLUMNS`, source_id last, non-empty + empty) — the
  empty-input case is checked with an exact `list(...)` equality
  (`test_places_to_swarm_frame_empty_input_exact_columns`); the non-empty case
  (`test_places_to_swarm_frame_renames_and_fills_defaults`) only asserts `set(...) ==
  set(SWARM_COLUMNS)`, not list order. This is a minor test-coverage gap against the AC's
  literal wording, but not a functional defect: the implementation's final line always
  does `result[SWARM_COLUMNS]` bracket-indexing, which deterministically enforces column
  order on every call regardless of input, so the order guarantee holds even though no
  non-empty test asserts it directly. Not blocking — noting for the owner's awareness.
- AC #3 (`place_name`/`place_type` still absent) — explicit assertions present and passing.
- AC #4 (`events_to_lastfm_frame` untouched) — confirmed via `git diff` (zero lines
  changed in that function) and its 5 existing tests passing unmodified.
- AC #5 (forbidden-imports source-inspection test) — `test_localizer_frames_module_has_no_forbidden_imports`
  passing.

No issues found that require reversal to RED.

Owner Review: NEEDS_REVISION — implementation is correct and the code-mode review above
stands; this is a test-coverage-only gap the code reviewer flagged but left as
non-blocking. On independent review I'm sending it back because it's a real (if narrow)
hole, not merely cosmetic:

- **Finding**: `test_places_to_swarm_frame_renames_and_fills_defaults`
  (`tests/test_localizer_frames.py` line 178) asserts
  `set(result.columns) == set(SWARM_COLUMNS)`, which does not verify AC #2's literal
  requirement — `list(places_to_swarm_frame(df).columns) == SWARM_COLUMNS` — for the
  **non-empty**-input path. `test_places_to_swarm_frame_empty_input_exact_columns`
  already does the exact-list check, but only for the empty-input branch
  (`pd.DataFrame(columns=SWARM_COLUMNS)`, a structurally separate code path from the
  non-empty branch's dict-construction-then-`[SWARM_COLUMNS]`-reindex). A future edit to
  the non-empty branch that reorders the dict literal and drops the trailing
  `[SWARM_COLUMNS]` re-index would silently break column order with zero test failure —
  exactly the "silent breakage" risk class this subtask's own docstring and Test
  Guidance call out ("assert ... not on set membership alone").
- **What correct looks like**: change line 178 to
  `assert list(result.columns) == SWARM_COLUMNS` (or add it alongside the existing set
  check) in `test_places_to_swarm_frame_renames_and_fills_defaults`. This is a test-only
  change — no implementation edit is required, since `core/localizer_frames.py` already
  satisfies it via the unconditional `[SWARM_COLUMNS]` re-index at the end of
  `places_to_swarm_frame()`.
- Everything else in this subtask (row-for-row `source_id` correctness post-sort,
  `place_name`/`place_type` still absent, `events_to_lastfm_frame` untouched, forbidden-imports
  test intact, ruff/format/pytest all clean) is verified and does not need to change.

Code Review: APPROVED (re-review) — Verified directly against the file on disk, not just
the notes above: `tests/test_localizer_frames.py` line 178 now reads
`assert list(result.columns) == SWARM_COLUMNS`, exactly closing the exact-order gap
raised in the finding above. No implementation edit was made or needed — the
unconditional `result[...][SWARM_COLUMNS]` re-index at the end of
`places_to_swarm_frame()` (`core/localizer_frames.py` line 96) already guarantees exact
column order on every call. Re-ran the scoped suite directly:
`python -m pytest tests/test_localizer_frames.py -v --no-cov` — 13 passed, 0 failed.
`python -m ruff check core/localizer_frames.py tests/test_localizer_frames.py` — all
checks passed. `python -m ruff format --check ...` — 2 files already formatted.
`python -m mypy core/localizer_frames.py` — no issues found. Confirmed all Test Guidance
items are present: mixed-source 3-row fixture, single-row, empty-input exact columns,
`test_places_to_swarm_frame_same_source_id_not_collapsed` (line 309, proves passthrough
doesn't dedupe by source), and `test_localizer_frames_module_has_no_forbidden_imports`
(line 324) all present and passing. All 5 Acceptance Criteria are satisfied with no
remaining gaps. Approved — advancing to Subtask 2.

---

### Subtask 2 — Preserve `source_id` through the legacy flat-file pipeline

**Status**: APPROVED

**PR Group**: preserve-source-id

**Depends On**: none

**Description**:
Modify `components/sidebar.py::_load_data_with_progress()` so the legacy (non-broker) loading path
also tags each row with its origin. Immediately after `load_swarm_data(swarm_dir)` returns a
non-empty frame, assign `swarm_df["source_id"] = "swarm"`. Immediately after
`load_google_timeline(timeline_path)` returns a non-empty frame, assign
`timeline_df["source_id"] = "google_timeline"`, before the existing `pd.concat()` call. Do not
modify `analysis_utils.py`'s `load_swarm_data()` or the localizer-side `load_google_timeline()`
parser — both stay exactly as they are; tagging happens only at this call site. When neither
source is configured, `swarm_df` remains the existing empty `pd.DataFrame()` with no `source_id`
column at all — this is an acceptable, already-handled edge case that Subtask 3's filter helper
must tolerate gracefully (not this subtask's concern to guard against).

**Acceptance Criteria**:
- [ ] With both `swarm_dir` and `timeline_path` configured, the resulting `swarm_df` in
  `st.session_state["swarm_df"]` has every Swarm-derived row's `source_id == "swarm"` and every
  Timeline-derived row's `source_id == "google_timeline"`, verified by cross-referencing specific
  `timestamp` values from each mocked loader's fixture (not just checking two distinct values
  exist).
- [ ] With only `swarm_dir` configured (no `timeline_path`), every resulting row has
  `source_id == "swarm"`.
- [ ] The existing `TestLoadDataCombination` tests (`test_timeline_rows_appended_to_swarm`,
  `test_combined_frame_sorted_by_timestamp`, `test_no_timeline_leaves_swarm_only`) continue to pass
  with their row-count and sort-order assertions unchanged — only augmented with `source_id`
  assertions, not altered in their existing checks.
- [ ] `load_swarm_data` and `load_google_timeline` are called with the exact same arguments as
  today (no signature change) — confirmed by the existing mocks (`patch.object(sidebar,
  "load_swarm_data", ...)`) requiring zero changes to their call sites' argument lists.

**Files to Touch**:
- `components/sidebar.py` (edit: `_load_data_with_progress()` — tag `source_id` on `swarm_df` and
  `timeline_df` before the concat; update module docstring's "Broker mode"/session-state contract
  section if it references `swarm_df`'s column shape)
- `tests/test_sidebar.py` (edit: extend `TestLoadDataCombination` with `source_id` assertions on
  the existing fixtures; add a case for swarm-only, keeping all existing assertions intact)

**Test Guidance**:
- Reuse the existing `self.swarm_df` / `self.timeline_df` fixtures in `TestLoadDataCombination`'s
  `setUp()` — do not rebuild new fixtures; add `source_id` assertions on top of the existing
  row-count/sort-order checks so the diff stays minimal and provably non-regressive.
- Cover: both sources present (mixed `source_id` values, verified per-row against known timestamps
  from each fixture), swarm-only (`timeline_path=""`, all rows `"swarm"`), and — as a documented
  edge case, not a new requirement — confirm that when neither source is configured the empty
  `pd.DataFrame()` path (already covered by other existing tests in this file) is untouched by this
  change.
- This is a plain column-tagging change with no branching complexity; a single focused test class
  extension is sufficient — no need for exhaustive combinatorial cases beyond what's listed above.

**Test Files**:
`tests/test_sidebar.py` — RED-confirmed (`pytest tests/test_sidebar.py -v`: 2 failed / 7 passed; failures are `AssertionError: 'source_id' not found in Index(...)`, the correct pre-implementation failure mode; all 7 pre-existing tests pass unmodified).
- `TestLoadDataCombination::test_source_id_tagged_per_row_when_both_sources_present` (cross-references known timestamps against `source_id`)
- `TestLoadDataCombination::test_source_id_all_swarm_when_only_swarm_dir_configured` (swarm-only case)
- AC #4 (loader call-argument stability) intentionally has no dedicated test — it's vacuously true pre-implementation since tagging doesn't touch call sites; verify by inspection at review time.

**Implementation Notes**:
In `components/sidebar.py::_load_data_with_progress()`, tagged `swarm_df["source_id"]
= "swarm"` immediately after `load_swarm_data(swarm_dir)` returns (guarded by the
existing `if not swarm_df.empty:` check, added inline), and tagged
`timeline_df["source_id"] = "google_timeline"` immediately after
`load_google_timeline(timeline_path)` returns non-empty, before the existing
`pd.concat()` call. Neither `load_swarm_data` nor `load_google_timeline` call sites'
arguments changed — tagging is a pure post-return DataFrame column assignment, so
`analysis_utils.py` was not touched at all, matching the plan.

Also added one clarifying sentence to the module docstring's session-state contract
(`swarm_df` entry) noting each row now carries a `source_id` of `"swarm"` or
`"google_timeline"`, since the docstring previously didn't describe the column shape
at all — a minor addition beyond the letter of "Files to Touch" but within its
explicit allowance to "update module docstring's ... session-state contract section
if it references swarm_df's column shape."

The two new tests in `tests/test_sidebar.py`
(`test_source_id_tagged_per_row_when_both_sources_present` and
`test_source_id_all_swarm_when_only_swarm_dir_configured`) were already written by
the tester agent in the RED phase; no test-file edits were made in this GREEN pass.

When neither source is configured, `swarm_df` stays the pre-existing empty
`pd.DataFrame()` with no `source_id` column — untouched by this change, as specified
(Subtask 3's filter helper is responsible for tolerating that case).

Ran `python -m pytest tests/test_sidebar.py -v --no-cov`: 9 passed, 0 failed (7
pre-existing + 2 new). Ran the scoped set including Subtask 1's GREEN/APPROVED tests:
`python -m pytest tests/test_sidebar.py tests/test_localizer_frames.py -v --no-cov`:
22 passed, 0 failed.
Ran `python -m ruff check components/sidebar.py tests/test_sidebar.py`: all checks
passed. Ran `python -m ruff format --check components/sidebar.py tests/test_sidebar.py`:
2 files already formatted, no changes needed. Ran `python -m mypy components/sidebar.py`:
no issues found.

No deviations from the plan; no files touched beyond `components/sidebar.py` (test-file
edits were already made by the tester in the RED phase).

**Review Notes**:
Code Review: APPROVED — checks clean

Automated checks (scoped to the current subtask's Test Files entry
(`tests/test_sidebar.py`) plus Subtask 1's GREEN/APPROVED `tests/test_localizer_frames.py`;
no other subtask is yet GREEN/APPROVED):
- `python -m ruff check components/sidebar.py tests/test_sidebar.py` — All checks passed!
- `python -m ruff format --check components/sidebar.py tests/test_sidebar.py` — 2 files already formatted
- `python -m mypy components/sidebar.py` — no issues found
- `python -m pytest tests/test_sidebar.py tests/test_localizer_frames.py -v --no-cov` — 22 passed, 0 failed

Diff review (`git diff -- components/sidebar.py`, +6/-1; `git diff -- tests/test_sidebar.py`,
+33/-0): matches the plan exactly. `components/sidebar.py`'s only functional change is two
guarded assignments — `swarm_df["source_id"] = "swarm"` right after `load_swarm_data()`
returns non-empty, and `timeline_df["source_id"] = "google_timeline"` right after
`load_google_timeline()` returns non-empty, before the existing `pd.concat()` — plus a
docstring sentence describing the new `source_id` column in the session-state contract.
`tests/test_sidebar.py`'s diff is purely additive (two new test methods appended to
`TestLoadDataCombination`); the three pre-existing tests
(`test_timeline_rows_appended_to_swarm`, `test_combined_frame_sorted_by_timestamp`,
`test_no_timeline_leaves_swarm_only`) are byte-for-byte unchanged and still pass. No dead
code, no commented-out blocks, no secrets/tokens, no N+1 or hot-path synchronous-call
concerns (pure in-memory pandas column assignment). Confirmed `analysis_utils.py` has zero
diff (`git diff --stat -- analysis_utils.py` empty) — `load_swarm_data()` and
`load_google_timeline()` were not touched, matching the subtask's explicit constraint.

All 4 Acceptance Criteria verified:
- AC #1 (mixed-source row-for-row tagging, cross-referenced by timestamp) — covered by
  `test_source_id_tagged_per_row_when_both_sources_present`, passing.
- AC #2 (swarm-only → all rows `"swarm"`) — covered by
  `test_source_id_all_swarm_when_only_swarm_dir_configured`, passing.
- AC #3 (existing `TestLoadDataCombination` tests unchanged and passing) — confirmed via
  diff (only additions) and the pytest run above.
- AC #4 (loader call-argument stability) — confirmed by inspection: `load_swarm_data(swarm_dir)`
  and `load_google_timeline(timeline_path)` call sites are unmodified; tagging happens only via
  a post-return attribute assignment on the returned DataFrame.

No issues found that require reversal to RED.

Owner Review: APPROVED — Independently verified, not just re-reading the code-review notes:
- Re-read `components/sidebar.py` lines 230-289 in full. Traced both branches: swarm-only
  (`timeline_path` falsy short-circuits the second `if`, so only the guarded
  `swarm_df["source_id"] = "swarm"` assignment runs) and both-configured (swarm tagged first,
  then `timeline_df["source_id"] = "google_timeline"` immediately before the existing
  `pd.concat()`/re-sort). Both traces match AC #1 and AC #2 exactly, including the
  `if not swarm_df.empty` / `if not timeline_df.empty` guards that keep the untouched
  "neither configured" empty-`pd.DataFrame()` path (no `source_id` column at all) exactly as
  it was before this diff — that path is out of scope per the subtask's own description and
  Subtask 3 is responsible for tolerating it.
- Re-ran the scoped set independently rather than trusting the coder/reviewer's prior output:
  `python -m pytest tests/test_sidebar.py tests/test_localizer_frames.py -v --no-cov` → 22
  passed, 0 failed. `python -m ruff check components/sidebar.py tests/test_sidebar.py` → all
  checks passed. `python -m ruff format --check components/sidebar.py tests/test_sidebar.py` →
  2 files already formatted. `python -m mypy components/sidebar.py` → no issues found.
- Diff is minimal (+6/-1 in `components/sidebar.py`, purely additive +33/-0 in
  `tests/test_sidebar.py`) and `analysis_utils.py` has zero diff, confirmed via
  `git diff HEAD -- components/sidebar.py tests/test_sidebar.py`. No dead code, no
  over-abstraction — two guarded one-line column assignments, exactly what the plan called for.
  Mutating the DataFrame returned by `load_swarm_data()`/`load_google_timeline()` in place is
  safe here: both loaders build a fresh `pd.DataFrame` from a Python list on every call
  (confirmed by reading `analysis_utils.py::load_swarm_data`), so there is no shared/cached
  frame elsewhere that this mutation could corrupt.
- All 4 Acceptance Criteria verified directly (not merely by re-reading the code reviewer's
  claims): AC #1 (`test_source_id_tagged_per_row_when_both_sources_present` cross-references
  the exact fixture timestamps 100/300 → "swarm", 200/400 → "google_timeline"), AC #2
  (`test_source_id_all_swarm_when_only_swarm_dir_configured`), AC #3 (the three pre-existing
  `TestLoadDataCombination` tests are byte-for-byte unchanged in the diff and still pass), AC #4
  (loader call sites `load_swarm_data(swarm_dir)` / `load_google_timeline(timeline_path)`
  unmodified — tagging is a post-return attribute assignment only).
- One non-blocking observation for the record: the Test Guidance's claim that the
  "neither source configured" empty-`pd.DataFrame()`-with-no-`source_id` case is "already
  covered by other existing tests in this file" is not literally accurate — grepping this file
  shows exactly one call site to `_load_data_with_progress()` (inside `_run()`), and it always
  passes a truthy `swarm_dir` with `os.path.exists` mocked `True`, so that exact branch
  combination is never exercised end-to-end here. This is not a functional gap, though: the
  `else: swarm_df = pd.DataFrame()` branch is completely untouched by this diff (confirmed via
  the diff above — no lines changed in that branch), so there is no new regression risk, and a
  test asserting today's unchanged behavior would pass vacuously either way. Not blocking.

Both subtasks in PR Group `preserve-source-id` (Subtask 1 and Subtask 2) are now `APPROVED`.
Proceeding per AGENTS.md "After each subtask is APPROVED" §4 (full PR-group close).

---

### Subtask 3 — Shared pure source-filter helper (`core/source_filter.py`)

**Status**: RED

**PR Group**: geo-source-filter-ui

**Depends On**: none

**Description**:
Create `core/source_filter.py` with three small, pure, Streamlit-free functions used by both
consuming pages (Subtasks 4 and 5) so the source→label mapping and filtering logic exists in
exactly one place:

- `source_label(source_id: str) -> str` — returns `SOURCE_LABELS.get(source_id,
  source_id.replace("_", " ").title())` where `SOURCE_LABELS = {"swarm": "Swarm",
  "google_timeline": "Google Timeline"}`. Unknown/future `source_id` values get a humanized
  fallback label rather than crashing or being hidden.
- `get_source_options(swarm_df: pd.DataFrame | None) -> list[str]` — returns `["All"]` when
  `swarm_df` is `None`, empty, or lacks a `source_id` column; otherwise returns `["All"]` followed
  by the sorted, de-duplicated human labels of every distinct `source_id` present.
- `filter_by_source(swarm_df: pd.DataFrame | None, selected_label: str) -> pd.DataFrame | None` —
  returns `swarm_df` unchanged when it is `None`/empty, when `selected_label == "All"`, or when the
  `source_id` column is absent (graceful passthrough, never an exception). Otherwise returns only
  the rows whose `source_label(row.source_id) == selected_label`, with a reset index.

This module has no dependency on Streamlit, DuckDB, or `LocalizerBroker` — pure DataFrame-in/
DataFrame-out logic, independently testable with hand-built fixtures, mirroring
`core/localizer_frames.py`'s existing convention.

**Acceptance Criteria**:
- [ ] `get_source_options()` on a `None` input, an empty DataFrame, and a DataFrame with no
  `source_id` column all return exactly `["All"]`.
- [ ] `get_source_options()` on a DataFrame with `source_id` values `["swarm", "google_timeline",
  "swarm"]` returns exactly `["All", "Google Timeline", "Swarm"]` (alphabetically sorted labels
  after `"All"`).
- [ ] `filter_by_source(df, "All")` returns a frame with the same row count as the input, for both
  a `source_id`-bearing and a `source_id`-lacking input.
- [ ] `filter_by_source(df, "Swarm")` on a mixed-source 4-row fixture (2 swarm, 2 google_timeline)
  returns exactly the 2 rows whose `source_id == "swarm"`, values matching the input row-for-row
  (not just row count).
- [ ] `filter_by_source(df, "Nonexistent Label")` (a label matching no present source) returns an
  empty-but-correctly-shaped DataFrame (same columns, zero rows) rather than raising or returning
  the unfiltered frame.
- [ ] `source_label("swarm") == "Swarm"`, `source_label("google_timeline") == "Google Timeline"`,
  and `source_label("some_future_plugin") == "Some Future Plugin"` (humanized fallback).

**Files to Touch**:
- `core/source_filter.py` (new)
- `tests/test_source_filter.py` (new)

**Test Guidance**:
- Cover all three functions independently with hand-built fixtures (do not route through
  `LocalizerBroker`, `core/localizer_frames.py`, or Streamlit — that integration belongs to
  Subtasks 4/5).
- Explicitly test the "graceful passthrough" edge cases required by the acceptance criteria: `None`
  input, empty DataFrame, missing `source_id` column, and a single-distinct-value `source_id`
  column (proving the filter is a harmless no-op rather than something that needs to be hidden by
  the caller).
- Test the unknown-label fallback in `source_label()` with at least two different underscore-
  separated inputs to confirm the humanization formula generalizes (not hardcoded to one string).
- Test that `filter_by_source()` never mutates its input DataFrame in place (assert the original
  `df` still has all rows after calling the function) — pure functions must not have side effects
  on caller-owned data.

**Test Files**:
`tests/test_source_filter.py` (new) — RED-confirmed (`pytest tests/test_source_filter.py`: collection error `ModuleNotFoundError: No module named 'core.source_filter'`, fails all 20 tests — correct pre-implementation state since the module doesn't exist yet).
20 tests covering all 6 ACs plus edge cases: `test_source_label_known_swarm`, `test_source_label_known_google_timeline`, `test_source_label_unknown_humanized_fallback_first_example`, `test_source_label_unknown_humanized_fallback_second_example`, `test_get_source_options_none_input_returns_all_only`, `test_get_source_options_empty_dataframe_returns_all_only`, `test_get_source_options_missing_source_id_column_returns_all_only`, `test_get_source_options_mixed_sources_sorted_after_all`, `test_get_source_options_single_distinct_source_value`, `test_filter_by_source_none_input_returns_none`, `test_filter_by_source_empty_dataframe_returns_unchanged`, `test_filter_by_source_all_label_mixed_source_row_count_unchanged`, `test_filter_by_source_all_label_no_source_id_row_count_unchanged`, `test_filter_by_source_missing_source_id_column_is_graceful_passthrough`, `test_filter_by_source_swarm_label_returns_only_swarm_rows_row_for_row`, `test_filter_by_source_google_timeline_label_returns_only_those_rows`, `test_filter_by_source_nonexistent_label_returns_empty_but_correctly_shaped`, `test_filter_by_source_result_has_reset_index`, `test_filter_by_source_does_not_mutate_input_in_place`, `test_source_filter_module_has_no_forbidden_imports`.

**Implementation Notes**:
(filled by coder agent)

**Review Notes**:
(filled by owner agent)

---

### Subtask 4 — Wire the source filter into Geo Explorer

**Status**: NEW

**PR Group**: geo-source-filter-ui

**Depends On**: 3

**Description**:
Add a `st.selectbox("Source", get_source_options(swarm_df), key="geo_source_filter")` call inside
`pages/geo_explorer.py::render_geo_explorer()`'s existing "⚡ Filter" popover (`with filt_col: with
st.popover("⚡ Filter"):`), shown only when `has_swarm` is true (mirroring how the Artist selectbox
is already gated on `has_music`). After the popover block — at the same point `music_df` is
already filtered by date range and artist (immediately before the "Share button" section) — apply
`swarm_df = filter_by_source(swarm_df, selected_source)` so every downstream consumer
(`_render_3d_globe`, `_render_2d_map`) sees only the filtered places, exactly once, with no
per-view-mode duplication of filtering logic. Note that the "By City" breakdown table and city
detail card (`_build_city_stats()` / `_render_city_breakdown()` / `_render_atlas_city_detail()`,
lines ~793-1037) operate exclusively on `music_df` (they require `artist`/`track`/`date_text`
columns that `swarm_df` doesn't have) and are out of scope for this subtask — check-ins only ever
appear, in every view mode including "By City", as a single "Check-ins"-labeled dot layer on the
map itself (the `ci` groupby in `_render_2d_map`, and the equivalent `checkin_geo` groupby in
`_render_3d_globe`). This subtask's job is to make that dot layer (in both `_render_2d_map` and
`_render_3d_globe`) reflect the filtered `swarm_df`, not to invent a check-in breakdown table that
doesn't exist today.

**Acceptance Criteria**:
- [ ] With `swarm_df` seeded with mixed `source_id` values and `st.selectbox` mocked to return
  `"Swarm"`, the 2D Map view's check-in dot layer (`_render_2d_map`'s internal `ci` groupby, lines
  ~559-576) only reflects rows whose `source_id == "swarm"` — verified via a specific lat/lng value
  present only in the Swarm-tagged rows appearing, and one present only in Google-Timeline-tagged
  rows being absent. This holds in both "By Artist" and "By City" breakdown modes, since the "By
  City" mode only changes the check-in dots' displayed label (to "Check-ins"), not their filtering.
- [ ] With the selectbox mocked to return `"All"`, behavior is unchanged from pre-filter output
  (same row count reaching `_render_2d_map`/`_render_3d_globe` as the unfiltered `swarm_df`).
- [ ] When `has_swarm` is `False` (i.e. `swarm_df` is `None` or empty — the state every existing
  test in this file already uses), the new selectbox is never called — verified by asserting
  `st.selectbox` was not invoked with a `"Source"` label argument, so `Depends On` Subtask 3's
  helper never even runs the "All"-only path in those cases.
- [ ] All pre-existing tests in `tests/test_geo_explorer.py` continue to pass with zero
  modification to their assertions (only mock setups may gain a new default `st.selectbox`
  side effect entry if required for a shared mock across labels — verify this is not needed since
  none currently populate `swarm_df`).
- [ ] `_build_city_stats()` / `_render_city_breakdown()` / `_render_atlas_city_detail()` remain
  untouched by this subtask and continue to operate solely on `music_df` — no `swarm_df` argument
  is introduced into that call path (regression guard against accidentally wiring `swarm_df` into
  the scrobble-only breakdown table, which would require columns it doesn't have).

**Files to Touch**:
- `pages/geo_explorer.py` (edit: `render_geo_explorer()` — add gated `st.selectbox("Source", ...)`
  inside the filter popover; apply `filter_by_source()` to `swarm_df` before view dispatch; import
  `get_source_options`, `filter_by_source` from `core.source_filter`)
- `tests/test_geo_explorer.py` (edit: add a new test class exercising the filter with a seeded,
  mixed-source `swarm_df`; zero edits to existing test classes' assertions)

**Test Guidance**:
- This is the second-riskiest subtask in the plan (large file, four view-dispatch branches). After
  writing the new filter-specific tests, re-run the entire `tests/test_geo_explorer.py` file and
  confirm the exact same pass count as before this change — this is the load-bearing regression
  check, since none of the four existing view-dispatch tests populate `swarm_df` today and must
  keep passing completely unmodified.
- Build a mixed-source `swarm_df` fixture with at least one row's `lat`/`lng`/`city` unique to
  `"swarm"` and one unique to `"google_timeline"`, so filtering-by-source assertions can check for
  presence/absence of specific values, not just row counts.
- Test the check-in dot layer in both `_render_2d_map` (via its `ci` groupby, lines ~559-576) and
  `_render_3d_globe` (via its `checkin_geo` groupby, lines ~275-438) — these are the two independent
  consumption points of the same filtered `swarm_df` and both must reflect the filter. Do **not**
  test `_build_city_stats()`/the "By City" breakdown table against `swarm_df` — that path only ever
  consumes `music_df` and is explicitly out of scope (see Acceptance Criterion #5's regression
  guard); a test asserting swarm data appears there would be testing for a regression, not a
  feature.
- Verify the selectbox is only rendered when `has_swarm` — mock `st.selectbox` with a side-effect
  function keyed by label (like the existing `test_us_states_view_dispatches`'s `_sel_side_effect`
  pattern) so adding the new call doesn't silently break the Artist-selectbox's expected return
  value in tests that do populate `swarm_df`.
- No concurrency, network I/O, or database-write risk domains apply to this subtask (pure
  Streamlit widget wiring over in-memory DataFrames) — standard Streamlit-mock test technique
  already used throughout this file suffices.

**Test Files**:
HALT (test-ahead batch, 2026-07-07) — blocked on `Depends On: 3`. `core/source_filter.py` does not exist yet. This repo's established mocking convention patches names already present in the consuming module's namespace (e.g. `@patch("pages.geo_explorer.render_share_button")`); patching `pages.geo_explorer.get_source_options`/`filter_by_source` the same way isn't possible yet since that import doesn't exist in `pages/geo_explorer.py` until this subtask's own coder adds it, and pre-registering a fake `core.source_filter` module in `sys.modules` has no precedent in this suite and risks silently shadowing the real Subtask 3 implementation once it lands. Re-run this tester once Subtask 3 reaches `GREEN` (real `core/source_filter.py` will exist with its interface locked in by Subtask 3's own tests).

**Implementation Notes**:
(filled by coder agent)

**Review Notes**:
(filled by owner agent)

---

### Subtask 5 — Wire the source filter into Check-in Insights

**Status**: RED

**PR Group**: geo-source-filter-ui

**Depends On**: 3

**Description**:
Add the same filter pattern to `pages/places.py::render_checkin_insights()`. Immediately after the
existing empty-state check (`if swarm_df is None or swarm_df.empty: ... return`), add
`st.selectbox("Source", get_source_options(swarm_df), key="checkin_source_filter")` and apply
`swarm_df = filter_by_source(swarm_df, selected_source)` before the shareable HTML export
(`build_checkin_insights_html`) and the country/city `groupby` breakdowns — so the filter affects
the exported HTML and both breakdown tables/charts consistently. If filtering narrows `swarm_df` to
empty (e.g. a user selects a source with zero rows after some other future filter interacts with
it), show an informative `st.info` message and return, rather than letting the country/city
`groupby` calls run on an empty frame and render blank charts.

**Acceptance Criteria**:
- [ ] With a mixed-source `swarm_df` and the selectbox mocked to return `"Swarm"`, the "By Country"
  and "Top Cities" breakdown tables only reflect rows whose `source_id == "swarm"` — verified via a
  specific country/city value present only in Google-Timeline-tagged rows being absent from the
  output tables.
- [ ] `build_checkin_insights_html()` is called with the filtered `swarm_df`, not the original
  (verified via a mock call-arg inspection asserting the argument's row count/content matches the
  filtered set).
- [ ] With the selectbox mocked to return `"All"`, output row counts match the unfiltered
  `swarm_df` exactly (no regression from today's behavior).
- [ ] When `swarm_df` is `None` or empty (today's existing empty-state test), the existing `st.info`
  empty-state message still fires and the function returns before the new selectbox is ever
  called — zero behavior change for the no-data case.
- [ ] Filtering down to zero rows (a source with no matching rows) shows an `st.info` message and
  does not raise inside the `groupby("country")`/`groupby(["city", "country"])` calls.

**Files to Touch**:
- `pages/places.py` (edit: `render_checkin_insights()` — add gated `st.selectbox("Source", ...)`
  after the empty-state check; apply `filter_by_source()` before the HTML export and both
  breakdowns; handle the post-filter-empty case; import `get_source_options`, `filter_by_source`
  from `core.source_filter`)
- `tests/test_places.py` (new — no test file exists yet for `pages/places.py`; create one scoped to
  `render_checkin_insights()` following this repo's existing Streamlit-mock conventions from
  `tests/test_geo_explorer.py`)

**Test Guidance**:
- No existing test file covers `pages/places.py` at all (confirmed via repo-wide search) — the new
  `tests/test_places.py` must include, at minimum: the pre-existing-equivalent empty-state test
  (swarm_df `None`/empty → `st.info` shown, no crash), the "All" passthrough case, the "Swarm"-only
  filtered case (with specific country/city presence/absence assertions), the HTML-export
  call-argument assertion, and the post-filter-empty-result case.
- Build a mixed-source fixture with at least one row's `country`/`city` unique to `"swarm"` and one
  unique to `"google_timeline"` (parallel to Subtask 4's fixture design) so presence/absence
  assertions are meaningful.
- Follow this repo's existing `MagicMock`-based Streamlit mocking convention (see
  `tests/test_geo_explorer.py`'s `_make_col_mock`/`_cols_side_effect` helpers) rather than
  introducing a new mocking style.
- No concurrency, network I/O, or database-write risk domains apply — pure Streamlit widget wiring
  over an in-memory DataFrame plus an HTML-export function call.

**Test Files**:
`tests/test_places.py` (new — no prior test file existed for `pages/places.py`) — RED-confirmed (`pytest tests/test_places.py -v --no-cov`: 5 of 7 fail for genuine reasons tied to absent implementation; 2 empty-state regression guards pass today by design, per AC #4).
- `TestRenderCheckinInsightsEmptyState::test_none_swarm_df_shows_info_and_skips_selectbox` (passes today — regression guard)
- `TestRenderCheckinInsightsEmptyState::test_empty_swarm_df_shows_info_and_skips_selectbox` (passes today — regression guard)
- `TestRenderCheckinInsightsSourceFilter::test_selectbox_populated_from_get_source_options` (RED)
- `TestRenderCheckinInsightsSourceFilter::test_swarm_only_filter_narrows_country_and_city_breakdowns` (RED, AC #1)
- `TestRenderCheckinInsightsSourceFilter::test_html_export_receives_filtered_dataframe` (RED, AC #2)
- `TestRenderCheckinInsightsSourceFilter::test_all_selection_keeps_full_dataset` (RED, AC #3)
- `TestRenderCheckinInsightsSourceFilter::test_post_filter_empty_shows_info_and_skips_breakdowns` (RED, AC #5)
- Note: `core/source_filter.py` (Subtask 3) doesn't exist yet either, but this tester did not halt — it mocked `pages.places.get_source_options`/`pages.places.filter_by_source` with `create=True`, testing the integration (does `render_checkin_insights` call and thread these correctly) independent of Subtask 3's actual implementation, which has its own separate test coverage.

**Implementation Notes**:
(filled by coder agent)

**Review Notes**:
(filled by owner agent)

---
