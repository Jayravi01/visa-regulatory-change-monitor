# Visa and Regulatory Change Source Register (Module 3)

Document status: Working register - business and governance approval pending  
Technical source of truth: `scraper/sources.py`  
Companion to the Module 1 register (`SOURCE_REGISTER.md` in the Promotions repository).

## Purpose

This register lists the public sources configured for Module 3, why each is
used and what is known about collecting it. It uses the same three states as
Module 1:

1. **Registered** - the source and its business purpose are documented here.
2. **Collected** - a successful snapshot exists for a collection attempt.
3. **Validated** - a human reviewer confirmed the extracted change against its
   evidence, and recorded an impact level with a reason.

Only validated records are suitable for dashboard publication. A successful
HTTP response does not prove extraction is complete, and finding no change on a
page does not prove that nothing changed.

## Governance rules

- Collect public information only.
- Do not bypass logins, CAPTCHAs, paywalls, bot-management challenges or other
  technical controls, and do not render pages in a browser to get past a block.
- Use a low request rate (2 seconds between requests), immutable snapshots and a
  durable log for every attempt.
- Keep requested URL, final URL, timestamp, source identity, evidence and hashes
  with each snapshot.
- Government primary sources take precedence over news or industry summaries.
  Records from `industry` sources stay unpublished until corroborated.
- Record a peer terms-of-use review before enabling a source for recurring
  collection. That sign-off is not represented in code and remains open.

## Module scope (from the client brief)

Track visa, migration, education and regulatory changes that may affect demand
for overseas health insurance: student visa changes, worker visa changes,
temporary visa policy updates, processing times, eligibility changes,
compliance requirements and international student policy announcements.
Dashboard output per record: change summary, effective date, impact assessment,
visa categories affected and source link, with High / Medium / Low alerts.

## Configured sources (all proposed, not yet approved)

| Source ID | Organisation | Group | Role | Public URL | Notes |
| --- | --- | --- | --- | --- | --- |
| `homeaffairs_student_500` | Department of Home Affairs | Government | Policy page | [Student 500](https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500) | Public. Page-level "last updated" is kept; a changed date is a lead, not proof of a rule change |
| `homeaffairs_graduate_485` | Department of Home Affairs | Government | Policy page | [Temporary Graduate 485](https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/temporary-graduate-485) | Public |
| `homeaffairs_processing_times` | Department of Home Affairs | Government | Processing times | [Global visa processing times](https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-processing-times/global-visa-processing-times) | Interactive tool; a plain HTTP snapshot may hold little text and is flagged `possible_client_rendered_page` |
| `homeaffairs_news_archive` | Department of Home Affairs | Government | News listing | [News archive](https://immi.homeaffairs.gov.au/news-media/archive) | Landing page whose items are script-loaded; an HTTP snapshot may contain no items. Registered gap |
| `homeaffairs_student_changes_factsheet` | Department of Home Affairs | Government | Policy document (PDF) | [Changes to student visa applications](https://immi.homeaffairs.gov.au/Visa-subsite/files/changes-to-student-visa-applications-factsheet.pdf) | PDF text extracted with pypdf |
| `studyaustralia_news` | Study Australia | Government | News listing | [News](https://www.studyaustralia.gov.au/en/tools-and-resources/news) | Public listing of dated notices (fee, settings and wage announcements) |
| `education_newsroom` | Department of Education | Government | News listing | [Newsroom](https://www.education.gov.au/newsroom) | Public; items may show no date in the text, so dates will often need reviewer entry |
| `education_esos_changes` | Department of Education | Government | Policy page | [ESOS legislative changes](https://www.education.gov.au/esos-framework/changes-legislative-framework-overseas-students) | Public |
| `fairwork_news` | Fair Work Ombudsman | Government | News listing | [News](https://www.fairwork.gov.au/newsroom/news) | Public; most items are domestic workplace news, so relevance filtering matters |
| `mia_media_releases` | Migration Institute of Australia | Industry | News listing | [Media releases](https://mia.org.au/Web/Web/Public-Resources/Media-Releases-Index.aspx) | Secondary source; corroboration required |

Reachability was checked on 5 October 2026 with a page fetch tool. The pages
listed above returned content except where noted. This is not a terms review,
and it was not a run of the collector. The collector itself has not yet been run
against these live pages by this project.

## Sources named in the brief but not yet registered

| Source | Why not registered | Next step |
| --- | --- | --- |
| Home Affairs ministerial media releases | Landing page returned no release list to the check | Confirm an exact release-listing URL |
| Study Australia (other sections) | News listing registered; policy pages not scoped | Confirm which pages hold standing policy |
| Immigration news portals | Not primary sources; quality varies | Business to nominate named portals and corroboration rules |
| Government media releases (other departments) | Scope not agreed | Business to nominate departments |
| Education agents and migration agents | Belongs mainly to Module 4 | Confirm overlap with Product and Partnership module |

## Operational ownership and review

Add these fields for every approved source before the register is treated as
complete (same as Module 1):

| Field | Required value |
| --- | --- |
| Business owner | Person accountable for relevance and priority |
| Technical owner | Person accountable for collection and maintenance |
| Peer governance reviewer | Someone other than the proposer who checked access conditions |
| Terms review date | Date access and automation conditions were checked |
| Collection cadence | Daily, weekly or another approved interval (proposed: daily) |
| Latest successful collection | Derived from `data/runs`, not maintained by hand |
| Latest failed attempt | Derived from `data/runs` with the failure reason |
| Validation owner | Reviewer accountable for impact ratings |
| Retirement status | Active, paused, unavailable, replaced or retired, with reason |

## Approval checklist for a new source

- [ ] Business purpose and module recorded.
- [ ] Exact canonical URL and source role recorded.
- [ ] Government primary source or secondary source recorded.
- [ ] Public access confirmed without authentication or personal data.
- [ ] Terms and access conditions reviewed by someone other than the proposer.
- [ ] Collection method does not bypass a technical control.
- [ ] Cadence and request rate approved.
- [ ] Failure logging and stale-source handling tested.
- [ ] Labelled validation example reviewed before scheduled collection.
- [ ] Business, technical and validation owners assigned.

## Next register actions

1. Business approval of the source list and the denominator for coverage.
2. Run the collector against each source and inspect real snapshots.
3. Peer terms review for each source, with date and reviewer recorded.
4. Agree the impact-rating criteria (see the Data Dictionary open decisions).
5. Nominate immigration news portals and a corroboration rule for them.
