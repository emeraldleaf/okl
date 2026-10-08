---
description: Turn what this session just learned (a decision, a convention, a bug fixed) into an okl lesson — drafted from the conversation, recorded after you confirm.
argument-hint: "[what to record, in your own words — optional]"
---

# /record — add a lesson to the store from plain language

The person wants to keep something so the next session does not relearn it. They may
have said it in `$ARGUMENTS`; if that is empty, take it from the last few turns of this
conversation (the bug just fixed, the choice just made, the convention just followed).

## 1. Draft it

Pick the type from what it is:

- **Decision** — chosen on purpose; should not be quietly reversed. Body starts `why:`.
- **Rule** — a convention. Needs a `symptom` (what an agent would see or do that should
  trigger it) and a `fix` (what to do instead). Cause goes in `body`.
- **Defect** — a bug that was fixed. `symptom` is how it showed up, `fix` is the repair,
  `body` is the cause.

Then fill in, from evidence in this session only:

- **id** — a short kebab-case key (`discount-single-use`). Reusing an id updates that
  lesson; search first (`okl_search`) and reuse the id if this refines an existing one.
- **scope** — `repo` unless the lesson is true in every codebase that shares the store.
  If unsure, `repo`.
- **files** — the files the lesson governs, if it governs specific code. This is what
  makes `okl drift` notice when that code changes. Omit for pure decisions.
- **tags** — only from the vocabulary `okl_record` names; omit if none fits.
- **applies_to** — leave unset. Only set it if the lesson is *false* off one stack.

Do not invent a cause, a number or a file you have not seen in this session.

## 2. Show it, then record it

Show the draft as a short block (type, id, scope, title, symptom → fix, files) and ask
the person to confirm or correct it. On a yes, record it with the `okl_record` MCP tool.
If that tool is not available, run the equivalent `okl record --type … --id … --scope …`
command instead.

## 3. Decide how hard it must be enforced

Use the softest level that holds, and say which you chose:

- **Briefing only** — every lesson reaches the per-task briefing. Most need nothing more.
- **Watched by the drift gate** — the lesson governs specific code (`files` is set). Offer to prove it
  with a check that fails when the lesson is broken:

  ```bash
  okl verify <id> --run "<that check>" --expect "<text its passing output contains>"
  ```

  The drift gate (the pre-push hook by default, or CI with `okl init --ci`) then goes red
  when that code changes, until the check is re-run. If the repo commits `okl-drift.json`,
  remind the person to commit the refreshed copy. Never mark a lesson verified any
  other way.
- **Build-breaking** — the same mistake has happened before, or it is costly when it
  happens (security, data loss, a published number). Propose a test or CI check that
  fails the build; a sterner lesson will not stop a repeat.
- **Always-on** — only if every session needs it regardless of task, propose a line for
  `CLAUDE.md` / `AGENTS.md`. This is rare; the briefing already delivers the rest.

The `encoding-loop` skill has the full table.
