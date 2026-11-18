/**
 * CDP ERP Screen Direct Navigator
 * Calls window.DynamicERP.navigateToScreen or Angular app-base pageService.addNewPage.
 */
(async function() {
    const target = __TARGET__;
    const targetPid = parseInt(target, 10);
    const targetStr = String(target).trim().toLowerCase();

    // دالة مساعدة للتحقق مما إذا أصبحت الشاشة النشطة فعلياً تطابق targetPid
    function isTargetPageOpen(pid) {
        if (!pid || isNaN(pid)) return false;
        try {
            if (window.DynamicERP && typeof window.DynamicERP.getActiveScreen === 'function') {
                const act = window.DynamicERP.getActiveScreen();
                if (act && Number(act.pageId) === Number(pid)) return true;
            }
        } catch(e) {}
        try {
            const baseEl = document.querySelector('app-base');
            if (window.ng && window.ng.getComponent && baseEl) {
                const comp = window.ng.getComponent(baseEl);
                const ps = comp ? comp.pageService : null;
                const curr = ps && ps.getCurrentOpenPage ? ps.getCurrentOpenPage() : null;
                if (curr && Number(curr.PageID || curr.page_id) === Number(pid)) return true;
            }
        } catch(e) {}
        return false;
    }

    // 1. الأولوية الأولى: جسر DynamicERP الرسمي إن وجد (مع التحقق الفعلي من تطابق PageID)
    if (window.DynamicERP && typeof window.DynamicERP.navigateToScreen === 'function') {
        try {
            const arg = (targetPid && !isNaN(targetPid)) ? targetPid : target;
            const res = window.DynamicERP.navigateToScreen(arg);
            if (res && typeof res.then === 'function') await res;
            await new Promise(r => setTimeout(r, 120));
            if (res === true && (!targetPid || isNaN(targetPid) || isTargetPageOpen(targetPid))) {
                return true;
            }
        } catch(e) {
            console.warn('Bridge navigateToScreen error:', e);
        }
    }

    // 2. الأولوية الثانية: خدمة التنقل الأصلية للنظام (Angular app-base -> pageService.addNewPage)
    try {
        const baseEl = document.querySelector('app-base');
        if (window.ng && window.ng.getComponent && baseEl) {
            const comp = window.ng.getComponent(baseEl);
            const ps = comp ? comp.pageService : null;
            if (ps) {
                const authList = Array.isArray(ps.pageAuthArray) ? ps.pageAuthArray : [];
                let matchedPage = null;

                // التمريرة الأولى: مطابقة رقم PageID بدقة قصوى لمنع تداخل الأسماء (مثل 225 و 244)
                if (targetPid && !isNaN(targetPid)) {
                    const byPid = authList.find(a => {
                        const p = a.Page || a || {};
                        return Number(p.PageID || p.page_id) === Number(targetPid);
                    });
                    if (byPid) matchedPage = byPid.Page || byPid;
                }

                // التمريرة الثانية: مطابقة الاسم العربي أو الإنجليزي إذا لم يوجد targetPid
                if (!matchedPage && targetStr) {
                    const byName = authList.find(a => {
                        const p = a.Page || a || {};
                        const pName = (p.PageName || p.screen_key || '').trim().toLowerCase();
                        const arName = (p.ArName || p.name_ar || '').trim().toLowerCase();
                        return arName === targetStr || pName === targetStr;
                    });
                    if (byName) matchedPage = byName.Page || byName;
                }

                if (matchedPage && typeof ps.addNewPage === 'function') {
                    if (comp.zone && typeof comp.zone.run === 'function') {
                        comp.zone.run(() => {
                            ps.addNewPage(matchedPage);
                            if (comp.cdr && typeof comp.cdr.detectChanges === 'function') {
                                comp.cdr.detectChanges();
                            }
                        });
                    } else {
                        ps.addNewPage(matchedPage);
                    }
                    return true;
                }
            }
        }
    } catch(e) {
        console.warn('Host Angular pageService navigation error:', e);
    }

    return false;
})();
