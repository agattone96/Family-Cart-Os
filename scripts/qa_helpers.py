"""Shared QA helpers used by the v1 release-gate tests.

These helpers exist so QA-level invariants (normalized-name behaviour, AI
response validation, dedupe rules) can be exercised in isolation while the
production feature wiring is still being built. They are deliberately small,
dependency-free, and stable so that the tests in ``tests/`` remain valid
contracts regardless of the surrounding implementation.

Production code should adopt these helpers (or a strict superset of their
behaviour) when the corresponding ticket lands. If product behaviour diverges
from these helpers, file an entry in ``docs/qa/known-issues.md`` and update
the helpers in the same PR — the tests are the contract.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Mapping, MutableMapping, Sequence

# ---------------------------------------------------------------------------
# normalized_name
# ---------------------------------------------------------------------------

# Family Cart OS v1 ingredient matching uses an exact comparison on a
# deterministic, lowercase, single-spaced, alphanumeric representation of the
# user-entered name. This is intentionally narrow — the brief calls out that
# we are not pretending to do fuzzy matching.

_NORMALIZED_NON_ALPHA = re.compile(r"[^a-z0-9]+")


def normalize_name(value: str | None) -> str:
    """Return the canonical ``normalized_name`` for ingredient matching.

    Rules (per ticket 2 + 4):

    * Lowercase.
    * Strip leading/trailing whitespace.
    * Collapse any run of non-alphanumeric characters to a single ``" "``.
    * Trim the resulting string.
    * Empty input returns ``""``.
    """
    if value is None:
        return ""
    lower = str(value).strip().lower()
    collapsed = _NORMALIZED_NON_ALPHA.sub(" ", lower).strip()
    return collapsed


def names_match(a: str | None, b: str | None) -> bool:
    """Two ingredient names match when their normalized forms are equal and non-empty."""
    norm_a = normalize_name(a)
    norm_b = normalize_name(b)
    return bool(norm_a) and norm_a == norm_b


# ---------------------------------------------------------------------------
# Shopping list dedupe / merge
# ---------------------------------------------------------------------------


def merge_into_shopping_list(
    existing: Sequence[MutableMapping[str, Any]],
    incoming: Mapping[str, Any],
) -> List[MutableMapping[str, Any]]:
    """Merge an incoming item into an active shopping list by ``normalized_name``.

    Rules:

    * Match is by exact ``normalized_name``.
    * Active items only (``archived_at`` and ``removed_at`` must be falsy).
    * Checked items are **not** silently reactivated; merge happens but the
      ``is_checked`` flag is preserved (see the v1 brief: "checked items
      should not be silently reactivated unless the expected behavior is
      explicitly defined").
    * User-edited ``name``, ``quantity``, ``notes``, ``category`` are
      preserved — incoming values are only adopted when the existing field
      is missing / empty.
    * Source references are preserved. If the existing row has no source
      reference for a given field, the incoming value fills it in.

    Returns the updated list (the same list object is mutated in place for
    callers that prefer that style, and is also returned for chaining).
    """
    incoming_normalized = normalize_name(incoming.get("name"))
    if not incoming_normalized:
        # Anonymous items can never dedupe; just append a copy.
        existing_list = list(existing)
        existing_list.append(dict(incoming))
        return existing_list

    for item in existing:
        if item.get("archived_at") or item.get("removed_at"):
            continue
        if normalize_name(item.get("name")) != incoming_normalized:
            continue

        # Preserve user-edited primary fields. Only fill in missing values.
        for field in ("quantity", "unit", "notes", "category"):
            if not item.get(field) and incoming.get(field):
                item[field] = incoming[field]

        # Adopt source references that aren't already set.
        for ref in (
            "source_type",
            "source_meal_plan_id",
            "source_meal_ingredient_id",
            "source_inventory_item_id",
        ):
            if not item.get(ref) and incoming.get(ref):
                item[ref] = incoming[ref]

        # is_checked is intentionally NOT toggled here.
        return list(existing)

    # No match → append.
    return list(existing) + [dict(incoming)]


# ---------------------------------------------------------------------------
# AI response validation
# ---------------------------------------------------------------------------


REQUIRED_AI_MEAL_FIELDS: Sequence[str] = (
    "title",
    "description",
    "ingredients_used",
    "inventory_matches",
    "missing_ingredients",
    "optional_substitutions",
    "estimated_prep_complexity",
)


class AIResponseValidationError(ValueError):
    """Raised when an AI response cannot be safely rendered."""


def validate_ai_meal_response(payload: Any) -> List[dict]:
    """Validate an AI meal-idea response before rendering.

    Behaviour matches the contract in Ticket 3:

    * ``None`` / non-list payloads are rejected.
    * Empty lists are rejected.
    * Each meal must be a mapping and must include every required field.
    * Returns the parsed list of meals on success.
    """
    if payload is None:
        raise AIResponseValidationError("AI response was empty (None).")
    if not isinstance(payload, list):
        raise AIResponseValidationError(
            f"AI response must be a list of meals, got {type(payload).__name__}."
        )
    if len(payload) == 0:
        raise AIResponseValidationError("AI response was empty (no meals).")

    for index, meal in enumerate(payload):
        if not isinstance(meal, Mapping):
            raise AIResponseValidationError(
                f"Meal #{index} is not an object (got {type(meal).__name__})."
            )
        missing = [f for f in REQUIRED_AI_MEAL_FIELDS if f not in meal]
        if missing:
            raise AIResponseValidationError(
                f"Meal #{index} is missing required fields: {missing}."
            )
    # Return a list of plain dicts so callers can safely mutate.
    return [dict(meal) for meal in payload]


def parse_and_validate_ai_meal_text(text: str) -> List[dict]:
    """Parse a raw AI text response and validate it.

    The AI response sometimes arrives wrapped in markdown fences (``` ... ```).
    The parser tolerates one level of fencing. Anything else is rejected.
    """
    if not isinstance(text, str) or not text.strip():
        raise AIResponseValidationError("AI response text was empty.")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Drop leading fence and optional language tag.
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIResponseValidationError(
            f"AI response was not valid JSON: {exc.msg}"
        ) from exc

    return validate_ai_meal_response(payload)
