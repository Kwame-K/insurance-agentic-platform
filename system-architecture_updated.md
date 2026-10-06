# System Architecture

## Purpose

This document describes the architecture of the **Insurance Agentic Platform**, the Docker Compose orchestration layer for the insurance agentic AI portfolio.

Unlike Projects 1, 3, and 4, this repository contains no application source code. It exists solely to build and run the Submission Extractor, the Insurance Knowledge Agent (RAG Assistant), and the Underwriting Agent together with a shared PostgreSQL server on a common Docker network, wiring their existing HTTP contracts and environment configuration without modifying any internal logic.

Persistence is being migrated to PostgreSQL one agent at a time. The Submission Extractor and Underwriting Agent are connected to isolated PostgreSQL databases; the Knowledge Agent still uses local Qdrant.

This is a portfolio and learning project. All underwriting rules, risk scores, pricing, and insurance documents served by the underlying services are synthetic or demonstrative.

## Design Goals

- **Zero business logic here:** the platform repository only expresses networking, environment variables, build contexts, and volumes; it must never contain rules, prompts, or domain code.
- **Preserve existing HTTP contracts:** each service is reached through the same API it exposes in local, non-containerized development — only the hostname changes, from `127.0.0.1` to the Compose service name.
- **Independent versioning:** each service is built from its own sibling repository, so Projects 1, 3, and 4 can evolve, be tested, and be released independently of this orchestration layer.
- **Explicit persistence boundaries:** every stateful service gets a dedicated named Docker volume so state survives restarts but can be reset deliberately.
- **Isolated database ownership:** one PostgreSQL server is shared for operations, but each agent gets its own database and its own login role (`extractor_app`, `underwriting_app`, `knowledge_app`), with `CONNECT` revoked from `PUBLIC`, so no agent can read another agent's data.
- **Incremental migration:** the Extractor applies Alembic migrations on its first database write (`DATABASE_AUTO_MIGRATE=true`) and the Underwriting Agent applies them at startup; the platform only provisions databases and roles.
- **Secrets isolated at the edge:** provider API keys and database passwords are injected only through environment variables at the Compose layer, never baked into any image.

## High-Level Architecture

```mermaid
flowchart TD
    subgraph DockerNetwork [Docker Compose Network]
        P[postgres<br/>pgvector/pgvector:pg17<br/>:5432]
        A[submission-extractor<br/>build: ../insurance-submission-extractor<br/>:8000]
        B[knowledge-agent<br/>build: ../insurance-rag-assistant<br/>:8001]
        C[underwriting-agent<br/>build: ../underwriting-agent<br/>:8002]
    end

    Client[External client / curl] -->|POST /extract-and-underwrite| C
    Client -->|POST /v1/retrieve-evidence| B
    Client -->|POST /v1/extract-submission| A

    C -->|depends_on: service_started| A
    C -->|HTTP: http://submission-extractor:8000| A
    C -->|HTTP: http://knowledge-agent:8001| B

    B --> D[(rag_vector_store volume<br/>local Qdrant)]
    B --> E[(rag_artifacts volume)]
    B --> F[(rag_model_cache volume<br/>HF / sentence-transformers)]
    A -->|DATABASE_URL: extractor_app| P
    C -->|DATABASE_URL: underwriting_app| P
    P --> H[(postgres_data volume<br/>databases: extractor, underwriting, knowledge)]
    A -->|depends_on: service_healthy| P
    C -->|depends_on: service_healthy| P
```

The `extractor` and `underwriting` databases are in use today. The `knowledge` database and its role are provisioned for a later pgvector migration.

Each box in the Docker network is an independently built image from a sibling repository's own `Dockerfile`. This repository defines only the arrows: which service talks to which, on which port, with which environment variables and volumes.

## Main Components

| File | Responsibility |
|---|---|
| `compose.yaml` | Declares PostgreSQL and the three agent services, their build contexts, environment variables, ports, volumes, and the `depends_on` relationships |
| `.env` | Local, untracked secrets and overrides (Groq/Gemini API keys, model names, timeouts, PostgreSQL passwords) |
| `.env.example` | Tracked template listing every required variable with placeholder values |
| `postgres/init/` | One-time provisioning scripts that create the three databases and roles, revoke `PUBLIC` access, and enable `vector` in `knowledge` |
| `.gitignore` | Excludes `.env`, `.env.*` (except `.env.example`), `.DS_Store`, and `volumes/` |
| `volumes/` | Local placeholder directory, currently empty and gitignored; distinct from the named Docker-managed volumes |

There is no `src/`, `tests/`, or application code in this repository by design.

## Service Definitions

| Service | Build context | Image tag | Exposed port | Depends on |
|---|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` (no build) | `pgvector/pgvector:pg17` | `${POSTGRES_PORT:-5432}:5432` | — |
| `submission-extractor` | `../insurance-submission-extractor` | `insurance-submission-extractor:platform` | `8000:8000` | `postgres` (`condition: service_healthy`) |
| `knowledge-agent` | `../insurance-rag-assistant` | `insurance-rag-assistant:platform` | `8001:8001` | — |
| `underwriting-agent` | `../underwriting-agent` | `underwriting-agent:platform` | `8002:8002` | `postgres` (`condition: service_healthy`), `submission-extractor` (`condition: service_started`) |

`knowledge-agent` has no declared dependency on `underwriting-agent`, and `underwriting-agent` calls it directly by its internal Compose hostname (`http://knowledge-agent:8001`) without a corresponding `depends_on` entry — this is a gap addressed in Extensibility below.

## Environment Variable Flow

```mermaid
flowchart LR
    A[.env<br/>local, untracked] --> B[compose.yaml<br/>variable substitution]
    B --> C[submission-extractor container<br/>LLM_PROVIDER, GROQ_API_KEY,\nGROQ_MODEL, GEMINI_API_KEY, DATABASE_URL, ...]
    B --> D[knowledge-agent container<br/>GROQ_API_KEY, GROQ_MODEL_NAME,\nHF_HOME, SENTENCE_TRANSFORMERS_HOME]
    B --> E[underwriting-agent container<br/>DATABASE_URL, SUBMISSION_EXTRACTOR_BASE_URL,\nKNOWLEDGE_AGENT_BASE_URL, timeouts]
    B --> F[postgres container<br/>POSTGRES_SUPERUSER_PASSWORD, EXTRACTOR_DB_PASSWORD,<br/>UNDERWRITING_DB_PASSWORD, KNOWLEDGE_DB_PASSWORD]
```

Database passwords are interpolated into connection URLs such as `postgresql://extractor_app:${EXTRACTOR_DB_PASSWORD}@postgres:5432/extractor`, so they must not contain URL-reserved characters (`@`, `/`, `:`, `#`, `%`). Use hexadecimal values (`openssl rand -hex 24`). Avoid `$` in any `.env` value, because Compose interpolates it.

`compose.yaml` uses `${VARIABLE:-default}` substitution throughout, so most keys have sensible defaults and only provider API keys are strictly required in `.env`.

## Request Flow: End-to-End Extraction and Underwriting

```mermaid
sequenceDiagram
    actor Client
    participant UW as underwriting-agent :8002
    participant SE as submission-extractor :8000
    participant KA as knowledge-agent :8001
    participant PG as postgres :5432

    Client->>UW: POST /extract-and-underwrite (X-Correlation-ID)
    UW->>SE: HTTP extraction call (http://submission-extractor:8000)
    SE->>PG: store extraction record (best effort)
    SE-->>UW: extraction result
    alt Extraction complete
        UW->>UW: run decision hierarchy (rules, scoring, pricing)
        UW->>KA: POST /v1/retrieve-evidence (http://knowledge-agent:8001)
        KA-->>UW: citations / retrieval status
        UW->>PG: persist submission, decision, and audit events
        UW-->>Client: UnderwritingDecision (persisted to PostgreSQL)
    else Extraction incomplete or SE unavailable
        UW-->>Client: PENDING_INFORMATION / EXTRACTION_UNAVAILABLE
    end
```

All inter-service calls stay inside the Docker network using Compose service names as hostnames; no service reaches another through `localhost` inside the containers.

## Persisted Volumes

| Volume | Mounted in | Purpose | Reset behavior |
|---|---|---|---|
| `postgres_data` | `postgres:/var/lib/postgresql/data` | Shared PostgreSQL cluster with the `extractor`, `underwriting`, and `knowledge` databases | Cleared by `docker compose down -v`; init scripts rerun only on an empty volume |
| `rag_vector_store` | `knowledge-agent:/app/vector_store` | Local Qdrant collection of embedded policy documents | Cleared by `docker compose down -v` |
| `rag_artifacts` | `knowledge-agent:/app/artifacts` | Retrieval evaluation reports | Cleared by `docker compose down -v` |
| `rag_model_cache` | `knowledge-agent:/app/.cache` | Cached embedding model weights | Cleared by `docker compose down -v`; re-download otherwise avoided on restart |

These are Docker-managed named volumes declared under the top-level `volumes:` key in `compose.yaml`, distinct from the unused local `volumes/` folder in this repository.

## Failure Handling

| Condition | Required behavior |
|---|---|
| PostgreSQL unreachable or credentials wrong when the Extractor writes a record | The Extractor logs `Could not store the extraction record in the database` and still returns the extraction result; the record is lost, so the log must be monitored |
| PostgreSQL unreachable or credentials wrong when the Underwriting Agent persists a decision | The request fails rather than returning an unpersisted decision; database availability and credentials must be monitored |
| Database password changed in `.env` after first startup | The role keeps its old password and the Extractor cannot connect; run `ALTER ROLE <role> PASSWORD '<new value>'` or reset the volume |
| Database password contains URL-reserved characters | The connection URL is parsed incorrectly and the connection fails with an `OperationalError`; regenerate the password as hexadecimal |
| `submission-extractor` container not yet ready when `underwriting-agent` starts | `depends_on: condition: service_started` only guarantees the container process started, not that its HTTP server is accepting connections; an early request may still fail |
| `knowledge-agent` unreachable from `underwriting-agent` | No `depends_on` relationship exists between them; `underwriting-agent`'s own resilience logic (empty evidence, recorded failure reason) is the only safeguard |
| Missing `GROQ_API_KEY` in `.env` | `submission-extractor` and `knowledge-agent` containers start but fail at the first LLM call; no Compose-level validation currently catches this before startup |
| `docker compose down -v` run accidentally | All persisted state (PostgreSQL data, Qdrant index, model cache) is deleted; this is an explicit, irreversible operator action |

## Security and Configuration Boundaries

```text
Tracked by Git
- compose.yaml
- .env.example
- postgres/init/ (provisioning scripts, no secrets)
- .gitignore
- README documentation

Never tracked by Git
- .env (provider API keys, model overrides, PostgreSQL passwords)
- volumes/ (local bind-mount placeholder)
- Any Docker-managed named volume content (PostgreSQL data, Qdrant index, model cache)
```

`.env.example` documents every required variable. Compose fails fast with an explicit message if a PostgreSQL password is missing, because the variables use the `${VAR:?message}` form.

## Extensibility

1. Add `condition: service_healthy` to the `underwriting-agent` -> `submission-extractor` dependency, backed by each service's existing `/health` endpoint, and add an equivalent dependency toward `knowledge-agent`.
2. Migrate the Knowledge Agent from local Qdrant to pgvector in the `knowledge` database.
3. Add Project 2 (Data Analyst Agent) as an optional Compose profile once it exposes an HTTP interface, without requiring every user to run it.
4. Add a reverse proxy (Caddy or Traefik) in front of the three services for unified routing ahead of any non-local deployment.
5. Add an OpenTelemetry Collector sidecar to aggregate traces across the three containers for the end-to-end extraction-and-underwriting path.

## Current Limitations

- No health-check-based readiness gating between services; only one `depends_on` relationship exists, and it only checks that a container process started.
- The Knowledge Agent still uses local Qdrant; the Extractor and Underwriting Agent use isolated PostgreSQL databases.
- Extraction records are written best effort: a database outage loses the record without failing the request.
- PostgreSQL has no backup or restore process; `postgres_data` is a single local volume.
- No reverse proxy, TLS termination, or authentication layer; all three ports are exposed directly on the host.
- No centralized logging or tracing across containers.
- Project 2 (Data Analyst Agent) is CLI-only and is not part of this Compose stack.
