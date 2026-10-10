"""Management feature contracts shared by menu construction and validation.

The runtime still owns typed callable registration. This catalog binds its
stable entry IDs to category, policy, state ownership and acceptance evidence.
"""
from __future__ import annotations
from dataclasses import dataclass

# Feature IDs remain stable so already-sent Telegram buttons keep working.
ADMIN_CATEGORIES = {
    "safety": ("群安全", (
        ("进群欢迎", "welcome"), ("进群验证", "verification"),
        ("新成员限制", "newmem"), ("垃圾防护", "antispam"),
        ("惩罚策略", "punish"), ("删除提示", "autodel"),
        ("夜间管控", "night"), ("改名监控", "renamewatch"),
        ("强制订阅", "forcesub"), ("联盟功能", "alliance"),
    )),
    "messages": ("消息运营", (
        ("轮播广告", "ads"), ("自动回复", "autoreply"),
        ("定时消息", "scheduled"), ("频道同步", "sync"),
        ("底部按钮", "bottom_button"), ("快捷发布", "qpub"),
    )),
    "growth": ("积分与增长", (
        ("主积分", "points"), ("自定义积分", "custom_points"),
        ("积分等级", "points_level"), ("积分商城", "points_mall"),
        ("邀请链接", "invite"), ("账号继承", "inherit"),
    )),
    "activities": ("活动互动", (
        ("抽奖", "lottery"), ("接龙", "solitaire"), ("拍卖", "auction"),
        ("游戏", "game"), ("竞猜", "guess"), ("促活工具", "engagement"),
    )),
    "garage": ("车库业务", (
        ("车库认证", "garage_auth"), ("老师搜索", "teacher_search"), ("车评系统", "car_review"),
    )),
    "system": ("系统管理", (
        ("命令配置", "gcmd"), ("健康检查", "health"), ("群组统计", "stats"),
        ("导入设置", "import"), ("克隆设置", "clone"),
        ("管理权限", "control"), ("服务状态", "renewal"),
    )),
}



@dataclass(frozen=True)
class FeatureRegistration:
    feature_id: str
    title: str
    category: str
    entry: str
    permission_policy: str
    action_prefixes: tuple[str, ...]
    input_prefixes: tuple[str, ...]
    message_adapter: str | None
    acceptance_scenarios: tuple[str, ...]


_FEATURE_CONTRACTS = {
    "welcome": (("adm:wel:",), ("welcome_",), "welcome", ("T14",)),
    "verification": (("adm:vfy_",), ("verification_", "vfy_"), None, ("T06",)),
    "newmem": (("adm:nml:",), ("new_member_",), None, ()),
    "antispam": (("gg:", "adm:as_config"), ("anti_spam_", "garbage_"), None, ()),
    "punish": (("adm:punish:",), ("punishment_",), None, ()),
    "autodel": (("adm:toggle:",), (), None, ("T23",)),
    "night": (("adm:night:",), ("night_",), None, ()),
    "renamewatch": (("adm:rm:",), ("rename_",), None, ()),
    "forcesub": (("adm:fs:",), ("force_subscribe_",), None, ()),
    "alliance": (("ali:",), ("alliance_",), None, ()),
    "ads": (("ads:",), ("ads_",), "ads", ("T14",)),
    "autoreply": (("auto_reply:",), ("auto_reply_",), "auto_reply", ("T14",)),
    "scheduled": (("sm:",), ("sm_", "scheduled_"), None, ("T24",)),
    "sync": (("gfw:",), ("garage_forward_",), None, ("T24",)),
    "bottom_button": (("btm:",), ("bottom_button_",), None, ()),
    "qpub": (("qpub:",), ("quick_publish_",), None, ()),
    "points": (("pts:", "adm:toggle:"), ("points_",), None, ()),
    "custom_points": (("adm:cpt:",), ("custom_points_",), None, ()),
    "points_level": (("adm:lvl:",), ("points_level_",), None, ()),
    "points_mall": (("adm:mall:", "mall:", "morder:"), ("points_mall_",), None, ("T12", "T15", "T16", "T17", "T18", "T19", "T20")),
    "invite": (("inv:",), ("invite_link_",), "invite", ("T05", "T14")),
    "inherit": (("inh:",), ("account_inherit_",), None, ()),
    "lottery": (("lot:", "lottery:"), ("lottery_",), None, ()),
    "solitaire": (("sol:", "solitaire:"), ("solitaire_",), None, ()),
    "auction": (("auc:",), ("auction_",), None, ("T21", "T22")),
    "game": (("gm:",), ("game_",), None, ()),
    "guess": (("guess:",), ("guess_",), None, ("T21",)),
    "engagement": (("act:",), ("engagement_",), None, ("T12", "T13")),
    "garage_auth": (("grg:",), ("garage_",), None, ("T12", "T13")),
    "teacher_search": (("tsearch:",), ("teacher_",), None, ("T05",)),
    "car_review": (("crv:",), ("car_review_",), None, ("T05",)),
    "gcmd": (("adm:gcmd:",), ("command_config_",), None, ("T08", "T10", "T11")),
    "health": ((), (), None, ()),
    "stats": ((), (), None, ()),
    "import": (("adm:import:",), ("import_",), None, ()),
    "clone": (("adm:clone:",), ("clone_",), None, ()),
    "control": (("adm:perm:",), (), None, ("T06",)),
    "renewal": (("adm:renewal:", "renew:", "sub:"), ("redeem_",), None, ("T23",)),
}


def _build_registrations():
    result = {}
    for category, (_, entries) in ADMIN_CATEGORIES.items():
        for title, feature in entries:
            if feature in result:
                raise ValueError(f"Duplicate feature entry: {feature}")
            actions, states, adapter, scenarios = _FEATURE_CONTRACTS[feature]
            result[feature] = FeatureRegistration(feature, title, category, f"adm:menu:{feature}:{{chat_id}}",
                "PermissionPolicyService.require_manage", actions, states, adapter,
                tuple(dict.fromkeys(("T01", "T02", "T04", "T06", *scenarios))))
    if result.keys() != _FEATURE_CONTRACTS.keys():
        raise ValueError("Feature contracts and menu entries disagree")
    return result


FEATURE_REGISTRATIONS = _build_registrations()
