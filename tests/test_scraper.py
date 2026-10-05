"""Collector tests: evidence retention, immutable storage and persisted failed runs."""
import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import requests

from scraper.base_scraper import (PDF_MEDIA_TYPE, decode_html, download_page, extract_document_data,
                                  extract_page_data, is_pdf, pdf_paragraphs, scrape_source)
from scraper.run_scraper import run_sources
from scraper.storage import save_json, write_unique_json
from scraper.sources import SOURCES

NEWS_HTML = """
<html><head><title>News</title></head><body>
<nav><ul><li><a href="/home">Home page menu item</a></li></ul></nav>
<main>
  <ul>
    <li><a href="/news/fee-rise">Student Visa Application Charge increase</a>
        <span>3 July 2026</span>
        <p>The charge for Student visa and Temporary Graduate visa increased on 1 July 2026.</p></li>
    <li><a href="https://example.gov.au/ed">Education settings</a> <span>15 July 2026</span></li>
  </ul>
  <h2>Short heading</h2>
  <p>Last updated 2/10/2026 10:10 AM</p>
</main>
<footer><p>Footer text that is boilerplate</p></footer>
</body></html>
"""


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.data = extract_page_data(NEWS_HTML, 'https://example.gov.au/news', 'https://example.gov.au/news')

    def test_news_cards_keep_title_date_text_and_link_together(self):
        card = next(b for b in self.data['content_blocks'] if 'Application Charge' in b['text'])
        self.assertIn('3 July 2026', card['text'])
        self.assertIn('increased on 1 July 2026', card['text'])
        self.assertEqual(card['href'], 'https://example.gov.au/news/fee-rise')
        self.assertEqual(card['link_text'], 'Student Visa Application Charge increase')

    def test_navigation_and_footer_are_not_collected(self):
        texts = ' '.join(b['text'] for b in self.data['content_blocks'])
        self.assertNotIn('menu item', texts)
        self.assertNotIn('Footer text', texts)

    def test_original_html_hashes_and_page_date_are_retained(self):
        self.assertEqual(self.data['raw_html'], NEWS_HTML)
        self.assertEqual(self.data['raw_html_hash'], sha256(NEWS_HTML.encode()).hexdigest())
        self.assertEqual(self.data['page_last_updated_text'], '2/10/2026 10:10 AM')
        self.assertEqual(self.data['quality_warnings'], [])

    def test_short_evidence_is_kept_not_dropped(self):
        data = extract_page_data('<html><body><p>Visa fee up</p></body></html>', 'u', 'https://x.gov.au/')
        self.assertEqual(data['paragraphs'], ['Visa fee up'])

    def test_empty_script_driven_page_is_flagged(self):
        html = '<html><body>' + '<script>1</script>' * 6 + '<div id="app"></div></body></html>'
        data = extract_page_data(html, 'u', 'https://x.gov.au/')
        self.assertIn('no_text_extracted', data['quality_warnings'])
        self.assertIn('possible_client_rendered_page', data['quality_warnings'])

    def test_decode_html_prefers_declared_utf8(self):
        self.assertEqual(decode_html('<meta charset="utf-8">Café'.encode('utf8'), 'iso-8859-1').count('é'), 1)


def minimal_pdf(lines):
    content = b'BT /F1 12 Tf 12 TL 20 260 Td\n'
    for line in lines:
        content += b'(' + line.encode('ascii') + b') Tj T*\n'
    content += b'ET'
    objects = [
        b'<</Type/Catalog/Pages 2 0 R>>', b'<</Type/Pages/Kids[3 0 R]/Count 1>>',
        b'<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>',
        b'<</Length ' + str(len(content)).encode() + b'>>stream\n' + content + b'\nendstream',
        b'<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>']
    out, offsets = bytearray(b'%PDF-1.4\n'), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b' 0 obj' + body + b'endobj\n'
    start = len(out)
    out += b'xref\n0 ' + str(len(objects) + 1).encode() + b'\n0000000000 65535 f \n'
    for offset in offsets:
        out += ('%010d 00000 n \n' % offset).encode()
    out += (b'trailer<</Size ' + str(len(objects) + 1).encode() + b'/Root 1 0 R>>\nstartxref\n'
            + str(start).encode() + b'\n%%EOF\n')
    return bytes(out)


class PdfTests(unittest.TestCase):
    def test_pdf_detected_by_type_or_signature(self):
        self.assertTrue(is_pdf(b'%PDF-1.7', 'application/octet-stream'))
        self.assertFalse(is_pdf('<html></html>', 'text/html'))

    def test_pdf_paragraphs_rejoin_wrapped_lines(self):
        self.assertEqual(pdf_paragraphs('Student visa fee\nrises soon.\n\nSecond.'),
                         ['Student visa fee rises soon.', 'Second.'])

    def test_pdf_text_becomes_blocks(self):
        pdf = minimal_pdf(['Student visa rules change from 1 July 2026.'])
        data = extract_document_data(pdf, 'https://x.gov.au/f.pdf', 'https://x.gov.au/f.pdf', PDF_MEDIA_TYPE)
        self.assertEqual(data['media_type'], PDF_MEDIA_TYPE)
        self.assertTrue(any('1 July 2026' in b['text'] for b in data['content_blocks']))
        self.assertEqual(data['raw_document_hash'], sha256(pdf).hexdigest())
        self.assertIsNone(data['raw_html'])


class StorageAndRunTests(unittest.TestCase):
    def source(self):
        return {'source_id': 'demo_news', 'organisation': 'Demo Dept', 'url': 'https://example.gov.au/news',
                'source_group': 'government', 'primary_government_source': True}

    def test_snapshots_never_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = {'source_id': 'demo', 'organisation': 'Demo Dept'}
            with patch('scraper.storage.datetime') as clock:
                from datetime import datetime, timezone
                clock.now.return_value = datetime(2026, 10, 5, tzinfo=timezone.utc)
                first, second = save_json(dict(record, n=1), tmp), save_json(dict(record, n=2), tmp)
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text())['n'], 1)

    def test_failed_attempts_are_persisted_and_exit_code_is_one(self):
        response = requests.Response()
        response.status_code = 403
        error = requests.HTTPError('403 Client Error', response=response)
        with tempfile.TemporaryDirectory() as tmp, patch('scraper.run_scraper.scrape_source', side_effect=error):
            code = run_sources([self.source()], Path(tmp, 'raw'), Path(tmp, 'runs'), delay=0)
            logs = [json.loads(p.read_text()) for p in Path(tmp, 'runs').glob('*.json')]
            self.assertEqual(code, 1)
            self.assertEqual(logs[0]['status'], 'failed')
            self.assertEqual(logs[0]['http_status'], 403)
            self.assertFalse(list(Path(tmp, 'raw').rglob('*.json')))

    def test_successful_run_saves_snapshot_and_log(self):
        data = extract_page_data(NEWS_HTML, 'https://example.gov.au/news', 'https://example.gov.au/news')
        data.update(source_id='demo_news', organisation='Demo Dept', http_status=200, collection_method='http')
        with tempfile.TemporaryDirectory() as tmp, patch('scraper.run_scraper.scrape_source', return_value=data):
            code = run_sources([self.source()], Path(tmp, 'raw'), Path(tmp, 'runs'), delay=0)
            self.assertEqual(code, 0)
            self.assertEqual(len(list(Path(tmp, 'raw').rglob('*.json'))), 1)
            log = json.loads(next(Path(tmp, 'runs').glob('*.json')).read_text())
            self.assertEqual(log['status'], 'success')
            self.assertTrue(Path(log['snapshot_path']).exists())

    def test_download_uses_no_browser_fallback_and_raises_on_403(self):
        response = requests.Response()
        response.status_code = 403
        response.url = 'https://example.gov.au/'
        with patch('scraper.base_scraper.requests.get', return_value=response):
            with self.assertRaises(requests.HTTPError):
                download_page('https://example.gov.au/')

    def test_scrape_source_records_source_identity(self):
        with patch('scraper.base_scraper.download_page',
                   return_value=(NEWS_HTML, 'https://example.gov.au/news', 200, 'text/html')):
            data = scrape_source(self.source())
        self.assertEqual(data['module'], 'visa_regulatory')
        self.assertTrue(data['primary_government_source'])
        self.assertEqual(data['http_status'], 200)


class RegistryTests(unittest.TestCase):
    def test_source_registry_is_consistent(self):
        ids = [s['source_id'] for s in SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        for s in SOURCES:
            self.assertTrue(s['url'].startswith('https://'), s['source_id'])
            self.assertIn(s['source_group'], {'government', 'industry'})
            self.assertEqual(s['source_group'] == 'government', s['primary_government_source'], s['source_id'])


if __name__ == '__main__':
    unittest.main()
