---
name: excel-packaging
description: Use when building or updating the final Excel workbook so it exactly matches the required schema and formatting.
---

# excel-packaging

## Goal
Maintain a clean final `.xlsx` file with the exact required structure.

## Required workbook
- path: `output/mitino_target_companies_lpr_direct_contacts.xlsx`
- sheet: `Direct LPR Contacts`

## Required columns
1. Legal entity name
2. Website
3. Decision-maker full name
4. Decision-maker title
5. Corporate email
6. Mobile phone
7. Work phone + extension
8. Telegram niknames
9. Telegram-group
10. Source URL
11. Verification note

## Rules
- do not rename columns
- do not change sheet name
- do not add extra columns beyond the approved schema
- keep one row per company
- the workbook may include seed companies plus newly discovered companies
- maintain formatting directly in the single final workbook; no separate Excel template is used
- use blank cells for unknown direct contacts
- store `Telegram niknames` as verified personal LPR nicknames, not URLs or notes
- store `Telegram-group` as verified official company/group/channel handles, not URLs or notes
- for discovery progress, count only rows with a verified person-level contact; `Telegram-group` alone does not satisfy the active discovery stop rule

## Final step
Run validation after packaging.

## Accelerated batch note
When the task is using accelerated batch delivery via `output/new_contacts.xlsx`:
- keep the exact accelerated six-column schema from `input/output_schema.md`
- set every column width to `30`
- enable wrapped text for all cells so text stays within cell boundaries
- do not ship the batch unless all 25 rows contain both a verified LPR email and a verified LPR phone channel, unless the user explicitly changed the batch size
