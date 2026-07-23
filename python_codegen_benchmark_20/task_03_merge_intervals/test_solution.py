import pytest
from solution import merge_intervals

def test_merge():
    assert merge_intervals([(1,3),(2,6),(8,10),(15,18)]) == [(1,6),(8,10),(15,18)]

def test_touching():
    assert merge_intervals([(1,3),(3,5)]) == [(1,5)]

def test_unsorted_and_nested():
    assert merge_intervals([(5,7),(1,10),(2,3)]) == [(1,10)]

def test_empty():
    assert merge_intervals([]) == []

def test_invalid():
    with pytest.raises(ValueError):
        merge_intervals([(4, 2)])
