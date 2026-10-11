"""MCP server exposing okl.check / okl.record / okl.search to coding agents.

This is how Claude Code / Cursor / Copilot call the layer as first-class tools.
It resolves through the same Client, so it works in local OR remote mode. The
check tool fails CLOSED (raises) if a configured remote is unreachable.

Requires the `mcp` package: install 'observed-knowledge-ledger[mcp]'. Run: `okl mcp` (stdio transport).
"""
from __future__ import annotations

import json
from typing import Any

from . import core
from .client import (
    Client,
    OKLNoAnswerError,
    OKLNotConfiguredError,
    OKLRejectedError,
    OKLUnreachableError,
)


# Any: the server's class is picked at runtime from whichever SDK major is installed.
def _build() -> Any:  # noqa: C901, PLR0915 - a declarative table of tool definitions, see pyproject
    """Construct the MCP server, tolerating both major versions of the SDK.

    The class was renamed in mcp 2.x: `mcp.server.fastmcp.FastMCP` became
    `mcp.server.mcpserver.MCPServer`. The decorator API we use (`.tool()`) is the same
    on both, so try the newer name first and fall back. Without this, `pip install
    observed-knowledge-ledger[mcp]` resolves to 2.x and every tool call fails.
    """
    server_cls = None
    errors = []
    for module, name in (("mcp.server.mcpserver", "MCPServer"),   # mcp >= 2
                         ("mcp.server.fastmcp", "FastMCP")):      # mcp 1.x
        try:
            server_cls = getattr(__import__(module, fromlist=[name]), name)
            break
        except (ImportError, AttributeError) as e:
            errors.append(f"{module}.{name}: {e}")
    if server_cls is None:
        # Surface the REAL cause. Saying "install 'observed-knowledge-ledger[mcp]'" to someone who just did is
        # the same failure as reporting a validation error as an outage: the message
        # sends them to fix a thing that is not broken.
        raise RuntimeError(
            "Could not load an MCP server class from the installed 'mcp' package.\n"
            + "\n".join(f"  tried {e}" for e in errors)
            + "\nInstall the extra with `pip install \"observed-knowledge-ledger[mcp]\"`, or report "
              "this if the SDK has changed again.")

    # Clients read the server's version from the initialize reply. With none passed, mcp
    # 2.x sends "" and 1.x sends the SDK's own version (#159). Only 2.x takes `version`;
    # 1.x's FastMCP would fold an unknown keyword into its settings and drop it, so ask the
    # signature rather than catching an error.
    import inspect

    from . import __version__
    if "version" in inspect.signature(server_cls).parameters:
        mcp = server_cls("okl", version=__version__)
    else:
        mcp = server_cls("okl")
        mcp._mcp_server.version = __version__
    client = Client()

    @mcp.tool()
    def okl_check(task: str, repo: str | None = None, limit: int | None = None,
                  compact: bool = False) -> str:
        """Read the org's encoded rules that apply to a task, BEFORE starting it.

        Returns armed gates (with the defect each catches), past defects in this area,
        live retractions, retired identifiers, THREAT prior-art, rules and vocabulary.
        Call this first.

        `compact=True` returns ONLY the imperative action list (what to fix, when you
        see it, what to do): roughly 260 tokens at limit=3 and 940 at the default limit
        of 12, versus ~1,770 for the full briefing (measured by evals/briefing_size.py).
        Use it when working in a small context budget, e.g. a subagent handling one
        focused subtask. `limit` caps how many records are drawn on.
        """
        try:
            result = client.check(task, repo=repo, limit=limit)
        except OKLUnreachableError as e:
            return (f"⚠️ OKL UNREACHABLE — cannot confirm a clean check ({e}). "
                    "Treat as: rules may exist that you cannot see. Proceed with caution "
                    "and re-run once connectivity is restored.")
        except (OKLRejectedError, OKLNotConfiguredError) as e:
            # A service that refused the request (any 4xx, such as a 401 for a missing
            # token), or no store named here. Either way no check ran, and the agent must
            # hear that as plainly as an outage, not as a raw tool error. Only these two:
            # any other ValueError is a bug, and must surface as one.
            return (f"⚠️ OKL REFUSED THE CHECK — cannot confirm a clean check ({e}). "
                    "Treat as: rules may exist that you cannot see. Fix the cause in "
                    "parentheses and re-run.")
        if compact:
            return core.render_actions_only(result, limit=limit)
        return core.render_check_for_agent(result)

    # Keyword-only: the SDK always calls a tool with named arguments, and fourteen
    # mostly-string parameters are too easy to pass in the wrong order by position.
    @mcp.tool()
    def okl_record(*, type: str, title: str, scope: str, body: str | None = None,
                   status: str | None = None, found_by: str | None = None,
                   ttl_days: int | None = None, repo: str | None = None,
                   symptom: str | None = None, fix: str | None = None,
                   files: str | None = None, tags: str | None = None,
                   id: str | None = None, applies_to: str | None = None) -> str:
        """Record a NEW lesson. To change an existing one, use okl_update.

        scope='org' for facts about the world (prior art, API contracts, data
        gotchas, vocabulary) true in any repo; each repo has its own store, so another
        repo gets an org lesson only through a pack it loads. scope='repo' for a quirk
        true only of this codebase. type is one of: Defect, Gate,
        Rule, Claim, Retraction, Tombstone, Decision, PriorArt, Vocabulary, Entity.
        symptom/fix make the lesson actionable ("when you see X → do Z"; cause
        goes in body). files (comma-sep globs) enrolls it in drift detection.
        tags (comma-sep, controlled vocabulary — e.g. react, security,
        eval-integrity) categorize the subject so `check` can filter by interest.
        id is a short stable key for the new lesson. An id that already exists is
        refused: refine that lesson with okl_update, which keeps its proof.
        applies_to: leave unset unless the lesson is false off one stack; unset
        reaches every repo, a wrong value hides the lesson silently.
        """
        try:
            node_id = client.record(type=type, title=title, scope=scope, body=body,
                                    status=status, found_by=found_by, ttl_days=ttl_days,
                                    repo=repo, symptom=symptom, fix=fix, files=files, tags=tags,
                                    id=id, applies_to=applies_to)
        except core.LessonExistsError:
            # Point only at okl_update. The CLI also offers --replace, a deliberate
            # overwrite; an agent is not offered a one-step way to wipe a lesson's proof,
            # which is the defect this refusal exists for (review of okl R1).
            return (f"NOT RECORDED — a lesson with id {id!r} already exists. To change it, "
                    "call okl_update with that id: it changes only the fields you give and "
                    "keeps the lesson's proof.")
        except ValueError as e:
            # Hand the agent the actual complaint (unknown tag, bad scope) so it can fix
            # its own call. Raising here surfaces as an opaque "Error executing tool",
            # which reads like an outage and teaches the agent nothing.
            return f"NOT RECORDED — {e}"
        return f"recorded {node_id} ({type}, {scope})"

    @mcp.tool()
    def okl_search(query: str, scope: str | None = None, limit: int = 15) -> str:
        """Search the org's encoded body for anything matching `query`.

        Each line leads with the lesson's id: pass it to okl_update to refine that
        lesson rather than adding a near-duplicate, or to okl_get to read it whole.
        """
        try:
            rows = client.search(query, scope=scope, limit=limit)
        except OKLUnreachableError as e:
            return f"⚠️ OKL UNREACHABLE — no search ran ({e})."
        except (OKLRejectedError, OKLNotConfiguredError) as e:
            return f"⚠️ OKL REFUSED THE SEARCH — no search ran ({e})."
        if not rows:
            return "no matches."
        # The id was missing, so an agent told to "search first and reuse the id" had no
        # id to reuse (CodeRabbit on #79).
        return "\n".join(f"{r['id']} [{r['type']}] {r['scope']} — {r['title']}"
                         + (" (STALE)" if r.get("stale") else "") for r in rows)

    @mcp.tool()
    def okl_update(*, id: str, type: str | None = None, title: str | None = None,
                   scope: str | None = None, body: str | None = None,
                   status: str | None = None, found_by: str | None = None,
                   symptom: str | None = None, fix: str | None = None,
                   files: str | None = None, tags: str | None = None,
                   applies_to: str | None = None, ttl_days: int | None = None,
                   owner: str | None = None) -> str:
        """Refine an existing lesson by its id (the briefing shows it in [brackets]).

        Only the fields given change; an empty string clears an optional one. The proof
        and the first creation date are kept, unless `files` changes: a check of other
        files proves nothing about these, so the lesson then needs verifying again.
        """
        try:
            before = client.get(id)   # nothing is sent yet, so any failure is NOT UPDATED
        except (OKLUnreachableError, ValueError) as e:
            return f"NOT UPDATED — {e}"
        try:
            node = client.update(id, type=type, title=title, scope=scope, body=body,
                                 status=status, found_by=found_by, symptom=symptom, fix=fix,
                                 files=files, tags=tags, applies_to=applies_to,
                                 ttl_days=ttl_days, owner=owner)
        except OKLNoAnswerError as e:
            return (f"MAYBE UPDATED — the service may have applied this; calling okl_update "
                    f"again with the same fields is safe. ({e})")
        except (OKLUnreachableError, ValueError) as e:
            return f"NOT UPDATED — {e}"
        if node.get("verified_at") is not None:
            proof = "proof kept"
        elif before and before.get("verified_at") is not None:
            proof = ("proof cleared: its governed files changed. `okl reverify` re-runs its "
                     "stored check")
        else:
            proof = "not proven yet"
        return f"updated {node['id']} ({node['type']}, {node['scope']}): {proof}"

    @mcp.tool()
    def okl_retire(*, id: str, reason: str, by: str | None = None,
                   obsolete: bool = False) -> str:
        """Retire a lesson that is wrong, replaced or obsolete; it is never deleted.

        Wrong (the default) keeps it briefed as AVOID so nobody restates it as fact. `by`
        names the lesson that replaces it: briefings leave this one out and point there.
        `obsolete` is for a lesson whose subject is gone. A fixed defect is not retired; it
        keeps briefing against its return. `reason` is required and kept.
        """
        try:
            node = client.retire(id, reason, by=by, obsolete=obsolete)
        except OKLNoAnswerError as e:
            return (f"MAYBE RETIRED — the service may have applied this; calling okl_retire "
                    f"again is safe. ({e})")
        except (OKLUnreachableError, ValueError) as e:
            return f"NOT RETIRED — {e}"
        return f"retired {node['id']} ({node['status']})"

    @mcp.tool()
    def okl_get(id: str) -> str:
        """Read one lesson whole by its id, with its proof, as JSON."""
        try:
            node = client.get(id)
        except OKLUnreachableError as e:
            return f"⚠️ OKL UNREACHABLE — could not read the lesson ({e})."
        except ValueError as e:
            return f"⚠️ OKL REFUSED — could not read the lesson ({e})."
        if node is None:
            return f"no lesson with id {id!r}"
        return json.dumps(node, sort_keys=True)

    return mcp


def run_stdio() -> None:
    """Serve the MCP tools over stdio, the transport coding agents spawn."""
    _build().run()
