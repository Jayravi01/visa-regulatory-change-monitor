"""Processing tests: candidate extraction, versioning, invalid input and source audit."""
import json
import tempfile
import unittest
from pathlib import Path

from processing.run_processing import (build_history, extract, latest_attempts, load_snapshots, run,
                                       validate_snapshot)


def block(text, href=None, link_text=None, tag='li', index=0):
    return {'block_id': f'b{index}', 'tag': tag, 'text': text, 'link_text': link_text, 'href': href}


def snapshot(blocks, collected_at='2026-10-01T00:00:00+00:00', source_id='studyaustralia_news',
             primary=True, **extra):
    data = {'source_id': source_id, 'organisation': 'Study Australia', 'final_url': 'https://example.gov.au/news',
            'collected_at': collected_at, 'http_status': 200, 'content_blocks': blocks,
            'content_hash': collected_at, 'primary_government_source': primary, 'media_type': 'text/html'}
    data.update(extra)
    return data


FEE = block('Student Visa Application Charge increase 3 July 2026 The charge increased on 1 July 2026 for Student visa holders.',
            href='https://example.gov.au/news/fee-rise', link_text='Student Visa Application Charge increase')
NOISE = block('Join our newsletter', index=1)
MENU = block('Student visa', index=2)


class ExtractionTests(unittest.TestCase):
    def test_relevant_block_becomes_candidate_with_exact_evidence(self):
        (c,) = extract(snapshot([FEE, NOISE, MENU]))
        self.assertEqual(c['change_title'], 'Student Visa Application Charge increase')
        self.assertEqual(c['change_type'], 'fee_change')
        self.assertEqual(c['visa_categories'], ['500'])
        self.assertEqual(c['published_date'], '2026-07-03')
        self.assertEqual(c['effective_date'], '2026-07-01')
        self.assertEqual(c['publication_url'], 'https://example.gov.au/news/fee-rise')
        self.assertEqual(c['evidence'][0]['raw_text'], FEE['text'])
        self.assertEqual(c['review_status'], 'needs_review')
        self.assertEqual(c['impact_level'], 'unassessed')
        self.assertIsNone(c['impact_reason'])
        self.assertEqual(c['suggested_impact_level'], 'high')
        self.assertIn('impact_unassessed', c['validation_issues'])

    def test_secondary_source_is_flagged(self):
        (c,) = extract(snapshot([FEE], source_id='mia_media_releases', primary=False))
        self.assertFalse(c['primary_government_source'])
        self.assertEqual(c['corroboration_status'], 'uncorroborated')
        self.assertIn('secondary_source_requires_corroboration', c['validation_issues'])

    def test_page_wrapper_blocks_are_skipped(self):
        self.assertEqual(extract(snapshot([block('visa ' * 600)])), [])

    def test_missing_published_date_is_reported_not_guessed(self):
        (c,) = extract(snapshot([block('New requirements for student visa applicants apply soon')]))
        self.assertIsNone(c['published_date'])
        self.assertIn('published_date_not_found', c['validation_issues'])

    def test_no_visa_or_date_guessing_when_text_is_generic(self):
        (c,) = extract(snapshot([block('International education settings confirmed by government')]))
        self.assertEqual(c['visa_categories'], [])
        self.assertIn('visa_categories_missing', c['validation_issues'])


class SnapshotValidationTests(unittest.TestCase):
    def test_valid_snapshot_has_no_problems(self):
        self.assertEqual(validate_snapshot(snapshot([FEE])), [])

    def test_bad_snapshots_are_described(self):
        self.assertTrue(validate_snapshot(snapshot([FEE], http_status=403)))
        self.assertTrue(validate_snapshot(snapshot([FEE], collected_at='2026-10-01T00:00:00')))
        self.assertTrue(validate_snapshot(snapshot([FEE], collected_at='yesterday')))
        self.assertTrue(validate_snapshot(snapshot('not a list')))
        self.assertTrue(validate_snapshot({}))


class HistoryTests(unittest.TestCase):
    def history(self, *snaps):
        return build_history([(Path(f's{i}.json'), s) for i, s in enumerate(snaps)])

    def test_unchanged_notice_is_one_version(self):
        a = snapshot([FEE], '2026-10-01T00:00:00+00:00')
        b = snapshot([FEE], '2026-10-02T00:00:00+00:00')
        versions, events, current = self.history(a, b)
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]['version'], 1)
        self.assertEqual(current[0]['last_observed_at'], '2026-10-02T00:00:00+00:00')
        self.assertEqual([e['event'] for e in events], ['first_observed'])

    def test_changed_text_makes_new_version_and_new_fingerprint(self):
        changed = dict(FEE, text=FEE['text'] + ' The fee is now confirmed for Temporary Graduate visa holders.')
        _, events, current = self.history(snapshot([FEE], '2026-10-01T00:00:00+00:00'),
                                          snapshot([changed], '2026-10-02T00:00:00+00:00'))
        self.assertEqual(current[0]['version'], 2)
        self.assertEqual([e['event'] for e in events], ['first_observed', 'changed_candidate'])
        self.assertEqual(current[0]['first_observed_at'], '2026-10-01T00:00:00+00:00')

    def test_block_position_and_collection_time_do_not_change_fingerprint(self):
        moved = dict(FEE, block_id='b9')
        _, _, current = self.history(snapshot([FEE], '2026-10-01T00:00:00+00:00'),
                                     snapshot([NOISE, moved], '2026-10-02T00:00:00+00:00'))
        self.assertEqual(current[0]['version'], 1)

    def test_absent_notice_is_not_treated_as_ended(self):
        _, events, current = self.history(snapshot([FEE], '2026-10-01T00:00:00+00:00'),
                                          snapshot([NOISE], '2026-10-02T00:00:00+00:00'))
        self.assertEqual(len(current), 1)
        self.assertFalse(current[0]['present_in_latest_snapshot'])
        self.assertEqual(current[0]['lifecycle_status'], 'unknown')
        self.assertEqual([e['event'] for e in events], ['first_observed'])


class RunTests(unittest.TestCase):
    def write(self, folder, name, data):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(json.dumps(data) if not isinstance(data, str) else data, encoding='utf8')

    def test_run_isolates_bad_files_and_reports_stale_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.write(tmp / 'raw/study_australia', 'good.json', snapshot([FEE]))
            self.write(tmp / 'raw/study_australia', 'broken.json', '{not json')
            self.write(tmp / 'raw/study_australia', 'forbidden.json', snapshot([FEE], http_status=403))
            self.write(tmp / 'runs', 'a.json', {'source_id': 'education_newsroom', 'status': 'failed',
                                                'http_status': 403, 'error': '403', 'started_at': '2026-10-02'})
            summary = run(tmp / 'raw', tmp / 'runs', tmp / 'out', tmp / 'approvals.json')
            self.assertEqual(summary['valid_snapshots'], 1)
            self.assertEqual(summary['invalid_files'], 2)
            self.assertEqual(summary['awaiting_decision'], 1)
            self.assertEqual(summary['validated_changes'], 0)
            audit = json.loads((tmp / 'out/source_audit.json').read_text())
            education = next(r for r in audit['sources'] if r['source_id'] == 'education_newsroom')
            self.assertTrue(education['snapshot_may_be_stale'])
            self.assertTrue(education['no_snapshot'])
            self.assertIn('education_newsroom', (tmp / 'out/RUN_REPORT.md').read_text())

    def test_latest_attempt_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.write(tmp, 'a.json', {'source_id': 's', 'status': 'failed', 'started_at': '2026-10-01'})
            self.write(tmp, 'b.json', {'source_id': 's', 'status': 'success', 'started_at': '2026-10-02'})
            self.assertEqual(latest_attempts(tmp)['s']['status'], 'success')

    def test_snapshots_are_loaded_oldest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.write(tmp, 'z.json', snapshot([FEE], '2026-10-01T00:00:00+00:00'))
            self.write(tmp, 'a.json', snapshot([FEE], '2026-10-03T00:00:00+00:00'))
            valid, _ = load_snapshots(tmp)
            self.assertEqual([d['collected_at'][:10] for _, d in valid], ['2026-10-01', '2026-10-03'])


if __name__ == '__main__':
    unittest.main()
