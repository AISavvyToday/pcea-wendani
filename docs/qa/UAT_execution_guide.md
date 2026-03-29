# UAT / QA Script (1:1 Client Mapping)

## Objective
This script enforces one-to-one mapping between the original client requirement list and execution evidence with pass/fail traceability.

## Source of truth
1. Paste each original client requirement verbatim into `docs/qa/UAT_master_checklist.csv` under **Original Client Requirement (verbatim)**.
2. Keep one row per original requirement item (`CL-###`) to preserve 1:1 traceability.
3. Do not merge/split client items unless the client approves a rewritten list.

## Execution workflow per checklist item
For every row in `UAT_master_checklist.csv`, fill these fields during test execution:
- **Setup Data**: exact records, org scope, term/date, and prerequisites.
- **Actions**: click path and actions taken.
- **Expected Result**: what should happen from the original item.
- **Actual Result**: what actually happened.
- **Pass/Fail**: Pass / Fail / Blocked / Not Run.
- **Evidence Path/Link**: screenshot and export artifacts.

## Mandatory evidence packs
Store evidence under `docs/qa/evidence/staging/<ITEM-ID>/`.

Each item should include at least:
- Dashboard screenshot(s)
- Report screenshot(s)
- Unmatched table screenshot(s) where applicable
- Clubs screenshot(s) where applicable
- Bulk stream screenshot(s) where applicable
- Export files used for reconciliation (CSV/XLSX/PDF)

Suggested naming:
- `<ITEM-ID>_01_setup.png`
- `<ITEM-ID>_02_action.png`
- `<ITEM-ID>_03_result.png`
- `<ITEM-ID>_report_export.xlsx`

## Cross-report total validation protocol
Use `XREP-001` row in the checklist and execute:
1. Fix a single term/date filter pair.
2. Capture totals from all related dashboard cards and reports.
3. Record a reconciliation table in `docs/qa/evidence/exports/XREP-001_reconciliation.xlsx`.
4. Mark Pass only when totals match or an approved exception is documented in Notes.

## Delete/Restore/Purge lifecycle + KPI validation
Use `LIFE-001` to `LIFE-003` rows:
1. Capture KPI/report baseline values.
2. Delete record and verify KPI/report deltas.
3. Restore and verify values return to baseline.
4. Purge and verify permanent removal from KPI/report totals.

## Staging smoke test protocol
Use real org-scoped staging data and cover critical paths:
- dashboard load
- key reports load/export
- unmatched table load/action
- clubs page and related flow
- bulk stream page and flow

Log run details in `docs/qa/staging_smoke_execution_log.md`:
- timestamp
- tester
- org/account used
- flow executed
- result
- server log check outcome (confirm no 5xx/tracebacks)

## Terminology signoff checklist
Record signoff outcome for each:
- **Educational Activities**
- **Other Income** in dashboard totals
- **New students strict current term**

For each terminology item:
- Add screenshot evidence where term appears.
- Capture signoff date, approver name, and decision in checklist Notes.
