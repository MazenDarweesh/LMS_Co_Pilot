/**
 * CDP Active Toasts & Save Sub-Menu Inspector
 * Detects open save sub-menus (span.dp-menu_text) and clicks "حفظ",
 * and reads active validation or error toasts from #toast-container and .overlay-container.
 */
(function() {
    const out = [];

    // 1. إذا كانت قائمة الحفظ الفرعية مفتوحة (span.dp-menu_text)، ننقر عليها لإتمام الحفظ
    const menuSpans = Array.from(document.querySelectorAll('span.dp-menu_text, span.dp-menu__text'));
    for (const sp of menuSpans) {
        const txt = (sp.textContent || '').trim();
        if (txt === 'حفظ' && sp.offsetWidth > 0 && sp.offsetHeight > 0) {
            const btn = sp.closest('button, li, a, [role="menuitem"]') || sp;
            btn.click();
            out.push({ kind: 'sub_menu_clicked', text: 'تم النقر التلقائي على خيار القائمة الفرعية: حفظ' });
            break;
        }
    }

    // 2. قراءة رسائل التنبيه من #toast-container.dp-toast-top-end و .overlay-container
    const toastNodes = document.querySelectorAll(
        '#toast-container > div, .dp-toast-top-end > div, .overlay-container .ngx-toastr, .swal2-container .swal2-popup'
    );
    for (const node of toastNodes) {
        const text = (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
        if (!text) continue;
        const cls = (node.className || '').toLowerCase();
        let kind = 'info';
        if (cls.includes('error') || cls.includes('danger') || /برجاء|مطلوب|يجب|ادخال|إدخال|اختيار|ناقص|خطأ|تعذر/.test(text)) {
            kind = 'error';
        } else if (cls.includes('success') || /تم الحفظ|بنجاح/.test(text)) {
            kind = 'success';
        }
        out.push({ kind, text });
    }

    return out;
})();

