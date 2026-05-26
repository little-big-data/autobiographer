"""Shared plugin configuration utilities used by both the sidebar and Data Sources page.

Extracted from ``components/sidebar.py`` so the same path-input widgets and
session-state hydration logic can be reused without duplication.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import streamlit as st

from core.local_settings import LocalSettings

try:
    import tkinter as _tk  # noqa: F401

    _TKINTER_AVAILABLE = True
except Exception:
    _TKINTER_AVAILABLE = False

# Module-level singleton — reads local_settings.json once on first import.
settings = LocalSettings()


def load_config_into_session_state() -> None:
    """Hydrate session state from local_settings.json.

    Called on every page render. Sets keys that are absent from session state,
    and also restores keys that are present as empty string when the disk value
    is non-empty.  The empty-string case happens when Streamlit resets a
    widget-bound key after an in-handler st.rerun() call — restoring from disk
    prevents the sidebar from treating the path as unconfigured and reloading
    data without swarm context.
    """
    for plugin_id, plugin_cfg in settings.get_all_plugin_configs().items():
        for field_key, value in plugin_cfg.items():
            if not isinstance(value, str):
                continue
            session_key = f"{plugin_id}_{field_key}"
            current = st.session_state.get(session_key)
            # Set if absent; also restore from disk when session has empty
            # string but disk has a non-empty value (widget reset after rerun).
            if current is None or (isinstance(current, str) and not current and value):
                st.session_state[session_key] = value


def path_input(
    label: str,
    session_key: str,
    on_persist: Callable[[str], None],
    default: str = "",
    file_types: list[tuple[str, str]] | None = None,
    is_dir: bool = False,
) -> str:
    """Render a path text input with a native browse button.

    The browse button opens a tkinter file or directory dialog on the local
    machine. This is valid because the Streamlit server is localhost for this
    application.

    Streamlit forbids writing to a session state key that is already bound to a
    widget in the same script run. We work around this with a pending-key
    pattern: the browse dialog stores its result under ``_pending_{session_key}``
    and triggers a rerun. At the top of the *next* run this value is transferred
    to the widget key before the widget is instantiated, which is always allowed.

    Args:
        label: Display label for the text input.
        session_key: Session state key used to persist the path value.
        on_persist: Callback invoked with the new path string whenever the value
            changes; responsible for writing to ``local_settings.json``.
        default: Default path value when neither session state nor the saved
            config has an entry for this key.
        file_types: List of (description, glob pattern) tuples for the file
            dialog filter, e.g. ``[("CSV files", "*.csv")]``. Ignored when
            ``is_dir`` is True.
        is_dir: If True, open a directory picker; otherwise open a file picker.

    Returns:
        The current path string from session state.
    """
    pending_key = f"_pending_{session_key}"

    if pending_key in st.session_state:
        value = str(st.session_state.pop(pending_key))
        st.session_state[session_key] = value
        on_persist(value)
    elif session_key not in st.session_state:
        st.session_state[session_key] = default

    def _on_change() -> None:
        on_persist(str(st.session_state.get(session_key, "")))

    if _TKINTER_AVAILABLE:
        col1, col2 = st.columns([4, 1])
        col1.text_input(label, key=session_key, on_change=_on_change)

        if col2.button("...", key=f"browse_{session_key}", help="Browse for path"):
            import threading

            _result: list[str] = []

            def _open_dialog() -> None:
                import tkinter as tk
                from tkinter import filedialog

                root = tk.Tk()
                root.withdraw()
                try:
                    root.wm_attributes("-topmost", 1)
                except Exception:  # noqa: S110 — not available on all platforms
                    pass
                if is_dir:
                    path = filedialog.askdirectory(title=label)
                else:
                    path = filedialog.askopenfilename(
                        title=label,
                        filetypes=file_types or [("All files", "*.*")],
                    )
                root.destroy()
                if path:
                    _result.append(path)

            t = threading.Thread(target=_open_dialog, daemon=True)
            t.start()
            t.join()

            if _result:
                st.session_state[pending_key] = _result[0]
                st.rerun()
    else:
        st.text_input(label, key=session_key, on_change=_on_change)

    return str(st.session_state.get(session_key, default))


def render_plugin_config_fields(plugin_id: str, fields: list[dict[str, Any]]) -> dict[str, str]:
    """Render config fields for one plugin and return collected values.

    Args:
        plugin_id: The plugin's PLUGIN_ID, used to namespace session state keys.
        fields: Field descriptor list from ``plugin.get_config_fields()``.

    Returns:
        Dict mapping each field key to its current value.
    """
    config: dict[str, str] = {}
    saved_cfg = settings.get_plugin_config(plugin_id)
    for field in fields:
        env_key = f"AUTOBIO_{plugin_id.upper()}_{field['key'].upper()}"
        # Env var overrides disk; disk value is the fallback over blank.
        default = os.getenv(env_key, "") or saved_cfg.get(field["key"], "")
        is_dir = field.get("type") == "dir_path"
        field_key = field["key"]

        def _make_persist(fk: str = field_key) -> Callable[[str], None]:
            def _persist(path: str) -> None:
                settings.set_plugin_value(plugin_id, fk, path)

            return _persist

        value = path_input(
            label=field["label"],
            session_key=f"{plugin_id}_{field['key']}",
            on_persist=_make_persist(),
            default=default,
            file_types=field.get("file_types"),
            is_dir=is_dir,
        )
        config[field["key"]] = value
    return config


def get_plugin_config_from_session(plugin_id: str, fields: list[dict[str, Any]]) -> dict[str, str]:
    """Read current config values from session state without rendering any widgets.

    Args:
        plugin_id: The plugin's PLUGIN_ID.
        fields: Field descriptor list from ``plugin.get_config_fields()``.

    Returns:
        Dict mapping each field key to its current session state value.
    """
    return {
        field["key"]: str(st.session_state.get(f"{plugin_id}_{field['key']}", ""))
        for field in fields
    }
