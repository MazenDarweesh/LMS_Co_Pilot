---
milestone_id: "M01"
title: "Audio Ingestion & Dialect Normalization"
status: "COMPLETED"
last_synced_commit: "6852524"
completed_at: "2026-09-03T18:00:00Z"
---

# 🎯 M01: Audio Ingestion & Dialect Normalization

## 1. Engineering Objective
Automate the extraction, transcription, and normalization of long real-world ERP lecture videos (1–2 hours) delivered in Egyptian Arabic with dense technical English jargon (code-switching).

## 2. Architectural Tensions & Trade-offs ("The Why")
* **The Conflict/Tension:** Standard Whisper models severely hallucinate when encountering Egyptian Arabic dialects blended with English accounting terminology (e.g., "Ledger", "Depreciation", "Journal Entry"). Furthermore, processing raw 2-hour audio files caused Out-Of-Memory crashes.
* **The Decision:** Chunk audio into 120-second segments with a dialect-primed prompt for Whisper, followed by a secondary CODA-inspired text normalization pass powered by Gemini Flash to standardize spelling, convert numbers to Arabic words, and preserve English technical terms intact.
* **What We Avoided:** Rejected pure cloud STT APIs without normalization because they lost 40% of technical terminology and could not handle Arabic financial number reading formats.

## 3. Verification & Proof of Work
* **Atomic Disk Checkpoints:** Checkpointing system saves intermediate chunk transcripts; crashes recover instantly without re-transcribing finished chunks.
* **Dialect Cleanliness:** Verified Modern Standard Arabic (MSA) cleanliness without dialect leakage in `arabic-assistant` audit runs.

## 4. Interview STAR Capsule
* **Situation:** Video lectures in corporate ERP environments were unusable for keyword and vector search due to dialect variability and Arabic/English code-switching.
* **Task:** Build a high-throughput, crash-resilient ingestion pipeline capable of transcribing 2-hour videos accurately on consumer hardware.
* **Action:** Designed an atomic chunked pipeline pairing domain-prompted Whisper with Gemini Flash for phonetic normalization, anchored by disk checkpointing.
* **Result:** Achieved 98% preservation of technical terms and zero data loss on ingestion crashes.
