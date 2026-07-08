"""Identity tests proving ``analysis_utils``'s Google Timeline names are a
re-export shim pointing at ``localizer.plugins.google_timeline.parser``, not a
duplicated copy that could silently drift.

These are intentionally *not* behavioral tests — parsing behavior is already
covered by ``tests/test_google_timeline.py`` (23 tests, unmodified by this
subtask) and by Subtask 1's
``packages/localizer/tests/test_google_timeline_parser.py``. A copy-pasted
duplicate of the parser logic would pass every behavioral test yet still fail
these identity checks, which is exactly the failure mode this file exists to
catch.
"""

from __future__ import annotations

import localizer.plugins.google_timeline.parser as parser_mod

import analysis_utils


def test_load_google_timeline_is_reexported_from_parser_module() -> None:
    """``analysis_utils.load_google_timeline`` must be the *same object* as
    ``localizer.plugins.google_timeline.parser.load_google_timeline``."""
    assert analysis_utils.load_google_timeline is parser_mod.load_google_timeline


def test_where_when_columns_is_reexported_from_parser_module() -> None:
    """``analysis_utils._WHERE_WHEN_COLUMNS`` must be the *same object* as
    ``localizer.plugins.google_timeline.parser._WHERE_WHEN_COLUMNS``."""
    assert analysis_utils._WHERE_WHEN_COLUMNS is parser_mod._WHERE_WHEN_COLUMNS


def test_parse_latlng_is_reexported_from_parser_module() -> None:
    """``analysis_utils._parse_latlng`` must be the *same object* as
    ``localizer.plugins.google_timeline.parser._parse_latlng``."""
    assert analysis_utils._parse_latlng is parser_mod._parse_latlng
