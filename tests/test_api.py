"""API smoke tests. Skipped automatically when the optional `api` extra is not installed."""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from .conftest import EXAMPLES, example_email  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COI_DB", ":memory:")
    monkeypatch.setenv("COI_API_KEY", "secret")
    import coi.api

    module = importlib.reload(coi.api)
    return TestClient(module.app)


H = {"X-API-Key": "secret"}


def test_requires_api_key(client):
    assert client.get("/requests").status_code == 401
    assert client.get("/requests", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/health").status_code == 200


def test_full_flow(client):
    clients_json = (EXAMPLES / "clients.json").read_text()
    assert (
        client.put(
            "/clients", content=clients_json, headers={**H, "Content-Type": "application/json"}
        ).status_code
        == 200
    )
    created = client.post("/requests", content=example_email("01_clean_request.eml"), headers=H)
    assert created.status_code == 200
    request_id = created.json()["id"]
    assert client.get(f"/requests/{request_id}/certificate.pdf", headers=H).content.startswith(
        b"%PDF"
    )
    assert client.post(f"/requests/{request_id}/approve", headers=H).json()["status"] == "approved"
    assert client.post(f"/requests/{request_id}/approve", headers=H).status_code == 409
