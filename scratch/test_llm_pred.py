import asyncio
import json
from src.services.cdp_agent_service import cdp_agent_service
from src.services.vision_grounding_service import vision_grounding_service

async def test_llm():
    tab = await cdp_agent_service.get_active_erp_tab(port=9222, host="https://ppbpzkns-9222.eun1.devtunnels.ms")
    ws_url = tab.get("webSocketDebuggerUrl")
    
    # 1. Reset to dashboard
    await cdp_agent_service.evaluate_script(ws_url, "window.location.href = 'http://localhost:4200/core'")
    await asyncio.sleep(2.5)

    vp = await cdp_agent_service.get_viewport_metrics(ws_url)
    ss = await cdp_agent_service.capture_screenshot(ws_url)
    
    pred = await vision_grounding_service.predict_next_action(
        screenshot_b64=ss,
        goal="اذهب للموردين والمشتريات",
        history=[],
        viewport_metrics=vp
    )
    print("LLM Prediction:", json.dumps(pred, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(test_llm())
