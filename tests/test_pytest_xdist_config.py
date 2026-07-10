"""Config-drift regression guard for Subtask 2 (pytest-xdist for the root suite and CI).

These are lightweight meta-tests: they parse `pyproject.toml` and
`.github/workflows/ci.yml` as data/text and assert the presence of the
`pytest-xdist` dev dependency and the `pytest -n auto` CI invocation. They do
not run pytest-xdist itself (that would require actually installing it and
exercising the full suite, which is out of scope for a fast unit test) — they
only guard against someone reverting the flag/dependency later without
noticing.
"""

from __future__ import annotations

import re
from pathlib import Path

import tomllib
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _normalize_dependency_name(dependency: str) -> str:
    """Strip version-pin syntax and extras from a PEP 508-ish dependency string.

    e.g. "pytest-xdist>=3.5" -> "pytest-xdist", "pytest-xdist[psutil]>=3.5.0" ->
    "pytest-xdist". Case is lowercased so comparisons are case-insensitive.
    """
    # Cut at the first character that starts a version specifier, extras
    # marker, or environment marker.
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)", dependency)
    name = match.group(1) if match else dependency
    return name.strip().lower()


def test_pytest_xdist_is_declared_in_root_dev_dependencies() -> None:
    """`pytest-xdist` must be a declared dev dependency in root pyproject.toml.

    This guards Subtask 2's core requirement: `pytest -n auto` is only usable
    locally and in CI once the package is actually installed via `pip install
    -e ".[dev]"`. Currently `pyproject.toml`'s dev list does not include
    pytest-xdist, so this test is expected to fail (RED) until the coder adds
    it.
    """
    pyproject_data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    dev_dependencies = pyproject_data["project"]["optional-dependencies"]["dev"]
    normalized_names = {_normalize_dependency_name(dep) for dep in dev_dependencies}

    assert "pytest-xdist" in normalized_names, (
        "Expected 'pytest-xdist' in [project.optional-dependencies].dev of "
        f"pyproject.toml, found: {sorted(normalized_names)}"
    )


def test_ci_workflow_runs_tests_with_xdist_auto_flag() -> None:
    """CI's 'Tests and coverage' step must invoke `pytest -n auto`, not bare `pytest`.

    Parses the workflow YAML (rather than a raw substring search over the
    whole file) so the assertion is scoped specifically to the "Tests and
    coverage" step's `run:` command and not merely to the presence of the
    substring anywhere in the file (e.g. in an unrelated comment). Currently
    that step runs bare `pytest`, so this test is expected to fail (RED)
    until the coder updates the workflow.
    """
    workflow_data = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    quality_steps = workflow_data["jobs"]["quality"]["steps"]

    tests_steps = [step for step in quality_steps if step.get("name") == "Tests and coverage"]
    assert len(tests_steps) == 1, (
        "Expected exactly one 'Tests and coverage' step in the 'quality' job, "
        f"found {len(tests_steps)}"
    )

    run_command = tests_steps[0].get("run", "")
    assert "pytest -n auto" in run_command, (
        "Expected the 'Tests and coverage' step's run command to contain "
        f"'pytest -n auto', got: {run_command!r}"
    )


def test_ci_workflow_raw_text_contains_xdist_auto_flag() -> None:
    """Belt-and-suspenders raw-text check, as specified in the subtask's Test Guidance.

    Complements the YAML-scoped assertion above with a plain substring check
    over the file text, in case the workflow's structure is ever refactored
    (e.g. a shell script extracted to a separate file) in a way that changes
    how the YAML-based test locates the step.
    """
    ci_text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "pytest -n auto" in ci_text, (
        "Expected the substring 'pytest -n auto' to appear in .github/workflows/ci.yml"
    )
