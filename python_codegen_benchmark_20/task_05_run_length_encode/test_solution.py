from solution import run_length_encode

def test_basic():
    assert run_length_encode("aaabbcaaa") == [("a",3),("b",2),("c",1),("a",3)]

def test_single():
    assert run_length_encode("x") == [("x",1)]

def test_empty():
    assert run_length_encode("") == []

def test_unicode():
    assert run_length_encode("áá🙂🙂🙂") == [("á",2),("🙂",3)]
