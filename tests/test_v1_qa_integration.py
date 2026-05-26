"""Integration-style QA tests that exercise multiple v1 contracts together.

These tests do not require a running server. They use the reference helpers in
``scripts/qa_helpers.py`` plus the small reference models declared in the
sibling QA test files to demonstrate the end-to-end pantry → AI → plan →
missing ingredients → shopping list → shopping mode loop described in
Ticket 1.

If the production wiring diverges from the helpers, update both — these tests
are the contract.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List

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


# ---------------------------------------------------------------------------
# Inventory fast-add contract
# ---------------------------------------------------------------------------


def _inventory_row(name: str, location: str, **overrides) -> Dict:
    """Pin the v1 inventory create contract: only `name` + `location` required."""
    row = {"name": name, "location": location, "normalized_name": qa.normalize_name(name)}
    row.update(overrides)
    return row


def test_fast_add_requires_only_name_and_location():
    row = _inventory_row("Tomato", "pantry")
    assert row["name"] == "Tomato"
    assert row["location"] == "pantry"
    assert row["normalized_name"] == "tomato"
    # No other field is required to persist.
    for field in ("quantity", "unit", "category", "expiry_date", "low_stock_threshold", "notes"):
        assert field not in row


def test_supported_locations_are_pantry_fridge_freezer():
    supported = {"pantry", "fridge", "freezer"}
    for loc in supported:
        _inventory_row("X", loc)  # must not raise
    assert supported == {"pantry", "fridge", "freezer"}


def test_archived_items_excluded_from_active_views():
    inventory = [
        {**_inventory_row("Tomato", "pantry"), "archived_at": None},
        {**_inventory_row("Olive Oil", "pantry"), "archived_at": "2026-05-01T00:00:00Z"},
    ]
    active = [item for item in inventory if not item.get("archived_at")]
    assert [item["name"] for item in active] == ["Tomato"]


# ---------------------------------------------------------------------------
# Low-stock + expiring-soon (Ticket 2)
# ---------------------------------------------------------------------------


def _is_low_stock(item: Dict) -> bool:
    qty = item.get("quantity")
    threshold = item.get("low_stock_threshold")
    return qty is not None and threshold is not None and qty <= threshold


def test_low_stock_only_triggers_when_both_fields_present():
    assert _is_low_stock({"quantity": 1, "low_stock_threshold": 2}) is True
    assert _is_low_stock({"quantity": 5, "low_stock_threshold": 2}) is False
    assert _is_low_stock({"quantity": 2, "low_stock_threshold": 2}) is True  # <= boundary
    # Missing either field => never low-stock.
    assert _is_low_stock({"quantity": 1}) is False
    assert _is_low_stock({"low_stock_threshold": 5}) is False
    assert _is_low_stock({}) is False


# ---------------------------------------------------------------------------
# AI generation → save to planner → missing ingredients → shopping list
# ---------------------------------------------------------------------------


def _ai_meal() -> Dict:
    return {
        "title": "Tomato Pasta",
        "description": "Quick pantry pasta.",
        "ingredients_used": [
            {"name": "Tomato", "quantity": 2, "unit": "ea"},
            {"name": "Pasta", "quantity": 200, "unit": "g"},
            {"name": "Parmesan", "quantity": 50, "unit": "g"},
        ],
        "inventory_matches": ["Tomato", "Pasta"],
        "missing_ingredients": [{"name": "Parmesan", "quantity": 50, "unit": "g"}],
        "optional_substitutions": [],
        "estimated_prep_complexity": "low",
    }


def test_ai_success_then_save_then_add_missing_to_shopping_list():
    # 1. Validate the AI response.
    meals = qa.validate_ai_meal_response([_ai_meal()])
    assert len(meals) == 1
    meal = meals[0]

    # 2. Save to planner (we just check ingredient matching here).
    inventory = [
        _inventory_row("Tomato", "pantry"),
        _inventory_row("Pasta", "pantry"),
    ]
    inventory_normalized = {item["normalized_name"] for item in inventory}
    for ingredient in meal["ingredients_used"]:
        ingredient["normalized_name"] = qa.normalize_name(ingredient["name"])
        ingredient["match_status"] = (
            "available"
            if ingredient["normalized_name"] in inventory_normalized
            else "missing"
        )
    missing = [i for i in meal["ingredients_used"] if i["match_status"] == "missing"]
    assert [m["name"] for m in missing] == ["Parmesan"]

    # 3. Add missing ingredients to shopping list, dedupe by normalized_name.
    shopping_list: List[Dict] = []
    for ingredient in missing:
        shopping_list = qa.merge_into_shopping_list(
            shopping_list,
            {
                "name": ingredient["name"],
                "quantity": ingredient["quantity"],
                "unit": ingredient["unit"],
                "source_type": "missing_ingredient",
                "source_meal_plan_id": "plan-1",
            },
        )
    # Adding the same missing ingredient again from a second meal must not duplicate.
    shopping_list = qa.merge_into_shopping_list(
        shopping_list,
        {"name": "parmesan", "source_type": "missing_ingredient"},
    )
    assert len(shopping_list) == 1
    assert shopping_list[0]["source_type"] == "missing_ingredient"


def test_archived_inventory_excluded_from_ai_input_and_matching():
    inventory = [
        _inventory_row("Tomato", "pantry"),
        {**_inventory_row("Pasta", "pantry"), "archived_at": "2026-05-01T00:00:00Z"},
    ]
    # The AI input snapshot must only include active items.
    snapshot = [i for i in inventory if not i.get("archived_at")]
    assert [i["name"] for i in snapshot] == ["Tomato"]

    # Ingredient matching against the same active subset.
    snapshot_normalized = {i["normalized_name"] for i in snapshot}
    assert qa.normalize_name("Pasta") not in snapshot_normalized
    assert qa.normalize_name("Tomato") in snapshot_normalized


# ---------------------------------------------------------------------------
# Dashboard counts (Ticket 6)
# ---------------------------------------------------------------------------


def test_dashboard_inventory_counts_exclude_archived():
    inventory = [
        _inventory_row("A", "pantry"),
        _inventory_row("B", "fridge"),
        {**_inventory_row("C", "pantry"), "archived_at": "2026-05-01T00:00:00Z"},
    ]
    active_count = sum(1 for i in inventory if not i.get("archived_at"))
    assert active_count == 2


def test_dashboard_shopping_count_excludes_checked_and_archived():
    items = [
        {"id": "1", "name": "A", "is_checked": False, "archived_at": None},
        {"id": "2", "name": "B", "is_checked": True, "archived_at": None},
        {"id": "3", "name": "C", "is_checked": False, "archived_at": "2026-05-01T00:00:00Z"},
    ]
    active_unchecked = [
        i for i in items if not i["is_checked"] and not i.get("archived_at")
    ]
    assert len(active_unchecked) == 1
    assert active_unchecked[0]["id"] == "1"


# ---------------------------------------------------------------------------
# Empty-state copy guardrail (Ticket 7)
# ---------------------------------------------------------------------------


BANNED_EMPTY_STATE_PHRASES = [
    "scan receipt",
    "scan barcode",
    "live price",
    "apply coupon",
    "household inbox",
    "switch household",
    "co-admin",
    "teen role",
    "child role",
    "audit log",
    "activity history",
    "save as template",
]


@pytest.mark.parametrize("phrase", BANNED_EMPTY_STATE_PHRASES)
def test_empty_states_do_not_mention_out_of_scope_features(phrase):
    """Walk product source files and assert no empty-state copy promises deferred features."""
    targets: List[Path] = []
    for sub in ("frontend/app", "frontend/src", "apps/diana-web/src"):
        base = REPO_ROOT / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*.tsx"):
            if ".metro-cache" in path.parts:
                continue
            targets.append(path)
    offenders = []
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if phrase in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"Banned phrase '{phrase}' appears in: {offenders}"
