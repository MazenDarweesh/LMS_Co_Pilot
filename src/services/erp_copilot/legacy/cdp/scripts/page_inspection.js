/**
 * CDP Active Page DOM Inspector
 * Inspects all Angular form controls, localized labels, and tables for automatic cataloging.
 */
(function() {
    try {
        const url = window.location.href;
        const match = url.match(/page_id=(\d+)/i) || url.match(/\/(\d+)(?:[?#]|$)/) || url.match(/#\/[^\/]+\/(\d+)/);
        const pageId = match ? parseInt(match[1]) : null;

        const headerEl = document.querySelector('h1, h2, h3, .page-title, .breadcrumb-item.active');
        const pageTitle = headerEl ? (headerEl.textContent || '').trim() : document.title;

        const controls = [];
        const elements = Array.from(document.querySelectorAll('[formcontrolname], input:not([type="hidden"]), select, textarea, ng-select'));
        const seenNames = new Set();

        for (const el of elements) {
            const fcName = el.getAttribute('formcontrolname') || el.getAttribute('name') || el.id;
            if (!fcName || seenNames.has(fcName.toLowerCase())) continue;
            seenNames.add(fcName.toLowerCase());

            let label = '';
            if (el.id) {
                const lbl = document.querySelector(`label[for="${el.id}"]`);
                if (lbl) label = (lbl.textContent || '').trim();
            }
            if (!label) {
                const parent = el.closest('.form-group, .col, .field, div');
                if (parent) {
                    const lbl = parent.querySelector('label');
                    if (lbl) label = (lbl.textContent || '').trim();
                }
            }
            if (!label) {
                label = el.getAttribute('placeholder') || el.getAttribute('title') || fcName;
            }

            let type = el.tagName.toLowerCase();
            if (type === 'input') type = el.type || 'text';
            if (el.classList.contains('ng-select') || type === 'ng-select') type = 'select_typeahead';

            controls.push({
                name: fcName,
                label: label,
                type: type,
                required: el.hasAttribute('required') || el.getAttribute('aria-required') === 'true'
            });
        }

        const grids = [];
        const tables = Array.from(document.querySelectorAll('table'));
        for (const table of tables) {
            const headers = Array.from(table.querySelectorAll('thead th, tr:first-child th'))
                .map(th => (th.textContent || '').trim())
                .filter(Boolean);
            if (headers.length >= 2) {
                grids.push({ headers: headers });
            }
        }

        return {
            page_id: pageId,
            url: url,
            title: pageTitle,
            controls_count: controls.length,
            controls: controls,
            grids: grids
        };
    } catch(e) {
        return { error: String(e) };
    }
})();
