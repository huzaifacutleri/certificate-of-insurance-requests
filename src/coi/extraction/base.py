"""Extractor interface. Anything that turns an email into an ``ExtractedRequest`` fits."""

from __future__ import annotations

from typing import Protocol

from ..models import ExtractedRequest, IncomingEmail


class ExtractionError(Exception):
    """Raised when an extractor cannot produce a usable result (bad LLM output, API error)."""


class Extractor(Protocol):
    #: Short identifier stored on each extraction, e.g. "rules" or "llm:<model>".
    name: str

    def extract(self, email: IncomingEmail) -> ExtractedRequest: ...
