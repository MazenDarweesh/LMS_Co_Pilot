/**
 * Set-of-Mark (SoM) Overlay Injector & Remover for Vision Grounding.
 * Draws high-contrast numbered bounding boxes [0], [1], [2]... on interactive elements
 * before Page.captureScreenshot so Multimodal VLM can select `element_id` with 100% accuracy.
 */
(function() {
    const mode = "__MODE__";
    const existing = document.getElementById('__copilot_som_overlay__');
    if (existing) {
        existing.remove();
    }
    if (mode === "remove") {
        return true;
    }

    const items = __ELEMENTS_JSON__;
    if (!Array.isArray(items) || items.length === 0) {
        return false;
    }

    const container = document.createElement('div');
    container.id = '__copilot_som_overlay__';
    container.style.cssText = [
        'position:fixed',
        'top:0',
        'left:0',
        'width:100vw',
        'height:100vh',
        'pointer-events:none',
        'z-index:2147483646',
        'overflow:hidden'
    ].join(';');

    const maxItems = Math.min(items.length, 60);
    for (let i = 0; i < maxItems; i++) {
        const el = items[i];
        const r = el && el.rect;
        if (!r || r.width <= 2 || r.height <= 2) continue;

        const box = document.createElement('div');
        box.style.cssText = [
            'position:fixed',
            `left:${r.left}px`,
            `top:${r.top}px`,
            `width:${r.width}px`,
            `height:${r.height}px`,
            'border:2px solid #e11d48',
            'background:rgba(225,29,72,0.06)',
            'box-sizing:border-box',
            'border-radius:3px',
            'pointer-events:none'
        ].join(';');

        const badge = document.createElement('span');
        badge.textContent = String(i);
        badge.style.cssText = [
            'position:absolute',
            'top:-10px',
            'right:-2px',
            'background:#e11d48',
            'color:#ffffff',
            'font-family:Consolas,monospace,sans-serif',
            'font-size:11px',
            'font-weight:900',
            'line-height:14px',
            'padding:0 4px',
            'border-radius:3px',
            'box-shadow:0 1px 3px rgba(0,0,0,0.45)',
            'pointer-events:none'
        ].join(';');

        box.appendChild(badge);
        container.appendChild(box);
    }

    document.body.appendChild(container);
    return true;
})();

