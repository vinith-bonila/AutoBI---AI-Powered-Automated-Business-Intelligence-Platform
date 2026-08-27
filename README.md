# AutoBI — AI-Powered Automated Business Intelligence

**Turn any CSV into an intelligent, interactive dashboard.**

Upload a CSV and AutoBI does the work a data analyst normally does by hand:

```
CSV → Parse → Profile → Clean → Analyse → KPIs → Charts
    → (LLM semantics) → Dashboard spec → Validate → Interactive dashboard
```

It works on **any structured tabular dataset** — sales, e-commerce, HR,
marketing, finance, operations, customer data — and builds the dashboard that
fits *that* data, not a hardcoded template. A sales file and an HR file produce
entirely different KPIs, charts and insights from the same code path.

---

## Why it's different

**Numbers are computed, never generated.** Every KPI value, trend, correlation
and insight figure is calculated deterministically in Python (pandas + DuckDB).
The optional LLM only *chooses* which metrics matter and *narrates* them in
plain English — it never produces a number. An AI-written insight that cites a
metric the engine did not compute is discarded automatically.

**It runs fully without an API key.** With no LLM configured, AutoBI still
profiles, cleans, analyses and visualises the data and writes rule-based
insights. Add a provider to enrich the wording; the underlying numbers are
identical.

**Cleaning is transparent and non-destructive.** Every transformation is logged
with the rows it touched and the reason. Missing numeric values are excluded
from aggregations, never silently imputed.

---

## Platform features (interactive dashboard)

Beyond generating the dashboard, AutoBI is a customizable BI workspace:

- **Customize** — a side panel to change theme (Light / Dark / Professional),
  pick a colour palette (7 professional presets) or override individual colours,
  choose a layout (2-col / 3-col / compact / wide / executive), and
  show/hide/reorder/reformat KPIs. Charts recolour live.
- **Time aggregation** — when a date column exists, switch Daily / Weekly /
  Monthly / Quarterly / Yearly; the backend re-buckets the underlying data
  (`DATE_TRUNC`), it is not a relabel.
- **Change any chart** — a `⋮` menu on every chart to switch its type
  (only combinations that are valid for the data are offered), change X/Y axes
  or aggregation, duplicate, remove, or reorder (drag-and-drop *and* accessible
  buttons).
- **Add visualization** — build a chart with no code: pick type, axes and
  aggregation and see a live preview before adding it.
- **Ask your data** — a chat panel that answers natural-language questions.
  The answer is computed deterministically first (DuckDB), then optionally
  phrased by the LLM; every answer shows the supporting metrics and a chart.
  The model never invents a number.
- **Export** — PNG, PDF, cleaned CSV, Excel workbook, analysis report
  (Markdown), data dictionary, reloadable dashboard config (JSON), and a
  Power BI-ready **semantic model**.
- **Persistent, portable state** — all customization lives in one central
  `DashboardConfig`, saved per-dataset and serialised by the config export, so
  a dashboard can be saved, reloaded and (later) shared.

## Analysis features

- **Dataset profiling** — row/column counts, per-column types, missing %,
  cardinality, duplicates, and a *semantic role* for every column (currency,
  quantity, percentage, dimension, time, identifier, …) inferred from both the
  name and the actual values, each with the evidence that produced it.
- **Automated cleaning** — currency/percent parsing, mixed-format date parsing,
  numeric-string coercion, whitespace and casing normalisation, safe
  de-duplication, with a full audit report and a 0–100 quality score.
- **EDA engine** — descriptive statistics, correlations (with significance),
  time trends with growth rates and period-over-period change, segment
  analysis with concentration/Gini, outliers (IQR) and time-series anomalies.
- **KPI discovery** — rule patterns matched against the dataset's actual
  columns and inferred domain: profit margin, AOV, conversion rate, ROAS,
  attrition rate, and more — chosen dynamically, never from a fixed list.
- **Chart recommendation** — a visualisation-grammar rule set proposes charts,
  and a deterministic validator rejects any that don't make sense (a pie of
  4,000 ids, a line chart without a date axis, a donut of averages).
- **Interactive dashboard** — KPI cards, 6–9 charts, auto-generated filters,
  and an AI Insights section. Filters update every chart and KPI live, with no
  page reload.
- **Data quality view** — the full cleaning log, missing-value strategy,
  column profile and a preview of the cleaned data.
- **Configurable AI provider** — Anthropic or OpenAI-compatible, selected
  entirely through environment variables. Keys never reach the frontend.

---

## Tech stack

| Layer     | Choices |
|-----------|---------|
| Frontend  | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Recharts |
| Backend   | Python 3.13, FastAPI, pandas, NumPy, SciPy, DuckDB, Pydantic v2 |
| AI        | Provider-agnostic abstraction (Anthropic / OpenAI-compatible), configurable |
| Storage   | Local filesystem for the MVP, behind a `StorageBackend` interface |

---

## Project structure

```
backend/
  app/
    api/          FastAPI routes + dependencies (no business logic)
    ai/           provider-agnostic LLM client, prompts, JSON repair
    analysis/     DuckDB query layer + EDA engine
    charts/       chart recommendation + deterministic validator
    cleaning/     auditable cleaning pipeline
    insights/     deterministic insights + LLM narration
    kpi/          KPI catalogue + discovery/calculation engine
    profiling/    type detection + semantic role inference
    schemas/      Pydantic contracts (the system's backbone)
    services/     storage, pipeline orchestration, dashboard assembly
    utils/        CSV I/O, coercion, formatting, serialization
  tests/          201 tests across every stage
data/
  generate_samples.py   creates realistic messy test datasets
  samples/              generated CSVs
frontend/
  app/            landing, analyze (progress), dashboard pages
  components/     ui, upload, dashboard, charts, insights, quality
  lib/            typed API client, formatting, chart theme
  types/          TypeScript mirrors of the backend contracts
docs/
  ARCHITECTURE.md
```

---

## Installation

Prerequisites: **Python 3.11+** (3.13 recommended) and **Node.js 20+**.

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env        # optional — sensible defaults work as-is
```

### 2. Generate sample datasets (optional, for testing)

```bash
python ../data/generate_samples.py
```

### 3. Frontend

```bash
cd ../frontend
npm install
cp .env.local.example .env.local   # points at http://127.0.0.1:8000
```

---

## Running locally

Open two terminals.

**Terminal 1 — backend** (from `backend/`, venv activated):

```bash
uvicorn app.main:app --reload --port 8000
```

API docs are then at http://127.0.0.1:8000/docs.

**Terminal 2 — frontend** (from `frontend/`):

```bash
npm run dev
```

Open **http://localhost:3000**, drop in a CSV (try the ones in
`data/samples/`), watch the analysis run, and explore the dashboard.

---

## Environment variables

All backend configuration lives in `backend/.env` (see `.env.example`). Every
value has a working default — the app runs with no `.env` at all.

| Variable | Default | Meaning |
|----------|---------|---------|
| `AI_PROVIDER` | `none` | `anthropic`, `openai`, or `none` (deterministic mode) |
| `AI_MODEL` | `claude-sonnet-5` | Model id for the chosen provider |
| `AI_API_KEY` | *(empty)* | Provider API key. **Never exposed to the frontend.** |
| `AI_BASE_URL` | *(empty)* | Override for OpenAI-compatible endpoints |
| `AI_MAX_RETRIES` | `2` | Repair-and-retry attempts on invalid AI JSON |
| `MAX_UPLOAD_BYTES` | `104857600` | Upload size limit (100 MB) |
| `MAX_ROWS_ANALYZED` | `1000000` | Row cap per dataset |
| `RETENTION_HOURS` | `24` | Datasets older than this are purged on startup |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Allowed frontend origins |

The frontend reads a single public variable, `NEXT_PUBLIC_API_URL` (in
`frontend/.env.local`).

### Enabling AI

```bash
# backend/.env
AI_PROVIDER=anthropic
AI_MODEL=claude-sonnet-5
AI_API_KEY=sk-ant-...
```

or an OpenAI-compatible endpoint:

```bash
AI_PROVIDER=openai
AI_MODEL=gpt-4o-mini
AI_API_KEY=sk-...
AI_BASE_URL=https://api.openai.com/v1
```

---

## API

| Method & path | Purpose |
|---------------|---------|
| `POST /api/datasets` | Upload a CSV; returns a `dataset_id` and starts analysis |
| `GET /api/datasets/{id}/status` | Poll pipeline progress (per-step) |
| `GET /api/datasets/{id}` | Full dashboard payload (spec, profile, quality, analysis) |
| `POST /api/datasets/{id}/charts/{chart_id}/data` | Chart data under a set of filters |
| `POST /api/datasets/{id}/kpis` | Recompute KPI values under filters |
| `GET /api/datasets/{id}/preview` | Sample of the cleaned data |
| `GET /api/datasets` | List analysed datasets |
| `GET /api/datasets/{id}/fields` | Column metadata for the customization UI |
| `POST /api/datasets/{id}/charts/execute` | Run an ad-hoc (switched/custom) chart |
| `POST /api/datasets/{id}/charts/validate` | Validate a chart & list valid types |
| `POST /api/datasets/{id}/ask` | Grounded natural-language Q&A |
| `GET /api/datasets/{id}/export/{kind}` | Export (cleaned-csv, excel, report, config, semantic-model, data-dictionary) |
| `DELETE /api/datasets/{id}` | Delete a dataset |
| `GET /api/config` | Capability flags for the frontend (never the API key) |
| `GET /api/health` | Liveness check |

Interactive OpenAPI docs: `/docs`.

---

## Example datasets

`data/generate_samples.py` creates four realistic, deliberately *messy*
datasets (currency symbols, percent strings, mixed date formats, duplicates,
missing values, inconsistent casing) plus edge cases:

- `ecommerce_sales.csv` — ~20k orders → domain **sales**, KPIs like Total
  Revenue, Profit Margin, AOV, Return Rate.
- `hr_employees.csv` — 2.4k employees → domain **hr**, KPIs like Headcount,
  Attrition Rate, Total Salary.
- `marketing_campaigns.csv` → domain **marketing**, KPIs like Conversion Rate,
  ROAS, Cost per Acquisition.
- `financial_transactions.csv` → domain **finance**, KPIs like Total Amount,
  Effective Tax Rate.

Uploading each produces a visibly different dashboard — proof the system reads
the data rather than templating it.

---

## Testing

```bash
cd backend
pytest                 # 201 tests
```

Coverage spans CSV parsing, profiling, cleaning, the query layer (including SQL
injection attempts), KPI calculation, chart validation, dashboard-spec
validation, the AI JSON-repair/retry/fallback path, insight grounding, and the
full API surface against the real pipeline. Edge cases covered include empty
columns, all-categorical and all-numeric datasets, datasets with no dates,
three-row datasets, and malformed input.

---

## Design decisions

- **Deterministic core, AI at the edges.** See `docs/ARCHITECTURE.md` for the
  full rationale. In short: statistics are reproducible and must be correct, so
  Python owns them; naming, ranking and narration benefit from judgement, so
  the LLM contributes there — behind validation.
- **The dashboard is a *specification*, not generated code.** The LLM emits a
  small, typed proposal; the backend compiles it into a validated
  `DashboardSpecification` that fixed React components render. The model never
  writes frontend or SQL.
- **Untrusted input, throughout.** Uploaded CSVs are size- and type-limited,
  parsed as strings, and every DuckDB query is built from validated column
  names with bound parameters — an attacker-controlled column name or a
  hallucinated one is rejected, never executed.
- **Re-profiling after cleaning.** The pipeline profiles the *cleaned* frame a
  second time so every downstream stage reasons about the data as it will
  actually be queried.

---

## Future improvements

- Persist datasets and dashboards in PostgreSQL + object storage (the
  `StorageBackend` interface is already the seam for this).
- Authentication and multi-user workspaces.
- Saved views and shareable dashboard links.
- More chart types (funnel, map/choropleth, box plot) and drill-down.
- Natural-language "ask a question of your data" over the controlled query
  layer.
- Streaming progress over WebSockets instead of polling.
- Export to PDF / scheduled email digests.

---

## License

Provided as a portfolio / reference implementation.
