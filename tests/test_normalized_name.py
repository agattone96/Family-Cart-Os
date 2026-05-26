"""normalized_name + ingredient matching contract tests (Tickets 2 & 4).

These tests pin the v1 ingredient-matching contract independent of which
backend implementation lands. Production code should use
``scripts.qa_helpers.normalize_name`` (or behave identically) — if you change
this helper, you are changing the QA contract, and the change must be
reflected in ``docs/qa/known-issues.md``.
"""
from __future__ import annotations

import importlib.util
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


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Tomato", "tomato"),
        ("  Tomato  ", "tomato"),
        ("Roma Tomatoes", "roma tomatoes"),
        ("RED-bell pepper", "red bell pepper"),
        ("Heavy   Cream", "heavy cream"),
        ("Garlic\t\nCloves", "garlic cloves"),
        ("Whole-Wheat—Flour", "whole wheat flour"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_name_matches_v1_contract(raw, expected):
    assert qa.normalize_name(raw) == expected


def test_normalize_name_is_idempotent():
    once = qa.normalize_name("Crushed Tomatoes!!")
    twice = qa.normalize_name(once)
    assert once == twice


@pytest.mark.parametrize(
    "a, b, matches",
    [
        ("Tomato", "tomato", True),
        ("Tomato", "tomatoes", False),  # exact match only — no fuzzy matching
        ("Roma Tomatoes", "  ROMA tomatoes  ", True),
        ("Red Bell Pepper", "Red  Bell  Pepper", True),
        ("Olive Oil", "Vegetable Oil", False),
        ("", "Tomato", False),
        ("Tomato", "", False),
        (None, None, False),
    ],
)
def test_names_match_uses_normalized_form(a, b, matches):
    assert qa.names_match(a, b) is matches


def test_normalize_name_handles_unicode_punctuation():
    # The brief warns against pretending fuzzy matching is perfect, but
    # collapsing punctuation must be consistent across input variants.
    assert qa.normalize_name("Half‑and‑Half") == qa.normalize_name("half and half")


def test_normalize_name_is_used_for_ingredient_match():
    inventory_normalized = qa.normalize_name("Olive Oil")
    meal_ingredient_normalized = qa.normalize_name("olive   oil")
    assert inventory_normalized == meal_ingredient_normalized
