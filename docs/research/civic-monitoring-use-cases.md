# Who could use contextual civic monitoring

Research checked 2026-10-30. This is a workflow-informed scenario catalog, not market validation, a list of existing customers or an implementation commitment. All people, organizations, objectives and events in the examples are invented. Primary sources support the workflow; the proposed Matter use and expected judgments are our inference.

The [structured catalog](../../examples/civic/purpose-comparison/use-case-catalog.json) is planning material, not an evaluator packet or held-out labels. It does not modify the twelve-release rehearsal or broaden MAT-082 acceptance beyond the two-objective capture slice.

## Primary workflow evidence

- **S1: [USAC E-Rate competitive bidding](https://www.usac.org/e-rate/applicant-process/competitive-bidding/28-day-waiting-period/)** — Schools/libraries and suppliers must distinguish posting, bid deadlines, allowable contract dates and substantive amendments. Access: `opened_primary_page`.
- **S2: [Overland Park development review](https://codes.opkansas.org/municipal-code/doc-view.aspx?ajax=0&secid=5207)** — Zoning changes have hearings and notice processes; a preliminary plan is not interchangeable with every later approval. Access: `indexed_primary_page`.
- **S3: [NC Broadband rights of way](https://www.ncbroadband.gov/technical-assistance/playbook/policy-broadband/rights-way)** — Broadband projects depend on easements, local permissions and rights-of-way coordination. Access: `opened_primary_page`.
- **S4: [Grants.gov eligibility](https://www.grants.gov/learn-grants/grant-eligibility)** — Eligible categories include governments, tribes, school districts, housing authorities and nonprofits; each opportunity has its own conditions. Access: `opened_primary_page`.
- **S5: [EPA public comment opportunities](https://www.epa.gov/publicnotices/how-find-dockets-and-other-public-comment-opportunities)** — Dockets, proposed/final rules, environmental reviews and pesticide decisions offer distinct participation opportunities. Access: `opened_primary_page`.
- **S6: [KCC public comments](https://www.kcc.ks.gov/public-comments-frequently-asked-questions)** — Utility rate and siting comment deadlines may precede the evidentiary hearing. Access: `opened_primary_page`.
- **S7: [GSA solicitation research](https://www.gsa.gov/sell-to-government/step-2-compete-for-a-contract/research-active-solicitations?topnav=sell-to-government)** — Contractors can research active public solicitations; opportunity fit differs from a general industry mention. Access: `indexed_primary_page`.
- **S8: [LA Metro participation](https://www.metro.net/projects/public-participation-plan-development/)** — Public participation covers fares, service adjustments, transit projects and equity programs. Access: `opened_primary_page`.
- **S9: [DOL construction contract tools](https://www.dol.gov/agencies/whd/government-contracts/construction/tools)** — Construction procurement uses project-relevant wage determinations, published through SAM.gov. Access: `indexed_primary_page_open_403`.
- **S10: [FEMA flood map updates](https://msc.fema.gov/msccontent/Flood_Hazard_Mapping_Updates_Overview_Fact_Sheet.pdf)** — Map revisions and effective-map status can matter to specific properties; preliminary information is not automatically effective. Access: `indexed_primary_excerpt_only`.

Direct fetch of the FEMA product page and DOL tools page was denied (403); FEMA uses only the indexed official excerpt above and DOL its indexed primary page. SAM direct access also failed; GSA guidance supplies the procurement basis. Overland Park migrated its commission page, whose current text is sparse; the official code/its indexed passage supplies the notice-stage basis. No missing source is treated as reviewed in full.

## Illustrative users and scenarios

### School board / superintendent

**Invented example:** Willow School Board. Prepare school connectivity policy and hearing decisions, separate from vendor selection. Workflow basis: S1.

- Development: A committee recommends a connectivity policy and publishes a hearing notice.
- Useful capture: Digest the proposal and hearing opportunity; retain recommendation-only status.
- Stay quiet: Routine mention of broadband in acknowledgements; an unchanged agenda reprint.
- Correction: A corrected notice moves the hearing; correct the actual prior captured date.
- Contrast: District technology supplier needs an open procurement, so policy discussion alone stays quiet.

### School district IT / purchasing

**Invented example:** Willow District IT. Track approved network procurement opportunities, material bid amendments and deadlines. Workflow basis: S1.

- Development: An actual request for network services is published with a submission deadline.
- Useful capture: Inspect the service scope and explicit dates; capture a fitting solicitation or amendment.
- Stay quiet: Connectivity policy recommendation without a solicitation; award close-out for an old purchase.
- Correction: An amendment changes eligible equipment or deadline; do not treat the minimum waiting period as the bid deadline.
- Contrast: The school board may care about policy even before an actionable solicitation exists.

### Land developer / project manager

**Invented example:** Prairie Infill Partners. Track access, density and hearing changes affecting the approved Northfield project. Workflow basis: S2.

- Development: A planning recommendation changes access conditions on the project and schedules a hearing.
- Useful capture: Capture the changed condition/opportunity; keep final approval unresolved.
- Stay quiet: Another city uses the same case number; unrelated rezonings; repeated staff boilerplate.
- Correction: A later source corrects the parcel or hearing date; distinguish that from reversing final approval.
- Contrast: An adjacent neighborhood group watches traffic/affordability consequences rather than entitlement speed.

### Real estate agent / brokerage

**Invented example:** Meadow Homes Advisory. Track verified land-use and access changes around an opted-in listing portfolio. Workflow basis: S2, S10.

- Development: A published zoning or map notice specifically affects an approved property scope.
- Useful capture: Capture the source stage and potentially relevant change for professional review.
- Stay quiet: County-wide real-estate headlines; a preliminary map presented as already effective; another client portfolio.
- Correction: Withdraw a previously captured property match if an amendment shows it covered another parcel.
- Contrast: A developer may favor greater density while an individual buyer only needs access/hazard implications; do not infer either stance.

### Technology company / public affairs

**Invented example:** Cedar Cloud Systems. Track interoperability requirements and qualified public procurement opportunities. Workflow basis: S1, S7.

- Development: An agency opens a consultation on interoperability; later it issues a relevant solicitation.
- Useful capture: Keep the consultation and procurement as distinct useful developments with explicit next steps.
- Stay quiet: Company-name mentions, congratulatory speeches, unrelated IT awards or close-outs.
- Correction: Correct an earlier captured new-grant/new-contract claim when the source is only existing-program close-out.
- Contrast: A privacy coalition can support interoperability while opposing biometric mandates in the same proposal.

### Broadband cooperative / infrastructure lead

**Invented example:** Tallgrass Fiber Cooperative. Track rights-of-way, conduit access and permits for an approved service-area build. Workflow basis: S3.

- Development: A proposed right-of-way ordinance changes permit procedures in the build corridor.
- Useful capture: Capture material procedure changes and comment timing; keep proposal versus effective permission distinct.
- Stay quiet: General broadband praise; ordinances outside the build; archived identical permit language.
- Correction: A corrected route attachment removes a segment from scope; refresh pending relevance and cite the amendment.
- Contrast: A resident association follows disruption and restoration schedules, not provider build economics.

### Housing nonprofit / grant lead

**Invented example:** Common Ground Housing. Find eligible housing-program opportunities and changes affecting a submitted application. Workflow basis: S4.

- Development: A notice opens a housing grant and specifies eligible applicants and a deadline.
- Useful capture: Capture possible eligibility with cited limitations; send to the assigned grant lead for review.
- Stay quiet: Awards already made; close-out of an existing grant; a program restricted to another applicant type.
- Correction: An amendment excludes the organization type; correct the previous opportunity capture, without declaring legal eligibility.
- Contrast: A housing authority and a nonprofit may have different eligibility for the same notice.

### Tribal government / program officer

**Invented example:** Riverbend Tribal Programs. Track infrastructure funding and consultation opportunities relevant to approved public projects. Workflow basis: S4, S5.

- Development: A notice specifies a tribal-eligible program or a consultation affecting a public project.
- Useful capture: Capture the relevant opportunity and actual response deadline for the responsible office.
- Stay quiet: Generic tribal keywords; other communities projects; inferred sensitive cultural locations.
- Correction: Correct a grant-match if revised eligibility or geography excludes this project.
- Contrast: A nearby municipality may be eligible under a different track; never copy private tribal rationale across audiences.

### Utility customer / consumer group

**Invented example:** County Energy Consumers. Track rate/siting changes and comment opportunities affecting approved customer classes. Workflow basis: S6.

- Development: A docket notice opens comments and sets a deadline before its hearing.
- Useful capture: Capture the comment cutoff, proposed impact and uncertainty, separately from the hearing.
- Stay quiet: Utility-name mentions in unrelated cases; unchanged filings; a proposal described as an adopted rate.
- Correction: A revised tariff changes the applicable class; correct the earlier client implication.
- Contrast: An industrial customer may care about demand charges while household customers care about residential provisions.

### Manufacturer / plant operations

**Invented example:** Plainview Manufacturing. Track industrial tariff, access and operating-policy changes for the approved plant. Workflow basis: S6, S5.

- Development: A proposed tariff changes industrial demand charges or a permit docket changes an operating condition.
- Useful capture: Capture the matching provision and review window; do not estimate costs without approved consumption data.
- Stay quiet: Residential-only rate changes; unrelated permits; another plant with a similar name.
- Correction: A correction limits the tariff to another service class; retract the prior matching implication.
- Contrast: The same utility docket may be quiet for a nonprofit on a different tariff.

### Construction contractor / estimator

**Invented example:** Flint Works Construction. Track fitting solicitations, bid amendments and referenced wage-determination revisions. Workflow basis: S7, S9.

- Development: A bid amendment changes the required work or referenced wage determination.
- Useful capture: Capture the material amendment and explicit deadline for estimator review.
- Stay quiet: Unrelated contract awards; narrative rewording with identical requirements; an inapplicable geographic schedule.
- Correction: A replacement amendment restores the prior deadline; preserve both versions and what was actually captured.
- Contrast: A subcontractor may care only about a particular trade package, not every prime-contract update.

### Transit rider / disability advocate

**Invented example:** Accessible Routes Coalition. Track proposed service changes that affect approved accessible-route connections. Workflow basis: S8.

- Development: A transit board proposes a service adjustment and opens public input.
- Useful capture: Capture affected connections and participation dates; separate proposal from adopted timetable.
- Stay quiet: Bus references outside selected routes; duplicated survey reminders; unrelated capital-project branding.
- Correction: A corrected map restores a connection previously shown removed; correct the prior consequence.
- Contrast: A nearby employer follows shift access while the coalition follows accessible transfers.

### Watershed or environmental group

**Invented example:** Clear Creek Watershed. Track permit/rule changes affecting the approved watershed and comment opportunities. Workflow basis: S5.

- Development: A public docket opens on a discharge or infrastructure proposal in scope.
- Useful capture: Capture a substantive provision and response window with cited evidence gaps.
- Stay quiet: Environment keywords outside scope; identical filings; draft described as final authorization.
- Correction: Correct the scope if a new map locates the discharge in another watershed.
- Contrast: A farm cooperative may evaluate water availability while a conservation group evaluates habitat effects.

### University / research administrator

**Invented example:** Regional Mobility Lab. Find program opportunities matching the labs approved research and applicant status. Workflow basis: S4.

- Development: A notice opens a research opportunity with institution-specific eligibility.
- Useful capture: Capture a potential fit and actual submission milestone for grants-office review.
- Stay quiet: Awards/close-outs; opportunities restricted to another institution type; generic research mentions.
- Correction: An amendment changes cost-share or eligibility; refresh the pending result and preserve prior communicated limits.
- Contrast: A small business collaborator can have a different eligibility result from the university.

### Local journalist / editor

**Invented example:** Civic Ledger Desk. Track substantive reversals, decisions and corrections in an approved reporting beat. Workflow basis: S2, S5.

- Development: A recommendation is followed by a recorded vote, or an official correction changes a material assertion.
- Useful capture: Capture the changed stage and source citation for editorial verification.
- Stay quiet: Repeated stories derived from one source; unnamed actor stance inferred from a group vote.
- Correction: Correct the desk capture when an official source revises the earlier claim; do not silently overwrite the chronology.
- Contrast: A public-affairs client wants action implications; an editor wants verified changes, not client advocacy.

### Resident / parent / neighborhood volunteer

**Invented example:** Personal objective without client. Track a chosen school or neighborhood issue and useful participation opportunities. Workflow basis: S2, S8.

- Development: A hearing or route proposal affects the residents explicitly saved objective.
- Useful capture: Capture a meaningful change or actionable deadline according to that persons preferences.
- Stay quiet: Every keyword match; other neighborhoods; private contact details; already handled unchanged notices.
- Correction: A correction of an earlier captured date remains useful even after the person marked the original notice handled.
- Contrast: Two people in the same neighborhood can have different priorities and receive different treatments.

## How this informs the bounded adapter

The variety tests one shared boundary: explicit purpose/scope/provision positions, authorized evidence, independent audience context, actual conveyed baseline and current output guards. Organization type alone never supplies relevance or stance. An approved objective is not a fake civic record. A source recommendation is not final approval, a close-out is not a new grant, and a notice already available about a future event is usable before that event; evidence not yet available is not.

First executable slice reuses the school-policy versus procurement contrast already in MAT-081 fixtures. Land-use, grants, utility and transit scenarios remain candidate later episodes; adding them does not promise a new crawler feed, legal classifier, UI or provider qualification. Every episode must eventually have independently reviewed source/authority/scope/availability and output expectations before it supports accuracy claims.

The same article can be relevant to two opposing clients for different reasons, or quiet for both. Duplicates remain quiet unless material content or the applicable conveyed baseline changes. Corrections must refer to actual previously captured material and preserve uncertainty. Real/private evidence still requires actual MAT-072 controls. The later custom LLM writer remains separate.
