# Family Cart OS v1 — Known Issues

This file tracks defects and rough edges that QA has confirmed and that the
team has *consciously* decided to ship around. Anything that should hold a
release belongs in `docs/qa/release-blockers.md` instead.

## How to file a known issue

* Use the table below.
* Severity follows: `low`, `medium`, `high`. Anything `release-blocker` must be
  moved to `release-blockers.md`.
* Link the test that surfaces the issue when possible (`backend/tests/...`,
  `tests/...`).
* If the issue is later resolved, move the row to the **Resolved** section
  rather than deleting it, so we keep an audit trail.

## Open known issues

| ID | Date opened | Severity | Area | Summary | Workaround | Linked test / PR | Owner |
|---|---|---|---|---|---|---|---|
| KI-001 | 2026-05-26 | medium | App shell | Existing app exposes 4 tabs (This Week / Inventory / Lists / Settings) rather than the 5 v1 sections (Dashboard / Inventory / AI Meal Ideas / Weekly Meal Planner / Shopping List). The mapping must be sorted before a Family Cart OS v1 release. | None — affects naming/navigation only, underlying flows still usable. | `tests/test_release_guardrails.py::test_five_v1_navigation_sections_present_or_blocker` | unassigned |
| KI-002 | 2026-05-26 | medium | Inventory | `inventory_items` does not yet persist `normalized_name`, `archived_at`, `expiry_date`, `low_stock_threshold`, `category`, or `notes`. Matching falls back to raw `name`. | Compare ingredients case-insensitively in the client until backend migration lands. | `tests/test_normalized_name.py` | unassigned |
| KI-003 | 2026-05-26 | medium | AI generation | `ai_generations` table is not yet present. Generations are not auditable after the fact. | None — guardrail tests rely on the validator path only. | `tests/test_ai_response_validation.py` | unassigned |
| KI-004 | 2026-05-26 | low | Shopping mode | Optimistic / offline behaviour is not implemented; failures fall back to inline error messages. | Avoid using shopping mode without connectivity during pilot. | `docs/qa/release-blockers.md` row RB-004 | unassigned |
| KI-005 | 2026-05-26 | low | Tests | `backend/tests/test_auth_enforcement_unit.py::test_protected_endpoints_enforce_session` regex does not handle `Header(default=None)` signatures and fails locally. Not a regression from this PR — pre-existing. | Run targeted v1 tests under `tests/` instead. | n/a | unassigned |

## Resolved

| ID | Date resolved | Resolution | PR |
|---|---|---|---|

(empty)
