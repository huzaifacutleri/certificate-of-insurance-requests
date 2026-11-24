"""Business-rule tests. These protect the product's core promise: never certify what the
policy data does not support."""

from datetime import date, timedelta

from coi.matching import match_client
from coi.models import (
    Client,
    Coverage,
    CoverageType,
    Endorsement,
    ExtractedRequest,
    MatchResult,
    MatchStatus,
    RequiredCoverage,
    Severity,
)
from coi.validation import build_draft, validate

from .conftest import TODAY


def _gl(**overrides) -> Coverage:
    data = dict(
        type=CoverageType.GENERAL_LIABILITY,
        carrier="C",
        policy_number="GL-1",
        effective=TODAY - timedelta(days=100),
        expiration=TODAY + timedelta(days=200),
        limits={"each_occurrence": 1_000_000, "general_aggregate": 2_000_000},
        endorsements={Endorsement.ADDITIONAL_INSURED},
    )
    return Coverage(**{**data, **overrides})


def _run(extracted: ExtractedRequest, *coverages: Coverage, today: date = TODAY):
    client = Client(id="c1", name="Acme Co", coverages=list(coverages))
    match = match_client(extracted.insured_name or "Acme", [client])
    return validate(extracted, match, client, today)


def _codes(issues, severity=None):
    return {i.code for i in issues if severity is None or i.severity is severity}


def _request(**kw) -> ExtractedRequest:
    kw.setdefault("insured_name", "Acme Co")
    kw.setdefault("holder_name", "Holder Inc")
    kw.setdefault(
        "required_coverages",
        [
            RequiredCoverage(
                type=CoverageType.GENERAL_LIABILITY, min_limits={"each_occurrence": 1_000_000}
            )
        ],
    )
    return ExtractedRequest(**kw)


def test_clean_request_has_no_issues():
    assert _run(_request(), _gl()) == []


def test_missing_holder_is_a_blocker():
    assert "MISSING_HOLDER" in _codes(_run(_request(holder_name=None), _gl()), Severity.BLOCKER)


def test_policy_expiring_today_is_not_in_force():
    # Policies expire at 12:01 AM on the expiration date.
    issues = _run(_request(), _gl(expiration=TODAY))
    assert "COVERAGE_NOT_IN_FORCE" in _codes(issues, Severity.BLOCKER)


def test_future_policy_is_not_in_force():
    issues = _run(
        _request(), _gl(effective=TODAY + timedelta(days=1), expiration=TODAY + timedelta(days=366))
    )
    assert "COVERAGE_NOT_IN_FORCE" in _codes(issues)


def test_missing_coverage_type_is_a_blocker():
    req = _request(required_coverages=[RequiredCoverage(type=CoverageType.WORKERS_COMP)])
    assert "COVERAGE_MISSING" in _codes(_run(req, _gl()), Severity.BLOCKER)


def test_limit_below_request_is_a_blocker():
    req = _request(
        required_coverages=[
            RequiredCoverage(
                type=CoverageType.GENERAL_LIABILITY, min_limits={"each_occurrence": 2_000_000}
            )
        ]
    )
    issues = _run(req, _gl())
    assert "LIMIT_TOO_LOW" in _codes(issues, Severity.BLOCKER)
    assert "$2,000,000" in next(i.message for i in issues if i.code == "LIMIT_TOO_LOW")


def test_requested_endorsement_not_on_policy_is_a_blocker():
    req = _request(requested_endorsements={Endorsement.WAIVER_OF_SUBROGATION})
    assert "ENDORSEMENT_MISSING" in _codes(_run(req, _gl()), Severity.BLOCKER)


def test_endorsement_on_policy_passes():
    req = _request(requested_endorsements={Endorsement.ADDITIONAL_INSURED})
    assert _run(req, _gl()) == []


def test_endorsement_without_gl_policy_is_unverifiable():
    auto = Coverage(
        type=CoverageType.AUTO_LIABILITY,
        carrier="C",
        policy_number="A",
        effective=TODAY - timedelta(days=5),
        expiration=TODAY + timedelta(days=300),
        limits={"combined_single_limit": 1_000_000},
    )
    req = _request(requested_endorsements={Endorsement.ADDITIONAL_INSURED}, required_coverages=[])
    assert "ENDORSEMENT_UNVERIFIABLE" in _codes(_run(req, auto), Severity.BLOCKER)


def test_expiring_soon_is_only_a_warning():
    issues = _run(_request(), _gl(expiration=TODAY + timedelta(days=10)))
    assert _codes(issues) == {"EXPIRING_SOON"}
    assert all(i.severity is Severity.WARNING for i in issues)


def test_no_stated_requirements_warns():
    assert "NO_REQUIREMENTS_STATED" in _codes(
        _run(_request(required_coverages=[]), _gl()), Severity.WARNING
    )


def test_unmatched_client_stops_further_checks():
    extracted = _request(insured_name="Totally Different Business")
    client = Client(id="c1", name="Acme Co", coverages=[_gl()])
    match = match_client(extracted.insured_name, [client])
    assert match.status is MatchStatus.NOT_FOUND
    assert _codes(validate(extracted, match, None, TODAY)) == {"CLIENT_NOT_FOUND"}


def test_ambiguous_match_is_a_blocker():
    extracted = _request()
    match = MatchResult(status=MatchStatus.AMBIGUOUS, score=0.8)
    assert _codes(validate(extracted, match, None, TODAY)) == {"CLIENT_AMBIGUOUS"}


def test_draft_comes_from_policy_not_from_the_email():
    # The email asks for waiver of subrogation, which the policy lacks: it must not appear.
    req = _request(
        requested_endorsements={Endorsement.ADDITIONAL_INSURED, Endorsement.WAIVER_OF_SUBROGATION}
    )
    client = Client(id="c1", name="Acme Co", address="1 Main St", coverages=[_gl()])
    draft = build_draft(req, client, TODAY)
    assert "additional insured" in draft.description_of_operations
    assert "subrogation" not in draft.description_of_operations
    assert draft.insured_name == "Acme Co" and draft.insured_address == "1 Main St"


def test_draft_lists_only_coverage_in_force():
    expired = _gl(
        policy_number="OLD",
        expiration=TODAY - timedelta(days=1),
        effective=TODAY - timedelta(days=366),
    )
    client = Client(id="c1", name="Acme Co", coverages=[expired, _gl()])
    draft = build_draft(_request(), client, TODAY)
    assert [c.policy_number for c in draft.coverages] == ["GL-1"]
