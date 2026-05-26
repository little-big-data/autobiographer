"""Tests for Subtasks 2 & 3 — Infer Residency UI in pages/data_sources.py.

Subtask 2: inference button, spinner, preview dataframe.
Subtask 3: save flow — writes JSON, invalidates cache, reruns.

All Streamlit widget calls are mocked via unittest.mock.patch.
The function under test is _render_swarm_analysis() in pages/data_sources.py,
which does not yet have the new UI code — every test here must FAIL (RED).

ExitStack is used instead of parenthesised `with (...)` blocks to avoid
Python 3.11's "too many statically nested blocks" compile error.
"""

from __future__ import annotations

import builtins
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_col_mock() -> MagicMock:
    """Return a MagicMock that works as a context manager (for st.columns)."""
    col = MagicMock()
    col.__enter__ = MagicMock(return_value=col)
    col.__exit__ = MagicMock(return_value=False)
    return col


def _make_spinner_mock() -> MagicMock:
    """Return a MagicMock that works as a context manager (for st.spinner)."""
    sp = MagicMock()
    sp.__enter__ = MagicMock(return_value=sp)
    sp.__exit__ = MagicMock(return_value=False)
    return sp


def _sample_swarm_df() -> Any:
    """Return a minimal non-empty swarm DataFrame."""
    import pandas as pd

    return pd.DataFrame(
        {
            "timestamp": [1_000_000, 1_100_000, 1_200_000],
            "city": ["Chicago", "Chicago", "Chicago"],
            "lat": [41.8781, 41.8782, 41.8780],
            "lng": [-87.6298, -87.6299, -87.6300],
        }
    )


def _sample_inferred() -> list[dict[str, str]]:
    """Return a minimal inferred residency list."""
    return [{"city": "Chicago", "start": "2012-03-01", "end": "2018-07-31"}]


def _base_patch_specs(
    session: dict[str, Any],
    swarm_df: Any,
    *,
    infer_return: list[dict[str, str]] | None = None,
    button_side_effect: Any = False,
    col_mock: MagicMock | None = None,
    extra_patches: dict[str, Any] | None = None,
) -> list[tuple[str, Any]]:
    """Return a list of (target, new) pairs suitable for use with ExitStack + patch.

    ``button_side_effect`` may be a bool, callable, or list.
    ``infer_return`` defaults to [] (no inferred periods).
    """
    if col_mock is None:
        col_mock = _make_col_mock()
    if infer_return is None:
        infer_return = []

    specs: list[tuple[str, Any]] = [
        ("streamlit.session_state", session),
        ("streamlit.info", MagicMock()),
        ("streamlit.subheader", MagicMock()),
        ("streamlit.caption", MagicMock()),
        ("streamlit.divider", MagicMock()),
        # _render_swarm_analysis calls st.columns(3) for status metrics then
        # st.columns(2) for the slider pair.  Use side_effect to serve different
        # sized lists per call so neither unpack fails.
        (
            "streamlit.columns",
            MagicMock(
                side_effect=[
                    [col_mock, col_mock, col_mock],  # first call: 3 status cols
                    [col_mock, col_mock],  # second call: 2 slider cols
                    [col_mock, col_mock, col_mock],  # defensive: extra calls
                    [col_mock, col_mock],
                    [col_mock, col_mock, col_mock],
                    [col_mock, col_mock],
                ]
            ),
        ),
        ("streamlit.slider", MagicMock(return_value=80)),
        ("streamlit.metric", MagicMock()),
        ("streamlit.spinner", MagicMock(return_value=_make_spinner_mock())),
        ("streamlit.dataframe", MagicMock()),
        ("streamlit.warning", MagicMock()),
        ("streamlit.error", MagicMock()),
        ("streamlit.success", MagicMock()),
        ("streamlit.rerun", MagicMock()),
        # load_swarm_data is imported locally inside _render_swarm_analysis;
        # patch it at its source so the lazy import picks up the mock.
        ("analysis_utils.load_swarm_data", MagicMock(return_value=swarm_df)),
        # get_plugin_config_from_session is also imported locally; patch at source.
        (
            "components.plugin_config.get_plugin_config_from_session",
            MagicMock(return_value={"swarm_dir": ""}),
        ),
        # These are imported at module level in pages/data_sources.py.
        ("pages.data_sources.load_detected_trips_cache", MagicMock(return_value=[])),
        ("pages.data_sources.load_transit_days_cache", MagicMock(return_value=[])),
        ("pages.data_sources.load_dining_cache", MagicMock(return_value=[])),
        ("pages.data_sources.load_assumptions", MagicMock(return_value={})),
        # infer_residency_periods does not exist in pages/data_sources yet.
        # The coder will add it as a module-level import; we pre-patch the
        # analysis_utils source so both the local-import and module-import
        # patterns are covered.
        ("analysis_utils.infer_residency_periods", MagicMock(return_value=infer_return)),
        ("pages.data_sources.invalidate_data_cache", MagicMock()),
    ]

    # Add the button mock with the appropriate side_effect / return_value
    if callable(button_side_effect):
        btn_mock: MagicMock = MagicMock(side_effect=button_side_effect)
    elif isinstance(button_side_effect, bool):
        btn_mock = MagicMock(return_value=button_side_effect)
    else:
        btn_mock = MagicMock(side_effect=button_side_effect)
    specs.append(("streamlit.button", btn_mock))

    if extra_patches:
        for target, new in extra_patches.items():
            specs.append((target, new))

    return specs


def _run_render(specs: list[tuple[str, Any]]) -> dict[str, MagicMock]:
    """Apply all patches in specs, call _render_swarm_analysis(), return mocks keyed by target."""
    from pages.data_sources import _render_swarm_analysis  # noqa: PLC0415

    mocks: dict[str, MagicMock] = {}
    with ExitStack() as stack:
        for target, new in specs:
            mocks[target] = stack.enter_context(patch(target, new))
        _render_swarm_analysis()
    return mocks


# ---------------------------------------------------------------------------
# Subtask 2 — Inference button and preview
# ---------------------------------------------------------------------------


class TestInferResidencyButtonNotShownWhenNoData(unittest.TestCase):
    """When swarm_df is None or empty, the inference button must NOT appear."""

    def _run_with_swarm_df(self, swarm_df: Any) -> dict[str, MagicMock]:
        session: dict[str, Any] = {"swarm_df": swarm_df}
        specs = _base_patch_specs(session, swarm_df, button_side_effect=False)
        return _run_render(specs)

    def test_swarm_df_none_shows_info_no_infer_button(self) -> None:
        """With swarm_df=None the function shows st.info and no infer button rendered."""
        mocks = self._run_with_swarm_df(None)

        mock_info = mocks["streamlit.info"]
        mock_info.assert_called()

        mock_button = mocks["streamlit.button"]
        infer_calls = [c for c in mock_button.call_args_list if "infer_residency_btn" in str(c)]
        self.assertEqual(
            len(infer_calls),
            0,
            "infer_residency_btn should not be rendered when swarm_df is None",
        )

        mocks["analysis_utils.infer_residency_periods"].assert_not_called()

    def test_swarm_df_empty_shows_info_no_infer_button(self) -> None:
        """With an empty DataFrame the infer button must not be rendered."""
        import pandas as pd

        mocks = self._run_with_swarm_df(pd.DataFrame())

        mock_button = mocks["streamlit.button"]
        infer_calls = [c for c in mock_button.call_args_list if "infer_residency_btn" in str(c)]
        self.assertEqual(
            len(infer_calls),
            0,
            "infer_residency_btn should not be rendered when swarm_df is empty",
        )
        mocks["analysis_utils.infer_residency_periods"].assert_not_called()


class TestInferResidencyButtonPresent(unittest.TestCase):
    """When swarm data is available, the infer button must be rendered."""

    def test_infer_button_rendered_when_data_available(self) -> None:
        """A button with key='infer_residency_btn' must be rendered."""
        swarm_df = _sample_swarm_df()
        session: dict[str, Any] = {"swarm_df": swarm_df}
        specs = _base_patch_specs(session, swarm_df, button_side_effect=False)
        mocks = _run_render(specs)

        mock_button = mocks["streamlit.button"]
        infer_calls = [c for c in mock_button.call_args_list if "infer_residency_btn" in str(c)]
        self.assertGreater(
            len(infer_calls),
            0,
            "Expected a button with key='infer_residency_btn' to be rendered",
        )


class TestInferResidencyButtonClickedNonEmpty(unittest.TestCase):
    """When the infer button is clicked and returns non-empty results."""

    def _run_clicked(
        self,
        infer_result: list[dict[str, str]],
        session: dict[str, Any] | None = None,
    ) -> dict[str, MagicMock]:
        swarm_df = _sample_swarm_df()
        if session is None:
            session = {"swarm_df": swarm_df}

        def button_side_effect(*args: Any, **kwargs: Any) -> bool:
            return kwargs.get("key") == "infer_residency_btn"

        specs = _base_patch_specs(
            session,
            swarm_df,
            infer_return=infer_result,
            button_side_effect=button_side_effect,
        )
        return _run_render(specs)

    def test_infer_residency_periods_called_on_button_click(self) -> None:
        """Clicking the infer button calls infer_residency_periods."""
        mocks = self._run_clicked(_sample_inferred())
        mocks["analysis_utils.infer_residency_periods"].assert_called_once()

    def test_result_stored_in_session_state(self) -> None:
        """After inference the result is stored in session_state['_inferred_residency']."""
        swarm_df = _sample_swarm_df()
        session: dict[str, Any] = {"swarm_df": swarm_df}
        self._run_clicked(_sample_inferred(), session=session)

        self.assertIn(
            "_inferred_residency",
            session,
            "'_inferred_residency' must be stored in session_state after inference",
        )
        self.assertEqual(session["_inferred_residency"], _sample_inferred())

    def test_dataframe_rendered_with_non_empty_result(self) -> None:
        """A non-empty inference result must trigger st.dataframe."""
        mocks = self._run_clicked(_sample_inferred())
        mocks["streamlit.dataframe"].assert_called()

    def test_no_zero_result_warning_on_non_empty_result(self) -> None:
        """No 'no residency periods' warning when inference succeeds."""
        mocks = self._run_clicked(_sample_inferred())
        mock_warning = mocks["streamlit.warning"]
        zero_result_warnings = [
            c
            for c in mock_warning.call_args_list
            if "no residency periods" in str(c).lower() or "sufficient check-ins" in str(c).lower()
        ]
        self.assertEqual(len(zero_result_warnings), 0)


class TestInferResidencyButtonClickedEmpty(unittest.TestCase):
    """When the infer button is clicked but returns an empty list."""

    def _run_clicked_empty(self) -> dict[str, MagicMock]:
        swarm_df = _sample_swarm_df()
        session: dict[str, Any] = {"swarm_df": swarm_df}

        def button_side_effect(*args: Any, **kwargs: Any) -> bool:
            return kwargs.get("key") == "infer_residency_btn"

        specs = _base_patch_specs(
            session,
            swarm_df,
            infer_return=[],
            button_side_effect=button_side_effect,
        )
        return _run_render(specs)

    def test_warning_shown_when_result_empty(self) -> None:
        """An empty inference result must trigger st.warning."""
        mocks = self._run_clicked_empty()
        mocks["streamlit.warning"].assert_called()

    def test_dataframe_not_called_when_result_empty(self) -> None:
        """st.dataframe must NOT be called when inference returns []."""
        mocks = self._run_clicked_empty()
        mocks["streamlit.dataframe"].assert_not_called()

    def test_session_state_key_absent_on_empty_result(self) -> None:
        """'_inferred_residency' must not remain in session_state after empty result."""
        swarm_df = _sample_swarm_df()
        session: dict[str, Any] = {"swarm_df": swarm_df}

        def button_side_effect(*args: Any, **kwargs: Any) -> bool:
            return kwargs.get("key") == "infer_residency_btn"

        specs = _base_patch_specs(
            session,
            swarm_df,
            infer_return=[],
            button_side_effect=button_side_effect,
        )
        _run_render(specs)

        self.assertNotIn(
            "_inferred_residency",
            session,
            "'_inferred_residency' must not remain in session_state after empty result",
        )


class TestInferResidencyNoInferenceWhenButtonNotClicked(unittest.TestCase):
    """When the infer button is not clicked, no inference and no dataframe."""

    def test_no_inference_when_button_not_clicked(self) -> None:
        swarm_df = _sample_swarm_df()
        session: dict[str, Any] = {"swarm_df": swarm_df}
        specs = _base_patch_specs(session, swarm_df, button_side_effect=False)
        mocks = _run_render(specs)

        mocks["analysis_utils.infer_residency_periods"].assert_not_called()


class TestInferResidencyPreviewShownFromSessionState(unittest.TestCase):
    """When _inferred_residency is already in session state, the preview dataframe
    is rendered without clicking the infer button again."""

    def test_preview_shown_when_inferred_residency_in_session_state(self) -> None:
        swarm_df = _sample_swarm_df()
        session: dict[str, Any] = {
            "swarm_df": swarm_df,
            "_inferred_residency": _sample_inferred(),
        }
        specs = _base_patch_specs(session, swarm_df, button_side_effect=False)
        mocks = _run_render(specs)

        mocks["streamlit.dataframe"].assert_called()


# ---------------------------------------------------------------------------
# Subtask 3 — Save flow
# ---------------------------------------------------------------------------


class TestSaveButtonNotShownWithoutInferredResidency(unittest.TestCase):
    """When _inferred_residency is not in session state, the Save button must
    not be rendered."""

    def test_save_button_absent_when_no_inferred_residency(self) -> None:
        swarm_df = _sample_swarm_df()
        session: dict[str, Any] = {"swarm_df": swarm_df}  # no _inferred_residency

        specs = _base_patch_specs(session, swarm_df, button_side_effect=False)
        mocks = _run_render(specs)

        mock_button = mocks["streamlit.button"]
        save_calls = [c for c in mock_button.call_args_list if "save_residency_btn" in str(c)]
        self.assertEqual(
            len(save_calls),
            0,
            "Save button must not be rendered when _inferred_residency is absent",
        )


class TestSaveButtonPresentWhenInferredResidencySet(unittest.TestCase):
    """When _inferred_residency is in session state, the Save button must appear."""

    def test_save_button_rendered_when_inferred_residency_in_session(self) -> None:
        swarm_df = _sample_swarm_df()
        session: dict[str, Any] = {
            "swarm_df": swarm_df,
            "_inferred_residency": _sample_inferred(),
        }
        specs = _base_patch_specs(session, swarm_df, button_side_effect=False)
        mocks = _run_render(specs)

        mock_button = mocks["streamlit.button"]
        save_calls = [c for c in mock_button.call_args_list if "save_residency_btn" in str(c)]
        self.assertGreater(
            len(save_calls),
            0,
            "Save button (key='save_residency_btn') must be rendered when "
            "_inferred_residency is in session state",
        )


class TestSaveNoAssumptionsPath(unittest.TestCase):
    """When the Save button is clicked but no assumptions path is configured,
    st.error must be called and no file must be written."""

    def test_save_with_no_assumptions_path_calls_error(self) -> None:
        swarm_df = _sample_swarm_df()
        session: dict[str, Any] = {
            "swarm_df": swarm_df,
            "_inferred_residency": _sample_inferred(),
            "_loaded_config": None,  # no assumptions path
        }

        def button_side_effect(*args: Any, **kwargs: Any) -> bool:
            return kwargs.get("key") == "save_residency_btn"

        # Patch open to assert it is never called
        sentinel = MagicMock(side_effect=AssertionError("open should not be called"))

        specs = _base_patch_specs(
            session,
            swarm_df,
            button_side_effect=button_side_effect,
            extra_patches={"builtins.open": sentinel},
        )
        mocks = _run_render(specs)

        mocks["streamlit.error"].assert_called()


class TestSaveHappyPath(unittest.TestCase):
    """Save writes the new residency list to the JSON file, preserving other keys,
    then calls invalidate_data_cache() and st.rerun()."""

    def _make_session_with_file(
        self, initial_assumptions: dict[str, Any], inferred: list[dict[str, str]]
    ) -> tuple[dict[str, Any], str]:
        swarm_df = _sample_swarm_df()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(initial_assumptions, fh)
            assumptions_path = fh.name
        session: dict[str, Any] = {
            "swarm_df": swarm_df,
            "_inferred_residency": inferred,
            "_loaded_config": ("plugin", "config", assumptions_path),
        }
        return session, assumptions_path

    def test_save_writes_residency_to_file(self) -> None:
        """The JSON file's 'residency' key is replaced with the inferred list."""
        initial = {
            "home": {"city": "Chicago", "lat": 41.8781, "lng": -87.6298},
            "residency": [{"city": "Old City", "start": "2000-01-01", "end": "2005-12-31"}],
        }
        inferred = _sample_inferred()
        swarm_df = _sample_swarm_df()
        session, assumptions_path = self._make_session_with_file(initial, inferred)

        try:

            def button_side_effect(*args: Any, **kwargs: Any) -> bool:
                return kwargs.get("key") == "save_residency_btn"

            specs = _base_patch_specs(
                session,
                swarm_df,
                button_side_effect=button_side_effect,
                extra_patches={
                    "pages.data_sources.load_assumptions": MagicMock(return_value=dict(initial)),
                },
            )
            _run_render(specs)

            with open(assumptions_path, encoding="utf-8") as fh:
                saved = json.load(fh)

            self.assertEqual(
                saved["residency"],
                inferred,
                "Saved 'residency' key must match the inferred list",
            )
            self.assertIn("home", saved, "Other assumption keys must be preserved")

        finally:
            os.unlink(assumptions_path)

    def test_save_calls_invalidate_data_cache(self) -> None:
        """invalidate_data_cache() must be called once on successful save."""
        initial = {"residency": []}
        inferred = _sample_inferred()
        swarm_df = _sample_swarm_df()
        session, assumptions_path = self._make_session_with_file(initial, inferred)

        try:

            def button_side_effect(*args: Any, **kwargs: Any) -> bool:
                return kwargs.get("key") == "save_residency_btn"

            mock_invalidate = MagicMock()
            specs = _base_patch_specs(
                session,
                swarm_df,
                button_side_effect=button_side_effect,
                extra_patches={
                    "pages.data_sources.load_assumptions": MagicMock(return_value=dict(initial)),
                    "pages.data_sources.invalidate_data_cache": mock_invalidate,
                },
            )
            _run_render(specs)

            mock_invalidate.assert_called_once()

        finally:
            os.unlink(assumptions_path)

    def test_save_calls_st_rerun(self) -> None:
        """st.rerun() must be called after a successful save."""
        initial = {"residency": []}
        inferred = _sample_inferred()
        swarm_df = _sample_swarm_df()
        session, assumptions_path = self._make_session_with_file(initial, inferred)

        try:

            def button_side_effect(*args: Any, **kwargs: Any) -> bool:
                return kwargs.get("key") == "save_residency_btn"

            mock_rerun = MagicMock()
            specs = _base_patch_specs(
                session,
                swarm_df,
                button_side_effect=button_side_effect,
                extra_patches={
                    "pages.data_sources.load_assumptions": MagicMock(return_value=dict(initial)),
                    "streamlit.rerun": mock_rerun,
                },
            )
            _run_render(specs)

            mock_rerun.assert_called()

        finally:
            os.unlink(assumptions_path)

    def test_save_removes_session_key_on_success(self) -> None:
        """After a successful save, '_inferred_residency' must be removed from
        session_state."""
        initial = {"residency": []}
        inferred = _sample_inferred()
        swarm_df = _sample_swarm_df()
        session, assumptions_path = self._make_session_with_file(initial, inferred)

        try:

            def button_side_effect(*args: Any, **kwargs: Any) -> bool:
                return kwargs.get("key") == "save_residency_btn"

            specs = _base_patch_specs(
                session,
                swarm_df,
                button_side_effect=button_side_effect,
                extra_patches={
                    "pages.data_sources.load_assumptions": MagicMock(return_value=dict(initial)),
                },
            )
            _run_render(specs)

            self.assertNotIn(
                "_inferred_residency",
                session,
                "'_inferred_residency' must be deleted from session_state after save",
            )

        finally:
            os.unlink(assumptions_path)


class TestSavePermissionError(unittest.TestCase):
    """A PermissionError during write must call st.error and must NOT propagate
    the exception or call invalidate_data_cache."""

    def test_write_permission_error_calls_st_error_not_invalidate(self) -> None:
        initial = {"residency": []}
        inferred = _sample_inferred()
        swarm_df = _sample_swarm_df()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(initial, fh)
            assumptions_path = fh.name

        try:
            session: dict[str, Any] = {
                "swarm_df": swarm_df,
                "_inferred_residency": inferred,
                "_loaded_config": ("plugin", "config", assumptions_path),
            }

            def button_side_effect(*args: Any, **kwargs: Any) -> bool:
                return kwargs.get("key") == "save_residency_btn"

            real_open = builtins.open

            def open_side_effect(file: Any, mode: str = "r", **kwargs: Any) -> Any:
                if file == assumptions_path and "w" in mode:
                    raise PermissionError("Permission denied")
                return real_open(file, mode, **kwargs)

            mock_error = MagicMock()
            mock_invalidate = MagicMock()

            specs = _base_patch_specs(
                session,
                swarm_df,
                button_side_effect=button_side_effect,
                extra_patches={
                    "pages.data_sources.load_assumptions": MagicMock(return_value=dict(initial)),
                    "streamlit.error": mock_error,
                    "pages.data_sources.invalidate_data_cache": mock_invalidate,
                    "builtins.open": MagicMock(side_effect=open_side_effect),
                },
            )
            # Must not raise
            _run_render(specs)

            mock_error.assert_called()
            mock_invalidate.assert_not_called()

        finally:
            os.unlink(assumptions_path)
