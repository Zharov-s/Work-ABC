# Codex project pack for direct LPR contact research

This package is designed to help Codex produce a strict, high-confidence Excel workbook of named decision-makers and direct public professional contacts for a fixed list of target companies.

## Goal
Create:
- `output/mitino_target_companies_lpr_direct_contacts.xlsx`
- `output/new_contacts.xlsx` for accelerated 25-company batches
- `output/evidence_log.csv`
- `output/research_notes/*.md`

## Core rule
This project is about **direct named LPR contacts**.  
It is **not** acceptable to fill direct-contact columns with:
- generic corporate emails,
- general office numbers,
- switchboards without a named extension,
- guessed addresses or guessed extensions.

## First files to read
1. `AGENTS.md`
2. `input/property_profile_mitino.md`
3. `input/tenant_fit_rubric.md`
4. `input/tenant_fit_config.json`
5. `input/agent_research_playbook.md`
6. `input/mcp_research_stack.md`
7. `input/codex_prompt_mitino_lpr_direct_contacts_strict.md`
8. `input/output_schema.md`
9. `scoring/contact_quality_scoring.md`

## Main workflow
1. Read the target companies from `input/target_companies.csv`
2. Apply the tenant-fit gate before deep contact work
3. Research only companies that fit the asset or need a documented rejection
4. Store interim research in `output/research_notes/`
5. Append evidence to `output/evidence_log.csv`
6. Fill the workbook template
7. Run validation:
   - `python validation/validate_contacts.py`
8. Fix issues until validation passes

## Accelerated batch + send workflow
When the user asks for the accelerated 25-company batch and wants the mailing completed in the same request:
1. Research and approve exactly 25 **new** companies with one qualified LPR each
2. Package them into `output/new_contacts.xlsx`
3. Prepare the batch:
   - `python3 scripts/run_accelerated_outreach.py --stage prepare`
4. Tell the user that the batch is ready and ask whether to send it
5. Only after confirmation, send it:
   - `python3 scripts/run_accelerated_outreach.py --stage send`

The helper supports three stages:
- `--stage prepare` formats `output/new_contacts.xlsx`, runs accelerated validation with the expected batch size, appends the batch into `output/found_contacts_memory.jsonl`, and stops for user confirmation
- `--stage send` sends the Pro-email campaign in safe batches of at most 29 total recipients per email, including `s.zharov@abcentrum.ru` in each batch
- `--stage full` runs both stages in one command, but use it only when the user explicitly wants no confirmation pause

For the default 25-contact batch, the safe send split is one email: `25` target recipients + `s.zharov@abcentrum.ru`.
Reports are written to `output/last_email_send_report.json` and `output/last_accelerated_pipeline.json`.

## Key folders
- `input/` — targets, schema, prompt
- `output/` — workbook template, research notes, evidence log
- `validation/` — validation logic and blocked patterns
- `tasks/` — runbooks for Codex
- `.codex/` — project-scoped MCP research server configuration
- `.agents/skills/` — narrow skills for research, validation, packaging
- `scoring/` — scoring rubric for contact quality and completeness

## Notes
- Blank direct-contact cells are allowed when no direct public data exists.
- A row is not complete without a source URL and a verification note.
- Use the strongest official source available.
- Accelerated mode is stricter: rows with blank email or blank phone channel are not shippable.
- A contact-rich company is still rejected if it is warehouse-only, fulfilment-only,
  heavy production, pure office/software/retail, or too price-sensitive for the A+
  Mitino object.
