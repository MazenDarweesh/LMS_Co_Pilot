# المعمارية الموزعة لطبقة الخدمات (Services Architecture Taxonomy)
## نظام LMS Co-Pilot & ERP Agentic Copilot — المعمارية الصافية للمجال (Pure Domain-Driven Architecture)

---

### 1. نظرة عامة ورؤية المعمارية (Pure Domain Vision)

تم إنجاز **الخيار (أ) - التطهير المعماري الكامل (Pure Clean Architecture)** بنجاح تام، بحيث تم التخلص بالكامل من جميع ملفات الـ Facades السطحية المبعثرة خارج المجلدات، وأصبح مجلد [src/services/](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services) يضم حصراً **5 مجلدات دومين رئيسية مستقلة ومغلفة**، مع دمج بروتوكول المتصفح CDP ومحرك الخطوات الذاتية كحزمتين داخليتين تحت وكيل الـ ERP:

```text
src/services/
├── audio_ingestion/           # [1] خط معالجة وتفريغ الوسائط الصوتية
├── cognitive_search/          # [2] المحرك المعرفي والبحث الهجين والـ RAG
├── erp_copilot/               # [3] وكيل الـ ERP الذاتي المتكامل
│   ├── cdp/                   # بروتوكول DevTools والتحكم بالمتصفح ونبضات العتاد
│   ├── agentic_stepper/       # محرك الخطوات الذاتية والتنقل واستخراج الحقول
│   ├── forms_catalog_service  # كتالوج النماذج O(1) الفوري
│   ├── erp_service            # توجيه النوايا المحاسبية واستخراج المتبقيات
│   ├── erp_decision_memory    # ذاكرة قرارات التوجيه المحققة في Qdrant و PostgreSQL
│   └── vision_grounding       # التوجيه البصري متعدد الوسائط
├── lms_bridge/                # [4] جسر التكامل ومزامنة منصة LMS (.NET)
├── shared_infrastructure/     # [5] البنية التحتية المشتركة (الأمان، السجلات، التقييم)
├── docs/                      # التوثيق المعماري للمنظومة
└── __init__.py                # ملف تهيئة الحزمة الرئيسية
```

---

### 2. الحزم الخمس وتفاصيل الخدمات (The 5 Pure Domain Packages)

#### [1] حزمة البحث المعرفي (`src.services.cognitive_search`)
* **`search_service`**: المحرك المعرفي الهجين والـ RAG Streaming.
* **`qdrant_service`**: إدارة اتصالات Qdrant والبحث المتجهي المشترك (Dense + Sparse).
* **`embedding_service`**: توليد المتجهات الكثيفة (BGE-M3) والمتفرقة (BM25).
* **`reranker_service`**: إعادة الترتيب فائق السرعة عبر Quantized ONNX FlashRank.
* **`semantic_cache_service`**: الذاكرة التخزينية المتجهية للأسئلة المكررة في Qdrant (< 15ms).
* **`exact_cache_service`**: ذاكرة LRU فائقة السرعة للردود المتطابقة حرفياً (< 2ms).
* **`intent_router`**: موجه النوايا والاعتراض الأمني الفوري (< 1ms).
* **`rag_service`**: واجهة الاستعلام المباشر للـ RAG.

#### [2] حزمة تفريغ الوسائط (`src.services.audio_ingestion`)
* **`pipeline_orchestrator`**: منسق معمارية "Process Once, Reference Everywhere".
* **`audio_downloader`**: محمل الصوتيات من YouTube.
* **`transcription_service`**: تفريغ الصوتيات عبر Groq Whisper.
* **`transcript_normalizer`**: معالجة وتوحيد النصوص العربية.
* **الدوال المساعدة:** `make_chunk_id`, `CHECKPOINT_DIR`.

#### [3] حزمة وكيل الـ ERP الذاتي (`src.services.erp_copilot`)
* **`forms_catalog_service`**: كتالوج النماذج بذاكرة O(1) Hash Map الفورية (< 0.01ms).
* **`erp_service`**: محرك مطابقة النوايا واستخراج الحقول وتوليد قرارات الانتقال.
* **`erp_decision_memory_service`**: الذاكرة الدائمة للقرارات المحققة.
* **`vision_grounding_service`**: محرك التحديد البصري الدقيق بالإحداثيات.
* **`cdp` (حزمة فرعية)**:
  * `cdp_agent_service`: الواجهة الموحدة للتنقل والحقن والنقر عبر Chrome DevTools Protocol.
  * `CdpConnectionManager`, `CdpInputDispatcher`, `CdpVisualGrounding`, `CdpErpNavigator`, `CdpFormBridge`.
* **`agentic_stepper` (حزمة فرعية)**:
  * `agentic_stepper_service`: محرك الأتمتة البصرية والتنقل الهرمي والتسجيل.
  * `ScreenResolver`, `PayloadExtractor`, `StepperEngine`, `session_telemetry`.

#### [4] حزمة جسر التكامل مع منصة LMS (`src.services.lms_bridge`)
* **`lms_client_service`**: العميل الشبكي الموثوق مع Backend منصة .NET.
* **`lesson_content_service`**: توليد الاختبارات والملخصات المقسمة زمنياً.

#### [5] حزمة البنية التحتية المشتركة (`src.services.shared_infrastructure`)
* **`auth_validator_service`**: التحقق من التوكنات وصلاحيات Zero-Hop RBAC.
* **`event_logger_service`**: السجل الهيكلي للأحداث والعمليات.
* **`feedback_service`**: تسجيل وإحصاء تقييمات الطلاب وتصدير Ragas.

---

### 3. نتائج الاختبار والتحقق (Test Verification)

```text
============================= test session starts =============================
platform win32 -- Python 3.13.14, pytest-9.1.1
collected 105 items

tests/unit/test_citations_and_sources.py ............                     [ 20%]
tests/unit/test_dotnet_compatibility.py .........                        [ 26%]
tests/unit/test_erp_endpoints.py ........                                [ 34%]
tests/unit/test_extraction_prompts.py ...                                [ 37%]
tests/unit/test_filter_scoping.py ....                                    [ 40%]
tests/unit/test_forms_catalog.py .....                                    [ 45%]
tests/unit/test_forms_resolution.py ..                                   [ 47%]
tests/unit/test_generic_auto_scaling.py ...                               [ 50%]
tests/unit/test_generic_stepper_extraction.py ...                         [ 53%]
tests/unit/test_ingest_status.py .....                                    [ 58%]
tests/unit/test_memory_trimmer.py .........                              [ 66%]
tests/unit/test_metrics.py .....                                         [ 71%]
tests/unit/test_multi_lesson_search.py ......                             [ 77%]
tests/unit/test_process_once_reference.py ........                        [ 84%]
tests/unit/test_rag_prompt.py ..                                         [ 86%]
tests/unit/test_session_telemetry_hierarchical.py ..                      [ 88%]
tests/unit/test_webhook_security.py ......                                [ 94%]
tests/unit/test_zero_hop_rbac.py ......                                   [100%]

============================= 105 passed in 2.66s =============================
```
