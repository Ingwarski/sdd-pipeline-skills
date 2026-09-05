# Structural traceability

Canonical decisions stay in their existing owner documents. Owners return a compact `traceability` projection; the orchestrator stores it on each artifact and sets `traceability_version: 1`. No new product document or approval is needed.

Each definition has `id`, `kind`, `required` (boolean), and `definition_ref: {path, heading}` into its owner's document. Excluded definitions need a source-backed `rationale`. Split compound FR/NFRs into observable clause IDs; a parent summary does not replace its clauses. Cross-cutting requirements may declare `cross_cutting: true` with the reason in the canonical requirement.

| Kind | Canonical owner |
|---|---|
| `job` / JOB-* | product idea |
| `use_case` / UC-*; `requirement` / FR-*, NFR-* and clause IDs | PRD |
| `surface`, `state` | screen map |
| `check` | QA checklist; same actual IDs as verification index |
| `unit` | development plan |

Each link has `from`, `to`, `relation`, and a `definition_ref` into the source ID's owner document. Its referenced section cites both IDs and explains the local consequence:

| Relation | Direction |
|---|---|
| `realizes_job` | use case → job |
| `specifies` | requirement → use case; cross-cutting obligations explicitly explain the exception |
| `supports` | surface → use case |
| `state_of` | state → surface |
| `verifies` | check → requirement clause or state |
| `implements` | unit → requirement clause or state |

Return `{"definitions": [...], "links": [...]}` using actual IDs. Empty lists are valid only where the owner's scope genuinely contains none; do not invent records to fill a template. Security requirements keep the same FR/NFR IDs in this index and the existing security projection, which adds ASVS-specific assurance rather than competing definitions.

The checker validates owner/type, canonical ID existence, resolvable relationships and coverage appropriate to the current stage. Required jobs need use cases; use cases need jobs and requirements; requirements/states need checks once QA exists and units once the plan exists. Later-stage mappings never become earlier prerequisites. Headless work has no UI surface/state obligations.

Missing legacy indexes require owner-reviewed migration. Keep document bytes, IDs, valid approvals and history; never invent old coverage. Mechanical checks cannot establish that an ID's description is adequate, all needed requirements were discovered, or a human observation is authentic. Review those separately.
