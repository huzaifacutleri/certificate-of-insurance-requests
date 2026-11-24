"""End-to-end tests of the pipeline using the bundled example emails."""

from datetime import date

import pytest

from coi.extraction import ExtractionError, LLMExtractor
from coi.models import Endorsement, RequestStatus
from coi.workflow import ApprovalBlocked, Workflow, WorkflowError

from .conftest import TODAY, example_email


def test_clean_request_is_ready_for_review(workflow):
    request = workflow.process_email(example_email("01_clean_request.eml"))
    assert request.status is RequestStatus.READY_FOR_REVIEW
    assert request.draft is not None and request.draft.holder_name == "Harbor Property Group"
    assert [i.code for i in request.issues] == ["EXPIRING_SOON"]  # workers comp expires in 16 days


@pytest.mark.parametrize(
    "eml,code",
    [
        ("02_missing_endorsement.eml", "ENDORSEMENT_MISSING"),
        ("03_policy_expired.eml", "COVERAGE_NOT_IN_FORCE"),
        ("04_unknown_client.eml", "CLIENT_NOT_FOUND"),
    ],
)
def test_problem_requests_need_attention(workflow, eml, code):
    request = workflow.process_email(example_email(eml))
    assert request.status is RequestStatus.NEEDS_ATTENTION
    assert code in {i.code for i in request.blockers}


def test_duplicate_delivery_creates_one_request(workflow, repo):
    first = workflow.process_email(example_email("01_clean_request.eml"))
    second = workflow.process_email(example_email("01_clean_request.eml"))
    assert first.id == second.id and len(repo.list_requests()) == 1


def test_approve_then_send_and_audit_trail(workflow, repo):
    request = workflow.process_email(example_email("01_clean_request.eml"))
    workflow.approve(request.id, actor="csr@agency")
    workflow.mark_sent(request.id, actor="csr@agency")
    assert repo.get_request(request.id).status is RequestStatus.SENT
    assert [e["action"] for e in repo.list_audit(request.id)] == ["received", "approved", "sent"]
    assert repo.list_audit(request.id)[1]["actor"] == "csr@agency"


def test_blocked_request_cannot_be_approved(workflow):
    request = workflow.process_email(example_email("02_missing_endorsement.eml"))
    with pytest.raises(WorkflowError):
        workflow.approve(request.id, actor="csr")


def test_approval_rechecks_policy_data(workflow, repo):
    """A policy lapsing between draft and approval must block approval."""
    request = workflow.process_email(example_email("01_clean_request.eml"))
    later = Workflow(repo, workflow._extractor, "Test Agency", clock=lambda: date(2027, 2, 1))
    with pytest.raises(ApprovalBlocked):
        later.approve(request.id, actor="csr")
    assert repo.get_request(request.id).status is RequestStatus.NEEDS_ATTENTION


def test_reprocess_after_fixing_policy_data(workflow, repo):
    request = workflow.process_email(example_email("02_missing_endorsement.eml"))
    client = repo.get_client("pine-ridge-electric")
    client.coverages[0].endorsements.add(Endorsement.WAIVER_OF_SUBROGATION)  # carrier issued it
    repo.upsert_clients([client])
    updated = workflow.reprocess(request.id, actor="csr")
    assert updated.status is RequestStatus.READY_FOR_REVIEW


def test_terminal_states_cannot_change(workflow):
    request = workflow.process_email(example_email("04_unknown_client.eml"))
    workflow.reject(request.id, actor="csr", reason="not our client")
    with pytest.raises(WorkflowError):
        workflow.mark_sent(request.id, actor="csr")


def test_extraction_failure_is_parked_not_dropped(repo):
    def broken(system, user):
        return "I cannot help with that"

    wf = Workflow(repo, LLMExtractor(broken, "test"), "Test Agency", clock=lambda: TODAY)
    request = wf.process_email(example_email("01_clean_request.eml"))
    assert request.status is RequestStatus.NEEDS_ATTENTION
    assert [i.code for i in request.blockers] == ["EXTRACTION_FAILED"]


def test_tenants_are_isolated(repo):
    from coi.storage import Repository

    other = Repository(repo._conn, "other-agency")
    assert other.list_clients() == [] and other.list_requests() == []


def test_extraction_error_type_is_exported():
    assert issubclass(ExtractionError, Exception)
