# Deployment

## Frontend

The frontend is deployed on Netlify.

### Netlify settings

- Base directory: `frontend`
- Build command: `npx expo export --platform web`
- Publish directory: `dist`
- Redirect rule: `/.netlify/identity/* -> /.netlify/identity/:splat (200)`
- SPA fallback: `/* -> /index.html (200)`

### Required Netlify environment variable

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
