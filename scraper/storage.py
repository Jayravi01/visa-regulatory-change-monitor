"""Immutable JSON snapshots with repository-relative defaults."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def make_folder_name(organisation):
    return re.sub(r'[^a-z0-9]+', '_', organisation.lower()).strip('_') or 'unknown'


def write_unique_json(data, folder, prefix):
    """Write a new file and never replace an existing one."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    target = folder / f'{make_folder_name(prefix)}_{stamp}_{uuid4().hex}.json'
    # Publish a fully written file by hard link so a crash never leaves a partial snapshot.
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=folder)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
    finally:
        os.unlink(temporary)
    return target


def save_json(data, raw_dir=None):
    folder = Path(raw_dir) if raw_dir is not None else ROOT / 'data/raw'
    return write_unique_json(data, folder / make_folder_name(data['organisation']), data['source_id'])
