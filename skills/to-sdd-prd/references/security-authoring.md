# Security requirements during PRD authoring

Apply this procedure inside `to-sdd-prd` on initial authoring and relevant revisions. OWASP is the Open Worldwide Application Security Project; ASVS is its Application Security Verification Standard. This is a reviewed adaptation of OWASP's PRD procedure, licensed CC-BY-SA-4.0; see [source pins, changes and attribution](owasp/NOTICE.md).

This installed baseline authorizes routine protective requirements for the product's confirmed scope. It does not authorize new features, changed business intent, scans, production code, network testing, purchases, plugins or security services. Keep the existing FR/NFR and UC IDs, document structure, language, owners and approval boundaries. Write only `docs/prd.md`.

## 1. Establish scope and risk

Read the confirmed product idea and available independent evidence; do not require later context or architecture documents. For each material use case identify actors/privileges, valuable or sensitive data, externally supplied inputs, integrations and trust boundaries. Group shared concerns once and reference their IDs. Include malicious use and failure paths, not only the intended journey.

Choose a planning target before mapping controls:

- **ASVS 5.0.0 Level 2** is the baseline for production web/API products with accounts, customer data or consequential actions.
- **Level 1** needs an explicit low-impact, low-sensitivity rationale. Being internal, an MVP or represented by a mockup does not itself justify a downgrade; assess the intended production product.
- **Level 3** applies where the confirmed impact/adversary warrants higher assurance. Record feature-specific escalation without imposing unrelated controls on the whole product.
- For native/mobile, desktop, embedded or other non-web products, record an **adapted** scope, no ASVS assurance-level claim, relevant ASVS controls and additional platform-specific needs. ASVS alone is not complete coverage for every product type.

Record the target, rationale, assumptions, covered surfaces and exclusions in the PRD. Resolve material unknowns about roles, sensitivity, public access or risk acceptance through the existing product-idea question route. Do not invent regulatory obligations or present recommendations as confirmed facts.

## 2. Read applicable controls from the pinned catalog

Use the bundled [offline reader](../scripts/asvs.py), resolved from the real installed skill directory. It only reads reference data; Python 3.9+ is already a pipeline prerequisite. Use the detected Python 3 command on Windows as elsewhere.

```text
python3 /resolved/to-sdd-prd/scripts/asvs.py --list-chapters
python3 /resolved/to-sdd-prd/scripts/asvs.py --level 2 --chapters V6 V7 V8
python3 /resolved/to-sdd-prd/scripts/asvs.py --ids v5.0.0-8.2.2
```

Consider all 17 chapters for applicability; read the actual controls at the selected level and below for each applicable chapter, plus justified escalations. Work in small chapter groups instead of loading the whole catalog into every skill. For adapted scopes, inspect relevant controls across levels without claiming a level. Missing/corrupt references block the affected review; do not reconstruct control text or IDs from memory.

Use the catalog's chapter names: authentication is **V6**, sessions **V7**, authorization **V8**, and configuration **V13**. Do not reuse the original procedure's inconsistent chapter/example mappings. Cite exact existing IDs as `v5.0.0-8.2.2`; chapter references alone are not requirement mappings.

## 3. Turn gaps into product obligations

For each applicable control, determine whether the PRD already addresses it, needs clarification, lacks it, or has a justified exclusion. Record a compact coverage table using grouped controls/shared obligations where their applicability is identical. Account for excluded chapters once with a source-backed reason; do not duplicate every control for every feature.

Add or strengthen existing FR/NFR obligations with the affected UC/surface, security outcome, exact ASVS reference and observable acceptance criterion. Keep a shared control in one requirement and link all affected use cases. A security tag or section does not replace stable requirement IDs. Split independently testable obligations rather than hiding them behind one vague parent requirement.

If a control needs an unconfirmed user-facing capability, check whether an already-scoped provider supplies it; otherwise record the gap and return the scope decision to `to-product-idea`. Do not silently add the feature, waive the control, or mark the assessment complete while that material decision is unresolved. Unverified technical configuration alone remains an architecture decision, not proof of compliance.

Review relevant exposure, including:

- Injection, untrusted rendering/deserialization, file handling and server-side fetches; do not equate input validation alone with injection prevention.
- Authentication/recovery, sessions, server-side object/tenant authorization and privilege changes; hiding a button or using unguessable IDs is not authorization.
- Business-rule abuse, replay, concurrent actions, rate/resource limits and safe failure.
- Secrets, transport/storage protection, data minimization/retention and security logging without credential or unnecessary sensitive-data leakage.
- Dependency provenance, supported versions, vulnerability remediation ownership, secure configuration, and incident/credential-revocation expectations appropriate to the product.
- For AI/tool-enabled products, separate untrusted content from instructions, restrict tool authority and data access, validate outputs before side effects, and bound resource use. Label additional product/platform rules as supplemental; never invent ASVS IDs for them.

Require allowed and denied/adversarial acceptance outcomes, including the protected data or state and expected evidence. Choose mechanisms in architecture, actual tests in QA, and build tasks in the plan. Do not copy example rate limits, expiry times, stack choices or purchases as universal requirements. Unresolved security-critical parameters need an owner and resolution point before affected checks can be prepared.

Example: a private-document download must deny another user's or tenant's document even when its identifier is supplied directly, without returning protected content. Architecture selects enforcement; QA defines cross-user/tenant checks. Do not add a public-sharing feature to satisfy an example.

## 4. Finish the existing PRD

Keep a concise security scope/target, mapped security requirements and acceptance criteria, coverage/exclusion reasons, and unresolved gaps in this same document. Reuse equivalent localized headings. Put only implementation-relevant consequences beside a feature; do not paste the ASVS catalog or create a second security policy document.

Every applicable control must map to an obligation or a visible unresolved gap; do not silently waive requirements. Return a blocked assessment when material gaps prevent a usable specification. Routine protections do not add a human approval step. Risk-reducing changes are not permission to change confirmed product intent.

Validate identifiers with the catalog and return the [security record](../../to-sdd-pipeline/references/security-contract.md) to the caller. `complete` means requirements were assessed and specified, not that code is secure, tests passed, or ASVS compliance was achieved. The target level is not a certification. Plan product-specific follow-up for risks outside ASVS and ongoing maintenance.

## 5. Synchronize without restarting

On a change to actors, permissions, data, inputs/outputs, integrations, deployment exposure, dependencies, consequential actions or AI/tool authority, reassess affected use cases and shared controls. Preserve unchanged IDs and history. A material new product choice goes through the product-idea owner first; a design cannot silently redefine security behavior.

A purely visual change needs no PRD rewrite if these boundaries are unchanged. Reconcile affected UX/design owners and then architecture → DoD → QA → development plan. Changed requirements invalidate their old mappings and test evidence; visual-only revisions may retain unaffected security definitions. The caller tracks source hashes and requests only affected owner work.

For an existing PRD without this assessment, add the missing assessment through its owner before downstream advancement; preserve valid content and approvals. Do not fabricate a historical review. Production implementation still waits for a later explicit user prompt.
