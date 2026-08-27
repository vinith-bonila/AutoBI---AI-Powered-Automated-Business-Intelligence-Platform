# Deploying AutoBI

AutoBI is two services — a **FastAPI backend** (analysis engine + DuckDB) and a
**Next.js frontend**. The browser calls the backend directly, so the frontend
only needs to know the backend's public URL (`NEXT_PUBLIC_API_URL`).

Three ways to deploy, easiest first.

---

## 1. Docker Compose (self-host — one command)

The whole stack, production-built, on any machine with Docker:

```bash
docker compose up --build
```

- Frontend → http://localhost:3000
- Backend → http://localhost:8000
- Uploaded datasets persist in the `autobi-storage` volume.

To enable AI narration, create a `.env` next to `docker-compose.yml`:

```
AI_PROVIDER=anthropic
AI_MODEL=claude-sonnet-5
AI_API_KEY=sk-ant-...
```

For a real server with a domain, set `NEXT_PUBLIC_API_URL` to your backend's
public URL and `CORS_ORIGINS` to your frontend's URL before building:

```bash
NEXT_PUBLIC_API_URL=https://api.example.com \
CORS_ORIGINS=https://app.example.com \
docker compose up --build -d
```

Put a reverse proxy (Caddy/Nginx) in front for TLS.

---

## 2. Managed platform (Render.com)

`render.yaml` in the repo root describes both services. Push the repo to
GitHub, then in Render: **New → Blueprint → pick the repo**. Render builds both
Docker images.

After the first deploy:
1. Copy the backend service URL (e.g. `https://autobi-backend.onrender.com`).
2. Set the frontend's `NEXT_PUBLIC_API_URL` to that URL and redeploy the
   frontend (its public URL is baked at build time).
3. Set the backend's `CORS_ORIGINS` to the frontend URL (replace the initial
   `*`) and redeploy.
4. Optionally set `AI_PROVIDER` + `AI_API_KEY` on the backend for AI narration.

The same shape works on Railway, Fly.io, or any Docker host.

---

## 3. Split hosting (Vercel frontend + container backend)

**Frontend on Vercel** — import the repo, set the project root to `frontend/`,
and add an environment variable `NEXT_PUBLIC_API_URL` = your backend URL. Vercel
builds and hosts the Next.js app.

**Backend on Render / Railway / Fly** — deploy `backend/` from its Dockerfile,
mount a disk at `/app/storage`, and set `CORS_ORIGINS` to your Vercel URL.

---

## Environment variables

### Backend

| Variable | Default | Purpose |
|----------|---------|---------|
| `CORS_ORIGINS` | `http://localhost:3000,...` | Allowed browser origins; `*` allows any (loosen for the first deploy, then tighten) |
| `STORAGE_DIR` | `backend/storage` | Where uploaded/cleaned datasets live — mount a volume here |
| `MAX_UPLOAD_BYTES` | `104857600` (100 MB) | Upload size cap |
| `RETENTION_HOURS` | `24` | Datasets older than this are purged on boot |
| `AI_PROVIDER` | `none` | `anthropic` \| `openai` \| `none` |
| `AI_MODEL` | `claude-sonnet-5` | Model id |
| `AI_API_KEY` | — | Provider key (never exposed to the browser) |
| `AI_BASE_URL` | — | Override for OpenAI-compatible endpoints |

### Frontend

| Variable | Default | Purpose |
|----------|---------|---------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend origin the **browser** calls (baked at build time) |

---

## Production notes

- **AI is optional.** With `AI_PROVIDER=none` the platform is fully functional
  on its deterministic engine — nothing is sent to any third party.
- **Storage is local by design (MVP).** `StorageBackend` is an interface; a
  PostgreSQL/S3 implementation can replace `LocalStorage` without touching the
  rest of the app. Mount a persistent volume at `STORAGE_DIR` so datasets
  survive restarts.
- **Secrets never reach the browser.** The API key lives only in the backend
  process; `/api/config` exposes capability flags, never the key.
- **Scaling:** the backend holds an in-memory job tracker and dataset cache, so
  run a single replica per storage volume for the MVP. The `JobTracker` and
  `StorageBackend` interfaces are the seams to swap in Redis/object storage for
  horizontal scaling.
