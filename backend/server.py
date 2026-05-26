import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg
import requests
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Json
from starlette.middleware.cors import CORSMiddleware

try:
    from . import family_cart  # type: ignore
except ImportError:  # pragma: no cover
    import family_cart  # type: ignore

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
# Allow using a root-level `.env` (see `.env.example`) when `backend/.env` is absent.
load_dotenv(ROOT_DIR.parent / ".env", override=False)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required. Copy `.env.example` to `.env` and set DATABASE_URL.")

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_STORES = ["Walmart", "Tractor Supply", "Amazon", "Sam's Club", "Costco"]
DEFAULT_MEAL_COVERAGE = ["Breakfast", "Lunch", "Dinner", "Snacks"]
DEFAULT_COOKING_STYLES = ["Easy meals", "Crockpot", "One pan", "Minimum effort"]
DEFAULT_DIETARY_TAGS = ["Gluten free", "Dairy free", "Low carb", "Vegetarian"]


@app.get("/health")
async def healthcheck():
    return {"ok": True}


def db_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def serialize_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    data: Dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
        else:
            data[key] = value
    return data


def serialize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [serialize_row(row) or {} for row in rows]


def init_schema():
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  email TEXT NOT NULL UNIQUE,
                  password_hash TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  token TEXT NOT NULL UNIQUE,
                  email TEXT NOT NULL,
                  name TEXT NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS household_defaults (
                  owner_id TEXT PRIMARY KEY,
                  id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  email TEXT,
                  trip_type TEXT NOT NULL,
                  budget DOUBLE PRECISION NOT NULL,
                  adults INTEGER NOT NULL,
                  children INTEGER NOT NULL,
                  preferred_stores TEXT[] NOT NULL DEFAULT '{}',
                  meal_coverage TEXT[] NOT NULL DEFAULT '{}',
                  cooking_style TEXT[] NOT NULL DEFAULT '{}',
                  dietary_rules TEXT[] NOT NULL DEFAULT '{}',
                  exclusions TEXT NOT NULL DEFAULT '',
                  price_mode TEXT NOT NULL DEFAULT 'No prices',
                  household_summary TEXT NOT NULL DEFAULT '',
                  reusable_planning_instructions TEXT NOT NULL DEFAULT '',
                  custom_store_options TEXT[] NOT NULL DEFAULT '{}',
                  custom_meal_coverage_options TEXT[] NOT NULL DEFAULT '{}',
                  custom_cooking_style_options TEXT[] NOT NULL DEFAULT '{}',
                  custom_dietary_tags TEXT[] NOT NULL DEFAULT '{}',
                  reusable_exclusions TEXT[] NOT NULL DEFAULT '{}',
                  planner_prompt_override TEXT NOT NULL DEFAULT '',
                  onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE,
                  onboarding_completed_at TIMESTAMPTZ,
                  expiring_soon_days INTEGER NOT NULL DEFAULT 7,
                  last_inventory_location TEXT NOT NULL DEFAULT 'pantry',
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                ALTER TABLE household_defaults ADD COLUMN IF NOT EXISTS expiring_soon_days INTEGER NOT NULL DEFAULT 7;
                ALTER TABLE household_defaults ADD COLUMN IF NOT EXISTS last_inventory_location TEXT NOT NULL DEFAULT 'pantry';

                CREATE TABLE IF NOT EXISTS inventory_items (
                  id TEXT PRIMARY KEY,
                  owner_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  normalized_name TEXT NOT NULL DEFAULT '',
                  quantity DOUBLE PRECISION,
                  unit TEXT,
                  location TEXT NOT NULL DEFAULT 'pantry',
                  category TEXT,
                  expiry_date DATE,
                  low_stock_threshold DOUBLE PRECISION,
                  notes TEXT,
                  archived_at TIMESTAMPTZ,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS normalized_name TEXT NOT NULL DEFAULT '';
                ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS category TEXT;
                ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS expiry_date DATE;
                ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS low_stock_threshold DOUBLE PRECISION;
                ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS notes TEXT;
                ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
                ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
                ALTER TABLE inventory_items ALTER COLUMN quantity DROP NOT NULL;
                ALTER TABLE inventory_items ALTER COLUMN unit DROP NOT NULL;

                CREATE TABLE IF NOT EXISTS required_items (
                  id TEXT PRIMARY KEY,
                  owner_id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  quantity DOUBLE PRECISION NOT NULL,
                  unit TEXT NOT NULL DEFAULT '',
                  note TEXT NOT NULL DEFAULT '',
                  category TEXT NOT NULL DEFAULT 'grocery',
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS weekly_plans (
                  id TEXT PRIMARY KEY,
                  owner_id TEXT NOT NULL UNIQUE,
                  plan JSONB,
                  config JSONB,
                  ai_input JSONB,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS weekly_history (
                  id TEXT PRIMARY KEY,
                  owner_id TEXT NOT NULL,
                  plan JSONB,
                  config JSONB,
                  saved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                  created_at TIMESTAMPTZ
                );
                """
            )
        conn.commit()


@app.on_event("startup")
def startup_event():
    init_schema()
    with db_conn() as conn:
        family_cart.init_family_cart_schema(conn)
    family_cart.configure(session_resolver=get_session, db_factory=db_conn)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def auth_error() -> HTTPException:
    return HTTPException(status_code=401, detail="Authentication required")


def normalize_list(values: Optional[List[str]]) -> List[str]:
    if not values:
        return []
    seen = set()
    result = []
    for raw in values:
        value = str(raw).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


import re as _re_inventory


VALID_LOCATIONS = ("pantry", "fridge", "freezer")
DEFAULT_EXPIRING_SOON_DAYS = 7


def normalize_inventory_name(value: Optional[str]) -> str:
    """Lowercased, whitespace-collapsed identifier used for ingredient matching.

    Preserves the original user-visible ``name`` while giving downstream
    features (meal planning, shopping list dedupe) a consistent key.
    Returns an empty string when ``value`` is falsy.
    """
    if not value:
        return ""
    text = str(value).lower()
    text = _re_inventory.sub(r"[^a-z0-9]+", " ", text)
    text = _re_inventory.sub(r"\s+", " ", text).strip()
    return text


def normalize_location(value: Optional[str], fallback: str = "pantry") -> str:
    if value is None:
        return fallback
    lowered = str(value).strip().lower()
    if lowered in VALID_LOCATIONS:
        return lowered
    return fallback


def coerce_expiry_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Accept full ISO datetimes too.
        try:
            return date.fromisoformat(text[:10])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid expiry_date: {value!r}") from exc
    raise HTTPException(status_code=400, detail=f"Invalid expiry_date: {value!r}")


def is_low_stock(quantity: Any, threshold: Any) -> bool:
    """True only when both quantity and threshold are present and quantity <= threshold."""
    if quantity is None or threshold is None:
        return False
    try:
        return float(quantity) <= float(threshold)
    except (TypeError, ValueError):
        return False


def is_expiring_soon(expiry_value: Any, window_days: int, today: Optional[date] = None) -> bool:
    """True when expiry_value falls within `window_days` of today (inclusive).

    Items without an ``expiry_date`` never count as expiring soon.
    A negative offset (already past expiry) also counts as expiring soon so
    users still see it surfaced for action.
    """
    if expiry_value is None or expiry_value == "":
        return False
    if isinstance(expiry_value, str):
        try:
            expiry = date.fromisoformat(expiry_value[:10])
        except ValueError:
            return False
    elif isinstance(expiry_value, datetime):
        expiry = expiry_value.date()
    elif isinstance(expiry_value, date):
        expiry = expiry_value
    else:
        return False
    reference = today or date.today()
    window = max(int(window_days or 0), 0)
    delta = (expiry - reference).days
    return delta <= window


def annotate_inventory_item(item: Dict[str, Any], window_days: int) -> Dict[str, Any]:
    item = dict(item)
    item["is_low_stock"] = is_low_stock(item.get("quantity"), item.get("low_stock_threshold"))
    item["is_expiring_soon"] = is_expiring_soon(item.get("expiry_date"), window_days)
    return item


def combine_options(*groups: Optional[List[str]]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for group in groups:
        for item in normalize_list(group):
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def password_hash(password: str, salt: Optional[str] = None) -> str:
    actual_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), actual_salt.encode("utf-8"), 120000)
    return f"{actual_salt}${base64.b64encode(digest).decode('utf-8')}"


def verify_password(password: str, encoded: str) -> bool:
    salt, expected = encoded.split("$", 1)
    actual = password_hash(password, salt).split("$", 1)[1]
    return hmac.compare_digest(actual, expected)


async def get_session(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.replace("Bearer ", "", 1).strip()
    if not token:
        return None
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, token, email, name, created_at
                FROM sessions
                WHERE token = %s
                LIMIT 1
                """,
                (token,),
            )
            session = cur.fetchone()
    return serialize_row(session)


async def require_session(authorization: Optional[str]) -> Dict[str, Any]:
    session = await get_session(authorization)
    if not session:
        raise auth_error()
    return session


def owner_filter(owner_id: str) -> Dict[str, Any]:
    return {"owner_id": owner_id}


def profile_defaults(name: str = "Household", email: Optional[str] = None) -> Dict[str, Any]:
    return HouseholdProfile(name=name, email=email).dict()


async def ensure_profile(owner_id: str, name: str = "Household", email: Optional[str] = None) -> Dict[str, Any]:
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM household_defaults WHERE owner_id = %s LIMIT 1", (owner_id,))
            profile = cur.fetchone()
    profile_data = serialize_row(profile)
    if profile_data:
        return profile_data

    doc = profile_defaults(name=name, email=email)
    doc["owner_id"] = owner_id
    columns = ", ".join(doc.keys())
    placeholders = ", ".join(["%s"] * len(doc))
    values = tuple(doc.values())

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"INSERT INTO household_defaults ({columns}) VALUES ({placeholders})", values)
        conn.commit()
    return doc


def build_planner_input(config: Dict[str, Any], inventory: List[Dict[str, Any]], required: List[Dict[str, Any]], request_data: Dict[str, Any]) -> Dict[str, Any]:
    advanced = {
        "promptOverride": request_data.get("prompt_override") or config.get("planner_prompt_override", ""),
        "customInstructions": request_data.get("custom_instructions") or config.get("reusable_planning_instructions", ""),
        "householdContextOverride": request_data.get("household_context_override") or "",
        "inventoryContextOverride": request_data.get("inventory_context_override") or "",
        "requiredItemsContextOverride": request_data.get("required_items_context_override") or "",
        "planningNotes": request_data.get("planning_notes") or "",
        "customOptions": {
            "stores": combine_options(config.get("custom_store_options"), request_data.get("custom_store_options")),
            "mealCoverage": combine_options(config.get("custom_meal_coverage_options"), request_data.get("custom_meal_coverage_options")),
            "cookingStyles": combine_options(config.get("custom_cooking_style_options"), request_data.get("custom_cooking_style_options")),
            "dietaryTags": combine_options(config.get("custom_dietary_tags"), request_data.get("custom_dietary_tags")),
            "reusableExclusions": combine_options(config.get("reusable_exclusions"), request_data.get("reusable_exclusions")),
        },
    }

    return {
        "householdProfile": {
            "name": config.get("name", "Household"),
            "adults": config.get("adults", 4),
            "children": config.get("children", 1),
            "tripType": config.get("trip_type", "Full week"),
            "preferredStores": config.get("preferred_stores", []),
            "budget": config.get("budget", 200),
            "mealCoverage": config.get("meal_coverage", []),
            "cookingStyle": config.get("cooking_style", []),
            "dietaryRules": config.get("dietary_rules", []),
            "exclusions": config.get("exclusions", ""),
            "mealSummary": config.get("household_summary", ""),
        },
        "savedDefaults": {
            "customStoreOptions": config.get("custom_store_options", []),
            "customMealCoverageOptions": config.get("custom_meal_coverage_options", []),
            "customCookingStyleOptions": config.get("custom_cooking_style_options", []),
            "customDietaryTags": config.get("custom_dietary_tags", []),
            "reusableExclusions": config.get("reusable_exclusions", []),
            "reusablePlanningInstructions": config.get("reusable_planning_instructions", ""),
        },
        "weeklyPreferences": {
            "tripType": config.get("trip_type", "Full week"),
            "budget": config.get("budget", 200),
            "mealCoverage": config.get("meal_coverage", []),
            "cookingStyle": config.get("cooking_style", []),
            "priceMode": config.get("price_mode", "No prices"),
        },
        "inventoryItems": [
            {
                "name": item["name"],
                "normalizedName": item.get("normalized_name")
                    or normalize_inventory_name(item.get("name", "")),
                "quantity": item.get("quantity"),
                "unit": item.get("unit", "") or "",
                "location": item["location"],
                "category": item.get("category"),
                "expiryDate": item.get("expiry_date"),
                "isLowStock": is_low_stock(item.get("quantity"), item.get("low_stock_threshold")),
            }
            for item in inventory
        ],
        "requiredItems": [
            {
                "name": item["name"],
                "quantity": item["quantity"],
                "unit": item.get("unit", ""),
                "category": item.get("category", "grocery"),
                "note": item.get("note", ""),
            }
            for item in required
        ],
        "advancedControls": advanced,
    }


def openai_text_from_response(data: Dict[str, Any]) -> str:
    if data.get("output_text"):
        return data["output_text"]
    chunks: List[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def call_openai_responses(system_prompt: str, user_prompt: str, schema_name: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    body = {
        "model": os.environ.get("OPENAI_PLANNER_MODEL", "gpt-5.1"),
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": {
                    "type": "object",
                    "additionalProperties": True,
                },
            }
        },
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=90,
    )
    if not response.ok:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {response.text}")
    return openai_text_from_response(response.json())


async def call_emergent_chat(system_message: str, prompt: str, session_prefix: str) -> str:
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="AI key not configured")

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="Optional dependency missing: emergentintegrations. Install backend/requirements-emergent.txt to enable EMERGENT_LLM_KEY support.",
        ) from exc

    chat = LlmChat(
        api_key=api_key,
        session_id=f"{session_prefix}-{uuid.uuid4()}",
        system_message=system_message,
    ).with_model("openai", "gpt-5.2")

    return await chat.send_message(UserMessage(text=prompt))


async def generate_plan_with_provider(system_prompt: str, ai_input: Dict[str, Any]) -> Dict[str, Any]:
    prompt = (
        "Generate a weekly meal and shopping plan from this input. Return valid JSON only, no markdown.\n\n"
        f"{json.dumps(ai_input, indent=2)}"
    )
    if os.environ.get("OPENAI_API_KEY"):
        response_text = call_openai_responses(system_prompt, prompt, "pantry_plan")
    else:
        response_text = await call_emergent_chat(system_prompt, prompt, "plan")

    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end_idx = len(lines) - 1
        text = "\n".join(lines[1:end_idx]) if lines[end_idx].strip().startswith("```") else "\n".join(lines[1:])
    return json.loads(text)


async def generate_recipe_replacement(old_recipe: Dict[str, Any], config: Dict[str, Any], inventory: List[Dict[str, Any]], preference: str) -> Dict[str, Any]:
    system_prompt = (
        "You are a recipe replacement engine. Given a recipe to replace and household context, "
        "generate ONE replacement recipe. Return valid JSON only matching this shape: "
        "{\"id\": \"new-uuid\", \"name\": \"...\", \"reasonChosen\": \"...\", \"servings\": N, "
        "\"effortLevel\": \"low|medium|high\", \"cookMethod\": \"...\", \"mealType\": \"...\", "
        "\"ingredients\": [{\"name\": \"...\", \"quantity\": N, \"unit\": \"...\", \"section\": \"...\", "
        "\"onHand\": bool, \"mustBuy\": bool, \"optionalSubstitution\": null, \"estimatedPrice\": null}]}"
    )
    prompt = (
        f"Replace this recipe with a {preference} alternative:\n"
        f"Recipe to replace: {json.dumps(old_recipe)}\n"
        f"Household: {config.get('adults', 4)} adults, {config.get('children', 1)} children\n"
        f"Cooking style: {json.dumps(config.get('cooking_style', []))}\n"
        f"Dietary rules: {json.dumps(config.get('dietary_rules', []))}\n"
        f"Exclusions: {config.get('exclusions', '')}\n"
        f"Inventory on hand: {json.dumps([i['name'] for i in inventory[:30]])}\n"
        "Return valid JSON only."
    )
    if os.environ.get("OPENAI_API_KEY"):
        response_text = call_openai_responses(system_prompt, prompt, "recipe_replacement")
    else:
        response_text = await call_emergent_chat(system_prompt, prompt, "regen")

    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end_idx = len(lines) - 1
        text = "\n".join(lines[1:end_idx]) if lines[end_idx].strip().startswith("```") else "\n".join(lines[1:])
    recipe = json.loads(text)
    recipe["id"] = str(uuid.uuid4())
    return recipe


class AuthRequest(BaseModel):
    name: Optional[str] = None
    email: str
    password: str


class HouseholdProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Household"
    email: Optional[str] = None
    trip_type: str = "Full week"
    budget: float = 200.0
    adults: int = 4
    children: int = 1
    preferred_stores: List[str] = Field(default_factory=lambda: DEFAULT_STORES.copy())
    meal_coverage: List[str] = Field(default_factory=lambda: DEFAULT_MEAL_COVERAGE.copy())
    cooking_style: List[str] = Field(default_factory=lambda: DEFAULT_COOKING_STYLES.copy())
    dietary_rules: List[str] = Field(default_factory=list)
    exclusions: str = ""
    price_mode: str = "No prices"
    household_summary: str = ""
    reusable_planning_instructions: str = ""
    custom_store_options: List[str] = Field(default_factory=list)
    custom_meal_coverage_options: List[str] = Field(default_factory=list)
    custom_cooking_style_options: List[str] = Field(default_factory=list)
    custom_dietary_tags: List[str] = Field(default_factory=list)
    reusable_exclusions: List[str] = Field(default_factory=list)
    planner_prompt_override: str = ""
    onboarding_completed: bool = False
    onboarding_completed_at: Optional[str] = None
    expiring_soon_days: int = DEFAULT_EXPIRING_SOON_DAYS
    last_inventory_location: str = "pantry"
    updated_at: str = Field(default_factory=utc_now)


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    trip_type: Optional[str] = None
    budget: Optional[float] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    preferred_stores: Optional[List[str]] = None
    meal_coverage: Optional[List[str]] = None
    cooking_style: Optional[List[str]] = None
    dietary_rules: Optional[List[str]] = None
    exclusions: Optional[str] = None
    price_mode: Optional[str] = None
    household_summary: Optional[str] = None
    reusable_planning_instructions: Optional[str] = None
    custom_store_options: Optional[List[str]] = None
    custom_meal_coverage_options: Optional[List[str]] = None
    custom_cooking_style_options: Optional[List[str]] = None
    custom_dietary_tags: Optional[List[str]] = None
    reusable_exclusions: Optional[List[str]] = None
    planner_prompt_override: Optional[str] = None
    onboarding_completed: Optional[bool] = None
    onboarding_completed_at: Optional[str] = None
    expiring_soon_days: Optional[int] = None
    last_inventory_location: Optional[str] = None


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


class RequiredItemCreate(BaseModel):
    name: str
    quantity: float = 1
    unit: str = ""
    note: str = ""
    category: str = "grocery"


class RequiredItemUpdate(BaseModel):
    name: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    note: Optional[str] = None
    category: Optional[str] = None


class PhotoExtractRequest(BaseModel):
    image_base64: str
    location: str = "pantry"


class GeneratePlanRequest(BaseModel):
    trip_type: Optional[str] = None
    budget: Optional[float] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    preferred_stores: Optional[List[str]] = None
    meal_coverage: Optional[List[str]] = None
    cooking_style: Optional[List[str]] = None
    dietary_rules: Optional[List[str]] = None
    exclusions: Optional[str] = None
    price_mode: Optional[str] = None
    prompt_override: Optional[str] = None
    custom_instructions: Optional[str] = None
    household_context_override: Optional[str] = None
    inventory_context_override: Optional[str] = None
    required_items_context_override: Optional[str] = None
    planning_notes: Optional[str] = None
    custom_store_options: Optional[List[str]] = None
    custom_meal_coverage_options: Optional[List[str]] = None
    custom_cooking_style_options: Optional[List[str]] = None
    custom_dietary_tags: Optional[List[str]] = None
    reusable_exclusions: Optional[List[str]] = None
    save_new_defaults: bool = False


class UpdatePlanBody(BaseModel):
    plan: dict


class RegenerateRecipeRequest(BaseModel):
    recipe_id: str
    preference: str = "similar"


PLANNER_SYSTEM_PROMPT = """You are the planning engine for Diana's Pantry Plan.

ROLE
You generate a practical weekly household meal and shopping plan based on structured household inputs. You are not a chatbot and you do not return conversational fluff. You return structured planning output only.

GOAL
Given household defaults, weekly preferences, current inventory, required items, store preferences, and budget, generate:
- 3 to 7 realistic recipe ideas
- ingredients for each recipe
- what is already on hand
- what must be purchased
- one merged grocery list grouped by section
- household supply items
- optional price estimates
- cheaper substitutions when requested
- minimum-effort recommendations

ADVANCED CONTROL RULES
- Respect any promptOverride while still keeping JSON output only
- Treat customInstructions and planningNotes as high-priority user intent
- Use householdContextOverride, inventoryContextOverride, and requiredItemsContextOverride to fill gaps in structured data
- Consider customOptions as valid additions to the default choices rather than throwaway notes

PRIORITIES
1. Prefer easy realistic meals
2. Strongly favor minimum effort
3. Favor crockpot, one-pan, sheet pan, batchable, and low-cleanup meals
4. Reuse ingredients across meals
5. Reduce waste
6. Avoid duplicate purchases
7. Use pantry/fridge/freezer inventory first
8. Stay within budget when possible
9. Suggest cheaper substitutions when needed
10. Keep meals household-friendly and practical

AVOID
- vague meal inspiration
- overly complex meals
- niche ingredients unless necessary
- duplicate ingredients under slightly different names
- output that is hard to edit
- conversational filler

REQUIRED LOGIC
- Generate 3 to 7 meals that fit household size and meal preferences
- Match meals to effort preference and cooking style
- Use overlapping ingredients where possible
- Flag inventory matches
- Separate on-hand items from must-buy items
- Merge duplicate grocery items into a consolidated shopping list
- Keep household supply items in a separate list
- If price mode is cheap-first, bias toward lower-cost meals and substitutions
- If price mode is estimated-prices, return rough estimates by item and total
- Respect exclusions, allergies, and diet rules strictly

RECIPE OUTPUT REQUIREMENTS
For each recipe include:
- id (string uuid)
- name
- short reasonChosen
- servings
- effortLevel (low, medium, or high)
- cookMethod
- mealType (breakfast, lunch, dinner, or snack)
- ingredients array

Each ingredient should include:
- name
- quantity (number)
- unit
- section (produce, meat, dairy, frozen, pantry, snacks, beverages, household, misc)
- onHand (boolean)
- mustBuy (boolean)
- optionalSubstitution (string or null)
- estimatedPrice (number or null)

MERGED GROCERY LIST RULES
- group by section
- merge duplicates
- normalize naming
- include quantity and unit where possible
- mark whether item was required by recipe, user-required list, or both

HOUSEHOLD LIST RULES
- keep household items separate from groceries
- preserve user-added required household items

RESPONSE FORMAT
Return valid JSON only. No markdown, no backticks, no explanation.

JSON SHAPE
{
  "selectedRecipes": [],
  "pantryMatches": [],
  "itemsToPurchase": [],
  "mergedGroceryListBySection": [],
  "householdItems": [],
  "estimatedTotal": null,
  "substitutions": [],
  "notes": []
}

QUALITY BAR
The plan must feel like something a real household would actually use this week."""


@api_router.post("/auth/signup")
async def signup(req: AuthRequest):
    email = req.email.strip().lower()
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s LIMIT 1", (email,))
            existing = cur.fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="Account already exists")

    user_id = str(uuid.uuid4())
    user = {
        "id": user_id,
        "name": (req.name or "Household").strip() or "Household",
        "email": email,
        "password_hash": password_hash(req.password),
    }

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, name, email, password_hash, created_at) VALUES (%s, %s, %s, %s, %s::timestamptz)",
                (user_id, user["name"], email, user["password_hash"], utc_now()),
            )
        conn.commit()

    await ensure_profile(user_id, name=user["name"], email=email)

    token = secrets.token_urlsafe(32)
    session = {"id": str(uuid.uuid4()), "user_id": user_id, "token": token, "email": email, "name": user["name"]}

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (id, user_id, token, email, name, created_at) VALUES (%s, %s, %s, %s, %s, %s::timestamptz)",
                (session["id"], user_id, token, email, user["name"], utc_now()),
            )
        conn.commit()

    profile = await ensure_profile(user_id, name=user["name"], email=email)
    return {"token": token, "user": {"id": user_id, "name": user["name"], "email": email}, "profile": profile}


@api_router.post("/auth/login")
async def login(req: AuthRequest):
    email = req.email.strip().lower()
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, email, password_hash FROM users WHERE email = %s LIMIT 1", (email,))
            user = cur.fetchone()

    user_data = serialize_row(user)
    if not user_data or not verify_password(req.password, user_data["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = secrets.token_urlsafe(32)

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (id, user_id, token, email, name, created_at) VALUES (%s, %s, %s, %s, %s, %s::timestamptz)",
                (str(uuid.uuid4()), user_data["id"], token, email, user_data["name"], utc_now()),
            )
        conn.commit()

    profile = await ensure_profile(user_data["id"], name=user_data["name"], email=email)
    return {"token": token, "user": {"id": user_data["id"], "name": user_data["name"], "email": email}, "profile": profile}


@api_router.get("/auth/me")
async def auth_me(authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    profile = await ensure_profile(session["user_id"], name=session.get("name", "Household"), email=session.get("email"))
    return {
        "user": {"id": session["user_id"], "name": session.get("name", "Household"), "email": session.get("email")},
        "profile": profile,
    }


@api_router.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token = %s", (session["token"],))
        conn.commit()
    return {"success": True}


@api_router.get("/profile")
async def get_profile(authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    return await ensure_profile(session["user_id"], name=session.get("name", "Household"), email=session.get("email"))


@api_router.put("/profile")
async def update_profile(update: ProfileUpdate, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    existing = await ensure_profile(owner_id, name=session.get("name", "Household"), email=session.get("email"))
    update_data = {k: v for k, v in update.dict().items() if v is not None}

    for key in (
        "preferred_stores",
        "meal_coverage",
        "cooking_style",
        "dietary_rules",
        "custom_store_options",
        "custom_meal_coverage_options",
        "custom_cooking_style_options",
        "custom_dietary_tags",
        "reusable_exclusions",
    ):
        if key in update_data:
            update_data[key] = normalize_list(update_data[key])

    if "name" in update_data and session:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET name = %s WHERE id = %s", (update_data["name"], session["user_id"]))
                cur.execute("UPDATE sessions SET name = %s WHERE user_id = %s", (update_data["name"], session["user_id"]))
            conn.commit()

    update_data["updated_at"] = utc_now()
    set_fields = ", ".join([f"{key} = %s" + ("::timestamptz" if key == "onboarding_completed_at" else "") for key in update_data.keys()])
    values: List[Any] = list(update_data.values()) + [owner_id]

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE household_defaults SET {set_fields} WHERE owner_id = %s", values)
            cur.execute("SELECT * FROM household_defaults WHERE owner_id = %s LIMIT 1", (owner_id,))
            updated = cur.fetchone()
        conn.commit()

    return serialize_row(updated) or existing


@api_router.post("/profile/reset")
async def reset_profile(authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM household_defaults WHERE owner_id = %s", (owner_id,))
        conn.commit()
    profile = await ensure_profile(owner_id, name=session.get("name", "Household"), email=session.get("email"))
    return profile


INVENTORY_COLUMNS = (
    "id, owner_id, name, normalized_name, quantity, unit, location, category, "
    "expiry_date, low_stock_threshold, notes, archived_at, created_at, updated_at"
)


def _profile_for_session(session: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": session.get("name", "Household"),
        "email": session.get("email"),
    }


@api_router.get("/inventory")
async def get_inventory(
    location: Optional[str] = None,
    search: Optional[str] = None,
    low_stock: Optional[bool] = None,
    expiring_soon: Optional[bool] = None,
    include_archived: bool = False,
    authorization: Optional[str] = Header(default=None),
):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    profile = await ensure_profile(owner_id, **_profile_for_session(session))
    window_days = int(profile.get("expiring_soon_days") or DEFAULT_EXPIRING_SOON_DAYS)

    clauses = ["owner_id = %s"]
    params: List[Any] = [owner_id]
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if location:
        clauses.append("location = %s")
        params.append(normalize_location(location))
    if search:
        clauses.append("normalized_name LIKE %s")
        params.append(f"%{normalize_inventory_name(search)}%")

    where = " AND ".join(clauses)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {INVENTORY_COLUMNS} FROM inventory_items WHERE {where} "
                "ORDER BY created_at DESC LIMIT 1000",
                params,
            )
            rows = cur.fetchall()

    items = [annotate_inventory_item(serialize_row(row) or {}, window_days) for row in rows]
    if low_stock:
        items = [item for item in items if item["is_low_stock"]]
    if expiring_soon:
        items = [item for item in items if item["is_expiring_soon"]]
    return items


def _update_last_inventory_location(owner_id: str, location: str) -> None:
    safe = normalize_location(location)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE household_defaults SET last_inventory_location = %s WHERE owner_id = %s",
                (safe, owner_id),
            )
        conn.commit()


def _insert_inventory_row(cur, owner_id: str, item: InventoryItemCreate) -> Dict[str, Any]:
    location = normalize_location(item.location)
    expiry = coerce_expiry_date(item.expiry_date)
    doc = {
        "id": str(uuid.uuid4()),
        "owner_id": owner_id,
        "name": item.name.strip(),
        "normalized_name": normalize_inventory_name(item.name),
        "quantity": item.quantity,
        "unit": item.unit,
        "location": location,
        "category": item.category,
        "expiry_date": expiry.isoformat() if expiry else None,
        "low_stock_threshold": item.low_stock_threshold,
        "notes": item.notes,
        "archived_at": None,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    cur.execute(
        f"INSERT INTO inventory_items ({INVENTORY_COLUMNS}) VALUES ("
        "%s, %s, %s, %s, %s, %s, %s, %s, %s::date, %s, %s, %s, %s::timestamptz, %s::timestamptz)",
        (
            doc["id"], doc["owner_id"], doc["name"], doc["normalized_name"], doc["quantity"],
            doc["unit"], doc["location"], doc["category"], doc["expiry_date"],
            doc["low_stock_threshold"], doc["notes"], doc["archived_at"],
            doc["created_at"], doc["updated_at"],
        ),
    )
    return doc


@api_router.post("/inventory")
async def add_inventory_item(item: InventoryItemCreate, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    if not item.name or not item.name.strip():
        raise HTTPException(status_code=400, detail="Item name is required")
    owner_id = session["user_id"]
    await ensure_profile(owner_id, **_profile_for_session(session))
    with db_conn() as conn:
        with conn.cursor() as cur:
            doc = _insert_inventory_row(cur, owner_id, item)
        conn.commit()
    _update_last_inventory_location(owner_id, item.location)
    profile = await ensure_profile(owner_id, **_profile_for_session(session))
    window_days = int(profile.get("expiring_soon_days") or DEFAULT_EXPIRING_SOON_DAYS)
    return annotate_inventory_item(doc, window_days)


@api_router.post("/inventory/batch")
async def add_inventory_batch(items: List[InventoryItemCreate], authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    profile = await ensure_profile(owner_id, **_profile_for_session(session))
    window_days = int(profile.get("expiring_soon_days") or DEFAULT_EXPIRING_SOON_DAYS)
    results: List[Dict[str, Any]] = []
    if not items:
        return results
    last_location: Optional[str] = None
    with db_conn() as conn:
        with conn.cursor() as cur:
            for item in items:
                if not item.name or not item.name.strip():
                    continue
                doc = _insert_inventory_row(cur, owner_id, item)
                results.append(annotate_inventory_item(doc, window_days))
                last_location = doc["location"]
        conn.commit()
    if last_location:
        _update_last_inventory_location(owner_id, last_location)
    return results


@api_router.put("/inventory/{item_id}")
async def update_inventory_item(item_id: str, update: InventoryItemUpdate, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    profile = await ensure_profile(owner_id, **_profile_for_session(session))
    window_days = int(profile.get("expiring_soon_days") or DEFAULT_EXPIRING_SOON_DAYS)

    raw = update.dict(exclude_unset=True)
    if not raw:
        raise HTTPException(status_code=400, detail="No fields to update")

    update_data: Dict[str, Any] = {}
    archive_flag = raw.pop("archived", None)

    for key, value in raw.items():
        if key == "name":
            if value is None or not str(value).strip():
                raise HTTPException(status_code=400, detail="Name cannot be empty")
            update_data["name"] = str(value).strip()
            update_data["normalized_name"] = normalize_inventory_name(value)
        elif key == "location":
            update_data["location"] = normalize_location(value)
        elif key == "expiry_date":
            expiry = coerce_expiry_date(value)
            update_data["expiry_date"] = expiry.isoformat() if expiry else None
        else:
            update_data[key] = value

    if archive_flag is True:
        update_data["archived_at"] = utc_now()
    elif archive_flag is False:
        update_data["archived_at"] = None

    update_data["updated_at"] = utc_now()

    def column_sql(key: str) -> str:
        if key == "expiry_date":
            return "expiry_date = %s::date"
        if key in {"archived_at", "updated_at"}:
            return f"{key} = %s::timestamptz"
        return f"{key} = %s"

    set_fields = ", ".join(column_sql(k) for k in update_data.keys())
    values = list(update_data.values()) + [item_id, owner_id]

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE inventory_items SET {set_fields} WHERE id = %s AND owner_id = %s",
                values,
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Item not found")
            cur.execute(
                f"SELECT {INVENTORY_COLUMNS} FROM inventory_items WHERE id = %s AND owner_id = %s",
                (item_id, owner_id),
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    if "location" in update_data:
        _update_last_inventory_location(owner_id, update_data["location"])
    return annotate_inventory_item(serialize_row(row) or {}, window_days)


@api_router.post("/inventory/{item_id}/archive")
async def archive_inventory_item(item_id: str, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    profile = await ensure_profile(owner_id, **_profile_for_session(session))
    window_days = int(profile.get("expiring_soon_days") or DEFAULT_EXPIRING_SOON_DAYS)
    archived_at = utc_now()
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory_items SET archived_at = %s::timestamptz, updated_at = %s::timestamptz "
                "WHERE id = %s AND owner_id = %s",
                (archived_at, archived_at, item_id, owner_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Item not found")
            cur.execute(
                f"SELECT {INVENTORY_COLUMNS} FROM inventory_items WHERE id = %s AND owner_id = %s",
                (item_id, owner_id),
            )
            row = cur.fetchone()
        conn.commit()
    return annotate_inventory_item(serialize_row(row) or {}, window_days)


@api_router.delete("/inventory/{item_id}")
async def delete_inventory_item(item_id: str, authorization: Optional[str] = Header(default=None)):
    """Soft delete: marks the inventory item as archived rather than removing it."""
    session = await require_session(authorization)
    owner_id = session["user_id"]
    archived_at = utc_now()
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory_items SET archived_at = %s::timestamptz, updated_at = %s::timestamptz "
                "WHERE id = %s AND owner_id = %s AND archived_at IS NULL",
                (archived_at, archived_at, item_id, owner_id),
            )
            affected = cur.rowcount
        conn.commit()
    if affected == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"success": True, "archived_at": archived_at}


@api_router.get("/inventory/dashboard")
async def get_inventory_dashboard(authorization: Optional[str] = Header(default=None)):
    """Surface low-stock and expiring-soon items for the dashboard."""
    session = await require_session(authorization)
    owner_id = session["user_id"]
    profile = await ensure_profile(owner_id, **_profile_for_session(session))
    window_days = int(profile.get("expiring_soon_days") or DEFAULT_EXPIRING_SOON_DAYS)
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {INVENTORY_COLUMNS} FROM inventory_items "
                "WHERE owner_id = %s AND archived_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1000",
                (owner_id,),
            )
            rows = cur.fetchall()
    items = [annotate_inventory_item(serialize_row(row) or {}, window_days) for row in rows]
    low_stock_items = [item for item in items if item["is_low_stock"]]
    expiring_soon_items = [item for item in items if item["is_expiring_soon"]]
    return {
        "expiring_soon_days": window_days,
        "last_inventory_location": profile.get("last_inventory_location", "pantry"),
        "low_stock_count": len(low_stock_items),
        "expiring_soon_count": len(expiring_soon_items),
        "low_stock": low_stock_items,
        "expiring_soon": expiring_soon_items,
        "active_total": len(items),
    }


@api_router.post("/inventory/extract-photo")
async def extract_photo(req: PhotoExtractRequest, authorization: Optional[str] = Header(default=None)):
    await require_session(authorization)
    try:
        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="AI key not configured")

        try:
            from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail="Optional dependency missing: emergentintegrations. Install backend/requirements-emergent.txt to enable EMERGENT_LLM_KEY support.",
            ) from exc

        chat = LlmChat(
            api_key=api_key,
            session_id=f"photo-{uuid.uuid4()}",
            system_message=(
                "You are an inventory scanner. Given a photo of a pantry, fridge, or freezer, identify all visible food "
                "and household items. Return ONLY a valid JSON array of objects with keys: name (string), quantity "
                "(number estimate), unit (string like 'bottles', 'bags', 'boxes', 'lbs', 'items', 'cans'). No extra text."
            ),
        ).with_model("openai", "gpt-5.2")

        response = await chat.send_message(
            UserMessage(
                text=f"List every item visible in this {req.location} photo as a JSON array.",
                file_contents=[ImageContent(image_base64=req.image_base64)],
            )
        )

        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            end = -1 if lines[-1].strip().startswith("```") else len(lines)
            text = "\n".join(lines[1:end])

        items_raw = json.loads(text)
        extracted = []
        for item in items_raw:
            extracted.append(
                {
                    "id": str(uuid.uuid4()),
                    "name": item.get("name", "Unknown"),
                    "quantity": float(item.get("quantity", 1)),
                    "unit": item.get("unit", ""),
                    "location": req.location,
                }
            )
        return {"items": extracted}
    except json.JSONDecodeError:
        logger.error("Failed to parse AI photo response")
        raise HTTPException(status_code=500, detail="Failed to parse extracted items from photo")
    except Exception as exc:
        logger.error(f"Photo extraction error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@api_router.get("/required-items")
async def get_required_items(authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, owner_id, name, quantity, unit, note, category, created_at FROM required_items WHERE owner_id = %s ORDER BY created_at DESC LIMIT 1000",
                (owner_id,),
            )
            rows = cur.fetchall()
    return serialize_rows(rows)


@api_router.post("/required-items")
async def add_required_item(item: RequiredItemCreate, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    doc = {
        "id": str(uuid.uuid4()),
        "owner_id": session["user_id"],
        "name": item.name,
        "quantity": item.quantity,
        "unit": item.unit,
        "note": item.note,
        "category": item.category,
        "created_at": utc_now(),
    }
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO required_items (id, owner_id, name, quantity, unit, note, category, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::timestamptz)
                """,
                (doc["id"], doc["owner_id"], doc["name"], doc["quantity"], doc["unit"], doc["note"], doc["category"], doc["created_at"]),
            )
        conn.commit()
    return doc


@api_router.put("/required-items/{item_id}")
async def update_required_item(item_id: str, update: RequiredItemUpdate, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_fields = ", ".join([f"{k} = %s" for k in update_data.keys()])
    values = list(update_data.values()) + [item_id, owner_id]

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE required_items SET {set_fields} WHERE id = %s AND owner_id = %s", values)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Item not found")
            cur.execute(
                "SELECT id, owner_id, name, quantity, unit, note, category, created_at FROM required_items WHERE id = %s AND owner_id = %s",
                (item_id, owner_id),
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    return serialize_row(row)


@api_router.delete("/required-items/{item_id}")
async def delete_required_item(item_id: str, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM required_items WHERE id = %s AND owner_id = %s", (item_id, owner_id))
            deleted = cur.rowcount
        conn.commit()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"success": True}


@api_router.post("/generate-plan")
async def generate_plan(req: GeneratePlanRequest, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    profile = await ensure_profile(owner_id, name=session.get("name", "Household"), email=session.get("email"))

    config = {**profile}
    for key, value in req.dict().items():
        if value is not None and key != "save_new_defaults":
            config[key] = value

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {INVENTORY_COLUMNS} FROM inventory_items WHERE owner_id = %s AND archived_at IS NULL", (owner_id,))
            inventory = serialize_rows(cur.fetchall())
            cur.execute("SELECT id, owner_id, name, quantity, unit, note, category, created_at FROM required_items WHERE owner_id = %s", (owner_id,))
            required = serialize_rows(cur.fetchall())

    ai_input = build_planner_input(config, inventory, required, req.dict())

    if req.save_new_defaults:
        save_patch = {
            "custom_store_options": combine_options(profile.get("custom_store_options"), req.custom_store_options),
            "custom_meal_coverage_options": combine_options(profile.get("custom_meal_coverage_options"), req.custom_meal_coverage_options),
            "custom_cooking_style_options": combine_options(profile.get("custom_cooking_style_options"), req.custom_cooking_style_options),
            "custom_dietary_tags": combine_options(profile.get("custom_dietary_tags"), req.custom_dietary_tags),
            "reusable_exclusions": combine_options(profile.get("reusable_exclusions"), req.reusable_exclusions),
            "reusable_planning_instructions": req.custom_instructions or profile.get("reusable_planning_instructions", ""),
            "planner_prompt_override": req.prompt_override or profile.get("planner_prompt_override", ""),
            "updated_at": utc_now(),
        }
        set_fields = ", ".join([f"{k} = %s" for k in save_patch.keys()])
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE household_defaults SET {set_fields} WHERE owner_id = %s", list(save_patch.values()) + [owner_id])
            conn.commit()

    try:
        plan_data = await generate_plan_with_provider(PLANNER_SYSTEM_PROMPT, ai_input)
        plan_record = {
            "id": str(uuid.uuid4()),
            "owner_id": owner_id,
            "plan": plan_data,
            "config": {k: v for k, v in config.items() if k != "_id"},
            "ai_input": ai_input,
            "created_at": utc_now(),
        }

        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM weekly_plans WHERE owner_id = %s", (owner_id,))
                cur.execute(
                    """
                    INSERT INTO weekly_plans (id, owner_id, plan, config, ai_input, created_at)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::timestamptz)
                    """,
                    (
                        plan_record["id"],
                        owner_id,
                        Json(plan_data),
                        Json(plan_record["config"]),
                        Json(ai_input),
                        plan_record["created_at"],
                    ),
                )
            conn.commit()

        return plan_record
    except json.JSONDecodeError:
        logger.error("Failed to parse AI plan response")
        raise HTTPException(status_code=500, detail="AI returned invalid format. Please try again.")
    except Exception as exc:
        logger.error(f"Plan generation error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@api_router.get("/current-plan")
async def get_current_plan(authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, owner_id, plan, config, ai_input, created_at FROM weekly_plans WHERE owner_id = %s LIMIT 1", (owner_id,))
            plan = cur.fetchone()
    return serialize_row(plan) or {"plan": None}


@api_router.put("/current-plan")
async def update_current_plan(body: UpdatePlanBody, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE weekly_plans SET plan = %s::jsonb WHERE owner_id = %s", (Json(body.plan), owner_id))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="No current plan")
            cur.execute("SELECT id, owner_id, plan, config, ai_input, created_at FROM weekly_plans WHERE owner_id = %s LIMIT 1", (owner_id,))
            updated = cur.fetchone()
        conn.commit()
    return serialize_row(updated)


@api_router.delete("/current-plan/recipe/{recipe_id}")
async def remove_recipe(recipe_id: str, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, owner_id, plan, config, ai_input, created_at FROM weekly_plans WHERE owner_id = %s LIMIT 1", (owner_id,))
            plan_doc = cur.fetchone()

    plan_doc_data = serialize_row(plan_doc)
    if not plan_doc_data:
        raise HTTPException(status_code=404, detail="No current plan")

    plan = plan_doc_data.get("plan", {})
    plan["selectedRecipes"] = [recipe for recipe in plan.get("selectedRecipes", []) if recipe.get("id") != recipe_id]

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE weekly_plans SET plan = %s::jsonb WHERE owner_id = %s", (Json(plan), owner_id))
            cur.execute("SELECT id, owner_id, plan, config, ai_input, created_at FROM weekly_plans WHERE owner_id = %s LIMIT 1", (owner_id,))
            updated = cur.fetchone()
        conn.commit()

    return serialize_row(updated)


@api_router.post("/regenerate-recipe")
async def regenerate_recipe(req: RegenerateRecipeRequest, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, owner_id, plan, config, ai_input, created_at FROM weekly_plans WHERE owner_id = %s LIMIT 1", (owner_id,))
            plan_doc = cur.fetchone()

    plan_doc_data = serialize_row(plan_doc)
    if not plan_doc_data or not plan_doc_data.get("plan"):
        raise HTTPException(status_code=404, detail="No current plan")

    old_recipe = None
    for recipe in plan_doc_data["plan"].get("selectedRecipes", []):
        if recipe.get("id") == req.recipe_id:
            old_recipe = recipe
            break
    if not old_recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {INVENTORY_COLUMNS} FROM inventory_items WHERE owner_id = %s AND archived_at IS NULL", (owner_id,))
            inventory = serialize_rows(cur.fetchall())

    try:
        new_recipe = await generate_recipe_replacement(old_recipe, plan_doc_data.get("config", {}), inventory, req.preference)
        plan = plan_doc_data["plan"]
        plan["selectedRecipes"] = [new_recipe if recipe.get("id") == req.recipe_id else recipe for recipe in plan.get("selectedRecipes", [])]

        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE weekly_plans SET plan = %s::jsonb WHERE owner_id = %s", (Json(plan), owner_id))
                cur.execute("SELECT id, owner_id, plan, config, ai_input, created_at FROM weekly_plans WHERE owner_id = %s LIMIT 1", (owner_id,))
                updated = cur.fetchone()
            conn.commit()

        return serialize_row(updated)
    except Exception as exc:
        logger.error(f"Recipe regeneration error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@api_router.get("/history")
async def get_history(authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, owner_id, plan, config, saved_at, created_at FROM weekly_history WHERE owner_id = %s ORDER BY created_at DESC NULLS LAST LIMIT 50",
                (owner_id,),
            )
            rows = cur.fetchall()
    return serialize_rows(rows)


@api_router.post("/history/save")
async def save_to_history(authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, owner_id, plan, config, ai_input, created_at FROM weekly_plans WHERE owner_id = %s LIMIT 1", (owner_id,))
            plan = cur.fetchone()

    plan_data = serialize_row(plan)
    if not plan_data:
        raise HTTPException(status_code=404, detail="No current plan to save")

    history_entry = {
        "id": str(uuid.uuid4()),
        "owner_id": owner_id,
        "plan": plan_data.get("plan"),
        "config": plan_data.get("config"),
        "saved_at": utc_now(),
        "created_at": plan_data.get("created_at"),
    }

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO weekly_history (id, owner_id, plan, config, saved_at, created_at)
                VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::timestamptz, %s::timestamptz)
                """,
                (
                    history_entry["id"],
                    owner_id,
                    Json(history_entry["plan"]),
                    Json(history_entry["config"]),
                    history_entry["saved_at"],
                    history_entry["created_at"],
                ),
            )
        conn.commit()

    return history_entry


@api_router.post("/history/{history_id}/duplicate")
async def duplicate_from_history(history_id: str, authorization: Optional[str] = Header(default=None)):
    session = await require_session(authorization)
    owner_id = session["user_id"]

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, owner_id, plan, config, saved_at, created_at FROM weekly_history WHERE id = %s AND owner_id = %s LIMIT 1",
                (history_id, owner_id),
            )
            entry = cur.fetchone()

    entry_data = serialize_row(entry)
    if not entry_data:
        raise HTTPException(status_code=404, detail="History entry not found")

    plan_record = {
        "id": str(uuid.uuid4()),
        "owner_id": owner_id,
        "plan": entry_data.get("plan"),
        "config": entry_data.get("config"),
        "created_at": utc_now(),
    }

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM weekly_plans WHERE owner_id = %s", (owner_id,))
            cur.execute(
                """
                INSERT INTO weekly_plans (id, owner_id, plan, config, ai_input, created_at)
                VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::timestamptz)
                """,
                (plan_record["id"], owner_id, Json(plan_record["plan"]), Json(plan_record["config"]), Json({}), plan_record["created_at"]),
            )
        conn.commit()

    return plan_record


app.include_router(api_router)
app.include_router(family_cart.build_router())

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    return None
