---
name: communications-audit
description: Audit sales and marketing communications and create a professional, modern DOCX consulting report using the seven dimensions Communicator, Audience, Desired Effect, Message, Channel, Timing, and Execution. Use for full-site or scoped website audits, landing pages, sales decks, proposals, one-pagers, brochures, email or outbound sequences, advertising, social content, scripts, audio, video, or mixed campaigns when the user wants evidence-led findings, a weighted effectiveness score, prioritized recommendations, rewritten examples, or a McKinsey-style communications review. Do not use for standalone SEO, AI-discoverability, accessibility, performance, legal, or security audits.
---

# Communications Audit

Produce an answer-first, evidence-led consulting report in editable `.docx` format. Use the user's seven-step Effective Communication method as the diagnostic spine while organizing the main narrative around business impact.

## Required References

Read these files before analysis:

1. `references/seven-step-framework.md` for the canonical dimensions, rubric, weights, and score calculation.
2. `references/report-contract.md` for evidence, severity, recommendation, research, report, and DOCX rules.
3. `references/artifact-modules.md`, then apply only the modules relevant to the audited material.

## Workflow

### 1. Ground the mandate

- Identify the communicator, intended audience, desired effect, audited materials, delivery channel, geography, language, and business context from supplied evidence.
- Inspect files, URLs, transcripts, repositories, analytics, and prior briefs before asking questions.
- If the audience or desired effect remains materially ambiguous, ask one question at a time. Include a recommended answer and its rationale. Do not finalize scoring until both are resolved.
- Use the requested report language. Otherwise match the dominant language of the audited material. Preserve source-language excerpts; translate proposed copy only when requested.
- Treat non-public supplied materials as confidential. They may be quoted or reproduced in the report because they were shared for audit, but never upload them to an external service without explicit permission.

### 2. Collect the evidence

- For a website, perform a full public same-domain crawl unless the user specifies a smaller scope. Use sitemaps and internal links; deduplicate canonical URLs and repeated templates. Exclude authenticated areas, query duplicates, search results, binaries, and technical archive/tag duplicates. Inventory the full crawl and audit representative examples of repeated templates.
- For files, inspect the complete relevant artifact rather than a convenient sample. For audio or video, inspect the media when available; otherwise use the supplied transcript and state that limitation.
- Prefer text evidence. Include screenshots or excerpts only when necessary to prove or explain a finding.
- Do not benchmark by default. If the user requests benchmarking, perform it and include a distinct, source-backed benchmarking section. Do not substitute current-context research for competitor benchmarking.
- When Timing is applicable, research the current market, industry, geography, season, news, labor, regulatory, or reputational context on the web. Use recent authoritative sources, record the as-of date, and cite every external claim. If current research cannot be completed, do not issue a confident Timing score.

### 3. Diagnose with the seven dimensions

- Apply all applicable dimensions in canonical order: Communicator, Audience, Desired Effect, Message, Channel, Timing, Execution.
- Choose the closest default weight profile, adjust it when the mandate requires, and disclose every final weight.
- Score each applicable dimension from 1 to 5 and assign High, Medium, or Low confidence. Tie every score to observed evidence.
- Mark Timing `N/A` only when it is genuinely irrelevant. Explain why and proportionally redistribute its weight across the other dimensions.
- Calculate the overall score exactly as specified in `references/seven-step-framework.md`. Never manipulate weights or confidence to improve the result.

### 4. Synthesize the answer

- Use answer-first consulting logic: conclusion, supporting findings, implications, and actions.
- Make findings mutually distinct and collectively cover the material issues. Do not force one finding per dimension; one finding may tag multiple dimensions.
- Distinguish direct observation, reasoned inference, unverified hypothesis, and external fact.
- Classify severity as Critical, Major, Moderate, or Minor using `references/report-contract.md`.
- Present at most seven prioritized recommendations by default. Include every Critical and Major issue even when that exceeds seven recommendations or the normal page budget.
- For each recommendation, state the evidence, commercial consequence, exact change, expected impact, effort, priority, owner, confidence, success metric, and a before/after example when useful.
- Preserve a coherent existing brand voice. If none is evident, use credible plain language. Never invent promises, proof, capabilities, testimonials, conversion lifts, revenue impact, baselines, or targets.
- Prioritize as Now, Next, or Later using impact, effort, confidence, and dependency.
- Flag likely SEO, AI-discoverability, accessibility, performance, legal, security, or other specialist issues only as out-of-scope follow-ups. Exclude them from the Communications Audit score.

### 5. Build the DOCX report

- Default to 5–10 pages. Expand only when the user requests depth or when all Critical and Major issues cannot be addressed responsibly within ten pages.
- Follow the standard report sequence in `references/report-contract.md`; compress sections onto shared pages rather than omitting them.
- Use the bundled `scripts/build_report.py` with a validated JSON content file:

```bash
python scripts/build_report.py --input <report.json> --output <report.docx>
```

- Use the authoritative bundled Python runtime discovered through the workspace dependency loader. Do not rely on the system Python.
- The generated report must be text-led, editable, restrained, and modern: navy, charcoal, white, one blue accent, generous spacing, clear takeaway headings, explicit table geometry, quiet page furniture, and limited visual evidence.
- Use a neutral `Communications Audit` identity unless auditor branding is supplied. The audited company's visual identity may appear as subject evidence, not as the report's author identity.

### 6. Verify before delivery

- Run the skill validator during skill maintenance and the builder's JSON validation for every report.
- Use the available `documents` skill to render the final DOCX to page PNGs with its canonical `render_docx.py` workflow.
- Inspect every rendered page at full size. Fix clipping, overflow, cramped tables, broken page breaks, inconsistent furniture, unresolved placeholders, or illegible visual evidence, then render again.
- Verify the score calculation, weights, severity coverage, current-context citations, recommendation count exception, source list, page count, and scope statement.
- Scrub personal document metadata before delivery when the required document tooling is available.
- Deliver only the final DOCX unless the user requests supporting files.

## Stop Conditions

Stop and state the exact blocker when:

- audience or desired effect remains materially unknown after inspection and the user has not answered;
- a private source would have to be uploaded externally without permission;
- an applicable Timing assessment cannot be supported by current research;
- the evidence is too incomplete to support a responsible score;
- DOCX generation or visual verification fails after reasonable repair attempts.
