"""Request extraction: turning an email into structured data."""

from __future__ import annotations

from ..config import Settings
from .base import ExtractionError, Extractor
from .llm import LLMExtractor, anthropic_llm
from .rules import RuleBasedExtractor

__all__ = [
    "ExtractionError",
    "Extractor",
    "LLMExtractor",
    "RuleBasedExtractor",
    "build_extractor",
]


def build_extractor(settings: Settings) -> Extractor:
    """Pick the extractor named in settings. Unknown names fail loudly at startup."""
    if settings.extractor == "rules":
        return RuleBasedExtractor()
    if settings.extractor == "llm":
        return LLMExtractor(anthropic_llm(settings.llm_model), model_label=settings.llm_model)
    raise ValueError(f"Unknown COI_EXTRACTOR {settings.extractor!r}; use 'rules' or 'llm'.")
