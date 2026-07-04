# Handoff

## Plan Status
status: COMPLETE

**Final summary**: Built the localizer-side counterpart to the legacy Google Maps Timeline
plugin so Timeline exports flow into `~/.localizer/store.duckdb` alongside every other source.
Subtask 1 added `GoogleTimelinePlugin` (`packages/localizer/src/localizer/plugins/
google_timeline/loader.py`), wrapping `analysis_utils.load_google_timeline()` and reusing the
legacy plugin's `venue`/`venue_category` → `place_name`/`place_type` mapping verbatim, with
`ValueError` (unsupported/legacy export format) translated to `OSError` so one bad file can't
kill `localizer sync` for other plugins, and a distinct `google_timeline_path` settings key kept
separate from the legacy Streamlit session-state key. Subtask 2 wired it into
`load_builtin_plugins()` (2-line additive change: one import, one registry assignment,
alphabetically placed). Subtask 3 documented it in `packages/localizer/README.md`: a
`localizer sources` listing, a `### Google Maps Timeline` subsection covering the manual/
no-network export flow, and an updated `places` table `source_id` example. Total new/changed
tests: 26 (23 in `test_google_timeline_plugin.py`, 3 added to `test_cli.py`); full localizer
suite is 187/187 passing. `ruff check .`, `ruff format --check .`, and `mypy` all exit 0
unscoped from the repo root. All three subtasks share PR Group `google-timeline-localizer-plugin`
and are now ready for the orchestrator's full-suite integration gate, branch/commit, and PR.

## Task Overview

PR #111 added a Google Maps Timeline source to the **legacy** plugin system
(`plugins/sources/google_timeline/`) only. That plugin is done and must not be
touched. This plan adds the missing **localizer-side** counterpart so Timeline
data can flow into `~/.localizer/store.duckdb` like every other source
(`swarm`, `lastfm`, `github`, `feedly`, `rss`, `letterboxd`), making it visible
to `LocalizerBroker` / `localizer sync` / `localizer sources`.

The new plugin is additive only: a new package
`packages/localizer/src/localizer/plugins/google_timeline/` alongside the
existing localizer plugins, registered in `load_builtin_plugins()`, and
documented in `packages/localizer/README.md`. It reuses
`analysis_utils.load_google_timeline()` (the existing JSON parser, already
tested in `tests/test_google_timeline.py`) for parsing, and reuses the exact
`venue`/`venue_category` → `place_name`/`place_type` column mapping that the
legacy plugin's `load()` already performs — no new parsing or mapping logic is
invented.

**Architecture context**: No prior `/feature-dev` or `/plan-feature` run
occurred for this task; scope was specified directly by the user with
concrete file-level context. Two design decisions were made during planning
(not fully specified by the user) and are recorded here so later agents don't
re-litigate them:

1. **Settings key name**: the new plugin reads its configured file path from
   `LocalizerSettings().get_setting("google_timeline_path")` — a distinct flat
   key from the legacy plugin's Streamlit session-state key `timeline_path`.
   The two systems have independent config surfaces (`~/.localizer/config.toml`
   vs. Streamlit session state / `components/plugin_config.py`), so there is no
   collision to resolve and no reason to share a key.
2. **Error translation (ValueError → OSError)**: `load_google_timeline()`
   raises `ValueError` when given an unsupported/legacy-format file (e.g. a
   pre-2024 `Records.json` export instead of the new `Timeline.json`). The
   localizer CLI's `sync`/`fetch --dry-run` commands (`packages/localizer/src/
   localizer/cli.py`, `sync_cmd`) only catch `OSError` per-plugin to skip a
   misconfigured source gracefully — any other exception propagates and kills
   the entire `sync` run for every plugin, not just this one. This is also the
   documented contract in `packages/localizer/README.md`'s "Writing a plugin"
   section: *"Raise `OSError` ... when required credentials or paths are
   missing — the CLI catches `OSError` and skips the plugin gracefully."*
   Therefore `fetch_records()` must catch the `ValueError` from
   `load_google_timeline()` and re-raise it as `OSError` so one user's
   unsupported/legacy export doesn't crash `localizer sync` for every other
   source. A missing/nonexistent path is handled separately and does **not**
   raise anything — `load_google_timeline()` already returns an empty
   DataFrame in that case (mirrors Swarm's "missing directory yields nothing"
   behavior), so `fetch_records()` simply yields nothing.

Plan Review: APPROVED — Three subtasks (plugin implementation, registry wiring, README docs) form a valid DAG (1 → 2 → 3, matching `current:` order), touch disjoint source files and disjoint test files (new `test_google_timeline_plugin.py` in Subtask 1, additions to existing `test_cli.py` in Subtask 2, docs-only with no new test file in Subtask 3), each have falsifiable acceptance criteria and edge-case-specific Test Guidance, and both recorded design decisions were verified directly against the code: `cli.py::sync_cmd` catches only `OSError` per-plugin in both its dry-run (line 424) and real-sync (line 458) branches, and the legacy plugin's `venue`/`venue_category` → `place_name`/`place_type` mapping is exactly at `plugins/sources/google_timeline/loader.py` lines 76-80 as cited.

## Current Subtask
current: 3

---

## Subtasks

### Subtask 1 — Implement the localizer Google Timeline plugin

**Status**: APPROVED

**PR Group**: google-timeline-localizer-plugin

**Depends On**: none

**Description**:
Create `GoogleTimelinePlugin`, a `localizer.plugins.base.SourcePlugin`
subclass that wraps `analysis_utils.load_google_timeline()` and yields
`OutputTable.PLACES`-shaped record dicts. This mirrors
`packages/localizer/src/localizer/plugins/swarm/loader.py`'s structure
(`FetchMode.MANUAL`, a single config-field path, directory/file read in
`fetch_records()`, settings-based path resolution in `__init__`), but reads a
single `Timeline.json` file instead of a directory of check-in files, and
performs the same `venue`/`venue_category` → `place_name`/`place_type`
mapping the legacy plugin's `load()` already does (see
`plugins/sources/google_timeline/loader.py` lines 76-80).

Scoped to this subtask only: the plugin class and its own unit tests. It is
NOT wired into `load_builtin_plugins()` yet (Subtask 2) and the README is not
updated yet (Subtask 3) — the plugin is fully testable in isolation by
importing the module directly and instantiating the class, exactly as
`test_swarm_plugin.py` does before Swarm's registry wiring is exercised.

**Acceptance Criteria**:
- [ ] `GoogleTimelinePlugin` (in
  `packages/localizer/src/localizer/plugins/google_timeline/loader.py`) has
  `PLUGIN_ID == "google_timeline"`, `DISPLAY_NAME`, `FETCH_MODE ==
  FetchMode.MANUAL`, and `OutputTable.PLACES in OUTPUT_TABLES`.
- [ ] `fetch_records()` on a valid `Timeline.json` fixture (containing at
  least one `visit` segment and one `activity` segment, matching the fixture
  shapes used in `tests/test_google_timeline.py`) yields one dict per segment,
  each containing exactly the keys `source_id, timestamp, lat, lng,
  place_name, place_type, raw_json, fetched_at`, with `place_name`/
  `place_type` equal to the parser's `venue`/`venue_category` values for that
  row (not re-derived from raw JSON).
- [ ] `fetch_records()` yields nothing and raises no exception when no path is
  configured (`GoogleTimelinePlugin()` with no arg and no settings entry) and
  when the configured path does not exist on disk.
- [ ] `fetch_records()` raises `OSError` (never lets the underlying
  `ValueError` escape) when `load_google_timeline()` rejects an unsupported/
  legacy-format file (e.g. JSON without a top-level `semanticSegments` key).
- [ ] `ruff check .`, `ruff format --check .`, `mypy`, and `pytest` (with
  `--cov-fail-under=70`, per `pyproject.toml`) all exit 0.

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/google_timeline/__init__.py` (new — empty, matching `swarm/__init__.py`)
- `packages/localizer/src/localizer/plugins/google_timeline/loader.py` (new)

**Test Guidance**:
- Mirror `packages/localizer/tests/test_swarm_plugin.py`'s structure and
  naming conventions in a new file
  `packages/localizer/tests/test_google_timeline_plugin.py`. Do NOT add a
  `REGISTRY`/`load_builtin_plugins()` test here — that requires Subtask 2's
  wiring and belongs there instead, to keep this subtask's test file
  independently RED/GREEN without depending on later work.
- Class-attribute tests: `PLUGIN_ID`, `FETCH_MODE`, `OUTPUT_TABLES`, `ICON`.
- `get_config_fields()` returns a non-empty list; each field dict has `key`
  and `label`. Confirm the field's `key` is `"google_timeline_path"` (the
  chosen settings key — see Task Overview decision #1), distinct from the
  legacy plugin's `"timeline_path"` session-state key.
- `get_manual_download_instructions()` returns a non-empty string.
- Build a minimal `Timeline.json` fixture dict with `semanticSegments`
  containing one `visit` segment (with `topCandidate.placeLocation.latLng`,
  `semanticType`, optionally a `userLocationProfile.frequentPlaces` label) and
  one `activity` segment (with `start.latLng`, `topCandidate.type`) — reuse
  the fixture-building helpers/patterns already present in
  `tests/test_google_timeline.py` rather than inventing new ones from scratch.
- Verify record count matches the number of parseable segments, and that
  `place_name`/`place_type` for the visit segment equal the parser's
  `venue`/`venue_category` output (e.g. a frequent-place label or humanized
  semantic type; `"home"`-style lowercase category), and for the activity
  segment `place_type` starts with `"activity:"`.
- `lat`/`lng` are Python `float`; `timestamp` is Python `int`; `fetched_at` is
  an `int` unix timestamp within ~60 seconds of "now" (mirror
  `test_fetch_records_fetched_at_is_recent` from the Swarm test file).
- `source_id` is always `"google_timeline"` on every yielded record.
- `since` filtering: a record with `timestamp <= since` must be excluded when
  `since` is passed to `fetch_records()`.
- No-path case: `GoogleTimelinePlugin()` (no arg, and with
  `LocalizerSettings.get_setting` returning `None`/unset) → `fetch_records()`
  yields `[]`, no exception raised.
- Missing-file case: `GoogleTimelinePlugin(timeline_path=str(tmp_path /
  "does_not_exist.json"))` → `fetch_records()` yields `[]`, no exception
  raised (mirror `test_fetch_records_missing_dir` from Swarm).
- Unsupported-format case: write a JSON file that is a dict without a
  top-level `semanticSegments` key (e.g. a bare `{"foo": "bar"}` or a
  `Records.json`-shaped legacy export) → iterating `fetch_records()` must
  raise `OSError`, and must NOT raise `ValueError` (assert the exact
  exception type, not just "raises `Exception`", so a future regression that
  lets the raw `ValueError` leak is caught).
- Settings integration: when constructed with no explicit path,
  `__init__` must read `LocalizerSettings().get_setting("google_timeline_path")`.
  Test by monkeypatching `LocalizerSettings.get_setting` (or writing a real
  config file via `LOCALIZER_CONFIG_PATH` env var, matching the pattern in
  `packages/localizer/tests/test_settings.py`) and asserting the resolved
  path is used.
- `raw_json` on each yielded record must be JSON-serializable (dict or str) —
  mirror `test_fetch_records_raw_json_is_serializable` from Swarm.

**Test Files**:
- `packages/localizer/tests/test_google_timeline_plugin.py` (new) — 23 tests, all RED with
  `ModuleNotFoundError: No module named 'localizer.plugins.google_timeline'`:
  `test_google_timeline_plugin_plugin_id`, `test_google_timeline_plugin_display_name_is_set`,
  `test_google_timeline_plugin_fetch_mode_manual`, `test_google_timeline_plugin_output_tables_places`,
  `test_google_timeline_plugin_icon_is_set`, `test_google_timeline_plugin_get_config_fields`,
  `test_google_timeline_plugin_manual_download_instructions`,
  `test_fetch_records_yields_one_dict_per_segment`, `test_fetch_records_dict_has_required_keys`,
  `test_fetch_records_source_id_is_google_timeline`, `test_fetch_records_lat_lng_are_floats`,
  `test_fetch_records_timestamp_is_int`, `test_fetch_records_visit_place_name_and_type_match_parser`,
  `test_fetch_records_activity_place_type_starts_with_activity_prefix`,
  `test_fetch_records_fetched_at_is_recent`, `test_fetch_records_raw_json_is_serializable`,
  `test_fetch_records_since_filtering_excludes_older_record`,
  `test_fetch_records_no_path_configured_yields_nothing`, `test_fetch_records_missing_file_yields_nothing`,
  `test_fetch_records_unsupported_format_raises_oserror`,
  `test_fetch_records_legacy_records_format_raises_oserror`, `test_init_reads_path_from_localizer_settings`,
  `test_explicit_path_overrides_settings`.
- Tests stub `reverse_geocoder.search` via an autouse fixture so the parser's optional geocoding
  doesn't slow down or affect determinism — coder should not need to touch this.
- Constructor contract the tests assume: `GoogleTimelinePlugin(timeline_path: str | None = None)`,
  falling back to `LocalizerSettings().get_setting("google_timeline_path")` when unset.

**Implementation Notes**:
Created `packages/localizer/src/localizer/plugins/google_timeline/__init__.py` (empty) and
`.../google_timeline/loader.py` implementing `GoogleTimelinePlugin(SourcePlugin)`:
`PLUGIN_ID = "google_timeline"`, `DISPLAY_NAME = "Google Maps Timeline"`,
`FETCH_MODE = FetchMode.MANUAL`, `OUTPUT_TABLES = [OutputTable.PLACES]`,
`ICON = ":material/map:"`. `__init__(timeline_path=None)` falls back to
`LocalizerSettings().get_setting("google_timeline_path")` when no explicit path is given.
`get_config_fields()` returns a single `google_timeline_path` file field.
`get_manual_download_instructions()` documents both the on-device export and Google Takeout
flows, reusing the wording style of the legacy plugin. `fetch_records()` wraps
`analysis_utils.load_google_timeline()` (imported lazily to avoid a hard dependency from
localizer on the top-level app), yields one dict per parsed row with keys
`source_id/timestamp/lat/lng/place_name/place_type/raw_json/fetched_at` — `place_name`/
`place_type` are taken verbatim from the parser's `venue`/`venue_category` columns, no
re-derivation. Catches the parser's `ValueError` (unsupported/legacy format) and re-raises
as `OSError` so `localizer sync` can skip this source without killing other plugins. No path
configured or a nonexistent file both yield nothing without raising, since
`load_google_timeline()` already returns an empty DataFrame in both cases. `since` filtering
excludes records with `timestamp <= since`. Not yet wired into `load_builtin_plugins()`
(Subtask 2) — importable and testable standalone, matching the Swarm plugin's pre-wiring state.

Test results: all 23 tests in `packages/localizer/tests/test_google_timeline_plugin.py` pass.
`ruff check` and `ruff format --check` scoped to the new package both exit 0; `mypy` scoped to
the new package exits 0 with no issues. (Scoped coverage run reports low % because only this
one test file was run in isolation — the full-suite coverage gate is deferred to the PR-close
step per AGENTS.md.)

**Formatting fix (post NEEDS_REVISION)**: Ran `ruff format
packages/localizer/tests/test_google_timeline_plugin.py`, which reformatted 1 file — collapsing
the multi-line `legacy_file.write_text(json.dumps({"locations": [...]}), encoding="utf-8")` call
in `test_fetch_records_legacy_records_format_raises_oserror` and the multi-line
`test_explicit_path_overrides_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:`
signature each onto a single line (both fit within the project's line-length limit). No logic,
test names, or assertions changed — purely mechanical formatting. Re-verified **unscoped** from
the repo root: `ruff format --check .` now reports "125 files already formatted" (0 need
reformatting); `ruff check .` reports "All checks passed!"; `mypy` (unscoped) reports "Success:
no issues found in 14 source files"; `pytest
packages/localizer/tests/test_google_timeline_plugin.py -v --no-cov` reports all 23/23 tests
still passing. All four acceptance-criterion-5 commands now exit 0 unscoped.

**Review Notes**:
Code Review: APPROVED — checks clean. `ruff check`/`ruff format --check` scoped to
`packages/localizer/src/localizer/plugins/google_timeline/` both pass; `mypy` scoped to the
same package reports no issues; `pytest packages/localizer/tests/test_google_timeline_plugin.py
-v --no-cov` passes all 23/23 (coverage flag dropped deliberately for this scoped run per
AGENTS.md — full-suite coverage gate is deferred to PR-close). Verified against
`analysis_utils.load_google_timeline()`'s actual output columns
(`timestamp/offset/city/state/country/venue/venue_category/lat/lng/event_category/shout` from
`_WHERE_WHEN_COLUMNS`) that every key `fetch_records()` reads off each row exists — no
`KeyError` risk. Confirmed both Task Overview design decisions are implemented exactly as
specified: (1) `get_config_fields()`'s `key` is the distinct flat string
`"google_timeline_path"`, not the legacy plugin's `"timeline_path"`; (2) `fetch_records()`
catches the parser's `ValueError` and re-raises `OSError` so a legacy/unsupported export can't
kill `localizer sync` for other plugins, while a missing path/file yields nothing without
raising (matches `load_google_timeline()`'s own empty-DataFrame contract). `place_name`/
`place_type` are taken verbatim from `row["venue"]`/`row["venue_category"]` with no
re-derivation, matching the legacy plugin's mapping at
`plugins/sources/google_timeline/loader.py` lines 76-80. Structure mirrors
`packages/localizer/src/localizer/plugins/swarm/loader.py` (`@register` decorator,
`FetchMode.MANUAL`, settings-fallback `__init__`, lazy imports for `LocalizerSettings` and
`analysis_utils`); `__init__.py` is empty, matching `swarm/__init__.py` byte-for-byte (0
bytes). No dead code, no secrets/credentials, no N+1 or hot-path sync-call concerns (single
JSON file parse, no loop-driven I/O). No issues found.

Owner Review: APPROVED — Re-ran the full acceptance-criteria gate from the repo root myself
(venv python, not trusting the report alone): `ruff format --check .` now reports "125 files
already formatted" (0 need reformatting, was previously flagging this test file); `ruff check .`
reports "All checks passed!"; `mypy` (unscoped) reports "Success: no issues found in 14 source
files"; `pytest packages/localizer/tests/test_google_timeline_plugin.py -v --no-cov` passes
23/23. Confirmed the only changes were the two mechanical single-line collapses previously
identified — read both spots directly: `test_fetch_records_legacy_records_format_raises_oserror`
(line 425-430) and `test_explicit_path_overrides_settings` (line 472) — both now single-line
statements with identical logic, no assertion, docstring, or test-name changes. The test file is
untracked (new file, no git history to diff against), so verification relied on direct reading of
the flagged spots plus the full 23/23 pass and matching the previously-reported test name list.
All acceptance criteria for Subtask 1 are met; implementation logic (key names, OSError
translation, verbatim venue/venue_category mapping, since-filtering) was already verified correct
in the prior Code Review pass. No new issues found.

---PRIOR NEEDS_REVISION (resolved, kept for history)---
Owner Review: NEEDS_REVISION — Re-ran the acceptance-criteria gate from the repo root myself
(not trusting the prior review's scoped result): `ruff format --check .` **fails** — "Would
reformat: packages\localizer\tests\test_google_timeline_plugin.py" (1 file would be
reformatted, 124 already formatted). `ruff format --diff` on that file shows two concrete
hunks: (1) the multi-line `legacy_file.write_text(json.dumps({"locations": [...]}),
encoding="utf-8")` call in `test_fetch_records_legacy_records_format_raises_oserror` (originally
around line 429) collapses to one line under the formatter; (2) the multi-line `def
test_explicit_path_overrides_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) ->
None:` signature (originally around line 474) also collapses to one line. Both fit within the
project's line-length limit once joined, so `ruff format` treats the existing multi-line form
as unformatted. This is the exact violation a previous owner-review attempt reported (whose
handoff.md edit never persisted) — independently reconfirmed here by running the command
myself. The prior Code Review's approval scoped its `ruff format --check` run to
`packages/localizer/src/localizer/plugins/google_timeline/` only, which excludes the tests
directory and is why it missed this. `ruff check .` (unscoped), `mypy` (scoped to the new
package), and `pytest packages/localizer/tests/test_google_timeline_plugin.py` (23/23) all pass
cleanly — implementation logic itself (key names, OSError translation, verbatim
venue/venue_category mapping, since-filtering) is correct. Fix required: run `ruff format
packages/localizer/tests/test_google_timeline_plugin.py` (or repo-wide `ruff format .`), then
re-verify with an **unscoped** `ruff format --check .` from the repo root (not scoped to only
the src package) before returning to GREEN, since acceptance criterion 5 requires `ruff format
--check .` (the whole repo, per the dot) to exit 0.

---

### Subtask 2 — Register the plugin in `load_builtin_plugins()`

**Status**: APPROVED

**PR Group**: google-timeline-localizer-plugin

**Depends On**: 1

**Description**:
Wire `GoogleTimelinePlugin` into the global registry so `localizer sync`,
`localizer fetch google_timeline`, and `localizer sources` all pick it up,
exactly as every other builtin plugin is wired in
`packages/localizer/src/localizer/plugins/__init__.py::load_builtin_plugins()`.
This is a small, mechanical, independently-reviewable change — it depends on
Subtask 1's `loader.py` module existing to import from.

**Acceptance Criteria**:
- [ ] After `REGISTRY.clear(); load_builtin_plugins()`,
  `"google_timeline" in REGISTRY` and `REGISTRY["google_timeline"] is
  GoogleTimelinePlugin`.
- [ ] `localizer sources` (invoked via Click's `CliRunner`, matching the
  pattern in `packages/localizer/tests/test_cli.py`) lists `google_timeline`
  with fetch mode `MANUAL` and output table `places`.
- [ ] Existing registration tests for every other plugin (`swarm`, `lastfm`,
  `github`, `feedly`, `rss`, `letterboxd`) still pass unmodified — this change
  is purely additive to the registry dict.
- [ ] `ruff check .`, `ruff format --check .`, `mypy`, and `pytest` (with
  `--cov-fail-under=70`) all exit 0.

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/__init__.py` (add the import and
  registry assignment in `load_builtin_plugins()`)

**Test Guidance**:
- Add tests to the existing `packages/localizer/tests/test_cli.py` (NOT a new
  file, and NOT Subtask 1's `test_google_timeline_plugin.py`, to keep this
  subtask's test file disjoint from Subtask 1's) — mirror
  `test_sources_lists_swarm` and `test_sources_shows_manual_mode` with a new
  `test_sources_lists_google_timeline` asserting the CLI output contains
  `"google_timeline"` and `"MANUAL"`.
- Add a `REGISTRY`-level registration test (e.g. in
  `packages/localizer/tests/test_cli.py` or a small dedicated block) mirroring
  `test_swarm_plugin_is_registered`: `REGISTRY.clear(); load_builtin_plugins();
  assert "google_timeline" in REGISTRY`.
- Regression check: run the full existing registration/CLI test suite to
  confirm no other plugin's entry in `REGISTRY` or `localizer sources` output
  changed.

**Test Files**:
- `packages/localizer/tests/test_cli.py` (extended, disjoint from Subtask 1's new file) — 3 tests,
  all RED: `test_sources_lists_google_timeline` (fails: `google_timeline` absent from `localizer
  sources` output), `test_google_timeline_plugin_is_registered` (fails:
  `ModuleNotFoundError: No module named 'localizer.plugins.google_timeline'`),
  `test_other_plugins_still_registered_alongside_google_timeline` (fails: `google_timeline` not
  in REGISTRY). Verified no collateral damage: the 4 pre-existing sibling tests
  (`test_sources_lists_swarm`, `test_sources_lists_lastfm`, `test_sources_shows_api_mode`,
  `test_sources_shows_manual_mode`) still pass unmodified.

**Implementation Notes**:
Edited `packages/localizer/src/localizer/plugins/__init__.py::load_builtin_plugins()` only:
added `from localizer.plugins.google_timeline.loader import GoogleTimelinePlugin` alongside the
other five builtin imports (alphabetically ordered between `github` and `lastfm`, matching the
existing import block's alphabetical ordering), and added
`REGISTRY[GoogleTimelinePlugin.PLUGIN_ID] = GoogleTimelinePlugin` after the existing five registry
assignments. Purely additive — no other lines touched.

Test results: `pytest packages/localizer/tests/test_cli.py -v --no-cov` — 16/16 passed, including
the 3 new tests (`test_sources_lists_google_timeline`, `test_google_timeline_plugin_is_registered`,
`test_other_plugins_still_registered_alongside_google_timeline`) and all pre-existing tests
unmodified. `ruff check .` (unscoped, repo root): "All checks passed!". `ruff format --check .`
(unscoped): "125 files already formatted". `mypy` (unscoped): "Success: no issues found in 14
source files". Full regression run `pytest packages/localizer/tests/ -v --no-cov`: 187/187 passed,
no collateral damage to any other plugin's registration or CLI output.

**Review Notes**:
Code Review: APPROVED — checks clean. Ran all four gates unscoped from the repo root (venv
python): `ruff check .` → "All checks passed!"; `ruff format --check .` → "125 files already
formatted"; `mypy` → "Success: no issues found in 14 source files"; `pytest
packages/localizer/tests/test_cli.py -v --no-cov` → 16/16 passed, including the 3 new tests
(`test_sources_lists_google_timeline`, `test_google_timeline_plugin_is_registered`,
`test_other_plugins_still_registered_alongside_google_timeline`) and all pre-existing sibling
tests unmodified. Full regression run `pytest packages/localizer/tests/ -v --no-cov` → 187/187
passed, no collateral damage to any other plugin's registration. Reviewed the diff scope
directly (`git diff --stat`): `plugins/__init__.py` changed by exactly 2 lines (one import
line, one registry assignment), alphabetically placed between `github` and `lastfm` matching
existing convention; `test_cli.py` gained 71 lines (the 3 new tests) with no edits to existing
tests. Verified against Subtask 2's acceptance criteria: `REGISTRY["google_timeline"] is
GoogleTimelinePlugin` after clear+reload (test confirms), `localizer sources` lists
`google_timeline  MANUAL  places` (test confirms exact string), all six other plugins still
registered (test confirms), and all four static/test commands exit 0 unscoped. No dead code,
no secrets/credentials, no N+1 or hot-path concerns (pure dict-assignment and import, no I/O).
No issues found.

Owner Review: APPROVED — Independently re-ran the full acceptance-criteria gate from the repo
root (venv python, not trusting the code reviewer's report alone): `ruff check .` → "All checks
passed!"; `ruff format --check .` → "125 files already formatted"; `mypy` → "Success: no issues
found in 14 source files"; `pytest packages/localizer/tests/ -v --no-cov` → 187/187 passed.
Confirmed the diff is genuinely minimal via `git diff --stat` and a full read of
`plugins/__init__.py`: exactly 2 lines added (one import, alphabetically placed between `github`
and `lastfm`; one `REGISTRY[GoogleTimelinePlugin.PLUGIN_ID] = GoogleTimelinePlugin` assignment
appended after the existing five) — no other lines touched. Read the 3 new tests in
`test_cli.py` directly: `test_sources_lists_google_timeline` asserts the exact
`"google_timeline  MANUAL  places"` CLI output line; `test_google_timeline_plugin_is_registered`
asserts `REGISTRY["google_timeline"] is GoogleTimelinePlugin` after clear+reload;
`test_other_plugins_still_registered_alongside_google_timeline` iterates all 6 other builtin
plugin IDs (`swarm`, `lastfm`, `github`, `feedly`, `rss`, `letterboxd`) plus `google_timeline`
itself, fully covering the Test Guidance's regression-check item. All tests verify observable
behavior (REGISTRY state, CLI stdout), not implementation details. No dead code, no
over-abstraction, naming and ordering consistent with existing plugins. All four acceptance
criteria met. No issues found.

---

### Subtask 3 — Document the plugin in the localizer README

**Status**: APPROVED

**PR Group**: google-timeline-localizer-plugin

**Depends On**: 1, 2

**Description**:
Document the new source in `packages/localizer/README.md` so it's
discoverable the same way every other localizer source is: an entry in the
`localizer sources` example output, a `### Google Maps Timeline` subsection
under `## Sources` explaining the manual-export flow and the
`google_timeline_path` config key, and a mention in the `places` table's
`source_id` example values. Docs-only; no source code changes. Waits until
Subtask 2 lands so the documented config key name and CLI listing behavior
are final and won't need to be re-documented if either changes during review.

**Acceptance Criteria**:
- [ ] The `localizer sources` example code block in the README's "CLI
  reference" section includes a `google_timeline  MANUAL   places` line
  (alphabetically ordered with the existing entries, matching the real
  `sorted(REGISTRY.items())` output order from `sync_cmd`/`sources_cmd`).
- [ ] A new `### Google Maps Timeline` subsection exists under `## Sources`,
  describing: it's a manual, local-file-only source (no network calls), the
  export process (device Timeline export or Google Takeout — reuse the
  wording already present in `plugins/sources/google_timeline/loader.py`'s
  `get_manual_download_instructions()`), and the
  `localizer config set google_timeline_path "/path/to/Timeline.json"`
  command.
- [ ] The `places` table's `source_id` example column mentions
  `"google_timeline"` alongside `"swarm"`.
- [ ] `ruff check .`, `ruff format --check .`, `mypy`, and `pytest` all still
  exit 0 (docs-only change; this confirms nothing was inadvertently broken).

**Files to Touch**:
- `packages/localizer/README.md`

**Test Guidance**:
- No automated tests are expected for this subtask (documentation only). If
  the tester agent identifies an existing doc-drift test (e.g. a test that
  asserts the README's `localizer sources` code block matches
  `REGISTRY.keys()`), extend it to include `google_timeline`; otherwise no
  new test file is needed and the tester should report a RED-confirmed no-op
  (or halt) rather than inventing a new doc-sync test not requested elsewhere
  in the codebase.
- Manual verification: re-run `ruff`/`mypy`/`pytest` after the edit to confirm
  the markdown-only change didn't break anything (should be a no-op).

**Test Files**:
No automated test applies — this is a docs-only subtask. Searched the full repo for an
existing doc-drift test (a test parsing/asserting against `packages/localizer/README.md`'s
content): `Grep "README"` (case-insensitive) across `packages/localizer/` and across every
`test_*.py` file repo-wide returned zero matches. No such test exists, so per Test Guidance no
new doc-sync test was invented. Status set to `RED` regardless (no meaningful RED/GREEN
distinction with zero applicable tests) so the subtask routes to the coder next, who will make
the actual README edit described in the Description/Acceptance Criteria.

**Implementation Notes**:
Docs-only edit to `packages/localizer/README.md`, three additions:
1. The `localizer sources` example code block (CLI reference section) gained a
   `google_timeline  MANUAL   places` row, inserted alphabetically between
   `github` and `lastfm`. Re-padded the whole block's column widths (name
   column to 17 chars, mode column to 9 chars past that) so every row's
   `MANUAL`/`API` and value columns still line up now that `google_timeline`
   is the longest name — verified column start offsets are identical (index
   17 for mode, index 26 for value) across all seven rows.
2. Added a new `### Google Maps Timeline` subsection under `## Sources`,
   placed after `### Foursquare / Swarm` (both populate `places`). States
   it's a manual, local-file-only source with no network calls, describes
   both export options (on-device Timeline export via Settings -> Location
   -> Location Services -> Timeline, and Google Takeout at
   takeout.google.com selecting only "Location History (Timeline)") reusing
   the wording from `loader.py`'s `get_manual_download_instructions()`, and
   shows `localizer config set google_timeline_path "/path/to/Timeline.json"`
   plus `localizer fetch google_timeline`.
3. The `places` table's `source_id` example column changed from `"swarm"`,
   `"google_location"`, … to `"swarm"`, `"google_timeline"`, … (the old
   `"google_location"` placeholder didn't match any real source_id; replaced
   with the actual registered PLUGIN_ID).

No source code, test files, or `Files to Touch` deviations — only
`packages/localizer/README.md` was edited, exactly as scoped.

Verification (venv python, unscoped from repo root):
- `ruff check .` -> "All checks passed!"
- `ruff format --check .` -> "125 files already formatted"
- `mypy` -> "Success: no issues found in 14 source files"
- `pytest packages/localizer/tests/ -v --no-cov` -> 187 passed

All four commands exit 0, confirming the docs-only change did not break
anything (per acceptance criterion 4). No automated test applies to this
subtask per the tester's earlier RED-confirmation (no doc-drift test exists
in the repo).

**Review Notes**:
Code Review: APPROVED — checks clean. Ran all four gates unscoped from the repo root (venv
python): `ruff check .` → "All checks passed!"; `ruff format --check .` → "125 files already
formatted"; `mypy` → "Success: no issues found in 14 source files"; `pytest
packages/localizer/tests/ -v --no-cov` → 187/187 passed. Confirmed via `git diff --stat` that
only `packages/localizer/README.md` changed for this subtask (other working-tree diffs are
prior approved Subtasks 1-2, not yet committed). Verified all three required additions directly
against the file: (1) `localizer sources` block contains `google_timeline  MANUAL   places`,
alphabetically ordered between `github` and `lastfm`; programmatically confirmed column
alignment — the mode field starts at character column 18 and the value field at column 27 for
all 7 rows, identical across the block. (2) A `### Google Maps Timeline` subsection exists under
`## Sources` describing the manual/no-network nature, both export options (on-device Timeline
export and Google Takeout), and the `localizer config set google_timeline_path "..."` command.
(3) The `places` table's `source_id` example column now reads `"swarm", "google_timeline", …`.
No dead code, no secrets/credentials, no N+1/hot-path concerns — pure markdown edit. No issues
found.

Owner Review: APPROVED — Independently re-read the full `packages/localizer/README.md` and
re-ran the entire gate unscoped from the repo root (venv python, not trusting prior reports):
`ruff check .` → "All checks passed!"; `ruff format --check .` → "125 files already formatted";
`mypy` → "Success: no issues found in 14 source files"; `pytest packages/localizer/tests/ -v
--no-cov` → 187/187 passed. Verified all three required additions directly: (1) the `localizer
sources` block (lines 84-93) lists `google_timeline  MANUAL   places` alphabetically between
`github` and `lastfm` — programmatically confirmed the mode column starts at character index 17
and the value column at index 26 across all 7 rows, identical alignment. (2) The `### Google Maps
Timeline` subsection (lines 229-243) states it's a manual, local-file-only source with no network
calls, describes both export options (on-device Settings → Location → Location Services →
Timeline, and Google Takeout selecting only "Location History (Timeline)"), and shows `localizer
config set google_timeline_path "/path/to/Timeline.json"` — cross-checked this wording against
`GoogleTimelinePlugin.get_manual_download_instructions()` in `loader.py` (lines 63-78) and it
mirrors the same two-option structure and phrasing. (3) The `places` table's `source_id` example
(line 301) reads `"swarm"`, `"google_timeline"`, …, matching the real registered `PLUGIN_ID`
(not the stale `"google_location"` placeholder). Confirmed no doc-drift test exists anywhere in
the repo (`Grep "README" -i` across `packages/localizer/`), consistent with the Test Guidance's
documented no-op path — nothing was skipped. Docs-only change; no source or test files touched.
All four acceptance criteria met. No issues found.

---
