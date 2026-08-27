# AutoBI Architecture

This document explains the complete pipeline and, above all, **why deterministic
analysis and LLM reasoning are kept separate**.

---

## The pipeline

```
                 ┌─────────────┐
   CSV upload ──▶│  csvio       │  size/type gate, delimiter & encoding sniff,
                 │  (parser)    │  parse-as-strings, row cap
                 └──────┬───────┘
                        ▼
                 ┌─────────────┐
                 │  profiler    │  physical type + semantic role per column,
                 │              │  domain guess, primary date/measure
                 └──────┬───────┘
                        ▼
                 ┌─────────────┐
                 │  cleaner     │  commit type conversions, normalise, safe
                 │              │  de-dupe, missing-value strategy → audit report
                 └──────┬───────┘
                        ▼
                 ┌─────────────┐
                 │  re-profile  │  the CLEANED frame, so types are now real
                 └──────┬───────┘
                        ▼
        ┌───────────────┼────────────────┐
        ▼               ▼                 ▼
  ┌───────────┐  ┌────────────┐   ┌──────────────┐
  │ EDA engine│  │ KPI engine │   │ chart recomm.│   all read the SAME
  │ (DuckDB)  │  │            │   │ + validator  │   cleaned frame + profile
  └─────┬─────┘  └─────┬──────┘   └──────┬───────┘
        └──────────────┼─────────────────┘
                       ▼
              ┌──────────────────┐
              │  LLM semantic    │  (optional) proposes titles, KPI/chart
              │  analysis        │  intent — validated against the same rules
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │ DashboardSpec    │  Pydantic-validated, fully typed
              │ assembly         │
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │ Insights         │  deterministic baseline + LLM narration,
              │ (grounded)       │  every figure traced to a computed metric
              └────────┬─────────┘
                       ▼
              stored artifacts → API → fixed React renderer
```

Each stage reports into a `JobState`, so the frontend shows real per-step
progress rather than a spinner.

---

## Why deterministic analysis and LLM reasoning are separated

This is the central design decision of AutoBI.

### The two jobs have opposite requirements

| | Statistical computation | Semantic reasoning |
|---|---|---|
| Examples | totals, margins, correlations, growth % | "what is this dataset about?", which KPIs matter, how to phrase an insight |
| Correctness | must be exact and reproducible | judgement; several answers are reasonable |
| Failure mode | a wrong number is a silent, serious bug | a mediocre title is a cosmetic issue |
| Best tool | Python (pandas / DuckDB / SciPy) | an LLM |

An LLM is excellent at the right column, and unreliable at arithmetic over
thousands of rows. So AutoBI gives each half the job it is good at:

- **Python computes every value.** KPIs, trends, correlations, segment shares,
  anomaly scores — all calculated deterministically from the cleaned data.
- **The LLM only reasons about meaning.** It picks which metrics are worth
  showing, names the dashboard, chooses among valid charts, and narrates the
  insights — using the numbers Python already computed.

### The guarantee this buys

Because the model never emits a number:

- **It cannot hallucinate a statistic.** There is no code path where a figure
  on the dashboard came from the model.
- **Insights are grounded.** Each LLM insight must cite metrics from a
  pre-built *evidence index*. An insight referencing a metric that was never
  computed is dropped (`insights/generator.py`). That is exactly the shape of a
  hallucination, so it is filtered mechanically.
- **The product degrades gracefully.** Remove the API key and everything still
  works — deterministic rules produce the KPIs, charts and insights. The AI is
  an enhancement layer, never a dependency.

### The LLM proposes; the backend disposes

The model never writes frontend code or SQL. It returns a small, typed proposal
(`LLMSemanticResponse`, `LLMInsightResponse`) which is:

1. parsed with JSON repair (models fence, truncate, add trailing commas),
2. validated against a Pydantic schema (retry with a repair prompt on failure),
3. re-checked against the dataset — a proposed KPI or chart referencing a
   column that doesn't exist, or a chart that violates a visualisation rule, is
   rejected and replaced by the deterministic version.

The worst case of a total AI failure is a dashboard identical to the
deterministic one.

---

## Key components

### Schemas (`app/schemas`) — the backbone

Every stage communicates through Pydantic models: `DatasetProfile`,
`DataQualityReport`, `AnalysisResult`, `KPI`, `ChartSpecification`,
`FilterSpecification`, `Insight`, `DashboardSpecification`. The controlled
vocabularies (chart types, aggregations, roles) are enums the LLM must choose
from and the validator enforces. The frontend `types/index.ts` mirrors these
exactly.

### Profiling (`app/profiling`)

Type detection tries boolean → datetime → numeric → categorical/text, using
shared coercion primitives so detection and cleaning can never disagree.
Semantic roles combine a name lexicon with value evidence (cardinality, range,
distribution) and return a confidence plus the evidence — so the UI can explain
*why* a column was classified the way it was. Domain is scored against
per-domain lexicons.

### Cleaning (`app/cleaning`)

Auditable and non-destructive. Rules:

1. **Never silently destroy data** — every change appends a `CleaningAction`
   with the affected row count and a reason.
2. **Never invent numbers** — missing numeric values stay missing; aggregations
   skip them. Imputing a mean would corrupt every downstream KPI.
3. **Only commit a conversion the profiler validated** above a confidence
   threshold. Mixed date formats are parsed with a multi-format sweep so a
   file mixing `YYYY-MM-DD` and `MM/DD/YYYY` loses no rows.
4. **De-duplicate safely** — a narrow categorical table that legitimately
   repeats rows is *not* de-duplicated (which would delete most of it); it is
   flagged instead.

### Query layer (`app/analysis/query.py`) — controlled DuckDB

The LLM never writes SQL. It selects a chart *type* and column *names*; this
layer compiles those into SQL where **every identifier is checked against the
real column list and quoted, and every literal is a bound parameter**. An
attacker-controlled column name in a CSV, or a hallucinated column from the
model, can only ever produce a rejected query — never execution.

### EDA engine (`app/analysis/eda.py`)

Computes only analyses that make sense for the dataset. A dataset with no dates
gets no trend section; an all-categorical dataset still gets segment analysis.
Guards against real-world traps: partial final periods are excluded from
headline change, mixed-sign ledgers use absolute totals for share, per-unit
measures are averaged not summed.

### KPI engine (`app/kpi`)

A catalogue of KPI *patterns* (not a fixed list) is matched against the
dataset's actual columns and inferred domain. Values are computed by DuckDB;
period-over-period deltas isolate the latest complete period. A KPI whose value
cannot be computed is dropped, never shown as zero.

### Chart recommendation (`app/charts`)

Visualisation-grammar rules propose charts (date+measure → line,
category+measure → bar, small category → donut, two measures → scatter, …). A
deterministic validator then rejects anything that doesn't hold up — a pie with
too many slices, a donut of averages, a histogram of an identifier. LLM-proposed
charts pass through the identical validator.

### Rendering (frontend)

`ChartRenderer.tsx` maps each `ChartSpecification` to a fixed React/Recharts
component. There is **no per-dataset chart code** anywhere — the same renderer
draws every dashboard. Colour assignment follows the data-visualisation
guidelines: a fixed, CVD-validated categorical palette assigned in first-seen
order (so filtering never repaints surviving series), a diverging scale for
correlations, a sequential ramp for histograms, and reserved status colours that
never double as series colours.

---

## Storage & extensibility

`StorageBackend` (`app/services/storage.py`) is an interface; `LocalStorage`
implements it on the filesystem for the MVP. A PostgreSQL + object-storage
implementation can replace it without touching profiling, analysis or the API —
services depend only on the interface. Dataset ids are validated to prevent path
traversal, and datasets past the retention window are purged on startup.

The AI layer is equally pluggable: `LLMProvider` is the only vendor seam, with
`AnthropicProvider` and `OpenAIProvider` implementations selected from
configuration. Adding a provider means implementing one `complete` method.
