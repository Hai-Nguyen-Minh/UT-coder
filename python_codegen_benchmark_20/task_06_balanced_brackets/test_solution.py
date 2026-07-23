from solution import is_balanced

def test_valid():
    assert is_balanced("a*(b+[c-{d}])")

def test_invalid_order():
    assert not is_balanced("([)]")

def test_unclosed():
    assert not is_balanced("(()")

def test_extra_close():
    assert not is_balanced("abc]")

def test_no_brackets():
    assert is_balanced("hello")
