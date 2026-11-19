# Insurance Agentic Platform

Local Docker Compose platform for four HTTP-facing projects in an insurance-agentic-AI portfolio, plus a shared PostgreSQL server:

1. Submission Extractor
2. Data Analyst Agent
3. Insurance Knowledge Agent (RAG)
4. Underwriting Agent

This repository is an orchestration layer only. It builds the sibling projects, provides networking, environment configuration, volumes, and PostgreSQL databases; it contains no domain rules, prompts, or application source code.

> **Scope note:** this is a portfolio and learning project. All underwriting rules, risk scores, pricing, data, and insurance documents are synthetic or demonstrative.

## Services

| Service | Compose name | Local URL | Source project | Purpose |
|---|---|---|---|---|
| Submission Extractor | `submission-extractor` | http://127.0.0.1:8000 | Project 1 (`../insurance-submission-extractor`) | Extracts and validates candidate submission data from broker text. |
| Data Analyst Agent | `data-analyst-agent` | http://127.0.0.1:8003 | Project 2 (`../insurance-data-analyst-agent`) | Provides controlled, read-only portfolio analytics over synthetic PostgreSQL data. |
| Insurance Knowledge Agent | `knowledge-agent` | http://127.0.0.1:8001 | Project 3 (`../insurance-rag-assistant`) | Retrieves grounded, cited policy evidence from its local Qdrant store. |
| Underwriting Agent | `underwriting-agent` | http://127.0.0.1:8002 | Project 4 (`../underwriting-agent`) | Orchestrates extraction, deterministic underwriting, risk scoring, pricing, and evidence retrieval. |
| Shared PostgreSQL | `postgres` | `localhost:5432` by default | Platform infrastructure | Hosts isolated `extractor`, `analyst`, `underwriting`, and reserved `knowledge` databases. |

## Architecture

```text
                         Docker Compose network

  submission-extractor  <---- extraction request ----  underwriting-agent
  :8000                                                  :8002
                                                              |
  knowledge-agent        <----- evidence retrieval ----------'
  :8001

  data-analyst-agent :8003 ---- deployed independently ---->
  (its direct API is available after its database is initialized)

  postgres :5432 -- extractor, analyst, underwriting, knowledge
```

The active Compose configuration connects Underwriting to the Submission Extractor and Knowledge Agent. The Data Analyst is deployed and independently usable, but it is **not yet wired into Underwriting**: `PORTFOLIO_ANALYST_BASE_URL` is not set in `compose.yaml`, so Underwriting retains its in-container default of `http://127.0.0.1:8003`. See [Known limitations](#known-limitations).

## Repository layout

```text
insurance-agentic-platform/
├── compose.yaml          # Four application services plus PostgreSQL
├── postgres/init/        # One-time database and role provisioning
├── .env.example          # Configuration template; copy locally to .env
├── .env                  # Local secrets and overrides (never committed)
├── .gitignore
└── system-architecture_updated.md  # Supplementary architecture notes
```

## Prerequisites

- Docker and Docker Compose
- The four sibling repositories at the relative paths used by `compose.yaml`:

  ```text
  ../insurance-submission-extractor
  ../insurance-data-analyst-agent
  ../insurance-rag-assistant
  ../underwriting-agent
  ```

- A Groq API key when using the configured Groq-backed extraction and knowledge flows.

## Configuration

Copy the tracked template, then replace every password and provider-key placeholder with an appropriate value:

```bash
cp .env.example .env
```

`ANALYST_DB_PASSWORD` is intentionally blank in the template, but is required by Compose. Set it before running any Compose command. All database passwords are interpolated into PostgreSQL URLs, so use URL-safe values (for example, `openssl rand -hex 24`).

| Agent | Database | Login role | Current use |
|---|---|---|---|
| Submission Extractor | `extractor` | `extractor_app` | Connected through `DATABASE_URL`; migration runs on first write. |
| Data Analyst Agent | `analyst` | `analyst_app` | Connected through `DATABASE_URL`; schema and synthetic data must be initialized manually (below). |
| Underwriting Agent | `underwriting` | `underwriting_app` | Connected through `DATABASE_URL`; Alembic migration runs on first persistence request. |
| Knowledge Agent | `knowledge` | `knowledge_app` | Provisioned with `vector`; the service currently uses Qdrant instead. |

The PostgreSQL initialization script runs only for an empty `postgres_data` volume. Changing a password in `.env` after the first startup does not update the database role. For local reset only, use `docker compose down -v`; this deletes PostgreSQL data, the RAG index, model cache, Analyst output artifacts, and Underwriting records.

Validate the resolved configuration before starting the platform:

```bash
docker compose config --quiet
```

## Start

### 1. Initialize PostgreSQL and the Analyst dataset

The Data Analyst API starts without running migrations or seeding its synthetic portfolio. Initialize it once before using `/v1` analytics endpoints:

```bash
docker compose up --build -d postgres
docker compose run --build --rm data-analyst-agent \
  insurance-data-analyst init-db --seed 20260904
```

The initialization command applies migrations and loads the synthetic dataset. Re-running it replaces the dataset, so do not use it against non-synthetic data.

### 2. Start all services

```bash
docker compose up --build -d
```

To observe logs in the foreground, omit `-d`.

The Knowledge Agent’s first build and startup can take longer because it downloads its multilingual embedding model.

## Stop and reset

```bash
docker compose down
```

For a full local reset, including all named volumes:

```bash
docker compose down -v
```

## Persisted volumes

| Volume | Mounted in | Purpose |
|---|---|---|
| `postgres_data` | `postgres:/var/lib/postgresql/data` | Shared PostgreSQL cluster and the four isolated databases. |
| `analyst_output` | `data-analyst-agent:/app/output` | Analyst audit artifacts and optional charts. |
| `rag_vector_store` | `knowledge-agent:/app/vector_store` | Local Qdrant collection of embedded policy documents. |
| `rag_artifacts` | `knowledge-agent:/app/artifacts` | Retrieval evaluation reports. |
| `rag_model_cache` | `knowledge-agent:/app/.cache` | Cached Hugging Face and sentence-transformers models. |

## Health checks

```bash
curl http://127.0.0.1:8000/health  # Submission Extractor
curl http://127.0.0.1:8001/health  # Knowledge Agent
curl http://127.0.0.1:8002/health  # Underwriting Agent
curl http://127.0.0.1:8003/health  # Data Analyst Agent
```

The Data Analyst health endpoint checks API liveness, not that its database has been migrated and seeded. Run the initialization step before calling its analytics endpoints.

## Test the extraction-and-underwriting flow

The combined endpoint calls the Submission Extractor and the Knowledge Agent. `persist` defaults to `false`; set it explicitly to persist a completed evaluation.

```bash
curl -i -X POST "http://127.0.0.1:8002/extract-and-underwrite" \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: platform-e2e-001" \
  -d '{{
    "source_id": "SRC-PLATFORM-001",
    "source_type": "FREE_TEXT",
    "content": "We are a Montreal software company seeking cyber insurance. Annual revenue is CAD 2,000,000 and we employ 18 people.",
    "language": "en",
    "overrides": {
      "mfa_enabled": true,
      "requested_limit_cad": 1000000,
      "requested_retention_cad": 25000
    },
    "persist": true
  }'
```

The response can still be `PENDING_INFORMATION` if the extracted submission is incomplete or requires human review; those outcomes are not persisted by this endpoint.

## Service readiness and network boundaries

- `submission-extractor`, `data-analyst-agent`, and `underwriting-agent` wait for PostgreSQL to be healthy.
- Underwriting waits only for the Extractor container to start, not for its HTTP API or the Knowledge Agent to become ready.
- Internal calls use Compose hostnames such as `http://submission-extractor:8000`, not `localhost`.
- The short `ports` syntax in `compose.yaml` publishes ports according to Docker’s host defaults. For strict local-only access, bind each published port explicitly to `127.0.0.1` or apply host firewall rules.

## Known limitations

- The Data Analyst service is deployed by default, but is not yet integrated into Underwriting because the platform does not set `PORTFOLIO_ANALYST_BASE_URL=http://data-analyst-agent:8003` or a readiness dependency. Underwriting therefore degrades its portfolio context to `UNAVAILABLE`.
- The Analyst database initialization is a manual operator step; its health check does not prove that the schema or synthetic dataset exists.
- There is no health-check-based readiness dependency from Underwriting to the Extractor, Knowledge Agent, or Data Analyst.
- The Knowledge Agent uses local Qdrant rather than the reserved PostgreSQL/pgvector database.
- There is no reverse proxy, TLS termination, authentication layer, centralized logging, distributed tracing, or PostgreSQL backup/restore process.
- `docker compose down -v` irreversibly removes all local persisted state.

## Roadmap

1. Configure Underwriting with `PORTFOLIO_ANALYST_BASE_URL=http://data-analyst-agent:8003` and a health-based dependency.
2. Automate Analyst migrations and synthetic-data initialization with an idempotent initialization job or entrypoint.
3. Add health checks for the Extractor and Knowledge Agent, then use `condition: service_healthy` for all Underwriting dependencies.
4. Add Compose configuration validation and platform smoke tests to CI.
5. Add a reverse proxy, authentication, TLS, centralized OpenTelemetry tracing, and a PostgreSQL backup/restore strategy before any non-local deployment.

## Design principles

- **Independent services:** application code remains in each sibling repository.
- **HTTP boundaries:** agents communicate through explicit HTTP contracts, not each other’s tables.
- **Database isolation:** each agent has its own database and login role; `PUBLIC` access is revoked by the initialization script.
- **Explicit state:** PostgreSQL, Qdrant, analyst artifacts, and model cache use named volumes with deliberate reset behavior.
- **Local secret handling:** credentials are injected from an untracked `.env` file, never baked into images or committed.
