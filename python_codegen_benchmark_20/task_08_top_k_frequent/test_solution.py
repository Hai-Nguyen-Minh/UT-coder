from solution import top_k_frequent

def test_basic():
    assert top_k_frequent([1,1,1,2,2,3], 2) == [1,2]

def test_tie_first_seen():
    assert top_k_frequent(["b","a","b","a","c"], 2) == ["b","a"]

def test_large_k():
    assert top_k_frequent([3,3,2], 10) == [3,2]

def test_non_positive():
    assert top_k_frequent([1,2], 0) == []
