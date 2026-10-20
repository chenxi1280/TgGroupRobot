"""Run UI regressions through a private SSH tunnel to the isolated project DB.

Credentials and the immutable instance guard are provisioned outside the repository.
No local database process or Docker daemon is started.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import threading

import psycopg
from psycopg.conninfo import make_conninfo
from sqlalchemy.engine import URL

CONFIG = Path.home() / ".config/shanghai-dev-middleware/tggrouprobot-test.json"
ROOT = Path(__file__).resolve().parents[1]


def _verify_config():
    if CONFIG.stat().st_mode & 0o077:
        raise RuntimeError("Test credentials must be readable only by their owner")
    config = json.loads(CONFIG.read_text())
    expected = {"host": "shanghai-tg-test-db", "container": "tggrouprobot-test-postgres",
                "database": "tgr_ui_test", "user": "tgr_ui_test", "remote_port": 16445}
    if any(config.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Unexpected test database identity")
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", config["host"],
         "sudo -n docker inspect --format '{{index .Config.Labels \"project\"}}/"
         "{{index .Config.Labels \"purpose\"}}' tggrouprobot-test-postgres"],
        capture_output=True, text=True, check=True)
    if result.stdout.strip() != "TgGroupRobot/isolated-test":
        raise RuntimeError("Remote container ownership mismatch")
    return config


def _wait_connection(config, port, tunnel):
    conninfo = make_conninfo(host="127.0.0.1", port=port, dbname=config["database"],
                            user=config["user"], password=config["password"], connect_timeout=2,
                            application_name="tggrouprobot-ui-test-guard",
                            options="-c tcp_keepalives_idle=30 -c tcp_keepalives_interval=10 -c tcp_keepalives_count=3")
    for _ in range(30):
        if tunnel.poll() is not None:
            break
        try:
            return psycopg.connect(conninfo, autocommit=True)
        except psycopg.OperationalError:
            time.sleep(0.2)
    raise RuntimeError("Shanghai test tunnel unavailable")


def _run(config, port, tunnel):
    with _wait_connection(config, port, tunnel) as guard:
        identity = guard.execute("SELECT current_database(), current_user").fetchone()
        marker = guard.execute("SELECT marker FROM public.tgr_test_guard WHERE id=1").fetchone()
        if identity != (config["database"], config["user"]) or marker != (config["guard"],):
            raise RuntimeError("Test database guard mismatch; refusing migration or tests")
        if not guard.execute("SELECT pg_try_advisory_lock(20261020, 16445)").fetchone()[0]:
            raise RuntimeError("Another regression owns the Shanghai test database")
        url = URL.create("postgresql+psycopg", username=config["user"],
                         password=config["password"], host="127.0.0.1",
                         port=port, database=config["database"]).render_as_string(hide_password=False)
        env = {**os.environ, "DATABASE_URL": url, "TGR_REPAIR_TEST_DATABASE_URL": url,
               "BOT_TOKEN": "999000:TEST_TOKEN", "BOT_ADMIN_IDS": "", "PYTHONPATH": str(ROOT)}
        migration = (
            "import asyncio, os\n"
            "from backend.platform.db.runtime.session import create_database\n"
            "from backend.platform.db.runtime.database_migrations import migrate_database\n"
            "async def run():\n"
            " d=create_database(os.environ['DATABASE_URL'])\n"
            " try: await migrate_database(d.engine)\n"
            " finally: await d.engine.dispose()\n"
            "asyncio.run(run())\n")
        subprocess.run([sys.executable, "-c", migration], cwd=ROOT, env=env, check=True)
        return _pytest(env, config, tunnel)


def _pytest(env, config, tunnel):
    process = subprocess.Popen([sys.executable, "-m", "pytest", "-v", "-W", "error", "--tb=short",
                                *sys.argv[1:]], cwd=ROOT, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    def forward_output():
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line.replace(config["password"], "[REDACTED_TEST_SECRET]"))
            sys.stdout.flush()
    reader = threading.Thread(target=forward_output, daemon=True)
    reader.start()
    try:
        while process.poll() is None:
            if tunnel.poll() is not None:
                print("Shanghai SSH tunnel ended; stopping tests, do not interpret connection failures as application regressions.", flush=True)
                process.terminate()
                break
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        return process.wait(timeout=15)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        reader.join(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


def main():
    config = _verify_config()
    with open(Path(tempfile.gettempdir()) / "tgr-shanghai-ui-tests.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        tunnel = subprocess.Popen(["ssh", "-N", "-o", "BatchMode=yes",
                                   "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                                   "-o", "ControlMaster=no", "-o", "ControlPath=none",
                                   "-o", "ExitOnForwardFailure=yes",
                                   "-L", f"127.0.0.1:{port}:127.0.0.1:{config['remote_port']}",
                                   config["host"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            return _run(config, port, tunnel)
        finally:
            tunnel.terminate()
            tunnel.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
