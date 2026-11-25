"""evals/event_replay.py's rules: what a lesson's text names, and when that fires on a change.

REPORT §4bm rests on these functions, so each rule is shown on a small case: a figure from an
instrument nobody tested is a figure about the instrument. The run itself needs §4bj's built tasks,
which are not committed, so it is not run here.
"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def replay():
    """The script as a module; it reads the eval helpers beside it, so evals/ is on the path while it loads."""
    sys.path.insert(0, str(REPO / "evals"))
    try:
        import event_replay
    finally:
        sys.path.remove(str(REPO / "evals"))
    return event_replay


LESSON = """[example] Rule · Every caller of Client.check that briefs no agent asks for it unlogged
symptom: okl metric's exposure counts jump after a run of evals/layout_preflight.py
fix: set OKL_BRIEFING_LOG=0 before building the Client; see docs/COSTS-AND-KNOBS.md and pass --no-log
body: e.g. record_briefing() wrote a row for and/or every lookup in src/okl/cli/, version 0.17.0"""


def test_a_lesson_names_paths_and_pieces_of_code(replay):
    """Paths are words with a slash or a file name with a known extension; code is a dotted name, a
    call, an ALL_CAPS, snake_case or CamelCase name, or a --flag. Prose is neither."""
    assert replay.named_paths(LESSON) == {"evals/layout_preflight.py", "docs/COSTS-AND-KNOBS.md", "src/okl/cli"}
    code = replay.named_code(LESSON)
    assert {"Client.check", "OKL_BRIEFING_LOG", "record_briefing", "--no-log"} <= code
    assert not {"exposure", "symptom", "and/or", "0.17.0", "layout_preflight.py"} & code


@pytest.mark.parametrize("named, changed, fires", [
    ({"src/okl/cli"}, ["src/okl/cli/intake.py"], True),            # a folder the lesson names holds the file
    ({"evals/layout_preflight.py"}, ["evals/layout_preflight.py"], True),
    ({"intake.py"}, ["src/okl/cli/intake.py"], True),              # a bare file name
    ({"hooks/*.sh"}, ["hooks/stop-okl-encode.sh"], True),          # a star within one segment
    ({"hooks/*.sh"}, ["hooks/nested/x.sh"], False),
    ({"hooks/*.sh"}, ["src/hooks/a.sh"], True),                    # as a path without a star ends a longer one
    ({"hooks/*.sh"}, ["otherhooks/run.sh"], False),                # a star does not loosen where the name starts
    ({"hooks/*.sh"}, ["hooks/run.sh.bak"], False),                 # or where it ends
    ({"src/okl/cli"}, ["src/okl/client.py"], False),               # a folder is not a prefix of a name
    ({"docs/COSTS-AND-KNOBS.md"}, ["README.md"], False),
])
def test_a_named_path_fires_on_a_changed_file_its_folder_or_its_bare_name(replay, named, changed, fires):
    """Each way a named path matches a changed file, and the near misses that must not."""
    assert replay.path_fires(named, changed) is fires


def test_named_code_fires_only_whole_and_only_in_added_lines(replay):
    """The change's added lines are read, not its removed ones or its headers, and a name inside a
    longer name is not that name."""
    diff = "\n".join(["diff --git a/a.py b/a.py", "--- a/a.py", "+++ b/a.py", "@@ -1,2 +1,2 @@",
                      "-old = Client.check(task)", "+new = client.check_all(task)", "+flag = OKL_BRIEFING_LOG"])
    assert replay.changed_paths(diff) == ["a.py"]
    added = replay.added_lines(diff)
    assert "Client.check(task)" not in added and "a.py" not in added
    assert replay.code_fires({"OKL_BRIEFING_LOG"}, added) is True
    assert replay.code_fires({"Client.check"}, added) is False, "removed, and check_all is another name"
    assert replay.code_fires({"client.check"}, added) is False, "client.check_all is not client.check"
    assert replay.code_fires({"--no-log"}, "run(\"--no-log-extra\")") is False, "a longer flag is another flag"
    assert replay.code_fires({"--no-log"}, "run(\"--no-log\")") is True and replay.code_fires({"--no-log"}, "x --no-log y") is True


def test_a_file_name_with_several_dots_is_one_path_and_not_code(replay):
    """`worker.test.py` is a file: named whole as a path, and never read as the dotted name of some code."""
    text = "symptom: the suite in worker.test.py passes while okl.client.check fails"
    assert replay.named_paths(text) == {"worker.test.py"}
    assert "worker.test.py" not in replay.named_code(text) and "okl.client.check" in replay.named_code(text)
    assert replay.path_fires({"worker.test.py"}, ["src/worker.test.py"]) is True


def test_the_reports_figures_are_the_receipts():
    """REPORT §4bm's table and counts are read back from the receipt it names, and the two figures
    it sets beside them from §4bl's receipt: a table typed by hand is a table that can drift from
    the run (lesson comparison-table-one-sitting-generated, which the review at a push applied to
    this section's first draft)."""
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = report[report.index("## 4bm."):report.index("## 5. Findings")]
    results = REPO / "evals" / "results"
    receipt = json.loads((results / re.search(r"`(event-replay-[0-9-]+[.]json)`", section).group(1)).read_text())
    n = receipt["tasks"]
    for arm in ("governs today", "paths", "code", "either"):
        a = receipt["rates"][arm]
        row = f"| {a['right_fired']} of {n} ({a['rate']}) | {a['fired_median']} ({a['fired_min']} to {a['fired_max']}) |"
        assert row in section, (arm, row)
    today = receipt["store_today"]
    assert f"break {today['distinct_right_lessons']} distinct lessons" in section
    assert (f"{len(today['with_an_observed_check'])} of them have an observed check and "
            f"{len(today['with_files'])} have files") in section
    assert receipt["okl_commit"] == receipt["okl_commit_at_start"] and f"at {receipt['okl_commit']}" in section
    pick = json.loads((results / "lesson-finding-20261117-0441.json").read_text())["reach"]
    assert f"on {pick['n10']['rate']} of the tasks" in section and f"{pick['n30']['rate']} (`lesson-finding" in section
    assert "a model's pick of" not in section, "the other sitting's figures stay out of this run's table"
