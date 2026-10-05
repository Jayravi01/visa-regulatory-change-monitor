"""Rule tests: dates, visa categories, change types and suggestions use only source text."""
import unittest

from processing.classify import (classify_change_type, detect_visa_categories, extract_dates,
                                 find_dates, is_relevant, suggest_cover_types, suggest_impact)


class DateTests(unittest.TestCase):
    def test_find_dates_handles_common_australian_formats(self):
        text = '28 August 2026, 3 Jul 2026, 2026-09-15 and 2/10/2026.'
        self.assertEqual([d['iso'] for d in find_dates(text)],
                         ['2026-08-28', '2026-07-03', '2026-09-15', '2026-10-02'])

    def test_impossible_dates_are_ignored(self):
        self.assertEqual(find_dates('31 February 2026 and 2026-13-40'), [])

    def test_effective_and_published_dates_are_separated(self):
        text = '3 July 2026 Student visa fee rise. The charge increased on 1 July 2026.'
        self.assertEqual(extract_dates(text), ('2026-07-03', '2026-07-01'))

    def test_effective_date_is_none_when_not_announced(self):
        published, effective = extract_dates('15 July 2026 Australia confirms international education settings')
        self.assertEqual(published, '2026-07-15')
        self.assertIsNone(effective)

    def test_collection_date_is_never_substituted(self):
        self.assertEqual(extract_dates('Changes to the student visa are coming.'), (None, None))

    def test_listing_item_with_one_trailing_date_is_published(self):
        text = 'Student visa application charge increase and what it means for you which was announced 28 August 2026'
        self.assertEqual(extract_dates(text), (None, None))
        self.assertEqual(extract_dates(text, listing_item=True), ('2026-08-28', None))

    def test_two_unlabelled_dates_are_not_guessed_for_listing_items(self):
        text = 'Long student visa notice about reforms with dates 5 May 2026 and 6 June 2026 appearing later'
        self.assertEqual(extract_dates(text, listing_item=True), (None, None))


class VisaTests(unittest.TestCase):
    def test_subclass_numbers_need_visa_context(self):
        self.assertEqual(detect_visa_categories('Fee rises by $500 on 1 July.'), ([], False))
        self.assertEqual(detect_visa_categories('Student (subclass 500) rules change'), (['500'], True))
        self.assertEqual(detect_visa_categories('The 485 visa now requires a new test'), (['485'], True))

    def test_named_visas_map_to_subclasses(self):
        cats, specific = detect_visa_categories('Working holiday and Temporary Graduate visas')
        self.assertEqual(cats, ['417', '462', '485'])
        self.assertTrue(specific)

    def test_general_migration_is_the_only_fallback(self):
        self.assertEqual(detect_visa_categories('New migration program announced'), (['general_migration'], False))


class TypeAndImpactTests(unittest.TestCase):
    def test_change_types(self):
        cases = {
            'Visa processing times have improved': 'processing_time',
            'Student Visa Application Charge increase': 'fee_change',
            'Work rights for student visa holders': 'visa_condition',
            'New genuine student requirement': 'compliance_requirement',
            'Eligibility for the 485 visa narrows': 'eligibility',
            'Minister announces a new policy': 'policy_announcement',
            'Gardening tips': 'other',
        }
        for text, expected in cases.items():
            self.assertEqual(classify_change_type(text), expected, text)

    def test_relevance_gate(self):
        self.assertTrue(is_relevant('Changes for international students'))
        self.assertFalse(is_relevant('Join our newsletter today'))

    def test_impact_is_only_a_suggestion(self):
        self.assertEqual(suggest_impact('fee_change', ['500'])[0], 'high')
        self.assertEqual(suggest_impact('fee_change', ['general_migration'])[0], 'medium')
        self.assertEqual(suggest_impact('processing_time', ['500'])[0], 'medium')
        self.assertEqual(suggest_impact('other', [])[0], 'low')

    def test_cover_suggestions(self):
        self.assertEqual(suggest_cover_types(['500', '485']), ['OSHC', 'OWHC'])
        self.assertIsNone(suggest_cover_types(['general_migration']))


if __name__ == '__main__':
    unittest.main()
