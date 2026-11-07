"""`okl intake pr <n>` puts a PR's resolved review findings to the encoding loop (#376).

The fixture is GitHub's pullRequest object as the query returns it, recorded, so none of this
needs the network: four review threads, one unresolved, over three commits.
"""
import json
import shlex

import pytest

from okl import intake

C1, C2, C3 = "1111111aaaaaaa", "2222222bbbbbbb", "3333333ccccccc"
PR = {
    "number": 7, "title": "Fix the price check", "url": "https://github.com/o/r/pull/7", "state": "MERGED",
    "commits": {"nodes": [
        {"commit": {"oid": C1, "committedDate": "2026-11-01T10:00:00Z", "messageHeadline": "first"}},
        {"commit": {"oid": C2, "committedDate": "2026-11-01T12:00:00Z", "messageHeadline": "handle empty carts"}},
        {"commit": {"oid": C3, "committedDate": "2026-11-01T14:00:00Z", "messageHeadline": "price from the catalogue"}},
    ]},
    "reviewThreads": {"nodes": [
        {   # a review bot's finding, its fix named in a reply
            "isResolved": True, "path": "app/orders.py", "line": 41, "originalLine": 40,
            "resolvedBy": {"login": "coderabbitai"},
            "comments": {"nodes": [
                {"author": {"login": "coderabbitai"}, "createdAt": "2026-11-01T11:00:00Z",
                 "url": "https://github.com/o/r/pull/7#discussion_r1",
                 "body": "<!-- internal -->_⚠️ Potential issue_ | **Major** | **Quick win**\n\n"
                         "**Don't trust the client's price for an order.**\n\nThe handler saves `price` as sent."},
                {"author": {"login": "dev"}, "createdAt": "2026-11-01T14:05:00Z", "url": "",
                 "body": f"Fixed in {C3[:7]}: the price comes from the catalogue."}]}},
        {   # a person's comment; no reply names a commit, so the first one to touch the file
            "isResolved": True, "path": "app/cart.py", "line": 10, "originalLine": 10,
            "resolvedBy": {"login": "dev"},
            "comments": {"nodes": [
                {"author": {"login": "reviewer"}, "createdAt": "2026-11-01T11:30:00Z",
                 "url": "https://github.com/o/r/pull/7#discussion_r2", "body": "An empty cart crashes here."}]}},
        {   # still open: not a lesson yet
            "isResolved": False, "path": "app/orders.py", "line": 50, "originalLine": 50, "resolvedBy": None,
            "comments": {"nodes": [
                {"author": {"login": "reviewer"}, "createdAt": "2026-11-01T11:40:00Z",
                 "url": "https://github.com/o/r/pull/7#discussion_r3", "body": "Is this the right status code?"}]}},
        {   # resolved, but nothing after it touched the file and no reply names a commit
            "isResolved": True, "path": "README.md", "line": None, "originalLine": 3,
            "resolvedBy": {"login": "dev"},
            "comments": {"nodes": [
                {"author": {"login": "reviewer"}, "createdAt": "2026-11-01T15:00:00Z",
                 "url": "https://github.com/o/r/pull/7#discussion_r4", "body": "Typo in the heading."}]}},
    ]},
}
FILES = {C1: {"app/orders.py"}, C2: {"app/cart.py"}, C3: {"app/orders.py"}}


def _files_of(asked: list[str] | None = None):
    def files_of(sha: str) -> set[str]:
        if asked is not None:
            asked.append(sha)
        return FILES[sha]
    return files_of


def test_resolved_threads_are_listed_with_the_commit_that_resolved_them():
    """Each resolved thread, with its resolving commit: the one a reply names, or else the
    first commit after the finding to touch its file, marked as a guess. The unresolved one is
    left out, and the files of a commit are read only for a thread no reply settles."""
    asked: list[str] = []
    found = intake.findings(PR, _files_of(asked))

    assert [f.url[-2:] for f in found] == ["r1", "r2", "r4"]           # r3 is unresolved
    named, guessed, none = found
    assert (named.commit, named.found_how) == (C3[:7], "named in a reply")
    assert named.summary == "Don't trust the client's price for an order"
    assert (named.where(), named.author, named.resolved_by) == ("app/orders.py:41", "coderabbitai", "coderabbitai")
    assert guessed.commit == C2[:7] and guessed.found_how.startswith("a guess")
    assert none.commit is None and none.where() == "README.md:3"
    assert asked == [C2]          # only r2 needed a commit's files: r1's reply named its fix


def test_a_review_bots_title_is_the_summary_not_its_badges():
    """CodeRabbit opens with badges (**Major**, **Quick win**) and HTML comments; the finding
    is its first bold sentence. A plain comment's first line stands as it is."""
    assert intake.summary_of("<!-- x -->**Minor** | **Quick win**\n\n**Reject unknown function qualifiers.**") \
        == "Reject unknown function qualifiers"
    assert intake.summary_of("An empty cart crashes here.\nMore detail.") == "An empty cart crashes here."
    assert intake.summary_of("") == "(no text)"


def test_the_printed_commands_are_ones_the_cli_accepts():
    """Every `okl record` and `okl verify` the worksheet prints parses with okl's own parser,
    the comment's quote characters included, so it can be filled in and run as it stands."""
    from okl.cli.parser import build_parser
    text = intake.render(intake.findings(PR, _files_of()), PR)
    commands = [line.strip() for line in text.splitlines() if line.strip().startswith(("okl record", "okl verify"))]
    assert len(commands) == 6, text
    parser = build_parser()
    for cmd in commands:
        argv = shlex.split(cmd)
        args = parser.parse_args(argv[1:])
        if argv[1] == "record":
            assert args.found_by.startswith("review on PR #7")
    record = parser.parse_args(shlex.split(commands[0])[1:])
    assert record.files == "app/orders.py" and record.triggers == ["Don't trust the client's price for an order"]
    assert "fixed in " + C3[:7] in record.found_by


def test_the_cli_lists_them_as_text_or_json_and_fails_plainly_without_gh(monkeypatch, capsys, tmp_path):
    """The command prints the worksheet, or JSON with each finding's commands for an agent; it
    writes nothing; and when gh cannot read the PR it says why and exits 2."""
    from okl.cli import main
    monkeypatch.chdir(tmp_path)                                         # no store: no briefing lookup
    monkeypatch.setattr(intake, "fetch", lambda n, repo=None: (PR, _files_of()))

    assert main(["intake", "pr", "7"]) == 0
    out = capsys.readouterr().out
    assert "3 resolved review thread(s)" in out and "Encode it?" in out and "r3" not in out

    assert main(["intake", "pr", "7", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [f["commit"] for f in data["findings"]] == [C3[:7], C2[:7], None]
    assert all(f["record"].startswith("okl record") for f in data["findings"])

    def no_gh(n, repo=None):
        raise intake.IntakeError("gh is not installed")
    monkeypatch.setattr(intake, "fetch", no_gh)
    assert main(["intake", "pr", "7"]) == 2
    assert "gh is not installed" in capsys.readouterr().err
    assert not (tmp_path / ".okl").exists()


def test_an_open_pr_with_nothing_resolved_says_so():
    """A PR whose only thread is still open has nothing to put to the loop, and says so."""
    pr = {**PR, "reviewThreads": {"nodes": [PR["reviewThreads"]["nodes"][2]]}}
    assert "Nothing to ask" in intake.render(intake.findings(pr, _files_of()), pr)


@pytest.mark.parametrize("missing", ["data", "repository", "pullRequest"])
def test_a_pr_gh_cannot_find_is_an_error_not_an_empty_list(monkeypatch, missing):
    """A wrong number or repo comes back from GitHub as a null PR, not an HTTP error; that is
    'no such PR', never 'nothing resolved'."""
    body = {"data": {"repository": {"pullRequest": None}}}
    if missing == "repository":
        body = {"data": {"repository": None}}
    elif missing == "data":
        body = {}
    monkeypatch.setattr(intake, "_gh", lambda *a: json.dumps(body))
    with pytest.raises(intake.IntakeError, match="no PR #9"):
        intake.fetch(9, "o/r")


def test_every_page_of_threads_and_commits_is_read_and_a_long_thread_is_named(monkeypatch):
    """One page held 100 threads and 250 commits, and a PR with more was shown as if whole
    (CodeRabbit on #388). Both connections are followed page by page; a thread with more
    comments than a page holds is named in a warning."""
    t1, t2 = PR["reviewThreads"]["nodes"][0], PR["reviewThreads"]["nodes"][1]
    long_thread = {**t2, "comments": {**t2["comments"], "pageInfo": {"hasNextPage": True}}}
    pages = {
        ("reviewThreads", None): {"hasNextPage": True, "endCursor": "T1", "nodes": [t1]},
        ("reviewThreads", "T1"): {"hasNextPage": False, "endCursor": None, "nodes": [long_thread]},
        ("commits", None): {"hasNextPage": True, "endCursor": "K1", "nodes": PR["commits"]["nodes"][:2]},
        ("commits", "K1"): {"hasNextPage": False, "endCursor": None, "nodes": PR["commits"]["nodes"][2:]},
    }

    def gh(*args):
        if args[:1] == ("api",) and args[1].startswith("repos/"):
            return json.dumps({"files": [{"filename": f} for f in FILES[args[1].rsplit("/", 1)[1]]]})
        query = next(a for a in args if a.startswith("query="))
        key = "reviewThreads" if "reviewThreads" in query else "commits"
        after = next((a.split("=", 1)[1] for a in args if a.startswith("after=")), None)
        page = pages[(key, after)]
        conn = {"pageInfo": {"hasNextPage": page["hasNextPage"], "endCursor": page["endCursor"]},
                "nodes": page["nodes"]}
        return json.dumps({"data": {"repository": {"pullRequest": {"number": 7, "title": "t", key: conn}}}})
    monkeypatch.setattr(intake, "_gh", gh)

    pr, files_of = intake.fetch(7, "o/r")
    found = intake.findings(pr, files_of)

    assert [f.url[-2:] for f in found] == ["r1", "r2"]                  # the second page's thread too
    assert [f.commit for f in found] == [C3[:7], C2[:7]]                 # C3 is on the second commit page
    assert pr["warnings"] == ["a thread on app/cart.py has more than 100 comments; only the first 100 were read"]
    assert "! a thread on app/cart.py" in intake.render(found, pr)


def test_findings_come_in_the_order_they_were_made():
    """By when each was made, then by comment number: sorting the URLs put discussion_r10
    before discussion_r9 (CodeRabbit on #388)."""
    def thread(n: int, at: str) -> dict:
        return {"isResolved": True, "path": "a.py", "line": n, "resolvedBy": None,
                "comments": {"nodes": [{"author": {"login": "x"}, "createdAt": at, "body": f"finding {n}",
                                        "url": f"https://github.com/o/r/pull/7#discussion_r{n}"}]}}
    pr = {"number": 7, "commits": {"nodes": []}, "reviewThreads": {"nodes": [
        thread(10, "2026-11-01T12:00:00Z"), thread(9, "2026-11-01T11:00:00Z"),
        thread(12, "2026-11-01T13:00:00Z"), thread(11, "2026-11-01T13:00:00Z")]}}
    assert [f.line for f in intake.findings(pr, lambda sha: set())] == [9, 10, 11, 12]


def test_a_briefing_lookup_that_fails_is_said_not_read_as_nothing_covered(tmp_path, monkeypatch, capsys):
    """With a store that cannot be read, the related lessons are skipped, and saying so keeps a
    finding from reading as one no lesson covers (CodeRabbit on #388)."""
    from okl.cli import main
    from okl.client import Client, OKLUnreachableError
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    monkeypatch.setattr(intake, "fetch", lambda n, repo=None: (PR, _files_of()))
    def unreachable(self, *a, **k):
        raise OKLUnreachableError("service unreachable: connection refused")
    monkeypatch.setattr(Client, "check", unreachable)

    assert main(["intake", "pr", "7"]) == 0
    out = capsys.readouterr()
    assert "briefing lookup skipped" in out.err and "connection refused" in out.err
    assert "a briefing on it already shows" not in out.out
