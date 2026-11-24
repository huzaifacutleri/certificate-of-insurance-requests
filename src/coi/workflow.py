"""Workflow orchestration: the only module that knows the order of the pipeline stages.

    process_email -> (extract, match, validate, draft) -> NEEDS_ATTENTION | READY_FOR_REVIEW
    approve       -> APPROVED          (re-validates first; stale data cannot slip through)
    mark_sent     -> SENT
    reject        -> REJECTED

Human approval is mandatory: nothing here ever sends a certificate on its own.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime

from .extraction import ExtractionError, Extractor
from .ingest import parse_email
from .matching import match_client
from .models import (
    CoiRequest,
    ExtractedRequest,
    IncomingEmail,
    Issue,
    MatchResult,
    MatchStatus,
    RequestStatus,
    Severity,
)
from .render import render_certificate
from .storage import Repository
from .validation import build_draft, validate

# Allowed state changes. Anything not listed is rejected.
_TRANSITIONS: dict[RequestStatus, set[RequestStatus]] = {
    RequestStatus.NEEDS_ATTENTION: {RequestStatus.READY_FOR_REVIEW, RequestStatus.REJECTED},
    RequestStatus.READY_FOR_REVIEW: {
        RequestStatus.NEEDS_ATTENTION,
        RequestStatus.APPROVED,
        RequestStatus.REJECTED,
    },
    RequestStatus.APPROVED: {RequestStatus.SENT},
    RequestStatus.SENT: set(),
    RequestStatus.REJECTED: set(),
}


class WorkflowError(Exception):
    """A requested action is not allowed in the request's current state."""


class ApprovalBlocked(WorkflowError):
    """Approval refused because validation now reports blockers."""

    def __init__(self, blockers: list[Issue]) -> None:
        super().__init__("; ".join(b.message for b in blockers))
        self.blockers = blockers


class Workflow:
    def __init__(
        self,
        repo: Repository,
        extractor: Extractor,
        agency_name: str,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._repo = repo
        self._extractor = extractor
        self._agency_name = agency_name
        self._clock = clock  # injectable so tests and demos control "today"

    # ---- evaluation (shared by ingest, reprocess and approve) ---------------------

    def _evaluate(self, extracted: ExtractedRequest):
        """Match + validate + draft from an extraction. Returns (match, issues, draft)."""
        today = self._clock()
        match = match_client(extracted.insured_name, self._repo.list_clients())
        client = self._repo.get_client(match.client_id) if match.client_id else None
        issues = validate(extracted, match, client, today)
        draft = build_draft(extracted, client, today) if client is not None else None
        return match, issues, draft

    @staticmethod
    def _status_for(issues: list[Issue]) -> RequestStatus:
        has_blocker = any(i.severity is Severity.BLOCKER for i in issues)
        return RequestStatus.NEEDS_ATTENTION if has_blocker else RequestStatus.READY_FOR_REVIEW

    # ---- actions ------------------------------------------------------------------

    def process_email(self, raw: bytes, actor: str = "system") -> CoiRequest:
        """Ingest one raw email. Re-delivery of the same email returns the existing request."""
        email = parse_email(raw)
        existing = self._repo.find_by_message_id(email.message_id)
        if existing is not None:
            return existing
        return self.process_parsed_email(email, actor)

    def process_parsed_email(self, email: IncomingEmail, actor: str = "system") -> CoiRequest:
        now = datetime.now(UTC)
        try:
            extracted = self._extractor.extract(email)
            failure: Issue | None = None
        except ExtractionError as exc:
            # Never drop an email silently: park it for a human with a clear reason.
            extracted = ExtractedRequest(extractor=self._extractor.name)
            failure = Issue(
                severity=Severity.BLOCKER,
                code="EXTRACTION_FAILED",
                message=f"Could not read this request automatically: {exc}",
            )

        if failure is None:
            match, issues, draft = self._evaluate(extracted)
        else:
            match, issues, draft = MatchResult(status=MatchStatus.NOT_FOUND), [failure], None

        request = CoiRequest(
            id=uuid.uuid4().hex,
            agency_id=self._repo.agency_id,
            status=self._status_for(issues),
            email=email,
            extracted=extracted,
            match=match,
            issues=issues,
            draft=draft,
            created_at=now,
            updated_at=now,
        )
        self._repo.save_request(request)
        self._repo.add_audit(request.id, actor, "received", f"status={request.status.value}")
        return request

    def reprocess(self, request_id: str, actor: str) -> CoiRequest:
        """Re-run matching and validation (e.g. after fixing policy data). Does not re-extract."""
        request = self._repo.get_request(request_id)
        if request.status not in (RequestStatus.NEEDS_ATTENTION, RequestStatus.READY_FOR_REVIEW):
            raise WorkflowError(f"Cannot reprocess a request that is {request.status.value}.")
        match, issues, draft = self._evaluate(request.extracted)
        request.match, request.issues, request.draft = match, issues, draft
        self._move(request, self._status_for(issues), actor, "reprocessed")
        return request

    def approve(self, request_id: str, actor: str) -> CoiRequest:
        request = self._repo.get_request(request_id)
        if request.status is not RequestStatus.READY_FOR_REVIEW:
            raise WorkflowError(
                f"Only ready-for-review requests can be approved, not {request.status.value}."
            )
        # Policy data may have changed (or a policy lapsed) since the draft was made.
        match, issues, draft = self._evaluate(request.extracted)
        blockers = [i for i in issues if i.severity is Severity.BLOCKER]
        if blockers:
            request.match, request.issues, request.draft = match, issues, draft
            self._move(
                request,
                RequestStatus.NEEDS_ATTENTION,
                actor,
                "approval_blocked",
                "re-check found blockers",
            )
            raise ApprovalBlocked(blockers)
        request.match, request.issues, request.draft = match, issues, draft
        self._move(request, RequestStatus.APPROVED, actor, "approved")
        return request

    def reject(self, request_id: str, actor: str, reason: str = "") -> CoiRequest:
        request = self._repo.get_request(request_id)
        self._move(request, RequestStatus.REJECTED, actor, "rejected", reason)
        return request

    def mark_sent(self, request_id: str, actor: str) -> CoiRequest:
        """Record that the approved certificate was delivered (sending itself is manual in the MVP)."""
        request = self._repo.get_request(request_id)
        self._move(request, RequestStatus.SENT, actor, "sent")
        return request

    def render_pdf(self, request_id: str) -> bytes:
        """PDF for a request. Only approved/sent certificates are un-watermarked."""
        request = self._repo.get_request(request_id)
        if request.draft is None:
            raise WorkflowError("No draft exists for this request (client not matched).")
        final = request.status in (RequestStatus.APPROVED, RequestStatus.SENT)
        return render_certificate(request.draft, self._agency_name, final=final)

    # ---- internals ----------------------------------------------------------------

    def _move(
        self,
        request: CoiRequest,
        new_status: RequestStatus,
        actor: str,
        action: str,
        detail: str = "",
    ) -> None:
        """Validate the transition, persist the request and write the audit entry."""
        if new_status is not request.status and new_status not in _TRANSITIONS[request.status]:
            raise WorkflowError(f"Cannot move from {request.status.value} to {new_status.value}.")
        request.status = new_status
        request.updated_at = datetime.now(UTC)
        self._repo.save_request(request)
        self._repo.add_audit(request.id, actor, action, detail)
