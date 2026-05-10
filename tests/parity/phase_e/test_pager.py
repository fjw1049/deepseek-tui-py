"""Pager state machine parity tests.

Mirror Rust tests in ``crates/tui/src/tui/pager.rs`` (pager.rs:483-808).
"""

from __future__ import annotations

from deepseek_tui.tui.widgets.pager import PagerAction, PagerState


def _make(lines: int = 50) -> PagerState:
    state = PagerState(title="T", lines=[f"line-{i:03}" for i in range(lines)])
    state.visible_height = 22
    return state


def test_j_scrolls_down_one_line() -> None:
    p = _make()
    p.handle_key("j")
    assert p.scroll == 1


def test_k_scrolls_up_one_line() -> None:
    p = _make()
    p.scroll = 5
    p.handle_key("k")
    assert p.scroll == 4


def test_gg_jumps_to_top() -> None:
    p = _make()
    p.scroll = 30
    p.handle_key("g")
    assert p.pending_g
    assert p.scroll == 30
    p.handle_key("g")
    assert p.scroll == 0
    assert not p.pending_g


def test_home_jumps_to_top() -> None:
    p = _make()
    p.scroll = 30
    p.handle_key("home")
    assert p.scroll == 0


def test_shift_g_jumps_to_bottom() -> None:
    p = _make()
    p.handle_key("G")
    assert p.scroll == p.max_scroll()


def test_end_jumps_to_bottom() -> None:
    p = _make()
    p.handle_key("end")
    assert p.scroll == p.max_scroll()


def test_ctrl_d_half_page_down() -> None:
    p = _make(200)
    half = p.half_page_height()
    assert half >= 1
    p.handle_key("d", ctrl=True)
    assert p.scroll == half


def test_ctrl_u_half_page_up() -> None:
    p = _make(200)
    p.scroll = 50
    half = p.half_page_height()
    p.handle_key("u", ctrl=True)
    assert p.scroll == 50 - half


def test_ctrl_f_full_page_down() -> None:
    p = _make(200)
    page = p.page_height()
    p.handle_key("f", ctrl=True)
    assert p.scroll == page


def test_ctrl_b_full_page_up() -> None:
    p = _make(200)
    p.scroll = 80
    page = p.page_height()
    p.handle_key("b", ctrl=True)
    assert p.scroll == 80 - page


def test_space_pages_down() -> None:
    p = _make(200)
    page = p.page_height()
    p.handle_key("space")
    assert p.scroll == page


def test_shift_space_pages_up() -> None:
    p = _make(200)
    p.scroll = 80
    page = p.page_height()
    p.handle_key("space", shift=True)
    assert p.scroll == 80 - page


def test_pagedown_uses_page_height() -> None:
    p = _make(200)
    page = p.page_height()
    p.handle_key("pagedown")
    assert p.scroll == page


def test_q_closes_pager() -> None:
    p = _make(10)
    assert p.handle_key("q") == PagerAction.CLOSE


def test_esc_closes_pager() -> None:
    p = _make(10)
    assert p.handle_key("escape") == PagerAction.CLOSE


def test_g_does_not_consume_search_input() -> None:
    """In search mode 'g' is a search character, not a chord half."""
    p = _make()
    p.scroll = 10
    p.handle_key("/")
    assert p.search_mode
    p.handle_key("g")
    assert p.search_input == "g"
    assert p.scroll == 10


def test_search_finds_matches() -> None:
    p = _make(20)
    p.handle_key("/")
    p.handle_key("5")
    p.handle_key("enter")
    assert p.search_matches  # found at least one match
    # cursor jumped to first match
    assert p.scroll == p.search_matches[0]


def test_esc_in_search_mode_clears_matches() -> None:
    p = _make(20)
    p.handle_key("/")
    p.handle_key("5")
    p.handle_key("enter")
    assert p.search_matches

    p.handle_key("/")
    p.handle_key("escape")
    assert p.search_matches == []
    assert p.search_input == ""
    assert not p.search_mode


def test_n_and_capital_n_cycle_matches_with_wrap() -> None:
    p = _make(50)
    p.handle_key("/")
    p.handle_key("1")
    p.handle_key("enter")
    total = len(p.search_matches)
    assert total > 1

    start = p.search_index
    p.handle_key("n")
    assert p.search_index == (start + 1) % total
    p.handle_key("N")
    assert p.search_index == start

    # Wrap backwards from 0 to last.
    p.handle_key("N")
    assert p.search_index == total - 1
    p.handle_key("n")
    assert p.search_index == 0


def test_backspace_in_search_removes_last_char() -> None:
    p = _make()
    p.handle_key("/")
    p.handle_key("5")
    p.handle_key("0")
    assert p.search_input == "50"
    p.handle_key("backspace")
    assert p.search_input == "5"


def test_visible_lines_window() -> None:
    p = _make(10)
    p.visible_height = 4
    p.scroll = 2
    assert p.visible_lines() == ["line-002", "line-003", "line-004", "line-005"]
