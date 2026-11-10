import asyncio, json, time
from pathlib import Path
from unittest.mock import MagicMock

print("1. Importing...", flush=True)
from src.services.cognitive_search.search.erp_action_extractor import (
    build_form_fill_payload,
    extract_form_fields_if_needed,
    resolve_and_enrich_erp_action_schema,
)
print("2. Loading case...", flush=True)
case = json.loads(Path("tests/golden/cases.json").read_text(encoding="utf-8"))["cases"][0]

print("3. Calling resolve_and_enrich_erp_action_schema...", flush=True)
t0 = time.perf_counter()
res = resolve_and_enrich_erp_action_schema(
    query=case["query"],
    visible_fields=None,
    form_schema=case["form_schema"],
    erp_key=case["erp_key"],
)
print(f"4. Done resolve in {time.perf_counter()-t0:.2f}s -> schema len={len(res[1])}", flush=True)

fake_resp = MagicMock()
fake_resp.text = json.dumps({"batch_mode": False, "fields": {"SupplierID": "حسين"}, "rows": []})
mock_client = MagicMock()
mock_client.models.generate_content.return_value = fake_resp

async def run():
    print("5. Calling extract_form_fields_if_needed...", flush=True)
    out = await extract_form_fields_if_needed(
        gemini_client=mock_client,
        query=case["query"],
        visible_fields=res[0],
        form_schema=res[1],
    )
    print("6. Done extract:", out, flush=True)
    payload = build_form_fill_payload(out, res[2], page_id=res[3], document_name=res[4], schema=res[1])
    print("7. Done payload:", payload, flush=True)

asyncio.run(run())
print("8. Finished cleanly!", flush=True)

