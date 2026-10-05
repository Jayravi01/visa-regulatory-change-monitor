"""
Process saved scraper JSON into visa and regulatory change candidates.

The processor runs offline and never edits raw snapshots. It turns relevant
content blocks into candidate change records with exact evidence, tracks how each
candidate changes between snapshots, and applies stored human review decisions.
Only reviewed, approved records reach data/processed/validated_changes.json.
"""
import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re

from processing import review
from processing.classify import (classify_change_type, clean, detect_visa_categories, extract_dates,
                                 is_relevant, suggest_cover_types, suggest_impact)

ROOT = Path(__file__).resolve().parents[1]
RULE_VERSION = '0.1.0'
MODULE = 'visa_regulatory'
JURISDICTION = 'Australia'
MAX_BLOCK_CHARS = 1500       # larger blocks are page wrappers, not single notices
MIN_BLOCK_WORDS = 4          # shorter text without a date is usually a menu item
LISTING_TAGS = {'article', 'li', 'tr'}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def masked(text):
    """Letters only, lower case: identity that survives a changed date or number."""
    return re.sub(r'[^a-z]+', ' ', text.lower()).strip()[:160]


# -------------- Snapshot validation --------------

def validate_snapshot(data):
    """Return problems that make a snapshot unusable; empty list means usable."""
    problems = []
    for field in ('source_id', 'organisation', 'final_url'):
        if not isinstance(data.get(field), str) or not data[field].strip():
            problems.append(f'missing {field}')
    try:
        if datetime.fromisoformat(data.get('collected_at', '')).tzinfo is None:
            problems.append('collected_at has no timezone')
    except (TypeError, ValueError):
        problems.append('collected_at is not an ISO datetime')
    if data.get('http_status') != 200:
        problems.append(f"http_status is {data.get('http_status')!r}, not 200")
    blocks = data.get('content_blocks')
    if not isinstance(blocks, list) or not all(isinstance(b, dict) and isinstance(b.get('text'), str) for b in blocks):
        problems.append('content_blocks must be a list of blocks with text')
    return problems


def snapshot_id(data):
    return digest([data.get('source_id'), data.get('collected_at'), data.get('content_hash')])


# -------------- Extraction --------------

def title_for(block, text):
    """Link text when it reads like a headline, otherwise the first sentence."""
    link = clean(block.get('link_text') or '')
    candidate = link if len(link) >= 15 else re.split(r'(?<=[.!?])\s', text, maxsplit=1)[0]
    candidate = re.sub(r'^(?:news|media release)\s*\|\s*', '', candidate, flags=re.I)
    return candidate[:200].strip()


def make_candidate(snapshot, block, index, path=None):
    raw = block['text']
    text = clean(raw)
    published, effective = extract_dates(text, listing_item=block.get('tag') in LISTING_TAGS)
    categories, specific = detect_visa_categories(text)
    change_type = classify_change_type(text)
    level, reason = suggest_impact(change_type, categories)
    primary = bool(snapshot.get('primary_government_source'))
    url = block.get('href') or snapshot['final_url']

    issues = ['human_review_required', 'impact_unassessed']
    if not categories:
        issues.append('visa_categories_missing')
    elif not specific:
        issues.append('visa_category_unconfirmed')
    if published is None:
        issues.append('published_date_not_found')
    if not primary:
        issues.append('secondary_source_requires_corroboration')

    evidence = [{
        'evidence_id': digest([snapshot['source_id'], block.get('block_id'), text])[:12],
        'evidence_type': 'html_text' if snapshot.get('media_type') != 'application/pdf' else 'pdf_text',
        'raw_text': raw, 'clean_text': text,
        'locator': {'block_id': block.get('block_id'), 'block_index': index, 'tag': block.get('tag')},
        'source_url': snapshot['final_url'], 'collected_at': snapshot['collected_at'],
    }]
    record = {
        'module': MODULE,
        'record_id': digest([snapshot['source_id'], block.get('href') or masked(text)]),
        'snapshot_id': snapshot_id(snapshot),
        'snapshot_path': str(path) if path else None,
        'organisation': snapshot['organisation'],
        'source_id': snapshot['source_id'],
        'source_url': snapshot['final_url'],
        'collected_at': snapshot['collected_at'],
        'change_title': title_for(block, text),
        'change_summary': text[:600],
        'change_type': change_type,
        'published_date': published,
        'effective_date': effective,
        'visa_categories': categories,
        'jurisdiction': JURISDICTION,
        'impact_level': 'unassessed',
        'impact_reason': None,
        'suggested_impact_level': level,
        'suggested_impact_reason': reason,
        'affected_cover_types': None,
        'suggested_affected_cover_types': suggest_cover_types(categories),
        'primary_government_source': primary,
        'corroboration_status': 'not_required' if primary else 'uncorroborated',
        'supersedes_record_id': None,
        'publication_url': url,
        'evidence': evidence,
        'review_status': 'needs_review',
        'lifecycle_status': 'unknown',
        'validation_issues': issues,
        'extraction_method': 'rules',
        'rule_version': RULE_VERSION,
    }
    # Fingerprint binds structured values to evidence TEXT only. Collection time and
    # block position are left out so an unchanged notice keeps its fingerprint.
    record['fingerprint'] = digest({
        'title': record['change_title'], 'summary': record['change_summary'],
        'type': change_type, 'published': published, 'effective': effective,
        'visa_categories': categories, 'url': url,
        'evidence': [e['clean_text'] for e in evidence]})
    return record


def extract(snapshot, path=None):
    """Candidate change records from one valid snapshot."""
    candidates = []
    for index, block in enumerate(snapshot['content_blocks']):
        text = clean(block['text'])
        if not text or len(text) > MAX_BLOCK_CHARS:
            continue
        if not (is_relevant(text) or is_relevant(clean(block.get('link_text') or ''))):
            continue
        if len(text.split()) < MIN_BLOCK_WORDS and not extract_dates(text)[0]:
            continue
        candidates.append(make_candidate(snapshot, block, index, path))
    return candidates


# -------------- History across snapshots --------------

def build_history(snapshots):
    """
    Version candidates over time.

    snapshots: list of (path, data) sorted oldest first. A new version is created
    only when a candidate's fingerprint changes. A candidate that is absent from a
    later snapshot is NOT treated as ended or withdrawn.
    """
    versions, events, latest_ids = {}, [], {}
    for path, data in snapshots:
        seen = set()
        for candidate in extract(data, path):
            rid = candidate['record_id']
            seen.add(rid)
            history = versions.setdefault(rid, [])
            if history and history[-1]['fingerprint'] == candidate['fingerprint']:
                history[-1]['last_observed_at'] = candidate['collected_at']
                continue
            kind = 'changed_candidate' if history else 'first_observed'
            candidate['version'] = len(history) + 1
            candidate['first_observed_at'] = history[0]['first_observed_at'] if history else candidate['collected_at']
            candidate['last_observed_at'] = candidate['collected_at']
            history.append(candidate)
            events.append({'event': kind, 'record_id': rid, 'version': candidate['version'],
                           'source_id': candidate['source_id'], 'observed_at': candidate['collected_at'],
                           'change_title': candidate['change_title'],
                           'note': 'candidate observation, not a verified government change'})
        latest_ids[data['source_id']] = seen
    current = []
    for history in versions.values():
        record = history[-1]
        record['present_in_latest_snapshot'] = record['record_id'] in latest_ids.get(record['source_id'], set())
        current.append(record)
    current.sort(key=lambda r: (r['source_id'], r['record_id']))
    return versions, events, current


# -------------- Loading --------------

def load_json_files(folder):
    """Yield (path, data, error). Unreadable files are reported, never fatal."""
    for path in sorted(Path(folder).rglob('*.json')) if Path(folder).exists() else []:
        try:
            yield path, json.loads(path.read_text(encoding='utf8')), None
        except (OSError, ValueError) as exc:
            yield path, None, str(exc)


def load_snapshots(raw_dir):
    valid, errors = [], []
    for path, data, error in load_json_files(raw_dir):
        if error:
            errors.append({'file': str(path), 'problems': [error]})
            continue
        problems = validate_snapshot(data) if isinstance(data, dict) else ['not a JSON object']
        if problems:
            errors.append({'file': str(path), 'problems': problems})
        else:
            valid.append((path, data))
    valid.sort(key=lambda item: (datetime.fromisoformat(item[1]['collected_at']), str(item[0])))
    return valid, errors


def latest_attempts(runs_dir):
    """Most recent run log per source, from the durable per-attempt logs."""
    latest = {}
    for path, data, error in load_json_files(runs_dir):
        if error or not isinstance(data, dict) or 'source_id' not in data:
            continue
        current = latest.get(data['source_id'])
        if current is None or data.get('started_at', '') >= current.get('started_at', ''):
            latest[data['source_id']] = data
    return latest


# -------------- Outputs --------------

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def source_audit(snapshots, errors, attempts):
    from scraper.sources import SOURCES
    by_source = {}
    for path, data in snapshots:
        by_source.setdefault(data['source_id'], []).append((path, data))
    rows = []
    for source in SOURCES:
        sid = source['source_id']
        snaps = by_source.get(sid, [])
        attempt = attempts.get(sid)
        latest = snaps[-1][1] if snaps else None
        stale = bool(attempt and attempt.get('status') == 'failed')
        rows.append({
            'source_id': sid, 'organisation': source['organisation'],
            'primary_government_source': source['primary_government_source'],
            'snapshots': len(snaps),
            'latest_snapshot_at': latest['collected_at'] if latest else None,
            'latest_quality_warnings': latest.get('quality_warnings', []) if latest else [],
            'latest_attempt_status': attempt.get('status') if attempt else None,
            'latest_attempt_error': attempt.get('error') if attempt else None,
            'latest_attempt_http_status': attempt.get('http_status') if attempt else None,
            'snapshot_may_be_stale': stale,
            'no_snapshot': not snaps,
        })
    return {'sources': rows, 'invalid_files': errors,
            'unregistered_sources': sorted(set(by_source) - {s['source_id'] for s in SOURCES})}


def run_report(summary, audit):
    lines = ['# Visa and Regulatory processing run report', '',
             f"Rule version: {RULE_VERSION}", '',
             '| Measure | Count |', '| --- | ---: |']
    lines += [f'| {k} | {v} |' for k, v in summary.items()]
    lines += ['', '## Sources needing attention', '']
    flagged = [r for r in audit['sources'] if r['no_snapshot'] or r['snapshot_may_be_stale'] or r['latest_quality_warnings']]
    if not flagged:
        lines.append('None.')
    for r in flagged:
        notes = []
        if r['no_snapshot']:
            notes.append('no usable snapshot')
        if r['snapshot_may_be_stale']:
            notes.append(f"latest attempt failed (HTTP {r['latest_attempt_http_status']}); snapshot may be stale")
        if r['latest_quality_warnings']:
            notes.append('warnings: ' + ', '.join(r['latest_quality_warnings']))
        lines.append(f"- `{r['source_id']}`: " + '; '.join(notes))
    lines += ['', '## Limitations', '',
              '- Candidates are rule outputs from page text. They are not verified government changes.',
              '- A candidate missing from a later snapshot is never assumed withdrawn or ended.',
              '- Impact stays unassessed until a reviewer records a level and a reason.',
              '- Pages drawn by JavaScript, images and linked documents can be missed.',
              '- A successful download is not proof that extraction is complete.', '']
    return '\n'.join(lines)


def run(raw_dir=ROOT / 'data/raw', runs_dir=ROOT / 'data/runs', output_dir=ROOT / 'data/processed',
        approvals_file=review.DEFAULT_APPROVALS_FILE):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshots, errors = load_snapshots(raw_dir)
    versions, events, current = build_history(snapshots)
    decisions = review.load_decisions(approvals_file)
    targets, validated, approval_audit = review.apply_decisions(current, decisions)
    queue = [t for t in targets if t['review_status'] not in review.RESOLVED]
    audit = source_audit(snapshots, errors, latest_attempts(runs_dir))

    all_versions = [v for history in versions.values() for v in history]
    all_versions.sort(key=lambda r: (r['source_id'], r['record_id'], r['version']))
    write_json(output_dir / 'change_candidates.json', all_versions)
    write_json(output_dir / 'change_events.json', events)
    write_json(output_dir / 'approval_targets.json', targets)
    write_json(output_dir / 'approval_queue.json', queue)
    write_json(output_dir / 'approval_audit.json', approval_audit)
    write_json(output_dir / 'validated_changes.json', validated)
    write_json(output_dir / 'source_audit.json', audit)

    summary = {'valid_snapshots': len(snapshots), 'invalid_files': len(errors),
               'candidate_versions': len(all_versions), 'current_candidates': len(current),
               'awaiting_decision': len(queue), 'validated_changes': len(validated),
               'stale_decisions': len(approval_audit['stale']),
               'orphaned_decisions': len(approval_audit['orphaned'])}
    (output_dir / 'RUN_REPORT.md').write_text(run_report(summary, audit), encoding='utf8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, default=ROOT / 'data/raw')
    parser.add_argument('--runs-dir', type=Path, default=ROOT / 'data/runs')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/processed')
    parser.add_argument('--approvals-file', type=Path, default=review.DEFAULT_APPROVALS_FILE)
    args = parser.parse_args()
    for key, value in run(args.raw_dir, args.runs_dir, args.output_dir, args.approvals_file).items():
        print(f'{key}: {value}')


if __name__ == '__main__':
    main()
