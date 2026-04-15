from __future__ import annotations

from types import SimpleNamespace

import backend.app.bootstrap as app_main


class _FakeBuilder:
    def __init__(self) -> None:
        self.concurrent_updates_value = None
        self.token_value = None
        self.request_value = None
        self.get_updates_request_value = None
        self.post_shutdown_value = None
        self.app = SimpleNamespace(bot_data={}, add_error_handler=lambda handler: None)

    def token(self, token: str):
        self.token_value = token
        return self

    def concurrent_updates(self, value: bool):
        self.concurrent_updates_value = value
        return self

    def request(self, request):
        self.request_value = request
        return self

    def get_updates_request(self, request):
        self.get_updates_request_value = request
        return self

    def post_shutdown(self, callback):
        self.post_shutdown_value = callback
        return self

    def build(self):
        return self.app


def test_build_application_uses_serial_updates(monkeypatch):
    fake_builder = _FakeBuilder()
    captured_requests: list[tuple[object, dict]] = []
    settings = SimpleNamespace(
        log_level="INFO",
        database_url="postgresql+asyncpg://example",
        database_connect_timeout_seconds=10,
        proxy_url=None,
        bot_token="token",
        telegram_connection_pool_size=32,
        telegram_pool_timeout_seconds=15.0,
        telegram_connect_timeout_seconds=10.0,
        telegram_read_timeout_seconds=20.0,
        telegram_write_timeout_seconds=20.0,
    )
    fake_db = object()
    captured_db: list[tuple[str, int]] = []

    class _FakeRequest:
        def __init__(self, proxy=None, **kwargs):
            captured_requests.append((proxy, kwargs))

    monkeypatch.setattr(app_main, "get_settings", lambda: settings)
    monkeypatch.setattr(app_main, "configure_logging", lambda level: None)
    def fake_create_database(url: str, connect_timeout_seconds: int = 10):
        captured_db.append((url, connect_timeout_seconds))
        return fake_db

    monkeypatch.setattr(app_main, "create_database", fake_create_database)
    monkeypatch.setattr(app_main, "_register_commands", lambda app: None)
    monkeypatch.setattr(app_main, "_register_routers", lambda app: None)
    monkeypatch.setattr(app_main, "_register_common_handlers", lambda app: None)
    monkeypatch.setattr(app_main, "HTTPXRequest", _FakeRequest)
    monkeypatch.setattr(app_main.Application, "builder", staticmethod(lambda: fake_builder))

    app = app_main.build_application()

    assert app is fake_builder.app
    assert fake_builder.concurrent_updates_value is False
    assert captured_db == [("postgresql+asyncpg://example", 10)]
    assert len(captured_requests) == 2
    assert captured_requests[0][1]["connection_pool_size"] == 32
    assert captured_requests[0][1]["pool_timeout"] == 15.0
    assert captured_requests[0][1]["read_timeout"] == 20.0
    assert app.bot_data["settings"] is settings
    assert app.bot_data["db"] is fake_db


def test_check_single_instance_skips_lock_inside_container(monkeypatch, tmp_path):
    pid_file = tmp_path / "tggrouprobot.pid"
    pid_file.write_text("999999")

    monkeypatch.setattr(app_main, "_PID_FILE", str(pid_file))
    monkeypatch.setattr(app_main, "_should_skip_single_instance_lock", lambda: True)

    app_main._check_single_instance()

    assert pid_file.read_text() == "999999"


def test_check_single_instance_allows_current_pid(monkeypatch, tmp_path):
    pid_file = tmp_path / "tggrouprobot.pid"
    pid_file.write_text(str(app_main.os.getpid()))

    monkeypatch.setattr(app_main, "_PID_FILE", str(pid_file))
    monkeypatch.setattr(app_main, "_should_skip_single_instance_lock", lambda: False)

    app_main._check_single_instance()
