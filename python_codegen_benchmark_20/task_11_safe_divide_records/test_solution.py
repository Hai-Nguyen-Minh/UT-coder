from solution import safe_divide_records

def test_mixed():
    assert safe_divide_records([(6,2),(1,0),("a",2),(5,2)]) == [
        3.0, "division_by_zero", "invalid_operand", 2.5
    ]

def test_empty():
    assert safe_divide_records([]) == []

def test_float_zero():
    assert safe_divide_records([(1,0.0)]) == ["division_by_zero"]
