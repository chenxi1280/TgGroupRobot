# 2026-10-15 本地实施与自有功能独立检查记录

> 状态：通用代码及两项补验修复已部署7044d73；私聊分项通过，PRD整体未完成。下文本地阶段记录保留为历史。
> 基线：本地 master / feecab8 加本次工作树。日期按 Asia/Shanghai。
> 需求：[竞品差距 PRD v0.7](./2026-10-15-competitor-gap-prd.md)。

## 授权及实现范围

2026-10-15追加发布授权已执行，CI1272项通过、生产0017、136个源文件哈希匹配。CG00身份/版本/发布已核实，CG01广告检索筛选与三类空列表、CG02空恢复页、CG03四快捷入口及CG13夜间父页有局部客户端证据；CG12/13/14/18真实副作用与38项/74条完整组合仍未完成。[生产发布与对照验收](./2026-10-15-production-general-acceptance.md)覆盖当前状态，表内未更新的本地/待现场结论不推定关闭。

用户在完成 PRD 后授权代码实现、操作逻辑检查和自有功能独立检查。通用管理、权限、统计、积分反馈与可靠执行状态已进行本地改造。竞品可见业务涉及商业性服务人员的查询、位置、评价和推广，因此没有扩展该类撮合、定位、报告/认证、人员标记、交易及相关认证豁免链路，也没有删除既有代码。下表明确未实施内容，不能将本记录解释为完成全部 PRD。

没有启动真实机器人 polling、连接生产数据库、部署或向真实群/频道发送测试消息。使用真实 Application 注册、输入分发、服务和一次性 PostgreSQL；仅 Telegram HTTP 传输被测试替身承接。模拟 API 成功不是 Telegram 真实送达证明。

## 19 组需求逐项实施状态

| 需求 | 当前状态 |
|---|---|
| CG00 | 已核实线上@testxd02bot、专用群、运行7044d73/0017及源文件；私聊局部验收，群内现场动作未执行 |
| CG01 | 列表搜索/筛选/分页/返回已本地实现；中文/编号/长度、删除末页及1000条完整渲染有隔离证据，三类空列表和广告检索筛选有真实私聊证据，完整生产数据组合未验 |
| CG02 | 摘要、消息链接、持久延删及逐动作恢复已实现；七态和崩溃/并发已隔离验证，空恢复页与到期提醒私聊计划收件已现场检查；群投递/链接/清理仍待确认 |
| CG03 | 四项快捷入口及分类已有真实私聊证据；来源返回有指定场景证据，窄屏真实客户端未验收 |
| CG04 | 未实施；不扩展当前商业性服务场景的人员标记与协作流程 |
| CG05 | 未实施；未新增该业务场景的积分红包及交易流转 |
| CG06 | 产品形态、成本和运维责任待决策，未建设 |
| CG07 | 不实施商业性服务人员认证及展示扩展；保留原代码与历史问题 |
| CG08 | 不实施商业性服务人员搜索、匹配、定位及打卡扩展 |
| CG09 | 不实施商业性服务评价报告发布与推广扩展；原缺口未关闭 |
| CG10 | 不实施商业性服务人员报告检索、榜单及身份扩展 |
| CG11 | 未实施该业务场景的成员转让、佣金、换汇与商品币种扩展 |
| CG12 | 零门槛、字段白名单及独立等级标签已有本地实现；标签合法/表情校验、保存/取消和关闭状态已真实私聊检查；实际成员标签升级/降级/冲突仍待确认 |
| CG13 | 双权限、原权限快照、通知和持久计划已实现；通知私聊预览/取消、权限方案保存与真实快照、群权限未变及临时方案恢复已核实；计划/权限/通知群内动作仍待确认 |
| CG14 | 处罚去重/升级、角色复核、本群确认解除及池移除/退出语义已本地实现并隔离验证；现场待验收 |
| CG15 | 部分实现：显式拍卖权限及抽奖用户名检查；匿名待决策，全入口组合未穷举 |
| CG16 | 不实施该商业性服务人员认证身份的入群豁免扩展 |
| CG17 | 未新增玩法；范围与规则待产品决策 |
| CG18 | 签到反馈/每日激励及旧UTC正奖励兼容已本地验证；旧零奖励时间需上线前核对，完整延删组合及现场待验收 |

## 通用改造的实现约束

- 三类管理列表共用私聊搜索状态与查询器，字面包含匹配、100字上限、8条一页、群绑定、启用筛选、稳定排序、计数/页码纠正。搜索返回暂停输入，详情返回原条件；查询数据库故障提供重试、清除及返回。过滤条件保留于用户运行时上下文，进程重启不保证恢复。
- 最近成功与最近执行分别读取真实执行记录，七种状态不互相替代；新发送记录将置顶、删除旧消息、取消旧置顶结果单独落库。发送成功后的附加动作失败不重发消息。历史空事实显示“历史未记录”，不虚构成功。v0.7已把广告延迟删除及发送前后动作接入AdminEffect；回执、置顶及延删任务同事务保存，失败正文保留已发生动作。历史未记录不回填；未知动作不重放。
- 首页四项快捷入口保留六类分类和38个稳定功能ID；显式记录首页/分类来源，只改回退导航，不新增业务投递。
- 等级门槛允许0，负数/重复门槛拒绝；可修改权限字段使用白名单。没有基础等级时沿用旧版放行，界面说明该含义，不暗中收紧存量群。后续v0.5通过公开do_api_request补通用等级标签；不扩展认证标签或身份链路。
- 开群与关群分别保存完整权限方案，保存不执行；已有调度器及口令消费方案，显式传入 independent 权限参数，避免 Telegram 权限隐含关系覆盖媒体选择。旧配置继续仅控制文本。后续v0.5已补原权限快照、通知卡片及持久计划，详见[续建记录](./2026-10-15-general-features-completion.md)。
- 联盟新池记录保存 ban/mute 类型，旧记录迁移默认ban；同一联盟写入串行化，禁言只能升级封禁。新增显式 team_mute 回复命令，期限为持续禁言；按当前群管理策略鉴权，池记录与实际动作反馈区分。移除池记录只停止后续传播，不自动解除其他群既有处罚。v0.7以池版本/群/类型稳定身份去重，并提供有确认的本群解除；预先存在/未知处罚无可解除所有权。同一版本解除后不立即再次处罚。
- 拍卖原 create_permission 虽存admin但历史执行允许所有成员。为避免升级时突然收紧，以 permission_enforced 明确启用新策略；管理员显式选择后在开始创建和发布前复核。抽奖默认不要求用户名，启用后在主动参与校验和扣分之前拒绝无用户名身份；匿名未增加。
- 签到反馈支持纯文本安全占位符、去重人数、签到名次、独立保留时长；该名次不冒充积分排行。每日激励使用首档等额奖励，保留原递增/周期方案与当天领奖事实。签到、发言、邀请日配额和激励按 Asia/Shanghai；没有改写历史行、补偿历史少发奖金或重发旧奖励。v0.7已用旧UTC合成签到及正奖励流水演练兼容；历史行不重写。零奖励没有不可变时间凭证，需上线前人工核对，不能自动推定历史领取时刻。

## 自有操作逻辑独立发现与修复

| 问题 | 本地改动与证据边界 |
|---|---|
| 广告/定时多个新建、详情、编辑、启停失败返回使用错误的位置参数 | 修正真实单例处理器的关键字调用；新建、编辑保存、启用失败返回通过真实注册路由和DB检查；并非仅检查按钮格式 |
| 广告显式群A撤权后会回退到当前选中的群B | 仅无显式目标才允许选择群回退；A/B隔离与撤权测试不泄漏B页面 |
| 定时旧列表最多读取50条 | 改为DB分页计数，1000条逐页可达；每类125页验证 |
| 搜索与字段编辑争抢私聊输入 | 进入列表暂停编辑并保留草稿；退出搜索清理输入，临时搜索不冒充业务草稿 |
| 成功时间被最近失败/未知覆盖的表达风险 | 独立取最近成功与最新执行；两次刷新不创建新执行 |
| 置顶/清理失败只有日志，后台难以辨别 | 附加动作事实落库并显示；独立DB回读证明消息只发一次、不进入重试 |
| 取消旧置顶、新置顶均失败时丢失旧置顶指针 | 未确认新置顶/取消前保留旧消息已知事实 |
| 等级修改允许任意已有属性名 | 收紧为明确7项权限字段，不能改写chat_id等身份字段 |
| 拍卖权限字段未消费 | 显式策略生效，并在创建/发布前检查；历史策略兼容见上文 |
| 连续签到用当天新建计数递增，可能一直为1 | 从昨日统计及有效签到计算；23:59至00:01合成时钟验证第二天为2，并发奖10分 |
| 连签奖励后的返回余额不含奖金 | 返回最终余额；合成例子初始100、两天各5、奖金10，结果余额120 |
| 每日激励并发读取“未领取”，可能多次加奖 | INSERT ON CONFLICT + 行锁，3个并发请求只有一次10分流水；切模式不重复领取 |
| 群锁消息管线与调度器重复计算时段 | 复用同一 Asia/Shanghai 判定；跨午夜、等时、24:00、非法分钟及空时间分别验证 |
| 新权限配置伪造字段导致异常 | 白名单拒绝并反馈，不改数据库；不把异常当保存成功 |

## 自有 38 项独立检查清单

以下逐项核对稳定目录、管理分发和对应业务源文件；通用导航通过 `test_button_navigation_postgres.py` 的真实注册入口回归。每项的深度不同，表内没有新证据的业务仍保持待业务验收。商业性服务相关模块只作既有实现和缺口登记，没有扩展或现场执行。

| ID | 功能 | 页面/业务代码依据 | 本轮独立检查结论 |
|---|---|---|---|
| `welcome` | 进群欢迎 | [管理](../../backend/features/admin/welcome/controller.py)、[投递](../../backend/features/verification/welcome_delivery.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `verification` | 进群验证 | [页面](../../backend/features/admin/moderation/verification_views.py)、[入群消费](../../backend/features/verification/verification_handler.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `newmem` | 新成员限制 | [页面](../../backend/features/admin/moderation/member_menu_views.py)、[消费](../../backend/features/group_ops/group_hooks/control_new_member.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `antispam` | 垃圾防护 | [管理](../../backend/features/admin/ui/antispam_controls.py)、[规则](../../backend/features/moderation/services/garbage_guard_rules.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `punish` | 惩罚策略 | [页面](../../backend/features/admin/moderation/config_menus.py)、[动作](../../backend/features/moderation/services/user_action_runtime.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `autodel` | 删除提示 | [配置](../../backend/features/admin/ui/auto_delete.py)、[群管线](../../backend/features/group_ops/group_hooks/core.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `night` | 夜间管控 | [页面](../../backend/features/admin/moderation/member_menu_views.py)、[权限消费](../../backend/features/group_ops/group_hooks/control_lock.py) | 双权限、原权限快照、通知与持久去重/恢复已隔离验证；真实现场待验收 |
| `renamewatch` | 改名监控 | [页面](../../backend/features/admin/moderation/control_menus.py)、[消费](../../backend/features/group_ops/group_hooks/control_rename.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `forcesub` | 强制订阅 | [页面](../../backend/features/admin/moderation/member_menu_views.py)、[消费](../../backend/features/group_ops/group_hooks/control_force_subscribe.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `alliance` | 联盟功能 | [管理](../../backend/features/admin/garage/alliance.py)、[池](../../backend/features/garage/services/alliance_ban.py)、[处罚](../../backend/features/group_ops/group_hooks/moderation.py) | v0.7已补去重/升封禁、角色/缺权/未知、池移除/退出及本群解除隔离验证；Telegram真实处罚未执行 |
| `ads` | 轮播广告 | [页面](../../backend/features/automation/ads_context.py)、[执行](../../backend/features/automation/ad_delivery_executor.py) | 真实运行类为 ads_context.AdsHandler；搜索/新建/编辑/返回/执行结果通过隔离回归；附加动作失败不重发 |
| `autoreply` | 自动回复 | [页面](../../backend/features/moderation/auto_reply_views.py)、[管理](../../backend/features/moderation/auto_reply_detail_actions.py) | 查询与权限/输入状态独立检查；原匹配执行由既有回归覆盖，未发群消息 |
| `scheduled` | 定时消息 | [列表](../../backend/features/automation/scheduled_message_listing.py)、[执行](../../backend/features/automation/scheduled_delivery_executor.py) | DB分页替代截断；新建/保存/失败返回及执行事实已验证；无真实投递 |
| `sync` | 频道同步 | [管理](../../backend/features/admin/garage/forward.py)、[服务](../../backend/features/garage/services/garage_forward_service.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `bottom_button` | 底部按钮 | [管理](../../backend/features/admin/activity/bottom_button.py)、[生成](../../backend/features/group_ops/services/bottom_button_service.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `qpub` | 快捷发布 | [草稿与发送](../../backend/features/admin/import_export/quick_publish.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `points` | 主积分 | [页面](../../backend/features/admin/points/overview_views.py)、[消息消费](../../backend/features/points/points_message_actions.py)、[管理员转让](../../backend/features/admin/points_config_messages.py) | 业务日、连续奖励、最终余额、反馈人数及名次已验证；历史补偿未执行 |
| `custom_points` | 自定义积分 | [管理](../../backend/features/admin/points/custom_points.py)、[服务](../../backend/features/points/services/points_extended_custom.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `points_level` | 积分等级 | [页面](../../backend/features/admin/ui/points_extended_levels.py)、[服务](../../backend/features/points/services/points_extended_levels.py)、[执行](../../backend/features/points/points_message_actions.py) | 零门槛、字段白名单和标签生命期已隔离验证；全媒体/身份例外组合及现场仍有原开放项 |
| `points_mall` | 积分商城 | [详情](../../backend/features/admin/points/mall_product_pages.py)、[扣款](../../backend/features/points/services/points_mall_products.py)、[订单](../../backend/features/points/services/points_mall_orders.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `invite` | 邀请链接 | [管理](../../backend/features/invite/invite_admin_menu_callbacks.py)、[归因](../../backend/features/invite/services/invite_tracking.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `inherit` | 账号继承 | [管理](../../backend/features/admin/import_export/inherit.py)、[迁移](../../backend/features/invite/services/account_inherit_service.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `lottery` | 抽奖 | [设置](../../backend/features/activity/lottery_menus.py)、[参与](../../backend/features/activity/lottery_participation.py) | 主动按钮无用户名拒绝且不扣分已验证；全参与类型组合未穷举 |
| `solitaire` | 接龙 | [管理入口](../../backend/features/admin/core/basic_menus.py)、[参与](../../backend/features/activity/solitaire_participation_callbacks.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `auction` | 拍卖 | [页面](../../backend/features/admin/activity/auction.py)、[创建](../../backend/features/activity/auction_handler.py)、[结算](../../backend/features/activity/services/auction_settlement.py) | 显式创建权限与兼容已验证；结算由既有回归覆盖，匿名未新增 |
| `game` | 游戏 | [页面](../../backend/features/admin/activity/game_presenters.py)、[服务](../../backend/features/activity/services/game_service.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `guess` | 竞猜 | [管理](../../backend/features/admin/activity/guess.py)、[结算](../../backend/features/activity/services/guess_service_runtime.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `engagement` | 促活工具 | [彩蛋](../../backend/features/admin/activity/engagement_egg_actions.py)、[激励](../../backend/features/activity/services/engagement_chat.py) | 每日奖励、3并发只领奖一次及切模式保持回执已验证；红包未新增 |
| `garage_auth` | 车库认证 | [页面](../../backend/features/admin/garage/auth_views.py)、[服务](../../backend/features/garage/services/garage_auth_service.py)、[索引绑定](../../backend/features/garage/services/teacher_search_channel_index.py) | 只核对原有认证路径及缺口；未扩展业务、未授予或变更真实身份 |
| `teacher_search` | 老师搜索 | [页面](../../backend/features/admin/garage/teacher_search_views.py)、[查询](../../backend/features/garage/services/teacher_search_queries.py)、[配置](../../backend/features/garage/services/teacher_search_settings.py) | 只登记原搜索/定位/打卡和已发现缺口；未扩展、未提交身份/坐标 |
| `car_review` | 车评系统 | [管理](../../backend/features/admin/garage/review_views.py)、[审核](../../backend/features/admin/garage/review_actions.py)、[发布](../../backend/features/group_ops/group_hooks/car_review.py) | 只登记原审核/发布/查询缺口；未扩展报告业务或实际审核/发布 |
| `gcmd` | 命令配置 | [页面](../../backend/features/admin/moderation/config_menus.py)、[契约](../../backend/shared/services/command_config_service.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `health` | 健康检查 | [群权限及功能诊断](../../backend/features/admin/subscription/controller.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `stats` | 群组统计 | [聚合读取与页面](../../backend/features/admin/core/basic_menus.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `import` | 导入设置 | [页面/应用](../../backend/features/admin/import_export/settings_transfer.py)、[服务](../../backend/shared/services/import_settings_service.py) | v0.7新增选中JSON模块及等级标签重建；两端权限、目标快照、失败回滚及未选保留已隔离验证，无真实群写入 |
| `clone` | 克隆设置 | [页面/应用](../../backend/features/admin/import_export/settings_transfer.py)、[服务](../../backend/shared/services/import_settings_service.py) | v0.7共用选中模块复制；保留目标快照/所有权，不复制余额/同意/运行历史；隔离验证，现场待验收 |
| `control` | 管理权限 | [页面](../../backend/features/admin/moderation/control_menus.py)、[策略](../../backend/shared/services/permission_service.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |
| `renewal` | 服务状态 | [入口](../../backend/features/admin/subscription/controller.py)、[续费处理](../../backend/features/subscription/renewal_handler.py) | 已核对原菜单/业务消费者并纳入38入口导航回归；未新增能力，真实业务及全部异常组合未验收 |

## 74 条标准的验收台账

“本地验证”限定于所列子场景；写成“部分”或“待补”的标准不登记为整条关闭。测试总数不用于折算需求完成率。

| 标准 | 场景 | 证据及未完成部分 |
|---|---|---|
| A00-1 | 对齐入口与运行身份 | 已核实生产7044d73、@testxd02bot、专用群、0017及136个源文件哈希；历史本地基线另留 |
| A00-2 | 核对历史记录 | 已更新文档台账；保留历史日期及范围 |
| A00-3 | 核对业务结果 | 部分：真实私聊计划提醒、预览和配置反馈已读回；群内投递、权限、成员处置与全业务结果仍未现场验收 |
| A01-1 | 三类列表分别搜索 | 本地验证：三类大小写、字面特殊字符、空结果、中文、精确编号、100/101字边界 |
| A01-2 | 搜索与分页组合 | 本地验证：筛选/分页/详情返回；三类删除末页后纠正页码且保留条件 |
| A01-3 | 多群及权限变化 | 本地验证：A/B同名隔离、撤权及拒绝回退其他已选群 |
| A01-4 | 搜索与编辑切换 | 本地验证：原编辑转草稿、搜索不留伪草稿；全出口普通文本组合待补 |
| A01-5 | 大列表与异常 | 本地验证：每类1000条/125页完整Application+DB+伪HTTP渲染，全部可达，P95<2秒；查询故障有出口，不代表真实网络时延 |
| A02-1 | 成功后再次失败 | 本地验证：最近成功独立保留，最新七态分别渲染；刷新不生成业务执行 |
| A02-2 | 状态全集 | 本地验证：七态及无历史文案；只对确认成功且合法群类型生成消息链接 |
| A02-3 | 未知结果与刷新 | 本地验证：连续刷新不新增occurrence，不把未知转成成功 |
| A02-4 | 后续动作失败与消息链接 | v0.7本地验证：合法消息链接、发送前后逐动作事实、延迟删除持久化、收尾前崩溃后仅恢复动作；失败/429/未知不重发正文 |
| A02-5 | 计划和历史边界 | 部分实现：无历史及下次计划；已结束/过期全组合未验证 |
| A02-6 | 广告到期提醒 | 已真实私聊验证未同意拦截、本人同意、计划收件、同日多轮/发布重建进程后仍1条成功/1次尝试、撤销；预览时区差异已修复。时间/到期变更、限流及未知等仍为隔离证据；完整生产异常组合未关闭 |
| A03-1 | 高频路径 | 本地注册路由验证：四项直达、38入口和6分类保留 |
| A03-2 | 返回与旧按钮 | 本地验证四项来源返回；旧按钮由既有回归覆盖部分路径 |
| A03-3 | 窄屏及草稿 | 部分本地验证：两列结构及草稿；窄屏实际客户端未验收 |
| A04-1 | 新建及批准 | 未实施本项业务扩展；不登记通过 |
| A04-2 | 拒绝、撤回、修订及停用 | 未实施本项业务扩展；不登记通过 |
| A04-3 | 重复与并发审核 | 未实施本项业务扩展；不登记通过 |
| A04-4 | 角色及群隔离 | 未实施本项业务扩展；不登记通过 |
| A04-5 | 身份、输入及通知失败 | 未实施本项业务扩展；不登记通过 |
| A05-1 | 创建及输入边界 | 未实施本项业务扩展；不登记通过 |
| A05-2 | 发布失败及未知 | 未实施本项业务扩展；不登记通过 |
| A05-3 | 并发领取 | 未实施本项业务扩展；不登记通过 |
| A05-4 | 资格、关闭及旧按钮 | 未实施本项业务扩展；不登记通过 |
| A05-5 | 到期与取消竞争 | 未实施本项业务扩展；不登记通过 |
| A05-6 | 崩溃恢复及通知失败 | 未实施本项业务扩展；不登记通过 |
| A06-1 | 产品决策 | 产品决策待完成；未建设/启用 |
| A06-2 | 后续立项条件 | 产品决策待完成；未建设/启用 |
| A07-1 | 来源与身份绑定 | 未实施本项业务扩展；不登记通过 |
| A07-2 | 认证池及权限 | 未实施本项业务扩展；不登记通过 |
| A07-3 | 图标及认证标签 | 未实施本项业务扩展；不登记通过 |
| A07-4 | 限频 白名单与汇总 | 未实施本项业务扩展；不登记通过 |
| A08-1 | 关键词与资料来源 | 未实施本项业务扩展；不登记通过 |
| A08-2 | 严格开课与打卡日期 | 未实施本项业务扩展；不登记通过 |
| A08-3 | 定位完整流程 | 未实施本项业务扩展；不登记通过 |
| A08-4 | 距离与结果可达 | 未实施本项业务扩展；不登记通过 |
| A08-5 | 两类按钮及返回 | 未实施本项业务扩展；不登记通过 |
| A08-6 | 来源及结果清理 | 未实施本项业务扩展；不登记通过 |
| A08-7 | 批量/计划打卡决策及边界 | 未实施本项业务扩展；不登记通过 |
| A09-1 | 提交与审核 | 未实施本项业务扩展；不登记通过 |
| A09-2 | 三类目标独立及组合 | 未实施本项业务扩展；不登记通过 |
| A09-3 | 部分失败及恢复 | 未实施本项业务扩展；不登记通过 |
| A09-4 | 未知结果与重启 | 未实施本项业务扩展；不登记通过 |
| A09-5 | 图片 预览与按钮 | 未实施本项业务扩展；不登记通过 |
| A09-6 | 用户结果与现场限制 | 未实施本项业务扩展；不登记通过 |
| A10-1 | 历史可达与检索 | 未实施本项业务扩展；不登记通过 |
| A10-2 | 两种榜单及时间窗口 | 未实施本项业务扩展；不登记通过 |
| A10-3 | 模板及报告按钮 | 未实施本项业务扩展；不登记通过 |
| A10-4 | 临时身份及换号 | 未实施本项业务扩展；不登记通过 |
| A10-5 | 审核可见性 | 未实施本项业务扩展；不登记通过 |
| A11-1 | 商品币种与旧数据 | 未实施本项业务扩展；不登记通过 |
| A11-2 | 订单快照与退款 | 未实施本项业务扩展；不登记通过 |
| A11-3 | 换汇决策与账务 | 未实施本项业务扩展；不登记通过 |
| A11-4 | 商品复制 | 未实施本项业务扩展；不登记通过 |
| A11-5 | 成员转让与佣金 | 未实施本项业务扩展；不登记通过 |
| A12-1 | 等级分段 | 部分本地验证：零门槛、负门槛拒绝、字段白名单；全分段组合未穷举 |
| A12-2 | 权限及老师例外 | 保留原媒体权限及例外；未扩展目标人员身份，未逐类型复验 |
| A12-3 | 标签生命期 | v0.5本地验证四种开关、阈值/升降级、停用清理、外来标签保留、缺权/不支持/限流/未知读回；真实客户端待验收 |
| A13-1 | 双权限与兼容 | v0.5本地验证：双方案、保存无远端写、原权限快照、读回失败不启用及独立媒体参数；现场权限未改 |
| A13-2 | 通知与删除分离 | v0.5本地验证：图片/文案/按钮、权限与通知失败分离、口令和通知独立清理、默认关闭及私聊预览；现场未发送 |
| A13-3 | 时间 权限与恢复 | v0.5本地验证：跨日/等时/非法时间、持久身份、多进程/重启去重、租约分界、收尾故障未知隔离与撤权；现场未执行 |
| A14-1 | 类型 迁移与升级 | 本地验证：旧0014池结构升级默认ban且来源/原因保留、重复升级/Schema Gate；mute升级ban及并发不降级 |
| A14-2 | 执行与权限 | v0.7本地验证：命令/命中共用持久身份；管理员/缺权/已有处罚/未知/退出/池删除复核；重复事件不重做，真实API待验收 |
| A14-3 | 解除与追溯 | v0.7本地验证：本群显式确认、当前角色/所有权/状态检查、并发解除一次、保留原限制和现群权限；跨群/其他来源冲突拒绝，移除/退出不自动解除 |
| A15-1 | 创建权限全入口 | 部分本地验证：历史兼容、显式admin策略拒绝成员；草稿撤权及全部入口组合待补 |
| A15-2 | 用户名主动参与 | 部分本地验证：无用户名按钮被拒且不扣分；其他主动入口及自动入场组合待补 |
| A15-3 | 匿名产品决策 | 匿名未实现，未作擅自产品决议 |
| A16-1 | 例外来源与顺序 | 未实施本项业务扩展；不登记通过 |
| A16-2 | 失败及兼容 | 未实施本项业务扩展；不登记通过 |
| A17-1 | 范围决议 | 产品决策待完成；未建设/启用 |
| A18-1 | 签到反馈与统计 | 部分本地验证：文案校验、编辑退出、去重人数/名次、跨零点/连续奖励；延删全部组合未穷举 |
| A18-2 | 每日与计划模式 | 本地验证：daily首档/三并发一次/切模式不重领，旧UTC正奖励流水去重及次日连续；旧零奖励无不可变时间，人工核对仍开放 |

## 验证环境及结果

- 本地 Python 3.12.9、python-telegram-bot 21.6；PostgreSQL 16 Alpine 一次性容器，仅绑定127.0.0.1动态端口。测试Application使用伪造令牌，未打开生产连接。
- 新增 `tests/test_competitor_admin_lists_postgres.py`、`tests/test_general_admin_policies_postgres.py`、`tests/test_delivery_action_facts_postgres.py`。使用真实路由、数据库事务及服务；HTTP传输替身模拟 Telegram，故障用边界注入验证。
- 查询性能样本为每类1000条、125页；仅测查询耗时并断言P95<2秒。没有生成完整Telegram页面的计量结果，A01-5不算完整通过。
- 最终工作树全量 `pytest -q --maxfail=8 --tb=short -W error`：**1166通过，48.64秒，无跳过、失败或warning**。包括新增查询故障出口、签到最终余额、人数/名次去重、非法群锁时间及迁移审计保留回归。
- 最终compileall、Ruff、mypy（644个源文件）、结构质量（0违规）、调用契约（0违规）、git diff --check均通过。静态调用检查不解析歧义动态方法，不把0违规解释成所有运行时调用已被证明。
- 迁移 `0015_general_admin_policies`：拍卖显式权限标记、抽奖用户名开关、联盟处罚类型。`0016_delivery_action_facts`：定时/广告附加操作事实JSONB。均已在已有一次性库及新空库执行，空库全链初始化、重复升级和Schema Gate通过；两个revision拒绝破坏性downgrade，相关测试通过；无生产迁移。历史事实空对象表示未记录，不回填虚假成功。

## 上线与后续验收边界

当前只有本地工作树可评审，不是已发布版本。发布前需按既有流程审查迁移、业务日切换和遗留配置，再在明确授权的专用验收对象核验真实机器人身份、角色、权限、发送、清理和客户端表现。原有 `.planning/`、reports及无关文件保留。本文未授权自动部署、发群测试或历史账务补偿。

## v0.5 四项通用功能续建

后续用户授权的关群通知、持久切换、等级标签及到期提醒已本地实现，新增0017；具体运行约束、异常恢复与最终验证见[续建记录](./2026-10-15-general-features-completion.md)。上文1166项为前一轮历史结果，不能作为新代码测试结果。

## v0.6 全面本地复核追加

本轮重新核对全部变更（含新增源文件）、19组需求/38个入口/74条标准，并补主积分旧链、五类输入撤权、导入/克隆两端鉴权与并发、原子配置合并、异常回滚、429和共享巡检恢复。15项具体修复、新测试及当前未完成/未验证内容见[全面复核记录](./2026-10-15-comprehensive-local-review.md)。38项均新增撤权入口拒绝证据，不能据此关闭原业务的全部组合；74条原开放标准继续保留。


## v0.7 剩余通用能力本地状态

消息链接与持久附加动作、延迟清理、选中JSON/等级标签复制、联盟处罚去重与本群解除、旧UTC正奖励兼容已追加本地实现；证据、限制及开放项以[本轮记录](./2026-10-15-remaining-general-features.md)为准。此前带版本/日期的测试结果保留为历史。没有部署、生产写入或真实群/频道消息。19组需求、38个入口、74条标准数量不变；整体PRD及全部业务组合未完成。
