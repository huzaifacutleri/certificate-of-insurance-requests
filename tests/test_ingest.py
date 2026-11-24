from coi.ingest import html_to_text, parse_email

from .conftest import example_email


def test_parses_headers_and_body():
    email = parse_email(example_email("01_clean_request.eml"))
    assert email.sender == "dana@harborproperty.example"
    assert email.message_id == "<demo-001@harborproperty.example>"
    assert "Certificate holder: Harbor Property Group" in email.body


def test_missing_message_id_gets_stable_hash():
    raw = b"From: a@b.example\nSubject: hi\n\nbody"
    first, second = parse_email(raw), parse_email(raw)
    assert first.message_id.startswith("sha256:")
    assert first.message_id == second.message_id


def test_html_only_email_is_converted_to_text():
    raw = (
        b"From: a@b.example\nSubject: hi\nContent-Type: text/html\n\n"
        b"<html><style>p{color:red}</style><p>Insured: Acme</p><p>Holder: X</p></html>"
    )
    body = parse_email(raw).body
    assert "Insured: Acme" in body and "color:red" not in body


def test_html_to_text_skips_scripts():
    assert "alert" not in html_to_text("<script>alert(1)</script><div>ok</div>")


def test_attachment_names_are_listed():
    raw = (
        b"From: a@b.example\nSubject: s\nMIME-Version: 1.0\n"
        b'Content-Type: multipart/mixed; boundary="X"\n\n'
        b"--X\nContent-Type: text/plain\n\nInsured: Acme\n"
        b'--X\nContent-Type: application/pdf\nContent-Disposition: attachment; filename="contract.pdf"\n\nJVBERi0=\n'
        b"--X--\n"
    )
    assert parse_email(raw).attachment_names == ["contract.pdf"]
