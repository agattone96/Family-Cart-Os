# AGENTS.md – Diana Project Guidelines

## Purpose

**Diana** (Family Cart OS) is a multi-platform household inventory and meal planning system with shared family lists. This document guides autonomous agents (e.g., Codex) through safe modification workflows without requiring clarification on foundational setup.

## Project Structure

```
agattone96/Family-Cart-Os/
├── backend/              # FastAPI service (Python 3.12)
│   ├── server.py         # Entry point
│   ├── requirements.txt   # Dependencies (pytest, black, isort, flake8, mypy)
│   └── tests/            # Backend unit tests
├── frontend/             # Expo app (React Native + web export)
│   ├── app/              # File-based routing (expo-router)
│   ├── package.json      # yarn workspace
│   └── tsconfig.json     # strict: true
├── desktop/              # Electron wrapper (macOS)
│   ├── electron/         # Main process
│   ├── renderer-dist/    # Web export bundle
│   └── package.json      # electron-builder
├── apps/diana-web/       # Vite + React web app
│   ├── package.json      # npm ci / npm run dev
│   └── tsconfig.json
├── Makefile              # db + backend commands
├── docker-compose.yml    # Local postgres (5432)
├── .tool-versions        # nodejs 22.11.0, python 3.12.8
├── tsconfig.json         # Root (ES2020, strict)
├── .env.example          # Template
└── docs/                 # Developer, user, QA, release guides
```

## Setup Command

**First-time setup:**
```bash
make setup
```

Creates `.venv`, installs `backend/requirements.txt` with pytest, black, isort, flake8, mypy.

**Frontend:**
```bash
cd frontend && yarn install
```

**Web app:**
```bash
cd apps/diana-web && npm ci
```

**Database:**
```bash
make db-up
```

Starts local Docker Postgres (user: `diana`, password: `diana`, db: `diana`, port: 5432).

## Common Commands

| Command | Purpose | Context |
|---------|---------|---------|
| `make setup` | Create venv, install backend deps | Once per environment |
| `make lint` | Compile `scripts/bootstrap_workspace.py` | Pre-commit |
| `make test` | `pytest -q` (backend) | Before merge |
| `make ci` | `make lint && make test` | CI pipeline |
| `make db-up` | Start postgres container | Dev session |
| `make db-down` | Stop container | End session |
| `make db-reset` | Wipe data (destructive) | Reset local state |
| `make db-verify` | Health check on local postgres | Verify connectivity |
| `.venv/bin/python backend/server.py` | Run backend (port 8000) | Dev server |
| `cd frontend && yarn start` | Run Expo dev server | Mobile/web dev |
| `cd frontend && yarn web` | Export web (Expo web target) | Testing web platform |
| `cd frontend && yarn lint` | Lint frontend | Pre-commit |
| `cd apps/diana-web && npm run dev` | Run Vite server | Web app dev |
| `cd apps/diana-web && npm run build` | Build web app | Production |
| `npm run desktop:build` | Export web + sync to Electron | Desktop prep |
| `npm run desktop:dist:mac` | Build unsigned macOS DMG | Distribution |

## Validation Rules

**Linting & Testing:**
- `make lint` must pass (Python compile check on bootstrap script).
- `make test` must pass (pytest on backend).
- **Frontend:** `cd frontend && yarn lint` (expo lint).
- **Web app:** TypeScript strict mode enforced (tsconfig.json).

**Release Gate (v1):**
- `DATABASE_URL='...' pytest tests/ -q` must exit 0.
- `python3 scripts/check_release_guardrails.py` must exit 0.
- No open `severity = blocker` in `docs/qa/release-blockers.md`.
- QA sign-off required in `docs/qa/scope-guardrail-signoff.md`.

**Health Check:**
- Backend: `GET /health` → `{ "ok": true }` (port 8000).
- Database: `make db-verify` or `npm run db:verify` with Neon URL.

## Coding Standards

**Python (Backend):**
- Black formatting (see `backend/requirements.txt`).
- isort imports.
- flake8 linting, mypy static typing.
- pytest for unit tests.
- Keep functions small and testable.

**TypeScript (Frontend & Web):**
- Strict mode: `"strict": true` in all tsconfig.json.
- Discriminated unions, utility types.
- Component-Driven Design (Expo Router file-based routing).
- Radix UI + Tailwind for UI (see `package.json` dependencies).
- react-hook-form for forms, zod for schema validation.
- react-resizable-panels for layouts.

**General:**
- Prefer semantic commit messages.
- Update `CHANGELOG.md` under **Unreleased** for user-facing changes.
- Include screenshots for UI changes.
- Separate concerns: UI, business logic, data (clean architecture).

## Change Rules

1. **Branches & PRs:** Create focused PRs; keep diffs minimal.
2. **Database:**  
   - Schema created on app startup (migrations not yet implemented).
   - Breaking schema changes = breaking release.
3. **API Changes:**  
   - Update CORS_ALLOWED_ORIGINS in `.env` if adding new frontend origin.
   - Test against both local Postgres and Neon URL.
4. **Frontend/Desktop:**
   - Run `npm run desktop:build` after web changes before testing in Electron.
   - Test responsive layout (mobile, tablet, desktop).
5. **Testing:**  
   - Add/update tests in `backend/tests/` for backend changes.
   - Add/update tests in `tests/` for repo-level release-gate checks.
   - Ensure pytest fixtures use proper isolation (see `test_household_setup.py`).

## Environment Variable & Secrets Rules

**Backend-only (server-side):**
- `DATABASE_URL` – PostgreSQL connection string; include `?sslmode=require` for Neon.
- `ENVIRONMENT` – "development" or "production".
- `CORS_ALLOWED_ORIGINS` – CSV of allowed frontend origins.
- `OPENAI_API_KEY` – Optional; LLM integration.
- `EMERGENT_LLM_KEY` – Optional; emergent LLM service.

**Frontend-safe (never a database URL):**
- `EXPO_PUBLIC_BACKEND_URL` – Backend base URL (e.g., `http://localhost:8000`).

**Never commit:**
- Real `.env` (copy from `.env.example`).
- Private keys, tokens, database passwords.

**Local defaults (`.env.example`):**
```
DATABASE_URL="postgresql://diana:diana@localhost:5432/diana"
EXPO_PUBLIC_BACKEND_URL="http://localhost:8000"
ENVIRONMENT="development"
CORS_ALLOWED_ORIGINS="http://localhost:3000,http://localhost:8081,http://localhost:19006"
```

## Platform Limits

- **Database:** Postgres 16 (docker-compose), Neon serverless HTTP driver supported.
- **Backend:** FastAPI 0.110.1, uvicorn, Python 3.12.
- **Frontend:** Expo 54, React Native 0.81.5, yarn workspace.
- **Web App:** Vite 7, React 19.1, TypeScript 5.9.
- **Desktop:** Electron 41.5, macOS target (arm64 + x64).
- **Ports (local):** 5432 (Postgres), 8000 (backend), 8081/19006 (Expo), 3000 (Vite).

## Done Criteria

A change is **done** when:
1. Code follows standards (Black/isort for Python, strict TS for frontend).
2. Tests pass: `make ci` (backend), `cd frontend && yarn lint` (frontend).
3. Database changes do not break schema contract (or v1 release gate updated).
4. Secrets not in code; `.env` copied from `.env.example`.
5. CHANGELOG.md updated for user-facing changes.
6. Desktop change? `npm run desktop:build` succeeds.
7. PR reviewed, diffs minimal.

## Final Response Format

When a modification task completes, respond:

```
✓ Change: [brief description]
✓ Files: [list modified files]
✓ Tests: [result of make test / yarn lint]
✓ Validation: [database, health, platform-specific checks]
✓ Breaking: [Y/N + reasoning if yes]
✓ Deployment: [target platform(s): backend, frontend, desktop, web]
```

## Maintenance Notes

- **Database migrations:** Not yet implemented; schema created on startup. Treat breaking schema changes as major releases.
- **Release Gate:** v1 (pantry → AI → plan → missing → shopping list → shop) requires QA checklist + guardrail script passing + blocker resolution.
- **Monorepo:** Root Makefile + multiple package.json files. Use workspace package managers (yarn for frontend, npm for others).
- **Secrets Rotation:** Store real `DATABASE_URL`, API keys in platform secrets (e.g., Render env vars, Netlify env vars), never in repo.
- **CI/CD:** Root `package.json` scripts delegate to subdirectories. Desktop build exports web first, then syncs to Electron.
- **Future Work:** Migrations layer, schema versioning, cross-platform feature flags (docs/developer/environment.md references these).

---

**Last Updated:** 2026-05-26  
**Repo:** agattone96/Family-Cart-Os  
**For:** Codex & autonomous agents
