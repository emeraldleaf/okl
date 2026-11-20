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
                     #   (or --yes), because they come from the store; --dry-run lists only;
                     #   --untimed also re-runs, once, each lesson whose check could run on edit
                     #   and has no timed run, so `okl on-edit add --quick` can judge it
okl retire <id> --reason "why"
                     # retire a lesson, keeping the reason with it; nothing is deleted. With no
                     #   other flag it was wrong: it stays briefed as AVOID, so nobody restates
                     #   it as fact. --by <id> names the lesson that replaces it: briefings leave
                     #   this one out and point to that one. --obsolete: its subject is gone, and
                     #   it is no longer briefed. Not both. A resolved defect is not retired; it
                     #   keeps briefing against its return. Drift stops checking a retired lesson,
                     #   and one that governs files refreshes okl-drift.json as `okl verify` does.
                     #   Exit 2, writing nothing, when it is refused, with the reason (a --by
                     #   lesson that is missing, retired or scoped more narrowly, for one), or the
                     #   store cannot be reached; exit 2 too when a service's answer is lost
                     #   (MAYBE RETIRED: running it again is safe).
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
okl on-edit          # the approved lesson checks, which run after every edit in the repo, those
                     #   of the lessons governing the edited file first
                     #   (Claude Code's edit hook calls `okl on-edit run <file>`; another agent's
                     #   hook can too). `okl on-edit add <id>...` shows each stored command and
                     #   approves it on your yes (--yes skips the question; unattended without it,
                     #   exit 2), pinned to the command's hash: a command that changes afterwards
                     #   is not run until approved again. `add --quick` does the same for the
                     #   lessons whose stored check last passed in at most --under seconds (10;
                     #   above 0, up to 30, 2.5 works), as okl verify and okl reverify timed it,
                     #   each shown with its time; a check that failed its last run is left out,
                     #   and one never timed is listed apart by id and title, never approved
                     #   (`okl reverify --untimed` times them). While none is approved, `okl
                     #   on-edit` and `okl init` say how many are quick (local stores only).
                     #   `remove <id>...` drops one. `run` exits
                     #   1 when a check failed, 2 when one could not be judged (out of time, or
                     #   changed since approved), 0 when every one passed or the file lies
                     #   outside the repo; each gets --timeout (30 s) and one edit --budget (50 s). Nothing is
                     #   stamped verified, and nothing runs until a check is approved.
okl on-edit list     # what `okl on-edit` alone prints: the approved checks, each with the command
                     #   it runs, marked NOT RUN when its stored check changed since it was
                     #   approved or its lesson can no longer have one (gone, retired, another
                     #   repo's, no stored check, or an unprintable character in its command,
                     #   signal, title or files); then the lessons that could be added, with the
                     #   command each would run. Exit 2, for every on-edit command, when there is
                     #   no .okl/config.json here or above or the store cannot be read.
okl on-edit remove <id>...
                     # stop running these lessons' checks after an edit, then list as `list`
                     #   does; exit 2, changing nothing, when one of them was never approved.
okl changes          # what a change did to the files lessons name, read from git with no model:
                     #   new, deleted and renamed files, and code moved between files (5 or more
                     #   lines removed from one file and added to another, which git's rename
                     #   detection misses); the lessons governing each new file; where the tree
                     #   still names a removed path; and, for each of this repo's lessons left
                     #   pointing at the wrong place, a proposed `okl update --files` (a deleted
                     #   file's lesson is yours to re-point, drop or retire). Compares the merge base
                     #   with --base (default: the remote's default branch) to --head (default HEAD),
                     #   in the git checkout --repo-dir names (default: the current directory; the
                     #   lessons still come from this directory's store); --format json for an
                     #   agent; writes nothing; exit 2 when git cannot read it.
okl review           # opt-in: a model reads each lesson that governs no files and that no check
                     #   backs (the ones the briefing marks UNCHECKED) against the repo at HEAD,
                     #   in a scratch worktree, and reports each it questions (detail wrong,
                     #   outlived or stale) with the words that no longer hold; writes nothing.
                     #   It asks before the first model call (--yes skips; unattended without
                     #   it, exit 2); --list names the lessons and calls no model; <id>... judges
                     #   only those; --judge '<cmd>' swaps the judge (§4ai's rates are the default's);
                     #   --workers sets how many lessons are judged at once (3), and --timeout the
                     #   seconds each may take (300). Exit 1 some questioned; else 2 could not run
                     #   or a lesson got no answer; 0 none questioned. REPORT §4ai measured the
                     #   default.
okl drift --gate     # flag lessons whose governed source changed after they were last verified
                     #   (exit 1 on drift, 2 when nothing could be checked; the pre-push hook
                     #   and CI run it; lessons last checked on another branch are listed
                     #   below the report, exit code unchanged). --repo-dir names the git
                     #   checkout whose history it reads (default: the top of the git repository
                     #   it runs in, from any folder of it).
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
                     #   repo, and names them; --allow-shrink writes it anyway. --output (-o)
                     #   writes it to another path (default: okl-drift.json at the project root).
okl doctor           # names other agent-memory tools installed beside okl (claude-mem,
                     #   agentmemory, ECC, beads) and how each collides with okl's hooks,
                     #   read from Claude Code's settings files (the user's in CLAUDE_CONFIG_DIR
                     #   when that is set, else ~/.claude, then the project's); and whether
                     #   the pre-push drift gate is installed and CI gates drift; with
                     #   `init --owner`, asks GitHub (through gh) whether the owner's
                     #   approval is enforced; and which org lessons this
                     #   repo's interests keep out of every briefing, with the default
                     #   subjects the list lacks. Writes nothing.
okl --version        # the installed release, for a repo whose hooks run a pinned okl
okl coverage         # ratio of encoded-knowledge lines to code lines — a health signal.
                     #   Code lines are those of the .py, .cs, .ts, .tsx, .js, .jsx, .go, .rs,
                     #   .java and .rb files git tracks in --repo-dir (default: the current
                     #   directory); --format json for a script.
okl bootstrap        # cold-start a new repo: propose starter notes from its own
                     #   git history + docs into a reviewable file you edit, then seed.
                     #   --out names the file (default okl-bootstrap.json); --repo-dir the
                     #   checkout it reads (default: the current directory).
okl metric           # recurrence: defect classes that came back, split by whether a
                     #   gate existed, with how many defects the number can speak for;
                     #   exposure: how many briefings okl has logged, the lessons
                     #   never shown, those shown most with no stored check, and how
                     #   many the interests keep out of those figures;
                     #   and hygiene: stale-use (briefings that included a lesson whose
                     #   code had changed since its check) and over-scope (org lessons
                     #   whose title, symptom or fix names one repository's world),
                     #   each with its denominator and the lessons it flags
okl dedup            # pairs of lessons that may say the same thing, for a person to rule on;
                     #   it never merges. Only lessons a briefing can show are compared: a
                     #   superseded or obsolete one is left out, and a retracted one, briefed as
                     #   AVOID, stays in. --threshold: the similarity, 0 to 1, a pair must reach
                     #   (default 0.45, set to over-report); --limit: pairs to print (20). Keep
                     #   one of a pair and retire the other with `okl retire <other> --by <kept>
                     #   --reason "..."`. Exit 1 when it finds a pair, 0 when none, 2 when okl is
                     #   not configured here.
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
                     #   governing a changed file first; about 60 tokens a lesson, never cut;
                     #   a list past about 24,000 characters comes in pages, each short enough
                     #   to arrive whole as one command's output, page 1 naming the command for
                     #   each further one), with the steps: say what
                     #   the changed code does, pick the ten lessons it most likely breaks, check
                     #   each in its own fresh sub-agent (on Sonnet in Claude Code, the model it was
                     #   measured with) with one question (does this change break
                     #   it?), asked to list every path the lesson's rule covers first,
                     #   fix only what breaks one and run its tests again. okl calls no model;
                     #   the agent does the review. A step under measurement (REPORT §4at to §4bg). --format json for a script. --format hook
                     #   prints only the Stop hook's one-line note, unless `okl init
                     #   --no-review-after-writing` turned it off (OKL_REVIEW_AFTER_WRITING=1 or 0 for
                     #   one session); on by default. A retracted lesson stays in the list as
                     #   what to avoid. Exit 2 when git or the store cannot be read, or BASE
                     #   starts with '-'.
okl check --change [BASE] [--repo R] --page N --of FINGERPRINT
                     # page N of that review, as page 1 names it (REPORT §4bk: a list past Claude
                     #   Code's ~30,000-character cap came back as a 2 KB preview). Exit 2 for a
                     #   page the review does not have, a page below 1, a FINGERPRINT other than
                     #   the review's now (its lessons, or which govern a changed file, changed
                     #   since page 1; a page saved into the repo is no change), and
                     #   --page other than 1 or --of with --task, --path, or --format json or hook.
okl recap --transcript <path> --log-review
                     # in Claude Code: read the session's transcript, and its sub-agents' under
                     #   ~/.claude/projects, and keep one row about its review after writing in the
                     #   store (the local file, or the database OKL_DATABASE_URL names), replaced when
                     #   the same session is logged again: whether Claude Code's Stop hook asked for
                     #   the review and the agent ran `okl check --change`, the files and lessons it
                     #   listed, and for each sub-agent the review started its model, the lessons it
                     #   opened, whether it edited anything in the repository and which files (the
                     #   edits elsewhere only counted), the tests it ran (a runner name, repository
                     #   paths and the outcome), and its tokens, with the review's tokens and seconds
                     #   (tokens are the work, input, output and cache creation; the cache reads, which a
                     #   call makes of the whole context and which cost far less, are kept apart), and how
                     #   many Agent calls came back as an error,
                     #   all counted from the review's command to the next prompt you typed, or to a
                     #   Stop-hook summary at which none of the review's sub-agents is still running (a
                     #   background one is running until its completion is reported, in any of the
                     #   shapes Claude Code writes it), so the stops between one lesson and the next
                     #   do not end it. The review is the first command that ran `okl check --change`
                     #   after the hook's note and before your next prompt; a prompt first means the
                     #   request was skipped (asked, not run). With several notes in a session the row
                     #   describes the last one: the earlier notes, and their runs, are not logged.
                     #   With no note at all, the first run counts. An Agent call that returned an
                     #   error started no sub-agent and is no check (the row does not count it). Ids, paths,
                     #   counts and model names only: no code, no command
                     #   line, no text from the session. The Stop hook runs it at a later stop, silently
                     #   and cut off after about five seconds.
                     #   It writes nothing, and exits 0, where the directory was never set up with
                     #   `okl init` (a store URL exported does not enroll it), where the review after
                     #   writing is off, where OKL_REVIEW_LOG=0 or `"review_log": false` in
                     #   .okl/config.json turns the log off (the environment wins), and for a session
                     #   that neither asked for the review nor ran it. Status goes to stderr. Exit 0 as
                     #   well when the transcript cannot be read. Exit 2: no --transcript; --report
                     #   given beside it; OKL_SERVICE_URL or `service_url` set (a shared service keeps
                     #   no such log); a review_log setting that is not on or off; the store cannot
                     #   be opened or written.
okl recap --reviews  # the review log, from those rows: how often the review was asked for and run,
                     #   how many reviews came in pages and how many of those read every page,
                     #   lessons checked per review, how many checks were followed by an edit, tokens (the work, with the cache reads apart)
                     #   and seconds per review, and per lesson how often it was checked and how often
                     #   that was followed by an edit. An edit after a check means the review acted on
                     #   that lesson, not that it caught a break: the log cannot tell whether the edit
                     #   fixed a real one, and only an edit in the repository counts. Claude Code sessions only, since other agents leave no
                     #   transcript okl can read. --since limits it, --limit sets how many lessons are
                     #   listed, --format json for a script; beside --log-review it still prints only
                     #   the report on stdout. Exit 2: --report given beside it, a service, or no store.
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
                     #   startup (it runs one inference before it serves). One runs at a time per
                     #   user, at the socket ~/.cache/okl/warm.sock (under XDG_CACHE_HOME when that
                     #   is set; OKL_WARM_SOCKET names another path). Its log is the socket's path
                     #   with .log for .sock: ~/.cache/okl/warm.log by default.
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
okl connect https://okl.internal --token "$OKL_TOKEN"
                     # point this repo at a shared okl service: writes the URL as service_url,
                     #   and with --token the token, to .okl/config.json in the current
                     #   directory, keeping the rest of the config. The .gitignore okl writes
                     #   in .okl/ keeps that file out of git, and on macOS and Linux a config
                     #   that holds a token is readable by its owner only. In CI and on shared
                     #   machines, give the token as OKL_TOKEN instead. `okl init --service <url>`
                     #   writes the same URL, with no token. Running the service: docs/DEPLOY.md.
okl serve            # run the shared HTTP service (needs the `service` extra); --host (default
                     #   0.0.0.0) and --port (default 8080). With OKL_TOKEN set, every route but
                     #   /health needs it. Without it, off loopback, serve refuses to start (exit
                     #   2), since every route would be open; --allow-no-token, or
                     #   OKL_ALLOW_NO_TOKEN=1, starts it anyway, for a proxy in front that
                     #   authenticates. Exit 2 as well when FastAPI or uvicorn is missing.
                     #   It serves the store OKL_DATABASE_URL names, else the one of the repo it
                     #   starts in, and exits 2 when nothing names one.
okl mcp              # serve okl's MCP tools over stdio, for any agent that speaks MCP (needs the
                     #   `mcp` extra): okl_check, okl_search, okl_get, okl_record, okl_update and
                     #   okl_retire, on the same store as the CLI. The agent's MCP config starts
                     #   it; for Claude Code, `okl init` registers it in .mcp.json when the extra
                     #   is installed. Exit 2 when the MCP SDK is missing or has no server class
                     #   okl knows.
okl scaffold .       # stamp the method kit into a folder (default: the current one): what
                     #   docs/SCAFFOLD.md lists, including skills and commands under .claude/
                     #   for Claude Code. It never overwrites a file unless --force, and lists
                     #   the <<FILL>> slots left to complete. --repo names the repo (default: the
                     #   folder's name); --profile <stack> adds that stack's rules to
                     #   .claude/rules/ (repeatable); --plugin also writes
                     #   .claude-plugin/plugin.json, a Claude Code plugin manifest; --verbose
                     #   lists each file written.
```
