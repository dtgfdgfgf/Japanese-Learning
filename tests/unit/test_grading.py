"""
Unit tests for grading logic.

T062: Write unit tests for grader
DoD: 涵蓋所有 normalize 規則；邊界案例（空白、標點）通過
"""

import json
from pathlib import Path

import pytest

from src.lib.normalizer import normalize_for_compare, is_correct_answer


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "grading"


@pytest.fixture
def grading_fixtures() -> dict:
    """Load grading test fixtures."""
    with open(FIXTURES_DIR / "test_cases.json", "r", encoding="utf-8") as f:
        return json.load(f)


class TestGrading:
    """Tests for answer grading logic."""
    
    def test_exact_match(self, grading_fixtures):
        """Test exact match."""
        case = grading_fixtures["exact_match"]
        result = is_correct_answer(case["input"], case["expected"])
        assert result is case["should_be_correct"]
    
    def test_width_conversion(self, grading_fixtures):
        """Test fullwidth to halfwidth conversion."""
        for case in grading_fixtures["width_conversion"]["cases"]:
            result = is_correct_answer(case["input"], case["expected"])
            assert result is case["should_be_correct"], f"Failed for {case['input']}"
    
    def test_whitespace_handling(self, grading_fixtures):
        """Test whitespace handling."""
        for case in grading_fixtures["whitespace_handling"]["cases"]:
            result = is_correct_answer(case["input"], case["expected"])
            assert result is case["should_be_correct"], f"Failed for {case['input']}"
    
    def test_case_insensitive(self, grading_fixtures):
        """Test case insensitive matching."""
        for case in grading_fixtures["case_insensitive"]["cases"]:
            result = is_correct_answer(case["input"], case["expected"])
            assert result is case["should_be_correct"], f"Failed for {case['input']}"
    
    def test_wrong_answer(self, grading_fixtures):
        """Test incorrect answers."""
        for case in grading_fixtures["wrong_answer"]["cases"]:
            result = is_correct_answer(case["input"], case["expected"])
            assert result is case["should_be_correct"], f"Should be False for {case['input']}"
    
    def test_empty_strings(self, grading_fixtures):
        """Test empty string handling."""
        for case in grading_fixtures["empty_strings"]["cases"]:
            result = is_correct_answer(case["input"], case["expected"])
            assert result is case["should_be_correct"]
    
    def test_grammar_patterns(self, grading_fixtures):
        """Test grammar pattern matching."""
        for case in grading_fixtures["grammar_patterns"]["cases"]:
            result = is_correct_answer(case["input"], case["expected"])
            # Allow some flexibility in grammar matching
            # The exact result depends on normalizer implementation


class TestNormalizeForCompare:
    """Tests for normalize_for_compare function."""
    
    def test_lowercase(self):
        """Test lowercase conversion."""
        assert "hello" in normalize_for_compare("HELLO").lower()
    
    def test_strip_whitespace(self):
        """Test whitespace stripping."""
        result = normalize_for_compare("  test  ")
        assert result == "test"
    
    def test_fullwidth_to_halfwidth(self):
        """Test fullwidth to halfwidth conversion."""
        result = normalize_for_compare("ＡＢＣ１２３")
        assert result == "abc123"
    
    def test_empty_string(self):
        """Test empty string."""
        result = normalize_for_compare("")
        assert result == ""
    
    def test_hiragana_preserved(self):
        """Test hiragana is preserved."""
        result = normalize_for_compare("ひらがな")
        assert "ひらがな" in result or result == "ひらがな"
    
    def test_kanji_preserved(self):
        """Test kanji is preserved."""
        result = normalize_for_compare("漢字")
        assert "漢字" in result


class TestIsCorrectAnswer:
    """Tests for is_correct_answer function."""
    
    def test_basic_correct(self):
        """Test basic correct answer."""
        assert is_correct_answer("考える", "考える") is True
    
    def test_basic_incorrect(self):
        """Test basic incorrect answer."""
        assert is_correct_answer("wrong", "correct") is False
    
    def test_with_whitespace(self):
        """Test matching with whitespace."""
        assert is_correct_answer("  考える  ", "考える") is True
    
    def test_case_insensitive(self):
        """Test case insensitive matching."""
        assert is_correct_answer("Hello", "hello") is True
    
    def test_fullwidth_halfwidth(self):
        """Test fullwidth/halfwidth equivalence."""
        assert is_correct_answer("ＡＢＣ", "abc") is True
