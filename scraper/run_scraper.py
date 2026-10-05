"""Collect the registered public sources and persist each attempt, including failures."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import time

from scraper.sources import SOURCES
from scraper.base_scraper import scrape_source
from scraper.storage import ROOT, save_json, write_unique_json

# Seconds between requests: a low, polite rate for public government sites.
REQUEST_DELAY = 2


def run_sources(sources, raw_dir=None, log_dir=None, delay=REQUEST_DELAY):
    """
    Collect each source once. Every attempt writes a run log, success or failure.

    Returns 1 if any source failed, so a scheduler can see partial failure.
    A blocked source (for example HTTP 403) is logged, never worked around.
    """
    log_dir = Path(log_dir) if log_dir is not None else ROOT / 'data/runs'
    failures = 0
    for index, source in enumerate(sources):
        attempt = {'module': 'visa_regulatory', 'source_id': source['source_id'],
                   'requested_url': source['url'],
                   'started_at': datetime.now(timezone.utc).isoformat()}
        try:
            data = scrape_source(source)
            saved = save_json(data, raw_dir)
            attempt.update(status='success', http_status=data['http_status'],
                           media_type=data.get('media_type'),
                           collection_method=data.get('collection_method', 'http'),
                           snapshot_path=str(saved.resolve()), final_url=data['final_url'],
                           quality_warnings=data.get('quality_warnings', []))
        except Exception as exc:
            failures += 1
            response = getattr(exc, 'response', None)
            attempt.update(status='failed', error_type=type(exc).__name__, error=str(exc),
                           http_status=response.status_code if response is not None else None)
        attempt['finished_at'] = datetime.now(timezone.utc).isoformat()
        log = write_unique_json(attempt, log_dir, source['source_id'])
        print(f"{source['source_id']}: {attempt['status']} | log: {log}", flush=True)
        if index + 1 < len(sources):
            time.sleep(delay)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--organisation')
    parser.add_argument('--source', action='append', help='Source ID; may be repeated')
    parser.add_argument('--raw-dir', type=Path)
    parser.add_argument('--log-dir', type=Path)
    args = parser.parse_args()
    if args.source and set(args.source) - {s['source_id'] for s in SOURCES}:
        parser.error('Unknown source ID')
    selected = [s for s in SOURCES
                if (not args.organisation or s['organisation'].lower() == args.organisation.lower())
                and (not args.source or s['source_id'] in args.source)]
    if not selected:
        parser.error('No matching sources')
    return run_sources(selected, args.raw_dir, args.log_dir)


if __name__ == '__main__':
    raise SystemExit(main())
