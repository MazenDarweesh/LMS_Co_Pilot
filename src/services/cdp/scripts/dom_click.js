/**
 * CDP DOM Direct Click Dispatcher
 * Locates element at (__X__, __Y__) via elementFromPoint and dispatches mouse events & Angular triggers.
 */
(function() {
    const el = document.elementFromPoint(__X__, __Y__);
    if (el) {
        try { el.focus(); } catch(_) {}
        const opts = { bubbles: true, cancelable: true, view: window, clientX: __X__, clientY: __Y__ };
        el.dispatchEvent(new MouseEvent('mousedown', opts));
        el.dispatchEvent(new MouseEvent('mouseup', opts));
        el.dispatchEvent(new MouseEvent('click', opts));
        if (typeof el.click === 'function') {
            el.click();
        }
        // إذا كان العنصر ابن لرابط أو زر أو tile، اضغط الأب أيضاً
        const parentInteractive = el.closest('button, a, [role="button"], .dp-mods__card, .dp-rise, .dp-btn, .dp-pgs__tile, .dp-pgs__mod, .dp-hdr__tab, [routerlink]');
        if (parentInteractive && parentInteractive !== el) {
            parentInteractive.dispatchEvent(new MouseEvent('click', opts));
            if (typeof parentInteractive.click === 'function') {
                parentInteractive.click();
            }
        }
        return el.tagName;
    }
    return null;
})();
