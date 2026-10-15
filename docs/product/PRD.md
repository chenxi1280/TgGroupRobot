# TgGroupRobot PRD 入口与代码对接索引

> 版本：v1.13
> 日期：2026-10-15
> 状态：通用及按钮布局修复已部署0e5152d；我方专用群轮播/定时/延删部分实测通过，管理权限待核对，整体PRD未完成

本文档作为后续维护的 PRD 入口，避免引用空文件导致产品、架构、问题清单三套文档断开。

当前新增需求见[竞品差距改造 PRD](./2026-10-15-competitor-gap-prd.md)，区分已有能力、待补齐项和待核实证据，并定义优先级及验收标准。[全功能复核清单](./2026-10-15-full-feature-review.md)逐项对应竞品 29 个业务入口和我方 38 个稳定 ID。各需求、38项自有功能与74条标准的实现状态见[独立实施与验收记录](./2026-10-15-implementation-and-own-feature-audit.md)。用户已追加授权发布，通用实现首轮部署15c1247，后续补验修复为7044d73，按钮布局与新权限字段兼容续修为0e5152d；版本、CI、数据库回读、私聊对照及未验项见[生产发布与对照验收](./2026-10-15-production-general-acceptance.md)和[最新分项记录](./2026-10-15-non-group-general-acceptance.md)。用户随后允许在专用测试群验收我方机器人，已发送广告A/B及一次定时共3条消息，延删与上一条已删除的恢复通过；群测试详情和未验项见最新分项记录，全部业务验收未完成。

2026-10-10 的[服务修复与交互统一 PRD](./2026-10-10-service-repair-prd.md)继续作为既有导航、权限、草稿与业务修复的设计基线；当日实施、部署和局部现场结果见[验收记录](./2026-10-10-service-repair-acceptance.md)最后追加章节。历史结果不概括为当前所有功能均已闭环，也不代表 2026-10-15 重新核验了线上版本。

## 1. 权威文档

| 用途 | 文档 | 说明 |
|------|------|------|
| 管理按钮布局改造 | [2026-10-15-admin-keyboard-layout.md](./2026-10-15-admin-keyboard-layout.md) | 两列短选项、语义分组、长名称和确认保留、注册链与私聊验收 |
| 剩余通用功能分项验收 | [2026-10-15-non-group-general-acceptance.md](./2026-10-15-non-group-general-acceptance.md) | 私聊通知、标签配置、提醒真实收件/跨进程去重、权限草稿和复制边界；G2/G3部分实测；G1权限待核对，G4—G6缺测试对象 |
| 竞品差距改造 PRD | [2026-10-15-competitor-gap-prd.md](./2026-10-15-competitor-gap-prd.md) | v0.7；19组需求/74条标准；通用部分已部署，整体未完成 |
| 生产发布与对照验收 | [2026-10-15-production-general-acceptance.md](./2026-10-15-production-general-acceptance.md) | 最新0e5152d、CI1283项通过、0017；私聊及专用群部分场景通过，完整业务仍未验 |
| 剩余通用能力续建 | [2026-10-15-remaining-general-features.md](./2026-10-15-remaining-general-features.md) | 消息链接、持久清理及恢复、配置复制、联盟去重与本群解除、旧业务日兼容；历史本地候选记录；现已发布，现场范围见生产记录 |
| 全面本地复核 | [2026-10-15-comprehensive-local-review.md](./2026-10-15-comprehensive-local-review.md) | 15项追加修复；38项覆盖深度、并发/权限/异常证据与未完成、未验证清单 |
| 四项通用功能续建 | [2026-10-15-general-features-completion.md](./2026-10-15-general-features-completion.md) | 通知/持久计划、等级标签和到期提醒、异常恢复及自有逻辑复核；历史本地候选记录；现已发布，现场范围见生产记录 |
| 本地实施及自有功能检查 | [2026-10-15-implementation-and-own-feature-audit.md](./2026-10-15-implementation-and-own-feature-audit.md) | 19组状态、38项自有检查、74条标准证据与开放项 |
| 全功能复核清单 | [2026-10-15-full-feature-review.md](./2026-10-15-full-feature-review.md) | 竞品 29 业务入口/1 导航，我方 38 ID，逐项页面/代码依据、具体差距与未执行分支；不是全量业务通过证明 |
| 既有修复 PRD | [2026-10-10-service-repair-prd.md](./2026-10-10-service-repair-prd.md) | 问题基线、六类导航、公共交互、业务补全及验收场景；实施状态以验收记录为准 |
| 配套实施与运行恢复 | [2026-10-10-service-repair-design.md](../architecture/2026-10-10-service-repair-design.md) | 既有注册、状态、事务、兼容、运行反馈与发布回退设计 |
| 既有修复验收 | [2026-10-10-service-repair-acceptance.md](./2026-10-10-service-repair-acceptance.md) | 按日期、版本、环境和场景记录，历史局部通过不代表全量现场完成 |
| 产品需求全文 | [TgGroupRobot_PRD.md](./TgGroupRobot_PRD.md) | 当前完整 PRD，覆盖产品定位、角色、功能需求、流程和验收口径 |
| 当前功能状态 | [06_feature_truth_table.md](../setup/06_feature_truth_table.md) | 区分已发现缺口、历史记录待复核、本地验证、Telegram 验收与策略关闭 |
| 架构总览 | [code_structure_index.md](../architecture/code_structure_index.md) | 面向维护者的模块结构、运行链路、测试归类和架构模式 |
| 逐文件索引 | [code_file_inventory.md](../architecture/code_file_inventory.md) | 机器辅助生成的逐文件职责、类/方法、函数和常量索引 |
| 问题与历史审计 | [pending_issues.md](./pending_issues.md) | 2026-10-10 待修复问题，以及 2026-07-14 特定范围的历史审计 |

## 2. PRD 与代码模块映射

| PRD 功能域 | 主要代码目录 | 说明 |
|------------|--------------|------|
| Bot 启动与运行时 | `main.py`、`backend/app/` | CLI 入口、Application 装配、Router 注册、polling、scheduler、Web 后台启动 |
| 平台能力 | `backend/platform/` | 配置、数据库、schema lifecycle、Telegram 适配、状态、调度器 |
| 管理员私聊工作台 | `backend/features/admin/` | `/admin`、私聊菜单、功能配置入口、输入状态分发 |
| 群基础能力 | `backend/features/group_ops/` | `/start`、群 hooks、自动删除、底部按钮、命令别名、文本触发 |
| 新人验证与欢迎 | `backend/features/verification/` | 进群验证、超时处理、强制订阅相关运行时、欢迎消息 |
| 审核与风控 | `backend/features/moderation/` | 反垃圾、防刷屏、违禁词、自动回复、处罚动作 |
| 积分体系 | `backend/features/points/` | 签到、发言积分、排行、自定义积分、积分等级、积分商城 |
| 自动化发布 | `backend/features/automation/` | 轮播广告、定时消息、调度派发 |
| 邀请增长 | `backend/features/invite/` | 邀请链接、邀请归因、统计、炸号继承 |
| 活动互动 | `backend/features/activity/` | 抽奖、接龙、游戏、竞猜、拍卖、促活 |
| 车库生态 | `backend/features/garage/` | 车库认证、车库转发、老师搜索、车评服务 |
| 订阅续费底座 | `backend/features/subscription/`、`backend/features/web_admin/` | 续费入口、卡密、平台后台；当前不对群功能做付费门禁 |
| 跨域共享能力 | `backend/shared/` | 权限、发布、按钮布局、callback 解析、通用 UI 和服务 |
| 文档站 | `docs-site/` | 功能手册、流程内容、文档/流程审计脚本 |
| 回归测试 | `tests/` | 当前为平铺测试目录，靠文件名和架构索引映射业务域 |

## 3. 维护口径

- 产品状态以 `docs/setup/06_feature_truth_table.md` 为准。
- 本轮范围内的导航、交互与修复验收以 2026-10-10 修复 PRD 为设计基线；未覆盖的业务需求继续沿用产品需求全文。
- 竞品差距新增需求按 2026-10-15 PRD 评审；其搜索、快捷入口和执行摘要为增量，沿用既有权限、草稿、群隔离及可靠执行约束。实施状态按2026-10-15独立记录逐项标记，不将部分本地通过写成全量完成。
- 设计完成、代码实现、本地验证、已部署与真实 Telegram 验收分别记录，不相互替代。
- 代码结构以 `docs/architecture/code_structure_index.md` 和 `docs/architecture/code_file_inventory.md` 为准。
- ORM 模型当前权威路径为 `backend/platform/db/schema/models/`。
- `tests/` 当前是平铺结构，不存在 `tests/features/<domain>/` 目录。
- `pending_issues.md` 同时维护当前待修复条目和有日期、范围限定的历史审计；历史关闭不代表新发现已解决。

## 4. 工程质量与交付门禁

- 生产 Python 全量执行 `scripts/quality_metrics.py`，文件、函数、嵌套、位置参数、圈复杂度和魔法比较数字必须全部为 0 项违规。
- Ruff 覆盖 `main.py`、`backend/`、`scripts/`、`tests/` 的明确正确性规则；未定义名称、重复字典键、无效控制流和未使用局部变量会阻断 CI。
- mypy 覆盖 `main.py`、`backend/`、`scripts/` 的全量文件，并检查已注解及未注解函数体。动态 Mixin、星号聚合导出和第三方框架收窄产生的已知类别在配置中显式列出，不以文件白名单规避检查。
- CI 固定执行 compileall、质量指标、Ruff、mypy 和 `pytest -W error`；任一失败不得进入镜像构建和生产发布阶段。
- 后端回归测试使用 60 秒硬超时，不保留未解释 warning。
## 定时消息可靠执行

- 每个计划发送时间必须先生成唯一执行实例，唯一键为 `task_id + scheduled_for`；同一实例不得因多进程调度或重启而重复创建。
- 执行实例保存发送时的完整内容、媒体、按钮、删除上一条和置顶选项快照，后续重试不读取已被修改的任务配置。
- 状态固定为 `pending / processing / retryable_failed / succeeded / permanent_failed / uncertain / cancelled`。
- worker 必须先持久化 `send_started_at` 再调用 Telegram；发送开始后的网络未知结果或数据库落库失败进入 `uncertain`，不得自动重发。
- 明确的限流错误按退避策略自动重试；明确的权限、参数错误进入永久失败；达到最大尝试次数后停止自动重试。
- 调度 tick 内任一执行失败必须上浮到调度健康状态，不能把“全部发送失败”记录为健康成功。
- 管理员可在任务详情查看最近执行历史，并可重试明确失败、取消未成功实例；`uncertain` 仅允许二次确认后人工重放。
- 成功完成时，执行日志和任务的 `last_sent_message_id` 必须在同一数据库事务中更新。

### 验收标准

- 多进程同时扫描同一任务只产生一个执行实例。
- worker 崩溃后，发送前过期租约可恢复重试；发送后过期租约进入 `uncertain`。
- 任务配置在 occurrence 创建后被修改，不影响该 occurrence 的发送快照。
- Telegram 明确失败、未知结果、数据库完成失败均有可查询状态和错误码。
- 管理页面能区分成功、重试中、永久失败、不确定和已取消记录，并限制不安全操作。

## 轮播广告可靠执行

- 轮播候选先排除 `exclude_campaign_ids`；配置了 `top_campaign_ids` 时仅从有效置顶池选择。置顶池无有效条目属于配置错误，不得静默退回全部广告。
- 置顶池和排除池只能引用当前群的广告；管理界面必须能查看和切换两类成员。
- 每个计划派发先生成唯一 `dispatch_key` 执行记录并保存完整广告、按钮和规则快照，再推进规则 `next_run_at`。
- worker 使用 `pending / processing / retryable_failed / succeeded / permanent_failed / uncertain / cancelled` 状态、租约和退避策略执行。
- 只有成功完成才推进广告游标、发送次数和最近消息；发送开始后的未知结果或数据库完成失败进入 `uncertain`，禁止自动重发。
- 管理员可按状态查看历史、重试明确失败、取消未成功执行；不确定记录仅允许二次确认后的人工重放。
- 任一派发失败必须上浮至广告 scheduler 健康状态。

### 验收标准

- 置顶/排除选择规则具有确定性，并覆盖无有效置顶条目的显式错误。
- 同一群同一 `scheduled_for` 只创建一条派发记录，多进程扫描不重复发送。
- 配置修改不影响已创建派发的内容与规则快照。
- 成功、限流、权限错误、网络未知和数据库完成失败都有可查询状态。
- Telegram 管理入口可完成历史筛选、安全重试、取消和二次确认重放。

## 群消息业务流水线异常契约

- 业务 handler 按固定顺序执行：`verification → auction → engagement → game → guess → lottery → solitaire → moderation → points`。
- handler 主动放弃或未命中应返回 `False/None`；可预期且允许继续的业务异常必须显式抛出 `BusinessRuleError`。
- `BusinessRuleError` 记录 warning 后继续后续 handler。
- `ValueError / LookupError / TypeError` 及其他未预期异常属于实现或依赖故障，必须保留堆栈并重新抛给全局错误处理器；异常后不得继续执行后续 handler。
- ConversationHandler 的回调入口必须按用户与群跟踪，不能使用按消息键导致后续文本无法关联；测试运行不得产生 PTB tracking warning。

### 验收标准

- 真实 handler 注册顺序与上述列表完全一致。
- `BusinessRuleError` 后下一个 handler 继续执行。
- `ValueError` 和任意未预期异常原样上抛，后续 handler 不执行。
- 完整测试输出不包含 PTB ConversationHandler 警告。

## 数据库版本迁移与启动校验

- 数据库结构变更必须进入 Alembic revision；每个 revision 同时提供 upgrade 与 downgrade。
- 历史数据库首次发现没有 `alembic_version` 时，必须显式执行一次 legacy bootstrap，成功后标记 `legacy_baseline`，随后升级到 head。
- 已建立版本表的数据库启动时只能执行 `alembic upgrade head`，不得重复扫描历史兼容 SQL。
- legacy bootstrap、stamp 或 upgrade 任一步失败都必须阻断启动，不允许配置开关或环境变量静默跳过。
- Schema Gate 在迁移后只读运行，并一次性汇总表、字段、PostgreSQL 类型、nullable、server default、外键目标/删除策略、必要索引和唯一约束差异。
- Bot 主进程和独立数据库初始化命令必须复用同一条“迁移后校验”链路。

### 验收标准

- 空库、未纳管历史库和已纳管数据库分别覆盖自动化测试。
- 未纳管历史库严格按 `legacy bootstrap → stamp baseline → upgrade head → schema gate` 执行。
- 已纳管数据库不会调用 legacy bootstrap。
- 任一迁移错误或任一 Schema Gate 差异都会保留原始错误并拒绝启动。
- Schema Gate 同一轮能报告多个不同类别的结构差异。
