# Risks and compliance

This document records engineering and product risks and how the design addresses them. It is
**not legal advice**. Before taking money from customers, have an insurance-industry attorney
review the points marked *needs counsel*.

## 1. Errors and omissions (E&O) exposure

A certificate issued with wrong information can create liability for the agency, and possibly
for you. Mitigations built in:

- Certificates are built from **policy data only**, never from email text.
- Unsupported requests (missing endorsement, low limit, lapsed policy) are **blocked**, not
  softened.
- Human approval is mandatory; the approver is recorded in an audit log.
- Approval re-validates against current data.
- Drafts carry a DRAFT watermark until approved.
- The generated description of operations is a conservative template that defers to the policy's
  terms. Reviewers must confirm wording matches the carrier's endorsement forms.

*Needs counsel:* your customer terms (disclaimers, limitation of liability), whether you need
your own E&O / tech E&O cover, and how responsibility is allocated between you and the agency.

## 2. State certificate-of-insurance rules

Several US states regulate what certificates may say and how they are issued (for example,
restrictions on certificates that purport to alter coverage, and rules about requesting
endorsements). The disclaimer on the generated certificate says it does not amend, extend or
alter coverage. *Needs counsel:* confirm requirements for the states your pilots operate in.

## 3. ACORD forms

The standard certificate in the US market is the ACORD 25, which is a licensed form. This
product renders **its own layout**, not an ACORD copy. Many agencies will expect ACORD output
eventually. Review ACORD's licensing terms for software vendors and budget for it in Phase 3.

## 4. Prompt injection and untrusted email

Request emails are untrusted input. Controls:

- The LLM extractor has **no tools**; its only output is JSON parsed into `ExtractedRequest`.
- The email is passed as tagged data with an instruction not to follow it.
- Output is strictly schema-validated; failures park the request for a human
  (`EXTRACTION_FAILED`), they are never dropped.
- Extracted data cannot add coverage to a certificate (see section 1).
- Residual risk: a crafted email could cause a wrong *extraction* (for example a different
  holder). Human review is the control; keep the UI showing extracted fields next to the
  original email.

## 5. Wrong-insured matches

Matching is conservative: auto-match requires a clear best candidate with a margin over the
runner-up. Ambiguous or unknown names always go to a human. Track the false-match rate during
the pilot; the target is zero.

## 6. Data protection and security

The product handles business names, addresses, and policy details, not consumer payment or
health data, but agencies will still ask. Before pilots:

- Encrypt data at rest and in transit; restrict database access; keep backups.
- Replace the shared API key with per-user authentication (roadmap Phase 2).
- Do not log full email bodies in application logs.
- Define retention and deletion for emails and certificates.
- Check whether the LLM provider terms fit agency expectations (data retention / training use)
  and describe the data flow plainly in a one-page security overview.
- Pursue SOC 2 only when a customer or deal requires it.

## 7. Operational risks

| Risk | Mitigation |
|---|---|
| Stale policy data in the product | Show data freshness; re-validate on approval; automate imports |
| Policy export formats vary by management system | Start with one pilot's export; add importers per customer need |
| LLM outages or cost spikes | Extractor is swappable; rules fallback; per-request cost logging |
| Agencies slow to adopt | Pilot pricing, forwarding-inbox onboarding that needs no IT |
| Management-system vendors restrict API access | Prefer CSV/export flows; confirm terms before building integrations |

## 8. Repository note

This repository is currently **public**. Consider making it private before adding customer
data, prompts you consider proprietary, or anything pilot-specific. Never commit real client
or email data; `examples/` must stay synthetic.
