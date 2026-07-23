import pytest
from solution import dependency_order

def test_basic():
    graph = {"build":["compile","test"],"compile":["fetch"],"test":["compile"]}
    order = dependency_order(graph)
    pos = {x:i for i,x in enumerate(order)}
    assert pos["fetch"] < pos["compile"] < pos["test"] < pos["build"]

def test_lexical_tie():
    assert dependency_order({"c":["a"],"b":["a"]}) == ["a","b","c"]

def test_dependency_only_node():
    assert dependency_order({"b":["a"]}) == ["a","b"]

def test_duplicate_dependency():
    assert dependency_order({"b":["a","a"]}) == ["a","b"]

def test_cycle():
    with pytest.raises(ValueError):
        dependency_order({"a":["b"],"b":["a"]})
