---
description: React storefront canon — server state, effects, render/bundle perf, SPA auth
paths: ["frontend/**/*.tsx", "frontend/**/*.ts", "**/frontend/**/*.tsx", "**/frontend/**/*.ts"]
---

# React canon (frontend SPA)

> Portable React rules, ported verbatim from the .NET platform's `frontend/CLAUDE.md` (the .NET platform
> storefront) — but backend-agnostic: stack these onto ANY backend profile (dotnet, python-rag, …)
> whose repo has a React frontend. Reference stack: Vite + React 19 + TypeScript (strict), CSR SPA;
> TanStack Query v5 + Router; Zustand (small UI globals only); Tailwind v4 + shadcn/ui; oidc-client-ts
> → Keycloak (auth-code + PKCE); React Compiler on. These rules are original to this kit;
> where you also consult an external React best-practices guide, **this canon wins where they disagree.**
>
> Where a rule cites "the backend" (VSA feature folders, server-controlled fields, cache-in-write-path,
> measure-before-optimizing), the parallel holds against whatever backend you pair this with.

## Architecture

- **Feature folders mirror the backend's VSA.** `src/features/<capability>/` owns its components, hooks, api calls, types. `src/shared/` is domain-agnostic; `src/core/` is singletons (query client, router, auth); `src/app/` is a thin shell — no business logic.
- **Feature boundaries are enforced, not conventional.** Features never import another feature's internals — only via its `index.ts` public API; `shared/` never imports from features. ESLint `import/no-restricted-paths` makes violations build errors.
- **Barrel files are intentional** — a feature's `index.ts` exports its public surface explicitly; everywhere else import directly (wildcard re-export barrels defeat tree-shaking).
- **Promotion to `shared/` requires proven reuse** (2–3 features independently need it). Speculative abstraction is the same dead weight as speculative interfaces in the backend.

## Server state (the biggest rule)

- **All server data flows through TanStack Query. Fetching in `useEffect` is banned** — hand-rolled effect-fetching badly reimplements dedup/caching/race-handling/retries the library gives you.
- **Query keys are a typed convention** `[feature, entity, params]` (e.g. `['catalog','products',{search}]`); key factories live in the feature's `api/` module.
- **Mutations invalidate (or update) their affected queries in the same mutation definition** (`onSuccess`), never "later" or via refetch-on-focus luck — the backend's "cache invalidation in the write path" rule, client-side.
- **Server data is never copied into `useState`** — render from the query result; copying makes a second source of truth that goes stale.

## Effects discipline ("You Might Not Need an Effect")

- **An Effect is only for synchronizing with an external system** (browser API, non-React widget, subscription). Everything else has a better tool: derived data → **calculate during render** (`useMemo` only if measured-expensive); reset-on-prop-change → **`key` prop**; "user did X" (POST/notify/navigate) → **event handler**, not an effect watching a flag; external store → **`useSyncExternalStore`**; state chains → compute in the handler; notify parent → call the callback in the handler or lift state up.
- **Effect dependencies are facts, not knobs.** Never lie to the dependency array to control *when* an effect runs — restructure instead. `eslint-plugin-react-hooks` `exhaustive-deps` is an error, not a warning.

## Render & bundle performance

- **Don't fight the React Compiler.** No reflexive `useMemo`/`useCallback`/`memo` — the compiler memoizes; manual memoization needs a profiler trace (the backend's "measure before optimizing"). Structural cases the compiler can't fix are still yours: don't define components inside components; hoist static JSX / default non-primitive props; functional `setState` for stable callbacks; refs for transient high-frequency values.
- **No request waterfalls on the critical path** — route loaders start queries before render; independent fetches run in parallel (`Promise.all` / parallel `useQuery`); Suspense streams what's ready. A fetch waiting on a render waiting on a fetch is the client-side N+1.
- **Route-level code splitting is the default**; heavy below-the-fold components via dynamic import; third-party scripts after hydration. **Initial bundle budget ≤ 200 KB gz, CI-checked.**
- **Virtualize lists past ~50 items.** **`startTransition`/`useDeferredValue` for non-urgent updates** (search-as-you-type) to keep input latency flat.

## Security

- **Auth flow: authorization code + PKCE, full stop.** The OAuth Browser-Based Apps BCP makes PKCE a MUST for SPA public clients and deprecates the implicit flow — no `response_type=token` anywhere.
- **Tokens live in memory (oidc-client-ts session), never `localStorage`** — XSS that reads storage steals tokens. **Documented trade-off:** the BCP ranks browser-held tokens as the least secure of its three patterns and recommends a BFF (tokens server-side, browser gets an HttpOnly cookie) for sensitive apps; acceptable here only because it's a demo storefront with fake data — if it ever fronts real user data, the BFF becomes the required shape.
- **Refresh tokens: rely on Keycloak's rotation** (BCP requires rotation/sender-constraining + bounded lifetime for SPA refresh tokens).
- **The client never computes or trusts money/authorization fields** — display what the server returns (backend's server-controlled-fields rule; the cart total is a preview, the authoritative total comes back from `POST /orders`).
- **No secrets in the bundle** — `import.meta.env` carries public config only.

## Testing & conventions

- **Test user-visible behavior, not implementation** — RTL queries by role/label; no testing hook internals or state shapes.
- **MSW mocks at the network boundary** — component/integration tests against mocked REST handlers per service (including error and slow cases).
- **Every feature ships happy path + error path + loading/empty state tests.** **Playwright E2E for the saga walk-through** runs against the real Aspire stack — regression gate and demo script both.
- Components `PascalCase.tsx`, hooks `useX.ts`, feature folders `kebab-case`, one component per file, named exports (default only where the router requires). TypeScript strict; no `any` (`unknown` + narrowing); API response types derived from backend DTO shapes.
