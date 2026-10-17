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

## How the work runs

The main Codex or Claude Code agent runs this work when the user authorizes it. Architecture defines the supported environment, operational mechanisms and accountable roles. QA defines checks. The development plan assigns construction and verification to concrete units. Keep the actual project commands, tool operations, targets, prerequisites, success criteria and rollback triggers in the relevant project procedures and checks. Do not invent a universal deployment command or repeat the same procedure in several documents.

- **Release preparation:** read current implementation and acceptance evidence, run authorized readiness checks and report passed, blocked and untested items. Preparation does not itself authorize deployment or infrastructure changes.
- **Release:** after authorization covers the actual target and actions, use the documented project procedure and available tools. Check applicable backup and rollback prerequisites before consequential changes. Verify the actual deployed version, required product flows and operational signals, then record observations. A command returning success is not by itself a verified release.
- **Recovery:** follow the project's documented trigger, authorized recovery steps and data-integrity checks. Execute rollback or restore only within existing authority. Check the recovered state and record actual results. A written recovery plan or simulated test is not evidence of a real production recovery.
- **Maintenance:** when requested, inspect current dependencies, vulnerability information and operational evidence against the project's requirements. A review request authorizes review, not changes. Apply fixes only within the requested scope, then rerun affected checks and record results. Changed requirements return to their owners.

The agent verifies missing access or capabilities and follows project execution instructions for any pause. The user makes material product, access, spending and deployment decisions; the agent handles the authorized technical steps. Maintenance runs later only after a user request or through an explicitly authorized, configured and verified scheduled mechanism. A document does not create monitoring or schedule future work. If only SDD authoring was requested, these procedures remain prepared, not executed.

After release, actual user evidence, incidents and operational measurements return to the product-idea/PRD owner when intent or requirements change. The actual authorized executor owns deployment observations; authoring these records does not prove a successful release or restore. [NIST SSDF](https://csrc.nist.gov/projects/ssdf).
