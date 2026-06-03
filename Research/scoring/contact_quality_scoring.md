# Contact quality scoring

Use this scoring model to assess each completed row and to prioritize QA.

## Total score: 100

## Asset-fit gate
Before numeric scoring, confirm that the company is actually in scope for the property.
Read `input/property_profile_mitino.md` and `input/tenant_fit_rubric.md` first.

A row is in scope only if the company plausibly fits:
- VRI `6.3` Light Industry and/or VRI `6.12` Scientific-production activity
- premium-rent economics for an A+ Moscow promtechnopark

Strong indicators include:
- electronics, instrumentation, automation, server/telecom/PAK equipment, medtech, photonics, robotics, drones, scientific-production, light assembly, pilot production, lab + office + showroom logic
- federal-brand service centers with workshop + office + client reception
- fashion / beauty / consumer-goods companies only when showroom + office + light assembly / samples / repair / quality control is evidenced
- staff accessibility, metro, client visits, image and Moscow location visibly matter to the operating model
- evidence of revenue, funding, scale, contracts, group backing, or an existing industrial / technopark footprint

Out-of-scope indicators include:
- heavy / hazardous manufacturing
- classic warehouse, pallet storage, warehousing-only, logistics-only, e-commerce fulfilment or dark-store use
- pure retail / horeca
- pure software / consulting with no physical product, lab, or R&D footprint
- cheap workshop demand with no office-client contour
- obviously budget-constrained tenants that are unlikely to sustain the site economics

If the company fails this gate, the row should not be treated as a valid outbound target even if the contact data is strong.

Recommended fit labels in research notes:
- `PASS_STRONG`
- `PASS_CONDITIONAL`
- `REJECT_SEGMENT`
- `REJECT_ECONOMICS`
- `REJECT_CONTACT`
- `HOLD`

### 1. Legal entity confidence — 15 points
- 15: verified on official site or official requisites page
- 10: verified via high-confidence official PDF or public filing
- 5: only registry-level evidence, no official confirmation
- 0: unclear or conflicting

### 2. LPR priority fit — 15 points
- 15: highest-priority publicly evidenced LPR selected, even if direct-contact cells remain blank
- 10: role is acceptable but priority fit is slightly weaker and explicitly justified
- 5: lower-priority person used because higher-priority candidates were not evidenced after broad search
- 0: row was downgraded to an easier-to-contact employee despite evidence of a higher-priority LPR

### 3. Named person confidence — 15 points
- 15: person and role shown on official site or official document
- 12: person confirmed on official event/speaker page plus one other source
- 8: person confirmed on high-confidence public professional profile plus one company-linked source
- 0: person not adequately supported

### 4. Direct corporate email quality — 18 points
- 18: real direct personal corporate email on official source
- 15: real direct personal corporate email on strong public source tied to the company
- 10: derived candidate corporate email verified by strong public corroboration after direct-source search failed
- 0: blank
- fail: generic mailbox used
- fail: guessed/pattern-only email used without public verification
- fail: stale or non-working email used

### 5. Direct mobile quality — 8 points
- 8: direct public mobile shown on official source
- 5: direct public mobile shown on strong secondary source
- 0: blank
- fail: shared/general number used
- fail: stale or non-working mobile used

### 6. Work phone + extension quality — 8 points
- 8: public switchboard + named extension on official source
- 5: strong public secondary source
- 0: blank
- fail: no named extension
- fail: city office number or switchboard used without a public named extension
- fail: stale or non-working work phone used

### 7. Telegram personal/group quality — 8 points
- 8: verified personal public Telegram nickname tied to the named person on official or strongly corroborated public sources; any company/group handle is correctly stored in `Telegram-group`
- 5: verified personal public Telegram nickname on strong non-official sources with corroboration, or verified official company/group handle correctly stored in `Telegram-group`
- 0: blank
- fail: unverified, fake, or stale Telegram handle used
- fail: official company/group handle stored in `Telegram niknames`
- fail: personal LPR handle stored in `Telegram-group`

### 8. Search breadth and source quality — 8 points
- 8: official site plus broader public web searched; row supported by official or corroborated strong public sources; research notes show breadth when needed; broader market discovery was used when the seed list alone was insufficient
- 5: official site plus at least one broader source class searched and used well
- 2: acceptable source quality but search breadth appears partial
- 0: search scope too narrow or unclear

### 9. Verification note quality — 3 points
- 3: concise and factual
- 1: vague
- 0: missing

### 10. Evidence logging completeness — 2 points
- 2: evidence log entry complete
- 0: missing evidence log

## Quality bands
- 85–100: strong row
- 70–84: usable but review recommended
- 50–69: weak row, review required
- below 50: incomplete / likely invalid

## Fail conditions
Any of the following overrides numeric score and forces review failure:
- company is clearly outside VRI `6.3` / `6.12` fit or clearly implausible for premium-rent economics
- generic email in direct email column
- general office phone without a named extension
- guessed email pattern used as final data
- stale or non-working contact used as final data
- lower-priority employee selected solely because that person had a direct contact
- unverified Telegram handle or messenger nickname used as proof
- official company/group Telegram handle stored in the personal Telegram column
- personal Telegram nickname stored in the Telegram-group column
- missing source URL
- missing named person
