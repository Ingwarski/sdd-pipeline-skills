# Product Idea Intake Adapter

Read only when orchestrating Phase 0 in DAS Forge. `to-product-idea` owns intent and the final artifact; this adapter contract owns visible and durable transport.

Product Idea Intake is a Product Creation Run, not a Feature Unit. It must appear in Mission Control as a dedicated foreground workspace with one current question, appropriate decision support, custom-answer controls, live draft preview, and decision coverage. A question may never exist only in terminal output or a hidden agent log.

Use `to-product-idea` as the sole owner of `docs/product-idea.md`. The DAS Forge `ProductIdeaIntake` runtime adapter owns durable session/draft state and the handoff receipt under `forge/intake/`. It must:

- emit and persist one typed `ProductIntentQuestion` at a time;
- project an unanswered material question as `Input needed`, not `Blocked` or an approval;
- keep each question on one relevant branch, cite its source basis or state its absence, and name affected artifacts/boundaries; include a recommendation and rationale for operator decisions, but keep behavioral research questions neutral;
- after the answer, play back the confirmed decision and consequences through the owning skill before resuming dependent nodes;
- show the exact pending request on the selected supported intake surface when it is not active; honor an explicit host/browser preference, otherwise use the external default browser; report an unavailable selected surface before changing transport;
- restore the current question, answers, draft version, assumptions, and decision branch after restart;
- resume automatically after each answer without a separate continuation command;
- never convert a timeout, silence, recommendation, or non-response into consent for material product intent;
- on an explicit creation/start request, including the original pipeline request, atomically create/version `docs/product-idea.md` when absent or confirmed intent/source notes changed; otherwise preserve its validated bytes, then hash it;
- write `forge/intake/product-idea-handoff.json` with at least intake/session ID, source mode, `working_language`, language-selection source, distinct product content locales, artifact path, content hash, answered decision IDs, assumptions, unresolved non-blocking questions, submission event, and timestamp.

`Create product idea and start SDD` is one supported start command. Preserve prior explicit start authorization in the submission event; require no magic phrase or repeated confirmation. Draft playback, answers, edits, resume and submission add no approval gate. Whole-design approval remains the sole normal approval for UI scope.

If a downstream owner discovers missing material product intent, suspend only the affected dependency branch, route one scoped question through the same intake UI, persist the answer, re-invoke `to-product-idea`, and invalidate only transitive dependents of the changed idea hash. Unrelated safe work may continue when ownership and dependencies remain unambiguous.
