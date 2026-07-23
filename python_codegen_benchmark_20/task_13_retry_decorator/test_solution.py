import pytest
from solution import retry

def test_eventual_success():
    state = {"n": 0}
    @retry(3, (ValueError,))
    def f():
        state["n"] += 1
        if state["n"] < 3:
            raise ValueError("x")
        return 7
    assert f() == 7
    assert state["n"] == 3

def test_final_exception():
    @retry(2, (ValueError,))
    def f():
        raise ValueError("last")
    with pytest.raises(ValueError, match="last"):
        f()

def test_unmatched_exception_no_retry():
    state = {"n": 0}
    @retry(5, (ValueError,))
    def f():
        state["n"] += 1
        raise TypeError("stop")
    with pytest.raises(TypeError):
        f()
    assert state["n"] == 1

def test_metadata():
    @retry(1)
    def named():
        "doc"
    assert named.__name__ == "named"
    assert named.__doc__ == "doc"

@pytest.mark.parametrize("n", [0,-1,1.2,True])
def test_invalid(n):
    with pytest.raises(ValueError):
        retry(n)
