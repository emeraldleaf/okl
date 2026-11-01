"""The two pattern checks behind watched lessons, held to the shapes they have met (#318, REPORT
§4ah): the claims §4af's breaks and two local reviews wrote, and the sentences a review showed
they must let through. They run on these sentences only, never on the repository: running the
lessons' checks on the repository is drift's job, and CI doing it would empty their governed
files (#39). A new shape passes the checks until it is added here and to them."""
import runpy
from pathlib import Path

import pytest

CI = Path(__file__).resolve().parents[1] / "ci"
claims = runpy.run_path(str(CI / "check-positioning.py"), run_name="test")["claims"]
unlabelled = runpy.run_path(str(CI / "check-agent-neutral.py"), run_name="test")["unlabelled"]


@pytest.mark.parametrize("text", [
    # §4af's breaks of n_d45d7bf64896
    "okl is built to beat those tools at recall, and replaces them.",
    "okl replaces them with better recall of your team's lessons, and is meant to be used instead of them.",
    "its retrieval is better than theirs, and none of them is worth composing with.",
    "okl's main aim is to be the better memory store: its retrieval is meant to replace a hosted Mem0 configuration.",
    # the local reviews' probes
    "okl remembers more of what matters than mem0 does.",
    "Unlike mem0 or Zep, okl's retrieval is more accurate.",
    "okl's recall is superior to Zep's.",
    "Once okl is installed you will not need claude-mem.",
    "okl finds the right lesson more often than any memory tool.",
    "No memory tool verifies its lessons; okl is the one that does.",
    "okl is the first memory layer that proves what it stores.",
    "okl outranks mem0 on retrieval benchmarks.",
    "okl can stand in for mem0 entirely.",
    "Swap your memory layer for okl.",
    "There is no question that okl beats mem0 on recall.",
    "okl is a stronger memory layer than Zep.",
    "okl's retrieval is more precise than mem0's.",
    "okl makes mem0 unnecessary.",
])
def test_the_positioning_check_catches_each_claim_it_has_met(text):
    """A claim of okl over the memory tools, in a shape met before, fails the check."""
    assert claims(text)


@pytest.mark.parametrize("text", [
    "okl is no replacement for mem0 or Zep.",
    "okl is not meant to replace a memory store; run both.",
    "It doesn't try to replace those tools.",
    "They're worth composing with: they remember what happened, okl keeps what must stay true.",
    "The tiered decision beats the floor on recall, at twice the tokens.",
    "Hybrid retrieval did better than full-text alone on paraphrases.",
    "if semantic recall is the problem you have, those tools are better at it than anything I would build.",
    "okl's recall is weaker than mem0's, by design.",
    "At best, a memory tool reminds the agent; okl gates the push.",
    "Nobody else has to remember to run it: CI does.",
    "It skips files it did not write (with `--force` to replace them), and merges settings.",
])
def test_the_positioning_check_lets_the_stance_and_okls_own_comparisons_through(text):
    """The lesson's own stance, and okl comparing its own settings, pass."""
    assert claims(text) == []


@pytest.mark.parametrize("text", [
    # §4af's break of docs-agent-neutral in the README: a later item's label does not cover it
    "- **When you learn something** say so; the Stop hook also asks once.\n- **Another agent?** The hooks are"
    " Claude Code's.",
    "Before each prompt, the prompt hook runs `okl check` and briefs the agent.",
    "The session-end question asks what was learned.",
    "Run `/seed-from-docs` to import your ADRs.",
    "The stop-hook blocks the first stop.",
    "okl's hooks brief the agent before every prompt.",
    "Your agent's prompt hook runs okl check.",
    "| Task | What happens |\n|---|---|\n| Recording | the Stop hook asks once |",
])
def test_the_label_check_catches_each_unlabelled_mention_it_has_met(text):
    """A Claude Code-only surface named with no label nearby fails the check."""
    assert unlabelled(text)


@pytest.mark.parametrize("text", [
    "In Claude Code the Stop hook asks once.",
    "In Claude Code, two hooks run:\n- the pre-task hook briefs the agent\n- the Stop hook asks what was learned",
    "## In Claude Code\n\nThe Stop hook asks once.",
    "| In Claude Code | Elsewhere |\n|---|---|\n| the Stop hook asks once | the okl_record tool |",
    "`okl init --git-hook` installs a pre-push hook script that runs `okl drift --gate`.",
    "claude-mem's Stop hook records the session too, so their Stop hooks run twice.",
    "It removes the two hook scripts and their entries in `.claude/settings.json`.",
])
def test_the_label_check_lets_labelled_and_other_tools_mentions_through(text):
    """A label in the unit, its table header, its heading or its lead-in clears it; so does another tool's hook."""
    assert unlabelled(text) == []
