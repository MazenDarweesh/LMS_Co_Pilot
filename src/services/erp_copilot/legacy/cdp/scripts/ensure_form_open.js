/**
 * CDP Ensure ERP Form Open
 * Checks if AddOrEdit form is open; otherwise calls bridge triggerAddNew or clicks the New button.
 */
(async function() {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const ctxOpen = () => { try { const c = window.DynamicERP?.getActiveFormContext?.(); return !!(c && (c.dataObject || (c.rows && c.formType !== 'dom') || c.isInvoice)); } catch(e) { return false; } };
    const domOpen = () => {
        const p = document.querySelector('.dp-shell__pages > div:not([hidden])') || document;
        const f = p.querySelector('.dp-edit, .dp-list__pre, .dp-edit__head, section.dp-pu__sup, app-add-or-edit, .dp-modal, #addOrEditPopUp');
        if (f && f.offsetParent !== null) return true;
        const primaryInp = p.querySelector('[formcontrolname="SupplierID"], [formcontrolname="CustomerID"], [formcontrolname="StoreID"], [formcontrolname="EmpId"], input#productQty');
        return !!(primaryInp && primaryInp.offsetParent !== null);
    };
    const isOpen = () => ctxOpen() || domOpen();
    if (isOpen()) return { opened: true, method: 'already_open' };
    const deadline = Date.now() + __TIMEOUT_MS__;
    let bridgeCalls = 0, domClicks = 0;
    while (Date.now() < deadline) {
        try { if (window.DynamicERP && typeof window.DynamicERP.triggerAddNew === 'function') { bridgeCalls++; await window.DynamicERP.triggerAddNew(); } } catch(e) {}
        await sleep(350);
        if (isOpen()) return { opened: true, method: 'bridge', bridgeCalls, domClicks };
        const page = document.querySelector('.dp-shell__pages > div:not([hidden])') || document;
        const masterBtn = page.querySelector('button.dp-btn--primary.dp-list__act, .dp-list__act.dp-btn--primary, button.dp-btn--new, [data-action="new"], button.dp-list__act');
        const btn = masterBtn || Array.from(page.querySelectorAll('button, a')).find(b => {
            if (b.closest('lms-ai-copilot, app-copilot-chat, nav, .dp-hdr')) return false;
            const txt = (b.textContent || '').trim().replace(/[إأآ]/g, 'ا');
            const hasPlus = !!b.querySelector('.fa-plus, .bi-plus, i[class*="plus"]');
            return /اضافة جديد|جديد|^اضافة$|add new/i.test(txt) || (hasPlus && (/اضاف|جديد/.test(txt) || txt === ''));
        });
        if (btn && btn.offsetParent !== null) { 
            domClicks++; 
            btn.click(); 
            await sleep(550); 
            if (isOpen()) return { opened: true, method: 'dom_button', bridgeCalls, domClicks }; 
        }
        await sleep(250);
    }
    return { opened: false, method: 'timeout', bridgeCalls, domClicks };
})();
