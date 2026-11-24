"""Runtime configuration, read from environment variables.

Kept in one place so the rest of the code receives plain values and stays easy to test.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Application settings. All fields have safe local-development defaults."""

    # SQLite file path. Swap for Postgres later (see docs/ARCHITECTURE.md).
    db_path: str = "coi.db"
    # Every row is scoped to an agency so one deployment can host several pilots.
    agency_id: str = "demo"
    # Printed on certificates as the issuing agency.
    agency_name: str = "Demo Insurance Agency"
    # "rules" (offline baseline) or "llm" (production path; needs the `llm` extra).
    extractor: str = "rules"
    # Model used when extractor == "llm".
    llm_model: str = "claude-sonnet-5-5"
    # Shared secret for the HTTP API. If unset, the API refuses all requests.
    api_key: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build settings from COI_* environment variables."""
        env = os.environ if env is None else env
        defaults = cls()
        return cls(
            db_path=env.get("COI_DB", defaults.db_path),
            agency_id=env.get("COI_AGENCY_ID", defaults.agency_id),
            agency_name=env.get("COI_AGENCY_NAME", defaults.agency_name),
            extractor=env.get("COI_EXTRACTOR", defaults.extractor),
            llm_model=env.get("COI_LLM_MODEL", defaults.llm_model),
            api_key=env.get("COI_API_KEY") or None,
        )
