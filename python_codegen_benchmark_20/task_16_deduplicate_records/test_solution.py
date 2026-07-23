import pytest
from solution import deduplicate_records

def test_basic():
    rows = [{"id":1,"x":"a"},{"id":2,"x":"b"},{"id":1,"x":"c"}]
    assert deduplicate_records(rows, "id") == rows[:2]

def test_copies():
    row = {"id":1}
    out = deduplicate_records([row], "id")
    assert out[0] == row
    assert out[0] is not row

def test_missing_key():
    with pytest.raises(KeyError):
        deduplicate_records([{"id":1}, {"x":2}], "id")

def test_generator():
    rows = ({"id":x} for x in [1,1,2])
    assert deduplicate_records(rows, "id") == [{"id":1},{"id":2}]
