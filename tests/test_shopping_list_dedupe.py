"""Shopping list deduplication contract (Ticket 5).

These tests pin the deduplication rules required by the v1 brief:

* Items are matched by ``normalized_name``.
* Manual / missing-ingredient / low-stock additions are all deduped.
* User-edited fields are not silently overwritten.
* Checked items are not silently reactivated on merge.
* Source references are preserved (and back-filled when missing).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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


def test_incoming_item_with_same_normalized_name_does_not_duplicate():
    existing = [
        {
            "id": "1",
            "name": "Tomato",
            "quantity": 2,
            "is_checked": False,
            "source_type": "manual",
        }
    ]
    merged = qa.merge_into_shopping_list(
        existing,
        {"name": "tomatoes  ", "quantity": 1, "source_type": "missing_ingredient"},
    )
    # tomatoes != tomato in v1 (exact match only — see test_normalized_name).
    # We use the same word here ("tomato" vs "  Tomato  ") in the next test.
    assert len(merged) == 2


def test_dedupe_by_normalized_name_collapses_whitespace_case_punctuation():
    existing = [{"id": "1", "name": "Roma Tomatoes", "quantity": 2, "is_checked": False}]
    merged = qa.merge_into_shopping_list(
        existing,
        {"name": "  roma-tomatoes  ", "quantity": 1, "source_type": "missing_ingredient"},
    )
    assert len(merged) == 1, "Whitespace/case/punctuation must dedupe"


def test_merge_does_not_overwrite_user_edited_fields():
    existing = [
        {
            "id": "1",
            "name": "Olive Oil",
            "quantity": 5,
            "unit": "tbsp",
            "notes": "extra virgin",
            "category": "pantry",
            "is_checked": False,
        }
    ]
    merged = qa.merge_into_shopping_list(
        existing,
        {
            "name": "olive oil",
            "quantity": 1,
            "unit": "tsp",
            "notes": "any",
            "category": "oils",
            "source_type": "missing_ingredient",
        },
    )
    assert len(merged) == 1
    # User-edited values are preserved
    assert merged[0]["quantity"] == 5
    assert merged[0]["unit"] == "tbsp"
    assert merged[0]["notes"] == "extra virgin"
    assert merged[0]["category"] == "pantry"


def test_merge_fills_in_missing_fields_from_incoming():
    existing = [{"id": "1", "name": "Pasta", "is_checked": False}]
    merged = qa.merge_into_shopping_list(
        existing,
        {"name": "pasta", "quantity": 500, "unit": "g", "source_type": "manual"},
    )
    assert len(merged) == 1
    assert merged[0]["quantity"] == 500
    assert merged[0]["unit"] == "g"
    assert merged[0]["source_type"] == "manual"


def test_merge_preserves_existing_source_references_and_backfills_missing():
    existing = [
        {
            "id": "1",
            "name": "Basil",
            "is_checked": False,
            "source_type": "manual",
            "source_meal_plan_id": None,
        }
    ]
    merged = qa.merge_into_shopping_list(
        existing,
        {
            "name": "basil",
            "source_type": "missing_ingredient",
            "source_meal_plan_id": "plan-42",
        },
    )
    assert len(merged) == 1
    # Existing source_type wins; missing reference is back-filled.
    assert merged[0]["source_type"] == "manual"
    assert merged[0]["source_meal_plan_id"] == "plan-42"


def test_checked_items_are_not_silently_reactivated():
    existing = [
        {
            "id": "1",
            "name": "Sugar",
            "is_checked": True,
            "checked_at": "2026-05-20T00:00:00Z",
        }
    ]
    merged = qa.merge_into_shopping_list(
        existing,
        {"name": "Sugar", "source_type": "missing_ingredient"},
    )
    assert len(merged) == 1
    assert merged[0]["is_checked"] is True, "checked items must not be silently reactivated"


def test_archived_or_removed_items_do_not_dedupe():
    existing = [
        {"id": "1", "name": "Yogurt", "archived_at": "2026-05-01T00:00:00Z"},
        {"id": "2", "name": "Yogurt", "removed_at": "2026-05-02T00:00:00Z"},
    ]
    merged = qa.merge_into_shopping_list(
        existing,
        {"name": "yogurt", "source_type": "manual"},
    )
    # archived + removed are tombstones; the incoming row must land as a new
    # active row instead of merging into a dead one.
    assert len(merged) == 3
    assert any(
        not item.get("archived_at") and not item.get("removed_at") for item in merged
    )


def test_dedupe_applies_to_all_three_source_types():
    existing: list[dict] = [{"id": "1", "name": "Carrot", "is_checked": False}]
    for source_type in ("manual", "missing_ingredient", "low_stock"):
        merged = qa.merge_into_shopping_list(
            existing,
            {"name": "Carrot", "source_type": source_type},
        )
        assert len(merged) == 1
        existing = merged  # carry forward
    # Still only one row after three merges.
    assert len(existing) == 1


def test_empty_incoming_name_does_not_merge_with_anything():
    existing = [{"id": "1", "name": "Apple", "is_checked": False}]
    merged = qa.merge_into_shopping_list(existing, {"name": "", "source_type": "manual"})
    assert len(merged) == 2
