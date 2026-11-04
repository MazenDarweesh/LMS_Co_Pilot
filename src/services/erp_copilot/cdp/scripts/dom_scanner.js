/**
 * CDP DOM Interactive Elements Scanner
 * Extracts bounding rectangles, centers, and labels for all interactive elements in the viewport.
 */
(function() {
    const results = [];
    const selectors = [
        'button', 'a', '[role="button"]', '[role="tab"]', '[role="menuitem"]',
        '.dp-hdr__tab', '.dp-pgs__tile', '.dp-pgs__mod', '.dp-mods__card', '.dp-rise',
        '.dp-btn', '.nav-link', '.menu-item',
        'input:not([type="hidden"])', 'select', 'ng-select', '.ng-select',
        'body > ng-dropdown-panel .ng-option', '.ng-dropdown-panel [role="option"]', '.ng-option',
        '[data-screen]', '[routerlink]', 'td.clickable', '.btn'
    ];

    const elements = document.querySelectorAll(selectors.join(','));
    for (const el of elements) {
        // استبعاد أي عناصر تخص نافذة محادثة المساعد الذكي (LMS Copilot) حتى لا يضغط العميل على نفسه
        if (el.closest('lms-copilot-chat, .copilot-window, .ai-chat-window, .chat-panel')) {
            continue;
        }

        // فحص الرؤية الحقيقية
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
            continue;
        }
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        // التأكد من وجود العنصر داخل نافذة العرض
        if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) {
            continue;
        }

        const rawText = (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim();
        const cleanText = rawText.replace(/\\s+/g, ' ').substring(0, 100);

        results.push({
            tag: el.tagName.toLowerCase(),
            text: cleanText,
            x: Math.round(rect.left + rect.width / 2),
            y: Math.round(rect.top + rect.height / 2),
            rect: {
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            }
        });
    }
    return results;
})();
