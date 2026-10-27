# Every okl command

Part of okl's documentation; the [README](../README.md) is the short version.

The four everyday commands are in the README's "Use it"; these are the rest.

```bash
okl verify <id> --run "pytest -q" --expect "passed"
                     # run the named check and stamp the node verified ONLY on an observed
                     #   pass; the command + result is stored as the evidence trail.
                     #   --expect requires a positive success signal in the output, so an
                     #   exit code alone can't self-certify. (`record --verified` is
                     #   refused; historical receipts import through `okl seed`.)
okl reverify         # re-run the stored check of every drifted lesson, and of any last checked
                     #   on another branch, and re-stamp the passes;
                     #   lists the commands first and runs them only after you confirm
                     #   (or --yes), because they come from the store; --dry-run lists only
okl drift --gate     # flag lessons whose governed source changed after they were last verified
                     #   (exit 1 on drift, 2 when nothing could be checked; the pre-push hook
                     #   and CI run it; lessons last checked on another branch are listed
                     #   below the report, exit code unchanged)
okl export --drift   # write okl-drift.json, the committed snapshot CI's drift gate reads
                     #   when it has no store; `okl verify` creates it for the first lesson
                     #   with --files and refreshes it after that (with no CI workflow, it
                     #   only refreshes a committed one).
                     #   CI reads the COMMITTED copy, and refuses an entry whose timestamp
                     #   does not match its verify evidence, so editing the timestamp alone
                     #   cannot clear it (editing both fields can; review is the guard).
okl doctor           # names other agent-memory tools installed beside okl (claude-mem,
                     #   agentmemory, ECC, beads) and how each collides with okl's hooks,
                     #   and whether the pre-push drift gate is installed and CI gates
                     #   drift; reads settings and git config, changes nothing.
okl --version        # the installed release, for a repo whose hooks run a pinned okl
okl coverage         # ratio of encoded-knowledge lines to code lines — a health signal
okl bootstrap        # cold-start a new repo: propose starter notes from its own
                     #   git history + docs into a reviewable file you edit, then seed
okl metric           # recurrence: defect classes that came back, split by whether a
                     #   gate existed, with how many defects the number can speak for;
                     #   exposure: how many briefings okl has logged, the lessons
                     #   never shown, and those shown most with no stored check;
                     #   and hygiene: stale-use (briefings that included a lesson whose
                     #   code had changed since its check) and over-scope (org lessons
                     #   whose title, symptom or fix names one repository's world),
                     #   each with its denominator and the lessons it flags
okl embed            # build or refresh one local vector per record for --hybrid briefings
                     #   (needs the `hybrid` extra; downloads a 249 MB static model once;
                     #   re-embeds only records whose text changed). Off by default: a check
                     #   never reaches the network for it, and without the extra, the model or
                     #   the vectors the briefing is the full-text one and the JSON says why.
okl check --hybrid   # fuse the nearest records by that embedding with the full-text
                     #   candidates (linear, the measured configuration, or --hybrid rrf);
                     #   `"hybrid": "linear"` in .okl/config.json or OKL_HYBRID turns it on for
                     #   every check. What it buys and costs: REPORT §4q. A record found by
                     #   meaning alone is briefed only under --decision floor.
okl check --near-misses
                     # append the records that matched the task and were left out, by the decision
                     #   or the cutoff, as `- [id] title`, at most twelve (about 1.8 KB). Off by
                     #   default; REPORT §4s says why it was not measured live.
okl check --rerank   # reorder the first 24 candidates (fused when --hybrid is on) by a local
                     #   cross-encoder's score for the (task, record) pair before the gates;
                     #   `"rerank": true` in .okl/config.json or OKL_RERANK=1 turns it on for
                     #   every check. Needs the `rerank` extra and `okl embed` once online (an
                     #   80 MB ONNX model). Measured and shipped off (REPORT §4t): one held-out
                     #   paraphrase in, one bug report out, 0.5 s a check.
okl check --decision floor
                     # how candidates become a briefing. The default, tiered, shows in full what
                     #   clears the calibrated line (three shared subject words in the title,
                     #   symptom, aliases and triggers, or two rare ones; at most five; REPORT
                     #   §4w) and lists the rest of what matched, one line each, up to --limit
                     #   (§4y). `calibrated` is the first tier alone; `floor` shows every match by
                     #   the word floor in full, up to --limit. `"decision"` in .okl/config.json
                     #   or OKL_DECISION sets it for every check.
okl check --index    # append every other lesson in scope as `- [id] title`, so an agent can
                     #   fetch one with `okl show <id>` when the briefing did not select it.
                     #   A treatment under measurement (REPORT §4r); about 120 characters a lesson.
okl triggers         # list this store's own advice lessons that have no triggers (--format json
                     #   carries their text, for an agent to draft from: /triggers in Claude Code).
                     #   The default briefing finds a lesson by its title, symptom, aliases and
                     #   triggers; recorded lessons without them are found far less (REPORT §4x).
okl seed --refresh   # re-import only the records this store already holds, from the packs
                     #   they came from (newer symptoms, aliases, triggers, text; verification kept),
                     #   without importing the rest of each pack. No path: the bundled packs
                     #   the store's own seed ids name; a repo's own pack file is named.
okl seed <pack> --strict
                     # exit 2 instead of importing when an advice record has no symptom,
                     #   a record is trace-shaped, or an org record names one repository's
                     #   paths or name; without it the same findings are printed as
                     #   warnings and the import runs
```
