import asyncio
import json
from src.services.cdp_agent_service import cdp_agent_service

async def test_interactive():
    tab = await cdp_agent_service.get_active_erp_tab(port=9222, host="https://ppbpzkns-9222.eun1.devtunnels.ms")
    ws_url = tab.get("webSocketDebuggerUrl")
    
    # 1. Reset to dashboard
    await cdp_agent_service.evaluate_script(ws_url, "window.location.href = 'http://localhost:4200/core'")
    await asyncio.sleep(2.5)
    
    # 2. Get interactive elements
    els = await cdp_agent_service.get_interactive_elements(ws_url)
    print(f"Total interactive elements: {len(els)}")
    
    # 3. Test click_element_or_coordinate with off-target coordinates [435, 172]
    # Semantic text matching should snap to real element (999, 173)
    fx, fy, snapped = await cdp_agent_service.click_element_or_coordinate(
        ws_url=ws_url,
        x=435,
        y=172,
        target_text="الموردين والمشتريات",
        interactive_elements=els
    )
    print(f"Final coordinates: ({fx}, {fy}), was_snapped={snapped}")
    
    # 4. Check if navigation succeeded
    await asyncio.sleep(2.5)
    new_url = await cdp_agent_service.evaluate_script(ws_url, "window.location.href")
    print(f"URL after snapped click: {new_url}")

if __name__ == "__main__":
    asyncio.run(test_interactive())
