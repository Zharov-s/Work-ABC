# Run full research

## Goal
Produce the final workbook, evidence log, and research notes for all target companies.

## Steps
1. Read `AGENTS.md`
2. Read `input/property_profile_mitino.md`
3. Read `input/tenant_fit_rubric.md`
4. Read `input/tenant_fit_config.json`
5. Read `input/agent_research_playbook.md`
6. Read `input/codex_prompt_mitino_lpr_direct_contacts_strict.md`
7. Read `input/output_schema.md`
8. Read `scoring/contact_quality_scoring.md`
9. Load `input/target_companies.csv`
10. For each company:
   - create or update `output/research_notes/<slug>.md`
   - apply the tenant-fit gate before deep contact research
   - verify official website
   - verify legal entity
   - confirm premium-rent plausibility or document rejection
   - identify the best named LPR
   - search for direct corporate email
   - search for direct mobile
   - search for named work phone + extension
   - append evidence to `output/evidence_log.csv`
   - update the workbook row
11. Run `python validation/validate_contacts.py`
12. Fix all blocking issues
13. Repeat validation until pass

## Mandatory completion condition
Do not stop after partial progress.
Do not leave rows missing source URL or verification note.
Do not insert generic contacts into direct-contact columns.

## Accelerated batch completion condition
If the run is in accelerated mode:
1. Package the approved batch into `output/new_contacts.xlsx`
2. Run `python3 validation/validate_new_contacts.py --workbook output/new_contacts.xlsx --expected-rows 25`
3. Run `python3 scripts/run_accelerated_outreach.py --stage prepare`
4. Tell the user the batch is ready and ask whether to send it
5. Only after confirmation, run `python3 scripts/run_accelerated_outreach.py --stage send`
