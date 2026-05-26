# Family Cart OS v1 — Scope Guardrail Sign-Off

The Family Cart OS v1 MVP is intentionally scoped to the pantry-to-shopping
loop:

```
Add food → Generate meals → Plan meals → Find missing ingredients → Build shopping list → Shop
```

This document is the formal record that the v1 release **does not** include any
of the explicitly deferred features. It must be signed before each v1 release
ships and re-affirmed after any feature merge that touches scope-sensitive UI.

## What v1 must NOT include

Sign-off confirms that the following are absent from the shipped product:

| # | Deferred feature | Confirmed absent | Notes / evidence |
|---|---|---|---|
| 1 | Request approval flow |  |  |
| 2 | Household inbox |  |  |
| 3 | Five-role permission system (Owner, Co-admin, Adult, Teen, Child) |  |  |
| 4 | Receipt scanning |  |  |
| 5 | Barcode scanning |  |  |
| 6 | Live grocery pricing |  |  |
| 7 | Coupons |  |  |
| 8 | Grocery delivery integrations |  |  |
| 9 | Nutrition tracking |  |  |
| 10 | Budget tracking |  |  |
| 11 | Multi-household switching UI |  |  |
| 12 | Templates |  |  |
| 13 | Reusable list presets |  |  |
| 14 | Activity history / audit log |  |  |
| 15 | Complex household logistics outside the pantry-to-shopping loop |  |  |

For each row, the QA owner must confirm `yes` and link the evidence (test run,
guardrail script output, screenshot, or PR review trail).

## Automated guardrail

`scripts/check_release_guardrails.py` scans the repository for in-product
strings that would imply any of the deferred features above. The script must
exit with code `0` for sign-off.

```bash
python3 scripts/check_release_guardrails.py
```

The script also enforces:

* The five v1 navigation sections exist in the app shell.
* No more than 5 primary cards are rendered on the Dashboard.
* Empty-state copy in `frontend/app/**.tsx` does not promise deferred
  functionality.

## Allowed in v1 (clarifications)

The following are intentionally permitted because they are part of the
pantry-to-shopping loop or required infrastructure:

* Owner / Member role split (only these two roles).
* Single active household per user.
* Optional plain-text copy/share of the shopping list (no third-party export).
* AI meal idea generation grounded in actual inventory.
* Soft delete via `archived_at` for inventory and checked shopping list items.

If a debate arises about scope, the source of truth is the v1 product brief
(reproduced in `docs/qa/mvp-release-checklist.md`). Anything not described
there is out of scope until explicitly added in a future story.

## Sign-off

| Role | Name | Date | Signature / approval link |
|---|---|---|---|
| QA owner |  |  |  |
| Engineering owner |  |  |  |
| Product owner |  |  |  |
| Release manager |  |  |  |

Sign-off is required for **every** v1 release. Re-sign after any merge that
modifies navigation, dashboard cards, AI generation, shopping mode, or
permission logic.
