"""Thin HTTP API over ``Workflow``. Needs the ``api`` extra (FastAPI + uvicorn).

Run:  COI_API_KEY=change-me uvicorn coi.api:app

This layer holds no business logic: it authenticates, calls the workflow, and maps domain
errors to HTTP status codes. Auth is a single shared key for the MVP pilot; per-user login
and roles are on the roadmap (docs/ROADMAP.md).
"""

from __future__ import annotations

import hmac
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response

from .config import Settings
from .extraction import build_extractor
from .models import Client, CoiRequest, RequestStatus
from .storage import Repository, RequestNotFound, connect
from .workflow import ApprovalBlocked, Workflow, WorkflowError

settings = Settings.from_env()
app = FastAPI(title="COI Assistant", version="0.1.0")

# One connection for the process is fine for SQLite at pilot scale; Postgres will use a pool.
_conn = connect(settings.db_path)
_repo = Repository(_conn, settings.agency_id)
_extractor = build_extractor(settings)


def get_workflow() -> Workflow:
    return Workflow(_repo, _extractor, settings.agency_name, date.today)


def require_api_key(x_api_key: str = Header(default="")) -> None:
    """Constant-time API key check. With no key configured the API stays closed."""
    if not settings.api_key:
        raise HTTPException(503, "COI_API_KEY is not configured")
    if not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(401, "Invalid API key")


auth = [Depends(require_api_key)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.put("/clients", dependencies=auth)
def put_clients(clients: list[Client]) -> dict[str, int]:
    """Replace/insert clients and their policies (e.g. nightly export from the AMS)."""
    _repo.upsert_clients(clients)
    return {"imported": len(clients)}


@app.post("/requests", dependencies=auth, response_model=CoiRequest)
async def ingest_request(request: Request, wf: Workflow = Depends(get_workflow)) -> CoiRequest:
    """Body: a raw RFC 822 email (``Content-Type: message/rfc822``)."""
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "Empty body")
    return wf.process_email(raw, actor="api")


@app.get("/requests", dependencies=auth, response_model=list[CoiRequest])
def list_requests(status: RequestStatus | None = None) -> list[CoiRequest]:
    return _repo.list_requests(status)


def _guard(action):
    """Run a workflow action and translate domain errors into HTTP errors."""
    try:
        return action()
    except RequestNotFound:
        raise HTTPException(404, "Request not found") from None
    except ApprovalBlocked as exc:
        raise HTTPException(
            409, {"error": "approval_blocked", "blockers": [b.message for b in exc.blockers]}
        ) from None
    except WorkflowError as exc:
        raise HTTPException(409, str(exc)) from None


@app.get("/requests/{request_id}", dependencies=auth, response_model=CoiRequest)
def get_request(request_id: str) -> CoiRequest:
    return _guard(lambda: _repo.get_request(request_id))


@app.get("/requests/{request_id}/audit", dependencies=auth)
def get_audit(request_id: str) -> list[dict[str, str]]:
    _guard(lambda: _repo.get_request(request_id))
    return _repo.list_audit(request_id)


@app.post("/requests/{request_id}/reprocess", dependencies=auth, response_model=CoiRequest)
def reprocess(request_id: str, wf: Workflow = Depends(get_workflow)) -> CoiRequest:
    return _guard(lambda: wf.reprocess(request_id, actor="api"))


@app.post("/requests/{request_id}/approve", dependencies=auth, response_model=CoiRequest)
def approve(request_id: str, wf: Workflow = Depends(get_workflow)) -> CoiRequest:
    return _guard(lambda: wf.approve(request_id, actor="api"))


@app.post("/requests/{request_id}/reject", dependencies=auth, response_model=CoiRequest)
def reject(request_id: str, reason: str = "", wf: Workflow = Depends(get_workflow)) -> CoiRequest:
    return _guard(lambda: wf.reject(request_id, actor="api", reason=reason))


@app.post("/requests/{request_id}/sent", dependencies=auth, response_model=CoiRequest)
def mark_sent(request_id: str, wf: Workflow = Depends(get_workflow)) -> CoiRequest:
    return _guard(lambda: wf.mark_sent(request_id, actor="api"))


@app.get("/requests/{request_id}/certificate.pdf", dependencies=auth)
def certificate_pdf(request_id: str, wf: Workflow = Depends(get_workflow)) -> Response:
    pdf = _guard(lambda: wf.render_pdf(request_id))
    return Response(pdf, media_type="application/pdf")
