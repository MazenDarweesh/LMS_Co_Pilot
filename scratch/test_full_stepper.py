import asyncio
import json
from src.services.cdp_agent_service import cdp_agent_service
from src.services.agentic_stepper_service import agentic_stepper_service

async def test_full_step():
    tab = await cdp_agent_service.get_active_erp_tab(port=9222, host="https://ppbpzkns-9222.eun1.devtunnels.ms")
    ws_url = tab.get("webSocketDebuggerUrl")
    
    # 1. Reset to dashboard
    await cdp_agent_service.evaluate_script(ws_url, "window.location.href = 'http://localhost:4200/core'")
    await asyncio.sleep(2.5)
    
    # 2. Run single step generator
    events = []
    async for event in agentic_stepper_service.execute_goal_stream(
        goal="اذهب للموردين والمشتريات",
        cdp_port=9222,
        cdp_host="https://ppbpzkns-9222.eun1.devtunnels.ms",
        session_id="test_verify_session",
        max_steps=1
    ):
        thought_snip = (event.get("thought") or "")[:40]
        print(f"STEP EVENT: status={event.get('status')}, step={event.get('step')}, coord={event.get('coordinate')}, thought={thought_snip}")
        events.append(event)

    # 3. Check new URL
    await asyncio.sleep(2.5)
    new_url = await cdp_agent_service.evaluate_script(ws_url, "window.location.href")
    print(f"Final URL after 1 step: {new_url}")

if __name__ == "__main__":
    asyncio.run(test_full_step())
