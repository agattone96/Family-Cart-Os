"""AI response validation contract tests (Ticket 3).

The v1 brief says AI responses must be validated before rendering and that
empty / malformed / incomplete responses must be rejected — they may not
produce broken or partial cards. These tests pin that contract.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_helpers():
    spec = importlib.util.spec_from_file_location(
        "qa_helpers", REPO_ROOT / "scripts" / "qa_helpers.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qa = _load_helpers()


def _valid_meal(title: str = "Quick Tomato Pasta") -> dict:
    return {
        "title": title,
        "description": "Pantry pasta with what you already have.",
        "ingredients_used": [{"name": "Tomato", "quantity": 2, "unit": "ea"}],
        "inventory_matches": ["Tomato", "Pasta"],
        "missing_ingredients": [{"name": "Parmesan", "quantity": 50, "unit": "g"}],
        "optional_substitutions": [{"from": "Parmesan", "to": "Pecorino"}],
        "estimated_prep_complexity": "low",
    }


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_validate_accepts_minimal_valid_response():
    payload = [_valid_meal()]
    parsed = qa.validate_ai_meal_response(payload)
    assert len(parsed) == 1
    assert parsed[0]["title"] == "Quick Tomato Pasta"


def test_parse_and_validate_handles_markdown_fenced_response():
    fenced = "```json\n" + json.dumps([_valid_meal()]) + "\n```"
    parsed = qa.parse_and_validate_ai_meal_text(fenced)
    assert len(parsed) == 1
    assert parsed[0]["estimated_prep_complexity"] == "low"


def test_parse_and_validate_handles_plain_json_response():
    raw = json.dumps([_valid_meal("A"), _valid_meal("B")])
    parsed = qa.parse_and_validate_ai_meal_text(raw)
    assert [m["title"] for m in parsed] == ["A", "B"]


# ---------------------------------------------------------------------------
# Failure: empty response
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [None, [], {}])
def test_validate_rejects_empty_or_non_list_payload(payload):
    with pytest.raises(qa.AIResponseValidationError):
        qa.validate_ai_meal_response(payload)


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_parse_and_validate_rejects_empty_text(text):
    with pytest.raises(qa.AIResponseValidationError):
        qa.parse_and_validate_ai_meal_text(text)


def test_parse_and_validate_rejects_empty_json_array_text():
    with pytest.raises(qa.AIResponseValidationError):
        qa.parse_and_validate_ai_meal_text("[]")


# ---------------------------------------------------------------------------
# Failure: malformed JSON
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        '{"title": "Pasta", "description": ',  # truncated
        '[{"title": "Pasta", }]',  # trailing comma
        "[null]",
    ],
)
def test_parse_and_validate_rejects_malformed_json(text):
    with pytest.raises(qa.AIResponseValidationError):
        qa.parse_and_validate_ai_meal_text(text)


# ---------------------------------------------------------------------------
# Failure: missing required fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing_field", list(qa.REQUIRED_AI_MEAL_FIELDS))
def test_validate_rejects_meal_missing_any_required_field(missing_field):
    meal = _valid_meal()
    del meal[missing_field]
    with pytest.raises(qa.AIResponseValidationError) as exc:
        qa.validate_ai_meal_response([meal])
    assert missing_field in str(exc.value)


def test_validate_rejects_when_first_meal_invalid_even_if_second_valid():
    bad = _valid_meal()
    del bad["title"]
    good = _valid_meal()
    with pytest.raises(qa.AIResponseValidationError):
        qa.validate_ai_meal_response([bad, good])


def test_validate_rejects_non_object_meal_entry():
    with pytest.raises(qa.AIResponseValidationError):
        qa.validate_ai_meal_response(["just a string"])


# ---------------------------------------------------------------------------
# Documented set of required fields
# ---------------------------------------------------------------------------


def test_required_fields_match_v1_brief():
    assert set(qa.REQUIRED_AI_MEAL_FIELDS) == {
        "title",
        "description",
        "ingredients_used",
        "inventory_matches",
        "missing_ingredients",
        "optional_substitutions",
        "estimated_prep_complexity",
    }
