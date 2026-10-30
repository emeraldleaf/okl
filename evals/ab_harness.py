#!/usr/bin/env python3
"""Held-fixed A/B: does the okl briefing reduce defect reproduction?

Two arms per task, same generator, ONLY the briefing differs:
  baseline : the task alone
  briefed  : `okl check --task <task>` briefing + the task

Outcome per (task, arm): did the generated code reproduce the task's known defect
class, judged BLIND (the judge sees task + code + defect signal, never the arm) by a
model that must differ from the generator (refused otherwise).

Eval-integrity rules enforced (they are stored lessons; this harness obeys them):
  - judge != generator, refused at startup
  - the report LEADS with its own failure count; RESULTS NOT USABLE above threshold
  - a sample with no implementation to judge is unevaluable: a failure, never "clean"
  - generator/judge run in a clean temp cwd so repo hooks can't inject themselves

Usage:
  python3 evals/ab_harness.py [--limit N] [--dry-run] [--timeout SECS]
Env:
  GENERATOR_CMD  (default: "claude -p --model sonnet")
  JUDGE_CMD      (default: "claude -p --model haiku")
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Overridable so the instrument guard can be tested against a CONSTRUCTED receipt history.
# Without this the guard is only testable against whatever this repo happens to hold, and
# the modal-vs-latest distinction it exists to make is exactly the one real receipts stop
# discriminating as soon as the series is restored — which is how its first regression test
# passed against the broken implementation.
RESULTS_DIR = Path(os.environ.get("AB_RESULTS_DIR") or (REPO / "evals" / "results"))
FAILURE_RATE_UNUSABLE = 0.20

GENERATOR_CMD = os.environ.get("GENERATOR_CMD", "claude -p --model sonnet")
JUDGE_CMD = os.environ.get("JUDGE_CMD", "claude -p --model haiku")
# The briefed arm's interest filter. Default "" (unfiltered) is what every run in the
# report used and why 4f could not measure applies_to: an empty interest set short-circuits
# the filter entirely. Parameterised so 4h can vary the one retrieval knob this harness is
# actually able to test. Recorded in the receipt, because a run whose retrieval config is
# not on its own face cannot be compared to one whose is.
BRIEF_INTERESTS = os.environ.get("OKL_BRIEF_INTERESTS", "")
# Tools the generator may use, as `claude -p --allowedTools` takes them (REPORT §4r:
# "Bash(okl show:*)"). Empty, the default, is the one-shot generator every earlier section
# ran. When set, an `okl` shim on the generator's PATH logs each invocation, so the receipt
# says which lessons each sample fetched. Stamped into the receipt: it is the instrument.
GENERATOR_TOOLS = os.environ.get("GENERATOR_TOOLS", "")
ARMS = ("baseline", "briefed", "indexed", "nearmiss", "full", "line", "titles", "when", "when-tool")
# The tier arms (REPORT §4aa): the same briefing with the task's governing lesson shown in full,
# or named only as the first one-line entry of the second tier; nothing else differs. The line
# arms differ only in what each second-tier line says (REPORT §4ab): the start of the fix
# ("line"), the title alone ("titles"), or when the lesson applies ("when", "when-tool"). The
# last offers the fetch as an MCP tool instead of `okl show` (FETCH_TOOL).
TIER_ARMS = ("full", "line", "titles", "when", "when-tool")
LINE_STYLES = {"line": "line", "titles": "titles", "when": "when", "when-tool": "when"}
# The when-tool arm's only fetch path: okl_get from evals/fetch_tool.py, over MCP.
FETCH_TOOL = "mcp__okl__okl_get"
FETCH_SERVER = REPO / "evals" / "fetch_tool.py"

GEN_PROMPT = """You are implementing one task for an existing codebase. Output ONLY the code (or YAML/script), no explanation.

{briefing}TASK: {task}"""

BRIEFING_HEADER = "Read this briefing from your org's knowledge layer before implementing:\n\n{briefing}\n\n---\n\n"

JUDGE_PROMPT = """You are auditing a code submission for ONE specific defect class. Be strict and literal: judge only this defect, not general quality.

The developer was asked: {task}

Defect class to check for: {signal}

Submitted code:
```
{output}
```

"implemented" is false when the submission contains no implementation of the task to judge: only a plan, a description of what the code would do, a question, or a refusal. Then "defect_reproduced" is false too.

Respond with ONLY this JSON, nothing else:
{{"implemented": true or false, "defect_reproduced": true or false, "reason": "<one sentence citing the evidence>"}}"""


def call(cmd: str, prompt: str, timeout: int, workdir: str, env: dict[str, str] | None = None) -> str:
    """Send `prompt` on stdin to the model command `cmd`, run from `workdir`; return stdout.

    `cmd` is split like a shell line but no shell runs it; `timeout` is in seconds; `env`
    replaces the environment when given (the generator's PATH shim and store, §4r).
    Raises RuntimeError on a non-zero exit, so the caller counts the run as a failure.
    """
    r = subprocess.run(shlex.split(cmd), input=prompt, capture_output=True, text=True,
                       timeout=timeout, cwd=workdir, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"exit {r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout


def get_briefing(task: str, timeout: int, *, index: bool = False, near_misses: bool = False) -> str:
    """Return the briefing `okl check` gives the briefed arm for `task`; with the index of every
    other lesson in scope when `index` (the indexed arm, §4r), or with the near-miss list when
    `near_misses` (§4s); raises RuntimeError if it fails."""
    # Fails CLOSED: a briefed arm without a briefing would silently become a second
    # baseline arm and corrupt the comparison.
    # --interests from OKL_BRIEF_INTERESTS, default "" (unfiltered); evals/preflight.py reads
    # the same variable, so the gate checks the briefing this arm receives. The host repo's
    # interests are not the experiment's — react_fetch's rule is tagged `react`, which okl
    # does not declare, so inheriting them made that task measure its rule's ABSENCE; the
    # receipts from ab-20260903-1323 to ab-20261011-2254 ran with okl's seven set and stamp
    # the value. The harness states its retrieval config instead of borrowing one.
    # OKL_BRIEFING_LOG=0: an experiment's briefings are not exposure. Logging them would
    # count every bait task's rules as "shown" in the store's exposure report (#129). It
    # changes nothing in the briefing itself.
    r = subprocess.run([sys.executable, "-m", "okl", "check", "--task", task,
                        "--format", "agent", "--interests", BRIEF_INTERESTS,
                        *(["--index"] if index else []), *(["--near-misses"] if near_misses else [])],
                       capture_output=True, text=True, timeout=timeout, cwd=REPO,
                       env={**os.environ, "OKL_BRIEFING_LOG": "0"})
    if r.returncode != 0:
        raise RuntimeError(f"okl check failed: {r.stderr.strip()[:200]}")
    return r.stdout


def when_text(lesson: dict, cap: int) -> str:
    """What a "when" line says a lesson applies to (REPORT §4ab): its symptom, else its first
    trigger, cut at a word to `cap` characters as the fix's sentence is; "" when it has neither."""
    triggers = [x.strip() for x in (lesson.get("triggers") or "").splitlines() if x.strip()]
    text = (lesson.get("symptom") or "").strip() or (triggers[0] if triggers else "")
    if len(text) > cap:
        text = text[:cap].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def restyled(also: list[dict], style: str, lessons: dict[str, dict], cap: int) -> list[dict]:
    """The second tier's entries as a line arm words them (REPORT §4ab): unchanged ("line"), the
    title alone ("titles"), or the title and when the lesson applies ("when"). An AVOID entry
    stays a warning in every arm."""
    if style == "line":
        return also
    out = []
    for e in also:
        when = "" if style == "titles" or e.get("avoid") else when_text(lessons[e["id"]], cap)
        out.append(e if e.get("avoid") else {**e, "fix": f"when you see: {when}" if when else ""})
    return out


def tier_briefings(task: str, governing: str, timeout: int) -> dict[str, str]:
    """The tier arms' briefings for `task`, by arm (REPORT §4aa, §4ab): one `okl check` result,
    rendered by okl's own renderer with the lesson `governing` shown in full ("full") or as the
    first one-line entry under "Also matched", worded as each line arm words it. The routed
    actions are rebuilt by okl's own router each time, and the second tier keeps its length.
    Fails closed."""
    sys.path.insert(0, str(REPO / "src"))
    import copy
    import dataclasses

    from okl import core
    from okl.store import Node
    env = {**os.environ, "OKL_BRIEFING_LOG": "0"}
    r = subprocess.run([sys.executable, "-m", "okl", "check", "--task", task, "--format", "json",
                        "--interests", BRIEF_INTERESTS, "--decision", "tiered"],
                       capture_output=True, text=True, timeout=timeout, cwd=REPO, env=env)
    s = subprocess.run([sys.executable, "-m", "okl", "show", governing, "--format", "json"],
                       capture_output=True, text=True, timeout=timeout, cwd=REPO, env=env)
    if r.returncode != 0 or s.returncode != 0:
        raise RuntimeError(f"okl failed: {(r.stderr or s.stderr).strip()[:200]}")
    result, shown = json.loads(r.stdout), json.loads(s.stdout)
    node = Node(**{f.name: shown[f.name] for f in dataclasses.fields(Node) if f.name in shown})
    limit = max(len(result.get("also_matched") or []), 1)
    # Each second-tier lesson whole, for the "when" lines' symptoms.
    lessons = {governing: shown}
    for e in result.get("also_matched") or []:
        if e["id"] not in lessons:
            o = subprocess.run([sys.executable, "-m", "okl", "show", e["id"], "--format", "json"],
                               capture_output=True, text=True, timeout=timeout, cwd=REPO, env=env)
            if o.returncode != 0:
                raise RuntimeError(f"okl show {e['id']} failed: {o.stderr.strip()[:200]}")
            lessons[e["id"]] = json.loads(o.stdout)

    def placed(in_full: bool, style: str = "line") -> str:
        out = copy.deepcopy(result)
        # Every bucket okl has, from okl itself: a copied list would skip a new one (review on #303).
        keys = core._bucket_by_type([])
        if in_full and any(x.get("id") == governing for k in keys for x in out.get(k) or []):
            # Already in full: the natural briefing as okl rendered it. Moving the lesson to the
            # end of its section reordered the routed actions too (review on #303).
            return core.render_check_for_agent(out)
        buckets = {k: [x for x in out.get(k) or [] if x.get("id") != governing] for k in keys}
        also = [e for e in out.get("also_matched") or [] if e.get("id") != governing]
        if in_full:
            for k, recs in core._bucket_by_type([node]).items():
                buckets[k].extend(recs)
        else:
            also = restyled([core._also_entry(node), *also][:limit], style, lessons, core.ALSO_FIX_CHARS)
        out.update(buckets, also_matched=also, next_actions=core._route_actions(buckets),
                   match_count=sum(len(v) for k, v in buckets.items() if k != "stale_warnings"))
        return core.render_check_for_agent(out)
    return {"full": placed(True), **{arm: placed(False, style) for arm, style in LINE_STYLES.items()}}


def unchanged_by_style(briefings: dict[str, str], arms: list[str], governing: str) -> list[str]:
    """The line arms in `arms` that do not carry their treatment (REPORT §4ab), so each fails
    closed for that task: an experiment cannot measure a change it never made. titles must
    differ from the line arm. when and when-tool (whose treatment is the when wording and the
    tool together) must say when the governing lesson applies on its own line: a lesson with
    no symptom or trigger lost its fix and gained no "when you see", and its briefing still
    differed from the line arm's (reviews on #305)."""
    said = re.compile(rf"^- \[{re.escape(governing)}\].*— when you see: \S", re.MULTILINE)
    return [a for a in ("titles", "when", "when-tool") if a in arms
            and (briefings[a] == briefings["line"] if a == "titles" else not said.search(briefings[a]))]


def tier_headers_for(t: dict, arms: list[str], timeout: int) -> tuple[dict[str, str], str]:
    """Task `t`'s headers for the tier arms in `arms`, and why any of them is missing. An arm
    that does not carry its treatment fails closed on its own: one shared raise also failed
    the tier arms that did, and the briefed arms built after it (review on #305)."""
    if not set(arms) & set(TIER_ARMS):
        return {}, ""
    try:
        tiers = tier_briefings(t["task"], t["defect_node"], timeout)
    except Exception as e:  # noqa: BLE001 — fail closed: no briefing, no tier arm
        return {}, str(e)[:300]
    same = unchanged_by_style(tiers, arms, t["defect_node"])
    err = (f"the {', '.join(same)} briefing does not carry its treatment "
           "(the restyle changed nothing, or the lesson has no symptom or trigger)") if same else ""
    return {a: BRIEFING_HEADER.format(briefing=b) for a, b in tiers.items() if a in arms and a not in same}, err


def parse_judge(raw: str) -> dict:
    """Pull the verdict JSON out of the judge's reply.

    Raises ValueError without a boolean `implemented` and a boolean `defect_reproduced`: a
    verdict that does not say whether there was code to judge is a judge failure, counted
    as one, never read as clean.
    """
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in judge output: {raw.strip()[:120]}")
    d = json.loads(m.group(0))
    for key in ("implemented", "defect_reproduced"):
        if not isinstance(d.get(key), bool):
            raise ValueError(f"judge JSON missing boolean {key}: {d}")
    return d


# How much of a submission the judge reads. It read only the first 8,000 characters: a
# 15,585-character rate limiter was cut off mid-line, the judge said there was no code,
# and §4l lost that sample (#182). 40,000 characters is about 10,000 tokens, far inside the
# judge's context; a longer submission is unevaluable rather than judged on a cut copy.
JUDGE_MAX_CHARS = 40_000
# The window every receipt before #182 was judged with; those receipts do not record one.
HISTORICAL_JUDGE_MAX_CHARS = 8_000


class Unevaluable(Exception):  # noqa: N818 - a verdict, not an error in the harness
    """A sample the judge cannot rule on: no implementation (a plan, a question, a refusal),
    or a submission longer than the judge's window (marked `truncated`).

    It shows nothing either way, so it is a failure: kept in `failures`, out of both arms'
    denominators, and counted toward the usability bar. Scored clean, it flattered
    whichever arm it landed in: §4j's briefed idor_endpoint sample 1 was a plan the judge
    said had no code, and the harness counted it as a clean briefed run (#164).
    """


def generator_env(workdir: str, log: str) -> dict[str, str] | None:
    """The generator's environment when it may run tools (§4r): an `okl` shim first on PATH
    that appends each invocation to `log` and runs the real okl against the store this harness
    reads; None (inherit) when no tools are allowed."""
    if not GENERATOR_TOOLS:
        return None
    return {**os.environ, "PATH": f"{Path(workdir) / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
            "OKL_SHIM_LOG": log, "OKL_BRIEFING_LOG": "0", "OKL_DATABASE_URL": store_url()}


def store_url() -> str:
    """The store the generator's fetches read: the harness's own."""
    return os.environ.get("OKL_DATABASE_URL") or f"sqlite:///{REPO / '.okl' / 'okl.db'}"


def fetch_tool_description() -> str:
    """The fetch tool's description, read from evals/fetch_tool.py, for the receipt's face."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fetch_tool", FETCH_SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {FETCH_SERVER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DESCRIPTION


def write_fetch_tool_config(log: str) -> str:
    """The when-tool arm's MCP config for one sample (REPORT §4ab), beside its log: the fetch
    tool over stdio, logging to `log`, against the harness's store and okl code. Only the
    variables the tool needs are written, never the environment, which can hold secrets."""
    path = Path(log).with_suffix(".mcp.json")
    path.write_text(json.dumps({"mcpServers": {"okl": {
        "command": sys.executable, "args": [str(FETCH_SERVER)],
        "env": {"OKL_SHIM_LOG": log, "OKL_BRIEFING_LOG": "0", "OKL_DATABASE_URL": store_url(),
                "PYTHONPATH": str(REPO / "src")}}}}))
    return str(path)


def write_shim(workdir: str) -> None:
    """Put the `okl` shim in `workdir`/bin: runs the real okl, then logs the exit status and
    the arguments, so a fetch counts only when `okl show` succeeded (review on #269)."""
    bin_dir = Path(workdir) / "bin"
    bin_dir.mkdir(exist_ok=True)
    shim = bin_dir / "okl"
    shim.write_text('#!/bin/sh\n'
                    f'{shlex.quote(sys.executable)} -m okl "$@"\n'
                    'rc=$?\n'
                    'printf \'%s %s\\n\' "$rc" "$*" >> "$OKL_SHIM_LOG"\n'
                    'exit $rc\n')
    shim.chmod(0o755)


def fetched_ids(log: str) -> list[str]:
    """The lesson ids an `okl show` fetched AND returned (exit 0), in order, from the shim's
    log; [] when none. An attempt that failed is not a lesson read."""
    try:
        lines = Path(log).read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        parts = shlex.split(line) if line.strip() else []
        if len(parts) >= 3 and parts[0] == "0" and parts[1] == "show":
            out.append(parts[2])
    return out


def parse_arms(spec: str) -> list[str]:
    """`--arms` as a list, refused by argparse when it names an arm that does not exist."""
    arms = [a.strip() for a in spec.split(",") if a.strip()]
    if not arms or any(a not in ARMS for a in arms) or len(set(arms)) != len(arms):
        # A repeated arm would run and count twice (review on #269).
        raise argparse.ArgumentTypeError(f"--arms must name each of {','.join(ARMS)} at most once, not {spec!r}")
    pointed = [a for a in ("titles", "when", "when-tool") if a in arms]
    if pointed and not GENERATOR_TOOLS:
        # These arms withhold the fix and point at a fetch (§4ab), and only a logged fetch counts.
        # One-shot, nothing is logged and an MCP server from the user's own settings could fetch
        # unseen (review on #305); refusing them keeps the one-shot command every earlier
        # section ran unchanged.
        raise argparse.ArgumentTypeError(f"the {', '.join(pointed)} arm(s) need GENERATOR_TOOLS set "
                                         "(e.g. 'Bash(okl show:*)'): they point at a fetch, and only "
                                         "a logged fetch counts")
    return arms


def generator_cmd(arm: str = "", mcp_config: str = "") -> str:
    """The generator command, with the allowed tools when any (claude -p's flag; §4r). With
    tools on, only the MCP servers an arm names load (--strict-mcp-config), so a lesson can be
    fetched only by the path the arm offers (REPORT §4ab): `okl show` through the shim, or, in
    the when-tool arm, only the fetch tool whose config is `mcp_config`. Tools on also run
    --restricted, which reads no settings file: --allowedTools only adds approvals, so a rule
    in the user's own settings (`Bash(uv run *)`) could read the store by another command the
    shim never logs. Restricted, the Bash arms keep Bash alone; the when-tool arm keeps no
    built-in tool (`--tools ""`), since the shim is on its PATH too (review on #305)."""
    if not GENERATOR_TOOLS:
        return GENERATOR_CMD
    if arm == "when-tool":
        return (f"{GENERATOR_CMD} --restricted --strict-mcp-config --mcp-config {shlex.quote(mcp_config)} "
                f'--tools "" --allowedTools {FETCH_TOOL}')
    return (f"{GENERATOR_CMD} --restricted --tools Bash --strict-mcp-config "
            f"--allowedTools {shlex.quote(GENERATOR_TOOLS)}")


def startup_refusal(models: dict, arms: list[str], workdir: str, governing: str,
                    timeout: int) -> tuple[int, str] | None:
    """Why the run must not start, with its exit code, once the models are known; None to run.
    3: the judge resolves to the generator's model. 7: the okl that would run is not this
    checkout's (code_outside_checkout); set PYTHONPATH to its src. 6: a fetch path the arms offer
    did not work when the generator was asked to use it (probe_fetch)."""
    if judge_is_generator(models):
        return 3, (f"the judge resolves to the generator's model ({', '.join(models['judge'])}) "
                   "— it must not grade its own homework (qz_judge_self).")
    elsewhere = code_outside_checkout()
    if elsewhere:
        return 7, f"{elsewhere}; set PYTHONPATH={REPO / 'src'} so the run measures this checkout."
    # The when-tool arm is offered okl_get alone, so okl show is probed only for another arm
    # that can use it (review on #305).
    paths = {"okl show": False} if GENERATOR_TOOLS and any(a != "when-tool" for a in arms) else {}
    paths.update({"okl_get": True} if "when-tool" in arms else {})
    for name, tool in paths.items():
        why = probe_fetch(workdir, governing, timeout, tool=tool)
        if why:
            return 6, f"the generator could not fetch through {name} ({why})."
        print(f"fetch path: the generator fetched through {name} and the fetch was logged")
    return None


def probe_fetch(workdir: str, governing: str, timeout: int, *, tool: bool) -> str:
    """"" when the generator, run as the arms run it, can fetch `governing` and the fetch is
    logged; otherwise why not. `tool` probes the when-tool arm's okl_get, else `okl show` through
    the shim. One generation per path, spent before the run, so a path that never opened cannot
    read as an agent that never fetched (REPORT §4ab)."""
    log = str(Path(workdir) / f"probe-{'tool' if tool else 'shim'}.log")
    ask = f"Call the okl_get tool with id {governing!r}" if tool else f"Run `okl show {governing}`"
    env = generator_env(workdir, log)
    try:
        call(generator_cmd("when-tool" if tool else "", write_fetch_tool_config(log) if tool else ""),
             f"{ask}, then reply with the lesson's title only.", timeout, workdir,
             **({"env": env} if env else {}))
    except Exception as e:  # noqa: BLE001 - any failure is the answer
        return f"the probe call failed: {str(e)[:200]}"
    return "" if governing in fetched_ids(log) else "the probe asked for a fetch and none was logged"


def run_one(t: dict, arm: str, s: int, *, briefed_header: str | None, brief_err: str,
            timeout: int, workdir: str, indexed_header: str | None = None,
            nearmiss_header: str | None = None, tier_headers: dict[str, str] | None = None,
            ) -> tuple[dict, bool]:
    """Generate and judge one (task, arm, sample). Returns the record and whether it is a result.

    False means a failure: anything that raised, including an Unevaluable sample, which is
    marked `unevaluable` so the report can say how many failures were no implementation,
    and `truncated` as well when the cause was length. With tools allowed, the record also
    carries the lesson ids the generator fetched and whether the governing one was among them.
    """
    rec = {"task": t["id"], "arm": arm, "sample": s, "defect_node": t["defect_node"]}
    t0 = time.time()
    log = str(Path(workdir) / f"shim-{t['id'].replace('/', '_')}-{arm}-{s}.log")
    try:
        header = {"baseline": "", "briefed": briefed_header, "indexed": indexed_header,
                  "nearmiss": nearmiss_header, **{a: (tier_headers or {}).get(a) for a in TIER_ARMS}}[arm]
        if header is None:
            raise RuntimeError(f"briefing unavailable (fail closed): {brief_err}")
        env = generator_env(workdir, log)
        mcp_config = write_fetch_tool_config(log) if GENERATOR_TOOLS and arm == "when-tool" else ""
        # The environment is passed only when tools are on, so the one-shot path is byte for
        # byte the call every section through §4q made (and its tests' fakes still fit).
        code = call(generator_cmd(arm, mcp_config), GEN_PROMPT.format(briefing=header, task=t["task"]),
                    timeout, workdir, **({"env": env} if env else {}))
        if GENERATOR_TOOLS:
            rec["fetched"] = fetched_ids(log)
            rec["fetched_governing"] = t["defect_node"] in rec["fetched"]
        # The receipt keeps no code, so this is what lets a reader audit a verdict: a "no
        # implementation" on thousands of characters is the judge's mistake, not the model's.
        rec["code_chars"] = len(code)
        if len(code) > JUDGE_MAX_CHARS:
            rec["truncated"] = True
            raise Unevaluable(f"{len(code)} characters, longer than the judge's "
                              f"{JUDGE_MAX_CHARS}-character window")
        verdict = parse_judge(call(
            JUDGE_CMD,
            JUDGE_PROMPT.format(task=t["task"], signal=t["signal"], output=code),
            timeout, workdir))
        if not verdict["implemented"]:
            rec["excerpt"] = code[:300]
            raise Unevaluable(f"no implementation to judge: {verdict['reason']}")
        rec.update(reproduced=verdict["defect_reproduced"], reason=verdict["reason"],
                   seconds=round(time.time() - t0, 1))
        return rec, True
    except Exception as e:  # noqa: BLE001 — every failure must be COUNTED, not raised past
        rec.update(error=str(e)[:300], seconds=round(time.time() - t0, 1))
        if isinstance(e, Unevaluable):
            rec["unevaluable"] = True
        return rec, False


def failure_label(rec: dict) -> str:
    """How a failed sample reads in the run log.

    An over-window submission holds code, so it must not read NO CODE (review of #198).
    """
    if rec.get("truncated"):
        return "TOO LONG"
    return "NO CODE" if rec.get("unevaluable") else "FAILED"


def failure_causes(failures: list[dict]) -> str:
    """The report's breakdown of failures that were verdicts rather than crashes."""
    too_long = sum(1 for f in failures if f.get("truncated"))
    no_code = sum(1 for f in failures if f.get("unevaluable") and not f.get("truncated"))
    return ((f", {no_code} of them no implementation to judge" if no_code else "")
            + (f", {too_long} longer than the judge's window" if too_long else ""))


def instrument_drift(prior: list[dict], current: dict) -> dict:
    """Each part of the instrument this run changes, against the series it is quoted with.

    The commands are compared with their mode across every receipt. The judge's window is
    compared with its mode across the receipts that record one, or with the 8,000
    characters every earlier receipt used when none do. Counting the unrecorded receipts as
    8,000 would flag every run of the 40,000-character series for as long as the older
    receipts outnumber it: the guard telling you to discard the runs that fixed the problem
    (review of #198).
    """
    modal: dict = {}
    for key in ("generator", "judge"):
        seen = Counter(r[key].strip() for r in prior if r.get(key))
        if seen and seen.most_common(1)[0][0] != current[key]:
            was, n = seen.most_common(1)[0]
            modal[key] = {"series": was, "runs": n}
    windows = Counter(r["judge_max_chars"] for r in prior if r.get("judge_max_chars"))
    was, n = windows.most_common(1)[0] if windows else (HISTORICAL_JUDGE_MAX_CHARS, len(prior))
    if prior and was != current["judge_max_chars"]:
        modal["judge_max_chars"] = {"series": was, "runs": n}
    return modal


def code_outside_checkout() -> str:
    """"" when this harness imports okl from this checkout's src and `python -m okl`, run as its
    subprocesses run it, does too; otherwise where one of them loads okl from. An editable install
    points both at the checkout it was installed from, so a run from a worktree without
    PYTHONPATH would measure another tree's code under this tree's commit (review on #303)."""
    import okl
    src = (REPO / "src").resolve()
    here = Path(okl.__file__).resolve()
    if not here.is_relative_to(src):
        return f"this process imports okl from {here.parent}, not {src}"
    # From the checkout, as the briefings are rendered, and from elsewhere, as the generator's
    # shim runs: a relative PYTHONPATH holds in one and not the other (review on #303).
    for cwd in (REPO, Path(tempfile.gettempdir())):
        r = subprocess.run([sys.executable, "-c", "import okl; print(okl.__file__)"], cwd=cwd,
                           capture_output=True, text=True)
        there = Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None
        if there is None or not there.is_relative_to(src):
            return f"`python -m okl` run from {cwd} loads okl from {there.parent if there else 'nowhere'}, not {src}"
    return ""


def judge_is_generator(models: dict) -> bool:
    """True when the judge resolved to exactly the generator's models.

    The startup guard compares command strings, and two strings can name one model
    (`--model sonnet` and the model's full id), so the judge could grade its own model's
    output (CodeRabbit on #168). Equal sets, not overlap: a CLI can report a helper model
    beside the main one, and a shared helper is not the judge grading itself. Unknown on
    either side proves nothing; the string guard still stands.
    """
    gen, judge = models.get("generator"), models.get("judge")
    return bool(gen) and gen == judge


def resolved_model(cmd: str, timeout: int, workdir: str) -> list[str] | None:
    """The model ids a `claude` command resolves to, from one tiny call; None otherwise.

    A receipt named only the alias (`sonnet`), so when §4j's unbriefed arm fell 26 points
    nothing could say whether the model behind the alias had changed (review item R12).
    `claude -p --output-format json` lists the models it used under `modelUsage`. Any other
    command, or a failed probe, records None: the receipt says it does not know, rather
    than guessing from the alias.
    """
    argv = shlex.split(cmd)
    if not argv or Path(argv[0]).name != "claude" or "--output-format" in argv:
        return None
    try:
        r = subprocess.run([*argv, "--output-format", "json"], input="Reply with the single word OK.",
                           capture_output=True, text=True, timeout=timeout, cwd=workdir)
        usage = json.loads(r.stdout).get("modelUsage") if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    return sorted(usage) if isinstance(usage, dict) and usage else None


def drift_banner(drift_from: dict) -> str:
    """The report-time instrument warning, as a string.

    A function rather than an inline print so it can be tested. Inline, it was reachable
    only by a full harness run, and every test used --dry-run, which returns before any
    report is printed. So when the drift record's shape changed — it carried a `receipt`
    name while the comparison was against the latest run, and stopped when the comparison
    moved to the modal instrument — this formatter kept reaching for a key that no longer
    existed, and nothing failed until a real off-series run crashed at the very end.

    Not merely repeated from startup: the report is what gets read and pasted.
    """
    return ("⚠️  NOT COMPARABLE ACROSS RUNS — this run's instrument differs from the series: "
            + "; ".join(f"{k} series uses {v['series']} ({v['runs']} runs)"
                        for k, v in drift_from.items() if isinstance(v, dict))
            + ". These numbers are internally valid only.")


def head_moved(started: tuple[str | None, str] | None,
               now: tuple[str | None, str] | None) -> dict | None:
    """The receipt fields for a working tree that moved during a run, or None.

    The briefed arm renders from this checkout's `src/`, so a branch switch mid-run
    briefs the later samples with code the pre-registration never described, and the
    receipt would then name only the commit found at the end. Receipt ab-20261022-0455
    was made that way (REPORT §4o); a run whose tree moved is not usable, and says so.

    Each side is `tree_state()`: the commit label the receipt shows and a fingerprint of
    the code. The fingerprint decides, so an edit to a tree that was already `+dirty`
    counts as movement even though its label did not change (review on #262).
    """
    if started is None or now is None or started[1] == now[1]:
        return None
    return {"okl_commit_at_start": started[0], "okl_commit": now[0], "working_tree_moved": True}


def moved_banner(moved: dict) -> str:
    """The report-time line for a run whose working tree moved; a function so it is testable."""
    return (f"❌ RESULTS NOT USABLE — the working tree moved from {moved['okl_commit_at_start']} to "
            f"{moved['okl_commit']} during the run, so the later briefings came from code the "
            "pre-registration did not describe. Run the harness from a pinned worktree.")


def _okl_commit() -> str | None:
    """The commit that rendered this run's briefings, marked `+dirty` when okl's code had
    uncommitted edits: a bare hash would then name code that did not produce the receipt
    (found in review of #52)."""
    return tree_state()[0]


def _head(git: list[str]) -> tuple[str, str] | None:
    """The short and full HEAD, or None when either lookup fails or reads empty."""
    short = subprocess.run([*git, "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    full = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True)
    if short.returncode != 0 or full.returncode != 0:
        return None
    return (short.stdout.strip(), full.stdout.strip()) if short.stdout.strip() and full.stdout.strip() else None


def tree_state() -> tuple[str | None, str]:
    """The receipt's commit label for okl's code, and a fingerprint of that code.

    The label is the short HEAD, `+dirty` when `src/okl` has uncommitted edits. The
    fingerprint is the full HEAD plus a hash of the uncommitted diff and the untracked
    files under `src/okl`, so two dirty trees with different content do not compare equal.
    """
    git = ["git", "-C", str(REPO)]
    heads = _head(git)
    if heads is None:
        # Fail closed, as for the other probes: no HEAD means no claim about the tree, and
        # two such readings must not compare equal. A full lookup that fails after the short
        # one read is the same case: an empty fingerprint would equal itself (review on #262).
        return None, f"head-failed-{os.urandom(4).hex()}"
    head, full = heads
    # --untracked-files=all: a wholly untracked directory is otherwise one "?? dir/" entry,
    # and its files' content would never reach the fingerprint. -z: NUL-delimited entries
    # with unquoted paths, so a name git would quote still resolves to its file.
    probe = subprocess.run([*git, "status", "--porcelain", "-z", "--untracked-files=all", "--", "src/okl"],
                           capture_output=True)
    if probe.returncode != 0:
        # Fail closed: a probe that cannot say what the tree holds must not compare equal
        # to anything, so the run reads as moved and the receipt as not usable.
        return f"{head}+unknown", f"{full}+status-failed-{os.urandom(4).hex()}"
    entries = [e for e in probe.stdout.decode("utf-8", "surrogateescape").split("\0") if e]
    if not entries:
        return head, full
    diffed = subprocess.run([*git, "diff", "HEAD", "--", "src/okl"], capture_output=True)
    if diffed.returncode != 0:
        # Same rule as the status probe: a diff that cannot be read must not compare equal.
        return f"{head}+unknown", f"{full}+diff-failed-{os.urandom(4).hex()}"
    # One digest per untracked file, keyed by path: a lossless manifest, so two files whose
    # contents shift a boundary ("ab","c" -> "a","bc") do not hash alike.
    manifest = hashlib.sha256(diffed.stdout)
    for entry in entries:
        manifest.update(entry.encode("utf-8", "surrogateescape") + b"\0")
        if entry.startswith("?? "):
            path = Path(REPO, entry[3:])
            if path.is_file():
                try:
                    manifest.update(hashlib.sha256(path.read_bytes()).digest())
                except OSError:
                    # Listed a moment ago and unreadable now: the tree is moving under the
                    # probe, which is the very thing to report, not a reason to abort the run.
                    return f"{head}+unknown", f"{full}+read-failed-{os.urandom(4).hex()}"
    return f"{head}+dirty", f"{full}+{manifest.hexdigest()[:16]}"


def main() -> int:
    """Run every task through both arms, print the report, and write the receipt to evals/results/.

    Returns the exit code: 0 for a usable run (or a --dry-run, which only lists the plan),
    1 when the failure rate makes the results unusable, and 3, 4 or 5 when it refuses to start
    (judge equals generator, a task cites an unknown defect_node, the pre-flight failed).
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(REPO / "evals" / "tasks.jsonl"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--samples", type=int, default=1,
                    help="repetitions per (task, arm) — single samples are noisy; ≥3 for citable numbers")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--accept-missing-lessons", action="store_true",
                    help="run even when some tasks' briefings lack their governing lesson, and list them "
                         "in the receipt. For an instrument where that absence is the condition under "
                         "study (§4r's held-out tasks), never for the authored series.")
    ap.add_argument("--arms", default="baseline,briefed", type=parse_arms,
                    help="comma-separated subset of baseline,briefed,indexed,nearmiss,full,line (§4r adds "
                         "indexed: the briefing plus every other lesson in scope, for a generator that may "
                         "`okl show`; §4aa adds full and line: the governing lesson in full, or only as the "
                         "second tier's first line)")
    args = ap.parse_args()
    arms = args.arms

    if GENERATOR_CMD.strip() == JUDGE_CMD.strip():
        print("REFUSING TO RUN: JUDGE_CMD == GENERATOR_CMD — the judge must not grade "
              "its own homework (qz_judge_self).", file=sys.stderr)
        return 3

    # INSTRUMENT CONTINUITY. A run graded by a different judge than the series it will be
    # quoted alongside is internally valid and externally meaningless, and nothing about it
    # looks wrong: no failure, no warning, both arms simply shift together the way a
    # stricter grader shifts them. That happened — REPORT §4f was launched with opus where
    # every prior run used haiku, typed inline with the other flags and caught only when
    # the receipts were tabulated by hand afterwards.
    #
    # This does not refuse. Changing the instrument is sometimes the point (§4a's
    # cross-model run swapped both arms deliberately). It makes the change impossible to
    # MISS: named at startup, repeated in the final report, and — the part that actually
    # matters — stamped into the receipt, because a run launched in the background scrolls
    # its startup banner past nobody. A reader tabulating receipts sees the flag.
    # Compared against the MODAL instrument, not the most recent receipt. The first version
    # compared against the latest one and got its first live run exactly backwards: the run
    # before it was the anomalous opus-judged §4f, so a run returning to the documented
    # haiku judge was announced as "NOT COMPARABLE" when it had just restored the series.
    # A guard that tells you to discard the run that fixed the problem is worse than none.
    # The series is what a number gets quoted against, and the series is the mode.
    drift_from = None
    prior, last_name = [], None
    for p in sorted(RESULTS_DIR.glob("ab-*.json")):
        try:
            prior.append(json.loads(p.read_text()))
            last_name = p.name
        # Why the noqa below: one corrupt receipt must not stop a run, and this loops over a
        # handful of files once at startup — PERF203's hot-loop concern does not apply.
        except (OSError, ValueError):
            continue
    current = {"generator": GENERATOR_CMD.strip(), "judge": JUDGE_CMD.strip(),
               "judge_max_chars": JUDGE_MAX_CHARS}
    if prior:
        modal = instrument_drift(prior, current)
        if modal:
            drift_from = {"differs_from": "modal instrument", **modal}
            print("⚠️  INSTRUMENT DIFFERS FROM THE SERIES — these numbers are internally "
                  "valid but may not be quoted against earlier runs:", file=sys.stderr)
            for k, v in modal.items():
                print(f"      {k}: series uses {v['series']} ({v['runs']} runs)  →  this run "
                      f"uses {current[k]}", file=sys.stderr)
        elif (any(prior[-1].get(k, "").strip() != current[k] for k in ("generator", "judge"))
              or prior[-1].get("judge_max_chars", HISTORICAL_JUDGE_MAX_CHARS) != JUDGE_MAX_CHARS):
            # On the series, but the run immediately before was not. Say so plainly: this
            # is the case that restores comparability, and it must not read as a warning.
            print(f"ℹ️  instrument matches the series; the previous receipt ({last_name}) "
                  "did not. This run restores comparability.", file=sys.stderr)

    tasks = [json.loads(line) for line in Path(args.tasks).read_text().splitlines() if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]

    # Every task's defect_node must resolve to a real record. It is provenance, not an
    # input to judging, which is exactly why it rotted unnoticed: `r_pin_gating_tool` was
    # recorded in eight receipts while the record is `r_pin_gating_tools`, so those results
    # could not be traced back to the lesson they test.
    #
    # Client(), not Store(): a bare Store() defaults to sqlite:///okl.db in the CURRENT
    # directory and silently creates an empty one, so the check would have "found" every
    # reference missing while pointing at a database that never existed. Client walks up to
    # the configured .okl/ the way every other command does.
    lacking: list[str] = []
    lined: list[str] = []
    if not args.dry_run:
        # Retrieval is deterministic, so whether each task still receives the rule it tests
        # is answerable in milliseconds. Checking it AFTER a 25-minute run is how §4d cost
        # what it cost. Refused here, before anything is spent.
        # The gate reads the task set this run executes, with its --limit, not the authored
        # file regardless (review on #269).
        pf = subprocess.run([sys.executable, str(Path(__file__).parent / "preflight.py"),
                             "--tasks", str(args.tasks),
                             *(["--limit", str(args.limit)] if args.limit else []),
                             *(["--accept-missing"] if args.accept_missing_lessons else [])],
                            capture_output=True, text=True)
        print(pf.stdout, end="")
        print(pf.stderr, end="", file=sys.stderr)   # a refusal (e.g. no store) says why here
        if pf.returncode != 0:
            print("REFUSING TO RUN: pre-flight failed (see above).")
            return 5
        # Which tasks measure the briefing without their lesson, for the receipt's face.
        lacking = [ln.split()[1] for ln in pf.stdout.splitlines() if ln.strip().startswith("[MISSING]")]
        # And which receive it only as a one-line entry (REPORT §4aa; review on #303).
        lined = [ln.split()[1] for ln in pf.stdout.splitlines() if ln.strip().startswith("[line]")]

        from okl.client import Client
        _client = Client()
        _nodes = {n.id for n in _client.all_nodes()}
        missing = [(t["id"], t["defect_node"]) for t in tasks
                   if t.get("defect_node") and t["defect_node"] not in _nodes]
        if missing:
            print("REFUSING TO RUN: task(s) cite a defect_node that is not in the store —")
            for tid, node in missing:
                print(f"  {tid}: {node}")
            print("Fix the id in tasks.jsonl, or seed the record it names.")
            return 4

    n_runs = len(tasks) * len(arms) * args.samples
    if args.dry_run:
        for t in tasks:
            print(f"— {t['id']}  (defect: {t['defect_node']})")
        print(f"\n{len(tasks)} task(s) × {len(arms)} arm(s) ({', '.join(arms)}) × {args.samples} sample(s) = "
              f"{n_runs} generations + {n_runs} judgments")
        print(f"generator: {generator_cmd()}\njudge:     {JUDGE_CMD}"
              + (f"\ntools:     {GENERATOR_TOOLS} (an okl shim logs each fetch)" if GENERATOR_TOOLS else "")
              + (f"\nwhen-tool: {generator_cmd('when-tool', '<per-sample config>')}"
                 if GENERATOR_TOOLS and "when-tool" in arms else ""))
        return 0

    results, failures = [], []
    index_chars: int | None = None
    started_tree = tree_state()
    with tempfile.TemporaryDirectory(prefix="okl-ab-") as clean_cwd:
        if GENERATOR_TOOLS:
            write_shim(clean_cwd)
        models = {"generator": resolved_model(GENERATOR_CMD, args.timeout, clean_cwd),
                  "judge": resolved_model(JUDGE_CMD, args.timeout, clean_cwd)}
        print(f"resolved models: generator {models['generator']}, judge {models['judge']}")
        refused = startup_refusal(models, arms, clean_cwd, tasks[0]["defect_node"], args.timeout)
        if refused:
            print(f"REFUSING TO RUN: {refused[1]}", file=sys.stderr)
            return refused[0]
        for t in tasks:
            # The briefing is deterministic per task — fetch once, reuse across samples.
            brief_err = ""
            briefed_header = indexed_header = nearmiss_header = None
            tier_headers, tier_err = tier_headers_for(t, arms, args.timeout)
            try:
                if "briefed" in arms:
                    briefed_header = BRIEFING_HEADER.format(briefing=get_briefing(t["task"], args.timeout))
                if "nearmiss" in arms:
                    nearmiss_header = BRIEFING_HEADER.format(
                        briefing=get_briefing(t["task"], args.timeout, near_misses=True))
                if "indexed" in arms:
                    with_index = get_briefing(t["task"], args.timeout, index=True)
                    indexed_header = BRIEFING_HEADER.format(briefing=with_index)
                    # The index's cost is part of the treatment: the characters it adds.
                    index_chars = max(index_chars or 0, len(with_index) - len(get_briefing(t["task"], args.timeout)))
            except Exception as e:  # noqa: BLE001 — fail closed: no briefing, no briefed arm
                brief_err = str(e)[:300]
            for s in range(args.samples):
                for arm in arms:
                    rec, ok = run_one(t, arm, s, briefed_header=briefed_header,
                                      brief_err=tier_err if arm in TIER_ARMS else brief_err,
                                      timeout=args.timeout, workdir=clean_cwd, indexed_header=indexed_header,
                                      nearmiss_header=nearmiss_header, tier_headers=tier_headers)
                    if ok:
                        results.append(rec)
                        print(f"  {t['id']:16} {arm:8} s{s} → "
                              f"{'REPRODUCED' if rec['reproduced'] else 'clean':10} "
                              f"({rec['seconds']}s)", flush=True)
                    else:
                        failures.append(rec)
                        print(f"  {t['id']:16} {arm:8} s{s} → {failure_label(rec)}: {rec['error'][:80]}",
                              flush=True)

    # ---- report: failure count FIRST (qz_judge_crash) ----
    total = len(results) + len(failures)
    frate = len(failures) / total if total else 1.0
    print(f"\n=== A/B REPORT ===\nruns: {total}   FAILURES: {len(failures)} ({frate:.0%})"
          + failure_causes(failures))
    if frate > FAILURE_RATE_UNUSABLE:
        print("❌ RESULTS NOT USABLE — failure rate above threshold. Fix the harness before "
              "reading any number below.")
    # One reading of the tree at the end, used for both the verdict and the receipt, so
    # the receipt cannot say usable beside a commit the verdict never saw (review on #262).
    ended_tree = tree_state()
    moved = head_moved(started_tree, ended_tree)
    if moved:
        print(moved_banner(moved))
    if drift_from:
        print(drift_banner(drift_from))
    def by(arm: str) -> list[dict]:
        return [r for r in results if r["arm"] == arm]

    for arm in arms:
        rows = by(arm)
        rep = sum(r["reproduced"] for r in rows)
        print(f"  {arm:8}: defect reproduced in {rep}/{len(rows)} runs"
              + (f"  ({rep/len(rows):.0%})" if rows else ""))
        if GENERATOR_TOOLS and rows:
            got = sum(1 for r in rows if r.get("fetched_governing"))
            any_fetch = sum(1 for r in rows if r.get("fetched"))
            print(f"            fetched the governing lesson in {got}/{len(rows)}, fetched anything in {any_fetch}/{len(rows)}")
    if args.samples > 1:
        print("  per task (reproduced/samples):")
        for t in tasks:
            cells = []
            for arm in arms:
                rs = [r for r in by(arm) if r["task"] == t["id"]]
                cells.append(f"{arm} {sum(r['reproduced'] for r in rs)}/{len(rs)}")
            print(f"    {t['id']:28} " + "   ".join(cells))
    # conditional subset: tasks where the BASELINE arm failed at least once
    base_failed = {r["task"] for r in by("baseline") if r["reproduced"]}
    cond = [r for r in by("briefed") if r["task"] in base_failed]
    if cond:
        rep = sum(r["reproduced"] for r in cond)
        print(f"  briefed runs on the {len(base_failed)} task(s) the baseline failed at least once: "
              f"{rep}/{len(cond)} reproduced")
    out = RESULTS_DIR
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    path = out / f"ab-{stamp}.json"
    path.write_text(json.dumps({
        "generator": GENERATOR_CMD, "judge": JUDGE_CMD, "brief_interests": BRIEF_INTERESTS,
        # §4r: which arms ran, what the generator could do, and what the index cost per prompt.
        "arms": arms, "generator_tools": GENERATOR_TOOLS, "tasks_file": str(args.tasks),
        # §4ab: the command the arms ran (with tools on, only the MCP servers an arm names
        # load); the when-tool arm's command and the fetch tool's description are its treatment.
        "generator_cmd": generator_cmd(),
        **({"when_tool_generator": generator_cmd("when-tool", "<per-sample config>"),
            "fetch_tool_description": fetch_tool_description()} if "when-tool" in arms else {}),
        **({"preflight_missing": lacking} if args.accept_missing_lessons else {}),
        **({"preflight_line": lined} if lined else {}),
        **({"index_chars": index_chars} if index_chars is not None else {}),
        # How much of each submission the judge read (#182): part of the instrument.
        "judge_max_chars": JUDGE_MAX_CHARS,
        # What each alias resolved to on the day (None: not a claude command, or the probe
        # failed). Two receipts naming `sonnet` may not have run the same model (R12).
        "generator_model": models["generator"], "judge_model": models["judge"],
        "failure_rate": round(frate, 3),
        "usable": frate <= FAILURE_RATE_UNUSABLE and not moved,
        # Durable: a receipt read months later says on its own face whether it may be
        # compared to its neighbours. Absent means the instrument matched the prior run.
        "instrument_changed_from": drift_from,
        # The code that rendered the briefings. The briefing's layout is part of the
        # treatment (§4i changed it), and without this two receipts from different layouts
        # look identical on their face.
        "okl_commit": ended_tree[0],
        # Where the tree stood when the run began, and whether it moved (REPORT §4o).
        "okl_commit_at_start": started_tree[0],
        **({"working_tree_moved": True} if moved else {}),
        "results": results, "failures": failures,
    }, indent=1) + "\n")
    try:
        shown = path.relative_to(REPO)
    except ValueError:
        shown = path   # AB_RESULTS_DIR may point outside the repo
    print(f"\nwrote {shown}")
    return 0 if frate <= FAILURE_RATE_UNUSABLE and not moved else 1


if __name__ == "__main__":
    raise SystemExit(main())
