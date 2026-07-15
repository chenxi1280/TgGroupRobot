# TgGroupRobot 代码结构索引

> 版本：v2.0（2026-07-14）
> 范围：当前工作区 `main.py`、`backend/`、`scripts/`、`tests/`、`alembic/` 和 Web 管理静态资源。
> 产品事实见 [PRD.md](../product/PRD.md)，闭环状态见 [pending_issues.md](../product/pending_issues.md)。

## 1. 当前规模

| 范围 | Python 文件数 |
|---|---:|
| `backend/` | 598 |
| `tests/` | 109 |
| `scripts/` | 5 |
| 合计 | 712 |

代码规模数字用于定位，不作为完成度判断；结构质量以 `scripts/quality_metrics.py` 的全量 0 违规结果为准。

## 2. 运行时装配

```text
main.py
  -> backend.app.runtime.main
  -> backend.app.bootstrap.build_application
     -> Settings / Database / PTB Application
     -> router_registry.register_all
     -> update_pipeline.MessageDispatcher
  -> migrate_database
     -> legacy bootstrap（仅无 alembic_version 的历史库）
     -> alembic upgrade head
  -> validate_database_schema
  -> polling + Scheduler + FastAPI admin
```

迁移和 Schema Gate 均在 Telegram polling 前完成。失败不降级、不跳过，直接阻断启动。

## 3. 顶层边界

| 目录 | 职责 |
|---|---|
| `backend/app/` | 应用装配、Router 注册、update 分流、生命周期 |
| `backend/platform/config/` | 环境配置和日志 |
| `backend/platform/db/` | SQLAlchemy session、ORM、Alembic 调用、Schema Gate |
| `backend/platform/delivery/` | 不可变执行结果、七状态和退避算法 |
| `backend/platform/scheduler/` | 调度器、任务注册、运行健康 |
| `backend/platform/state/` | 私聊/群聊 conversation state |
| `backend/platform/telegram/` | Telegram pipeline、对话回调适配、配置状态注册表 |
| `backend/features/` | 按业务域组织的 handler/service/repository/view |
| `backend/shared/` | 跨域解析、权限、动作、UI 和通用服务 |
| `alembic/` | 版本化数据库迁移链 |
| `scripts/` | 开发重载和工程质量门禁 |
| `tests/` | 领域、契约、迁移、路由和质量回归 |

## 4. 业务域

| 业务域 | 目录 | 主要职责 |
|---|---|---|
| 管理工作台 | `features/admin/` | 群选择、菜单、私聊输入、配置和操作入口 |
| 活动 | `features/activity/` | 抽奖、接龙、游戏、竞猜、拍卖、促活 |
| 自动化 | `features/automation/` | 定时消息、轮播广告、快捷发布和可靠派发 |
| 车库 | `features/garage/` | 认证、联盟、老师搜索、车评、可靠转发 |
| 群操作 | `features/group_ops/` | 群消息 hooks、命令别名、自动删除、底部按钮 |
| 邀请 | `features/invite/` | 邀请链接、归因、统计和账号继承 |
| 风控 | `features/moderation/` | 反垃圾、防刷屏、违禁词、自动回复、处罚动作 |
| 附近 | `features/nearby/` | 用户/老师位置与附近查询 |
| 积分 | `features/points/` | 签到、账户、流水、排行、等级、商城 |
| 订阅 | `features/subscription/` | 套餐、续费和卡密底座；运行时付费门禁关闭 |
| 验证 | `features/verification/` | 新人验证、超时可靠状态机、欢迎投递 |
| Web 后台 | `features/web_admin/` | 管理员会话、卡密、公告、验证/广告操作 API |

## 5. 群消息执行顺序

`backend/platform/telegram/group_pipeline.py` 的业务顺序固定为：

```text
verification
  -> auction
  -> engagement
  -> game
  -> guess
  -> lottery
  -> solitaire
  -> moderation
  -> points
```

- handler 未命中返回 `False/None`。
- 只有 `BusinessRuleError` 会记录 warning 后继续。
- 其他异常保留堆栈并原样上抛，后续 handler 不再执行。

## 6. 私聊配置数据流

```text
callback / command
  -> private_config_registry 的精确 state-handler 映射
  -> target_chat_id 解析与管理员权限校验
  -> 领域输入 handler
  -> service/repository 持久化
  -> 清理 state 并返回对应管理页面
```

注册表按领域声明，当前 131 个状态键与重构前完全一致；未知状态不会被静默映射到其他 handler。

## 7. 可靠投递数据流

四类外部副作用共享 `backend/platform/delivery/` 的状态与结果语义，但保留各自领域表和收尾规则：

| 领域 | 执行记录 | worker / repository |
|---|---|---|
| 验证超时 | `VerificationChallenge` + `VerificationTimeoutAttempt` | `timeout_worker.py` / `timeout_repository.py` |
| 车库转发 | `GarageForwardRetryQueue` | `forward_delivery_worker.py` / `forward_delivery_repository.py` |
| 定时消息 | `ScheduledMessageLog` | `scheduled_delivery_worker.py` / `scheduled_occurrence_repository.py` |
| 轮播广告 | `AdRotationHistory` | `ad_delivery_worker.py` / `ad_delivery_repository.py` |

共同规则：唯一执行键、不可变快照、锁定认领、发送前开始标记、明确失败退避、未知结果停止自动重放、管理员确认恢复。

## 8. 数据库结构

ORM 位于 `backend/platform/db/schema/models/`，以 `chat_id` 为主要租户隔离维度。可靠性迁移链：

```text
0001_legacy_baseline
  -> 0002_verification_reliability
  -> 0003_garage_forward_reliability
  -> 0004_scheduled_reliability
  -> 0005_ad_rotation_reliability
```

Schema Gate 位于 `backend/platform/db/runtime/schema_gate.py` 和 `schema_contract.py`，统一聚合类型、nullable、default、外键、普通索引和唯一约束差异。

## 9. 调度与健康

`ScheduledTask` 统一记录：

- `total_runs` / `total_errors` / `consecutive_errors`
- `last_success_at` / `last_failure_at` / `last_error`
- `enabled` / `is_running` / `last_run` / `next_run`

领域 worker 若整批存在失败会抛出健康异常，由调度器累计并展示；不会把“0 成功、全部失败”记录为健康执行。

## 10. Web 管理边界

Web 后台采用拆分 Router：认证、账号、卡密、公告、验证超时和广告派发分别注册。所有操作 API 同时依赖当前管理员和有效管理会话；不确定任务重放要求显式确认，并写管理员、原因和来源执行记录。

## 11. 工程门禁

| 门禁 | 范围 | 失败条件 |
|---|---|---|
| compileall | `main.py backend scripts` | 语法/字节码编译失败 |
| 质量指标 | `backend/**/*.py` | 500/50、嵌套、参数、复杂度、魔法数字任一违规 |
| Ruff | `main.py backend scripts tests` | 明确正确性规则失败 |
| mypy | `main.py backend scripts` | 配置启用的全量类型规则失败 |
| pytest | `tests/` | 任一失败、warning 或 60 秒超时 |

CI 的 checks job 全部通过后才允许构建镜像。

## 12. 维护约束

- Handler 只做边界解析和编排，业务规则进入 service，查询/持久化进入 repository，文本键盘进入 view/presenter。
- 数据库变更同步 ORM、Alembic、Schema Gate、数据库设计和测试。
- 外部输入在边界验证；SQL 使用 SQLAlchemy 参数绑定，不拼接用户输入。
- 不保留死入口、静默兜底、假成功或吞错路径。
- 文件和函数拆分后保持稳定的 Router/service 对外入口，删除已替代实现。
