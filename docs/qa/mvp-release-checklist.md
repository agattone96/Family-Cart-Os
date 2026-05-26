# Family Cart OS v1 — MVP Release Checklist

This checklist is the reusable QA gate for shipping the Family Cart OS v1 MVP
(pantry → AI meal ideas → weekly plan → missing ingredients → shopping list →
shopping mode). It must be filled in and signed off before any v1 production
release. Tests live in `tests/` and `backend/tests/`; automated guardrail checks
live in `scripts/check_release_guardrails.py`.

## How to use this checklist

1. Run the automated test suite for the area being shipped (see `docs/developer/testing.md`).
2. Run the release-guardrail script:
   ```bash
   python3 scripts/check_release_guardrails.py
   ```
3. Walk every row below.
   * Fill in **Actual Result**.
   * Mark **Pass / Fail** (`pass`, `fail`, `blocked`, `n/a`).
   * Capture any open follow-ups in **Notes**.
   * If a row is marked **Release Blocker = Yes** and **Pass / Fail = fail or blocked**,
     the release MUST NOT ship until the row is resolved or formally accepted.
4. File any new defects in `docs/qa/known-issues.md` and any blockers in
   `docs/qa/release-blockers.md`.
5. Confirm the scope-guardrail sign-off in `docs/qa/scope-guardrail-signoff.md`.

## Status legend

| Symbol | Meaning |
|---|---|
| `pass` | Verified working, matches expected result. |
| `fail` | Behaviour does not match expected result. Must be resolved or accepted. |
| `blocked` | Cannot be exercised because the feature has not been implemented yet. Promote to a release blocker. |
| `n/a` | Out of scope for this release branch. |

## Checklist rows

> Fields per row: **Test name · Feature area · Preconditions · Test steps · Expected result · Actual result · Pass/Fail · Notes · Release blocker**

---

### Foundation: app shell + household scope (Ticket 7)

| Test name | Feature area | Preconditions | Test steps | Expected result | Actual result | Pass / Fail | Notes | Release blocker |
|---|---|---|---|---|---|---|---|---|
| `nav-five-sections` | App shell | Signed-in user with active household | Open the app and verify the bottom navigation | The five v1 sections exist: **Dashboard, Inventory, AI Meal Ideas, Weekly Meal Planner, Shopping List** |  |  | `scripts/check_release_guardrails.py` flags missing sections as guardrail failures (must be fixed). | Yes |
| `nav-empty-states` | App shell | First-run user | Open each of the five sections before adding any data | Each empty state explains what the section is for; no placeholder promises out-of-scope features (no receipts, barcodes, pricing, coupons, delivery, nutrition, budget, templates, requests) |  |  | Empty-state guardrail check enforces this via `scripts/check_release_guardrails.py`. | Yes |
| `household-create-on-first-login` | Household setup | New user, no household | Sign up, follow the household setup flow | One household is created and the user is added as `Owner` |  |  | Tested by `tests/test_household_setup.py::test_first_household_setup_assigns_owner` (currently expected to be `blocked` until Ticket 7 ships). | Yes |
| `household-active-context` | Household setup | Signed-in user | Hit a protected endpoint without an active household | Request is rejected with a clear error; no v1 data is returned |  |  |  | Yes |
| `household-isolation-read` | Household data scoping | Two households A and B with data | User in household A requests records belonging to household B | API returns 404/403 and no data leaks |  |  |  | Yes |
| `household-isolation-write` | Household data scoping | Two households A and B | User in household A attempts to create / update / archive records under household B's `household_id` | API rejects the request; nothing is written under B |  |  |  | Yes |
| `role-enforcement-shared-layer` | Authorization | n/a | Inspect role enforcement | Role checks live in a single shared access-control layer, not duplicated per route |  |  | See `backend/tests/test_auth_enforcement_unit.py` and the v1 isolation tests. | Yes |

### Inventory (Ticket 2)

| Test name | Feature area | Preconditions | Test steps | Expected result | Actual result | Pass / Fail | Notes | Release blocker |
|---|---|---|---|---|---|---|---|---|
| `inv-fast-add` | Inventory | Active household, empty inventory | Open fast-add, enter only `name` and `location`, save | Item is created with only the two required fields; defaults are respected; mobile add completes in < 15s |  |  | Backend supports `name` + `location` minimally; full fast-add UX is tracked in `release-blockers.md`. | Yes |
| `inv-normalized-name` | Inventory | n/a | Create item named `Roma Tomatoes`, then rename to `tomato` | `normalized_name` is populated on create and updated when `name` changes |  |  | `tests/test_normalized_name.py` covers the helper; persistence is gated on the v1 schema landing. | Yes |
| `inv-soft-delete` | Inventory | Item exists | Archive item, then list active inventory | `archived_at` is set; item disappears from active list, AI snapshots and ingredient matching |  |  |  | Yes |
| `inv-low-stock` | Inventory | Item with quantity=1 and threshold=2 | Open dashboard / inventory filter | Item is flagged low-stock; items without both quantity and threshold do **not** trigger |  |  |  | No |
| `inv-expiring-soon` | Inventory | Item with `expiry_date` within window | Open dashboard / inventory filter | Item is flagged expiring-soon; items without `expiry_date` are **not** flagged |  |  |  | No |

### AI meal generation (Ticket 3)

| Test name | Feature area | Preconditions | Test steps | Expected result | Actual result | Pass / Fail | Notes | Release blocker |
|---|---|---|---|---|---|---|---|---|
| `ai-success-path` | AI Meal Ideas | Active inventory with ≥ 3 items | Trigger generation; AI returns valid JSON | Meals render as result cards with all required fields (`title`, `description`, `ingredients_used`, `inventory_matches`, `missing_ingredients`, `optional_substitutions`, `estimated_prep_complexity`); an `ai_generations` row is created with the immutable `input_snapshot` |  |  |  | Yes |
| `ai-malformed-response` | AI Meal Ideas | Inventory present | AI returns non-JSON / malformed payload | App shows error state with retry; **no** broken / partial meal card is rendered |  |  |  | Yes |
| `ai-empty-response` | AI Meal Ideas | Inventory present | AI returns `[]` / empty payload | App shows error state with retry; user options + inventory remain intact |  |  |  | Yes |
| `ai-empty-inventory-blocks-generation` | AI Meal Ideas | No active inventory | Open meal-ideas screen | Generate action is disabled or blocked; user is prompted to add inventory |  |  |  | Yes |
| `ai-archived-items-excluded` | AI Meal Ideas | One active item, one archived item | Trigger generation | `input_snapshot.inventory_snapshot` contains only the active item |  |  |  | Yes |
| `ai-food-preferences-included` | AI Meal Ideas | Saved household food preferences exist | Trigger generation | Preferences are included in the request; UI shows "Generated using your saved food preferences" |  |  |  | No |

### Weekly meal planner (Ticket 4)

| Test name | Feature area | Preconditions | Test steps | Expected result | Actual result | Pass / Fail | Notes | Release blocker |
|---|---|---|---|---|---|---|---|---|
| `plan-save-ai-meal` | Weekly Meal Planner | Generated meal result available | Save meal to a day + slot | Planned meal stored with `source_type = ai_generated` and `ai_generation_id` retained |  |  |  | Yes |
| `plan-manual-meal` | Weekly Meal Planner | Empty slot | Add manual meal with title only | Stored with `source_type = manual`; description optional |  |  |  | No |
| `plan-ingredient-match` | Weekly Meal Planner | Planned meal + inventory items | Open planned meal detail | Ingredient match status uses `normalized_name` exact match; archived inventory excluded |  |  |  | Yes |
| `plan-manual-override` | Weekly Meal Planner | Planned meal with missing ingredient | User toggles ingredient as available | Override is scoped to that planned meal ingredient only; does not flip inventory globally |  |  |  | No |
| `plan-add-missing-to-shopping` | Weekly Meal Planner ↔ Shopping List | Planned meal with missing ingredients | Tap "Add missing to shopping list" | All missing ingredients land on the active shopping list, deduplicated by `normalized_name`; source references retained |  |  |  | Yes |

### Shopping list + shopping mode (Ticket 5)

| Test name | Feature area | Preconditions | Test steps | Expected result | Actual result | Pass / Fail | Notes | Release blocker |
|---|---|---|---|---|---|---|---|---|
| `shop-dedupe-normalized` | Shopping List | Active list contains "Tomato" | Add "tomatoes" from another source | Items merge by `normalized_name`; no duplicate row created; user-edited fields are not overwritten |  |  |  | Yes |
| `shop-source-references` | Shopping List | Items added from manual / missing ingredient / low stock paths | Inspect each item | Source type stored as `manual` / `missing_ingredient` / `low_stock`; source references preserved when available |  |  |  | No |
| `shop-mode-checkoff` | Shopping Mode | Active list with ≥ 5 unchecked items | Enter shopping mode, tap to check off items one at a time | Each tap toggles `is_checked`; unchecked items shown first; checked items dim / strikethrough |  |  |  | Yes |
| `shop-mode-finish-session` | Shopping Mode | Active session with mix of checked + unchecked items | Tap finish session | Checked items get `archived_at`; unchecked remain on active list; `shopping_lists.finished_at` set; `status = finished` |  |  |  | Yes |
| `shop-mode-optimistic-offline` | Shopping Mode | Network disabled | Toggle items, then re-enable network | UI updates immediately; pending changes are queued and synced; sync status is visible; **no local progress is lost** on failure |  |  |  | Yes |

### Dashboard (Ticket 6)

| Test name | Feature area | Preconditions | Test steps | Expected result | Actual result | Pass / Fail | Notes | Release blocker |
|---|---|---|---|---|---|---|---|---|
| `dash-card-limit` | Dashboard | n/a | Inspect dashboard cards | Dashboard renders **no more than 5** primary cards |  |  | Enforced by `scripts/check_release_guardrails.py`. | Yes |
| `dash-counts-accurate` | Dashboard | Known inventory + plan + shopping list state | Load dashboard | Inventory total, low-stock, expiring-soon, today's meals, missing ingredient, active shopping list counts all match underlying data; archived / checked items excluded |  |  |  | Yes |
| `dash-empty-states` | Dashboard | Empty household | Load dashboard | Empty states link to the relevant section and **do not** promise out-of-scope features |  |  |  | Yes |
| `dash-quick-actions` | Dashboard | n/a | Tap each quick action | "Add pantry item", "Generate meal ideas", "View meal plan", "Open shopping list" each navigate to the correct screen |  |  |  | No |

### Scope guardrails

| Test name | Feature area | Preconditions | Test steps | Expected result | Actual result | Pass / Fail | Notes | Release blocker |
|---|---|---|---|---|---|---|---|---|
| `guardrail-no-out-of-scope-ui` | Scope | Repo at release SHA | Run `python3 scripts/check_release_guardrails.py` | Script exits with code `0`; no in-product strings expose Requests / Templates / Activity history / Receipt scan / Barcode / Live pricing / Coupons / Delivery / Nutrition / Budget / Multi-household switching / Five-role labels |  |  | Failures must be triaged before release. | Yes |
| `guardrail-ai-validation-before-render` | Scope | n/a | Inspect AI rendering | AI responses are validated before rendering; failed / malformed responses surface an error state, not partial cards |  |  | Covered by `ai-malformed-response` and `ai-empty-response` rows. | Yes |
| `guardrail-empty-state-copy` | Scope | n/a | Inspect every empty state | No empty-state copy promises unsupported functionality |  |  | Automated check: `scripts/check_release_guardrails.py` scans `frontend/app` for banned phrases. | Yes |

## Sign-off

| Role | Name | Date | Signature / approval link |
|---|---|---|---|
| QA owner |  |  |  |
| Engineering owner |  |  |  |
| Product owner |  |  |  |

A v1 release may only ship when:

* every **Release blocker = Yes** row is `pass` or has an explicit, time-bound exception,
* `scripts/check_release_guardrails.py` exits cleanly,
* `docs/qa/scope-guardrail-signoff.md` is signed for the release,
* `docs/qa/release-blockers.md` has no open `severity = blocker` rows.
