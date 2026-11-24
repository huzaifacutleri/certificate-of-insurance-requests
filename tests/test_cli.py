from coi.cli import main


def test_demo_runs_and_writes_pdfs(tmp_path, capsys):
    assert main(["demo", "--out", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "ENDORSEMENT_MISSING" in output and "CLIENT_NOT_FOUND" in output
    assert (tmp_path / "approved_final.pdf").read_bytes().startswith(b"%PDF")
