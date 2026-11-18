/**
 * CDP Screen Metadata Extraction
 * Extracts columnList BehaviorSubject in 0ms directly from Angular component memory.
 */
(function() {
    try {
        let columns = [];
        // 1. محاولة الوصول عبر الجسر الرسمي
        if (window.DynamicERP && typeof window.DynamicERP.getActiveComponentInstance === 'function') {
            const comp = window.DynamicERP.getActiveComponentInstance();
            if (comp && comp.columnList && typeof comp.columnList.getValue === 'function') {
                columns = comp.columnList.getValue() || [];
            }
        }

        // 2. محاولة الوصول المباشر عبر شجرة مكونات Angular إذا لم يكن الجسر متاحاً
        if (!columns || columns.length === 0) {
            const pageEl = document.querySelector('.dp-shell__pages > div:not([hidden]), app-base');
            if (window.ng && window.ng.getComponent && pageEl) {
                const comp = window.ng.getComponent(pageEl);
                if (comp && comp.columnList && typeof comp.columnList.getValue === 'function') {
                    columns = comp.columnList.getValue() || [];
                }
            }
        }

        if (!Array.isArray(columns) || columns.length === 0) {
            return [];
        }

        return columns
            .filter(c => c.InsertVisable === 1 || c.IsRquired === 1)
            .map(c => ({
                name: c.ColumnName,
                label: c.arColumnLabel || c.enColumnLabel || c.ColumnName,
                type: c.InsertType || 'text',
                isMandatory: Boolean(c.IsRquired),
                isHeader: Boolean(c.IsGeneral),
                lookup: c.DroModel || null,
                sort: c.sort || 0
            }))
            .sort((a, b) => a.sort - b.sort);
    } catch(e) {
        return [];
    }
})();
