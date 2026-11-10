"""ERP Form Action Intent Classifier, Schema Enricher, and Field Extractor."""
import asyncio
import json
import random
from typing import Any
import structlog
from google import genai
from google.genai import types

from src.core.config import settings
from src.core.prompts import (
    get_erp_form_extraction_prompt,
    get_erp_intent_classification_prompt,
)
from src.services.erp_copilot.forms_catalog_service import forms_catalog_service

logger = structlog.get_logger()

FORM_FILL_CONFIRMATION = (
    "تم تجهيز البيانات المطلوبة وهي جاهزة للإدخال في الشاشة النشطة عبر بطاقة الإجراء أدناه."
)

_SEMANTIC_LABEL_DEFAULTS = {
    "posetting": "طريقة الشراء",
    "contracttype": "طريقة البيع",
    "currancyid": "العملة",
    "currencyid": "العملة",
    "exchangeprice": "سعر الصرف",
    "exchangerate": "سعر الصرف",
    "safeaccounid": "الخزينة",
    "safeaccountid": "الخزينة",
    "safeaccount": "الخزينة",
    "costitemid": "مركز التكلفة",
    "projectid": "المشروع",
    "storeid": "المخزن",
    "supplierid": "المورد",
    "customerid": "العميل",
}


_TREASURY_FIELD_KEYS_LOWER = {
    "safeaccounid",
    "safeaccount",
    "safeaccountid",
    "خزينة",
    "الخزينة",
}


def _strip_total_from_treasury_fields(record: Any) -> Any:
    """Deterministic guard: removes disallowed `$TOTAL` values from treasury/safe dropdown fields."""
    if not isinstance(record, dict):
        return record
    cleaned: dict[str, Any] = {}
    for k, v in record.items():
        if str(k).strip().lower() in _TREASURY_FIELD_KEYS_LOWER and str(v or "").strip().upper() == "$TOTAL":
            logger.warning("Stripped disallowed $TOTAL value from treasury field in build_form_fill_payload", field=k)
            continue
        cleaned[k] = v
    return cleaned


def build_form_fill_payload(
    raw_extracted: Any,
    screen_key: str | None,
    page_id: int | str | None = None,
    document_name: str | None = None,
    schema: list[dict] | None = None,
) -> dict | None:
    """
    Normalizes the AI extraction result into the `form_fill` SSE payload.
    Returns None when nothing concrete was extracted (so the request falls back to plain RAG).
    The target screen is ALWAYS the active screen chosen by the AI router (no keyword inference).
    """
    if not raw_extracted or not isinstance(raw_extracted, dict):
        return None
    raw_fields = raw_extracted.get("fields") if isinstance(raw_extracted.get("fields"), dict) else {}
    raw_rows = raw_extracted.get("rows") if isinstance(raw_extracted.get("rows"), list) else []
    raw_batch = raw_extracted.get("batch_items") if isinstance(raw_extracted.get("batch_items"), list) else []

    fields_dict = _strip_total_from_treasury_fields(raw_fields)
    rows_list = [
        _strip_total_from_treasury_fields(r) if isinstance(r, dict) else r
        for r in raw_rows
    ]
    batch_items = []
    for item in raw_batch:
        if isinstance(item, dict):
            sanitized_item = {**item}
            if isinstance(item.get("fields"), dict):
                sanitized_item["fields"] = _strip_total_from_treasury_fields(item["fields"])
            if isinstance(item.get("rows"), list):
                sanitized_item["rows"] = [
                    _strip_total_from_treasury_fields(r) if isinstance(r, dict) else r
                    for r in item["rows"]
                ]
            batch_items.append(sanitized_item)
        else:
            batch_items.append(item)

    if not (fields_dict or rows_list or batch_items):
        return None

    # Check for missing required fields based on schema contract
    missing_required: list[dict[str, str]] = []
    if schema and isinstance(schema, list):
        extracted_keys = {str(k).strip().lower() for k in fields_dict.keys()}
        for sf in schema:
            if not isinstance(sf, dict):
                continue
            is_req = sf.get("required") is True or sf.get("is_required") is True
            section = sf.get("section")
            if is_req and section != "grid":
                f_key = str(sf.get("key") or sf.get("name") or "").strip()
                f_label = str(sf.get("label") or f_key).strip()
                if f_key and f_key.lower() not in extracted_keys:
                    missing_required.append({"key": f_key, "label": f_label})

    raw_action_intent = str(raw_extracted.get("intent") or "new").strip().lower()
    action_intent = raw_action_intent if raw_action_intent in ("new", "edit_current") else "new"

    payload: dict[str, Any] = {
        "intent": "form_fill",
        "action_intent": action_intent,
        "fields": fields_dict,
        "rows": rows_list,
        "screenKey": screen_key,
        "batch_mode": bool(raw_extracted.get("batch_mode", False)),
        "batch_items": batch_items,
        "missing_required": missing_required,
    }
    if page_id:
        payload["pageId"] = page_id
    if document_name:
        payload["documentName"] = document_name
    return payload


def build_schema_from_catalog(form_meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Synthesizes a standardized schema from catalog metadata for LLM extraction context."""
    schema: list[dict[str, Any]] = []
    # 1. Header fields
    headers = form_meta.get("header_fields") or form_meta.get("expected_header") or {}
    if isinstance(headers, dict):
        for key, val in headers.items():
            label = val.get("label_ar") if isinstance(val, dict) else str(val)
            ctrl = val.get("control_type", "input") if isinstance(val, dict) else "input"
            req_flag = val.get("is_required", False) if isinstance(val, dict) else False
            schema.append({
                "key": key,
                "name": key,
                "label": label or key,
                "type": ctrl,
                "required": req_flag,
                "section": "header",
            })
    elif isinstance(headers, list):
        for val in headers:
            if isinstance(val, dict):
                key = val.get("key") or val.get("name", "")
                label = val.get("label_ar") or val.get("label") or key
                ctrl = val.get("control_type", "input")
                req_flag = val.get("is_required", False) or val.get("required", False)
                schema.append({
                    "key": key,
                    "name": key,
                    "label": label,
                    "type": ctrl,
                    "required": req_flag,
                    "section": "header",
                })
    # 2. Grid fields
    grids = form_meta.get("grid_fields") or form_meta.get("expected_grid") or {}
    if isinstance(grids, dict):
        for key, val in grids.items():
            label = val.get("label_ar") if isinstance(val, dict) else str(val)
            ctrl = val.get("control_type", "input") if isinstance(val, dict) else "input"
            req_flag = val.get("is_required", False) if isinstance(val, dict) else False
            schema.append({
                "key": key,
                "name": key,
                "label": label or key,
                "type": ctrl,
                "required": req_flag,
                "section": "grid",
            })
    elif isinstance(grids, list):
        for val in grids:
            if isinstance(val, dict):
                key = val.get("key") or val.get("name", "")
                label = val.get("label_ar") or val.get("label") or key
                ctrl = val.get("control_type", "input")
                req_flag = val.get("is_required", False) or val.get("required", False)
                schema.append({
                    "key": key,
                    "name": key,
                    "label": label,
                    "type": ctrl,
                    "required": req_flag,
                    "section": "grid",
                })
    return schema


async def classify_form_action_intent(
    gemini_client: genai.Client | None,
    query: str,
    erp_intent: str | None = None,
) -> bool:
    """
    AI-only intent resolution (no keyword / regex lists):
    - If the AI navigation router already classified the message (`erp_intent`), reuse it — zero extra LLM calls.
    - Otherwise ask the lightweight AI classifier. On AI failure we do NOT guess: the message is treated as a
      plain question (no auto-fill), and the failure is logged.
    """
    if erp_intent in ("question", "navigate", "action"):
        return erp_intent == "action"

    q = query.strip()
    if not q:
        return False

    try:
        intent_prompt = get_erp_intent_classification_prompt(q)
        client = gemini_client or genai.Client(api_key=settings.GEMINI_API_KEY)
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=intent_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=32,
            ),
        )
        if resp and resp.text:
            detected = json.loads(resp.text).get("intent", "").lower()
            logger.info("AI intent classification result", detected=detected, query=q)
            return detected == "form_action"
    except Exception as e:
        logger.warning("AI intent classification failed; treating message as a plain question", error=str(e))
    return False


def build_extraction_response_json_schema() -> dict[str, Any]:
    """
    Constructs the Gemini `response_json_schema` contract enforcing structured
    `intent` (`new` | `edit_current`), `batch_mode`, `fields`, `rows`, and `batch_items`.
    Using `additionalProperties` avoids state-budget overflow and field recall collapse on
    wide ERP forms while keeping top-level intent & types strictly constrained.
    """
    scalar_or_null: dict[str, Any] = {"type": ["string", "number", "boolean", "null"]}
    record_obj: dict[str, Any] = {"type": "object", "additionalProperties": scalar_or_null}
    rows_arr: dict[str, Any] = {"type": "array", "items": record_obj}
    return {
        "type": "object",
        "required": ["intent", "batch_mode", "fields", "rows"],
        "properties": {
            "intent": {"type": "string", "enum": ["new", "edit_current"]},
            "batch_mode": {"type": "boolean"},
            "fields": record_obj,
            "rows": rows_arr,
            "batch_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fields": record_obj,
                        "rows": rows_arr,
                    },
                },
            },
        },
    }


def _strip_null_row_values(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            compact = {k: v for k, v in r.items() if v is not None}
            if compact:
                cleaned.append(compact)
    return cleaned


_EXTRACTION_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY_SEC = 1.5


def _is_transient_gemini_error(err: Exception) -> bool:
    """Returns True when Gemini fails with a transient 429/503/rate-limit/unavailable error."""
    code = getattr(err, "code", None) or getattr(err, "status_code", None)
    if code in (429, 503):
        return True
    msg = str(err).upper()
    return any(
        marker in msg
        for marker in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "HIGH DEMAND", "RATE LIMIT")
    )


async def extract_form_fields_if_needed(
    gemini_client: genai.Client | None,
    query: str,
    visible_fields: list[str] | None,
    form_schema: list[dict] | None = None,
) -> dict[str, Any]:
    """Extracts structured ERP form fields/rows from natural language using Gemini constrained JSON schema."""
    if not visible_fields and not form_schema:
        return {}
    try:
        fields_ctx = form_schema if form_schema else visible_fields
        fields_ctx_json = json.dumps(fields_ctx, ensure_ascii=False)
        prompt = get_erp_form_extraction_prompt(query, fields_ctx_json)
        response_json_schema = build_extraction_response_json_schema()
        candidate_models = list(dict.fromkeys([m for m in [settings.GEMINI_MODEL] if m]))
        client = gemini_client or genai.Client(api_key=settings.GEMINI_API_KEY)

        last_err = None
        for model_name in candidate_models:
            for attempt in range(_EXTRACTION_MAX_ATTEMPTS):
                try:
                    resp = await asyncio.to_thread(
                        client.models.generate_content,
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_json_schema=response_json_schema,
                            temperature=0.0,
                        ),
                    )
                    data = json.loads(resp.text)
                    if isinstance(data, dict):
                        raw_intent = str(data.get("intent") or "new").strip().lower()
                        norm_intent = raw_intent if raw_intent in ("new", "edit_current") else "new"
                        if "fields" not in data and "rows" not in data and "batch_items" not in data:
                            return {
                                "intent": norm_intent,
                                "batch_mode": False,
                                "fields": {k: v for k, v in data.items() if k != "intent"},
                                "rows": [],
                            }
                        data["intent"] = norm_intent
                        data["rows"] = _strip_null_row_values(data.get("rows"))
                        if isinstance(data.get("batch_items"), list):
                            for item in data["batch_items"]:
                                if isinstance(item, dict) and "rows" in item:
                                    item["rows"] = _strip_null_row_values(item.get("rows"))
                        return data
                    break
                except Exception as err:
                    last_err = err
                    if _is_transient_gemini_error(err) and attempt < _EXTRACTION_MAX_ATTEMPTS - 1:
                        delay_s = _RETRY_BASE_DELAY_SEC * (2 ** attempt) + random.uniform(0.15, 0.75)
                        logger.warning(
                            "Transient Gemini 429/503 during ERP extraction; retrying with exponential backoff",
                            model=model_name,
                            attempt=attempt + 1,
                            max_attempts=_EXTRACTION_MAX_ATTEMPTS,
                            delay_s=round(delay_s, 2),
                            error=str(err),
                        )
                        await asyncio.sleep(delay_s)
                        continue
                    logger.warning("Batch extraction attempt failed on model, trying next", model=model_name, error=str(err))
                    break

        if last_err:
            logger.error("All candidate models failed for ERP form extraction", error=str(last_err))
    except Exception as e:
        logger.error("Failed to extract ERP form data", error=str(e))
    return {}


def resolve_and_enrich_erp_action_schema(
    query: str,
    visible_fields: list[str] | None,
    form_schema: list[dict] | None,
    erp_key: str | None,
) -> tuple[list[str] | None, list[dict] | None, str | None, int | str | None, str | None]:
    """
    Resolves catalog metadata for the target ERP form and reconciles/enriches the live DOM schema
    so mismatched setup screens or unlabeled controls do not pollute AI field extraction.
    """
    effective_fields = visible_fields
    effective_schema = form_schema
    resolved_screen_key = erp_key
    resolved_page_id: int | str | None = None
    resolved_doc_name: str | None = None

    target_form = forms_catalog_service.resolve_form_by_text(query)
    if not target_form and resolved_screen_key:
        target_form = (
            forms_catalog_service.get_form_by_page_id(resolved_screen_key)
            or forms_catalog_service.get_form_by_screen_key(resolved_screen_key)
        )

    if target_form:
        resolved_page_id = target_form.get("page_id")
        resolved_screen_key = target_form.get("screen_key") or resolved_screen_key
        resolved_doc_name = target_form.get("name_ar") or target_form.get("document_name")

        catalog_schema = build_schema_from_catalog(target_form)
        if not effective_fields and not effective_schema:
            effective_schema = catalog_schema
            logger.info(
                "Resolved cross-screen form schema from catalog for compound intent",
                page_id=resolved_page_id,
                screen_key=resolved_screen_key,
                doc_name=resolved_doc_name,
                fields_count=len(effective_schema),
            )
        elif effective_schema and catalog_schema:
            live_keys = {
                str(f.get("key") or f.get("name", "")).strip().lower()
                for f in effective_schema
                if isinstance(f, dict)
            }
            cat_header_keys = set()
            headers = target_form.get("header_fields") or target_form.get("expected_header") or {}
            if isinstance(headers, dict):
                cat_header_keys = {str(k).strip().lower() for k in headers.keys()}
            elif isinstance(headers, list):
                for f in headers:
                    if isinstance(f, dict):
                        k = f.get("key") or f.get("name")
                        if k:
                            cat_header_keys.add(str(k).strip().lower())

            if cat_header_keys and not live_keys.intersection(cat_header_keys):
                effective_schema = catalog_schema
                effective_fields = None
                logger.info(
                    "Replaced mismatched DOM schema with authoritative catalog schema",
                    page_id=resolved_page_id,
                    doc_name=resolved_doc_name,
                )
            else:
                cat_label_map = {
                    str(cf.get("key") or cf.get("name", "")).strip().lower(): str(cf.get("label", "")).strip()
                    for cf in catalog_schema
                    if isinstance(cf, dict) and (cf.get("key") or cf.get("name")) and cf.get("label")
                }
                has_method_field = any(
                    str(f.get("key") or f.get("name", "")).strip().lower() in ("posetting", "contracttype")
                    for f in effective_schema
                    if isinstance(f, dict)
                )
                enriched_schema = []
                for f in effective_schema:
                    if not isinstance(f, dict):
                        continue
                    f_key = str(f.get("key") or f.get("name", "")).strip()
                    f_key_low = f_key.lower()
                    f_label = str(f.get("label", "")).strip()
                    if has_method_field and f_key_low in ("custom_select", "inserttype", "defultvalue") and (
                        not f_label or f_label.lower() == f_key_low
                    ):
                        continue
                    if not f_label or f_label.lower() == f_key_low:
                        enriched_label = cat_label_map.get(f_key_low) or _SEMANTIC_LABEL_DEFAULTS.get(f_key_low, "")
                        if enriched_label:
                            f = {**f, "label": enriched_label}
                    enriched_schema.append(f)
                effective_schema = enriched_schema

    return effective_fields, effective_schema, resolved_screen_key, resolved_page_id, resolved_doc_name


def build_action_guide_message(
    effective_schema: list[dict] | None,
    effective_fields: list[str] | None,
    resolved_doc_name: str | None,
    resolved_screen_key: str | None,
) -> str:
    """Builds the friendly Arabic action-mode guidance message when no field values were specified yet."""
    sample_labels: list[str] = []
    if effective_schema:
        for sf in effective_schema[:8]:
            if isinstance(sf, dict):
                lbl = str(sf.get("label") or sf.get("name") or sf.get("key") or "").strip()
                if lbl and lbl not in sample_labels:
                    sample_labels.append(lbl)
    elif effective_fields:
        sample_labels = [str(f).split("(")[0].strip() for f in effective_fields[:8] if f]

    fields_hint = f" (أبرز الحقول المتاحة: {'، '.join(sample_labels)})" if sample_labels else ""
    screen_label = resolved_doc_name or resolved_screen_key or "الحالية"
    return (
        f"⚡ أنت الآن في وضع التنفيذ المباشر على شاشة «{screen_label}»{fields_hint}. "
        "يرجى ذكر القيم المطلوب إدخالها (مثل اسم المورد/العميل، المخزن، الأصناف والكميات) وسأقوم بتعبئتها فوراً."
    )

