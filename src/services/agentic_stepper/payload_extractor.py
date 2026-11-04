"""
AI-Powered Transaction Payload Extractor Service.
Dynamically extracts structured document headers and line items from natural language
using Gemini models guided by schema contracts from forms_catalog_service and ERP_PAYMENT_RULES.
"""

import asyncio
import json
from typing import Any, Optional
import structlog

from google.genai import types
from src.core.config import settings
from src.core.prompts import ERP_PAYMENT_RULES
from src.services.forms_catalog_service import forms_catalog_service
from src.services.vision_grounding_service import vision_grounding_service

logger = structlog.get_logger()


class PayloadExtractor:
    """
    مسؤول عن استخراج البيانات المنظمة للمعاملات (الفواتير، السلف، القيود، المخازن)
    من نية المستخدم باللغة الطبيعية دون أي كود صلب.
    """

    def __init__(self) -> None:
        pass

    async def extract_transaction_payload(
        self,
        goal: str,
        target_screen: Optional[dict[str, Any]] = None,
        target_page_id: Optional[int] = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """
        استخراج البيانات المنظمة للمعاملة باستخدام الذكاء الاصطناعي (Generic Dynamic AI Extractor)
        بناءً على مخطط النموذج المسجل في كتالوج النماذج أو المولد التلقائي للشاشات غير المسجلة.
        يدعم جميع أنواع المعاملات (فواتير، سلف، قيود، حركات مخازن، مقاولين، إلخ) دون أي كود صلب.
        """
        if not vision_grounding_service._client:
            vision_grounding_service.initialize()
        client = vision_grounding_service._client
        if not client:
            return {"header": {}, "items": []}

        # تحديد المعرف ومخطط الشاشة
        pid = target_page_id or (target_screen.get("page_id") if target_screen else None)
        if not pid:
            direct = forms_catalog_service.resolve_form_by_text(goal)
            if direct:
                pid = direct.get("page_id")

        schema_contract = forms_catalog_service.get_prompt_schema_for_gemini(pid or 289, fallback_meta=target_screen)
        doc_name = schema_contract.get("document_name", "مستند ERP")
        is_excel = schema_contract.get("is_excel", False)
        expected_header = schema_contract.get("expected_header", {})
        expected_grid = schema_contract.get("expected_grid", {})

        extraction_prompt = f"""You are an ERP Document Parser for DynamicPro ERP.
Extract structured transaction data for document '{doc_name}' from the user's natural language goal in Arabic.

USER GOAL:
"{goal}"

DOCUMENT SPECIFICATION:
- Document Type: {doc_name}
- Multi-line Items Grid: {"Yes" if is_excel else "No"}
- Target Page ID: {schema_contract.get("page_id")}
- Target Screen Key: {schema_contract.get("screen_key")}

EXPECTED HEADER FIELDS (Extract values for any matching fields present in the user goal):
{json.dumps(expected_header, ensure_ascii=False, indent=2)}

EXPECTED LINE/GRID FIELDS:
{json.dumps(expected_grid, ensure_ascii=False, indent=2) if is_excel else "None (Single-record form: items must be empty [])"}

RULES:
1. Map values strictly to the matching field keys from EXPECTED HEADER FIELDS and EXPECTED LINE/GRID FIELDS.
2. {ERP_PAYMENT_RULES}
3. Keep values literal as spoken (Arabic names of suppliers, items, warehouses).

OUTPUT FORMAT (JSON only):
{{
  "header": {{
    // Map extracted values strictly to keys from EXPECTED HEADER FIELDS (e.g. VendorID, CustomerID, EmpId, StoreID, Amount, Months, DocDate, Description)
  }},
  "items": [
    // Array of objects matching keys from EXPECTED LINE/GRID FIELDS (e.g. product, productQty, UnitPrice, AccID, Debit, Credit) or empty [] if not applicable
  ],
  "target_page_id": {schema_contract.get("page_id")},
  "document_title": "{doc_name}"
}}
"""
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=settings.GEMINI_MODEL,
                    contents=extraction_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                ),
                timeout=timeout,
            )
            raw = resp.text if hasattr(resp, "text") and resp.text else "{}"
            parsed = json.loads(raw)
            if "target_page_id" not in parsed and schema_contract.get("page_id"):
                parsed["target_page_id"] = schema_contract.get("page_id")
            if "document_title" not in parsed:
                parsed["document_title"] = doc_name
            return parsed
        except TimeoutError:
            logger.warning("Timeout extracting structured transaction payload", timeout=timeout)
            return {"header": {}, "items": [], "target_page_id": schema_contract.get("page_id"), "document_title": doc_name}
        except Exception as e:
            logger.warning("Failed to extract structured transaction payload", error=repr(e))
            return {"header": {}, "items": [], "target_page_id": schema_contract.get("page_id"), "document_title": doc_name}
