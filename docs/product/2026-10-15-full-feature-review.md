# TgGroupRobot 竞品全功能复核清单

> 日期：2026-10-15（Asia/Shanghai）
> 范围：本会话实际可见的保安机器人管理功能，以及本地 master / feecab8 的 38 个稳定功能入口
> 性质：只读产品与代码复核；不是全量业务验收通过证明
> 需求基线：[竞品差距 PRD](./2026-10-15-competitor-gap-prd.md)

> 后续状态：本文保留代码修改前的只读审计事实。用户随后授权本地实现；变化与未完成项见[独立实施记录](./2026-10-15-implementation-and-own-feature-audit.md)，不将下文历史差距视为全部已修复。

## 1. 复核结论与计数口径

竞品当前群管理首页共 **29 个业务入口，另有 1 个切换群入口**。下表逐项登记，不把子页数当作功能数。其中 28 项读到了管理页面，车库转发只读到频道后台指引。我方目录共 **38 个稳定功能 ID，分为 6 类**；均已核对菜单处理器，并按业务族追查页面、服务或运行时消费者。此处的覆盖表示目录和本次实际进入的安全只读页面已对账，不表示所有下级页面、每条配置组合、历史记录、权限角色和异常场景均已检查或执行通过。

这次重新检查发现，原稿仅有 CG00—CG10 不足以覆盖差距：需要追加积分流转与币种、等级标签及零门槛、关群权限与通知、联盟处罚类型、活动参与治理、入群筛选例外、签到与每日激励，以及游戏范围决策。老师搜索补入批量/定时打卡的产品决策；车评补清模板、按钮、临时名单的实际语义；广告补到期私聊提醒 CG02-B。PRD 现有 **19 组需求、74 条后续验收标准**。

本轮没有向群或频道发送测试消息，没有提交搜索词、坐标、报告、兑换、出价或下注，没有修改应用代码、数据库、开关、权限或部署。私聊操作限于进入既有管理入口、读取页面、返回及客户端刷新；不把这些操作称为业务验收。没有逐份打开报告、订单和人员明细，文档只保留字段和规则，省略个人资料及业务正文。

状态使用以下统一口径：**页面已看**表示实际读到页面/说明；**代码已有**表示本地有可追踪实现；**差距已确认**表示可见能力与当前实现存在具体差异；**待核实**表示仍缺规则、权限或运行证据；**未执行**表示受本轮边界限制的业务动作。网页曾显示 Updating，部分回调延迟后返回；不能据此判定竞品业务故障。

## 2. 竞品 29 项逐项对账

竞品入口：[保安机器人](https://t.me/abaoan_bot)，再进入其展示的群专属机器人。以下为本会话 2026-10-15 的界面观察；竞品页面只证明所展示的配置与文案，不证明其执行质量。

| 序号 | 竞品功能 | 实际查看的范围 | 我方对应与结论 | 未执行或仍缺证据 |
|---|---|---|---|---|
| C01 | 轮播广告 | 概览、规则/广告列表、标题搜索提示、启停、起止/上次/下次/顺序、过期清理、到期通知模板说明 | `ads` 已有派发历史和恢复；补列表搜索与结果摘要，CG01/02；到期提醒为 CG02-B | 不发送、不清理、不改规则；未验证搜索结果或实际提醒 |
| C02 | 自动回复 | 列表/既有详情、全等/包含、排序、状态、搜索提示、来源删除、媒体按钮及延删、分页 | `autoreply` 已有对应配置；补管理搜索，CG01 | 不提交关键词、不改规则、不触发群回复 |
| C03 | 定时消息 | 列表/详情、标题搜索提示、起止时间、间隔、上次/下次、媒体按钮/置顶/延删及编号 | `scheduled` 已有 occurrence/历史/恢复；补搜索和摘要，CG01/02 | 不创建、启停或试发，不以展示时间认定送达 |
| C04 | 车库认证 | 认证首页、手动认证列表、限频白名单；自动认证、图标、标签、汇总入口 | `garage_auth` 已有手动、频道绑定自动建记录、池/白名单；补来源管理、图标消费及标签，CG07 | 未执行自动认证、添加/删除、标签变更、汇总发布与限频处罚 |
| C05 | 老师搜索 | 搜索/打卡/附近/删除配置、结果链接布局、代录身份输入页、人工打卡列表、定时打卡设置 | `teacher_search` 已有多字段查询/定位/打卡；补严格筛选、结果分页/按钮、两类清理；批量/定时打卡待决策，CG08 | 未输入身份、搜索词或坐标；未点击名单人员、批量打卡或启动定时；未验证距离与跨日 |
| C06 | 车库转发 | 点击后返回明确说明：须在车库频道发送管理指令后配置 | `sync` 已有来源/目标/映射/可靠执行；竞品后台具体能力仍待核实 | 未向频道发送指令，因此没有进入竞品频道后台；不能标记深度对齐 |
| C07 | 主积分 | 主页面、签到/发言/邀请/转让子页、别名及加减/导出入口；转让佣金/最低佣金，签到文案/延删/人数/排行 | `points` 已有管理员转让；成员自助及佣金 CG11，签到配置 CG18；共同群门槛只有文案 | 未签到、转让、加减、导出或清空；不复制未经验证的反作弊规则 |
| C08 | 自定义积分 | 空列表、管理员加减说明、换汇中心指令说明 | `custom_points` 已有类型/账户/流水；换汇未见对应实现，CG11 | 空表无法查看既有类型详情；未添加类型、配置汇率或兑换 |
| C09 | 积分等级 | 列表、已有等级详情、媒体/@权限、排除老师、全局标签与单级显示标签；存在 0 门槛等级 | `points_level` 已有权限和老师例外；标签、零门槛与最低等级语义需补，CG12 | 不切换权限/标签，不修改门槛，不模拟违规发言 |
| C10 | 拍卖 | 首页：启停、置顶、延时、创建权限、积分关联、匿名 | `auction` 已有创建/出价/结算；创建权限未被现路径校验且 UI 缺选择，匿名未见实现，CG15 | 未发起、出价、结算或改权限；未验证匿名实际显示 |
| C11 | 抽奖 | 首页、活动列表入口、设置页：发布/结果置顶、删除口令、用户名校验 | `lottery` 已有前 3 类设置；主动参与用户名校验需补，CG15 | 未创建活动、参与、开奖；各抽奖类型条件组合未逐条执行 |
| C12 | 游戏 | 首页 6 类玩法、指令、抽水、关联积分说明、定时启停与消息清理 | `game` 当前只见快三、黑杰克；其他 4 类为范围决策，CG17 | 未启动任何玩法、下注、扣分或结算；不能用首页证明玩法正确 |
| C13 | 竞猜 | 首页按待开奖/进行/已开/取消分类，规则设置、关联积分说明、无庄/庄家文案 | `guess` 已有创建、参与、两种结算及抽水；未确认新的必补功能 | 空分类没有业务详情；不创建、下注、开奖；跨群关联仅说明，未实测 |
| C14 | 邀请链接 | 启停、提醒/延删、首次邀请去重说明、中转/直达、统计、清零/导出入口 | `invite` 已有中转/直达、归因/统计/去重；无已证实的新缺口 | 未生成/撤销链接、导出或清零；未实际入群或发积分 |
| C15 | 进群欢迎 | 模板列表、已有配置详情、入群/验证后欢迎、封面/文案/按钮/延删 | `welcome` 已有多模板和两类时机；无已证实的新缺口 | 未修改、预览投递、启停或制造入群事件 |
| C16 | 进群验证 | 根页及验证模式、垃圾拦截、自助审核、批量进群 4 个子页 | `verification` 已有四类路径；入群拦截缺“排除老师”的明确策略，CG16 | 不切验证模式、不申请入群、不触发禁言/踢人/审核 |
| C17 | 促活工具 | 根页、彩蛋空列表、水群激励每日/递增/周期和七日后策略、手气红包设置 | `engagement` 已有彩蛋/递增/周期；红包 CG05，每日模式表达 CG18 | 空彩蛋无详情；未创建/发布、领奖或封/抢红包；奖励/退款未实测 |
| C18 | 垃圾防护 | 根页全部规则、白名单入口、检查顺序和终止规则说明 | `antispam`、`punish` 已有对应规则族；未确认其每项阈值、优先级完全等同 | 未修改规则、添加词、发违规消息、警告/禁言/踢人；各规则详情非穷举 |
| C19 | 关群设置 | 话术/定时、开关群时间、开群权限细项、开群通知模板子页；关群权限/通知入口 | `night` 已有口令/时间；当前只设 can_send_messages，缺双套权限与通知卡片，CG13 | 未点权限选项、触发口令或调度；关群权限/通知镜像子页未逐项操作 |
| C20 | 用户监控 | 改名与用户标记根页、改名模板/延删、标记权限/深链/审核入口 | `renamewatch` 已有改名通知；用户标记缺失，CG04 | 未提交/审核/查询标记，未修改用户资料，未触发改名提醒 |
| C21 | 炸号继承 | 允许开关、旧号保存 Token/新号使用说明 | `inherit` 已有一次性有期令牌、主/自定义积分继承 | 未生成或使用 Token，不证明积分实际迁移通过 |
| C22 | 联盟功能 | 联盟首页、成员列表、禁言/封禁与升级不降级说明、邀请/退出入口 | `alliance` 已有生命周期和联合封禁；池/执行仅封禁，补类型和升级规则，CG14 | 未查看/生成邀请码、入退联盟、删除成员或实施处罚 |
| C23 | 积分商城 | 根页、商品列表/详情字段、订单列表分页入口；无货下架、限购/发放/权重、商品积分类型 | `points_mall` 已有订单确认/取消/退款/通知；当前只扣主积分，商品币种需补，CG11 | 未兑换/发放/退款/复制商品；不逐单读取成员资料；积分类型选择页未提交 |
| C24 | 车评系统 | 根页、自定义项、报告发布类型、报告/上牌模板、报告按钮、评价管理/通过列表/详情、在榜/临时老师 | `car_review` 已有核心链路；CG09 多目标发布缺口；CG10 历史/时间/榜单/模板/按钮/临时身份 | 未提交/审核/撤审/换号/重发/更新；不是全部历史报告逐份审核 |
| C25 | 底部按钮 | 根页、每行最多 4 个布局、重复生成周期 | `bottom_button` 已有四列布局、事件/文本触发和周期生成；不与搜索结果链接混淆 | 未修改布局、立即生成或改周期；未在群内点击验证 |
| C26 | 强制订阅 | 两频道、进群/发言/全部范围、封面/文案/按钮、未订阅处理和提示延删 | `forcesub` 已有绑定、成员检查、诊断与动作；无已确认新缺口 | 未改绑定、订退频道、触发处罚；检查失败语义待后续现场验收 |
| C27 | 删除提示 | 入群、退群、置顶、头像、群名 5 项开关 | `autodel` 已有各服务消息清理 | 未制造系统事件或删除消息，不证明当前机器人权限足够 |
| C28 | 控制权限 | 所有管理/封禁/改信息/加管理/仅群主五种策略 | `control` 已有同类策略与统一鉴权 | 未切权限或使用无权账号；旧按钮/角色变更要后续验证 |
| C29 | 续费入口 | 服务版本、到期、卡密输入说明 | `renewal` 已有底座，目前功能收费限制按本项目策略关闭 | 未购买、输入卡密或恢复收费；商业定价不作为能力缺口 |

切换群为导航入口，不计业务功能。已确认存在；本轮主要在同一管理群对比，未为验证隔离而切换配置或发消息。我方已有选群及稳定群绑定，跨群访问控制仍须角色场景验收。

## 3. 我方 38 项实现范围核对

共同入口证据：[稳定功能目录](../../backend/features/admin/feature_registry.py)、[菜单分发](../../backend/features/admin/core/menu_dispatch.py)、[管理运行时](../../backend/features/admin/runtime.py)。下表补充页面或业务消费者。代码核对没有启动机器人或测试环境；历史验收只引用原日期，不改写为今天重新通过。

| ID | 功能 | 页面/业务证据 | 复核结论与后续覆盖 |
|---|---|---|---|
| `welcome` | 进群欢迎 | [管理](../../backend/features/admin/welcome/controller.py)、[投递](../../backend/features/verification/welcome_delivery.py) | 多模板、时机、媒体按钮已有；实际入群/验证后投递未执行 |
| `verification` | 进群验证 | [页面](../../backend/features/admin/moderation/verification_views.py)、[入群消费](../../backend/features/verification/verification_handler.py) | 挑战、自助审核、筛选/批量已有；老师例外待补 CG16 |
| `newmem` | 新成员限制 | [页面](../../backend/features/admin/moderation/member_menu_views.py)、[消费](../../backend/features/group_ops/group_hooks/control_new_member.py) | 时间及消息类型限制已有；不因竞品没有独立入口而删除 |
| `antispam` | 垃圾防护 | [管理](../../backend/features/admin/ui/antispam_controls.py)、[规则](../../backend/features/moderation/services/garbage_guard_rules.py) | 多规则与白名单已有；完整阈值/动作矩阵未运行 |
| `punish` | 惩罚策略 | [页面](../../backend/features/admin/moderation/config_menus.py)、[动作](../../backend/features/moderation/services/user_action_runtime.py) | 处罚底座已有；各类远端失败/权限不足待业务验收 |
| `autodel` | 删除提示 | [配置](../../backend/features/admin/ui/auto_delete.py)、[群管线](../../backend/features/group_ops/group_hooks/core.py) | 系统事件清理已有；未实际删消息 |
| `night` | 夜间管控 | [页面](../../backend/features/admin/moderation/member_menu_views.py)、[权限消费](../../backend/features/group_ops/group_hooks/control_lock.py) | 口令/定时已有；双权限及通知 CG13 |
| `renamewatch` | 改名监控 | [页面](../../backend/features/admin/moderation/control_menus.py)、[消费](../../backend/features/group_ops/group_hooks/control_rename.py) | 模板/延删已有；标记为新增 CG04 |
| `forcesub` | 强制订阅 | [页面](../../backend/features/admin/moderation/member_menu_views.py)、[消费](../../backend/features/group_ops/group_hooks/control_force_subscribe.py) | 多目标、范围、引导/诊断已有；不以 getChatMember 调用存在认定现场通过 |
| `alliance` | 联盟功能 | [管理](../../backend/features/admin/garage/alliance.py)、[池](../../backend/features/garage/services/alliance_ban.py)、[处罚](../../backend/features/group_ops/group_hooks/moderation.py) | 建立/加入/退出/池已有；类型与升级 CG14 |
| `ads` | 轮播广告 | [页面](../../backend/features/automation/ads_context.py)、[执行](../../backend/features/automation/ad_delivery_executor.py) | 可靠派发已有；CG01/02 只增强查询与摘要 |
| `autoreply` | 自动回复 | [页面](../../backend/features/moderation/auto_reply_views.py)、[管理](../../backend/features/moderation/auto_reply_detail_actions.py) | 匹配与内容配置已有；管理搜索 CG01 |
| `scheduled` | 定时消息 | [列表](../../backend/features/automation/scheduled_message_listing.py)、[执行](../../backend/features/automation/scheduled_delivery_executor.py) | 日志及 occurrence 已有；CG01/02 |
| `sync` | 频道同步 | [管理](../../backend/features/admin/garage/forward.py)、[服务](../../backend/features/garage/services/garage_forward_service.py) | 来源/目标、快照与消息映射已有；竞品频道后台未进入 |
| `bottom_button` | 底部按钮 | [管理](../../backend/features/admin/activity/bottom_button.py)、[生成](../../backend/features/group_ops/services/bottom_button_service.py) | 四列/六行、触发配置/周期已有；禁止本轮立即生成 |
| `qpub` | 快捷发布 | [草稿与发送](../../backend/features/admin/import_export/quick_publish.py) | 文本/媒体/按钮及确认发送路径已有；竞品未见独立入口，不推断独有 |
| `points` | 主积分 | [页面](../../backend/features/admin/points/overview_views.py)、[消息消费](../../backend/features/points/points_message_actions.py)、[管理员转让](../../backend/features/admin/points_config_messages.py) | 签到/发言/邀请/排行/流水及管理员转让已有；成员转让 CG11、签到展示 CG18；无余额改动 |
| `custom_points` | 自定义积分 | [管理](../../backend/features/admin/points/custom_points.py)、[服务](../../backend/features/points/services/points_extended_custom.py) | 多类型/加减/流水已有；换汇及用途扩展 CG11 |
| `points_level` | 积分等级 | [页面](../../backend/features/admin/ui/points_extended_levels.py)、[服务](../../backend/features/points/services/points_extended_levels.py)、[执行](../../backend/features/points/points_message_actions.py) | 媒体限制、排除老师已有；零门槛/标签 CG12 |
| `points_mall` | 积分商城 | [详情](../../backend/features/admin/points/mall_product_pages.py)、[扣款](../../backend/features/points/services/points_mall_products.py)、[订单](../../backend/features/points/services/points_mall_orders.py) | 确认/库存/通知/发放/退款已有；币种 CG11；商品复制入口未见对应，属 P2 效率增强 |
| `invite` | 邀请链接 | [管理](../../backend/features/invite/invite_admin_menu_callbacks.py)、[归因](../../backend/features/invite/services/invite_tracking.py) | 中转/直达、首次去重、统计已有；实际邀请奖励未执行 |
| `inherit` | 账号继承 | [管理](../../backend/features/admin/import_export/inherit.py)、[迁移](../../backend/features/invite/services/account_inherit_service.py) | 一次性令牌和积分迁移已有；不是老师报告换号同一业务 |
| `lottery` | 抽奖 | [设置](../../backend/features/activity/lottery_menus.py)、[参与](../../backend/features/activity/lottery_participation.py) | 多类活动/置顶/删除已有；用户名治理 CG15 |
| `solitaire` | 接龙 | [管理入口](../../backend/features/admin/core/basic_menus.py)、[参与](../../backend/features/activity/solitaire_participation_callbacks.py) | 既有独立业务继续保留；竞品主页未见，不推断竞品无此能力 |
| `auction` | 拍卖 | [页面](../../backend/features/admin/activity/auction.py)、[创建](../../backend/features/activity/auction_handler.py)、[结算](../../backend/features/activity/services/auction_settlement.py) | 核心流程已有；create_permission 未被创建函数检查，CG15 |
| `game` | 游戏 | [页面](../../backend/features/admin/activity/game_presenters.py)、[服务](../../backend/features/activity/services/game_service.py) | 快三/黑杰克、抽水/定时已有；额外玩法待 CG17 决策 |
| `guess` | 竞猜 | [管理](../../backend/features/admin/activity/guess.py)、[结算](../../backend/features/activity/services/guess_service_runtime.py) | 无庄/庄家及抽水已有；不照搬竞品文案认定账务正确 |
| `engagement` | 促活工具 | [彩蛋](../../backend/features/admin/activity/engagement_egg_actions.py)、[激励](../../backend/features/activity/services/engagement_chat.py) | 两类已有；红包 CG05，每日模式/业务日表达 CG18 |
| `garage_auth` | 车库认证 | [页面](../../backend/features/admin/garage/auth_views.py)、[服务](../../backend/features/garage/services/garage_auth_service.py)、[索引绑定](../../backend/features/garage/services/teacher_search_channel_index.py) | 非整体缺失；CG07 补来源与展示消费 |
| `teacher_search` | 老师搜索 | [页面](../../backend/features/admin/garage/teacher_search_views.py)、[查询](../../backend/features/garage/services/teacher_search_queries.py)、[配置](../../backend/features/garage/services/teacher_search_settings.py) | 搜索/附近/打卡已有；CG08，不当作任意自定义规则引擎 |
| `car_review` | 车评系统 | [管理](../../backend/features/admin/garage/review_views.py)、[审核](../../backend/features/admin/garage/review_actions.py)、[发布](../../backend/features/group_ops/group_hooks/car_review.py) | CG09/10；配置存在与发布已接通必须区分 |
| `gcmd` | 命令配置 | [页面](../../backend/features/admin/moderation/config_menus.py)、[契约](../../backend/shared/services/command_config_service.py) | 启停、别名、冲突/分页已有；不是竞品未见就删减 |
| `health` | 健康检查 | [群权限及功能诊断](../../backend/features/admin/subscription/controller.py) | 读取状态、权限与提示已有；不替代业务送达证明 |
| `stats` | 群组统计 | [聚合读取与页面](../../backend/features/admin/core/basic_menus.py) | 成员/邀请/流水/违规及近期统计已有；未读线上新数据 |
| `import` | 导入设置 | [页面/应用](../../backend/features/admin/import_export/settings_transfer.py)、[服务](../../backend/shared/services/import_settings_service.py) | 来源群/模块/覆盖流程已有；本轮不导入 |
| `clone` | 克隆设置 | [页面/应用](../../backend/features/admin/import_export/settings_transfer.py)、[服务](../../backend/shared/services/import_settings_service.py) | 目标群/模块/覆盖流程已有；本轮不克隆 |
| `control` | 管理权限 | [页面](../../backend/features/admin/moderation/control_menus.py)、[策略](../../backend/shared/services/permission_service.py) | 五类管理策略已有；多角色及撤权执行未现场复测 |
| `renewal` | 服务状态 | [入口](../../backend/features/admin/subscription/controller.py)、[续费处理](../../backend/features/subscription/renewal_handler.py) | 会员/卡密底座已有，功能门禁按既有策略关闭；不恢复收费 |

## 4. 具体新增差距的源代码锚点

| 差距 | 可核查事实 | 需求归属 |
|---|---|---|
| 多积分用途 | `CustomPointType/Account/Ledger` 已有；`PointsMallProduct/Order` 无币种字段，兑换/退款消费主积分 `change_points`；未找到换汇路由/汇率及双边账务 | CG11；换汇规则尚未实测，先设计再执行 |
| 等级标签与零门槛 | `PointsLevelSetting/PointsLevel` 无标签开关；`update_level` 拒绝门槛 ≤0；发言消费对没有匹配等级的成员放行 | CG12；补基准等级语义，不能仅加标签按钮 |
| 关群权限和通知 | `_apply_group_lock_permissions` 仅构造 `ChatPermissions(can_send_messages=not closed)`；现有 notice 设置控制删除口令消息，不能冒充已发送通知卡片 | CG13 |
| 联盟处罚类型 | `GroupAllianceBanPool` 无处罚类型；`_process_alliance_joint_ban` 固定 `action="ban"` | CG14；既有封禁不能偷偷改成禁言 |
| 拍卖创建权限 | 模型有 `create_permission`，页面描述固定“所有群成员”；`_check_auction_create_allowed` 只检查 enabled | CG15；模型字段不等于权限执行 |
| 抽奖用户名 | 当前 `LotterySetting` 只有两类置顶及删参与消息；参与路径未见对应用户名开关/校验 | CG15；主动参与与系统自动入场分别定义 |
| 入群筛选老师例外 | `handle_join_spam_guard` 先取用户名/昵称信号并处罚；模型/配置/消费者未见独立老师排除策略 | CG16；认证来源安全与例外顺序先明确 |
| 额外玩法 | 当前游戏页面及服务只见快三、黑杰克；竞品另列骰子、炸金花、德州、抢庄牛 | CG17；菜单对比，不承诺新增或执行任何投注 |
| 打卡批量/调度 | 竞品人工打卡列表有批量名单、一键、每日定时；我方未找到同类批量/定时打卡路径 | CG08；标明人工/计划来源，产品决策后才设计写操作 |
| 商城商品复制 | 竞品列表存在复制按钮；我方商品服务和管理页未见对应流程 | CG11 下独立 P2 效率增强；不复制库存消耗、订单和兑换身份 |
| 成员转让 | 当前 `_apply_points_transfer` 是管理员面板的转让，未见成员自助开关/佣金/最低佣金路径 | CG11；已有转让底座，不写成整体缺失 |
| 签到/每日模式 | 签到配置当前只有启停、金额与连续奖励；促活页面只有递增/周期类型 | CG18；模板/人数/排行/延删与每日模式表达待补，不改历史奖励 |
| 广告到期提醒 | 竞品说明到期前 3 天每天 10 点向配置用户私聊；当前 `AdCampaign/AdRotationRule` 无收件人/到期模板，未见提醒执行路径 | CG02-B；P2 独立提醒需求，未发通知 |

原有报告多目标发布、历史截断、时间窗口、搜索回退、消息删除、认证反应等证据见 [PRD 对应方案](./2026-10-15-competitor-gap-prd.md)。

## 5. 尚未完成的检查及其原因

以下项目仍明确开放，不写成“所有功能已验收”：

1. **竞品频道后台**：转发入口要求在频道发管理指令。用户禁止未经确认发群/频道测试消息，因此只记录指引，未进入；不能据此确定转发全部细项。
2. **写操作后的页面与行为**：新建、启停、编辑后保存、模板重置、认证、打卡、位置提交、审核/撤审、原帖更新、批量重发、联盟变更、处罚和积分动作均未执行。需要创建记录才能出现的子页保持未验证。
3. **竞品运行正确性**：搜索准确率、距离、跨日打卡、奖励/退款守恒、并发结算、未知发送恢复、角色隔离和权限不足等没有执行证据；不能从界面承诺推断其已实现。
4. **我方当前线上运行身份**：用户提供链接与历史验收账号不同，本次没有新版本/进程读回证据。CG00 继续待核实；不报告生产故障或全量通过。
5. **业务细项穷举**：未遍历每条广告、规则、人员、报告、商品和订单；未打开会直接修改状态的选项。首页和安全子页的复核清单已形成，完整业务场景验收仍应按 PRD 分层执行。

后续实际验收记录需包含需求/场景 ID、版本、环境、目标对象、角色、预期、实际、时间和证据。先用隔离数据与传输边界验证，真实群/频道/位置/扣分场景由用户确认具体对象和影响后再执行。任何条目发现新子页或规则，先更新本清单和 PRD，再登记实现或完成结果。
