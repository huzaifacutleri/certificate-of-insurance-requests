"""Render a ``CertificateDraft`` to PDF bytes with reportlab.

IMPORTANT: this is the product's own certificate layout, *not* a copy of the ACORD 25 form.
ACORD forms are licensed; agencies that must issue on ACORD paper need a licensed form
(see docs/RISKS_AND_COMPLIANCE.md and docs/ROADMAP.md).
"""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import CertificateDraft, Coverage
from .validation import label, money

DISCLAIMER = (
    "This certificate is issued for information only and confers no rights upon the "
    "certificate holder. It does not amend, extend or alter the coverage afforded by the "
    "policies listed above."
)


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    """Paragraph with user-supplied text escaped (names like 'A&B Roofing' break reportlab's
    XML-ish markup otherwise)."""
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _limits_text(coverage: Coverage) -> str:
    return "\n".join(f"{label(k).capitalize()}: {money(v)}" for k, v in coverage.limits.items())


def _draw_draft_watermark(canvas, doc) -> None:  # reportlab callback signature
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 90)
    canvas.setFillColorRGB(0.92, 0.92, 0.92)
    canvas.translate(letter[0] / 2, letter[1] / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "DRAFT")
    canvas.restoreState()


def render_certificate(draft: CertificateDraft, agency_name: str, final: bool) -> bytes:
    """Return the certificate as PDF bytes.

    ``final=False`` stamps a DRAFT watermark so an unapproved certificate can never be
    mistaken for an issued one.
    """
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], fontSize=16, spaceAfter=4)
    heading = ParagraphStyle("heading", parent=styles["Heading4"], spaceAfter=2, spaceBefore=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.grey)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title="Certificate of Insurance",
        author=agency_name,
    )

    story: list = [
        _p("CERTIFICATE OF INSURANCE", title),
        _p(f"Issued {draft.issued_on.isoformat()} by {agency_name}", small),
        Spacer(1, 10),
    ]

    parties = Table(
        [
            [
                _p("INSURED", heading),
                _p("CERTIFICATE HOLDER", heading),
            ],
            [
                _p(f"{draft.insured_name}\n{draft.insured_address}".strip(), body),
                _p(f"{draft.holder_name or '-'}\n{draft.holder_address or ''}".strip(), body),
            ],
        ],
        colWidths=[3.5 * inch, 3.5 * inch],
    )
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(parties)

    story.append(_p("COVERAGES", heading))
    rows: list[list] = [
        [
            _p(h, small)
            for h in ("Coverage", "Carrier", "Policy no.", "Effective", "Expires", "Limits")
        ]
    ]
    for c in draft.coverages:
        rows.append(
            [
                _p(label(c.type.value).title(), body),
                _p(c.carrier, body),
                _p(c.policy_number, body),
                _p(c.effective.isoformat(), body),
                _p(c.expiration.isoformat(), body),
                _p(_limits_text(c), body),
            ]
        )
    table = Table(
        rows, colWidths=[1.0 * inch, 1.1 * inch, 0.9 * inch, 0.9 * inch, 0.9 * inch, 2.3 * inch]
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)

    if draft.description_of_operations:
        story.append(_p("DESCRIPTION OF OPERATIONS", heading))
        story.append(_p(draft.description_of_operations, body))

    story.append(Spacer(1, 14))
    story.append(_p(DISCLAIMER, small))

    on_page = (lambda c, d: None) if final else _draw_draft_watermark
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
