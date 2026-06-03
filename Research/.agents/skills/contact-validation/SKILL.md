---
name: contact-validation
description: Use when checking that workbook rows contain only valid direct person-level contacts and no forbidden generic data.
---

# contact-validation

## Goal
Prevent invalid direct-contact rows from reaching the final workbook.

## Check for
- generic inboxes in `Corporate email`
- guessed or suspicious email formats
- mobile field containing general office numbers
- work phone field missing a named extension
- `Telegram niknames` containing unverified, malformed, or obviously non-personal handles
- `Telegram-group` containing malformed handles or personal nicknames
- stale or obviously non-working contact values
- companies that are clearly off-scope for the asset and should be reviewed before staying in the workbook
- missing source URL
- missing verification note
- missing named person

## Inputs
- workbook
- evidence log
- blocked and suspicious pattern files

## Outputs
- list of blocking issues
- list of warnings for manual review

## Rules
- blank is allowed
- generic is not allowed
- suspicious patterns require warning or manual review
- only verified current/working contacts may stay in the workbook
- no row is complete without a source URL and note
- track progress toward the 50-company discovery goal using only person-level contact fields; `Telegram-group` alone does not count
