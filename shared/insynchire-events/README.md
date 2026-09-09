<!-- LOCATION: shared/insynchire-events/README.md -->

# insynchire-events

Internal shared Python package — the Kafka contract layer for every
InSyncHire microservice (Section "insynchire-events" / M0 in the project plan).

No service should write raw `aiokafka` code. Import this package instead.

## Install (editable, for local monorepo dev)

```bash
cd shared/insynchire-events
pip install -e ".[dev]"
```

Each service's `requirements.txt` / `pyproject.toml` should depend on this
package via a local path or an internal package index in CI.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | comma-separated |
| `KAFKA_SECURITY_PROTOCOL` | `PLAINTEXT` | use `SASL_SSL` in prod |
| `KAFKA_SASL_MECHANISM` | unset | e.g. `SCRAM-SHA-512` |
| `KAFKA_SASL_USERNAME` / `KAFKA_SASL_PASSWORD` | unset | from secrets manager, never hardcoded |
| `KAFKA_MAX_PUBLISH_RETRIES` | `3` | |
| `KAFKA_RETRY_BACKOFF_BASE_SECONDS` | `0.5` | exponential backoff base |
| `KAFKA_PRODUCER_ACKS` | `all` | |
| `KAFKA_AUTO_OFFSET_RESET` | `earliest` | |
| `KAFKA_ENABLE_AUTO_COMMIT` | `false` | we commit manually after handler success |

## Publishing an event

```python
from insynchire_events import publish, Topics
from insynchire_events.schemas import ApplicationSubmittedEvent

event = ApplicationSubmittedEvent(
    trace_id=request_state.trace_id,
    tenant_id=tenant_id,
    application_id=application_id,
    job_id=job_id,
    candidate_user_id=candidate_user_id,
    resume_id=resume_id,
)
await publish(Topics.APPLICATION_SUBMITTED.value, event)
```

For services with a FastAPI lifespan (recommended over the module-level
singleton, so shutdown flushes cleanly):

```python
from contextlib import asynccontextmanager
from insynchire_events import EventProducer

producer = EventProducer()

@asynccontextmanager
async def lifespan(app):
    await producer.start()
    yield
    await producer.stop()

app = FastAPI(lifespan=lifespan)
```

## Subscribing to a topic (headless consumer service)

```python
# migration_service/main.py
import asyncio
from insynchire_events import subscribe, Topics
from insynchire_events.schemas import TenantSignupInitiatedEvent

async def handle_signup(event: TenantSignupInitiatedEvent) -> None:
    await provision_tenant_db(event.tenant_id)

async def main():
    await subscribe(
        Topics.TENANT_SIGNUP_INITIATED.value,
        handle_signup,
        group_id="migration_service",
    )

if __name__ == "__main__":
    asyncio.run(main())
```

## Adding a new event type

1. Add the topic name to `Topics` in `topics.py`.
2. Add the topic to the relevant Kafka topics list in the project plan doc too.
3. Define the Pydantic model in `schemas.py`, subclassing `BaseEvent`.
4. Register it in `EVENT_SCHEMA_REGISTRY`.
5. Add a test in `tests/test_schemas.py` asserting the new topic is registered.

This is the *only* place event shapes are defined — do not let a service
define its own ad-hoc dict for a Kafka message.

## Dead-letter queues

Every topic `X` has a paired `X.dlq` topic. Messages land there when:
- A producer exhausts `KAFKA_MAX_PUBLISH_RETRIES` sends (transport failure)
- A consumer receives a message that fails Pydantic validation
- A consumer's handler raises an unhandled exception

The Reporting Service should also consume `*.dlq` topics into
`reporting_db.error_logs` — wire this up in Milestone M12 dashboards.
