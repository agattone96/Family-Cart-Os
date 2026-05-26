# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project aims to follow Semantic Versioning.

## Unreleased

### Added
- Repository-grade documentation under `docs/`
- GitHub issue and PR templates under `.github/`
- Family Cart OS v1 — Pantry + AI Meal Planning MVP (Tickets 1–8):
  - `backend/family_cart.py` module with the canonical ten-table
    schema, household-scoped API router mounted at `/api/v1/*`, and
    pure helpers (`normalized_name`, ingredient matching, shopping
    deduplication, AI output validation, dashboard aggregation,
    out-of-scope guardrails).
  - Swappable AI provider abstraction with a deterministic
    `StubAIProvider` for CI; production providers plug in via
    `set_default_provider`.
  - Inventory fast-add with `archived_at` soft delete and
    `normalized_name` for matching.
  - Weekly meal planner with manual + AI-sourced meals, per-ingredient
    `is_available` override, and one-action "push missing ingredients
    to shopping list" that deduplicates by `normalized_name`.
  - Shopping list + shopping-mode endpoints; one active list per
    household, optimistic-UI friendly idempotent endpoints, atomic
    finish-session archival.
  - Dashboard endpoint capped at five cards: inventory totals, today's
    meals, missing-ingredient count, shopping-list count, quick
    actions.
  - Unit tests in `backend/tests/test_family_cart_unit.py` (55
    cases) — pure helpers, schema contract, scope guardrails.
  - Developer architecture doc (`docs/developer/family-cart-architecture.md`),
    QA checklist (`docs/release/family-cart-mvp-qa-checklist.md`),
    and user-facing overview (`docs/user/family-cart-mvp.md`).

### Changed
- `backend/server.py` startup now bootstraps the Family Cart schema and
  wires the `/api/v1/*` router.
- (Add entries here as features evolve)

### Fixed
- (Add entries here as bugs are fixed)
