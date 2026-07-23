from core.source_analyzer import analyze_python_source


def test_analyzer_reports_top_level_contract_and_nested_functions():
    source = '''
def transform(values, limit=3):
    def helper(value):
        return value * 2
    if not values:
        raise ValueError("values required")
    values.append(limit)
    return [helper(value) for value in values]
'''

    analysis = analyze_python_source(source)

    assert analysis["valid"] is True
    assert analysis["top_level_symbols"] == ["transform"]
    function = analysis["functions"][0]
    assert function["nested_functions"] == ["helper"]
    assert function["mutated_arguments"] == ["values"]
    assert function["branches"][0]["condition"] == "not values"
    assert function["raises"][0]["exception"] == "ValueError"
    assert analysis["behavioral_eligibility"]["eligible"] is True


def test_deterministic_datetime_csv_io_and_unicode_remain_probeable():
    source = '''
from datetime import datetime
import csv
import io
import unicodedata

def normalize_row(value):
    parsed = datetime.strptime("2023-01-01", "%Y-%m-%d")
    row = next(csv.reader(io.StringIO(value)))
    return parsed.year, [unicodedata.normalize("NFC", item) for item in row]
'''

    analysis = analyze_python_source(source)

    assert analysis["unsafe_imports"] == []
    assert analysis["functions"][0]["external_dependencies"] == []
    assert analysis["behavioral_eligibility"]["eligible"] is True


def test_nondeterministic_datetime_now_is_not_behaviorally_probed():
    source = '''
from datetime import datetime

def current_time():
    return datetime.now()
'''

    analysis = analyze_python_source(source)

    assert analysis["functions"][0]["external_dependencies"] == ["time"]
    assert analysis["behavioral_eligibility"]["eligible"] is False


def test_analyzer_returns_a_structured_error_for_invalid_source():
    analysis = analyze_python_source("def broken(:\n    pass")

    assert analysis["valid"] is False
    assert analysis["functions"] == []
    assert "SyntaxError" in analysis["error"]


def test_router_rejects_custom_objects_and_injected_protocols():
    custom_source = '''
class TreeNode:
    def __init__(self, value):
        self.value = value

def traverse_tree(node: TreeNode):
    return node.value
'''
    dependency_source = '''
def fetch_user_data(db_connection, user_id):
    return db_connection.execute("select user", user_id)
'''

    custom = analyze_python_source(custom_source)["behavioral_eligibility"]
    dependency = analyze_python_source(dependency_source)["behavioral_eligibility"]

    assert custom["eligible"] is False
    assert "module_contains_classes_or_custom_objects" in custom["reasons"]
    assert dependency["eligible"] is False
    assert "fetch_user_data:custom_object_or_injected_protocol" in dependency["reasons"]


def test_router_rejects_external_imports_and_import_time_side_effects():
    source = '''
import requests
TOKEN = load_token()

def fetch(url):
    return requests.get(url).json()
'''
    eligibility = analyze_python_source(source)["behavioral_eligibility"]

    assert eligibility["eligible"] is False
    assert "module_has_external_imports" in eligibility["reasons"]
    assert "module_has_top_level_side_effects" in eligibility["reasons"]


def test_router_rejects_shared_state_and_generators():
    stateful = '''
def next_value():
    next_value.counter += 1
    return next_value.counter
'''
    generator = '''
def values(limit):
    for item in range(limit):
        yield item
'''

    stateful_reasons = analyze_python_source(stateful)["behavioral_eligibility"]["reasons"]
    generator_reasons = analyze_python_source(generator)["behavioral_eligibility"]["reasons"]

    assert "next_value:shared_state_mutation" in stateful_reasons
    assert "values:generator_requires_consumption_strategy" in generator_reasons
