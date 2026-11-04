/**
 * CDP ERP Screen Direct Navigator
 * Calls window.DynamicERP.navigateToScreen or Angular app-base pageService.addNewPage.
 */
(async function() {
    const target = __TARGET__;
    const targetPid = parseInt(target, 10);
    const targetStr = String(target).trim().toLowerCase();

    // 1. الأولوية الأولى: جسر DynamicERP الرسمي إن وجد
    if (window.DynamicERP && typeof window.DynamicERP.navigateToScreen === 'function') {
        try {
            const res = window.DynamicERP.navigateToScreen(target);
            if (res && typeof res.then === 'function') await res;
            return true;
        } catch(e) {
            console.warn('Bridge navigateToScreen error:', e);
        }
    }

    // 2. الأولوية الثانية: خدمة التنقل الأصلية للنظام (Angular app-base -> pageService)
    try {
        const baseEl = document.querySelector('app-base');
        if (window.ng && window.ng.getComponent && baseEl) {
            const comp = window.ng.getComponent(baseEl);
            const ps = comp ? comp.pageService : null;
            if (ps && ps.pageAuthArray && ps.pageAuthArray.length > 0) {
                const pageAuth = ps.pageAuthArray.find(a => {
                    const p = a.Page || {};
                    const pid = p.PageID || p.page_id;
                    const pName = (p.PageName || p.screen_key || '').trim().toLowerCase();
                    const arName = (p.ArName || p.name_ar || '').trim().toLowerCase();
                    return (targetPid && pid === targetPid) || pName === targetStr || arName === targetStr;
                });
                if (pageAuth && pageAuth.Page) {
                    comp.zone.run(() => {
                        ps.addNewPage(pageAuth.Page);
                        comp.cdr.detectChanges();
                    });
                    return true;
                }
            }
        }
    } catch(e) {
        console.warn('Host Angular pageService navigation error:', e);
    }

    // 3. الأولوية الثالثة: التوجيه بالرابط المباشر
    if (targetPid && !isNaN(targetPid)) {
        try {
            window.location.href = `/core?p=${targetPid}&a=${targetPid}`;
            return true;
        } catch(e) {}
    }

    return false;
})();
