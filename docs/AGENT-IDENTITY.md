# Give your agent its own identity

okl keeps a thesis (`docs/THESIS.md`): the claim, what holds today, and a measured baseline.
The agent proposes changes to it, and a person decides. Nothing enforces the second half if the
agent works as your own GitHub account. GitHub cannot tell its approval from yours, and as an
administrator it can bypass branch protection or change it. A gate holds only if the agent
cannot change it, so the agent needs an identity of its own, without admin rights over what
gates it (#329).

## What okl does, and what it leaves to you

- **`okl init --owner @you`** writes a block into CODEOWNERS that names you as owner of:
  - `docs/THESIS.md`;
  - every place GitHub reads CODEOWNERS from (`.github/`, the root, `docs/`), so the gate cannot
    be edited around you, nor replaced by a new CODEOWNERS that GitHub would read first;
  - any path you add with `--owned` (repeatable), such as your rules or decision records.

  The block is spliced into an existing CODEOWNERS in its own line endings and changes no line
  of yours; only a last line with no newline gets one. A path you already own on a line of your
  own stays yours, and init says so. okl's block goes last, because CODEOWNERS applies the last
  line that matches, so a team-wide rule above it (`* @team`) does not take the thesis back. If
  okl's markers in the file no longer pair, init and uninstall keep the file and say so rather
  than guess. `okl init --uninstall` removes the block and nothing else.
- **In Claude Code, init adds deny rules** to `.claude/settings.json` for the usual ways to undo
  the gate: editing branch protection or rulesets through `gh api` (REST or GraphQL), and merging
  past them with `gh pr merge --admin` or the merge API. They advise the agent; GitHub is what
  enforces. Claude Code's rules do not match a command run through `sh -c '...'`, `gh` called by
  its full path, or a `git push`, so they never stand in for the branch rule. Uninstall removes
  these exact rules, including one you had written the same way. Other agents need their own
  equivalent.
- **`okl doctor` asks GitHub whether the gate is real,** and changes nothing. It says
  "enforced" only when it has read and recognised every condition: the merged CODEOWNERS gives
  each path to you, a rule requires code-owner review, a new push dismisses an approval, and the
  identity running it can neither bypass the rule nor change it. A condition it read as missing
  is "not enforced", with the reason; one it could not read or did not recognise is "unknown",
  with what it was. It lists each path's owner on the default branch. Run it as the agent's
  identity, `GH_TOKEN=<the agent's token> okl doctor`. Run as an administrator, it answers "not
  enforced", correctly: that identity can change the rule.
- **What okl cannot do:** create the identity or turn the protection on. Both are yours, on
  purpose. A gate the agent could set up, it could also take down.

## Set it up, in this order

1. **Create the agent's identity.** GitHub recommends an App for long-lived automation: its
   permissions are fine-grained, and it acts independently of any user. A machine account works
   too. Give it write access to contents and pull requests, and no administration.
2. **Give the agent that identity's token**, for example as `GH_TOKEN` in its environment. Your
   own login stays the administrator.
3. **Name yourself owner:** `okl init --owner @you`, then commit the CODEOWNERS file and merge it.
   GitHub reads CODEOWNERS from the branch a pull request targets, so it counts once it is on
   that branch.
4. **Turn on the rule for the default branch**, as a ruleset or as classic branch protection:
   - require a pull request, with review from code owners;
   - require approval of the most recent reviewable push, or dismiss stale approvals when new
     commits are pushed: without one of them, an approval of one change lets a later push merge;
   - keep your required status checks;
   - bind administrators: "Do not allow bypassing the above settings" in classic protection, or
     no bypass entry for the agent in a ruleset.

   Identity first, then protection. A pull request's author cannot approve it, so while the
   agent opens pull requests as you, requiring reviews blocks every one of them.
5. **Check it:** `GH_TOKEN=<the agent's token> okl doctor` should say "enforced".
6. **Prove it once, and write it down.** As the agent, open a pull request that changes
   `docs/THESIS.md` and try to merge it without your approval; then try to change the protection
   with the agent's token. GitHub should refuse both.

## Limits

- **GitHub only, for now.** Other hosts have their own code-owner approvals, and each would need
  its own version of `okl doctor`'s check.
- **What `okl doctor` cannot see.** A custom role granted "edit repository rules" reports its
  base role, so an identity holding one looks safe; give the agent a built-in role. A GitHub
  App's token may report no role at all, and then doctor answers "unknown": check in the App's
  settings that it has no Administration write permission. Classic branch protection is
  readable by an administrator only, so as the agent doctor can confirm a ruleset but not
  classic protection: use a ruleset, or doctor answers "unknown". It does not evaluate every
  CODEOWNERS glob as GitHub does; one that might own a path makes the answer "unknown".
- **Private repositories on GitHub Free** have no protected branches, code owners or required
  reviewers; GitHub Pro or a paid organization plan adds them. `okl doctor` says so when it can
  tell.
- **The cost** is one approval from you for each change to an owner-approved path. A pull
  request that touches none of them still merges on its checks.

## Considered: signed thesis commits

A check could fail a pull request whose changes to owner-approved paths are not signed by a key
in a committed list of allowed signers, with the key behind your touch on a hardware key or in a
password manager's agent. It works on any host and needs no second account. But an agent with an
admin token can edit that check or the protection, so it holds only with the same identity split,
or with the check run from the base branch under protection that binds administrators. It stays a
possible second layer, not the first step.

## Sources

- GitHub Docs, [About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches):
  review from code owners, and "Do not allow bypassing the above settings"; by default the
  restrictions do not apply to administrators.
- GitHub Docs, [Approving a pull request with required reviews](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/approving-a-pull-request-with-required-reviews):
  "Pull request authors cannot approve their own pull requests."
- GitHub Docs, [GitHub's plans](https://docs.github.com/en/get-started/learning-about-github/githubs-plans):
  GitHub Pro adds protected branches, required reviewers and code owners in private repositories.
- GitHub Docs, [Deciding when to build a GitHub App](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/deciding-when-to-build-a-github-app):
  an App is recommended for long-lived integrations, has fine-grained permissions, and acts
  independently of a user.
- Claude Code docs, [Configure permissions](https://code.claude.com/docs/en/permissions): deny
  rules win over allow rules, and a Bash rule does not match the same program run by its full
  path or inside `sh -c`.
