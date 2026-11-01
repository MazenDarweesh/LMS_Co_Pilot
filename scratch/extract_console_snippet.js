// ==============================================================================
// DynamicPro ERP: 1-Click Metadata Extractor from Browser Tab (Chrome DevTools)
// Usage: Open ERP screen on PC 2, press F12 -> Console, paste this snippet and press Enter.
// The complete metadata dictionary is copied directly to your clipboard!
// ==============================================================================

(function() {
  const comp = window.DynamicERP?.getActiveComponentInstance?.();
  if (!comp) {
    console.error("❌ DynamicERP active component not found! Make sure an ERP form screen is currently open.");
    return;
  }

  const rawCols = comp.columnList?.getValue?.() || comp.columns || [];
  const headerCols = rawCols.filter(c => c.IsGeneral == 1 || c.isGeneral == 1);
  const gridCols = rawCols.filter(c => c.IsGeneral == 0 || c.isGeneral == 0);

  const exportData = {
    page_id: comp.pageId || comp.PageID,
    screen_key: comp.constructor?.name?.replace('Component', '') || "Screen",
    is_excel: gridCols.length > 0,
    header_fields: {},
    grid_fields: {}
  };

  headerCols.forEach(c => {
    exportData.header_fields[c.ColumnName] = {
      column_name: c.ColumnName,
      label_ar: c.arColumnLabel,
      label_en: c.enColumnLabel,
      control_type: c.InsertType || "input",
      is_required: Boolean(c.IsRquired),
      lookup_model: c.LookupModel || null,
      dom_selector: `[formcontrolname='${c.ColumnName}'], #${c.ColumnName}`
    };
  });

  gridCols.forEach(c => {
    exportData.grid_fields[c.ColumnName] = {
      column_name: c.ColumnName,
      label_ar: c.arColumnLabel,
      label_en: c.enColumnLabel,
      control_type: c.InsertType || "input",
      is_required: Boolean(c.IsRquired),
      lookup_model: c.LookupModel || null,
      dom_selector: `[formcontrolname='${c.ColumnName}'], #${c.ColumnName}`
    };
  });

  copy(JSON.stringify(exportData, null, 2));
  console.log("✅ Copied screen metadata to clipboard in Co-Pilot format!", exportData);
})();
