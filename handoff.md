# Handoff

## Plan Status
status: COMPLETE

## Task Overview

**The bug (issue #93)**: real Foursquare/Swarm exports have an empty `categories` array on
every venue object — confirmed by reading the export-format handling in
`packages/localizer/src/localizer/plugins/swarm/loader.py`. This makes `place_type` always `""`
in `SwarmPlugin.fetch_records()`, which becomes `venue_category` always `""` after
`core/localizer_frames.py::places_to_swarm_frame()`'s pure rename/passthrough. Downstream,
`analysis_utils.py`'s `_classify_venue_category()` / `_CATEGORY_RULES` (used by
`get_dining_soundtrack_data()`, issue #81) and `TRANSIT_CATEGORY_KEYWORDS` (used by
`get_transit_days()`, issue #83) never match against an all-empty column, so both shipped
features silently return empty results for every real user, with no error surfaced.

**The fix (Option 2 from the issue, already decided — offline-first, no new dependencies, no
network calls, per CLAUDE.md Section 3)**: infer a `place_type` string from the venue **name**
when `categories` is empty, using a keyword-matching heuristic scoped to Swarm/Foursquare naming
conventions. The synthesized value reuses the exact keyword vocabulary the downstream classifiers
already recognize (`_CATEGORY_RULES` substrings for dining, `TRANSIT_CATEGORY_KEYWORDS`
substrings for transit — both read in full during planning, see below), so
`analysis_utils.py` needs **zero changes**. When no heuristic pattern matches, `place_type`
stays `""` exactly as it does today — no regression, no forced guess, no crash.

**Design decision — where the heuristic lives (and why)**: in
`packages/localizer/src/localizer/plugins/swarm/loader.py`, as a new private, pure module-level
function (`_infer_place_type_from_name(venue_name: str) -> str`) plus a name-pattern rule table,
called from `fetch_records()` only when `categories` is empty/missing. **Not** in
`analysis_utils.py`. Rationale: the vocabulary here (airport/station/pizza/cafe-style *name*
patterns) is Foursquare/Swarm-specific naming convention, not a generic place-classification
concern — `analysis_utils.py` is shared by every source in the unified places layer (Google
Location History, etc. — see project memory on the places layer), and adding Swarm-specific name
heuristics there would be the wrong layer for it. Keeping the fix in the plugin loader also means
`analysis_utils.py`'s well-tested classifiers require zero changes (smallest possible blast
radius) and the heuristic is unit-testable in complete isolation from real personal data, using
the same synthetic-fixture style already established in `packages/localizer/tests/test_swarm_plugin.py`.
**Assumption flagged**: if a reviewer disagrees and prefers a shared `analysis_utils.py` function
instead, that changes Subtask 1's file target and Subtask 3's integration-test shape — but the
rationale above (scope, blast radius, existing test conventions) is the basis for this call.

**`core/localizer_frames.py::places_to_swarm_frame()` needs no change** — confirmed by reading
it: it is a pure column rename/passthrough (`place_type` → `venue_category`), with no
classification logic of its own. The fix belongs upstream (the plugin loader), not here.

**Cache files need no new invalidation logic** — confirmed by reading `pages/data_sources.py`
(~lines 284-399): `swarm_transit_days.json` (`TRANSIT_DAYS_CACHE`) and `swarm_dining.json`
(`DINING_CACHE`) are only written when the user clicks "Build Swarm Analysis Cache", which calls
`get_transit_days(swarm_df)` / `get_dining_soundtrack_data(swarm_df, df)` fresh from the
currently-loaded DataFrames every time. There is no staleness-detection or diffing logic to
update — once the heuristic populates non-empty `venue_category` values, the very next cache
rebuild naturally picks up correct results. No cache-invalidation subtask is included.

**Confirmed scope boundary**: `SwarmPlugin` lives only under `packages/localizer/` (the active
plugin system per project memory on the two-plugin-system migration). Nothing under the legacy
`plugins/sources/` tree is touched by this plan.

**Shared-source-file note**: Subtasks 1 and 2 both touch `loader.py` (Subtask 1 adds the pure
heuristic function; Subtask 2 wires it into `fetch_records()`). This is safe because `current:`
ordering is strictly sequential (Subtask 1 completes — reaches `APPROVED` — before Subtask 2's
coder phase starts) and Subtask 2 declares `Depends On: 1`, so there is never a concurrent writer
of `loader.py`. Test files are kept fully disjoint per subtask (see Files to Touch below) so the
parallel test-ahead batch never has two testers writing the same file.

**Full `_CATEGORY_RULES` list** (from `analysis_utils.py`, lines 1591-1631 — 37 rules mapping a
lowercase substring to one of 4 buckets): `fast food`, `burger`, `pizza`, `fried chicken`,
`hot dog`, `sandwich` → Fast Food; `bar`, `nightclub`, `pub`, `brewery`, `wine`, `cocktail`,
`lounge`, `club` → Bars & Nightlife; `cafe`, `café`, `coffee`, `tea room`, `bakery`, `dessert`,
`ice cream`, `juice bar` → Cafes; `restaurant`, `diner`, `food`, `sushi`, `ramen`, `noodle`,
`steakhouse`, `bbq`, `seafood`, `bistro`, `brasserie`, `tapas`, `dim sum`, `buffet`, `grill`,
`kitchen`, `eatery` → Restaurants.

**Full `TRANSIT_CATEGORY_KEYWORDS` list** (from `analysis_utils.py`, lines 1498-1516 — matched
case-insensitively via `.str.contains`): `Airport`, `Train Station`, `Transit`, `Bus Station`,
`Metro`, `Subway`, `Ferry`, `Port`, `Rail`, `Rest Area`, `Rest Stop`, `Travel Plaza`,
`Service Plaza`, `Turnpike`, `Toll`, `Gas Station`, `Truck Stop`.

**Non-overlap constraint for the new name-heuristic rule table (Subtask 1)**: every synthesized
`place_type` value must contain at least one of the two lists above (so the existing classifiers
fire unchanged), and the coder must avoid overly broad name-substring rules that would produce
false positives — e.g. do **not** add a bare `"port"` name-pattern rule (would false-positive on
venue names like "Portland" or "Import Foods"); do **not** add a bare `"club"` name-pattern rule
without disambiguating from generic use. Prefer specific, low-collision name substrings (e.g.
`"airport"`, `"pizza"`, `"metro station"`, `"train station"`, `"coffee"`) over generic ones.

**Privacy constraint (CLAUDE.md Section 3)**: no real personal venue names anywhere in code or
tests. All test fixtures use clearly synthetic/generic names (e.g. "O'Hare International
Airport", "Joe's Pizza Place", "Downtown Metro Station", "Generic City Museum").

**Architecture context**: no prior `/feature-dev` or `/plan-feature` run occurred for this task.
This plan is investigation-driven — every claim above was verified by reading the actual files
(`loader.py`, `localizer_frames.py`, `analysis_utils.py`, `pages/data_sources.py`,
`test_swarm_plugin.py`, `test_analysis_utils.py`), not inferred from the issue text alone.

Plan Review: APPROVED — the three subtasks (name-heuristic function, fetch_records() wiring, end-to-end integration test + docs) have disjoint test files, a valid acyclic dependency chain (1 → 2 → {1,2}) matching the `current:` topological order, sufficient falsifiable acceptance criteria and test guidance including the new empty-categories/empty-name edge case in Subtask 2, and the shared `loader.py` source-file edit across Subtasks 1–2 is safe under this workflow's strictly-sequential (non-Phase-2) coder/reviewer/owner execution.

## Current Subtask
current: 3

---

## Subtasks

### Subtask 1 — Add name-based venue-category heuristic function

**Status**: APPROVED

**PR Group**: venue-category-heuristics

**Depends On**: none

**Description**:
Add a new private, pure function `_infer_place_type_from_name(venue_name: str) -> str` to
`packages/localizer/src/localizer/plugins/swarm/loader.py`, plus a name-pattern rule table (e.g.
`_NAME_HEURISTIC_RULES: list[tuple[str, str]]`, mirroring the `(substring, result)` list style
already used by `analysis_utils._CATEGORY_RULES`). The function lower-cases `venue_name` and
checks it against the rule table in order, returning the first matching rule's synthesized
`place_type` string. Each synthesized value must contain at least one substring from the full
`_CATEGORY_RULES` list or the full `TRANSIT_CATEGORY_KEYWORDS` list quoted in the Task Overview,
so the existing downstream classifiers recognize it unchanged. Returns `""` when no pattern
matches (never `None`, never raises). This subtask does not wire the function into
`fetch_records()` yet — that is Subtask 2. No changes to `analysis_utils.py`.

**Acceptance Criteria**:
- [ ] `_infer_place_type_from_name("O'Hare International Airport")` returns a string containing
  `"Airport"` (case-sensitive match against `TRANSIT_CATEGORY_KEYWORDS`).
- [ ] `_infer_place_type_from_name("Downtown Metro Station")` returns a string containing one of
  the transit keywords (e.g. `"Metro"`).
- [ ] `_infer_place_type_from_name("Joe's Pizza Place")` returns a string whose lowercased form
  contains `"pizza"` (matches `_CATEGORY_RULES`).
- [ ] `_infer_place_type_from_name("Downtown Coffee Roasters")` returns a string whose lowercased
  form contains `"coffee"`.
- [ ] `_infer_place_type_from_name("Generic City Museum")` (no pattern matches) returns exactly
  `""`, not `None`, and does not raise.
- [ ] Matching is case-insensitive on the input venue name (e.g. `"downtown metro station"` in
  all-lowercase still matches) and does not crash on an empty string or a name containing only
  punctuation/whitespace.

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/swarm/loader.py`
- `packages/localizer/tests/test_swarm_plugin.py`

**Test Guidance**:
- Cover at least one representative name per downstream bucket that must remain reachable:
  an airport-style name, a train/metro-station-style name, a pizza-style name, a coffee/cafe-style
  name, a bar/pub-style name, and a restaurant-style name — assert each produces a value
  containing the expected keyword substring from the lists in the Task Overview.
- Cover the explicit no-match fallback: a generic, non-food/non-transit venue name (e.g. "Generic
  City Museum", "Downtown Art Gallery") must return exactly `""`.
- Cover false-positive risk: a venue name that superficially resembles a risky substring but
  should NOT match transit (e.g. "Portland Pizza Co." should classify as pizza/dining via the
  `"pizza"` rule, not accidentally trip a transit `"port"`-style rule — this also verifies the
  rule table has no bare `"port"` rule per the Task Overview's non-overlap constraint).
- Cover case-insensitivity (mixed-case and all-lowercase venue names) and empty-string / purely
  punctuation input (must return `""`, must not raise).
- Use only synthetic/generic venue names — no real personal data, per CLAUDE.md Section 3.

**Test Files**:
- `packages/localizer/tests/test_swarm_plugin.py` — 16 tests appended (all targeting
  `localizer.plugins.swarm.loader._infer_place_type_from_name`): airport, train/metro station,
  pizza, coffee, bar/pub, restaurant matches; no-match fallback (parametrized: "Generic City
  Museum", "Downtown Art Gallery"); false-positive guard ("Portland Pizza Co." must not trip a
  bare transit "port" rule); case-insensitivity (lowercase and mixed-case); empty-string and
  punctuation-only input (parametrized: "   ", "!!!", "...,", "---"). RED-confirmed: 0 passed, 16
  failed, all via `ImportError: cannot import name '_infer_place_type_from_name'` (function does
  not exist yet — genuine RED, not a vacuous test).

**Implementation Notes**:
Added `_NAME_HEURISTIC_RULES: list[tuple[str, str]]` (ordered `(lowercase substring,
synthesized place_type)` pairs) and `_infer_place_type_from_name(venue_name: str) -> str` to
`packages/localizer/src/localizer/plugins/swarm/loader.py`, placed above the `@register`
decorator on `SwarmPlugin`. The function returns `""` immediately for a falsy `venue_name`,
otherwise lower-cases it and returns the first matching rule's synthesized value, else `""`.

Rule table covers the transit bucket (`airport`, `train station`, `metro station`, `subway
station`, `bus station`, `ferry terminal`, `rail station`, `gas station`, `truck stop`, `rest
area`, `rest stop`, `travel plaza`, `service plaza`, `turnpike`, `toll plaza`) and the dining/
nightlife buckets from `_CATEGORY_RULES` (fast food, bars, cafes, restaurants — e.g. `pizza`,
`coffee`, `pub`, `restaurant`, `bbq`, `sushi`, etc.). Per the Task Overview's non-overlap
constraint, deliberately omitted a bare `"port"` rule and a bare `"club"` rule; used
`"nightclub"` (not bare `"club"`) and no transit rule uses `"port"` as a standalone substring,
so `"Portland Pizza Co."` correctly falls through to the `"pizza"` rule only.

No changes to `analysis_utils.py`; `fetch_records()` wiring is untouched (Subtask 2). Did not
modify `test_swarm_plugin.py` — its 16 pre-written tests were used as-is.

**Environment note (not a repo file change)**: the venv's editable install of `localizer`
(`venv/Lib/site-packages/__editable__.localizer-0.1.0.pth`) was pointing at a stale worktree
copy (`.claude/worktrees/agent-a23c5b3a17bb523c4/packages/localizer/src`) left over from a
prior agent session, so tests were initially importing that stale `loader.py` instead of this
repo's copy (masking the fix as 16 ImportErrors). Fixed by re-running
`pip install -e packages/localizer/ --no-deps` from the repo root, which repointed the `.pth`
file at `C:\Users\johns\Code\autobiographer\packages\localizer\src`. No source files were
changed by this step; flagging in case future agents hit the same stale-worktree symptom.

**Verification**:
- `ruff check --fix packages/localizer/src/localizer/plugins/swarm/loader.py` → "No issues found"
- `ruff format packages/localizer/src/localizer/plugins/swarm/loader.py` → "All files formatted correctly"
- `pytest packages/localizer/tests/test_swarm_plugin.py -v --no-cov` → 34 passed (16 new +
  18 pre-existing, confirming no regression)
- `mypy packages/localizer/src/localizer/plugins/swarm/loader.py` → "No issues found"

**Review Notes**:
Code Review: APPROVED — checks clean. `ruff check` and `ruff format --check` on loader.py both
clean; `mypy` clean; `pytest packages/localizer/tests/test_swarm_plugin.py -v --no-cov` → 34
passed (18 pre-existing + 16 new, no regressions, none skipped/xfailed). Verified all 16 new
tests genuinely exercise `_infer_place_type_from_name` (import + call + assert on the real
return value, not vacuous). Confirmed the non-overlap constraint holds in the actual rule table:
no bare `"port"` rule (transit rules use `"gas station"`, `"toll plaza"`, etc., never a standalone
`"port"` substring) and no bare `"club"` rule (`"nightclub"` only) — traced `"Portland Pizza
Co."` through the rule list by hand and confirmed it falls through all transit rules and matches
only `"pizza"`. Cross-checked every synthesized value against `_CATEGORY_RULES` /
`TRANSIT_CATEGORY_KEYWORDS` and confirmed each contains a recognized substring (matching is
case-insensitive downstream via `.lower()` / `case=False`, so the capitalized synthesized values
work correctly). Confirmed `fetch_records()` is untouched — the function is added but not yet
wired in, correctly scoped to Subtask 2.

Owner: APPROVED — independently re-ran the gate: `ruff check` on loader.py + test_swarm_plugin.py
→ "All checks passed!"; `pytest packages/localizer/tests/test_swarm_plugin.py -q --no-cov` → 34
passed; `mypy packages/localizer/src/localizer/plugins/swarm/loader.py` → "Success: no issues
found". Read the full function, rule table, and all 16 tests. Traced `"Portland Pizza Co."` by
hand: lower-cased, no transit rule matches (no bare `"port"` rule present), falls through to the
`"pizza"` rule → returns `"Pizza"` — non-overlap constraint holds. Every Test Guidance item
(airport, train/metro station, pizza, coffee, bar/pub, restaurant, no-match fallback, false-positive
port/pizza guard, case-insensitivity, empty-string, punctuation-only) has a corresponding test.
Confirmed `fetch_records()` (lines 267-271) is untouched, correctly scoping the wiring to Subtask 2.
Function is pure, typed, Google-style docstring, PEP 8-compliant, uses only synthetic venue names —
no personal data. Simplest implementation that satisfies the contract; no dead code or premature
abstraction. Deliberate omissions of generic substrings (bare `"bar"`, `"food"`, `"wine"`, `"dessert"`)
are sound anti-false-positive choices, not gaps — plan only required representative bucket coverage.
No issues found.

---

### Subtask 2 — Wire the heuristic into `SwarmPlugin.fetch_records()`

**Status**: APPROVED

**PR Group**: venue-category-heuristics

**Depends On**: 1

**Description**:
In `fetch_records()` (`packages/localizer/src/localizer/plugins/swarm/loader.py`, ~lines
165-169), call `_infer_place_type_from_name(place_name)` **only** when `venue.get("categories")`
is empty/missing, and use its result as `place_type`. When `categories` is non-empty, behavior is
completely unchanged (`place_type = categories[0].get("name", "")`, exactly as today) — this is a
strict additive fallback, not a replacement of existing category-derived classification.

**Acceptance Criteria**:
- [ ] A venue with a non-empty `categories` array behaves exactly as before (existing test
  `test_fetch_records_place_type_from_category` continues to pass unchanged — no regression).
- [ ] A venue with `categories: []` (or the key missing) and a heuristic-matching `name` (e.g.
  "O'Hare International Airport") yields a record whose `place_type` is non-empty and contains
  the expected keyword.
- [ ] A venue with `categories: []` and a non-matching `name` (e.g. "Generic City Museum") yields
  a record whose `place_type` is exactly `""` — identical to current (pre-fix) behavior, proving
  no regression for the no-match case.
- [ ] The fallback applies identically regardless of which documented export wrapper format the
  file uses (`{"items": [...]}` vs `{"checkins": {"items": [...]}}` vs bare list) — the loader
  already normalizes to a single `items` iteration before per-checkin processing, so this proves
  the fallback isn't wrapper-format-dependent.

**Files to Touch**:
- `packages/localizer/src/localizer/plugins/swarm/loader.py`
- `packages/localizer/tests/test_swarm_plugin_heuristic_wiring.py` (new — kept disjoint from
  Subtask 1's `test_swarm_plugin.py` so the parallel test-ahead batch has no shared-file writer
  conflict; this file imports and reuses the existing `_make_checkin()` / `_write_checkins_json()`
  helpers from `test_swarm_plugin.py` rather than duplicating them)

**Test Guidance**:
- Import/reuse the existing `_make_checkin()` / `_write_checkins_json()` helpers from
  `test_swarm_plugin.py`; extend `_make_checkin()` (or add a sibling helper, defined in the new
  file if the shared helper's signature can't be changed without touching Subtask 1's file) to
  support constructing a checkin with an empty `categories` list, since the current helper always
  populates one category.
- Explicitly re-run/keep the existing category-present tests (e.g.
  `test_fetch_records_place_type_from_category` in `test_swarm_plugin.py`) untouched to prove no
  regression — do not weaken or delete them.
- Add a case where `categories` key is entirely absent from the venue dict (not just an empty
  list), matching real-world export variance.
- Add at least one case per wrapper format (`{"items": [...]}`, `{"checkins": {"items": [...]}}`)
  with an empty-categories, heuristic-eligible venue, to prove the fallback is wrapper-agnostic.
- Add the combined edge case of empty/missing `categories` **and** an empty (or purely
  punctuation) venue `name` at the `fetch_records()` integration level — assert the resulting
  `place_type` is exactly `""` and `fetch_records()` does not raise (Subtask 1 already covers
  empty-string input at the unit level directly against `_infer_place_type_from_name`; this proves
  the same guarantee holds through the full wiring).
- All venue names must be synthetic/generic, per CLAUDE.md Section 3.

**Test Files**:
- `packages/localizer/tests/test_swarm_plugin_heuristic_wiring.py` (new, disjoint from Subtask
  1's file — confirmed via `pytest --collect-only` across both swarm test files: 44 tests
  collected, no conflicts) — 10 tests: empty-categories heuristic match (airport), missing-key
  variant (pizza), both wrapper formats (`{"items": [...]}` and `{"checkins": {"items": [...]}}`)
  with empty-categories heuristic-eligible venues, wiring-contract tests asserting
  `_infer_place_type_from_name` is actually called when categories is empty/missing (mocked with
  `create=True` so this file has no hard dependency on Subtask 1's function existing yet), a
  no-match-flows-through-as-empty-string case, and 3 parametrized combined-edge-case tests (empty
  categories + blank/whitespace/punctuation-only name must not raise). Note: AC1 (non-empty
  categories unchanged) is deliberately not re-tested here — already covered by the pre-existing
  `test_fetch_records_place_type_from_category` in `test_swarm_plugin.py`, which the coder must
  keep passing unmodified. RED-confirmed: 10 failed, 0 passed, 0 errored (clean AssertionErrors,
  no import errors).

**Implementation Notes**:
In `fetch_records()` (`packages/localizer/src/localizer/plugins/swarm/loader.py`), replaced the
always-`""` fallback with a call to `_infer_place_type_from_name(place_name)`, invoked only in the
`else` branch of `if categories: ... else: ...` (i.e. only when `venue.get("categories")` is
empty or missing). When `categories` is non-empty, the line
`place_type = categories[0].get("name", "")` is byte-for-byte unchanged from before — same branch,
same expression, just now paired with an `else` instead of leaving `place_type` at a pre-set `""`.
No other lines in `fetch_records()` were touched (wrapper-format normalization, timestamp
handling, lat/lng handling all untouched), so the wrapper-agnostic behavior required by AC4 falls
out for free — the heuristic call sits after per-checkin normalization is already complete.

No changes needed to `_infer_place_type_from_name()` or `_NAME_HEURISTIC_RULES` themselves
(Subtask 1's code was used as-is). No files beyond the two listed in Files to Touch were touched.

**Verification**:
- `ruff check --fix packages/localizer/src/localizer/plugins/swarm/loader.py` → "No issues found"
- `ruff format packages/localizer/src/localizer/plugins/swarm/loader.py` → "All files formatted
  correctly"
- `pytest packages/localizer/tests/test_swarm_plugin_heuristic_wiring.py
  packages/localizer/tests/test_swarm_plugin.py -v --no-cov` → 44 passed (10 new wiring tests +
  34 pre-existing from Subtask 1, including `test_fetch_records_place_type_from_category`
  unmodified and passing — confirms AC1's no-regression requirement)
- `mypy packages/localizer/src/localizer/plugins/swarm/loader.py` → "No issues found"

**Review Notes**:
Code Review: APPROVED — checks clean. `ruff check` on loader.py → "No issues found"; `ruff format
--check` → "1 file already formatted"; `mypy` → "No issues found". Ran
`pytest packages/localizer/tests/test_swarm_plugin_heuristic_wiring.py
packages/localizer/tests/test_swarm_plugin.py -v --no-cov` → 44 passed, 0 failed — confirmed
`test_fetch_records_place_type_from_category` passed unmodified (AC1, no regression). Read the
full diff: in `fetch_records()` the non-empty-categories branch
(`place_type = categories[0].get("name", "")`) is byte-for-byte unchanged, only now paired with an
`else: place_type = _infer_place_type_from_name(place_name)` — confirms the heuristic is called
only when `categories` is empty/missing, with `place_name` as the sole argument (verified directly
and via the mock-based wiring-contract tests asserting `mock_infer.assert_called_once_with(...)`).
Verified all 4 ACs against the diff, not just test mocking: AC1 (unchanged branch, passing
pre-existing test), AC2 (real end-to-end test with "O'Hare International Airport" yields
non-empty place_type containing "Airport"), AC3 (mocked-return-"" test proves fetch_records
surfaces "" via the real call path, combined with Subtask 1's own coverage that the real function
returns "" for non-matching names), AC4 (separate tests for both `{"items": [...]}` and
`{"checkins": {"items": [...]}}` wrapper formats, both passing, proving the fallback sits after
wrapper normalization). Reviewed the new test file for vacuousness — none found; mocks use
`create=True` deliberately per Subtask 1/2 dependency ordering, not to hide missing coverage. No
dead code, no secrets/credentials, no N+1/hot-path concerns (pure local JSON parsing). Confirmed
`test_swarm_plugin.py` diff (lines 329+) is purely additive (Subtask 1's tests), no existing test
bodies modified. No issues found.

Owner: APPROVED — independently re-ran the gate: `pytest packages/localizer/tests/test_swarm_plugin.py
packages/localizer/tests/test_swarm_plugin_heuristic_wiring.py -q --no-cov` → 44 passed; `ruff check` on
loader.py + test_swarm_plugin_heuristic_wiring.py → "No issues found"; `mypy loader.py` → "No issues
found". Read the full diff: the non-empty-categories branch
(`place_type = categories[0].get("name", "")`) is byte-for-byte unchanged, now paired with
`else: place_type = _infer_place_type_from_name(place_name)`, called only when `categories` is
empty/missing (`venue.get("categories", [])` defaults to `[]`) — a strict additive fallback, no
regression risk. Verified all 4 ACs directly against the diff and tests: AC1 (unchanged branch,
pre-existing `test_fetch_records_place_type_from_category` passes unmodified), AC2 (real
unmocked airport test yields non-empty place_type containing "Airport"), AC3 (mocked
wiring-contract test proves fetch_records() genuinely calls the heuristic and surfaces its `""`
return rather than silently defaulting — a real unmocked call couldn't distinguish those two
cases, so mocking here is deliberate test design, not a coverage gap, especially combined with
Subtask 1's direct unit coverage of blank/punctuation input against the real function), AC4
(both `{"items": [...]}` and `{"checkins": {"items": [...]}}` wrapper formats tested and passing,
proving the fallback sits after wrapper normalization). Test Guidance fully covered: reused
helpers, missing-key vs. empty-list variants, both wrapper formats, combined blank-name edge
case, existing category-present test left untouched. No dead code, simplest possible change
(one `else` branch). No issues found.

---

### Subtask 3 — End-to-end integration test proving dining/transit features populate, plus docs note

**Status**: APPROVED

**PR Group**: venue-category-heuristics

**Depends On**: 1, 2

**Description**:
Add a new integration test file (`tests/test_venue_category_heuristic_integration.py`, root
`tests/`, alongside other tests that already cross-import from the `localizer` package — e.g.
`tests/test_localizer_broker.py`) that exercises the **full previously-broken pipeline**:
`SwarmPlugin.fetch_records()` (synthetic empty-`categories` venues) → a DataFrame shaped like
`core/localizer_frames.py::places_to_swarm_frame()`'s output → `analysis_utils.get_transit_days()`
and `analysis_utils.get_dining_soundtrack_data()`. Assert both now return non-empty results for
synthetic data that would have produced empty results before this fix (i.e., with `place_type`
forced to `""`, matching the pre-fix behavior). Also add a short documentation note (in
`packages/localizer/README.md`'s "places layer" section) describing the name-based fallback and
its known limitation (approximate, name-pattern-based — real Foursquare category data, when
present, is always preferred and unaffected).

**Acceptance Criteria**:
- [ ] A synthetic fixture built via `SwarmPlugin.fetch_records()` with empty-`categories`
  checkins for an airport-style venue and a restaurant-style venue, converted into a `swarm_df`
  matching `places_to_swarm_frame()`'s column shape, produces a non-empty result from
  `get_transit_days(swarm_df)`.
- [ ] The same fixture's restaurant-style checkin, combined with a small synthetic `lastfm_df`
  containing listens within the dining time window, produces a non-empty result from
  `get_dining_soundtrack_data(swarm_df, lastfm_df)` containing the expected bucket key (e.g.
  `"Restaurants"`).
- [ ] A control case using the same fixture but with `place_type`/`venue_category` forced to `""`
  (simulating pre-fix behavior) demonstrates both functions return empty results — documenting
  the before/after contrast explicitly rather than only asserting the fixed behavior.
- [ ] `packages/localizer/README.md` documents the name-based fallback and its approximation
  limitation in the existing "places layer" section (no new doc file created).

**Files to Touch**:
- `tests/test_venue_category_heuristic_integration.py` (new)
- `packages/localizer/README.md`

**Test Guidance**:
- Build the fixture using only synthetic venue names (reuse the style from Subtasks 1-2's
  fixtures — e.g. "O'Hare International Airport", "Joe's Pizza Place") — no real personal data.
- Construct the intermediate `swarm_df` either by calling `places_to_swarm_frame()` directly on a
  DataFrame shaped like `fetch_records()`'s output (preferred, since it exercises the real adapter
  code path end-to-end) or by hand-building a DataFrame with the exact `SWARM_COLUMNS` shape if
  wiring the two together proves awkward in a unit test — prefer the former for genuine
  end-to-end coverage.
- For the dining assertion, place at least one synthetic Last.fm listen timestamp within the
  existing `_DINING_WINDOW_MINUTES` (30 min) window of the restaurant checkin's timestamp, per
  `get_dining_soundtrack_data()`'s documented windowing behavior.
- For the "before" control case, do not re-derive `place_type` from the heuristic — explicitly
  construct it as `""` to simulate the documented pre-fix bug, then assert both downstream
  functions return empty (`set()` / `{}`) on that input, confirming the contrast is real and not
  incidental.
- This subtask adds no new production code — it is test-and-docs only, so no risk-domain-specific
  guidance (concurrency/network/DB/etc.) applies here.

**Test Files**:
- `tests/test_venue_category_heuristic_integration.py` (new) — 6 tests:
  `test_transit_days_populate_after_fix`, `test_dining_soundtrack_data_populates_after_fix`,
  `test_dining_soundtrack_data_top_artists_include_synthetic_listen` (all RED — exercise the real
  `SwarmPlugin.fetch_records()` → `places_to_swarm_frame()` → `get_transit_days()`/
  `get_dining_soundtrack_data()` pipeline with synthetic empty-categories venues, e.g. an
  O'Hare-style airport checkin and a "Corner City Diner" checkin with a Last.fm listen inside the
  dining window); `test_transit_days_empty_before_fix_control` and
  `test_dining_soundtrack_data_empty_before_fix_control` (both pass now by design — the explicit
  before/after control, with `place_type` forced to `""`); `test_readme_documents_name_based_fallback_limitation`
  (RED — asserts `packages/localizer/README.md` mentions the name-based fallback and its
  approximation limitation via a durable keyword check, not a pinned sentence). RED-confirmed: 4
  failed (genuine assertion failures — all imports resolved cleanly since the target module
  already exists, just not yet wired with the heuristic), 2 passed (the intentional controls).

**Implementation Notes**:
This subtask required only test-verification (no new production code) plus one README
doc addition, per its Files to Touch (`tests/test_venue_category_heuristic_integration.py`
was already written by the tester; `packages/localizer/README.md` is the only file this
coder edited).

Ran the pre-written `tests/test_venue_category_heuristic_integration.py` first, before
making any change: 5 of 6 tests already passed (`test_transit_days_populate_after_fix`,
`test_dining_soundtrack_data_populates_after_fix`,
`test_dining_soundtrack_data_top_artists_include_synthetic_listen`, plus the two
before/after control tests) — confirming Subtasks 1+2's merged heuristic + wiring already
make the real `SwarmPlugin.fetch_records()` -> `places_to_swarm_frame()` ->
`get_transit_days()` / `get_dining_soundtrack_data()` pipeline work end-to-end with no
further production-code changes needed. Only `test_readme_documents_name_based_fallback_limitation`
was RED, failing because the README doc note didn't exist yet.

Added a new paragraph to `packages/localizer/README.md`'s existing "### The places layer
and location assumptions" section (after the existing "This means:" bullet list, no new
section/file created) titled "Name-based `place_type` fallback (Swarm/Foursquare)"
describing: (1) the real-world bug (empty `categories` on every venue breaking
category-dependent features), (2) that `SwarmPlugin.fetch_records()` now falls back to a
name-based heuristic (with example keywords: airport, pizza, metro station, coffee) when
`categories` is empty/missing, (3) the explicit limitation that this is an approximation
used only as a fallback, and (4) that real Foursquare category data, when present, is
always preferred and completely unaffected. This satisfies the test's loose keyword
checks (`"name"` + `"fallback"`/`"heuristic"`, and `"approximat"`/`"limitation"`) without
pinning exact wording.

No changes to `loader.py`, `test_swarm_plugin.py`, or
`test_swarm_plugin_heuristic_wiring.py` — untouched, per the coder's scope boundary for
this subtask.

**Verification**:
- `pytest tests/test_venue_category_heuristic_integration.py -v --no-cov` (before README
  edit) → 5 passed, 1 failed (`test_readme_documents_name_based_fallback_limitation`)
- `ruff check --fix .` (repo-wide) → "No issues found"
- `ruff format .` (repo-wide) → "All files formatted correctly" (reformatted whitespace in
  the untracked, tester-authored `tests/test_venue_category_heuristic_integration.py`; no
  content/assertion changes, confirmed by full re-run below)
- `pytest tests/test_venue_category_heuristic_integration.py -v --no-cov` (after README
  edit) → 6 passed
- Scoped set: `pytest tests/test_venue_category_heuristic_integration.py
  packages/localizer/tests/test_swarm_plugin.py
  packages/localizer/tests/test_swarm_plugin_heuristic_wiring.py -v --no-cov` → 50 passed
  (6 + 34 + 10, no regressions)
- `ruff check packages/localizer/README.md tests/test_venue_category_heuristic_integration.py`
  → "No issues found"; `ruff format --check tests/test_venue_category_heuristic_integration.py`
  → "1 file already formatted"

**Review Notes**:
Code Review: APPROVED — checks clean. `ruff check .` (repo-wide) → "No issues found"; `ruff
format --check .` → "163 files already formatted"; `mypy` → "No issues found"; `pytest
tests/test_venue_category_heuristic_integration.py -v --no-cov` → 6 passed. Full scoped
regression set for the PR group — `pytest packages/localizer/tests/test_swarm_plugin.py
packages/localizer/tests/test_swarm_plugin_heuristic_wiring.py
tests/test_venue_category_heuristic_integration.py -v --no-cov` → 50 passed, 0 failed, no
regressions across all 3 subtasks. Read the full test file: all 6 tests are genuine, not
vacuous — `test_transit_days_populate_after_fix` /
`test_dining_soundtrack_data_populates_after_fix` /
`test_dining_soundtrack_data_top_artists_include_synthetic_listen` exercise the real
`SwarmPlugin.fetch_records()` -> `places_to_swarm_frame()` -> `get_transit_days()`/
`get_dining_soundtrack_data()` pipeline on synthetic empty-categories venues (airport +
diner); the two control tests hand-construct `place_type=""` (not derived from the
heuristic) to prove the before/after contrast is real, not incidental; the README test
does a loose keyword check against the real file content. All 4 ACs verified against actual
behavior: AC1 (transit_days non-empty via real pipeline), AC2 ("Restaurants" bucket with
checkin_count/listen_count >= 1), AC3 (both functions return `set()`/`{}` on the forced-""
control), AC4 (README paragraph present, read directly). README addition is accurate,
correctly placed in the existing "### The places layer and location assumptions" section
(single occurrence, immediately after the existing bullet list, before the `---`/##
Installation break), not duplicative — no other mention of the name-based fallback exists
elsewhere in the file. No dead code, no secrets/credentials, no N+1/hot-path concerns (test
file only constructs small in-memory DataFrames). No issues found.

Owner: APPROVED — independently re-ran the full scoped set: `pytest
packages/localizer/tests/test_swarm_plugin.py
packages/localizer/tests/test_swarm_plugin_heuristic_wiring.py
tests/test_venue_category_heuristic_integration.py -q --no-cov` → 50 passed; `ruff check` on all
touched files → "No issues found"; `mypy packages/localizer/src/localizer/plugins/swarm/loader.py`
→ "No issues found". Read the full integration test file and the README diff. Confirmed
`get_transit_days()`/`get_dining_soundtrack_data()` fixture design matches the real
`analysis_utils.py` implementation (30-minute `_DINING_WINDOW_MINUTES`, `venue_category` column
requirement) — the synthetic listen is placed 5 minutes after the dining checkin, safely inside
the window. All 4 ACs verified against real behavior, not mocks: AC1 (`get_transit_days()`
non-empty via the real `SwarmPlugin.fetch_records()` → `places_to_swarm_frame()` pipeline on an
airport-style empty-categories checkin), AC2 ("Restaurants" bucket populated with
checkin_count/listen_count >= 1 for a diner-style checkin), AC3 (both functions return
`set()`/`{}` on the hand-constructed forced-`""` control, proving the before/after contrast is
real, not incidental), AC4 (README paragraph at lines 49-59 of
`packages/localizer/README.md`, correctly placed in the existing "places layer" section, accurate,
documents the approximation/limitation as required). No dead code, no vacuous tests, no personal
data in fixtures (all synthetic names).

**Holistic plan assessment (issue #93, all 3 subtasks now APPROVED)**: The issue's confirmed root
cause — real Foursquare/Swarm exports ship an empty `categories` array on every venue, making
`venue_category` always `""` and silently breaking both the Dining Soundtrack (#81) and In Transit
(#83) features — is fixed via exactly the issue's own "Approach 2: name-based heuristics", with
the tradeoff (lower accuracy, documented as an approximation) explicitly called out in the README
per the issue's own framing. The fix is offline-first with zero new dependencies (CLAUDE.md
Section 3 and the issue's explicit runtime constraint), correctly scoped to the active
`packages/localizer` plugin system only, requires zero changes to the shared, well-tested
`analysis_utils.py` classifiers (smallest blast radius), and is proven end-to-end by a real
pipeline integration test plus an explicit before/after control contrast. Nothing from the issue's
original ask is missing. Recommend the orchestrator append `Closes #93` to the PR-group commit
message per the standard workflow rule.

**All 3 subtasks in PR Group `venue-category-heuristics` are now APPROVED. Plan Status: COMPLETE.**

---
