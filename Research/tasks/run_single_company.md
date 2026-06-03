# Run single-company research

## Goal
Research exactly one seed or newly discovered company end-to-end and update all project outputs consistently.

## Steps
1. Read `AGENTS.md`
2. Read `input/property_profile_mitino.md`, `input/tenant_fit_rubric.md`, `input/tenant_fit_config.json`, and `input/output_schema.md`
3. If the company comes from `input/target_companies.csv`, read that seed row; if it is newly discovered, document why it fits VRI `6.3` / `6.12` and premium-rent economics for the asset
4. Create/update `output/research_notes/<slug>.md`
5. Apply the tenant-fit gate and reject fast if the company is warehouse-only, fulfilment-only, heavy production, pure office/software/retail, or cheap-workshop demand
6. Verify website and legal entity
7. Confirm the company is a commercially plausible tenant for the asset
8. Select the best named LPR using the priority ladder, with strongest attention to administrative, HR, technical, executive, finance, and deputy-GD roles
9. Extract only direct person-level contacts and keep official Telegram channels/groups separate from personal Telegram nicknames; when searching admin/office leaders, explicitly check профильные sources like `proffadmin.ru`, plus news and interview materials
10. Update:
   - `output/mitino_target_companies_lpr_direct_contacts.xlsx`
   - `output/evidence_log.csv`
   - `output/research_notes/<slug>.md`
11. Run validation and fix issues affecting the row

## Guardrails
- Never use generic email in the direct email column
- Never use general office number without a named extension
- Leave blank instead of guessing
- Do not keep a company just because it has a contact; it must fit the asset
