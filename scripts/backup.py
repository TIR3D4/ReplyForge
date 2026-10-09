#!/usr/bin/env python3
"""Atomic PostgreSQL backup via the installation's Compose DB container."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import hashlib

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default=str(ROOT/'backups'))
    args = parser.parse_args()
    folder = Path(args.directory).resolve()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = folder/('replyforge-' + stamp + '.dump')
    partial = target.with_suffix('.partial')
    descriptor = os.open(partial, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            subprocess.run(['docker','compose','exec','-T','db','pg_dump','-U','replyforge','-d','replyforge','-Fc'],
                           cwd=ROOT, stdout=output, check=True)
            output.flush(); os.fsync(output.fileno())
        if partial.stat().st_size < 100:
            raise RuntimeError('Backup is unexpectedly small')
        partial.rename(target)
        with target.open('rb') as saved:
            digest = hashlib.file_digest(saved, 'sha256').hexdigest()
        target.with_suffix('.sha256').write_text(digest + '  ' + target.name + '\n')
        print('Backup created:', target)
        print('Protect/encrypt offsite copies and rehearse restoration to a separate database.')
    finally:
        partial.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
