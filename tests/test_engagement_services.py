from __future__ import annotations

import pytest

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
                "【线索1奖励】50口令+300积分",
                "【线索1时间】2026-04-15 09:00",
                "",
                "【线索2】火遍大江南北",
                "【线索2奖励】30口令+200积分",
                "【线索2时间】2026-04-15 11:00",
                "",
                "【线索3】演唱是两个人",
                "【线索3奖励】20口令+100积分",
                "【线索3时间】2026-04-15 14:00",
                "",
                "【线索4】凤凰传奇唱的",
                "【线索4奖励】10口令+50积分",
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
