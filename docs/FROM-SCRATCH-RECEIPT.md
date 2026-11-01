# What was run for the from-scratch guide, 2026-11-01

The record behind [Set up a repository from scratch](FROM-SCRATCH.md): each command its tables
give, run on a scratch repository per stack, with what it printed. The scratch repositories were
deleted afterwards; this page is what remains of them. The CI workflows and the SonarQube steps
were not run.

## Python

uv 0.13.5 with Python 3.14; ruff 0.17.3, mypy 2.4.1, pytest 9.2.0, coverage 7.17.0,
import-linter 2.15, pip-audit 2.9.0. A layered package (`domain`, `infra`) with two tests.

| Command | Result |
|---|---|
| `uv add --dev --bounds exact ruff mypy pytest coverage import-linter` | `==` pins in `[dependency-groups].dev` |
| `uv lock --check` | `Resolved 21 packages` |
| `uv run ruff format --check .` | `6 files already formatted` |
| `uv run ruff check .` | `All checks passed!` |
| `uv run mypy` | `Success: no issues found in 5 source files` |
| `uv run lint-imports` | `Contracts: 1 kept, 0 broken.` |
| `uv run pytest -q tests/test_pricing.py::test_total_applies_the_discount_to_the_whole_order` | `1 passed` |
| `uv run coverage run -m pytest -q && uv run coverage xml` | `coverage.xml` written |
| `uv export … -o req.txt && uvx pip-audit==2.9.0 -r req.txt --disable-pip` | exit 0, `No known vulnerabilities found` |

In this first batch, output was piped through `tail`, so the rows above record the line each tool
printed, not its exit code. The runs below captured exit codes.

| Probe | Result |
|---|---|
| `pytest -q -k no_such_test` | exit 5 |
| a `domain` module importing `infra`, then `lint-imports` | `infra may import domain, never the reverse BROKEN`, `Contracts: 0 kept, 1 broken.`, exit 1 |
| `fail_under = 100`, one test, then `coverage report` | exit 2, `Coverage failure: total of 89 is less than fail-under=100` |
| pip-audit on a hashed pin of `urllib3==1.26.4` | three advisories listed, exit 1 |
| pip-audit without `--disable-pip`, under Python 3.14 | crashed creating its own virtualenv (`ensurepip` died with SIGABRT) |

**okl, from main:** `okl verify <id> --run "uv run pytest -q tests/test_pricing.py::test_total_refuses_a_discount_over_100_percent" --expect "1 passed"` verified the lesson.
- With no `--ci` workflow, it wrote no `okl-drift.json`.
- `okl drift --gate` on an uncommitted snapshot: `OKL SNAPSHOT REFUSED … not committed`, exit 2.
- After `okl export --drift`, a commit of the snapshot and a commit that broke the rule:
  `okl drift --gate` exited 1, and `okl reverify` reported `1 failed`.

## .NET

The .NET SDK 10.0.102; xunit.v3.mtp-v2 4.0.2, Microsoft.Testing.Extensions.CodeCoverage 18.1.0,
TngTech.ArchUnitNET.xUnitV3 0.13.5; `DOTNET_CLI_UI_LANGUAGE=en`. A second run at 23:22Z followed
the guide's Create-it block as published, with `global.json` naming the installed SDK.

| Command | Exit | Result |
|---|---|---|
| `dotnet --version` | 0 | `10.0.102` |
| `dotnet tool restore` | 0 | `Restore was successful` |
| `dotnet restore`, then `dotnet restore --locked-mode` | 0 | `Restored` |
| `dotnet format --verify-no-changes && echo OK:format` | 0 | `OK:format` |
| `dotnet build -c Release` | 0 | `Build succeeded.` |
| `CI=true dotnet build -c Release --no-incremental` | 0 | `Build succeeded.` |
| `dotnet test --project tests/App.Tests --filter-method '*.Total_DiscountOver100_Throws'` | 0 | `Test run summary: Passed!` (also when piped) |
| `dotnet test --project tests/App.ArchitectureTests` | 0 | `Test run summary: Passed!` |
| `dotnet test --coverage --coverage-output-format cobertura` | 0 | `Test run summary: Passed!`, a `TestResults/<guid>.cobertura.xml` per test project |
| `dotnet restore -p:AuditPipeline=true` | 0 | `Restored` |
| `dotnet package list --vulnerable --include-transitive` | 0 | `The given project `App` has no vulnerable packages given the current sources.` |

| Probe | Result |
|---|---|
| a filter matching nothing | `Test run summary: Zero tests ran`, exit 8 |
| a `Domain` type depending on `Infrastructure` | ArchUnitNET: `App.Domain.Leak does depend on "App.Infrastructure.OrderStore"`, exit 2 |
| `Newtonsoft.Json` 12.0.1, `CI=true dotnet restore` | `warning NU1903`, exit 0 |
| the same, `dotnet restore -p:AuditPipeline=true` | `error NU1903: Warning As Error`, exit 1 |

The runs corrected the guide four times:
- **Test names under `latest-recommended`.** It turns on CA1707, so `Method_Scenario_Expected`
  names failed the `CI=true` build: `Build FAILED.`, exit 1. With `tests/.editorconfig` setting
  CA1707 to `none`, it passed.
- **The `xunit3` template's framework.** It defaults to `net8.0`, and `dotnet add reference` to the
  `net10.0` library failed: "incompatible targeted frameworks". `-f net10.0` fixes it.
- **The editorconfig template.** It sets `insert_final_newline = false`, which makes
  `dotnet format` fail on the templates' own files (found in review). It also separates `using`
  groups, so `dotnet format` wanted a blank line before `using static`: `error WHITESPACE`, exit 2,
  until the snippet had one.
- **Speed.** `dotnet format` took several minutes on this machine.

**okl, from main:** `okl verify <id> --run "DOTNET_CLI_UI_LANGUAGE=en dotnet test --project tests/App.Tests --filter-method '*.Total_DiscountOver100_Throws'" --expect "Test run summary: Passed!"` verified the lesson in 2.4 seconds, build included.

## TypeScript

Node 22.22 with pnpm 11.3.0; typescript 6.0.3, eslint 10.14.0, typescript-eslint 8.72.1,
prettier 3.9.10, vitest and @vitest/coverage-v8 5.0.5, dependency-cruiser 18.7.0.

| Command | Exit | Result |
|---|---|---|
| `pnpm add -D -E …` | 0 | exact versions; `typescript 6.0.3 (7.0.2 is available)` |
| `pnpm exec prettier . --check` | 0 | `All matched files use Prettier code style!` |
| `pnpm exec eslint . --max-warnings 0` | 0 | no output |
| `pnpm exec tsc --noEmit` | 0 | no output |
| `pnpm exec depcruise src` (with `doNotFollow`) | 0 | `✔ no dependency violations found (4 modules, 3 dependencies cruised)` |
| `pnpm exec vitest run src/domain/pricing.test.ts -t 'refuses a discount' --reporter=dot` | 0 | `Tests  1 passed \| 1 skipped (2)` |
| `pnpm exec vitest run --coverage --reporter=dot` | 0 | `coverage/lcov.info` written |
| `pnpm audit --prod --audit-level high` | 0 | `No known vulnerabilities found` |

| Probe | Result |
|---|---|
| `depcruise src` without `doNotFollow` | 27 modules cruised: it followed into `node_modules` |
| a `domain` module importing `infra` | `error domain-not-to-infra`, `x 1 dependency violations`, exit 1 |
| a `-t` that matches nothing | exit 0, `Tests  2 skipped (2)`, no "passed" anywhere |
| `-t 'refuses a discount over 100 percent'`, with two tests containing that phrase | `Tests  2 passed \| 1 skipped (3)`, while `Test Files  1 passed (1)` still contains "1 passed" |
| `-t '^total > refuses a discount over 100 percent$'`, or the test's `file:line` | `Tests  1 passed \| 2 skipped (3)` |
| no `--reporter`, with `AI_AGENT` and `CLAUDECODE` set | the summary printed as usual |

**okl, from main:**
- `okl verify <id> --run "pnpm exec vitest run src/domain/pricing.test.ts -t 'refuses a discount' --reporter=dot" --expect "1 passed"`
  verified the lesson.
- With `-t 'renamed test'` it refused: `check exited 0 but expected signal '1 passed' NOT in output — NOT stamping`.
- The anchored pattern the guide now gives was run through Vitest, not through `okl verify`. Review
  confirmed that its quoting reaches the shell intact from zsh and bash.

## okl itself

- A `Gate` recorded with no files and verified with a passing check is briefed without a mark
  (on a throwaway store).
- `okl init` flags in the guide: `ci/check-init-flags.py` reads the guide, and fails on a flag
  `okl init --help` does not know.
