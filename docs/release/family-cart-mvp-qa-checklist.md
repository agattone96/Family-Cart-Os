# Family Cart OS v1 — End-to-End QA Checklist

Ticket 8 requires the MVP core loop to be validated end-to-end and the
out-of-scope guardrails to be signed off **before** every release.  This
file is the formal checklist — copy it into the release ticket, tick each
box, and attach evidence (screenshot or short clip) where indicated.

Reuse this document across releases.  Do not delete failed boxes —
record the failure and link to the bug ticket so reviewers can see the
fix in the next pass.

---

## 1. App shell & household scope (Ticket 7)

- [ ] First-login user is prompted to create or join a household.
- [ ] Creating a household automatically assigns the **Owner** role.
- [ ] All five sections render: Dashboard, Inventory, AI Meal Ideas,
      Weekly Meal Planner, Shopping List.
- [ ] Each section has an empty state that explains what it does and
      does **not** imply unsupported functionality.
- [ ] Navigation is reachable with one tap on mobile (bottom nav or
      equivalent).
- [ ] Cross-household read attempt returns HTTP 403/404 (verify via
      curl with a foreign household id).

## 2. Inventory fast-add (Ticket 2)

- [ ] Add an inventory item with only `name` + `location` — no other
      required field prompts.
- [ ] Default location preselects the **last-used** location.
- [ ] Time the add: stopwatch ≤ 15 seconds on a mobile device.  Record
      the actual seconds in this checkbox.
- [ ] Optional fields (quantity, unit, category, expiry date, low-stock
      threshold, notes) save when supplied.
- [ ] Inventory list is grouped by location.
- [ ] Search by name returns the new item.
- [ ] Filters work: location, low-stock, expiring-soon.
- [ ] Editing any field persists.
- [ ] Archiving an item removes it from the active list but keeps it
      in the database (`archived_at` populated).
- [ ] `normalized_name` is populated (spot-check via API).

## 3. AI meal ideas (Ticket 3)

- [ ] With an empty pantry, generation is **blocked** with a prompt to
      add inventory first.
- [ ] With 10+ pantry items, generation returns 3 structured meals.
- [ ] Loading state is visible during generation.
- [ ] Force a failure (e.g. unset the AI key, or use the stub provider
      with corrupted payload).  UI shows an error + retry — **never**
      a broken JSON dump.
- [ ] An `ai_generations` row exists for every attempt — both
      `completed` and `failed`.  The row stores the full pantry
      snapshot in `input_snapshot`.
- [ ] Set household food preferences (likes, dislikes, allergies,
      diet style, avoided ingredients).  Regenerate.  UI displays
      "Generated using your saved food preferences".
- [ ] Save a generated meal to the planner — the saved meal stores
      `ai_generation_id`.

## 4. Weekly meal planner (Ticket 4)

- [ ] Weekly view shows meals by day and by slot.
- [ ] Slots available: breakfast, lunch, dinner, snack, other.
- [ ] Add a manual meal (title required, description optional).
- [ ] Save an AI meal to a specific day + slot.
- [ ] Source label (manual vs ai_generated) is visible in meal detail.
- [ ] Meal detail shows which ingredients are available vs missing.
- [ ] Manual override of `is_available` persists across reload.
- [ ] **"Add all missing to shopping list"** adds exactly the missing
      ingredients — never duplicates an existing list item with the
      same `normalized_name`.

## 5. Shopping list + shopping mode (Ticket 5)

- [ ] Only one active list per household exists at a time.
- [ ] Manual add deduplicates by `normalized_name` (existing item is
      merged, no duplicate row).
- [ ] Each item shows its `source` (manual / missing_ingredient /
      low_stock).
- [ ] Items sourced from a meal show the meal name.
- [ ] Shopping mode is reachable from the shopping list.
- [ ] Shopping mode has large tap targets (≥ 44pt) — measure on
      mobile.
- [ ] Checked items remain visible but are struck through.
- [ ] Finishing the session archives checked items.
- [ ] Shopping mode contains **no** editing, AI generation, household
      settings or navigation distractions.
- [ ] Throttle network to 3G in DevTools — checking off items still
      responds instantly (optimistic UI), and the server syncs once
      the network returns.

## 6. Dashboard (Ticket 6)

- [ ] Dashboard is the default landing screen after login.
- [ ] Inventory total, low-stock, and expiring-soon counts are
      accurate.
- [ ] Today's meals match the planner for today.
- [ ] Missing-ingredient count matches the planner totals.
- [ ] Shopping list count matches the active list.
- [ ] Quick actions navigate to: Add pantry item, Generate meal ideas,
      View meal plan, Open shopping list.
- [ ] Dashboard renders **no more than five cards**.

## 7. Activation, conversion & retention checks (Ticket 1)

- [ ] New user can add 10+ inventory items in the first session.
- [ ] New user can generate one AI meal idea and save it to the
      planner.
- [ ] New user can convert a planner item's missing ingredients into
      shopping list items.
- [ ] Returning user (within 7 days) lands on the dashboard with all
      previous data intact.

## 8. Scope guardrail sign-off (Ticket 8)

This step is a **formal sign-off**, not an informal review.  Two
reviewers must initial each box.

- [ ] No UI element references **request approval / approval inbox**.
- [ ] No UI element references **Co-admin / Adult / Teen / Child**
      roles.
- [ ] No UI element references **templates / reusable list presets**.
- [ ] No UI element references **activity history / audit log**.
- [ ] No UI element references **receipt scan / barcode scan**.
- [ ] No UI element references **live pricing / coupons / delivery**.
- [ ] No UI element references **calorie / macro / budget tracking**.
- [ ] No UI element references **multi-household switcher**.

For automated coverage, the backend unit-test suite includes
`TestScopeGuardrails::test_flags_out_of_scope_terms` which exercises the
guardrail string list against arbitrary UI copy.  Wire it into a CI job
that points at the rendered copy bundle before release.

## 9. Sign-off block

| Role              | Name | Date | Notes |
|-------------------|------|------|-------|
| Engineering lead  |      |      |       |
| Product reviewer  |      |      |       |
| QA reviewer       |      |      |       |

Attach exported issues, screenshots and the recorded fast-add timing to
the release ticket.
