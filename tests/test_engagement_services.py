from __future__ import annotations

import pytest

from bot.services.activity.engagement_service import parse_egg_template, parse_reward_plan
from bot.services.base import ValidationError


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
