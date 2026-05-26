# Family Cart OS v1 — Architecture

This document is the canonical reference for the Family Cart OS v1
implementation that ships under `/api/v1/*`.  It complements the
existing "Diana's Pantry Plan" docs and supersedes them for anything
referenced from the Family Cart epic (Tickets 1–8).

## 1. Goals

Ship a working pantry + AI meal-planning loop households will actually
use:

```
inventory  ─►  AI meal ideas  ─►  weekly meal plan  ─►  missing
ingredients  ─►  shopping list  ─►  shopping mode
```

The MVP is intentionally narrow.  See the "Out of scope" section below
for what we are *not* building in v1.

## 2. Module layout

```
backend/
  server.py            # legacy app + auth; hosts the family-cart router
  family_cart.py       # v1 implementation (schema, helpers, router)
  tests/
    test_family_cart_unit.py
docs/
  developer/family-cart-architecture.md      (this file)
  release/family-cart-mvp-qa-checklist.md    (Ticket 8 sign-off)
  user/family-cart-mvp.md                    (user-facing overview)
```

`backend/family_cart.py` exports:

- `SCHEMA_SQL` / `init_family_cart_schema(conn)` — bootstrap the ten
  canonical tables.
- `build_router()` — FastAPI router mounted at `/api/v1`.
- Pure helpers: `normalized_name`, `is_low_stock`, `is_expiring_soon`,
  `match_ingredient_to_inventory`, `dedup_shopping_items`,
  `validate_ai_meal_output`, `build_dashboard_payload`,
  `assert_no_out_of_scope_features`.
- `AIProvider` (abstract) + `StubAIProvider` (default) +
  `set_default_provider` for plugging in a real model when one is
  selected.

The wiring is done in `backend/server.py::startup_event` via
`family_cart.configure(session_resolver=get_session, db_factory=db_conn)`.

## 3. Data model

| Table                       | Purpose                                  |
|-----------------------------|------------------------------------------|
| `users`                     | Existing — auth identity.                |
| `households`                | Family Cart household.                   |
| `household_members`         | User ↔ household, role in (`owner`, `member`). |
| `fc_inventory_items`        | Pantry / fridge / freezer items.         |
| `fc_ai_generations`         | Every AI request, with `input_snapshot`. |
| `fc_meal_plans`             | Weekly planner entries.                  |
| `fc_meal_ingredients`       | Per-meal ingredients + match state.      |
| `fc_shopping_lists`         | One active list per household.           |
| `fc_shopping_list_items`    | List entries with source + meal FK.      |
| `fc_user_food_preferences`  | Household / per-user preferences.        |

### Conventions

- **`household_id` is required on every household-scoped table** — DB
  `NOT NULL`, indexed, and enforced at the API layer by
  `family_cart.household_scope`.
- **`normalized_name`** is the canonical match key.  It is computed by
  `normalized_name(value)` (lowercased, punctuation stripped, whitespace
  collapsed) at write time.  Use it for:
  - Matching `fc_meal_ingredients.inventory_item_id`.
  - Deduplicating `fc_shopping_list_items` (Tickets 4 + 5).
- **Soft delete** via `archived_at TIMESTAMPTZ` on `fc_inventory_items`
  and `fc_shopping_lists` (never hard delete).
- **`fc_ai_generations.input_snapshot`** is a hard requirement, not
  optional logging.  Pantry context that produced an output must be
  reconstructable from this column alone.
- **`fc_meal_ingredients.is_required`** marks optional / substitution
  ingredients so a partially-stocked pantry doesn't surface false
  "needs to buy" warnings.
- **`fc_shopping_list_items.source`** enum: `manual`,
  `missing_ingredient`, `low_stock` — plus nullable `meal_plan_id` for
  traceability.
- **`fc_user_food_preferences.user_id`** may be `NULL` (household-level
  preference).

## 4. Household scoping (Ticket 7)

```python
@router.get("/inventory-items")
async def list_inventory(..., scope=Depends(family_cart.household_scope)):
    ...
```

`household_scope` is the single middleware-level dependency for every
v1 route.  It resolves the active session, looks up the user's
household membership, and returns
`{ household_id, user_id, role, session }`.

- Missing / invalid token → HTTP 401.
- Authenticated but no membership → HTTP 403.
- Multiple memberships are supported in the schema (so we can grow
  into multi-household without a migration), but v1 picks the
  earliest-joined household.  **Do not** add a switcher UI — that is
  out of scope.

Owner-only routes call `require_owner(scope)` after resolution.

## 5. AI provider abstraction (Ticket 3)

The AI provider is intentionally swappable because the production
model is not selected at MVP-cut time.  The default
`StubAIProvider` is deterministic, structured-output compliant, and
suitable for CI.  Real provider implementations must:

1. Subclass `AIProvider`.
2. Set `model_name` to a stable identifier (persisted in
   `fc_ai_generations.model_name`).
3. Return a payload that passes `validate_ai_meal_output` — i.e.
   `{ "meals": [ { title, description, ingredients_used,
   missing_ingredients, estimated_prep_complexity, ... } ] }`.

Install a real provider with `family_cart.set_default_provider(provider)`
during startup (e.g. behind an env flag).  The route never invokes the
provider for an empty pantry — it returns HTTP 400 to satisfy the
"empty pantry blocks generation" requirement.

`fc_ai_generations` records both successful and failed attempts.  A
failure stores `status = 'failed'` plus `error_message`; the route
returns HTTP 502 so the UI can render a retryable error state.

## 6. Offline architecture (Ticket 5 prerequisite)

The shopping list and shopping mode must remain usable under poor
connectivity.  The contract:

1. **Optimistic UI** — local mutations apply immediately to the cached
   list and are mirrored to the server in the background.
2. **Idempotent endpoints** — `PATCH /shopping-list/items/{id}/check`
   and `POST /shopping-list/items` are safe to retry; the server
   deduplicates by `normalized_name` (see `dedup_shopping_items`).
3. **Finish session is atomic on the server** —
   `POST /shopping-list/finish` archives every checked row in one
   transaction.  Clients may queue the call and replay on reconnect.
4. **Shopping mode is read-only-friendly** — even if the network is
   completely offline, the client renders the most recent list snapshot
   and lets the user check items off; the local store reconciles when
   the network returns.

This decision was made before Ticket 5 implementation began and is
documented here, not buried in code.

## 7. Out of scope (hard guardrails)

The following must not appear in v1 UI, routes, or data model beyond
what's needed for future compatibility:

- Request approval flow / inbox.
- Co-admin / Adult / Teen / Child roles (only `owner` and `member`).
- Templates / reusable list presets.
- Activity history / audit log.
- Receipt scanning, barcode scanning, live pricing, coupons, delivery.
- Nutrition / calorie / macro / budget tracking.
- Multi-household switching UI.
- Export / share (a plain-text copy of the shopping list is acceptable
  if trivial).

The `family_cart.assert_no_out_of_scope_features(copy_blob)` helper
checks the rendered copy bundle for these terms.  Wire it into the QA
sign-off step described in the release checklist.

## 8. Test strategy

- `backend/tests/test_family_cart_unit.py` covers every pure helper,
  validation path, dedup branch, dashboard count, schema contract,
  and the scope guardrail strings.  It does **not** require a database
  and can run in any CI environment.
- Integration testing (DB + HTTP) lives in
  `backend/tests/test_backend_apis.py` style harnesses and runs only
  when `EXPO_PUBLIC_BACKEND_URL` is set — that is the e2e harness for
  the QA checklist.
- The Ticket 8 QA checklist (`docs/release/family-cart-mvp-qa-checklist.md`)
  must be completed and signed off before every release.
