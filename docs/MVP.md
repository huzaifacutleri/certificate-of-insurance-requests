# MVP definition

## Problem

Independent commercial-lines agencies get many certificate requests a week, mostly by email and
mostly for contractor clients. Each one means: find the client, find the policies, check the
requested limits and endorsements, produce a certificate, reply. It is repetitive, interrupt-
driven, and error-prone, and a wrong certificate creates liability for the agency.

## Target customer

Commercial-lines independent agencies, roughly 5 to 50 staff, with many contractor and
subcontractor clients. Buyer: agency principal or operations manager. User: customer service
representatives (CSRs).

## What the MVP does (one workflow)

Certificate **issuance requests**: email in, reviewed draft certificate out.

User stories:

1. As a CSR, I get each request as a structured item (insured, holder, requirements) instead of
   an email I have to decode.
2. As a CSR, I see immediately whether the policies on file satisfy the request, and exactly
   why not when they do not.
3. As a CSR, I review a ready draft and approve it with one action.
4. As a principal, I know nothing leaves the agency without a named person's approval, and I
   can see who approved what and when.

## In scope (built)

- Email parsing, de-duplication
- Extraction: rule-based baseline + schema-validated LLM extractor
- Client matching that refuses to guess
- Validation: coverage in force, minimum limits, requested endorsements, expiring-soon
- Draft + PDF generation from policy data only; DRAFT watermark until approved
- Approval workflow with re-check at approval time, audit log
- Multi-tenant data model (`agency_id` on every row)
- CLI and HTTP API

## Out of scope for now

- Review UI (next up; see roadmap)
- Mailbox connectors (Gmail / Microsoft 365). MVP takes forwarded `.eml` files
- Agency management system integrations. MVP takes a JSON/CSV policy export
- Reading attached contracts or PDFs
- ACORD-form output (licensing; see RISKS_AND_COMPLIANCE.md)
- Sending email from the product; certificate is delivered by the CSR
- Per-user accounts, billing, SOC 2

## Hypotheses the pilot must test

These are targets to validate, not facts.

| Hypothesis | How to measure | Target |
|---|---|---|
| Extraction is good enough on real emails | % of requests whose extraction needs no correction, on 30+ real emails | 80%+ |
| Clean requests save real time | CSR minutes per certificate, before vs after | Under 2 min |
| Blocks are correct | % of blocker issues the CSR agrees with | 90%+ |
| Agencies will pay | Pilot converts to paid at a stated price | 2 of 3 pilots |

## Pricing starting point

Roughly $300 to $600 per agency per month; discount for the first five pilots. Adjust after
measuring hours saved.
