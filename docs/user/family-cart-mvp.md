# Family Cart OS — Pantry + AI Meal Planning (v1)

Family Cart helps your household answer one question: **"What can we
make with what we already have, and what do we need to buy?"**

The core loop is:

1. Track what's in your **pantry, fridge, and freezer**.
2. Ask the AI for **meal ideas** grounded in your current inventory.
3. Drop the ones you like onto your **weekly meal plan**.
4. See **missing ingredients** for each meal at a glance.
5. Push them to your **shopping list** in one tap.
6. Switch to **shopping mode** at the store — big buttons, no
   distractions, works on a flaky connection.

## App shell

Five sections are reachable from the bottom navigation:

| Section              | What it does                                   |
|----------------------|------------------------------------------------|
| Dashboard            | Inventory health, today's meals, quick actions |
| Inventory            | Pantry / fridge / freezer items                |
| AI Meal Ideas        | Generate meals from your current inventory     |
| Weekly Meal Planner  | Plan meals by day and slot                     |
| Shopping List        | Active list + shopping mode                    |

A first-time user is prompted to **create or join a household**.  The
creator becomes the household **Owner** automatically; everyone else
joins as a **Member**.

## Inventory fast-add

Adding an item only requires a name and a location (pantry, fridge,
freezer).  Everything else — quantity, unit, category, expiry date,
low-stock threshold, notes — is optional.  The default location
preselects whatever you used last.

Items at or below the low-stock threshold appear flagged on the
dashboard.  Items with an expiry date within the next seven days are
flagged as "expiring soon".

## AI meal ideas

The AI request always sends:

- The full pantry snapshot at the time of the request.
- Your household food preferences (likes, dislikes, allergies,
  diet style, avoided ingredients).
- The number of meals you want and any slot preferences.
- An optional prompt and "quick meals only" / "use mostly what I have"
  toggles.

If preferences are saved, the UI labels the result with
**"Generated using your saved food preferences"**.  Allergies trigger a
disclaimer — Family Cart does not give medical advice.

Every generation creates a record in `ai_generations` that includes the
full pantry snapshot, so a household can review exactly what the AI
saw.

## Weekly meal planner

The planner shows breakfast / lunch / dinner / snack / other slots for
each day.  You can add a manual meal or save an AI suggestion to any
slot.  Meals carry their source (manual or AI) plus a reference to the
generation that produced them.

Each meal lists the ingredients that **are already available** in your
inventory and the ones that are **missing**.  Tap a single button to
add the missing ones to your shopping list — duplicates are merged
automatically so you don't end up with two "milk" rows.

## Shopping mode

Tap "Start shopping" from the shopping list to enter shopping mode:

- Large tap targets, optimistic UI, optional grouping by category.
- Checking off an item strikes it through but keeps it visible until
  you finish the session.
- Finish the session and checked items are archived.
- Works under poor connectivity — actions sync as soon as the network
  returns.

## What v1 does **not** include

To keep the MVP focused, v1 deliberately leaves the following out:

- Request approval flow.
- Five-role permission system (Co-admin, Adult, Teen, Child).
- Templates / reusable list presets.
- Activity history.
- Receipt or barcode scanning.
- Live pricing, coupons, delivery integrations.
- Nutrition, calorie, macro or budget tracking.
- Multi-household switching UI (the schema supports it, but v1 does
  not expose it).

These are tracked separately and may come in a future release.
