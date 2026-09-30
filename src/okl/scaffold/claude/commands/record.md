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

## 3. Offer the proof

A lesson is unverified until a check passes. If there is a test or command that fails
when the lesson is broken, offer to run:

```bash
okl verify <id> --run "<that check>" --expect "<text its passing output contains>"
```

Never mark it verified any other way. If the lesson has `files`, remind the person to
commit `okl-drift.json` after the verify.
