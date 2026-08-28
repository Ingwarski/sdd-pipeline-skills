# Security traceability records

Product security obligations live in the PRD. Owners return this metadata; only the orchestrator records it in the existing manifest. References resolve exact, possibly localized headings in the owner's document. Existing artifact/source hashes bind these records; they are not another policy document or proof of security.

## PRD owner return

Return `security_review` on `artifacts.prd`:

```json
{
  "version": 1,
  "asvs_version": "5.0.0",
  "scope": "web-api",
  "level": 2,
  "status": "complete",
  "rationale": "Production service handling private customer documents.",
  "definition_ref": {"path": "docs/prd.md", "heading": "## Security Requirements"},
  "requirements": [
    {
      "requirement_id": "NFR-02",
      "definition_ref": {"path": "docs/prd.md", "heading": "### NFR-02"},
      "asvs_ids": ["v5.0.0-8.2.2"]
    }
  ]
}
```

Use actual existing IDs, not these example IDs. The canonical section states scope, target/rationale, control coverage, exclusions and open gaps. `status` is `complete | blocked`; unresolved material gaps block advancement. `web-api` requires level 1–3; `adapted` requires `level: null` and an explanation of non-web/platform coverage limits. Every product needs explicit protective obligations. Each requirement must resolve in its PRD section with its exact ASVS IDs. A supplemental rule may have `asvs_ids: []` only with a `rationale` stated in that section; never fabricate a control number.

## Downstream owner return

Architecture, DoD, QA and development plan each return `security_coverage`: an object mapping **every** current security requirement ID to an owned-document `definition_ref` shape, e.g. `"NFR-02": {"path": "docs/architecture.md", "heading": "## Access Control"}`. That section cites the ID and records the owner's local consequence: mechanism, gate, concrete check or work unit. Reuse existing records/headings; do not copy PRD definitions.

DoD defines the required, active `product_security_requirements` gate. The verification index records `security_requirement_ids` on this gate and each of its concrete QA checks. Their union covers every PRD security obligation. Bind real QA IDs only after QA authoring; no reverse dependency is added. Checks use `phase: implementation | both` and executed evidence includes `kind: security`; mockup-only evidence cannot satisfy product security. No applicable security obligation can be silently marked not-applicable or made advisory. Prepared checks remain `not_run`; release needs fresh passing evidence under the existing verification rules.

## Changes and limitations

Missing legacy records require the PRD/affected owner to assess and return them; never infer a past review from metadata. Do not reset documents, IDs, design history or approvals. Source changes revalidate affected records. Removed/changed obligations require explicit PRD reconciliation, not deletion from a downstream index. A design acceptance never waives security or releases implementation authorization.

The checker validates these records, real ASVS IDs and declared coverage. Semantic applicability, adequate control design and complete inventory remain the owner's responsibility. It performs no vulnerability scan or product tests. Standalone owners apply equivalent checks and report missing downstream work without creating a manifest.
