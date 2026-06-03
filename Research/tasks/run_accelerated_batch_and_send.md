# Run accelerated batch and send

## Goal
Complete the full one-request workflow:
1. find 25 new qualified companies with one LPR each
2. package them into `output/new_contacts.xlsx`
3. append the batch into memory
4. stop and ask the user whether to send the prepared batch
5. only after confirmation, send the Pro-email campaign in safe batches

## Required sequence
1. Read `input/property_profile_mitino.md`, `input/tenant_fit_rubric.md`, `input/tenant_fit_config.json`, and `input/agent_research_playbook.md`
2. Process `input/target_companies.csv` first
3. Reject weak-fit candidates before deep contact research
4. Expand discovery until exactly 25 new companies meet both tenant-fit and accelerated contact rules
5. Keep evidence in `output/evidence_log.csv`
6. Keep one research note per processed company in `output/research_notes/`
7. Package the approved batch into `output/new_contacts.xlsx`
8. Run:
   - `python3 validation/validate_new_contacts.py --workbook output/new_contacts.xlsx --expected-rows 25`
9. Run:
   - `python3 scripts/run_accelerated_outreach.py --stage prepare`
10. Tell the user the batch is ready and ask whether to send it
11. Only after confirmation, run:
   - `python3 scripts/run_accelerated_outreach.py --stage send`

## What the helper does
`scripts/run_accelerated_outreach.py` will:
- in `prepare` stage: format `output/new_contacts.xlsx`, re-run strict accelerated validation, append the batch into `output/found_contacts_memory.jsonl`, and stop for confirmation
- in `send` stage: send the Pro-email campaign from `Pro-email/`
- enforce the safe send cap of 29 total recipients per email, including `s.zharov@abcentrum.ru`
- for the default 25-contact batch, send one batch of `25 + 1`
- write send reports for audit and resume support

## Resume options
If the workbook is already valid and only the mailing stage needs to be retried:
- resend everything in dry-run mode:
  - `python3 scripts/run_accelerated_outreach.py --stage send --skip-validation --dry-run-email`
- resend only a chosen batch range:
  - `python3 scripts/run_accelerated_outreach.py --stage send --skip-validation --start-batch 1 --end-batch 1`
