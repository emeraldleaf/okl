# E2E receipt — 2026-09-26 the plugin delivers the briefing (#45)

One haiku call. The scratch repo from `e2e-20260926/` with its project hooks removed
(`okl init --uninstall`: both hook scripts and both settings registrations gone, `.okl/`
kept), then a headless session with this checkout loaded as a plugin:

```
printf '%s' "Reply with exactly the single word: ok" \
  | OKL_BIN="/path/to/okl" OKL_DISABLED_HOOKS=encode   # replace with your okl \
    claude --plugin-dir /Users/joshuadell/Dev/okl -p --model haiku --allowedTools ""
```

| evidence | outcome |
|---|---|
| `transcript-plugin.jsonl` | one `UserPromptSubmit` `hook_success` attachment carrying the OKL briefing; no other source of that hook existed in the repo |
| `session-plugin.txt` | `ok` — the Stop question was switched off through the environment (`OKL_DISABLED_HOOKS=encode`), so `-p` printed the answer, not the reply to the hook |

What this shows: the plugin's `hooks/hooks.json` (top-level `hooks` key, `${CLAUDE_PLUGIN_ROOT}`
paths) loads, the hook anchors to `$CLAUDE_PROJECT_DIR` (the scratch repo, not the plugin
root), resolves okl, and injects the briefing. Both manifests passed `claude plugin validate`.

Not shown here: installation from the GitHub marketplace (`/plugin marketplace add
emeraldleaf/okl`), which needs the manifest on `main`. Until that is merged the plugin can
only be loaded with `--plugin-dir`.
