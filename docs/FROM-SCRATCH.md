# Set up a repository from scratch, so okl works at its best

Part of okl's documentation; the [README](../README.md) is the short version. [Getting
started](GETTING-STARTED.md) wires okl into a repository that already has its tooling. This
page starts from an empty folder, for Python, .NET or TypeScript, and builds what okl needs to
point at. That means a CI that gates every change, tests small enough to prove one claim each,
and code shaped so a lesson can watch the few files it is about. Then it seeds okl, names the
tools that pair with it, and shows how to prompt so the briefing finds what you need.

Every gate in the tables below, and each lesson check, was run on a scratch repository per stack
on 2026-11-01. The CI workflows were not run; they follow each tool's own documentation. Every
tool choice cites its sources at the end. Versions move: pin the current release of each tool
when you start, and let Dependabot move the pins.

- [What you end with](#what-you-end-with)
- [What okl needs from your tooling](#what-okl-needs-from-your-tooling)
- [1. Every stack: versions, CI, GitHub settings, SonarQube](#1-every-stack-versions-ci-github-settings-sonarqube)
- [2. Python](#2-python)
- [3. .NET](#3-net)
- [4. TypeScript](#4-typescript)
- [5. Tests that make good checks](#5-tests-that-make-good-checks)
- [6. Shape the code so lessons can watch it](#6-shape-the-code-so-lessons-can-watch-it)
- [7. Wire okl in](#7-wire-okl-in)
- [8. Seed it](#8-seed-it)
- [9. Tools and skills that pair with okl](#9-tools-and-skills-that-pair-with-okl)
- [10. Prompting and daily use](#10-prompting-and-daily-use)
- [Checklist](#checklist)
- [Sources](#sources)

## What you end with

- **A CI that gates every change.** It runs a formatter, a linter, the type checker, the tests,
  architecture rules, a dependency audit and static analysis, each pinned to an exact version.
- **Tests that each prove one claim,** fast enough to run alone. These are the checks okl's
  lessons point at.
- **okl briefing your agent before each task,** from a store seeded with lessons for your stack
  and your own rules.
- **A drift gate.** When a file a proven lesson governs changes, the push is held until the
  lesson's check passes again.

## What okl needs from your tooling

A lesson is proven by a command:

```bash
okl verify <id> --run "<command>" --expect "<text>"
```

It passes only when the command exits 0 **and** its output contains the expected text. The
command has 120 seconds by default. Four things follow:

- **Selectable.** A check runs one test, or one rule, by its exact name. A suite that takes
  minutes is CI's job, not a lesson's.
- **A line that appears only on success.** Pick text a failure can never print. "1 passed" is
  also inside "11 passed", so select one test by its exact id.
- **A tool that is silent on success.** ESLint and `tsc` print nothing when they pass. Give such
  a tool its own marker: `--run "<tool> && echo OK:lint" --expect "OK:lint"`.
- **An empty selection must not pass.** A filter that matches no test exits 5 in pytest and
  8 in `dotnet test`. Vitest exits 0, printing that every test was skipped. The expected text
  catches all three: okl refuses to stamp a check whose output lacks it.

Two rules from the rest of okl's docs apply throughout:
- **CI-run checks govern no files.** What CI already runs needs no lesson to watch it. Give a
  lesson governed files only when its check is not a CI step; drift then re-checks it when
  those files change ([Getting started](GETTING-STARTED.md#prove-it-a-lesson-is-verified-by-running-a-check)).
- **The commit order.** After changing a file a lesson governs: commit the change, run `okl
  verify`, then commit the refreshed `okl-drift.json`
  ([Getting started](GETTING-STARTED.md#commit-in-this-order)).

## 1. Every stack: versions, CI, GitHub settings, SonarQube

**Versions.** Keep one home for versions, commit the lockfile, and pin every tool that gates CI
to an exact version. A range lets a release you never chose fail a branch that changed nothing.
Pin the runtime too: Python through uv, the .NET SDK in `global.json`, Node in `.node-version`.
Turn on Dependabot version updates for the package ecosystem and for `github-actions`, so the
pins move in pull requests you review.

**The CI workflow.** The workflows below follow GitHub's hardening guide:
- `permissions: contents: read` at the top;
- every action pinned to a full commit SHA, with the tag in a comment (`uses: actions/checkout@<sha> # v7`);
- a concurrency group, so a new push cancels the run it replaces.

Copy each action's SHA from its release page, or let Dependabot write them.

**GitHub settings, not code.** Turn these on in the repository's settings:
- Dependabot alerts;
- secret scanning with push protection;
- CodeQL's default setup, which needs no workflow file for these three languages.

They are free on public repositories. On private ones, secret scanning and CodeQL are paid
per active committer (GitHub Secret Protection and GitHub Code Security), so check GitHub's
current pricing. For a secret scan in CI that costs nothing, run the gitleaks binary from its
release page. Its README now says it takes security patches only.

**SonarQube.** For a new repository, use SonarQube Cloud with **CI-based** analysis.
- Automatic analysis cannot import coverage, so the coverage report your tests write would go
  unused.
- Cloud is free for public repositories. Private ones are free up to 50,000 lines and five
  members, analysing only the main branch and pull requests into it.
- A self-hosted SonarQube Community Build is free, but analyses the main branch only.
- Each stack below shows its scanner step and coverage path. Make the quality gate a required
  check.

## 2. Python

Tools: uv (environment and lockfile), Ruff (format and lint), mypy (strict), pytest, coverage.py,
import-linter (one-way imports). Sources disagree on one choice: Pyright is faster and is VS Code's
default, but mypy is the reference implementation and the most used checker, so it is the CI gate
here.

**Create it.**

```bash
uv init --lib my-service && cd my-service      # src/ layout, with py.typed
uv add --dev --bounds exact ruff mypy pytest coverage import-linter
```

`--bounds exact` writes `==` pins into `[dependency-groups]`, which never ship with the package.
Add to `pyproject.toml`:

```toml
[tool.ruff.lint]
select = ["E", "F", "UP", "B", "SIM", "I"]   # add groups one at a time; "ALL" grows on every upgrade

[tool.mypy]
strict = true                                # a new repo has nothing to loosen
warn_unreachable = true
files = ["src", "tests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["-ra", "--import-mode=importlib"]  # never --cov here: see below
strict = true
filterwarnings = ["error"]

[tool.coverage.run]
source = ["my_service"]
branch = true
relative_files = true                         # SonarQube needs repo-relative paths

[tool.importlinter]
root_package = "my_service"

[[tool.importlinter.contracts]]
id = "layers"
name = "infra may import domain, never the reverse"
type = "layers"
layers = ["my_service.infra", "my_service.domain"]
```

**The gates.**

| Gate | Command | Success text |
|---|---|---|
| Lockfile current | `uv lock --check` | `Resolved` |
| Format | `uv run ruff format --check .` | `already formatted` |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Types | `uv run mypy` | `Success: no issues found` |
| One-way imports | `uv run lint-imports` | `0 broken.` |
| One test | `uv run pytest -q tests/test_pricing.py::test_total_refuses_a_discount_over_100_percent` | `1 passed` |
| Full suite, coverage | `uv run coverage run -m pytest -q && uv run coverage xml` | exit 0 |
| Dependency audit | `uv export --format requirements.txt --no-emit-project -o req.txt && uvx pip-audit==<pin> -r req.txt --disable-pip` | `No known vulnerabilities found` |

A lesson's check, run on the scratch repository:

```bash
okl verify <id> --run "uv run pytest -q tests/test_pricing.py::test_total_refuses_a_discount_over_100_percent" --expect "1 passed"
```

`uv export` pins every package with its hash, so `--disable-pip` lets pip-audit read the file
as it is, without building a virtualenv to resolve it. Keep coverage out of `addopts`. With a `fail_under` threshold, a run of one test fails on
coverage even though the test passed (`coverage report` exits 2). Measure coverage on the
full-suite step only.

**CI.**

```yaml
on: { push: { branches: [main] }, pull_request: {} }
permissions: { contents: read }
concurrency: { group: "${{ github.workflow }}-${{ github.ref }}", cancel-in-progress: true }
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>        # v7
        with: { fetch-depth: 0 }            # SonarQube blame, gitleaks history
      - uses: astral-sh/setup-uv@<sha>      # pin
        with: { version: "<exact>", enable-cache: true }
      - run: uv sync --locked               # fails on a stale lockfile
      - run: uv run ruff format --check . && uv run ruff check --output-format=github .
      - run: uv run mypy
      - run: uv run lint-imports
      - run: uv run coverage run -m pytest -q && uv run coverage xml
      - run: uv export --format requirements.txt --no-emit-project -o req.txt && uvx pip-audit==<exact> -r req.txt --disable-pip
      - uses: SonarSource/sonarqube-scan-action@<sha>   # pin
        env: { SONAR_TOKEN: "${{ secrets.SONAR_TOKEN }}" }
```

For SonarQube, put `sonar.python.coverage.reportPaths=coverage.xml` in
`sonar-project.properties`. Pre-commit hooks are optional; if you add them, keep them to
`ruff check --fix` and `ruff format`, and leave mypy and the tests to CI.

## 3. .NET

Tools: the .NET 10 SDK (the current LTS), central package management, the SDK's own analyzers,
`dotnet format`, xUnit v3 on Microsoft.Testing.Platform, ArchUnitNET, Microsoft's coverage
extension, NuGet Audit. Sources disagree on two choices:
- **Test framework.** MSTest is as defensible as xUnit v3; both run on the new test platform.
- **Architecture rules.** NetArchTest has more downloads, but no release since 2021, so this
  page uses ArchUnitNET.

**Set the language first.** The SDK's and the test platform's summary lines are translated.
Put `DOTNET_CLI_UI_LANGUAGE=en` in CI's environment and in every lesson's check, or a check
written in English fails on a machine set to another language.

**Create it.**

```bash
dotnet new install xunit.v3.templates
dotnet new sln -n App                      # writes App.slnx
dotnet new classlib -o src/App
dotnet new xunit3 -o tests/App.Tests
dotnet new xunit3 -o tests/App.ArchitectureTests
dotnet sln add src/App tests/App.Tests tests/App.ArchitectureTests
dotnet add tests/App.Tests reference src/App
dotnet add tests/App.ArchitectureTests reference src/App
dotnet new tool-manifest && dotnet tool install dotnet-sonarscanner --version <exact>
```

The `xunit3` template targets `net8.0`, which leaves support on 2026-11-10. Delete
`TargetFramework`, `Nullable` and `ImplicitUsings` from each project and set them once:

`global.json` pins the SDK and opts in to the test platform:

```json
{
  "sdk": { "version": "10.0.403", "rollForward": "disable" },
  "test": { "runner": "Microsoft.Testing.Platform" }
}
```

`Directory.Build.props` applies to every project:

```xml
<Project>
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <AnalysisLevel>latest-recommended</AnalysisLevel>
    <EnforceCodeStyleInBuild>true</EnforceCodeStyleInBuild>
    <TreatWarningsAsErrors Condition="'$(CI)' == 'true'">true</TreatWarningsAsErrors>
    <RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>
    <!-- NuGet Audit: errors only in the audit step (restore -p:AuditPipeline=true) -->
    <NuGetAuditCodes>NU1900;NU1901;NU1902;NU1903;NU1904;NU1905</NuGetAuditCodes>
    <WarningsAsErrors Condition="'$(AuditPipeline)' == 'true'">$(WarningsAsErrors);$(NuGetAuditCodes)</WarningsAsErrors>
    <WarningsNotAsErrors Condition="'$(AuditPipeline)' != 'true'">$(WarningsNotAsErrors);$(NuGetAuditCodes)</WarningsNotAsErrors>
  </PropertyGroup>
</Project>
```

`Directory.Packages.props` holds every version, with transitive pinning:

```xml
<Project>
  <PropertyGroup>
    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
    <CentralPackageTransitivePinningEnabled>true</CentralPackageTransitivePinningEnabled>
  </PropertyGroup>
  <ItemGroup>
    <PackageVersion Include="xunit.v3.mtp-v2" Version="<exact>" />
    <PackageVersion Include="Microsoft.Testing.Extensions.CodeCoverage" Version="<exact>" />
    <PackageVersion Include="TngTech.ArchUnitNET.xUnitV3" Version="<exact>" />
  </ItemGroup>
</Project>
```

The projects then carry `<PackageReference Include="..." />` with no `Version`. Test names in the
`Method_Scenario_Expected` style that Microsoft's testing guidance recommends break a CI build:
`latest-recommended` turns on CA1707, which forbids underscores. Microsoft's page for CA1707 says
it is safe to suppress for test code, so add `tests/.editorconfig`:

```ini
[*.cs]
dotnet_diagnostic.CA1707.severity = none
```

An architecture rule is an ordinary test in its own project:

```csharp
private static readonly Architecture Arch =
    new ArchLoader().LoadAssemblies(typeof(App.Domain.Pricing).Assembly).Build();

[Fact]
public void Domain_DoesNotDependOn_Infrastructure() =>
    Types().That().ResideInNamespace("App.Domain").Should()
        .NotDependOnAny(Types().That().ResideInNamespace("App.Infrastructure")).Check(Arch);
```

**The gates.**

| Gate | Command | Success text |
|---|---|---|
| SDK | `dotnet --version` | the pinned version |
| Locked restore | `dotnet restore --locked-mode` | exit 0 |
| Format | `dotnet format --verify-no-changes && echo OK:format` | `OK:format` |
| Build and analyzers | `dotnet build -c Release` (CI sets `CI=true`) | `Build succeeded.` |
| One test | `dotnet test --project tests/App.Tests --filter-method '*.Total_DiscountOver100_Throws'` | `Test run summary: Passed!` |
| Architecture | `dotnet test --project tests/App.ArchitectureTests` | `Test run summary: Passed!` |
| Coverage | `dotnet test --coverage --coverage-output-format cobertura` | exit 0 |
| Dependency audit | `dotnet restore -p:AuditPipeline=true` | exit 0 (a known vulnerability is `error NU1903`, exit 1) |

Under the new test platform, xUnit filters with `--filter-method`, `--filter-class` and
`--filter-namespace`; the old `--filter` syntax does not work. A filter that matches nothing
prints `Test run summary: Zero tests ran` and exits 8. `dotnet package list --vulnerable
--include-transitive` reports findings but exits 0 either way, so the gate is the audit restore.

A lesson's check, run on the scratch repository (a few seconds, build included):

```bash
okl verify <id> --run "DOTNET_CLI_UI_LANGUAGE=en dotnet test --project tests/App.Tests --filter-method '*.Total_DiscountOver100_Throws'" --expect "Test run summary: Passed!"
```

**CI.** SonarQube runs in its own job: its scanner rebuilds the solution and overrides
`TreatWarningsAsErrors`, so it cannot double as the warnings gate.

```yaml
on: { push: { branches: [main] }, pull_request: {} }
permissions: { contents: read }
env: { DOTNET_CLI_UI_LANGUAGE: en, NUGET_PACKAGES: "${{ github.workspace }}/.nuget/packages" }
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>       # v7
      - uses: actions/setup-dotnet@<sha>   # pin
        with: { global-json-file: global.json, cache: true, cache-dependency-path: "**/packages.lock.json" }
      - run: dotnet tool restore
      - run: dotnet restore --locked-mode -p:AuditPipeline=true
      - run: dotnet format --verify-no-changes --no-restore
      - run: dotnet build -c Release --no-restore
      - run: dotnet test -c Release --no-build --coverage --coverage-output-format cobertura
  sonar:
    if: github.event_name == 'push' || github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>       # v7
        with: { fetch-depth: 0 }
      - uses: actions/setup-dotnet@<sha>
        with: { global-json-file: global.json }
      - run: dotnet tool restore
      - run: >-
          dotnet sonarscanner begin /k:"<key>" /o:"<org>" /d:sonar.token="${{ secrets.SONAR_TOKEN }}"
          /d:sonar.cs.cobertura.reportsPaths="**/TestResults/**/*.cobertura.xml" /d:sonar.qualitygate.wait=true
      - run: dotnet build -c Release --no-incremental
      - run: dotnet test -c Release --no-build --coverage --coverage-output-format cobertura
      - run: dotnet sonarscanner end /d:sonar.token="${{ secrets.SONAR_TOKEN }}"
```

GitHub sets `CI=true` on its runners, so the build treats warnings as errors there and not on a
laptop. Fork pull requests have no secrets, which is why the SonarQube job skips them.

## 4. TypeScript

Tools: Node's current LTS, pnpm, Prettier, ESLint with typescript-eslint, `tsc`, Vitest,
dependency-cruiser. Sources disagree on one choice: Biome is one fast tool for formatting and
linting, but by its own measure its type-aware rules catch less than typescript-eslint's, so this
page keeps ESLint and Prettier.

**Create it.**

```bash
mkdir my-service && cd my-service && git init
echo 26 > .node-version                 # the current LTS; match engines and @types/node to it
pnpm init
pnpm add -D -E typescript@6 eslint @eslint/js typescript-eslint prettier eslint-config-prettier \
  vitest @vitest/coverage-v8 dependency-cruiser @types/node@26
```

`-E` writes exact versions. Pin TypeScript to 6.x for now: `pnpm add typescript` installs 7.0,
and typescript-eslint does not support it yet. Set `"type": "module"`, `"packageManager":
"pnpm@<exact>"` and `"engines": { "node": ">=26" }` in `package.json`.

`tsconfig.json` for a Node service (a React app uses `module: preserve`, `moduleResolution:
bundler`, `jsx: react-jsx` and the `dom` lib instead):

```json
{
  "compilerOptions": {
    "target": "es2023",
    "module": "nodenext",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "verbatimModuleSyntax": true,
    "erasableSyntaxOnly": true,
    "rewriteRelativeImportExtensions": true,
    "types": ["node"],
    "noEmit": true,
    "skipLibCheck": true
  },
  "include": ["src", "*.config.ts", "*.config.js"]
}
```

`eslint.config.js`, type-aware (run Prettier on its own rather than through ESLint):

```js
import js from "@eslint/js";
import prettier from "eslint-config-prettier";
import { defineConfig } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["coverage/", ".dependency-cruiser.cjs"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, tseslint.configs.strictTypeChecked],
    languageOptions: { parserOptions: { projectService: true } },
  },
  prettier,
);
```

`vitest.config.ts` writes the coverage report SonarQube reads:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { coverage: { provider: "v8", reporter: ["text", "lcov"], include: ["src/**/*.ts"] } },
});
```

`.dependency-cruiser.cjs` holds the one-way rule. Keep `doNotFollow`; without it the check walks
into `node_modules`:

```js
module.exports = {
  forbidden: [
    { name: "no-circular", severity: "error", from: {}, to: { circular: true } },
    { name: "domain-not-to-infra", severity: "error", from: { path: "^src/domain" }, to: { path: "^src/infra" } },
  ],
  options: { doNotFollow: { path: "node_modules" }, tsPreCompilationDeps: true, tsConfig: { fileName: "tsconfig.json" } },
};
```

**The gates.**

| Gate | Command | Success text |
|---|---|---|
| Format | `pnpm exec prettier . --check` | `All matched files use Prettier code style!` |
| Lint | `pnpm exec eslint . --max-warnings 0 && echo OK:lint` | `OK:lint` |
| Types | `pnpm exec tsc --noEmit && echo OK:types` | `OK:types` |
| One-way imports | `pnpm exec depcruise src` | `no dependency violations found` |
| One test | `pnpm exec vitest run src/domain/pricing.test.ts -t 'refuses a discount' --reporter=dot` | `1 passed` |
| Full suite, coverage | `pnpm exec vitest run --coverage --reporter=dot` | exit 0 |
| Dependency audit | `pnpm audit --prod --audit-level high` | `No known vulnerabilities found` |

Give Vitest a file path with `-t`, or it loads every test file. Pass a reporter explicitly, so
the summary line a check expects does not depend on how Vitest guesses its environment. A `-t`
that matches nothing exits 0 with every test skipped and no "passed" anywhere, so the expected
text is what catches a renamed test:

```bash
okl verify <id> --run "pnpm exec vitest run src/domain/pricing.test.ts -t 'refuses a discount' --reporter=dot" --expect "1 passed"
```

**CI.**

```yaml
on: { push: { branches: [main] }, pull_request: {} }
permissions: { contents: read }
concurrency: { group: "${{ github.workflow }}-${{ github.ref }}", cancel-in-progress: true }
jobs:
  quality:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@<sha>        # v7
        with: { fetch-depth: 0 }
      - uses: pnpm/action-setup@<sha>       # reads packageManager
      - uses: actions/setup-node@<sha>
        with: { node-version-file: .node-version, cache: pnpm }
      - run: pnpm install                   # frozen lockfile in CI
      - run: pnpm exec prettier . --check
      - run: pnpm exec eslint . --max-warnings 0
      - run: pnpm exec tsc --noEmit
      - run: pnpm exec depcruise src
      - run: pnpm exec vitest run --coverage --reporter=dot
      - run: pnpm audit --prod --audit-level high
      - uses: SonarSource/sonarqube-scan-action@<sha>
        env: { SONAR_TOKEN: "${{ secrets.SONAR_TOKEN }}" }
```

For SonarQube, put `sonar.sources=src` and
`sonar.javascript.lcov.reportPaths=coverage/lcov.info` in `sonar-project.properties`.

## 5. Tests that make good checks

A lesson is only as good as the check behind it.

- **One claim per test, named for the claim.** `test_total_refuses_a_discount_over_100_percent`
  reads like the lesson it proves. The lesson's check runs that one test.
- **Test the behaviour the lesson is about,** not that the suite is green. A lesson about a
  discount cap points at the test of the cap.
- **Fast and alone.** A check that needs a database, a network or the whole suite belongs in CI.
- **Guard the tests themselves.** In okl's own eval, the breaks that neither drift nor CI caught
  weakened a test or a stated contract rather than the code: a weakened test still passes
  ([REPORT §4ah](../evals/REPORT.md)). Review changes to the tests a lesson points at as carefully
  as changes to the code.
- **Keep thresholds on the full suite.** Coverage gates and timing budgets fail a one-test run
  for reasons that have nothing to do with the claim.
- **Architecture rules are checks too.** A one-way-imports contract or an ArchUnitNET test is the
  check for a lesson about layering. Run it in CI and the lesson needs no governed files.

## 6. Shape the code so lessons can watch it

- **Small modules with one job.** A lesson that governs one or two files is re-checked only when
  they change. A lesson that governs a folder is re-checked on every change there.
- **Watch what the claim depends on, and no more.** That is a caller whose contract the lesson
  relies on, or the lockfile when a version matters. Every extra file adds re-checks.
- **Back doc claims with a check.** A README that documents a flag can carry a lesson whose check
  reads the README and the CLI ([Getting started §3](GETTING-STARTED.md#3-put-your-docs-in-the-canon-so-they-cannot-drift-silently)).
- **Write decisions down as ADRs,** so they load as decisions the agent will not silently reverse
  ([Load your rules](LOAD-YOUR-RULES.md#6-adrs-including-superseded-ones)).
- **Keep the always-on file short.** `CLAUDE.md` or `AGENTS.md` holds the rules every task needs.
  Everything that applies only sometimes is a lesson, briefed when it fits
  ([Getting started](GETTING-STARTED.md#store-records-vs-claudemd--agentsmd)).

## 7. Wire okl in

[Getting started §1](GETTING-STARTED.md#1-set-up-about-10-minutes) has the full steps. On a new
repository:

```bash
okl init --repo my-service --interests python --ci --git-hook
```

- `--interests` takes your stack's tags (`python`, `dotnet`, `frontend`, `react`), and init seeds
  the bundled packs that match.
- `--ci` adds okl's GitHub Actions drift workflow.
- `--git-hook` keeps the pre-push hook as well. It is the default only where that workflow is not
  installed, and it warns before CI does.
- When init finds Claude Code, it wires its hooks too.

Commit what it writes. Until the repository has a CI workflow, `okl verify` writes no
`okl-drift.json`: run `okl export --drift` once and commit it, or the gate refuses to run on a
snapshot that is not committed.

## 8. Seed it

An empty store briefs nothing. Fill it in this order ([Seeding](SEEDING.md) has the detail):

1. **Your stack's packs.** `okl seed` lists them and marks the ones that match your interests.

   | Stack | Packs |
   |---|---|
   | Python | `python-canon` |
   | .NET | `dotnet-canon`, `dotnet-decisions`, `dotnet-defects`, `dotnet-review-surfaces` |
   | TypeScript, React | `frontend-canon`, `react-defects` |

2. **Rules you already wrote.** Your rules files, ADRs, standards and specs become lessons that
   cite their source line ([Load your rules](LOAD-YOUR-RULES.md)). In Claude Code,
   `/seed-from-docs` proposes them. Another agent can follow its prompt file.
3. **What the code already enforces.** In Claude Code, `/seed-from-codebase` (from
   `okl scaffold .`) proposes lessons from your guard rails, CI and fix commits, each with a
   `file:line` citation.
4. **Triggers.** A lesson is found by the moments it applies to. `okl triggers` lists your
   lessons that have none. In Claude Code, `/triggers` drafts them for you to confirm.
5. **Prove the ones that govern code.** Give them files, and `okl verify` each with a check from
   sections 2 to 5.

Review before importing: a plausible rule no file supports is worse than an empty store.

## 9. Tools and skills that pair with okl

- **A reviewer on every pull request.**
  - A review bot, or your own reviewer agent with the repository's rules in front of it.
  - The scaffold's optional CI review step runs a model you name, and is off by default
    ([Costs and knobs](COSTS-AND-KNOBS.md#architecture-review-in-ci-off-by-default)).
  - When review finds a rule worth keeping, record it as a lesson, so it is checked next time
    rather than found again.
- **SonarQube,** for what okl does not hold: code smells, duplication, coverage on new code.
- **The method kit, `okl scaffold .`.** It adds two skills, the encoding loop and
  verify-before-claiming, and the gates that hold them ([Scaffold](SCAFFOLD.md)).
- **General engineering skills,** in Claude Code. The kit names a separately installed
  collection, Superpowers, for systematic debugging, test-driven development, plan writing and
  worktree isolation. Install it from its own project; it is not bundled.
- **Subagents** brief themselves the same way ([Subagents](SUBAGENTS.md)).

## 10. Prompting and daily use

**Name the subject.** The briefing compares your prompt's subject words with what each lesson
says it is about: its title, symptom, aliases and triggers. A lesson is briefed when it shares
three subject words with the prompt, or two rare ones. At most five are shown in full; other
matches are listed one line each, up to twelve, for the agent to read with `okl show <id>`
([Retrieval](RETRIEVAL.md)). "Fix the discount bug" says little. "Order
totals accept a discount over 100 percent" names the subject.

**Preview it.** `okl check --task "<your prompt>"` shows what the agent will be briefed on, before
you send the prompt.

**Read the marks.**
- **STALE:** the lesson's files changed since its check last passed. Run `okl reverify`.
- **UNCHECKED:** the lesson has no observed check behind it. Treat it as advice, and confirm it
  against the code before relying on it.

**Say what to remember.** "Remember: a discount is capped at 100 percent, tested in
`test_pricing.py`" is enough for the agent to record a lesson.
- In Claude Code the `/record` command drafts one from the session.
- Another agent calls the `okl_record` tool.
- Give each new lesson its trigger: the request or error that led to it is the best one.

**At the end of a session.**
- In Claude Code, the Stop hook asks once what was learned. Answer it, or say nothing new.
- `okl recap` lists the lessons the session was briefed on, and those whose files it changed. In
  Claude Code it reads the session's transcript.

**After changing governed code,** follow the commit order: commit, `okl verify`, commit the
snapshot. The pre-push hook holds the push until it is done.

**Now and then:**
- `okl doctor` reports what else is installed beside okl and where drift is gated.
- `okl metric` reports how often a known defect comes back after its lesson exists, and which
  lessons are never shown or most often shown unchecked.
- `okl triggers` lists lessons that cannot yet be found.

## Checklist

- [ ] Runtime pinned (`uv`, `global.json`, `.node-version`), lockfile committed, gate tools
      pinned exactly, Dependabot on for packages and actions.
- [ ] CI runs format, lint, types, tests with coverage, architecture rules and the dependency
      audit, with actions pinned by SHA and `permissions: contents: read`.
- [ ] Repository settings: Dependabot alerts, secret scanning with push protection, CodeQL default
      setup.
- [ ] SonarQube Cloud with CI-based analysis and its coverage report path; quality gate required.
- [ ] Each lesson-worthy claim has one fast test, selectable by exact name, with a success line
      only success prints.
- [ ] okl wired (`okl init`), the drift snapshot committed, the pre-push hook in place.
- [ ] Store seeded: stack packs, your own rules, triggers; lessons that govern code proven with
      `okl verify`.
- [ ] Prompts name their subject; STALE and UNCHECKED marks read; lessons recorded as you learn.

## Sources

Read on 2026-11-01. Each tool choice above rests on at least two of these.

**All stacks.**
- GitHub, [Security hardening for GitHub Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions);
  OpenSSF Scorecard, [Pinned-Dependencies](https://github.com/ossf/scorecard/blob/main/docs/checks.md).
- GitHub, [About GitHub Advanced Security](https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security);
  [Configuring default setup for code scanning](https://docs.github.com/en/code-security/code-scanning/enabling-code-scanning/configuring-default-setup-for-code-scanning).
- SonarSource, [sonarqube-scan-action](https://github.com/SonarSource/sonarqube-scan-action);
  [subscription plans](https://docs.sonarsource.com/sonarqube-cloud/administering-sonarcloud/managing-subscription/subscription-plans);
  [automatic analysis](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/automatic-analysis).
- [gitleaks](https://github.com/gitleaks/gitleaks).

**Python.**
- pytest, [good practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html),
  [usage](https://docs.pytest.org/en/stable/how-to/usage.html),
  [exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html).
- PyPA, [src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/);
  [dependency groups](https://packaging.python.org/en/latest/specifications/dependency-groups/).
- uv, [locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/),
  [GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/); Ruff,
  [the linter](https://docs.astral.sh/ruff/linter/).
- Scientific Python development guide: [style](https://learn.scientific-python.org/development/guides/style/),
  [pytest](https://learn.scientific-python.org/development/guides/pytest/),
  [coverage](https://learn.scientific-python.org/development/guides/coverage/).
- mypy, [using mypy with existing code](https://mypy.readthedocs.io/en/stable/existing_code.html);
  Meta, [Python typing survey 2025](https://engineering.fb.com/2025/12/22/developer-tools/python-typing-survey-2025-code-quality-flexibility-typing-adoption/).
- [import-linter](https://import-linter.readthedocs.io/en/stable/); [pip-audit](https://github.com/pypa/pip-audit);
  SonarSource, [Python test coverage](https://docs.sonarsource.com/sonarqube-cloud/enriching/test-coverage/python-test-coverage/).

**.NET.**
- Microsoft Learn: [central package management](https://learn.microsoft.com/en-us/nuget/consume-packages/central-package-management);
  [global.json](https://learn.microsoft.com/en-us/dotnet/core/tools/global-json);
  [local tools](https://learn.microsoft.com/en-us/dotnet/core/tools/local-tools-how-to-use);
  [code analysis](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/overview);
  [CA1707](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/quality-rules/ca1707);
  [auditing packages](https://learn.microsoft.com/en-us/nuget/concepts/auditing-packages).
- Microsoft Learn: [testing in .NET](https://learn.microsoft.com/en-us/dotnet/core/testing/);
  [unit testing best practices](https://learn.microsoft.com/en-us/dotnet/core/testing/unit-testing-best-practices);
  [migrating to Microsoft.Testing.Platform](https://learn.microsoft.com/en-us/dotnet/core/testing/migrating-vstest-microsoft-testing-platform);
  [code coverage](https://learn.microsoft.com/en-us/dotnet/core/testing/microsoft-testing-platform-code-coverage).
- xUnit.net, [Microsoft Testing Platform](https://xunit.net/docs/getting-started/v3/microsoft-testing-platform);
  [ArchUnitNET](https://github.com/TNG/ArchUnitNET).
- SonarSource, [.NET getting started](https://docs.sonarsource.com/sonarqube-cloud/analyzing-source-code/dotnet-environments/getting-started-with-dotnet),
  [.NET test coverage](https://docs.sonarsource.com/sonarqube-cloud/enriching/test-coverage/dotnet-test-coverage);
  [setup-dotnet](https://github.com/actions/setup-dotnet).

**TypeScript.**
- Node.js, [releases](https://github.com/nodejs/Release); pnpm, [supply-chain security](https://pnpm.io/supply-chain-security),
  [continuous integration](https://pnpm.io/continuous-integration), [audit](https://pnpm.io/cli/audit).
- typescript-eslint, [typed linting](https://typescript-eslint.io/getting-started/typed-linting),
  [dependency versions](https://typescript-eslint.io/users/dependency-versions),
  [performance](https://typescript-eslint.io/troubleshooting/typed-linting/performance);
  ESLint, [v10.0.0](https://eslint.org/blog/2026/02/eslint-v10.0.0-released/).
- Prettier, [install](https://prettier.io/docs/install); Biome, [v2](https://biomejs.dev/blog/biome-v2/);
  TypeScript, [TSConfig reference](https://www.typescriptlang.org/tsconfig/),
  [TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/).
- Vitest, [filtering](https://vitest.dev/guide/filtering), [reporters](https://vitest.dev/guide/reporters),
  [coverage](https://vitest.dev/guide/coverage); [State of JS 2025, testing](https://2025.stateofjs.com/en-US/libraries/testing/).
- [dependency-cruiser](https://github.com/sverweij/dependency-cruiser);
  SonarSource, [JavaScript and TypeScript test coverage](https://docs.sonarsource.com/sonarqube-cloud/enriching/test-coverage/javascript-typescript-test-coverage).
