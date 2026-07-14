# TgGroupRobot 全量闭环审计

> 历史文件名保留为 `pending_issues.md`，便于旧链接继续有效。
>
> 审计日期：2026-07-14
> 审计范围：2026-07-13《全量可靠性与工程质量闭环设计》确认的实现、功能设计、操作、数据流、数据库、可观测性和工程质量问题。
> 当前结论：批准范围内没有未完成、失败或未证实条目。

## 1. 闭环状态

| 领域 | 状态 | 当前事实 |
|---|---|---|
| 定时窗口 | 已闭环 | 直接计算下一个 UTC+8 窗口边界，覆盖 12 小时、24 小时和跨日窗口，不再靠周期盲目迭代 |
| 验证超时 | 已闭环 | 七状态执行记录、追加 attempt、租约、退避、未知结果隔离、Telegram/Web 管理操作均已落地 |
| 车库转发 | 已闭环 | 来源事件唯一键、消息映射占位、完整按钮快照、原子收尾、租约恢复与人工重放已落地 |
| 定时消息 | 已闭环 | 每次计划时间创建唯一 occurrence，快照、重试、不确定状态、历史和操作入口已落地 |
| 轮播广告 | 已闭环 | 置顶池/排除池参与真实选择，派发前建历史，成功后推进游标，失败与不确定记录可操作 |
| 群消息管线 | 已闭环 | 仅 `BusinessRuleError` 允许继续；编程错误原样上抛并停止后续 handler |
| PTB 对话状态 | 已闭环 | 回调入口与 chat/user 对话键一致，全量 warning-as-error 回归无 tracking warning |
| 数据库迁移 | 已闭环 | async Alembic、legacy baseline、四个可靠性 revision、唯一 head 和 downgrade 路径齐备 |
| Schema Gate | 已闭环 | 聚合校验表、字段、类型、nullable、default、外键、索引和唯一约束；差异阻断启动 |
| 调度健康 | 已闭环 | 领域批次失败上浮；调度状态暴露累计错误、连续错误、最近成功、最近失败和最近错误 |
| 操作恢复 | 已闭环 | 明确失败可重试，未成功可关闭，`uncertain` 仅二次确认后重放并保留来源关联 |
| 工程结构 | 已闭环 | 全量生产 Python 的 500/50、嵌套、位置参数、复杂度、魔法数字门禁为 0 项违规 |
| 静态门禁 | 已闭环 | compileall、Ruff、mypy、质量指标和 warning-as-error pytest 已接入发布 checks job |
| 文档事实 | 已闭环 | PRD、真值表、数据库设计、后端架构和本审计使用同一可靠性语义 |

## 2. 统一数据流

所有会触发 Telegram 外部副作用的可靠执行都遵循同一边界：

```text
业务配置/来源事件
  -> 数据库创建唯一执行记录和不可变快照
  -> worker 以 FOR UPDATE SKIP LOCKED 认领并持久化 processing/lease/send_started_at
  -> 调用 Telegram
     -> 明确成功：原子写业务收尾 + succeeded
     -> 明确瞬时失败：retryable_failed + next_retry_at
     -> 明确永久失败：permanent_failed
     -> 结果未知或发送后落库失败：uncertain，禁止自动重放
  -> 管理员按状态查询、重试、关闭或二次确认重放
```

状态固定为：`pending / processing / retryable_failed / succeeded / permanent_failed / uncertain / cancelled`。

## 3. 数据库版本链

| Revision | 内容 |
|---|---|
| `0001_legacy_baseline` | 历史库一次性纳管基线 |
| `0002_verification_reliability` | 验证超时状态和 attempt 历史 |
| `0003_garage_forward_reliability` | 车库来源事件幂等和可靠执行字段 |
| `0004_scheduled_message_reliability` | 定时 occurrence、快照、租约和状态 |
| `0005_ad_rotation_reliability` | 广告派发记录、池配置、租约和重放关联 |

启动顺序固定为：`legacy bootstrap（仅未纳管历史库） → stamp baseline → alembic upgrade head → schema gate`。已纳管库不会重复执行兼容 SQL，任何错误都会阻断启动。

## 4. 操作入口

- 验证超时：Telegram 管理面板与 Web 后台支持群/状态筛选、重试、关闭和不确定重放确认。
- 车库转发：Telegram 车库管理面板支持失败、永久失败、不确定列表及对应操作。
- 定时消息：任务详情支持执行历史、安全重试、取消和不确定重放确认。
- 轮播广告：Telegram 与 Web 后台支持池配置、派发历史、状态筛选和恢复操作。
- 调度器：任务状态包含运行中、总运行、总错误、连续错误、最近成功、最近失败与最近错误。

## 5. 工程门禁

发布检查按以下顺序执行：

```text
compileall
quality_metrics.py
ruff check
mypy
pytest -W error（60 秒硬超时）
```

`scripts/quality_metrics.py` 对整个 `backend/` 执行，无基线豁免：

- 文件不超过 500 行。
- 函数不超过 50 个非空行。
- 嵌套深度不超过 3。
- 位置参数不超过 3。
- 圈复杂度不超过 10。
- 比较表达式不使用未命名数字。

## 6. 产品策略与非问题项

- 会员/套餐授权保持“暂时关闭”：底座保留，当前所有群功能默认开放。这是明确产品策略，不是实现缺口。
- 私有仓库 README 保持最小披露是仓库治理策略，不影响内部 PRD、真值表和操作文档完整性。
- 生产发布不在本轮隐含授权内；仓库代码、迁移和检查已达到可发布状态，但未把“本地通过”表述成“线上已部署”。

## 7. 维护规则

- 新行为先更新 PRD，再提交 RED/GREEN 证据。
- 数据库结构变更必须同时更新 ORM、Alembic revision、Schema Gate 和数据库设计。
- 新增 Telegram 副作用必须复用明确的可靠状态语义，不得吞错、静默回退或自动重放不确定任务。
- 任何文档若与当前代码和自动化证据冲突，以可复现的代码、迁移和测试结果为准，并在同一变更中修正文档。
