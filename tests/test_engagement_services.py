from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.activity import engagement_handler
from backend.features.activity.services.engagement_service import parse_egg_template, parse_reward_plan
from backend.shared.services.base import ValidationError


def test_parse_reward_plan_requires_seven_values():
    assert parse_reward_plan("10 20 30 40 50 60 70") == [10, 20, 30, 40, 50, 60, 70]
    with pytest.raises(ValidationError):
        parse_reward_plan("10 20 30")


def test_parse_reward_plan_requires_non_decreasing_values():
    with pytest.raises(ValidationError):
        parse_reward_plan("10 9 30 40 50 60 70")


def test_parse_egg_template_requires_answer_clues_rewards_and_times():
    parsed = parse_egg_template(
        "\n".join(
            [
                "标题=四月彩蛋",
                "答案=测试答案",
                "线索1=第一条",
                "奖励1=50",
                "时间1=09:00",
                "线索2=第二条",
                "奖励2=40",
                "时间2=10:00",
                "线索3=第三条",
                "奖励3=30",
                "时间3=11:00",
                "线索4=第四条",
                "奖励4=20",
                "时间4=12:00",
            ]
        )
    )
    assert parsed["title"] == "四月彩蛋"
    assert parsed["answer"] == "测试答案"
    assert parsed["clues"][0] == "第一条"
    assert parsed["clue_rewards"][1] == 40
    assert parsed["clue_times"][3] == "12:00"


def test_parse_egg_template_accepts_bracket_quick_add_format():
    parsed = parse_egg_template(
        "\n".join(
            [
                "@abaoan_bot 添加彩蛋",
                "",
                "【群ID】-1002966682374",
                "【答案】爱情买卖",
                "",
                "【线索1】猜一首歌",
                "【线索1奖励】300积分",
                "【线索1时间】2026-04-15 09:00",
                "",
                "【线索2】火遍大江南北",
                "【线索2奖励】200积分",
                "【线索2时间】2026-04-15 11:00",
                "",
                "【线索3】演唱是两个人",
                "【线索3奖励】100积分",
                "【线索3时间】2026-04-15 14:00",
                "",
                "【线索4】凤凰传奇唱的",
                "【线索4奖励】50积分",
                "【线索4时间】2026-04-15 16:00",
                "",
                "【颁奖人】@UserName",
            ]
        )
    )

    assert parsed["chat_id"] == -1002966682374
    assert parsed["answer"] == "爱情买卖"
    assert parsed["clues"] == ["猜一首歌", "火遍大江南北", "演唱是两个人", "凤凰传奇唱的"]
    assert parsed["clue_rewards"] == [300, 200, 100, 50]
    assert parsed["clue_times"] == ["09:00", "11:00", "14:00", "16:00"]


def test_parse_egg_template_rejects_non_point_rewards():
    raw = "\n".join(
        [
            "答案=测试",
            "线索1=一",
            "奖励1=50口令+300积分",
            "时间1=09:00",
            "线索2=二",
            "奖励2=200积分",
            "时间2=11:00",
            "线索3=三",
            "奖励3=100积分",
            "时间3=14:00",
            "线索4=四",
            "奖励4=50积分",
            "时间4=16:00",
        ]
    )
    with pytest.raises(ValidationError, match="只支持积分奖励"):
        parse_egg_template(raw)


@pytest.mark.asyncio
async def test_group_egg_template_with_answer_is_rejected_before_creation(monkeypatch):
    replies: list[str] = []

    async def fake_require_manage(context, chat_id: int, user_id: int, capability: str):
        return True, None

    async def fake_reply(context, *, chat_id: int, text: str, reply_to_message_id: int, **kwargs):
        replies.append(text)
        return SimpleNamespace(message_id=100)

    async def fail_create(*args, **kwargs):
        raise AssertionError("group answer template should not create an egg")

    monkeypatch.setattr(engagement_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(engagement_handler.PublishService, "reply", fake_reply)
    monkeypatch.setattr(engagement_handler, "update_egg_event_from_template", fail_create)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(
            message_id=9,
            text="\n".join(
                [
                    "添加彩蛋",
                    "【答案】爱情买卖",
                    "【线索1】猜一首歌",
                    "【线索1奖励】300积分",
                    "【线索1时间】09:00",
                ]
            ),
        ),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": None}), bot=SimpleNamespace(username="bot"))

    handled = await engagement_handler.engagement_message_handler(update, context)

    assert handled is True
    assert replies == ["⚠️ 彩蛋答案不能在群聊里配置。请到机器人私聊中复制模板并创建，避免群友提前看到答案。"]
