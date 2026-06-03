# Output schema

## Primary accelerated batch workbook
- Filename: `output/new_contacts.xlsx`
- Default sheet name: `new_contacts`

## Exact column order
1. `Наименование`
2. `Сайт`
3. `ФИО`
4. `Должность`
5. `Емайл`
6. `Мобильный телефон или городской с добавочным`

## Workbook rules
- Use exactly one sheet for the accelerated batch output
- Do not rename columns
- Do not add columns
- Do not remove columns
- Use one row per company
- Do not create duplicates for the same company / legal entity / website combination
- Only package companies that pass `input/tenant_fit_rubric.md`; the workbook has no
  separate fit column, so the fit label and rationale must live in the research note
  and evidence trail
- Each batch must contain exactly 25 new companies with 25 selected LPRs unless the user explicitly changes the batch size
- In accelerated mode, each of the 25 rows must contain both:
  - a direct verified person-level LPR email
  - and either a direct verified LPR mobile or a verified work phone with a named extension tied to that LPR
- This accelerated batch output replaces direct appends into `output/mitino_target_companies_lpr_direct_contacts.xlsx`
- Set every column width in `output/new_contacts.xlsx` to `30`
- Enable wrapped text for all populated cells so content stays within cell boundaries

## Column rules

### Наименование
- Use the best-supported current Russian operating legal entity
- Prefer full normalized forms such as `ООО "..."`, `АО "..."`, `ПАО "..."`, etc.

### Сайт
- Use the main official website/domain

### ФИО
- Use the highest-priority publicly evidenced relevant LPR
- Do not downgrade to an easier-to-contact lower-priority employee

### Должность
- Use the exact or near-exact publicly evidenced role/title

### Емайл
- Only direct public person-level work email of the named LPR
- Must not be generic
- Must be publicly verified, not guessed from a pattern
- In accelerated batch mode, this field is mandatory for every row

### Мобильный телефон или городской с добавочным
- Allowed values:
  - direct public business mobile of the named LPR
  - or public company phone plus named extension tied to the LPR
- Do not use a general office number without a named extension
- In accelerated batch mode, this field is mandatory for every row

## Legacy note
- The old strict workbook `output/mitino_target_companies_lpr_direct_contacts.xlsx` remains part of project history, but accelerated batch delivery now uses `output/new_contacts.xlsx`.
