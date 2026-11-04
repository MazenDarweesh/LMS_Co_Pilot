/**
 * CDP Generic Polymorphic Form & Grid Injector
 * Injects header controls, Angular ng-select lookups, grid item lines, and resolves net totals for payments.
 */
(async function() {
    const payload = __PAYLOAD__;
    const logs = [];

    // 1. محرك التعبئة المعمم فائق الدقة (Generic Polymorphic DOM Injector)
    async function selectNgSelect(target, targetVal) {
        if (!targetVal) return false;
        const sel = typeof target === 'string' ? document.querySelector(target) : target;
        if (!sel) return false;
        const container = sel.querySelector('.ng-select-container') || sel;
        container.click();
        await new Promise(r => setTimeout(r, 120));
        const input = sel.querySelector('input');
        if (input) {
            input.focus();
            input.value = targetVal;
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }
        await new Promise(r => setTimeout(r, 450));
        const panels = Array.from(document.querySelectorAll('body > ng-dropdown-panel, ng-dropdown-panel, .ng-dropdown-panel'));
        const lastPanel = panels[panels.length - 1];
        if (!lastPanel) return false;
        const opts = Array.from(lastPanel.querySelectorAll('.ng-option, [role="option"]'));
        const norm = s => String(s || '').trim().replace(/[أإآ]/g, 'ا').replace(/ى/g, 'ي');
        const tv = norm(targetVal);
        const tvStem = tv.replace(/[ةه]$/, '');
        const wantsNeg = tv.includes('غير');
        const okOpts = opts.filter(o => wantsNeg || !norm(o.textContent).includes('غير'));
        const match = okOpts.find(o => norm(o.textContent) === tv)
            || okOpts.find(o => norm(o.textContent).includes(tv))
            || okOpts.find(o => tvStem.length >= 3 && norm(o.textContent).includes(tvStem));
        if (match) {
            match.click();
            return true;
        }
        if (input) {
            input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Escape' }));
        }
        return false;
    }

    function findFieldElement(fieldName) {
        const candidates = [
            `[formcontrolname='${fieldName}']`,
            `[formcontrolname='${fieldName.toLowerCase()}']`,
            `#${fieldName}`,
            `#${fieldName.toLowerCase()}`,
            `input[name='${fieldName}']`,
            `select[name='${fieldName}']`,
            `textarea[name='${fieldName}']`
        ];
        for (const c of candidates) {
            const el = document.querySelector(c);
            if (el) return el;
        }

        // المطابقة المعممة بواسطة تسميات الحقول بالعربية أو الإنجليزية (Label-Anchored Matching)
        try {
            const labels = Array.from(document.querySelectorAll('label'));
            const cleanField = fieldName.trim().toLowerCase();
            const matchedLabel = labels.find(l => {
                const txt = (l.textContent || '').trim().toLowerCase();
                return txt && (txt === cleanField || txt.includes(cleanField) || cleanField.includes(txt));
            });
            if (matchedLabel) {
                const forAttr = matchedLabel.getAttribute('for');
                if (forAttr) {
                    const target = document.getElementById(forAttr);
                    if (target) return target;
                }
                const parent = matchedLabel.closest('.form-group, .col, .field, div, td, tr');
                if (parent) {
                    const inner = parent.querySelector('input:not([type="hidden"]), select, textarea, ng-select');
                    if (inner) return inner;
                }
            }
        } catch(e) {
            console.warn('Label match error:', e);
        }

        return null;
    }

    async function fillSingleControl(fieldName, val) {
        if (val === undefined || val === null || val === '') return false;
        const el = findFieldElement(fieldName);
        if (!el) return false;

        const isNgSelect = el.tagName.toLowerCase() === 'ng-select' || el.classList.contains('ng-select');
        if (isNgSelect) {
            const strVal = String(val);
            const firstTerm = strVal.includes(' ') ? strVal.split(' ')[0] : strVal;
            return await selectNgSelect(el, strVal) || await selectNgSelect(el, firstTerm);
        }

        if (el.type === 'checkbox') {
            el.checked = Boolean(val);
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }

        el.focus();
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        await new Promise(r => setTimeout(r, 80));
        return true;
    }

    // أ. تعبئة حقول الهيدر ديناميكياً لأي وثيقة
    const header = payload.header || {};
    let filledCount = 0;
    const deferredTotals = [];
    for (const [key, val] of Object.entries(header)) {
        const sVal = String(val).toUpperCase();
        const lKey = key.toLowerCase();
        const isTotalVal = sVal === '$TOTAL' || sVal === 'TOTAL';
        const isPaidField = lKey.includes('popaid') || lKey.includes('cashpaid') || lKey.includes('madfou') || /مدفوع|محصل|سداد|نقد/.test(key);
        if (isTotalVal || (isPaidField && (isTotalVal || !val || val === '0' || Number(val) === 0))) {
            deferredTotals.push(key);
            continue;
        }
        if (await fillSingleControl(key, val)) {
            filledCount++;
        }
    }

    // ب. تعبئة أسطر الجدول / الأصناف ديناميكياً لأي وثيقة
    const items = payload.items || payload.lines || [];
    let itemsAdded = 0;
    for (const item of items) {
        let itemFilled = false;

        const prodSel = document.querySelector('ng-select#product, [formcontrolname="product"], [formcontrolname="AccID"], ng-select#AccID, table ng-select');
        const itemName = item.product || item.name || item.AccID || item.ItemName;
        if (prodSel && itemName) {
            if (await selectNgSelect(prodSel, itemName)) {
                itemFilled = true;
            }
        }

        for (const [col, colVal] of Object.entries(item)) {
            if (col !== 'product' && col !== 'name' && col !== 'AccID' && col !== 'ItemName') {
                if (await fillSingleControl(col, colVal)) {
                    itemFilled = true;
                }
            }
        }

        await new Promise(r => setTimeout(r, 350));
        const qtyInp = document.querySelector('input#productQty, [formcontrolname="productQty"], input[type="number"]');
        const continueBtn = Array.from(document.querySelectorAll('button')).find(b => {
            const t = (b.textContent || '').trim();
            return t === 'متابعة' || t === 'تأكيد' || t === 'موافق' || t === 'إضافة';
        });
        if (qtyInp && continueBtn && (item.productQty !== undefined || item.qty !== undefined)) {
            const qVal = item.productQty !== undefined ? item.productQty : item.qty;
            qtyInp.focus();
            qtyInp.value = qVal;
            qtyInp.dispatchEvent(new Event('input', { bubbles: true }));
            qtyInp.dispatchEvent(new Event('change', { bubbles: true }));
            await new Promise(r => setTimeout(r, 120));
            continueBtn.click();
            await new Promise(r => setTimeout(r, 300));
        }

        if (itemFilled) itemsAdded++;
    }

    // ج. تسوية الدفع: المحصل نقداً = إجمالي الفاتورة المحسوب بعد إدخال الأصناف
    let paidFilled = false;
    if (deferredTotals.length) {
        await new Promise(r => setTimeout(r, 450));
        let total = null;
        try {
            const dobj = (window.DynamicERP.getActiveFormContext() || {}).dataObject || {};
            total = dobj.TotalCurrancy || dobj.TotalOrderBeforCurrancy || dobj.NetTotal || null;
        } catch(e) {}

        if (!total || Number(total) === 0) {
            const grandValEl = document.querySelector('.dp-edit__grandval, .dp-edit__grand strong, .dp-edit__grand, [class*="grandval"]');
            if (grandValEl) {
                const v = parseFloat((grandValEl.textContent || '').replace(/,/g, '').replace(/[^0-9.]/g, '').trim());
                if (!isNaN(v) && v > 0) { total = v; }
            }
        }

        if (!total || Number(total) === 0) {
            const totInputs = Array.from(document.querySelectorAll('input#TotalCurrancy, input[name="TotalCurrancy"], input[formcontrolname="TotalCurrancy"], input#TotalOrderBeforCurrancy, input[formcontrolname="TotalOrderBeforCurrancy"], .dp-edit__total input[readonly], .totlbl + * input, input[name*="total" i]'));
            for (const inp of totInputs) {
                const v = parseFloat((inp.value || '').replace(/,/g, ''));
                if (!isNaN(v) && v > 0) { total = v; break; }
            }
        }

        if (!total || Number(total) === 0) {
            let sum = 0;
            for (const itm of items) {
                const q = parseFloat(itm.productQty ?? itm.qty ?? itm.quantity ?? 1) || 1;
                const p = parseFloat(itm.price ?? itm.cost ?? itm.UnitPrice ?? itm.ItemPrice ?? 0) || 0;
                sum += q * p;
            }
            if (sum > 0) total = sum;
        }

        if (total) {
            const paidDirect = document.querySelector('input#POPaid, input[name="POPaid"], input[formcontrolname="POPaid"], input#POPaidCurrancy, input[name="POPaidCurrancy"], input[formcontrolname="POPaidCurrancy"], input[name*="paid" i], input[id*="paid" i]');
            const lbls = Array.from(document.querySelectorAll('.dp-edit__totlbl, .totlbl, [class*="totlbl"], label'));
            const lbl = lbls.find(l => /المحصل|مدفوع|المسدد|نقد|سداد/.test(l.textContent || ''));
            const holder = lbl ? (lbl.closest('li, .dp-edit__total, .dp-field, .form-group') || lbl.parentElement) : null;
            const inp = paidDirect || (holder ? holder.querySelector('input:not([disabled]):not([readonly])') : null);

            if (inp) {
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                inp.focus();
                setter.call(inp, String(total));
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                inp.dispatchEvent(new Event('blur', { bubbles: true }));
                paidFilled = true;
            }

            if (window.DynamicERP && typeof window.DynamicERP.fillFormData === 'function') {
                try {
                    const bRes = await window.DynamicERP.fillFormData({
                        fields: { POPaidCurrancy: total, POPaid: total },
                        rows: []
                    });
                    if (bRes) paidFilled = true;
                } catch(e) {}
            }

            try {
                const ctx = window.DynamicERP?.getActiveFormContext?.();
                if (ctx && ctx.dataObject) {
                    ctx.dataObject.POPaidCurrancy = total;
                    ctx.dataObject.POPaid = total;
                    paidFilled = true;
                }
            } catch(e) {}
        }
        if (paidFilled) filledCount++;
    }

    return {
        success: filledCount > 0 || itemsAdded > 0,
        method: 'dom_precision_generic',
        filled_count: filledCount,
        items_count: itemsAdded,
        paid_filled: paidFilled
    };
})();
