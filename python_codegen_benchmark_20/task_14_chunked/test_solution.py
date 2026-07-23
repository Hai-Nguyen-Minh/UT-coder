import pytest
from solution import chunked

def test_list():
    assert list(chunked([1,2,3,4,5], 2)) == [[1,2],[3,4],[5]]

def test_generator():
    source = (i*i for i in range(5))
    assert list(chunked(source, 3)) == [[0,1,4],[9,16]]

def test_empty():
    assert list(chunked([], 2)) == []

@pytest.mark.parametrize("size", [0,-1,2.5,True])
def test_invalid(size):
    with pytest.raises(ValueError):
        list(chunked([1,2], size))
