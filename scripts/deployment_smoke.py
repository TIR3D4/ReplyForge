#!/usr/bin/env python3
"""Disposable Compose smoke test. Never uses .env or existing project volumes."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import uuid

import yaml

ROOT = Path(__file__).resolve().parent.parent


def main():
    project = 'replyforge_smoke_' + uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix='replyforge-smoke-') as folder:
        tmp = Path(folder)
        env = tmp / '.env'
        env.write_text('\n'.join([
            'BOT_TOKEN=123:synthetic-smoke-token',
            'WEBHOOK_SECRET=synthetic-webhook-secret-012345',
            'ADMIN_PASSWORD=synthetic-admin-password-012345',
            'BINDING_PEPPER=synthetic-binding-pepper-012345',
            'INTERNAL_API_KEY=synthetic-internal-key-012345',
            'POSTGRES_PASSWORD=synthetic-db-password-012345',
            'AUTO_REPLY_ENABLED=false',
            'BUSINESS_CONFIG=config/business.yaml',
        ]) + '\n')
        os.chmod(env, 0o600)
        topology = yaml.safe_load((ROOT/'compose.yml').read_text())
        for service in topology['services'].values():
            if 'build' in service:
                service['build'] = str(ROOT)
            if 'env_file' in service:
                service['env_file'] = str(env)
        topology['services']['api']['ports'] = ['127.0.0.1::8080']
        compose = tmp/'compose.yml'
        compose.write_text(yaml.safe_dump(topology))
        prefix = ['docker','compose','--project-name',project,'--env-file',str(env),'-f',str(compose)]
        def run(*args, **kwargs):
            return subprocess.run([*prefix,*args], check=True, **kwargs)
        try:
            run('up','-d','--build', 'api', 'worker')
            port = run('port','api','8080',capture_output=True,text=True).stdout.strip().rsplit(':',1)[1]
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def wait_ready():
                deadline = time.monotonic()+90
                while time.monotonic()<deadline:
                    try:
                        with opener.open('http://127.0.0.1:'+port+'/readyz',timeout=3) as response:
                            if json.load(response)['status']=='ready':
                                return
                    except (OSError, ValueError):
                        pass
                    time.sleep(1)
                raise RuntimeError('Worker did not become ready')
            wait_ready()
            run('restart','worker','api')
            wait_ready()
            dump = run('exec','-T','db','pg_dump','-U','replyforge','-d','replyforge','-Fc',capture_output=True).stdout
            run('exec','-T','db','createdb','-U','replyforge','restore_check')
            run('exec','-T','db','pg_restore','-U','replyforge','-d','restore_check',input=dump)
            restored = run('exec','-T','db','psql','-U','replyforge','-d','restore_check','-Atc','SELECT version_num FROM alembic_version',capture_output=True,text=True).stdout.strip()
            assert restored == '0010_operators', restored
            print('PASS: migrations, API/worker readiness, restart, dump and isolated restore')
        finally:
            run('down','--volumes','--remove-orphans')


if __name__ == '__main__':
    main()
