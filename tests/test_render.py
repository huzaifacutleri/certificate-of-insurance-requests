import io

import pytest

from coi.models import RequestStatus

from .conftest import example_email

pypdf = pytest.importorskip("pypdf")


def _text(pdf_bytes: bytes) -> str:
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


def test_draft_pdf_is_watermarked_and_contains_policy_data(workflow):
    request = workflow.process_email(example_email("01_clean_request.eml"))
    pdf = workflow.render_pdf(request.id)
    assert pdf.startswith(b"%PDF")
    text = _text(pdf)
    assert "DRAFT" in text
    assert "Summit Roofing LLC" in text and "Harbor Property Group" in text
    assert "GL-100234" in text and "$1,000,000" in text


def test_approved_pdf_has_no_watermark(workflow):
    request = workflow.process_email(example_email("01_clean_request.eml"))
    workflow.approve(request.id, actor="csr")
    assert "DRAFT" not in _text(workflow.render_pdf(request.id))


def test_special_characters_do_not_break_rendering(workflow, repo):
    request = workflow.process_email(example_email("01_clean_request.eml"))
    request.draft.holder_name = "A&B <Holdings> Ltd"
    repo.save_request(request)
    assert "A&B" in _text(workflow.render_pdf(request.id))
    assert request.status is RequestStatus.READY_FOR_REVIEW


def test_no_draft_means_no_pdf(workflow):
    from coi.workflow import WorkflowError

    request = workflow.process_email(example_email("04_unknown_client.eml"))
    with pytest.raises(WorkflowError):
        workflow.render_pdf(request.id)
