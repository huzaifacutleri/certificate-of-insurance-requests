"""Shared fixtures: an in-memory database loaded with the example clients."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from coi.extraction import RuleBasedExtractor
from coi.models import Client
from coi.storage import Repository, connect
from coi.workflow import Workflow

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
TODAY = date(2026, 11, 24)


def load_clients() -> list[Client]:
    return [Client.model_validate(c) for c in json.loads((EXAMPLES / "clients.json").read_text())]


def example_email(name: str) -> bytes:
    return (EXAMPLES / "requests" / name).read_bytes()


@pytest.fixture
def clients() -> list[Client]:
    return load_clients()


@pytest.fixture
def repo(clients) -> Repository:
    repo = Repository(connect(":memory:"), agency_id="test-agency")
    repo.upsert_clients(clients)
    return repo


@pytest.fixture
def workflow(repo) -> Workflow:
    return Workflow(repo, RuleBasedExtractor(), "Test Agency", clock=lambda: TODAY)
