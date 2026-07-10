"""Config-drift regression guard for packages/localizer's dev dependencies (Subtask 3).

Parses packages/localizer/pyproject.toml and asserts that pytest-xdist is declared
in [project.optional-dependencies].dev, so `pytest -n auto` is available for the
local dev loop for this sub-package's test suite. This test is expected to FAIL
(RED) until the coder agent adds the pytest-xdist dependency to pyproject.toml.
"""

from __future__ import annotations

from pathlib import Path

import tomllib

# packages/localizer/pyproject.toml, relative to this test file
# (packages/localizer/tests/test_dev_dependencies.py -> packages/localizer/pyproject.toml)
_PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _load_dev_dependencies() -> list[str]:
    """Parse packages/localizer/pyproject.toml and return the dev dependency list.

    Returns:
        The raw list of dependency strings under
        [project.optional-dependencies].dev, e.g. ["pytest>=8.2", "ruff>=0.4"].
    """
    data = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))
    return list(data["project"]["optional-dependencies"]["dev"])


def _dependency_names(dependencies: list[str]) -> list[str]:
    """Strip version-pin syntax from a list of dependency strings, lowercased.

    Handles common PEP 508 pin operators (>=, ==, <=, >, <, ~=, !=) and extras
    (e.g. "package[extra]>=1.0") so the resulting names can be compared to a
    bare package name regardless of exact pin formatting.
    """
    names = []
    for dep in dependencies:
        name = dep
        for operator in (">=", "==", "<=", "~=", "!=", ">", "<"):
            if operator in name:
                name = name.split(operator)[0]
                break
        name = name.split("[")[0].strip().lower()
        names.append(name)
    return names


def test_pyproject_toml_is_readable() -> None:
    """packages/localizer/pyproject.toml must exist and parse as valid TOML."""
    assert _PYPROJECT_PATH.exists(), f"Expected pyproject.toml at {_PYPROJECT_PATH}"
    data = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))
    assert "project" in data


def test_dev_dependencies_contains_known_packages() -> None:
    """Sanity check: the existing dev deps (pytest, ruff, mypy) are still present.

    Guards against this test accidentally reading the wrong table/key path.
    """
    dev_deps = _dependency_names(_load_dev_dependencies())
    assert "pytest" in dev_deps
    assert "ruff" in dev_deps
    assert "mypy" in dev_deps


def test_pytest_xdist_declared_in_dev_dependencies() -> None:
    """pytest-xdist must be declared in [project.optional-dependencies].dev.

    Case-insensitive and ignoring exact version pin syntax (>=3.5 vs >=3.5.0,
    etc.) so this test only asserts the package name's presence, not its exact
    formatting. This is the core regression guard for Subtask 3 and is expected
    to FAIL until the coder agent adds "pytest-xdist>=3.5" (or similar) to
    packages/localizer/pyproject.toml's dev optional-dependencies list.
    """
    dev_deps = _dependency_names(_load_dev_dependencies())
    assert "pytest-xdist" in dev_deps, (
        f"'pytest-xdist' not found in packages/localizer/pyproject.toml's "
        f"[project.optional-dependencies].dev list. Found: {dev_deps}"
    )
