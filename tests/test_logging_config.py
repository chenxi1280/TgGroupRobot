from __future__ import annotations

import structlog

from backend.platform.config.core.logging import configure_logging


def test_configure_logging_supports_current_structlog_api() -> None:
    configure_logging("INFO", "console")


def test_configure_logging_prints_info_by_default(capsys) -> None:
    configure_logging()
    log = structlog.get_logger("tests.logging_config")

    log.info("info_should_print")
    log.info("bot_starting")
    log.warning("warning_should_print")

    captured = capsys.readouterr()

    assert "info_should_print" in captured.out
    assert "bot_starting" in captured.out
    assert "warning_should_print" in captured.out
