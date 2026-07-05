"""Regression test: the installed `localizer` console-script entry point must
not raise `ModuleNotFoundError: No module named 'analysis_utils'` when
fetching Google Timeline data.

Context (see handoff.md Task Overview): `GoogleTimelinePlugin.fetch_records()`
does a lazy `from analysis_utils import load_google_timeline`, but
`analysis_utils.py` is a bare top-level module in the autobiographer app, not
part of any installed package. It only "works" under pytest (which injects
the repo root onto `sys.path` via `pythonpath = ["."]`) or under
`streamlit run visualize.py` (script-directory injection). The actual
installed console-script entry point (`venv/Scripts/localizer.exe`) gets
neither benefit, so every real user of `localizer fetch google_timeline` /
`localizer sync` hits `ModuleNotFoundError` regardless of cwd.

This test spawns the real installed executable as an OS subprocess (per Task
Overview design decision 3) -- NOT Click's CliRunner (runs in-process,
inherits pytest's sys.path and would mask the bug) and NOT
`python -m localizer.cli` (also technically dodges the pytest pythonpath
shim, but is a less faithful reproduction of what a real user actually ran).

Pre-fix (Subtasks 1-2 not yet landed), this test must fail with
`ModuleNotFoundError: No module named 'analysis_utils'` captured in the
subprocess's stderr. Post-fix, it must pass cleanly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_console_script() -> Path:
    """Resolve the path to the installed `localizer` console-script executable.

    Returns:
        Path to `localizer.exe` (Windows) or `localizer` (POSIX), living
        alongside the current Python interpreter in an editable venv install.
    """
    interpreter_dir = Path(sys.executable).parent
    if sys.platform.startswith("win"):
        return interpreter_dir / "localizer.exe"
    return interpreter_dir / "localizer"


def _one_visit_segment_timeline_payload() -> dict[str, Any]:
    """Return a minimal Timeline.json payload with exactly one visit segment.

    Mirrors the fixture shape used across the plan's other subtasks (a single
    HOME visit with a frequent-place label) -- kept to one segment so the
    only real fixed cost this test pays is the one-time geocode-index load
    inside the real (unmocked) subprocess.
    """
    return {
        "userLocationProfile": {
            "frequentPlaces": [
                {
                    "placeId": "PID_HOME",
                    "placeLocation": "40.0°, -74.0°",
                    "label": "My Home Base",
                }
            ]
        },
        "semanticSegments": [
            {
                "startTime": "2025-01-01T08:00:00.000-05:00",
                "endTime": "2025-01-01T09:00:00.000-05:00",
                "startTimeTimezoneUtcOffsetMinutes": -300,
                "visit": {
                    "topCandidate": {
                        "placeId": "PID_HOME",
                        "semanticType": "HOME",
                        "placeLocation": {"latLng": "40.0°, -74.0°"},
                    }
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# Regression test
# ---------------------------------------------------------------------------


def test_installed_console_script_fetches_google_timeline_without_module_not_found_error(
    tmp_path: Path,
) -> None:
    """The installed `localizer` executable must not raise ModuleNotFoundError.

    Spawns the real console-script entry point from a cwd that is not the
    repo root, with LOCALIZER_DB_PATH / LOCALIZER_CONFIG_PATH pointed at temp
    paths so the real `~/.localizer/` store is never touched, and with any
    inherited PYTHONPATH stripped so a developer's stray repo-root
    PYTHONPATH can't accidentally mask the bug.
    """
    console_script = _resolve_console_script()
    if not console_script.exists():
        pytest.skip(
            f"Installed console script not found at {console_script}. "
            "Run `pip install -e packages/localizer/` to install it, then re-run this test."
        )

    # Working directory that is deliberately NOT the repo root.
    work_dir = tmp_path / "cwd"
    work_dir.mkdir()

    fixture_path = tmp_path / "Timeline.json"
    fixture_path.write_text(json.dumps(_one_visit_segment_timeline_payload()), encoding="utf-8")

    db_path = tmp_path / "store.duckdb"
    config_path = tmp_path / "config.toml"

    env = dict(os.environ)
    env["LOCALIZER_DB_PATH"] = str(db_path)
    env["LOCALIZER_CONFIG_PATH"] = str(config_path)
    # Strip any inherited PYTHONPATH so a developer's stray repo-root entry
    # can't mask the bug this test exists to catch.
    env.pop("PYTHONPATH", None)

    result = subprocess.run(  # noqa: S603 -- spawns a known local installed
        # executable (resolved from sys.executable's own directory) with a
        # fixed, test-controlled argument list; not user-controlled input.
        [
            str(console_script),
            "fetch",
            "google_timeline",
            "--set-file",
            str(fixture_path),
        ],
        cwd=str(work_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )

    combined_output = f"{result.stdout}\n{result.stderr}"

    assert "ModuleNotFoundError" not in combined_output, (
        f"Subprocess raised ModuleNotFoundError:\n{combined_output}"
    )
    assert "No module named 'analysis_utils'" not in combined_output, (
        f"Subprocess could not import analysis_utils:\n{combined_output}"
    )
    assert result.returncode == 0, (
        f"Console script exited with code {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # Verify a record actually landed in the store.
    from localizer.store.db import LocalizerStore

    with LocalizerStore(db_path) as store:
        places_df = store.query_places(source_id="google_timeline")

    assert len(places_df) >= 1, (
        "Expected at least one google_timeline place row in the store after "
        f"a successful fetch; got {len(places_df)}.\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
