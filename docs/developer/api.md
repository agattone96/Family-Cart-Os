# Backend API Reference (Developer)

Base paths:
- Health: `/health`
- Legacy API: `/api/*`
- Family Cart OS v1: `/api/v1/*`

Authentication:
- Use `Authorization: Bearer <token>` for protected endpoints.

## Auth

- `POST /api/auth/signup`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/logout`

## Profile / defaults

- `GET /api/profile`
- `PUT /api/profile`
- `POST /api/profile/reset`

## Inventory (legacy)

- `GET /api/inventory?location=pantry|fridge|freezer`
- `POST /api/inventory`
- `POST /api/inventory/batch`
- `PUT /api/inventory/{item_id}`
- `DELETE /api/inventory/{item_id}`
- `POST /api/inventory/extract-photo`

## Required items

- `GET /api/required-items`
- `POST /api/required-items`
- `PUT /api/required-items/{item_id}`
- `DELETE /api/required-items/{item_id}`

## Plans and history

- `POST /api/generate-plan`
- `GET /api/current-plan`
- `PUT /api/current-plan`
- `DELETE /api/current-plan/recipe/{recipe_id}`
- `POST /api/regenerate-recipe`
- `GET /api/history`
- `POST /api/history/save`
- `POST /api/history/{history_id}/duplicate`

---

## Family Cart OS v1 (`/api/v1/*`)

All routes require `Authorization: Bearer <token>` and the active user
must be a member of a household.  `household_id` scoping is enforced at
the middleware level via `family_cart.household_scope`.

See `docs/developer/family-cart-architecture.md` for the full design.

### Households (Ticket 7)

- `POST /api/v1/households` — create a household (caller becomes owner)
- `GET /api/v1/households/me` — current household + role
- `POST /api/v1/households/{household_id}/join` — join as member

### Inventory (Ticket 2)

- `GET /api/v1/inventory-items?location=&low_stock=&expiring_soon=&q=`
- `POST /api/v1/inventory-items`
- `PATCH /api/v1/inventory-items/{item_id}` — supports archive via
  `{"archived": true}`

### Food preferences (Ticket 3)

- `GET /api/v1/food-preferences`
- `PUT /api/v1/food-preferences`

### AI meal ideas (Ticket 3)

- `POST /api/v1/ai/meal-ideas`
  - body: `{ "meal_count": 3, "quick_only": false, "use_mostly_what_i_have": false, "prompt": null, "slot_preferences": [] }`
  - response includes `meals[]`, `id` (generation id), `model_name`,
    `preferences_applied`.
  - HTTP 400 if pantry is empty; HTTP 502 on AI failure (UI must render
    retry).

### Meal plans (Ticket 4)

- `GET /api/v1/meal-plans`
- `POST /api/v1/meal-plans`
- `PATCH /api/v1/meal-ingredients/{ingredient_id}` — manual override
  of `is_available`.
- `POST /api/v1/meal-plans/{plan_id}/missing-to-shopping-list` —
  one-action push that deduplicates by `normalized_name`.

### Shopping list + shopping mode (Ticket 5)

- `GET /api/v1/shopping-list` — returns the single active list +
  items.
- `POST /api/v1/shopping-list/items`
- `PATCH /api/v1/shopping-list/items/{item_id}/check` —
  `{"checked": true|false}`.
- `POST /api/v1/shopping-list/finish` — archive checked items.

### Dashboard (Ticket 6)

- `GET /api/v1/dashboard` — returns `totals`, `today_meals`,
  `missing_ingredient_count`, `shopping_list_count`, `quick_actions`.

### Out-of-scope (Ticket 1, 8)

The v1 API intentionally **does not** include endpoints for: request
approval, templates, activity history, receipt or barcode scanning,
live pricing, coupons, delivery, nutrition / budget tracking, or
multi-household switching.
