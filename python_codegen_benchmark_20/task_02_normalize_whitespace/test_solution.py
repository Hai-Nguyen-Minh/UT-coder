from solution import normalize_whitespace

def test_spaces():
    assert normalize_whitespace("  hello   world  ") == "hello world"

def test_tabs_newlines():
    assert normalize_whitespace("\ta\n\n b\r\nc ") == "a b c"

def test_empty():
    assert normalize_whitespace("   \t\n") == ""

def test_unicode_text():
    assert normalize_whitespace("  xin   chào\nViệt Nam ") == "xin chào Việt Nam"
