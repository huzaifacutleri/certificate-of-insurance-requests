"""Domain models shared by every pipeline stage.

Design notes
------------
* Everything is a pydantic model so it can be validated (important for LLM output),
  serialized to JSON for storage, and round-tripped without custom code.
* The *policy data* (``Client`` / ``Coverage``) is the single source of truth for what a
  certificate may say. Extracted request text can only ask for things; it can never add
  coverage to a certificate. See ``validation.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------
# Policy data (what the agency actually knows about its client)
# --------------------------------------------------------------------------------------


class CoverageType(StrEnum):
    GENERAL_LIABILITY = "general_liability"
    AUTO_LIABILITY = "auto_liability"
    WORKERS_COMP = "workers_comp"
    UMBRELLA = "umbrella"


class Endorsement(StrEnum):
    """Endorsements certificate holders commonly require. MVP checks them on the GL policy."""

    ADDITIONAL_INSURED = "additional_insured"
    WAIVER_OF_SUBROGATION = "waiver_of_subrogation"
    PRIMARY_NONCONTRIBUTORY = "primary_noncontributory"


# Canonical limit keys (free-form strings in storage, constants here to avoid typos).
EACH_OCCURRENCE = "each_occurrence"
GENERAL_AGGREGATE = "general_aggregate"
COMBINED_SINGLE_LIMIT = "combined_single_limit"
EACH_ACCIDENT = "each_accident"
AGGREGATE = "aggregate"


class Coverage(BaseModel):
    type: CoverageType
    carrier: str
    policy_number: str
    effective: date
    expiration: date
    # Limit key -> whole-dollar amount, e.g. {"each_occurrence": 1_000_000}.
    limits: dict[str, int] = Field(default_factory=dict)
    endorsements: set[Endorsement] = Field(default_factory=set)

    def is_active_on(self, day: date) -> bool:
        """True if the policy is in force on ``day``.

        Policies conventionally expire at 12:01 AM on the expiration date, so the
        expiration day itself is *not* covered.
        """
        return self.effective <= day < self.expiration


class Client(BaseModel):
    """An insured the agency services, with the policies currently on file."""

    id: str
    name: str
    address: str = ""
    coverages: list[Coverage] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Incoming request and what we extract from it
# --------------------------------------------------------------------------------------


class IncomingEmail(BaseModel):
    message_id: str
    sender: str
    subject: str
    body: str
    received_at: datetime
    attachment_names: list[str] = Field(default_factory=list)


class RequiredCoverage(BaseModel):
    type: CoverageType
    # Minimum limits the requester states, by canonical limit key. May be empty.
    min_limits: dict[str, int] = Field(default_factory=dict)


class ExtractedRequest(BaseModel):
    """Structured form of a request email. Every field is optional because emails are messy;
    missing essentials are reported as validation issues, never guessed."""

    insured_name: str | None = None
    holder_name: str | None = None
    holder_address: str | None = None
    project_description: str | None = None
    requested_endorsements: set[Endorsement] = Field(default_factory=set)
    required_coverages: list[RequiredCoverage] = Field(default_factory=list)
    # Which extractor produced this ("rules", "llm:<model>"); useful when debugging quality.
    extractor: str = "unknown"
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Matching, validation, draft
# --------------------------------------------------------------------------------------


class MatchStatus(StrEnum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


class Candidate(BaseModel):
    client_id: str
    name: str
    score: float


class MatchResult(BaseModel):
    status: MatchStatus
    client_id: str | None = None
    score: float = 0.0
    candidates: list[Candidate] = Field(default_factory=list)


class Severity(StrEnum):
    BLOCKER = "blocker"  # A human must fix the cause; the request cannot be approved.
    WARNING = "warning"  # Reviewer should look, but approval is allowed.


class Issue(BaseModel):
    severity: Severity
    code: str
    message: str


class CertificateDraft(BaseModel):
    """Everything needed to render a certificate. A snapshot: it does not change if the
    underlying policy data changes later, which keeps issued certificates reproducible."""

    insured_name: str
    insured_address: str = ""
    holder_name: str | None = None
    holder_address: str | None = None
    description_of_operations: str = ""
    coverages: list[Coverage] = Field(default_factory=list)
    issued_on: date


# --------------------------------------------------------------------------------------
# Stored request record and workflow state
# --------------------------------------------------------------------------------------


class RequestStatus(StrEnum):
    NEEDS_ATTENTION = "needs_attention"  # Has blockers; waiting on a human to fix data.
    READY_FOR_REVIEW = "ready_for_review"  # Clean draft; waiting for CSR approval.
    APPROVED = "approved"  # CSR approved; certificate is final.
    SENT = "sent"  # Delivered to the requester.
    REJECTED = "rejected"  # CSR declined the request.


class CoiRequest(BaseModel):
    id: str
    agency_id: str
    status: RequestStatus
    email: IncomingEmail
    extracted: ExtractedRequest
    match: MatchResult
    issues: list[Issue] = Field(default_factory=list)
    draft: CertificateDraft | None = None
    created_at: datetime
    updated_at: datetime

    @property
    def blockers(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.BLOCKER]
