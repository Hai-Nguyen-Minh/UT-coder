import ast

from core.ast_patcher import (
    extract_functions,
    failed_pytest_targets,
    patch_functions,
)


def test_failed_targets_include_class_method_parameters_and_setup_hook():
    log = '''
ERROR at setup of TestRecords.test_build
FAILED test_module_under_test.py::TestMath::test_value[negative] - assert 1 == 2
ERROR test_module_under_test.py::TestRecords::test_build - TypeError
'''

    assert failed_pytest_targets(log) == [
        "TestMath::test_value",
        "TestRecords::test_build",
        "TestRecords::setup_method",
    ]


def test_extract_qualified_async_method_keeps_decorator():
    source = '''
class TestApi:
    @pytest.mark.asyncio
    async def test_fetch(self):
        assert await fetch() == 1
'''

    extracted = extract_functions(source, ["TestApi::test_fetch"])

    assert "# pytest node: TestApi::test_fetch" in extracted
    assert "@pytest.mark.asyncio" in extracted
    assert "async def test_fetch" in extracted


def test_patch_only_selected_class_method_and_preserve_decorator():
    original = '''
class TestA:
    @pytest.mark.parametrize("value", [1])
    def test_same(self, value):
        assert value == 2

class TestB:
    def test_same(self):
        assert 1 == 2
'''
    replacement = '''
def test_same(self, value):
    assert value == 1
'''

    patched = patch_functions(original, replacement, ["TestA::test_same"])
    tree = ast.parse(patched)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    method_a = classes["TestA"].body[0]
    method_b = classes["TestB"].body[0]

    assert method_a.decorator_list
    assert "value == 1" in ast.unparse(method_a)
    assert "1 == 2" in ast.unparse(method_b)
