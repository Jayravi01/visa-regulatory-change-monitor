"""
Human review for visa and regulatory change records.

Nothing reaches validated_changes.json without a recorded decision that matches
the record's CURRENT evidence fingerprint. Decisions are append-only audit
events stored in data/approvals/change_decisions.json. If the evidence changes,
the fingerprint changes, the old decision becomes stale and the record returns
to the approval queue.

    python3 -m processing.review list
    python3 -m processing.review interactive
    python3 -m processing.review show TARGET_ID
    python3 -m processing.review approve TARGET_ID --reviewer "Name" \
        --impact high --impact-reason "Student visa fee rise lifts OSHC price sensitivity"
"""
import argparse
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / 'data/processed'
DEFAULT_APPROVALS_FILE = ROOT / 'data/approvals/change_decisions.json'

# command word -> stored decision / review status
DECISIONS = {'approve': 'approved', 'reject': 'rejected',
             'needs-correction': 'needs_correction', 'needs-more-evidence': 'needs_more_evidence'}
RESOLVED = {'approved', 'rejected'}

CHANGE_TYPES = {'processing_time', 'eligibility', 'compliance_requirement', 'policy_announcement',
                'visa_condition', 'education_policy', 'worker_policy', 'fee_change', 'other'}
IMPACT_LEVELS = {'high', 'medium', 'low'}
COVER_TYPES = {'OSHC', 'OVHC', 'OWHC'}
# Reviewers may correct these fields; everything else is evidence and cannot be edited.
EDITABLE_FIELDS = {'change_title', 'change_summary', 'change_type', 'published_date', 'effective_date',
                   'visa_categories', 'jurisdiction', 'impact_level', 'impact_reason',
                   'affected_cover_types', 'publication_url', 'corroboration_status',
                   'supersedes_record_id'}


class ReviewError(ValueError):
    """A decision or stored file is invalid."""


def now():
    return datetime.now(timezone.utc).isoformat()


# -------------- Decision storage --------------

def load_decisions(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        decisions = json.loads(path.read_text(encoding='utf8'))
    except ValueError as exc:
        raise ReviewError(f'{path} is not valid JSON: {exc}') from exc
    if not isinstance(decisions, list):
        raise ReviewError(f'{path} must contain a JSON list')
    for item in decisions:
        if not isinstance(item, dict) or not {'target_id', 'decision', 'fingerprint', 'reviewer'} <= item.keys():
            raise ReviewError(f'{path} holds a malformed decision: {item!r}')
        if item['decision'] not in DECISIONS.values():
            raise ReviewError(f'{path} holds an unknown decision: {item["decision"]!r}')
    return decisions


def save_decisions(path, decisions):
    """Replace the file atomically so an interrupted save cannot corrupt the audit trail."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            stream.write(json.dumps(decisions, ensure_ascii=False, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def latest_decisions(decisions):
    """Latest decision for each (target, fingerprint); later events override earlier ones."""
    latest = {}
    for item in decisions:
        latest[(item['target_id'], item['fingerprint'])] = item
    return latest


# -------------- Validation --------------

def _iso_or_none(value):
    if value is None:
        return True
    try:
        date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_publishable(record):
    """Problems that block publication; an empty list means the record may be published."""
    problems = []
    for field in ('change_title', 'change_summary', 'jurisdiction'):
        if not str(record.get(field) or '').strip():
            problems.append(f'{field} is required')
    if record.get('change_type') not in CHANGE_TYPES:
        problems.append('change_type must use the change type vocabulary')
    categories = record.get('visa_categories')
    if not isinstance(categories, list) or not categories or not all(isinstance(c, str) and c for c in categories):
        problems.append('visa_categories needs at least one category or general_migration')
    if record.get('impact_level') not in IMPACT_LEVELS:
        problems.append('impact_level must be high, medium or low after review')
    if not str(record.get('impact_reason') or '').strip():
        problems.append('impact_reason is required for a high, medium or low rating')
    for field in ('published_date', 'effective_date'):
        if not _iso_or_none(record.get(field)):
            problems.append(f'{field} must be an ISO date (YYYY-MM-DD) or null')
    covers = record.get('affected_cover_types')
    if covers is not None and (not isinstance(covers, list) or not set(covers) <= COVER_TYPES):
        problems.append('affected_cover_types must be null or a list of OSHC, OVHC, OWHC')
    if not str(record.get('publication_url') or '').startswith(('http://', 'https://')):
        problems.append('publication_url must be an absolute http(s) URL')
    if not record.get('evidence'):
        problems.append('at least one evidence item is required')
    if not record.get('primary_government_source') and record.get('corroboration_status') != 'corroborated':
        problems.append('a secondary (non-government) source needs corroboration_status = corroborated')
    return problems


def _set_field(record, name, value):
    if name not in EDITABLE_FIELDS:
        raise ReviewError(f'{name} cannot be corrected; editable fields: {", ".join(sorted(EDITABLE_FIELDS))}')
    record[name] = value


# -------------- Applying decisions --------------

def apply_decisions(records, decisions):
    """
    Combine current records with stored decisions.

    Returns (targets, validated, audit). A decision applies only when both the
    target id and the evidence fingerprint match the current record.
    """
    latest = latest_decisions(decisions)
    current = {r['record_id']: r for r in records}
    targets, validated = [], []
    audit = {'applied': [], 'stale': [], 'orphaned': [], 'invalid_approvals': []}

    for record in records:
        target = deepcopy(record)
        target['review_status'] = 'needs_review'
        target['review'] = None
        decision = latest.get((record['record_id'], record['fingerprint']))
        if decision:
            target['review_status'] = decision['decision']
            target['review'] = {k: decision.get(k) for k in
                                ('decision_id', 'reviewer', 'reviewed_at', 'note', 'field_corrections')}
            audit['applied'].append(decision['decision_id'] if 'decision_id' in decision else decision['target_id'])
            if decision['decision'] == 'approved':
                merged = deepcopy(target)
                for name, value in (decision.get('field_corrections') or {}).items():
                    _set_field(merged, name, value)
                problems = validate_publishable(merged)
                if problems:
                    target['review_status'] = 'needs_correction'
                    target['validation_issues'] = sorted(set(target['validation_issues']) | set(problems))
                    audit['invalid_approvals'].append({'target_id': record['record_id'], 'problems': problems})
                else:
                    merged['validation_issues'] = []
                    merged['review_status'] = 'approved'
                    validated.append(merged)
        targets.append(target)

    for key, decision in latest.items():
        record = current.get(decision['target_id'])
        entry = {'decision_id': decision.get('decision_id'), 'target_id': decision['target_id'],
                 'decision': decision['decision'], 'fingerprint': decision['fingerprint']}
        if record is None:
            audit['orphaned'].append(entry)
        elif record['fingerprint'] != decision['fingerprint']:
            audit['stale'].append(entry)
    return targets, validated, audit


# -------------- Recording decisions --------------

def load_targets(output_dir):
    path = Path(output_dir) / 'approval_targets.json'
    if not path.exists():
        raise ReviewError(f'{path} not found; run python3 -m processing.run_processing first')
    return json.loads(path.read_text(encoding='utf8'))


def record_decision(target_id, decision, reviewer, note='', field_corrections=None,
                    output_dir=DEFAULT_OUTPUT_DIR, approvals_file=DEFAULT_APPROVALS_FILE):
    """Validate and append one decision for the target's current fingerprint."""
    if decision not in DECISIONS.values():
        raise ReviewError(f'unknown decision {decision!r}')
    if not str(reviewer or '').strip():
        raise ReviewError('a reviewer name is required')
    targets = {t['record_id']: t for t in load_targets(output_dir)}
    if target_id not in targets:
        raise ReviewError(f'unknown target {target_id}; run the list command')
    target = targets[target_id]
    corrections = dict(field_corrections or {})

    if decision == 'approved':
        merged = deepcopy(target)
        for name, value in corrections.items():
            _set_field(merged, name, value)
        problems = validate_publishable(merged)
        if problems:
            raise ReviewError('cannot approve: ' + '; '.join(problems))
    else:
        for name in corrections:
            if name not in EDITABLE_FIELDS:
                raise ReviewError(f'{name} cannot be corrected')

    event = {'decision_id': uuid.uuid4().hex, 'target_id': target_id, 'decision': decision,
             'reviewer': reviewer.strip(), 'reviewed_at': now(), 'note': note,
             'fingerprint': target['fingerprint'], 'field_corrections': corrections}
    decisions = load_decisions(approvals_file)
    decisions.append(event)
    save_decisions(approvals_file, decisions)
    return event


# -------------- Display and interactive review --------------

def _parse_field(text):
    """KEY=VALUE where VALUE is JSON when it parses, otherwise a plain string."""
    if '=' not in text:
        raise argparse.ArgumentTypeError('use KEY=VALUE')
    key, value = text.split('=', 1)
    try:
        return key, json.loads(value)
    except ValueError:
        return key, value


def _summary(record):
    evidence = record['evidence'][0]['clean_text'] if record.get('evidence') else ''
    lines = [
        f"Target:      {record['record_id']}",
        f"Source:      {record['organisation']} ({record['source_id']})"
        f"{'' if record.get('primary_government_source') else '  [secondary source]'}",
        f"Title:       {record['change_title']}",
        f"Type:        {record['change_type']}    Visa categories: {', '.join(record['visa_categories']) or 'none found'}",
        f"Published:   {record.get('published_date')}    Effective: {record.get('effective_date')}",
        f"Suggested:   impact {record.get('suggested_impact_level')} - {record.get('suggested_impact_reason')}",
        f"Link:        {record['publication_url']}",
        f"Status:      {record['review_status']}",
        f"Evidence:    {evidence}",
    ]
    return '\n'.join(lines)


def interactive_review(output_dir=DEFAULT_OUTPUT_DIR, approvals_file=DEFAULT_APPROVALS_FILE,
                       reviewer=None, input_fn=input, output_fn=print, refresh=None):
    """Walk through unresolved records, saving each decision immediately. Returns count saved."""
    queue = [t for t in load_targets(output_dir) if t['review_status'] not in RESOLVED]
    if not queue:
        output_fn('Nothing to review.')
        return 0
    reviewer = (reviewer or input_fn('Reviewer name: ')).strip()
    saved = 0
    for position, target in enumerate(queue, start=1):
        output_fn(f'\n--- {position} of {len(queue)} ---')
        output_fn(_summary(target))
        while True:
            choice = input_fn('[a]pprove [r]eject [c]orrection needed [m]ore evidence [s]kip [q]uit: ').strip().lower()
            if choice == 'q':
                if saved and refresh:
                    refresh()
                return saved
            if choice == 's':
                break
            if choice not in {'a', 'r', 'c', 'm'}:
                continue
            corrections = {}
            decision = {'a': 'approved', 'r': 'rejected', 'c': 'needs_correction', 'm': 'needs_more_evidence'}[choice]
            if decision == 'approved':
                corrections['impact_level'] = input_fn('Impact (high/medium/low): ').strip().lower()
                corrections['impact_reason'] = input_fn('Impact reason: ').strip()
                cats = input_fn('Visa categories, comma separated (blank keeps current): ').strip()
                if cats:
                    corrections['visa_categories'] = [c.strip() for c in cats.split(',') if c.strip()]
                if not target.get('primary_government_source'):
                    if input_fn('Corroborated by a government source? [y/N]: ').strip().lower() == 'y':
                        corrections['corroboration_status'] = 'corroborated'
            note = input_fn('Note: ').strip()
            try:
                record_decision(target['record_id'], decision, reviewer, note, corrections,
                                output_dir, approvals_file)
            except ReviewError as exc:
                output_fn(f'Not saved: {exc}')
                continue
            saved += 1
            output_fn('Saved.')
            break
    if saved and refresh:
        refresh()
    return saved


# -------------- Command line --------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--raw-dir', type=Path, default=ROOT / 'data/raw')
    parser.add_argument('--runs-dir', type=Path, default=ROOT / 'data/runs')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--approvals-file', type=Path, default=DEFAULT_APPROVALS_FILE)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='list records still needing a decision')
    interactive = sub.add_parser('interactive', help='review unresolved records one by one')
    interactive.add_argument('--reviewer')
    show = sub.add_parser('show', help='show one record')
    show.add_argument('target_id')
    for command in DECISIONS:
        action = sub.add_parser(command)
        action.add_argument('target_id')
        action.add_argument('--reviewer', required=True)
        action.add_argument('--note', default='')
        action.add_argument('--field', action='append', default=[], type=_parse_field,
                            help='reviewed correction KEY=VALUE (JSON values allowed)')
        if command == 'approve':
            action.add_argument('--impact', choices=sorted(IMPACT_LEVELS))
            action.add_argument('--impact-reason')
    args = parser.parse_args(argv)

    try:
        if args.command == 'list':
            queue = [t for t in load_targets(args.output_dir) if t['review_status'] not in RESOLVED]
            for t in queue:
                print(f"{t['record_id']}  {t['review_status']:<20} {t['organisation']}: {t['change_title'][:80]}")
            print(f'{len(queue)} record(s) need a decision')
        elif args.command == 'show':
            targets = {t['record_id']: t for t in load_targets(args.output_dir)}
            if args.target_id not in targets:
                raise ReviewError(f'unknown target {args.target_id}')
            print(_summary(targets[args.target_id]))
        elif args.command == 'interactive':
            def refresh():
                from processing.run_processing import run
                run(args.raw_dir, args.runs_dir, args.output_dir, args.approvals_file)
            interactive_review(args.output_dir, args.approvals_file, args.reviewer, refresh=refresh)
        else:
            corrections = dict(args.field)
            if args.command == 'approve':
                if args.impact:
                    corrections['impact_level'] = args.impact
                if args.impact_reason:
                    corrections['impact_reason'] = args.impact_reason
            event = record_decision(args.target_id, DECISIONS[args.command], args.reviewer, args.note,
                                    corrections, args.output_dir, args.approvals_file)
            print(f"Recorded {event['decision']} for {args.target_id}. "
                  f"Rerun: python3 -m processing.run_processing")
    except ReviewError as exc:
        print(f'Error: {exc}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
