"""Family Cart OS v1 — Pantry + AI Meal Planning MVP

This module implements the canonical Family Cart OS data model and API
surface on top of the existing FastAPI app.  Everything lives in a
dedicated module so the legacy "Diana's Pantry Plan" routes remain
untouched.

Implements the eight MVP tickets:

* Ticket 1 – Pantry + AI meal planning MVP (umbrella).
* Ticket 2 – Inventory (pantry / fridge / freezer) with archive +
  ``normalized_name``.
* Ticket 3 – AI meal-idea generation grounded in the live pantry, with
  ``ai_generations`` audit table and a swappable provider.
* Ticket 4 – Weekly meal planner with manual + AI-saved meals and
  per-ingredient ``is_available`` matching.
* Ticket 5 – One active shopping list per household with
  shopping-mode-friendly endpoints.
* Ticket 6 – Dashboard aggregates (counts only — no junk drawer).
* Ticket 7 – App shell / household scope.  ``household_id`` is required
  on every household-scoped table and is enforced by middleware via
  :func:`household_scope`.
* Ticket 8 – End-to-end QA contract: pure helpers exposed (``normalized_name``,
  ``validate_ai_meal_output`` …) so the QA checklist can be exercised
  without a database.

Hard guardrails honoured (see ``docs/developer/family-cart-architecture.md``):

* ``household_members.role`` enum is **only** ``owner`` / ``member`` — the
  five-role system is intentionally out of scope.
* No request approval flow, templates, activity history, receipt /
  barcode scanning, live pricing, coupons, delivery, nutrition tracking,
  budget tracking or multi-household switching UI is exposed here.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / enums
# ---------------------------------------------------------------------------

LOCATIONS: Tuple[str, ...] = ("pantry", "fridge", "freezer")
MEAL_SLOTS: Tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack", "other")
MEAL_SOURCES: Tuple[str, ...] = ("manual", "ai_generated")
SHOPPING_SOURCES: Tuple[str, ...] = ("manual", "missing_ingredient", "low_stock")
HOUSEHOLD_ROLES: Tuple[str, ...] = ("owner", "member")
GENERATION_TYPES: Tuple[str, ...] = ("meal_ideas", "weekly_plan", "recipe_detail")
GENERATION_STATUSES: Tuple[str, ...] = ("pending", "completed", "failed")

#: Hard scope guardrails — these strings must never appear in v1 UI copy.
#: Used by :func:`assert_no_out_of_scope_features` so QA reviewers can run
#: the check programmatically against rendered HTML or copy bundles.
OUT_OF_SCOPE_TERMS: Tuple[str, ...] = (
    "approval inbox",
    "request approval",
    "co-admin",
    "teen role",
    "child role",
    "templates",
    "activity history",
    "audit log",
    "receipt scan",
    "barcode scan",
    "live pricing",
    "coupons",
    "delivery integration",
    "calorie tracking",
    "macro tracking",
    "budget tracking",
    "multi-household switcher",
)


# ---------------------------------------------------------------------------
# Pure helpers — exported so they can be unit-tested without a database
# ---------------------------------------------------------------------------

_NORMALIZE_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalized_name(name: str) -> str:
    """Return the canonical match key for an ingredient or inventory item.

    Lower-cased, ASCII-fold-ish, punctuation removed, whitespace collapsed.
    Used for matching ``meal_ingredients`` to ``inventory_items`` and for
    deduplicating shopping list entries (Tickets 2, 3, 4, 5).
    """

    if name is None:
        return ""
    cleaned = _NORMALIZE_NON_ALNUM.sub(" ", str(name).strip().lower())
    return " ".join(cleaned.split())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_low_stock(quantity: Optional[float], threshold: Optional[float]) -> bool:
    """Inventory item flagged as low-stock when quantity <= threshold.

    Items without a quantity or threshold are never flagged — matches the
    "no false warnings" requirement in the architecture notes.
    """

    if quantity is None or threshold is None:
        return False
    try:
        return float(quantity) <= float(threshold)
    except (TypeError, ValueError):
        return False


def is_expiring_soon(
    expiry_date: Optional[str],
    *,
    today: Optional[datetime] = None,
    window_days: int = 7,
) -> bool:
    """An item with an ``expiry_date`` within ``window_days`` of ``today``."""

    if not expiry_date:
        return False
    now = today or datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(expiry_date)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = (dt - now).total_seconds() / 86400.0
    return -1 <= delta <= window_days


def match_ingredient_to_inventory(
    ingredient_name: str,
    inventory: Iterable[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the inventory row that matches ``ingredient_name`` by
    ``normalized_name``.

    The match is intentionally simple — we do not attempt fuzzy /
    embedding-based matching in v1.  Callers must surface unmatched
    ingredients explicitly so users can override (Ticket 4 acceptance
    criteria).
    """

    key = normalized_name(ingredient_name)
    if not key:
        return None
    for row in inventory:
        if row.get("archived_at"):
            continue
        if normalized_name(row.get("normalized_name") or row.get("name", "")) == key:
            return row
    return None


def dedup_shopping_items(
    existing: Iterable[Dict[str, Any]],
    incoming: Iterable[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Compute the net change to a shopping list when adding ``incoming``.

    Returns a tuple ``(to_insert, to_merge)`` where:

    * ``to_insert`` is the list of new items keyed by ``normalized_name``
      that do not exist in ``existing`` (status active, not archived).
    * ``to_merge`` is the list of incoming items that mapped onto an
      existing active row — the caller decides whether to bump quantity,
      add a note, or simply skip.  Either behaviour satisfies the
      "merge, never duplicate" rule from Tickets 4 and 5.
    """

    by_key: Dict[str, Dict[str, Any]] = {}
    for row in existing:
        if row.get("archived_at"):
            continue
        key = row.get("normalized_name") or normalized_name(row.get("name", ""))
        if key:
            by_key[key] = row

    to_insert: List[Dict[str, Any]] = []
    to_merge: List[Dict[str, Any]] = []
    seen_in_batch: Dict[str, Dict[str, Any]] = {}

    for raw in incoming:
        key = raw.get("normalized_name") or normalized_name(raw.get("name", ""))
        if not key:
            continue
        if key in by_key:
            to_merge.append({"incoming": raw, "existing": by_key[key]})
            continue
        if key in seen_in_batch:
            to_merge.append({"incoming": raw, "existing": seen_in_batch[key]})
            continue
        normalized_row = dict(raw)
        normalized_row["normalized_name"] = key
        seen_in_batch[key] = normalized_row
        to_insert.append(normalized_row)

    return to_insert, to_merge


# ---------------------------------------------------------------------------
# AI provider abstraction (Ticket 3)
# ---------------------------------------------------------------------------


class AIProvider:
    """Abstract AI provider — concrete implementations are wired in
    :func:`get_default_provider`.

    The model_name attribute is persisted on every ``ai_generations`` row
    so a future provider swap is observable in the data without schema
    changes.
    """

    model_name: str = "stub"

    def generate_meal_ideas(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class StubAIProvider(AIProvider):
    """Deterministic provider used when no real LLM key is configured.

    The stub returns one meal idea per pantry item (capped by
    ``meal_count``) and marks every ingredient as available.  It is
    structured-output compliant so the rest of the stack can be exercised
    end-to-end in tests and CI.
    """

    model_name = "stub-meal-ideas-v1"

    def generate_meal_ideas(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        snapshot: List[Dict[str, Any]] = payload.get("pantry_snapshot", []) or []
        meal_count = max(1, int(payload.get("meal_count", 3)))
        meals: List[Dict[str, Any]] = []
        for index, item in enumerate(snapshot[:meal_count]):
            name = item.get("name", f"item {index + 1}")
            meals.append(
                {
                    "title": f"Quick {name} bowl",
                    "description": f"A simple meal centred on {name}.",
                    "ingredients_used": [
                        {
                            "name": name,
                            "normalized_name": normalized_name(name),
                            "is_available": True,
                            "is_required": True,
                        }
                    ],
                    "missing_ingredients": [],
                    "substitutions": [],
                    "estimated_prep_complexity": "easy",
                }
            )
        return {"meals": meals}


_DEFAULT_PROVIDER: Optional[AIProvider] = None


def get_default_provider() -> AIProvider:
    global _DEFAULT_PROVIDER
    if _DEFAULT_PROVIDER is None:
        _DEFAULT_PROVIDER = StubAIProvider()
    return _DEFAULT_PROVIDER


def set_default_provider(provider: AIProvider) -> None:
    global _DEFAULT_PROVIDER
    _DEFAULT_PROVIDER = provider


# ---------------------------------------------------------------------------
# AI output validation (Ticket 3 acceptance: reject malformed responses
# before rendering)
# ---------------------------------------------------------------------------


class AIValidationError(ValueError):
    """Raised when the AI provider returns an output we cannot render."""


_REQUIRED_MEAL_KEYS = {
    "title",
    "description",
    "ingredients_used",
    "missing_ingredients",
    "estimated_prep_complexity",
}


def validate_ai_meal_output(payload: Any) -> Dict[str, Any]:
    """Validate the structured AI response.

    Returns the payload unchanged when valid; raises
    :class:`AIValidationError` otherwise so callers can render an error
    state with retry (the Ticket 3 acceptance criterion).
    """

    if not isinstance(payload, dict):
        raise AIValidationError("AI response must be a JSON object")

    meals = payload.get("meals")
    if not isinstance(meals, list) or not meals:
        raise AIValidationError("AI response must include a non-empty 'meals' list")

    for index, meal in enumerate(meals):
        if not isinstance(meal, dict):
            raise AIValidationError(f"meals[{index}] must be an object")
        missing = _REQUIRED_MEAL_KEYS - set(meal.keys())
        if missing:
            raise AIValidationError(
                f"meals[{index}] missing required fields: {sorted(missing)}"
            )
        if not isinstance(meal["title"], str) or not meal["title"].strip():
            raise AIValidationError(f"meals[{index}].title must be a non-empty string")
        if not isinstance(meal["ingredients_used"], list):
            raise AIValidationError(
                f"meals[{index}].ingredients_used must be a list"
            )
        if not isinstance(meal["missing_ingredients"], list):
            raise AIValidationError(
                f"meals[{index}].missing_ingredients must be a list"
            )
    return payload


# ---------------------------------------------------------------------------
# Dashboard aggregation (Ticket 6)
# ---------------------------------------------------------------------------


def build_dashboard_payload(
    *,
    inventory: List[Dict[str, Any]],
    meal_plans: List[Dict[str, Any]],
    shopping_list_items: List[Dict[str, Any]],
    today: Optional[datetime] = None,
    expiring_window_days: int = 7,
) -> Dict[str, Any]:
    """Build the Ticket 6 dashboard payload from raw rows.

    The dashboard is intentionally capped at five cards: ``totals``,
    ``today_meals``, ``missing_ingredient_count``, ``shopping_list_count``
    and ``quick_actions``.  Adding a sixth card requires explicit product
    sign-off — do not surface delayed features here.
    """

    now = today or datetime.now(timezone.utc)
    today_iso = now.date().isoformat()

    active_inventory = [row for row in inventory if not row.get("archived_at")]
    low_stock = [
        row
        for row in active_inventory
        if is_low_stock(row.get("quantity"), row.get("low_stock_threshold"))
    ]
    expiring = [
        row
        for row in active_inventory
        if is_expiring_soon(
            row.get("expiry_date"), today=now, window_days=expiring_window_days
        )
    ]
    today_meals = [
        meal for meal in meal_plans if (meal.get("planned_for") or "")[:10] == today_iso
    ]
    missing_ingredient_count = sum(
        1
        for meal in meal_plans
        for ingredient in (meal.get("ingredients") or [])
        if ingredient.get("is_available") is False
    )
    active_shopping_items = [
        item
        for item in shopping_list_items
        if item.get("status") != "archived" and not item.get("archived_at")
    ]

    return {
        "totals": {
            "inventory_items": len(active_inventory),
            "low_stock": len(low_stock),
            "expiring_soon": len(expiring),
        },
        "today_meals": today_meals,
        "missing_ingredient_count": missing_ingredient_count,
        "shopping_list_count": len(active_shopping_items),
        "quick_actions": [
            {"id": "add_pantry_item", "label": "Add pantry item", "route": "/inventory/new"},
            {"id": "generate_meal_ideas", "label": "Generate meal ideas", "route": "/ai/meal-ideas"},
            {"id": "view_meal_plan", "label": "View meal plan", "route": "/meal-plan"},
            {"id": "open_shopping_list", "label": "Open shopping list", "route": "/shopping-list"},
        ],
    }


def assert_no_out_of_scope_features(copy_blob: str) -> List[str]:
    """Return any out-of-scope feature terms found in ``copy_blob``.

    Used by the Ticket 8 scope guardrail check — call this against the
    rendered UI copy bundle in CI to fail the build if a delayed feature
    leaks into a user-facing string.
    """

    blob = (copy_blob or "").lower()
    return [term for term in OUT_OF_SCOPE_TERMS if term in blob]


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS households (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by TEXT
);

CREATE TABLE IF NOT EXISTS household_members (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',
  joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (household_id, user_id)
);
CREATE INDEX IF NOT EXISTS household_members_user_idx ON household_members(user_id);

CREATE TABLE IF NOT EXISTS fc_inventory_items (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  location TEXT NOT NULL,
  quantity DOUBLE PRECISION,
  unit TEXT,
  category TEXT,
  expiry_date DATE,
  low_stock_threshold DOUBLE PRECISION,
  notes TEXT,
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS fc_inventory_household_idx ON fc_inventory_items(household_id);
CREATE INDEX IF NOT EXISTS fc_inventory_normalized_idx ON fc_inventory_items(household_id, normalized_name);

CREATE TABLE IF NOT EXISTS fc_ai_generations (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  generation_type TEXT NOT NULL DEFAULT 'meal_ideas',
  status TEXT NOT NULL DEFAULT 'pending',
  model_name TEXT,
  input_snapshot JSONB NOT NULL,
  output_json JSONB,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS fc_ai_generations_household_idx ON fc_ai_generations(household_id);

CREATE TABLE IF NOT EXISTS fc_meal_plans (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  planned_for DATE NOT NULL,
  slot TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  ai_generation_id TEXT REFERENCES fc_ai_generations(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS fc_meal_plans_household_idx ON fc_meal_plans(household_id, planned_for);

CREATE TABLE IF NOT EXISTS fc_meal_ingredients (
  id TEXT PRIMARY KEY,
  meal_plan_id TEXT NOT NULL REFERENCES fc_meal_plans(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  quantity DOUBLE PRECISION,
  unit TEXT,
  inventory_item_id TEXT,
  is_available BOOLEAN NOT NULL DEFAULT FALSE,
  is_required BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS fc_meal_ingredients_plan_idx ON fc_meal_ingredients(meal_plan_id);

CREATE TABLE IF NOT EXISTS fc_shopping_lists (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'active',
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS fc_shopping_lists_household_idx ON fc_shopping_lists(household_id);

CREATE TABLE IF NOT EXISTS fc_shopping_list_items (
  id TEXT PRIMARY KEY,
  shopping_list_id TEXT NOT NULL REFERENCES fc_shopping_lists(id) ON DELETE CASCADE,
  household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  quantity DOUBLE PRECISION,
  unit TEXT,
  category TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  meal_plan_id TEXT REFERENCES fc_meal_plans(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  checked_at TIMESTAMPTZ,
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS fc_shopping_list_items_list_idx ON fc_shopping_list_items(shopping_list_id);
CREATE INDEX IF NOT EXISTS fc_shopping_list_items_household_idx ON fc_shopping_list_items(household_id);

CREATE TABLE IF NOT EXISTS fc_user_food_preferences (
  id TEXT PRIMARY KEY,
  household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
  user_id TEXT,
  likes TEXT[] NOT NULL DEFAULT '{}',
  dislikes TEXT[] NOT NULL DEFAULT '{}',
  allergies TEXT[] NOT NULL DEFAULT '{}',
  diet_style TEXT,
  avoided_ingredients TEXT[] NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS fc_user_food_preferences_household_idx ON fc_user_food_preferences(household_id);
"""


def init_family_cart_schema(conn) -> None:
    """Initialise the Family Cart OS schema on the supplied connection."""

    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class HouseholdCreate(BaseModel):
    name: str = "My Household"


class HouseholdJoin(BaseModel):
    household_id: str


class InventoryItemCreate(BaseModel):
    name: str
    location: str = "pantry"
    quantity: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    expiry_date: Optional[str] = None
    low_stock_threshold: Optional[float] = None
    notes: Optional[str] = None


class InventoryItemUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    expiry_date: Optional[str] = None
    low_stock_threshold: Optional[float] = None
    notes: Optional[str] = None
    archived: Optional[bool] = None


class MealIdeasRequest(BaseModel):
    meal_count: int = 3
    quick_only: bool = False
    use_mostly_what_i_have: bool = False
    prompt: Optional[str] = None
    slot_preferences: List[str] = Field(default_factory=list)


class FoodPreferencesUpdate(BaseModel):
    likes: List[str] = Field(default_factory=list)
    dislikes: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    diet_style: Optional[str] = None
    avoided_ingredients: List[str] = Field(default_factory=list)


class MealIngredientPayload(BaseModel):
    name: str
    normalized_name: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    is_required: bool = True
    is_available: Optional[bool] = None


class MealPlanCreate(BaseModel):
    planned_for: str
    slot: str
    title: str
    description: Optional[str] = None
    source: str = "manual"
    ai_generation_id: Optional[str] = None
    ingredients: List[MealIngredientPayload] = Field(default_factory=list)


class MealIngredientOverride(BaseModel):
    is_available: bool


class ShoppingItemCreate(BaseModel):
    name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    source: str = "manual"
    meal_plan_id: Optional[str] = None


class ShoppingItemCheck(BaseModel):
    checked: bool


# ---------------------------------------------------------------------------
# Household-scoping middleware
# ---------------------------------------------------------------------------

#: Module-level hook so the host app can plug in its own session resolver.
_SESSION_RESOLVER: Optional[Callable[[Optional[str]], Any]] = None
_DB_FACTORY: Optional[Callable[[], Any]] = None


def configure(*, session_resolver: Callable, db_factory: Callable) -> None:
    """Wire the host application's auth resolver + DB connection factory.

    ``session_resolver`` must accept an ``Authorization`` header value and
    return a dict-like session row (with at least ``user_id``).  It may be
    sync or async; the dependency wrapper handles both.
    """

    global _SESSION_RESOLVER, _DB_FACTORY
    _SESSION_RESOLVER = session_resolver
    _DB_FACTORY = db_factory


async def _resolve_session(authorization: Optional[str]) -> Dict[str, Any]:
    if _SESSION_RESOLVER is None:
        raise HTTPException(status_code=500, detail="Family Cart not configured")
    result = _SESSION_RESOLVER(authorization)
    if hasattr(result, "__await__"):
        result = await result  # type: ignore[assignment]
    if not result:
        raise HTTPException(status_code=401, detail="Authentication required")
    return result


def _conn():
    if _DB_FACTORY is None:
        raise HTTPException(status_code=500, detail="Family Cart not configured")
    return _DB_FACTORY()


async def household_scope(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """FastAPI dependency that resolves the active household.

    Enforces:

    * The session is authenticated (HTTP 401 otherwise).
    * The user is a member of at least one household (HTTP 403 otherwise).
    * The active household is the first one they joined — multi-household
      switching UI is out of scope for v1.
    """

    session = await _resolve_session(authorization)
    user_id = session["user_id"]
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT hm.household_id, hm.role
                FROM household_members hm
                WHERE hm.user_id = %s
                ORDER BY hm.joined_at ASC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="No household for user")
    return {
        "session": session,
        "user_id": user_id,
        "household_id": row["household_id"],
        "role": row["role"],
    }


def require_owner(scope: Dict[str, Any]) -> Dict[str, Any]:
    """Helper for routes that mutate household membership."""

    if scope.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")
    return scope


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def build_router() -> APIRouter:
    """Construct the Family Cart OS v1 API router.

    The router is built lazily so unit tests that only exercise the pure
    helpers do not need the host app to be configured.
    """

    router = APIRouter(prefix="/api/v1", tags=["family-cart"])

    async def _ensure_active_list(conn, household_id: str) -> str:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM fc_shopping_lists WHERE household_id = %s AND status = 'active' LIMIT 1",
                (household_id,),
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            new_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO fc_shopping_lists (id, household_id, status, created_at) VALUES (%s, %s, 'active', %s::timestamptz)",
                (new_id, household_id, utc_now_iso()),
            )
        conn.commit()
        return new_id

    # ---------------- Households (Ticket 7) ----------------
    @router.post("/households")
    async def create_household(
        body: HouseholdCreate,
        authorization: Optional[str] = Header(default=None),
    ):
        session = await _resolve_session(authorization)
        user_id = session["user_id"]
        household_id = str(uuid.uuid4())
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO households (id, name, created_at, created_by) VALUES (%s, %s, %s::timestamptz, %s)",
                    (household_id, body.name, utc_now_iso(), user_id),
                )
                cur.execute(
                    "INSERT INTO household_members (id, household_id, user_id, role, joined_at) VALUES (%s, %s, %s, 'owner', %s::timestamptz)",
                    (str(uuid.uuid4()), household_id, user_id, utc_now_iso()),
                )
            conn.commit()
        return {"id": household_id, "name": body.name, "role": "owner"}

    @router.get("/households/me")
    async def my_household(scope: Dict[str, Any] = Depends(household_scope)):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name FROM households WHERE id = %s",
                    (scope["household_id"],),
                )
                row = cur.fetchone()
        return {"household": row, "role": scope["role"]}

    @router.post("/households/{household_id}/join")
    async def join_household(
        household_id: str,
        authorization: Optional[str] = Header(default=None),
    ):
        session = await _resolve_session(authorization)
        user_id = session["user_id"]
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM households WHERE id = %s", (household_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Household not found")
                cur.execute(
                    """
                    INSERT INTO household_members (id, household_id, user_id, role, joined_at)
                    VALUES (%s, %s, %s, 'member', %s::timestamptz)
                    ON CONFLICT (household_id, user_id) DO NOTHING
                    """,
                    (str(uuid.uuid4()), household_id, user_id, utc_now_iso()),
                )
            conn.commit()
        return {"household_id": household_id, "role": "member"}

    # ---------------- Inventory (Ticket 2) ----------------
    @router.get("/inventory-items")
    async def list_inventory(
        location: Optional[str] = None,
        low_stock: Optional[bool] = None,
        expiring_soon: Optional[bool] = None,
        q: Optional[str] = None,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        sql = (
            "SELECT * FROM fc_inventory_items "
            "WHERE household_id = %s AND archived_at IS NULL"
        )
        args: List[Any] = [scope["household_id"]]
        if location:
            if location not in LOCATIONS:
                raise HTTPException(status_code=400, detail="invalid location")
            sql += " AND location = %s"
            args.append(location)
        if q:
            sql += " AND name ILIKE %s"
            args.append(f"%{q}%")
        sql += " ORDER BY created_at DESC LIMIT 2000"
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
        results = [dict(r) for r in rows]
        if low_stock:
            results = [
                r
                for r in results
                if is_low_stock(r.get("quantity"), r.get("low_stock_threshold"))
            ]
        if expiring_soon:
            results = [r for r in results if is_expiring_soon(str(r.get("expiry_date")) if r.get("expiry_date") else None)]
        return results

    @router.post("/inventory-items")
    async def add_inventory(
        body: InventoryItemCreate,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        if body.location not in LOCATIONS:
            raise HTTPException(status_code=400, detail="invalid location")
        item_id = str(uuid.uuid4())
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO fc_inventory_items (
                      id, household_id, name, normalized_name, location,
                      quantity, unit, category, expiry_date, low_stock_threshold,
                      notes, created_at, updated_at
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    )
                    """,
                    (
                        item_id,
                        scope["household_id"],
                        body.name,
                        normalized_name(body.name),
                        body.location,
                        body.quantity,
                        body.unit,
                        body.category,
                        body.expiry_date,
                        body.low_stock_threshold,
                        body.notes,
                    ),
                )
            conn.commit()
        return {"id": item_id, "household_id": scope["household_id"], "name": body.name, "location": body.location}

    @router.patch("/inventory-items/{item_id}")
    async def update_inventory(
        item_id: str,
        body: InventoryItemUpdate,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        updates: Dict[str, Any] = {}
        for key in (
            "name",
            "location",
            "quantity",
            "unit",
            "category",
            "expiry_date",
            "low_stock_threshold",
            "notes",
        ):
            value = getattr(body, key)
            if value is not None:
                updates[key] = value
        if "name" in updates:
            updates["normalized_name"] = normalized_name(updates["name"])
        if body.archived is not None:
            updates["archived_at"] = utc_now_iso() if body.archived else None
        if not updates:
            raise HTTPException(status_code=400, detail="no fields to update")
        if "location" in updates and updates["location"] not in LOCATIONS:
            raise HTTPException(status_code=400, detail="invalid location")
        set_clause = ", ".join(
            f"{k} = %s" + ("::timestamptz" if k == "archived_at" else "") for k in updates
        )
        args = list(updates.values()) + [item_id, scope["household_id"]]
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE fc_inventory_items SET {set_clause}, updated_at = NOW() WHERE id = %s AND household_id = %s",
                    args,
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="not found")
            conn.commit()
        return {"id": item_id, "updated": True}

    # ---------------- Food preferences (Ticket 3) ----------------
    @router.get("/food-preferences")
    async def get_food_preferences(
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM fc_user_food_preferences WHERE household_id = %s ORDER BY updated_at DESC LIMIT 1",
                    (scope["household_id"],),
                )
                row = cur.fetchone()
        return row or {
            "household_id": scope["household_id"],
            "likes": [],
            "dislikes": [],
            "allergies": [],
            "diet_style": None,
            "avoided_ingredients": [],
        }

    @router.put("/food-preferences")
    async def set_food_preferences(
        body: FoodPreferencesUpdate,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        pref_id = str(uuid.uuid4())
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM fc_user_food_preferences WHERE household_id = %s",
                    (scope["household_id"],),
                )
                cur.execute(
                    """
                    INSERT INTO fc_user_food_preferences (
                      id, household_id, user_id, likes, dislikes, allergies, diet_style, avoided_ingredients, updated_at
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                    """,
                    (
                        pref_id,
                        scope["household_id"],
                        None,
                        body.likes,
                        body.dislikes,
                        body.allergies,
                        body.diet_style,
                        body.avoided_ingredients,
                    ),
                )
            conn.commit()
        return {"id": pref_id, **body.dict()}

    # ---------------- AI generation (Ticket 3) ----------------
    @router.post("/ai/meal-ideas")
    async def generate_meal_ideas(
        body: MealIdeasRequest,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, normalized_name, location, quantity, unit FROM fc_inventory_items WHERE household_id = %s AND archived_at IS NULL",
                    (scope["household_id"],),
                )
                snapshot = [dict(r) for r in cur.fetchall()]
                cur.execute(
                    "SELECT likes, dislikes, allergies, diet_style, avoided_ingredients FROM fc_user_food_preferences WHERE household_id = %s ORDER BY updated_at DESC LIMIT 1",
                    (scope["household_id"],),
                )
                prefs = cur.fetchone() or {}
        if not snapshot:
            raise HTTPException(status_code=400, detail="Pantry is empty — add inventory before generating ideas")
        payload = {
            "pantry_snapshot": snapshot,
            "preferences": prefs,
            "meal_count": body.meal_count,
            "quick_only": body.quick_only,
            "use_mostly_what_i_have": body.use_mostly_what_i_have,
            "prompt": body.prompt,
            "slot_preferences": body.slot_preferences,
        }
        gen_id = str(uuid.uuid4())
        provider = get_default_provider()
        with _conn() as conn:
            with conn.cursor() as cur:
                # Persist the pending row first so failures are still recorded.
                from psycopg.types.json import Json  # local import keeps this module pure for unit tests
                cur.execute(
                    """
                    INSERT INTO fc_ai_generations (id, household_id, user_id, generation_type, status, model_name, input_snapshot, created_at)
                    VALUES (%s, %s, %s, 'meal_ideas', 'pending', %s, %s::jsonb, NOW())
                    """,
                    (
                        gen_id,
                        scope["household_id"],
                        scope["user_id"],
                        provider.model_name,
                        Json(payload),
                    ),
                )
            conn.commit()
        try:
            raw = provider.generate_meal_ideas(payload)
            output = validate_ai_meal_output(raw)
        except Exception as exc:  # AIValidationError or provider failure — render retryable error
            with _conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE fc_ai_generations SET status = 'failed', error_message = %s, completed_at = NOW() WHERE id = %s",
                        (str(exc), gen_id),
                    )
                conn.commit()
            raise HTTPException(status_code=502, detail="AI generation failed; retry") from exc

        with _conn() as conn:
            with conn.cursor() as cur:
                from psycopg.types.json import Json
                cur.execute(
                    "UPDATE fc_ai_generations SET status = 'completed', output_json = %s::jsonb, completed_at = NOW() WHERE id = %s",
                    (Json(output), gen_id),
                )
            conn.commit()
        return {
            "id": gen_id,
            "status": "completed",
            "model_name": provider.model_name,
            "meals": output["meals"],
            "preferences_applied": bool(prefs),
        }

    # ---------------- Meal plans (Ticket 4) ----------------
    @router.get("/meal-plans")
    async def list_meal_plans(
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM fc_meal_plans WHERE household_id = %s ORDER BY planned_for ASC LIMIT 200",
                    (scope["household_id"],),
                )
                plans = [dict(r) for r in cur.fetchall()]
                if plans:
                    plan_ids = tuple(p["id"] for p in plans)
                    cur.execute(
                        "SELECT * FROM fc_meal_ingredients WHERE meal_plan_id = ANY(%s)",
                        (list(plan_ids),),
                    )
                    ingredients_by_plan: Dict[str, List[Dict[str, Any]]] = {}
                    for row in cur.fetchall():
                        ingredients_by_plan.setdefault(row["meal_plan_id"], []).append(dict(row))
                    for plan in plans:
                        plan["ingredients"] = ingredients_by_plan.get(plan["id"], [])
        return plans

    @router.post("/meal-plans")
    async def create_meal_plan(
        body: MealPlanCreate,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        if body.slot not in MEAL_SLOTS:
            raise HTTPException(status_code=400, detail="invalid slot")
        if body.source not in MEAL_SOURCES:
            raise HTTPException(status_code=400, detail="invalid source")
        plan_id = str(uuid.uuid4())
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, normalized_name FROM fc_inventory_items WHERE household_id = %s AND archived_at IS NULL",
                    (scope["household_id"],),
                )
                inventory = [dict(r) for r in cur.fetchall()]
                cur.execute(
                    """
                    INSERT INTO fc_meal_plans (
                      id, household_id, planned_for, slot, title, description, source, ai_generation_id, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """,
                    (
                        plan_id,
                        scope["household_id"],
                        body.planned_for,
                        body.slot,
                        body.title,
                        body.description,
                        body.source,
                        body.ai_generation_id,
                    ),
                )
                for ingredient in body.ingredients:
                    norm = ingredient.normalized_name or normalized_name(ingredient.name)
                    match = match_ingredient_to_inventory(ingredient.name, inventory)
                    if ingredient.is_available is None:
                        is_available = bool(match)
                    else:
                        is_available = ingredient.is_available
                    cur.execute(
                        """
                        INSERT INTO fc_meal_ingredients (
                          id, meal_plan_id, name, normalized_name, quantity, unit, inventory_item_id, is_available, is_required, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        """,
                        (
                            str(uuid.uuid4()),
                            plan_id,
                            ingredient.name,
                            norm,
                            ingredient.quantity,
                            ingredient.unit,
                            match["id"] if match else None,
                            is_available,
                            ingredient.is_required,
                        ),
                    )
            conn.commit()
        return {"id": plan_id, "household_id": scope["household_id"]}

    @router.patch("/meal-ingredients/{ingredient_id}")
    async def override_meal_ingredient(
        ingredient_id: str,
        body: MealIngredientOverride,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE fc_meal_ingredients SET is_available = %s
                    WHERE id = %s AND meal_plan_id IN (
                      SELECT id FROM fc_meal_plans WHERE household_id = %s
                    )
                    """,
                    (body.is_available, ingredient_id, scope["household_id"]),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="ingredient not found")
            conn.commit()
        return {"id": ingredient_id, "is_available": body.is_available}

    @router.post("/meal-plans/{plan_id}/missing-to-shopping-list")
    async def push_missing_to_shopping_list(
        plan_id: str,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM fc_meal_plans WHERE id = %s AND household_id = %s",
                    (plan_id, scope["household_id"]),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="meal plan not found")
                cur.execute(
                    "SELECT name, normalized_name, quantity, unit FROM fc_meal_ingredients WHERE meal_plan_id = %s AND is_available = FALSE",
                    (plan_id,),
                )
                missing = [dict(r) for r in cur.fetchall()]
                list_id = await _ensure_active_list(conn, scope["household_id"])
                cur.execute(
                    "SELECT id, name, normalized_name, status, archived_at FROM fc_shopping_list_items WHERE shopping_list_id = %s",
                    (list_id,),
                )
                existing = [dict(r) for r in cur.fetchall()]
                to_insert, to_merge = dedup_shopping_items(existing, missing)
                for item in to_insert:
                    cur.execute(
                        """
                        INSERT INTO fc_shopping_list_items (
                          id, shopping_list_id, household_id, name, normalized_name,
                          quantity, unit, source, meal_plan_id, status, created_at
                        ) VALUES (
                          %s, %s, %s, %s, %s, %s, %s, 'missing_ingredient', %s, 'pending', NOW()
                        )
                        """,
                        (
                            str(uuid.uuid4()),
                            list_id,
                            scope["household_id"],
                            item["name"],
                            item["normalized_name"],
                            item.get("quantity"),
                            item.get("unit"),
                            plan_id,
                        ),
                    )
            conn.commit()
        return {
            "shopping_list_id": list_id,
            "added": len(to_insert),
            "merged": len(to_merge),
        }

    # ---------------- Shopping list (Ticket 5) ----------------
    @router.get("/shopping-list")
    async def get_shopping_list(scope: Dict[str, Any] = Depends(household_scope)):
        with _conn() as conn:
            list_id = await _ensure_active_list(conn, scope["household_id"])
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM fc_shopping_list_items WHERE shopping_list_id = %s ORDER BY created_at ASC",
                    (list_id,),
                )
                items = [dict(r) for r in cur.fetchall()]
        return {"shopping_list_id": list_id, "items": items}

    @router.post("/shopping-list/items")
    async def add_shopping_item(
        body: ShoppingItemCreate,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        if body.source not in SHOPPING_SOURCES:
            raise HTTPException(status_code=400, detail="invalid source")
        with _conn() as conn:
            list_id = await _ensure_active_list(conn, scope["household_id"])
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, normalized_name, status, archived_at FROM fc_shopping_list_items WHERE shopping_list_id = %s",
                    (list_id,),
                )
                existing = [dict(r) for r in cur.fetchall()]
                to_insert, _ = dedup_shopping_items(
                    existing,
                    [
                        {
                            "name": body.name,
                            "normalized_name": normalized_name(body.name),
                            "quantity": body.quantity,
                            "unit": body.unit,
                            "category": body.category,
                        }
                    ],
                )
                if not to_insert:
                    return {"merged": True, "shopping_list_id": list_id}
                row = to_insert[0]
                new_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO fc_shopping_list_items (
                      id, shopping_list_id, household_id, name, normalized_name,
                      quantity, unit, category, source, meal_plan_id, status, created_at
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', NOW()
                    )
                    """,
                    (
                        new_id,
                        list_id,
                        scope["household_id"],
                        row["name"],
                        row["normalized_name"],
                        row.get("quantity"),
                        row.get("unit"),
                        row.get("category"),
                        body.source,
                        body.meal_plan_id,
                    ),
                )
            conn.commit()
        return {"id": new_id, "shopping_list_id": list_id}

    @router.patch("/shopping-list/items/{item_id}/check")
    async def check_shopping_item(
        item_id: str,
        body: ShoppingItemCheck,
        scope: Dict[str, Any] = Depends(household_scope),
    ):
        new_status = "checked" if body.checked else "pending"
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE fc_shopping_list_items SET status = %s, checked_at = CASE WHEN %s THEN NOW() ELSE NULL END WHERE id = %s AND household_id = %s",
                    (new_status, body.checked, item_id, scope["household_id"]),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="not found")
            conn.commit()
        return {"id": item_id, "status": new_status}

    @router.post("/shopping-list/finish")
    async def finish_shopping_session(scope: Dict[str, Any] = Depends(household_scope)):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM fc_shopping_lists WHERE household_id = %s AND status = 'active' LIMIT 1",
                    (scope["household_id"],),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="no active list")
                list_id = row["id"]
                cur.execute(
                    "UPDATE fc_shopping_list_items SET archived_at = NOW() WHERE shopping_list_id = %s AND status = 'checked' AND archived_at IS NULL",
                    (list_id,),
                )
            conn.commit()
        return {"shopping_list_id": list_id, "finished": True}

    # ---------------- Dashboard (Ticket 6) ----------------
    @router.get("/dashboard")
    async def dashboard(scope: Dict[str, Any] = Depends(household_scope)):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM fc_inventory_items WHERE household_id = %s",
                    (scope["household_id"],),
                )
                inventory = [dict(r) for r in cur.fetchall()]
                cur.execute(
                    "SELECT * FROM fc_meal_plans WHERE household_id = %s",
                    (scope["household_id"],),
                )
                plans = [dict(r) for r in cur.fetchall()]
                if plans:
                    cur.execute(
                        "SELECT meal_plan_id, is_available FROM fc_meal_ingredients WHERE meal_plan_id = ANY(%s)",
                        ([p["id"] for p in plans],),
                    )
                    ingredients_by_plan: Dict[str, List[Dict[str, Any]]] = {}
                    for row in cur.fetchall():
                        ingredients_by_plan.setdefault(row["meal_plan_id"], []).append(dict(row))
                    for plan in plans:
                        plan["ingredients"] = ingredients_by_plan.get(plan["id"], [])
                cur.execute(
                    """
                    SELECT i.* FROM fc_shopping_list_items i
                    JOIN fc_shopping_lists l ON i.shopping_list_id = l.id
                    WHERE i.household_id = %s AND l.status = 'active'
                    """,
                    (scope["household_id"],),
                )
                shopping_items = [dict(r) for r in cur.fetchall()]
        return build_dashboard_payload(
            inventory=inventory,
            meal_plans=plans,
            shopping_list_items=shopping_items,
        )

    return router
