# Deployment

## Frontend

The frontend is deployed on Vercel (Expo web build).

### Frontend build settings

- Base directory: `frontend`
- Build command: `npx expo export --platform web`
- Publish directory: `dist`
- SPA fallback/rewrites configured via `vercel.json`

### Required Vercel environment variable

- `EXPO_PUBLIC_BACKEND_URL=https://<your-render-service>.onrender.com`

The web bundle will fail auth and API requests if `EXPO_PUBLIC_BACKEND_URL` is missing.

### Vercel environment variable update steps (Expo frontend)

1. Open Vercel Dashboard.
2. Select the Expo frontend project.
3. Go to Settings.
4. Open Environment Variables.
5. Find `EXPO_PUBLIC_BACKEND_URL`.
6. Replace the current value with the actual backend API HTTPS URL.
7. Select the correct environments:
   - Production
   - Preview, if preview deployments should call the same or staging backend
   - Development, if Vercel development env pull is used
8. Save changes.
9. Redeploy the frontend project because updated environment variables do not change already-built deployments.

Important:
- Do not put `DATABASE_URL` in the frontend Vercel project.
- If `DATABASE_URL` is needed, it belongs in backend hosting provider environment variables only.
- If backend and frontend are separate Vercel projects, `DATABASE_URL` belongs only in the backend project.
- If backend is hosted on Render/Railway/Fly/etc., use that service's public HTTPS URL for `EXPO_PUBLIC_BACKEND_URL`.

## Backend

The backend is prepared for Render using [`render.yaml`](./render.yaml).

### Render web service settings

- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`

### Required Render environment variables

- `DATABASE_URL` = Neon Postgres connection string
- `OPENAI_API_KEY`
- `ENVIRONMENT=production`
- `CORS_ALLOWED_ORIGINS=https://YOUR-VERCEL-FRONTEND.vercel.app`

### Optional

- `PYTHON_VERSION` if you want to pin the runtime in Render

## Database

Use Neon Postgres for production auth and storage.

1. Create a Neon project and database.
2. Copy the Neon connection string.
3. Add it to Render as `DATABASE_URL`.
4. Ensure the connection string includes `sslmode=require`.

Example server-side usage:

```ts
// app/actions.ts
"use server";
import { neon } from "@neondatabase/serverless";

export async function getData() {
  const sql = neon(process.env.DATABASE_URL!);
  const data = await sql`...`;
  return data;
}


## Backend (Fly.io explicit config, no add-ons)

This backend uses **Neon PostgreSQL**, so do **not** use Fly Managed Postgres.
This app does **not** require object storage, so do **not** enable Tigris (and do not run `flyctl ext tigris create`).

Use CLI deploy from `backend/` with explicit config to avoid Fly UI add-on guessing.

- Working directory: `backend`
- Config path from repo root: `backend/fly.toml`
- Config path inside backend dir: `fly.toml`
- Internal port: `8000`

### Fly deploy commands (from repo root)

```zsh
cd backend

fly auth login

fly apps create diana-backend --org personal

fly secrets set DATABASE_URL='PASTE_REAL_NEON_DATABASE_URL_HERE'
fly secrets set ENVIRONMENT='production'
fly secrets set CORS_ALLOWED_ORIGINS='https://diana-git-codex-fix-expo-frontend-environ-15f503-allis-projects.vercel.app'

# Optional only if enabled backend features need them
# fly secrets set OPENAI_API_KEY='PASTE_REAL_KEY_HERE'
# fly secrets set EMERGENT_LLM_KEY='PASTE_REAL_KEY_HERE'

fly secrets list

fly deploy -a diana-backend

fly status -a diana-backend

fly logs -a diana-backend

curl https://diana-backend.fly.dev/health
```

Expected:

```json
{"ok":true}
```

### Vercel frontend update

Set in Vercel frontend project:

- `EXPO_PUBLIC_BACKEND_URL=https://diana-backend.fly.dev`

Ensure this is **not** set in Vercel frontend:

- `DATABASE_URL`

Redeploy Vercel frontend after env updates.
