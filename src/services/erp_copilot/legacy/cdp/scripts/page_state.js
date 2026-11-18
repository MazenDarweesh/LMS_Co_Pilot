/**
 * CDP Page State Inspector
 * Extracts current URL, title, prominent headings, and active ERP screen from Angular / DynamicERP.
 */
(function() {
    const headings = [];
    document.querySelectorAll('h1, h2, h3, .dp-list__ttl, .dp-hdr__tab--active, .active').forEach(el => {
        const txt = (el.innerText || el.textContent || '').trim();
        if (txt && txt.length < 100) headings.push(txt);
    });
    let activeScreen = null;
    try {
        if (window.DynamicERP && typeof window.DynamicERP.getActiveScreen === 'function') {
            activeScreen = window.DynamicERP.getActiveScreen();
        }
    } catch(e) {}

    if (!activeScreen || !activeScreen.pageId) {
        try {
            const baseEl = document.querySelector('app-base');
            if (window.ng && window.ng.getComponent && baseEl) {
                const comp = window.ng.getComponent(baseEl);
                const ps = comp ? comp.pageService : null;
                const curr = ps && ps.getCurrentOpenPage ? ps.getCurrentOpenPage() : null;
                if (curr) {
                    activeScreen = {
                        pageId: curr.PageID || curr.page_id,
                        pageName: (curr.PageName || curr.screen_key || '').trim(),
                        title: curr.ArName || curr.name_ar || (curr.PageName || '').trim()
                    };
                }
            }
        } catch(e) {}
    }

    return {
        url: window.location.href,
        title: document.title,
        headings: headings.slice(0, 5),
        activeScreen: activeScreen
    };
})();
