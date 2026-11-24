# Insurance Agentic Platform

Local Docker Compose platform for six insurance applications and a shared PostgreSQL server. It brings together submission extraction, portfolio analytics, documentary evidence retrieval, underwriting, broker email intake, and a Streamlit console.

This repository is the orchestration layer. Application code and underwriting rules live in the sibling repositories. This repository provides builds, networking, environment configuration, database provisioning, and persistent volumes.

> **Scope:** This is a local portfolio and learning project. The underwriting rules, risk scores, pricing indications, and demonstration data are synthetic. The stack is not intended for production use or real underwriting decisions.

## Services

| Service | Compose name | Local address | Source repository | Purpose |
|---|---|---|---|---|
| Submission Extractor | `submission-extractor` | `http://127.0.0.1:8000` | [insurance-submission-extractor](https://github.com/Kwame-K/insurance-submission-extractor) | Extracts and validates candidate fields from submission text. |
| Data Analyst Agent | `data-analyst-agent` | `http://127.0.0.1:8003` | [insurance-data-analyst-agent](https://github.com/Kwame-K/insurance-data-analyst-agent) | Computes deterministic metrics over a synthetic insurance portfolio. |
| Insurance Knowledge Agent | `knowledge-agent` | `http://127.0.0.1:8001` | [insurance-rag-assistant](https://github.com/Kwame-K/insurance-rag-assistant) | Retrieves documentary evidence and citations from its local Qdrant index. |
| Underwriting Agent | `underwriting-agent` | `http://127.0.0.1:8002` | [underwriting-agent](https://github.com/Kwame-K/underwriting-agent) | Applies deterministic underwriting rules, scores risk, produces a synthetic pricing indication, and supports decision review. |
| Email Intake | `email-intake` | `http://127.0.0.1:8004` | [insurance-email-intake](https://github.com/Kwame-K/insurance-email-intake) | Accepts broker email content and forwards it to the Underwriting Agent. |
| Underwriting UI | `underwriting-ui` | `http://127.0.0.1:8501` | [insurance-underwriting-ui](https://github.com/Kwame-K/insurance-underwriting-ui) | Provides a Streamlit console for email intake, decision details, and human review. |
| Shared PostgreSQL | `postgres` | `localhost:5432` by default | Platform infrastructure | Hosts separate `extractor`, `analyst`, `underwriting`, and reserved `knowledge` databases. |

The local addresses above are for clients on the host. Containers call each other by Compose service name.

## Architecture

```text
underwriting-ui :8501 ──► email-intake :8004 ──► underwriting-agent :8002
        └─────────────────────────────────────►         │
                                                        ├──► submission-extractor :8000
                                                        ├──► knowledge-agent :8001
                                                        └──► data-analyst-agent :8003

postgres :5432 ──► extractor, analyst, underwriting, and reserved knowledge databases
```

The Underwriting Agent calls the Submission Extractor when processing raw submission text. It can also retrieve documentary evidence and request assistive portfolio context. That context does not change the underwriting decision, risk score, or pricing indication.

Compose sets `PORTFOLIO_ANALYST_BASE_URL=http://data-analyst-agent:8003`. The HTTP integration is configured, but Underwriting does not wait for the Analyst API to be ready or for its dataset to be initialized. If the Analyst is unavailable, the underwriting result can still be returned without portfolio context.

The Knowledge Agent uses local Qdrant in this stack. Its PostgreSQL database is provisioned but is not the active vector store.

## Repository Layout

```text
insurance-agentic-platform/
├── compose.yaml                     # Six application services plus PostgreSQL
├── postgres/init/                   # Database and role provisioning
├── .env.example                     # Template for local configuration
├── .gitignore
├── system-architecture_updated.md   # Supplementary architecture notes
└── README.md
```

## Prerequisites

- Docker with the Docker Compose plugin.
- The six application repositories cloned beside this repository. The build contexts in `compose.yaml` use relative paths.
- A Groq API key for Groq-backed workflows, such as the default extraction configuration. Documentary evidence retrieval itself does not call a generation model.

Your checkout should look like this:

```text
workspace/
├── insurance-agentic-platform/
├── insurance-submission-extractor/
├── insurance-data-analyst-agent/
├── insurance-rag-assistant/
├── underwriting-agent/
├── insurance-email-intake/
└── insurance-underwriting-ui/
```

Run the platform commands below from `insurance-agentic-platform/`.

## Configuration

```bash
cp .env.example .env
```

Replace the database password placeholders and configure the provider keys you intend to use. Compose requires `POSTGRES_SUPERUSER_PASSWORD`, `EXTRACTOR_DB_PASSWORD`, `ANALYST_DB_PASSWORD`, `UNDERWRITING_DB_PASSWORD`, and `KNOWLEDGE_DB_PASSWORD`. Use URL-safe database passwords, as the application passwords are interpolated into connection URLs. Do not commit `.env`.

| Database | Application role | Usage |
|---|---|---|
| `extractor` | `extractor_app` | Extraction history; automatic migrations are enabled in Compose. |
| `analyst` | `analyst_app` | Synthetic portfolio; initialize its schema and dataset before using the analytics endpoints. |
| `underwriting` | `underwriting_app` | Underwriting decision persistence and audit history. |
| `knowledge` | `knowledge_app` | Reserved PostgreSQL database; the running Knowledge Agent uses Qdrant. |

PostgreSQL runs its initialization scripts only when the `postgres_data` volume is empty. Changing a password in `.env` after the first startup does not change the existing database role.

### Email Intake and UI

| Setting | Platform configuration |
|---|---|
| Email Intake → Underwriting | `UNDERWRITING_BASE_URL=http://underwriting-agent:8002` |
| Email Intake folder watcher | Enabled by Compose with `WATCH_ENABLED=true` and a 10-second interval. |
| Email Intake inbox | `../insurance-email-intake/data/inbox` is mounted read-only at `/app/data/inbox`. |
| Email Intake state | `/app/data/state`, backed by the `email_intake_state` volume. |
| IMAP and SMTP reply options | Disabled by default: `IMAP_ENABLED=false` and `SMTP_REPLY_ENABLED=false`. |
| UI → Email Intake | `INTAKE_BASE_URL=http://email-intake:8004` |
| UI → Underwriting | `UNDERWRITING_BASE_URL=http://underwriting-agent:8002` |
| Email Intake request timeout | `EMAIL_INTAKE_TIMEOUT_SECONDS` sets the container's `UNDERWRITING_TIMEOUT_SECONDS`; defaults to 120 seconds. |
| UI request timeout | `UI_REQUEST_TIMEOUT_SECONDS` sets the container's `REQUEST_TIMEOUT_SECONDS`; defaults to 120 seconds. |

Validate the resolved configuration:

```bash
docker compose config --quiet
```

## Start

### 1. Initialize PostgreSQL and the Analyst Dataset

```bash
docker compose up --build -d postgres
docker compose run --build --rm data-analyst-agent \
  insurance-data-analyst init-db --seed 20260904
```

The initialization command applies migrations and loads the synthetic portfolio. Re-running it replaces the dataset. Do not run it against a database containing non-synthetic data.

### 2. Start All Services

```bash
docker compose up --build -d
docker compose ps
```

The first Knowledge Agent build or startup can take longer while model files are downloaded. The vector index must contain the intended corpus for documentary evidence to be available; see the [Knowledge Agent ingestion instructions](https://github.com/Kwame-K/insurance-rag-assistant#ingestion).

Open the Streamlit console at `http://127.0.0.1:8501`. You can submit email text or an `.eml` file, inspect its result, and use the human-review queue for stored decisions that require review.

## Health Checks

```bash
curl -f http://127.0.0.1:8000/health           # Submission Extractor
curl -f http://127.0.0.1:8001/health           # Knowledge Agent
curl -f http://127.0.0.1:8002/health           # Underwriting Agent
curl -f http://127.0.0.1:8003/health           # Data Analyst Agent
curl -f http://127.0.0.1:8004/health           # Email Intake
curl -f http://127.0.0.1:8501/_stcore/health   # Streamlit
```

These checks do not prove that the Analyst dataset is loaded, the RAG index is populated, or the provider credentials work. Use a workflow request to check the integrations.

## Test the Extraction and Underwriting Flow

Call Underwriting directly to test extraction and evaluation without going through Email Intake or the UI:

```bash
curl -i -X POST http://127.0.0.1:8002/extract-and-underwrite \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-ID: platform-e2e-001' \
  -d '{
    "source_id": "SRC-PLATFORM-001",
    "source_type": "FREE_TEXT",
    "content": "We are a Montreal software company seeking cyber insurance. Annual revenue is CAD 2,000,000 and we employ 18 people.",
    "language": "en",
    "overrides": {
      "mfa_enabled": true,
      "requested_limit_cad": 1000000,
      "requested_retention_cad": 25000
    },
    "persist": false
  }'
```

`persist` defaults to `false`. Set it to `true` to save a completed evaluation. The example demonstrates the request format; it does not guarantee a completed evaluation. If extraction or underwriting still needs information, the endpoint can return `PENDING_INFORMATION` without saving a decision.

To test the email intake path instead, use the Streamlit submission page or call an endpoint documented in [Email Intake](https://github.com/Kwame-K/insurance-email-intake#endpoints).

## Persisted Volumes

| Volume | Mount | Purpose |
|---|---|---|
| `postgres_data` | `postgres:/var/lib/postgresql/data` | PostgreSQL cluster and application databases. |
| `analyst_output` | `data-analyst-agent:/app/output` | Audit artifacts and optional charts. |
| `rag_vector_store` | `knowledge-agent:/app/vector_store` | Local Qdrant index. |
| `rag_artifacts` | `knowledge-agent:/app/artifacts` | Retrieval evaluation artifacts. |
| `rag_model_cache` | `knowledge-agent:/app/.cache` | Model cache. |
| `email_intake_state` | `email-intake:/app/data/state` | Stored Email Intake state and results. |

The inbox directory is a read-only bind mount from the sibling Email Intake repository, not a named volume.

## Stop and Reset

Stop the stack while keeping named volumes:

```bash
docker compose down
```

For a full local reset:

```bash
docker compose down -v
```

**Warning:** `down -v` deletes the named volumes, including PostgreSQL records, Analyst artifacts, RAG indexes and caches, and Email Intake state. It does not delete the host inbox directory. Reinitialize the Analyst dataset after a reset.

## Service Readiness and Network Boundaries

- The Submission Extractor, Data Analyst, and Underwriting Agent wait for PostgreSQL to be healthy.
- Underwriting waits for the Extractor container to start, not for its HTTP API to become ready. It has no readiness dependency on the Knowledge Agent or Data Analyst.
- Email Intake waits for the Underwriting container to start. The UI waits for Email Intake to be healthy and the Underwriting container to start.
- The published ports use Compose short syntax without explicit loopback bindings. The `127.0.0.1` URLs in this README do not restrict the network interfaces Docker binds to. For local-only access, bind published ports explicitly to `127.0.0.1` or restrict access at the host.

## Known Limitations

- Analyst schema migration and synthetic seeding are manual prerequisites. A healthy API does not mean the dataset is ready.
- The Knowledge Agent's evidence depends on the populated Qdrant index. The reserved PostgreSQL knowledge database is not used for retrieval by default.
- The stack does not provide a reverse proxy, TLS termination, platform-level authentication, centralized tracing, or a PostgreSQL backup and restore process.
- Email Intake can accept email text but does not process PDF attachments in its v1 contract.

## Roadmap

1. Automate Analyst migrations and synthetic dataset initialization.
2. Add application readiness checks and use them where startup ordering matters.
3. Add Compose validation and platform smoke tests to CI.
4. Add authentication, TLS, observability, and backup and restore procedures before considering any non-local deployment.

## Design Principles

- Keep domain logic in each application repository.
- Integrate services through explicit HTTP contracts, not direct access to another application's tables.
- Isolate application databases and login roles.
- Document which state persists and which commands delete it.
- Keep secrets in local configuration rather than in images or version control.
