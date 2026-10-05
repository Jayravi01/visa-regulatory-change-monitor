# Visa and Regulatory Data Dictionary (Module 3)

Document status: Draft - business and database approval pending  
Rule version: `0.1.0`

This extends the shared canonical dictionary from the Promotions repository
(`DATA_DICTIONARY.md`, module vocabulary `visa_regulatory`). It defines the
publication fields for `validated_changes.json`. `PROCESSING.md` describes the
fields on candidates before review.

## Requirement levels

Mandatory: a publishable record must have a valid value. Optional: the source
may omit it; use `null`. Conditional: mandatory when the stated condition is
true. System: assigned by the pipeline. `null` means unknown or not announced,
never zero, false or "no end date".

## Controlled vocabularies

| Vocabulary | Values |
| --- | --- |
| Change type | `processing_time`, `eligibility`, `compliance_requirement`, `policy_announcement`, `visa_condition`, `education_policy`, `worker_policy`, `fee_change`, `other` |
| Impact level | `high`, `medium`, `low`, `unassessed` (unassessed is never published) |
| Cover type | `OSHC`, `OVHC`, `OWHC` |
| Review status | `needs_review`, `approved`, `rejected`, `needs_correction`, `needs_more_evidence` |
| Lifecycle status | `unknown`, `scheduled`, `active`, `ended`, `superseded`, `withdrawn` (this module writes `unknown`) |
| Evidence type | `html_text`, `pdf_text` (others reserved by the shared dictionary) |

## Published fields

| Field | Type | Level | Example | Validation rule |
| --- | --- | --- | --- | --- |
| `record_id` | string | System | hash | Stable for the same notice |
| `module` | string | System | `visa_regulatory` | Fixed |
| `organisation`, `source_id` | string | Mandatory | `Study Australia`, `studyaustralia_news` | `source_id` exists in the register and `scraper/sources.py` |
| `source_url` | URL | Mandatory | page URL | Final URL of the snapshot |
| `collected_at` | datetime | Mandatory | `2026-10-05T01:32:11+00:00` | Timezone required; not a publication date |
| `change_title` | string | Mandatory | Student Visa Application Charge increase | Non-empty, traceable to evidence |
| `change_summary` | string | Mandatory | source text | Must not add claims absent from the source |
| `change_type` | enum | Mandatory | `fee_change` | Change type vocabulary |
| `published_date` | date/null | Optional | `2026-07-03` | ISO date; never the collection date |
| `effective_date` | date/null | Optional | `2026-07-01` | ISO date; `null` unless announced; never guessed |
| `visa_categories` | array | Mandatory | `["500", "485"]` | At least one category or `general_migration` |
| `jurisdiction` | string | Mandatory | `Australia` | Non-empty |
| `impact_level` | enum | Mandatory | `high` | high, medium or low; human-reviewed |
| `impact_reason` | string | Conditional | Fee rise lifts OSHC price sensitivity | Required with any published impact level |
| `affected_cover_types` | array/null | Optional | `["OSHC"]` | Cover type vocabulary or `null` |
| `primary_government_source` | boolean | Mandatory | `true` | From the source registry |
| `corroboration_status` | string | Conditional | `corroborated` | Must be `corroborated` when `primary_government_source` is false |
| `supersedes_record_id` | string/null | Optional | earlier `record_id` | Must refer to an existing change record |
| `publication_url` | URL | Mandatory | notice link | Absolute http(s); the most authoritative available |
| `evidence` | array | Mandatory | see below | At least one item |
| `review_status` | enum | Mandatory | `approved` | Only `approved` records are published |
| `lifecycle_status` | enum | Mandatory | `unknown` | Never inferred from absence or failed collection |
| `version`, `fingerprint` | integer, string | System | `2`, hash | Fingerprint changes when values or evidence text change |
| `review` | object | System | reviewer, time, note, corrections | From the decision event |

### Evidence object

`evidence_id`, `evidence_type`, `raw_text` (exact, unrewritten), `clean_text`,
`locator` (`block_id`, `block_index`, `tag`), `source_url`, `collected_at`.

## Cross-field publication rules

1. The source is registered and the record has every mandatory field.
2. Evidence supports the claim and resolves to a stored snapshot.
3. `review_status` is `approved` and the decision fingerprint matches the
   current evidence fingerprint.
4. Dates are valid ISO dates or `null`.
5. Secondary sources are corroborated by a government source.
6. Absence after a failed or incomplete collection never creates an ended event.

## Suggested relational mapping

Matches the shared mapping: `sources`, `collection_runs` (from `data/runs`),
`snapshots`, `intelligence_records`, `visa_regulatory_changes` (the fields
above), `evidence_items`, `review_decisions`.

## Open decisions

- Approve impact-rating criteria (what makes a change high, medium or low) with
  Medibank. The current suggestion rule is a starting point only.
- Approve the source list and the coverage denominator.
- Decide whether `lifecycle_status` should be reviewer-entered for this module.
- Decide how corroboration is evidenced (a second URL field, or a linked record).
- Confirm the dashboard target (Tableau or Power BI) and AWS loading path, as in
  the shared dictionary.
