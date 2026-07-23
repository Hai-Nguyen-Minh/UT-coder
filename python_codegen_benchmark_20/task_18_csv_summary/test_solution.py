import pytest
from decimal import Decimal
from solution import summarize_csv

def test_basic():
    text = "category,amount\nA,1.20\nB,2\nA,3.30\n"
    assert summarize_csv(text) == {"A":Decimal("4.50"),"B":Decimal("2")}

def test_spaces_and_blank():
    text = "category,amount\n A , 2.5 \n\n"
    assert summarize_csv(text) == {"A":Decimal("2.5")}

def test_missing_header():
    with pytest.raises(ValueError):
        summarize_csv("name,value\na,1\n")

def test_invalid_amount():
    with pytest.raises(ValueError):
        summarize_csv("category,amount\nA,abc\n")

def test_empty_category():
    with pytest.raises(ValueError):
        summarize_csv("category,amount\n,1\n")
