---
name: rag-debug-analyst
description: >
  Analyzes Hybrid RAG pipeline trace JSON files from downloads/search_debugs/.
  Use when the user wants to debug search quality, inspect reranker scores,
  identify duplicate Qdrant vectors by point_id, or diagnose latency bottlenecks
  across embedding / retrieval / reranker / Gemini stages.
---

# RAG Debug Analyst Skill

You are an expert RAG pipeline diagnostician for the LMS Co-Pilot system.
When activated, analyze search trace JSON files and produce a clear, structured report.

## Trace File Location

Search trace files are stored in:
```
e:\Mazen\EgyDynamic\LMS_CO_Pilot\downloads\search_debugs\search_YYYYMMDD_HHMMSS_*.json
```
Read the most recent file unless the user specifies another.

## JSON Schema — Know This Exactly

```json
{
  "timestamp": "ISO datetime",
  "query": "the user's Arabic query",
  "metrics": {
    "embedding_latency_ms": 634,
    "qdrant_latency_ms": 140,
    "reranker_latency_ms": 30995,
    "gemini_latency_ms": 2149,
    "total_latency_ms": 33921
  },
  "token_usage": {
    "prompt_tokens": 1132,
    "completion_tokens": 71,
    "total_tokens": 1384
  },
  "qdrant_rrf_candidates": [
    {
      "point_id": "UUID",
      "chunk_id": "UUID",
      "content_type": "video_chunk",
      "text_msa": "Arabic text...",
      "source_url": "https://youtu.be/..."
    }
  ],
  "reranker_results": [
    {
      "point_id": "UUID",
      "chunk_id": "UUID",
      "content_type": "video_chunk",
      "text_msa": "Arabic text...",
      "source_url": "https://youtu.be/...",
      "reranker_score": 0.9988
    }
  ],
  "prompt_sent_to_gemini": "Full Arabic prompt...",
  "gemini_answer": "Final Arabic answer..."
}
```

## Analysis Steps — Follow in Order

### Step 1: Latency Audit
Check each stage against thresholds:
| Stage | Field | Threshold | Status |
|:------|:------|:----------|:-------|
| Embedding | `embedding_latency_ms` | > 2000 = ⚠️ | |
| Qdrant | `qdrant_latency_ms` | > 500 = ⚠️ | |
| Reranker | `reranker_latency_ms` | > 5000 = ⚠️ (cold-start ~30s OK once) | |
| Gemini | `gemini_latency_ms` | > 10000 = ⚠️ | |

### Step 2: Token Usage Audit
- `total_tokens` > 2000 → flag as context bloat, recommend pruning low-score chunks
- `prompt_tokens` / `total_tokens` ratio > 0.9 → answer is very short relative to prompt

### Step 3: Duplication Detection
Compare `chunk_id` values across ALL entries in `qdrant_rrf_candidates`.
- If two entries share the same `chunk_id` but have different `point_id` → **DUPLICATE VECTOR DETECTED**
- List: duplicate `chunk_id`, both `point_id` values, recommend deleting the second one

### Step 4: Reranker Score Assessment
For each entry in `reranker_results`:
- `score > 0.9` → ✅ Highly relevant
- `0.3 ≤ score ≤ 0.9` → ⚠️ Acceptable
- `score < 0.3` → ❌ Poor match — should be filtered BEFORE sending to Gemini

### Step 5: Hallucination Spot-Check
Compare sentences in `gemini_answer` against `text_msa` content in `reranker_results`.
Flag any factual claim in the answer that cannot be traced to the retrieved chunks.

## Output Format — Always Use This Structure

```
┌─────────────────────────────────────────────────────────────┐
│ RAG Trace Analysis — [timestamp]                            │
│ Query: "[query]"                                            │
├─────────────────────────────────────────────────────────────┤
│ ⏱️  LATENCY BREAKDOWN                                       │
│   Embedding  : XXX ms  [✅/⚠️]                              │
│   Qdrant     : XXX ms  [✅/⚠️]                              │
│   Reranker   : XXX ms  [✅/⚠️]                              │
│   Gemini     : XXX ms  [✅/⚠️]                              │
│   ─────────────────────────────                             │
│   Total      : XXX ms                                       │
├─────────────────────────────────────────────────────────────┤
│ 💰 TOKEN USAGE                                              │
│   Prompt: XXX | Completion: XXX | Total: XXX  [✅/⚠️]       │
├─────────────────────────────────────────────────────────────┤
│ 🗑️  DUPLICATE VECTORS                                       │
│   [None found ✅] OR [chunk_id: X — point_ids: A, B ⚠️]    │
├─────────────────────────────────────────────────────────────┤
│ 🎯 RERANKER SCORES                                          │
│   [1] 0.9988 ✅ chunk_id: ...                               │
│   [2] 0.9988 ✅ chunk_id: ...                               │
│   [3] 0.0586 ❌ chunk_id: ... (below threshold!)            │
├─────────────────────────────────────────────────────────────┤
│ 🔍 HALLUCINATION CHECK                                      │
│   [Clean ✅] OR [Sentence "X" not grounded in chunks ⚠️]    │
└─────────────────────────────────────────────────────────────┘

📋 RECOMMENDATIONS:
1. ...
2. ...
```

## Decision Tree for Recommendations

- Duplicate vectors found → "Run Qdrant deduplication: delete point_id [X]"
- Reranker score < 0.3 → "Add score threshold filter in search_service.py (filter chunks before RAG prompt)"
- Reranker latency > 5000ms (not first call) → "Consider GPU acceleration or smaller reranker model"
- Token usage > 2000 → "Reduce top_n in reranker from current value, or truncate long text_msa fields"
- Hallucination detected → "Check normalizer output quality for this chunk, possibly re-index"

## Qdrant REST API Reference (via `fetch` MCP)

You can use the `fetch` MCP server to query Qdrant directly at `http://localhost:6333` if you need to fetch live data or delete duplicates.

**Query Points (Count/Search):**
```bash
POST http://localhost:6333/collections/<collection_name>/points/scroll
Content-Type: application/json

{
  "filter": {
    "must": [
      {
        "key": "source_url",
        "match": {
          "text": "<video_id>"
        }
      }
    ]
  },
  "limit": 10
}
```

**Delete Points:**
```bash
POST http://localhost:6333/collections/<collection_name>/points/delete
Content-Type: application/json

{
  "points": ["<duplicate_point_id>"]
}
```
