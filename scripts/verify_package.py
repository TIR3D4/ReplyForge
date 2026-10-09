#!/usr/bin/env python3
"""Check source archive contents and every declared digest without extracting."""
from pathlib import Path
import hashlib
import tomllib
import zipfile

root = Path(__file__).resolve().parent.parent
version = tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
prefix = 'ReplyForge-' + version
archive = root/'dist'/(prefix+'.zip')
with zipfile.ZipFile(archive) as bundle:
    assert bundle.testzip() is None
    manifest = bundle.read(prefix+'/MANIFEST.sha256').decode().splitlines()
    for line in manifest:
        digest, name = line.split('  ', 1)
        assert name != '.env' and '..' not in Path(name).parts
        assert hashlib.sha256(bundle.read(prefix+'/'+name)).hexdigest() == digest, name
    for required in ['compose.yml','Dockerfile','requirements.lock','scripts/install.py','scripts/setup.py',
                     'templates/inbox.html','static/admin.css','migrations/versions/0011_release_runtime.py']:
        assert prefix+'/'+required in bundle.namelist()
print('PASS: installation archive, required runtime files and SHA-256 manifest')
