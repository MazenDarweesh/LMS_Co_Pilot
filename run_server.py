import sys
import os
import asyncio
import selectors
import uvicorn

# Disable rate limiting for load testing on localhost if not explicitly overridden
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("MOCK_LMS", "true")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

def selector_loop_factory():
    return asyncio.SelectorEventLoop(selectors.SelectSelector())

if __name__ == "__main__":
    config = uvicorn.Config("src.main:app", host="0.0.0.0", port=8000, loop="none", log_level="info")
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=selector_loop_factory)
