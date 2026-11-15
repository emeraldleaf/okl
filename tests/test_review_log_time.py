"""evals/review_log_time.py times the review log as a process, and a run that failed is no receipt (#464).

A timing of a command that exited non-zero measures how fast it failed, so the script names the cases
that did and writes nothing. Its transcripts are resolved before the process changes directory.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "evals"))
import review_log_time  # noqa: E402


def _run_with(monkeypatch, tmp_path, code: int, *args: str):
    """`main()` with the timed process replaced by one that exits `code`; the commands it was given."""
    seen = []
    real = subprocess.run

    def fake(cmd, **kw):
        if "recap" in cmd:
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, code, b"", b"")
        return real(cmd, **kw)
    monkeypatch.setattr(review_log_time.subprocess, "run", fake)
    (tmp_path / "results").mkdir()
    monkeypatch.setattr(review_log_time, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(sys, "argv", ["review_log_time.py", "--runs", "1", *args])
    return review_log_time.main(), seen


def test_a_run_that_exited_non_zero_leaves_no_receipt(monkeypatch, tmp_path, capsys):
    """The cases that failed are named on stderr, the exit is non-zero, and nothing is written."""
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n")

    code, _ = _run_with(monkeypatch, tmp_path, 1, "--no-synthetic", str(t))

    assert code == 1
    assert list((tmp_path / "results").iterdir()) == []
    assert "real transcript 1 by size" in capsys.readouterr().err


def test_a_run_that_succeeded_writes_the_receipt_and_a_relative_path_is_made_absolute(monkeypatch, tmp_path):
    """Sizes and seconds only; and the process, which runs in the scratch repository, is given the
    transcript's absolute path, whatever directory the script was called from."""
    (tmp_path / "t.jsonl").write_text("{}\n")
    monkeypatch.chdir(tmp_path)

    code, seen = _run_with(monkeypatch, tmp_path, 0, "--no-synthetic", "t.jsonl")

    assert code == 0 and [Path(cmd[cmd.index("--transcript") + 1]).is_absolute() for cmd in seen] == [True]
    (receipt,) = (tmp_path / "results").iterdir()
    text = receipt.read_text()
    assert '"largest_real_megabytes"' in text and "t.jsonl" not in text and str(tmp_path) not in text
