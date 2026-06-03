# Agent research playbook

This file optimizes future runs for AI agents. It is operational, not explanatory:
use it to decide what to do next and when to stop.

## Batch default
- Default mode: accelerated batch.
- Target: exactly 25 new companies and exactly 25 selected LPRs.
- Required contact gate for every row: verified direct person-level LPR email plus
  verified LPR mobile or verified named landline extension for the same LPR.
- Output: overwrite `output/new_contacts.xlsx`.
- Do not send email until `scripts/run_accelerated_outreach.py --stage prepare`
  has appended memory and the user explicitly confirms sending.

## Read order
1. `input/property_profile_mitino.md`
2. `input/tenant_fit_rubric.md`
3. `input/tenant_fit_config.json`
4. `input/mcp_research_stack.md`
5. `input/output_schema.md`
6. `validation/blocked_generic_emails.txt`
7. `validation/suspicious_email_patterns.txt`
8. `validation/suspicious_phone_patterns.txt`
9. `output/found_contacts_memory.jsonl`
10. Existing `output/research_notes/*.md` for reusable domain/person/source patterns.

## MCP usage
- Use Perplexity, Exa, Brave, SerpApi and Yandex Search for discovery and source
  finding.
- Use Firecrawl for source extraction, site maps, PDFs and evidence capture.
- Use search MCP outputs as leads only. Final contacts must still be verified on
  official or strongly corroborated public sources.
- Prefer Yandex Search for Russian-language person/email/phone/PDF queries.
- Prefer Firecrawl when an official site is hard to navigate or has many PDFs.

## Candidate funnel
1. Load seed list first.
2. Remove anything already present in `output/found_contacts_memory.jsonl`.
3. Run a fast tenant-fit pass using `input/tenant_fit_rubric.md`.
4. For `PASS_STRONG` and strong `PASS_CONDITIONAL` candidates, search for LPR and
   direct contacts.
5. Reject fast when the candidate is warehouse-only, fulfilment-only, heavy
   production, price-sensitive workshop, pure office, pure software or pure resale.
6. Continue broader discovery only after seed candidates are exhausted or cannot
   produce the required 25 contact-qualified rows.

## High-yield discovery surfaces
Use sources likely to expose both target companies and named contacts:
- official staff/contact/team pages in electronics, instrumentation, medtech,
  telecom hardware, robotics, service-center and light-assembly segments;
- official PDFs, catalogues, annual reports, product brochures and requisites pages;
- expo and conference exhibitor/speaker pages for electronics, industrial
  automation, robotics, medtech, lab equipment, telecom, import substitution,
  service and technical operations;
- technopark, SEZ, industrial park, innovation cluster and Moscow industry resident
  lists;
- procurement supplier cards and public contract documents that name managers and
  direct work contacts;
- professional/admin communities such as `proffadmin.ru` for administrative,
  office-infrastructure and facilities roles;
- official Telegram/company social channels only as verification/search surfaces,
  not as substitutes for person-level contacts.

## Search order per company
1. Confirm official site and legal entity.
2. Confirm segment fit and premium-rent plausibility.
3. Identify the highest-priority evidenced LPR by role ladder.
4. Search official site and PDFs for named person + direct email/phone.
5. Search event/speaker/exhibitor pages.
6. Search procurement, registry, filings and reputable business sources.
7. Search professional profiles, interviews, public communities and Telegram surfaces.
8. Only after direct-source search fails, derive candidate corporate emails as search
   hypotheses; never package a hypothesis without public verification.

## Query blocks
Use Russian and English variants. Combine brand, legal entity, person name and role.

Segment/fit:
- `[brand] производство разработка оборудование Москва`
- `[brand] технопарк производство офис сервис`
- `[brand] лаборатория сборка сервисный центр`
- `[brand] выручка сотрудники производство контракт`

LPR:
- `[brand] административный директор`
- `[brand] директор по административным вопросам`
- `[brand] исполнительный директор`
- `[brand] заместитель генерального директора`
- `[brand] HR директор`
- `[brand] технический директор`
- `[brand] финансовый директор`
- `[brand] директор по эксплуатации`
- `[brand] директор по развитию`
- `[brand] директор производства`

Direct contacts:
- `"[person]" "[company]" email`
- `"[person]" "[company]" e-mail`
- `"[person]" "[company]" почта`
- `"[person]" "[company]" моб`
- `"[person]" "[company]" доб.`
- `"[person]" "[company]" extension`
- `site:proffadmin.ru "[person]" "[company]"`
- `site:*.pdf "[person]" "[company]"`
- `"[person]" "[company]" t.me OR Telegram`

## Research note minimum
Every processed candidate needs enough notes to resume quickly:
- fit label from `input/tenant_fit_rubric.md`;
- one-line reason why the company fits or is rejected;
- official site and legal entity evidence;
- chosen LPR and why higher-priority roles were or were not found;
- source trail for email and phone;
- explicit reason if a candidate was rejected from accelerated mode.

## Packaging commands
After 25 rows are ready:
```bash
python3 scripts/format_new_contacts.py --workbook output/new_contacts.xlsx
python3 validation/validate_new_contacts.py --workbook output/new_contacts.xlsx --expected-rows 25
python3 scripts/run_accelerated_outreach.py --stage prepare
```

Only after the user confirms sending:
```bash
python3 scripts/run_accelerated_outreach.py --stage send
```
