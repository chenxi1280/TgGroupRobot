"""Run the uploaded test snapshot on Shanghai; configuration arrives via stdin."""
import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg
from sqlalchemy.engine import URL


def main():
    config = json.load(sys.stdin)
    if (config['database'], config['user'], config['remote_port']) != ('tgr_ui_test', 'tgr_ui_test', 16445):
        raise RuntimeError('Unexpected isolated test database')
    with psycopg.connect(host='127.0.0.1', port=16445, dbname=config['database'], user=config['user'],
                        password=config['password'], autocommit=True, connect_timeout=5,
                        application_name='tggrouprobot-ui-host-guard') as guard:
        identity = guard.execute('SELECT current_database(),current_user').fetchone()
        marker = guard.execute('SELECT marker FROM public.tgr_test_guard WHERE id=1').fetchone()
        if identity != (config['database'],config['user']) or marker != (config['guard'],):
            raise RuntimeError('Isolated database identity/guard mismatch')
        if not guard.execute('SELECT pg_try_advisory_lock(20261020,16445)').fetchone()[0]:
            raise RuntimeError('Another regression owns the isolated test database')
        url = URL.create('postgresql+psycopg', username=config['user'],password=config['password'],
                         host='127.0.0.1',port=16445,database=config['database']).render_as_string(hide_password=False)
        env = {**os.environ,'DATABASE_URL':url,'TGR_REPAIR_TEST_DATABASE_URL':url,
               'BOT_TOKEN':'999000:TEST_TOKEN','BOT_ADMIN_IDS':'','PYTHONPATH':str(Path.cwd())}
        result = Path('ui-test-results.xml')
        process = subprocess.Popen([sys.executable,'-m','pytest','-q','-W','error','--tb=short',
                                    f'--junitxml={result}',*sys.argv[1:]],env=env,
                                   stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        try:
            assert process.stdout is not None
            with Path('ui-test-output.log').open('w') as output:
                for line in process.stdout:
                    safe = line.replace(config['password'],'[REDACTED_TEST_SECRET]')
                    output.write(safe)
                    output.flush()
                    try:
                        print(safe,end='',flush=True)
                    except BrokenPipeError:
                        sys.stdout = open(os.devnull, 'w')
            return process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            Path('ui-test-exit-code.txt').write_text(str(process.returncode))
            if result.exists():
                result.write_text(result.read_text().replace(config['password'],'[REDACTED_TEST_SECRET]'))


if __name__ == '__main__':
    raise SystemExit(main())
