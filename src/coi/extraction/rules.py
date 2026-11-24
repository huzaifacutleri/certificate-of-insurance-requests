"""Deterministic, offline baseline extractor.

It handles emails that use labelled lines ("Insured: ...", "Certificate holder: ...") and
common phrases ("additional insured", "$1,000,000 per occurrence"). Free-form emails are
the LLM extractor's job; this one exists so that:

* the whole pipeline runs and is testable with no network or API key, and
* there is a cheap fallback / comparison baseline when evaluating the LLM extractor.

It never guesses: a field it cannot find stays ``None`` and surfaces later as a
validation issue.
"""

from __future__ import annotations

import re

from ..models import (
    AGGREGATE,
    COMBINED_SINGLE_LIMIT,
    EACH_ACCIDENT,
    EACH_OCCURRENCE,
    GENERAL_AGGREGATE,
    CoverageType,
    Endorsement,
    ExtractedRequest,
    IncomingEmail,
    RequiredCoverage,
)

# Label text (lowercase) -> logical field.
_LABELS = {
    "insured": "insured",
    "named insured": "insured",
    "vendor": "insured",
    "subcontractor": "insured",
    "certificate holder": "holder",
    "holder": "holder",
    "send to": "holder",
    "send certificate to": "holder",
    "project": "project",
    "job": "project",
    "description of operations": "project",
}
# "Label: value" lines. Only ":" counts as a separator so addresses like "Suite 2 - Rear"
# are not mistaken for labels.
_LABELED_LINE = re.compile(r"^\s*(?P<label>[A-Za-z' ]{2,40}):\s*(?P<value>.*)$")


def _scan_labeled_fields(text: str) -> dict[str, str]:
    """Collect ``insured`` / ``holder`` / ``project`` values and the holder's address lines."""
    fields: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _LABELED_LINE.match(lines[i])
        key = _LABELS.get(m["label"].strip().lower()) if m else None
        if key and key not in fields and m["value"].strip():
            fields[key] = m["value"].strip()
            if key == "holder":
                # Up to three following non-blank, non-label lines are the holder's address.
                address: list[str] = []
                j = i + 1
                while (
                    j < len(lines)
                    and lines[j].strip()
                    and not _LABELED_LINE.match(lines[j])
                    and len(address) < 3
                ):
                    address.append(lines[j].strip())
                    j += 1
                if address:
                    fields["holder_address"] = ", ".join(address)
                i = j - 1
        i += 1
    return fields


# $1,000,000 | $1M | $1 million | $500k
_AMOUNT = re.compile(
    r"\$\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>million|mm|m|thousand|k)?\b",
    re.IGNORECASE,
)
_UNIT_MULTIPLIER = {
    "million": 1_000_000,
    "mm": 1_000_000,
    "m": 1_000_000,
    "thousand": 1_000,
    "k": 1_000,
}


def _to_dollars(num: str, unit: str | None) -> int:
    value = float(num.replace(",", "").rstrip("."))
    return int(round(value * _UNIT_MULTIPLIER.get((unit or "").lower(), 1)))


def _coverage_in(line: str) -> CoverageType | None:
    """Which coverage a line is talking about, judged by keywords (most specific first)."""
    low = line.lower()
    if re.search(r"umbrella|excess", low):
        return CoverageType.UMBRELLA
    if re.search(r"\bauto\b|automobile|vehicle", low):
        return CoverageType.AUTO_LIABILITY
    if re.search(r"workers'?\s*comp", low):
        return CoverageType.WORKERS_COMP
    if re.search(r"general liability|\bc?gl\b|per occurrence|each occurrence|aggregate", low):
        return CoverageType.GENERAL_LIABILITY
    return None


def _limit_key(descriptor: str, coverage: CoverageType) -> str | None:
    """Map the words right after a dollar amount to a canonical limit key."""
    low = descriptor.lower()
    if "aggregate" in low:
        return AGGREGATE if coverage is CoverageType.UMBRELLA else GENERAL_AGGREGATE
    if re.search(r"combined single|\bcsl\b", low):
        return COMBINED_SINGLE_LIMIT
    if re.search(r"each accident|per accident", low):
        return EACH_ACCIDENT
    if re.search(r"occurrence", low):
        return EACH_OCCURRENCE
    return None


def _scan_coverages(text: str) -> list[RequiredCoverage]:
    required: dict[CoverageType, dict[str, int]] = {}
    current: CoverageType | None = None  # a coverage heading carries over to following lines
    for line in text.splitlines():
        mentioned = _coverage_in(line)
        if mentioned:
            current = mentioned
            required.setdefault(mentioned, {})
        coverage = mentioned or current
        if not coverage:
            continue
        matches = list(_AMOUNT.finditer(line))
        for idx, m in enumerate(matches):
            # The descriptor is the text after the amount, up to the next amount.
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(line)
            descriptor = line[m.end() : min(end, m.end() + 40)]
            key = _limit_key(descriptor, coverage)
            if key is None and coverage is CoverageType.AUTO_LIABILITY:
                key = COMBINED_SINGLE_LIMIT  # a bare auto amount is conventionally the CSL
            if key:
                required.setdefault(coverage, {})[key] = _to_dollars(m["num"], m["unit"])
    return [RequiredCoverage(type=t, min_limits=limits) for t, limits in required.items()]


_ENDORSEMENT_PATTERNS = {
    Endorsement.ADDITIONAL_INSURED: r"additional\s+insured",
    Endorsement.WAIVER_OF_SUBROGATION: r"waiver\s+of\s+subrogation",
    Endorsement.PRIMARY_NONCONTRIBUTORY: r"primary\s*(?:and|&|/)?\s*non-?\s*contributory",
}


class RuleBasedExtractor:
    name = "rules"

    def extract(self, email: IncomingEmail) -> ExtractedRequest:
        text = email.body
        fields = _scan_labeled_fields(text)
        endorsements = {
            e for e, pattern in _ENDORSEMENT_PATTERNS.items() if re.search(pattern, text, re.I)
        }
        notes: list[str] = []
        if "insured" not in fields:
            notes.append("No 'Insured:' line found.")
        if "holder" not in fields:
            notes.append("No 'Certificate holder:' line found.")
        if email.attachment_names:
            notes.append(
                "Email has attachments that were not read: " + ", ".join(email.attachment_names)
            )
        return ExtractedRequest(
            insured_name=fields.get("insured"),
            holder_name=fields.get("holder"),
            holder_address=fields.get("holder_address"),
            project_description=fields.get("project"),
            requested_endorsements=endorsements,
            required_coverages=_scan_coverages(text),
            extractor=self.name,
            notes=notes,
        )
