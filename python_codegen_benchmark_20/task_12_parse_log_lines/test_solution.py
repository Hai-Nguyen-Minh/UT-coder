import pytest
from datetime import datetime
from solution import parse_log_lines

def test_basic():
    rows = parse_log_lines(["2026-01-02 03:04:05 | info | started"])
    assert rows == [{
        "timestamp": datetime(2026,1,2,3,4,5),
        "level": "INFO",
        "message": "started",
    }]

def test_pipe_in_message():
    rows = parse_log_lines(["2026-01-01 00:00:00|warn|a|b"])
    assert rows[0]["message"] == "a|b"

def test_skip_blank():
    assert parse_log_lines([" ", "\n"]) == []

def test_bad_line_number():
    with pytest.raises(ValueError, match="2"):
        parse_log_lines(["", "bad"])
