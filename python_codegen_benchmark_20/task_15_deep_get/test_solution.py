from solution import deep_get

DATA = {"users":[{"name":"An"},{"name":"Bình"}],"meta":{"count":2}}

def test_dict_and_list():
    assert deep_get(DATA, "users.1.name") == "Bình"

def test_default():
    assert deep_get(DATA, "users.9.name", "N/A") == "N/A"

def test_invalid_index():
    assert deep_get(DATA, "users.-1.name") is None
    assert deep_get(DATA, "users.01.name") is None

def test_empty_path():
    assert deep_get(DATA, "") is DATA
