#!/usr/bin/env python3
"""Build a tracked-source installation ZIP, excluding local secrets and caches."""
from pathlib import Path
import hashlib
import subprocess
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    prefix = 'ReplyForge-' + version
    target = ROOT/'dist'/(prefix+'.zip')
    target.parent.mkdir(exist_ok=True)
    tracked = subprocess.check_output(['git','ls-files','-z'], cwd=ROOT).decode().split('\0')
    hashes = []
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(filter(None, tracked)):
            path = ROOT/name
            if path.is_symlink() or not path.is_file() or name == '.env' or name.startswith(('backups/','artifacts/','dist/')):
                raise RuntimeError('Unsafe tracked release entry: ' + name)
            data = path.read_bytes()
            archive.writestr(prefix+'/'+name, data)
            hashes.append(hashlib.sha256(data).hexdigest() + '  ' + name)
        archive.writestr(prefix+'/MANIFEST.sha256', '\n'.join(hashes)+'\n')
    target.with_suffix('.zip.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name+'\n')
    print(target)


if __name__ == '__main__':
    main()
