"""Unit tests for the Family Cart OS v1 module.

These exercise the pure helpers, AI output validation, ingredient
matching, shopping-list deduplication, dashboard aggregation, and the
out-of-scope guardrail check.  None of them require a database — they
satisfy the Ticket 8 acceptance criterion that the MVP core loop is
verifiable without a live environment.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

from backend import family_cart


# ---------------------------------------------------------------------------
# normalized_name (Tickets 2, 3, 4, 5)
# ---------------------------------------------------------------------------


class TestNormalizedName:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Olive Oil", "olive oil"),
            ("  Olive   Oil!  ", "olive oil"),
            ("Olive-Oil", "olive oil"),
            ("OLIVE oil", "olive oil"),
            ("", ""),
            ("Salt & Pepper", "salt pepper"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert family_cart.normalized_name(raw) == expected

    def test_none_input(self):
        assert family_cart.normalized_name(None) == ""


# ---------------------------------------------------------------------------
# Inventory flagging helpers (Ticket 2)
# ---------------------------------------------------------------------------


class TestInventoryFlags:
    def test_is_low_stock_when_at_threshold(self):
        assert family_cart.is_low_stock(2, 2)

    def test_is_low_stock_below_threshold(self):
        assert family_cart.is_low_stock(1, 2)

    def test_is_low_stock_above_threshold(self):
        assert not family_cart.is_low_stock(5, 2)

    def test_is_low_stock_handles_missing_values(self):
        assert not family_cart.is_low_stock(None, 2)
        assert not family_cart.is_low_stock(2, None)

    def test_is_expiring_soon_within_window(self):
        today = datetime(2026, 5, 26, tzinfo=timezone.utc)
        tomorrow = (today + timedelta(days=1)).isoformat()
        assert family_cart.is_expiring_soon(tomorrow, today=today)

    def test_is_expiring_soon_outside_window(self):
        today = datetime(2026, 5, 26, tzinfo=timezone.utc)
        far_future = (today + timedelta(days=30)).isoformat()
        assert not family_cart.is_expiring_soon(far_future, today=today)

    def test_is_expiring_soon_ignores_missing_date(self):
        assert not family_cart.is_expiring_soon(None)

    def test_is_expiring_soon_handles_bad_format(self):
        assert not family_cart.is_expiring_soon("not-a-date")


# ---------------------------------------------------------------------------
# Ingredient matching (Tickets 3, 4)
# ---------------------------------------------------------------------------


class TestIngredientMatching:
    def test_matches_by_normalized_name(self):
        inventory = [
            {"id": "1", "name": "Olive Oil", "normalized_name": "olive oil"},
            {"id": "2", "name": "Onions", "normalized_name": "onions"},
        ]
        match = family_cart.match_ingredient_to_inventory("olive-oil", inventory)
        assert match is not None
        assert match["id"] == "1"

    def test_skips_archived_inventory(self):
        inventory = [
            {
                "id": "1",
                "name": "Olive Oil",
                "normalized_name": "olive oil",
                "archived_at": "2026-05-25T00:00:00+00:00",
            }
        ]
        assert family_cart.match_ingredient_to_inventory("Olive Oil", inventory) is None

    def test_no_match_returns_none(self):
        assert family_cart.match_ingredient_to_inventory("foo", []) is None

    def test_empty_ingredient_name_returns_none(self):
        inventory = [{"id": "1", "name": "X", "normalized_name": "x"}]
        assert family_cart.match_ingredient_to_inventory("", inventory) is None


# ---------------------------------------------------------------------------
# Shopping-list deduplication (Tickets 4, 5)
# ---------------------------------------------------------------------------


class TestDedup:
    def test_inserts_new_items(self):
        to_insert, to_merge = family_cart.dedup_shopping_items(
            existing=[],
            incoming=[{"name": "Bread"}, {"name": "Milk"}],
        )
        assert len(to_insert) == 2
        assert to_merge == []
        assert {row["normalized_name"] for row in to_insert} == {"bread", "milk"}

    def test_merges_against_existing(self):
        existing = [{"name": "Bread", "normalized_name": "bread"}]
        to_insert, to_merge = family_cart.dedup_shopping_items(
            existing=existing,
            incoming=[{"name": "bread"}, {"name": "Milk"}],
        )
        assert [row["normalized_name"] for row in to_insert] == ["milk"]
        assert len(to_merge) == 1
        assert to_merge[0]["existing"]["normalized_name"] == "bread"

    def test_deduplicates_within_batch(self):
        to_insert, to_merge = family_cart.dedup_shopping_items(
            existing=[],
            incoming=[{"name": "Bread"}, {"name": "BREAD"}, {"name": "bread"}],
        )
        assert len(to_insert) == 1
        assert len(to_merge) == 2

    def test_ignores_archived_existing(self):
        existing = [
            {
                "name": "Bread",
                "normalized_name": "bread",
                "archived_at": "2026-05-25T00:00:00+00:00",
            }
        ]
        to_insert, to_merge = family_cart.dedup_shopping_items(
            existing=existing,
            incoming=[{"name": "Bread"}],
        )
        assert len(to_insert) == 1
        assert to_merge == []


# ---------------------------------------------------------------------------
# AI output validation (Ticket 3)
# ---------------------------------------------------------------------------


class TestValidateAIOutput:
    def _valid_meal(self):
        return {
            "title": "Tomato Soup",
            "description": "A soup",
            "ingredients_used": [],
            "missing_ingredients": [],
            "estimated_prep_complexity": "easy",
        }

    def test_accepts_valid_payload(self):
        payload = {"meals": [self._valid_meal()]}
        assert family_cart.validate_ai_meal_output(payload) is payload

    def test_rejects_non_dict(self):
        with pytest.raises(family_cart.AIValidationError):
            family_cart.validate_ai_meal_output("not json")

    def test_rejects_empty_meals(self):
        with pytest.raises(family_cart.AIValidationError):
            family_cart.validate_ai_meal_output({"meals": []})

    def test_rejects_missing_keys(self):
        meal = self._valid_meal()
        del meal["title"]
        with pytest.raises(family_cart.AIValidationError):
            family_cart.validate_ai_meal_output({"meals": [meal]})

    def test_rejects_blank_title(self):
        meal = self._valid_meal()
        meal["title"] = "   "
        with pytest.raises(family_cart.AIValidationError):
            family_cart.validate_ai_meal_output({"meals": [meal]})

    def test_rejects_wrong_ingredients_type(self):
        meal = self._valid_meal()
        meal["ingredients_used"] = "not a list"
        with pytest.raises(family_cart.AIValidationError):
            family_cart.validate_ai_meal_output({"meals": [meal]})


# ---------------------------------------------------------------------------
# Stub AI provider (Ticket 3)
# ---------------------------------------------------------------------------


class TestStubAIProvider:
    def test_stub_returns_structured_output(self):
        provider = family_cart.StubAIProvider()
        payload = {
            "pantry_snapshot": [
                {"name": "Onions"},
                {"name": "Tomatoes"},
                {"name": "Pasta"},
            ],
            "meal_count": 2,
        }
        output = provider.generate_meal_ideas(payload)
        family_cart.validate_ai_meal_output(output)
        assert len(output["meals"]) == 2
        # ingredient.normalized_name is populated so the meal can be
        # matched against inventory without re-normalising on the client.
        first_ingredient = output["meals"][0]["ingredients_used"][0]
        assert first_ingredient["normalized_name"] == "onions"


# ---------------------------------------------------------------------------
# Dashboard aggregation (Ticket 6)
# ---------------------------------------------------------------------------


class TestDashboard:
    def test_counts_low_stock_expiring_and_missing(self):
        today = datetime(2026, 5, 26, tzinfo=timezone.utc)
        inventory = [
            {
                "id": "i1",
                "name": "Bread",
                "quantity": 1,
                "low_stock_threshold": 2,
                "expiry_date": (today + timedelta(days=2)).date().isoformat(),
            },
            {
                "id": "i2",
                "name": "Cheese",
                "quantity": 5,
                "low_stock_threshold": 2,
                "expiry_date": None,
            },
            {
                "id": "i3",
                "name": "Old item",
                "archived_at": today.isoformat(),
                "quantity": 0,
                "low_stock_threshold": 1,
            },
        ]
        meal_plans = [
            {
                "id": "m1",
                "planned_for": "2026-05-26",
                "slot": "dinner",
                "title": "Pasta",
                "ingredients": [
                    {"name": "Pasta", "is_available": True},
                    {"name": "Onion", "is_available": False},
                ],
            },
            {
                "id": "m2",
                "planned_for": "2026-05-27",
                "slot": "dinner",
                "title": "Soup",
                "ingredients": [{"name": "Broth", "is_available": False}],
            },
        ]
        shopping_items = [
            {"id": "s1", "status": "pending"},
            {"id": "s2", "status": "checked"},
            {"id": "s3", "status": "checked", "archived_at": today.isoformat()},
        ]
        payload = family_cart.build_dashboard_payload(
            inventory=inventory,
            meal_plans=meal_plans,
            shopping_list_items=shopping_items,
            today=today,
        )
        assert payload["totals"]["inventory_items"] == 2  # archived excluded
        assert payload["totals"]["low_stock"] == 1
        assert payload["totals"]["expiring_soon"] == 1
        assert len(payload["today_meals"]) == 1
        assert payload["today_meals"][0]["id"] == "m1"
        assert payload["missing_ingredient_count"] == 2
        assert payload["shopping_list_count"] == 2  # archived excluded
        assert {a["id"] for a in payload["quick_actions"]} == {
            "add_pantry_item",
            "generate_meal_ideas",
            "view_meal_plan",
            "open_shopping_list",
        }


# ---------------------------------------------------------------------------
# Scope guardrail (Ticket 8)
# ---------------------------------------------------------------------------


class TestScopeGuardrails:
    def test_clean_copy_passes(self):
        copy = (
            "Welcome to Family Cart. Track pantry, fridge and freezer. "
            "Generate AI meal ideas grounded in your inventory."
        )
        assert family_cart.assert_no_out_of_scope_features(copy) == []

    def test_flags_out_of_scope_terms(self):
        copy = (
            "Coming soon: receipt scan, coupons, calorie tracking and "
            "an approval inbox for kids."
        )
        flagged = family_cart.assert_no_out_of_scope_features(copy)
        assert "receipt scan" in flagged
        assert "coupons" in flagged
        assert "calorie tracking" in flagged
        # Substring matches catch the "approval inbox" wording.
        assert any("approval" in term for term in flagged)


# ---------------------------------------------------------------------------
# Router shape (Ticket 7)
# ---------------------------------------------------------------------------


class TestRouter:
    def test_router_registers_v1_routes(self):
        router = family_cart.build_router()
        paths = {route.path for route in router.routes}
        required = {
            "/api/v1/households",
            "/api/v1/households/me",
            "/api/v1/inventory-items",
            "/api/v1/inventory-items/{item_id}",
            "/api/v1/ai/meal-ideas",
            "/api/v1/meal-plans",
            "/api/v1/meal-plans/{plan_id}/missing-to-shopping-list",
            "/api/v1/meal-ingredients/{ingredient_id}",
            "/api/v1/shopping-list",
            "/api/v1/shopping-list/items",
            "/api/v1/shopping-list/items/{item_id}/check",
            "/api/v1/shopping-list/finish",
            "/api/v1/food-preferences",
            "/api/v1/dashboard",
        }
        missing = required - paths
        assert not missing, f"Router missing routes: {missing}"


# ---------------------------------------------------------------------------
# Schema contract sanity (Ticket 7 — required household_id columns)
# ---------------------------------------------------------------------------


class TestSchemaSqlContract:
    """Light-weight smoke test on the SCHEMA_SQL string.

    Pytest still skips real DB I/O — we just inspect the literal SQL so
    a future refactor cannot silently drop the household_id columns or
    the canonical table names.
    """

    @pytest.mark.parametrize(
        "table",
        [
            "households",
            "household_members",
            "fc_inventory_items",
            "fc_ai_generations",
            "fc_meal_plans",
            "fc_meal_ingredients",
            "fc_shopping_lists",
            "fc_shopping_list_items",
            "fc_user_food_preferences",
        ],
    )
    def test_table_defined(self, table):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in family_cart.SCHEMA_SQL

    @pytest.mark.parametrize(
        "table",
        [
            "fc_inventory_items",
            "fc_ai_generations",
            "fc_meal_plans",
            "fc_shopping_lists",
            "fc_shopping_list_items",
            "fc_user_food_preferences",
        ],
    )
    def test_household_id_is_required(self, table):
        # Walk the SQL line by line; any household_id declaration on a
        # scoped table must say NOT NULL.
        in_table = False
        for line in family_cart.SCHEMA_SQL.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"CREATE TABLE IF NOT EXISTS {table}"):
                in_table = True
                continue
            if in_table and stripped.startswith(");"):
                pytest.fail(f"{table} has no household_id column")
            if in_table and stripped.startswith("household_id"):
                assert "NOT NULL" in stripped, f"{table}.household_id must be NOT NULL"
                return
        pytest.fail(f"{table} not found in schema")

    def test_archived_at_soft_delete_present(self):
        assert "archived_at TIMESTAMPTZ" in family_cart.SCHEMA_SQL

    def test_role_enum_only_owner_member(self):
        # The CHECK constraint isn't there, but the only seeded roles
        # come from code — make sure the codebase never references the
        # five-role enum that v1 explicitly out-scopes.
        for forbidden in ("co_admin", "co-admin", "teen", "child"):
            assert forbidden not in family_cart.SCHEMA_SQL


# ---------------------------------------------------------------------------
# Constants (Ticket 1 — keep the canonical enums stable)
# ---------------------------------------------------------------------------


class TestConstants:
    def test_locations_canonical(self):
        assert family_cart.LOCATIONS == ("pantry", "fridge", "freezer")

    def test_meal_slots_canonical(self):
        assert family_cart.MEAL_SLOTS == (
            "breakfast",
            "lunch",
            "dinner",
            "snack",
            "other",
        )

    def test_shopping_sources_canonical(self):
        assert family_cart.SHOPPING_SOURCES == (
            "manual",
            "missing_ingredient",
            "low_stock",
        )

    def test_household_roles_only_owner_member(self):
        assert family_cart.HOUSEHOLD_ROLES == ("owner", "member")
