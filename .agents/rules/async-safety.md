# Rule: Async Safety

This rule is **always active**. Never introduce blocking calls inside async functions.

## Core Principle

FastAPI runs on an async event loop. Blocking that loop even for 1 second degrades
all concurrent requests. Every CPU-bound or I/O-bound call MUST be offloaded.

## Required Pattern

```python
# ✅ CORRECT — offload any blocking operation
result = await asyncio.to_thread(blocking_function, arg1, arg2)

# ✅ CORRECT — inline lambda for simple calls
data = await asyncio.to_thread(lambda: json.load(open(path)))
```

## Forbidden Direct Calls Inside `async def`

| Operation | Forbidden | Use Instead |
|:----------|:----------|:------------|
| ML model inference | `model.predict(...)` | `await asyncio.to_thread(model.predict, ...)` |
| File read/write | `open(...)`, `json.dump(...)`, `json.load(...)` | `await asyncio.to_thread(...)` |
| Sync HTTP | `requests.get(...)` | `httpx.AsyncClient` or `await asyncio.to_thread(requests.get, ...)` |
| Embedding generation | Direct `model.encode(...)` | `await asyncio.to_thread(model.encode, ...)` |
| Reranker scoring | Direct `cross_encoder.predict(...)` | `await asyncio.to_thread(cross_encoder.predict, ...)` |

## Project-Specific Examples

```python
# ✅ Correct — embedding service (already implemented)
dense_vec, sparse_vec = await embedding_service.get_both_embeddings(query)

# ✅ Correct — reranker (already implemented)
top_chunks = await reranker_service.rerank(query=query, passages=candidates, ...)

# ✅ Correct — debug file write (already implemented)
await asyncio.to_thread(_write_search_debug_file, query=..., ...)

# ❌ Wrong — never do this in an async function:
scores = self._model.predict(pairs)  # blocks event loop!
json.dump(data, f)                   # blocks event loop!
```

## Verification Checklist

Before committing any async function, verify:
- [ ] No `model.predict()` call without `asyncio.to_thread`
- [ ] No `open()` / `json.dump()` / `json.load()` without `asyncio.to_thread`
- [ ] No `requests.get()` — use `httpx.AsyncClient` instead
- [ ] All Qdrant calls use `AsyncQdrantClient` methods (they are already async)
