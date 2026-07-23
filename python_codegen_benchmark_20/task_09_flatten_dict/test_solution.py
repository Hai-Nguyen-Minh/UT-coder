from solution import flatten_dict

def test_basic():
    assert flatten_dict({"a":{"b":1},"c":2}) == {"a.b":1,"c":2}

def test_custom_separator():
    assert flatten_dict({"a":{"b":{"c":3}}}, "/") == {"a/b/c":3}

def test_empty_nested():
    assert flatten_dict({"a":{}}) == {"a":{}}

def test_list_is_value():
    assert flatten_dict({"a":[{"b":1}]}) == {"a":[{"b":1}]}

def test_empty_root():
    assert flatten_dict({}) == {}
