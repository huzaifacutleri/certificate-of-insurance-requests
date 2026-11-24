# Architecture

## Shape

A small modular monolith. The core pipeline is plain Python with no web-framework dependency;
the HTTP API and CLI are thin shells around one `Workflow` class. One person must be able to
hold the whole system in their head, so there are no queues, services, or ORMs yet.

```
        ┌────────────┐   ┌───────────┐
 .eml ─▶│  ingest    │──▶│  extract  │  rules | LLM (Extractor protocol)
        └────────────┘   └─────┬─────┘
                               ▼
                         ┌───────────┐     ┌──────────────┐
                         │  match    │◀────│ clients +    │ policy data = source of truth
                         └─────┬─────┘     │ policies     │
                               ▼           └──────────────┘
                         ┌───────────┐
                         │ validate  │  pure functions, no I/O
                         └─────┬─────┘
                               ▼
                    ┌─────────────────────┐
                    │ draft (from policy) │
                    └─────┬───────────────┘
                          ▼
   NEEDS_ATTENTION ◀─ workflow ─▶ READY_FOR_REVIEW ─▶ APPROVED ─▶ SENT
   (blockers)          + audit log       (CSR)         (re-checked)
                          │
                          ▼
                     render PDF
```

## Modules

| Module | Responsibility | I/O? |
|---|---|---|
| `models.py` | Pydantic domain models | no |
| `ingest.py` | Raw email to `IncomingEmail` | no |
| `extraction/` | `Extractor` protocol; `RuleBasedExtractor`; `LLMExtractor` | LLM only |
| `matching.py` | Client name matching | no |
| `validation.py` | Rules and draft building | no |
| `render.py` | Draft to PDF bytes | no |
| `storage.py` | SQLite repository, audit log | yes |
| `workflow.py` | Orchestration and state machine | via repo |
| `cli.py`, `api.py` | Interfaces | yes |

Keeping `validation.py` pure (it takes `today` as an argument) makes the business rules cheap
to test exhaustively. That is where the product's correctness lives.

## Key decisions

**1. Policy data is the source of truth; the email only asks.** The draft is built from the
client's policies. Extracted text never becomes certificate content, so a bad extraction or a
malicious email cannot make a certificate claim coverage that does not exist.

**2. Human approval is mandatory, and re-checked.** `approve()` re-runs validation against
current data. A policy that lapsed between draft and approval blocks the approval.

**3. Conservative matching.** Wrong-insured certificates are the worst failure, so the matcher
auto-matches only a clear winner and otherwise returns `AMBIGUOUS` for a human.

**4. Extractor behind a protocol.** The rule-based extractor makes the pipeline testable
offline and is a baseline to measure the LLM extractor against. The LLM is an injected
callable, so tests need no network.

**5. Tenant scoping in the repository.** `Repository` is constructed for one `agency_id`;
every query includes it. Adding customers does not need a rewrite.

**6. SQLite + JSON documents for now.** Records are stored as JSON next to a few indexed
columns. Fine for pilot scale and cheap to migrate to Postgres (same repository interface).

**7. Draft is a snapshot.** `CertificateDraft` copies policy data at drafting time, so an
issued certificate can be re-rendered identically later.

**8. Own layout, not ACORD.** See RISKS_AND_COMPLIANCE.md.

## State machine

```
NEEDS_ATTENTION ──reprocess──▶ READY_FOR_REVIEW ──approve──▶ APPROVED ──▶ SENT
      │                             │   ▲                         
      └──────▶ REJECTED ◀───────────┘   └── approval re-check fails
```

`SENT` and `REJECTED` are terminal. Illegal transitions raise `WorkflowError`.

## Data model

- `clients(agency_id, id, name, data)`: `data` is a `Client` with its `Coverage` list
- `requests(id, agency_id, message_id, status, created_at, updated_at, data)`: `data` is the
  full `CoiRequest`; unique on `(agency_id, message_id)` for de-duplication
- `audit_log(id, agency_id, request_id, at, actor, action, detail)`: append-only

## Extending

- **New extractor:** implement `extract(email) -> ExtractedRequest` and register it in
  `extraction/__init__.py`.
- **New rule:** add a check in `validation.validate` returning an `Issue`, plus a test in
  `tests/test_validation.py`.
- **New policy source (AMS import):** write a function that produces `list[Client]` and call
  `Repository.upsert_clients`. Nothing downstream changes.
- **Postgres:** reimplement `Repository` with the same methods.

## Testing approach

Tests run offline in under a second. Business rules are unit-tested in isolation; the pipeline
is tested end to end on the example emails; PDFs are checked by extracting their text. The API
tests skip themselves when the `api` extra is not installed.
