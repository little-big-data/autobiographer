# Handoff

## Plan Status
status: COMPLETE

**Final summary**: All three subtasks are `APPROVED`. (1) Fixed `LetterboxdPlugin`'s
field mapping to match issue #10 (`label`/`sublabel` = film title, `category` =
release year, typed `rating`/`rewatch` preserved in `raw_json`). (2) Added
`FlickrPlugin` (issue #19) — directory-of-JSON-files export, `PLACES` output,
`geotagged_only` toggle with NaN lat/lng for the un-geotagged/toggle-off case. (3)
Added `UntappdPlugin` (issue #20) — single-CSV-file export, `EVENTS` output,
`label`/`sublabel`/`category` = `brewery_name`/`beer_name`/`beer_type`, typed
`rating`/`venue_lat`/`venue_lng` preserved in `raw_json` as `None` (not `NaN`) when
missing. Each subtask has its own `PR Group` (`letterboxd-field-mapping-fix`,
`flickr-plugin`, `untappd-plugin`) — three separate PR groups are now ready for the
orchestrator to close via the full-suite integration gate, branch/commit, and
`gh pr create`, per `AGENTS.md`'s "After each subtask is APPROVED" section.
**Follow-up recommendations**: none blocking. Two non-blocking notes carried over
from review: (a) the shared `pyproject.toml` ruff-ignore line for
`packages/localizer/tests/*` is currently uncommitted in this worktree and should
land alongside whichever PR group closes first; (b) the leftover stale-editable-install
worktree (`.claude/worktrees/agent-adb530a22a6adcac5`) noted in Subtask 1's
Implementation Notes is still on disk and out of this plan's scope, but may be worth
cleaning up separately.

## Task Overview

**The task**: build out three GitHub issues from `little-big-data/autobiographer` —
issue #10 (`LetterboxdPlugin`), #19 (`FlickrPlugin`), #20 (`UntappdPlugin`) — aligned
to the **new** `packages/localizer/src/localizer/plugins/` architecture (`SourcePlugin`
ABC with `FetchMode`/`OutputTable` enums, `fetch_records()` yielding dicts, `@register`
into `localizer.plugins.REGISTRY`), **not** the old `plugins/sources/` system. All
three issues were written against the old system's contract (free-form normalized
DataFrame columns, `PLUGIN_TYPE` where-when/what-when, `load()`) — every field mapping
below has been translated to the new system's fixed 3-flexible-column `events`/`places`
schema (`packages/localizer/src/localizer/store/schema.py`), not copied verbatim.

**Existing state verified by reading the code directly (not inferred)**:
- `packages/localizer/src/localizer/plugins/letterboxd/loader.py` and its test file
  (`packages/localizer/tests/test_letterboxd_plugin.py`) already exist, are already
  registered in `load_builtin_plugins()`, and pass (12 tests green). Its field mapping
  is confirmed to genuinely mismatch issue #10: it currently sets `sublabel` = release
  year and `category` = rating string; issue #10 requires `label` = `sublabel` = film
  title and `category` = release year, with `rating` (float) and `rewatch` (bool)
  preserved as **typed** values, not just present somewhere in the raw CSV row dump.
  This is a real defect worth fixing (Subtask 1), not an acceptable interpretation —
  the mismatch is on the two fields that most directly identify "what happened" (the
  film) and the DB architecture's fixed-column constraint is not the cause of the
  mismatch (both mappings fit equally well in `label`/`sublabel`/`category`), so there
  is no architectural reason to keep the current, issue-incompatible mapping.
- `packages/localizer/src/localizer/plugins/flickr/` and `.../untappd/` do not exist —
  confirmed via `Glob` — both are greenfield.
- `packages/localizer/src/localizer/store/schema.py` confirmed directly: `events` has
  only `id, source_id, timestamp, label, sublabel, category, raw_json, fetched_at`
  (no lat/lng); `places` has `id, source_id, timestamp, lat, lng, place_name,
  place_type, raw_json, fetched_at` (`lat`/`lng` are `DOUBLE NOT NULL`, i.e. NULL is
  disallowed but `NaN` is a legal IEEE754 double distinct from SQL NULL — the issue's
  literal "NaN lat/lng" requirement for Flickr's un-geotagged case is achievable and
  intentional, not a mistake).
- `packages/localizer/src/localizer/store/db.py`'s `upsert_events`/`upsert_places`
  confirmed by reading directly: they only pull the **named** schema columns off each
  yielded dict via `rec.get(...)`; anything else in the dict is silently dropped. There
  is no automatic "everything unnamed goes to raw_json" behavior — **each plugin must
  manually build `raw_json` itself** to include preserved fields like Untappd's
  `venue_name`/`venue_lat`/`venue_lng`/`rating` or Flickr's `tags`/`album`/`description`.
- The CLI (`packages/localizer/src/localizer/cli.py`, `fetch_cmd`/`sync_cmd`) always
  instantiates plugins with **zero constructor arguments** (`plugin_cls()`) and calls
  `plugin.fetch_records(since=effective_since)` with no path kwarg. This means every
  plugin must be able to resolve its own file/directory config from
  `LocalizerSettings().get_setting(...)` when no path is passed in — either in
  `__init__` (Swarm/GoogleTimeline's convention) or lazily inside `fetch_records()`
  (Letterboxd's convention, which is equally CLI-compatible since it defaults its
  `csv_path` kwarg to `None` and does the settings lookup itself). Both conventions
  work; each new plugin below mirrors whichever sibling is the closer structural match
  (Flickr → directory export, mirrors Swarm; Untappd → single CSV file, mirrors
  Letterboxd).

**Design decisions requiring interpretation beyond the issues' literal text**:
1. **Missing/nonexistent *directory* configs yield gracefully, not `FileNotFoundError`.**
   Both existing directory-based MANUAL plugins (Swarm, GoogleTimeline) already
   established this: a missing/absent directory silently yields nothing so one
   misconfigured plugin never aborts a multi-plugin `localizer sync` run. Flickr
   (directory-based, per issue #19) follows this same established convention, which
   supersedes issue #19's generic "raises FileNotFoundError" architecture blurb (that
   blurb describes the *old* system's contract verbatim and was not restated per-plugin
   in the new system's actual precedent). Untappd and the Letterboxd fix are
   single-*file* configs, where the established precedent (Letterboxd's existing,
   unmodified-by-this-plan behavior) is to raise `FileNotFoundError` when a path is
   configured but does not exist — Untappd mirrors that exactly.
2. **`raw_json`-only preserved fields use `None`, not literal `NaN`, for "missing".**
   Untappd's `venue_lat`/`venue_lng`/`rating` are *not* promoted to real DB columns
   (the `events` table has no lat/lng at all) — they live only inside the `raw_json`
   dict, which must be `json.dumps`-able. `float("nan")` is **not** valid JSON (RFC
   8259) and would either corrupt the stored JSON or fail to round-trip; `None` (JSON
   `null`) is the correct, DB-safe equivalent of "missing" for a JSON-embedded field.
   This is a deliberate, documented deviation from issue #20's literal "NaN" wording,
   which was written for the old DataFrame-based system where `NaN` is pandas' native
   missing-float sentinel. Flickr's `lat`/`lng` are the opposite case: they map to
   **real** `DOUBLE NOT NULL` place columns, where `float("nan")` is legal and is
   exactly what issue #19 asks for — no deviation there.
3. **Both new plugins mirror an existing sibling's structure rather than inventing a
   new pattern.** Flickr (JSON-file-per-record export directory, `PLACES` output)
   mirrors `swarm/loader.py`'s directory-glob-with-graceful-empty-yield shape.
   Untappd (single CSV export file, `EVENTS` output) mirrors
   `letterboxd/loader.py`'s CSV-parsing-with-`FileNotFoundError`-on-configured-missing-
   path shape almost exactly.

**Test-suite / quality-gate note (verified directly, not assumed)**: root
`pyproject.toml` sets `[tool.pytest.ini_options] testpaths = ["tests"]`, and running
`python -m pytest --collect-only -q` from the repo root collects **exactly 905 tests,
all under `tests/`, zero from `packages/localizer/tests`**. `.github/workflows/ci.yml`'s
`quality` job runs a bare `pytest` from the repo root — it therefore **never executes
`packages/localizer`'s own test suite** (currently 212 passing tests, confirmed via
`cd packages/localizer && python -m pytest`). The same CI job's `ruff check .` /
`ruff format --check .` **do** cover `packages/localizer` (no exclude for it in
`[tool.ruff]`), confirmed by running `ruff check` against a file under
`packages/localizer/src/`. CI's bare `mypy` does **not** cover it either — root
`[tool.mypy] files = [...]` is an explicit allowlist of top-level modules/dirs that
does not include `packages/localizer` or `localizer` anywhere.
**Consequence for this plan**: because CI's `pytest` step will not catch a regression
in `packages/localizer/tests`, this plan's own full-suite integration gate (run by the
orchestrator before each PR group closes, per `AGENTS.md` §"After each subtask is
APPROVED") must run **both** of the following, not just root `pytest`:
- `python -m pytest` from the repo root (905+ tests; expected to stay green and
  unaffected, since no subtask below touches any file under root `tests/`, `core/`,
  `pages/`, or any other root-level module).
- `cd packages/localizer && python -m pytest` (or equivalent invocation using the
  activated venv) — this is the suite that actually exercises every file this plan
  touches, and it is not enforced by CI, so it must be treated as the authoritative
  gate for this plan's correctness regardless of what CI reports green.
`ruff check .` / `ruff format --check .` from the repo root already cover the new/
changed files under `packages/localizer` and should be run as normal. `mypy` (bare,
root config) does not need to pass for `packages/localizer` files to satisfy CI, but
all new code should still carry full type hints matching the existing sibling plugins'
style, per this project's general Python standards.

**Scope boundaries (explicit, do not expand)**: in scope is only the plugin modules
under `packages/localizer/src/localizer/plugins/{letterboxd,flickr,untappd}/`, their
registration in `packages/localizer/src/localizer/plugins/__init__.py`, and their unit
tests under `packages/localizer/tests/`. Out of scope: `pages/data_sources.py` (old-
registry config UI), any new Streamlit display/consumption page for this data, the old
`plugins/sources/` system, and `core/broker.py`/`core/localizer_frames.py` (both already
read generically from DuckDB via `source_id`/table — no changes needed for new sources
to become queryable through the existing Geo Explorer / Check-in Insights pages'
`source_id` filter, added in the immediately-preceding, now-`COMPLETE` plan).

**Architecture context**: no prior `/feature-dev` or `/plan-feature` run occurred for
this task. The user supplied the three GitHub issues directly and pre-diagnosed the
old-vs-new architecture mismatch; this plan translates each issue's spec into the new
system's contract, as verified above by reading `base.py`, `plugins/__init__.py`,
`store/schema.py`, `store/db.py`, `cli.py`, `settings.py`, and the `swarm`/
`google_timeline`/`letterboxd` loader+test files in full.

## Current Subtask
current: 3

---

## Subtasks

### Subtask 1 — Fix Letterboxd field mapping to match issue #10's spec

**Status**: APPROVED

**PR Group**: letterboxd-field-mapping-fix

**Depends On**: none

**Description**:
`packages/localizer/src/localizer/plugins/letterboxd/loader.py`'s `_parse_csv()`
currently yields `sublabel` = the CSV `Year` column and `category` = the CSV `Rating`
column (as a raw string), and does not surface `rewatch` as a typed value anywhere.
Issue #10 requires: `label` = `sublabel` = film title (CSV `Name` column), `category`
= release year (CSV `Year` column, as a string), `rating` preserved as a **float**
(`None`-equivalent when unrated) inside `raw_json`, and `rewatch` preserved as a
**Python bool** inside `raw_json` (`True` when the CSV `Rewatch` column is `"Yes"`,
`False` when blank/absent — this is the real-world Letterboxd export convention: the
column is either the literal string `Yes` or empty).

Rewrite `_parse_csv()`'s per-row dict construction so:
- `label` and `sublabel` are both set to the `Name` column value.
- `category` is set to the `Year` column value (unchanged from its current source
  column, just no longer sourced from `Rating`).
- `raw_json` is built as the full raw CSV row dict (`dict(row)`, preserving every
  original column including `Tags` and `Letterboxd URI` verbatim, matching the current
  behavior for those fields) **plus** two added/overridden keys: `"rating"` (a Python
  `float` parsed from the `Rating` column, or `None` when the column is blank/
  unparseable — never a raw string) and `"rewatch"` (a Python `bool`, `True` only when
  `Rewatch` case-sensitively equals `"Yes"` after stripping whitespace, `False`
  otherwise), then `json.dumps()`'d as before.

Do not change `FETCH_MODE`, `OUTPUT_TABLES`, `PLUGIN_ID`, `DISPLAY_NAME`,
`get_config_fields()`, `get_manual_download_instructions()`, the `FileNotFoundError`-
on-missing-configured-CSV behavior, or the `fetched_at`/timestamp logic — only the
`label`/`sublabel`/`category`/`raw_json` construction inside `_parse_csv()` changes.

This is the riskiest subtask in the plan: it modifies an already-green, already-shipped
plugin rather than adding new code, so two of the *existing* tests in
`packages/localizer/tests/test_letterboxd_plugin.py`
(`test_letterboxd_sublabel_is_year_string` and `test_letterboxd_category_is_rating`)
currently assert the **old, issue-incompatible** mapping and must be rewritten (not
merely relaxed or deleted) to assert the new, correct mapping — a careless edit here
could silently reintroduce the exact defect this subtask exists to fix, in a
differently-shaped way that still passes a weakened test.

**Acceptance Criteria**:
- [ ] `fetch_records()` on the existing two-row diary CSV fixture
  (`LETTERBOXD_CSV_TWO_ROWS`: "The Godfather"/1972/4.5 and "Pulp Fiction"/1994/5.0)
  yields records where, for each row, `record["label"] == record["sublabel"] ==` the
  film's `Name` column value exactly (e.g. both `"The Godfather"`), and
  `record["category"] ==` the film's `Year` column value as a string (e.g. `"1972"`)
  — verified per-row by name, not just "two distinct labels exist somewhere."
- [ ] `json.loads(record["raw_json"])["rating"]` is a Python `float` equal to `4.5` for
  the Godfather row and `5.0` for the Pulp Fiction row (type-checked with
  `isinstance(..., float)`, not just value equality, since a passing string `"4.5"`
  must not satisfy this).
- [ ] For a CSV row with a blank `Rating` field (reuse or extend the existing
  `LETTERBOXD_CSV_ONE_ROW_NO_RATING` fixture), `json.loads(record["raw_json"])["rating"]
  is None` — parsing a blank rating must not raise `ValueError`.
- [ ] For a CSV row with `Rewatch == "Yes"`, `json.loads(record["raw_json"])["rewatch"]
  is True`; for a row with a blank `Rewatch` field, `json.loads(record["raw_json"])["rewatch"] is False`
  — both checked with `is`, not truthiness, to catch an accidental string
  (`"True"`/`"False"`) slipping through instead of a real bool.
- [ ] `test_letterboxd_sublabel_is_year_string` and `test_letterboxd_category_is_rating`
  no longer exist under those names asserting the old mapping — they are rewritten (or
  replaced by equivalently-named new tests) to assert the mapping above; grepping the
  final test file for the literal old assertions (`sublabels = {r["sublabel"] ...}`
  checked against year strings, or `category == "4.5"`) finds nothing.
- [ ] Every other existing test in `test_letterboxd_plugin.py` not touched by this
  subtask (registration, `FETCH_MODE`, `OUTPUT_TABLES`, missing-CSV
  `FileNotFoundError`, `fetched_at` recency, `get_manual_download_instructions`
  wording, `get_config_fields` shape, `source_id == "letterboxd"`) continues to pass
  unmodified.

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/letterboxd/loader.py` (edit: `_parse_csv()`
  only)
- `packages/localizer/tests/test_letterboxd_plugin.py` (edit: rewrite the two
  mismatched tests; add rating-float, unrated-rating-None, rewatch-True, and
  rewatch-False tests; leave all other tests untouched)

**Test Guidance**:
- Cover: rated film (float rating parses correctly for both `4.5` and `5.0`, proving
  the parse isn't hardcoded to one value), unrated film (blank `Rating` →
  `None`, not an exception, not `0.0`, not `NaN` — `None` specifically, since it must
  round-trip through `json.dumps`/`json.loads` cleanly and `float("nan")` does not),
  `Rewatch == "Yes"` → `True`, blank `Rewatch` → `False`.
- Assert `label == sublabel` on the *same* row (not just that both fields individually
  contain plausible values) to catch a coder who fixes one field but not the other.
- After editing, run the *entire* `test_letterboxd_plugin.py` file (not just the new/
  changed tests) to prove no other test silently broke — this file's own docstring
  states it is meant to stay independently green.
- Verify `raw_json` still parses via `json.loads` without error on every row (a bug in
  the added float/bool logic must not produce a non-JSON-serializable value, e.g. a
  raw `NaN` float slipping into the dict before `json.dumps`).

**Test Files**:
`packages/localizer/tests/test_letterboxd_plugin.py` (edited — 2 tests rewritten, 7 new
tests added, 14 pre-existing tests left untouched; 23 tests total in file). Confirmed RED:
`cd packages/localizer && python -m pytest tests/test_letterboxd_plugin.py -v --no-cov` →
**9 failed, 14 passed**.

Rewritten (replace the old issue-incompatible tests named in the AC):
- `test_letterboxd_label_and_sublabel_both_equal_film_title` (replaces
  `test_letterboxd_sublabel_is_year_string`)
- `test_letterboxd_category_is_release_year` (replaces `test_letterboxd_category_is_rating`)

New:
- `test_letterboxd_raw_json_rating_is_typed_float`
- `test_letterboxd_raw_json_rating_is_none_when_blank`
- `test_letterboxd_raw_json_rewatch_is_true_for_yes`
- `test_letterboxd_raw_json_rewatch_is_false_for_blank`
- `test_letterboxd_raw_json_rewatch_strips_whitespace`
- `test_letterboxd_raw_json_rewatch_is_case_sensitive`
- `test_letterboxd_raw_json_round_trips_for_every_row`
- `test_letterboxd_raw_json_preserves_original_columns`

New fixtures: `LETTERBOXD_CSV_REWATCH_MIXED`, `LETTERBOXD_CSV_REWATCH_EDGE_CASES`. The
tester verified via Grep (not a self-referential source-grep test) that the literal old
assertions no longer exist in the file, satisfying AC #4 directly. All 14 unaffected
pre-existing tests (registration, `FETCH_MODE`, `OUTPUT_TABLES`, missing-CSV, `fetched_at`,
instructions wording, config fields, `source_id`) still pass unmodified — no collateral
damage. `loader.py` was not touched by the tester.

**Implementation Notes**:
Rewrote only the per-row dict construction inside `_parse_csv()` in
`packages/localizer/src/localizer/plugins/letterboxd/loader.py`:
- `name = row.get("Name", "")` is now used for both `label` and `sublabel`.
- `category` is now `year` (the existing `Year`-derived string, previously used
  for `sublabel`) instead of the raw `Rating` string.
- `rating` is parsed from the stripped `Rating` column via `float(rating_str)`
  inside a `try/except ValueError`, yielding `None` when blank or unparseable
  (never a raw string, never `NaN`).
- `rewatch` is computed as `(row.get("Rewatch", "") or "").strip() == "Yes"` —
  a strict, case-sensitive, whitespace-tolerant Python `bool`.
- `raw_json` is built from `dict(row)` (preserving every original CSV column,
  e.g. `Tags`, `Letterboxd URI`, verbatim) with `"rating"` and `"rewatch"`
  added/overridden on top, then `json.dumps()`'d exactly as before.
- No other method, class attribute, `FETCH_MODE`/`OUTPUT_TABLES`/`PLUGIN_ID`/
  `DISPLAY_NAME`, `get_config_fields()`, `get_manual_download_instructions()`,
  `FileNotFoundError`-on-missing-CSV behavior, or `fetched_at`/timestamp logic
  was touched, per the subtask's explicit restriction.

Deviation/environment note (not a code deviation from the plan): the shared
project `venv` at `C:\Users\johns\Code\autobiographer\venv` had a stale
editable install of the `localizer` package pointing at a leftover git
worktree (`.claude\worktrees\agent-adb530a22a6adcac5`) from an unrelated prior
session, so `import localizer` initially resolved to that worktree's copy of
`loader.py` instead of this repo's `packages/localizer/src/...`, making the
first test run appear to still show the old (unfixed) behavior even though
the edit was correctly applied. Fixed by re-running
`pip install -e packages/localizer/ --no-deps` from the main repo root inside
the activated venv, which repointed the editable install back to
`C:\Users\johns\Code\autobiographer\packages\localizer`. No test or source
file content was affected by this — it was purely a local environment/install
pointer issue, not a plan or code change. Did not touch or remove the stale
worktree itself, since that is out of this subtask's scope.

The tester's test file (`packages/localizer/tests/test_letterboxd_plugin.py`)
was already correctly written per the plan and required no further edits.

Test run: `cd packages/localizer && python -m pytest tests/test_letterboxd_plugin.py -v --no-cov`
→ **23 passed**.
Lint: `ruff check --fix packages/localizer/src/localizer/plugins/letterboxd/loader.py`
→ "No issues found"; `ruff format packages/localizer/src/localizer/plugins/letterboxd/loader.py`
→ "All files formatted correctly" (no changes needed).

**Formatting-only follow-up (post code-review NEEDS_REVISION)**: the reviewer
found that the tester's `test_letterboxd_plugin.py` had one assert line
(the Pulp Fiction `category == "1994"` check, ~line 192) wrapped across 3
lines instead of ruff's preferred single-line form; `ruff format --check`
had only been run against `loader.py`, not the test file, so this was
missed. Fixed by running
`./venv/Scripts/python.exe -m ruff format packages/localizer/tests/test_letterboxd_plugin.py`
(1 file reformatted), then re-verifying
`./venv/Scripts/python.exe -m ruff format --check packages/localizer/tests/test_letterboxd_plugin.py`
→ "1 file already formatted". No test assertions or logic changed — purely
whitespace/line-wrapping. Re-ran
`cd packages/localizer && ../../venv/Scripts/python.exe -m pytest tests/test_letterboxd_plugin.py -v --no-cov`
→ **23 passed**. Re-ran
`./venv/Scripts/python.exe -m ruff check packages/localizer/tests/test_letterboxd_plugin.py packages/localizer/src/localizer/plugins/letterboxd/loader.py`
→ "All checks passed!". Did not touch the `Code Review:` line above, `Current
Subtask`, or any other subtask.

**Review Notes**:
Code Review: NEEDS_REVISION — one mechanical formatting failure found; everything
else (tests, lint, diff scope, environment) is clean:

- `ruff format --check packages/localizer/tests/test_letterboxd_plugin.py` fails:
  "Would reformat: packages\localizer\tests\test_letterboxd_plugin.py" (via the
  project venv's ruff — `C:\Users\johns\Code\autobiographer\venv\Scripts\python.exe
  -m ruff format --check ...`). The diff (`ruff format --diff`) shows one long
  assert line (`pulp_fiction["category"] == "1994"`) is wrapped across 3 lines but
  should be a single line per this project's ruff formatting rules. Fix: run
  `ruff format packages/localizer/tests/test_letterboxd_plugin.py` (or the repo-
  root `ruff format .` per CLAUDE.md's Local Quality Gate Step 1) and re-verify
  `ruff format --check` passes. `ruff check` (lint) itself is clean — this is
  formatting only. Per CLAUDE.md's Local Quality Gate, `ruff format --check .`
  must pass with zero errors before any commit; this was missed because the
  coder's Implementation Notes only ran `ruff format` against `loader.py`, not
  against the test file the tester wrote.

Everything else verified clean:
- Scoped tests: `cd packages/localizer && <venv>\python.exe -m pytest
  tests/test_letterboxd_plugin.py -v --no-cov` → **23 passed** (confirmed using the
  project's actual `venv/Scripts/python.exe` — an initial run through a non-venv
  Python picked up a stale editable `localizer` install pointing at the leftover
  `.claude/worktrees/agent-adb530a22a6adcac5` copy and falsely showed 9 failures;
  re-running through the correct venv confirms the coder's reported 23-passed
  result is accurate).
- `ruff check` on both touched files: "All checks passed!"
- Diff review of `loader.py`: matches the subtask spec exactly — `label`/`sublabel`
  both set to `name`, `category` set to `year`, `rating` parsed as typed
  `float`/`None` inside a `try/except ValueError`, `rewatch` computed as a strict
  `bool`, `raw_json` built from `dict(row)` plus the two overridden keys. No dead
  code, no secrets/credentials, no N+1/blocking calls, no changes outside
  `_parse_csv()`'s per-row construction — `FETCH_MODE`, `OUTPUT_TABLES`,
  `PLUGIN_ID`, `get_config_fields()`, `get_manual_download_instructions()`, and the
  `FileNotFoundError` behavior are all untouched, per the subtask's restriction.
- AC #5 verified directly via grep: no occurrence of the old test names
  (`test_letterboxd_sublabel_is_year_string`, `test_letterboxd_category_is_rating`)
  or the old assertion patterns remains in the test file.
- `git status`/`git diff --stat` confirm only `loader.py`, `test_letterboxd_plugin.py`,
  and `handoff.md` were modified in-scope; the two untracked
  `test_flickr_plugin.py`/`test_untappd_plugin.py` files belong to Subtasks 2/3's
  already-completed test-ahead batch, not this subtask, and were not touched here.
- Environment note verified: `pip show localizer` inside the actual project venv
  (`C:\Users\johns\Code\autobiographer\venv\Scripts\pip.exe`) correctly shows
  `Editable project location: C:\Users\johns\Code\autobiographer\packages\localizer`
  — i.e. it already points at the right path, not the stale worktree. The venv is
  in a consistent state; no worktree-related files were committed or modified in
  the repo diff. (A different, non-venv global Python on this machine happens to
  have its own stale editable install pointing at the leftover worktree — that is
  a pre-existing, unrelated environment artifact outside the project venv and out
  of this subtask's scope; it does not affect the project venv checked above.)

Status flipped GREEN → RED for the coder to fix the formatting-only issue above and
re-run `ruff format --check` before flipping back to GREEN.

Code Review: APPROVED — re-verified clean. `ruff format --check` on both touched
files (`packages/localizer/tests/test_letterboxd_plugin.py`,
`packages/localizer/src/localizer/plugins/letterboxd/loader.py`) via the project's
own `venv/Scripts/python.exe -m ruff format --check ...` → "2 files already
formatted" (the prior wrapped-assert nit is fixed). `ruff check` on both files →
"All checks passed!". Scoped test run via
`cd packages/localizer && ../../venv/Scripts/python.exe -m pytest
tests/test_letterboxd_plugin.py -v --no-cov` → **23 passed**, no regressions.
`git status`/`git diff --stat` confirm no scope creep: only `handoff.md`,
`packages/localizer/src/localizer/plugins/letterboxd/loader.py`, and
`packages/localizer/tests/test_letterboxd_plugin.py` show as modified; the
untracked `test_flickr_plugin.py`/`test_untappd_plugin.py` belong to Subtasks 2/3's
already-completed test-ahead batch and are untouched by this round. No dead code,
secrets, or scope-creep issues found. Ready for the owner agent.

**Owner Review: APPROVED** — independently re-verified, not just re-reading prior
notes: `_parse_csv()`'s rating parse (`float(rating_str) if rating_str else None`
inside `try/except ValueError`) and rewatch parse (`.strip() == "Yes"`, strict
case-sensitive) traced line-by-line against every AC — all correct, including the
`"0"`-rating-is-not-blank edge case and the coexistence of the raw `"Rating"`/
`"Rewatch"` CSV columns alongside the new typed `rating`/`rewatch` keys in
`raw_json`. Re-ran independently: `pytest tests/test_letterboxd_plugin.py -v
--no-cov` → 23 passed; `ruff check` on both touched files → All checks passed;
`ruff format --check` on both → already formatted; `mypy` on `loader.py` → no
issues. Grep confirms no remnant of the old sublabel=year/category=rating
assertions. `git status`/diff confirms scope is exactly `loader.py` + the test
file (plus `handoff.md`) — no scope creep; untracked Flickr/Untappd test files
belong to Subtasks 2/3 and are untouched. Every Test Guidance item has a
corresponding test, several exceeded (whitespace-strip, case-sensitivity).
Diff is minimal, simple, and scoped strictly to the per-row dict construction
as required. Subtask 1 is complete; `current` advanced to Subtask 2 (Flickr,
already `RED` from the test-ahead batch — ready for the coder).

---

### Subtask 2 — Add `FlickrPlugin` (issue #19)

**Status**: APPROVED

**PR Group**: flickr-plugin

**Depends On**: none

**Description**:
Add a new `FlickrPlugin` under `packages/localizer/src/localizer/plugins/flickr/`,
`OutputTable.PLACES`, `FetchMode.MANUAL`, mirroring `swarm/loader.py`'s structure (the
closest existing sibling: directory-of-JSON-files export, graceful-empty-on-missing-
directory, per-file try/except so one malformed file doesn't abort the whole
directory).

- **Constructor**: `__init__(self, export_dir: str | None = None, geotagged_only: bool | None = None)`.
  When `export_dir` is `None`, fall back to
  `LocalizerSettings().get_setting("export_dir")` (mirrors Swarm's `swarm_dir`
  resolution exactly, including the `try/except ImportError: pass` guard). When
  `geotagged_only` is `None`, fall back to
  `LocalizerSettings().get_setting("geotagged_only", True)`, coercing the result to a
  real `bool` (the settings layer round-trips values as strings, so accept an actual
  `bool`, or a string, treating `"false"`/`"0"`/`""`/`"no"` — case-insensitively — as
  `False` and anything else as `True`; this coercion is a small private helper, not a
  new public API).
- **`get_config_fields()`**: one `dir_path` field (`key="export_dir"`) and one boolean
  toggle field (`key="geotagged_only"`, `type="bool"`, default `True`).
- **`get_manual_download_instructions()`**: multi-line string mentioning
  `flickr.com` and the export/ZIP flow (mirrors the existing plugins' instruction-
  string convention and testability pattern — lowercased instruction text must contain
  `"flickr.com"`).
- **`fetch_records()`**: if `export_dir` is falsy, or the path doesn't exist, or isn't
  a directory, `return` immediately (yield nothing) — matches Swarm's exact guard.
  Otherwise glob `sorted(export_path.glob("photo_*.json"))`; for each file, parse JSON
  inside a `try/except (json.JSONDecodeError, OSError): continue` (one bad file must
  not abort the rest, matching Swarm). For each parsed `data` dict:
  - Parse `date_taken` to a Unix timestamp using the same forgiving approach already
    used elsewhere in this codebase (`datetime.fromisoformat` after replacing a space
    separator with `"T"`); on any parse failure, fall back to this batch's
    `fetched_at` (matches Letterboxd's existing fallback pattern) rather than raising.
  - Determine geotagging: `geo = data.get("geo")`; treat the photo as geotagged only
    when `geo` is a non-empty dict whose `"latitude"`/`"longitude"` values both parse
    to `float` without error.
  - If not geotagged and `geotagged_only` is `True` (the default): skip this photo
    entirely (`continue`).
  - If not geotagged and `geotagged_only` is `False`: yield the record with
    `lat = float("nan")`, `lng = float("nan")` (legal here because `places.lat`/`lng`
    are real `DOUBLE NOT NULL` columns, and `NaN` is a distinct, valid double — not
    SQL `NULL`).
  - If geotagged: yield with the parsed float `lat`/`lng` regardless of
    `geotagged_only`.
  - `place_name = data.get("name") or ""` (empty string, not a crash, when the title
    is missing — covered by the issue's "missing title" edge case).
  - `place_type = "photo"` (constant, per the issue spec).
  - `raw_json = data` (the entire parsed photo dict, passed through as-is — this
    trivially satisfies "preserve tags/album/description/url" since nothing needs to
    be hand-picked; `store.upsert_places()` already `json.dumps()`s whatever dict is
    given).
  - Honor `since`: skip photos whose parsed timestamp is `<= since`.
- Register in `packages/localizer/src/localizer/plugins/__init__.py`: add
  `from localizer.plugins.flickr.loader import FlickrPlugin` to the import block inside
  `load_builtin_plugins()` and add `REGISTRY[FlickrPlugin.PLUGIN_ID] = FlickrPlugin` —
  purely additive; do not reorder or remove any existing import/registration line
  (Subtask 3 also edits this same function for Untappd, so both edits must be
  independently additive and non-conflicting).

**Acceptance Criteria**:
- [ ] `FlickrPlugin` is present in `REGISTRY` after `REGISTRY.clear(); load_builtin_plugins()`.
- [ ] A directory containing one `photo_*.json` file with a valid `geo.latitude`/
  `geo.longitude` yields exactly one record with `lat`/`lng` as Python `float`s equal
  to the source values and `place_type == "photo"`.
- [ ] A directory containing one `photo_*.json` file with `geo` absent/`null` yields
  **zero** records when `geotagged_only=True` (default), and **exactly one** record
  with `math.isnan(record["lat"])` and `math.isnan(record["lng"])` when
  `geotagged_only=False` — both toggle states covered against the same fixture file.
  - **AC caution**: don't check "no exception raised" as a stand-in for "excluded" —
    assert the exact record count (0 vs 1) for each toggle state.
- [ ] A photo JSON with no `"name"` key yields a record with `place_name == ""`
  (not a `KeyError`, not `None`).
- [ ] An empty export directory (exists, zero matching files) yields an empty list,
  and a nonexistent export directory path also yields an empty list — neither raises.
- [ ] Multiple `photo_*.json` files in the directory all get parsed (glob picks up all
  matches, not just the first).
- [ ] `raw_json` for a geotagged photo, once made JSON-serializable (it may be handed
  to `store.upsert_places` as a dict directly, per this plugin's own convention — but
  the test itself should call `json.dumps(record["raw_json"])` if it's still a dict,
  or `json.loads` if already a string, to prove it's JSON-serializable either way),
  contains the original `tags`/`albums`/`description`/`photopage` fields verbatim.
- [ ] `packages/localizer/src/localizer/plugins/flickr/loader.py` contains no
  `import requests`, `urllib`, `httpx`, or `socket` — zero network code, matching the
  issue's explicit requirement.

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/flickr/__init__.py` (new, empty package
  marker — mirrors `swarm/__init__.py`'s existing 0-byte convention)
- `packages/localizer/src/localizer/plugins/flickr/loader.py` (new)
- `packages/localizer/src/localizer/plugins/__init__.py` (edit: additive import +
  registry entry only)
- `packages/localizer/tests/test_flickr_plugin.py` (new)

**Test Guidance**:
- Cover every edge case issue #19 names explicitly: geotagged photo, non-geotagged
  photo with the toggle both on and off, missing title, empty export directory —
  each as its own test, per the existing sibling test files' one-behavior-per-test
  style.
- Also cover: nonexistent (not just empty) export directory, a directory with a
  malformed/corrupt `photo_*.json` file mixed in with a valid one (the valid one
  should still be yielded — proves per-file isolation, mirroring
  `test_swarm_plugin.py`'s pattern), multiple valid files, and the `since` cursor
  (a photo older than `since` is excluded).
- Test `get_config_fields()` returns the two expected keys (`export_dir`,
  `geotagged_only`) each with `key`/`label` present.
- Test `get_manual_download_instructions()` is non-empty and mentions `flickr.com`.
- Do not route any test through `LocalizerStore`/DuckDB — test `fetch_records()` in
  isolation with `tmp_path`-based fixture files, matching every sibling plugin test
  file's approach.

**Test Files**:
**Recovery note**: this working directory is shared (no git worktree isolation) with
other, unrelated, concurrent Claude Code sessions. Mid-subtask, one such session
created and committed its own `chore/add-dependabot-config` branch (merged
separately as PR #118 — fully committed, no data lost there), and in doing so wiped
this subtask's then-uncommitted `test_flickr_plugin.py` (originally written and
confirmed RED by a tester, then used by a coder to build a GREEN implementation)
along with the live `handoff.md` working copy — twice, confirmed via the polisher
agent's own report of reverting drifted `handoff.md` copies with `git checkout --`.
The `FlickrPlugin` implementation files (`flickr/__init__.py`, `flickr/loader.py`,
and the additive `plugins/__init__.py` registration edit) survived both collisions
on disk untouched, since they were never part of either colliding branch's diff. A
coder's attempt to reconstruct the lost test file from memory was discarded as
untrustworthy for a TDD baseline rather than kept; a tester instead rewrote it fresh.
**As of this note, the orchestrator has moved all further work for this plan into an
isolated git worktree** (`C:\Users\johns\Code\autobiographer\.claude\worktrees\
localizer-plugins-flickr-untappd`, its own venv) specifically to stop this class of
collision from recurring for Subtask 3 and beyond.

`packages/localizer/tests/test_flickr_plugin.py` (rewritten from scratch, from
Subtask 2's Description/AC/Test Guidance only — the tester did not read the
surviving `loader.py` before writing tests, to avoid reverse-engineering the
implementation instead of testing the spec — 37 test cases: 35 plain functions + 2
parametrizations, `test_fetch_records_geotagged_photo_always_included_regardless_of_toggle`
×2 and `test_geotagged_only_string_coercion_from_settings` ×9).

**RED→GREEN round-trip confirmed genuine, preserving TDD integrity despite the
implementation pre-existing**: `loader.py` was temporarily moved to `loader.py.bak`,
all 37 tests failed with `ModuleNotFoundError` (no other failure types, no vacuous
passes), then `loader.py` was restored and `cd packages/localizer &&
../../venv/Scripts/python.exe -m pytest tests/test_flickr_plugin.py -v --no-cov` →
**37 passed, 0 failed**. No test was weakened to pass — every AC is satisfied by the
pre-collision implementation exactly as originally built (float typing via
`isinstance`, exact record counts rather than truthiness, `math.isnan` checks,
`is`-based bool/count assertions, black-box settings-coercion behavior, per-file
malformed-JSON isolation, glob selectivity, `since`-cursor filtering, no-network-
import scan).

Test names: `test_flickr_plugin_is_registered`, `test_flickr_plugin_plugin_id`,
`test_flickr_plugin_fetch_mode_manual`, `test_flickr_plugin_output_tables_places`,
`test_flickr_plugin_get_config_fields`,
`test_flickr_plugin_geotagged_only_field_is_bool_type_default_true`,
`test_flickr_plugin_manual_download_instructions`,
`test_fetch_records_geotagged_photo_yields_float_lat_lng`,
`test_fetch_records_non_geotagged_geotagged_only_true_yields_zero`,
`test_fetch_records_non_geotagged_geotagged_only_false_yields_nan`,
`test_fetch_records_geotagged_only_default_is_true`,
`test_fetch_records_geotagged_photo_always_included_regardless_of_toggle`,
`test_geotagged_only_string_coercion_from_settings` (parametrized x9: `"false"`,
`"False"`, `"0"`, `""`, `"no"`, `"No"`, `"true"`, `"1"`, `"yes"`),
`test_fetch_records_missing_title_yields_empty_place_name`,
`test_fetch_records_raw_json_preserves_tags_albums_description_photopage`,
`test_fetch_records_empty_export_dir_yields_empty_list`,
`test_fetch_records_nonexistent_export_dir_yields_empty_list`,
`test_fetch_records_unconfigured_export_dir_yields_empty_list`,
`test_fetch_records_multiple_files_all_parsed`,
`test_fetch_records_ignores_non_matching_files`,
`test_fetch_records_malformed_json_file_skipped_valid_still_yielded`,
`test_fetch_records_date_taken_parses_to_expected_timestamp`,
`test_fetch_records_unparseable_date_taken_falls_back_to_fetched_at`,
`test_fetch_records_since_cursor_excludes_older_photo`,
`test_fetch_records_dict_has_required_keys`, `test_fetch_records_source_id_is_flickr`,
`test_fetch_records_fetched_at_is_recent`, `test_flickr_loader_has_no_network_imports`.

`raw_json` tests accept either a dict or a JSON string (handoff.md explicitly permits
handing a dict straight to `store.upsert_places()`). No `LocalizerStore`/DuckDB
involved — all fixtures are `tmp_path`-based JSON files.

**IMPORTANT — also discovered during recovery**: `packages/localizer/tests/
test_untappd_plugin.py` (Subtask 3's test file) was ALSO wiped by the same collision
and has NOT been recovered — Subtask 3's `Test Files` block below is now stale/
inaccurate and must be redone by a fresh tester before Subtask 3's coder work is
trusted. Subtask 3 has no implementation yet, so this just means re-running its
test-ahead step, not a recovery like this one, and it will happen entirely inside
the isolated worktree from the start.

**Implementation Notes**:
`FlickrPlugin` was implemented (pre-collision) per Subtask 2's spec exactly:
`packages/localizer/src/localizer/plugins/flickr/__init__.py` (new, empty package
marker) and `packages/localizer/src/localizer/plugins/flickr/loader.py` (new),
mirroring `swarm/loader.py`'s directory-glob/graceful-empty-yield structure, with a
private `_coerce_bool` helper for `geotagged_only` string coercion, `date_taken`
parsing with a `fetched_at` fallback on parse failure, and NaN-lat/lng handling for
non-geotagged photos when `geotagged_only=False`. `packages/localizer/src/localizer/
plugins/__init__.py` was edited additively only (one import line inserted
alphabetically, one `REGISTRY[...] = FlickrPlugin` line appended) — re-applied by
hand in the isolated worktree after the original diff was lost to the collision
(the mangled `rtk`-wrapped `git diff` output saved as a backup wasn't a valid patch
for `git apply`; the two-line edit was re-typed directly instead, matching the
original exactly). Confirmed the registration edit disturbs no existing line —
Subtask 3's Untappd edit to the same function remains independently safe.

Re-verified in the isolated worktree's fresh, dedicated venv (not the shared main
checkout's venv, to avoid the same stale-editable-install class of bug seen in
Subtask 1): `cd packages/localizer && ../../venv/Scripts/python.exe -m pytest
tests/test_flickr_plugin.py -v --no-cov` → **37 passed, 0 failed**.

**Review Notes**:
Code Review: skipped by orchestrator instruction — the recovery process (fresh
tester rewrite + verified `ModuleNotFoundError`→GREEN round-trip + independent
lint/format checks, documented above) already covers everything a code-mode
reviewer would check, so this pass does both code review and owner review.

**Owner Review: APPROVED** — independently re-verified from scratch, not from
prior notes:

- Read `flickr/loader.py`, `flickr/__init__.py` (confirmed 0-byte package
  marker, matching `swarm/__init__.py`'s convention), the additive diff to
  `plugins/__init__.py`, and all 579 lines of `test_flickr_plugin.py`.
- Traced the geotagging logic line-by-line: `geo = data.get("geo")` combined
  with `isinstance(geo, dict) and geo` correctly treats `None`/missing/empty
  `geo` as non-geotagged; `lat`/`lng` are pre-seeded to `nan` before the
  `try`, so a partial/invalid `geo` dict safely falls back to non-geotagged
  instead of raising. `since` filtering and the `geotagged_only` skip are
  independent `continue`s — their order doesn't affect the yielded set.
  `raw_json = data` is the direct output of `json.loads()`, so it is
  JSON-round-trippable by construction (AC #7's serializability requirement
  is structurally guaranteed even though no test calls `json.dumps()` on it
  explicitly — traced as a non-issue, not a gap).
- Re-ran independently (not trusting the coder's reported numbers):
  `pytest tests/test_flickr_plugin.py -v --no-cov` → **37 passed**;
  `ruff check` on all 4 touched files → All checks passed; `ruff format
  --check` on all 4 → already formatted; `mypy` on `loader.py` → no issues
  (ignoring the known pre-existing Python-3.9 config warning, not this
  subtask's concern); full `packages/localizer` sub-suite → **249 passed**,
  0 failures (`test_untappd_plugin.py` doesn't exist yet in this worktree —
  Subtask 3's test-ahead phase hasn't been re-run here yet, exactly matching
  the recovery note; confirmed zero regression in `test_flickr_plugin.py` or
  any other sibling test file).
- Verified every AC against the passing tests one-by-one: registration,
  float lat/lng + `place_type=="photo"` for a geotagged photo, exact 0-vs-1
  record counts for both `geotagged_only` states against equivalent
  non-geotagged fixtures (not truthiness-based), `math.isnan` checks,
  missing-title → `""`, empty and nonexistent directories → `[]` without
  raising, multi-file glob correctness, `tags`/`albums`/`description`/
  `photopage` preserved verbatim in `raw_json`, and a static-source scan
  confirming no `requests`/`urllib`/`httpx`/`socket` import.
- Every Test Guidance item has a corresponding test (cross-checked against
  the full test list) — nothing called out in guidance is missing.
- Scope check: `git diff --stat` confirms `plugins/__init__.py`'s edit is
  exactly the 2 additive lines described (import + registry entry,
  alphabetically placed, disturbing no existing line — Subtask 3's Untappd
  edit to the same function remains independently safe).
- One process note (not a defect, not blocking): the working tree also
  carries an uncommitted one-line `pyproject.toml` ruff-ignore addition
  (`"packages/localizer/tests/*" = ["S", "B", "E501"]`) that isn't listed in
  this subtask's Files to Touch. Verified by temporarily stashing it and
  re-running `ruff check` on the test file: it fails with 3× `E501` without
  that line, so the addition is necessary, minimal, and precedented
  (identical to Subtask 1's own already-committed fix on its separate,
  not-yet-merged branch — this worktree's HEAD simply predates that commit
  landing on `main`). No action needed; noting it only so a future PR-close
  diff review isn't surprised by it.
- No dead code, no premature abstraction, naming and docstrings consistent
  with `swarm`/`letterboxd` sibling conventions, no secrets, no blocking
  calls, no network code. Diff is simple and scoped exactly to the subtask.

Subtask 2 is complete; `current` advanced to Subtask 3 (Untappd, `RED` per
the plan but its `Test Files` block is stale per the recovery note above —
a fresh tester must re-run the test-ahead step for Untappd inside this
isolated worktree before a coder begins).

---

### Subtask 3 — Add `UntappdPlugin` (issue #20)

**Status**: APPROVED

**PR Group**: untappd-plugin

**Depends On**: none

**Description**:
Add a new `UntappdPlugin` under `packages/localizer/src/localizer/plugins/untappd/`,
`OutputTable.EVENTS`, `FetchMode.MANUAL`, mirroring `letterboxd/loader.py`'s structure
almost exactly (the closest existing sibling: single CSV export file,
`FileNotFoundError` when a configured path doesn't exist, `fetch_records(csv_path=...)`
-style kwarg resolved from `LocalizerSettings` when not passed).

- **`fetch_records(self, since=None, progress_cb=None, checkins_csv: str | None = None)`**:
  when `checkins_csv` is `None`, resolve via
  `LocalizerSettings().get_setting("checkins_csv")` (same `try/except ImportError: pass`
  guard as Letterboxd); if still `None` after that, yield nothing (not configured is
  not an error). Otherwise delegate to a `_parse_csv(checkins_csv, since)` helper.
- **`_parse_csv()`**: raise `FileNotFoundError` (with a message naming the path and
  pointing at `untappd.com` → Settings → Export Data) if the configured path does not
  exist — mirrors Letterboxd's exact behavior for a configured-but-missing file. Parse
  with `csv.DictReader`. For each row:
  - Parse `created_at` to a Unix timestamp using the same forgiving
    space-to-`"T"`-then-`datetime.fromisoformat` approach used by `swarm/loader.py`'s
    fallback parser; on failure, fall back to this batch's `fetched_at`.
  - `label = row.get("brewery_name", "") or ""`, `sublabel = row.get("beer_name", "") or ""`,
    `category = row.get("beer_type", "") or ""` — per issue #20's explicit mapping.
  - Parse `rating_score` to a Python `float`, or `None` if blank/unparseable (never a
    raw string, never `NaN` — same "`raw_json` must stay valid JSON" reasoning as
    Subtask 1's rating fix).
  - Parse `venue_lat`/`venue_lng` to Python `float`s, or `None` each if blank/
    unparseable (this is the "check-in without a venue" case — represented as JSON
    `null`, not `NaN`, since these live only inside `raw_json` and `events` has no
    lat/lng columns at all per `store/schema.py`).
  - Build `raw_json` as the full raw CSV row (`dict(row)`, preserving `comment`,
    `flavor_profiles`, `serving_type`, `photo_url` verbatim) plus overridden/added
    typed keys: `"rating"`, `"venue_name"` (`row.get("venue_name", "") or ""`),
    `"venue_lat"`, `"venue_lng"` — then `json.dumps()`'d.
  - Honor `since`: skip rows whose parsed timestamp is `<= since`.
- **`get_config_fields()`**: one `file_path` field, `key="checkins_csv"`.
- **`get_manual_download_instructions()`**: multi-line string mentioning
  `untappd.com` and `csv`.
- Register in `packages/localizer/src/localizer/plugins/__init__.py`: add
  `from localizer.plugins.untappd.loader import UntappdPlugin` to the import block and
  `REGISTRY[UntappdPlugin.PLUGIN_ID] = UntappdPlugin` — additive only, same caution as
  Subtask 2 about not disturbing Flickr's lines in this shared function.

**Acceptance Criteria**:
- [ ] `UntappdPlugin` is present in `REGISTRY` after `REGISTRY.clear(); load_builtin_plugins()`.
- [ ] `created_at` values in both a space-separated (`"2023-06-15 18:30:00"`) and a
  `T`-separated ISO form (`"2023-06-15T18:30:00"`) both parse to the same correct Unix
  timestamp for equivalent inputs — proving the parser isn't accidentally coupled to
  only one literal format.
- [ ] A check-in row with blank `venue_lat`/`venue_lng`/`venue_name` produces
  `json.loads(record["raw_json"])["venue_lat"] is None` and
  `[...]["venue_lng"] is None` (checked with `is None`, not falsiness) — while a
  check-in row *with* a venue produces the exact float values from the CSV, matching
  row-for-row (not just "some rows have venues").
  - **AC caution**: this must be checked via `json.loads`, not by inspecting a
    top-level `record["venue_lat"]` key — the schema has no such DB column, so any
    top-level key beyond the seven `EVENTS`-schema keys is silently dropped by
    `store.upsert_events()` and is not part of this plugin's real contract.
- [ ] An unrated check-in (`rating_score` blank) produces
  `json.loads(record["raw_json"])["rating"] is None`.
- [ ] An empty CSV (header row only, zero data rows) yields an empty list, no
  exception.
- [ ] `label`/`sublabel`/`category` on a known fixture row match `brewery_name`/
  `beer_name`/`beer_type` exactly (row-for-row, by a specific known value — e.g.
  brewery `"Test Brewery Co."` / beer `"Hazy IPA"` / style `"IPA"` — not just "three
  distinct strings exist").
- [ ] `packages/localizer/src/localizer/plugins/untappd/loader.py` contains no
  `import requests`, `urllib`, `httpx`, or `socket`.

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/untappd/__init__.py` (new, empty package
  marker)
- `packages/localizer/src/localizer/plugins/untappd/loader.py` (new)
- `packages/localizer/src/localizer/plugins/__init__.py` (edit: additive import +
  registry entry only)
- `packages/localizer/tests/test_untappd_plugin.py` (new)

**Test Guidance**:
- Cover every edge case issue #20 names explicitly: basic load, unrated check-in,
  check-in without a venue, empty CSV — each its own test.
- Also cover: `created_at` parsed correctly (both date-format variants above), a
  configured-but-nonexistent `checkins_csv` path raising `FileNotFoundError`, an
  unconfigured plugin (`checkins_csv=None`, no `LocalizerSettings` override) yielding
  nothing rather than raising, and the `since` cursor excluding an older row.
- Verify `raw_json` round-trips through `json.loads` cleanly on every row, including
  rows with `None` values inside it (proves no stray `NaN`/non-serializable value
  leaks in from the float-parsing logic).
- Test `get_config_fields()` and `get_manual_download_instructions()` shape/wording
  the same way the other two subtasks do.
- Do not route any test through `LocalizerStore`/DuckDB — isolate `fetch_records()`
  with `tmp_path`-based CSV fixtures, matching every sibling plugin test file.

**Test Files**:
**Recovery note**: this subtask's original test file was lost to the same collision
documented in Subtask 2's Test Files section, before any coder had touched Untappd —
so this was simply re-run as a normal test-ahead pass, entirely inside the isolated
worktree (`C:\Users\johns\Code\autobiographer\.claude\worktrees\
localizer-plugins-flickr-untappd`), with no recovery/reconstruction needed.

`packages/localizer/tests/test_untappd_plugin.py` (new — 29 test functions: 28
exercise the plugin, 1 is a `csv.DictReader` fixture sanity check with no plugin
import, expected to pass immediately and stay passing after implementation).
Confirmed RED: `cd packages/localizer && ../../venv/Scripts/python.exe -m pytest
tests/test_untappd_plugin.py -v --no-cov` → **28 failed, 1 passed** (the 1 pass is
the fixture sanity check, not a plugin test). All 28 plugin-test failures are either
`ModuleNotFoundError: No module named 'localizer.plugins.untappd'` or, for
`test_untappd_is_registered`, an `AssertionError` on `REGISTRY` membership — no
vacuous passes.

Test names: `test_untappd_plugin_id`, `test_untappd_fetch_mode_manual`,
`test_untappd_output_tables_events`, `test_untappd_is_registered`,
`test_untappd_get_config_fields_shape`, `test_untappd_manual_download_instructions`,
`test_untappd_fetch_records_from_csv_count`, `test_untappd_required_keys_present`,
`test_untappd_source_id_is_untappd`, `test_untappd_fetched_at_is_recent`,
`test_untappd_label_sublabel_category_mapping`,
`test_untappd_created_at_space_separated_parses`,
`test_untappd_created_at_t_separated_parses`,
`test_untappd_created_at_formats_are_equivalent`,
`test_untappd_unparseable_created_at_falls_back_to_fetched_at`,
`test_untappd_rated_checkin_rating_is_float`,
`test_untappd_unrated_checkin_rating_is_none`,
`test_untappd_checkin_with_venue_has_float_lat_lng_in_raw_json`,
`test_untappd_checkin_without_venue_has_none_lat_lng_in_raw_json`,
`test_untappd_no_top_level_venue_lat_lng_keys` (guards AC caution: venue lat/lng must
only be checked via `json.loads(raw_json)`, never a top-level `record` key, since
`events` has no such DB column),
`test_untappd_raw_json_round_trips_and_preserves_fields`,
`test_untappd_raw_json_none_values_round_trip`,
`test_untappd_empty_csv_yields_empty_list`, `test_untappd_missing_csv_raises_file_not_found`,
`test_untappd_missing_csv_error_mentions_untappd`,
`test_untappd_unconfigured_yields_nothing`, `test_untappd_since_cursor_excludes_older_row`,
`test_untappd_loader_has_no_network_imports`, `test_untappd_parses_header_columns_via_dictreader`
(the fixture sanity check).

Tests expect `UntappdPlugin.fetch_records(self, since=None, progress_cb=None,
checkins_csv=None)` with `checkins_csv` resolved from
`LocalizerSettings().get_setting("checkins_csv")` when `None`, `raw_json` built as
`dict(row)` plus overridden `rating`/`venue_name`/`venue_lat`/`venue_lng` keys (all
`None` when blank, never `NaN`/string), and `label`/`sublabel`/`category` =
`brewery_name`/`beer_name`/`beer_type` per the plan's explicit mapping (fixture row:
brewery `"Test Brewery Co."` / beer `"Hazy IPA"` / style `"IPA"`). No
`LocalizerStore`/DuckDB involved — `tmp_path`-based CSV fixtures only. No
implementation files exist yet and `plugins/__init__.py` was not touched.

**Implementation Notes**:
Created `UntappdPlugin` under
`packages/localizer/src/localizer/plugins/untappd/` mirroring
`letterboxd/loader.py`'s structure almost exactly, per the subtask spec:

- `packages/localizer/src/localizer/plugins/untappd/__init__.py` — new,
  empty package marker (matches the `letterboxd`/`swarm` convention).
- `packages/localizer/src/localizer/plugins/untappd/loader.py` — new.
  `UntappdPlugin` has no custom `__init__` (the CSV path is resolved
  lazily inside `fetch_records()`, exactly like Letterboxd, not in the
  constructor like Swarm/Flickr — the test suite instantiates
  `UntappdPlugin()` with zero args and passes `checkins_csv` per-call).
  `fetch_records(self, since=None, progress_cb=None, checkins_csv=None)`
  resolves `checkins_csv` from `LocalizerSettings().get_setting("checkins_csv")`
  inside a `try/except ImportError: pass` guard when not passed in; if still
  `None`, yields nothing. `_parse_csv()` raises `FileNotFoundError` (message
  names the path and points at `untappd.com` → Settings → Export Data) when
  a configured path doesn't exist, then parses with `csv.DictReader`.
  `created_at` is parsed via the same forgiving
  `str.replace(" ", "T")` + `datetime.fromisoformat()` approach used by
  `swarm/loader.py`'s fallback parser, falling back to this batch's
  `fetched_at` on any `ValueError` (covers both the space-separated and
  T-separated formats identically, and the fully-unparseable case).
  `label`/`sublabel`/`category` map to `brewery_name`/`beer_name`/
  `beer_type` per issue #20. A small private `_parse_optional_float()`
  helper parses `rating_score`/`venue_lat`/`venue_lng` to a Python `float`
  or `None` (never a raw string, never `NaN`) — used for all three fields.
  `raw_json` is built as `dict(row)` (preserving `comment`,
  `flavor_profiles`, `serving_type`, `photo_url`, and the original raw
  `rating_score`/`venue_lat`/`venue_lng`/`venue_name` columns verbatim)
  with `"rating"`, `"venue_name"`, `"venue_lat"`, `"venue_lng"` added/
  overridden as typed values on top, then `json.dumps()`'d — matching
  Subtask 1's letterboxd rating-fix reasoning (JSON `null`, not `NaN`, for
  "missing" inside a JSON-embedded field). The `since` cursor is applied
  before yielding (`timestamp <= since` is skipped), consistent with the
  other plugins.
- `packages/localizer/src/localizer/plugins/__init__.py` — edited
  additively only inside `load_builtin_plugins()`: one import line
  (`from localizer.plugins.untappd.loader import UntappdPlugin`) inserted
  alphabetically after the `swarm` import, and one
  `REGISTRY[UntappdPlugin.PLUGIN_ID] = UntappdPlugin` line appended after
  the existing `FlickrPlugin` registration line. No existing line
  (including Subtask 2's Flickr lines) was reordered, removed, or
  otherwise touched.

No deviations from the plan; no files touched beyond the four listed in
Subtask 3's "Files to Touch".

Test run: `cd packages/localizer && ../../venv/Scripts/python.exe -m pytest
tests/test_untappd_plugin.py -v --no-cov` → **29 passed** (28 plugin tests +
1 fixture sanity check).

Full sub-suite: `cd packages/localizer && ../../venv/Scripts/python.exe -m
pytest -q --no-cov` → **278 passed**, 0 failures (up from the prior
249-passed baseline noted in Subtask 2's Owner Review, +29 for this
subtask's new test file — no regressions in Flickr, Letterboxd, or any
other sibling plugin's tests).

Lint: `./venv/Scripts/python.exe -m ruff check --fix
packages/localizer/src/localizer/plugins/untappd/
packages/localizer/src/localizer/plugins/__init__.py` → "All checks
passed!"; `./venv/Scripts/python.exe -m ruff format
packages/localizer/src/localizer/plugins/untappd/
packages/localizer/src/localizer/plugins/__init__.py` → "3 files left
unchanged" (already correctly formatted, no auto-fix needed). `./venv/
Scripts/python.exe -m mypy
packages/localizer/src/localizer/plugins/untappd/loader.py` → "Success: no
issues found in 1 source file" (ignoring the known pre-existing
Python-3.9-not-supported config warning, per instructions).

**Review Notes**:
Code Review: skipped by orchestrator instruction — status went GREEN straight to
owner review (mirrors Subtask 2's mid-task-collision shortcut), so this pass covers
both code review and owner review.

**Owner Review: APPROVED** — independently re-verified from scratch, not from prior
notes:

- Read `untappd/loader.py`, `untappd/__init__.py` (confirmed 0-byte package marker,
  matching sibling convention), the additive diff to `plugins/__init__.py`, and all
  538 lines of `test_untappd_plugin.py`. Cross-referenced against `letterboxd/loader.py`
  (the sibling it mirrors) and `base.py`'s `SourcePlugin` ABC.
- Traced every AC line-by-line: `label`/`sublabel`/`category` = `brewery_name`/
  `beer_name`/`beer_type` verified against the plan's named fixture values ("Test
  Brewery Co."/"Hazy IPA"/"IPA"); `created_at` parsing (`.replace(" ", "T")` +
  `datetime.fromisoformat()`) correctly unifies space- and T-separated forms and
  falls back to `fetched_at` inside a `try/except ValueError` on any unparseable
  value; the shared `_parse_optional_float()` helper returns a typed `float` or
  `None` (never a raw string, never `NaN`) for `rating_score`/`venue_lat`/`venue_lng`,
  used consistently for all three; `venue_lat`/`venue_lng` never leak as top-level
  record keys (own dedicated test); `FileNotFoundError` is raised only for a
  configured-but-missing path, naming both the path and `untappd.com`; an
  unconfigured plugin (`checkins_csv=None`, no settings override) yields nothing
  rather than raising; the `since` cursor correctly excludes rows with
  `timestamp <= since`.
- Re-ran independently (not trusting the coder's reported numbers):
  `pytest tests/test_untappd_plugin.py -v --no-cov` → **29 passed**; `ruff check`
  on all 4 touched files (`untappd/__init__.py`, `untappd/loader.py`,
  `plugins/__init__.py`, `tests/test_untappd_plugin.py`) → All checks passed;
  `ruff format --check` on all 4 → already formatted; `mypy` on `loader.py` →
  no issues (ignoring the known pre-existing Python-3.9-config warning). Full
  `packages/localizer` sub-suite → **278 passed, 0 failures** — fully green with
  zero residual/expected failures, as required since this is the last subtask in
  the plan.
- Every Test Guidance item has a corresponding test (basic load, unrated check-in,
  no-venue check-in, empty CSV, both `created_at` format variants plus their
  equivalence, missing-path `FileNotFoundError` + message wording, unconfigured
  yields nothing, `since` cursor, `raw_json` round-trip including `None` values,
  `get_config_fields`/`get_manual_download_instructions` shape/wording, no
  `LocalizerStore`/DuckDB usage) — several exceeded (top-level-key-leak guard,
  unparseable-date fallback, no-network-import static scan, DictReader fixture
  sanity check).
- Scope check: `git diff --stat` on `plugins/__init__.py` shows exactly 4 additive
  lines (2 for Flickr's import/registration from Subtask 2, 2 for Untappd's from
  this subtask, against the pre-worktree base) — nothing reordered or removed,
  matching the "both edits must be independently additive and non-conflicting"
  requirement from both subtasks' specs. The 1-line `pyproject.toml` ruff-ignore
  addition (`"packages/localizer/tests/*" = ["S", "B", "E501"]`) is the same
  necessary, minimal, precedented line already vetted in Subtask 2's Owner Review
  — not new scope creep introduced here.
- No dead code, no premature abstraction, no secrets, no blocking/network calls
  (`import requests`/`urllib`/`httpx`/`socket` absent, confirmed both by static
  read and by the dedicated test). Naming, docstrings, and structure are
  consistent with the `letterboxd` sibling this subtask mirrors almost exactly,
  per the subtask's own design intent. Diff is simple and scoped exactly to the
  subtask's Files to Touch.

Subtask 3 is complete and APPROVED. This was the last subtask in the plan — all
three subtasks (Letterboxd field-mapping fix, Flickr, Untappd) now show
`Status: APPROVED`. Each subtask has its own `PR Group` (`letterboxd-field-mapping-fix`,
`flickr-plugin`, `untappd-plugin`), so per `AGENTS.md`'s "After each subtask is
APPROVED" section, PR group `untappd-plugin` (containing only this subtask) is now
ready to close: full-suite integration gate, branch/commit, and `gh pr create` are
the orchestrator's responsibility, not performed here. `Plan Status` is set to
`COMPLETE` below since no subtasks remain.

---
