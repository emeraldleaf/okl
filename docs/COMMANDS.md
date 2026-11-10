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
okl intake pr <n>    # a PR's resolved review threads, each with the commit that resolved it (named in
                     #   a reply, or else the first commit after it to touch the file, marked a
                     #   guess), the lessons a briefing on it already shows, the encoding-loop
                     #   question, and the okl record and okl verify commands that would encode it;
                     #   unresolved threads are left out. Reads through gh (--repo OWNER/NAME; default:
                     #   the repo gh sees here); --format json for an agent; writes nothing, not
                     #   even the briefing log `okl metric` reads; exit 2 when gh cannot read the PR.
okl standing         # the lessons this repo names on every task briefing, one line each, because
                     #   changes here keep needing them; `okl standing add <id>...` and `remove
                     #   <id>...` keep the list in .okl/config.json, at most 10 (REPORT §4am measured
                     #   ten: the ones most needed on earlier work, named on every task, raised the
                     #   briefing's reach on later work). A lesson the briefing already names is not
                     #   repeated, a file briefing gets none, and OKL_STANDING=0 leaves them out.
okl changes          # what a change did to the files lessons name, read from git with no model:
                     #   new, deleted and renamed files, and code moved between files (5 or more
                     #   lines removed from one file and added to another, which git's rename
                     #   detection misses); the lessons governing each new file; where the tree
                     #   still names a removed path; and, for each of this repo's lessons left
                     #   pointing at the wrong place, a proposed `okl update --files` (a deleted
                     #   file's lesson is yours to re-point, drop or retire). Compares the merge base
                     #   with --base (default: the remote's default branch) to --head (default HEAD);
                     #   --format json for an agent; writes nothing; exit 2 when git cannot read it.
okl review           # opt-in: a model reads each lesson that governs no files and that no check
                     #   backs (the ones the briefing marks UNCHECKED) against the repo at HEAD,
                     #   in a scratch worktree, and reports each it questions (detail wrong,
                     #   outlived or stale) with the words that no longer hold; writes nothing.
                     #   It asks before the first model call (--yes skips; unattended without
                     #   it, exit 2); --list names the lessons and calls no model; <id>... judges
                     #   only those; --judge '<cmd>' swaps the judge (§4ai's rates are the default's). Exit 1 some
                     #   questioned; else 2 could not run or a lesson got no answer; 0 none
                     #   questioned. REPORT §4ai measured the default.
okl drift --gate     # flag lessons whose governed source changed after they were last verified
                     #   (exit 1 on drift, 2 when nothing could be checked; the pre-push hook
                     #   and CI run it; lessons last checked on another branch are listed
                     #   below the report, exit code unchanged)
okl export --drift   # write okl-drift.json, the committed snapshot CI's drift gate reads
                     #   when it has no store; `okl verify` creates it for the first lesson
                     #   with --files and refreshes it after that (with no CI workflow, it
                     #   only refreshes a committed one). A stamp made on a commit
                     #   outside this branch's history is not written: the lesson keeps
                     #   the entry this branch committed, or is left out, and is named.
                     #   CI reads the COMMITTED copy, and refuses an entry whose timestamp
                     #   does not match its verify evidence, so editing the timestamp alone
                     #   cannot clear it (editing both fields can; review is the guard).
                     #   Every refresh refuses to drop a rule the committed copy holds and
                     #   this store does not (another clone's), or to write one for another
                     #   repo, and names them; --allow-shrink writes it anyway.
okl doctor           # names other agent-memory tools installed beside okl (claude-mem,
                     #   agentmemory, ECC, beads) and how each collides with okl's hooks,
                     #   and whether the pre-push drift gate is installed and CI gates
                     #   drift; with `init --owner`, asks GitHub (through gh) whether
                     #   the owner's approval is enforced; and which org lessons this
                     #   repo's interests keep out of every briefing, with the default
                     #   subjects the list lacks. Writes nothing.
okl --version        # the installed release, for a repo whose hooks run a pinned okl
okl coverage         # ratio of encoded-knowledge lines to code lines — a health signal
okl bootstrap        # cold-start a new repo: propose starter notes from its own
                     #   git history + docs into a reviewable file you edit, then seed
okl metric           # recurrence: defect classes that came back, split by whether a
                     #   gate existed, with how many defects the number can speak for;
                     #   exposure: how many briefings okl has logged, the lessons
                     #   never shown, those shown most with no stored check, and how
                     #   many the interests keep out of those figures;
                     #   and hygiene: stale-use (briefings that included a lesson whose
                     #   code had changed since its check) and over-scope (org lessons
                     #   whose title, symptom or fix names one repository's world),
                     #   each with its denominator and the lessons it flags
okl check --path src/orders.py
                     # every lesson whose `files` govern a file, before it is read or edited,
                     #   with its drift and proof marks, in any --format (repeatable; #94).
                     #   Found by the files a lesson names, not by words, so none is ranked
                     #   out. Relative to the working directory or absolute; a file outside
                     #   the repo has none. Instead of --task; okl_check takes `path` too.
                     #   --format hook --hook-event PostToolUse --session <id> is what the
                     #   Claude Code read hook runs: each lesson once a session, again only
                     #   while drift marks it, the briefing framed by its sha256 and bytes.
                     #   OKL_FRAME_LOG=<file> appends that frame too (REPORT §4aj's instrument).
okl check --change [BASE]
                     # the review after writing: the files changed since BASE (default: the
                     #   remote's default branch, then main, then master), committed or not,
                     #   untracked included, and every lesson in scope one line each (those
                     #   governing a changed file first; about 60 tokens a lesson, never cut,
                     #   its first line saying to read all of it), with the steps: say what
                     #   the changed code does, pick the ten lessons it most likely breaks, read
                     #   each with okl show, check the code, fix only what breaks one and run
                     #   its tests again. okl calls no model; the agent does the review. A step under
                     #   measurement (REPORT §4at). --format json for a script. --format hook
                     #   prints only the Stop hook's one-line note, where `okl init
                     #   --review-after-writing` turned it on (OKL_REVIEW_AFTER_WRITING=1 or 0 for
                     #   one session); off by default. A retracted lesson stays in the list as
                     #   what to avoid. Exit 2 when git or the store cannot be read, or BASE
                     #   starts with '-'.
okl embed            # build or refresh one local vector per record for --hybrid briefings
                     #   (needs the `hybrid` extra; downloads a 131 MB static model once;
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
                     #   every check. Needs the `rerank` extra and `okl embed` once online (a
                     #   92 MB ONNX model). Measured and shipped off (REPORT §4t): one held-out
                     #   paraphrase in, one bug report out, 0.5 s a check.
okl check --decision floor
                     # how candidates become a briefing. The default, tiered, shows in full what
                     #   clears the calibrated line (three shared subject words in the title,
                     #   symptom, aliases and triggers, or two rare ones; at most five; REPORT
                     #   §4w) and lists the rest of what matched, one line each, up to --limit
                     #   (§4y). `calibrated` is the first tier alone; `floor` shows every match by
                     #   the word floor in full, up to --limit. `"decision"` in .okl/config.json
                     #   or OKL_DECISION sets it for every check.
okl check --warm on  # add what a lesson means to the words it shares, from the model `okl warm`
                     #   keeps loaded (REPORT §4z). On by default once `okl warm index` has embedded
                     #   a local store's lessons (a shared database needs `"warm": true`); --warm off,
                     #   `"warm": false` or OKL_WARM=0 turns it off. When the model does not answer,
                     #   the briefing is the usual one and the JSON says why (`warm_unavailable`,
                     #   `warm_reason`). A shared service does not run it, and `--decision floor`
                     #   does not use it.
okl warm start       # start the local process that keeps EmbeddingGemma (int8) loaded; needs the
                     #   warm extra; --wait N waits for it to load. stop, status, and serve (the
                     #   process itself, in the foreground) too; after `okl warm stop` the default
                     #   leaves it off until `okl warm start`, `index` or `serve`. About 1.6 GB from
                     #   startup (it runs one inference before it serves). One runs at a time; its
                     #   log is ~/.cache/okl/warm.log.
okl warm index       # embed this store's lessons for it, one vector per phrasing; again after
                     #   lessons change (only changed ones are embedded)
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
                     #   A bundled pack renamed since the store was seeded refreshes from its
                     #   new name: each record moves to the new id with its proof, and the
                     #   old id is superseded by it.
okl seed <pack> --strict
                     # exit 2 instead of importing when an advice record has no symptom,
                     #   a record is trace-shaped, or an org record names one repository's
                     #   paths or name; without it the same findings are printed as
                     #   warnings and the import runs
```
