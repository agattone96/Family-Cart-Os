# Release Process

This project has two deployable artifacts:
- Backend API service (`backend/`) — typically deployed to Render
- Web frontend (`frontend/`) — typically deployed to Netlify (static export)

## Standard release checklist

1. Ensure `CHANGELOG.md` has an **Unreleased** section describing changes.
2. Run tests: `pytest -q`
3. Confirm environment variable matrix is accurate (`docs/developer/environment.md`).
4. Deploy backend and verify `/health` returns `{ "ok": true }`.
5. Deploy frontend and verify login + plan generation flows.
6. Create release notes from `docs/release/release-notes-template.md`.

## Family Cart OS v1 release gate

A v1 release (pantry → AI → plan → missing ingredients → shopping list →
shop) additionally requires the following before sign-off:

1. Run the QA suite:
   ```bash
   DATABASE_URL='postgresql://user:pass@localhost:5432/testdb' \
     python3 -m pytest tests/ -q
   ```
2. Run the automated guardrail script:
   ```bash
   python3 scripts/check_release_guardrails.py
   ```
3. Walk every row of `docs/qa/mvp-release-checklist.md` and record results.
4. Confirm `docs/qa/scope-guardrail-signoff.md` is signed for the release.
5. Verify `docs/qa/release-blockers.md` has no open `severity = blocker` rows
   (or that each is explicitly accepted with an exception).
6. File any new defects in `docs/qa/known-issues.md`.

A v1 release may only ship when steps 1 and 2 exit cleanly, every release
blocker is resolved or accepted, and the scope-guardrail sign-off has been
signed by QA, Engineering, and Product.

## Operational expectations

- Backend database schema is created on app startup (migrations are not yet implemented).
- Backwards-incompatible schema changes should be treated as a breaking release.
