# TgGroupRobot 关键代码文件索引

> 快照日期：2026-07-14
> 本索引记录运行、可靠性、操作和质量闭环的关键文件；完整文件集合以仓库中的 `rg --files` 结果为准，避免复制一份会立即漂移的 3000 行清单。

## 应用与平台

| 文件 | 职责 |
|---|---|
| `main.py` | 进程入口 |
| `backend/app/bootstrap.py` | Application、依赖和 handler 装配 |
| `backend/app/runtime.py` | 迁移、校验、polling、调度器、Web 生命周期 |
| `backend/app/router_registry.py` | 功能 Router 注册表 |
| `backend/app/update_pipeline.py` | 私聊/群聊消息分流 |
| `backend/platform/delivery/models.py` | 七状态枚举与不可变 `DeliveryOutcome` |
| `backend/platform/delivery/retry.py` | 有界指数退避 |
| `backend/platform/scheduler/core/core.py` | 任务执行、暂停、健康与最近错误 |
| `backend/platform/scheduler/core/task_config.py` | 任务周期和启用配置 |
| `backend/platform/telegram/group_pipeline.py` | 群业务 handler 顺序和异常契约 |
| `backend/platform/telegram/conversation_callback_handler.py` | chat/user 对话键兼容回调 |
| `backend/platform/telegram/private_config_registry.py` | 131 个私聊状态的声明式注册表 |

## 数据库生命周期

| 文件 | 职责 |
|---|---|
| `backend/platform/db/runtime/database_migrations.py` | legacy bootstrap、stamp、upgrade head |
| `backend/platform/db/runtime/startup_migrations.py` | 未纳管历史库的一次性兼容桥 |
| `backend/platform/db/runtime/schema_gate.py` | 只读结构校验执行器 |
| `backend/platform/db/runtime/schema_contract.py` | 类型/default/FK/index 契约提取 |
| `alembic/env.py` | async Alembic 环境 |
| `alembic/versions/0001_legacy_baseline.py` | 历史基线 |
| `alembic/versions/0002_verification_reliability.py` | 验证可靠性 |
| `alembic/versions/0003_garage_forward_reliability.py` | 车库可靠性 |
| `alembic/versions/0004_scheduled_message_reliability.py` | 定时消息可靠性 |
| `alembic/versions/0005_ad_rotation_reliability.py` | 广告可靠性 |

## 验证超时

| 文件 | 职责 |
|---|---|
| `backend/features/verification/timeout_executor.py` | Telegram 动作与结果分类 |
| `backend/features/verification/timeout_repository.py` | 锁定认领、attempt 和状态持久化 |
| `backend/features/verification/timeout_worker.py` | 批次隔离与健康传播 |
| `backend/features/verification/timeout_admin_service.py` | 重试、关闭、确认重放 |
| `backend/features/admin/moderation/verification_timeout_operations.py` | Telegram 管理入口 |
| `backend/features/web_admin/verification_timeout_router.py` | Web 查询和操作 API |

## 车库转发

| 文件 | 职责 |
|---|---|
| `backend/features/garage/forward_delivery_executor.py` | Telegram copy 执行与分类 |
| `backend/features/garage/forward_delivery_repository.py` | 幂等执行记录、占位、租约和原子收尾 |
| `backend/features/garage/forward_delivery_worker.py` | 批次执行与失败隔离 |
| `backend/features/garage/forward_delivery_admin_service.py` | 管理恢复操作 |
| `backend/features/admin/garage/forward_operations.py` | Telegram 状态列表与操作入口 |

## 定时消息

| 文件 | 职责 |
|---|---|
| `backend/features/automation/scheduled_message_service.py` | 任务配置与计划边界 |
| `backend/features/automation/scheduled_occurrence_repository.py` | 唯一 occurrence、快照、租约和收尾 |
| `backend/features/automation/scheduled_delivery_executor.py` | Telegram 发送分类 |
| `backend/features/automation/scheduled_delivery_worker.py` | occurrence worker |
| `backend/features/automation/scheduled_occurrence_admin_service.py` | 历史恢复操作 |
| `backend/features/automation/scheduled_message_operations.py` | Telegram 历史/重放入口 |
| `backend/platform/scheduler/tasks/scheduled_message_task.py` | 调度任务适配 |

## 轮播广告

| 文件 | 职责 |
|---|---|
| `backend/features/automation/services/ad_rotation_service.py` | 广告规则和选择入口 |
| `backend/features/automation/ad_delivery_repository.py` | 派发记录、租约、游标和原子收尾 |
| `backend/features/automation/ad_delivery_executor.py` | Telegram 广告发送分类 |
| `backend/features/automation/ad_delivery_worker.py` | 派发 worker |
| `backend/features/automation/ad_delivery_admin_service.py` | 重试、取消、确认重放 |
| `backend/features/automation/ads_operations.py` | Telegram 历史和恢复操作 |
| `backend/features/web_admin/ad_delivery_router.py` | Web 广告派发 API |

## 模型

| 文件 | 关键模型 |
|---|---|
| `backend/platform/db/schema/models/moderation.py` | `VerificationChallenge`、`VerificationTimeoutAttempt` |
| `backend/platform/db/schema/models/alliance.py` | `GarageForwardMessageMap`、`GarageForwardRetryQueue` |
| `backend/platform/db/schema/models/scheduled_message.py` | `ScheduledMessage`、`ScheduledMessageLog` |
| `backend/platform/db/schema/models/automation.py` | `AdCampaign`、`AdRotationRule`、`AdRotationHistory` |

## 工程质量

| 文件 | 职责 |
|---|---|
| `scripts/quality_metrics.py` | 全量生产 Python 结构指标门禁 |
| `tests/test_quality_metrics.py` | 门禁正反例 |
| `tests/test_static_runtime_contracts.py` | Ruff 揭示的运行时名称契约回归 |
| `pyproject.toml` | Ruff 和 mypy 全量配置 |
| `requirements-dev.txt` | 固定开发检查工具版本 |
| `.github/workflows/deploy-production.yml` | 发布前 compile/lint/type/test checks |

## 统计复核命令

```bash
rg --files backend | awk '/\.py$/' | wc -l
rg --files tests | awk '/\.py$/' | wc -l
python scripts/quality_metrics.py
```

本索引只陈述当前关键边界；文件级查找直接使用 `rg --files`，符号级查找使用 `rg -n 'class |def |async def '`，不再维护容易过期的重复清单。
