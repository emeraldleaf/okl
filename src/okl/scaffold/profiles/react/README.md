# React frontend profile

Portable React SPA canon, extracted verbatim from the .NET platform's `frontend/CLAUDE.md` (the .NET platform
storefront). **Backend-agnostic** — stack it onto any backend profile whose repo has a React frontend:

    okl scaffold --profile dotnet --profile react
    okl scaffold --profile python-rag --profile react

Installed to `.claude/rules/`:

- `frontend.md` — path-scoped to `frontend/**` and `**/frontend/**`: TanStack Query server state
  (useEffect-fetching banned), effects discipline ("You Might Not Need an Effect"), React-Compiler
  render/bundle perf (don't reflexively memoize; ≤200 KB gz budget), PKCE SPA auth + in-memory tokens
  (BFF trade-off documented), MSW + Playwright testing.

Reference stack: Vite + React 19 + TS strict, CSR SPA, TanStack Query/Router, Zustand, Tailwind v4 +
shadcn/ui, oidc-client-ts → Keycloak. Deep reference: the vendored `vercel-react-best-practices`
skill (70 rules), where the canon wins on any disagreement.
