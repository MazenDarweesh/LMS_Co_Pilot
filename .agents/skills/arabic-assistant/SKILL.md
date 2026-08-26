---
name: arabic-assistant
description: >
  Dual-purpose Arabic language assistant for the LMS Co-Pilot. Explains complex technical concepts in clear Arabic (architecture, ADRs, algorithms), AND validates Arabic text quality in Qdrant payloads and Gemini RAG responses. Activates for "اشرح لي", "Arabic QA", "text_msa check", or "hallucination audit".
---

# Arabic Assistant Skill (Unified)

Merged from two skills: `arabic-tech-explainer` (architectural explanations) and `arabic-content-qa` (RAG text validation).

---

## Mode 1: Tech Explainer (اشرح لي)

Use when the user asks "اشرح لي" or needs a breakdown of a complex architectural decision, algorithm, or ADR.

### Workflow

1. **Structure the Explanation** using 3 sections:
   - **المشكلة** (The Problem): What goes wrong without this pattern?
   - **الحل التقليدي** (The Naive Solution): The obvious but flawed approach.
   - **الحل الهندسي** (The Architecture Solution): The best practice used in this project.
2. **Use a Real-World Analogy** to explain algorithms or data flows (e.g., "HR resume screening" for Rerankers).
3. **Generate an Artifact** — output well-formatted Markdown to `understanding_[topic].md`.
4. **Tone**: Professional yet accessible Arabic. Keep technical terms (e.g., "Reranker", "Event Loop", "RRF") in English within the Arabic text.

### Decision Tree
- **Simple code snippet?** → Explain inline, don't use this skill.
- **Architecture, ADR, or core algorithm?** → Use this skill and generate an artifact.

---

## Mode 2: Arabic Content QA (RAG Text Validation)

Use when reviewing `text_msa` field quality in Qdrant, auditing Gemini hallucinations, or checking token efficiency in search traces.

### Input Sources
1. **Search trace files** in `downloads/search_debugs/` — check `text_msa` and `gemini_answer`
2. **Direct text** — paste Arabic text for assessment
3. **Qdrant payload inspection** — review `text_msa` field quality

### Check 1: MSA Cleanliness (Dialect Leakage Detection)

The `text_msa` field should contain Modern Standard Arabic (فصحى). Flag dialect markers:

| Dialect Word | Should Be | Severity |
|:-------------|:----------|:---------|
| ده / دي / دول | هذا / هذه / هؤلاء | ⚠️ High |
| مش / مفيش | لا / ليس / لا يوجد | ⚠️ High |
| عايز / عاوز | يريد / أريد | ⚠️ High |
| هيكون / هتكون | سيكون / ستكون | ⚠️ High |
| بتاع / بتاعت | خاص بـ / الخاص بـ | ⚠️ Medium |
| إزاي / ازيك | كيف | ⚠️ Medium |
| كمان / برضو | أيضاً / كذلك | ⚠️ Medium |
| اللي | الذي / التي | ⚠️ Low |

### Check 2: Hallucination Audit
Compare `gemini_answer` sentences against ALL `text_msa` fields in `reranker_results`.
- ✅ Grounded in chunk [N]: "..."
- ❌ NOT grounded — potential hallucination: "..."

### Check 3: Token Efficiency
- `total_tokens` > 2000 → ⚠️ Context bloat
- `prompt_tokens` > 1800 → ⚠️ Very large prompt — consider truncating `text_msa` to 500 chars max
- `completion_tokens` < 30 → ⚠️ Very short answer — may indicate insufficient context

### Output Format (Mode 2)

```
┌─────────────────────────────────────────────────────────────┐
│ Arabic Content QA Report                                    │
│ Query: "[query]"                                            │
├─────────────────────────────────────────────────────────────┤
│ 📝 MSA CLEANLINESS                                          │
│   Dialect markers found: X                                  │
├─────────────────────────────────────────────────────────────┤
│ 🔍 HALLUCINATION CHECK                                      │
│   Claim 1: "..." → ✅ Grounded in chunk [1]                 │
│   Claim 2: "..." → ❌ Not found in any chunk!               │
├─────────────────────────────────────────────────────────────┤
│ 💰 TOKEN EFFICIENCY                                         │
│   Total: XXX tokens  [✅/⚠️]                                │
└─────────────────────────────────────────────────────────────┘
```
