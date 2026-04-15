from __future__ import annotations

from types import SimpleNamespace

from backend.features.automation.scheduled_message_handler import ScheduledMessageHandler, _parse_buttons_text
from backend.features.automation.ui.scheduled_message import sm_detail_keyboard, sm_list_keyboard


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


def test_scheduled_message_detail_panel_marks_configured_fields() -> None:
    handler = ScheduledMessageHandler()
    task = SimpleNamespace(
        short_id="abcd1234",
        title="早安播报",
        enabled=True,
        repeat_interval_min=60,
        day_start_hour=0,
        day_end_hour=23,
        start_at=1_800_000_000,
        end_at=None,
        next_run_at=None,
        text="今日通知",
        media_type="photo",
        media_file_id="photo-file-id",
        buttons=[[{"text": "官网", "url": "https://example.com"}]],
        delete_previous=True,
        pin_message=False,
    )

    text = handler._format_task_detail(task)
    keyboard = sm_detail_keyboard(task, chat_id=-100123)

    assert "📮 标题备注: 早安播报" in text
    assert "🏞️ 封面设置: 已设置 photo" in text
    assert "📄 文本内容: 今日通知" in text
    assert "⭕ 设置按钮: 已设置 1 个" in text
    assert "⏰ 开始时间:" in text
    assert keyboard.inline_keyboard[1][0].text == "✅ 标题备注"
    assert keyboard.inline_keyboard[1][1].text == "✅ 设置封面"
    assert keyboard.inline_keyboard[2][0].text == "✅ 设置文本"
    assert keyboard.inline_keyboard[2][1].text == "✅ 设置按钮"
    assert keyboard.inline_keyboard[5][1].text == "✅ 启用"


def test_parse_buttons_text_supports_line_format_and_same_row_separator() -> None:
    buttons = _parse_buttons_text(
        "官网|example.com ; 帮助|https://help.example.com\n"
        "频道|@demo_channel"
    )

    assert buttons == [
        [
            {"text": "官网", "url": "https://example.com"},
            {"text": "帮助", "url": "https://help.example.com"},
        ],
        [
            {"text": "频道", "url": "https://t.me/demo_channel"},
        ],
    ]
