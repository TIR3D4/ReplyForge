#!/usr/bin/env python3
"""Interactive first install; preserves existing configuration and customer databases."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preset', choices=('generic','azadbird'), default='generic')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    subprocess.run(['docker','compose','version'], check=True, cwd=ROOT)
    if not (ROOT/'.env').exists():
        if args.check_only:
            raise SystemExit('Missing .env. Run install without --check-only to configure.')
        subprocess.run([sys.executable, str(ROOT/'scripts/setup.py'),'--preset',args.preset], check=True, cwd=ROOT)
    subprocess.run(['docker','compose','config','--quiet'], check=True, cwd=ROOT)
    if args.check_only:
        print('Compose and environment syntax validated; no containers changed.')
        return
    print('Existing .env is preserved. This starts services and runs forward migrations.')
    response = input('For an existing install, verify a backup first. Type INSTALL to continue: ')
    if response != 'INSTALL':
        raise SystemExit('No containers changed.')
    subprocess.run(['docker','compose','up','-d','--build'], check=True, cwd=ROOT)
    subprocess.run(['docker','compose','exec','-T','api','replyforge','doctor'], check=True, cwd=ROOT)
    print('Next: configure HTTPS, register webhook, test human replies, then enable automation.')
    print('AI text pricing must be configured before external model calls are allowed.')


if __name__ == '__main__':
    main()
