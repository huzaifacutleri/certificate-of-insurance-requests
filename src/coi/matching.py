"""Match the insured named in an email to a client on file.

Wrong matches are the most dangerous failure in this product (a certificate issued for the
wrong insured), so the matcher is conservative: it auto-matches only when one candidate is
clearly best, and otherwise returns AMBIGUOUS / NOT_FOUND for a human to resolve.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

from .models import Candidate, Client, MatchResult, MatchStatus

# Corporate suffixes carry no identity ("Summit Roofing LLC" == "Summit Roofing, Inc.").
_SUFFIXES = {
    "llc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "lp",
    "llp",
}

AUTO_MATCH_THRESHOLD = 0.90  # best candidate must score at least this...
MIN_MARGIN = 0.05  # ...and beat the runner-up by at least this much.
CANDIDATE_THRESHOLD = 0.60  # below this a name is not even worth suggesting.


def normalize(name: str) -> str:
    """Lowercase, drop punctuation and corporate suffixes, collapse whitespace."""
    tokens = re.sub(r"[^a-z0-9 ]+", " ", name.lower().replace("&", " and ")).split()
    return " ".join(t for t in tokens if t not in _SUFFIXES)


def similarity(a: str, b: str) -> float:
    """0..1 similarity between two business names."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    # Token containment ("Summit Roofing" inside "Summit Roofing and Siding") is a weaker signal
    # than equality, so it is capped below the auto-match threshold. Single-word names are
    # excluded: "Summit" being inside "Summit Roofing" says almost nothing.
    ta, tb = set(na.split()), set(nb.split())
    if min(len(ta), len(tb)) >= 2:
        containment = len(ta & tb) / min(len(ta), len(tb))
        ratio = max(ratio, min(containment, 1.0) * 0.85)
    return ratio


def match_client(insured_name: str | None, clients: Iterable[Client]) -> MatchResult:
    if not insured_name or not insured_name.strip():
        return MatchResult(status=MatchStatus.NOT_FOUND)

    scored = sorted(
        (
            Candidate(client_id=c.id, name=c.name, score=round(similarity(insured_name, c.name), 3))
            for c in clients
        ),
        key=lambda cand: cand.score,
        reverse=True,
    )
    candidates = [c for c in scored if c.score >= CANDIDATE_THRESHOLD][:5]
    if not candidates:
        return MatchResult(status=MatchStatus.NOT_FOUND)

    best = candidates[0]
    runner_up = candidates[1].score if len(candidates) > 1 else 0.0
    if best.score >= AUTO_MATCH_THRESHOLD and best.score - runner_up >= MIN_MARGIN:
        return MatchResult(
            status=MatchStatus.MATCHED,
            client_id=best.client_id,
            score=best.score,
            candidates=candidates,
        )
    return MatchResult(status=MatchStatus.AMBIGUOUS, score=best.score, candidates=candidates)
