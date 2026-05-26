# Family Cart OS v1 — Release Blockers

A release blocker is anything that must be resolved (or formally accepted with
an exception) before a v1 production release ships. This file is the canonical
list and is checked during the MVP release checklist sign-off.

## Rules

* Every blocker has a unique ID (`RB-XXX`).
* `severity = blocker` means **the release does not ship**. An accepted
  exception requires a signed entry in `docs/qa/scope-guardrail-signoff.md`.
* When a blocker is resolved, move it to the **Resolved** section with the
  resolving PR and date.
* If the blocker is downgraded (e.g. workaround accepted, scope re-cut), move
  it to `docs/qa/known-issues.md`.

## Currently open blockers

Tickets 1–7 describe the v1 feature spec. The blockers below were identified
while writing the QA coverage for v1. Each one explains the gap, what test
exists to detect it, and what needs to ship to clear it.

| ID | Severity | Area | Description | Detection / linked test | Acceptance criteria to clear |
|---|---|---|---|---|---|
| RB-001 | blocker | App shell (Ticket 7) | The app exposes 4 tabs (This Week / Inventory / Lists / Settings). The v1 brief requires 5 tabs: **Dashboard, Inventory, AI Meal Ideas, Weekly Meal Planner, Shopping List**. | `tests/test_release_guardrails.py::test_five_v1_navigation_sections_present_or_blocker` (skips with a blocker reason when sections are missing). `scripts/check_release_guardrails.py` exits non-zero. | All five v1 sections present in `frontend/app/(tabs)/_layout.tsx` (or replacement shell) with stable route names and empty states. |
| RB-002 | blocker | Household scoping (Ticket 7) | `households`, `household_members`, and `household_id` columns on v1 entities are not yet present. The current `inventory_items` table is owner-scoped, not household-scoped. | `tests/test_release_guardrails.py::test_household_scoping_blocker_documented` | Migration introduces `households`, `household_members`, and `household_id` foreign keys on `inventory_items`, `meal_plans`, `meal_ingredients`, `ai_generations`, `shopping_lists`, `shopping_list_items`, plus a shared access-control layer enforcing membership. |
| RB-003 | blocker | Inventory (Ticket 2) | `normalized_name`, `archived_at`, `expiry_date`, `low_stock_threshold`, `category`, and `notes` columns are not yet on `inventory_items`. v1 ingredient matching, soft delete, and dashboard health counts depend on them. | `tests/test_normalized_name.py` (helper coverage) + `tests/test_release_guardrails.py::test_inventory_schema_blocker_documented` | Backend schema expanded; `normalize_name` helper is the canonical normalizer; archived rows excluded from active reads, AI snapshots and ingredient matching. |
| RB-004 | blocker | Shopping mode (Ticket 5) | Offline behaviour is not implemented and not documented before the implementation begins. v1 explicitly requires this decision before shipping. | `tests/test_release_guardrails.py::test_shopping_mode_offline_decision_documented` (asserts a documented offline strategy exists in this file). | Either: (a) a written offline strategy in this file (optimistic UI, queued writes, sync-on-reconnect, visible sync status, no-loss guarantee), **and** an implementation that satisfies the `shop-mode-optimistic-offline` checklist row, **or** (b) a signed exception that excludes shopping mode from this release. |
| RB-005 | blocker | AI meal generation (Ticket 3) | `ai_generations` table is not yet present. Every generation attempt (success or failure) must produce an immutable record with `input_snapshot`, `output_json`, `status`, `error_message`. | `tests/test_release_guardrails.py::test_ai_generations_table_blocker_documented` | Backend persists every attempt; rendering blocked when output validation fails. |
| RB-006 | blocker | Meal planner (Ticket 4) | `meal_plans` / `meal_ingredients` tables and the planner → shopping list "add all missing" handoff are not yet present. | `tests/test_release_guardrails.py::test_meal_plan_blocker_documented` | Tables exist; `meal_ingredients.match_status` uses the documented enum; "add missing to shopping list" deduplicates by `normalized_name`. |
| RB-007 | blocker | Shopping list (Ticket 5) | `shopping_lists` / `shopping_list_items` tables with the v1 schema (status enum, source references, archived_at) are not yet present. | `tests/test_release_guardrails.py::test_shopping_list_blocker_documented` | Tables exist; one active list per household; dedupe by `normalized_name`; check-off + finish-session lifecycle implemented. |
| RB-008 | blocker | Dashboard (Ticket 6) | A dedicated Dashboard landing screen does not yet exist; counts are not surfaced. | `tests/test_release_guardrails.py::test_dashboard_blocker_documented` | Dashboard renders ≤ 5 primary cards with accurate household-scoped counts and quick actions. |

## Shopping-mode offline strategy (decision record)

Per Ticket 5, the offline strategy must be decided **before** implementation
begins. The current decision is:

1. **Optimistic updates.** Tapping check / uncheck updates UI state
   immediately.
2. **Local queue.** Mutations are written to a durable local queue keyed by
   `(shopping_list_id, item_id, action, timestamp)`. The queue survives app
   restarts.
3. **Sync on reconnect.** When connectivity returns, queued mutations are
   replayed in order. Conflicts (e.g. item removed server-side) prefer the
   server state but never silently drop user check-offs.
4. **Visible sync status.** The shopping mode header surfaces one of: `synced`,
   `pending: N`, `sync failed — retry`. Users always see why their state may
   differ from the server.
5. **No-loss guarantee.** A failed sync **never** clears the local queue;
   retries continue until the user explicitly resolves the conflict.

When the implementation lands, RB-004 may be closed with a link to the
implementing PR.

## Resolved blockers

| ID | Resolved date | Resolution PR | Notes |
|---|---|---|---|

(empty)
