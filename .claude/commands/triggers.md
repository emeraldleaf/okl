---
description: Draft triggers for this store's own lessons that have none, so the briefing can find them — shown to you before anything is written.
argument-hint: "[a lesson id, to do just that one — optional]"
---

# /triggers — give recorded lessons the words that find them

okl briefs a lesson when a prompt shares enough of its subject with the lesson's title,
symptom, aliases and *triggers*: whole phrasings of the moments it applies, in a developer's
own words. A lesson recorded without triggers is found far less often. On a real store,
writing them for the recorded lessons raised what the briefing found (REPORT §4x).

## 1. List the lessons that need them

Run `okl triggers --format json`, or `okl triggers <id> --format json` when `$ARGUMENTS` names
one lesson. It lists this store's own advice lessons with no triggers (only that one, given an
id): id, type, title, symptom, body, fix and aliases. If the list is empty, say so and stop.

## 2. Draft ten per lesson, from the lesson alone

For each lesson, write exactly ten triggers:

- **4 task**: the work someone would be doing when the lesson matters, phrased as a request
  to a coding agent ("Add a retry to the upload job so…").
- **3 symptom**: what they would see once it had already gone wrong (an error, a surprising
  behaviour, a failed check), without naming the lesson's fix.
- **3 vocabulary**: the other words people use for the same situation, as a short request
  or question.

Each is 5 to 25 words. Write from the lesson's substance, not its title: vary the wording, be
concrete (the kind of file, command, tool or behaviour involved), and do not copy the title or
the fix. If this session holds the actual request or error that led to a lesson, use it as one
of its task or symptom triggers: real words beat imagined ones.

## 3. Show them, then write them

Show the drafts grouped by lesson, and ask the person to confirm, correct or skip each one.
On a yes, add them with the `okl_update` MCP tool (`triggers`, one phrasing per line), or with
`okl update <id> --trigger "…" --trigger "…"` (repeatable). That keeps each lesson's proof:
triggers govern no files.

Do not invent a cause, a tool or a file the lesson does not name.
