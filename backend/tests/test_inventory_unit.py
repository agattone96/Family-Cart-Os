"""Unit tests for inventory normalization, low-stock, and expiring-soon logic.

These pure-function tests do not require a database connection. They verify
the behaviors mandated by ticket 1 (POR-1: inventory tracking) and protect
the ingredient-matching contract that downstream features depend on.
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ast
import os
import re

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

from backend import server
from backend.server import (
    DEFAULT_EXPIRING_SOON_DAYS,
    HouseholdProfile,
    InventoryItemCreate,
    InventoryItemUpdate,
    VALID_LOCATIONS,
    annotate_inventory_item,
    coerce_expiry_date,
    is_expiring_soon,
    is_low_stock,
    normalize_inventory_name,
    normalize_location,
)


# ─── normalize_inventory_name ────────────────────────────────────────────────


class TestNormalizeInventoryName:
    def test_lowercases_and_trims_whitespace(self):
        assert normalize_inventory_name("  Greek Yogurt  ") == "greek yogurt"

    def test_strips_punctuation(self):
        assert normalize_inventory_name("Greek-Yogurt!!") == "greek yogurt"

    def test_collapses_repeated_whitespace(self):
        assert normalize_inventory_name("greek\t\tyogurt\n  cup") == "greek yogurt cup"

    def test_handles_none_or_empty(self):
        assert normalize_inventory_name(None) == ""
        assert normalize_inventory_name("") == ""
        assert normalize_inventory_name("   ") == ""

    def test_keeps_digits(self):
        assert normalize_inventory_name("2% Milk") == "2 milk"

    def test_unicode_punctuation_dropped(self):
        assert normalize_inventory_name("crème brûlée") == "cr me br l e"

    def test_idempotent(self):
        once = normalize_inventory_name("Sour Cream (16oz)")
        assert normalize_inventory_name(once) == once
        # And consistent across casings/forms used by meals + shopping list.
        assert normalize_inventory_name("Sour CREAM 16OZ") == once


# ─── location normalization ──────────────────────────────────────────────────


class TestNormalizeLocation:
    def test_only_supports_pantry_fridge_freezer(self):
        for loc in VALID_LOCATIONS:
            assert normalize_location(loc) == loc

    def test_uppercase_normalized(self):
        assert normalize_location("PANTRY") == "pantry"
        assert normalize_location("Fridge") == "fridge"

    def test_unknown_falls_back_to_pantry(self):
        assert normalize_location("garage") == "pantry"
        assert normalize_location("garage", fallback="freezer") == "freezer"

    def test_none_uses_fallback(self):
        assert normalize_location(None) == "pantry"
        assert normalize_location(None, fallback="fridge") == "fridge"


# ─── low-stock logic ─────────────────────────────────────────────────────────


class TestLowStockLogic:
    def test_triggers_when_quantity_at_or_below_threshold(self):
        assert is_low_stock(0, 2) is True
        assert is_low_stock(1, 2) is True
        assert is_low_stock(2, 2) is True

    def test_skips_when_quantity_above_threshold(self):
        assert is_low_stock(3, 2) is False

    def test_requires_both_values(self):
        assert is_low_stock(None, 2) is False
        assert is_low_stock(2, None) is False
        assert is_low_stock(None, None) is False

    def test_coerces_numeric_strings(self):
        # Stored fields may come back as strings from clients.
        assert is_low_stock("1", "3") is True
        assert is_low_stock("4", "3") is False

    def test_invalid_inputs_are_safe(self):
        assert is_low_stock("notanumber", 2) is False


# ─── expiring-soon logic ─────────────────────────────────────────────────────


class TestExpiringSoonLogic:
    def test_within_window_flags_true(self):
        today = date.today()
        for offset in (-3, 0, 1, 3, 7):
            iso = (today + timedelta(days=offset)).isoformat()
            assert is_expiring_soon(iso, 7, today=today) is True, offset

    def test_outside_window_flags_false(self):
        today = date.today()
        iso = (today + timedelta(days=8)).isoformat()
        assert is_expiring_soon(iso, 7, today=today) is False

    def test_window_is_configurable(self):
        today = date.today()
        iso = (today + timedelta(days=14)).isoformat()
        assert is_expiring_soon(iso, 7, today=today) is False
        assert is_expiring_soon(iso, 21, today=today) is True

    def test_missing_expiry_never_flags(self):
        assert is_expiring_soon(None, 7) is False
        assert is_expiring_soon("", 7) is False

    def test_invalid_strings_do_not_crash(self):
        assert is_expiring_soon("not-a-date", 7) is False

    def test_accepts_datetime_or_date(self):
        today = date.today()
        assert is_expiring_soon(today + timedelta(days=1), 7, today=today) is True
        assert is_expiring_soon(datetime.now(timezone.utc) + timedelta(days=1), 7) is True


# ─── annotate_inventory_item ─────────────────────────────────────────────────


class TestAnnotateInventoryItem:
    def test_adds_flags(self):
        item = {
            "name": "Milk",
            "quantity": 1,
            "low_stock_threshold": 2,
            "expiry_date": (date.today() + timedelta(days=2)).isoformat(),
        }
        annotated = annotate_inventory_item(item, DEFAULT_EXPIRING_SOON_DAYS)
        assert annotated["is_low_stock"] is True
        assert annotated["is_expiring_soon"] is True

    def test_no_flags_when_data_missing(self):
        item = {"name": "Bread"}
        annotated = annotate_inventory_item(item, DEFAULT_EXPIRING_SOON_DAYS)
        assert annotated["is_low_stock"] is False
        assert annotated["is_expiring_soon"] is False


# ─── coerce_expiry_date ──────────────────────────────────────────────────────


class TestCoerceExpiryDate:
    def test_passthrough_for_none_or_empty(self):
        assert coerce_expiry_date(None) is None
        assert coerce_expiry_date("") is None

    def test_iso_date(self):
        assert coerce_expiry_date("2026-05-10") == date(2026, 5, 10)

    def test_iso_datetime_truncated(self):
        assert coerce_expiry_date("2026-05-10T12:34:56Z") == date(2026, 5, 10)

    def test_invalid_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            coerce_expiry_date("notadate")
        assert exc.value.status_code == 400


# ─── pydantic models for fast-add path ───────────────────────────────────────


class TestInventoryItemCreate:
    def test_requires_only_name_and_location(self):
        item = InventoryItemCreate(name="Bread")
        # Location defaults to pantry for fast-add convenience.
        assert item.location == "pantry"
        # Every other field defaults to None.
        assert item.quantity is None
        assert item.unit is None
        assert item.category is None
        assert item.expiry_date is None
        assert item.low_stock_threshold is None
        assert item.notes is None

    def test_accepts_full_payload(self):
        item = InventoryItemCreate(
            name="Sourdough",
            location="fridge",
            quantity=2,
            unit="loaves",
            category="bakery",
            expiry_date="2026-06-01",
            low_stock_threshold=1,
            notes="from the corner bakery",
        )
        assert item.location == "fridge"
        assert item.quantity == 2
        assert item.unit == "loaves"
        assert item.category == "bakery"
        assert item.notes == "from the corner bakery"


class TestInventoryItemUpdate:
    def test_all_fields_optional(self):
        update = InventoryItemUpdate()
        # exclude_unset means nothing is sent when no fields are passed.
        assert update.dict(exclude_unset=True) == {}

    def test_supports_archive_flag(self):
        update = InventoryItemUpdate(archived=True)
        assert update.dict(exclude_unset=True) == {"archived": True}


# ─── HouseholdProfile defaults for inventory settings ────────────────────────


class TestHouseholdProfileDefaults:
    def test_inventory_settings_have_sensible_defaults(self):
        profile = HouseholdProfile(name="Demo").dict()
        assert profile["expiring_soon_days"] == DEFAULT_EXPIRING_SOON_DAYS
        assert profile["last_inventory_location"] == "pantry"


# ─── schema definition ──────────────────────────────────────────────────────


class TestInventorySchema:
    """Static checks against init_schema so migrations stay in sync with the spec."""

    @pytest.fixture(scope="class")
    def server_source(self):
        return Path(server.__file__).read_text()

    @pytest.mark.parametrize(
        "column",
        [
            "normalized_name",
            "category",
            "expiry_date",
            "low_stock_threshold",
            "notes",
            "archived_at",
            "updated_at",
        ],
    )
    def test_inventory_columns_declared(self, server_source, column):
        # Each new inventory column should exist in the CREATE TABLE definition.
        match = re.search(
            r"CREATE TABLE IF NOT EXISTS inventory_items \(([\s\S]*?)\);",
            server_source,
        )
        assert match, "inventory_items CREATE TABLE not found"
        assert column in match.group(1), f"Missing column {column} in schema"

    def test_existing_table_migration_adds_columns(self, server_source):
        # ALTER TABLE statements keep older databases in sync (idempotent).
        for column in (
            "normalized_name",
            "category",
            "expiry_date",
            "low_stock_threshold",
            "notes",
            "archived_at",
            "updated_at",
        ):
            assert (
                f"ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS {column}"
                in server_source
            ), f"Missing migration for {column}"

    def test_active_inventory_query_excludes_archived(self, server_source):
        assert "archived_at IS NULL" in server_source

    def test_dashboard_endpoint_exists(self, server_source):
        tree = ast.parse(server_source)
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
        }
        assert "get_inventory_dashboard" in names
        assert "archive_inventory_item" in names
