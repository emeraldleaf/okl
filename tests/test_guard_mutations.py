"""ci/check-guard-mutations.py must not count what it could not see.

A guard counts as caught when pytest exits 1 with the guard switched off. A test that fails with
nothing switched off gives that exit for every guard, so the check passed whatever the guards
were: on a developer machine it said "CAUGHT 53 of 53" while CI named a guard no test held
(#511, issue #512). It now runs the tests once with every guard on and refuses to count when
they do not pass. These tests run the real check on a small repository of its own.
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELD = ("src/toy.py", "    if n < 0:", "    if False:", "a negative number")
NOT_HELD = ("src/toy.py", "    if n > 9:", "    if False:", "a number above nine")
BROKEN = "tests/test_broken.py::test_this_machine_cannot_pass"


@pytest.fixture
def check(tmp_path, monkeypatch):
    """The check, pointed at a repository with two guards, one test that holds the first of them,
    and one test that fails whatever the code does."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "toy"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "toy.py").write_text(
        "def allowed(n):\n    if n < 0:\n        return False\n    if n > 9:\n        return False\n    return True\n")
    (repo / "tests" / "test_toy.py").write_text(
        "import toy\n\n\ndef test_a_negative_number_is_refused():\n    assert toy.allowed(-1) is False and toy.allowed(1) is True\n")
    (repo / "tests" / "test_broken.py").write_text("def test_this_machine_cannot_pass():\n    raise AssertionError\n")
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "toy"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    spec = importlib.util.spec_from_file_location("check_guard_mutations", ROOT / "ci" / "check-guard-mutations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "REPO", repo)
    monkeypatch.setattr(module, "GUARD_CALLS", {})
    monkeypatch.setattr(module, "MUTATIONS", [HELD, NOT_HELD])
    monkeypatch.setattr(module, "TESTS", ["tests/test_toy.py"])
    return module


def test_a_guard_no_test_holds_is_named_and_one_that_is_held_passes(check, monkeypatch, capsys):
    """The check's two answers on tests that pass: exit 1 naming the guard nothing holds, and exit 0
    with a count when each is held. The file it edits is put back as it was."""
    before = (check.REPO / "src" / "toy.py").read_bytes()
    assert check.main([]) == 1
    out = capsys.readouterr().out
    assert "GUARD MUTATIONS MISSED 1 of 2" in out and "a number above nine" in out and "a negative number" not in out, out
    monkeypatch.setattr(check, "MUTATIONS", [HELD])
    assert check.main([]) == 0
    assert capsys.readouterr().out.strip() == "GUARD MUTATIONS CAUGHT 1 of 1"
    assert (check.REPO / "src" / "toy.py").read_bytes() == before


def test_with_a_test_that_fails_anyway_the_check_does_not_run_and_counts_nothing(check, monkeypatch, capsys):
    """A test that fails with every guard on makes pytest exit 1 for every guard. The check used to
    read that as "caught" and print a full count for a guard no test holds; it now exits 2 ("did
    not run"), names the failing test on stderr and prints no count."""
    monkeypatch.setattr(check, "TESTS", ["tests/test_toy.py", "tests/test_broken.py"])
    assert check.main([]) == 2
    said = capsys.readouterr()
    assert said.out == "", said.out
    assert "GUARD MUTATIONS NOT RUN" in said.err and f"FAILED {BROKEN}" in said.err, said.err
    assert "CAUGHT" not in said.err and "MISSED" not in said.err


def test_a_test_left_out_by_name_is_named_in_the_result_and_hides_no_missed_guard(check, monkeypatch, capsys):
    """`--deselect` leaves out a test that cannot pass on this machine. The guard no test holds is
    still named, and both results say which test was left out, so a count is never read as fuller
    than it was."""
    monkeypatch.setattr(check, "TESTS", ["tests/test_toy.py", "tests/test_broken.py"])
    assert check.main(["--deselect", BROKEN]) == 1
    out = capsys.readouterr().out
    assert "GUARD MUTATIONS MISSED 1 of 2" in out and "a number above nine" in out and f"left out: {BROKEN}" in out, out
    monkeypatch.setattr(check, "MUTATIONS", [HELD])
    assert check.main(["--deselect", BROKEN]) == 0
    assert capsys.readouterr().out.strip() == f"GUARD MUTATIONS CAUGHT 1 of 1, with 1 test(s) left out: {BROKEN}"


def test_tests_that_cannot_be_collected_are_not_a_pass(check, monkeypatch, capsys):
    """A test file that is not there is pytest exit 4, not 1: nothing was run, so nothing is counted."""
    monkeypatch.setattr(check, "TESTS", ["tests/test_not_here.py"])
    assert check.main([]) == 2
    said = capsys.readouterr()
    assert said.out == "" and "GUARD MUTATIONS NOT RUN" in said.err and "pytest exit 4" in said.err, said.err
