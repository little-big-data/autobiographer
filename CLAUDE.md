# Autobiographer: Engineering Standards & Mandates

This document serves as the foundational mandate for all development work performed by AI agents on this codebase. This is a high-quality Python project; every contribution must uphold the following standards of simplicity, clarity, reliability, and performance.

## Git Workflow

*   **Branch first**: Always create a new feature branch before making changes; never push directly to an existing PR's branch unless explicitly told to.
*   **Test before push**: After resolving conflicts or making multi-file changes, run the full test suite before pushing.
*   **Verify branch target**: When pushing, confirm the branch name matches the intended PR target.
*   **"Push to a PR" means open a Pull Request**: When asked to push to a PR, create a PR, or submit a PR — commit staged changes, push the branch, then immediately open a GitHub Pull Request using `gh pr create`. The PR must include: a descriptive title (under 70 chars), a `## Summary` section with bullet points, and a `## Test plan` section with a markdown checklist of steps to verify the feature. Do not stop at pushing the branch.

## Python Environment

*   **Use the venv**: Always activate the project venv (`venv/`) before running Python commands or installing packages; do not use system Python.
*   **Verify installs**: After installing a package, confirm it landed in the venv with `which python` and `pip list` before assuming a fix worked.
*   **pyproject.toml is canonical**: Any package imported in source must be listed in `pyproject.toml [project.dependencies]`. `requirements.txt` is for local venv convenience only — CI installs from `pyproject.toml`.

## Streamlit API deprecations

*   **`use_container_width` is removed**: Use `width="stretch"` instead of `use_container_width=True`, and `width="content"` instead of `use_container_width=False`. Never write `use_container_width` — it was removed after 2025-12-31.

## Streamlit Conventions

*   **Widget mock lists**: When adding or removing `st.columns()` calls, update the corresponding `side_effect` lists in any affected tests.
*   **Cache placement**: Do not apply `@st.cache_data` to pure utility modules; use it only on data-loading functions called from the UI layer.
*   **Widget state refreshes**: For widget state changes (e.g., date pickers, config path fields), use explicit `session_state` keys and call `st.rerun()` when widget snapshots need refreshing — but be aware that `st.rerun()` inside a page function runs *before* `render_sidebar()` on the next pass, so never rely on a post-rerun sidebar state set by the page itself.
*   **Session data cache**: When new data is saved (fetch or file selection), call `invalidate_data_cache()` from `components.sidebar` before `st.rerun()` so the next sidebar render reloads from disk.

## 1. Core Philosophy

*   **Simplicity over Cleverness**: Write code that is easy to reason about. Avoid complex abstractions or "magic" patterns unless they provide significant performance gains.
*   **Clarity is Paramount**: Variable names should be descriptive. Logic should be self-documenting. Complex blocks must have concise, meaningful comments.
*   **Test-Backed Integrity**: A feature is not complete, and a bug is not fixed, until it is verified by automated tests. We aim for high coverage and regression-proof logic.
*   **Performance by Design**: We handle large datasets (Last.fm listening histories and Foursquare/Swarm check-ins). Use vectorized `pandas` operations over loops and leverage caching systems to avoid redundant calculations.

## 2. Python Standards

*   **Type Safety**: Use Python 3.9+ type hints for all function signatures and complex variables. Use `from __future__ import annotations` where needed for forward references.
*   **Style**: Adhere strictly to PEP 8. Use `ruff` for linting and formatting (replaces black/flake8/isort).
*   **Documentation**: Every function must have a docstring (Google or NumPy style) explaining its purpose, parameters, and return values.
*   **Environment**: Always use the virtual environment (`venv/`) and keep `requirements.txt` updated.

## 3. Data & Privacy (Mandatory)

*   **Anonymity**: Never hardcode personal data (locations, usernames, credentials) into the codebase.
*   **Externalize Assumptions**: Any personal identifying data or location assumptions must reside in external JSON files (e.g., `default_assumptions.json.example`) or environment variables.
*   **Credential Protection**: Use the `AUTOBIO_` environment variable prefix for all configuration. Never log or print API keys or secrets.

## 4. Testing & Validation

*   **Framework**: Use `pytest` for all tests.
*   **Granularity**: Prefer unit tests for utility logic (`analysis_utils.py`) and integration tests for UI/CLI flows (`visualize.py`, `record_flythrough.py`).
*   **Mocks**: Properly mock external dependencies (Last.fm API, Streamlit UI components) to ensure tests are fast, deterministic, and can run in CI.
*   **Validation Step**: AI agents MUST run the full test suite and all static analysis tools before proposing any change (see Section 7).

## 5. Caching & Efficiency

*   **Computation**: Expensive geocoding or data processing must be cached locally in `data/cache/` using the established `get_cache_key` logic.
*   **UI Performance**: Use Streamlit's `@st.cache_data` for repeatable UI-level computations to ensure a snappy user experience.

## 6. Development Workflow

1.  **Research**: Map dependencies and identify the minimal path to implementation.
2.  **Strategy**: Formulate a plan that prioritizes the least disruptive, most maintainable change.
3.  **Act**: Apply surgical edits. Use `replace` for targeted updates to large files.
4.  **Validate**: Run the full local gate (Section 7) before committing or pushing.

## 7. Local Quality Gate (Required Before Every Commit or Push)

**This gate is mandatory — no exceptions.** All checks must pass with zero errors before any `git push` or PR submission. CI runs the same checks; a failing CI is a sign the gate was skipped locally. Fix locally first, then push.

AI agents must run these steps in order and fix every failure before proceeding. Do not open or update a PR until the full gate passes locally.

### Step 1 — Auto-fix what can be fixed automatically
```bash
ruff check --fix .
ruff format .
```

### Step 2 — Verify everything is clean
```bash
# Dependency sync — every package imported in source must be in pyproject.toml [dependencies]
# (requirements.txt is for local venv convenience only; CI installs from pyproject.toml)
python - <<'EOF'
import tomllib, pathlib, sys
data = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
declared = {d.split(">=")[0].split("==")[0].split("[")[0].lower()
            for d in data["project"]["dependencies"]}
dev = {d.split(">=")[0].split("==")[0].lower()
       for d in data["project"]["optional-dependencies"]["dev"]}
print("Runtime deps:", sorted(declared))
print("Dev deps:", sorted(dev))
EOF

# Lint and format
ruff check .
ruff format --check .

# Type checking
mypy

# Tests with coverage (threshold and flags are set in pyproject.toml)
pytest
```

All commands must exit with code 0. If any fail, fix the reported errors and re-run the full gate from Step 1 before pushing.

### Common failure patterns and fixes

| Failure | Fix |
|---|---|
| `ruff` import order / formatting | Run `ruff check --fix . && ruff format .` |
| `ruff` unused import (`F401`) | Remove the import or add `# noqa: F401` only if intentional |
| `ruff` unused variable (`F841`, `B007`) | Remove assignment or rename to `_varname` |
| `ruff` line too long (`E501`) | Extract to a named variable or add file to `per-file-ignores` in `pyproject.toml` |
| `mypy` type mismatch | Fix the type annotation or add an explicit cast; do not use `# type: ignore` without a comment explaining why |
| `pytest` test failure | Fix the code or test — never skip or delete a failing test |
| `pytest` coverage below 80% | Add tests for the new code path |
| CI fails with `ModuleNotFoundError` but tests pass locally | Package is in `requirements.txt` but missing from `pyproject.toml [project.dependencies]` — add it there; CI installs from `pyproject.toml`, not `requirements.txt` |

### Installing tools

```bash
pip install ruff mypy types-requests
```

### Installing git hooks (one-time, per clone)

The project uses `pre-commit` to enforce the quality gate automatically. After cloning, run:

```bash
pre-commit install
pre-commit install --hook-type pre-push
```

This installs two hook stages:
- **pre-commit**: ruff (auto-fix + format) and mypy — fast checks on every commit.
- **pre-push**: full CI gate (ruff check, ruff format --check, mypy, pytest) — mirrors CI exactly, blocking any push that would fail.
