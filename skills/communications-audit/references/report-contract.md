# Report Contract

## Consulting narrative

Use an answer-first structure inspired by rigorous strategy-consulting practice:

- Lead with the conclusion and business consequence.
- Use takeaway headings that state a finding, not topic labels.
- Build a clear hierarchy from executive answer to supporting evidence to action.
- Keep findings mutually distinct and collectively sufficient for the mandate.
- Show what each observation means and what decision it changes.
- Prefer specific, plain language over jargon, slogans, or inflated claims.

Do not imitate proprietary templates, logos, or confidential methods of any consulting firm. “McKinsey-style” describes clarity, synthesis, evidence, prioritization, and executive usability.

## Evidence classes

Label or write each claim so its evidence class is unambiguous:

- **Observation:** directly visible in the supplied material or audited page.
- **Inference:** a reasoned conclusion from observations; state the reasoning.
- **Hypothesis:** plausible but unverified; name the test needed.
- **External fact:** supported by a cited, current source.

Never invent customer behavior, performance data, conversion lift, revenue impact, testimonials, product capabilities, baselines, targets, or benchmark figures.

## Severity

| Severity | Definition | Report treatment |
|---|---|---|
| Critical | Fundamentally misleads, contradicts, prevents comprehension/action, or creates severe credibility or trust damage. | Include and address before all other work. |
| Major | Materially damages audience fit, credibility, response, conversion, or continuity across the primary journey. | Include every Major finding. |
| Moderate | Meaningfully limits effectiveness but does not break the primary communication job. | Prioritize by impact and effort. |
| Minor | Local polish or optimization with bounded commercial effect. | Consolidate unless strategically useful. |

The main report contains no more than seven recommendations by default. If more than seven Critical and Major issues exist, include all of them and allow the report to exceed ten pages. Do not displace a Critical or Major issue with a lower-severity item.

## Recommendation fields

Every recommendation must include:

1. Takeaway title.
2. Severity and tagged seven-step dimensions.
3. Evidence and evidence class.
4. Commercial or communication consequence.
5. Exact recommended change.
6. Before/after copy or structure when useful.
7. Expected impact: High, Medium, or Low.
8. Effort: High, Medium, or Low.
9. Confidence: High, Medium, or Low.
10. Priority: Now, Next, or Later.
11. Likely owner.
12. Success metric.

Preserve a coherent brand voice. When it is absent, use direct professional language. Never improve persuasiveness by inventing proof or certainty.

## Prioritization

Use four factors:

- business impact;
- implementation effort;
- confidence in the diagnosis;
- dependencies or sequencing.

Translate them into:

- **Now:** urgent risk or high-impact, lower-effort action.
- **Next:** material improvement requiring coordination or prerequisite work.
- **Later:** strategic experiment, lower-confidence opportunity, or optimization after foundations are fixed.

## Benchmarking and research

- Benchmarking is off by default.
- If explicitly requested, include a named benchmarking section with comparators, criteria, evidence, limitations, and sources.
- Timing research is separate and mandatory whenever Timing is applicable.
- Prefer authoritative, primary, and recent sources. Record title, publisher, URL, publication date when available, and access date.
- Never cite a search-results page. Distinguish sourced facts from analyst inference.

## Specialist boundaries

This report scores communication only. Mention a likely SEO, AI-discoverability, accessibility, performance, legal, security, analytics, media-buying, or technical defect as a concise specialist follow-up when it affects the mandate. Do not analyze it deeply or include it in the Communications Audit score.

## Standard 5–10-page structure

Use this compressible backbone:

1. **Cover and mandate:** audited subject, client, auditor, date, scope, confidentiality.
2. **Executive answer:** one conclusion, overall score, top strengths, material risks, priority actions.
3. **Seven-step scorecard:** ratings, weights, confidence, and concise evidence.
4. **Priority findings:** evidence, implication, exact action, and optional before/after example.
5. **Action roadmap:** Now, Next, Later; owners and dependencies.
6. **Measurement plan:** 3–5 KPIs with definition, data source, cadence, owner, baseline, and target. Use `To establish` rather than invented values.
7. **Method, assumptions, sources, and specialist follow-ups.**

Sections may share pages. Use text as the default evidence form. Add screenshots or excerpts only when necessary to establish the finding. If the user supplies auditor branding, use it; otherwise use a neutral Communications Audit identity.

## DOCX content schema

Pass a UTF-8 JSON file to `scripts/build_report.py`. Required top-level keys are:

```json
{
  "metadata": {
    "client": "Example Client",
    "subject": "Website communications",
    "date": "2026-08-10",
    "auditor": "Communications Audit",
    "confidentiality": "Confidential",
    "language": "English",
    "scope": "Full public same-domain crawl",
    "accent_color": "#2E74B5",
    "auditor_logo_path": "Optional local image path",
    "auditor_logo_alt": "Optional logo alternative text"
  },
  "executive_summary": {
    "headline": "The offer is credible but the buyer must reconstruct why it matters",
    "conclusion": "One short answer-first paragraph.",
    "strengths": ["..."],
    "risks": ["..."],
    "priorities": ["..."]
  },
  "scorecard": [
    {
      "id": "communicator",
      "score": 3,
      "weight": 10,
      "confidence": "High",
      "rationale": "Direct evidence-based rationale.",
      "applicable": true
    }
  ],
  "current_context": {
    "applicable": true,
    "as_of": "2026-08-10",
    "summary": "Current conditions and why they change reception.",
    "sources": ["S1", "S2"]
  },
  "findings": [
    {
      "title": "Takeaway title",
      "severity": "Major",
      "steps": ["Audience", "Message"],
      "evidence_class": "Observation",
      "evidence": "What is visible and where.",
      "implication": "Why it matters.",
      "recommendation": "Exact change.",
      "impact": "High",
      "effort": "Low",
      "confidence": "High",
      "priority": "Now",
      "owner": "Marketing lead",
      "success_metric": "Qualified CTA completion rate",
      "source_ids": [],
      "before": "Optional current copy",
      "after": "Optional proposed copy",
      "image_path": "Optional local evidence image",
      "image_caption": "Optional caption"
    }
  ],
  "roadmap": {
    "now": [{"action": "...", "owner": "...", "success_metric": "..."}],
    "next": [],
    "later": []
  },
  "measurement": [
    {
      "metric": "Qualified CTA completion rate",
      "definition": "...",
      "data_source": "Analytics",
      "cadence": "Weekly",
      "owner": "Growth lead",
      "baseline": "To establish",
      "target": "To establish"
    }
  ],
  "benchmarking": {"requested": false, "summary": "", "comparators": []},
  "assumptions": ["..."],
  "specialist_followups": ["Run a separate technical accessibility audit."],
  "sources": [
    {
      "id": "S1",
      "title": "Source title",
      "publisher": "Publisher",
      "url": "https://example.com/source",
      "published": "2026-07-01",
      "accessed": "2026-08-10"
    }
  ]
}
```

The scorecard must contain all seven canonical IDs in order: `communicator`, `audience`, `desired_effect`, `message`, `channel`, `timing`, `execution`. Set `applicable` to `false` only for Timing. The builder validates the schema, recalculates effective weights and the overall score, and refuses unsupported recommendation counts or incomplete mandatory research.

## Visual and QA contract

- Use US Letter portrait, one-inch margins, Arial body type, a navy/charcoal/white palette with one blue accent, and restrained section furniture.
- Use real Word styles, numbering, headers, footers, and explicit fixed-width table geometry.
- Keep tables for actual comparison or repeated fields, not as containers for prose.
- Use a quiet running footer and a neutral report identity.
- Render every page to PNG and inspect it. Correct clipping, wrapping, sparse pages, split headings, broken tables, inconsistent fonts, and illegible evidence.
- Deliver the DOCX only unless the user asks for QA images or PDF.
