from __future__ import annotations


STRINGS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "start.private": "你好！把我添加到群里并授予管理员权限，然后在群里输入 /admin 进行配置。",
        "start.group": "我已加入本群。管理员请使用 /admin 打开管理面板；成员可用 /sign 签到、/points 查积分。",
        "error.need_group": "请在群里使用该指令。",
        "error.need_admin": "需要群管理员权限才能使用。",
        "admin.title": "管理面板（本群独立配置）",
        "admin.settings": "群设置",
        "admin.points": "积分",
        "admin.verification": "新人验证",
        "admin.moderation": "内容审核",
        "admin.ads": "广告与订阅",
        "admin.back": "返回",
        "admin.toggle.on": "已开启：{name}",
        "admin.toggle.off": "已关闭：{name}",
        "points.signed": "签到成功，获得 {points} 积分。当前余额：{balance}",
        "points.already_signed": "你今天已经签到过了。当前余额：{balance}",
        "points.balance": "你在本群的积分余额：{balance}",
        "verify.prompt": "欢迎 {user}！请在 {seconds} 秒内点击按钮完成验证，否则将继续限制发言。",
        "verify.button": "我不是机器人",
        "verify.ok": "验证通过，已解除限制。",
        "verify.expired": "验证已过期，请联系管理员或重新入群触发验证。",
        "moderation.deleted": "已删除违规消息。",
    },
    "en": {
        "start.private": "Hi! Add me to a group and grant admin rights, then run /admin in the group to configure.",
        "start.group": "I’m active in this group. Admin: /admin. Members: /sign, /points.",
        "error.need_group": "Please use this command in a group.",
        "error.need_admin": "Admin permission required.",
        "admin.title": "Admin Panel (per-group settings)",
        "admin.settings": "Group Settings",
        "admin.points": "Points",
        "admin.verification": "New Member Verification",
        "admin.moderation": "Moderation",
        "admin.ads": "Ads & Subscription",
        "admin.back": "Back",
        "admin.toggle.on": "Enabled: {name}",
        "admin.toggle.off": "Disabled: {name}",
        "points.signed": "Signed in! +{points} points. Balance: {balance}",
        "points.already_signed": "You already signed in today. Balance: {balance}",
        "points.balance": "Your points balance in this group: {balance}",
        "verify.prompt": "Welcome {user}! Click the button within {seconds}s to verify.",
        "verify.button": "I'm human",
        "verify.ok": "Verified. Restrictions lifted.",
        "verify.expired": "Verification expired.",
        "moderation.deleted": "Removed a violating message.",
    },
}


def t(lang: str | None, key: str, **kwargs: object) -> str:
    lang = lang or "zh-CN"
    table = STRINGS.get(lang) or STRINGS["zh-CN"]
    template = table.get(key) or STRINGS["zh-CN"].get(key) or key
    try:
        return template.format(**kwargs)
    except Exception:
        return template



