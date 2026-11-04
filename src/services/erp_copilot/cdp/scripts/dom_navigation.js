/**
 * CDP DOM Navigation Fallback
 * Finds elements with [data-page-id], [routerlink], or Arabic screen names and dispatches clicks.
 */
(function() {
    const target = __TARGET__;
    const targetPid = parseInt(target, 10);
    const targetStr = String(target).trim().toLowerCase();

    // 1. بحث عن عنصر DOM يحمل المعرف المباشر
    const selector = `[data-page-id="${target}"], [data-screen-id="${target}"], [id="page_${target}"]`;
    let el = document.querySelector(selector);

    // 2. إذا لم نجد، ابحث في روابط التوجيه والقوائم
    if (!el) {
        const candidates = Array.from(document.querySelectorAll('.dp-pgs__tile, .dp-nav__item, [routerlink], a, button, .dp-mods__card'));
        el = candidates.find(e => {
            const rl = (e.getAttribute('routerlink') || '').toLowerCase();
            const href = (e.getAttribute('href') || '').toLowerCase();
            const txt = (e.innerText || e.textContent || '').trim().toLowerCase();
            if (targetPid && (rl.includes(String(targetPid)) || href.includes(String(targetPid)))) return true;
            if (targetStr && (txt === targetStr || txt.includes(targetStr))) return true;
            return false;
        });
    }

    if (el) {
        try { el.focus(); } catch(_) {}
        const opts = { bubbles: true, cancelable: true, view: window };
        el.dispatchEvent(new MouseEvent('mousedown', opts));
        el.dispatchEvent(new MouseEvent('mouseup', opts));
        el.dispatchEvent(new MouseEvent('click', opts));
        if (typeof el.click === 'function') el.click();
        return true;
    }

    // 3. محاولة أخيرة عبر جسر DynamicERP مباشرة بصيغة رقمية صريحة
    if (targetPid && window.DynamicERP && typeof window.DynamicERP.navigateToScreen === 'function') {
        try {
            window.DynamicERP.navigateToScreen(targetPid);
            return true;
        } catch(_) {}
    }

    return false;
})();
