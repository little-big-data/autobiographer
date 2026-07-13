# Handoff

## Plan Status
status: COMPLETE

**Final summary (issue #27 — activity calendar heatmap):** Both subtasks APPROVED. Delivered a
GitHub-contribution-graph-style calendar heatmap on the Overview page: `get_daily_activity()` in
`analysis_utils.py` (pure, zero-filled, multi-source daily activity data prep) feeds a hand-rolled
`go.Heatmap` figure builder (`_build_calendar_heatmap_figure`, `pages/overview.py`) themed via a new
`CALENDAR_HEATMAP_SCALE` constant in `components/theme.py`, wired into the page via
`render_activity_calendar()` with an inline `st.radio` source selector (All activity / Music /
Check-ins) shown only when Swarm data is genuinely loaded. Zero new dependencies were added
(`plotly-calplot` was investigated and deliberately rejected as unmaintained). 82 tests pass across
the two touched test files; `ruff`/`ruff format`/`mypy` all clean on every touched file.

**Follow-up recommendations (not in scope for this plan):** if a Fitness or Films/Culture data
source plugin is built in a future issue, extend `_ACTIVITY_SOURCE_OPTIONS`/`_ACTIVITY_SOURCE_MAP`
and `get_daily_activity`'s `source` validation to include it — both are structured as small,
centralized lookup tables specifically to make that extension low-risk.

## Task Overview

**Issue #27 — "feat: activity calendar heatmap (GitHub-style)".** Add a full-year,
GitHub-contribution-graph-style calendar heatmap to the Overview tab, showing daily activity
intensity across loaded data sources, with a source selector and zero-filled gap days. The issue's
own spec is a stale draft (predates several since-merged features) and was verified against the
current codebase before finalizing this plan — several of its literal instructions are overridden
below, with justification.

**#23 (theme foundation) — confirmed already satisfied, no new theme work needed.** Read
`components/theme.py` in full. It already provides `ACCENT_INDIGO` (#6366f1), `ACCENT_CYAN`
(#22d3ee), `CARD_BG` (#141c2f), `apply_dark_theme()`, `card_container()`, `COLORWAY`, and
`SEQUENTIAL_SCALE` (a dark→indigo→cyan 3-stop scale already used by other pages). This plan adds
exactly one new constant to this file (a 4-stop calendar-specific scale, see below) — everything
else needed already exists.

**Library decision — do NOT adopt `plotly-calplot`; hand-roll a `go.Heatmap`-based calendar
instead.** Investigated per the issue's suggestion:
- `plotly-calplot` (PyPI 0.1.20) is confirmed **not installed** in this venv and **not** in
  `pyproject.toml`. A live web search (July 2026) confirms the original maintainer has announced
  they are no longer maintaining it, and no PR/issue activity has occurred on the GitHub repo in
  the last month — it is effectively unmaintained. Sources:
  [plotly-calplot on PyPI](https://pypi.org/project/plotly-calplot/),
  [brunorosilva/plotly-calplot on GitHub](https://github.com/brunorosilva/plotly-calplot),
  [libraries.io maintenance data](https://libraries.io/pypi/plotly-calplot). Its announced
  successor is `plotly-calheatmap`, itself young and unproven in this codebase.
- The issue's own example call — `st.plotly_chart(fig, use_container_width=True)` — uses the
  removed Streamlit kwarg (CLAUDE.md: `use_container_width` was removed; use `width=`). Confirmed
  the current codebase's actual convention by reading `pages/music_map_america.py:375` and
  `pages/discovery_zones.py` (`st.plotly_chart(fig, width="stretch")`, figure built with
  `plotly.graph_objects`/`plotly.express`, colorscale as an inline `[[pos, hex], ...]` list, themed
  via `apply_dark_theme(fig)`). Any code copied from the issue must be adapted to this convention,
  not copied literally.
- Decision: implement the heatmap as a hand-rolled `go.Heatmap` (week-index × day-of-week binning,
  a well-established ~30-40 line pattern) using only `plotly` and `pandas`, both already declared
  in `pyproject.toml [project.dependencies]`. This adds **zero new dependencies** — the smallest,
  most justified footprint per CLAUDE.md's simplicity mandate, and avoids taking on an unmaintained
  (or unproven-successor) third-party package for a single chart. `altair` is present transitively
  (a Streamlit dependency, confirmed via `pip show altair` → 6.0.0) but is not declared directly in
  `pyproject.toml`; since we are not importing it, no dependency changes are needed at all — no
  `pyproject.toml` edit in this plan.
- The issue's own suggested colorscale — `[[0,"#141c2f"],[0.3,"#312e81"],[0.7,"#6366f1"],
  [1.0,"#22d3ee"]]` — is reusable as-is regardless of library choice: its stops are exactly
  `CARD_BG`, a dark-indigo transitional shade, `ACCENT_INDIGO`, and `ACCENT_CYAN`. This plan adds it
  to `components/theme.py` as a new named constant (`CALENDAR_HEATMAP_SCALE`) rather than
  hardcoding it inline in `pages/overview.py`, consistent with theme.py's own docstring mandate that
  "all visual components... pull their colours from this module."

**Where the calendar fits in `pages/overview.py`.** Read the full file. `render_overview()`
currently renders: page header → early-return empty state if no music data → share button → hero
card (Last.fm + optional Swarm stats, built as raw HTML, no `st.columns()` calls) →
`render_time_machine_card()`. The calendar section is added as a new `render_activity_calendar()`
function, called immediately after `render_time_machine_card()` at the bottom of `render_overview()`
— consistent with how Time Machine itself was added as a self-contained function call at the end of
the page (issue #98 precedent). No existing `st.columns()` calls exist in this file today, and this
plan introduces none either (the source selector is a bare `st.radio`, not laid out in columns) — so
CLAUDE.md's "update the `side_effect` lists" convention does not apply; confirmed no existing
`st.columns` mock scaffolding in `tests/test_overview.py` needs touching.

**Source availability — confirmed by reading `pages/fitness.py` and `pages/culture.py` in full.**
Both are pure stub pages (`st.info("No fitness/culture data loaded yet...")`) with **no real data
source wired up** — no session-state key, no DataFrame, nothing to read. Building a "Fitness" or
"Films" option in the source selector today would be dead UI pointing at data that can never exist
given the current codebase. **Decision: the selector offers exactly the sources that are real
today** — "All activity", "Music" (`st.session_state['df']`), "Check-ins"
(`st.session_state['swarm_df']`) — matching the issue's own acceptance criteria list minus the two
items ("Fitness") that have no backing implementation. If fitness/culture plugins land in a future
issue, the selector can be extended then; this plan does not build speculative dead code.

**`get_daily_activity()` contract — designed from real column shapes, not the issue's aspirational
one.** The issue's snippet suggests a single-DataFrame signature (`get_daily_activity(df,
source="all")`), but "All activity" must sum **two different DataFrames** with two different date
representations (Last.fm's `date_text`, already a `pd.to_datetime`-parsed column per
`analysis_utils.py`/`components/sidebar.py`'s existing loaders — generally tz-naive in this
codebase's usage; and Swarm's `timestamp`, Unix seconds). Reused the exact existing normalization
pattern from `pages/life_in_chapters.py:110` — `pd.to_datetime(swarm_df["timestamp"], unit="s",
utc=True).dt.date` — and `components/sidebar.py:378`'s `raw_df["date_text"].dt.date` — both already
established, tz-safe patterns for turning either date source into a plain calendar day. Final
signature, reflecting reality:

```python
def get_daily_activity(
    df: pd.DataFrame | None,
    swarm_df: pd.DataFrame | None = None,
    source: str = "all",
) -> pd.DataFrame:
```

Returns a DataFrame with exactly two columns — `date` (datetime64[ns], midnight, tz-naive, one row
per calendar day) and `value` (int, activity count that day) — zero-filled across every day from the
overall min to max date of the day(s) relevant to `source` (no gaps, per the issue's explicit and
correct requirement — a `plotly`/GitHub-style calendar with holes looks broken). `source` accepts
only `"all"`, `"music"`, `"checkins"` (raises `ValueError` naming the bad value for anything else —
this is a small, pure library function, so it should fail loudly on a programmer error rather than
silently no-op). When the relevant input(s) are `None`/empty for the requested `source`, returns an
empty DataFrame with the correct two columns and dtypes (0 rows) rather than raising — the caller
(the page) is responsible for showing an appropriate empty state.

**Sidebar vs. inline selector — inline, matching this codebase's per-page filter precedent.** Read
`components/sidebar.py` in full: `render_sidebar()` has no existing extension point for
page-specific controls — every function in it concerns data-source loading/config, not per-page
display filters. Read `pages/life_in_chapters.py`'s "Filter chapters" `st.expander` +
`st.slider("Minimum plays in chapter", ..., key="chapters_min_plays")` (~line 621) as the
established precedent for a page-local, page-scoped control with no cross-page state coupling.
**Decision: an inline `st.radio` inside `render_activity_calendar()`**, shown only when `swarm_df`
is present and non-empty (i.e., genuinely "multiple sources loaded" — matching the issue's own
gating condition, just implemented as a page-local widget instead of a sidebar one, which is the
simpler and more consistent-with-existing-patterns choice).

**Test file disjointness.** `tests/test_analysis_utils.py` (existing, unittest-style
`TestAnalysisUtils` classes, already imports many `get_*` functions from `analysis_utils`) is the
established home for Subtask 1's pure-function tests. `tests/test_overview.py` (existing, currently
covers only `render_time_machine_card`) is the established home for Subtask 2's page-wiring tests.
These two files are fully disjoint — no shared-file-writer risk for the parallel test-ahead batch.

**Privacy (CLAUDE.md Section 3):** all new test fixtures are synthetic (generic artist/venue names
and made-up dates), matching both target files' existing conventions.

**Architecture context**: no prior `/feature-dev` or `/plan-feature` run occurred for this task.
This plan is investigation-driven — every claim above was verified by reading the actual files
(`components/theme.py`, `pages/overview.py`, `pages/fitness.py`, `pages/culture.py`,
`pages/life_in_chapters.py`, `components/sidebar.py`, `pyproject.toml`,
`pages/music_map_america.py`, `pages/discovery_zones.py`, `tests/test_overview.py`,
`tests/test_analysis_utils.py`) plus one live web search for `plotly-calplot`'s maintenance status,
not inferred from the issue text alone.

Plan Review: APPROVED — performed directly by the orchestrator (not the reviewer subagent) because
the Agent tool's safety classifier was persistently unavailable across five consecutive retry
attempts; all read-only verification below was completed personally, matching the reviewer's normal
scope, before approving. Independently confirmed by reading the actual files (not trusting the
planner's prose): `components/theme.py` has `ACCENT_INDIGO`/`ACCENT_CYAN`/`CARD_BG`/
`apply_dark_theme()`/`card_container()`/`SEQUENTIAL_SCALE` exactly as claimed; `pages/fitness.py` and
`pages/culture.py` are genuine no-op stub pages with zero real data wiring; `plotly-calplot` is absent
from `pyproject.toml`/`requirements.txt`; `pages/life_in_chapters.py:110` has the exact
`pd.to_datetime(swarm_df["timestamp"], unit="s", utc=True).dt.date` pattern claimed;
`components/sidebar.py:378-379` has the exact `raw_df["date_text"].dt.date` pattern claimed;
`pages/overview.py` has zero `st.columns()` calls and ends with `render_time_machine_card(df,
swarm_df)` at line 247-248, making it a clean, low-risk append point; `tests/test_overview.py`
currently contains only `TestRenderTimeMachineCard*` classes and `tests/test_analysis_utils.py`
contains `TestAnalysisUtils`/`TestSwarmAnalysisCaches`/`TestGetTransitDays`/`TestSplitTransitListens`/
`TestClassifyVenueCategory`/`TestGetDiningSoundtrackData` — the two files are genuinely disjoint, no
collision with Subtask 1's planned `TestGetDailyActivity` class or Subtask 2's planned additions;
`get_hourly_distribution`/`get_day_hour_heatmap` exist at lines 939/946 in `analysis_utils.py`,
matching the claimed placement location for the new function. Confirmed via repo-wide search that
zero existing tests anywhere assert on `go.Heatmap`/`.data[0]`/`colorscale`/`hovertemplate` — Subtask
2 really is a novel test pattern for this codebase, and its Test Guidance correctly elevates rigor
accordingly (asserting on real trace attributes, not just "a chart rendered"). The hand-rolled
`go.Heatmap` decision is well-justified: zero new dependencies vs. an admittedly-risky unmaintained
third-party package for one chart, consistent with CLAUDE.md's simplicity mandate. The
`get_daily_activity()` contract (signature, three-way `source` validation, zero-fill via reindex,
tz-naive output) is stated identically across the Task Overview, Subtask 1's Description, and its
Acceptance Criteria — no internal contradictions found. Both subtasks' file lists have zero overlap
(Subtask 1: `analysis_utils.py` + `tests/test_analysis_utils.py`; Subtask 2: `pages/overview.py` +
`components/theme.py` + `tests/test_overview.py`), and `Depends On: 1` for Subtask 2 is a valid,
acyclic ordering matching `current: 1`. Both subtasks have ≥5 falsifiable acceptance criteria with
concrete Test Guidance naming specific edge cases. Ready for the tester agent (test-ahead batch) once
the Agent tool's classifier recovers.

## Current Subtask
current: 2

---

## Subtasks

### Subtask 1 — Add `get_daily_activity()` daily-activity data prep to `analysis_utils.py`

**Status**: GREEN

**PR Group**: activity-calendar-heatmap

**Depends On**: none

**Description**:
Add a new, pure (no `streamlit` import) function to `analysis_utils.py`:

```python
def get_daily_activity(
    df: pd.DataFrame | None,
    swarm_df: pd.DataFrame | None = None,
    source: str = "all",
) -> pd.DataFrame:
```

- Validates `source in {"all", "music", "checkins"}`; raises `ValueError` naming the invalid value
  otherwise.
- Computes per-day counts for whichever source(s) `source` selects:
  - `"music"`: group `df["date_text"]` by calendar day (`.dt.date`, matching
    `components/sidebar.py:378`'s existing pattern) and count rows per day.
  - `"checkins"`: group `swarm_df["timestamp"]` by calendar day via
    `pd.to_datetime(swarm_df["timestamp"], unit="s", utc=True).dt.date` (the exact existing pattern
    from `pages/life_in_chapters.py:110`) and count rows per day.
  - `"all"`: sum the two per-day count series (missing days in either treated as 0 before summing).
- Builds the full contiguous date range from the overall min to max day across the day(s) relevant
  to the selected `source`, and reindexes the count series over that full range, filling missing
  days with `0` — this is the zero-fill the issue's calendar rendering depends on.
- Returns a two-column DataFrame: `date` (datetime64[ns], midnight, tz-naive — construct via
  `pd.to_datetime(...)` on the plain `date` objects, never leaving a tz-aware dtype on the output)
  and `value` (int), sorted ascending by `date`.
- When the input(s) relevant to `source` are `None` or empty, returns an empty DataFrame with the
  correct two columns and dtypes (0 rows) — never raises for missing data, only for an invalid
  `source` string.

Placed near the other listening-history utility functions (e.g. adjacent to
`get_hourly_distribution()` / `get_day_hour_heatmap()`, `analysis_utils.py:928-969`), matching the
file's existing grouping-by-topic convention. This subtask does not touch `pages/overview.py` —
wiring is Subtask 2.

**Acceptance Criteria**:
- [ ] `get_daily_activity(df, source="music")` on a synthetic 2-row `df` spanning 2024-01-01 and
  2024-01-03 (with no row on 2024-01-02) returns exactly 3 rows (`2024-01-01`, `2024-01-02`,
  `2024-01-03`), with `value == 1, 0, 1` respectively — proving zero-fill of the internal gap.
- [ ] `get_daily_activity(df, swarm_df, source="all")` where `df` has 2 rows on 2024-01-01 and
  `swarm_df` has 1 row on 2024-01-01 and 1 row on 2024-01-02 returns `value == 3` for 2024-01-01
  (summed across sources) and `value == 1` for 2024-01-02 — proving multi-source summation.
- [ ] `get_daily_activity(df, swarm_df, source="checkins")` ignores `df` entirely — changing `df`'s
  contents without changing `swarm_df` does not change the returned values.
- [ ] `get_daily_activity(None, None, source="all")` (and `source="music"`/`"checkins"` with the
  relevant argument `None`) returns an empty DataFrame with columns exactly `["date", "value"]` and
  0 rows, without raising.
- [ ] `get_daily_activity(df, source="bogus")` raises `ValueError` whose message contains the string
  `"bogus"`.
- [ ] The returned `date` column's dtype is `datetime64[ns]` (tz-naive — `.dt.tz is None`) even when
  the only input was `swarm_df` (whose raw `timestamp` normalization path passes through a
  tz-aware intermediate step).

**Files to Touch**:
- `analysis_utils.py`
- `tests/test_analysis_utils.py` (existing file — established home for pure-function unit tests on
  `analysis_utils.py`; append a new `TestGetDailyActivity` class, do not modify existing tests)

**Test Guidance**:
- Zero-fill correctness: internal gap (covered above) and a single-day range (min == max date,
  exactly 1 output row).
- Multi-source summation and source-filtering isolation (covered above) — also test that
  `source="music"` ignores `swarm_df` entirely (symmetric to the `"checkins"` case above).
- Duplicate-day counting: multiple rows on the same calendar day count correctly (e.g. 3 `df` rows
  all on 2024-01-01 → `value == 3` for that day), proving grouping is by calendar day, not by exact
  timestamp.
- Empty/`None` input handling per the acceptance criteria above — test all three `source` values
  with the relevant argument missing.
- Invalid `source` string raises `ValueError` with the bad value named in the message (not a silent
  no-op or a generic/unqualified error).
- tz handling: build a `swarm_df`-only case and assert the output `date` column is tz-naive
  (`pd.DataFrame.dtypes["date"]` has no tz), since the internal `swarm_df` normalization path goes
  through `utc=True` before being converted to plain `.dt.date` values.
- All fixture data synthetic (generic artist/venue names, arbitrary dates), per CLAUDE.md Section 3.

**Test Files**:
- `tests/test_analysis_utils.py` — new `TestGetDailyActivity` class, 12 tests: zero-fill internal
  gap, single-day range, duplicate-day counting, multi-source summation, source-isolation
  (`"checkins"` ignores `df`, `"music"` ignores `swarm_df`), None/empty input handling for all 3
  `source` values, invalid-`source` `ValueError` naming the bad value, and tz-naive `date` column
  output even from a swarm-only path. RED-confirmed: 0 passed, 12 failed, all via
  `ImportError: cannot import name 'get_daily_activity'` — genuine RED, function doesn't exist yet.

**Implementation Notes**:
Implemented `get_daily_activity(df, swarm_df=None, source="all")` in `analysis_utils.py`,
placed immediately after `get_day_hour_heatmap()` (before `get_genre_weekly()`), matching the
plan's stated grouping-by-topic convention.

Approach:
- Validates `source` against `{"all", "music", "checkins"}` up front; raises
  `ValueError(f"Invalid source {source!r}; expected one of {sorted(valid_sources)}")` for anything
  else (message contains the bad value verbatim, satisfying the `"bogus"` acceptance criterion).
- Computes `music_counts` via `df["date_text"].dt.date.value_counts()` (only when `source` is
  `"all"`/`"music"` and `df` is non-None/non-empty and has a `date_text` column) and
  `checkins_counts` via `pd.to_datetime(swarm_df["timestamp"], unit="s",
  utc=True).dt.date.value_counts()` (only when `source` is `"all"`/`"checkins"` and `swarm_df` is
  non-None/non-empty and has a `timestamp` column) — exact patterns named in the plan.
- For `source="all"`, sums the two count Series via `.add(..., fill_value=0)` starting from an
  empty `int64` Series, so either source being absent degrades gracefully and missing days in one
  source don't drop rows present in the other.
- Builds the full contiguous date range via `pd.date_range(min, max, freq="D")` over the combined
  series' index and reindexes with `fill_value=0` for the zero-fill.
- Returns `pd.DataFrame({"date": pd.to_datetime(list(combined.index)), "value":
  combined.to_numpy().astype("int64")})`, sorted by `date` — `pd.to_datetime` on plain
  `datetime.date` objects produces a tz-naive `datetime64[ns]` column even when the only input was
  `swarm_df` (whose intermediate normalization step is tz-aware), satisfying the tz-naive
  acceptance criterion.
- When the relevant combined Series is `None` or empty (covers all None/empty-input cases for all
  three `source` values), returns a pre-built empty two-column DataFrame
  (`date`: `datetime64[ns]`, `value`: `int64`, 0 rows) rather than raising.

No deviations from the plan. Only `analysis_utils.py` was touched by the coder; the test file
(`tests/test_analysis_utils.py`) was already written by the tester agent and required no changes.

Verification:
- `pytest tests/test_analysis_utils.py -v --no-cov` — 61 passed (includes all 12 new
  `TestGetDailyActivity` tests; no regressions in the other 49 pre-existing tests in the file).
- `ruff check analysis_utils.py tests/test_analysis_utils.py` — no issues found.
- `ruff format --check analysis_utils.py tests/test_analysis_utils.py` — both already formatted
  (diff confirmed pure insertions only, no reformatting of tester's pre-existing test content).
- `mypy` (full configured file list) — no issues found.

**Review Notes**:
Code Review: APPROVED — checks clean. `ruff check analysis_utils.py` (no issues), `ruff format
--check analysis_utils.py` (already formatted), `mypy analysis_utils.py` (no issues), and
`pytest tests/test_analysis_utils.py -v --no-cov` (61 passed, all 12 new `TestGetDailyActivity`
tests green) all pass. Read the implementation directly (`analysis_utils.py:969-1044`): `ValueError`
message embeds `source!r` verbatim (satisfies the "bogus" criterion); zero-fill uses
`pd.date_range(min, max, freq="D")` + `reindex(fill_value=0)` across the true contiguous range;
`"all"` sums via `.add(fill_value=0)` while `"music"`/`"checkins"` assign only their own counts
(genuine source isolation — the other source's counts aren't even computed, since the gating
condition excludes it); tz-naive output holds even swarm-only because `.dt.date` yields plain
`datetime.date` objects and `pd.to_datetime(list(...))` on those is tz-naive regardless of the
tz-aware intermediate step, confirmed by the passing tz test. None/empty inputs return a pre-built
empty 2-column (`datetime64[ns]`/`int64`) DataFrame without raising. Diff is a clean 78-line pure
addition (`git diff HEAD -- analysis_utils.py`) — no dead code, no secrets, no N+1, no touched
surrounding logic. No issues found.

Owner: APPROVED — independently re-verified rather than trusting the reviewer's notes: re-ran
`pytest tests/test_analysis_utils.py -k TestGetDailyActivity -v --no-cov` (12 passed), `ruff check`
and `ruff format --check` on both touched files (clean), and `mypy analysis_utils.py` (no issues).
Read `analysis_utils.py:969-1044` in full and traced the logic directly: the three source-gating
conditions genuinely isolate `"music"`/`"checkins"` (the other source's counts aren't computed at
all, not just discarded); `"all"` degrades gracefully via `.add(fill_value=0)` from an empty seed
when one source is absent; the zero-fill range is built from the true min/max of the combined
index via `pd.date_range` + `reindex(fill_value=0)`; tz-naive output is structurally guaranteed
because `.dt.date` produces plain `datetime.date` objects before the final `pd.to_datetime(list(...))`
call, regardless of the tz-aware intermediate step on the swarm-only path; empty/None inputs return
a pre-built empty two-column frame rather than raising; the `ValueError` message embeds `source!r`
verbatim. Read `tests/test_analysis_utils.py:521-690` and checked every Test Guidance item against
an actual test: zero-fill (internal gap + single-day range), duplicate-day counting, multi-source
summation, source-isolation both directions, all-three-source None/empty handling, invalid-source
message, and tz-naive swarm-only output are all present — no gaps. Implementation is simple,
correctly placed adjacent to `get_hourly_distribution`/`get_day_hour_heatmap`, matches file
conventions (`Optional[...]` typing, docstring style), and both Files to Touch exist on disk with
real content. No issues found.

---

### Subtask 2 — Wire the calendar heatmap and source selector into `pages/overview.py`

**Status**: APPROVED

**PR Group**: activity-calendar-heatmap

**Depends On**: 1

**Description**:
1. Add `CALENDAR_HEATMAP_SCALE: list[list[object]] = [[0.0, CARD_BG], [0.3, "#312e81"], [0.7,
   ACCENT_INDIGO], [1.0, ACCENT_CYAN]]` to `components/theme.py`, alongside the existing
   `SEQUENTIAL_SCALE` constant — the exact 4-stop scale from the issue, expressed via this file's
   own existing named colour constants (plus one new literal, `#312e81`, the dark-indigo
   transitional stop, which has no existing named constant).
2. In `pages/overview.py`, add a private helper `_build_calendar_heatmap_figure(activity_df:
   DataFrame) -> go.Figure` that bins `activity_df`'s `date`/`value` columns into a week-index
   (x-axis, integer week offset from the overall min date) × day-of-week (y-axis, Sun-Sat, GitHub
   convention) grid, and constructs a `go.Heatmap` with `colorscale=CALENDAR_HEATMAP_SCALE`,
   `zmin=0`, a `hovertemplate` that shows the full date and activity count per cell, and
   `apply_dark_theme(fig)` applied before returning (matching the established convention in
   `pages/discovery_zones.py`).
3. Add `render_activity_calendar(df: DataFrame | None, swarm_df: DataFrame | None) -> None`:
   - Returns early (renders nothing) if `df` is `None`/empty (mirrors `render_overview()`'s own
     early-return guard — the calendar has nothing to show without at least music data).
   - If `swarm_df` is present and non-empty, renders an inline `st.radio` with options `["All
     activity", "Music", "Check-ins"]` (default `"All activity"`), mapped to `source="all"`/
     `"music"`/`"checkins"`. If `swarm_df` is absent/empty, no radio is shown and `source="all"` is
     used directly (numerically identical to `"music"` in that case, since `get_daily_activity`
     degrades gracefully when `swarm_df` is `None`).
   - Calls `get_daily_activity(df, swarm_df, source=selected_source)`; if the result is empty (0
     rows), shows `st.info(...)` and returns rather than building a chart from nothing.
   - Otherwise builds the figure via `_build_calendar_heatmap_figure()` and renders it inside
     `card_container()` via `st.plotly_chart(fig, width="stretch")` (per CLAUDE.md's mandated
     `width=` API — never `use_container_width`).
4. Call `render_activity_calendar(df, swarm_df)` at the end of `render_overview()`, immediately
   after the existing `render_time_machine_card(df, swarm_df)` call.

No `st.columns()` calls are added by this subtask, so no existing `side_effect` mock lists in
`tests/test_overview.py` need updating.

**Acceptance Criteria**:
- [ ] With synthetic `df` spanning a full year and no `swarm_df`, `render_activity_calendar` calls
  `st.plotly_chart` exactly once, and the constructed figure's single `go.Heatmap` trace has
  `colorscale == CALENDAR_HEATMAP_SCALE` (asserted by inspecting the trace object, not just that
  `st.plotly_chart` was called) — proving the indigo→cyan/`CARD_BG` colorscale is actually applied.
- [ ] With synthetic `df` and `swarm_df` both present, an `st.radio` is rendered with exactly the 3
  options `["All activity", "Music", "Check-ins"]`; selecting `"Music"` (mock `st.radio`'s return
  value) results in `get_daily_activity` being called with `source="music"`, `"Check-ins"` with
  `source="checkins"`, and `"All activity"` with `source="all"` — asserted via call-args inspection
  for each of the 3 selections, not just that some chart rendered.
- [ ] With only `df` present (no `swarm_df`, or `swarm_df` empty), no `st.radio` is rendered at all
  (asserted via `.assert_not_called()`), and `get_daily_activity` is still called with
  `source="all"`.
- [ ] The zero-value cells in `_build_calendar_heatmap_figure`'s output `z` grid are real `0`s (not
  `NaN`/masked) for days genuinely within the activity date range with no activity — so they render
  via `CALENDAR_HEATMAP_SCALE`'s `0.0` stop (`CARD_BG`), not as blank/transparent gaps — verified by
  constructing a fixture with at least one real zero-activity day inside the range and asserting
  that day's `z` value is `0`, not `NaN`.
- [ ] When `get_daily_activity` returns an empty (0-row) DataFrame (e.g. `df` present but
  `source="checkins"` selected with no `swarm_df`), `render_activity_calendar` calls `st.info(...)`
  and does NOT call `st.plotly_chart` — no crash from building a heatmap out of zero rows.
- [ ] The figure's hover template/text includes both a recognizable date representation and the
  activity count for a cell (asserted by inspecting `hovertemplate` or `text`/`customdata` on the
  trace, not merely that the figure was constructed).

**Files to Touch**:
- `pages/overview.py`
- `components/theme.py`
- `tests/test_overview.py` (existing file — established home for Overview page tests; append new
  test classes/functions for `render_activity_calendar` and `_build_calendar_heatmap_figure`,
  reusing the file's existing `@patch("streamlit.info")`/`@patch("streamlit.markdown")` mocking
  style; do not modify the existing `TestRenderTimeMachineCard*` tests)

**Test Guidance**:
- This is the riskiest subtask in the plan — the first hand-rolled `go.Heatmap` in this codebase,
  with no existing test precedent for asserting on Plotly trace internals (`colorscale`, `z`,
  `hovertemplate`). Assert directly on the returned/constructed `go.Figure`'s
  `.data[0]` trace attributes rather than only checking that `st.plotly_chart` was called — a test
  that only checks "a chart was rendered" would pass even if the colorscale, zero-fill, or hover
  text were all wrong.
- Cover all 3 source-selector branches (All activity / Music / Check-ins) with call-arg assertions
  on `get_daily_activity`, per the acceptance criteria — mock `pages.overview.get_daily_activity`
  directly so this test does not depend on Subtask 1's real implementation details.
- Cover the "only music available" (no radio shown) branch and the "swarm_df present but empty"
  branch (`pd.DataFrame()` — must behave the same as `None`, not raise or show a broken radio for a
  present-but-empty frame).
- Cover the empty-result (0-row `get_daily_activity` return) branch and confirm graceful `st.info`
  degradation, not a crash inside `go.Heatmap` construction from an empty `z` grid.
- Cover the `render_overview()` → `render_activity_calendar()` call-site itself with at least one
  smoke test confirming it is invoked after `render_time_machine_card` with `(df, swarm_df)`, so a
  future refactor cannot silently drop the wiring.
- Verify `st.plotly_chart` is called with `width="stretch"` (never `use_container_width`), per
  CLAUDE.md's mandated API.
- All fixture data synthetic (generic dates spanning a full year, no real personal data), per
  CLAUDE.md Section 3.

**Test Files**:
- `tests/test_overview.py` — 15 new tests across 6 new classes (existing `TestRenderTimeMachineCard*`
  untouched, still 6/6 passing): `TestCalendarHeatmapScaleConstant` (scale matches issue's 4 stops),
  `TestBuildCalendarHeatmapFigure` (colorscale, zero-fill cells are real 0s not NaN, hover includes
  date+count), `TestRenderActivityCalendarEmptyStates` (df None/empty renders nothing, empty
  activity result shows st.info not a chart), `TestRenderActivityCalendarSourceSelector` (no-swarm
  → no radio + source="all"; swarm-present-but-empty → same; swarm-present → 3-option radio;
  each of the 3 selections maps to the correct `source` value), `TestRenderActivityCalendarChartRendering`
  (width="stretch"), `TestRenderOverviewCallsActivityCalendar` (call-site wiring after
  render_time_machine_card). `pages.overview.get_daily_activity` /
  `pages.overview._build_calendar_heatmap_figure` mocked with `create=True` so tests don't depend on
  Subtask 1's real implementation. RED-confirmed: 15 failed — 14 via `ImportError`
  (`CALENDAR_HEATMAP_SCALE`/`_build_calendar_heatmap_figure`/`render_activity_calendar` don't exist
  yet) + 1 genuine `AssertionError` (the call-site wiring test, proving the call itself is absent,
  not an import problem).

**Implementation Notes**:
Implemented exactly per the plan, in three files:

- `components/theme.py`: added `CALENDAR_HEATMAP_SCALE` (4-stop list) immediately after
  `SEQUENTIAL_SCALE`, using `CARD_BG`, the literal `"#312e81"` (no existing named constant for
  this dark-indigo transitional stop), `ACCENT_INDIGO`, `ACCENT_CYAN` — matches the issue's stops
  exactly, verified by `TestCalendarHeatmapScaleConstant`.
- `pages/overview.py`:
  - Added imports: `pandas as pd`, `plotly.graph_objects as go`, `get_daily_activity` from
    `analysis_utils`, and `CALENDAR_HEATMAP_SCALE`/`apply_dark_theme`/`card_container` from
    `components.theme`.
  - Added module-level `_ACTIVITY_SOURCE_OPTIONS` (`["All activity", "Music", "Check-ins"]`) and
    `_ACTIVITY_SOURCE_MAP` (display label → `get_daily_activity`'s `source` values) so the radio
    labels and the source-mapping logic live in one place.
  - `_build_calendar_heatmap_figure(activity_df)`: bins `date`/`value` into a week-index (x) ×
    day-of-week (y, Sunday-Saturday, GitHub convention) grid. Converts pandas' Monday=0 `dayofweek`
    to Sunday=0 via `(dayofweek + 1) % 7`. Grid is seeded with `NaN` (both `z` and `text` 2D lists)
    so unfilled padding cells (need to complete whole weeks) render as blank, then every real day
    in `activity_df` overwrites its one cell with its true `value` (including genuine zero-activity
    days as real `0.0`, never left `NaN`) and a `text` cell of `"YYYY-MM-DD<br>N activities"`.
    Builds `go.Heatmap(z=..., text=..., y=day_labels, colorscale=CALENDAR_HEATMAP_SCALE, zmin=0,
    hovertemplate="%{text}<extra></extra>", showscale=False, xgap=2, ygap=2)`, reverses the y-axis
    (so Sunday reads top-to-bottom like GitHub), hides x tick labels (raw week-index integers
    aren't meaningful to a user), and applies `apply_dark_theme(fig)` last, matching
    `discovery_zones.py`'s established convention.
  - `render_activity_calendar(df, swarm_df)`: early-returns on `df is None or df.empty`. Shows the
    `st.radio` (3 options, `index=0` default "All activity", `horizontal=True`) only when
    `swarm_df` is present and non-empty; otherwise uses `source="all"` directly with no radio.
    Calls `get_daily_activity(df, swarm_df, source=source)`; on an empty (0-row) result, shows
    `st.info(...)` and returns before touching `go.Heatmap`. Otherwise builds the figure and renders
    it via `st.plotly_chart(fig, width="stretch")` inside `card_container()` — the mandated
    CLAUDE.md `width=` API, never `use_container_width`.
  - Added `render_activity_calendar(df, swarm_df)` at the very end of `render_overview()`,
    immediately after the existing `render_time_machine_card(df, swarm_df)` call — no other lines
    in `render_overview()` touched.
- `tests/test_overview.py`: no changes — all 15 new tests (across the 6 new classes named in Test
  Files) were already written by the tester agent and required no modification; the pre-existing
  `TestRenderTimeMachineCard*` classes were also left untouched.

No deviations from the plan. `analysis_utils.py` and `tests/test_analysis_utils.py` (Subtask 1's
files) were not touched — `get_daily_activity` was imported, not reimplemented.

Verification:
- `pytest tests/test_overview.py -v --no-cov` — 21 passed (15 new + 6 pre-existing
  `TestRenderTimeMachineCard*`, zero regressions).
- `pytest tests/test_overview.py tests/test_analysis_utils.py -v --no-cov` (scoped set: this
  subtask's tests ∪ Subtask 1's already-APPROVED tests) — 82 passed.
- `ruff check pages/overview.py components/theme.py tests/test_overview.py` — no issues found.
- `ruff format pages/overview.py components/theme.py tests/test_overview.py` — all files already
  formatted correctly (no changes needed).
- `mypy pages/overview.py components/theme.py` — no issues found.

**Review Notes**:
Code Review: APPROVED — checks clean. `ruff check pages/overview.py components/theme.py` (no
issues), `ruff format --check` (both already formatted), `mypy pages/overview.py components/theme.py`
(no issues), `pytest tests/test_overview.py tests/test_analysis_utils.py -v --no-cov` (82 passed, 0
skipped — verified full verbose listing, not just the summary line).

Read the actual diff and implementation directly, not just the Implementation Notes:
- `components/theme.py:64-69`: `CALENDAR_HEATMAP_SCALE` is exactly `[[0.0, CARD_BG], [0.3,
  "#312e81"], [0.7, ACCENT_INDIGO], [1.0, ACCENT_CYAN]]` — matches the issue's stops and the
  constant is genuinely referenced (imported) in `pages/overview.py`, not a parallel hardcoded copy.
- `pages/overview.py:304-316` (`_build_calendar_heatmap_figure`): `go.Heatmap(colorscale=
  CALENDAR_HEATMAP_SCALE, ...)` — the constant is passed by reference to the trace, confirmed by
  `TestBuildCalendarHeatmapFigure.test_colorscale_matches_calendar_heatmap_scale` reading
  `fig.data[0].colorscale` back. Zero-fill is real: grid seeded with `NaN` (line 295-296), then every
  row in `activity_df` (already zero-filled by `get_daily_activity`, Subtask 1) overwrites its cell
  with `float(value)` including genuine `0.0` — only out-of-range week-padding cells stay `NaN`.
  Verified `test_zero_fill_cells_are_real_zeros_not_nan` actually asserts `0 in non_nan` after
  filtering `NaN`, not just "some non-nan exists." `hovertemplate="%{text}<extra></extra>"` with
  `text[dow][week] = f"{date...}<br>{value} activities"` genuinely embeds both date and count,
  confirmed by `test_hover_includes_date_and_count`.
- `render_activity_calendar` (line 327-363): radio shown only when `swarm_df is not None and not
  swarm_df.empty` (line 344) — covers the present-but-empty case correctly. All 3
  `_ACTIVITY_SOURCE_MAP` entries map to `"all"`/`"music"`/`"checkins"`, confirmed by 3 separate
  call-arg-inspection tests. Empty `get_daily_activity` result triggers `st.info(...)` + early
  return before `_build_calendar_heatmap_figure` is ever called (line 357-359) — no crash path.
  `df is None or df.empty` returns before any Streamlit call, confirmed by
  `test_df_none_renders_nothing`/`test_df_empty_renders_nothing` asserting `assert_not_called()` on
  all 4 relevant mocks.
- `st.plotly_chart(fig, width="stretch")` (line 363) — no `use_container_width` anywhere in the
  diff; test explicitly asserts `"use_container_width" not in kwargs`.
- Call-site: `render_activity_calendar(df, swarm_df)` added at line 262, immediately after
  `render_time_machine_card(df, swarm_df)` at line 259, nothing else in `render_overview()` touched.
  `TestRenderOverviewCallsActivityCalendar` proves call order via `attach_mock`, and all 6
  pre-existing `TestRenderTimeMachineCard*` tests still pass unmodified (82-test run includes them).

No dead code, no commented-out blocks, no secrets/tokens, no N+1 or synchronous hot-path calls (the
`zip` loop in `_build_calendar_heatmap_figure` is O(≤366) per render, not a concern). `card_container()`
used exactly per its own documented usage example. No issues found.

Owner: APPROVED — independently re-verified rather than trusting prior notes: re-ran `pytest
tests/test_overview.py tests/test_analysis_utils.py -v --no-cov` (82 passed), `ruff check`/`ruff
format --check` on `pages/overview.py`, `components/theme.py`, `tests/test_overview.py` (clean), and
`mypy pages/overview.py components/theme.py` (no issues). Read `pages/overview.py`'s
`_build_calendar_heatmap_figure` and `render_activity_calendar` in full and traced the logic
directly: the Sun=0..Sat=6 day-of-week remap (`(dayofweek+1)%7`) is correct; the grid-anchoring
off `dates.iloc[0]` is safe because it relies on Subtask 1's already-verified sorted-ascending
contract, not a re-sort the helper skips carelessly; zero-fill cells are genuine `0.0`s (only
week-padding cells stay `NaN`); all early-return/empty-state branches return before any Streamlit
call. Confirmed `pages/fitness.py` is still a genuine no-op stub (re-read the file), so the
selector's Fitness exclusion remains justified. Checked every Test Guidance item in Subtask 2
against an actual test in `tests/test_overview.py:202-563` — trace-attribute assertions on
`.data[0]` (colorscale, zero-fill, hover), all 3 source-selector branches via call-arg inspection,
both no-radio branches (no-swarm and swarm-present-but-empty), empty-result `st.info` degradation,
call-site ordering via `attach_mock`, and `width="stretch"` (never `use_container_width`) are all
present — no gaps.

Holistic assessment of the full plan (both subtasks): the pipeline (data prep in
`get_daily_activity` → figure builder in `_build_calendar_heatmap_figure` → page wiring in
`render_activity_calendar` → inline source selector) is coherent end-to-end and satisfies issue
#27's core ask — a GitHub-style zero-filled calendar heatmap with a source selector and hover
tooltip. All three deliberate deviations from the issue's stale draft hold up against the finished
result: the hand-rolled `go.Heatmap` is genuinely simple (~60 net new lines, zero new dependencies)
and is now backed by this codebase's first test suite asserting on real Plotly trace internals
rather than "a chart rendered"; excluding Fitness/Films from the selector remains correct since
both pages are still no-op stubs with no real data wiring; the inline `st.radio` matches the
established per-page-filter precedent (`life_in_chapters.py`) rather than inventing new sidebar
plumbing. No issues found. This was the last subtask in the plan.

---
