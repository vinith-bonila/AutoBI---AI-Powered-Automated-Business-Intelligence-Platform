# shared

Reserved for cross-cutting assets shared between backend and frontend (e.g. a
generated OpenAPI client or JSON Schema exports).

The canonical contracts today live in two hand-maintained, intentionally
mirrored places:

- `backend/app/schemas/` — Pydantic models (source of truth)
- `frontend/types/index.ts` — TypeScript mirrors

They are kept small and readable on purpose. If you change one, change the other.
