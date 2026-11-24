# COI Assistant

Certificate-of-insurance (COI) request automation for independent insurance agencies.

Agencies spend hours every week answering emails like *"Please send a certificate for Summit
Roofing, with Harbor Property Group as additional insured."* COI Assistant reads the request,
checks it against the policies on file, drafts the certificate, and puts it in front of a
CSR for one-click approval. **A human always approves. Nothing is sent automatically.**

> Status: working MVP core (CLI + tested pipeline + API wrapper). No review UI yet. See
> [docs/ROADMAP.md](docs/ROADMAP.md).

## How it works

```
raw email → ingest → extract → match client → validate → draft → CSR approval → PDF
```

| Stage | What it does | Module |
|---|---|---|
| Ingest | Parse `.eml` / raw email into text, de-duplicate by Message-ID | `ingest.py` |
| Extract | Pull insured, holder, endorsements, required limits (rules baseline or LLM) | `extraction/` |
| Match | Find the client on file; refuse to guess when ambiguous | `matching.py` |
| Validate | Check policies in force, limits, endorsements, expiry | `validation.py` |
| Draft + render | Build the certificate **from policy data only**, render PDF | `validation.py`, `render.py` |
| Workflow | State machine, re-check on approval, audit log | `workflow.py`, `storage.py` |

The central rule: **a certificate can only state what the policy data supports.** An email can
ask for a waiver of subrogation; if the policy lacks it, the request is blocked, not certified.

## Try it in two minutes

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m coi demo        # runs 4 example emails end to end, writes PDFs to ./out
pytest                    # full test suite
```

The demo shows a clean request, a missing endorsement, an expired policy, and an unknown
client, then approves the clean one and writes a final (un-watermarked) PDF.

Working with your own data:

```bash
export COI_DB=./coi.db
python -m coi import-clients my_clients.json   # same shape as examples/clients.json
python -m coi ingest request.eml
python -m coi list
python -m coi show <id>
python -m coi approve <id> --actor you@agency.com
python -m coi pdf <id> -o certificate.pdf
```

## HTTP API (optional)

```bash
pip install -e ".[api]"
COI_API_KEY=change-me uvicorn coi.api:app
```

Endpoints (all need an `X-API-Key` header): `PUT /clients`, `POST /requests` (raw email body),
`GET /requests`, `GET /requests/{id}`, `POST /requests/{id}/approve|reject|reprocess|sent`,
`GET /requests/{id}/certificate.pdf`.

## LLM extraction (optional)

The default extractor is rule-based and offline. For free-form emails use the LLM extractor:

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...
export COI_EXTRACTOR=llm      # optionally COI_LLM_MODEL=<model id>
```

LLM output is strictly schema-validated, treated as untrusted, and can never add coverage to a
certificate. See [docs/RISKS_AND_COMPLIANCE.md](docs/RISKS_AND_COMPLIANCE.md).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `COI_DB` | `coi.db` | SQLite path |
| `COI_AGENCY_ID` | `demo` | Tenant id; all data is scoped to it |
| `COI_AGENCY_NAME` | `Demo Insurance Agency` | Printed on certificates |
| `COI_EXTRACTOR` | `rules` | `rules` or `llm` |
| `COI_LLM_MODEL` | `claude-sonnet-5-5` | Model for the LLM extractor |
| `COI_API_KEY` | unset | Required by the API; if unset the API refuses requests |

## Documentation

- [docs/MVP.md](docs/MVP.md): scope, user stories, pilot success criteria
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): design, data model, key decisions
- [docs/ROADMAP.md](docs/ROADMAP.md): phased plan for a solo founder
- [docs/RISKS_AND_COMPLIANCE.md](docs/RISKS_AND_COMPLIANCE.md): liability, ACORD licensing, security

## Project layout

```
src/coi/          application code (core has no web-framework dependency)
tests/            pytest suite (runs offline)
examples/         sample clients and request emails
docs/             product and engineering docs
```
