from __future__ import annotations

from types import SimpleNamespace

from bot.handlers.scheduled_message_handler import ScheduledMessageHandler
from bot.keyboards.integration.scheduled_message import sm_list_keyboard


def test_scheduled_message_list_keyboard_matches_document_layout() -> None:
    tasks = [
        SimpleNamespace(
            short_id="abcd1234",
            enabled=True,
        ),
    ]

    keyboard = sm_list_keyboard(tasks, chat_id=-100123)

    assert keyboard.inline_keyboard[0][0].text == "🔢 编号:abcd1234"
    assert keyboard.inline_keyboard[0][1].text == "❌ 关闭"
    assert keyboard.inline_keyboard[0][2].text == "✏️ 修改"
    assert keyboard.inline_keyboard[0][3].text == "🗑 删除"
    assert keyboard.inline_keyboard[1][0].text == "➕ 添加一条"


def test_format_task_list_uses_minimum_one_page_for_empty_list() -> None:
    handler = ScheduledMessageHandler()

    text = handler._format_task_list([], page=0, page_size=10)

    assert "0 条数据，第 1 页/共 1 页" in text


def test_format_task_list_renders_task_summary_lines() -> None:
    handler = ScheduledMessageHandler()
    tasks = [
        SimpleNamespace(
            short_id="abcd1234",
            title="早安播报",
            enabled=True,
            repeat_interval_min=60,
            end_at=None,
            next_run_at=1_800_000_000,
        ),
    ]

    text = handler._format_task_list(tasks, page=0, page_size=10)

    assert "#abcd1234 早安播报" in text
    assert "状态: 启用" in text
    assert "终止: 无限制" in text
    assert "下次:" in text
