---
description: Conventions for <AREA> — loaded only when the agent touches matching files.
paths:
  - "<<FILL: glob, e.g. **/*.sql or src/payments/**>>"
---

# <AREA> rules (path-scoped — surface 2, lazy-loaded)

<!-- This is a TEMPLATE for a path-scoped rule file. Copy it per area, set `paths:`, keep it short.
     The point of path-scoped rules is that CLAUDE.md stays lean: rules load into context ONLY when
     the agent is working on files that match the glob. Target ~30–60 lines each.

     Example (delete and replace):

     # Database rules (paths: **/*.sql, **/migrations/**)
     - Every migration is reversible; ship the down-migration in the same PR.
     - No `SELECT *` in application queries; name columns so a schema change breaks loudly.
     - Money is DECIMAL, never float; never round in the DB layer.
-->

- <<FILL: rule 1>>
- <<FILL: rule 2>>
