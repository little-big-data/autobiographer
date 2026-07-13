"""Failing tests for Subtask 2 (issue #93): wiring the name heuristic into
``SwarmPlugin.fetch_records()``.

Scope: this file tests ONLY the *wiring* in
``packages/localizer/src/localizer/plugins/swarm/loader.py::fetch_records()``
— i.e. that ``_infer_place_type_from_name(place_name)`` is called (and its
return value used as ``place_type``) precisely when ``venue["categories"]``
is empty or missing, and is never consulted when a real category is present.
The heuristic's own keyword-matching *logic* is Subtask 1's responsibility
and is fully covered by the parallel test file
``packages/localizer/tests/test_swarm_plugin.py`` (see the
``test_infer_place_type_from_name_*`` tests there) — this file must not
duplicate that coverage.

Kept in a new file, disjoint from ``test_swarm_plugin.py``, per the parallel
test-ahead batch's single-writer-per-file discipline (see handoff.md's
Shared-source-file note for Subtasks 1-2). This file imports and reuses the
existing ``_make_checkin()`` / ``_write_checkins_json()`` helpers from
``test_swarm_plugin.py`` rather than duplicating them, and defines its own
sibling helpers for the empty/missing-``categories`` shapes those helpers
don't produce, plus a nested-wrapper JSON writer for the wrapper-format
coverage below.

Two families of test live here:

  1. Direct (unmocked) end-to-end tests that call ``fetch_records()`` and
     assert on the real synthesized ``place_type``. These are genuinely RED
     right now via a plain ``AssertionError`` (the fallback isn't wired up
     yet, so ``place_type`` stays ``""``), independent of whether Subtask 1's
     ``_infer_place_type_from_name`` has landed.

  2. Mock-based wiring-contract tests that patch
     ``localizer.plugins.swarm.loader._infer_place_type_from_name`` with
     ``create=True`` (so patching succeeds whether or not Subtask 1's
     function exists yet) and assert the call happens exactly when expected,
     with the expected argument, and that its return value is threaded
     through as ``place_type``. These exist because a few of the required
     assertions (the "no match still returns ''" and "empty name still
     returns '' and doesn't raise" cases) are invariant — true both before
     and after this subtask's fix — so a plain end-to-end assertion on the
     literal value would pass vacuously today. Mocking the call itself makes
     those cases genuinely RED (the call is provably absent right now).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from tests.test_swarm_plugin import _make_checkin, _write_checkins_json

_LOADER_HEURISTIC_TARGET = "localizer.plugins.swarm.loader._infer_place_type_from_name"


# ---------------------------------------------------------------------------
# Helpers — sibling to test_swarm_plugin.py's _make_checkin()/_write_checkins_json(),
# covering shapes the shared helpers don't produce (empty/missing categories,
# alternate wrapper formats). Defined here, not in test_swarm_plugin.py, to
# keep this subtask's test file fully disjoint from Subtask 1's.
# ---------------------------------------------------------------------------


def _make_checkin_empty_categories(
    *,
    venue_name: str,
    created_at: int = 1_700_000_000,
    lat: float = 51.5074,
    lng: float = -0.1278,
) -> dict[str, Any]:
    """Return a checkin dict whose venue has an explicit empty categories list."""
    checkin = _make_checkin(created_at=created_at, lat=lat, lng=lng, venue_name=venue_name)
    checkin["venue"]["categories"] = []
    return checkin


def _make_checkin_missing_categories_key(
    *,
    venue_name: str,
    created_at: int = 1_700_000_000,
    lat: float = 51.5074,
    lng: float = -0.1278,
) -> dict[str, Any]:
    """Return a checkin dict whose venue has NO 'categories' key at all."""
    checkin = _make_checkin(created_at=created_at, lat=lat, lng=lng, venue_name=venue_name)
    del checkin["venue"]["categories"]
    return checkin


def _write_nested_checkins_json(path: Path, checkins: list[dict[str, Any]]) -> None:
    """Write a Swarm export using the ``{"checkins": {"items": [...]}}`` wrapper shape."""
    path.write_text(json.dumps({"checkins": {"items": checkins}}), encoding="utf-8")


# ---------------------------------------------------------------------------
# Direct end-to-end tests — real synthesized place_type, no mocking.
# ---------------------------------------------------------------------------


def test_fetch_records_empty_categories_heuristic_match_airport(tmp_path: Path) -> None:
    """AC2: empty categories + heuristic-matching name yields a non-empty, matching place_type."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    checkin = _make_checkin_empty_categories(venue_name="O'Hare International Airport")
    _write_checkins_json(tmp_path / "checkins_20231101.json", [checkin])

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 1
    place_type = records[0]["place_type"]
    assert place_type != "", "Expected a non-empty synthesized place_type"
    assert "Airport" in place_type, f"Expected 'Airport' substring, got {place_type!r}"


def test_fetch_records_missing_categories_key_heuristic_match_pizza(tmp_path: Path) -> None:
    """A venue dict with no 'categories' key must also trigger the name heuristic."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    checkin = _make_checkin_missing_categories_key(venue_name="Joe's Pizza Place")
    _write_checkins_json(tmp_path / "checkins_20231101.json", [checkin])

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 1
    place_type = records[0]["place_type"]
    assert "pizza" in place_type.lower(), f"Expected 'pizza' substring, got {place_type!r}"


def test_fetch_records_items_wrapper_empty_categories_heuristic_eligible(tmp_path: Path) -> None:
    """AC4: the {"items": [...]} wrapper format supports the empty-categories fallback."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    checkin = _make_checkin_empty_categories(venue_name="Downtown Metro Station")
    # _write_checkins_json uses the {"items": [...]} wrapper shape.
    _write_checkins_json(tmp_path / "checkins_20231101.json", [checkin])

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 1
    place_type = records[0]["place_type"]
    assert place_type != "", "Expected a non-empty synthesized place_type"


def test_fetch_records_nested_checkins_items_wrapper_empty_categories_heuristic_eligible(
    tmp_path: Path,
) -> None:
    """AC4: the {"checkins": {"items": [...]}} wrapper format also supports the fallback."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    checkin = _make_checkin_empty_categories(venue_name="Downtown Coffee Roasters")
    _write_nested_checkins_json(tmp_path / "checkins_20231101.json", [checkin])

    plugin = SwarmPlugin(swarm_dir=str(tmp_path))
    records = list(plugin.fetch_records())

    assert len(records) == 1
    place_type = records[0]["place_type"]
    assert "coffee" in place_type.lower(), f"Expected 'coffee' substring, got {place_type!r}"


# ---------------------------------------------------------------------------
# Mock-based wiring-contract tests.
#
# `create=True` lets these patch `_infer_place_type_from_name` whether or not
# Subtask 1's coder has landed the function yet (this subtask, per handoff.md,
# `Depends On: 1` and its tester's function may not exist in the module at
# test-authoring time). Regardless of that, these assertions are genuinely
# RED right now because fetch_records() does not call anything by this name
# yet at all.
# ---------------------------------------------------------------------------


def test_fetch_records_calls_heuristic_and_uses_return_value_when_categories_empty(
    tmp_path: Path,
) -> None:
    """Empty categories must call the heuristic with place_name and use its return value."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    checkin = _make_checkin_empty_categories(venue_name="Some Synthetic Venue")
    _write_checkins_json(tmp_path / "checkins_20231101.json", [checkin])

    with mock.patch(
        _LOADER_HEURISTIC_TARGET, create=True, return_value="Mocked Place Type"
    ) as mock_infer:
        plugin = SwarmPlugin(swarm_dir=str(tmp_path))
        records = list(plugin.fetch_records())

    assert len(records) == 1
    mock_infer.assert_called_once_with("Some Synthetic Venue")
    assert records[0]["place_type"] == "Mocked Place Type", (
        "fetch_records() must use the heuristic's return value as place_type "
        "when categories is empty"
    )


def test_fetch_records_calls_heuristic_when_categories_key_missing(tmp_path: Path) -> None:
    """A venue dict missing the 'categories' key entirely must also trigger the heuristic call."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    checkin = _make_checkin_missing_categories_key(venue_name="Another Synthetic Venue")
    _write_checkins_json(tmp_path / "checkins_20231101.json", [checkin])

    with mock.patch(
        _LOADER_HEURISTIC_TARGET, create=True, return_value="Mocked Place Type"
    ) as mock_infer:
        plugin = SwarmPlugin(swarm_dir=str(tmp_path))
        records = list(plugin.fetch_records())

    assert len(records) == 1
    mock_infer.assert_called_once_with("Another Synthetic Venue")
    assert records[0]["place_type"] == "Mocked Place Type"


def test_fetch_records_no_match_result_flows_through_as_empty_string(tmp_path: Path) -> None:
    """AC3: when the heuristic itself returns '', fetch_records() must still call it and
    surface '' as place_type — proving the no-match invariant is produced by real wiring,
    not by fetch_records() simply skipping the call and defaulting to ''."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    checkin = _make_checkin_empty_categories(venue_name="Generic City Museum")
    _write_checkins_json(tmp_path / "checkins_20231101.json", [checkin])

    with mock.patch(_LOADER_HEURISTIC_TARGET, create=True, return_value="") as mock_infer:
        plugin = SwarmPlugin(swarm_dir=str(tmp_path))
        records = list(plugin.fetch_records())

    assert len(records) == 1
    mock_infer.assert_called_once_with("Generic City Museum")
    assert records[0]["place_type"] == "", f"Expected exactly '', got {records[0]['place_type']!r}"


@pytest.mark.parametrize("venue_name", ["", "   ", "!!!"])
def test_fetch_records_empty_categories_and_blank_name_does_not_raise(
    tmp_path: Path, venue_name: str
) -> None:
    """Combined edge case: empty/missing categories AND an empty or punctuation-only venue
    name must not raise, must still invoke the heuristic, and must surface '' as place_type
    (Subtask 1 already covers empty-string input directly against
    _infer_place_type_from_name; this proves the same guarantee holds through the full
    fetch_records() wiring)."""
    from localizer.plugins.swarm.loader import SwarmPlugin

    checkin = _make_checkin_empty_categories(venue_name=venue_name)
    _write_checkins_json(tmp_path / "checkins_20231101.json", [checkin])

    with mock.patch(_LOADER_HEURISTIC_TARGET, create=True, return_value="") as mock_infer:
        plugin = SwarmPlugin(swarm_dir=str(tmp_path))
        try:
            records = list(plugin.fetch_records())
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"fetch_records() raised {type(exc).__name__} for blank venue name "
                f"{venue_name!r}: {exc}"
            )

    assert len(records) == 1
    mock_infer.assert_called_once_with(venue_name)
    assert records[0]["place_type"] == "", f"Expected '', got {records[0]['place_type']!r}"
