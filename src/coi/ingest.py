"""Parse raw RFC 822 email bytes into an ``IncomingEmail``.

Uses only the standard library. In production this is fed by a mailbox connector
(Gmail / Microsoft Graph, see docs/ROADMAP.md); for the MVP it takes ``.eml`` files or
raw bytes posted to the API.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from .models import IncomingEmail


class _TextFromHTML(HTMLParser):
    """Minimal HTML-to-text: keeps text, turns block-level tags into newlines."""

    _BREAKS = {"br", "p", "div", "tr", "li"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0  # depth inside <script>/<style>

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BREAKS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in self._BREAKS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    parser = _TextFromHTML()
    parser.feed(html)
    return parser.text()


def parse_email(raw: bytes, received_at: datetime | None = None) -> IncomingEmail:
    """Parse ``raw`` email bytes.

    ``received_at`` defaults to the message's Date header, then to "now" (UTC).
    A missing Message-ID is replaced by a content hash so de-duplication still works.
    """
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        body = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            body = html_to_text(body)

    message_id = (msg["Message-ID"] or "").strip()
    if not message_id:
        message_id = "sha256:" + hashlib.sha256(raw).hexdigest()

    if received_at is None:
        try:
            received_at = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
        except (TypeError, ValueError):
            received_at = None
    received_at = received_at or datetime.now(UTC)

    attachments = [p.get_filename() or "(unnamed)" for p in msg.iter_attachments()]

    return IncomingEmail(
        message_id=message_id,
        sender=parseaddr(msg["From"] or "")[1],
        subject=str(msg["Subject"] or ""),
        body=body.strip(),
        received_at=received_at,
        attachment_names=attachments,
    )
