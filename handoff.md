# Handoff

## Plan Status
status: IN_PROGRESS

## Task Overview

**Issue #92 — "Improved Caching and Loading."** Two asks: (1) general initial renders should
be fast/backgrounded (confirmed by the issue's own "Current Behavior" section to already be
"adequate: several seconds" app-wide — no fix needed there), and (2) **Life in Chapters**
specifically is slow (~30s) and — critically — **repeats that cost after every Year-carousel
click**, and should get "a much better caching strategy... precomputed and stored in the cache."
This plan scopes to (2) only, which is where all real work is.

**Confirmed: the carousel-repeat symptom is already partially fixed and verified safe.**
Commit `ea48138` (#91) added an in-memory `st.session_state` guard in
`pages/life_in_chapters.py::render_life_in_chapters()` (lines 548-561): a `_lic_key = (id(df),
hash(json.dumps(merged_assumptions, sort_keys=True, default=str)))` tuple gates whether
`build_life_chapters()` / `detect_trip_periods()` / `label_listening_context()` re-run. Read the
carousel button handlers directly (lines 600-626): clicking ◀/▶ only writes
`st.session_state["chapters_selected_year"]` and calls `st.rerun()` — it never touches `df`,
`merged_assumptions`, or `_lic_cache_key`. So `_lic_key` is unchanged across a carousel click and
the expensive block is correctly skipped. **No bug here; no change needed to the carousel
handlers.** What #91 does *not* fix — and what issue #92 is actually asking for — is that this
guard lives only in `st.session_state`, so it is lost on every fresh browser session, server
restart, or page reload. That cold-start cost is the real target.

**Root cause / cost drivers, confirmed by reading the functions:**
- `build_life_chapters()` (`analysis_utils.py:1169`): one full `groupby("artist")` pass for
  first-heard dates, then a per-period Python loop with nested per-artist dict lookups for
  discovery-count and chapter-exclusive-artist scoring.
- `detect_trip_periods()` (`analysis_utils.py:1024`): groups `swarm_df` by day and walks
  consecutive-day runs to find trips.
- `label_listening_context()` (`analysis_utils.py:1086`): cheap by comparison — one `home`/`trip`
  vectorized mask assignment **per trip period** (not per row), applied to the full listening
  history.

Because `label_listening_context()`'s cost scales with trip-period *count*, not row count, it
stays fast even against a large history — so it does **not** need disk caching. `build_life_chapters()`
and `detect_trip_periods()` are the two functions whose *output* (not the full labeled DataFrame)
is worth precomputing and persisting.

**Design decision — what gets cached to disk.** Cache only `chapters` (from `build_life_chapters()`)
and `trip_periods` (from `detect_trip_periods()`) — both small (tens to low-hundreds of entries).
Do **not** cache `df_labeled` (the full per-row listening history with a `context` column): it can
be many tens of thousands of rows, would bloat `data/cache/` for no reason, and — per the above —
recomputing it from the (now-cached) `trip_periods` via `label_listening_context(df, trip_periods)`
is already fast. This keeps the new cache payload small and keeps `analysis_utils.py`'s existing,
well-tested functions completely unchanged (no signature or behavior changes to any of the three).

**Design decision — UX: transparent write-through, not an opt-in "Build Cache" button.**
Read `pages/data_sources.py` in full around the Deep Analysis (`_render_deep_analysis_compute`,
~line 618) and Swarm Analysis Cache (`_render_swarm_analysis`, ~line 280) flows: **both existing
cache families are opt-in-gated** — the consuming pages (`venue_patterns.py`, `city_soundtracks.py`,
etc.) show a "hasn't been calculated yet, click X" banner via `_deep_analysis_not_computed_banner()`
until the user explicitly clicks a "Build/Calculate ... Cache" button. Life in Chapters has never
worked that way — it renders immediately today, just slowly on cold start. Issue #92's own
"Expected Behavior" explicitly asks for initial renders to be fast *without* a manual step
("populating in the background", "precalculated and stored"). Introducing an opt-in button here
would be a real UX regression (a zero-config page would suddenly require a click) and doesn't match
what was asked. **Decision: make the disk cache transparent and self-populating** — first render
after a cold start computes normally (same ~30s as today, unavoidable once) and silently writes the
result to disk; every subsequent cold start (new session, browser reload, server restart) reads the
disk cache instead of recomputing, until the underlying data or assumptions change. This is a
deliberate, justified departure from the opt-in convention used by the two existing cache families,
made because Life in Chapters was never opt-in to begin with.

**Design decision — cache key / invalidation, reusing established primitives instead of inventing
new ones.** Read `components/sidebar.py` in full: this codebase has **two data-loading modes**,
and both already expose a ready-made identity primitive:
- **Broker mode** (DuckDB store present): `st.session_state["_loaded_store_identity"]` =
  `(store_path, store_mtime, assumptions_path)`, written by `_broker_store_identity()`
  (`sidebar.py:100`) and already used to detect when the store needs reloading.
- **Legacy mode** (no store): `st.session_state["_loaded_config"]` =
  `(file_path, swarm_dir, assumptions_path, timeline_path)`, and `analysis_utils.get_cache_key()`
  (line 27) — the exact helper CLAUDE.md Section 5 says to reuse — already turns that 4-tuple into
  a stable MD5 hash for the existing raw-dataframe file cache (`sidebar.py:277`).

Neither of these alone is sufficient: `merged_assumptions` in `life_in_chapters.py` also folds in
`load_detected_trips_cache()`'s output (line 534-539), which can change (e.g. after the user clicks
"Build Swarm Analysis Cache") **without** the assumptions file's mtime changing. So the disk cache
key must combine (a) whichever of the two identity primitives above is active this session, with
(b) a hash of `merged_assumptions` — exactly the second half of the existing in-session `_lic_key`,
reused unchanged. New pure function `analysis_utils.get_life_chapters_cache_key(broker_identity,
legacy_config, merged_assumptions)` computes this; it takes plain values (no `streamlit` import),
keeping the utility layer framework-agnostic per CLAUDE.md's Streamlit Conventions. The caller
(`life_in_chapters.py`) resolves which session-state identity is active and passes it in.

**Design decision — Timestamp serialization.** `chapters` entries and `trip_periods` tuples contain
`pd.Timestamp` values, which JSON cannot represent natively — this is the wrinkle flagged before
investigation. Good news: `analysis_utils.py` already has a `_DeepCacheEncoder` (line 1918) used by
`_save_deep_cache()` that serializes `pd.Timestamp` via `.isoformat()` — so **writing** needs no new
code, just reuse of the existing private helpers. **Reading** is the genuinely new piece: none of
the 8 existing `load_deep_*_cache()` functions need to reconstruct `pd.Timestamp` objects (their
consumers, e.g. `venue_patterns.py`, only display the raw JSON), but Life in Chapters' rendering
code calls `.year`, `.strftime()`, `.date()`, `.normalize()` etc. directly on chapter `start`/`end`
and on `trip_periods` — so the new `load_life_chapters_cache()` must explicitly parse the ISO
strings back into `pd.Timestamp` before returning. This is new code, confined to one loader
function.

**Design decision — timing proof uses call-elision, not wall-clock assertions.** A literal
before/after wall-clock timing test would be flaky in CI (machine-dependent, and the ~30s figure
came from a large real dataset that cannot be reproduced with synthetic test fixtures without an
enormous, slow test). Instead, the deterministic, CI-safe proxy for "the cache actually makes this
faster" is: **assert `build_life_chapters()` / `detect_trip_periods()` are not called at all when a
matching disk cache is present** (mocked and asserted via `.called`), which is the actual mechanism
that produces the speedup. Both subtasks' acceptance criteria use this proxy.

**Confirmed: no other files need to change.**
- `_render_cache_tab()`'s "Clear Local Cache" button (`pages/data_sources.py:571`) already does
  `shutil.rmtree("data/cache")` — the new cache file lives in that same directory and is wiped for
  free; no changes needed there.
- Neither the Deep Analysis 8-cache registry/grid nor the Swarm Analysis Cache button flow need to
  register the new cache — per the UX decision above, Life in Chapters' cache is deliberately **not**
  part of either opt-in family.
- No atomic temp-file-then-rename write logic is introduced: all 8 existing deep caches already
  write directly via `open(path, "w")` with no atomicity guard, and this is a single-user local
  Streamlit deployment (per CLAUDE.md's personal-data framing) — matching that existing convention
  rather than introducing new complexity here.

**Test file disjointness (the previous plan for issue #93 was sent back for revision for missing
this):** `tests/test_deep_cache.py` already exists and is exactly the established home for
save/load-roundtrip tests on the deep-cache helpers (Subtask 1). `tests/test_life_in_chapters.py`
already exists and is the established home for `render_life_in_chapters()` integration tests
(Subtask 2). These two files are fully disjoint, so the parallel test-ahead batch has no
shared-file-writer conflict.

**Privacy (CLAUDE.md Section 3):** all new tests use only synthetic data (already the convention in
both target test files — synthetic artists/dates/cities). No real personal data is touched by this
plan.

**Architecture context**: no prior `/feature-dev` or `/plan-feature` run occurred for this task.
This plan is investigation-driven — every claim above was verified by reading the actual files
(`pages/life_in_chapters.py`, `analysis_utils.py`, `pages/data_sources.py`, `components/sidebar.py`,
`tests/test_deep_cache.py`, `tests/test_life_in_chapters.py`), not inferred from the issue text alone.

Plan Review: APPROVED — Independently re-verified every factual claim against the actual repo
(lines 548-561 and 600-626 of `life_in_chapters.py`, `analysis_utils.py`'s `get_cache_key`/
`_DeepCacheEncoder`/`_load_deep_cache`/`_save_deep_cache`/function signatures at 1024/1086/1169,
`sidebar.py`'s `_broker_store_identity`/`_loaded_config`/`_loaded_store_identity` contract including
the broker-mode `("", "", assumptions_path, "")` 4-tuple, `data_sources.py`'s opt-in Deep Analysis
banner vs. `_render_cache_tab`'s `rmtree("data/cache")`, and both target test files' existing
fixtures/conventions) — all confirmed accurate, not just plausible. The transparent write-through UX
decision is well-justified (Life in Chapters was never opt-in; the issue asks for no manual step) and
explicitly documented as a deliberate departure from the Deep/Swarm Analysis button convention. The
cache-key design correctly handles all three invalidation scenarios (different data, edited
assumptions content via the merged_assumptions hash, and broker/legacy mode switches) because it
combines the coarse identity tuple with a hash of the actual parsed `merged_assumptions` content, not
just file mtimes. The Timestamp round-trip claim is accurate: `_DeepCacheEncoder` already handles
writing via `.isoformat()`, but none of the 8 existing loaders reconstruct `pd.Timestamp` on read, so
`load_life_chapters_cache`'s rehydration is genuinely new code as claimed. The call-elision timing
proxy (asserting `build_life_chapters`/`detect_trip_periods` are not called) is a legitimate,
deterministic, CI-safe stand-in for the unreproducible ~30s wall-clock claim. Gates: both subtasks
have ≥5 falsifiable acceptance criteria; Files-to-Touch have zero source-file overlap and the two
test files (`tests/test_deep_cache.py`, `tests/test_life_in_chapters.py`) are fully disjoint; the
2-subtask dependency graph (2 depends on 1, `current: 1` first) is an acyclic, valid topological
order; both subtasks include concrete Test Guidance naming specific edge cases (stale-key miss,
corrupt/missing file, disk-write-failure resilience, broker-vs-legacy precedence, carousel-click
zero-overhead regression guard).

## Current Subtask
current: 2

---

## Subtasks

### Subtask 1 — Add Life Chapters disk-cache key, save, and load functions

**Status**: APPROVED

**PR Group**: life-chapters-disk-cache

**Depends On**: none

**Description**:
Add to `analysis_utils.py`:
- `LIFE_CHAPTERS_CACHE: str = os.path.join("data", "cache", "life_chapters.json")` (new constant,
  alongside the existing `DETECTED_TRIPS_CACHE` / `TRANSIT_DAYS_CACHE` / `DINING_CACHE` constants).
- `get_life_chapters_cache_key(broker_identity: tuple[Any, ...] | None, legacy_config: tuple[str,
  str, str, str] | None, merged_assumptions: dict[str, Any]) -> str` — a pure function (no
  `streamlit` import). If `broker_identity` is not `None`, use it as the base identity; otherwise if
  `legacy_config` is not `None`, use `get_cache_key(*legacy_config)` (the existing helper) as the
  base identity; otherwise use a fixed sentinel base (e.g. `"none"`). Combine the base identity with
  an MD5 hash of `json.dumps(merged_assumptions, sort_keys=True, default=str)` (identical
  serialization to the existing in-session `_lic_key` in `life_in_chapters.py`) into a single
  deterministic hex digest.
- `save_life_chapters_cache(cache_key: str, chapters: list[dict[str, Any]], trip_periods:
  list[tuple[pd.Timestamp, pd.Timestamp]], path: str = LIFE_CHAPTERS_CACHE) -> None` — builds a
  JSON payload `{"cache_key": cache_key, "chapters": chapters, "trip_periods": [[s, e] for s, e in
  trip_periods]}` and writes it via the existing private `_save_deep_cache()` helper (which already
  serializes `pd.Timestamp` via `_DeepCacheEncoder`).
- `load_life_chapters_cache(cache_key: str, path: str = LIFE_CHAPTERS_CACHE) -> tuple[list[dict[str,
  Any]], list[tuple[pd.Timestamp, pd.Timestamp]]] | None` — loads the raw JSON via the existing
  private `_load_deep_cache()` helper; returns `None` if the file is missing, corrupt, or its stored
  `"cache_key"` does not match the passed-in `cache_key` (stale cache → forced miss, never a stale
  hit). On a match, reconstructs `pd.Timestamp` objects for every chapter's `"start"`/`"end"` fields
  and for every `trip_periods` pair, and returns `(chapters, trip_periods)`.

This subtask does not touch `pages/life_in_chapters.py` — wiring is Subtask 2.

**Acceptance Criteria**:
- [ ] `get_life_chapters_cache_key(None, ("a.csv", "", "assump.json", ""), {"trips": []})` is
  deterministic — two calls with identical arguments return the identical string.
- [ ] Changing only `merged_assumptions` (e.g. adding a trip entry) while `broker_identity` and
  `legacy_config` stay fixed changes the returned key.
- [ ] When both `broker_identity` and `legacy_config` are non-`None`, the key is derived from
  `broker_identity` (broker-mode precedence, matching `components/sidebar.py`'s "opt-in when the
  DuckDB store exists" behavior) — verified by changing `legacy_config` alone and confirming the key
  does NOT change while `broker_identity` stays fixed.
- [ ] `save_life_chapters_cache(key, chapters, trip_periods, path=tmp)` followed by
  `load_life_chapters_cache(key, path=tmp)` returns `(chapters2, trip_periods2)` where every
  chapter's `start`/`end` are `pd.Timestamp` instances equal to the originals, and every
  `trip_periods2` pair is a `(pd.Timestamp, pd.Timestamp)` tuple equal to the original — proving
  round-trip fidelity through JSON (the Timestamp-serialization wrinkle).
- [ ] `load_life_chapters_cache("key-B", path=tmp)` returns `None` when the file at `tmp` was saved
  under `"key-A"` (stale/mismatched key is treated as a miss, not a stale hit).
- [ ] `load_life_chapters_cache("any-key", path="<nonexistent path>")` returns `None`, and a file at
  `path` containing invalid JSON also returns `None` (matches `_load_deep_cache`'s existing
  missing/corrupt handling — no new exception types introduced).

**Files to Touch**:
- `analysis_utils.py`
- `tests/test_deep_cache.py` (existing file — established home for deep-cache save/load-roundtrip
  tests; append new test classes/functions, do not modify existing tests)

**Test Guidance**:
- Determinism and sensitivity: same inputs → same key; changing `merged_assumptions` → different
  key; changing `legacy_config` with `broker_identity=None` → different key; changing `legacy_config`
  while `broker_identity` is set → key unchanged (precedence proof).
- Round-trip fidelity: build a chapters list with at least 2 entries (mix of `"kind": "residency"`
  and `"kind": "trip"`) and a `trip_periods` list with at least 1 pair, save then load, assert
  `pd.Timestamp` equality (not string equality) on every date field, and assert the two chapter
  dicts are otherwise equal (`label`, `location`, `total_plays`, etc. unchanged through the
  round-trip).
- Stale-key and missing/corrupt-file cases per the acceptance criteria above; write a corrupt file
  with plain non-JSON text (e.g. `"not json {"` ) to a temp path and assert `load_life_chapters_cache`
  returns `None` rather than raising.
- Use `tempfile.TemporaryDirectory()` for all save/load tests (matching the existing pattern already
  used in `tests/test_deep_cache.py`'s `TestSaveLoadRoundtrip`), never writing into the real
  `data/cache/` directory.
- All fixture data must be synthetic (generic city/artist names), per CLAUDE.md Section 3.

**Test Files**:
- `tests/test_deep_cache.py` — 10 new tests appended (existing tests untouched):
  `TestLifeChaptersCacheConstant::test_life_chapters_cache_constant_shape`;
  `TestGetLifeChaptersCacheKey::{test_deterministic_same_inputs_same_key,
  test_changing_merged_assumptions_changes_key,
  test_changing_legacy_config_changes_key_when_broker_identity_none,
  test_broker_identity_takes_precedence_over_legacy_config,
  test_none_broker_and_none_legacy_uses_sentinel_and_is_deterministic}`;
  `TestLifeChaptersCacheSaveLoadRoundtrip::test_roundtrip_preserves_timestamps_and_other_fields`;
  `TestLifeChaptersCacheStaleAndMissing::{test_mismatched_cache_key_is_treated_as_miss,
  test_load_missing_path_returns_none, test_load_corrupt_json_returns_none}`. All fixture data
  synthetic. RED-confirmed: 10 failed, each with `ImportError` (target names don't exist yet in
  `analysis_utils.py`) — genuine RED, no implementation code written by the tester.

**Implementation Notes**:
Added a new "Life Chapters disk cache (issue #92)" section to `analysis_utils.py`, inserted
immediately after `get_deep_analysis_status()` (before the "Listening session detection" section),
containing:
- `LIFE_CHAPTERS_CACHE = os.path.join("data", "cache", "life_chapters.json")`, following the
  existing `DETECTED_TRIPS_CACHE`/`TRANSIT_DAYS_CACHE`/`DINING_CACHE` constant convention.
- `get_life_chapters_cache_key(broker_identity, legacy_config, merged_assumptions)` — precedence:
  broker_identity (if not None) > legacy_config (if not None) > `"none"` sentinel. One deviation
  from the literal plan text: for the `legacy_config` branch the base identity is
  `f"{get_cache_key(*legacy_config)}|{legacy_config!r}"` rather than just
  `get_cache_key(*legacy_config)` alone. Reason: `get_cache_key()` short-circuits to the fixed
  string `"none"` whenever `lastfm_file` doesn't exist on disk (see `analysis_utils.py:34-35`), and
  the acceptance-criteria test `test_changing_legacy_config_changes_key_when_broker_identity_none`
  uses two different synthetic, non-existent file paths (`"a.csv"` vs `"b.csv"`, etc.) and asserts
  the resulting keys differ. Relying on `get_cache_key()`'s return value alone would collapse both
  to `"none"` and fail that test. Folding in `repr(legacy_config)` alongside the existing
  `get_cache_key()` call preserves sensitivity to config changes (satisfying the test) while still
  reusing `get_cache_key()` per the plan's intent, and does not affect the precedence test (which
  never enters this branch when `broker_identity` is set) or any other acceptance criterion. Both
  the base identity and `merged_assumptions` (via `json.dumps(..., sort_keys=True, default=str)`,
  identical serialization to the existing in-session `_lic_key`) are combined into a single MD5 hex
  digest.
- `save_life_chapters_cache(cache_key, chapters, trip_periods, path=LIFE_CHAPTERS_CACHE)` — builds
  the `{"cache_key", "chapters", "trip_periods"}` payload exactly as specified and delegates to the
  existing `_save_deep_cache()` (which already serializes `pd.Timestamp` via `_DeepCacheEncoder`).
- `load_life_chapters_cache(cache_key, path=LIFE_CHAPTERS_CACHE)` — delegates to the existing
  `_load_deep_cache()`; returns `None` on missing/corrupt file (matching `_load_deep_cache`'s
  existing behavior) or on `cache_key` mismatch (stale cache = forced miss); on a match, rehydrates
  `pd.Timestamp` for every chapter's `start`/`end` and every `trip_periods` pair via `pd.Timestamp(...)`.

No new dependencies added; no changes to `get_cache_key`, `_save_deep_cache`, `_load_deep_cache`, or
`_DeepCacheEncoder`. `pages/life_in_chapters.py` and `tests/test_life_in_chapters.py` untouched, per
scope. One mypy-driven fix beyond the plan text: used `Optional[tuple[...]]` / `Optional[tuple[...] ]`
instead of PEP 604 `X | None` syntax for the three new type annotations, because this file has no
`from __future__ import annotations` import and mypy is pinned to `python_version = "3.9"` in
`pyproject.toml` (PEP 604 union syntax at runtime requires 3.10+); `Optional[...]` matches the
existing convention already used elsewhere in the file (e.g. `_get_ruptures`).

Verification:
- `pytest tests/test_deep_cache.py -v --no-cov` → 31 passed, 0 failed (21 pre-existing + 10 new,
  confirming no regression to the existing deep-cache tests).
- `ruff check --fix analysis_utils.py` → no issues found. `ruff format analysis_utils.py` → already
  formatted correctly.
- `mypy analysis_utils.py` → no issues found (after the `Optional[...]` fix above; the initial PEP
  604 syntax produced 3 `[syntax]` errors under the `python_version = "3.9"` mypy config).

**Review Notes**:
Code Review: APPROVED — checks clean. `ruff check`, `ruff format --check`, and `mypy` all report
no issues on `analysis_utils.py`; `pytest tests/test_deep_cache.py -v --no-cov` → 31 passed (21
pre-existing + 10 new), 0 failed. Manual review of the diff found no dead code, no secrets, no N+1
patterns, and full null/error-handling parity with the existing `_load_deep_cache`/`_save_deep_cache`
helpers it reuses. The flagged deviation (`base = f"{get_cache_key(*legacy_config)}|{legacy_config!r}"`
instead of `get_cache_key(*legacy_config)` alone) is sound: (1) it still satisfies the AC's intent —
deterministic (legacy_config is an all-`str` 4-tuple, so `repr()` is stable) and sensitive to any
config change, verified by both `test_changing_legacy_config_changes_key_when_broker_identity_none`
and `test_broker_identity_takes_precedence_over_legacy_config` passing; (2) no security regression —
the `repr(legacy_config)` text (which can contain local file paths) is only ever folded into the
*pre-hash* `base` string, never returned or persisted directly; the function's only output is the
final `hashlib.md5(...).hexdigest()`, exactly mirroring `get_cache_key()`'s own existing pattern of
joining raw file paths into `key_parts` before hashing (`analysis_utils.py:38-58`) — this is the
established norm in this file, not a new exposure, and the only persisted artifact
(`save_life_chapters_cache`'s `"cache_key"` field) is the opaque digest, never the raw base string;
(3) real-world behavior with existing files is preserved — `get_cache_key()`'s real mtime-based
content hash still fully participates in `base` (it's the first half of the joined string), so
`repr(legacy_config)` is strictly additive (an extra invalidation trigger on config-tuple changes,
e.g. a changed path with unchanged mtime), never a replacement for the content-hash signal. No
concerns found; no changes requested.

Owner: APPROVED — Independently read the full implementation (`analysis_utils.py:2136-2245`) and
the 10 new tests in `tests/test_deep_cache.py`. Verified by direct trace: `get_life_chapters_cache_key`'s
precedence (`base = repr(broker_identity)` when set, else `f"{get_cache_key(*legacy_config)}|
{legacy_config!r}"`, else `"none"`, then combined with an `assumptions_hash` via a second md5) matches
every acceptance criterion, including the broker-precedence test (changing `legacy_config` alone
cannot affect `base` when `broker_identity is not None`). Confirmed `build_life_chapters()`'s own
docstring lists `start`/`end` as the only `pd.Timestamp` fields on a chapter (all other fields are
str/int/list), so `load_life_chapters_cache`'s rehydration of exactly those two fields (plus every
`trip_periods` pair) is complete, not partial. `_load_deep_cache`'s existing `FileNotFoundError`/
`json.JSONDecodeError` handling is reused unchanged for missing/corrupt files. Independently re-ran
the scoped suite (`pytest tests/test_deep_cache.py -q --no-cov` → 31 passed), `ruff check`, and
`mypy` — all clean. Test Guidance fully covered: determinism, assumptions-sensitivity, legacy-config-
sensitivity, broker-precedence, sentinel-path, Timestamp round-trip with a mixed residency/trip
fixture, stale-key miss, missing-path miss, corrupt-JSON miss. The flagged `repr(legacy_config)`
deviation is sound for the reasons the code reviewer already gave; independently confirmed no
alternative reading of the plan text is violated and no security/behavior regression results. Simple,
well-scoped, no dead code, no premature abstraction. Approved as-is.

---

### Subtask 2 — Wire the disk cache into `render_life_in_chapters()`

**Status**: APPROVED

**PR Group**: life-chapters-disk-cache

**Depends On**: 1

**Orchestrator note (post-NEEDS_REVISION fix)**: the owner's sole blocking finding was that
`tests/test_deep_cache.py` (Subtask 1's test file) wasn't `ruff format`-clean — Subtask 1's coder/
reviewer/owner had scoped their `ruff format --check` runs to `analysis_utils.py` only, missing the
test file they also wrote. Fixed directly by the orchestrator (trivial, mechanical, no design
decision — same trivial-change carve-out used elsewhere in this repo's AGENTS.md workflow): ran
`ruff format tests/test_deep_cache.py` (1 file reformatted), then re-verified repo-wide:
`ruff format --check .` → 163 files already formatted; `ruff check .` → all checks passed; `mypy`
→ no issues in 18 source files; `pytest tests/test_life_in_chapters.py tests/test_deep_cache.py -v
--no-cov` → **90 passed**, 0 failed. No test or production logic changed — formatting only. Subtask
2's substance (already reviewed and approved by both the code reviewer and the owner) is otherwise
unchanged. Status set to `APPROVED`; both subtasks in PR Group `life-chapters-disk-cache` are now
APPROVED.

**Description**:
In `pages/life_in_chapters.py::render_life_in_chapters()`, extend the existing session-state-guarded
block (lines 548-561) so the disk cache sits **behind** the cheap in-session `_lic_cache_key` guard
from #91 (no added disk I/O on carousel clicks or any rerun where `_lic_key` is unchanged) but
**in front of** the expensive `build_life_chapters()` / `detect_trip_periods()` calls:

1. Resolve `broker_identity = st.session_state.get("_loaded_store_identity")` and `legacy_config =
   st.session_state.get("_loaded_config")`.
2. Compute `cache_key = get_life_chapters_cache_key(broker_identity, legacy_config,
   merged_assumptions)`.
3. Only when the existing `_lic_cache_key` check misses (i.e. exactly the same branch that
   currently always recomputes):
   a. Try `load_life_chapters_cache(cache_key)`. If it returns a non-`None` `(chapters, trip_periods)`
      pair, use those directly — **skip** `build_life_chapters()` and `detect_trip_periods()`
      entirely — then still compute `df_labeled = label_listening_context(df, trip_periods)` (cheap,
      always recomputed; see Task Overview for why).
   b. If it returns `None` (cache miss), compute `chapters`, `trip_periods`, `df_labeled` exactly as
      today, then call `save_life_chapters_cache(cache_key, chapters, trip_periods)` wrapped in a
      broad `try/except` so a disk-write failure (permissions, full disk) cannot prevent the
      already-successfully-computed page from rendering.
   c. Store `chapters`, `trip_periods`, `df_labeled` into `st.session_state` exactly as today (no
      change to the downstream rendering code below this block).

No new `st.columns()` calls are introduced by this subtask — this is pure data-plumbing ahead of the
existing render logic, so no widget mock `side_effect` lists need updating.

**Acceptance Criteria**:
- [ ] Session-state cache miss + matching disk cache present: `build_life_chapters` and
  `detect_trip_periods` are NOT called (mocked, asserted via `.called is False`); `st.session_state`
  ends up populated with the disk-cached `chapters`/`trip_periods`; `label_listening_context` IS
  still called once with those `trip_periods`.
- [ ] Session-state cache miss + no matching disk cache (`load_life_chapters_cache` returns `None`):
  `build_life_chapters` and `detect_trip_periods` ARE called (existing behavior, unchanged), and
  `save_life_chapters_cache` is called exactly once afterward with the freshly computed values and
  the same `cache_key` a subsequent `load_life_chapters_cache` call would be given.
- [ ] A second `render_life_in_chapters()` call in the same session where `st.session_state
  ["_lic_cache_key"]` already matches `_lic_key` (the #91 guard) calls NEITHER
  `load_life_chapters_cache` NOR `build_life_chapters`/`detect_trip_periods` NOR
  `save_life_chapters_cache` — proving the disk-cache layer adds zero overhead to the already-fast
  carousel-click path (no regression to #91).
- [ ] When `st.session_state["_loaded_store_identity"]` is set (broker mode), the `cache_key` passed
  to `load_life_chapters_cache`/`save_life_chapters_cache` is derived from it, not from
  `_loaded_config` — verified by mocking `get_life_chapters_cache_key` and inspecting call args
  under both a broker-mode and a legacy-mode session-state fixture.
- [ ] If `save_life_chapters_cache` raises an exception, `render_life_in_chapters()` still completes
  without raising and still renders the in-memory-computed chapters (disk-write failure is
  non-fatal).

**Files to Touch**:
- `pages/life_in_chapters.py`
- `tests/test_life_in_chapters.py` (existing file — established home for `render_life_in_chapters()`
  integration tests; append new test methods to `TestRenderLifeInChapters`, reusing its existing
  `_make_full_df()` / `_make_assumptions()` fixtures and mocking conventions — plain-dict
  `patch("streamlit.session_state", {...})`, `_columns_side_effect` helper, expander/container
  context-manager mocks — do not modify existing passing tests)

**Test Guidance**:
- Reuse the existing `TestRenderLifeInChapters` fixtures and mocking style already in the file
  (see `test_renders_chapters_with_data` ~line 345) rather than inventing new ones.
- Cover both broker-mode (`_loaded_store_identity` set, `_loaded_config` absent or irrelevant) and
  legacy-mode (`_loaded_store_identity` absent, `_loaded_config` a 4-tuple) session-state fixtures.
- Cover the disk-cache-hit path (mock `pages.life_in_chapters.load_life_chapters_cache` to return a
  synthetic `(chapters, trip_periods)` pair) and assert `build_life_chapters`/`detect_trip_periods`
  are not called — this is the CI-safe proxy for "the cache makes cold start fast" (see Task
  Overview's rationale for avoiding wall-clock timing assertions).
- Cover the disk-cache-miss path (mock `load_life_chapters_cache` to return `None`) and assert the
  existing compute-and-store behavior is unchanged, plus the new `save_life_chapters_cache` call.
- Cover the "session cache already warm" path (pre-seed `st.session_state["_lic_cache_key"]` to
  match the freshly computed `_lic_key` before calling `render_life_in_chapters()`) and assert zero
  calls to any of the four new/existing expensive/disk functions — this is the regression guard for
  #91's carousel-click behavior.
- Cover the disk-write-failure resilience case: mock `save_life_chapters_cache` to raise, assert
  `render_life_in_chapters()` does not raise and `mock_header`/`mock_metric` (or equivalent) still
  fire, proving the page still rendered.
- All fixture data must be synthetic, per CLAUDE.md Section 3 and the existing file's convention.

**Test Files**:
- `tests/test_life_in_chapters.py` — 6 new tests appended to `TestRenderLifeInChapters` (existing
  53 tests untouched): `test_disk_cache_hit_skips_build_and_detect` (AC1),
  `test_disk_cache_miss_computes_and_saves` (AC2),
  `test_disk_cache_layer_adds_no_overhead_when_session_cache_warm` (AC3 — #91 regression guard),
  `test_cache_key_uses_broker_identity_when_present` / `test_cache_key_uses_legacy_config_when_no_broker_identity`
  (AC4), `test_disk_write_failure_does_not_break_render` (AC5). All three new functions
  (`get_life_chapters_cache_key`, `save_life_chapters_cache`, `load_life_chapters_cache`) mocked
  with `create=True` so tests are genuine assertion-failure RED rather than import/attribute-error
  RED (Subtask 1's implementation doesn't exist yet). RED-confirmed: 6 failed (clean
  `AssertionError`s, e.g. "Expected '<function>' to have been called once. Called 0 times."), 0
  errored; pre-existing 53 tests in the file still pass unaffected.

**Implementation Notes**:
In `pages/life_in_chapters.py::render_life_in_chapters()`, extended the existing `_lic_cache_key`
miss branch (lines 551-597) exactly per the plan:
- Imported `get_life_chapters_cache_key`, `load_life_chapters_cache`, `save_life_chapters_cache`
  from `analysis_utils` alongside the existing imports (alphabetized into the existing `from
  analysis_utils import (...)` block).
- Inside the miss branch: resolve `broker_identity = st.session_state.get("_loaded_store_identity")`
  and `legacy_config = st.session_state.get("_loaded_config")`, compute `cache_key =
  get_life_chapters_cache_key(broker_identity, legacy_config, merged_assumptions)`, then try
  `load_life_chapters_cache(cache_key)`. On a hit, use the returned `(chapters, trip_periods)`
  directly (skip `build_life_chapters`/`detect_trip_periods`) and still compute `df_labeled =
  label_listening_context(df, trip_periods)`. On a miss, compute `chapters`/`trip_periods`/
  `df_labeled` exactly as before, then call `save_life_chapters_cache(cache_key, chapters,
  trip_periods)` wrapped in `try/except Exception: pass` (annotated `# noqa: BLE001, S110` with a
  comment, matching the established broad-except-for-resilience convention already used elsewhere
  in this codebase, e.g. `pages/geo_explorer.py:233`, `pages/places.py:86`). Session-state storage
  (`_lic_cache_key`/`_lic_chapters`/`_lic_trip_periods`/`_lic_df_labeled`) and all downstream
  rendering code are unchanged.

One deviation from the literal plan text, required to keep the pre-existing test suite green:
`get_life_chapters_cache_key`'s legacy-mode branch (Subtask 1, `analysis_utils.py`) delegates to
`get_cache_key(*legacy_config)`, which calls `os.path.exists()` on the first tuple element and
raises `TypeError` if that element is `None` (not a valid path type). Several *pre-existing*
tests in `TestRenderLifeInChapters` (already-passing before this subtask, not written by this
subtask's tester) set `session_state["_loaded_config"] = (None, None, None)` — a 3-element
placeholder tuple that was previously only ever indexed (`loaded_config[2]`), never passed to
`get_cache_key`. Passing it through unchanged would crash `render_life_in_chapters()` for those
pre-existing fixtures (and for 4 of the 6 new Subtask-2 tests, which reuse the same placeholder).
Per scope, `analysis_utils.py` (Subtask 1, already `APPROVED`) could not be touched to fix this
there, so the fix lives entirely in `pages/life_in_chapters.py`: before calling
`get_life_chapters_cache_key`, `legacy_config` is sanitized — only passed through if it is a
tuple of exactly 4 `str` elements (the documented `_loaded_config` shape per
`components/sidebar.py`'s docstring, always true in real usage); anything else (missing, wrong
length, non-string elements) is treated as `None` (the function's existing "no legacy config"
sentinel path), which is deterministic and crash-free. This does not change behavior for any real
session (real `_loaded_config` is always a well-formed 4-string tuple) and does not affect the
`test_cache_key_uses_legacy_config_when_no_broker_identity` acceptance test, which uses a
well-formed 4-string tuple and passes through unchanged.

No files touched beyond the plan's `Files to Touch`. `analysis_utils.py` and
`tests/test_deep_cache.py` untouched.

Verification:
- `pytest tests/test_life_in_chapters.py -v --no-cov` → 59 passed, 0 failed (53 pre-existing + 6
  new, no regression).
- `pytest tests/test_deep_cache.py -v --no-cov` → 31 passed, 0 failed (Subtask 1's scoped tests,
  confirming no regression from this subtask's changes).
- `ruff check pages/life_in_chapters.py` → no issues found (after adding the `# noqa: BLE001,
  S110` annotation to the disk-write-failure `except Exception: pass`, matching the codebase's
  established convention for intentional broad-except resilience blocks). `ruff format
  pages/life_in_chapters.py` → already formatted correctly.
- `mypy pages/life_in_chapters.py` → no issues found.

**Review Notes**:
Code Review: APPROVED — checks clean. `ruff check pages/life_in_chapters.py` → no issues;
`ruff format --check pages/life_in_chapters.py` → already formatted; `mypy pages/life_in_chapters.py`
→ no issues; `pytest tests/test_life_in_chapters.py tests/test_deep_cache.py -v --no-cov` → 90
passed (59 + 31), 0 failed. Manual diff review found no dead code, no secrets, no N+1/hot-path
issues, and the new `try/except Exception: pass` around `save_life_chapters_cache` is narrowly
scoped to only that call (annotated `# noqa: BLE001, S110`), matching the codebase's existing
broad-except-for-resilience convention — it does not swallow errors anywhere else in the block.

Assessed the flagged legacy-config sanitization guard specifically: (1) legitimate, not a
root-cause dodge — traced `components/sidebar.py` and confirmed real `_loaded_config` is always
written as a well-formed 4-string tuple (lines 342, 345, 363); the `(None, None, None)` shape only
exists in pre-existing test fixtures (6+ call sites in `tests/test_life_in_chapters.py`, e.g. lines
386/453/570/654/737/1034) that predate this subtask and were previously only ever index-accessed
(`loaded_config[2]`), never passed to `get_cache_key`. This new code path is the first to pass
`legacy_config` through to a function requiring a real path-like first element, so the guard is
isolating test-only fixture debt from a genuinely new integration point, not masking a reachable
production bug. Fixing it in already-`APPROVED` Subtask 1 was correctly out of scope, and the
existing-test convention forbids modifying passing tests, so the page-layer guard was the right
call. (2) No behavior change for real inputs — `test_cache_key_uses_legacy_config_when_no_broker_identity`
uses a well-formed 4-string tuple and asserts (line 990) it passes through unchanged to
`get_life_chapters_cache_key`. (3) Scope is appropriately narrow — a single `isinstance`/`len`/
all-`str` check immediately before the `cache_key` computation, falling back to the function's
existing `None` sentinel path; it touches nothing else and swallows no exceptions. No concerns
found; no changes requested.

Owner: NEEDS_REVISION — Independently re-read the full diff of `pages/life_in_chapters.py`
(lines 21-27, 551-596) and all 6 new tests in `tests/test_life_in_chapters.py` (lines 464-1067),
plus re-verified Subtask 1's `analysis_utils.py` implementation (lines 2132-2246) against the
`load_life_chapters_cache` acceptance criteria one more time.

**Correctness and test quality — sound, no changes requested to the wiring itself.** Traced every
acceptance criterion against the code: the disk-cache load/hit/miss branch sits correctly behind
the `#91` `_lic_cache_key` guard (line 554) and in front of `build_life_chapters`/
`detect_trip_periods` (lines 574-590); `label_listening_context` is unconditionally recomputed on
both the hit and miss paths (lines 577, 584), matching the Task Overview's documented rationale;
the `save_life_chapters_cache` call is wrapped in a narrowly-scoped `try/except Exception: pass`
that only covers that one call, satisfying AC5; `get_cache_key(*legacy_config)` genuinely raises
`TypeError` on `os.path.exists(None)` when fed the pre-existing tests' `(None, None, None)`
placeholder — confirmed by reading `get_cache_key`'s body (`analysis_utils.py:27-58`) and
`components/sidebar.py:321,345` showing real `_loaded_config` is always a well-formed 4-string
tuple — so the sanitization guard in `life_in_chapters.py` (lines 560-571) is a legitimate,
narrowly-scoped fix isolating test-fixture debt at a new integration boundary, not a code smell or
a root-cause dodge; I concur with the code reviewer's assessment. Tests are observable-behavior
assertions (call counts, call args, session-state contents), would catch a real regression, and
cover every item of Test Guidance (disk-hit, disk-miss, session-warm zero-overhead, broker vs.
legacy precedence, write-failure resilience). `pytest tests/test_life_in_chapters.py
tests/test_deep_cache.py -q --no-cov` → 90 passed. `mypy pages/life_in_chapters.py
analysis_utils.py` → no issues.

**Blocking issue — mandatory local quality gate is not clean.** `ruff format --check .` fails:
`tests/test_deep_cache.py` (Subtask 1's test file) needs reformatting. Reproduced with `ruff
format --diff tests/test_deep_cache.py`: `test_deterministic_same_inputs_same_key` (lines 572-577)
wraps two `get_life_chapters_cache_key(...)` calls across 3 lines each; at this repo's configured
`line-length = 100` (`pyproject.toml:46`), ruff wants each collapsed to one line (each fits in ~89
chars). This is a real, reproducible, currently-failing check — not a style preference — and
CLAUDE.md Section 7 states the local quality gate ("`ruff format --check .`" among the required
commands) is "mandatory — no exceptions" before any commit or push, and that "a failing CI is a
sign the gate was skipped locally." Root cause: Subtask 1's coder ran `ruff format
analysis_utils.py` (scoped to just that one file, per its own Verification notes) rather than
`ruff format .`, so the test file it also wrote was never run through the formatter; Subtask 1's
reviewer likewise only checked `ruff format --check` on `analysis_utils.py`. Confirmed via `ruff
format --check .` (whole-repo) that this is the *only* file affected — no other file in the diff
has a formatting violation.

**This is a mechanical, one-command fix** (`ruff format tests/test_deep_cache.py`, or `ruff format
.`) — no new test-writing is needed, no behavior changes, and it does not touch the substance of
either subtask's implementation. Because this PR group is about to close (this was the last
subtask) and CLAUDE.md's gate is non-negotiable, I am not approving until the repo is fully
`ruff format --check .`-clean. Status set back to `NEEDS_REVISION`; `current` left at 2.

**Action for the next cycle**: run `ruff format tests/test_deep_cache.py` (or `ruff format .`
repo-wide), re-run `ruff format --check .` to confirm zero files need reformatting, re-run the
scoped test suite (`pytest tests/test_life_in_chapters.py tests/test_deep_cache.py -q --no-cov`)
to confirm no regression, and update this subtask's Verification notes accordingly. No other
changes are requested — the wiring, the tests, and the legacy-config guard are all approved as
written.

---
