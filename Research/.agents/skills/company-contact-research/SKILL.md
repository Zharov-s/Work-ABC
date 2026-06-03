---
name: company-contact-research
description: Use when researching one or more target companies to verify legal entity, identify the best named decision-maker, and collect only direct public person-level contacts.
---

# company-contact-research

## Goal
Produce a valid row for the direct-contact workbook and supporting evidence, whether the company comes from the seed list or from broader market discovery.

## Inputs
- `input/target_companies.csv`
- `input/property_profile_mitino.md`
- `input/tenant_fit_rubric.md`
- `input/tenant_fit_config.json`
- `input/agent_research_playbook.md`
- `input/output_schema.md`
- `validation/blocked_generic_emails.txt`
- `validation/suspicious_email_patterns.txt`
- `validation/suspicious_phone_patterns.txt`

## Outputs
- workbook row updated
- evidence log updated
- per-company research note updated

## Core rules
- Prefer official sources
- Do not stop at official sources when they are sparse; widen to the public web, PDFs, events, registries, professional profiles, official social surfaces, профильные admin/community sources such as `https://proffadmin.ru/`, news/interviews, and Telegram when relevant
- Use `input/target_companies.csv` as the mandatory seed list, not as the final search ceiling
- Only keep companies that plausibly fit VRI `6.3` and/or `6.12` and are commercially credible for a premium-rent A+ promtechnopark
- Reject warehouse-only, e-commerce fulfilment, pallet storage, heavy production,
  pure office/software/retail, and cheap-workshop demand before deep contact research
- Prioritize electronics, instrumentation, server/telecom/PAK equipment, medtech,
  laboratory equipment, robotics, drones, clean assembly, service-center and
  showroom + light-assembly use cases
- Use the role priority ladder
- Never downgrade the LPR just because a lower-priority employee has a public direct contact
- Never enter guessed emails
- Never guess extensions
- Only add contacts that are publicly evidenced as current and working
- Candidate corporate emails and Telegram handles may be used only as search leads until publicly verified
- Keep personal LPR Telegram nicknames separate from official company/group/channel handles
- Leave direct-contact cells blank when needed
- Always provide source URL and verification note
- Stop broader discovery after 50 suitable companies with at least one verified person-level contact have been found; `Telegram-group` alone does not count toward that cap

## Workflow
1. read `input/property_profile_mitino.md` and `input/tenant_fit_rubric.md`
2. verify whether the company is a credible fit for the asset, especially under VRI `6.3` / `6.12` and premium-rent economics
3. assign a fit label in the research note: `PASS_STRONG`, `PASS_CONDITIONAL`, `REJECT_SEGMENT`, `REJECT_ECONOMICS`, `REJECT_CONTACT`, or `HOLD`
4. verify official website
5. verify legal entity
6. prioritize searches for administrative directors, executive directors, deputy general directors, HR directors, technical directors, and financial directors before lower-priority fallbacks
7. identify highest-priority named LPR
8. first search for real public direct corporate emails, direct public mobiles, named work phones + extensions, and verified personal Telegram nicknames of that LPR
9. separately capture verified official company/group/channel Telegram handles in `Telegram-group`
10. search official pages, PDFs, events, procurement, registries, public professional profiles, профильные admin/community sources such as `proffadmin.ru`, news/interview sources, and Telegram/public-messenger surfaces when relevant
11. only if stronger direct-source channels fail, search direct corporate email via plausible naming-pattern hypotheses and verify before use
12. verify any Telegram handle or messenger nickname before it influences the row
13. reject stale / dead / reassigned contacts
14. if the seed list is insufficient, discover and append additional companies from exhibitor lists, technopark/cluster resident lists, rankings, portfolios, and sector media
15. log evidence
16. update workbook
17. mark issues for QA if confidence is low

## Done when
- company is a credible tenant for the asset, not just a company with a contact trail
- research note contains a fit label and short fit rationale
- named LPR selected
- role priority was not sacrificed for easier contactability
- all direct contact fields either supported or blank
- any Telegram nickname entered for the LPR is personal, verified, and current
- any `Telegram-group` value entered is an official verified company/group/channel handle
- source URL present
- verification note present
