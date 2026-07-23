import pytest
from solution import rotate_clockwise

def test_square():
    assert rotate_clockwise([[1,2],[3,4]]) == [[3,1],[4,2]]

def test_rectangle():
    assert rotate_clockwise([[1,2,3],[4,5,6]]) == [[4,1],[5,2],[6,3]]

def test_empty():
    assert rotate_clockwise([]) == []

def test_empty_rows():
    assert rotate_clockwise([[], []]) == []

def test_invalid():
    with pytest.raises(ValueError):
        rotate_clockwise([[1,2],[3]])
