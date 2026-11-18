/**
 * CDP DOM Navigation Fallback
 * Finds elements with [data-page-id], [routerlink], or Arabic screen names and dispatches clicks.
 */
(function() {
    const target = __TARGET__;
    const targetPid = parseInt(target, 10);
    const targetStr = String(target).trim().toLowerCase();
    let resolvedArName = '';

    // 0. محاولة استخراج الشاشة والاسم العربي من Angular app-base (وفتحها عبر pageService إن أمكن)
    try {
        const baseEl = document.querySelector('app-base');
        if (window.ng && window.ng.getComponent && baseEl) {
            const comp = window.ng.getComponent(baseEl);
            const ps = comp ? comp.pageService : null;
            if (ps && Array.isArray(ps.pageAuthArray)) {
                const found = ps.pageAuthArray.find(a => {
                    const p = a.Page || a || {};
                    const pid = Number(p.PageID || p.page_id);
                    const ar = (p.ArName || p.name_ar || p.PageNameAr || '').trim().toLowerCase();
                    return (targetPid && !isNaN(targetPid) && pid === targetPid) || (targetStr && ar === targetStr);
                });
                if (found) {
                    const pageObj = found.Page || found;
                    resolvedArName = (pageObj.ArName || pageObj.name_ar || pageObj.PageNameAr || '').trim().toLowerCase();
                    if (typeof ps.addNewPage === 'function') {
                        if (comp.zone && typeof comp.zone.run === 'function') {
                            comp.zone.run(() => {
                                ps.addNewPage(pageObj);
                                if (comp.cdr && typeof comp.cdr.detectChanges === 'function') {
                                    comp.cdr.detectChanges();
                                }
                            });
                        } else {
                            ps.addNewPage(pageObj);
                        }
                        return true;
                    }
                }
            }
        }
    } catch(_) {}

    // 1. بحث عن عنصر DOM يحمل المعرف المباشر
    const selector = `[data-page-id="${target}"], [data-screen-id="${target}"], [id="page_${target}"]`;
    let el = document.querySelector(selector);

    // 2. إذا لم نجد، ابحث في بطاقات الشاشات (.dp-pgs__tile) وروابط التوجيه بالمعرف أو الاسم العربي المستنتج
    if (!el) {
        const candidates = Array.from(document.querySelectorAll('.dp-pgs__tile, .dp-nav__item, [routerlink], a, button, .dp-mods__card'));
        el = candidates.find(e => {
            const rl = (e.getAttribute('routerlink') || '').toLowerCase();
            const href = (e.getAttribute('href') || '').toLowerCase();
            const txt = (e.innerText || e.textContent || '').trim().toLowerCase();
            if (targetPid && !isNaN(targetPid) && (rl.includes(String(targetPid)) || href.includes(String(targetPid)))) return true;
            if (resolvedArName && (txt === resolvedArName || txt.includes(resolvedArName))) return true;
            if (targetStr && isNaN(targetPid) && (txt === targetStr || txt.includes(targetStr))) return true;
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
