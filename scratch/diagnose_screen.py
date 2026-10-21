import asyncio
import json
import io
from PIL import Image
from src.services.cdp_agent_service import cdp_agent_service

async def run():
    tab = await cdp_agent_service.get_active_erp_tab(port=9222, host="https://ppbpzkns-9222.eun1.devtunnels.ms")
    ws_url = tab.get("webSocketDebuggerUrl")
    
    vp = await cdp_agent_service.get_viewport_metrics(ws_url)
    print("Viewport metrics:", json.dumps(vp))

    ss_b64 = await cdp_agent_service.capture_screenshot(ws_url)
    import base64
    ss = base64.b64decode(ss_b64)
    im = Image.open(io.BytesIO(ss))
    print(f"Screenshot image size: {im.size} (width={im.size[0]}, height={im.size[1]})")

    # Interactive elements
    els = await cdp_agent_service.get_interactive_elements(ws_url)
    print(f"Total interactive elements: {len(els)}")
    for el in els:
        txt = el.get("text", "")
        if "مورد" in txt or "مشتر" in txt:
            print("MATCHED ELEMENT IN get_interactive_elements:", json.dumps(el, ensure_ascii=False))

    # DOM search for all tiles / texts
    tiles = await cdp_agent_service.evaluate_script(ws_url, """
        (function() {
            const list = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.innerText && (el.innerText.includes('موردين') || el.innerText.includes('المشتريات')) && el.children.length <= 3) {
                    const r = el.getBoundingClientRect();
                    list.push({
                        tag: el.tagName,
                        className: el.className,
                        text: el.innerText.trim().replace(/\\s+/g, ' '),
                        rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }
                    });
                }
            });
            return list;
        })()
    """)
    print("DOM Tiles Found:", json.dumps(tiles, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(run())
