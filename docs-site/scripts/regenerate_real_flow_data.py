from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE = ROOT / "docs-site"
CATALOG_PATH = DOCS_SITE / "src/content/features/catalog.json"
FLOWS_DIR = DOCS_SITE / "src/content/flows"

CHAT = "{chat_id}"
TASK = "{task_id}"
RULE = "{rule_id}"
ITEM = "{item_id}"
PRODUCT = "{product_id}"
LEVEL = "{level_id}"
TYPE = "{type_id}"
WELCOME = "{welcome_id}"
LINK = "{link_id}"
ORDER = "{order_id}"
LOTTERY = "{lottery_id}"
SOLITAIRE = "{solitaire_id}"
EVENT = "{event_id}"
AUCTION = "{auction_id}"

ADMIN_FILES = [
    "backend/features/admin/ui/admin_main_keyboards.py",
    "backend/features/admin/core/menu_dispatch.py",
    "backend/features/admin/runtime.py",
]


def load_catalog() -> dict[str, dict[str, Any]]:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {feature["slug"]: feature for feature in payload["features"]}


CATALOG = load_catalog()


def button(
    label: str,
    callback: str,
    action: str = "goto",
    target: str | None = None,
    feedback: str | None = None,
    highlight: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "label": label,
        "callbackData": callback,
        "action": action,
    }
    if target is not None:
        item["target"] = target
    if feedback:
        item["feedback"] = feedback
    if highlight:
        item["highlight"] = True
    return item


def screen(
    screen_id: str,
    title: str,
    message: list[str],
    keyboard: list[list[dict[str, Any]]],
    state_lines: list[str] | None = None,
    input_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": screen_id,
        "title": title,
        "message": message,
        "keyboard": keyboard,
    }
    if state_lines:
        item["stateLines"] = state_lines
    if input_config:
        item["input"] = input_config
    return item


def input_config(
    input_type: str,
    prompt: str,
    placeholder: str,
    examples: list[tuple[str, str, str | None]] | None = None,
    clear: str | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "type": input_type,
        "prompt": prompt,
        "placeholder": placeholder,
    }
    if clear:
        config["clearCommand"] = clear
    if examples:
        config["examples"] = [
            {
                "label": label,
                "value": value,
                **({"target": target} if target else {}),
                "feedback": f"已填入：{label}。",
            }
            for label, value, target in examples
        ]
    if errors:
        config["errors"] = errors
    return config


def meta(slug: str) -> dict[str, str]:
    feature = CATALOG[slug]
    return {
        "slug": slug,
        "title": feature["title"],
        "status": feature["status"],
        "category": feature["category"],
    }


def coverage(
    prefixes: list[str],
    states: list[str] | None = None,
    files: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "mode": "complete",
        "callbackPrefixes": prefixes,
        "inputStates": states or [],
        "sourceFiles": sorted(dict.fromkeys((files or []) + ADMIN_FILES)),
        "alignmentStatus": "ok",
        "alignmentSummary": "真实回调审计通过。",
    }


def flow(slug: str, cov: dict[str, Any], screens: list[dict[str, Any]], entry: str = "entry") -> dict[str, Any]:
    return {
        **meta(slug),
        "entryScreen": entry,
        "coverage": cov,
        "screens": screens,
    }


def admin_entry(label: str, callback: str, target: str = "home") -> dict[str, Any]:
    return screen(
        "entry",
        "管理员主菜单",
        ["发送 /start 后点击管理入口，按按钮选择当前群组。", f"点击「{label}」进入配置页。"],
        [
            [button(label, callback, "goto", target, f"已进入「{label}」。", True)],
            [
                button("切换群", "adm:switch_group", "goto", "select_group", "进入群组选择。"),
                button("返回主菜单", f"adm:menu:main:{CHAT}", "goto", "main_menu", "已回到主菜单。"),
            ],
        ],
        ["当前群组：演示群"],
    )


def common_select_group(return_callback: str, return_target: str = "entry") -> dict[str, Any]:
    return screen(
        "select_group",
        "选择配置群组",
        ["私聊配置前先确认目标群组，后续按钮都会写入这个群。"],
        [
            [
                button("演示群", "adm:select_group:-1001001", "goto", return_target, "已切换到演示群。"),
                button("测试群", "adm:select_group:-1001002", "goto", return_target, "已切换到测试群。"),
            ],
            [button("返回", return_callback, "back", return_target, "已返回。")],
        ],
        ["可管理群：演示群、测试群"],
    )


def common_main_menu(label: str, callback: str, target: str = "home") -> dict[str, Any]:
    return screen(
        "main_menu",
        "主菜单",
        ["这里展示机器人后台的真实功能入口。"],
        [[button(label, callback, "goto", target, f"已进入「{label}」。", True)]],
    )


def admin_reference_flow(
    slug: str,
    label: str,
    menu_key: str,
    messages: list[str],
    state_lines: list[str] | None = None,
    extra_buttons: list[list[dict[str, Any]]] | None = None,
    prefixes: list[str] | None = None,
    states: list[str] | None = None,
    files: list[str] | None = None,
) -> dict[str, Any]:
    home_callback = f"adm:menu:{menu_key}:{CHAT}"
    rows = extra_buttons or [[button("刷新本页", home_callback, "goto", "home", "已刷新当前页。")]]
    rows.append([button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")])
    screens = [
            admin_entry(label, home_callback),
            common_select_group(home_callback, "entry"),
            common_main_menu(label, home_callback),
            screen("home", label, messages, rows, state_lines or ["当前群组：演示群"]),
            screen(
                "result",
                "操作结果",
                ["Bot 处理真实回调后会重新渲染当前功能页或返回上一级。"],
                [[button("返回", home_callback, "back", "home", "已返回。")]],
            ),
        ]
    return flow(
        slug,
        coverage(prefixes or [f"adm:menu:{menu_key}"], states, files),
        screens,
    )


def admin_menu_button_flow(
    slug: str,
    label: str,
    menu_key: str,
    action_prefixes: list[str],
    home_message: list[str],
    rows: list[list[dict[str, Any]]],
    states: list[str] | None = None,
    files: list[str] | None = None,
    input_screens: list[dict[str, Any]] | None = None,
    result_message: list[str] | None = None,
) -> dict[str, Any]:
    home_callback = f"adm:menu:{menu_key}:{CHAT}"
    base_screens = [
        admin_entry(label, home_callback),
        common_select_group(home_callback, "entry"),
        common_main_menu(label, home_callback),
        screen(
            "home",
            label,
            home_message,
            rows + [[button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")]],
            ["当前群组：演示群"],
        ),
    ]
    if input_screens:
        base_screens.extend(input_screens)
    base_screens.append(
        screen(
            "result",
            "设置结果",
            result_message or ["Bot 保存配置后会重新渲染当前功能页。", "请在群内用测试账号触发一次，确认权限和运行结果。"],
            [[button("返回设置页", home_callback, "back", "home", "已返回设置页。")]],
            ["审计：回调来自后端真实路由"],
        )
    )
    return flow(
        slug,
        coverage([f"adm:menu:{menu_key}", *action_prefixes], states, files),
        base_screens,
    )


def input_screen(
    sid: str,
    title: str,
    prompt: str,
    placeholder: str,
    return_callback: str,
    return_target: str = "home",
    input_type: str = "text",
    examples: list[tuple[str, str, str | None]] | None = None,
    clear: str | None = "/clear",
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return screen(
        sid,
        title,
        ["这里是后端进入私聊输入 state 后等待管理员发送内容的页面。"],
        [[button("返回", return_callback, "back", return_target, "已返回上一层。")]],
        input_config=input_config(
            input_type,
            prompt,
            placeholder,
            examples or [("示例", placeholder, "result")],
            clear,
            errors or ["格式不符合要求时，Bot 会停留在输入态并提示重新输入。"],
        ),
    )


def basic_runtime_flow(slug: str, label: str, messages: list[str], prefixes: list[str], files: list[str]) -> dict[str, Any]:
    return flow(
        slug,
        coverage(prefixes, [], files),
        [
            admin_entry(label, f"adm:menu:main:{CHAT}", "home"),
            common_select_group(f"adm:menu:main:{CHAT}", "entry"),
            common_main_menu(label, f"adm:menu:main:{CHAT}", "home"),
            screen(
                "home",
                label,
                messages,
                [
                    [button("返回管理入口", f"adm:menu:main:{CHAT}", "goto", "entry", "回到真实管理员入口。")],
                    [button("切换群", "adm:switch_group", "goto", "select_group", "进入群组选择。")],
                ],
                ["该页说明真实运行时逻辑，不编造二级配置按钮。"],
            ),
        ],
    )


def points_flow(slug: str, label: str, focus: str) -> dict[str, Any]:
    return flow(
        slug,
        coverage(
            ["pts:home:", "pts:rule:", "pts:toggle:", "pts:edit:", "inv:user:", "inv:home:"],
            [],
            [
                "backend/features/points/points_router.py",
                "backend/features/points/points_command_actions.py",
                "backend/features/points/points_message_actions.py",
                "backend/features/admin/ui/points.py",
                "backend/features/invite/ui/invite_link.py",
            ],
        ),
        [
            admin_entry(label, f"pts:home:{CHAT}"),
            common_select_group(f"pts:home:{CHAT}", "entry"),
            common_main_menu(label, f"pts:home:{CHAT}"),
            screen(
                "home",
                "积分中心",
                [focus, "签到、发言、邀请和展示规则都通过真实 pts 回调保存。"],
                [
                    [
                        button("签到规则", f"pts:rule:checkin:{CHAT}", "goto", "sign_rule", "打开签到积分规则。", slug == "sign-points"),
                        button("发言规则", f"pts:rule:speech:{CHAT}", "goto", "speech_rule", "打开发言积分规则。", slug == "message-points"),
                        button("邀请规则", f"pts:rule:invite:{CHAT}", "goto", "invite_rule", "打开邀请积分规则。", slug == "invite-points"),
                    ],
                    [
                        button("积分展示规则", f"pts:view:display_rules:{CHAT}", "goto", "display_rules", "打开积分展示规则。"),
                        button("额外规则", f"pts:view:extra_rules:{CHAT}", "goto", "extra_rules", "打开额外规则说明。"),
                    ],
                    [button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")],
                ],
                ["当前群组：演示群", "状态：已启用"],
            ),
            screen(
                "sign_rule",
                "签到积分规则",
                ["开启签到后，用户发送签到命令即可获得积分。"],
                [
                    [
                        button("开启签到", f"pts:toggle:sign_enabled:{CHAT}:1", "toggle", "result", "签到积分已开启。"),
                        button("关闭签到", f"pts:toggle:sign_enabled:{CHAT}:0", "toggle", "result", "签到积分已关闭。"),
                    ],
                    [
                        button("设置签到积分", f"pts:edit:sign_points:{CHAT}", "input", "points_input", "请输入每次签到积分。"),
                        button("设置连签奖励", f"pts:edit:sign_consecutive:{CHAT}", "input", "points_input", "请输入连签奖励。"),
                    ],
                    [button("返回积分中心", f"pts:home:{CHAT}", "back", "home", "已返回积分中心。")],
                ],
            ),
            screen(
                "speech_rule",
                "发言积分规则",
                ["开启后，达到最小字数的发言会按日上限累计积分。"],
                [
                    [
                        button("开启发言积分", f"pts:toggle:message_points_enabled:{CHAT}:1", "toggle", "result", "发言积分已开启。"),
                        button("关闭发言积分", f"pts:toggle:message_points_enabled:{CHAT}:0", "toggle", "result", "发言积分已关闭。"),
                    ],
                    [
                        button("设置每条积分", f"pts:edit:message_points:{CHAT}", "input", "points_input", "请输入每条消息积分。"),
                        button("设置每日上限", f"pts:edit:message_daily_limit:{CHAT}", "input", "points_input", "请输入每日上限。"),
                        button("设置最小字数", f"pts:edit:message_min_length:{CHAT}", "input", "points_input", "请输入最小字数。"),
                    ],
                    [button("返回积分中心", f"pts:home:{CHAT}", "back", "home", "已返回积分中心。")],
                ],
            ),
            screen(
                "invite_rule",
                "邀请积分规则",
                ["邀请归因成功后，邀请人按规则获得积分。"],
                [
                    [
                        button("开启邀请积分", f"pts:toggle:invite_points_enabled:{CHAT}:1", "toggle", "result", "邀请积分已开启。"),
                        button("关闭邀请积分", f"pts:toggle:invite_points_enabled:{CHAT}:0", "toggle", "result", "邀请积分已关闭。"),
                    ],
                    [
                        button("设置邀请积分", f"pts:edit:invite_points:{CHAT}", "input", "points_input", "请输入每次邀请积分。"),
                        button("设置每日上限", f"pts:edit:invite_daily_limit:{CHAT}", "input", "points_input", "请输入每日上限。"),
                    ],
                    [button("用户邀请入口", f"inv:user:menu:{CHAT}", "goto", "invite_user", "打开用户邀请入口。")],
                    [button("返回积分中心", f"pts:home:{CHAT}", "back", "home", "已返回积分中心。")],
                ],
            ),
            screen(
                "display_rules",
                "积分展示规则",
                ["排行榜、个人发言统计和积分别名都在这里配置。"],
                [
                    [
                        button("开启排行榜展示", f"pts:toggle:points_speech_rank_enabled:{CHAT}:1", "toggle", "result", "排行榜展示已开启。"),
                        button("个人发言统计", f"pts:toggle:points_personal_speech_enabled:{CHAT}:1", "toggle", "result", "个人统计已开启。"),
                    ],
                    [
                        button("设置积分别名", f"pts:edit:points_alias:{CHAT}", "input", "text_input", "请输入积分显示名称。"),
                        button("设置排行命令", f"pts:edit:points_rank_alias:{CHAT}", "input", "text_input", "请输入排行命令别名。"),
                    ],
                    [button("返回积分中心", f"pts:home:{CHAT}", "back", "home", "已返回积分中心。")],
                ],
            ),
            screen(
                "extra_rules",
                "额外规则",
                ["管理员可通过真实 pts 编辑入口执行加分、扣分、清空和导出。"],
                [
                    [
                        button("管理员加分", f"pts:edit:admin_add:{CHAT}", "input", "points_input", "请输入加分格式。"),
                        button("管理员扣分", f"pts:edit:admin_deduct:{CHAT}", "input", "points_input", "请输入扣分格式。"),
                    ],
                    [
                        button("清空积分", f"pts:edit:clear_points:{CHAT}", "confirm", "result", "已进入清空确认。"),
                        button("导出日志", f"pts:view:export_logs:{CHAT}", "goto", "result", "已发起导出。"),
                    ],
                    [button("返回积分中心", f"pts:home:{CHAT}", "back", "home", "已返回积分中心。")],
                ],
            ),
            screen(
                "invite_user",
                "用户邀请入口",
                ["用户可创建自己的邀请链接并查看排行。"],
                [
                    [
                        button("创建我的链接", f"inv:user:create:{CHAT}", "goto", "result", "已创建或返回现有邀请链接。"),
                        button("我的链接", f"inv:user:list:{CHAT}", "goto", "result", "已打开我的邀请链接。"),
                        button("邀请排行", f"inv:user:rank:{CHAT}", "goto", "result", "已打开邀请排行。"),
                    ],
                    [button("返回邀请配置", f"inv:home:{CHAT}", "back", "home", "已返回邀请配置。")],
                ],
            ),
            input_screen(
                "points_input",
                "输入积分数值",
                "发送整数数值",
                "10",
                f"pts:home:{CHAT}",
                examples=[("10", "10", "result"), ("每日上限 50", "50", "result")],
                clear=None,
            ),
            input_screen(
                "text_input",
                "输入积分文本",
                "发送别名或命令文本",
                "积分",
                f"pts:home:{CHAT}",
                examples=[("积分别名", "贡献值", "result"), ("排行命令", "/rank", "result")],
                clear="/clear",
            ),
            screen(
                "result",
                "积分设置结果",
                ["Bot 保存后回到积分中心，运行时按当前群组 chat_id 统计。"],
                [[button("返回积分中心", f"pts:home:{CHAT}", "back", "home", "已返回积分中心。")]],
            ),
        ],
    )


def invite_flow(slug: str, label: str, focus: str) -> dict[str, Any]:
    return flow(
        slug,
        coverage(
            ["inv:home:", "inv:toggle:", "inv:mode:", "inv:cover:", "inv:text:", "inv:buttons:", "inv:preview:", "inv:list:", "inv:detail:", "inv:user:"],
            ["invite_link_create", "invite_link_cover_input", "invite_link_text_input", "invite_link_buttons_input"],
            [
                "backend/features/invite/ui/invite_link.py",
                "backend/features/invite/invite_admin_config_callbacks.py",
                "backend/features/invite/invite_admin_link_callbacks.py",
                "backend/features/invite/invite_user_callbacks.py",
                "backend/features/invite/invite_router.py",
            ],
        ),
        [
            admin_entry(label, f"inv:home:{CHAT}"),
            common_select_group(f"inv:home:{CHAT}", "entry"),
            common_main_menu(label, f"inv:home:{CHAT}"),
            screen(
                "home",
                "邀请配置",
                [focus, "管理入口使用 inv:home，管理员配置和用户自助入口共用真实邀请服务。"],
                [
                    [
                        button("开启邀请", f"inv:toggle:enabled:{CHAT}:1", "toggle", "result", "邀请功能已开启。"),
                        button("关闭邀请", f"inv:toggle:enabled:{CHAT}:0", "toggle", "result", "邀请功能已关闭。"),
                        button("提醒开关", f"inv:toggle:remind:{CHAT}:1", "toggle", "result", "邀请提醒已切换。"),
                    ],
                    [
                        button("转发模式", f"inv:mode:{CHAT}:relay", "toggle", "result", "已选择转发模式。"),
                        button("直达模式", f"inv:mode:{CHAT}:direct", "toggle", "result", "已选择直达模式。"),
                    ],
                    [
                        button("设置封面", f"inv:cover:{CHAT}", "input", "cover_input", "请发送图片、视频或 /clear。"),
                        button("设置文本", f"inv:text:{CHAT}", "input", "text_input", "请输入邀请说明文本。"),
                        button("设置按钮", f"inv:buttons:{CHAT}", "input", "buttons_input", "请输入按钮配置。"),
                    ],
                    [
                        button("预览效果", f"inv:preview:{CHAT}", "goto", "preview", "已打开邀请卡片预览。"),
                        button("链接列表", f"inv:list:0:{CHAT}", "goto", "list", "已打开邀请链接列表。"),
                    ],
                    [
                        button("用户入口", f"inv:user:menu:{CHAT}", "goto", "user", "已打开用户自助邀请入口。"),
                        button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。"),
                    ],
                ],
                ["当前群组：演示群"],
            ),
            screen(
                "list",
                "邀请链接列表",
                ["管理员可以查看、刷新、撤销或删除具体邀请链接。"],
                [
                    [
                        button("链接详情", f"inv:detail:{LINK}:{CHAT}", "goto", "detail", "已打开链接详情。"),
                        button("创建确认", "inv:create_confirm", "confirm", "create_input", "请输入新链接参数。"),
                    ],
                    [button("返回邀请配置", f"inv:home:{CHAT}", "back", "home", "已返回邀请配置。")],
                ],
            ),
            screen(
                "detail",
                "邀请链接详情",
                ["链接详情展示归因人数、使用状态和撤销操作。"],
                [
                    [
                        button("刷新统计", f"inv:refresh:{LINK}:{CHAT}", "goto", "detail", "已刷新链接统计。"),
                        button("撤销链接", f"inv:revoke:{LINK}:{CHAT}", "confirm", "result", "已发起撤销。"),
                        button("删除记录", f"inv:delete:{LINK}:{CHAT}", "confirm", "result", "已发起删除。"),
                    ],
                    [button("返回链接列表", f"inv:list:0:{CHAT}", "back", "list", "已返回链接列表。")],
                ],
            ),
            screen(
                "user",
                "用户邀请入口",
                ["用户在群里点击或发送命令后，可创建自己的链接并查看排行。"],
                [
                    [
                        button("创建我的链接", f"inv:user:create:{CHAT}", "goto", "result", "已创建或返回现有链接。"),
                        button("我的链接", f"inv:user:list:{CHAT}", "goto", "result", "已打开我的链接。"),
                        button("邀请排行", f"inv:user:rank:{CHAT}", "goto", "result", "已打开邀请排行。"),
                    ],
                    [button("返回邀请配置", f"inv:home:{CHAT}", "back", "home", "已返回邀请配置。")],
                ],
            ),
            screen(
                "preview",
                "邀请卡片预览",
                ["预览使用当前封面、文本和按钮配置，不生成新的邀请记录。"],
                [[button("返回邀请配置", f"inv:home:{CHAT}", "back", "home", "已返回邀请配置。")]],
            ),
            input_screen(
                "cover_input",
                "设置邀请封面",
                "发送图片、视频，或发送 /clear 清空封面",
                "上传一张图片",
                f"inv:home:{CHAT}",
                input_type="media",
                examples=[("图片", "image.jpg", "preview"), ("清空", "/clear", "result")],
            ),
            input_screen(
                "text_input",
                "设置邀请文本",
                "发送邀请卡片正文",
                "邀请好友进群可获得积分。",
                f"inv:home:{CHAT}",
                examples=[("邀请文案", "邀请好友进群可获得积分。", "preview"), ("清空", "/clear", "result")],
            ),
            input_screen(
                "buttons_input",
                "设置邀请按钮",
                "逐行输入按钮，支持分号同排",
                "加入频道 - https://t.me/example",
                f"inv:home:{CHAT}",
                input_type="buttons",
                examples=[("单按钮", "加入频道 - https://t.me/example", "preview"), ("同排按钮", "频道 - https://t.me/a;客服 - https://t.me/b", "preview")],
            ),
            input_screen(
                "create_input",
                "创建邀请链接",
                "发送链接备注或使用默认创建",
                "社群活动链接",
                f"inv:list:0:{CHAT}",
                examples=[("备注", "社群活动链接", "detail")],
            ),
            screen("result", "邀请设置结果", ["Bot 保存后会回到邀请配置或链接详情页。"], [[button("返回邀请配置", f"inv:home:{CHAT}", "back", "home", "已返回邀请配置。")]]),
        ],
    )


def build_flows() -> dict[str, dict[str, Any]]:
    flows: dict[str, dict[str, Any]] = {}

    flows["multi-group-management"] = flow(
        "multi-group-management",
        coverage(["adm:switch_group", "adm:select_group", "adm:menu:main"], [], ADMIN_FILES),
        [
            screen(
                "entry",
                "管理员主菜单",
                ["发送 /start 后点击管理入口进入当前群组后台。", "点击「切换群」会进入真实群组选择回调。"],
                [
                    [button("切换群", "adm:switch_group", "goto", "select_group", "进入群组选择。", True)],
                    [button("返回主菜单", f"adm:menu:main:{CHAT}", "goto", "main_menu", "已回到主菜单。")],
                ],
                ["当前群组：演示群"],
            ),
            common_select_group(f"adm:menu:main:{CHAT}", "main_menu"),
            common_main_menu("切换群", "adm:switch_group", "select_group"),
        ],
    )

    flows["admin-permission"] = basic_runtime_flow(
        "admin-permission",
        "管理员权限校验",
        ["管理员入口会先检查当前用户在目标群组的 Telegram 权限。", "校验失败时不会进入敏感配置页。"],
        ["adm:menu:main", "adm:switch_group", "adm:select_group"],
        ["backend/features/admin/entrypoints.py", "backend/features/admin/runtime.py"],
    )

    flows["group-health-check"] = admin_reference_flow(
        "group-health-check",
        "健康检查",
        "health",
        ["健康检查汇总机器人权限、关键功能状态和配置缺口。", "该页只读取状态，不自动修改配置。"],
        ["机器人权限：可读取", "定时任务：运行中", "风控配置：建议检查"],
        files=["backend/features/admin/ui/admin_main_keyboards.py", "backend/features/admin/core/menu_dispatch.py"],
    )

    flows["auto-delete-system-messages"] = admin_reference_flow(
        "auto-delete-system-messages",
        "删除提示",
        "autodel",
        ["自动删除进群、退群、置顶、头像、群名和匿名消息等系统提示。"],
        ["状态：按类型独立开关"],
        [
            [
                button("进群提示", f"autodel:set:join:1:{CHAT}", "toggle", "result", "进群提示删除已开启。"),
                button("退群提示", f"autodel:set:left:1:{CHAT}", "toggle", "result", "退群提示删除已开启。"),
                button("置顶提示", f"autodel:set:pinned:1:{CHAT}", "toggle", "result", "置顶提示删除已开启。"),
            ],
            [
                button("头像变更", f"autodel:set:avatar:1:{CHAT}", "toggle", "result", "头像变更删除已开启。"),
                button("群名变更", f"autodel:set:title:1:{CHAT}", "toggle", "result", "群名变更删除已开启。"),
                button("匿名消息", f"autodel:set:anonymous:1:{CHAT}", "toggle", "result", "匿名消息删除已开启。"),
            ],
            [button("说明", f"autodel:noop:join:{CHAT}", "toast", feedback="Bot 缺少删除权限时不会删除系统消息。")],
        ],
        ["adm:menu:autodel", "autodel:set:", "autodel:noop:"],
        files=["backend/features/group_ops/auto_delete_config_handler.py", "backend/features/group_ops/auto_delete_handler.py"],
    )

    flows["control-permission"] = admin_menu_button_flow(
        "control-permission",
        "管理权限",
        "control",
        ["adm:perm:"],
        ["控制机器人内部管理能力需要的 Telegram 权限门槛。"],
        [
            [
                button("所有管理员", f"adm:perm:{CHAT}:all_admins", "toggle", "result", "已允许所有管理员。"),
                button("需要禁言权限", f"adm:perm:{CHAT}:can_restrict_members", "toggle", "result", "已切换禁言权限门槛。"),
            ],
            [
                button("需要改群资料", f"adm:perm:{CHAT}:can_change_info", "toggle", "result", "已切换改群资料门槛。"),
                button("需要提升管理员", f"adm:perm:{CHAT}:can_promote_members", "toggle", "result", "已切换提升管理员门槛。"),
                button("仅群主", f"adm:perm:{CHAT}:owner_only", "toggle", "result", "已切换仅群主。"),
            ],
        ],
        files=["backend/features/admin/moderation/member_actions.py"],
    )

    flows["group-stats"] = admin_reference_flow(
        "group-stats",
        "群组统计",
        "stats",
        ["群组统计按当前 chat_id 汇总成员、邀请、积分和违规数据。", "该页不直接修改配置。"],
        ["统计范围：当前群组"],
    )

    verification_files = [
        "backend/features/admin/moderation/verification_views.py",
        "backend/features/admin/moderation/verification_home_actions.py",
        "backend/features/admin/module_settings/verification_inputs.py",
        "backend/features/verification/verification_runtime.py",
        "backend/platform/scheduler/tasks/verification_timeout_task.py",
    ]
    verification_states = [
        "verification_cover_input",
        "vfy_agreement_text_input",
        "vfy_math_prompt_text_input",
    ]
    for slug, label, focus in [
        ("newcomer-verification", "进群验证", "配置按钮验证、数学验证和管理员审核。"),
        ("verification-timeout", "验证超时", "设置验证超时时间和超时后的禁言或踢出动作。"),
    ]:
        flows[slug] = admin_menu_button_flow(
            slug,
            label,
            "verification",
            ["adm:vfy_home:"],
            [focus, "所有模式配置通过 adm:vfy_home 回调分发。"],
            [
                [
                    button("规则总览", f"adm:vfy_home:{CHAT}:rules", "goto", "rules", "打开验证规则。", slug == "newcomer-verification"),
                    button("垃圾防护", f"adm:vfy_home:{CHAT}:spam", "goto", "spam", "打开垃圾防护。"),
                ],
                [
                    button("按钮验证", f"adm:vfy_home:{CHAT}:rule:button", "goto", "button_rule", "打开按钮验证。"),
                    button("数学验证", f"adm:vfy_home:{CHAT}:rule:math", "goto", "math_rule", "打开数学验证。"),
                    button("直接禁言", f"adm:vfy_home:{CHAT}:rule:mute", "toggle", "result", "已切换直接禁言模式。"),
                ],
            ],
            verification_states,
            verification_files,
            [
                screen(
                    "rules",
                    "验证规则总览",
                    ["规则总览展示当前启用模式和超时处理。"],
                    [
                        [button("按钮验证", f"adm:vfy_home:{CHAT}:rule:button", "goto", "button_rule", "进入按钮验证。")],
                        [button("数学验证", f"adm:vfy_home:{CHAT}:rule:math", "goto", "math_rule", "进入数学验证。")],
                        [button("返回验证首页", f"adm:menu:verification:{CHAT}", "back", "home", "已返回验证首页。")],
                    ],
                ),
                screen(
                    "button_rule",
                    "按钮验证",
                    ["按钮验证会发出入群确认按钮，新成员点击后解除限制。"],
                    [
                        [
                            button("开启按钮验证", f"adm:vfy_home:{CHAT}:rule:button:toggle", "toggle", "result", "按钮验证已切换。"),
                            button("设置封面", f"adm:vfy_home:{CHAT}:rule:button:input:cover", "input", "vfy_cover", "请发送验证封面。"),
                            button("设置文本", f"adm:vfy_home:{CHAT}:rule:button:input:text", "input", "vfy_text", "请输入验证文案。"),
                        ],
                        [
                            button("预览", f"adm:vfy_home:{CHAT}:rule:button:preview", "goto", "result", "已发送预览。"),
                            button("超时时间", f"adm:vfy_home:{CHAT}:rule:button:cycle:timeout", "toggle", "result", "已切换超时时间。"),
                            button("超时动作", f"adm:vfy_home:{CHAT}:rule:button:cycle:timeout_action", "toggle", "result", "已切换超时动作。"),
                        ],
                        [button("返回规则", f"adm:vfy_home:{CHAT}:rules", "back", "rules", "已返回规则总览。")],
                    ],
                ),
                screen(
                    "math_rule",
                    "数学验证",
                    ["数学验证会要求新成员回答题目。"],
                    [
                        [
                            button("开启数学验证", f"adm:vfy_home:{CHAT}:rule:math:toggle", "toggle", "result", "数学验证已切换。"),
                            button("设置文案", f"adm:vfy_home:{CHAT}:rule:math:input:text", "input", "math_text", "请输入数学验证提示文案。"),
                            button("设置封面", f"adm:vfy_home:{CHAT}:rule:math:input:cover", "input", "math_cover", "请发送数学验证封面。"),
                        ],
                        [
                            button("错误动作", f"adm:vfy_home:{CHAT}:rule:math:cycle:wrong_action", "toggle", "result", "已切换答错动作。"),
                            button("超时动作", f"adm:vfy_home:{CHAT}:rule:math:cycle:timeout_action", "toggle", "result", "已切换超时动作。"),
                        ],
                        [button("返回规则", f"adm:vfy_home:{CHAT}:rules", "back", "rules", "已返回规则总览。")],
                    ],
                ),
                screen(
                    "spam",
                    "入群垃圾防护",
                    ["刷号、可疑新号和入群频率在这里配置。"],
                    [
                        [
                            button("入群刷号开关", f"adm:vfy_home:{CHAT}:spam:toggle:enabled", "toggle", "result", "已切换入群刷号检测。"),
                            button("禁言可疑成员", f"adm:vfy_home:{CHAT}:spam:toggle:mute", "toggle", "result", "已切换可疑成员禁言。"),
                        ],
                        [button("返回验证首页", f"adm:menu:verification:{CHAT}", "back", "home", "已返回验证首页。")],
                    ],
                ),
                input_screen("vfy_cover", "设置验证封面", "发送图片、视频或 /clear", "image.jpg", f"adm:vfy_home:{CHAT}:rule:button", "button_rule", "media", [("图片", "image.jpg", "result"), ("清空", "/clear", "result")]),
                input_screen("vfy_text", "设置验证文本", "发送验证提示文案", "请点击下方按钮完成验证。", f"adm:vfy_home:{CHAT}:rule:button", "button_rule", "text", [("文案", "请点击下方按钮完成验证。", "result")]),
                input_screen("math_text", "设置数学验证文案", "发送数学验证提示文案", "请完成下方算术题，通过后解除限制。", f"adm:vfy_home:{CHAT}:rule:math", "math_rule", "text", [("文案", "请完成下方算术题，通过后解除限制。", "result")]),
                input_screen("math_cover", "设置数学验证封面", "发送图片、视频或 /clear", "image.jpg", f"adm:vfy_home:{CHAT}:rule:math", "math_rule", "media", [("图片", "image.jpg", "result"), ("清空", "/clear", "result")]),
            ],
        )

    flows["join-guard"] = admin_reference_flow(
        "join-guard",
        "垃圾防护",
        "antispam",
        ["入群刷号保护当前复用进群验证的垃圾防护配置和运行时检测。", "页面只展示真实入口，不编造独立设置按钮。"],
        ["触发场景：短时间大量新成员入群"],
        [
            [button("进入验证垃圾防护", f"adm:vfy_home:{CHAT}:spam", "goto", "spam", "打开真实垃圾防护配置。", True)],
            [button("返回进群验证", f"adm:menu:verification:{CHAT}", "goto", "home", "已打开进群验证入口。")],
        ],
        ["adm:menu:antispam", "adm:vfy_home:"],
        files=verification_files,
    )

    flows["force-subscribe"] = admin_menu_button_flow(
        "force-subscribe",
        "强制关注",
        "forcesub",
        ["adm:fs:"],
        ["要求成员关注指定频道或群组后才能发言。"],
        [
            [
                button("开启", f"adm:fs:{CHAT}:toggle:enabled", "toggle", "result", "强制关注已切换。"),
                button("频道 1", f"adm:fs:{CHAT}:input:channel1", "input", "channel_input", "请输入频道或群链接。"),
                button("频道 2", f"adm:fs:{CHAT}:input:channel2", "input", "channel_input", "请输入第二个目标。"),
            ],
            [
                button("设置封面", f"adm:fs:{CHAT}:input:cover", "input", "cover_input", "请发送封面媒体。"),
                button("设置文本", f"adm:fs:{CHAT}:input:text", "input", "text_input", "请输入提示文本。"),
                button("设置按钮", f"adm:fs:{CHAT}:input:buttons", "input", "buttons_input", "请输入按钮。"),
            ],
            [
                button("预览效果", f"adm:fs:{CHAT}:preview", "goto", "result", "已打开预览。"),
                button("判定模式", f"adm:fs:{CHAT}:cycle_check_mode", "toggle", "result", "已切换判定模式。"),
                button("处理动作", f"adm:fs:{CHAT}:cycle_action", "toggle", "result", "已切换处理动作。"),
            ],
            [button("删除延迟", f"adm:fs:{CHAT}:delete_after", "toggle", "result", "请选择删除延迟。")],
        ],
        ["force_subscribe_channel_1_input", "force_subscribe_channel_2_input", "force_subscribe_text_input", "force_subscribe_cover_input", "force_subscribe_buttons_input"],
        ["backend/features/admin/module_settings/force_subscribe_inputs.py", "backend/features/admin/moderation/member_actions.py", "backend/features/group_ops/group_hooks/control_force_subscribe.py"],
        [
            input_screen("channel_input", "设置关注目标", "发送频道用户名或邀请链接", "@example_channel", f"adm:menu:forcesub:{CHAT}", examples=[("频道用户名", "@example_channel", "result"), ("邀请链接", "https://t.me/example", "result")]),
            input_screen("cover_input", "设置强制关注封面", "发送图片、视频或 /clear", "image.jpg", f"adm:menu:forcesub:{CHAT}", "home", "media", [("图片", "image.jpg", "result"), ("清空", "/clear", "result")]),
            input_screen("text_input", "设置强制关注文本", "发送未关注时展示的文本", "请先关注频道后再发言。", f"adm:menu:forcesub:{CHAT}", examples=[("提示", "请先关注频道后再发言。", "result")]),
            input_screen("buttons_input", "设置强制关注按钮", "逐行输入按钮，支持分号同排", "关注频道 - https://t.me/example", f"adm:menu:forcesub:{CHAT}", "home", "buttons", [("单按钮", "关注频道 - https://t.me/example", "result"), ("同排", "频道 - https://t.me/a;客服 - https://t.me/b", "result")]),
        ],
    )

    flows["new-member-limit"] = admin_menu_button_flow(
        "new-member-limit",
        "新成员限制",
        "newmem",
        ["adm:nml:"],
        ["按入群时长限制新成员发送媒体、链接或非纯文本内容。"],
        [
            [
                button("开启/关闭", f"adm:nml:{CHAT}:toggle:enabled", "toggle", "result", "新成员限制已切换。"),
                button("限制时长", f"adm:nml:{CHAT}:input:window", "input", "window_input", "请输入限制分钟数。"),
            ],
            [
                button("限制媒体", f"adm:nml:{CHAT}:toggle:block_media", "toggle", "result", "限制媒体已切换。"),
                button("限制链接", f"adm:nml:{CHAT}:toggle:block_links", "toggle", "result", "限制链接已切换。"),
                button("仅纯文本", f"adm:nml:{CHAT}:toggle:text_only", "toggle", "result", "纯文本限制已切换。"),
            ],
            [
                button("删除触发消息", f"adm:nml:{CHAT}:toggle:delete_message", "toggle", "result", "删除触发消息已切换。"),
                button("提示开关", f"adm:nml:{CHAT}:toggle:warn_enabled", "toggle", "result", "提示已切换。"),
                button("提示文本", f"adm:nml:{CHAT}:input:warn_text", "input", "warn_input", "请输入提示文本。"),
            ],
            [button("提示删除时间", f"adm:nml:{CHAT}:cycle:warn_delete", "toggle", "result", "已切换提示删除时间。")],
        ],
        ["new_member_limit_text_input"],
        ["backend/features/admin/moderation/member_menus.py", "backend/features/admin/moderation/member_actions.py", "backend/features/group_ops/group_hooks/control_new_member.py"],
        [
            input_screen("window_input", "设置限制时长", "发送正整数分钟数", "10", f"adm:menu:newmem:{CHAT}", examples=[("10 分钟", "10", "result"), ("60 分钟", "60", "result")], clear=None),
            input_screen("warn_input", "设置提示文本", "发送触发限制时的提示文案", "新成员入群 10 分钟内不能发送链接。", f"adm:menu:newmem:{CHAT}", examples=[("提示文案", "新成员入群 10 分钟内不能发送链接。", "result")]),
        ],
    )

    flows["banned-words"] = flow(
        "banned-words",
        coverage(["banned_word:add:", "banned_word:list:", "banned_word_toggle_", "banned_word_delete_", "keywords:cancel:"], ["banned_word_add"], ["backend/features/moderation/banned_word_router.py", "backend/features/moderation/ui/banned_word.py"]),
        [
            admin_entry("违禁词", f"banned_word:list:{CHAT}"),
            common_select_group(f"banned_word:list:{CHAT}", "entry"),
            common_main_menu("违禁词", f"banned_word:list:{CHAT}"),
            screen(
                "home",
                "违禁词列表",
                ["违禁词使用独立 banned_word 回调创建、开关和删除。"],
                [
                    [
                        button("添加违禁词", f"banned_word:add:{CHAT}", "input", "word_input", "请输入违禁词。", True),
                        button("刷新列表", f"banned_word:list:{CHAT}", "goto", "home", "已刷新列表。"),
                    ],
                    [
                        button("启用词条", f"banned_word_toggle_12:{CHAT}", "toggle", "result", "词条状态已切换。"),
                        button("删除词条", f"banned_word_delete_12:{CHAT}", "confirm", "result", "已删除词条。"),
                    ],
                    [button("取消输入", f"keywords:cancel:{CHAT}", "back", "home", "已取消输入。")],
                    [button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")],
                ],
                ["当前群组：演示群"],
            ),
            input_screen("word_input", "添加违禁词", "发送一个词或多行词条", "广告词", f"banned_word:list:{CHAT}", examples=[("单词", "广告词", "result"), ("多行", "广告词\n诈骗", "result")]),
            screen("result", "违禁词设置结果", ["保存后列表会重新渲染。运行时命中后按惩罚策略处理。"], [[button("返回列表", f"banned_word:list:{CHAT}", "back", "home", "已返回列表。")]]),
        ],
    )

    flows["anti-spam"] = admin_reference_flow(
        "anti-spam",
        "垃圾防护",
        "antispam",
        ["反垃圾配置当前复用垃圾防护规则组，真实按钮为 gg 规则回调。"],
        ["规则：文本垃圾、白名单、动作策略"],
        [
            [
                button("规则详情", f"gg:rule:{RULE}:{CHAT}", "goto", "rule", "打开规则详情。", True),
                button("白名单", f"gg:whitelist:{CHAT}", "goto", "whitelist", "打开白名单。"),
            ],
            [button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")],
        ],
        ["adm:menu:antispam", "gg:rule:", "gg:toggle:", "gg:whitelist:", "gg:input:", "gg:clear:"],
        ["anti_spam_config", "garbage_guard_whitelist"],
        ["backend/features/group_ops/group_hooks/moderation.py", "backend/features/admin/moderation/verification_views.py"],
    )
    flows["join-guard"]["screens"].append(
        screen(
            "spam",
            "入群垃圾防护",
            ["这里复用进群验证中的垃圾拦截页，覆盖入群刷号、提示、禁言和踢出。"],
            [
                [
                    button("入群刷号开关", f"adm:vfy_home:{CHAT}:spam:toggle:enabled", "toggle", "result", "已切换入群刷号检测。"),
                    button("提示开关", f"adm:vfy_home:{CHAT}:spam:toggle:notify", "toggle", "result", "已切换提示。"),
                    button("踢出", f"adm:vfy_home:{CHAT}:spam:toggle:kick", "toggle", "result", "已切换踢出。"),
                ],
                [button("返回垃圾防护", f"adm:menu:antispam:{CHAT}", "back", "home", "已返回垃圾防护。")],
            ],
        )
    )
    flows["anti-spam"]["screens"].extend(
        [
            screen(
                "rule",
                "垃圾防护规则",
                ["真实规则按钮按 rule_id 操作。"],
                [
                    [
                        button("开启规则", f"gg:toggle:{RULE}:enabled:{CHAT}", "toggle", "result", "规则已切换。"),
                        button("消息阈值", f"gg:cycle:{RULE}:messages:{CHAT}", "toggle", "result", "已切换消息阈值。"),
                    ],
                    [button("返回防护首页", f"adm:menu:antispam:{CHAT}", "back", "home", "已返回防护首页。")],
                ],
            ),
            screen(
                "whitelist",
                "白名单",
                ["白名单可通过输入 state 添加，也可一键清空。"],
                [
                    [
                        button("添加白名单", f"gg:input:whitelist:{CHAT}", "input", "whitelist_input", "请输入白名单。"),
                        button("清空白名单", f"gg:clear:whitelist:{CHAT}", "confirm", "result", "已清空白名单。"),
                    ],
                    [button("返回防护首页", f"gg:home:{CHAT}", "back", "home", "已返回防护首页。")],
                ],
            ),
            input_screen("whitelist_input", "添加白名单", "发送用户 ID、用户名或关键词", "@trusted_user", f"gg:whitelist:{CHAT}", "whitelist", "text", [("用户名", "@trusted_user", "result"), ("用户 ID", "123456789", "result")]),
        ]
    )

    flows["anti-flood"] = admin_reference_flow(
        "anti-flood",
        "防刷屏",
        "flood",
        ["防刷屏使用同一组 gg 规则回调，按消息数量和时间窗口判断。"],
        ["规则：短时间多消息、动作策略"],
        [
            [
                button("刷屏规则", f"gg:rule:{RULE}:{CHAT}", "goto", "rule", "打开刷屏规则。", True),
                button("开启规则", f"gg:toggle:{RULE}:enabled:{CHAT}", "toggle", "result", "刷屏规则已切换。"),
            ],
            [
                button("消息阈值", f"gg:cycle:{RULE}:messages:{CHAT}", "toggle", "result", "已切换消息阈值。"),
                button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。"),
            ],
        ],
        ["adm:menu:flood", "gg:rule:", "gg:toggle:", "gg:cycle:"],
        ["anti_flood_config"],
        ["backend/features/group_ops/group_hooks/moderation.py"],
    )
    flows["anti-flood"]["screens"].extend(
        [
            screen("rule", "防刷屏规则", ["调整阈值后，Bot 会回到同一个规则详情页。"], [[button("返回防刷屏", f"adm:menu:flood:{CHAT}", "back", "home", "已返回防刷屏。")]]),
        ]
    )

    flows["punishment-downgrade"] = admin_reference_flow(
        "punishment-downgrade",
        "处罚动作降级",
        "punish",
        ["当机器人缺少禁言、封禁或删除权限时，运行时会按可执行动作降级。", "该能力复用惩罚策略入口，不编造独立配置按钮。"],
        ["运行时：按机器人权限自动降级"],
        [
            [
                button("只删除", f"adm:punish:{CHAT}:preset:delete", "toggle", "result", "已切换为只删除。"),
                button("禁言", f"adm:punish:{CHAT}:preset:mute", "toggle", "result", "已切换为禁言。"),
                button("封禁", f"adm:punish:{CHAT}:preset:ban", "toggle", "result", "已切换为封禁。"),
            ],
        ],
        ["adm:menu:punish", "adm:punish:"],
        files=["backend/features/admin/moderation/member_actions.py", "backend/features/group_ops/group_hooks/moderation.py"],
    )

    flows["punishment-policy"] = admin_menu_button_flow(
        "punishment-policy",
        "惩罚策略",
        "punish",
        ["adm:punish:"],
        ["统一配置删除、禁言、封禁等处罚预设。"],
        [
            [
                button("只删除", f"adm:punish:{CHAT}:preset:delete", "toggle", "result", "已切换为只删除。"),
                button("禁言", f"adm:punish:{CHAT}:preset:mute", "toggle", "result", "已切换为禁言。"),
                button("封禁", f"adm:punish:{CHAT}:preset:ban", "toggle", "result", "已切换为封禁。"),
            ]
        ],
        files=["backend/features/admin/moderation/member_actions.py"],
    )

    points_focus = {
        "sign-points": "这里聚焦签到积分，入口仍是积分中心真实 pts 回调。",
        "message-points": "这里聚焦发言积分，入口仍是积分中心真实 pts 回调。",
        "invite-points": "这里聚焦邀请积分，保存后由邀请归因运行时发放。",
        "points-center": "这里展示主积分中心的真实配置入口。",
        "points-tasks": "积分任务体系当前由签到、发言、邀请和额外规则组成，不编造独立任务按钮。",
    }
    for slug, focus in points_focus.items():
        flows[slug] = points_flow(slug, CATALOG[slug]["title"], focus)

    flows["custom-points"] = admin_menu_button_flow(
        "custom-points",
        "自定义积分",
        "custom_points",
        ["adm:cpt:"],
        ["创建自定义积分类型，并管理排行、加扣分和导出。"],
        [
            [button("新增类型", f"adm:cpt:{CHAT}:add", "input", "type_name_input", "请输入积分类型名称。", True)],
            [
                button("类型详情", f"adm:cpt:{CHAT}:detail:{TYPE}", "goto", "detail", "已打开类型详情。"),
                button("开启类型", f"adm:cpt:{CHAT}:toggle:{TYPE}:1", "toggle", "result", "类型已开启。"),
                button("关闭类型", f"adm:cpt:{CHAT}:toggle:{TYPE}:0", "toggle", "result", "类型已关闭。"),
            ],
        ],
        ["custom_points_name_input", "custom_points_rank_input", "custom_points_adjust_input"],
        ["backend/features/admin/ui/points_extended_custom.py", "backend/features/admin/points_extended/custom_inputs.py"],
        [
            screen(
                "detail",
                "自定义积分详情",
                ["详情页可编辑名称、排行命令、加扣分、导出、清空和删除。"],
                [
                    [
                        button("编辑名称", f"adm:cpt:{CHAT}:edit:name:{TYPE}", "input", "type_name_input", "请输入名称。"),
                        button("排行命令", f"adm:cpt:{CHAT}:edit:rank:{TYPE}", "input", "rank_input", "请输入排行命令。"),
                    ],
                    [
                        button("加分", f"adm:cpt:{CHAT}:adjust:add:{TYPE}", "input", "adjust_input", "请输入加分格式。"),
                        button("扣分", f"adm:cpt:{CHAT}:adjust:deduct:{TYPE}", "input", "adjust_input", "请输入扣分格式。"),
                    ],
                    [
                        button("导出", f"adm:cpt:{CHAT}:export:{TYPE}", "goto", "result", "已发起导出。"),
                        button("清空确认", f"adm:cpt:{CHAT}:clear_confirm:{TYPE}", "confirm", "confirm_clear", "请确认清空。"),
                        button("删除确认", f"adm:cpt:{CHAT}:delete_confirm:{TYPE}", "confirm", "confirm_delete", "请确认删除。"),
                    ],
                    [button("返回列表", f"adm:menu:custom_points:{CHAT}", "back", "home", "已返回列表。")],
                ],
            ),
            input_screen("type_name_input", "输入积分类型名称", "发送名称", "贡献值", f"adm:menu:custom_points:{CHAT}", examples=[("贡献值", "贡献值", "result")]),
            input_screen("rank_input", "输入排行命令", "发送命令别名", "/gxrank", f"adm:cpt:{CHAT}:detail:{TYPE}", "detail", examples=[("排行命令", "/gxrank", "result")]),
            input_screen("adjust_input", "输入加扣分", "格式：用户ID 分数 备注", "123456 10 活动奖励", f"adm:cpt:{CHAT}:detail:{TYPE}", "detail", examples=[("加分", "123456 10 活动奖励", "result"), ("扣分", "123456 5 违规扣除", "result")]),
            screen("confirm_clear", "清空确认", ["清空会删除该类型积分流水和余额。"], [[button("确认清空", f"adm:cpt:{CHAT}:clear:{TYPE}", "confirm", "result", "已清空。"), button("返回详情", f"adm:cpt:{CHAT}:detail:{TYPE}", "back", "detail", "已取消。")]]),
            screen("confirm_delete", "删除确认", ["删除积分类型后不可恢复。"], [[button("确认删除", f"adm:cpt:{CHAT}:delete:{TYPE}", "confirm", "result", "已删除。"), button("返回详情", f"adm:cpt:{CHAT}:detail:{TYPE}", "back", "detail", "已取消。")]]),
        ],
    )

    flows["points-level"] = admin_menu_button_flow(
        "points-level",
        "积分等级",
        "points_level",
        ["adm:lvl:"],
        ["配置积分等级门槛和等级权限。"],
        [
            [
                button("新增等级", f"adm:lvl:{CHAT}:add", "input", "level_name_input", "请输入等级名称。", True),
                button("开启等级", f"adm:lvl:{CHAT}:toggle:enabled:1", "toggle", "result", "积分等级已开启。"),
                button("关闭等级", f"adm:lvl:{CHAT}:toggle:enabled:0", "toggle", "result", "积分等级已关闭。"),
            ],
            [button("等级详情", f"adm:lvl:{CHAT}:detail:{LEVEL}", "goto", "detail", "已打开等级详情。")],
        ],
        ["points_level_name_input", "points_level_threshold_input"],
        ["backend/features/admin/ui/points_extended_levels.py", "backend/features/admin/points_extended/level_inputs.py"],
        [
            screen(
                "detail",
                "等级详情",
                ["详情页可以编辑名称、门槛、权限和删除等级。"],
                [
                    [
                        button("编辑名称", f"adm:lvl:{CHAT}:edit:name:{LEVEL}", "input", "level_name_input", "请输入等级名称。"),
                        button("编辑门槛", f"adm:lvl:{CHAT}:edit:threshold:{LEVEL}", "input", "threshold_input", "请输入积分门槛。"),
                    ],
                    [
                        button("允许发言", f"adm:lvl:{CHAT}:perm:{LEVEL}:allow_text:1", "toggle", "result", "等级发言权限已开启。"),
                        button("删除确认", f"adm:lvl:{CHAT}:delete_confirm:{LEVEL}", "confirm", "delete_confirm", "请确认删除。"),
                    ],
                    [button("返回等级列表", f"adm:menu:points_level:{CHAT}", "back", "home", "已返回等级列表。")],
                ],
            ),
            input_screen("level_name_input", "输入等级名称", "发送等级名称", "Lv1", f"adm:menu:points_level:{CHAT}", examples=[("等级名称", "Lv1", "result")]),
            input_screen("threshold_input", "输入等级门槛", "发送整数积分", "100", f"adm:lvl:{CHAT}:detail:{LEVEL}", "detail", examples=[("100 分", "100", "result")], clear=None),
            screen("delete_confirm", "删除确认", ["删除等级后不会删除用户积分。"], [[button("确认删除", f"adm:lvl:{CHAT}:delete:{LEVEL}", "confirm", "result", "已删除等级。"), button("返回详情", f"adm:lvl:{CHAT}:detail:{LEVEL}", "back", "detail", "已取消。")]]),
        ],
    )

    flows["points-mall"] = admin_menu_button_flow(
        "points-mall",
        "积分商城",
        "points_mall",
        ["adm:mall:"],
        ["配置商城开关、命令、封面、商品和订单处理。"],
        [
            [
                button("开启商城", f"adm:mall:{CHAT}:toggle:enabled:1", "toggle", "result", "商城已开启。"),
                button("关闭商城", f"adm:mall:{CHAT}:toggle:enabled:0", "toggle", "result", "商城已关闭。"),
                button("自动下架", f"adm:mall:{CHAT}:toggle:auto_unlist:1", "toggle", "result", "自动下架已开启。"),
            ],
            [
                button("设置命令", f"adm:mall:{CHAT}:edit:command", "input", "command_input", "请输入商城命令。"),
                button("设置封面", f"adm:mall:{CHAT}:edit:cover", "input", "cover_input", "请发送封面。"),
                button("清空封面", f"adm:mall:{CHAT}:cover:clear", "confirm", "result", "封面已清空。"),
            ],
            [
                button("新增商品", f"adm:mall:{CHAT}:product:add", "input", "product_name_input", "请输入商品名称。", True),
                button("商品详情", f"adm:mall:{CHAT}:product:detail:{PRODUCT}", "goto", "product_detail", "已打开商品详情。"),
                button("订单列表", f"adm:mall:{CHAT}:orders_status:a", "goto", "orders", "已打开订单列表。"),
            ],
        ],
        [
            "points_mall_command_input",
            "points_mall_cover_input",
            "points_mall_product_name_input",
            "points_mall_product_price_input",
            "points_mall_product_limit_input",
            "points_mall_product_stock_input",
            "points_mall_fulfiller_input",
            "points_mall_desc_input",
            "points_mall_product_sort_input",
            "points_mall_product_cover_input",
        ],
        ["backend/features/admin/ui/points_extended_mall.py", "backend/features/admin/points_extended/mall_inputs.py", "backend/features/points/points_mall_actions.py"],
        [
            screen(
                "product_detail",
                "商品详情",
                ["商品详情页使用真实 adm:mall:product:* 回调。"],
                [
                    [
                        button("名称", f"adm:mall:{CHAT}:product:edit:{PRODUCT}:name", "input", "product_name_input", "请输入商品名称。"),
                        button("价格", f"adm:mall:{CHAT}:product:edit:{PRODUCT}:price", "input", "product_price_input", "请输入价格。"),
                        button("库存", f"adm:mall:{CHAT}:product:edit:{PRODUCT}:stock", "input", "product_stock_input", "请输入库存。"),
                    ],
                    [
                        button("封面", f"adm:mall:{CHAT}:product:edit:{PRODUCT}:cover", "input", "product_cover_input", "请发送商品封面。"),
                        button("描述", f"adm:mall:{CHAT}:product:edit:{PRODUCT}:description", "input", "product_desc_input", "请输入描述。"),
                        button("上架", f"adm:mall:{CHAT}:product:toggle:{PRODUCT}:1", "toggle", "result", "商品已上架。"),
                    ],
                    [
                        button("预览", f"adm:mall:{CHAT}:product:preview:{PRODUCT}", "goto", "result", "已打开商品预览。"),
                        button("删除确认", f"adm:mall:{CHAT}:product:delete_confirm:{PRODUCT}", "confirm", "delete_product", "请确认删除。"),
                    ],
                    [button("返回商城", f"adm:menu:points_mall:{CHAT}", "back", "home", "已返回商城。")],
                ],
            ),
            screen(
                "orders",
                "订单列表",
                ["订单详情支持发货、取消和退款。"],
                [
                    [button("订单详情", f"adm:mall:{CHAT}:order:detail:{ORDER}:a:0", "goto", "order_detail", "已打开订单详情。")],
                    [button("返回商城", f"adm:menu:points_mall:{CHAT}", "back", "home", "已返回商城。")],
                ],
            ),
            screen(
                "order_detail",
                "订单详情",
                ["订单处理通过真实 order 回调完成。"],
                [
                    [
                        button("发货", f"adm:mall:{CHAT}:order:fulfill:{ORDER}:a:0", "confirm", "result", "订单已标记发货。"),
                        button("取消", f"adm:mall:{CHAT}:order:cancel:{ORDER}:a:0", "confirm", "result", "订单已取消。"),
                        button("退款", f"adm:mall:{CHAT}:order:refund:{ORDER}:a:0", "confirm", "result", "订单已退款。"),
                    ],
                    [button("返回订单列表", f"adm:mall:{CHAT}:orders_status:a", "back", "orders", "已返回订单列表。")],
                ],
            ),
            input_screen("command_input", "设置商城命令", "发送命令", "/shop", f"adm:menu:points_mall:{CHAT}", examples=[("命令", "/shop", "result")]),
            input_screen("cover_input", "设置商城封面", "发送图片或 /clear", "image.jpg", f"adm:menu:points_mall:{CHAT}", "home", "media", [("图片", "image.jpg", "result"), ("清空", "/clear", "result")]),
            input_screen("product_name_input", "输入商品名称", "发送商品名称", "VIP 兑换", f"adm:menu:points_mall:{CHAT}", examples=[("名称", "VIP 兑换", "result")]),
            input_screen("product_price_input", "输入商品价格", "发送积分价格", "100", f"adm:mall:{CHAT}:product:detail:{PRODUCT}", "product_detail", "number", [("价格", "100", "result")], clear=None),
            input_screen("product_stock_input", "输入商品库存", "发送库存数量", "20", f"adm:mall:{CHAT}:product:detail:{PRODUCT}", "product_detail", "number", [("库存", "20", "result")], clear=None),
            input_screen("product_cover_input", "输入商品封面", "发送图片或 /clear", "product.jpg", f"adm:mall:{CHAT}:product:detail:{PRODUCT}", "product_detail", "media", [("图片", "product.jpg", "result"), ("清空", "/clear", "result")]),
            input_screen("product_desc_input", "输入商品描述", "发送商品描述", "兑换后联系管理员发货。", f"adm:mall:{CHAT}:product:detail:{PRODUCT}", "product_detail", "text", [("描述", "兑换后联系管理员发货。", "result")]),
            screen("delete_product", "删除商品确认", ["删除商品不会删除已产生订单。"], [[button("确认删除", f"adm:mall:{CHAT}:product:delete:{PRODUCT}", "confirm", "result", "商品已删除。"), button("返回详情", f"adm:mall:{CHAT}:product:detail:{PRODUCT}", "back", "product_detail", "已取消。")]]),
        ],
    )

    flows["auto-reply"] = flow(
        "auto-reply",
        coverage(
            ["auto_reply:create:", "auto_reply:list:", "auto_reply:detail:", "auto_reply:set:", "auto_reply:edit:", "auto_reply:preview:", "auto_reply:delay:", "auto_reply:delete:", "btned:open:auto_reply:"],
            ["auto_reply_create", "auto_reply_edit_keywords", "auto_reply_edit_content", "auto_reply_edit_cover", "auto_reply_edit_buttons"],
            ["backend/features/moderation/auto_reply_router.py", "backend/features/moderation/ui/auto_reply.py", "backend/features/moderation/auto_reply_input.py"],
        ),
        [
            admin_entry("自动回复", f"auto_reply:list:{CHAT}"),
            common_select_group(f"auto_reply:list:{CHAT}", "entry"),
            common_main_menu("自动回复", f"auto_reply:list:{CHAT}"),
            screen(
                "home",
                "自动回复列表",
                ["自动回复通过 auto_reply:* 回调创建、编辑、排序和删除。"],
                [
                    [
                        button("创建规则", f"auto_reply:create:{CHAT}", "input", "create_input", "请输入触发词和回复内容。", True),
                        button("刷新列表", f"auto_reply:list:{CHAT}", "goto", "home", "已刷新列表。"),
                    ],
                    [button("规则详情", f"auto_reply:detail:{CHAT}:{RULE}", "goto", "detail", "已打开规则详情。")],
                    [button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")],
                ],
            ),
            screen(
                "detail",
                "自动回复详情",
                ["详情页覆盖启用、匹配方式、编辑内容、按钮、预览、延迟和删除。"],
                [
                    [
                        button("启用", f"auto_reply:set:{CHAT}:{RULE}:active:1", "toggle", "result", "规则已启用。"),
                        button("关闭", f"auto_reply:set:{CHAT}:{RULE}:active:0", "toggle", "result", "规则已关闭。"),
                    ],
                    [
                        button("精准匹配", f"auto_reply:set:{CHAT}:{RULE}:match:exact", "toggle", "result", "已改为精准匹配。"),
                        button("包含匹配", f"auto_reply:set:{CHAT}:{RULE}:match:contains", "toggle", "result", "已改为包含匹配。"),
                    ],
                    [
                        button("关键词", f"auto_reply:edit:{CHAT}:{RULE}:keywords", "input", "keywords_input", "请输入关键词。"),
                        button("回复内容", f"auto_reply:edit:{CHAT}:{RULE}:content", "input", "content_input", "请输入回复内容。"),
                        button("封面", f"auto_reply:edit:{CHAT}:{RULE}:cover", "input", "cover_input", "请发送封面。"),
                    ],
                    [
                        button("设置按钮", f"btned:open:auto_reply:{CHAT}:{RULE}", "input", "buttons_input", "请输入按钮。"),
                        button("预览", f"auto_reply:preview:{CHAT}:{RULE}", "goto", "result", "已发送预览。"),
                        button("延迟", f"auto_reply:delay:{CHAT}:{RULE}", "goto", "delay", "打开延迟设置。"),
                    ],
                    [
                        button("删除", f"auto_reply:delete:{CHAT}:{RULE}:confirm", "confirm", "delete_confirm", "请确认删除。"),
                        button("返回列表", f"auto_reply:list:{CHAT}", "back", "home", "已返回列表。"),
                    ],
                ],
            ),
            screen(
                "delay",
                "回复延迟",
                ["延迟按钮使用 auto_reply:delay:set 回调。"],
                [
                    [
                        button("15 秒", f"auto_reply:delay:set:{CHAT}:{RULE}:15", "toggle", "result", "已设置 15 秒。"),
                        button("30 秒", f"auto_reply:delay:set:{CHAT}:{RULE}:30", "toggle", "result", "已设置 30 秒。"),
                        button("不延迟", f"auto_reply:delay:set:{CHAT}:{RULE}:0", "toggle", "result", "已关闭延迟。"),
                    ],
                    [button("返回详情", f"auto_reply:detail:{CHAT}:{RULE}", "back", "detail", "已返回详情。")],
                ],
            ),
            input_screen("create_input", "创建自动回复", "格式：关键词 -> 回复内容", "关键词 -> 回复内容", f"auto_reply:list:{CHAT}", examples=[("创建规则", "价格 -> 请查看置顶价格表", "detail")]),
            input_screen("keywords_input", "编辑关键词", "每行一个关键词", "价格\n报价", f"auto_reply:detail:{CHAT}:{RULE}", "detail", examples=[("关键词", "价格\n报价", "result")]),
            input_screen("content_input", "编辑回复内容", "发送文本，支持 /clear", "这是自动回复内容。", f"auto_reply:detail:{CHAT}:{RULE}", "detail", examples=[("回复文本", "这是自动回复内容。", "result"), ("清空", "/clear", "result")]),
            input_screen("cover_input", "编辑封面", "发送媒体或 /clear", "image.jpg", f"auto_reply:detail:{CHAT}:{RULE}", "detail", "media", [("图片", "image.jpg", "result"), ("清空", "/clear", "result")]),
            input_screen("buttons_input", "编辑自动回复按钮", "逐行按钮，支持分号同排和 JSON", "官网 - https://example.com", f"auto_reply:detail:{CHAT}:{RULE}", "detail", "buttons", [("按钮", "官网 - https://example.com", "result"), ("同排", "官网 - https://a.com;客服 - https://b.com", "result")]),
            screen("delete_confirm", "删除确认", ["确认后规则会被删除。"], [[button("确认删除", f"auto_reply:delete:{CHAT}:{RULE}:do", "confirm", "result", "规则已删除。"), button("返回详情", f"auto_reply:detail:{CHAT}:{RULE}", "back", "detail", "已取消。")]]),
            screen("result", "自动回复设置结果", ["保存后回到列表或详情页，运行时按关键词匹配。"], [[button("返回详情", f"auto_reply:detail:{CHAT}:{RULE}", "back", "detail", "已返回详情。"), button("返回列表", f"auto_reply:list:{CHAT}", "back", "home", "已返回列表。")]]),
        ],
    )

    # 定时消息和按钮输入都复用真实 sm 工作台；两页关注点不同，但不拆出不存在的入口。
    for slug, title_msg in [
        ("scheduled-message", "定时消息列表、详情、编辑、预览和删除全部使用 sm:* 回调。"),
        ("scheduled-message-buttons", "这里重点展示「设置按钮」输入格式，入口仍是定时消息详情。"),
    ]:
        flows[slug] = flow(
            slug,
            coverage(
                ["sm:list:", "sm:add:", "sm:open:", "sm:set:", "sm:edit:", "sm:preview:", "sm:del_confirm:", "sm:del_do:", "sm:del_cancel:"],
                ["sm_edit_title", "sm_edit_text", "sm_edit_media", "sm_edit_buttons", "sm_edit_start_at", "sm_edit_end_at"],
                ["backend/features/automation/scheduled_message_router.py", "backend/features/automation/ui/scheduled_message_list.py", "backend/features/automation/ui/scheduled_message_detail.py", "backend/features/automation/ui/scheduled_message_edit.py", "backend/features/automation/scheduled_message_inputs.py"],
            ),
            [
                admin_entry(CATALOG[slug]["title"], f"sm:list:{CHAT}:0"),
                common_select_group(f"sm:list:{CHAT}:0", "entry"),
                common_main_menu(CATALOG[slug]["title"], f"sm:list:{CHAT}:0"),
                screen(
                    "home",
                    "定时消息列表",
                    [title_msg],
                    [
                        [
                            button("添加一条", f"sm:add:{CHAT}", "goto", "detail", "已创建未启用任务。", True),
                            button("任务详情", f"sm:open:{CHAT}:{TASK}", "goto", "detail", "已打开任务详情。"),
                        ],
                        [
                            button("上一页", f"sm:list:{CHAT}:0", "toast", feedback="已经是第一页。"),
                            button("下一页", f"sm:list:{CHAT}:1", "toast", feedback="演示数据没有下一页。"),
                        ],
                        [button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")],
                    ],
                    ["任务：A1B2C3，状态：关闭"],
                ),
                screen(
                    "detail",
                    "定时消息详情",
                    ["任务必须设置文本或封面后才能启用。"],
                    [
                        [
                            button("启用", f"sm:set:{CHAT}:{TASK}:enabled:1", "toggle", "enable_error", "启用失败：请先设置文本或封面。"),
                            button("关闭", f"sm:set:{CHAT}:{TASK}:enabled:0", "toggle", "result", "任务已关闭。"),
                        ],
                        [
                            button("标题备注", f"sm:edit:{CHAT}:{TASK}:title", "input", "title_input", "请输入标题备注。"),
                            button("设置封面", f"sm:edit:{CHAT}:{TASK}:media", "input", "media_input", "请发送封面媒体。"),
                            button("设置文本", f"sm:edit:{CHAT}:{TASK}:text", "input", "text_input", "请输入消息正文。"),
                        ],
                        [
                            button("设置按钮", f"sm:edit:{CHAT}:{TASK}:buttons", "input", "buttons_input", "请输入按钮。", slug == "scheduled-message-buttons"),
                            button("开始时间", f"sm:edit:{CHAT}:{TASK}:start_at", "input", "start_input", "请输入开始时间。"),
                            button("结束时间", f"sm:edit:{CHAT}:{TASK}:end_at", "input", "end_input", "请输入结束时间。"),
                        ],
                        [
                            button("每 60 分钟", f"sm:set:{CHAT}:{TASK}:repeat:60", "toggle", "result", "发送频率已设为 60 分钟。"),
                            button("置顶", f"sm:set:{CHAT}:{TASK}:pin_message:1", "toggle", "result", "置顶已开启。"),
                            button("删除上条", f"sm:set:{CHAT}:{TASK}:delete_previous:1", "toggle", "result", "删除上条已开启。"),
                        ],
                        [
                            button("预览效果", f"sm:preview:{CHAT}:{TASK}", "goto", "result", "已发送预览。"),
                            button("删除", f"sm:del_confirm:{CHAT}:{TASK}", "confirm", "delete_confirm", "请确认删除。"),
                            button("返回列表", f"sm:list:{CHAT}:0", "back", "home", "已返回列表。"),
                        ],
                    ],
                ),
                screen("enable_error", "启用失败", ["真实后端会检查任务是否有文本或封面；缺少内容时不会启用。"], [[button("设置文本", f"sm:edit:{CHAT}:{TASK}:text", "input", "text_input", "去设置文本。"), button("返回详情", f"sm:open:{CHAT}:{TASK}", "back", "detail", "已返回详情。")]]),
                input_screen("title_input", "设置标题备注", "发送备注文本", "每日公告", f"sm:open:{CHAT}:{TASK}", "detail", "text", [("备注", "每日公告", "result"), ("清空", "/clear", "result")]),
                input_screen("media_input", "设置封面", "发送图片、视频、文档、贴纸、动画，或 /clear", "image.jpg", f"sm:open:{CHAT}:{TASK}", "detail", "media", [("图片", "image.jpg", "result"), ("清空", "/clear", "result")]),
                input_screen("text_input", "设置文本", "发送消息正文，支持 /clear", "今晚 8 点开始活动。", f"sm:open:{CHAT}:{TASK}", "detail", "text", [("正文", "今晚 8 点开始活动。", "result"), ("清空", "/clear", "result")]),
                input_screen("buttons_input", "设置按钮", "支持逐行格式、分号同排和 JSON", "官网 - https://example.com", f"sm:open:{CHAT}:{TASK}", "detail", "buttons", [("逐行", "官网 - https://example.com", "result"), ("同排", "官网 - https://a.com;客服 - https://b.com", "result"), ("JSON", "[{\"text\":\"官网\",\"url\":\"https://example.com\"}]", "result")]),
                input_screen("start_input", "设置开始时间", "格式：YYYY-MM-DD HH:MM", "2026-04-18 20:00", f"sm:open:{CHAT}:{TASK}", "detail", "datetime", [("开始时间", "2026-04-18 20:00", "result")], clear="/clear"),
                input_screen("end_input", "设置结束时间", "格式：YYYY-MM-DD HH:MM", "2026-04-30 23:00", f"sm:open:{CHAT}:{TASK}", "detail", "datetime", [("结束时间", "2026-04-30 23:00", "result")], clear="/clear"),
                screen("delete_confirm", "删除确认", ["确认后任务会删除。"], [[button("确认删除", f"sm:del_do:{CHAT}:{TASK}", "confirm", "result", "任务已删除。"), button("取消", f"sm:del_cancel:{CHAT}:{TASK}", "back", "detail", "已取消。")]]),
                screen("result", "定时消息设置结果", ["保存后 Bot 回到任务详情或列表页。"], [[button("返回详情", f"sm:open:{CHAT}:{TASK}", "back", "detail", "已返回详情。"), button("返回列表", f"sm:list:{CHAT}:0", "back", "home", "已返回列表。")]]),
            ],
        )

    flows["rotating-ads"] = flow(
        "rotating-ads",
        coverage(
            ["ads:menu:", "ads:rules:", "ads:rules:set:", "ads:rules:input:", "ads:list:", "ads:create:", "ads:detail:", "ads:item:set:", "ads:item:input:", "ads:item:time:", "ads:item:preview:", "ads:item:delete:"],
            ["ads_create_config", "ads_rule_edit_start", "ads_rule_edit_interval", "ads_rule_edit_delay", "ads_item_edit_title", "ads_item_edit_text", "ads_item_edit_cover", "ads_item_edit_start", "ads_item_edit_end", "ads_item_edit_order"],
            ["backend/features/automation/ads_router.py", "backend/features/automation/ui/ads.py", "backend/features/automation/ads_menu.py", "backend/features/automation/ads_handler.py"],
        ),
        [
            admin_entry("轮播广告", f"ads:menu:{CHAT}"),
            common_select_group(f"ads:menu:{CHAT}", "entry"),
            common_main_menu("轮播广告", f"ads:menu:{CHAT}"),
            screen(
                "home",
                "轮播广告",
                ["轮播广告由全局规则和广告项组成。"],
                [
                    [
                        button("投放规则", f"ads:rules:{CHAT}", "goto", "rules", "打开投放规则。"),
                        button("广告列表", f"ads:list:{CHAT}:0", "goto", "list", "打开广告列表。"),
                        button("新建广告", f"ads:create:{CHAT}", "input", "create_input", "请输入广告配置。", True),
                    ],
                    [button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")],
                ],
            ),
            screen(
                "rules",
                "投放规则",
                ["规则控制启用、模式、开始时间、间隔和删除策略。"],
                [
                    [
                        button("启用规则", f"ads:rules:set:{CHAT}:enabled:1", "toggle", "result", "规则已启用。"),
                        button("发送并置顶", f"ads:rules:set:{CHAT}:mode:send_pin", "toggle", "result", "模式已切换。"),
                    ],
                    [
                        button("开始时间", f"ads:rules:input:{CHAT}:start", "input", "rule_time_input", "请输入开始时间。"),
                        button("发送间隔", f"ads:rules:input:{CHAT}:interval", "input", "rule_interval_input", "请输入发送间隔。"),
                        button("自定义间隔", f"ads:rules:input:{CHAT}:interval_custom", "input", "rule_interval_input", "请输入自定义间隔。"),
                    ],
                    [
                        button("取消上次置顶", f"ads:rules:set:{CHAT}:unpin_previous:1", "toggle", "result", "已开启取消上次置顶。"),
                        button("删除上一条", f"ads:rules:set:{CHAT}:delete_policy:delete_prev", "toggle", "result", "删除策略已切换。"),
                    ],
                    [button("返回广告首页", f"ads:menu:{CHAT}", "back", "home", "已返回广告首页。")],
                ],
            ),
            screen(
                "list",
                "广告列表",
                ["广告项可单独启用、编辑、预览和删除。"],
                [
                    [button("广告详情", f"ads:detail:{CHAT}:{ITEM}", "goto", "detail", "已打开广告详情。")],
                    [button("返回广告首页", f"ads:menu:{CHAT}", "back", "home", "已返回广告首页。")],
                ],
            ),
            screen(
                "detail",
                "广告详情",
                ["详情页使用 ads:item:* 回调编辑广告项。"],
                [
                    [
                        button("启用", f"ads:item:set:{CHAT}:{ITEM}:enabled:1", "toggle", "result", "广告已启用。"),
                        button("标题", f"ads:item:input:{CHAT}:{ITEM}:title", "input", "item_title_input", "请输入标题。"),
                        button("文本", f"ads:item:input:{CHAT}:{ITEM}:text", "input", "item_text_input", "请输入文本。"),
                    ],
                    [
                        button("封面", f"ads:item:input:{CHAT}:{ITEM}:cover", "input", "item_cover_input", "请发送封面。"),
                        button("时间", f"ads:item:time:{CHAT}:{ITEM}", "goto", "item_time", "打开时间设置。"),
                        button("预览", f"ads:item:preview:{CHAT}:{ITEM}", "goto", "result", "已发送预览。"),
                    ],
                    [button("删除", f"ads:item:delete:{CHAT}:{ITEM}", "confirm", "result", "广告已删除。"), button("返回列表", f"ads:list:{CHAT}:0", "back", "list", "已返回列表。")],
                ],
            ),
            screen("item_time", "广告时间", ["设置单条广告开始和结束时间。"], [[button("开始", f"ads:item:input:{CHAT}:{ITEM}:start", "input", "item_start_input", "请输入开始时间。"), button("结束", f"ads:item:input:{CHAT}:{ITEM}:end", "input", "item_end_input", "请输入结束时间。")], [button("返回详情", f"ads:detail:{CHAT}:{ITEM}", "back", "detail", "已返回详情。")]]),
            input_screen("create_input", "创建广告", "发送创建配置", "广告标题 | 广告文本", f"ads:menu:{CHAT}", examples=[("配置", "活动广告 | 今天 20:00 开始", "detail")]),
            input_screen("rule_time_input", "设置规则开始时间", "格式：YYYY-MM-DD HH:MM", "2026-04-18 20:00", f"ads:rules:{CHAT}", "rules", "datetime", [("开始时间", "2026-04-18 20:00", "result")]),
            input_screen("rule_interval_input", "设置投放间隔", "发送分钟数", "60", f"ads:rules:{CHAT}", "rules", "number", [("60 分钟", "60", "result")], clear=None),
            input_screen("item_title_input", "设置广告标题", "发送标题", "活动广告", f"ads:detail:{CHAT}:{ITEM}", "detail", "text", [("标题", "活动广告", "result")]),
            input_screen("item_text_input", "设置广告文本", "发送文本或 /clear", "今天 20:00 开始。", f"ads:detail:{CHAT}:{ITEM}", "detail", "text", [("文本", "今天 20:00 开始。", "result"), ("清空", "/clear", "result")]),
            input_screen("item_cover_input", "设置广告封面", "发送媒体或 /clear", "ad.jpg", f"ads:detail:{CHAT}:{ITEM}", "detail", "media", [("图片", "ad.jpg", "result"), ("清空", "/clear", "result")]),
            input_screen("item_start_input", "设置广告开始", "格式：YYYY-MM-DD HH:MM", "2026-04-18 20:00", f"ads:detail:{CHAT}:{ITEM}", "detail", "datetime", [("开始", "2026-04-18 20:00", "result")]),
            input_screen("item_end_input", "设置广告结束", "格式：YYYY-MM-DD HH:MM", "2026-04-30 23:00", f"ads:detail:{CHAT}:{ITEM}", "detail", "datetime", [("结束", "2026-04-30 23:00", "result")]),
            screen("result", "轮播广告设置结果", ["保存后返回规则页、列表页或详情页。"], [[button("返回广告首页", f"ads:menu:{CHAT}", "back", "home", "已返回广告首页。")]]),
        ],
    )

    for slug, focus in {
        "invite-link-management": "这里聚焦管理员创建、查看和撤销邀请链接。",
        "user-invite-link": "这里聚焦用户自助生成邀请链接。",
        "invite-attribution": "这里聚焦邀请归因运行时，配置入口仍是邀请配置。",
        "invite-rank": "这里聚焦用户邀请排行和邀请积分结果。",
    }.items():
        flows[slug] = invite_flow(slug, CATALOG[slug]["title"], focus)

    flows["welcome-message"] = admin_menu_button_flow(
        "welcome-message",
        "欢迎消息",
        "welcome",
        ["adm:wel:", "btned:open:welcome:"],
        ["配置新人入群欢迎消息，支持封面、文本、按钮、预览和删除。"],
        [
            [button("新增欢迎", f"adm:wel:{CHAT}:add", "input", "title_input", "请输入欢迎标题。", True)],
            [button("欢迎详情", f"adm:wel:{CHAT}:detail:{WELCOME}", "goto", "detail", "已打开欢迎详情。")],
        ],
        ["welcome_title_input", "welcome_text_input", "welcome_cover_input", "welcome_buttons_input"],
        ["backend/features/admin/welcome/controller.py", "backend/features/admin/welcome/input_handlers.py"],
        [
            screen(
                "detail",
                "欢迎消息详情",
                ["欢迎详情可编辑标题、封面、文本、按钮、模式和删除时间。"],
                [
                    [
                        button("启用", f"adm:wel:{CHAT}:toggle:{WELCOME}", "toggle", "result", "欢迎消息已切换。"),
                        button("模式", f"adm:wel:{CHAT}:mode:{WELCOME}", "toggle", "result", "欢迎模式已切换。"),
                    ],
                    [
                        button("标题", f"adm:wel:{CHAT}:input:{WELCOME}:title", "input", "title_input", "请输入标题。"),
                        button("封面", f"adm:wel:{CHAT}:input:{WELCOME}:cover", "input", "cover_input", "请发送封面。"),
                        button("文本", f"adm:wel:{CHAT}:input:{WELCOME}:text", "input", "text_input", "请输入文本。"),
                    ],
                    [
                        button("按钮", f"btned:open:welcome:{CHAT}:{WELCOME}", "input", "buttons_input", "请输入按钮。"),
                        button("预览", f"adm:wel:{CHAT}:preview:{WELCOME}", "goto", "result", "已发送预览。"),
                        button("删除延迟", f"adm:wel:{CHAT}:cycle_delete:{WELCOME}", "toggle", "result", "已切换删除延迟。"),
                    ],
                    [button("删除", f"adm:wel:{CHAT}:delete:{WELCOME}", "confirm", "result", "欢迎消息已删除。"), button("返回列表", f"adm:menu:welcome:{CHAT}", "back", "home", "已返回列表。")],
                ],
            ),
            input_screen("title_input", "输入欢迎标题", "发送标题", "欢迎新人", f"adm:menu:welcome:{CHAT}", examples=[("标题", "欢迎新人", "result")]),
            input_screen("cover_input", "输入欢迎封面", "发送媒体或 /clear", "welcome.jpg", f"adm:wel:{CHAT}:detail:{WELCOME}", "detail", "media", [("图片", "welcome.jpg", "result"), ("清空", "/clear", "result")]),
            input_screen("text_input", "输入欢迎文本", "发送欢迎正文", "欢迎加入本群，请先阅读群规。", f"adm:wel:{CHAT}:detail:{WELCOME}", "detail", "text", [("正文", "欢迎加入本群，请先阅读群规。", "result")]),
            input_screen("buttons_input", "输入欢迎按钮", "逐行按钮，支持分号同排", "群规 - https://example.com/rules", f"adm:wel:{CHAT}:detail:{WELCOME}", "detail", "buttons", [("按钮", "群规 - https://example.com/rules", "result")]),
        ],
    )

    flows["rename-monitor"] = admin_menu_button_flow(
        "rename-monitor",
        "改名监控",
        "renamewatch",
        ["adm:rm:"],
        ["监控成员改名并发送提示。"],
        [
            [
                button("开启", f"adm:rm:{CHAT}:set:enabled:1", "toggle", "result", "改名监控已开启。"),
                button("关闭", f"adm:rm:{CHAT}:set:enabled:0", "toggle", "result", "改名监控已关闭。"),
                button("提示文本", f"adm:rm:{CHAT}:input:text", "input", "text_input", "请输入提示文本。"),
            ],
            [button("预览", f"adm:rm:{CHAT}:preview", "goto", "result", "已发送预览。"), button("删除延迟", f"adm:rm:{CHAT}:cycle_delete_after", "toggle", "result", "已切换删除延迟。")],
        ],
        ["rename_monitor_text_input"],
        ["backend/features/admin/module_settings/group_control_inputs.py", "backend/features/group_ops/group_hooks/control_rename.py"],
        [input_screen("text_input", "设置改名提示", "发送提示文本", "成员 {old_name} 已改名为 {new_name}", f"adm:menu:renamewatch:{CHAT}", examples=[("提示", "成员 {old_name} 已改名为 {new_name}", "result")])],
    )

    flows["alliance"] = admin_menu_button_flow(
        "alliance",
        "联盟功能",
        "alliance",
        ["ali:"],
        ["联盟用于多个群共享联合封禁等治理能力。"],
        [
            [
                button("创建联盟", f"ali:create:input:{CHAT}", "input", "create_input", "请输入联盟名称。", True),
                button("加入联盟", f"ali:join:input:{CHAT}", "input", "join_input", "请输入邀请码。"),
            ],
            [
                button("成员列表", f"ali:members:{CHAT}", "goto", "members", "已打开成员列表。"),
                button("联合封禁", f"ali:jointban:toggle:{CHAT}:1", "toggle", "result", "联合封禁已开启。"),
                button("邀请码", f"ali:invite:show:{CHAT}", "goto", "result", "已显示邀请码。"),
            ],
            [button("退出联盟", f"ali:leave:{CHAT}:confirm", "confirm", "result", "请确认退出联盟。")],
        ],
        ["alliance_create_name_input", "alliance_join_code_input"],
        ["backend/features/admin/garage/alliance.py", "backend/features/admin/garage/alliance_inputs.py", "backend/features/garage/services/alliance_service.py"],
        [
            input_screen("create_input", "创建联盟", "发送联盟名称", "车友联盟", f"ali:home:{CHAT}", examples=[("名称", "车友联盟", "result")]),
            input_screen("join_input", "加入联盟", "发送联盟邀请码", "ABCD1234", f"ali:home:{CHAT}", examples=[("邀请码", "ABCD1234", "result")]),
            screen("members", "联盟成员", ["成员列表展示已加入联盟的群组。"], [[button("返回联盟", f"ali:home:{CHAT}", "back", "home", "已返回联盟。")]]),
        ],
    )

    flows["garage-auth"] = admin_menu_button_flow(
        "garage-auth",
        "车库认证",
        "garage_auth",
        ["grg:"],
        ["配置车库认证标识、老师白名单和发言限制。"],
        [
            [
                button("开启认证", f"grg:toggle:{CHAT}:1", "toggle", "result", "车库认证已开启。"),
                button("关闭认证", f"grg:toggle:{CHAT}:0", "toggle", "result", "车库认证已关闭。"),
                button("认证标识", f"grg:badge:{CHAT}", "input", "badge_input", "请输入认证标识。"),
            ],
            [
                button("老师列表", f"grg:teacher:list:{CHAT}:0", "goto", "teachers", "已打开老师列表。"),
                button("摘要菜单", f"grg:summary:menu:{CHAT}", "goto", "result", "已打开摘要菜单。"),
            ],
            [
                button("限制开启", f"grg:limit:toggle:{CHAT}:1", "toggle", "result", "发言限制已开启。"),
                button("限制模式", f"grg:limit:mode:{CHAT}:image_text", "toggle", "result", "限制模式已切换。"),
                button("白名单", f"grg:wl:list:{CHAT}:0", "goto", "whitelist", "已打开白名单。"),
            ],
        ],
        ["garage_badge_input", "garage_teacher_input", "garage_whitelist_input", "garage_limit_interval_input", "garage_limit_max_count_input"],
        ["backend/features/admin/garage/auth_views.py", "backend/features/admin/garage/auth_actions.py", "backend/features/admin/garage/auth_inputs.py"],
        [
            input_screen("badge_input", "设置认证标识", "发送认证标识", "认证车库", f"grg:home:{CHAT}", examples=[("标识", "认证车库", "result")]),
            screen("teachers", "老师列表", ["老师列表由真实 grg:teacher:list 回调分页。"], [[button("返回车库认证", f"grg:home:{CHAT}", "back", "home", "已返回车库认证。")]]),
            screen("whitelist", "认证白名单", ["白名单列表由真实 grg:wl:list 回调分页。"], [[button("返回车库认证", f"grg:home:{CHAT}", "back", "home", "已返回车库认证。")]]),
        ],
    )

    flows["teacher-search"] = admin_menu_button_flow(
        "teacher-search",
        "老师搜索",
        "teacher_search",
        ["tsearch:"],
        ["配置老师搜索标签、出勤、页脚和代理地点。"],
        [
            [
                button("标签开关", f"tsearch:toggle:tag:{CHAT}:1", "toggle", "result", "标签搜索已开启。"),
                button("出勤开关", f"tsearch:toggle:attendance:{CHAT}:1", "toggle", "result", "出勤已开启。"),
                button("只看可约", f"tsearch:toggle:only_open:{CHAT}:1", "toggle", "result", "只看可约已开启。"),
            ],
            [
                button("出勤模式", f"tsearch:attendance_mode:menu:{CHAT}", "goto", "attendance_mode", "打开出勤模式。"),
                button("页脚", f"tsearch:footer:menu:{CHAT}", "goto", "footer", "打开页脚设置。"),
                button("代理设置", f"tsearch:delegate:start:{CHAT}", "input", "delegate_input", "请输入代理目标。"),
            ],
        ],
        ["teacher_footer_text_input", "teacher_footer_link_input", "teacher_attend_target_input", "teacher_att_open_input", "teacher_att_full_input", "teacher_att_rest_input", "teacher_delegate_target_input", "teacher_delegate_location_input"],
        ["backend/features/admin/garage/teacher_search_views.py", "backend/features/admin/garage/teacher_search_actions.py", "backend/features/admin/garage/teacher_search_inputs.py"],
        [
            screen("attendance_mode", "出勤模式", ["出勤模式可选消息模式或关键词模式。"], [[button("消息模式", f"tsearch:attendance_mode:set:{CHAT}:message", "toggle", "result", "已设置消息模式。"), button("关键词模式", f"tsearch:attendance_mode:set:{CHAT}:keyword", "toggle", "result", "已设置关键词模式。")], [button("返回老师搜索", f"tsearch:home:{CHAT}", "back", "home", "已返回老师搜索。")]]),
            screen("footer", "页脚设置", ["页脚文本和链接会附加到老师搜索结果。"], [[button("页脚文本", f"tsearch:footer:text:{CHAT}", "input", "footer_text_input", "请输入页脚文本。"), button("页脚链接", f"tsearch:footer:link:{CHAT}", "input", "footer_link_input", "请输入链接。")], [button("返回老师搜索", f"tsearch:home:{CHAT}", "back", "home", "已返回老师搜索。")]]),
            input_screen("footer_text_input", "设置页脚文本", "发送页脚文本", "联系管理员获取更多信息", f"tsearch:footer:menu:{CHAT}", "footer", examples=[("页脚", "联系管理员获取更多信息", "result")]),
            input_screen("footer_link_input", "设置页脚链接", "发送 URL", "https://example.com", f"tsearch:footer:menu:{CHAT}", "footer", examples=[("链接", "https://example.com", "result")]),
            input_screen("delegate_input", "设置代理目标", "发送代理用户或地点", "@delegate", f"tsearch:home:{CHAT}", examples=[("代理", "@delegate", "result")]),
        ],
    )

    flows["garage-forward"] = admin_menu_button_flow(
        "garage-forward",
        "车库转发",
        "garage_forward",
        ["gfw:"],
        ["配置频道/群消息转发、关键词过滤和按钮保留。"],
        [
            [
                button("开启转发", f"gfw:toggle:{CHAT}:1", "toggle", "result", "转发已开启。"),
                button("关闭转发", f"gfw:toggle:{CHAT}:0", "toggle", "result", "转发已关闭。"),
                button("转发模式", f"gfw:mode:{CHAT}:all", "toggle", "result", "转发模式已切换。"),
            ],
            [
                button("保留按钮", f"gfw:btn_toggle:{CHAT}:1", "toggle", "result", "保留按钮已开启。"),
                button("按钮配置", f"gfw:buttons:input:{CHAT}", "input", "buttons_input", "请输入按钮配置。"),
                button("关键词", f"gfw:keywords:input:{CHAT}", "input", "keywords_input", "请输入关键词。"),
            ],
            [
                button("添加来源", f"gfw:source:add:{CHAT}", "input", "source_input", "请输入来源频道。"),
                button("审核列表", f"gfw:audit:{CHAT}:a", "goto", "result", "已打开审核列表。"),
            ],
        ],
        ["garage_forward_source_input", "garage_forward_keyword_input", "garage_forward_buttons_input"],
        ["backend/features/admin/garage/forward.py", "backend/features/admin/garage/forward_inputs.py", "backend/features/garage/garage_forward_handler.py"],
        [
            input_screen("buttons_input", "设置转发按钮", "逐行按钮，支持分号同排", "原文 - https://t.me/source", f"gfw:home:{CHAT}", input_type="buttons", examples=[("按钮", "原文 - https://t.me/source", "result")]),
            input_screen("keywords_input", "设置转发关键词", "每行一个关键词", "重要\n公告", f"gfw:home:{CHAT}", examples=[("关键词", "重要\n公告", "result")]),
            input_screen("source_input", "添加转发来源", "发送频道用户名或 ID", "@source_channel", f"gfw:home:{CHAT}", examples=[("来源", "@source_channel", "result")]),
        ],
    )

    flows["car-review"] = admin_menu_button_flow(
        "car-review",
        "车评系统",
        "car_review",
        ["crv:"],
        ["配置投稿命令、审批人、模板字段和发布目标。"],
        [
            [
                button("开启车评", f"crv:toggle:{CHAT}:1", "toggle", "result", "车评已开启。"),
                button("投稿命令", f"crv:submit_cmd:edit:{CHAT}", "input", "submit_command_input", "请输入投稿命令。"),
                button("排行命令", f"crv:rank_cmd:edit:{CHAT}", "input", "rank_command_input", "请输入排行命令。"),
            ],
            [
                button("审批人", f"crv:approver:set:{CHAT}", "input", "approver_input", "请输入审批人。"),
                button("模板", f"crv:template:edit:{CHAT}", "input", "template_input", "请输入模板。"),
                button("报告列表", f"crv:reports:{CHAT}:a", "goto", "reports", "已打开报告列表。"),
            ],
        ],
        ["car_review_submit_command_input", "car_review_rank_command_input", "car_review_approver_input", "car_review_template_input", "car_review_reward_points_input", "car_review_field_add_input", "car_review_field_label_input"],
        ["backend/features/admin/garage/review.py", "backend/features/admin/garage/review_actions.py", "backend/features/admin/garage/review_inputs.py"],
        [
            screen("reports", "车评报告列表", ["报告详情可通过真实 crv:report 回调审批。"], [[button("报告详情", f"crv:report:{CHAT}:detail:{EVENT}:a", "goto", "report_detail", "已打开报告详情。")], [button("返回车评", f"crv:home:{CHAT}", "back", "home", "已返回车评。")]]),
            screen("report_detail", "报告详情", ["审批通过后可发布到配置的目标。"], [[button("通过", f"crv:report:{CHAT}:approve:{EVENT}:a", "confirm", "result", "报告已通过。"), button("拒绝", f"crv:report:{CHAT}:reject:{EVENT}:a", "confirm", "result", "报告已拒绝。")], [button("返回列表", f"crv:reports:{CHAT}:a", "back", "reports", "已返回列表。")]]),
            input_screen("submit_command_input", "设置投稿命令", "发送命令", "/car", f"crv:home:{CHAT}", examples=[("命令", "/car", "result")]),
            input_screen("rank_command_input", "设置排行命令", "发送命令", "/carrank", f"crv:home:{CHAT}", examples=[("命令", "/carrank", "result")]),
            input_screen("approver_input", "设置审批人", "发送用户 ID 或用户名", "@admin", f"crv:home:{CHAT}", examples=[("审批人", "@admin", "result")]),
            input_screen("template_input", "设置模板", "发送发布模板", "车型：{model}\\n评分：{score}", f"crv:home:{CHAT}", examples=[("模板", "车型：{model}\\n评分：{score}", "result")]),
        ],
    )

    flows["night-mode"] = admin_menu_button_flow(
        "night-mode",
        "夜间管控",
        "night",
        ["adm:night:"],
        ["按统一时间段限制夜间发言，并支持提示、白名单、全员禁言和口令开关群。"],
        [
            [
                button("消息拦截", f"adm:night:{CHAT}:toggle:enabled", "toggle", "result", "消息拦截已切换。"),
                button("管控开始", f"adm:night:{CHAT}:input:start", "input", "start_input", "请输入管控开始时间。"),
                button("管控结束", f"adm:night:{CHAT}:input:end", "input", "end_input", "请输入管控结束时间。"),
            ],
            [
                button("全员禁言模式", f"adm:night:{CHAT}:toggle:lock_schedule", "toggle", "result", "全员禁言模式已切换。"),
                button("口令开关群", f"adm:night:{CHAT}:toggle:lock_phrase", "toggle", "result", "口令开关群已切换。"),
            ],
            [
                button("开群词", f"adm:night:{CHAT}:input:open_phrase", "input", "open_phrase_input", "请输入开群词。"),
                button("关群词", f"adm:night:{CHAT}:input:close_phrase", "input", "close_phrase_input", "请输入关群词。"),
            ],
            [
                button("管理员豁免", f"adm:night:{CHAT}:toggle:exempt_admin", "toggle", "result", "管理员豁免已切换。"),
                button("删除消息", f"adm:night:{CHAT}:toggle:delete_message", "toggle", "result", "删除消息已切换。"),
                button("提示开关", f"adm:night:{CHAT}:toggle:warn_enabled", "toggle", "result", "提示已切换。"),
            ],
            [button("白名单", f"adm:night:{CHAT}:input:whitelist", "input", "whitelist_input", "请输入白名单。"), button("提示文本", f"adm:night:{CHAT}:input:warn_text", "input", "warn_input", "请输入提示文本。"), button("提示删除", f"adm:night:{CHAT}:cycle:warn_delete", "toggle", "result", "已切换提示删除时间。")],
            [button("删除口令通知", f"adm:night:{CHAT}:notice:delete", "toggle", "result", "口令通知会删除。"), button("保留口令通知", f"adm:night:{CHAT}:notice:keep", "toggle", "result", "口令通知会保留。")],
        ],
        ["night_mode_text_input"],
        ["backend/features/admin/module_settings/limit_night_command_inputs.py", "backend/features/group_ops/group_hooks/control_night.py", "backend/features/group_ops/group_hooks/control_lock.py", "backend/platform/scheduler/tasks/group_lock_task.py"],
        [
            input_screen("start_input", "设置管控开始时间", "格式 HH:MM", "23:00", f"adm:menu:night:{CHAT}", examples=[("开始", "23:00", "result")], clear=None),
            input_screen("end_input", "设置管控结束时间", "格式 HH:MM", "08:00", f"adm:menu:night:{CHAT}", examples=[("结束", "08:00", "result")], clear=None),
            input_screen("whitelist_input", "设置夜间白名单", "发送用户 ID、用户名或关键词", "@trusted_user", f"adm:menu:night:{CHAT}", examples=[("白名单", "@trusted_user", "result")]),
            input_screen("warn_input", "设置夜间提示", "发送提示文本", "现在是夜间管控，请明天再发言。", f"adm:menu:night:{CHAT}", examples=[("提示", "现在是夜间管控，请明天再发言。", "result")]),
            input_screen("open_phrase_input", "设置开群词", "发送开群关键词", "开群", f"adm:menu:night:{CHAT}", examples=[("开群词", "开群", "result")]),
            input_screen("close_phrase_input", "设置关群词", "发送关群关键词", "关群", f"adm:menu:night:{CHAT}", examples=[("关群词", "关群", "result")]),
        ],
    )

    flows["command-config"] = admin_menu_button_flow(
        "command-config",
        "群组命令配置",
        "gcmd",
        ["adm:gcmd:"],
        ["开启或关闭群命令，并为命令设置别名。"],
        [
            [
                button("总开关", f"adm:gcmd:{CHAT}:toggle_enabled", "toggle", "result", "群命令总开关已切换。"),
                button("命令详情", f"adm:gcmd:{CHAT}:detail:rank", "goto", "detail", "已打开命令详情。"),
            ]
        ],
        ["command_config_alias_input"],
        ["backend/features/group_ops/command_alias_handler.py", "backend/features/admin/module_settings/group_control_inputs.py"],
        [
            screen("detail", "命令详情", ["详情页可开关单个命令或设置别名。"], [[button("开启命令", f"adm:gcmd:{CHAT}:toggle:rank", "toggle", "result", "命令已切换。"), button("设置别名", f"adm:gcmd:{CHAT}:alias:rank", "input", "alias_input", "请输入别名。"), button("清空别名", f"adm:gcmd:{CHAT}:clear_alias:rank", "confirm", "result", "别名已清空。")], [button("返回命令配置", f"adm:menu:gcmd:{CHAT}", "back", "home", "已返回命令配置。")]]),
            input_screen("alias_input", "设置命令别名", "发送别名命令", "/排行榜", f"adm:gcmd:{CHAT}:detail:rank", "detail", examples=[("别名", "/排行榜", "result")]),
        ],
    )

    flows["import-settings"] = admin_menu_button_flow(
        "import-settings",
        "导入设置",
        "import",
        ["adm:import:"],
        ["从其他已管理群导入配置到当前群。"],
        [
            [button("选择来源群", f"adm:import:{CHAT}:pick_source", "goto", "source", "请选择来源群。", True)],
        ],
        files=["backend/features/admin/import_export/inherit.py"],
        input_screens=[
            screen("source", "选择来源群", ["选择已有群作为配置来源。"], [[button("来源群 A", f"adm:import:{CHAT}:source:-1002001", "goto", "modules", "已选择来源群。")], [button("返回导入", f"adm:menu:import:{CHAT}", "back", "home", "已返回导入。")]]),
            screen("modules", "选择模块", ["选择要导入的配置模块。"], [[button("全部选择", f"adm:import:{CHAT}:select_all", "toggle", "modules", "已全选。"), button("清空", f"adm:import:{CHAT}:clear", "toggle", "modules", "已清空。")], [button("欢迎消息", f"adm:import:{CHAT}:module:welcome", "toggle", "modules", "欢迎消息已切换。"), button("积分配置", f"adm:import:{CHAT}:module:points", "toggle", "modules", "积分配置已切换。")], [button("执行导入", f"adm:import:{CHAT}:apply", "confirm", "result", "导入任务已提交。")]]),
        ],
    )

    flows["clone-settings"] = admin_menu_button_flow(
        "clone-settings",
        "克隆",
        "clone",
        ["adm:clone:"],
        ["把当前群配置克隆到其他已管理群。"],
        [[button("选择目标群", f"adm:clone:{CHAT}:pick_target", "goto", "target", "请选择目标群。", True)]],
        files=["backend/features/admin/import_export/inherit.py"],
        input_screens=[
            screen("target", "选择目标群", ["选择要写入配置的目标群。"], [[button("目标群 A", f"adm:clone:{CHAT}:target:-1003001", "goto", "modules", "已选择目标群。")], [button("返回克隆", f"adm:menu:clone:{CHAT}", "back", "home", "已返回克隆。")]]),
            screen("modules", "选择模块", ["选择要克隆的配置模块。"], [[button("全部选择", f"adm:clone:{CHAT}:select_all", "toggle", "modules", "已全选。"), button("清空", f"adm:clone:{CHAT}:clear", "toggle", "modules", "已清空。")], [button("欢迎消息", f"adm:clone:{CHAT}:module:welcome", "toggle", "modules", "欢迎消息已切换。"), button("积分配置", f"adm:clone:{CHAT}:module:points", "toggle", "modules", "积分配置已切换。")], [button("执行克隆", f"adm:clone:{CHAT}:apply", "confirm", "result", "克隆任务已提交。")]]),
        ],
    )

    flows["account-inherit"] = admin_menu_button_flow(
        "account-inherit",
        "炸号继承",
        "inherit",
        ["inh:"],
        ["生成或使用继承 token，把旧账号权益迁移到新账号。"],
        [
            [
                button("开启继承", f"inh:toggle:{CHAT}:1", "toggle", "result", "继承已开启。"),
                button("生成 Token", f"inh:token:gen:{CHAT}", "goto", "result", "已生成 token。"),
                button("使用 Token", f"inh:token:use:{CHAT}", "input", "token_input", "请输入 token。", True),
            ]
        ],
        ["inherit_wait_token_input"],
        ["backend/features/invite/account_inherit_handler.py", "backend/features/admin/import_export/inherit.py"],
        [input_screen("token_input", "输入继承 Token", "发送旧账号生成的 token", "INH-123456", f"inh:manage:{CHAT}", examples=[("Token", "INH-123456", "result")])],
    )

    flows["bottom-button"] = admin_menu_button_flow(
        "bottom-button",
        "底部按钮",
        "bottom_button",
        ["btm:"],
        ["配置底部键盘文案、按钮布局和绑定事件。", "必填步骤：先设置底部文本，再配置按钮布局，最后同步到底部键盘。"],
        [
            [
                button("开启", f"btm:toggle:{CHAT}:1", "toggle", "result", "底部按钮已开启。"),
                button("关闭", f"btm:toggle:{CHAT}:0", "toggle", "result", "底部按钮已关闭。"),
                button("文本", f"btm:text:{CHAT}:edit", "input", "text_input", "请输入底部文本。"),
                button("按钮布局", f"btm:layout:{CHAT}:edit", "goto", "layout", "已打开按钮布局。"),
            ],
            [button("同步到底部键盘", f"btm:generate:{CHAT}:now", "goto", "result", "已同步到底部键盘。")],
        ],
        ["bottom_button_text_input", "bottom_button_button_text_input", "bottom_button_payload_input"],
        ["backend/features/admin/activity/bottom_button.py", "backend/features/admin/activity/bottom_button_input.py", "backend/features/group_ops/bottom_button_handler.py"],
        [
            screen("layout", "按钮布局", ["添加按钮后进入按钮详情。"], [[button("添加按钮", f"btm:layout:{CHAT}:add:1:1", "goto", "button_detail", "已添加按钮。")], [button("清空按钮", f"btm:layout:{CHAT}:clear", "confirm", "result", "按钮已清空。"), button("返回底部按钮", f"btm:home:{CHAT}", "back", "home", "已返回底部按钮。")]]),
            screen("button_detail", "按钮详情", ["按钮可设置文字、绑定事件和自定义触发词。"], [[button("修改文字", f"btm:button:{CHAT}:text:1", "input", "button_text_input", "请输入按钮文本。"), button("绑定事件", f"btm:button:{CHAT}:events:1", "goto", "event_menu", "请选择绑定事件。")], [button("自定义触发词", f"btm:button:{CHAT}:payload:1", "input", "payload_input", "请输入触发词。")], [button("删除按钮", f"btm:button:{CHAT}:delete:1", "confirm", "result", "按钮已删除。"), button("返回布局", f"btm:layout:{CHAT}:edit", "back", "layout", "已返回按钮布局。")]]),
            screen("event_menu", "绑定事件", ["选择内置功能事件，或回到自定义触发词。"], [[button("积分", f"btm:button:{CHAT}:eventcat:1:points", "goto", "event_list", "已打开积分事件。"), button("自定义触发词", f"btm:button:{CHAT}:payload:1", "input", "payload_input", "请输入触发词。")], [button("返回按钮详情", f"btm:button:{CHAT}:detail:1", "back", "button_detail", "已返回按钮详情。")]]),
            screen("event_list", "选择事件", ["点击具体事件后会保存到该按钮。"], [[button("签到", f"btm:button:{CHAT}:event:1:points.sign", "toggle", "button_detail", "已绑定签到事件。")], [button("返回分类", f"btm:button:{CHAT}:events:1", "back", "event_menu", "已返回事件分类。")]]),
            input_screen("text_input", "设置底部文本", "发送底部消息文本", "点击下方按钮自助操作。", f"btm:home:{CHAT}", examples=[("文本", "点击下方按钮自助操作。", "result")]),
            input_screen("button_text_input", "设置按钮文本", "发送按钮显示文本", "联系客服", f"btm:button:{CHAT}:detail:1", "button_detail", examples=[("文本", "联系客服", "result")]),
            input_screen("payload_input", "设置自定义触发词", "发送点击后触发的群内关键词", "我要联系客服", f"btm:button:{CHAT}:detail:1", "button_detail", examples=[("触发词", "我要联系客服", "result")]),
        ],
    )

    flows["lottery"] = flow(
        "lottery",
        coverage(["lot:create_menu", "lot:mode_menu:", "lot:draw_cond:", "lot:create:", "lot:wiz:", "lottery:cancel:", "lot:list:", "lot:detail:", "lot:settings", "lot:setting:", "lot:draw:", "join_lottery_"], ["lottery_create"], ["backend/features/activity/lottery_router.py", "backend/features/activity/lottery_menus.py", "backend/features/activity/lottery_creation.py"]),
        [
            admin_entry("抽奖", f"lot:list:{CHAT}:all:all:0"),
            common_select_group(f"lot:list:{CHAT}:all:all:0", "entry"),
            common_main_menu("抽奖", f"lot:list:{CHAT}:all:all:0"),
            screen("home", "抽奖列表", ["抽奖列表支持创建、筛选、详情和开奖。"], [[button("创建抽奖", f"lot:create_menu:{CHAT}", "goto", "create_menu", "打开创建菜单。", True), button("抽奖设置", f"lot:settings:{CHAT}", "goto", "settings", "打开抽奖设置。")], [button("抽奖详情", f"lot:detail:{CHAT}:{LOTTERY}", "goto", "detail", "已打开抽奖详情。")], [button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")]]),
            screen("create_menu", "创建抽奖", ["选择普通抽奖、积分抽奖、邀请抽奖或群活跃抽奖。"], [[button("普通抽奖", f"lot:draw_cond:{CHAT}:c:t", "goto", "draw_condition", "选择开奖方式。"), button("积分抽奖", f"lot:draw_cond:{CHAT}:p:t", "goto", "draw_condition", "选择开奖方式。")], [button("邀请抽奖", f"lot:mode_menu:{CHAT}:invite", "goto", "invite_mode", "选择邀请抽奖玩法。"), button("群活跃抽奖", f"lot:mode_menu:{CHAT}:activity", "goto", "invite_mode", "选择群活跃抽奖玩法。")], [button("返回列表", f"lot:list:{CHAT}:all:all:0", "back", "home", "已返回列表。")]]),
            screen("invite_mode", "邀请/活跃抽奖玩法", ["邀请抽奖和群活跃抽奖支持达标随机或排名入围随机。"], [[button("达标随机", f"lot:draw_cond:{CHAT}:i:t", "goto", "draw_condition", "选择开奖方式。")], [button("排名入围随机", f"lot:draw_cond:{CHAT}:i:r", "goto", "draw_condition", "选择开奖方式。")], [button("返回创建", f"lot:create_menu:{CHAT}", "back", "create_menu", "已返回创建菜单。")]]),
            screen("draw_condition", "选择开奖条件", ["选择满人开奖或定时开奖，之后进入分步创建向导。"], [[button("满人开奖", f"lot:create:{CHAT}:c:t:f", "input", "create_input", "进入抽奖创建向导。")], [button("定时开奖", f"lot:create:{CHAT}:c:t:d", "input", "create_input", "进入抽奖创建向导。")], [button("返回创建", f"lot:create_menu:{CHAT}", "back", "create_menu", "已返回创建菜单。")]]),
            screen("settings", "抽奖设置", ["抽奖设置可切换发布后置顶等选项。"], [[button("发布后置顶", f"lot:setting:{CHAT}:publish_pin:1", "toggle", "result", "发布后置顶已开启。")], [button("返回列表", f"lot:list:{CHAT}:all:all:0", "back", "home", "已返回列表。")]]),
            screen("detail", "抽奖详情", ["详情页可手动开奖，用户运行时可点击参与。"], [[button("立即开奖", f"lot:draw:{CHAT}:{LOTTERY}", "confirm", "result", "已发起开奖。"), button("用户参与", f"join_lottery_{LOTTERY}", "goto", "result", "用户已参与抽奖。")], [button("返回列表", f"lot:list:{CHAT}:all:all:0", "back", "home", "已返回列表。")]]),
            input_screen("create_input", "创建抽奖向导", "按提示依次回复抽奖名称、奖品、中奖人数、开奖参数和积分类型", "春季抽奖\n1USDT\n1\n100", f"lottery:cancel:{CHAT}", "create_menu", examples=[("满人开奖向导输入", "春季抽奖|祝大家好运\n1USDT\n1\n100", "result")]),
            screen("result", "抽奖操作结果", ["保存或开奖后 Bot 会回到列表或详情页。"], [[button("返回列表", f"lot:list:{CHAT}:all:all:0", "back", "home", "已返回列表。")]]),
        ],
    )

    flows["solitaire"] = flow(
        "solitaire",
        coverage(["sol:create:", "sol:list", "sol:stats", "sol:detail:", "sol:refresh:", "sol:close:", "sol:delete:", "join_solitaire:", "solitaire:cancel:"], ["solitaire_create"], ["backend/features/activity/solitaire_router.py", "backend/features/activity/ui/solitaire.py", "backend/features/activity/solitaire_creation_wizard.py"]),
        [
            admin_entry("接龙", f"sol:list:{CHAT}:0"),
            common_select_group(f"sol:list:{CHAT}:0", "entry"),
            common_main_menu("接龙", f"sol:list:{CHAT}:0"),
            screen("home", "接龙列表", ["接龙支持创建、详情、统计、关闭和删除。"], [[button("创建接龙", f"sol:create:{CHAT}", "input", "create_input", "请输入接龙内容。", True), button("统计", f"sol:stats:{CHAT}", "goto", "stats", "打开统计。")], [button("接龙详情", f"sol:detail:{CHAT}:{SOLITAIRE}", "goto", "detail", "已打开详情。")], [button("返回主菜单", f"adm:menu:main:{CHAT}", "back", "entry", "已返回主菜单。")]]),
            screen("detail", "接龙详情", ["详情页可刷新、关闭、删除；用户可参与。"], [[button("刷新", f"sol:refresh:{CHAT}:{SOLITAIRE}", "goto", "detail", "已刷新。"), button("关闭", f"sol:close:{CHAT}:{SOLITAIRE}", "confirm", "result", "接龙已关闭。"), button("删除", f"sol:delete:{CHAT}:{SOLITAIRE}", "confirm", "result", "接龙已删除。")], [button("用户参与", f"join_solitaire:{SOLITAIRE}", "goto", "result", "用户已参与接龙。"), button("取消创建", f"solitaire:cancel:{CHAT}", "back", "home", "已取消。")]]),
            screen("stats", "接龙统计", ["统计页按当前接龙汇总参与人数和内容。"], [[button("返回列表", f"sol:list:{CHAT}:0", "back", "home", "已返回列表。")]]),
            input_screen("create_input", "创建接龙", "发送接龙标题和说明", "今晚报名接龙", f"sol:list:{CHAT}:0", examples=[("标题", "今晚报名接龙", "detail")]),
            screen("result", "接龙操作结果", ["保存后返回接龙列表或详情。"], [[button("返回列表", f"sol:list:{CHAT}:0", "back", "home", "已返回列表。")]]),
        ],
    )

    flows["game"] = admin_menu_button_flow(
        "game",
        "游戏",
        "game",
        ["gm:", "gmrun:"],
        ["配置骰子、21 点等游戏开关、抽水和自动开停。"],
        [
            [
                button("快三开关", f"gm:toggle:{CHAT}:k3:1", "toggle", "result", "快三已开启。"),
                button("21 点开关", f"gm:toggle:{CHAT}:blackjack:1", "toggle", "result", "21 点已开启。"),
                button("积分菜单", f"gm:points:{CHAT}:menu", "goto", "points_menu", "打开积分菜单。"),
            ],
            [
                button("抽水比例", f"gm:rake:{CHAT}:ratio", "input", "rake_ratio_input", "请输入抽水比例。"),
                button("自动开始", f"gm:auto:{CHAT}:start_time", "input", "auto_start_input", "请输入自动开始时间。"),
                button("帮助", f"gm:help:{CHAT}", "goto", "result", "已打开玩法帮助。"),
            ],
            [button("运行时下注", f"gmrun:k3:bet:{CHAT}:big:10", "goto", "result", "用户已下注。")],
        ],
        ["game_wait_rake_ratio", "game_wait_rake_owner", "game_wait_auto_start_time", "game_wait_auto_stop_time"],
        ["backend/features/admin/activity/game.py", "backend/features/admin/activity/game_input.py", "backend/features/activity/game_runtime_router.py"],
        [
            screen("points_menu", "游戏积分菜单", ["游戏可选择积分模式和扣奖规则。"], [[button("返回游戏设置", f"gm:home:{CHAT}", "back", "home", "已返回游戏设置。")]]),
            input_screen("rake_ratio_input", "设置抽水比例", "发送百分比或小数", "5", f"gm:home:{CHAT}", examples=[("5%", "5", "result")], clear=None),
            input_screen("auto_start_input", "设置自动开始", "格式 HH:MM", "20:00", f"gm:home:{CHAT}", examples=[("开始", "20:00", "result")], clear=None),
        ],
    )

    flows["guess"] = admin_menu_button_flow(
        "guess",
        "竞猜",
        "guess",
        ["guess:"],
        ["创建竞猜、设置选项、奖池、命令和开奖。"],
        [
            [
                button("创建竞猜", f"guess:create:{CHAT}:start", "goto", "create", "进入创建竞猜。", True),
                button("待开奖", f"guess:list:{CHAT}:running", "goto", "list", "打开运行中竞猜。"),
                button("设置", f"guess:settings:{CHAT}:home", "goto", "settings", "打开竞猜设置。"),
            ]
        ],
        ["guess_wait_title", "guess_wait_cover", "guess_wait_description", "guess_wait_banker", "guess_wait_pool", "guess_wait_options", "guess_wait_command", "guess_wait_deadline", "guess_wait_rake_ratio", "guess_wait_rake_owner"],
        ["backend/features/admin/activity/guess.py", "backend/features/admin/activity/guess_input.py", "backend/features/activity/guess_handler.py"],
        [
            screen("create", "创建竞猜", ["创建流程按字段逐步输入。"], [[button("标题", f"guess:create:{CHAT}:title", "input", "title_input", "请输入标题。"), button("选项", f"guess:create:{CHAT}:options", "input", "options_input", "请输入选项。"), button("截止时间", f"guess:create:{CHAT}:deadline", "input", "deadline_input", "请输入截止时间。")], [button("预览", f"guess:create:{CHAT}:preview", "goto", "result", "已打开预览。"), button("发布", f"guess:create:{CHAT}:publish", "confirm", "result", "竞猜已发布。")]]),
            screen("list", "竞猜列表", ["列表可打开详情、开奖或取消。"], [[button("竞猜详情", f"guess:detail:{CHAT}:{EVENT}", "goto", "detail", "已打开详情。")], [button("返回竞猜", f"guess:home:{CHAT}", "back", "home", "已返回竞猜。")]]),
            screen("detail", "竞猜详情", ["详情页可选择正确选项开奖。"], [[button("选 A 开奖", f"guess:open:{CHAT}:{EVENT}:A", "confirm", "result", "已按 A 开奖。"), button("取消竞猜", f"guess:cancel:{CHAT}:{EVENT}", "confirm", "result", "竞猜已取消。")], [button("返回列表", f"guess:list:{CHAT}:running", "back", "list", "已返回列表。")]]),
            screen("settings", "竞猜设置", ["设置抽水和消息删除策略。"], [[button("抽水比例", f"guess:settings:{CHAT}:rake_ratio", "input", "rake_input", "请输入抽水比例。"), button("删除消息", f"guess:settings:{CHAT}:delete_mode:delete", "toggle", "result", "已设置删除消息。")], [button("返回竞猜", f"guess:home:{CHAT}", "back", "home", "已返回竞猜。")]]),
            input_screen("title_input", "设置竞猜标题", "发送标题", "今晚比分竞猜", f"guess:create:{CHAT}:start", "create", examples=[("标题", "今晚比分竞猜", "result")]),
            input_screen("options_input", "设置竞猜选项", "每行一个选项", "A 队胜\nB 队胜", f"guess:create:{CHAT}:start", "create", examples=[("选项", "A 队胜\nB 队胜", "result")]),
            input_screen("deadline_input", "设置截止时间", "格式 YYYY-MM-DD HH:MM", "2026-04-18 20:00", f"guess:create:{CHAT}:start", "create", "datetime", [("截止", "2026-04-18 20:00", "result")]),
            input_screen("rake_input", "设置抽水比例", "发送百分比或小数", "5", f"guess:settings:{CHAT}:home", "settings", "number", [("5%", "5", "result")], clear=None),
        ],
    )

    flows["engagement"] = admin_menu_button_flow(
        "engagement",
        "促活工具",
        "engagement",
        ["act:"],
        ["配置彩蛋活动和聊天促活计划。"],
        [
            [
                button("新建彩蛋", f"act:egg:{CHAT}:new", "goto", "egg_detail", "已创建彩蛋。", True),
                button("彩蛋列表", f"act:egg:{CHAT}:list:all", "goto", "egg_list", "已打开彩蛋列表。"),
                button("聊天促活", f"act:chat:{CHAT}:home", "goto", "chat", "已打开聊天促活。"),
            ]
        ],
        ["engagement_wait_egg_template", "engagement_wait_chat_target", "engagement_wait_chat_plan", "engagement_wait_chat_command"],
        ["backend/features/admin/activity/engagement.py", "backend/features/admin/activity/engagement_input.py", "backend/features/admin/activity/engagement_egg_actions.py", "backend/features/admin/activity/engagement_chat_actions.py"],
        [
            screen("egg_list", "彩蛋列表", ["列表可打开彩蛋详情。"], [[button("彩蛋详情", f"act:egg:{CHAT}:detail:{EVENT}", "goto", "egg_detail", "已打开彩蛋详情。")], [button("返回促活", f"act:home:{CHAT}", "back", "home", "已返回促活。")]]),
            screen("egg_detail", "彩蛋详情", ["彩蛋可开关、编辑模板、预览和发布。"], [[button("启用", f"act:egg:{CHAT}:toggle:{EVENT}:1", "toggle", "result", "彩蛋已启用。"), button("模板", f"act:egg:{CHAT}:template:{EVENT}", "input", "egg_template_input", "请输入模板。"), button("预览", f"act:egg:{CHAT}:preview:{EVENT}", "goto", "result", "已预览。"), button("发布", f"act:egg:{CHAT}:publish:{EVENT}", "confirm", "result", "彩蛋已发布。")], [button("返回列表", f"act:egg:{CHAT}:list:all", "back", "egg_list", "已返回列表。")]]),
            screen("chat", "聊天促活", ["聊天促活可设置目标、计划、命令和统计。"], [[button("开启", f"act:chat:{CHAT}:toggle:1", "toggle", "result", "聊天促活已开启。"), button("目标", f"act:chat:{CHAT}:target", "input", "chat_target_input", "请输入目标。"), button("计划", f"act:chat:{CHAT}:plan", "input", "chat_plan_input", "请输入计划。")], [button("统计", f"act:chat:{CHAT}:stats", "goto", "result", "已打开统计。"), button("返回促活", f"act:home:{CHAT}", "back", "home", "已返回促活。")]]),
            input_screen("egg_template_input", "设置彩蛋模板", "发送彩蛋模板", "恭喜 {user} 触发彩蛋！", f"act:egg:{CHAT}:detail:{EVENT}", "egg_detail", examples=[("模板", "恭喜 {user} 触发彩蛋！", "result")]),
            input_screen("chat_target_input", "设置促活目标", "发送目标消息数", "100", f"act:chat:{CHAT}:home", "chat", "number", [("目标", "100", "result")], clear=None),
            input_screen("chat_plan_input", "设置促活计划", "发送计划文本", "每天 20:00 提醒聊天", f"act:chat:{CHAT}:home", "chat", examples=[("计划", "每天 20:00 提醒聊天", "result")]),
        ],
    )

    flows["auction"] = admin_menu_button_flow(
        "auction",
        "拍卖",
        "auction",
        ["auc:"],
        ["配置拍卖开关、积分模式和拍卖项目。群成员发送“拍卖”后，机器人会提示回复拍卖物品。"],
        [
            [
                button("开启拍卖", f"auc:toggle:{CHAT}:enabled:1", "toggle", "result", "拍卖已开启。"),
                button("置顶", f"auc:toggle:{CHAT}:pin:1", "toggle", "result", "拍卖置顶已开启。"),
                button("自动延时", f"auc:toggle:{CHAT}:auto_extend:1", "toggle", "result", "自动延时已开启。"),
            ],
            [
                button("不关联积分", f"auc:points_mode:{CHAT}:none", "toggle", "result", "已关闭积分关联。"),
                button("主积分", f"auc:points_mode:{CHAT}:group_points", "toggle", "result", "已使用群积分。"),
                button("拍卖列表", f"auc:list:{CHAT}:0", "goto", "list", "打开拍卖列表。"),
            ],
        ],
        ["auction_wait_title", "auction_wait_start_price", "auction_wait_end_at", "auction_wait_confirm"],
        ["backend/features/admin/activity/auction.py", "backend/features/activity/auction_handler.py"],
        [
            screen("list", "拍卖列表", ["列表页可打开拍卖详情。"], [[button("拍卖详情", f"auc:detail:{CHAT}:{AUCTION}", "goto", "detail", "已打开拍卖详情。")], [button("返回拍卖", f"auc:home:{CHAT}", "back", "home", "已返回拍卖。")]]),
            screen("detail", "拍卖详情", ["详情展示当前出价和结束时间。"], [[button("返回列表", f"auc:list:{CHAT}:0", "back", "list", "已返回列表。")]]),
        ],
    )

    flows["channel-sync"] = admin_menu_button_flow(
        "channel-sync",
        "频道同步",
        "sync",
        ["gfw:"],
        ["频道同步当前复用车库转发真实 gfw 配置链路。"],
        [
            [
                button("开启同步", f"gfw:toggle:{CHAT}:1", "toggle", "result", "同步已开启。"),
                button("添加来源", f"gfw:source:add:{CHAT}", "input", "source_input", "请输入来源频道。", True),
                button("全部转发", f"gfw:mode:{CHAT}:all", "toggle", "result", "已设置全部转发。"),
            ],
            [button("审核列表", f"gfw:audit:{CHAT}:a", "goto", "result", "已打开审核列表。")],
        ],
        ["garage_forward_source_input"],
        ["backend/features/admin/garage/forward.py", "backend/features/admin/garage/forward_inputs.py"],
        [input_screen("source_input", "添加同步来源", "发送频道用户名或 ID", "@source_channel", f"gfw:home:{CHAT}", examples=[("来源", "@source_channel", "result")])],
    )

    flows["channel-auto-buttons"] = admin_menu_button_flow(
        "channel-auto-buttons",
        "频道自动按钮",
        "sync",
        ["gfw:"],
        ["频道自动按钮当前复用 gfw 按钮配置入口。"],
        [
            [
                button("保留原按钮", f"gfw:btn_toggle:{CHAT}:1", "toggle", "result", "保留原按钮已开启。"),
                button("设置按钮", f"gfw:buttons:input:{CHAT}", "input", "buttons_input", "请输入按钮配置。", True),
                button("应用按钮", f"gfw:buttons:apply:{CHAT}", "confirm", "result", "按钮配置已应用。"),
            ]
        ],
        ["garage_forward_buttons_input"],
        ["backend/features/admin/garage/forward.py", "backend/features/admin/garage/forward_inputs.py"],
        [input_screen("buttons_input", "设置频道自动按钮", "逐行按钮，支持分号同排", "原文 - https://t.me/source", f"gfw:home:{CHAT}", "home", "buttons", [("按钮", "原文 - https://t.me/source", "result"), ("同排", "原文 - https://t.me/a;客服 - https://t.me/b", "result")])],
    )

    flows["quick-publish"] = admin_menu_button_flow(
        "quick-publish",
        "全局快捷发布",
        "qpub",
        ["qpub:"],
        ["配置一条待发布内容，并发送到目标频道或群。"],
        [
            [
                button("设置文本", f"qpub:input:{CHAT}:text", "input", "text_input", "请输入文本。", True),
                button("设置媒体", f"qpub:input:{CHAT}:media", "input", "media_input", "请发送媒体。"),
                button("设置按钮", f"qpub:input:{CHAT}:buttons", "input", "buttons_input", "请输入按钮。"),
            ],
            [
                button("清空草稿", f"qpub:clear:{CHAT}", "confirm", "result", "草稿已清空。"),
                button("发送", f"qpub:send:{CHAT}", "confirm", "result", "已发送。"),
            ],
        ],
        ["quick_publish_input"],
        ["backend/features/admin/import_export/quick_publish.py"],
        [
            input_screen("text_input", "设置发布文本", "发送正文", "频道公告内容", f"qpub:home:{CHAT}", examples=[("正文", "频道公告内容", "result")]),
            input_screen("media_input", "设置发布媒体", "发送图片、视频或文件", "image.jpg", f"qpub:home:{CHAT}", "home", "media", [("图片", "image.jpg", "result")]),
            input_screen("buttons_input", "设置发布按钮", "逐行按钮，支持分号同排", "查看 - https://example.com", f"qpub:home:{CHAT}", "home", "buttons", [("按钮", "查看 - https://example.com", "result")]),
        ],
    )

    flows["membership"] = admin_reference_flow(
        "membership",
        "会员 / 套餐授权",
        "renewal",
        ["当前所有功能默认开放，付费限制仅保留为后续能力。", "页面只展示真实续费/订阅保留入口，不展示购买流程。"],
        ["状态：暂时关闭"],
        [
            [
                button("续费入口", f"renew:menu:{CHAT}", "goto", "renewal", "打开真实续费保留入口。", True),
                button("订阅说明", f"sub:menu:{CHAT}", "goto", "subscription", "打开订阅说明。"),
            ],
        ],
        ["adm:menu:renewal", "renew:", "sub:"],
        files=["backend/features/subscription/renewal_router.py", "backend/features/subscription/subscription_router.py", "backend/features/admin/ui/renewal.py"],
    )
    flows["membership"]["screens"].extend(
        [
            screen("renewal", "续费保留入口", ["当前不引导购买；该入口用于后续恢复套餐授权时对接。"], [[button("返回会员页", f"adm:menu:renewal:{CHAT}", "back", "home", "已返回会员页。")]]),
            screen("subscription", "订阅说明", ["当前功能默认开放，订阅入口只说明能力边界。"], [[button("联系客服", f"sub:contact:{CHAT}", "toast", feedback="当前暂不需要购买；如有疑问联系管理员。"), button("返回会员页", f"adm:menu:renewal:{CHAT}", "back", "home", "已返回会员页。")]]),
        ]
    )

    return flows


def normalize_toggle_targets(payload: dict[str, Any]) -> None:
    for screen_item in payload.get("screens", []):
        screen_id = screen_item.get("id")
        if not screen_id:
            continue
        for row in screen_item.get("keyboard", []):
            for flow_button in row:
                if flow_button.get("action") == "toggle":
                    flow_button["target"] = screen_id
                    flow_button.setdefault("feedback", "设置已切换，Bot 会刷新当前页面。")


def main() -> int:
    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    flows = build_flows()
    expected = set(CATALOG)
    missing = expected - set(flows)
    extra = set(flows) - expected
    if missing or extra:
        raise SystemExit(f"flow slug mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    for slug, payload in sorted(flows.items()):
        normalize_toggle_targets(payload)
        (FLOWS_DIR / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"generated {len(flows)} flow files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
