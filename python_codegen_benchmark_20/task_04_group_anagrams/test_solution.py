from solution import group_anagrams

def test_basic():
    assert group_anagrams(["eat","tea","tan","ate","nat","bat"]) == [
        ["eat","tea","ate"], ["tan","nat"], ["bat"]
    ]

def test_case_sensitive():
    assert group_anagrams(["ab","BA","ba"]) == [["ab","ba"],["BA"]]

def test_empty_strings():
    assert group_anagrams(["", "", "a"]) == [["", ""], ["a"]]

def test_empty_input():
    assert group_anagrams([]) == []
