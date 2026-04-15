from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.moderation.anti_spam_config_handler import format_anti_spam_menu_text


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class _Db:
    def __init__(self):
        self.session_factory = lambda: _Session()


@pytest.mark.asyncio
async def test_group_lock_menu_uses_document_style_labels(monkeypatch):
    rendered: list[object] = []
    settings = SimpleNamespace(
        group_lock_delete_notice_mode="keep",
        group_lock_open_time="08:00",
        group_lock_close_time="02:00",
        group_lock_open_phrase="开群了",
        group_lock_close_phrase="关群了",
        group_lock_phrase_enabled=False,
        group_lock_schedule_enabled=False,
    )

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append(reply_markup)

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_group_lock_menu(update, context, -100123)

    keyboard = rendered[0]
    assert keyboard.inline_keyboard[0][0].text == "⚙️ 话术开关："
    assert keyboard.inline_keyboard[3][0].text == "⚙️ 定时开关："
    assert keyboard.inline_keyboard[6][0].text == "🧹 删除通知消息："


@pytest.mark.asyncio
async def test_rename_monitor_menu_uses_delete_label_with_colon(monkeypatch):
    rendered: list[object] = []
    settings = SimpleNamespace(
        name_change_monitor_enabled=False,
        name_change_monitor_template_text="模板",
        name_change_monitor_delete_after_seconds=60,
    )

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append(reply_markup)

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_rename_monitor_menu(update, context, -100123)

    keyboard = rendered[0]
    assert keyboard.inline_keyboard[3][0].text == "🧹 删除提示消息："


@pytest.mark.asyncio
async def test_control_permission_menu_includes_current_policy_summary(monkeypatch):
    rendered: list[str] = []
    settings = SimpleNamespace(control_permission_policy="owner_only")

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append(text)

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_control_permission_menu(update, context, -100123)

    assert rendered
    assert "当前策略：仅创建者" in rendered[0]
    assert "当前统一影响以下管理能力" in rendered[0]


@pytest.mark.asyncio
async def test_auto_delete_menu_shows_enabled_type_summary(monkeypatch):
    rendered: list[str] = []
    settings = SimpleNamespace(
        auto_delete_join=True,
        auto_delete_left=False,
        auto_delete_pinned=True,
        auto_delete_avatar=False,
        auto_delete_title=False,
        auto_delete_anonymous=True,
    )

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append(text)

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_auto_delete_menu(update, context, -100123)

    assert rendered
    assert "已开启类型：3/6" in rendered[0]
    assert "当前明细：进群、置顶、匿名消息" in rendered[0]


def test_anti_spam_text_marks_basic_mode() -> None:
    settings = SimpleNamespace(
        anti_spam_enabled=True,
        anti_spam_delete_notify=True,
        anti_spam_exempt_admin=True,
        anti_spam_action="delete",
        anti_spam_mute_duration=300,
        anti_spam_delete_notify_seconds=60,
        anti_spam_repeat_seconds=10,
        anti_spam_repeat_messages=3,
        anti_spam_rules={
            "ai_text": True,
            "global_ads": False,
            "flood_attack": True,
            "banned_accounts": False,
            "ai_image_ads": False,
            "block_links": True,
            "block_channel_alias": False,
            "block_forwards": False,
            "block_mentions": False,
            "block_eth_address": False,
            "clear_commands": False,
            "block_long_content": True,
            "message_max_length": 50,
            "name_max_length": 20,
            "exception_user_ids": [],
            "exception_chat_ids": [],
        },
    )

    text = format_anti_spam_menu_text("测试群", settings)

    assert "反垃圾" in text
    assert "集中配置页，可统一管理常见广告、链接、转发、超长内容和黑名单规则" in text
    assert "已启用规则: 4 项" in text
    assert "可用按钮快速切换，也可点“文本配置”一次性设置" in text


@pytest.mark.asyncio
async def test_engagement_home_shows_recent_summary_and_stats_entry(monkeypatch):
    rendered: list[tuple[str, object]] = []

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_counts(session, chat_id: int):
        return {"all": 4, "idle": 1, "running": 2, "finished": 1}

    async def fake_latest_running(session, chat_id: int):
        return SimpleNamespace(title="四月彩蛋", published_clue_count=2, clues=["a", "b", "c"])

    async def fake_get_reward(session, chat_id: int):
        return SimpleNamespace(enabled=True, reward_type="daily_increment", daily_message_target=200, command_keyword="我爱水群")

    async def fake_recent_stats(session, chat_id: int, days: int = 7):
        return [{"claim_count": 2}, {"claim_count": 1}]

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_egg_event_counts", fake_get_counts)
    monkeypatch.setattr(admin_handler, "get_latest_running_egg_event", fake_latest_running)
    monkeypatch.setattr(admin_handler, "get_engagement_chat_reward", fake_get_reward)
    monkeypatch.setattr(admin_handler, "get_recent_chat_reward_stats", fake_recent_stats)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_engagement_home(update, context, -100123)

    assert rendered
    text, keyboard = rendered[0]
    assert "运行中 2" in text
    assert "当前：四月彩蛋 | 线索 2/3" in text
    assert "近7日领取次数：3" in text
    assert keyboard.inline_keyboard[0][0].text == "➕ 添加彩蛋"
    assert keyboard.inline_keyboard[0][1].text == "🥚 彩蛋管理"
    assert keyboard.inline_keyboard[1][0].text == "🍬 水群激励"
    assert keyboard.inline_keyboard[1][1].text == "📊 水群数据"


@pytest.mark.asyncio
async def test_engagement_egg_menu_exposes_publish_and_pause_controls(monkeypatch):
    rendered: list[object] = []

    async def fake_get_event(session, chat_id: int, event_id: int):
        return SimpleNamespace(
            id=7,
            title="四月彩蛋",
            enabled=True,
            answer="答案",
            clues=["线索1", "线索2"],
            clue_rewards=[10, 8],
            clue_times=["09:00", "10:00"],
            winner_user_id=None,
            status="running",
            published_clue_count=1,
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append(reply_markup)

    monkeypatch.setattr(admin_handler, "get_egg_event", fake_get_event)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_engagement_egg(update, context, -100123, 7)

    keyboard = rendered[0]
    row_texts = [[button.text for button in row] for row in keyboard.inline_keyboard]
    assert ["👀 预览配置", "📤 立即发布"] in row_texts
    assert ["⏸ 暂停", "♻️ 重置活动"] in row_texts
    assert ["🔙 返回列表"] in row_texts


@pytest.mark.asyncio
async def test_game_menu_exposes_rounds_and_help(monkeypatch):
    rendered: list[object] = []

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_setting(session, chat_id: int):
        return SimpleNamespace(
            k3_enabled=True,
            blackjack_enabled=True,
            rake_ratio="0.1",
            rake_owner_user_id=None,
            auto_schedule_enabled=False,
            auto_start_time=None,
            auto_stop_time=None,
            delete_game_message_mode="keep",
        )

    async def fake_get_rake_owner(session, user_id):
        return "未设置"

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append(reply_markup)

    async def fake_get_chat_title(db, chat_id: int):
        return "测试群"

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler._admin_handler, "_get_chat_title", fake_get_chat_title)
    monkeypatch.setattr(admin_handler, "get_game_setting", fake_get_setting)
    monkeypatch.setattr(admin_handler, "get_game_rake_owner_label", fake_get_rake_owner)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_game_menu(update, context, -100123)

    keyboard = rendered[0]
    row_texts = [[button.text for button in row] for row in keyboard.inline_keyboard]
    assert ["📋 最近牌局", "📘 指令帮助"] in row_texts


@pytest.mark.asyncio
async def test_health_menu_surfaces_conflicts_and_shortcuts(monkeypatch):
    rendered: list[tuple[str, object]] = []
    settings = SimpleNamespace(
        verification_enabled=False,
        verification_mode="button",
        verification_timeout_seconds=60,
        force_subscribe_enabled=True,
        force_subscribe_bound_channel_1=None,
        force_subscribe_bound_channel_2=None,
        anti_flood_enabled=False,
        anti_flood_action="mute",
        anti_spam_enabled=False,
        anti_spam_action="ban",
        group_lock_phrase_enabled=False,
        group_lock_schedule_enabled=True,
        group_lock_open_time=None,
        group_lock_close_time="23:00",
        auto_delete_join=True,
        auto_delete_left=False,
        auto_delete_pinned=True,
        auto_delete_avatar=False,
        auto_delete_title=False,
        auto_delete_anonymous=False,
    )

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_get_chat_title(db, chat_id: int):
        return "测试群"

    async def fake_permission_summary(context, chat_id: int):
        return "✅ 权限检查：管理员权限正常（删消息✅ / 禁言✅ / 邀请✅ / 置顶❌）"

    async def fake_list_tasks(session, chat_id: int, limit: int = 200):
        return [
            SimpleNamespace(enabled=True),
            SimpleNamespace(enabled=False),
        ]

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_get_chat_title", fake_get_chat_title)
    monkeypatch.setattr(admin_handler._admin_handler, "_inspect_bot_admin_health", fake_permission_summary)
    monkeypatch.setattr(admin_handler.ScheduledMessageService, "list_tasks", fake_list_tasks)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_health_menu(update, context, -100123)

    assert rendered
    text, keyboard = rendered[0]
    assert "🩺 [测试群] 群组健康检查" in text
    assert "• 定时消息：2 条（启用 1 条）" in text
    assert "⚠️ 强制订阅已开启但尚未绑定频道" in text
    assert "⚠️ 定时关群已开启但开群/关群时间未完整配置" in text
    assert "⚠️ 当前验证、反垃圾、防刷屏均关闭，新成员保护较弱" in text

    row_texts = [[button.text for button in row] for row in keyboard.inline_keyboard]
    assert ["🛡️ 新人验证", "☂️ 反垃圾", "🌊 防刷屏"] in row_texts
    assert ["📣 强制订阅", "🧨 关群设置", "⏰ 定时消息"] in row_texts
