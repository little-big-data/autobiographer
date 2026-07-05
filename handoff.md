# Handoff

## Plan Status
status: COMPLETE

**Final summary**: Fixed the real-world bug where the installed `localizer` console-script entry
point (`localizer fetch google_timeline`) raised `ModuleNotFoundError: No module named
'analysis_utils'`, because `GoogleTimelinePlugin.fetch_records()` imported a bare top-level app
module unavailable to the installed package. The fix: (1) ported `load_google_timeline()` and its
private helpers verbatim into a new `localizer.plugins.google_timeline.parser` module inside the
`localizer` package (Subtask 1); (2) rewired `loader.py` to import from that new parser module
instead of `analysis_utils` (Subtask 2, the actual bug fix); (3) turned `analysis_utils.py`'s
former implementation into a minimal 3-name re-export shim pointing at the new parser module, so
top-level consumers (`tests/test_google_timeline.py`, `components/sidebar.py`, the legacy
`plugins/sources/google_timeline/loader.py`) kept working unmodified (Subtask 3); (4) added a
regression test that spawns the actual installed `localizer.exe` as a real OS subprocess from a
non-repo-root cwd to prove the bug cannot silently recur (Subtask 4). All four subtasks are
`APPROVED`. Final state: `ruff check .` 0 findings repo-wide, `ruff format --check .` clean (129
files), `mypy` clean both unscoped (14 files) and scoped to `packages/localizer/src` (26 files),
full top-level suite `pytest tests/` 837 passed / 0 failed, full localizer suite
`pytest packages/localizer/tests/` 212 passed / 0 failed. No follow-up work identified — the
localizer package now has zero runtime import dependency on the top-level `analysis_utils` module.

## Task Overview

**The bug**: `localizer fetch google_timeline` (the installed `localizer` console-script
entry point) raises `ModuleNotFoundError: No module named 'analysis_utils'`.
`GoogleTimelinePlugin.fetch_records()` in
`packages/localizer/src/localizer/plugins/google_timeline/loader.py` does a lazy
`from analysis_utils import load_google_timeline`, but `analysis_utils.py` is a bare
top-level module in the autobiographer app (not part of any installed package — confirmed
via `pip show autobiographer` and `[tool.setuptools.packages.find]` in the root
`pyproject.toml`, which only auto-discovers directories with `__init__.py`). It only
"works" today under `pytest` (root `pyproject.toml` sets
`[tool.pytest.ini_options] pythonpath = ["."]`) or when launched as
`streamlit run visualize.py` from the repo root (script-directory `sys.path` injection).
The installed console-script entry point (`venv/Scripts/localizer.exe`) gets neither
benefit, so every real user of `localizer fetch google_timeline` / `localizer sync` hits
this, regardless of cwd.

**The fix**: Port `load_google_timeline()` and its private dependents
(`_parse_latlng`, `_timeline_offset_minutes`, `_TIMELINE_SEMANTIC_LABELS`,
`_WHERE_WHEN_COLUMNS` — confirmed via repo-wide grep to be used *only* by
`load_google_timeline`, nothing else in `analysis_utils.py` references them) into the
`localizer` package, so the localizer-side plugin never has to reach into the top-level
app. `analysis_utils.py`'s copies become a re-export shim, mirroring the established
`core/fetch_utils.py` → `from localizer.fetch_utils import (...)` pattern from the prior
localizer migration (PR #112).

**Consumers that must keep working unchanged** (all confirmed via repo-wide grep):
- `tests/test_google_timeline.py` — imports `_WHERE_WHEN_COLUMNS`, `_parse_latlng`,
  `load_google_timeline` directly from `analysis_utils` (23 tests).
- `components/sidebar.py` — top-level `from analysis_utils import (..., load_google_timeline, ...)`,
  called at runtime inside `render_sidebar()`. `tests/test_sidebar.py` patches
  `sidebar.load_google_timeline` (the name as bound in `sidebar`'s own namespace), so it is
  unaffected by where the real implementation lives, as long as `analysis_utils.load_google_timeline`
  keeps existing.
- `plugins/sources/google_timeline/loader.py` (legacy, Streamlit-facing plugin from PR #111) —
  does a lazy `from analysis_utils import load_google_timeline` inside `load()`. Must NOT be
  touched. `tests/test_source_plugins.py` patches `"analysis_utils.load_google_timeline"`
  directly, which keeps working as long as that name is an attribute of the `analysis_utils`
  module (true for a re-exported name, same as a real one).

**Architecture context**: No prior `/feature-dev` or `/plan-feature` run occurred; this is a
direct bug-fix task with a fully diagnosed root cause supplied by the user. Three design
decisions were made during planning and are recorded here so later agents don't re-litigate
them:

1. **New module location**: `packages/localizer/src/localizer/plugins/google_timeline/parser.py`
   — a sibling module inside the *existing* `google_timeline` plugin package (created by the
   just-merged PR #111/#112 work), not a new top-level `localizer/parsers/` package and not
   `localizer/fetch_utils.py`. Rationale: this parsing logic is Google-Timeline-specific and has
   exactly one consumer inside `localizer` (`loader.py`) plus the `analysis_utils.py` shim: it
   doesn't belong in the generic, unrelated `fetch_utils.py` (checkpointing/retry logic only). The
   Swarm plugin (`packages/localizer/src/localizer/plugins/swarm/loader.py`) keeps its parsing
   inline in `fetch_records()` because it's short; Google Timeline's parser is ~120 lines with
   private helpers reused by two external callers (the shim and the plugin), which justifies a
   dedicated sibling module instead of inlining it into `loader.py`.
2. **Shim re-export surface is minimal**: `analysis_utils.py`'s shim re-exports exactly the three
   names actually imported elsewhere by name — `load_google_timeline`, `_WHERE_WHEN_COLUMNS`,
   `_parse_latlng`. `_timeline_offset_minutes` and `_TIMELINE_SEMANTIC_LABELS` are **not**
   re-exported; nothing outside the parser module references them, so they become purely internal
   implementation details of `localizer.plugins.google_timeline.parser`.
3. **Regression test invocation**: the subprocess regression test (Subtask 4) must spawn the
   actual installed console-script executable — resolved as
   `Path(sys.executable).parent / "localizer.exe"` on Windows / `Path(sys.executable).parent / "localizer"`
   on POSIX (both live next to the interpreter in an editable venv install; this is stable
   across machines, unlike relying on `PATH`) — via `subprocess.run`, **not** Click's
   `CliRunner` (masks the bug: runs in-process, inherits pytest's `sys.path`) and **not**
   `python -m localizer.cli` (also technically avoids the pytest `pythonpath` shim since `-m`
   only prepends the *current working directory*, not the repo root, to `sys.path` — but the
   literal installed entry point is the more faithful reproduction of what the user actually ran,
   per the bug report). `cwd` is set to a `tmp_path` directory that is *not* the repo root, and
   `LOCALIZER_DB_PATH` / `LOCALIZER_CONFIG_PATH` env vars point at temp files so the test never
   touches `~/.localizer/`.

Plan Review: APPROVED — DAG is a valid 4-node topological order (1→none, 2→1, 3→1, 4→{1,2}) with no cycles, test files are disjoint across all subtasks, acceptance criteria are falsifiable, and all five factual claims (helper usage, loader.py:117 import, consumer list completeness, `--set-file` config-key derivation, and the mypy `files` list excluding `packages/localizer` while including `analysis_utils.py`) were verified against the actual code.

## Current Subtask
current: 4

---

## Subtasks

### Subtask 1 — Port `load_google_timeline()` into `localizer.plugins.google_timeline.parser`

**Status**: APPROVED

**PR Group**: fix-google-timeline-console-script-import

**Depends On**: none

**Description**:
Create `packages/localizer/src/localizer/plugins/google_timeline/parser.py` containing a
verbatim (behavior-identical) port of `analysis_utils.py`'s `load_google_timeline()` function
and its four private dependents: `_TIMELINE_SEMANTIC_LABELS`, `_WHERE_WHEN_COLUMNS`,
`_parse_latlng()`, `_timeline_offset_minutes()`. This is purely additive — `analysis_utils.py`
is untouched in this subtask (that's Subtask 3, which depends on this one so the shim has
something to point at). Update the ported code's type hints to match this package's prevailing
style (`from __future__ import annotations` + `X | None` instead of `Optional[X]`, matching
`loader.py` in the same directory) — a style cleanup, not a behavior change.

**Acceptance Criteria**:
- [ ] `localizer.plugins.google_timeline.parser.load_google_timeline(path)` produces byte-for-byte
  the same output (same columns, same values, same row order) as
  `analysis_utils.load_google_timeline(path)` currently does, for the sample fixture used in
  `tests/test_google_timeline.py` (visits with/without frequent-place labels, an activity segment,
  a `timelinePath`-only segment that must be ignored, explicit vs. inferred UTC offsets).
- [ ] Missing file and empty-`semanticSegments` input both return an empty DataFrame with exactly
  the `_WHERE_WHEN_COLUMNS` columns, no exception raised.
- [ ] A file without a top-level `semanticSegments` key (legacy `Records.json`/Semantic Location
  History shape) raises `ValueError` mentioning `semanticSegments`.
- [ ] `reverse_geocoder` remains an optional, lazily-imported dependency (`try/except ImportError`)
  — the new module has no new hard dependency requirement in `packages/localizer/pyproject.toml`.
- [ ] `ruff check .`, `ruff format --check .` (unscoped, repo root) exit 0; `mypy` scoped to
  `packages/localizer/src` (bare unscoped `mypy` does **not** check `packages/localizer` — its
  `files` list in the root `pyproject.toml` doesn't include it, confirmed by reading that config)
  reports no issues; `pytest packages/localizer/tests/ -v --no-cov` passes.

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/google_timeline/parser.py` (new)
- `packages/localizer/tests/test_google_timeline_parser.py` (new)

**Test Guidance**:
- Mirror `tests/test_google_timeline.py`'s fixture (`_SAMPLE` payload: one HOME visit with a
  frequent-place label, one WORK visit without one, one UNKNOWN visit, one WALKING activity, one
  ignored `timelinePath`-only segment) and its `_write_timeline`/`_unix` helpers — copy-adapt
  rather than inventing new fixture shapes, so the two test suites stay easy to diff against each
  other.
- Stub `reverse_geocoder.search` (autouse fixture, same pattern as
  `packages/localizer/tests/test_google_timeline_plugin.py`'s `_stub_reverse_geocoder`) so the
  test suite is deterministic and doesn't pay the real geocode-index load cost.
- Cover: column-list-on-empty, ignoring `timelinePath`-only segments, timestamp UTC conversion,
  lat/lng parsing (`"40.5°, -74.25°"` and `"40.5, -74.25"` forms, malformed/empty strings for
  `_parse_latlng` directly), frequent-place label vs. humanized-semantic-type venue naming,
  activity `venue_category` prefixed `"activity:"`, explicit `startTimeTimezoneUtcOffsetMinutes`
  vs. RFC3339-offset fallback, both `ValueError` cases (bare `{"locations": [...]}"` and
  `{"timelineObjects": [...]}` legacy shapes), sort-by-timestamp + dedupe-on-timestamp.
- This is the riskiest subtask in the plan (transcription errors in a ~120-line port are easy to
  introduce silently) — after porting, diff the new module's logic line-by-line against
  `analysis_utils.py` lines ~265-450 to confirm no behavior drifted beyond the `Optional[X]` →
  `X | None` style change.

**Test Files**:
- `packages/localizer/tests/test_google_timeline_parser.py` (new) — 23 tests, RED-confirmed with
  `ModuleNotFoundError: No module named 'localizer.plugins.google_timeline.parser'`:
  `test_parse_latlng_parses_degree_string`, `test_parse_latlng_parses_without_degree_symbol`,
  `test_parse_latlng_returns_none_on_empty`, `test_parse_latlng_returns_none_on_malformed`,
  `test_parse_latlng_returns_none_on_single_value`, `test_returns_expected_columns`,
  `test_ignores_timeline_path_segments`, `test_rows_sorted_by_timestamp`,
  `test_visit_timestamp_is_utc_unix`, `test_visit_coordinates_parsed`,
  `test_frequent_place_label_used_when_available`, `test_semantic_type_humanized_when_no_label`,
  `test_unknown_semantic_type_humanized`, `test_activity_row_uses_start_point`,
  `test_activity_venue_category_has_activity_prefix`, `test_explicit_offset_used`,
  `test_offset_falls_back_to_rfc3339`, `test_reverse_geocode_fills_location`,
  `test_missing_file_returns_empty_frame`, `test_empty_segments_returns_empty_frame`,
  `test_legacy_records_format_raises`, `test_legacy_semantic_format_raises`,
  `test_dedupes_segments_sharing_the_same_timestamp` (added beyond the original suite to lock in
  `drop_duplicates("timestamp")` behavior, since the original top-level suite only exercises sort,
  not dedupe).
- Tester's notes for the coder, from reading `analysis_utils.py` lines 265-450: (1) preserve the
  exact narrow exception tuples — `_parse_latlng` catches `(ValueError, AttributeError)`,
  `_timeline_offset_minutes` catches `(ValueError, TypeError)`; (2) the per-segment
  `try/except (ValueError, TypeError)` around `pd.to_datetime(start).timestamp()` silently
  `continue`s past a bad `startTime` rather than raising — preserve this; (3) the
  `reverse_geocoder` import must stay function-local inside `load_google_timeline`
  (`try/except ImportError`), not hoisted to module top-level, to keep it optional; (4) the
  `df[_WHERE_WHEN_COLUMNS].sort_values("timestamp").drop_duplicates("timestamp")` reindex-then-
  sort-then-dedupe order must be preserved exactly; (5) `place_labels.get(place_id) or
  _TIMELINE_SEMANTIC_LABELS.get(semantic_type, semantic_type.replace("_", " ").title())` — the
  frequent-place label must win over humanized-semantic-type via this exact `or` short-circuit
  order; (6) style change is confined to `Optional[X]` → `X | None` plus
  `from __future__ import annotations` — no other signature/logic changes.

**Implementation Notes**:
Created `packages/localizer/src/localizer/plugins/google_timeline/parser.py` as a verbatim port
of `analysis_utils.py` lines 265-450: `_TIMELINE_SEMANTIC_LABELS`, `_WHERE_WHEN_COLUMNS`,
`_parse_latlng()`, `_timeline_offset_minutes()`, `load_google_timeline()`. Confirmed via a
line-by-line diff against the original source (re-read both blocks side by side) that the only
changes are the six pre-approved style items: `from __future__ import annotations` added at the
top, `Optional[tuple[float, float]]` -> `tuple[float, float] | None` in `_parse_latlng`'s
signature, and the module-local `reverse_geocoder` import kept function-local exactly as
before. All six tester-flagged pitfalls were preserved exactly: (1) `_parse_latlng`'s
`(ValueError, AttributeError)` and `_timeline_offset_minutes`'s `(ValueError, TypeError)`
exception tuples unchanged; (2) the per-segment `try/except (ValueError, TypeError)` around
`pd.to_datetime(start).timestamp()` that silently `continue`s past a bad `startTime`; (3)
`reverse_geocoder` import stays function-local inside `load_google_timeline` under
`try/except ImportError` (added `# noqa: PLC0415` since ruff's lazy-import rule fires on
function-local imports in this package, matching the existing `noqa` pattern in `loader.py` and
`_get_ruptures()` in `analysis_utils.py`); (4) the exact
`df[_WHERE_WHEN_COLUMNS].sort_values("timestamp").drop_duplicates("timestamp")` order; (5) the
`place_labels.get(place_id) or _TIMELINE_SEMANTIC_LABELS.get(...)` short-circuit order; (6) no
other signature/logic changes. Did not touch `analysis_utils.py` or `loader.py`, and did not edit
the tester's `test_google_timeline_parser.py` spec file.

Verification:
- `pytest packages/localizer/tests/test_google_timeline_parser.py -v --no-cov` — 23 passed.
- `ruff check .` (unscoped, repo root) — 3 pre-existing errors, all outside this subtask's scope
  and none in `parser.py`: an `S603` subprocess-check finding and an `I001` import-order finding
  in `packages/localizer/tests/test_google_timeline_cli_regression.py` (Subtask 4's test file), an
  `I001` finding in `tests/test_analysis_utils_google_timeline_shim.py` (Subtask 3's test file),
  and an `I001` finding in this subtask's own `test_google_timeline_parser.py` (the tester-written
  spec file, which I was instructed not to edit). `parser.py` itself has zero ruff findings.
- `ruff format --check .` — 1 file would be reformatted:
  `test_google_timeline_cli_regression.py` (Subtask 4's file, out of scope). `parser.py` is
  already correctly formatted.
- `mypy packages/localizer/src` — "Success: no issues found in 26 source files."
- `pytest packages/localizer/tests/ -v --no-cov` (full localizer suite) — 210 passed, 2 failed.
  Both failures are expected and out of this subtask's scope: `test_google_timeline_plugin.py::
  test_fetch_records_does_not_require_analysis_utils_importable` (Subtask 2's not-yet-implemented
  test, still `RED`) and `test_google_timeline_cli_regression.py::
  test_installed_console_script_fetches_google_timeline_without_module_not_found_error` (Subtask
  4's not-yet-implemented test, still `RED`) — both correctly still fail with the original
  `ModuleNotFoundError: No module named 'analysis_utils'` bug via `loader.py:117`, which Subtask 2
  fixes next. No regressions among the 210 passing tests.

**Review Notes**:
(filled by owner agent)

Owner Review: APPROVED — Independently re-read both `parser.py` and `analysis_utils.py` lines
265-450 side by side; confirmed byte-for-byte identical logic modulo the four disclosed style
items (`from __future__ import annotations`, `Optional[X]` -> `X | None`, a docstring `:func:`
role removed since no local Sphinx target exists, and an added `# noqa: PLC0415` matching this
subpackage's lint config). Spot-checked the three riskiest points myself: exception tuples
`(ValueError, AttributeError)` / `(ValueError, TypeError)` unchanged, the `place_labels.get(...)
or _TIMELINE_SEMANTIC_LABELS.get(...)` short-circuit order unchanged, and the exact
`sort_values("timestamp").drop_duplicates("timestamp")` order unchanged. Cross-checked every Test
Guidance bullet against the 23 tests in `test_google_timeline_parser.py` — full coverage, no gaps.
Independently re-ran all checks: 23/23 parser tests pass; `mypy packages/localizer/src` clean (26
files); `parser.py` alone clean on both `ruff check` and `ruff format --check`; the 3 ruff findings
and 1 format finding are confirmed confined to Subtask 3/4's files; full `packages/localizer/tests/`
suite is 210 passed / 2 failed, both expected pre-fix RED reproductions of the exact bug (Subtask
2/4's not-yet-implemented tests), no regressions. Acceptance criteria fully satisfied; test quality
is high (verifies observable output, not internals). Advancing to Subtask 2.

Code Review: APPROVED — Independent line-by-line diff of `parser.py` against `analysis_utils.py`
lines 265-450 confirms all six tester-flagged pitfalls preserved exactly: (1) `_parse_latlng`'s
`(ValueError, AttributeError)` and `_timeline_offset_minutes`'s `(ValueError, TypeError)` exception
tuples unchanged; (2) silent `continue` on bad `startTime` preserved; (3) `reverse_geocoder` import
stays function-local under `try/except ImportError`; (4) exact
`sort_values("timestamp").drop_duplicates("timestamp")` order preserved; (5) exact `or`
short-circuit for frequent-place-label-over-humanized-type; (6) only intentional changes are
`from __future__ import annotations`, `Optional[X]` → `X | None`, a docstring cross-ref adaptation,
and a disclosed `# noqa: PLC0415` comment (no behavior change). Re-ran all checks independently:
`pytest test_google_timeline_parser.py` 23 passed; `mypy packages/localizer/src` clean (26 files);
`ruff check .` 3 findings, all outside scope (Subtask 3/4 files + this subtask's own
tester-authored test file's import order) with zero findings in `parser.py`; `ruff format --check .`
1 file needs reformatting (Subtask 4's file, out of scope), `parser.py` already formatted; full
`packages/localizer/tests/` suite 210 passed / 2 failed, both expected RED (Subtask 2 and 4's
not-yet-implemented tests) with no regressions. All results match the coder's Implementation Notes
exactly.

---

### Subtask 2 — Rewire `GoogleTimelinePlugin.fetch_records()` to stop importing `analysis_utils`

**Status**: APPROVED

**PR Group**: fix-google-timeline-console-script-import

**Depends On**: 1

**Description**:
Change the lazy `from analysis_utils import load_google_timeline` in
`packages/localizer/src/localizer/plugins/google_timeline/loader.py::fetch_records()` (line 117)
to `from localizer.plugins.google_timeline.parser import load_google_timeline`. This is the line
that directly causes the reported bug — after this change, the localizer-side plugin has zero
dependency on the top-level app being on `sys.path`. Also fix two now-stale docstring/comment
references to `analysis_utils.load_google_timeline()` in `loader.py` (module docstring and
`fetch_records()` docstring) so they accurately describe the new import source.

**Acceptance Criteria**:
- [ ] `loader.py` no longer contains the string `analysis_utils` anywhere (grep-checkable).
- [ ] With `sys.modules["analysis_utils"]` forced to `None` (simulating "the module cannot be
  imported," the exact real-world failure mode), `GoogleTimelinePlugin(timeline_path=...).fetch_records()`
  still successfully yields records from a valid `Timeline.json` fixture — proving the plugin has
  no runtime dependency on `analysis_utils` being importable. This must currently (pre-fix) fail,
  since today's lazy import inside `fetch_records()` would raise
  `ImportError: import of analysis_utils halted; None in sys.modules`.
- [ ] All pre-existing behavioral tests in `packages/localizer/tests/test_google_timeline_plugin.py`
  (23 tests from the prior PR) still pass unmodified — this change swaps an import source, not
  behavior.
- [ ] `ruff check .`, `ruff format --check .` exit 0 unscoped; `mypy` scoped to
  `packages/localizer/src` reports no issues; `pytest packages/localizer/tests/ -v --no-cov` passes.

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/google_timeline/loader.py` (edit: swap the import,
  fix two stale docstring references)
- `packages/localizer/tests/test_google_timeline_plugin.py` (extended — new test only, no edits to
  the 23 existing tests)

**Test Guidance**:
- Add exactly one new test to `test_google_timeline_plugin.py` (keeps this subtask's touched test
  file the same file as Subtask 1 leaves alone — Subtask 1's new file is
  `test_google_timeline_parser.py`, disjoint from this one):
  `test_fetch_records_does_not_require_analysis_utils_importable`, using
  `monkeypatch.setitem(sys.modules, "analysis_utils", None)` before calling `fetch_records()`,
  with a valid `Timeline.json` fixture (reuse `_timeline_payload_with_visit_and_activity()` already
  in this file), asserting the yielded record list is non-empty and no exception propagates.
- Confirm this test is RED against current HEAD (pre-fix) with the exact `ImportError` message
  above, and GREEN once the import is swapped — this is the load-bearing assertion for the whole
  subtask, sharper than "no code changes" since it exercises the actual failure mode rather than
  just checking the import statement's text.
- Run the full pre-existing 23-test file afterward to confirm zero regressions from the docstring
  edits (docstrings aren't tested, but confirms nothing else in the diff broke behavior).

**Test Files**:
- `packages/localizer/tests/test_google_timeline_plugin.py` (extended, disjoint from Subtask 1's
  new file) — exactly one new test appended, zero edits to the 23 pre-existing tests:
  `test_fetch_records_does_not_require_analysis_utils_importable`, using
  `monkeypatch.setitem(sys.modules, "analysis_utils", None)`. RED-confirmed with:
  ```
  loader.py:117: from analysis_utils import load_google_timeline  # noqa: PLC0415
  E   ModuleNotFoundError: import of analysis_utils halted; None in sys.modules
  1 failed, 23 deselected in 1.15s
  ```
  Full-file regression run confirms all 23 pre-existing tests still pass: `1 failed, 23 passed`.

**Implementation Notes**:
In `packages/localizer/src/localizer/plugins/google_timeline/loader.py`, changed the lazy
`from analysis_utils import load_google_timeline` (line 117) to
`from localizer.plugins.google_timeline.parser import load_google_timeline` (wrapped in
parens to satisfy `ruff format`, `# noqa: PLC0415` retained). Also fixed the two stale
`analysis_utils.load_google_timeline()` references: the module docstring (now cites
`localizer.plugins.google_timeline.parser.load_google_timeline()` and
`tests/test_google_timeline_parser.py` instead of the old top-level test file) and the
`fetch_records()` docstring (same rewording). Did not touch the test file's 23 pre-existing
tests; the tester's `test_fetch_records_does_not_require_analysis_utils_importable` was
already appended and required no edits.

Verification:
- `pytest packages/localizer/tests/test_google_timeline_plugin.py -v --no-cov` — 24 passed
  (23 pre-existing + the new test).
- Grep for `analysis_utils` in `loader.py` — 0 matches, confirmed removed entirely.
- `ruff check .` (unscoped, repo root) — same 3 pre-existing errors as Subtask 1 reported,
  all in Subtask 3/4's out-of-scope test files (`test_google_timeline_cli_regression.py`
  S603 + I001, `test_analysis_utils_google_timeline_shim.py` I001); zero findings in
  `loader.py`.
- `ruff format --check .` — same 1 pre-existing out-of-scope finding
  (`test_google_timeline_cli_regression.py`, Subtask 4's file); `loader.py` already
  formatted.
- `mypy packages/localizer/src` — "Success: no issues found in 26 source files."
- `pytest packages/localizer/tests/ -v --no-cov` (full localizer suite) — **212 passed, 0
  failed** (up from 210 passed / 2 failed after Subtask 1). Both previously-RED tests are now
  GREEN: this subtask's own new test, and Subtask 4's
  `test_installed_console_script_fetches_google_timeline_without_module_not_found_error`
  (verified individually too: 1 passed in 3.78s) — Subtask 4's regression test only depended
  on Subtasks 1 and 2, both now landed, so it passes without any changes to its own file.

**Review Notes**:
(filled by owner agent)

Code Review: APPROVED — Read `loader.py` in full; confirmed the import at line 119-121 correctly
swaps to `from localizer.plugins.google_timeline.parser import load_google_timeline`, the string
`analysis_utils` no longer appears anywhere in the file (grep confirms 0 matches), and both stale
docstring references (module docstring lines 5-6, `fetch_records()` docstring lines 94-95) were
accurately updated to cite the new parser module and `test_google_timeline_parser.py`, not just
broken/removed. No dead code, secrets, or hot-path issues found in either touched file.
Independently re-ran all checks: `pytest test_google_timeline_plugin.py` 24 passed (23 pre-existing
+ new test); `pytest test_google_timeline_cli_regression.py` 1 passed, confirming Subtask 4's test
now passes since it only depended on Subtasks 1+2; `mypy packages/localizer/src` clean (26 files);
`ruff check .` 3 findings, all confined to Subtask 3/4's out-of-scope files (S603 + 2x I001), zero
in `loader.py`; `ruff format --check .` 1 file needs reformatting (Subtask 4's file, out of scope),
`loader.py` already formatted; full `packages/localizer/tests/` suite 212 passed, 0 failed. All
results match the coder's Implementation Notes exactly.

Owner Review: APPROVED — Independently read `loader.py` in full. Confirmed the import swap at
lines 119-121 (`from localizer.plugins.google_timeline.parser import load_google_timeline`) is
the only import mechanism for `load_google_timeline` in this file, grep confirms zero occurrences
of `analysis_utils` anywhere in `loader.py`, and both the module docstring (lines 1-10) and
`fetch_records()` docstring (lines 92-102) accurately describe the new parser module and its test
file. This is the core bug fix and it is correct and minimal — no unnecessary changes beyond the
import swap and the two stale docstring references. Independently re-ran every check: `pytest
test_google_timeline_plugin.py` 24/24 passed (23 pre-existing behavioral tests unmodified + the
new `test_fetch_records_does_not_require_analysis_utils_importable`, which exercises the actual
real-world failure mode via `monkeypatch.setitem(sys.modules, "analysis_utils", None)`, not just a
text check on the import statement); `mypy packages/localizer/src` clean (26 files); `ruff check .`
3 findings, all confined to Subtask 3/4's not-yet-implemented files, zero in `loader.py`; `ruff
format --check .` 1 out-of-scope file needs reformatting (Subtask 4's), `loader.py` already
formatted. Confirmed the whole point of this plan: read
`test_google_timeline_cli_regression.py` in full and independently ran it — it resolves the real
installed `venv/Scripts/localizer.exe` (verified the file exists on disk, so this run genuinely
exercised the fix rather than skipping), spawns it as a true OS subprocess with `cwd` set to a
`tmp_path` outside the repo and `PYTHONPATH` stripped from `env` (the exact conditions that
previously reproduced `ModuleNotFoundError: No module named 'analysis_utils'` per the RED-confirmed
capture recorded in this subtask's Test Files section), asserts no `ModuleNotFoundError`/
`analysis_utils` string in combined output, exit code 0, and >=1 row written to the DuckDB store —
and it passed (1 passed in 3.82s). Full `packages/localizer/tests/` suite independently re-run:
212 passed, 0 failed. Test quality is high: the new unit test exercises the actual failure mode
(forced `ImportError` on `analysis_utils`) rather than a superficial check, and the regression test
is a faithful end-to-end reproduction of the user-reported bug. No test-guidance gaps. This
subtask fully resolves the reported bug. Advancing to Subtask 3.

---

### Subtask 3 — Turn `analysis_utils.load_google_timeline` into a re-export shim

**Status**: APPROVED

**PR Group**: fix-google-timeline-console-script-import

**Depends On**: 1

**Description**:
Remove the `load_google_timeline()` function body and its four private dependents
(`_TIMELINE_SEMANTIC_LABELS`, `_WHERE_WHEN_COLUMNS`, `_parse_latlng`,
`_timeline_offset_minutes`) from `analysis_utils.py` (currently lines ~265-450) and replace them
with a top-of-file re-export shim, mirroring `core/fetch_utils.py`'s established pattern:

```python
from localizer.plugins.google_timeline.parser import (  # noqa: F401
    _WHERE_WHEN_COLUMNS,
    _parse_latlng,
    load_google_timeline,
)
```

The import must go at the top of the file alongside `analysis_utils.py`'s other imports (not
inline at the old location) — ruff's `E402` (module-level-import-not-at-top-of-file, part of the
selected `"E"` rule set) will reject a bare import statement placed after other module-level code,
which the old location is. Run `ruff check --fix .` to let ruff auto-sort the new import into the
existing block.

**Acceptance Criteria**:
- [ ] `analysis_utils.load_google_timeline is localizer.plugins.google_timeline.parser.load_google_timeline`
  (identity check, not just equal-output — proves this is a re-export, not a duplicated copy that
  could drift).
- [ ] `analysis_utils._WHERE_WHEN_COLUMNS is localizer.plugins.google_timeline.parser._WHERE_WHEN_COLUMNS`
  and `analysis_utils._parse_latlng is localizer.plugins.google_timeline.parser._parse_latlng`
  (same identity check for the two other re-exported names).
- [ ] `tests/test_google_timeline.py` (23 tests, imports `_WHERE_WHEN_COLUMNS`, `_parse_latlng`,
  `load_google_timeline` from `analysis_utils`) passes unmodified — zero edits to that file.
- [ ] `tests/test_source_plugins.py`'s `patch("analysis_utils.load_google_timeline")` tests and
  `tests/test_sidebar.py`'s `patch.object(sidebar, "load_google_timeline", ...)` test both pass
  unmodified — zero edits to either file.
- [ ] `ruff check .`, `ruff format --check .`, `mypy` (unscoped — `analysis_utils.py` **is** in the
  root `pyproject.toml`'s `[tool.mypy] files` list, so bare `mypy` does check this file), and
  `pytest` (full top-level suite, `tests/`) all exit 0.

**Files to Touch**:
- `analysis_utils.py` (edit: remove the ported block, add the shim import at the top)
- `tests/test_analysis_utils_google_timeline_shim.py` (new)

**Test Guidance**:
- New test file asserts the three identity checks above directly
  (`import analysis_utils; import localizer.plugins.google_timeline.parser as parser_mod; assert
  analysis_utils.load_google_timeline is parser_mod.load_google_timeline`, etc.) — this is the
  sharpest possible proof of "shim, not duplicate," since a copy-pasted duplicate would pass every
  *behavioral* test but fail this identity check.
- Do not duplicate `tests/test_google_timeline.py`'s 23 behavioral tests here; this subtask's job
  is proving the shim wiring, not re-testing parsing logic already covered by Subtask 1's
  `test_google_timeline_parser.py` and the pre-existing top-level test file.
- Regression check: run `tests/test_google_timeline.py`, `tests/test_source_plugins.py`, and
  `tests/test_sidebar.py` (all three confirmed via grep to reference `load_google_timeline` by
  name) to confirm zero behavior change for any of the three consumers identified in the Task
  Overview.

**Test Files**:
- `tests/test_analysis_utils_google_timeline_shim.py` (new, top-level `tests/` per this subtask's
  Files to Touch, not `packages/localizer/tests/`) — 3 identity-check tests, RED-confirmed with
  `ModuleNotFoundError: No module named 'localizer.plugins.google_timeline.parser'` (a legitimate
  compound-dependency RED: both this subtask's shim and Subtask 1's parser module are missing
  right now; will go GREEN once both land):
  `test_load_google_timeline_is_reexported_from_parser_module`,
  `test_where_when_columns_is_reexported_from_parser_module`,
  `test_parse_latlng_is_reexported_from_parser_module`.

**Implementation Notes**:
Added the re-export shim import to `analysis_utils.py`'s top-of-file import block (right after
`import pandas as pd`):
```python
from localizer.plugins.google_timeline.parser import (  # noqa: F401
    _WHERE_WHEN_COLUMNS,
    _parse_latlng,
    load_google_timeline,
)
```
Removed the old block — the `_TIMELINE_SEMANTIC_LABELS` comment+dict, `_WHERE_WHEN_COLUMNS` list,
`_parse_latlng()`, `_timeline_offset_minutes()`, and `load_google_timeline()` (previously lines
265-450) — entirely; `infer_residency_periods` now follows directly after
`load_swarm_data`'s tail (no orphaned blank-line gaps). `_timeline_offset_minutes` and
`_TIMELINE_SEMANTIC_LABELS` were deliberately **not** re-exported (per Task Overview design
decision 2) since nothing outside the parser module references them by name, and no test expects
them on `analysis_utils`. Ran `ruff check --fix .` which auto-sorted the new import into the
existing import block (merged it with the `numpy`/`pandas` group, no blank line before it — ruff's
own isort choice, not manually placed) and `ruff format .` which reformatted one unrelated
out-of-scope file (`packages/localizer/tests/test_google_timeline_cli_regression.py`, Subtask 4's
file). Did not edit `tests/test_analysis_utils_google_timeline_shim.py` (only `ruff check --fix`
reordered its two import lines alphabetically, standard isort behavior, no content change) or any
other test file.

Verification:
- `pytest tests/test_analysis_utils_google_timeline_shim.py -v --no-cov` — 3 passed (all identity
  checks).
- `pytest tests/test_google_timeline.py tests/test_source_plugins.py tests/test_sidebar.py -v
  --no-cov` — 86 passed, 0 failed, all three consumer files unmodified.
- `ruff check .` (unscoped, repo root) — 1 finding, `S603` in
  `test_google_timeline_cli_regression.py` (Subtask 4's out-of-scope file, pre-existing per Subtask
  1/2's notes); zero findings in `analysis_utils.py` or the new shim test file.
- `ruff format --check .` — 129 files already formatted, 0 pending.
- `mypy` (unscoped) — "Success: no issues found in 14 source files."
- `pytest tests/ -v --no-cov` (full top-level suite) — **837 passed**, 0 failed.
- `pytest packages/localizer/tests/ -v --no-cov` (full localizer suite) — **212 passed**, 0 failed,
  no regressions.

**Review Notes**:
(filled by owner agent)

Code Review: APPROVED — Read `analysis_utils.py` in full (3918 lines). Confirmed the
`load_google_timeline()` function body and its four private dependents
(`_TIMELINE_SEMANTIC_LABELS`, `_WHERE_WHEN_COLUMNS`, `_parse_latlng`,
`_timeline_offset_minutes`) were genuinely removed — the `git diff` shows a clean
5-insertion/188-deletion change with no leftover duplicate code, and a grep for all five
names inside `analysis_utils.py` returns only the three-name shim import block (lines
10-14). The re-export shim (`from localizer.plugins.google_timeline.parser import
(_WHERE_WHEN_COLUMNS, _parse_latlng, load_google_timeline)  # noqa: F401`) sits at the top
of the file alongside the other imports (line 10, right after `import pandas as pd`), not
inline at the old location — confirms no E402 risk. Confirmed `_timeline_offset_minutes`
and `_TIMELINE_SEMANTIC_LABELS` are genuinely not re-exported and not referenced anywhere
else in the repo by those names (repo-wide grep: both names appear only inside
`parser.py` and in docstrings/comments referencing them, never in `analysis_utils.py` or
any consumer). Confirmed `components/sidebar.py` and the legacy
`plugins/sources/google_timeline/loader.py` still reference `load_google_timeline`
unchanged. Ran all required checks independently:
- `pytest tests/test_analysis_utils_google_timeline_shim.py -v --no-cov` — 3 passed (all
  three `is`-identity checks, not equal-output checks).
- `pytest tests/test_google_timeline.py tests/test_source_plugins.py tests/test_sidebar.py
  -v --no-cov` — 86 passed; `git diff --stat` confirms zero changes to these three files.
- `ruff check .` (unscoped) — 1 finding, `S603` in
  `packages/localizer/tests/test_google_timeline_cli_regression.py` (Subtask 4's
  out-of-scope file); zero findings in any Subtask 3 file.
- `ruff format --check .` — 129 files already formatted, 0 pending.
- `mypy` (unscoped) — "Success: no issues found in 14 source files."
- `pytest tests/ -v --no-cov` (full top-level suite) — 837 passed, 0 failed.
- `pytest packages/localizer/tests/ -v --no-cov` (full localizer suite) — 212 passed, 0
  failed, no regressions.
No dead code, secrets, N+1 patterns, or missing null/error handling found in the diff.

Owner Review: APPROVED — Independently re-read `analysis_utils.py`'s top imports (lines 1-14) and
the post-removal join point (lines 265-270) plus the new `tests/test_analysis_utils_google_timeline_shim.py`.
Confirmed the shim is clean: the re-export sits correctly among the other top-level imports (no
E402 risk), the old 188-line block is fully gone with no dead code or orphaned gaps
(`load_swarm_data`'s tail flows straight into `infer_residency_periods`), and the re-export surface
is exactly the three approved names (`load_google_timeline`, `_WHERE_WHEN_COLUMNS`, `_parse_latlng`)
— repo-wide grep confirms `_TIMELINE_SEMANTIC_LABELS`/`_timeline_offset_minutes` are referenced only
inside `parser.py` and its own test, never re-exported or referenced elsewhere, per design decision 2.
Independently re-ran every required check: `pytest test_analysis_utils_google_timeline_shim.py` 3/3
identity checks passed; `pytest test_google_timeline.py test_source_plugins.py test_sidebar.py` 86
passed, all three consumer files unmodified per this subtask's contract; `mypy` (unscoped) clean (14
source files); `ruff check .` 1 finding, confined to Subtask 4's not-yet-implemented file, zero in
any Subtask 3 file; `ruff format --check .` 129 files clean; full `pytest tests/` 837 passed, 0
failed; full `pytest packages/localizer/tests/` 212 passed, 0 failed. All Test Guidance items
covered: three identity (`is`) checks present, no duplication of `test_google_timeline.py`'s 23
behavioral tests, and all three named consumers re-verified unmodified. Acceptance criteria fully
satisfied, test quality is high (identity checks are strictly sharper than equal-output checks, per
this subtask's own stated rationale). Advancing to Subtask 4.

---

### Subtask 4 — Regression test: installed console script no longer raises `ModuleNotFoundError`

**Status**: APPROVED

**PR Group**: fix-google-timeline-console-script-import

**Depends On**: 1, 2

**Description**:
Add the regression test that proves this exact bug class cannot silently recur: spawn the
actually-installed `localizer` console-script entry point as a real OS subprocess (not Click's
`CliRunner`, which runs in-process and inherits pytest's `sys.path` — see Task Overview design
decision 3) from a working directory that is **not** the repo root, with a valid `Timeline.json`
fixture, and assert it does not raise `ModuleNotFoundError` and does write a record to the store.

By the time this subtask's coder phase runs, Subtasks 1-2 (the actual fix) are already `APPROVED`
— this subtask legitimately may require **zero** production code changes; its coder's job is to
confirm the test is GREEN against the already-fixed code (it will have been written RED against
pre-fix HEAD during the test-ahead phase, correctly reproducing the real bug before any fix
landed).

**Acceptance Criteria**:
- [ ] The test resolves the installed console-script path as
  `Path(sys.executable).parent / "localizer.exe"` (Windows) or
  `Path(sys.executable).parent / "localizer"` (POSIX) and skips with a clear message (not an
  opaque failure) if that file doesn't exist — pointing at
  `pip install -e packages/localizer/` as the fix, per this repo's documented monorepo setup.
- [ ] The subprocess is run with `cwd` set to a `tmp_path` directory (never the repo root) and
  `env` containing `LOCALIZER_DB_PATH` and `LOCALIZER_CONFIG_PATH` pointing at paths under
  `tmp_path` — the real `~/.localizer/` is never touched.
- [ ] Invoking `localizer fetch google_timeline --set-file <fixture Timeline.json>` this way exits
  with code 0, and neither stdout nor stderr contains `ModuleNotFoundError` or
  `No module named 'analysis_utils'`.
- [ ] After the subprocess exits, opening the temp DuckDB file directly via
  `LocalizerStore(tmp_db_path).query_places(source_id="google_timeline")` (or equivalent) returns
  at least one row.
- [ ] The test completes in well under a minute — a `timeout=` is passed to `subprocess.run` so a
  hang fails loudly instead of blocking CI indefinitely.

**Files to Touch**:
- `packages/localizer/tests/test_google_timeline_cli_regression.py` (new)

**Test Guidance**:
- Build a minimal one-visit-segment `Timeline.json` fixture inline (reuse the same payload shape
  as Subtask 1/2's fixtures) and write it to `tmp_path` before spawning the subprocess.
- Do not attempt to monkeypatch `reverse_geocoder.search` for this test — monkeypatching cannot
  cross a subprocess boundary. Accept the one-time real geocode-index load cost; keep the fixture
  to a single segment to keep this fixed cost the only cost.
- Explicitly strip any inherited `PYTHONPATH` from the subprocess's `env` dict before spawning, so
  a developer's stray `PYTHONPATH=<repo-root>` in their shell can't accidentally mask the bug this
  test exists to catch.
- This test is intentionally slower than a unit test (real subprocess spawn + real geocode-index
  load) — that's expected and acceptable for a single regression test; do not add more than this
  one subprocess-spawning test to keep the suite's runtime impact minimal.
- Confirm the test fails with exactly `ModuleNotFoundError: No module named 'analysis_utils'` (in
  the subprocess's captured stderr) when run against pre-fix HEAD, and passes cleanly once
  Subtasks 1-2 have landed — this dual confirmation (RED reproduces the *exact* reported bug, GREEN
  proves the fix) is the acceptance bar for this subtask, not just "test passes."

**Test Files**:
- `packages/localizer/tests/test_google_timeline_cli_regression.py` (new) — 1 test,
  `test_installed_console_script_fetches_google_timeline_without_module_not_found_error`.
  Resolves `venv/Scripts/localizer.exe`, spawns it via `subprocess.run(..., cwd=<tmp_path
  subdir>, timeout=90)` with `LOCALIZER_DB_PATH`/`LOCALIZER_CONFIG_PATH` pointing at temp paths
  and `PYTHONPATH` stripped from `env`, invokes `localizer fetch google_timeline --set-file
  <fixture>`, asserts no `ModuleNotFoundError`/`analysis_utils` in combined output, exit code 0,
  and >=1 row in `LocalizerStore(db_path).query_places(source_id="google_timeline")`. Does not
  stub `reverse_geocoder` (can't cross the process boundary); fixture kept to one segment to
  minimize that one-time real-index-load cost. RED-confirmed — captured stderr reproduces the
  exact reported bug:
  ```
  File "...\packages\localizer\src\localizer\plugins\google_timeline\loader.py", line 117, in fetch_records
      from analysis_utils import load_google_timeline  # noqa: PLC0415
  ModuleNotFoundError: No module named 'analysis_utils'
  ```
  Failed on the first assertion as designed (not an unrelated failure). Wall time 1.12-1.20s
  (fails fast, before reaching the real geocode-index load); GREEN run will be slower once the
  import succeeds but should stay well under the 90s timeout.

**Implementation Notes**:
No production code changes were needed — Subtasks 1 and 2 (both `APPROVED`) already fully
resolve the bug this test guards against, exactly as the plan anticipated
("this subtask legitimately may require zero production code changes"). The tester's
`test_installed_console_script_fetches_google_timeline_without_module_not_found_error`
already passed independently against the current HEAD.

The one fix made in this subtask: the test file itself
(`packages/localizer/tests/test_google_timeline_cli_regression.py`) had a lingering `S603`
ruff finding (`subprocess` call: check for execution of untrusted input) at the
`subprocess.run(...)` call, previously flagged as out-of-scope by Subtasks 1-3's coders/
reviewers since it belonged to this file. Since this is now this file's own subtask, I
resolved it in-scope by adding a narrow `# noqa: S603` with an inline comment explaining why
it's safe here: the call spawns a known local installed executable (resolved from
`sys.executable`'s own directory, not from `PATH` or user input) with a fixed,
test-controlled argument list — not untrusted/attacker-controlled input. No `ruff check --fix`
or `ruff format` auto-fix was needed beyond this manual noqa addition; `ruff format --check .`
was already clean before and after (129 files, no reformatting needed for this file).

Verification (all run from repo root with the venv Python,
`C:/Users/johns/Code/autobiographer/venv/Scripts/python.exe`):
- `pytest packages/localizer/tests/test_google_timeline_cli_regression.py -v --no-cov` — 1
  passed (both before and after the noqa edit; the edit was comment-only, no behavior change).
- `ruff check .` (unscoped, repo root) — before the fix: 1 finding (`S603` in this subtask's
  file). After adding the scoped `# noqa: S603` with justification: **All checks passed!**
  (0 findings repo-wide).
- `ruff format --check .` — 129 files already formatted, 0 pending, both before and after.
- `mypy packages/localizer/src` (scoped) — "Success: no issues found in 26 source files."
- `pytest tests/ -v --no-cov` (full top-level suite) — **837 passed**, 0 failed.
- `pytest packages/localizer/tests/ -v --no-cov` (full localizer suite) — **212 passed**, 0
  failed.

All 4 subtasks are now implementation-complete with a fully green full-suite run on both test
trees; the reported bug (`ModuleNotFoundError: No module named 'analysis_utils'` from the
installed `localizer` console-script entry point) is resolved and regression-locked.

**Review Notes**:
(filled by owner agent)

Code Review: APPROVED — checks clean. Read `test_google_timeline_cli_regression.py` in full (171
lines): the test logic matches exactly what the Test Files section describes from the test-ahead
phase (resolve `venv/Scripts/localizer.exe`, skip with a clear message if absent, build a one-visit
fixture, spawn via `subprocess.run` with `cwd` outside the repo and `LOCALIZER_DB_PATH`/
`LOCALIZER_CONFIG_PATH`/stripped `PYTHONPATH` in `env`, assert no `ModuleNotFoundError`/
`analysis_utils` string in output, exit code 0, `timeout=90`, then reopen the DuckDB file via
`LocalizerStore(...).query_places(...)` and assert >=1 row). The coder's only change — a
`# noqa: S603` on the `subprocess.run(...)` line with an inline justification (lines 130-132) — is
substance-unchanged from the tester's version and legitimate: the call spawns a fixed, resolved
local executable path (from `sys.executable`'s own directory, not `PATH`) with a fixed,
test-controlled argument list (temp fixture paths built inside the test), not attacker/user-
controlled input, so ruff's untrusted-subprocess-input concern doesn't apply here.

Independently re-ran every required check from repo root with the venv Python:
- `pytest packages/localizer/tests/test_google_timeline_cli_regression.py -v --no-cov` — 1 passed.
- `ruff check .` (unscoped) — **All checks passed!** (0 findings repo-wide, confirming the coder's
  claim that this was the last remaining finding).
- `ruff format --check .` — 129 files already formatted, 0 pending.
- `mypy packages/localizer/src` (scoped) — "Success: no issues found in 26 source files."
- `pytest tests/ -v --no-cov` (full top-level suite) — **837 passed**, 0 failed.
- `pytest packages/localizer/tests/ -v --no-cov` (full localizer suite) — **212 passed**, 0 failed.
- Repo-wide grep for `analysis_utils` inside `packages/localizer/` — 4 files match, but every
  occurrence is a docstring/comment/regression-string-assertion (e.g. this test's own docstring
  narrating the historical bug, and its `assert "No module named 'analysis_utils'" not in
  combined_output` line; Subtask 2's `test_fetch_records_does_not_require_analysis_utils_importable`
  intentionally forcing `sys.modules["analysis_utils"] = None`; `parser.py`'s docstring crediting
  its origin). A stricter grep for an actual `from/import analysis_utils` statement anywhere under
  `packages/localizer/` returns zero matches — confirming the whole point of this plan: the
  localizer package has no runtime import dependency on the top-level `analysis_utils` module.

No dead code, secrets, N+1 patterns, or missing null/error handling found. This is the final
subtask; all automated gates are green and the plan's stated bug is verifiably fixed and
regression-locked.

Owner Review: APPROVED — Independently re-verified all checks from repo root with the venv
Python: `pytest packages/localizer/tests/test_google_timeline_cli_regression.py -v --no-cov` 1
passed; `ruff check .` 0 findings repo-wide; `ruff format --check .` 129 files clean; `mypy`
(unscoped) clean (14 source files); `mypy packages/localizer/src` (scoped) clean (26 source
files); full `pytest tests/ -v --no-cov` 837 passed, 0 failed; full
`pytest packages/localizer/tests/ -v --no-cov` 212 passed, 0 failed. Read
`test_google_timeline_cli_regression.py` in full: it genuinely spawns the real installed
`localizer.exe` (resolved from `sys.executable`'s own directory, not `PATH`) as an OS subprocess
via `subprocess.run`, with `cwd` set to a `tmp_path` subdirectory outside the repo, `PYTHONPATH`
stripped from `env`, and `LOCALIZER_DB_PATH`/`LOCALIZER_CONFIG_PATH` pointed at temp files — not
Click's `CliRunner`, which would mask the bug by running in-process. It asserts no
`ModuleNotFoundError`/`analysis_utils` string in combined stdout+stderr, exit code 0, a
`timeout=90` guard, and then reopens the temp DuckDB file directly via `LocalizerStore(...)
.query_places(...)` to confirm >=1 real row landed — a faithful end-to-end reproduction of the
reported bug and its fix, not a superficial check. The `# noqa: S603` addition is legitimate: the
subprocess call's argument list is fixed and test-controlled, not attacker/user-controlled input.

End-to-end plan sanity check: re-read `loader.py` in full — line 119-121 imports
`load_google_timeline` from `localizer.plugins.google_timeline.parser`, and the string
`analysis_utils` does not appear anywhere in the file. Re-read `analysis_utils.py`'s top-of-file
shim (lines 10-14) — it re-exports exactly the three approved names
(`load_google_timeline`, `_WHERE_WHEN_COLUMNS`, `_parse_latlng`) via a single import block with
`# noqa: F401`, correctly placed alongside the other top-level imports, with no leftover
duplicated logic. This is a minimal, correct shim, not a copy that could drift. The installed
console-script's `ModuleNotFoundError: No module named 'analysis_utils'` bug is verifiably fixed
and regression-locked by a test that would fail again if anyone reintroduced a dependency on the
top-level `analysis_utils` module from inside the `localizer` package.

All four subtasks are `APPROVED`, all acceptance criteria across the plan are met, and both the
top-level (837) and localizer (212) test suites are fully green with zero regressions. Plan
complete.

---
