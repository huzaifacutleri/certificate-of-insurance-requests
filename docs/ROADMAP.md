# Roadmap (solo founder)

Time estimates assume one person working part to full time. Each phase ends with something a
customer can use or a decision you can make from evidence.

## Phase 0: Validate before building more (weeks 1 to 2)

- Interview 10 agency principals / ops managers. Ask how many certificate requests per week,
  minutes each, who does them, which management system they use, what goes wrong.
- Ask three agencies for **30 real, anonymized request emails each**. This is the evaluation set
  for extraction quality and the most valuable asset you can have.
- Try to get 3 verbal pilot commitments with a stated price.
- **Decision gate:** fewer than 3 commitments after 15 conversations means stop or change niche.

## Phase 1: Usable pilot (weeks 3 to 6)

- [x] Core pipeline, CLI, API, tests (this repo)
- [ ] Extraction evaluation harness: run both extractors on the real-email set, report field-level
      accuracy. Tune the LLM prompt until it clears the target in MVP.md.
- [ ] **Review UI**: server-rendered (FastAPI + Jinja + HTMX) to stay solo-friendly. A queue of
      requests, a detail page showing extracted fields, issues, draft PDF, and Approve / Reject.
- [ ] Policy import from CSV/JSON export of the pilot agency's management system.
- [ ] Forwarding inbox: agency forwards requests to a dedicated address; inbound email webhook
      (Postmark / SES / Mailgun inbound) posts to `POST /requests`.
- [ ] Deploy: one small VM or PaaS, Postgres, backups, HTTPS.

## Phase 2: Pilot to paid (weeks 7 to 12)

- [ ] Per-user login with roles (CSR, principal); replace the shared API key.
- [ ] Send the approved certificate by email from within the product (with CSR confirmation).
- [ ] First management-system integration, chosen by what pilots actually use (check API access
      terms before promising anything).
- [ ] Editable draft fields (description of operations, holder address) with re-validation.
- [ ] Simple billing (Stripe).
- [ ] Basic security posture documented: encryption, access control, backups, a one-page
      security overview to answer agency questionnaires.

## Phase 3: Widen the moat (months 4 to 8)

- [ ] Read attached contracts / insurance-requirement PDFs and extract requirements.
- [ ] Licensed ACORD 25 output, if pilots require it (see RISKS_AND_COMPLIANCE.md).
- [ ] Renewal workflow: re-issue certificates automatically when policies renew (still approved).
- [ ] Holder tracking: who holds a certificate, and when to send an updated one.
- [ ] Direct Gmail / Microsoft 365 mailbox connectors.
- [ ] Formal SOC 2 only when a customer or deal requires it.

## Metrics to watch

- Extraction accuracy per field on the real-email set
- % of requests that reach READY_FOR_REVIEW with no CSR edits
- Minutes from email received to certificate approved
- Blocker agreement rate (does the CSR agree the block was right?)
- Weekly active agencies; pilot to paid conversion

## Explicitly not now

Mobile app, multi-language, workers' comp audit workflows, other insurance lines, a generic
workflow builder. Resist all of it until Phase 2 revenue exists.
