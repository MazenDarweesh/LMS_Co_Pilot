/**
 * CDP Click Ripple Effect
 * Injects a temporary pulsing visual indicator at coordinates (__X__, __Y__)
 */
(function() {
    const existing = document.getElementById('cdp-click-indicator');
    if (existing) existing.remove();
    const dot = document.createElement('div');
    dot.id = 'cdp-click-indicator';
    dot.style.position = 'fixed';
    dot.style.left = '__X__px';
    dot.style.top = '__Y__px';
    dot.style.width = '24px';
    dot.style.height = '24px';
    dot.style.marginLeft = '-12px';
    dot.style.marginTop = '-12px';
    dot.style.borderRadius = '50%';
    dot.style.border = '2px solid #ef4444';
    dot.style.backgroundColor = 'rgba(239, 68, 68, 0.35)';
    dot.style.boxShadow = '0 0 12px #ef4444';
    dot.style.pointerEvents = 'none';
    dot.style.zIndex = '2147483647';
    dot.style.transition = 'transform 0.4s ease-out, opacity 0.4s ease-out';
    dot.style.transform = 'scale(0.5)';
    dot.style.opacity = '1';
    document.body.appendChild(dot);
    requestAnimationFrame(() => {
        dot.style.transform = 'scale(1.6)';
        dot.style.opacity = '0';
    });
    setTimeout(() => dot.remove(), 500);
})();
