/**
 * CDP DOM Interactive Elements Scanner
 * Extracts bounding rectangles, centers, and labels for all interactive elements in the viewport.
 */
(function() {
    const results = [];
    const selectors = [
        'button', 'a', '[role="button"]', '[role="tab"]', '[role="menuitem"]',
        'span.dp-menu_text', 'span.dp-menu__text', '.dp-menu__item', '.dp-menu_item',
        '.dp-hdr__tab', '.dp-pgs__tile', '.dp-pgs__mod', '.dp-mods__card', '.dp-rise',
        '.dp-btn', '.nav-link', '.menu-item',
        'input:not([type="hidden"])', 'select', 'ng-select', 'eg-select', '.ng-select',
        'body > ng-dropdown-panel .ng-option', '.ng-dropdown-panel [role="option"]', '.ng-option',
        '[data-screen]', '[routerlink]', 'td.clickable', '.btn'
    ];

    const elements = document.querySelectorAll(selectors.join(','));
    for (const el of elements) {
        // استبعاد أي عناصر تخص نافذة محادثة المساعد الذكي (LMS Copilot) حتى لا يضغط العميل على نفسه
        if (el.closest('lms-ai-copilot, app-copilot-chat, lms-copilot-chat, .copilot-window, .ai-chat-window, .chat-panel')) {
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

        const tag = el.tagName.toLowerCase();
        let rawText = (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || '').trim();

        // إذا كان العنصر حقل إدخال أو قائمة منسدلة فارغة، نربطه بنص الـ Label المجاور له حتى ينقر الوكيل على مربع الإدخال وليس على النص الثابت
        if ((!rawText || rawText.length < 2) && (tag === 'input' || tag === 'select' || tag === 'ng-select' || tag === 'eg-select' || el.classList.contains('ng-select'))) {
            let lblText = '';
            if (el.id) {
                const explicitLbl = document.querySelector(`label[for="${el.id}"]`);
                if (explicitLbl) lblText = (explicitLbl.textContent || '').trim();
            }
            if (!lblText) {
                const holder = el.closest('.form-group, .dp-field, .col, [class*="col-"], div');
                if (holder) {
                    const innerLbl = holder.querySelector('label, .dp-edit__totlbl, mat-label');
                    if (innerLbl) lblText = (innerLbl.textContent || '').trim();
                }
            }
            if (!lblText) {
                lblText = el.getAttribute('formcontrolname') || el.getAttribute('name') || el.id || '';
            }
            rawText = lblText;
        }

        const cleanText = rawText.replace(/\s+/g, ' ').substring(0, 100);

        results.push({
            tag: tag,
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
