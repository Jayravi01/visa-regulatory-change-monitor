"""Review tests: nothing is published without a matching, valid, human decision."""
import json
import tempfile
import unittest
from pathlib import Path

from processing import review
from processing.review import ReviewError, interactive_review, record_decision
from processing.run_processing import run
from tests.test_processing import FEE, snapshot


class ReviewCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.raw, self.out = self.tmp / 'raw', self.tmp / 'out'
        self.approvals = self.tmp / 'approvals.json'
        self.snap(FEE)

    def tearDown(self):
        self._tmp.cleanup()

    def snap(self, block, when='2026-10-01T00:00:00+00:00', source_id='studyaustralia_news', primary=True):
        self.raw.mkdir(exist_ok=True)
        name = f'{source_id}_{when}.json'.replace(':', '')
        (self.raw / name).write_text(json.dumps(snapshot([block], when, source_id, primary)), encoding='utf8')

    def process(self):
        return run(self.raw, self.tmp / 'runs', self.out, self.approvals)

    def target(self):
        self.process()
        return json.loads((self.out / 'approval_targets.json').read_text())[0]

    def decide(self, target, decision='approved', corrections=None, reviewer='Reviewer'):
        return record_decision(target['record_id'], decision, reviewer, 'note',
                               corrections, self.out, self.approvals)

    def validated(self):
        return json.loads((self.out / 'validated_changes.json').read_text())

    GOOD = {'impact_level': 'high', 'impact_reason': 'Fee rise lifts OSHC price sensitivity'}


class ApprovalTests(ReviewCase):
    def test_nothing_is_validated_without_a_decision(self):
        self.process()
        self.assertEqual(self.validated(), [])

    def test_approval_requires_reviewed_impact_and_reason(self):
        t = self.target()
        with self.assertRaisesRegex(ReviewError, 'impact_level'):
            self.decide(t)
        with self.assertRaisesRegex(ReviewError, 'impact_reason'):
            self.decide(t, corrections={'impact_level': 'high'})
        self.assertEqual(load := review.load_decisions(self.approvals), [])

    def test_approved_record_is_published_with_corrections(self):
        t = self.target()
        self.decide(t, corrections=dict(self.GOOD, affected_cover_types=['OSHC'], effective_date='2026-07-01'))
        self.process()
        (record,) = self.validated()
        self.assertEqual(record['review_status'], 'approved')
        self.assertEqual(record['impact_level'], 'high')
        self.assertEqual(record['affected_cover_types'], ['OSHC'])
        self.assertEqual(record['validation_issues'], [])
        self.assertEqual(record['visa_categories'], ['500'])

    def test_evidence_and_identity_fields_cannot_be_corrected(self):
        t = self.target()
        for field in ('evidence', 'fingerprint', 'source_id', 'record_id'):
            with self.assertRaisesRegex(ReviewError, 'cannot be corrected'):
                self.decide(t, corrections=dict(self.GOOD, **{field: 'x'}))

    def test_invalid_values_are_rejected(self):
        t = self.target()
        for bad in ({'effective_date': '1 July 2026'}, {'affected_cover_types': ['HOME']},
                    {'change_type': 'rumour'}, {'visa_categories': []}, {'publication_url': 'ftp://x'}):
            with self.assertRaises(ReviewError, msg=bad):
                self.decide(t, corrections=dict(self.GOOD, **bad))

    def test_secondary_source_needs_corroboration(self):
        for p in self.raw.glob('*.json'):
            p.unlink()
        self.snap(FEE, source_id='mia_media_releases', primary=False)
        t = self.target()
        with self.assertRaisesRegex(ReviewError, 'corroborat'):
            self.decide(t, corrections=self.GOOD)
        self.decide(t, corrections=dict(self.GOOD, corroboration_status='corroborated'))
        self.process()
        self.assertEqual(len(self.validated()), 1)

    def test_reject_and_needs_more_evidence_publish_nothing(self):
        t = self.target()
        self.decide(t, 'rejected')
        self.process()
        self.assertEqual(self.validated(), [])
        status = json.loads((self.out / 'approval_targets.json').read_text())[0]['review_status']
        self.assertEqual(status, 'rejected')
        self.decide(t, 'needs_more_evidence')
        self.process()
        queue = json.loads((self.out / 'approval_queue.json').read_text())
        self.assertEqual([q['review_status'] for q in queue], ['needs_more_evidence'])

    def test_latest_decision_wins_and_history_is_append_only(self):
        t = self.target()
        self.decide(t, corrections=self.GOOD)
        self.decide(t, 'rejected', reviewer='Second')
        self.process()
        self.assertEqual(self.validated(), [])
        self.assertEqual(len(review.load_decisions(self.approvals)), 2)

    def test_reviewer_name_is_required(self):
        t = self.target()
        with self.assertRaisesRegex(ReviewError, 'reviewer'):
            self.decide(t, 'rejected', reviewer='  ')


class StalenessTests(ReviewCase):
    def test_changed_evidence_makes_decision_stale_and_requeues(self):
        t = self.target()
        self.decide(t, corrections=self.GOOD)
        self.process()
        self.assertEqual(len(self.validated()), 1)

        changed = dict(FEE, text=FEE['text'] + ' The government has since raised the amount again.')
        self.snap(changed, when='2026-10-02T00:00:00+00:00')
        summary = self.process()
        self.assertEqual(summary['validated_changes'], 0)
        self.assertEqual(summary['awaiting_decision'], 1)
        self.assertEqual(summary['stale_decisions'], 1)
        audit = json.loads((self.out / 'approval_audit.json').read_text())
        self.assertEqual(len(audit['stale']), 1)

    def test_decision_for_vanished_target_is_orphaned(self):
        review.save_decisions(self.approvals, [{
            'decision_id': 'd1', 'target_id': 'gone', 'decision': 'approved', 'reviewer': 'R',
            'fingerprint': 'x', 'field_corrections': {}}])
        self.assertEqual(self.process()['orphaned_decisions'], 1)

    def test_malformed_decision_file_is_an_error(self):
        self.approvals.write_text('{"not": "a list"}')
        with self.assertRaises(ReviewError):
            review.load_decisions(self.approvals)
        self.approvals.write_text('[{"target_id": "x"}]')
        with self.assertRaises(ReviewError):
            review.load_decisions(self.approvals)


class InteractiveTests(ReviewCase):
    def scripted(self, answers):
        items = iter(answers)
        return lambda prompt='': next(items)

    def test_interactive_approval_saves_a_decision(self):
        self.target()
        saved = interactive_review(self.out, self.approvals, input_fn=self.scripted(
            ['Rev', 'a', 'high', 'Fee rise affects OSHC demand', '', 'checked']), output_fn=lambda *_: None)
        self.assertEqual(saved, 1)
        self.process()
        self.assertEqual(len(self.validated()), 1)

    def test_interactive_retries_after_invalid_approval(self):
        self.target()
        saved = interactive_review(self.out, self.approvals, reviewer='Rev', input_fn=self.scripted(
            ['a', 'huge', 'x', '', 'n1',        # invalid impact level -> not saved
             'r', 'wrong visa', ]), output_fn=lambda *_: None)
        self.assertEqual(saved, 1)
        self.assertEqual(review.load_decisions(self.approvals)[0]['decision'], 'rejected')

    def test_skip_and_quit_save_nothing(self):
        self.target()
        self.assertEqual(interactive_review(self.out, self.approvals, reviewer='Rev',
                                            input_fn=self.scripted(['s']), output_fn=lambda *_: None), 0)
        self.assertEqual(review.load_decisions(self.approvals), [])


class CommandLineTests(ReviewCase):
    def args(self, *more):
        return ['--output-dir', str(self.out), '--approvals-file', str(self.approvals),
                '--raw-dir', str(self.raw), '--runs-dir', str(self.tmp / 'runs'), *more]

    def test_approve_command_with_impact_flags(self):
        t = self.target()
        code = review.main(self.args('approve', t['record_id'], '--reviewer', 'Em',
                                     '--impact', 'medium', '--impact-reason', 'Context for demand'))
        self.assertEqual(code, 0)
        self.assertEqual(review.load_decisions(self.approvals)[0]['field_corrections']['impact_level'], 'medium')

    def test_unknown_target_returns_error_code(self):
        self.process()
        self.assertEqual(review.main(self.args('reject', 'nope', '--reviewer', 'Em')), 1)

    def test_list_and_show(self):
        t = self.target()
        self.assertEqual(review.main(self.args('list')), 0)
        self.assertEqual(review.main(self.args('show', t['record_id'])), 0)


if __name__ == '__main__':
    unittest.main()
