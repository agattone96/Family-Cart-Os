# Environment and Configuration

This project uses two categories of environment variables:
- **server-only**: must never be embedded in frontend builds
- **frontend-safe**: can be compiled into the Expo app (prefixed with `EXPO_PUBLIC_`)

## Backend (`backend/.env`)

Required:
- `DATABASE_URL` — Postgres connection string (include `sslmode=require` for Neon)

AI features (at least one provider path must be configured):
- `OPENAI_API_KEY` — used for OpenAI Responses API requests
- `EMERGENT_LLM_KEY` — used by `emergentintegrations` for chat + image extraction

Optional:
- `OPENAI_PLANNER_MODEL` — defaults to `gpt-5.1` in code

## Frontend (`frontend/.env`)

Required:
- `EXPO_PUBLIC_BACKEND_URL` — frontend-safe backend API base URL.
  - Local development example: `http://localhost:8000`
  - Production example: `https://YOUR_BACKEND_API_HOST`
  - Must not be a database URL (`postgres://`, `postgresql://`, `mongodb://`, `mongodb+srv://`, `mysql://`)

The frontend calls `${EXPO_PUBLIC_BACKEND_URL}/api/*` and uses Bearer token auth.

## Example variable separation

Frontend-only (Expo client bundle):

```dotenv
EXPO_PUBLIC_BACKEND_URL=http://localhost:8000
```

Frontend production (Vercel build):

```dotenv
EXPO_PUBLIC_BACKEND_URL=https://YOUR_BACKEND_API_HOST
```

Backend-only runtime:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DB_NAME
```

`DATABASE_URL` must never be exposed to frontend code or `EXPO_PUBLIC_*` variables.
