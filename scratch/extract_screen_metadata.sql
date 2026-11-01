-- ==============================================================================
-- DynamicPro ERP: Universal Metadata Extractor for Co-Pilot Catalog
-- Database: DynamicPro ERP Database (SQL Server)
-- Usage: Run in SSMS or Azure Data Studio. Output is formatted as JSON.
-- ==============================================================================

-- ==============================================================================
-- الخيار 1: استخراج كافة شاشات النظام الـ 821 شاشة دفعة واحدة (Universal All-Screens Export)
-- لا يوجد أي شرط PageID IN (...) لاستخراج كافة شاشات وحقول النظام بالكامل
-- ==============================================================================
SELECT 
    PageID,
    ColumnName,
    arColumnLabel,
    enColumnLabel,
    InsertType,
    IsRquired,
    IsGeneral,
    ColOrder,
    IsHidden,
    LookupModel
FROM dbo.ListSetupuser
WHERE (IsHidden = 0 OR IsHidden IS NULL)
  AND PageID IS NOT NULL
ORDER BY PageID, IsGeneral DESC, ColOrder ASC
FOR JSON PATH, ROOT('screen_columns');

-- ==============================================================================
-- الخيار 2: استخراج موسع يربط اسم الشاشة والموديول (مع جدول ListSetups إن وجد)
-- ==============================================================================
/*
SELECT 
    u.PageID,
    s.PageName,
    s.Module,
    u.ColumnName,
    u.arColumnLabel,
    u.enColumnLabel,
    u.InsertType,
    u.IsRquired,
    u.IsGeneral,
    u.ColOrder,
    u.LookupModel
FROM dbo.ListSetupuser u
LEFT JOIN dbo.ListSetups s ON u.PageID = s.PageID
WHERE (u.IsHidden = 0 OR u.IsHidden IS NULL)
  AND u.PageID IS NOT NULL
ORDER BY u.PageID, u.IsGeneral DESC, u.ColOrder ASC
FOR JSON PATH, ROOT('screen_columns');
*/

-- ==============================================================================
-- الخيار 3: للاختبار التجريبي على شاشات محددة فقط (مثل الشاشات الـ 5 الأولى)
-- ==============================================================================
/*
SELECT 
    PageID,
    ColumnName,
    arColumnLabel,
    enColumnLabel,
    InsertType,
    IsRquired,
    IsGeneral,
    ColOrder,
    IsHidden,
    LookupModel
FROM dbo.ListSetupuser
WHERE PageID IN (289, 290, 7158, 311, 112)
  AND (IsHidden = 0 OR IsHidden IS NULL)
ORDER BY PageID, IsGeneral DESC, ColOrder ASC
FOR JSON PATH, ROOT('screen_columns');
*/
