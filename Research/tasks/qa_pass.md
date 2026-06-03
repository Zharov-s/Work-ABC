# QA pass

## Purpose
Perform a final quality review after research is complete.

## Required checks
1. Every target company has exactly one row in the workbook
2. Column names and order match the schema exactly
3. Named person exists in every row
4. Source URL exists in every row
5. Verification note exists in every row
6. Tenant-fit label is present in the research note and is not a weak/rejected segment
7. Premium-rent plausibility is evidenced
8. `Corporate email` contains no generic aliases
9. `Work phone + extension` contains no general number without extension
10. Blank direct-contact fields are justified by the research note
11. Evidence log exists and contains entries for every company
12. Suspicious emails/phones are reviewed manually

## Accelerated batch checks
For `output/new_contacts.xlsx` specifically:
1. The workbook has exactly 25 filled rows unless the user explicitly changed the batch size
2. Every row has both a direct verified LPR email and a phone channel
3. No company or website duplicates `output/found_contacts_memory.jsonl`
4. `python3 validation/validate_new_contacts.py --workbook output/new_contacts.xlsx --expected-rows 25` passes
5. The batch is ready for `python3 scripts/run_accelerated_outreach.py --stage prepare`
6. After user confirmation, the send stage can run via `python3 scripts/run_accelerated_outreach.py --stage send`

## Manual review focus
- rows with blank direct-contact fields
- rows sourced from non-official pages
- rows using CEO/founder fallback
- rows with only one evidence source
