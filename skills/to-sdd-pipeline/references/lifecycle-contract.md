# Risk-based delivery and operation

Use this checklist within existing documents, only for applicable product risks. It defines the handoff; it does not authorize deployment, scanning or production execution.

| Concern | Resolve where applicable |
|---|---|
| Delivery | Exact supported environment/version/use mode and required test combinations, deployment verification, rollout/rollback, compatible migrations and irreversible-step authority. |
| Continuity | Recovery, backup/restore, degraded operation and integrity. For local persistent data, distinguish application guarantees from platform inactivity/quota/eviction rules; use dated primary sources, actual environment and retention-mode outcomes. Qualify material limits and retained-backup recovery; simulated deletion proves recovery, not real platform retention. |
| Operations | Useful telemetry without secrets, alert/incident owner, escalation, runbook and verification after recovery. |
| Maintenance | Supported runtime/dependency policy, vulnerability response, updates and end-of-life/data export/deletion. |
| Performance and cost | Source-backed latency/load/resource budgets, external-service limits and cost owner. Do not invent thresholds. |
| Product outcomes | Observable success signals, privacy-aware measurement, user-feedback/incident routing into changed requirements. |
| Content and reach | Content owner, localization, discoverability/SEO for public searchable surfaces, accessibility and retention obligations. |
| Feasibility | Investigate uncertain required native/provider capabilities with a disposable non-production experiment before dependent construction. Record scope/authority, owner, exact environment, required outcome and evidence; starting an operation does not prove its outcome. Unavailable evidence remains an explicit prerequisite, not a presumed pass. |

Product idea/PRD own goals and clauses; architecture owns mechanisms, tradeoffs and operational roles. DoD defines readiness; QA owns checks. Planning gives each tested mechanism a construction owner, production paths, prerequisites, interface and construction checks, distinct from later qualification. Reference owned decisions rather than copying this table.

Record source-backed non-applicability or unresolved material targets at the appropriate owner. A local disposable tool does not need a production incident organization; a sensitive persistent service cannot silently omit restore or deletion planning. No extra approval gate or product document is added.

After release, actual user evidence, incidents and operational measurements return to the product-idea/PRD owner when intent or requirements change. The external executor owns deployment observations; authoring these records does not prove a successful release or restore. [NIST SSDF](https://csrc.nist.gov/projects/ssdf).
