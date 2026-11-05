"""
LMS Co-Pilot & ERP Agentic Services Root Package.
=================================================
Architecture: Pure Domain-Driven Architecture (Option A).
This root package encapsulates 5 isolated, specialized subsystems:

  1. cognitive_search: Hybrid vector retrieval, dense/sparse embeddings, caches, and RAG.
  2. audio_ingestion: Audio downloading, transcription, chunking, and normalization.
  3. erp_copilot: Autonomous ERP agent, CDP browser automation, forms catalog, and steering.
  4. lms_bridge: Secure integration client and content generation for .NET LMS.
  5. shared_infrastructure: Auth validator (Zero-Hop RBAC), structured logging, and feedback.
"""

__all__ = [
    "audio_ingestion",
    "cognitive_search",
    "erp_copilot",
    "lms_bridge",
    "shared_infrastructure",
]
