import json, re
from collections import Counter
from pathlib import Path

root = Path("e:/Mazen/EgyDynamic/LMS_CO_Pilot")

# 1. Inspect pageAttribute 289, pdetail, Listsetups for Purchases (289)
page_attrs = json.loads((root / "pageAttribute.json").read_text(encoding="utf-8-sig"))
p289_attr = [x for x in page_attrs if x.get("PageID") == 289]
print("=== pageAttribute 289 ===")
print(json.dumps(p289_attr, ensure_ascii=False, indent=2))

pdetails = json.loads((root / "pdetail.json").read_text(encoding="utf-8-sig"))
list_names_289 = set()
for item in p289_attr:
    for pa in item.get("pa", []):
        if pa.get("HeaderListName"):
            list_names_289.add(pa["HeaderListName"].strip())
        for pd in pa.get("pd", []):
            if pd.get("DetailListName"):
                list_names_289.add(pd["DetailListName"].strip())

pdet_289 = [d for d in pdetails if str(d.get("ListName", "")).strip() in list_names_289]
print("\n=== pdetail matches for 289 ===")
for d in pdet_289:
    print({k: d.get(k) for k in ["DetailId", "ListName", "TableName", "Primary", "ControllerName", "TableSrc", "EditSrc", "DataSourceApi"]})

listsetups = json.loads((root / "Listsetups.json").read_text(encoding="utf-8-sig"))
ls_289 = [
    x for x in listsetups
    if x.get("PageId") == 289 or str(x.get("ListName", "")).strip() in list_names_289
]
print(f"\n=== Listsetups matches for 289 ({len(ls_289)} rows) ===")
target_cols = {"SupplierID", "StoreID", "ProjectID", "CurrancyID", "ExchangePrice", "POSetting", "SafeAccounId", "CostItemId"}
for x in ls_289:
    col = str(x.get("ColumnName", "")).strip()
    if col in target_cols or x.get("DroModel"):
        print({k: x.get(k) for k in ["PageId", "ListName", "ColumnName", "arColumnLabel", "InsertType", "DroModel", "DroValue", "DroText", "TableName"] if x.get(k) is not None})

# Check ANY pdetail entries with non-null DataSourceApi or ControllerName related to Supplier/Store/Project
print("\n=== pdetail samples for Supplier / Store / Project / DroModels ===")
dro_models = {x.get("DroModel") for x in ls_289 if x.get("DroModel")}
for d in pdetails:
    if d.get("ListName") in dro_models or d.get("TableName") in dro_models or d.get("DataSourceApi"):
        if d.get("ListName") in dro_models or d.get("TableName") in dro_models or "Supplier" in str(d.get("ListName")) or "Store" in str(d.get("ListName")) or "Project" in str(d.get("ListName")):
            print({k: d.get(k) for k in ["ListName", "TableName", "Primary", "ControllerName", "DataSourceApi"]})

# 2. Count Q5: how many times lookup matched > 1 option in ALL session logs
print("\n=== Q5: LOOKUP OPTIONS COUNT ANALYSIS ACROSS ALL LOGS ===")
logs = sorted((root / "logs" / "erp_sessions").glob("session_*.log"))
multi_option_events = []
all_lookup_events = Counter()
by_term_counts = {}

for p in logs:
    for ln, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if "ng-select matched option" in line or "ng-select ambiguous" in line or "ambiguous" in line.lower():
            idx = line.find(" | {")
            if idx != -1:
                try:
                    data = json.loads(line[idx + 3 :])
                    term = data.get("term") or data.get("attemptedValue") or "?"
                    sel = data.get("targetSelector") or "?"
                    cnt = data.get("optionsCount")
                    chosen = data.get("selected")
                    all_lookup_events[(term, sel, cnt)] += 1
                    if cnt is not None and cnt > 1:
                        multi_option_events.append((p.name, ln, term, sel, cnt, chosen))
                    by_term_counts.setdefault(term, []).append(cnt)
                except Exception:
                    pass

print(f"Total multi-option (>1 match) lookup events across all 15 logs: {len(multi_option_events)}")
for ev in multi_option_events:
    print(f"  * {ev[0]}:L{ev[1]} | term='{ev[2]}' | target={ev[3]} | optionsCount={ev[4]} | selected='{ev[5]}'")

print("\nAll lookup (term, target, optionsCount) summary:")
for (term, sel, cnt), freq in all_lookup_events.most_common():
    print(f"  {freq}x | term='{term}' | target={sel} | optionsCount={cnt}")

