import pytest
from solution import LRUCache

def test_eviction():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)
    assert c.get("b") is None
    assert c.get("a") == 1
    assert c.get("c") == 3

def test_update():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 9)
    c.put("c", 3)
    assert c.get("b") is None
    assert c.get("a") == 9

def test_len():
    c = LRUCache(1)
    c.put(1, 1)
    c.put(2, 2)
    assert len(c) == 1

@pytest.mark.parametrize("capacity", [0, -1, 1.5, True])
def test_invalid_capacity(capacity):
    with pytest.raises(ValueError):
        LRUCache(capacity)
