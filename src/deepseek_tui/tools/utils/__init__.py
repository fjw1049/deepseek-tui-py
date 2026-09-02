"""Tool-implementation helpers (not ToolSpec modules).

Distinct from package-level ``deepseek_tui.utils`` (global infra).
"""

from __future__ import annotations

from deepseek_tui.tools.utils.edit_diagnostics import build_edit_no_match_message
from deepseek_tui.tools.utils.path_suggestions import format_not_found_error
from deepseek_tui.tools.utils.sensitive import is_sensitive_path
from deepseek_tui.tools.utils.validation import (
    optional_bool,
    optional_int,
    optional_non_negative_int,
    optional_string,
    optional_string_list,
    require_nonempty_string,
    require_string,
)

__all__ = [
    "build_edit_no_match_message",
    "format_not_found_error",
    "is_sensitive_path",
    "optional_bool",
    "optional_int",
    "optional_non_negative_int",
    "optional_string",
    "optional_string_list",
    "require_nonempty_string",
    "require_string",
]
