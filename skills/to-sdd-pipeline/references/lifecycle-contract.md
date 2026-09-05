# Risk-based delivery and operation

Use this checklist within existing documents, only for applicable product risks. It defines the handoff; it does not authorize deployment, scanning or production execution.

| Concern | Resolve where applicable |
|---|---|
| Delivery | Target environment, deployment verification, rollout/rollback criteria, compatible data migrations and irreversible-step authority. |
| Continuity | Availability/recovery objectives, backups, a restore test, degraded operation and data-integrity checks. |
| Operations | Useful telemetry without secrets, alert/incident owner, escalation, runbook and verification after recovery. |
| Maintenance | Supported runtime/dependency policy, vulnerability response, updates and end-of-life/data export/deletion. |
| Performance and cost | Source-backed latency/load/resource budgets, external-service limits and cost owner. Do not invent thresholds. |
| Product outcomes | Observable success signals, privacy-aware measurement, user-feedback/incident routing into changed requirements. |
| Content and reach | Content owner, localization, discoverability/SEO for public searchable surfaces, accessibility and retention obligations. |

Product idea establishes material goals/constraints; PRD owns required observable outcomes and FR/NFR clause IDs. Architecture resolves mechanisms, tradeoffs and operational owners. DoD defines readiness conditions; QA defines executable or named manual checks; the development plan allocates work, owners and those check IDs. Each owner references existing decisions rather than copying this table.

Record source-backed non-applicability or unresolved material targets at the appropriate owner. A local disposable tool does not need a production incident organization; a sensitive persistent service cannot silently omit restore or deletion planning. No extra approval gate or product document is added.

After release, actual user evidence, incidents and operational measurements return to the product-idea/PRD owner when intent or requirements change. The external executor owns deployment observations; authoring these records does not prove a successful release or restore. [NIST SSDF](https://csrc.nist.gov/projects/ssdf).
