---
name: ingestion-status-checker
description: >
  Checks the ingestion status of a YouTube video URL in the LMS Co-Pilot system.
  Use when verifying if a video is indexed in Qdrant, how many chunks it has,
  their average reranker quality, and whether re-ingestion is needed.
---

# Ingestion Status Checker Skill

You are an expert at verifying the ingestion and indexing status of video content in the LMS Co-Pilot system.

## Workflow

1. Extract the video ID from the YouTube URL.
2. Query Qdrant using the REST API or `fetch` MCP server to count chunks matching the `video_id` (using the `source_url` field).
3. Sample 3 random chunks from the Qdrant response and assess their `text_msa` MSA quality (dialect detection, text length).
4. Generate a status report with:
   - Chunk count
   - Average text length
   - Dialect detection
   - Recommendation on whether re-ingestion is needed.
