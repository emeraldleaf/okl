# Set up a repository from scratch, so okl works at its best

Part of okl's documentation; the [README](../README.md) is the short version. [Getting
started](GETTING-STARTED.md) wires okl into a repository that already has its tooling. This
page starts from an empty folder, for Python, .NET or TypeScript, and builds what okl needs to
point at. That means a CI that gates every change, tests small enough to prove one claim each,
and code shaped so a lesson can watch the few files it is about. Then it seeds okl, names the
tools that pair with it, and shows how to prompt so the briefing finds what you need.

**What was tested.** Every gate in the tables below was run on a scratch repository per stack on
2026-11-01, as were the lesson checks, and the Python and .NET dependency audits also against a
package with a known vulnerability. The versions run were:
- uv 0.13.5 with Python 3.14;
- the .NET SDK 10.0.102;
- Node 22.22 with pnpm 11.3.

The CI workflows and the SonarQube steps were not run; they follow each tool's own documentation.
Every tool choice cites its sources at the end. Versions move: pin the current release of each
tool when you start, and let Dependabot move the pins.

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
- **A drift gate,** for the lessons CI does not already hold. When a file such a lesson governs
  changes, the push is held until its check passes again.

## What okl needs from your tooling

A lesson is proven by a command:

```bash
okl verify <id> --run "<command>" --expect "<text>"
```

It passes only when the command exits 0 **and** its output contains the expected text. The
command has 600 seconds by default (`--timeout` changes it). Four things follow:

- **Selectable.** A check runs one test, or one rule, by its exact name. A suite that takes
  minutes is CI's job, not a lesson's.
- **The text matters where exit 0 misleads.** A tool that fails with a non-zero exit cannot pass,
  whatever it prints. The expected text is what catches a run that exits 0 without doing what you
  meant: a selection that ran nothing, or more than you meant.
- **A tool that is silent on success.** ESLint and `tsc` print nothing when they pass. Give such
  a tool its own marker: `--run "<tool> && echo OK:lint" --expect "OK:lint"`.
- **An empty selection must not pass.**
  - pytest exits 4 for a test id that no longer exists, and 5 for a `-k` that matches nothing.
  - `dotnet test` exits 8 when its filter matches nothing.
  - Vitest exits 0, with every test skipped.

  The exit code catches the first two. Only the expected text catches Vitest's: okl refuses to
  stamp a check whose output lacks it.

**Which lessons get files.** A lesson's `files` are what drift watches. CI already runs your
tests, so a lesson whose check is a test in CI's suite needs no files:
- Record it without them (as a `Gate`), and prove it once with `okl verify`. The briefing shows
  it as proven, and CI runs its test on every change. okl does not re-run a lesson without files,
  so if you rename or delete that test, run `okl verify` again with the new one.
- Give `files` only to a lesson whose check CI does not run, such as a doc claim checked by a
  script, a pattern found by a grep, or a check too slow for CI. Drift then re-opens it when those
  files change ([Load your rules](LOAD-YOUR-RULES.md#1-decide-what-goes-where)).
- For those lessons, follow the commit order after changing a file they govern: commit the change,
  run `okl verify`, then commit the refreshed `okl-drift.json`
  ([Getting started](GETTING-STARTED.md#commit-in-this-order)).

## 1. Every stack: versions, CI, GitHub settings, SonarQube

**Versions.** Keep one home for versions, commit the lockfile, and pin every tool that gates CI
to an exact version. A range lets a release you never chose fail a branch that changed nothing.
Pin the runtime too: Python through uv, the .NET SDK in `global.json`, Node in `.node-version`.
Dependabot moves the pins in pull requests you review, once `.github/dependabot.yml` names each
ecosystem:

```yaml
version: 2
updates:
  - { package-ecosystem: github-actions, directory: "/", schedule: { interval: weekly } }
  - { package-ecosystem: uv, directory: "/", schedule: { interval: weekly } }       # Python
  - { package-ecosystem: nuget, directory: "/", schedule: { interval: weekly } }    # .NET
  - { package-ecosystem: dotnet-sdk, directory: "/", schedule: { interval: weekly } }
  - { package-ecosystem: npm, directory: "/", schedule: { interval: weekly } }      # pnpm too
```

Keep the lines for your stack.

**The CI workflow.** The workflows below follow GitHub's hardening guide:
- `permissions: contents: read` at the top;
- every action pinned to a full commit SHA, with its tag in a comment;
- a concurrency group, so a new push cancels the run it replaces.

The workflows show `<sha>` where the SHA goes. Copy each one from the action's release, and
Dependabot keeps them current from then on.

**GitHub settings, not code.** Turn these on in the repository's settings:
- Dependabot alerts;
- secret scanning with push protection;
- CodeQL's default setup, which needs no workflow file for these three languages.

They are free on public repositories. On private ones, secret scanning and CodeQL are paid
per active committer (GitHub Secret Protection and GitHub Code Security), so check GitHub's
current pricing. For a secret scan in CI that costs nothing, add the gitleaks binary from its
release page. Its README says it is feature complete and takes security patches only.

**SonarQube.** For a new repository, use SonarQube Cloud with **CI-based** analysis:
- **Turn automatic analysis off** in the project's settings. Cloud refuses a CI scan while it is
  on, and automatic analysis cannot import coverage, so the report your tests write would go
  unused.
- **Cost, as of 2026-11:** Cloud is free for public repositories. Private ones are free up to
  50,000 lines and five members, analysing only the main branch and pull requests into it. A
  self-hosted SonarQube Community Build is free, but analyses the main branch only.
- **Fork pull requests** have no secrets, so each workflow below skips the scan for them.
- **Settings:** each stack below gives its `sonar-project.properties`, or its scanner settings
  for .NET.
- **Make the quality gate a required check.**

## 2. Python

Tools: uv (environment and lockfile), Ruff (format and lint), mypy (strict), pytest, coverage.py,
import-linter (one-way imports). Sources disagree on one choice: Pyright is faster and is VS Code's
default, but mypy is the reference implementation and the most used checker, so it is the CI gate
here.

**Create it.**

```bash
uv init --lib my-service && cd my-service      # src/ layout, with py.typed
uv add --dev --bounds exact ruff mypy pytest coverage import-linter
mkdir -p src/my_service/domain src/my_service/infra
touch src/my_service/domain/__init__.py src/my_service/infra/__init__.py
```

`--bounds exact` writes `==` pins into `[dependency-groups]`, which never ship with the package.
Create the two layer packages before the first `lint-imports`, which errors on a layer that does
not exist. Add to `pyproject.toml`:

```toml
[tool.ruff.lint]
select = ["E", "F", "UP", "B", "SIM", "I"]   # add groups one at a time; "ALL" grows on every upgrade

[tool.mypy]
strict = true                                # a new repo has nothing to loosen
warn_unreachable = true
files = ["src", "tests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["-ra", "--import-mode=importlib"]  # no coverage flags here: see below
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

`sonar-project.properties`:

```properties
sonar.organization=<org>
sonar.projectKey=<key>
sonar.sources=src
sonar.tests=tests
sonar.python.coverage.reportPaths=coverage.xml
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

`uv export` pins every package with its hash, so `--disable-pip` lets pip-audit read the file as
it is, without building a virtualenv to resolve it. A known-vulnerable pin makes it exit 1.

**Coverage thresholds belong on the full suite.** If you set `fail_under`, run `coverage report`
only in the full-suite step. After a run of one test, `coverage report` exits 2 on coverage that
one test never meant to reach. The same goes for coverage flags in pytest's `addopts`.

A lesson's check, once okl is wired in (section 7). Its test runs in CI's suite, so the lesson is
recorded without files:

```bash
okl verify <id> --run "uv run pytest -q tests/test_pricing.py::test_total_refuses_a_discount_over_100_percent" --expect "1 passed"
```

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
        with: { fetch-depth: 0 }            # SonarQube reads the history for blame
      - uses: astral-sh/setup-uv@<sha>      # pin
        with: { version: "<exact>", enable-cache: true }
      - run: uv sync --locked               # fails on a stale lockfile
      - run: uv run ruff format --check . && uv run ruff check --output-format=github .
      - run: uv run mypy
      - run: uv run lint-imports
      - run: uv run coverage run -m pytest -q && uv run coverage xml
      - run: uv export --format requirements.txt --no-emit-project -o req.txt && uvx pip-audit==<exact> -r req.txt --disable-pip
      - uses: SonarSource/sonarqube-scan-action@<sha>   # pin
        if: github.event_name == 'push' || github.event.pull_request.head.repo.full_name == github.repository
        env: { SONAR_TOKEN: "${{ secrets.SONAR_TOKEN }}" }
```

Pre-commit hooks are optional. If you add them, keep them to `ruff check --fix` and
`ruff format`, and leave mypy and the tests to CI.

## 3. .NET

Tools: the .NET 10 SDK (the current LTS), central package management, the SDK's own analyzers,
`dotnet format`, xUnit v3 on Microsoft.Testing.Platform, ArchUnitNET, Microsoft's coverage
extension, NuGet Audit. Sources disagree on three choices:
- **Test framework.** MSTest is as defensible as xUnit v3; both run on the new test platform.
- **Architecture rules.** NetArchTest has more downloads, but no release since 2021, so this page
  uses ArchUnitNET.
- **SDK roll-forward.** Microsoft's `global.json` page calls a range "typical" for CI, and also
  recommends `disable` with lock files. This page uses `disable`, so a check always runs on the
  same toolchain. The cost is that every machine needs that exact SDK; `setup-dotnet` installs it
  in CI.

**Set the language first.** The SDK's and the test platform's summary lines are translated.
Put `DOTNET_CLI_UI_LANGUAGE=en` in CI's environment and in every lesson's check, or a check
written in English fails on a machine set to another language.

**Create it.**

```bash
dotnet new install xunit.v3.templates
dotnet new sln -n App                      # writes App.slnx
dotnet new editorconfig                    # then set insert_final_newline = true in it
dotnet new classlib -o src/App
dotnet new xunit3 -f net10.0 -o tests/App.Tests
dotnet new xunit3 -f net10.0 -o tests/App.ArchitectureTests
dotnet sln add src/App tests/App.Tests tests/App.ArchitectureTests
dotnet add tests/App.Tests reference src/App
dotnet add tests/App.ArchitectureTests reference src/App
dotnet new tool-manifest && dotnet tool install dotnet-sonarscanner --version <exact>
```

Three details in that block matter:
- **`-f net10.0`.** The `xunit3` template defaults to `net8.0`, whose support ends on
  2026-11-10, and a `net8.0` test project cannot reference the `net10.0` library.
- **`insert_final_newline = true`.** The `.editorconfig` template sets it to `false`, and then
  `dotnet format` fails on the templates' own files.
- **The tool manifest.** It lands in `dotnet-tools.json` at the repository root.

Then delete `TargetFramework`, `Nullable` and `ImplicitUsings` from each project, and the
`Version` from each `PackageReference`. The two files below set them once.

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

The projects then carry `<PackageReference Include="..." />` with no `Version`: both test
projects reference `Microsoft.Testing.Extensions.CodeCoverage`, and the architecture tests also
`TngTech.ArchUnitNET.xUnitV3`. Run `dotnet restore` once and commit the `packages.lock.json`
files it writes; from then on, `--locked-mode` fails a restore that would change them.

Test names in the `Method_Scenario_Expected` style that Microsoft's testing guidance recommends
break a CI build. `latest-recommended` turns on CA1707, which forbids underscores. Microsoft's
page for CA1707 says it is safe to suppress for test code, so add `tests/.editorconfig`:

```ini
[*.cs]
dotnet_diagnostic.CA1707.severity = none
```

An architecture rule is an ordinary test in its own project:

```csharp
using ArchUnitNET.Domain;
using ArchUnitNET.Loader;
using ArchUnitNET.xUnitV3;
using static ArchUnitNET.Fluent.ArchRuleDefinition;

namespace App.ArchitectureTests;

public class LayerTests
{
    private static readonly Architecture Arch =
        new ArchLoader().LoadAssemblies(typeof(App.Domain.Pricing).Assembly).Build();

    [Fact]
    public void Domain_DoesNotDependOn_Infrastructure() =>
        Types().That().ResideInNamespace("App.Domain").Should()
            .NotDependOnAny(Types().That().ResideInNamespace("App.Infrastructure")).Check(Arch);
}
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
| Dependency audit | `dotnet restore -p:AuditPipeline=true` | exit 0 |

Notes on these gates:
- **Filters.** Under the new test platform, xUnit filters with `--filter-method`,
  `--filter-class` and `--filter-namespace`. The old `--filter` syntax does not work.
- **An empty filter.** A filter that matches nothing prints `Test run summary: Zero tests ran`
  and exits 8.
- **The dependency audit.** A known vulnerability fails the audit restore as an error, from
  NU1901 (low) to NU1904 (critical), and exits 1. `dotnet package list --vulnerable
  --include-transitive` reports the same findings but exits 0 either way, so it cannot be the
  gate.

A lesson's check, once okl is wired in (section 7), takes a few seconds, build included:

```bash
okl verify <id> --run "DOTNET_CLI_UI_LANGUAGE=en dotnet test --project tests/App.Tests --filter-method '*.Total_DiscountOver100_Throws'" --expect "Test run summary: Passed!"
```

**CI.** SonarQube runs in its own job, because its scanner rebuilds the solution and overrides
`TreatWarningsAsErrors`, so it cannot double as the warnings gate.

```yaml
on: { push: { branches: [main] }, pull_request: {} }
permissions: { contents: read }
concurrency: { group: "${{ github.workflow }}-${{ github.ref }}", cancel-in-progress: true }
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
laptop.

## 4. TypeScript

Tools: Node's current LTS, pnpm, Prettier, ESLint with typescript-eslint, `tsc`, Vitest,
dependency-cruiser. Sources disagree on one choice: Biome is one fast tool for formatting and
linting. Its own preliminary testing found that its type-aware floating-promise rule catches about
75% of what typescript-eslint's does, so this page keeps ESLint and Prettier.

**Create it.**

```bash
mkdir my-service && cd my-service && git init
echo 26 > .node-version                 # the current LTS; match engines and @types/node to it
pnpm init
pnpm add -D -E typescript@6 eslint @eslint/js typescript-eslint prettier eslint-config-prettier \
  vitest @vitest/coverage-v8 dependency-cruiser @types/node@26
mkdir -p src/domain src/infra
```

`-E` writes exact versions. Pin TypeScript to 6.x for now. `pnpm add typescript` installs 7.0,
and typescript-eslint did not support it as of version 8.72 (2026-11-01). Set `"type":
"module"`, `"packageManager": "pnpm@<exact>"` and `"engines": { "node": ">=26" }` in
`package.json`.

`tsconfig.json` for a Node service. A React app uses `module: preserve`, `moduleResolution:
bundler`, `jsx: react-jsx` and the `dom` lib instead:

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

`eslint.config.js` is type-aware. Run Prettier on its own rather than through ESLint:

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

`.dependency-cruiser.cjs` holds the one-way rule. Keep `doNotFollow`, or the check walks into
`node_modules`:

```js
module.exports = {
  forbidden: [
    { name: "no-circular", severity: "error", from: {}, to: { circular: true } },
    { name: "domain-not-to-infra", severity: "error", from: { path: "^src/domain" }, to: { path: "^src/infra" } },
  ],
  options: { doNotFollow: { path: "node_modules" }, tsPreCompilationDeps: true, tsConfig: { fileName: "tsconfig.json" } },
};
```

`sonar-project.properties`. The tests sit beside the code, so tell SonarQube which files are
tests:

```properties
sonar.organization=<org>
sonar.projectKey=<key>
sonar.sources=src
sonar.exclusions=**/*.test.ts,**/*.test.tsx
sonar.tests=src
sonar.test.inclusions=**/*.test.ts,**/*.test.tsx
sonar.javascript.lcov.reportPaths=coverage/lcov.info
```

**The gates.**

| Gate | Command | Success text |
|---|---|---|
| Format | `pnpm exec prettier . --check` | `All matched files use Prettier code style!` |
| Lint | `pnpm exec eslint . --max-warnings 0 && echo OK:lint` | `OK:lint` |
| Types | `pnpm exec tsc --noEmit && echo OK:types` | `OK:types` |
| One-way imports | `pnpm exec depcruise src` | `no dependency violations found` |
| One test | `pnpm exec vitest run src/domain/pricing.test.ts -t '^total > refuses a discount over 100 percent$' --reporter=dot` | `1 passed` |
| Full suite, coverage | `pnpm exec vitest run --coverage --reporter=dot` | exit 0 |
| Dependency audit | `pnpm audit --prod --audit-level high` | `No known vulnerabilities found` |

Selecting one Vitest test takes three things:
- **A file path.** Give it with `-t`, or Vitest loads every test file.
- **An anchored pattern.** `-t` is a pattern over the test's full name, which joins the
  `describe` and test names with " > ". Unanchored, it matches every test whose name contains it,
  and the `Test Files  1 passed` line still matches "1 passed". So anchor it with `^` and `$`, or
  select the test by `file:line`.
- **A reporter.** Pass one explicitly, so the summary a check expects does not depend on how
  Vitest reads its environment.

A `-t` that matches nothing exits 0 with every test skipped and no "passed" anywhere, so the
expected text is what catches a renamed test. A lesson's check, once okl is wired in (section 7):

```bash
okl verify <id> --run "pnpm exec vitest run src/domain/pricing.test.ts -t '^total > refuses a discount over 100 percent$' --reporter=dot" --expect "1 passed"
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
        with: { fetch-depth: 0 }            # SonarQube reads the history for blame
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
        if: github.event_name == 'push' || github.event.pull_request.head.repo.full_name == github.repository
        env: { SONAR_TOKEN: "${{ secrets.SONAR_TOKEN }}" }
```

## 5. Tests that make good checks

A lesson is only as good as the check behind it.

- **One claim per test, named for the claim.** `test_total_refuses_a_discount_over_100_percent`
  reads like the lesson it proves. The lesson's check runs that one test, and since CI runs it
  too, the lesson needs no files.
- **Test the behaviour the lesson is about,** not that the suite is green. A lesson about a
  discount cap points at the test of the cap.
- **Fast and alone.** A check that needs a database, a network or the whole suite belongs in CI.
- **Guard the tests themselves.** In okl's own eval, the breaks that neither drift nor CI caught
  weakened a test or a stated contract rather than the code: a weakened test still passes
  ([REPORT §4ah](../evals/REPORT.md#4ah-the-watched-lessons-watch-what-they-claim-318-the-change-its-cost-and-the-re-run-registered-2026-11-01)).
  Review changes to the tests a lesson points at as carefully as changes to the code.
- **Keep thresholds on the full suite.** Coverage gates and timing budgets fail a one-test run
  for reasons that have nothing to do with the claim.
- **Architecture rules are checks too.** A one-way-imports contract or an ArchUnitNET test is the
  check for a lesson about layering. CI runs it, so that lesson needs no files either.

## 6. Shape the code so lessons can watch it

Most lessons in a repository built this way are held by CI. The rest, whose checks CI does not
run, are watched by drift through their `files`:

- **Small modules with one job.** A lesson that governs one or two files is re-checked only when
  they change. One that governs a folder is re-checked on every change there.
- **Watch what the claim depends on, and no more.** That can be a caller whose contract the lesson
  relies on, or the lockfile when a version matters. Every extra file adds re-checks.
- **Back doc claims with a check.** A README that documents a flag can carry a lesson whose check
  reads the README and the CLI. This is the typical lesson with files
  ([Getting started §3](GETTING-STARTED.md#3-put-your-docs-in-the-canon-so-they-cannot-drift-silently)).
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

- `--interests` takes your stack's tag, and init imports the bundled packs that match it (section
  8): `python`, `dotnet`, or `react` for a React app. A TypeScript service with no React has no
  stack pack yet.
- `--ci` adds okl's GitHub Actions drift workflow.
- `--git-hook` keeps the pre-push hook as well. It is the default only where that workflow is not
  installed, and it warns before CI does.
- When init finds Claude Code, it wires its hooks too.

Commit what it writes. If you leave out `--ci`, `okl verify` writes no `okl-drift.json`. To run
the drift gate in another CI system, run `okl export --drift` once and commit it.

The Claude Code commands this page names (`/record`, `/triggers`, `/seed-from-docs` and
`/seed-from-codebase`) come with okl's Claude Code plugin or with `okl scaffold .`, not with
`okl init`. Another agent can follow the same prompts, in `src/okl/scaffold/claude/commands/`.

## 8. Seed it

An empty store briefs nothing. Fill it in this order ([Seeding](SEEDING.md) has the detail):

1. **Your stack's packs.** `okl init` already imported the packs that match your interests,
   unless you passed `--no-seed`. `okl seed` lists every pack and marks the matching ones.

   | Stack | Packs |
   |---|---|
   | Python | `python-canon` |
   | .NET | `dotnet-canon`, `dotnet-decisions`, `dotnet-defects`, `dotnet-review-surfaces` |
   | React | `frontend-canon`, `react-defects` |

2. **Rules you already wrote.** Your rules files, ADRs, standards and specs become lessons that
   cite their source line ([Load your rules](LOAD-YOUR-RULES.md)). In Claude Code,
   `/seed-from-docs` proposes them; another agent can follow its prompt,
   `src/okl/scaffold/claude/commands/seed-from-docs.md`.
3. **What the code already enforces.** In Claude Code, `/seed-from-codebase` proposes lessons from
   your guard rails, CI and fix commits, each with a `file:line` citation.
4. **Triggers.** A lesson is found by the moments it applies to. `okl triggers` lists your
   lessons that have none. In Claude Code, `/triggers` drafts them for you to confirm.
5. **Prove what you can.**
   - A lesson whose check is a CI test gets `okl verify` once, and no files.
   - A lesson whose check CI does not run gets its `files` and `okl verify`, so drift watches it.

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
([Retrieval](RETRIEVAL.md)). "Fix the discount bug" says little. "Order totals accept a discount
over 100 percent" names the subject.

**Preview it.** `okl check --task "<your prompt>"` shows what the agent will be briefed on, before
you send the prompt.

**Read the marks.**
- **STALE:** the lesson's files changed since its check last passed. Run `okl reverify`.
- **UNVERIFIED:** the lesson governs files, but no check has passed yet. Prove it with `okl verify
  <id> --run "<check>" --expect "<text>"`.
- **UNPROVEN:** the lesson governs files, but no observed check backs its stamp. Prove it the same
  way.
- **UNCHECKED:** the lesson has no observed check behind it. Treat it as advice, and confirm it
  against the code before relying on it.

**Say what to remember.** "Remember: a discount is capped at 100 percent, tested in
`test_pricing.py`" is enough for the agent to record a lesson.
- In Claude Code the `/record` command drafts one from the session.
- Another agent calls the `okl_record` tool.
- Give each new lesson its trigger: the request or error that led to it is the best one.

**At the end of a session.**
- In Claude Code, the Stop hook asks once what was learned. Answer it, or say nothing new. It also
  runs `okl recap` on the session's transcript, listing the lessons the session was briefed on and
  those whose files it changed.
- With another agent, `okl recap --since 2h` lists the lessons whose files changed in that time,
  and `okl recap --report` summarises the session from the store's own logs.

**After changing code a lesson governs,** follow the commit order: commit, `okl verify`, commit
the snapshot. The pre-push hook holds the push until it is done.

**Now and then:**
- `okl doctor` reports what else is installed beside okl and where drift is gated.
- `okl metric` reports how often a known defect comes back after its lesson exists, and which
  lessons are never shown or most often shown unchecked.
- `okl triggers` lists lessons that cannot yet be found.

## Checklist

- [ ] Runtime pinned (`uv`, `global.json`, `.node-version`), lockfile committed, gate tools
      pinned exactly, `.github/dependabot.yml` for packages and actions.
- [ ] CI runs format, lint, types, tests with coverage, architecture rules and the dependency
      audit, with actions pinned by SHA, `permissions: contents: read` and a concurrency group.
- [ ] Repository settings: Dependabot alerts, secret scanning with push protection, CodeQL default
      setup.
- [ ] SonarQube Cloud with automatic analysis off, CI-based analysis, the coverage report path,
      fork pull requests skipped; quality gate required.
- [ ] Each lesson-worthy claim has one fast test, selectable by exact name, with a success line
      only success prints.
- [ ] okl wired (`okl init`), the pre-push hook in place, and the drift snapshot committed once a
      lesson with files is verified.
- [ ] Store seeded: stack packs, your own rules, triggers. Lessons held by a CI test are verified
      with no files; the rest have files and are verified.
- [ ] Prompts name their subject, the marks are read, and lessons are recorded as you learn.

## Sources

Read on 2026-11-01.

**All stacks.**
- GitHub, [Security hardening for GitHub Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions);
  OpenSSF Scorecard, [Pinned-Dependencies](https://github.com/ossf/scorecard/blob/main/docs/checks.md).
- GitHub, [About GitHub Advanced Security](https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security);
  [Configuring default setup for code scanning](https://docs.github.com/en/code-security/code-scanning/enabling-code-scanning/configuring-default-setup-for-code-scanning).
- SonarSource, [sonarqube-scan-action](https://github.com/SonarSource/sonarqube-scan-action);
  [subscription plans](https://docs.sonarsource.com/sonarqube-cloud/administering-sonarcloud/managing-subscription/subscription-plans);
  [automatic analysis](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/automatic-analysis).
- [gitleaks](https://github.com/gitleaks/gitleaks); [gitleaks-action](https://github.com/gitleaks/gitleaks-action),
  which needs a licence key for organisation accounts, hence the binary.

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
- [import-linter](https://import-linter.readthedocs.io/en/stable/); Kraken Technologies on running
  it across a large monolith, [EuroPython blog](https://blog.europython.eu/kraken-technologies-how-we-organize-our-very-large-pythonmonolith/).
- [pip-audit](https://github.com/pypa/pip-audit); SonarSource,
  [Python test coverage](https://docs.sonarsource.com/sonarqube-cloud/enriching/test-coverage/python-test-coverage/).

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
  [ArchUnitNET](https://github.com/TNG/ArchUnitNET); NuGet,
  [TngTech.ArchUnitNET](https://www.nuget.org/packages/TngTech.ArchUnitNET) and
  [NetArchTest.Rules](https://www.nuget.org/packages/NetArchTest.Rules) (release history).
- SonarSource, [.NET getting started](https://docs.sonarsource.com/sonarqube-cloud/analyzing-source-code/dotnet-environments/getting-started-with-dotnet),
  [.NET test coverage](https://docs.sonarsource.com/sonarqube-cloud/enriching/test-coverage/dotnet-test-coverage);
  [setup-dotnet](https://github.com/actions/setup-dotnet).

**TypeScript.**
- Node.js, [releases](https://github.com/nodejs/Release); pnpm, [supply-chain security](https://pnpm.io/supply-chain-security),
  [continuous integration](https://pnpm.io/continuous-integration), [audit](https://pnpm.io/cli/audit);
  GitHub, [npm v12 breaking changes](https://github.blog/changelog/2026-06-09-upcoming-breaking-changes-for-npm-v12/).
- typescript-eslint, [typed linting](https://typescript-eslint.io/getting-started/typed-linting),
  [dependency versions](https://typescript-eslint.io/users/dependency-versions),
  [performance](https://typescript-eslint.io/troubleshooting/typed-linting/performance), which
  advises running cycle checks outside ESLint; ESLint, [v10.0.0](https://eslint.org/blog/2026/02/eslint-v10.0.0-released/).
- Prettier, [install](https://prettier.io/docs/install); Biome, [v2](https://biomejs.dev/blog/biome-v2/);
  TypeScript, [TSConfig reference](https://www.typescriptlang.org/tsconfig/),
  [TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/).
- Vitest, [filtering](https://vitest.dev/guide/filtering), [reporters](https://vitest.dev/guide/reporters),
  [coverage](https://vitest.dev/guide/coverage); [State of JS 2025, testing](https://2025.stateofjs.com/en-US/libraries/testing/).
- [dependency-cruiser](https://github.com/sverweij/dependency-cruiser);
  SonarSource, [JavaScript and TypeScript test coverage](https://docs.sonarsource.com/sonarqube-cloud/enriching/test-coverage/javascript-typescript-test-coverage).
