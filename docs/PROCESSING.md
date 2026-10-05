# Visa and Regulatory processing and human review workflow (0.1.0)

## Purpose

Convert saved scraper JSON into evidence-backed change candidates for manual
review. The processor runs offline and preserves raw snapshots. Review
decisions are stored separately and apply only to matching evidence
fingerprints. Automatic impact rating, expiry or withdrawal detection, news-portal
corroboration and dashboard or database loading are not implemented.
All source code, comments and documentation are in English.

## Run

From the repository root:

```sh
python3 -m scraper.run_scraper
python3 -m processing.run_processing
python3 -m processing.review list
python3 -m processing.review interactive
python3 -m unittest discover -s tests -t . -v
```

The scraper needs requests and beautifulsoup4 (pypdf for PDF sources) from
requirements.txt. Processing uses only the standard library. Processing accepts
`--raw-dir`, `--runs-dir`, `--output-dir` and `--approvals-file`; defaults are
repository-relative, so the working directory does not matter.

Generated outputs are rebuilt and overwritten on every processing run. Review
decisions live in `data/approvals/change_decisions.json`; never edit generated
JSON by hand. Retain raw snapshots.

## Collection design

- Decode HTML using a BOM or declared charset with UTF-8 and HTTP fallbacks.
- Keep the decoded `raw_html` and two hashes: `raw_html_hash` (whole page) and
  `content_hash` (extracted paragraph text). A changed hash means the page
  changed, not that a visa rule changed.
- Keep `content_blocks`: the smallest list item, article or table row (so a
  news card keeps title, date, text and link together), then headings and
  paragraphs outside those. Each block keeps its first absolute link.
- Navigation, headers, footers and forms are removed before extraction.
- Short text is kept in the snapshot; nothing is dropped for being short.
- `page_last_updated_text` keeps a page's "Last updated" stamp as text. It is a
  lead for review, not a publication or effective date.
- PDFs are extracted with pypdf into paragraph blocks.
- Quality warnings: `no_text_extracted`, `possible_client_rendered_page`.
- Every attempt, success or failure, writes a log in `data/runs/`. A source
  whose latest attempt failed is reported as possibly stale. Blocked requests
  (for example HTTP 403) are logged and never worked around.

## Outputs in data/processed

| File | Meaning |
| --- | --- |
| change_candidates.json | Every candidate version ever observed |
| change_events.json | First-observed or changed candidate observations, not verified government events |
| approval_targets.json | Current record per change with review status applied |
| approval_queue.json | Current records still needing a decision |
| approval_audit.json | Applied, stale, orphaned and invalid decisions |
| validated_changes.json | Approved records only (the dashboard input) |
| source_audit.json | Per-source snapshots, warnings, latest attempt, staleness |
| RUN_REPORT.md | Totals, sources needing attention, limitations |

## Extraction rules (rule version 0.1.0)

1. **Relevance:** a block must mention visa, migration, immigration,
   international students or education, overseas students, ESOS, working
   holiday, student intake, temporary graduate, skilled workers or temporary
   entrant. Blocks over 1,500 characters are skipped as page wrappers; text
   under four words is skipped unless it contains a published date.
2. **Visa categories:** a subclass number counts only next to the word
   "subclass" or "visa" and only if it is a known subclass, so "$500" is not a
   visa. Names map to subclasses (student → 500, temporary graduate → 485,
   skills in demand or TSS → 482, working holiday → 417 and 462, and so on). If
   only generic migration wording is found the category is `general_migration`
   with the issue `visa_category_unconfirmed`.
3. **Change type** (first match wins): processing_time, fee_change,
   visa_condition, compliance_requirement, eligibility, worker_policy,
   education_policy, policy_announcement, other.
4. **Dates:** a date introduced by effect wording ("from", "comes into effect
   on", "increased on") is `effective_date`. A date that opens the text or
   follows publication wording is `published_date`. For a listing item with
   exactly one other date, that date is taken as published; the reviewer must
   confirm it. Otherwise dates stay `null`. Day-first order is used for
   `2/10/2026`. Collection time is never substituted.
5. **Impact:** rules only fill `suggested_impact_level` and a reason. The real
   `impact_level` is `unassessed` until a reviewer sets it.
   High: eligibility, fee, compliance or visa-condition change naming a
   high-volume visa (500, 485, 482, 491, 494, 417, 462). Medium: the same types
   without such a visa, or processing time, education, worker or policy
   announcements. Low: everything else.
6. **Cover types:** `suggested_affected_cover_types` follows the named visas
   (500 → OSHC, 600 → OVHC, work visas → OWHC). It is a suggestion; the
   published `affected_cover_types` is reviewer-entered or null.

## Candidate data dictionary (implemented)

| Field | Type / values | Meaning |
| --- | --- | --- |
| record_id | string | Identity of one notice: source plus its link, or masked text when no link |
| snapshot_id / snapshot_path | string | Snapshot the version came from |
| version | integer | Increments when extracted fields or evidence text change |
| first_observed_at / last_observed_at | datetime | Observation times, not publication dates |
| organisation / source_id / source_url | string / URL | Source identity and actual final URL |
| change_title, change_summary | string | Headline and the source text (up to 600 characters); not a rewritten summary |
| change_type | enum | See rule 3 |
| published_date / effective_date | ISO date / null | See rule 4 |
| visa_categories | array | Subclasses, `general_migration`, or empty |
| jurisdiction | string | `Australia` |
| impact_level / impact_reason | enum / string | `unassessed` / null until review |
| suggested_impact_level / suggested_impact_reason | string | Rule hint only |
| affected_cover_types / suggested_affected_cover_types | array / null | Reviewed vs suggested |
| primary_government_source | boolean | From the source registry |
| corroboration_status | string | `not_required`, `uncorroborated` or `corroborated` |
| publication_url | URL | Block link, otherwise the source page |
| evidence | array | Exact raw_text and clean_text with block locator |
| review_status | enum | needs_review, approved, rejected, needs_correction, needs_more_evidence |
| lifecycle_status | enum | Always `unknown` here; never inferred from absence |
| present_in_latest_snapshot | boolean | Whether the latest snapshot of the source still shows it |
| validation_issues | array | human_review_required, impact_unassessed, visa_categories_missing, visa_category_unconfirmed, published_date_not_found, secondary_source_requires_corroboration |
| fingerprint | string | Hash of structured values and evidence text |

## Validation and known limits

- Unusable snapshots are isolated in `source_audit.invalid_files`. A snapshot
  needs source_id, organisation, final_url, a timezone-aware collected_at,
  content blocks and HTTP 200.
- Candidates are rule output from page text. They are not verified changes.
- A candidate missing from a later snapshot is never assumed withdrawn or ended.
  A rotating news listing would otherwise create false endings.
- Pages drawn by JavaScript (Home Affairs processing times and news archive),
  images and linked documents can be missed. The collector does not fetch linked
  pages or use a browser.
- Change of page layout can change a candidate without a policy change.
  First observed does not mean newly announced.
- The impact suggestion and cover suggestion are heuristics for reviewers, not
  forecasts of demand.
- Unit tests use synthetic fixtures. They do not measure real-world accuracy,
  and the collector has not yet been run against the live pages by this project.

## Review workflow

### Interactive wizard

```sh
python3 -m processing.review interactive
```

The wizard asks for the reviewer name once, shows each unresolved record, and
saves every decision immediately. On approval it asks for impact (high, medium
or low), the reason, optional visa categories, and corroboration for secondary
sources. Processing is refreshed at the end.

### Individual commands

```sh
python3 -m processing.review list
python3 -m processing.review show TARGET_ID
python3 -m processing.review approve TARGET_ID --reviewer "Name" \
  --impact high --impact-reason "Fee rise lifts OSHC price sensitivity" \
  --field effective_date='"2026-07-01"' --field affected_cover_types='["OSHC"]'
python3 -m processing.review reject TARGET_ID --reviewer "Name" --note "Not relevant to overseas cover"
python3 -m processing.review needs-correction TARGET_ID --reviewer "Name" --note "Date is wrong"
python3 -m processing.review needs-more-evidence TARGET_ID --reviewer "Name" --note "Need the government notice"
python3 -m processing.run_processing
```

Before approving, open the publication link, confirm the change on the
government page, confirm the visa categories and dates, and decide the impact.
Secondary sources need `--field corroboration_status='"corroborated"'` after a
government source confirms them.

### Rules for publication

An approval is accepted only if the corrected record has a title, summary,
valid change type, at least one visa category (or `general_migration`),
jurisdiction, impact level high/medium/low with a reason, ISO or null dates,
cover types from OSHC/OVHC/OWHC or null, an absolute publication URL, evidence,
and (for non-government sources) corroboration. Evidence, fingerprint, source
and record identity fields cannot be corrected.

Decisions are append-only audit events with reviewer, timezone-aware time, note,
fingerprint and corrections. The latest decision for the same target and
fingerprint applies. A later evidence change produces a new fingerprint: the old
decision becomes stale, the record leaves `validated_changes.json` and returns
to the queue. A decision for a record that no longer exists is reported as
orphaned.

Decision meanings:

- `approved`: publishable after the recorded corrections.
- `rejected`: reviewed and excluded (for example, not relevant to overseas cover).
- `needs_correction` / `needs_more_evidence`: stays in the approval queue.
