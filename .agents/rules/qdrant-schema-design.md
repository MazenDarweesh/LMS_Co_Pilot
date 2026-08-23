# Rule: Qdrant Flat Payload Schema

When designing Qdrant vector schemas for hierarchical content (like an LMS) in this workspace:
- ❌ NEVER use separate collections for different levels (e.g., `modules_collection`, `lessons_collection`).
- ✅ ALWAYS use a single flat collection with a rich, nullable payload schema.
- ✅ ALWAYS use `is_tenant=True` on the most frequently filtered identifier (e.g., `lesson_id`, `tenant_id`) to optimize HNSW traversal.
- ✅ Include a `content_type` field (e.g., `lms_lesson`, `playlist_video`) to distinguish between structured hierarchy and standalone items.
