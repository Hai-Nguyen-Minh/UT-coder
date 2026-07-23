import pytest
from solution import sliding_window_max

def test_basic():
    assert sliding_window_max([1,3,-1,-3,5,3,6,7], 3) == [3,3,5,5,6,7]

def test_k_one():
    assert sliding_window_max([2,1], 1) == [2,1]

def test_full():
    assert sliding_window_max([2,9,1], 3) == [9]

def test_duplicates():
    assert sliding_window_max([4,4,4], 2) == [4,4]

@pytest.mark.parametrize("k", [0,-1,4,1.5,True])
def test_invalid(k):
    with pytest.raises(ValueError):
        sliding_window_max([1,2,3], k)
