# Insurance Agentic Platform

Local Docker Compose platform that runs the three HTTP-facing insurance agent projects together with a shared PostgreSQL server: the Submission Extractor, the Insurance RAG Assistant (Insurance Knowledge Agent), and the Underwriting Agent. It is the orchestration layer of a five-project insurance agentic AI portfolio, wiring the services together on a shared Docker network without changing any of their internal logic.

> **Scope note:** this is a portfolio and learning project. All underwriting rules, risk scores, pricing, and insurance documents served by the underlying projects are synthetic or demonstrative.

## Services

| Service | Compose name | Local URL | Source project | Purpose |
|---|---|---|---|---|
| Submission Extractor | `submission-extractor` | http://localhost:8000 | Project 1 (`../insurance-submission-extractor`) | Extracts candidate submission data from broker text |
| Insurance Knowledge Agent | `knowledge-agent` | http://localhost:8001 | Project 3 (`../insurance-rag-assistant`) | Retrieves grounded, cited policy evidence from a local Qdrant vector store |
| Underwriting Agent | `underwriting-agent` | http://localhost:8002 | Project 4 (`../underwriting-agent`) | Orchestrates extraction, underwriting rules, risk scoring, pricing, and evidence retrieval |
| Shared PostgreSQL | `postgres` | localhost:5432 | Platform infrastructure | Isolated `extractor`, `underwriting`, and `knowledge` databases; pgvector-ready |

Project 2 (Data Analyst Agent) is a CLI-based tool and is not currently part of this Compose stack.

## Architecture

```text
                docker network (compose default)

  submission-extractor  <---- extraction request ----  underwriting-agent
  :8000                                                  :8002
                                                              |
  knowledge-agent        <---- evidence retrieval -----------'
  :8001

  postgres :5432 -- extractor (connected now), underwriting (reserved), knowledge (reserved)
```

Each service is built from its own repository via a relative build context, so this repository contains no application source code of its own — only the orchestration configuration.

```text
insurance-agentic-platform/
├── compose.yaml          # Services plus shared PostgreSQL definition
├── postgres/init/        # One-time database and role provisioning
├── .env.example          # Tracked configuration template
├── .env                  # Local secrets and overrides (never committed)
├── .gitignore            # Ignores .env, .env.*, .DS_Store, volumes/
└── volumes/              # Local bind-mount placeholder (currently empty, gitignored)
```

## Prerequisites

- Docker and Docker Compose
- The three sibling repositories checked out at the relative paths referenced in `compose.yaml`:

```text
../insurance-submission-extractor
../insurance-rag-assistant
../underwriting-agent
```

- A Groq API key (required by both the Submission Extractor and the Knowledge Agent)

## Configuration

Copy the tracked template, then replace every placeholder with a distinct, long random secret:

```bash
cp .env.example .env
```

`POSTGRES_SUPERUSER_PASSWORD` is used only to initialize PostgreSQL. Each agent uses its own role:

| Agent | Database | Login role | Current connection |
|---|---|---|---|
| Submission Extractor | `extractor` | `extractor_app` | Connected through `DATABASE_URL`; migrations run on its first write |
| Underwriting Agent | `underwriting` | `underwriting_app` | Reserved; it continues to use SQLite in this stage |
| Knowledge Agent | `knowledge` | `knowledge_app` | Reserved with the `vector` extension; it continues to use Qdrant in this stage |

The initialization script runs only on an empty `postgres_data` volume. Changing a password in
`.env` after first startup does **not** change the corresponding PostgreSQL role. For local reset
only, use `docker compose down -v`, update `.env`, then start again. This deletes every named
volume, including the RAG index and the Underwriting SQLite database.

`POSTGRES_PORT` defaults to 5432. Set it to another host port (for example 5434) if another local
PostgreSQL server already uses 5432. Containers always reach Postgres at `postgres:5432`.

Do not commit `.env`; it is excluded by `.gitignore`.

## Start

```bash
docker compose up --build
```

Run detached:

```bash
docker compose up --build -d
```

The first build downloads the multilingual embedding model used by the Knowledge Agent, so the initial `knowledge-agent` build and startup can take longer than the other two services.

## Stop

```bash
docker compose down
```

Stop and remove named volumes (this deletes PostgreSQL data, the local Qdrant index, RAG evaluation artifacts, model cache, and the underwriting SQLite database):

```bash
docker compose down -v
```

## Persisted Volumes

| Volume | Mounted in | Purpose |
|---|---|---|
| `postgres_data` | `postgres:/var/lib/postgresql/data` | Shared PostgreSQL cluster with isolated agent databases and roles |
| `underwriting_agent_data` | `underwriting-agent:/app/data` | SQLite database of submissions, decisions, reviews, and audit events (temporary until its PostgreSQL migration) |
| `rag_vector_store` | `knowledge-agent:/app/vector_store` | Local Qdrant collection of embedded policy documents |
| `rag_artifacts` | `knowledge-agent:/app/artifacts` | Retrieval evaluation reports |
| `rag_model_cache` | `knowledge-agent:/app/.cache` | Cached Hugging Face / sentence-transformers embedding model |

These are Docker-managed named volumes, distinct from the local `volumes/` folder in this repository, which is currently unused and gitignored.

## Service Startup Order

`submission-extractor` waits for PostgreSQL to pass its `pg_isready` healthcheck before starting. Its first database write applies the packaged Alembic migrations automatically. `underwriting-agent` declares `depends_on: submission-extractor` with `condition: service_started`, so Compose starts the extractor first. This only guarantees container start order, not full application readiness — there is currently no health-check-based dependency between services.

## Test the End-to-End Workflow

Once all three containers are running, call the Underwriting Agent's combined extraction-and-underwriting endpoint, which internally calls the Submission Extractor and the Knowledge Agent:

```bash
curl -i -X POST "http://127.0.0.1:8002/extract-and-underwrite" \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: platform-e2e-001" \
  -d '{
    "source_id": "SRC-PLATFORM-001",
    "source_type": "FREE_TEXT",
    "content": "We are a Montreal software company seeking cyber insurance. Annual revenue is CAD 2,000,000 and we employ 18 people.",
    "language": "en"
  }'
```

You can also check each service independently:

```bash
curl http://127.0.0.1:8000/health   # Submission Extractor
curl http://127.0.0.1:8001/health   # Knowledge Agent
curl http://127.0.0.1:8002/health   # Underwriting Agent
```

## Design Principles

- **No shared application code:** every service is built from its own independent repository; this repository only defines networking, environment wiring, and volumes.
- **HTTP service boundaries:** services communicate over the Docker network using their internal ports (for example `http://knowledge-agent:8001`), matching the same HTTP contracts used in local, non-containerized development.
- **Secrets stay local:** provider API keys are injected only through `.env`, which is never committed.
- **Isolated database ownership:** one PostgreSQL server is shared for operations, but every agent receives a separate database and login role; agents communicate through HTTP rather than each other's tables.
- **Explicit persistence:** each stateful service (PostgreSQL, Qdrant index, SQLite database, model cache) uses a named Docker volume so state survives container restarts but can be reset deliberately with `docker compose down -v`.

## Known Limitations

- Project 2 (Data Analyst Agent) is CLI-only and is not included in this Compose stack.
- There is no health-check-based `depends_on` condition, so a request to `underwriting-agent` shortly after startup may fail if `submission-extractor` or `knowledge-agent` has not finished initializing.
- There is no reverse proxy, TLS termination, or authentication layer; all ports are exposed directly on localhost.
- There is no centralized logging or tracing across the three containers.

## Roadmap

- [ ] Add health-check-based `depends_on` conditions so `underwriting-agent` waits for dependent services to be ready, not just started.
- [ ] Add Project 2 (Data Analyst Agent) as an optional service in this Compose stack.
- [ ] Add a reverse proxy (for example Caddy or Nginx) for unified routing and TLS in non-local environments.
- [ ] Add centralized logging and tracing across all containers.

## Position in the Insurance Agentic Platform

| Project | Repository | Role |
|---|---|---|
| 1 | insurance-submission-extractor | Structured submission intake and validation |
| 2 | insurance-data-analyst-agent | Controlled portfolio analytics (loss ratio, deterministic SQL); CLI only, not yet containerized here |
| 3 | insurance-rag-assistant | Insurance Knowledge Agent with grounded, cited retrieval |
| 4 | underwriting-agent | Deterministic underwriting rules, risk scoring, pricing, and evidence retrieval |
| — | insurance-agentic-platform (this repo) | Docker Compose orchestration layer for the running services |

## Recommended Technology Upgrades

| Area | Current | Recommended (2026) | Benefit |
|---|---|---|---|
| Service readiness | `depends_on: service_started` only | `depends_on` with `condition: service_healthy` backed by `/health` checks | Prevents early requests from failing while a dependency is still initializing |
| Configuration | Manual `.env` construction from README | Tracked `.env.example` with placeholders and `docker compose config` validation in CI | Faster onboarding and fewer misconfigured deployments |
| Networking | Direct localhost port exposure | Reverse proxy (Caddy or Traefik) with a single entry point | Centralized routing, TLS, and easier auth enforcement later |
| Observability | No cross-service tracing | OpenTelemetry Collector sidecar aggregating traces from all three services | End-to-end visibility into the extraction → underwriting → evidence retrieval path |
| Orchestration scope | Fixed three-service stack | Add Project 2 as an optional profile (`docker compose --profile analytics up`) | Lets the platform grow without forcing every user to run every service |

## Improvements and Next Steps

1. Add a tracked `.env.example` so the configuration section of this README becomes redundant with a runnable template instead of manual copy-paste instructions.
2. Replace `condition: service_started` with `condition: service_healthy` using each service's existing `/health` endpoint, eliminating startup-order race conditions.
3. Add an optional Compose profile for Project 2 so the full five-project portfolio can eventually be started with a single command.
4. Introduce a lightweight reverse proxy in front of the three services to prepare for a non-local deployment target.
5. Add a `docker compose config` and basic smoke-test step to CI so a broken `compose.yaml` or missing environment variable is caught before merge.

## Agentic AI Best Practices Applied Here

- **Clean orchestration boundary**: this repository contains zero business logic — it only wires together independently versioned services, keeping the agentic decision logic (Projects 1, 3, and 4) fully decoupled from deployment concerns.
- **Explicit, typed service contracts over shared state**: services communicate only through their existing HTTP APIs on the Docker network, the same contracts used in local development, avoiding hidden coupling through shared databases or file systems.
- **Secrets isolation**: provider credentials are injected exclusively through environment variables at the orchestration layer, never baked into images or committed to source control.
- **Stateful services are explicitly persisted**: the Qdrant index, SQLite database, and model cache each have a dedicated named volume, making state lifecycle (keep vs. reset via `-v`) an explicit operator decision rather than an accident of container storage.
- **Next practice to adopt**: introduce health-check-based readiness gating (`condition: service_healthy`) so the orchestration layer itself models the same fail-safe-over-fail-open principle already applied inside the Underwriting Agent's service integrations.
