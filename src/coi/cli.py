"""Command-line interface: the fastest way to try the pipeline and to operate it by hand.

python -m coi demo                      # end-to-end run on the bundled examples
python -m coi import-clients FILE.json  # load policy data (an export from your AMS)
python -m coi ingest FILE.eml ...       # process request emails
python -m coi list [--status STATUS]
python -m coi show REQUEST_ID
python -m coi approve|reject|sent REQUEST_ID
python -m coi pdf REQUEST_ID [-o FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from .config import Settings
from .extraction import build_extractor
from .models import Client, CoiRequest, RequestStatus
from .storage import Repository, RequestNotFound, connect
from .workflow import ApprovalBlocked, Workflow, WorkflowError

# The bundled examples are written relative to this date so the demo is reproducible.
DEMO_TODAY = date(2026, 11, 24)
EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def _build(settings: Settings, today: date | None = None) -> tuple[Repository, Workflow]:
    repo = Repository(connect(settings.db_path), settings.agency_id)
    clock = (lambda: today) if today else date.today
    return repo, Workflow(repo, build_extractor(settings), settings.agency_name, clock)


def _summarize(r: CoiRequest) -> str:
    holder = r.extracted.holder_name or "?"
    insured = r.extracted.insured_name or "?"
    return f"{r.id[:8]}  {r.status.value:<17} {insured}  ->  {holder}"


def _print_detail(r: CoiRequest) -> None:
    print(_summarize(r))
    print(f"  from: {r.email.sender}   subject: {r.email.subject}")
    print(f"  match: {r.match.status.value} (score {r.match.score})")
    for issue in r.issues:
        print(f"  [{issue.severity.value.upper():<7}] {issue.code}: {issue.message}")
    if not r.issues:
        print("  no issues")


def cmd_demo(args: argparse.Namespace, settings: Settings) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.fromisoformat(args.today) if args.today else DEMO_TODAY
    # Fresh throwaway database each run so the demo is repeatable.
    demo_settings = Settings(
        db_path=str(Path(tempfile.mkdtemp()) / "demo.db"),
        agency_id=settings.agency_id,
        agency_name=settings.agency_name,
        extractor="rules",  # the demo must work offline
    )
    repo, workflow = _build(demo_settings, today)
    clients = [
        Client.model_validate(c) for c in json.loads((EXAMPLES_DIR / "clients.json").read_text())
    ]
    repo.upsert_clients(clients)
    print(f"Loaded {len(clients)} clients. Treating today as {today.isoformat()}.\n")

    for eml in sorted((EXAMPLES_DIR / "requests").glob("*.eml")):
        request = workflow.process_email(eml.read_bytes(), actor="demo")
        print(f"{eml.name}")
        _print_detail(request)
        if request.draft is not None:
            pdf_path = out_dir / f"{eml.stem}.pdf"
            pdf_path.write_bytes(workflow.render_pdf(request.id))
            print(f"  draft PDF: {pdf_path}")
        print()

    # Show the approval step on the first clean request.
    clean = next((r for r in repo.list_requests(RequestStatus.READY_FOR_REVIEW)), None)
    if clean is not None:
        workflow.approve(clean.id, actor="demo-csr")
        final = out_dir / "approved_final.pdf"
        final.write_bytes(workflow.render_pdf(clean.id))
        print(f"Approved {clean.id[:8]} as demo-csr -> {final} (no DRAFT watermark)")
    return 0


def cmd_import_clients(args: argparse.Namespace, settings: Settings) -> int:
    repo, _ = _build(settings)
    clients = [Client.model_validate(c) for c in json.loads(Path(args.file).read_text())]
    repo.upsert_clients(clients)
    print(f"Imported {len(clients)} clients.")
    return 0


def cmd_ingest(args: argparse.Namespace, settings: Settings) -> int:
    _, workflow = _build(settings)
    for path in args.files:
        _print_detail(workflow.process_email(Path(path).read_bytes(), actor="cli"))
    return 0


def cmd_list(args: argparse.Namespace, settings: Settings) -> int:
    repo, _ = _build(settings)
    status = RequestStatus(args.status) if args.status else None
    for r in repo.list_requests(status):
        print(_summarize(r))
    return 0


def _resolve(repo: Repository, prefix: str) -> str:
    """Allow the short 8-character ids that ``list`` prints."""
    matches = [r.id for r in repo.list_requests() if r.id.startswith(prefix)]
    if len(matches) != 1:
        raise RequestNotFound(prefix)
    return matches[0]


def cmd_show(args: argparse.Namespace, settings: Settings) -> int:
    repo, _ = _build(settings)
    request_id = _resolve(repo, args.request_id)
    _print_detail(repo.get_request(request_id))
    for entry in repo.list_audit(request_id):
        print(f"  audit {entry['at']}  {entry['actor']}  {entry['action']}  {entry['detail']}")
    return 0


def cmd_transition(args: argparse.Namespace, settings: Settings) -> int:
    repo, workflow = _build(settings)
    request_id = _resolve(repo, args.request_id)
    actor = args.actor
    if args.command == "approve":
        workflow.approve(request_id, actor)
    elif args.command == "reject":
        workflow.reject(request_id, actor, args.reason)
    else:  # sent
        workflow.mark_sent(request_id, actor)
    _print_detail(repo.get_request(request_id))
    return 0


def cmd_pdf(args: argparse.Namespace, settings: Settings) -> int:
    repo, workflow = _build(settings)
    request_id = _resolve(repo, args.request_id)
    out = Path(args.output or f"{request_id[:8]}.pdf")
    out.write_bytes(workflow.render_pdf(request_id))
    print(f"Wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coi", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run the bundled examples end to end")
    demo.add_argument("--out", default="out", help="directory for generated PDFs")
    demo.add_argument("--today", help="override the demo date (YYYY-MM-DD)")
    demo.set_defaults(func=cmd_demo)

    imp = sub.add_parser("import-clients", help="load clients/policies from a JSON file")
    imp.add_argument("file")
    imp.set_defaults(func=cmd_import_clients)

    ing = sub.add_parser("ingest", help="process .eml request files")
    ing.add_argument("files", nargs="+")
    ing.set_defaults(func=cmd_ingest)

    lst = sub.add_parser("list", help="list requests")
    lst.add_argument("--status", choices=[s.value for s in RequestStatus])
    lst.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="show one request with its issues and audit trail")
    show.add_argument("request_id")
    show.set_defaults(func=cmd_show)

    for name in ("approve", "reject", "sent"):
        p = sub.add_parser(name, help=f"{name} a request")
        p.add_argument("request_id")
        p.add_argument(
            "--actor", default="cli", help="who is doing this (recorded in the audit log)"
        )
        if name == "reject":
            p.add_argument("--reason", default="")
        p.set_defaults(func=cmd_transition)

    pdf = sub.add_parser("pdf", help="render a request's certificate to a PDF file")
    pdf.add_argument("request_id")
    pdf.add_argument("-o", "--output")
    pdf.set_defaults(func=cmd_pdf)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, Settings.from_env())
    except ApprovalBlocked as exc:
        print(f"Approval blocked: {exc}", file=sys.stderr)
        return 2
    except (WorkflowError, RequestNotFound) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
