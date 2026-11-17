"""What a shell command line means, for the review log (#464): was it the review, which lesson did
it open, which tests did it run.

A transcript holds the commands an agent ran, and also the commands it only wrote about: a grep
for `okl check --change`, a commit message, a heredoc, a `python -c` string. Only a command that
was executed counts, so a line is split into the commands it runs (on `&&`, `||`, `;`, `|` and
newlines, outside quotes and outside heredoc bodies) and each is judged by its command word, after
the assignments, wrappers and shell keywords in front of it. A command a shell runs from a string
(`bash -c '...'`, `$(...)`, backticks) is read again the same way.

The log keeps no command-line text. A test run is stored as a fixed runner name and the paths it
named that exist in the repository, never the text that matched: a command line can carry a
password (`mvn -Ddb.password=...`), a token, or a test name that is somebody's address.

Imports nothing from okl; the import contract in pyproject.toml holds it below the store.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

MAX_TARGETS = 6
_DEPTH = 3          # how many times a command's own command strings are read again

_ASSIGN = re.compile(r"[A-Za-z_]\w*=")
_OKL_VAR = re.compile(r"\$\{?OKL\w*(?:\[[@*]\])?\}?")
_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_]\w*)\2")
_PYTHON = re.compile(r"python[\d.]*")
_SHELL_FLAGS = re.compile(r"-[a-z]{0,3}c")             # -c, -lc, -ec: the next word is the script
_DURATION = re.compile(r"\d+(?:\.\d+)?[smhd]?")
# Words that stand before the command and do not change which one runs.
_PREFIXES = frozenset({"time", "env", "nohup", "exec", "command",
                       "{", "(", "!", "if", "then", "elif", "else", "do", "while", "until"})
_FLAG_WRAPPERS = frozenset({"npx", "bunx", "xargs", "uvx"})          # their own options, then the command
_RUN_WRAPPERS = {"uv": "run", "poetry": "run", "pipenv": "run", "pipx": "run", "pnpm": "exec", "yarn": "exec"}
# The options of a wrapper that take the next word as their value; any other option stands alone, and
# `--opt=value` is one word. Without the table `uv run --with x okl ...` would take `x` for the command.
_UV = frozenset({"--with", "--with-editable", "--with-requirements", "--python", "-p", "--project", "--directory",
                 "--env-file", "--extra", "--group", "--no-group", "--only-group", "--package", "--index",
                 "--default-index", "--index-url", "--find-links", "--from", "--config-file", "--cache-dir"})
_TAKES = {"uv": _UV, "uvx": _UV, "poetry": frozenset({"--directory", "-C", "--project", "--python", "-p"}),
          "pipenv": frozenset({"--python", "--pypi-mirror"}), "pipx": frozenset({"--spec", "--python", "--index-url"}),
          "npx": frozenset({"-p", "--package", "-c", "--call"}), "bunx": frozenset({"-p", "--package"}),
          "xargs": frozenset({"-n", "-I", "-P", "-L", "-d", "-s", "-E", "-a", "-J"})}
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# A command that prints or searches text, so a test runner's name in it is a mention, not a run.
_NOT_RUNNERS = frozenset({"grep", "egrep", "fgrep", "rg", "ack", "cat", "less", "more", "head", "tail",
                          "sed", "awk", "ls", "echo", "printf", "git", "find", "wc", "which", "type",
                          "pip", "pip3", "man", "vim", "nano", "diff", "cp", "mv", "rm", "touch"})
# The runners, by the name of the program. What is stored is the value, never the text that matched.
_SOLO = {"pytest": "pytest", "py.test": "pytest", "tox": "tox", "nox": "nox", "jest": "jest",
         "vitest": "vitest", "mocha": "mocha", "rspec": "rspec", "phpunit": "phpunit", "ctest": "ctest"}
_PACKAGE = {"npm": "npm test", "yarn": "yarn test", "pnpm": "pnpm test", "bun": "bun test"}
_THEN_TEST = {"go": "go test", "dotnet": "dotnet test", "make": "make test", "swift": "swift test",
              "cargo": "cargo test"}
_GOAL_TEST = {"mvn": "mvn test", "mvnw": "mvn test", "gradle": "gradle test", "gradlew": "gradle test"}
# Flags whose next word is a test name, a marker or a pattern: never a path, often a secret.
_VALUE_FLAGS = frozenset({"-k", "-m", "--grep", "-run", "-t", "--test-name-pattern"})
_FAILED = re.compile(r"\b[1-9]\d* (?:failed|failures?|errors?)\b|\bFAILED\b", re.I)
_PASSED = re.compile(r"\b\d+ passed\b|\bOK\b|\bPASS(?:ED)?\b|\ball tests passed\b", re.I)
_SHOW = re.compile(r"\bokl\b\s+show\b((?:(?!\bokl\b)[^;&|\n`])*)", re.I)   # up to the next okl, quote or separator


def _words(text: str) -> list[str]:
    """The shell words of one command, quotes removed; whitespace-split when the quoting is broken."""
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _skip_heredoc_bodies(command: str, i: int, pending: list[tuple[str, bool]]) -> int:
    """Where the command resumes after the heredoc bodies that began on the line just ended."""
    n = len(command)
    for delimiter, indented in pending:
        while i < n:
            end = command.find("\n", i)
            line, i = (command[i:], n) if end < 0 else (command[i:end], end + 1)
            if (line.lstrip("\t") if indented else line) == delimiter:
                break
    return i


def _closing(command: str, start: int) -> int:
    """The index of the `)` that closes the `(` before `start`, skipping quoted text and the bodies of
    heredocs, which are text whatever parentheses and quotes they hold; the end if none."""
    depth, quote, i = 1, "", start
    pending: list[tuple[str, bool]] = []
    while i < len(command):
        c = command[i]
        if quote:
            i += 1 if c == "\\" and quote == '"' else 0
            quote = "" if c == quote else quote
        elif c in "'\"":
            quote = c
        elif c == "\\":
            i += 1
        elif c == "\n":
            i = _skip_heredoc_bodies(command, i + 1, pending) - 1
            pending = []
        elif c == "<" and command.startswith("<<", i) and not command.startswith("<<<", i):
            if m := _HEREDOC.match(command, i):
                pending.append((m.group(3), bool(m.group(1))))
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(command)


class _Splitter:
    """One pass over a command line, cutting it into the commands it runs, and collecting the
    command lines inside `$(...)` and backticks, which run as commands of their own."""

    def __init__(self, command: str) -> None:
        self.command = command
        self.out: list[list[str]] = []
        self.nested: list[str] = []
        self.cur: list[str] = []
        self.quote = ""
        self.i = 0
        self.arith = 0                                  # inside `$((...))`, where `<<` is a shift
        self.pending: list[tuple[str, bool]] = []      # heredocs opened on the line being read

    def flush(self) -> None:
        words = _words("".join(self.cur))
        if words:
            self.out.append(words)
        self.cur.clear()

    def run(self) -> list[list[str]]:
        while self.i < len(self.command):
            self.step(self.command[self.i])
            self.i += 1
        self.flush()
        return self.out

    def step(self, c: str) -> None:
        """Read the character at `self.i`; `self.i` ends on the last one it used."""
        if self.quote != "'" and self.nested_command(c):
            return
        if self.quote:
            self.cur.append(c)
            if c == "\\" and self.quote == '"':
                self.escape()
            elif c == self.quote:
                self.quote = ""
        elif c in "'\"":
            self.quote = c
            self.cur.append(c)
        elif c == "#" and (not self.cur or self.cur[-1] in " \t"):
            # A comment runs to the end of the line, and a `;` or `|` in it cuts nothing.
            end = self.command.find("\n", self.i)
            self.i = (len(self.command) if end < 0 else end) - 1
        elif c == "\\":
            self.cur.append(c)
            self.escape()
        elif c == "\n":
            self.flush()
            self.i = _skip_heredoc_bodies(self.command, self.i + 1, self.pending) - 1
            self.pending = []
        elif self.command.startswith(("&&", "||"), self.i):
            self.flush()
            self.i += 1
        elif c in ";|":
            self.flush()
        else:
            self.other(c)

    def other(self, c: str) -> None:
        """A character that cuts nothing: it may open a heredoc."""
        if c == "<" and not self.arith and self.command.startswith("<<", self.i) \
                and not self.command.startswith("<<<", self.i):
            m = _HEREDOC.match(self.command, self.i)
            if m:
                self.pending.append((m.group(3), bool(m.group(1))))
        self.cur.append(c)

    def nested_command(self, c: str) -> bool:
        """Note a `$(...)` or backtick command, to be read on its own, and where `$((...))` arithmetic
        opens and closes, since `<<` in it is a shift and no heredoc. A complete substitution is taken
        whole into the word being built and the cursor left on its last character, so this pass never
        reads inside it: a heredoc body in `$(cat <<'EOF' ...)` is text, and `okl check --change` in a
        commit message's backticks is not a run. Whether it took one."""
        cmd = self.command
        if c == "$" and cmd.startswith("$((", self.i):
            self.arith += 1
        elif self.arith and c == ")" and cmd.startswith("))", self.i):
            self.arith -= 1
        elif c == "$" and cmd.startswith("$(", self.i):
            end = _closing(cmd, self.i + 2)
            return self.take(cmd[self.i + 2:end], end)
        elif c == "`" and (end := cmd.find("`", self.i + 1)) > 0:
            return self.take(cmd[self.i + 1:end], end)
        return False

    def take(self, inner: str, end: int) -> bool:
        """Keep `inner` to be read as a command line, and the text through `end` in the current word."""
        self.nested.append(inner)
        self.cur.append(self.command[self.i:end + 1])
        self.i = end
        return True

    def escape(self) -> None:
        """Keep the character a backslash protects, whatever it is."""
        if self.i + 1 < len(self.command):
            self.i += 1
            self.cur.append(self.command[self.i])


def segments(command: str) -> list[list[str]]:
    """The commands a shell line runs, each as its words, quotes removed.

    Split on `&&`, `||`, `;`, `|` and newlines that are not inside quotes; the body of a heredoc
    is text, not commands, and is left out. `$(...)` is not entered here; `executed` does.
    """
    return _Splitter(command).run()


def _options(words: list[str], i: int, wrapper: str) -> int:
    """How many words from `i` are the options of `wrapper`, each with its value when it takes one."""
    takes, n = _TAKES.get(wrapper, frozenset()), 0
    while i + n < len(words) and words[i + n].startswith("-") and words[i + n] != "--":
        n += 2 if words[i + n] in takes else 1
    return n


def _timeout_args(words: list[str], i: int) -> int:
    """The words of `timeout`'s own options and its duration, from `i`."""
    n = 0
    while i + n < len(words) and words[i + n].startswith("-"):
        n += 2 if words[i + n] in ("-s", "-k") else 1
    if i + n < len(words) and _DURATION.fullmatch(words[i + n]):
        n += 1
    return n


def _nice_args(words: list[str], i: int) -> int:
    """The words of `nice`'s adjustment, from `i`: `-n 5`, `-5` or `--adjustment=5`."""
    nxt = words[i] if i < len(words) else ""
    if nxt == "-n":
        return 2
    return 1 if re.fullmatch(r"-\d+|--adjustment=.*", nxt) else 0


def _skip(words: list[str], i: int) -> int:
    """How many words from `i` stand before the command word (0 when the command word is at `i`)."""
    w = words[i]
    if _ASSIGN.match(w) or w in _PREFIXES:
        return 1
    if w in _RUN_WRAPPERS and words[i + 1:i + 2] == [_RUN_WRAPPERS[w]]:
        return 2 + _options(words, i + 2, w)
    if w in _FLAG_WRAPPERS:
        return 1 + _options(words, i + 1, w)
    if w == "timeout":
        return 1 + _timeout_args(words, i + 1)
    return 1 + _nice_args(words, i + 1) if w == "nice" else 0


def _command(words: list[str]) -> list[str]:
    """`words` from the command word on: leading `VAR=value` assignments, the wrappers that run
    what follows (`time`, `env`, `timeout 5`, `nice`, `uv run`, `uvx`, `npx`) and the shell keywords and
    brackets that open a command (`if`, `then`, `{`, `(`, `!`) are skipped."""
    words, closed = list(words), False
    while words and words[0].startswith("("):
        head = words[0].lstrip("(")
        words, closed = ([head] if head else []) + words[1:], True
    if closed and words:
        words[-1] = words[-1].rstrip(")")
    i = 0
    while i < len(words) and (step := _skip(words, i)):
        i += step
    return words[i:]


def _shell_script(words: list[str]) -> str | None:
    """The script a shell is given on its command line (`bash -c '...'`), or None."""
    if words[0].rsplit("/", 1)[-1] not in _SHELLS:
        return None
    return next((words[i + 1] for i in range(1, len(words) - 1) if _SHELL_FLAGS.fullmatch(words[i])), None)


def executed(command: str, depth: int = 0) -> list[list[str]]:
    """Every command a command line runs, each from its command word on, with the commands it runs
    from strings: a `bash -c` script, `$(...)` and backticks."""
    splitter = _Splitter(command)
    found: list[list[str]] = []
    for words in splitter.run():
        if not (cmd := _command(words)):
            continue
        found.append(cmd)
        if depth < _DEPTH and (script := _shell_script(cmd)) is not None:
            found += executed(script, depth + 1)
    if depth < _DEPTH:
        for inner in splitter.nested:
            found += executed(inner, depth + 1)
    return found


def _okl_args(words: list[str]) -> list[str] | None:
    """The arguments okl was given, when the command word is okl: `okl`, a path ending in `/okl`,
    `python -m okl`, or the variable a script keeps it in (`$OKL`, `"${OKL[@]}"`); else None."""
    cmd = words[0]
    if cmd == "okl" or cmd.endswith("/okl") or _OKL_VAR.fullmatch(cmd):
        return words[1:]
    if _PYTHON.fullmatch(cmd.rsplit("/", 1)[-1]) and (m := _python_module(words)) is not None and words[m] == "okl":
        return words[m + 1:]
    return None


def _python_module(words: list[str]) -> int | None:
    """Where the module `python -m` runs is in `words`, read among the interpreter's own options only.
    They end at `-c`, at `--` and at the script, the first word that is no option: in `python tool.py
    -m okl` the `-m okl` is the script's argument, and okl does not run."""
    i = 1
    while i < len(words):
        w = words[i]
        if w == "-m":
            return i + 1 if i + 1 < len(words) else None
        if w in ("-c", "--") or not w.startswith("-"):
            return None
        i += 2 if w in ("-W", "-X") else 1
    return None


def _hook_format(args: list[str]) -> bool:
    return "--format=hook" in args or any(a == "--format" and b == "hook" for a, b in zip(args, args[1:], strict=False))


def is_review_command(command: str) -> bool:
    """Whether a Bash command line runs the review: a command that is `okl` with `check` and
    `--change` (or `--change=BASE`), and not the Stop hook's own `--format hook` note. A line that
    only mentions it (a grep, an echo, a commit message, a heredoc, a `python -c` string) does not;
    one that runs it through a wrapper, a keyword, a `bash -c` script or `$(...)` does."""
    for words in executed(command):
        args = _okl_args(words)
        if (args is not None and "check" in args and not _hook_format(args)
                and any(a == "--change" or a.startswith("--change=") for a in args)):
            return True
    return False


def review_pages(command: str) -> list[int]:
    """The page each review command in a Bash line asks for, in order: `--page N` (or `--page=N`),
    and 1 for a review command without it. A word that is not a page number is left out."""
    out = []
    for words in executed(command):
        args = _okl_args(words)
        if args is None or "check" not in args or _hook_format(args) or not any(
                a == "--change" or a.startswith("--change=") for a in args):
            continue
        page = 1
        for i, a in enumerate(args):
            value = args[i + 1] if a == "--page" and i + 1 < len(args) else a.removeprefix("--page=") \
                if a.startswith("--page=") else None
            if value is not None:
                page = int(value) if value.isdigit() else 0
        if page:
            out.append(page)
    return out


def _first_id(args: list[str]) -> str | None:
    """The lesson id in `show`'s arguments: the first word that is not a flag or a flag's value."""
    i = 0
    while i < len(args):
        if args[i] == "--format":
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            return args[i]
    return None


def command_show_ids(command: str) -> list[str]:
    """The lesson ids that `okl show <id>` commands in a Bash command line open."""
    ids = []
    for words in executed(command):
        args = _okl_args(words)
        if args and args[0] == "show" and (i := _first_id(args[1:])):
            ids.append(i)
    return ids


def text_show_ids(text: str) -> list[str]:
    """The ids `okl show <id>` names anywhere in free text, such as a sub-agent's prompt."""
    found = (_first_id([t.strip("\"'`") for t in m.group(1).split()]) for m in _SHOW.finditer(text))
    return [i for i in found if i]


def _runner_at(words: list[str], i: int) -> tuple[str, int] | None:
    """The canonical runner the word at `i` starts, and the index of the word after it, or None."""
    base, nxt, name, used = words[i].rsplit("/", 1)[-1], words[i + 1:i + 3], None, 0
    if base in _SOLO:
        name, used = _SOLO[base], 1
    elif base == "unittest" and i and words[i - 1] == "-m":
        name, used = "unittest", 1
    elif base in _PACKAGE and nxt[:1] == ["test"]:
        name, used = _PACKAGE[base], 2
    elif base in _PACKAGE and nxt[:2] == ["run", "test"]:
        name, used = _PACKAGE[base], 3
    elif base == "cargo" and nxt[:2] == ["nextest", "run"]:
        name, used = "cargo nextest", 3
    elif base in _THEN_TEST and nxt[:1] == ["test"]:
        name, used = _THEN_TEST[base], 2
    elif base in _GOAL_TEST and "test" in words[i + 1:]:
        name, used = _GOAL_TEST[base], words.index("test", i + 1) + 1 - i
    return (name, i + used) if name else None


def _runner(words: list[str]) -> tuple[str, int] | None:
    """The canonical runner a command starts, and the index of the word after it, or None. Anchored:
    the runner is the command word (the wrappers are already gone), or the module after
    `python -m`. A word further along (`python tool.py --runner pytest`) is an argument."""
    if (found := _runner_at(words, 0)) is not None or not _PYTHON.fullmatch(words[0].rsplit("/", 1)[-1]):
        return found
    module = _python_module(words)
    return _runner_at(words, module) if module is not None else None


def _existing(token: str, root: str | None) -> str | None:
    """`token` as a path relative to `root`, when it names something that exists inside it."""
    if not root or not token or token.startswith("-") or len(token) > 400:
        return None
    try:
        base = Path(root).resolve()
        found = (base / token).resolve()    # an absolute token replaces the base; both sides are real paths
        if found == base or base not in found.parents or not found.exists():
            return None
    except (OSError, ValueError):
        return None
    return found.relative_to(base).as_posix()


def parse_test_run(command: str, root: str | None = None) -> tuple[str, list[str]] | None:
    """The test runner a Bash command line starts, and the paths in the repository it named; or None.

    The runner is a fixed name (`pytest`, `npm test`, `mvn test`), not the text that matched, and it
    is the command itself: the command word, the module after `python -m`, or what `npx`, `uv run`,
    `xargs` and the like run. A word further along is an argument, and a command that only searches
    or prints (`grep pytest`) is not a run. A path counts only if it exists under `root` as written,
    so `cd sub && pytest x.py`, whose path is relative to `sub`, keeps none. What follows `-k`, `-m`,
    `--grep`, `-run`, `-t`, `--test-name-pattern` or `--` is never read: those carry names and
    patterns, which can be anything.
    """
    for words in executed(command):
        if words[0] in _NOT_RUNNERS or (found := _runner(words)) is None:
            continue
        name, start = found
        targets: list[str] = []
        skip = False
        for tok in words[start:]:
            if tok == "--":
                break
            if skip:
                skip = False
            elif tok in _VALUE_FLAGS:
                skip = True
            elif (path := _existing(tok.split("::")[0], root)) and path not in targets:
                targets.append(path)
        return name, targets[:MAX_TARGETS]
    return None


def parse_test_outcome(is_error: bool, text: str) -> str:
    """"passed", "failed" or "unknown", from what a test command's result says."""
    if text.lstrip().startswith("<tool_use_error>"):
        return "unknown"       # the tool refused; no test ran
    if is_error or _FAILED.search(text):
        return "failed"
    return "passed" if _PASSED.search(text) else "unknown"


def inside(path: str, root: str | None) -> str | None:
    """`path` relative to the repository at `root`, or None when it is outside it, or when there
    is no repository to measure from. A relative path is taken from the repository. Both are real
    paths (`/tmp` is `/private/tmp` on a Mac), so a link into the repository is inside, and one out of
    it, relative or not, is not."""
    if not root:
        return None
    real = os.path.realpath(Path(root) / path)         # an absolute `path` replaces the root
    base = os.path.realpath(root).rstrip(os.sep)
    return real[len(base) + 1:] if real.startswith(base + os.sep) else None
