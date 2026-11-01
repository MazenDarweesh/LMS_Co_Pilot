# DynamicPro ERP — Metadata Discovery Reference & Technical Analysis

**Document Type:** Technical Discovery Reference & Architecture Specification  
**Classification:** Host ERP Internal Engine Specifications  
**Status:** Approved & Verified with ERP Engineering Team  
**Date:** 2026-10-25  
**Target Systems:** DynamicPro ERP (Backend .NET Core & Frontend Angular) & LMS Co-Pilot (Python AI Engine)

---

## 1. Executive Overview & Significance of the Discovery

The response from the DynamicPro ERP team confirms an extraordinary architectural breakthrough: **DynamicPro is a 100% Metadata-Driven Form Engine**. 

There are zero hardcoded templates or rigid HTML layouts in the host system. Every screen, form, dropdown, and grid is dynamically rendered at runtime from centralized metadata stored in SQL Server and loaded into memory via Angular services.

This discovery completely transforms our implementation roadmap:
* We do **not** need to manually scrape or reverse-engineer hundreds of forms.
* We do **not** need to guess HTML IDs or CSS selectors.
* We now have direct access to the exact database column names (`ColumnName`), Arabic labels (`arColumnLabel`), input types (`InsertType`), mandatory flags (`IsRquired`), and data-binding scopes (`IsGeneral` for Header vs Line Items).
* We have two complementary pathways to read this metadata: **offline via SQL / REST API** and **instantaneous (0ms) in-memory inspection via the active Angular component instance**.

---

## 2. Core Metadata Database Schema in SQL Server

The core metadata governing all input forms is maintained in the following schema:
* **Primary Table:** `ListSetups`
* **User-Scoped View:** `ListSetupuser` (filters columns based on active user security permissions)

### Detailed Column Specifications:

* **`ColumnName` (The Core Key):**
  * Represents the exact Angular `formControlName`, the database column, and the payload dictionary key.
  * Examples: `VendorID`, `StoreID`, `DocDate`, `CustomerID`, `Amount`, `EmpId`.
  * In Angular components, this key is bound directly to `excelObject[col]` (for documents/invoices) or `dataObject[col]` (for generic master records).

* **`arColumnLabel` and `enColumnLabel`:**
  * The human-readable visible labels in Arabic and English.
  * Used by the AI to match natural speech (e.g. "المورد", "المخزن", "تاريخ المستند", "الموظف").

* **`InsertType` (The Input Control Type):**
  Defines the exact widget rendered in the DOM:
  * `'dropdown'`: Searchable dropdown menu (wrapped `@ng-select/ng-select`).
  * `'input'` or `'text'`: Single-line text input field.
  * `'number'` or `'integer'`: Numeric input box with step/formatting.
  * `'date'`: DatePicker calendar input.
  * `'account'`: Specialized hierarchical Account Tree Selector modal.
  * `'checkbox'`: Boolean checkbox switch (`true` / `false`).
  * `'textarea'`: Multi-line text comment area.

* **`IsRquired` (Mandatory Validation Flag):**
  * Note on spelling: In the database schema, this column is spelled with a missing 'e' (`IsRquired`).
  * Value `1`: Field is mandatory; saving without this field is blocked by the ERP validator.
  * Value `0` or `NULL`: Field is optional.

* **`InsertVisable` (Form Visibility Flag):**
  * Value `1`: Field is rendered and visible in the creation form.
  * Value `0`: Field is an internal audit or system field (e.g., `CreatedBy`, `CreatedAt`), which must not be requested from the user.

* **`IsGeneral` (Header vs Grid Scope Flag — Critical for Transactional Documents):**
  * Applicable to screens where `Excel = true` (Invoices, Movements, Journal Entries).
  * Value `1`: Master / Header field. Stored on the parent document object (`excelObject`).
  * Value `0`: Detail / Line Item field. Stored within individual row objects (`this.rows[]`).

* **`DroModel`, `DroValue`, `DroText` (Dropdown Lookup Relations):**
  * `DroModel`: The entity or lookup table source (e.g. `Customer`, `Store`, `Vendor`, `Item`).
  * `DroValue`: The primary key / foreign key value field (e.g. `CustId`, `StoreID`).
  * `DroText`: The display label column (e.g. `CustNameAr`).

* **`sort`:**
  * Defines the visual tab order and sequence of fields within the form.

---

## 3. Host ERP REST API Endpoints (`StructureController.cs`)

The host ERP exposes endpoints to retrieve form metadata programmatically over HTTP without accessing SQL Server directly.

### Endpoint A: Page Attribute Discovery
* **HTTP Method & Route:** `GET Structure/getPageAttribute/{pageId}`
* **Model Contract:** Returns `PageAttribute` object:
  * `ListName`: The identifier for the master/header field setup.
  * `TableName`: The primary underlying database table.
  * `Excel`: Boolean flag (`true` indicates a transactional document with a grid like Purchases 289; `false` indicates a standard flat master form).
  * `PageDetail[]`: Array of detail specifications for grid lines (each detail entry contains its own `ListName` for child rows).

### Endpoint B: Column List Definition
* **HTTP Method & Route:** `GET Structure/getListSetups/{listName}`
* **Model Contract:** Returns an array of `ListDto` objects containing the full field definitions (`ColumnName`, `InsertType`, `IsRquired`, `arColumnLabel`, `DroModel`, etc.).

---

## 4. SQL Export Scripts for Database Extraction

The ERP team provided two ready-to-run queries to extract form specifications directly from SQL Server.

### Query 1: Single Screen Deep Extraction (Example for Purchases Page 289)

```sql
DECLARE @PageID INT = 289; 

SELECT 
    p.PageID,
    p.PageName                                 AS [ScreenKey],
    p.PageDisplay                              AS [ScreenNameAr],
    p.EnName                                   AS [ScreenNameEn],
    CASE 
        WHEN ls.ListName = pa.ListName THEN 'Header (Master)'
        ELSE 'Grid / Lines (Detail)'
    END                                        AS [Section],
    ls.ColumnName                              AS [FormControlName],
    ls.arColumnLabel                           AS [LabelAr],
    ls.enColumnLabel                           AS [LabelEn],
    ls.InsertType                              AS [ControlType],
    CAST(ISNULL(ls.IsRquired, 0) AS BIT)       AS [IsMandatory],
    CAST(ISNULL(ls.InsertVisable, 0) AS BIT)   AS [IsVisibleInForm],
    ISNULL(ls.IsGeneral, 0)                    AS [IsGeneralHeader],
    ls.DroModel                                AS [LookupTable],
    ls.DroValue                                AS [LookupValueField],
    ls.DroText                                 AS [LookupTextFieldAr],
    ls.sort                                    AS [FieldOrder]
FROM pages p
INNER JOIN PageAttribute pa ON p.PageID = pa.PageId
LEFT JOIN PageDetail pd ON pd.PageAttributeId = pa.AttributeId
INNER JOIN ListSetups ls ON (ls.ListName = pa.ListName OR ls.ListName = pd.ListName OR ls.PageId = p.PageID)
WHERE p.PageID = @PageID
  AND (ls.InsertVisable = 1 OR ls.IsRquired = 1)
ORDER BY 
    Section DESC, 
    ls.sort ASC;
```

### Query 2: Batch Export for Top Operational Screens

```sql
SELECT 
    p.PageID,
    p.PageName                                 AS [ScreenKey],
    p.PageDisplay                              AS [ScreenNameAr],
    CASE 
        WHEN ls.ListName = pa.ListName THEN 'Header'
        ELSE 'DetailRows'
    END                                        AS [FormScope],
    ls.ColumnName                              AS [FormControlName],
    ls.arColumnLabel                           AS [LabelAr],
    ls.InsertType                              AS [Type],
    CAST(ISNULL(ls.IsRquired, 0) AS BIT)       AS [IsRequired],
    ls.DroModel                                AS [DropdownSource]
FROM pages p
INNER JOIN PageAttribute pa ON p.PageID = pa.PageId
LEFT JOIN PageDetail pd ON pd.PageAttributeId = pa.AttributeId
INNER JOIN ListSetups ls ON (ls.ListName = pa.ListName OR ls.ListName = pd.ListName OR ls.PageId = p.PageID)
WHERE p.PageName IN ('Purchases', 'SalesDetails', 'JournalEntry', 'StoreMovement', 'Loans', 'Borrow')
   OR p.PageID IN (289, 290, 311, 112, 7158)
ORDER BY p.PageID, FormScope DESC, ls.sort ASC;
```

---

## 5. Instantaneous In-Memory Bridge Extraction (0ms Client-Side Access)

Beyond SQL and REST, the ERP team highlighted an extraordinary capability available directly in the browser's JavaScript execution context: **The active screen already possesses its full metadata in memory**.

Because Angular components extend `MasterBaseComponent`, the active component instance holds an RxJS BehaviorSubject named `columnList`:

```javascript
// Extract required metadata for active screen in 0ms via browser console or CDP evaluate:
(function() {
    const activeComp = window.DynamicERP?.getActiveComponentInstance?.();
    if (!activeComp) return [];
    
    const columns = activeComp.columnList?.getValue?.() || [];
    return columns
        .filter(c => c.InsertVisable === 1 || c.IsRquired === 1)
        .map(c => ({
            name: c.ColumnName,
            label: c.arColumnLabel,
            type: c.InsertType,
            isMandatory: Boolean(c.IsRquired),
            isHeader: Boolean(c.IsGeneral),
            lookup: c.DroModel
        }));
})();
```

---

## 6. Technical Commentary & Architectural Implications

### A. Perfect Alignment with Angular Reactive Forms
Knowing that `ColumnName` matches the Angular `formControlName` exactly means our CDP script does not need complex CSS selector guessing. We can target:
`ng-select[formcontrolname='${ColumnName}'], input[formcontrolname='${ColumnName}']`
Or even better:
`activeComp.dataObject[col] = val` or `activeComp.excelObject[col] = val`.

### B. Header vs Grid Boundary Solved (`IsGeneral`)
The historic ambiguity of whether a field belongs to the document header or to the transaction lines is completely resolved by `IsGeneral`:
* `IsGeneral == 1`: Treat as a top-level document field.
* `IsGeneral == 0`: Treat as a line-item column within the grid row.

### C. Dropdown Model Resolution (`DroModel`)
Knowing `DroModel` allows the AI to understand semantic relationships immediately. For instance, if `ColumnName` is `AccID` and `DroModel` is `Accounts`, the AI knows to prompt the user for an account name from the chart of accounts rather than a generic text string.
