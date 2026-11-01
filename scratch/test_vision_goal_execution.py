import asyncio
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.agentic_stepper_service import agentic_stepper_service

async def main():
    goal = "سجل فاتورة مشتريات جديدة من المورد حسين، على مخزن خامات تام، لمشروع السحاب، وطريقة الشراء مشتريات مباشرة، وسدد الإجمالي بالكامل نقداً، وأضف الأصناف التالية: صنف سن كمية 10، وصنف رمل كمية 20"
    print("=== STARTING VISION GOAL TEST ===")
    print("Goal:", goal)
    
    async for update in agentic_stepper_service.execute_goal_stream(
        goal=goal,
        cdp_port=9222,
        cdp_host="127.0.0.1",
        max_steps=5
    ):
        status = update.get("status")
        msg = update.get("message", "")
        step = update.get("step")
        print(f"[{step}] [{status}] {msg}")
        if status in ("completed", "error"):
            break

if __name__ == "__main__":
    asyncio.run(main())
