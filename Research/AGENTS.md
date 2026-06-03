# AGENTS.md

## Project objective
Build a high-confidence outbound-tenant workbook for named decision-makers (LPRs) at companies that are genuinely suitable for the Promtechnopark Mitino project: a premium class A+ urban light-industrial / R&D property in Moscow.

The required output is **not** a company contacts list.  
The required output is a workbook of **named LPRs** with **direct public corporate email**, **direct public mobile phone**, **named work phone + extension**, and verified Telegram data split into personal vs group/company fields when such details are publicly available.

`input/target_companies.csv` is the priority seed universe, not the final ceiling.
If the seed list does not produce enough suitable contactable targets, you must discover and add additional companies that fit the asset.

## Read these files first
1. `input/property_profile_mitino.md`
2. `input/tenant_fit_rubric.md`
3. `input/tenant_fit_config.json`
4. `input/agent_research_playbook.md`
5. `input/mcp_research_stack.md`
6. `input/codex_prompt_mitino_lpr_direct_contacts_strict.md`
7. `input/output_schema.md`
8. `scoring/contact_quality_scoring.md`
9. `validation/blocked_generic_emails.txt`
10. `validation/suspicious_email_patterns.txt`
11. `validation/suspicious_phone_patterns.txt`

## Agent operating principle
Optimize the workflow for fast AI execution:
- First apply the asset-fit gate from `input/tenant_fit_rubric.md`.
- Reject weak-fit companies before deep LPR contact research.
- Spend deep research time only on companies that plausibly need a premium Moscow
  production-client headquarters.
- Treat `input/property_profile_mitino.md` as the compact property brief and re-check
  the public site when pricing, address, availability, or timing may have changed.
- For accelerated mode, a candidate is useful only after both gates pass:
  `PASS_STRONG` or well-justified `PASS_CONDITIONAL` tenant fit, plus verified direct
  LPR email and verified LPR phone channel.

## Deliverables
You must produce all of the following:
- `output/mitino_target_companies_lpr_direct_contacts.xlsx`
- `output/new_contacts.xlsx` for accelerated 25-company batches
- `output/evidence_log.csv`
- `output/research_notes/` with one markdown note per processed company, including newly discovered ones
- a validator pass with no blocking errors

## Persistent contact memory
Maintain a separate append-only internal memory file for all companies and LPR contacts found during the project.

- File path: `output/found_contacts_memory.jsonl`
- Purpose: long-term cumulative memory of all discovered companies and contacts, including contacts that may be delivered later in separate batch files.
- This file is append-only: do not delete historical records from it.
- Add one JSON object per line so the file remains easy to search, diff, append, and process programmatically.
- Use it as the cumulative project memory before starting fresh discovery, deduplication, or batch packaging.

## Accelerated batch mode
In addition to all existing requirements, prohibitions, and evidence standards above, use the following accelerated operating mode for future discovery runs unless the user explicitly says otherwise:

- In one execution batch, find **exactly 25** new target companies and **exactly 25** LPR contacts.
- Each of the 25 companies must have one selected named LPR that follows the existing role-priority ladder.
- In accelerated batch mode, **every one of the 25 companies must have both**:
  - a direct verified person-level LPR email, and
  - either a direct verified LPR mobile phone, or a verified city office phone with a named extension tied to that LPR.
- If a company does not have both the required email and the required phone channel, it does **not** count toward the batch of 25.
- Do not weaken fit, verification, anti-generic-email, anti-guessing, or source-quality rules in order to hit the batch size.
- If a candidate company fails the asset-fit or evidence rules, it does not count toward the batch of 25.
- Prefer sources and workflows that increase throughput without lowering quality:
  - first mine high-yield official contact/team/staff pages,
  - then official PDFs and legal/contact subpages,
  - then event/exhibitor/speaker pages,
  - then procurement/registry corroboration,
  - then public professional/public-messenger corroboration when needed.
- Reuse already confirmed domain/person/entity patterns from previous research notes before starting a fresh broad search.
- Search and evaluate candidates in parallel where possible, but only write out the final batch after each company passes the existing evidence rules.

### Accelerated output rule
For this accelerated mode, do **not** append new findings into `output/mitino_target_companies_lpr_direct_contacts.xlsx`.

Instead, create a separate downloadable Excel file:
- `output/new_contacts.xlsx`

The user-facing result for each accelerated batch must be:
- a new file at `output/new_contacts.xlsx`
- a link to that file in the chat

### Accelerated batch schema
`output/new_contacts.xlsx` must contain exactly these columns in this exact order:
1. `Наименование`
2. `Сайт`
3. `ФИО`
4. `Должность`
5. `Емайл`
6. `Мобильный телефон или городской с добавочным`

### Accelerated population rules
- `Наименование` must contain the legal entity name, for example `ООО "Ромашка"`.
- `Сайт` must contain the official main website/domain.
- `ФИО` must contain the selected named LPR.
- `Должность` must contain the selected LPR title.
- `Емайл` must contain only a direct verified person-level work email. Leave blank if not found.
- `Мобильный телефон или городской с добавочным` must contain either:
  - a direct verified business mobile, or
  - a verified work phone with a named extension tied to the selected LPR.
  If neither exists, leave blank.
- In accelerated batch mode, blank values are **not allowed** in `Емайл` and `Мобильный телефон или городской с добавочным`.
- Only ship the batch when all 25 rows contain both required channels.

### Accelerated file-handling rule
- Overwrite `output/new_contacts.xlsx` on each new accelerated batch unless the user explicitly asks to preserve prior batches separately.
- Do not recolor or modify old workbook rows during accelerated batch delivery.
- Continue maintaining `output/research_notes/` and `output/evidence_log.csv` when useful for auditability and reuse, but the primary batch deliverable is `output/new_contacts.xlsx`.
- Format `output/new_contacts.xlsx` on every accelerated batch using these layout rules:
  - every column width must be set to `30`
  - text wrapping must be enabled for all cells
  - cell content must remain visually inside the cell bounds and not overflow into adjacent columns

### Accelerated outreach rule
After the 25-company accelerated batch is fully formed, formatted, and validated, do **not** send immediately.

- First append the new batch into `output/found_contacts_memory.jsonl`.
- Then stop and tell the user that the batch is ready for outreach.
- Ask the user explicitly whether to send the prepared batch from `output/new_contacts.xlsx`.
- Only after the user explicitly confirms should you switch to `Pro-email/` and complete the email send.
- Use the `Pro-email` project instructions and templates; do not invent a separate email workflow outside that folder.
- Split the recipients into batches with **no more than 29 total recipients per send**, counting the mandatory copy address.
- Add `s.zharov@abcentrum.ru` to **every** send batch.
- For 25 target emails, the safe default is one batch:
  - batch 1: 25 target recipients + `s.zharov@abcentrum.ru`
- The accelerated send helpers should write a machine-readable send report so the run can be audited or resumed if needed.

## Success criteria
A successful run means:
- every company from `input/target_companies.csv` is processed first,
- the workbook may include additional discovered companies beyond the seed list,
- discovered companies are added only when they fit the asset and improve the real outbound target pool,
- in the legacy full-workbook flow, search continues until 50 suitable companies with at least one verified person-level contact are found, then stops,
- in the default accelerated batch flow, search continues until 25 suitable companies with the required email + phone channels are found, then stops,
- each row contains the highest-priority publicly evidenced named LPR rather than a lower-level but easier-to-contact substitute,
- direct contact columns contain only person-level direct contacts and verified personal public Telegram nicknames of the LPR when available,
- `Telegram-group` contains only verified official company/group/channel Telegram handles,
- research is not limited to the official website and covers the broader public web when needed,
- any non-obvious direct contact used in the row was verified as real before it influenced the workbook,
- generic corporate inboxes are never used in `Corporate email`,
- general office numbers are never used unless tied to the named person by a public extension,
- blank cells are used when direct data is not publicly available,
- every row has a meaningful source URL and verification note,
- evidence is logged.

For the discovery stop rule, a company counts only if at least one of these fields is populated with a verified person-level contact:
- `Corporate email`
- `Mobile phone`
- `Work phone + extension`
- `Telegram niknames`

`Telegram-group` alone does not count toward the discovery stop rule.

## Asset-fit and affordability rule
Promtechnopark Mitino is not cheap inventory. The property is positioned as a premium class A+ boutique promtechnopark for light industrial, office, showroom, and mixed formats, with shell & core delivery, long-term lease structure, and rates that require financially credible tenants.

Use the project site `https://promtechnopark-mitino.ru/` and
`input/property_profile_mitino.md` as the commercial truth source. The public site
currently positions the object as:
- Moscow, Baryshiha 37a
- boutique promtechnopark class A+ for light industrial, office, showroom, service,
  commercial and mixed formats
- total area about 11,776.20 m2
- production area about 6,662.08 m2
- office area about 3,400.93 m2
- 1.5 MW power
- 70 parking spaces
- 6 gates, including 3 with dock levellers
- 2 lifts and 2 freight lifts up to 4 t
- ceiling height up to 8 m and floor load up to 5 t/m2
- shell & core delivery
- commissioning planned for Q3 2026
- production rent about 18,000 RUB/m2/year before VAT
- office rent from about 28,000 RUB/m2/year before VAT
- operating expenses up to 3,000 RUB/m2/year before VAT, plus utilities by consumption
- VAT currently stated as 22% above the rates
- Rubytech is named as a key tenant that leased about 4,200 m2 for PAK production expansion

Only target companies whose real operating profile plausibly fits VRI:
- `6.3` Light Industry
- `6.12` Scientific-production activity

Strong-fit examples:
- electronics and electronic assembly
- instrumentation and industrial automation
- server, telecom, network, data-center and PAK hardware
- medtech, diagnostics, laboratory, and pilot production
- microelectronics, photonics, optics, and laser systems
- robotics, mechatronics, drones, smart hardware
- contract manufacturing, service plus assembly, demo/showroom plus technical back office tied to a physical-product business
- federal-brand service centers needing workshop + office + client reception
- fashion, beauty, and consumer-goods brands only when they need showroom + office + light assembly / samples / repair / quality-control workflows
- companies combining R&D, engineering, testing, light production, and customer demo functions
- companies for which staff accessibility, metro, client visits, image and Moscow location are important

Weak-fit or out-of-scope examples:
- heavy, dirty, noisy, or high-hazard production
- bulk warehousing or logistics-only users
- classic warehouse, pallet storage, 3PL, e-commerce fulfilment, dark-store or marketplace-only users
- pure retail, horeca, or office-only occupiers with no light-industrial / scientific-production logic
- pure software or consulting firms with no hardware, laboratory, engineering, or pilot-production footprint
- tenants that only need a cheap shop floor with no office-client contour
- very small or obviously price-sensitive tenants that are unlikely to sustain premium rent economics

When deciding whether a company can afford the object, prefer businesses with public evidence of scale, such as:
- material revenue, profit, funding, or group backing
- government, enterprise, or export contracts
- multi-site operations, manufacturing footprint, or significant headcount
- premium office / technopark / industrial occupancy already visible in the market
- clear need for a Moscow production, lab, showroom, service, or mixed industrial-office presence

## Hard rules
### Never do these things
- Never enter a guessed email pattern into the workbook.
- Never infer or fabricate a mobile number.
- Never infer or fabricate an extension.
- Never treat a hypothesized Telegram handle or messenger nickname as real without verification.
- Never put an official company Telegram channel or group handle into `Telegram niknames`.
- Never put a personal LPR Telegram nickname into `Telegram-group`.
- Never add a contact that public evidence suggests is obsolete, dead, archived, reassigned, or non-working.
- Never downgrade the named LPR to a lower-priority employee only because that person has an easier public contact trail.
- Never put `info@`, `sales@`, `office@`, `support@`, `mail@`, `contact@`, `zakaz@`, `hello@`, `admin@`, `reception@`, `pr@`, `press@`, `media@`, `marketing@`, `hr@`, `career@`, `corp@` or similar generic inboxes into the `Corporate email` column.
- Never put a general company switchboard, reception line, hotline, sales desk, or city office number into `Work phone + extension` without a public named extension tied to the LPR.
- Never use private/leaked contact data.
- Never use low-trust people-search or broker sites as sole evidence.
- Never add a company to the workbook if it is clearly outside VRI `6.3` / `6.12` fit or clearly inconsistent with premium-rent economics.
- Never leave a company unprocessed.
- Never silently skip a row.

### Expanded search rule
Research is not limited to official websites. For every company, search across the broad public web when needed, including:
- official website sections and subdomains,
- official PDFs, brochures, catalogs, requisites, legal pages, and embedded documents,
- professional association sites and communities relevant to administrative / office / facilities leadership, including `https://proffadmin.ru/` when searching administrative directors and adjacent office-infrastructure leaders,
- official event, speaker, exhibitor, partner, webinar, and conference pages,
- news resources, interviews, editorial profiles, award shortlists, event recap pages, and industry-media mentions,
- procurement portals, public filings, public registry documents, and court / arbitration materials when relevant,
- reputable public professional profiles and official corporate social accounts,
- public Telegram channels, public Telegram handles, and messenger nicknames when they can help verify the person or direct contact.

Search using Russian and English variants, transliterations, legal-entity names, exact person names, role titles, email fragments, phone fragments, and messenger handle fragments.

### Expansion discovery rule
The workbook is not limited to the seed list in `input/target_companies.csv`.

Use the seed list as the mandatory first-pass universe.
After that, if fewer than the active target threshold have been accumulated, continue broader market discovery and append new companies that fit the asset.

Useful discovery sources include:
- exhibitor/speaker lists from industrial and technology events
- resident lists of technoparks, SEZs, industrial parks, and innovation clusters
- import-substitution catalogs and industry rankings
- venture, PE, or corporate portfolio pages
- procurement winners and supplier directories for industrial-tech segments
- media roundups, awards, and sector newsletters covering light industrial and scientific-production companies

Do not keep discovering forever.
Stop adding new companies once the active target threshold has been found:
- `25` for the default accelerated batch flow
- `50` only when the user explicitly asks for the full legacy direct-contact build
Do not add weak-fit companies merely to hit the number.

### Search priority rule
For each named LPR, search in this order:
1. Real public direct corporate emails shown in source material
2. Real public business mobile phones shown in source material
3. Real public city office numbers with a named extension shown in source material
4. Real verified public personal Telegram nicknames tied to the named LPR
5. Real verified official company/group/channel Telegram handles stored separately in `Telegram-group`
6. Only if the above do not yield a usable direct contact, begin candidate corporate-email derivation for the administrative director or other selected LPR

Candidate-email derivation is a fallback search technique, not a first-pass shortcut.
Any derived email may enter the workbook only after public verification under the evidence rules below.

### Corporate email discovery rule
It is allowed to derive a candidate corporate email only as a search hypothesis.
A candidate corporate email is admissible in the workbook only after public verification by:
- one official source that ties the email to the named person, or
- two independent public sources that tie the email to the named person and employer.

Pattern-only reasoning, MX/domain checks, or repetition on low-trust sites are not sufficient.
Generic aliases remain forbidden even if they are public.
Do not add a derived email unless public evidence indicates it is current and working.

### Telegram and messenger verification rule
Telegram or other public messenger handles may be used as a search channel and as corroborating evidence, but they must be verified as real before they influence the workbook.

Treat a handle as verified only when the public evidence shows a credible match between the person, employer, and account, such as:
- the handle is linked from an official or company-controlled source,
- the profile name, username, content, and activity clearly match the named person and company,
- a second independent public source supports the same identity or contact trail.

Write verified public personal Telegram handles of the named LPR only into `Telegram niknames`.
Write verified official company/group/channel Telegram handles only into `Telegram-group`.
If Telegram evidence helped confirm another contact, also log that in research notes and evidence notes.

### Current / working contact rule
Only add contacts that are publicly evidenced as current and usable.
If a source says a number/email no longer works, is archived, or belongs to a former employee, do not add it.
Do not attempt to verify by messaging or emailing the person; rely on current public evidence instead.

### Blank-cell policy
If no direct person-level public contact is found:
- keep the named LPR,
- leave `Corporate email`, `Mobile phone`, and `Work phone + extension` blank as needed,
- leave `Telegram niknames` blank if no verified personal public nickname of the LPR is found,
- leave `Telegram-group` blank if no verified official company/group/channel handle is found,
- explain the gap briefly in `Verification note`.

Blank cells are better than bad data.
Blank cells are also better than replacing the LPR with a lower-priority but more contactable employee.

## Role priority ladder
Use the highest-priority named role that is publicly evidenced, with the strongest emphasis on administrative, HR, technical, executive, finance, and deputy-GD roles:
1. Administrative Director / Director for Administrative Affairs
2. Executive Director / Managing Director
3. Deputy General Director / Vice General Director
4. HR Director / HRD / People Director
5. Technical Director / CTO / Engineering Director
6. Financial Director / CFO / Finance Director
7. Facilities Director / Real Estate Director / Office Infrastructure Director
8. Operations Director / COO
9. Director of Development / Business Development Director
10. Production Director / Manufacturing Director
11. CEO / General Director / Founder / Owner

## Legal entity rule
Use the best-supported current Russian operating legal entity tied to the brand’s production, R&D, service, or HQ operations.

Prefer:
1. Official website / requisites / legal pages
2. Official company PDFs
3. Public filings / government registries / procurement documents
4. Other reputable registries

## Evidence rule
Prefer two independent sources for:
- named person,
- title,
- direct contact.

One official source is enough if the person and direct contact are shown together on an official page or official document.
If Telegram, public messenger data, or a non-official corporate email source is used, prefer at least two independent public signals before treating it as verified.

## Fail-safe against lazy completion
You are not allowed to mark a company “done” if:
- the named LPR was not searched across official pages + open web + official PDFs/events + registries/procurement + public professional/social sources, and Telegram when relevant,
- the row is missing a source URL,
- the row is missing a verification note,
- you used a generic email or generic phone in a direct-contact column,
- you selected a lower-priority employee merely because a higher-priority LPR had no direct public contact,
- you used an unverified corporate-email hypothesis or unverified Telegram handle as if it were proven.

If a large number of rows are blank in direct-contact fields, you must confirm in research notes that you performed the required person-level search and cite where you looked.

## Required workflow
1. Load `input/target_companies.csv` as the seed list.
2. For each seed company, create/update a research note in `output/research_notes/<slug>.md`.
3. Verify that the company plausibly fits VRI `6.3` and/or `6.12` and is commercially plausible for a premium-rent A+ promtechnopark.
4. Research the legal entity, website, named LPR, and direct contacts across official pages, open web, official PDFs, events, registries, public professional profiles, administrative-profession communities such as `proffadmin.ru`, news/interview sources, and Telegram/messenger surfaces when relevant.
5. First search for real public direct emails, mobiles, named work phones + extensions, and verified personal Telegram nicknames tied to that LPR.
6. Separately capture verified official company/group/channel Telegram handles in `Telegram-group` when they are publicly linked from credible sources.
7. Only if those are not found, use candidate corporate emails as search leads until they are publicly verified.
8. Keep the highest-priority evidenced LPR even when direct-contact fields remain blank.
9. After the seed list is processed, measure how many companies already have at least one verified person-level contact field.
10. If that number is below the active target threshold, run broader company discovery for additional high-fit tenants and append them to the workbook, evidence log, and research notes.
11. Stop discovery when the active target threshold has been accumulated:
   - `25` for the default accelerated batch flow
   - `50` only when the user explicitly asks for the full legacy direct-contact build
12. Run `validation/validate_contacts.py`.
13. Fix all blocking errors.
14. Re-run validation until it passes.

For accelerated batch mode, replace the final packaging step with:
12. package the final approved batch into `output/new_contacts.xlsx`
13. run `scripts/format_new_contacts.py --workbook output/new_contacts.xlsx`
14. run `validation/validate_new_contacts.py --workbook output/new_contacts.xlsx --expected-rows 25`
15. fix blocking issues until the accelerated validator passes
16. append the approved batch into `output/found_contacts_memory.jsonl`
17. provide the user a link to `output/new_contacts.xlsx` and explicitly ask whether to send the prepared batch
18. only after the user confirms, run the Pro-email batch sender so the mailing is actually completed from `output/new_contacts.xlsx`
19. confirm the mailing batch was completed

## Output contract
The workbook must match `input/output_schema.md` exactly.
Do not add or remove columns.
Do not rename the sheet when working with the legacy direct-LPR workbook.
For accelerated batch mode, save the output to `output/new_contacts.xlsx`.

## Skills available
- `company-contact-research`
- `contact-validation`
- `excel-packaging`
