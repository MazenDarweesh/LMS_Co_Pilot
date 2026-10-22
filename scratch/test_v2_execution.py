import asyncio
import json
import time
from src.services.cdp_agent_service import cdp_agent_service
from src.services.agentic_stepper_service import agentic_stepper_service

async def test_live_execution():
    tab = await cdp_agent_service.get_active_erp_tab(port=9222, host="https://ppbpzkns-9222.eun1.devtunnels.ms")
    ws_url = tab.get("webSocketDebuggerUrl")
    print(f"Connected to Tab: {tab.get('title')} | URL: {tab.get('url')}")
    
    # 1. Reset to main core dashboard
    print("Resetting to dashboard: http://localhost:4200/core ...")
    await cdp_agent_service.evaluate_script(ws_url, "window.location.href = 'http://localhost:4200/core'")
    await asyncio.sleep(2.0)

    # 2. Execute stepper for goal: 'اذهب للموردين والمشتريات'
    goal = "اذهب للموردين والمشتريات"
    print(f"\n--- Starting Stepper with Goal: '{goal}' ---")
    
    start_t = time.perf_counter()
    step_events = []
    
    async for event in agentic_stepper_service.execute_goal_stream(
        goal=goal,
        cdp_port=9222,
        cdp_host="https://ppbpzkns-9222.eun1.devtunnels.ms",
        session_id="test_blueprint_v2_live",
        max_steps=3
    ):
        status = event.get("status")
        step = event.get("step")
        msg = event.get("message", "")
        coord = event.get("coordinate")
        print(f"[Step {step}] Status: {status} | Coord: {coord} | Msg: {msg[:60]}")
        step_events.append(event)
        if status in ("completed", "max_steps_reached", "error"):
            break

    total_time = round(time.perf_counter() - start_t, 2)
    print(f"\n--- Execution Completed in {total_time}s across {len(step_events)} events ---")
    
    # 3. Check final URL
    final_url = await cdp_agent_service.evaluate_script(ws_url, "window.location.href")
    print(f"Final Browser URL: {final_url}")
    
    # 4. Now test the Goal-Reached Pre-check by running again while already on target screen!
    print(f"\n--- Testing Pre-Check: Running again while already on target screen ---")
    pre_start_t = time.perf_counter()
    async for event in agentic_stepper_service.execute_goal_stream(
        goal=goal,
        cdp_port=9222,
        cdp_host="https://ppbpzkns-9222.eun1.devtunnels.ms",
        session_id="test_blueprint_v2_precheck",
        max_steps=3
    ):
        status = event.get("status")
        step = event.get("step")
        msg = event.get("message", "")
        print(f"[Pre-Check Step {step}] Status: {status} | Msg: {msg}")
        if status in ("completed", "max_steps_reached"):
            break
    print(f"Pre-check completed in {round(time.perf_counter() - pre_start_t, 2)}s (Target: < 0.5s without LLM call!)")

if __name__ == "__main__":
    asyncio.run(test_live_execution())
