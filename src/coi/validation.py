"""Business rules: can the requested certificate be issued from the policies on file?

Core principle: **a certificate may only state what the policy data supports.** The request
asks; the policy data decides. Every mismatch becomes an ``Issue``:

* BLOCKER  - cannot be approved until a human fixes the cause (update the policy data,
             contact the requester, or reject the request).
* WARNING  - the reviewer should look, but approval is allowed.

The functions are pure (no I/O, no clock) so they are trivial to test; callers pass ``today``.
"""

from __future__ import annotations

from datetime import date

from .models import (
    CertificateDraft,
    Client,
    Coverage,
    CoverageType,
    Endorsement,
    ExtractedRequest,
    Issue,
    MatchResult,
    MatchStatus,
    Severity,
)

EXPIRING_SOON_DAYS = 30

_COVERAGE_ORDER = [
    CoverageType.GENERAL_LIABILITY,
    CoverageType.AUTO_LIABILITY,
    CoverageType.UMBRELLA,
    CoverageType.WORKERS_COMP,
]

_ENDORSEMENT_LABEL = {
    Endorsement.ADDITIONAL_INSURED: "additional insured",
    Endorsement.WAIVER_OF_SUBROGATION: "waiver of subrogation",
    Endorsement.PRIMARY_NONCONTRIBUTORY: "primary and non-contributory",
}


def money(amount: int) -> str:
    return f"${amount:,}"


def label(value: str) -> str:
    return value.replace("_", " ")


def _blocker(code: str, message: str) -> Issue:
    return Issue(severity=Severity.BLOCKER, code=code, message=message)


def _warning(code: str, message: str) -> Issue:
    return Issue(severity=Severity.WARNING, code=code, message=message)


def coverages_in_force(client: Client, today: date) -> list[Coverage]:
    """Coverages active today, in the conventional certificate order."""
    active = [c for c in client.coverages if c.is_active_on(today)]
    return sorted(active, key=lambda c: _COVERAGE_ORDER.index(c.type))


def validate(
    extracted: ExtractedRequest,
    match: MatchResult,
    client: Client | None,
    today: date,
) -> list[Issue]:
    """Return every issue found. An empty list means the draft is clean."""
    issues: list[Issue] = []

    if not extracted.holder_name:
        issues.append(_blocker("MISSING_HOLDER", "The certificate holder could not be determined."))

    # Without a confident client match nothing else can be checked.
    if match.status is MatchStatus.AMBIGUOUS:
        names = ", ".join(c.name for c in match.candidates[:3])
        issues.append(
            _blocker("CLIENT_AMBIGUOUS", f"Insured name is not a clear match. Closest: {names}.")
        )
        return issues
    if match.status is MatchStatus.NOT_FOUND or client is None:
        name = extracted.insured_name or "(none given)"
        issues.append(_blocker("CLIENT_NOT_FOUND", f"No client on file matches insured {name!r}."))
        return issues

    in_force = coverages_in_force(client, today)
    by_type = {c.type: c for c in in_force}

    if not extracted.required_coverages:
        issues.append(
            _warning(
                "NO_REQUIREMENTS_STATED",
                "The request does not state required coverages; the certificate will list "
                "all coverage currently in force.",
            )
        )

    # Required coverages and minimum limits.
    for req in extracted.required_coverages:
        coverage = by_type.get(req.type)
        if coverage is None:
            on_file = any(c.type is req.type for c in client.coverages)
            code, why = (
                ("COVERAGE_NOT_IN_FORCE", "is on file but not in force today")
                if on_file
                else ("COVERAGE_MISSING", "is not on file")
            )
            issues.append(_blocker(code, f"{label(req.type.value).title()} {why}."))
            continue
        for key, minimum in req.min_limits.items():
            actual = coverage.limits.get(key, 0)
            if actual < minimum:
                issues.append(
                    _blocker(
                        "LIMIT_TOO_LOW",
                        f"{label(req.type.value).title()} {label(key)} is {money(actual)}; "
                        f"{money(minimum)} was requested.",
                    )
                )

    # Requested endorsements must already exist on the general liability policy (MVP rule).
    if extracted.requested_endorsements:
        gl = by_type.get(CoverageType.GENERAL_LIABILITY)
        for endorsement in sorted(extracted.requested_endorsements, key=lambda e: e.value):
            if gl is None:
                issues.append(
                    _blocker(
                        "ENDORSEMENT_UNVERIFIABLE",
                        f"{_ENDORSEMENT_LABEL[endorsement].capitalize()} was requested but no "
                        "general liability policy is in force to check it against.",
                    )
                )
            elif endorsement not in gl.endorsements:
                issues.append(
                    _blocker(
                        "ENDORSEMENT_MISSING",
                        f"{_ENDORSEMENT_LABEL[endorsement].capitalize()} was requested but is "
                        "not on the general liability policy. Do not certify it until the "
                        "carrier has issued the endorsement.",
                    )
                )

    # Heads-up for anything on the certificate that is about to lapse.
    for coverage in in_force:
        days_left = (coverage.expiration - today).days
        if days_left <= EXPIRING_SOON_DAYS:
            issues.append(
                _warning(
                    "EXPIRING_SOON",
                    f"{label(coverage.type.value).title()} policy {coverage.policy_number} "
                    f"expires {coverage.expiration.isoformat()} ({days_left} days).",
                )
            )

    return issues


def build_draft(extracted: ExtractedRequest, client: Client, today: date) -> CertificateDraft:
    """Assemble the certificate snapshot from *policy data*, never from the email.

    The description of operations is a conservative template. It only mentions endorsements
    the policy actually carries, and always defers to the policy terms. A reviewer must still
    confirm the wording matches the carrier's endorsement forms (docs/RISKS_AND_COMPLIANCE.md).
    """
    in_force = coverages_in_force(client, today)
    gl = next((c for c in in_force if c.type is CoverageType.GENERAL_LIABILITY), None)

    sentences: list[str] = []
    if extracted.project_description:
        sentences.append(f"Re: {extracted.project_description}.")
    if gl is not None:
        granted = [
            _ENDORSEMENT_LABEL[e]
            for e in (
                Endorsement.ADDITIONAL_INSURED,
                Endorsement.WAIVER_OF_SUBROGATION,
                Endorsement.PRIMARY_NONCONTRIBUTORY,
            )
            if e in extracted.requested_endorsements and e in gl.endorsements
        ]
        if granted:
            sentences.append(
                "General liability policy includes: "
                + ", ".join(granted)
                + ", where required by written contract and subject to the policy's terms, "
                "conditions and exclusions."
            )

    return CertificateDraft(
        insured_name=client.name,
        insured_address=client.address,
        holder_name=extracted.holder_name,
        holder_address=extracted.holder_address,
        description_of_operations=" ".join(sentences),
        coverages=in_force,
        issued_on=today,
    )
