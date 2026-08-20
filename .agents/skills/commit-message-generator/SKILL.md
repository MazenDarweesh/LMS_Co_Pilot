---
name: commit-message-generator
description: >
  Generates a professional Git commit message for all staged or unstaged changes
  in the LMS Co-Pilot project. Use when the user asks for a commit message,
  "what should I write in git?", or "summarize my changes for git".
---

# Commit Message Generator Skill

You are a professional Git commit message writer for the LMS Co-Pilot project.
When activated, analyze all changes and produce a single, cohesive commit message.

## Workflow — Follow These Steps in Order

1. Run `git status` to identify all modified and untracked files
2. Run `git diff` to read the actual changes
3. Categorize each changed file by type and scope (see tables below)
4. Write a single commit message covering ALL changes
5. Present the message in a code block, ready to copy

## Commit Message Format

```
<type>(<scope>): <short imperative summary (max 72 chars)>

- <bullet: what changed and why — 1 sentence>
- <bullet: next change>
- <bullet: new files added or deleted>
```

## Type Reference

| Type | When to Use |
|:-----|:------------|
| `feat` | New feature or capability added |
| `fix` | Bug fix or error correction |
| `refactor` | Code restructured, no behavior change |
| `chore` | Config, dependencies, build files |
| `docs` | Documentation only |
| `test` | Test files added or modified |
| `perf` | Performance improvement |

## Scope Reference (Project-Specific)

| Scope | Files/Areas Covered |
|:------|:--------------------|
| `rag` | `search_service.py`, `rag_service.py`, RAG logic |
| `search` | Hybrid search pipeline, reranking, embedding |
| `qdrant` | `qdrant_service.py`, vector database operations |
| `embedding` | `embedding_service.py`, BGE-M3, BM25 |
| `auth` | `auth_service.py`, JWT, permissions |
| `ingestion` | `pipeline_orchestrator.py`, audio/transcript processing |
| `api` | `router.py`, endpoints, schemas |
| `infra` | `docker-compose.yml`, `Dockerfile`, `session.py` |
| `observability` | Debug trace files, logging, metrics |
| `agents` | `.agents/` skills, rules, MCP, hooks |

## Multi-scope Rule

If changes span more than 2 scopes, use the **primary scope** + mention others in bullets.

## Quality Rules

- ✅ Summary line: imperative mood ("add", "fix", "implement" — NOT "added", "fixed")
- ✅ Summary line: max 72 characters
- ✅ Body bullets: explain WHY, not just WHAT
- ✅ One commit message total — never split into per-file messages
- ❌ Never mention file paths in the summary line
- ❌ Never use vague summaries like "update code" or "fix stuff"

## Example Output

```
feat(rag): implement production-ready hybrid search pipeline with JSON trace observability

- Integrated BGE-M3 dense + BM25 sparse embeddings via get_both_embeddings() for async safety
- Added Qdrant RRF hybrid search with _qdrant_point_id injection for duplication auditing
- Injected _reranker_score into BAAI/bge-reranker-v2-m3 outputs for quality debugging
- Built per-stage latency tracking (embedding/qdrant/reranker/gemini) and token_usage extraction
- Automated JSON trace files written to downloads/search_debugs/ after every query
- Bumped Qdrant docker image v1.9.2 → v1.13.2 for full RRF API support
- Refactored rag_service.py as backward-compatible wrapper delegating to search_service
```
