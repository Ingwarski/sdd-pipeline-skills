# Scope and portable execution

## Select the applicable work

The product-idea owner records confirmed scope once, under an existing/localized heading, with a small JSON block:

```json
{"profile":"new_product","capabilities":{"ui":true,"api":true,"persistence":true,"payments":false,"sensitive_data":true}}
```

Use actual capabilities, not this example. The orchestrator mirrors this object as `product_scope`, adding `definition_ref: {path, heading}`. The checker compares it with the canonical block. Missing legacy scope retains the full UI workflow; it never silently disables checks.

| Profile | Work |
|---|---|
| `new_product` | Existing full workflow; three equivalent-scope candidates and one integrated-design approval for UI products. |
| `existing_change` | Identify changed obligations and consumed inputs. Reuse current artifacts and approved baseline; reconcile affected owners only. If the approved design must change, use the existing candidate/revision process. |
| `headless` | `ui: false`; omit screen-map, wireframes, design-brief, prototypes and visual approval. Keep jobs, use cases, system/operator journey, architecture, security, DoD, QA and plan. Declare UI gates inapplicable with the source reference. |

Profiles change applicability, not authority. Headless delivery still requires the later implementation prompt, with an explicitly null baseline. When scope is declared, both that receipt and gate bind `product_scope_hash`: SHA-256 of `{profile, capabilities}` serialized with sorted JSON keys, separators `(',', ':')`, UTF-8. Changed scope invalidates prior authorization. Capabilities select security/lifecycle concerns, never waive them. Unknown or contradictory scope blocks affected work.

Early sketches and bounded feasibility experiments may resolve uncertainty before all documents exist. Keep them in `forge/exploration/`, label them unapproved/non-production and return findings to the owning specification. Do not connect live services, process real sensitive data, deploy or promote code without the necessary authority. Formal candidates still require their normal prerequisites.

## Direct Codex or Claude Code

No DAS Forge, Mission Control or external runner is required for SDD authoring. At entry the orchestrator identifies available files, terminal, browser, parallel workers and receipt/persistence support. Missing optional integrations do not block the portable path.

- The caller runs owner roles inline when dispatch tools are absent. Each role writes only its own artifact; the orchestrator alone updates `forge/sdd-manifest.json`.
- During intake the caller records draft, answered decision IDs/provenance, pending question, material gaps and last source hashes in `product_idea_intake` in that manifest. Do not publish a partial product-idea document. In standalone owner use, return this progress to the caller or retain it in the conversation; disclose when durable persistence is unavailable.
- Before dispatch, record a unique invocation ID, exact output set and consumed source hashes/fragments. After return, reject an unexpected invocation, changed source basis, wrong owner or output set. Retain older returns as history, never active evidence. Save manifest changes atomically and serialize its writers.
- New user messages update the active task. Stop obsolete work, reconcile only affected decisions and preserve still-valid authorization. The later implementation-prompt boundary remains the deliberate exception.
- Parallel workers receive bounded scopes, isolated outputs and source versions. Only independent ready work runs concurrently; the coordinator integrates and checks returns. Do not fabricate delegation when unavailable.
- The actual tool operator records browser observations, source-access results and original user events with tool/message identity, time and evidence. A narrative is not a tool receipt, and a file hash does not authenticate a person. Report missing provenance rather than inventing it.

Resume by checking current bytes, pending input and source versions, not merely a saved success flag. Continue safe authorized work; ask only when a material decision remains.

## Review surface and integrations

Preserve an explicit browser preference. `design_execution.review_surface` is `external_default` (existing default), `external_named` or `in_app`; record the user's chosen alternative. Browser receipts use the selected value as `browser_kind` and must describe an actual visible interactive review. Screenshots or headless automation alone do not prove that the user was shown the candidate.

An explicit whole-design decision in the active host conversation can approve the exact candidate; Codex is not a mandatory approval transport. Claude Design selection/export alone is still not approval. DAS Forge intake, Mission Control and Claude Design transport belong to their conditional adapters, not the portable core. If a requested adapter is unavailable, name the missing capability and ask before changing executors.

Production execution remains a separately authorized host/runner integration. This repository does not install or modify that runner and does not claim to enforce actions outside its checker.
