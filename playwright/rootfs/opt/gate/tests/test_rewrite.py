import rewrite

TABS_THREE = """### Result
- 0: [Login](http://127.0.0.1:8000/setcookie)
- 1: (current) [Upload](http://127.0.0.1:8000/upload)
- 2: [Who](http://127.0.0.1:8000/whoami)
"""


def test_parse_tabs_finds_current_and_count():
    assert rewrite.parse_tabs(TABS_THREE) == (1, 3)


def test_parse_tabs_single_tab():
    assert rewrite.parse_tabs("### Result\n- 0: (current) [Form](http://x/form)\n") == (0, 1)


def test_parse_tabs_unrecognised_output():
    assert rewrite.parse_tabs("### Result\nNo open tabs.") == (None, 0)


def test_needs_front_only_for_page_actions():
    assert rewrite.needs_front("browser_click")
    assert rewrite.needs_front("browser_file_upload")
    assert rewrite.needs_front("browser_take_screenshot")
    assert not rewrite.needs_front("browser_navigate")
    assert not rewrite.needs_front("browser_tabs")
    assert not rewrite.needs_front("browser_snapshot")


def test_filename_forced_into_playwright_dir():
    assert rewrite.rewrite_args("browser_take_screenshot", {"filename": "../code-interpreter/abc/evil.png"}) == {
        "filename": "playwright/evil.png"
    }
    assert rewrite.rewrite_args("browser_take_screenshot", {"filename": "/data/x.png"}) == {
        "filename": "playwright/x.png"
    }
    assert rewrite.rewrite_args("browser_snapshot", {"filename": "a\\b\\page.yml", "depth": 3}) == {
        "filename": "playwright/page.yml", "depth": 3
    }


def test_filename_hidden_or_empty_is_dropped():
    assert rewrite.rewrite_args("browser_take_screenshot", {"filename": "dir/"}) == {}
    assert rewrite.rewrite_args("browser_take_screenshot", {"filename": "../.."}) == {}
    assert rewrite.rewrite_args("browser_take_screenshot", {"filename": ".env"}) == {"filename": "playwright/env"}


def test_rewrite_does_not_mutate_input():
    args = {"filename": "x/y.png"}
    rewrite.rewrite_args("browser_take_screenshot", args)
    assert args == {"filename": "x/y.png"}


def test_snapshot_gets_default_depth_only_when_missing():
    assert rewrite.rewrite_args("browser_snapshot", {}) == {"depth": rewrite.SNAPSHOT_DEFAULT_DEPTH}
    assert rewrite.rewrite_args("browser_snapshot", {"depth": 12}) == {"depth": 12}
    assert rewrite.rewrite_args("browser_click", {"target": "e1"}) == {"target": "e1"}


def test_truncate_under_limit_untouched():
    assert rewrite.truncate_texts(["abc", "def"], 10) == ["abc", "def"]


def test_truncate_shares_budget_and_appends_note():
    out = rewrite.truncate_texts(["a" * 8, "b" * 8], 10)
    assert out[0] == "a" * 8
    assert out[1].startswith("bb")
    assert "10 of 16 characters" in out[1]
    assert "depth" in out[1]


def test_truncate_drops_text_after_budget():
    out = rewrite.truncate_texts(["a" * 10, "b" * 5, "c" * 5], 10)
    assert out[0].startswith("a" * 10) and "10 of 20" in out[0]
    assert out[1:] == ["", ""]
