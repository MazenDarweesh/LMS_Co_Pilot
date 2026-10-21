import asyncio
import json
import re
from src.services.cdp_agent_service import cdp_agent_service

async def test_match():
    tab = await cdp_agent_service.get_active_erp_tab(port=9222, host="https://ppbpzkns-9222.eun1.devtunnels.ms")
    ws_url = tab.get("webSocketDebuggerUrl")
    
    await cdp_agent_service.evaluate_script(ws_url, "window.location.href = 'http://localhost:4200/core'")
    await asyncio.sleep(2.5)

    els = await cdp_agent_service.get_interactive_elements(ws_url)
    target_text = "الموردين و المشتريات"
    print(f"Testing matching for: {target_text}")
    
    def normalize(s: str) -> str:
        s = re.sub(r"[أإآ]", "ا", s)
        s = re.sub(r"ة", "ه", s)
        s = re.sub(r"[\s_\-و]+", "", s).lower()
        return s

    norm_target = normalize(target_text)
    print(f"Normalized target: {norm_target}")
    
    matches = []
    for el in els:
        el_raw = el.get("text", "")
        if not el_raw:
            continue
        norm_el = normalize(el_raw)
        if norm_target in norm_el or norm_el in norm_target:
            matches.append((el, norm_el))

    print(f"Found {len(matches)} matches:")
    for m, norm_text in matches:
        print("  Match:", m["tag"], repr(m["text"]), "x=", m["x"], "y=", m["y"])

if __name__ == "__main__":
    asyncio.run(test_match())
