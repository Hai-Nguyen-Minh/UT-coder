import pytest
from solution import MemoizedFibonacci

def test_values():
    f = MemoizedFibonacci()
    assert [f.fib(i) for i in range(8)] == [0,1,1,2,3,5,8,13]

def test_cache_count():
    f = MemoizedFibonacci()
    assert f.fib(6) == 8
    assert f.computed_count == 5
    assert f.fib(4) == 3
    assert f.computed_count == 5
    assert f.fib(8) == 21
    assert f.computed_count == 7

@pytest.mark.parametrize("n", [-1,2.5,True])
def test_invalid(n):
    with pytest.raises(ValueError):
        MemoizedFibonacci().fib(n)

def test_read_only_property():
    f = MemoizedFibonacci()
    with pytest.raises(AttributeError):
        f.computed_count = 99
