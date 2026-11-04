/**
 * CDP Form State Snapshot
 * Reads active form inputs, labels, readonly states, footer totals, and dataObject model.
 */
(function() {
    try {
        const page = document.querySelector('.dp-shell__pages > div:not([hidden])') || document;
        const inputs = Array.from(page.querySelectorAll('input, select, textarea, ng-select')).slice(0, 120).map(el => {
            const holder = el.closest('li, .dp-edit__total, .dp-field, .form-group, [class*="col-"]') || el.parentElement;
            const lbl = holder ? holder.querySelector('label, .dp-edit__totlbl, .totlbl, mat-label') : null;
            return {
                tag: el.tagName.toLowerCase(), type: el.type || '',
                name: el.getAttribute('name') || el.getAttribute('formcontrolname') || el.id || '',
                label: lbl ? (lbl.textContent || '').trim().slice(0, 40) : '',
                disabled: !!(el.disabled || el.readOnly)
            };
        });
        let model = {}, isOpen = false, formType = null;
        try {
            const c = window.DynamicERP.getActiveFormContext() || {};
            isOpen = !!c.isOpen; formType = c.formType || null;
            for (const [k, v] of Object.entries(c.dataObject || {})) { if (v === null || typeof v !== 'object') model[k] = v; }
        } catch(e) {}
        const totals = Array.from(page.querySelectorAll('.dp-edit__totlbl, [class*="totlbl"]')).map(l => (l.textContent || '').trim()).slice(0, 20);
        return { isOpen, formType, inputs, totals, model };
    } catch(e) { return { error: String(e) }; }
})();
