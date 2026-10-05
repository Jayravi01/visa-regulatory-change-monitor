# Visa and Regulatory Change Monitor (Module 3)

Overseas Health Market Intelligence for Medibank. This module tracks visa,
migration, education and worker-policy changes that could shift demand for
OSHC, OVHC and OWHC cover. It follows the same design as Module 1
(Promotions and Offers): collect public pages, process them offline into
evidence-backed candidates, and publish only what a human has reviewed.

```
scraper -> data/raw (immutable snapshots) + data/runs (every attempt)
        -> processing.run_processing -> data/processed/*.json
        -> processing.review (human decision, impact rating + reason)
        -> data/processed/validated_changes.json  (the only dashboard input)
```

## Quick start

```sh
pip install -r requirements.txt
python3 -m scraper.run_scraper                    # collect all registered sources
python3 -m scraper.run_scraper --source studyaustralia_news   # or one source
python3 -m processing.run_processing              # build candidates and queues
python3 -m processing.review list                 # what needs a decision
python3 -m processing.review interactive          # review step by step
python3 -m processing.run_processing              # publish approved records
python3 -m unittest discover -s tests -t . -v     # 61 offline tests
```

The scraper exits with code 1 if any source failed, so a scheduler can alert on
partial failure. Processing needs only the standard library.

## Layout

| Path | Purpose |
| --- | --- |
| `scraper/sources.py` | Source registry (the technical source of truth) |
| `scraper/base_scraper.py` | HTML and PDF collector; keeps raw HTML, text and dated content blocks |
| `scraper/run_scraper.py` | Runner; writes one log per attempt, success or failure |
| `scraper/storage.py` | Non-overwriting JSON snapshot writes |
| `processing/classify.py` | Dates, visa categories, change type, impact and cover suggestions |
| `processing/run_processing.py` | Candidates, versions, events, source audit, outputs |
| `processing/review.py` | Human review CLI and fingerprint-gated decisions |
| `data/approvals/change_decisions.json` | Append-only review decisions (commit this file) |
| `docs/` | `SOURCE_REGISTER.md`, `PROCESSING.md`, `DATA_DICTIONARY.md` |
| `tests/` | Offline unit tests using synthetic fixtures |

## Principles (shared with Module 1)

- Public sources only. No logins, CAPTCHAs, bot-challenge workarounds or browser
  rendering to get past a block. A blocked source is logged as failed.
- Raw snapshots and run logs are never overwritten.
- Rules suggest; people decide. Impact is `unassessed` until a reviewer records
  a level and a reason. Dates the page does not state stay `null`.
- A missing notice is never read as a withdrawn or ended change.
- Government sources outrank industry summaries; secondary records need
  corroboration before publication.

All source code, comments and documentation are in English.
