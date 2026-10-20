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
                     #   and exposure: how many briefings okl has logged, the lessons
                     #   never shown, and those shown most with no stored check
```
