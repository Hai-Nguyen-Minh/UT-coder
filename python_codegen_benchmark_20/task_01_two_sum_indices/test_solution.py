from solution import two_sum_indices

def test_basic():
    assert two_sum_indices([2, 7, 11, 15], 9) == (0, 1)

def test_duplicate():
    assert two_sum_indices([3, 3], 6) == (0, 1)

def test_tie_break():
    assert two_sum_indices([1, 4, 2, 3], 5) == (0, 1)

def test_none():
    assert two_sum_indices([1, 2, 3], 99) is None

def test_input_unchanged():
    data = [2, 7, 1]
    copy = data[:]
    two_sum_indices(data, 9)
    assert data == copy
