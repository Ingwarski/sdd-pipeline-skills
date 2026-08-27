# Product Idea Intake Adapter

Read only when orchestrating Phase 0 in DAS Forge. `to-product-idea` owns intent and the final artifact; this adapter contract owns visible and durable transport.

Product Idea Intake is a Product Creation Run, not a Feature Unit. It must appear in Mission Control as a dedicated foreground workspace with one current question, its recommended answer and rationale, custom-answer controls, live draft preview, and decision coverage. A question may never exist only in terminal output or a hidden agent log.

Use `to-product-idea` as the sole owner of `docs/product-idea.md`. The DAS Forge `ProductIdeaIntake` runtime adapter owns durable session/draft state and the handoff receipt under `forge/intake/`. It must:

- emit and persist one typed `ProductIntentQuestion` at a time;
- project an unanswered material question as `Input needed`, not `Blocked` or an approval;
- ensure each question walks one relevant decision branch, includes a recommended answer and rationale, cites the source basis or states no source confirms it, and names the downstream artifacts or boundaries affected by a different answer;
- after the answer, play back the confirmed decision and consequences through the owning skill before resuming dependent nodes;
- route the operator's external default browser to the exact pending intake request when the intake surface is not active;
- restore the current question, answers, draft version, assumptions, and decision branch after restart;
- resume automatically after each answer without a separate continuation command;
- never convert a timeout, silence, recommendation, or non-response into consent for material product intent;
- after `Create product idea and start SDD`, atomically create or version `docs/product-idea.md` only when absent or confirmed intent changed, otherwise preserve the validated existing file byte-for-byte, then hash the final file;
- write `forge/intake/product-idea-handoff.json` with at least intake/session ID, source mode, `working_language`, language-selection source, distinct product content locales, artifact path, content hash, answered decision IDs, assumptions, unresolved non-blocking questions, submission event, and timestamp.

`Create product idea and start SDD` is the initial execution command, not an approval receipt. Draft playback, answering questions, editing prior answers, resuming intake, and submitting intent do not add approval gates. The only normal product-creation approval remains approval of the complete integrated design baseline.

If a downstream owner discovers missing material product intent, suspend only the affected dependency branch, route one scoped question through the same intake UI, persist the answer, re-invoke `to-product-idea`, and invalidate only transitive dependents of the changed idea hash. Unrelated safe work may continue when ownership and dependencies remain unambiguous.
