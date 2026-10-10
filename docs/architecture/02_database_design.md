# 阶段②：数据库与数据结构（PostgreSQL + SQLAlchemy）

本项目采用 **多群配置隔离**：几乎所有业务表均带 `chat_id`，确保同一 bot 在多个群内互不干扰。

## 1) 数据表设计（表名、字段、类型）

### `tg_users`
- `id` BIGINT PK（Telegram user_id）
- `username` VARCHAR(64)
- `first_name` VARCHAR(128)
- `last_name` VARCHAR(128)
- `language_code` VARCHAR(16)
- `created_at` TIMESTAMPTZ
- `updated_at` TIMESTAMPTZ

### `tg_chats`
- `id` BIGINT PK（Telegram chat_id）
- `type` VARCHAR(32)
- `title` VARCHAR(255)
- `created_at` TIMESTAMPTZ
- `updated_at` TIMESTAMPTZ

### `chat_settings`（群配置）
- `chat_id` BIGINT PK/FK -> `tg_chats.id`
- `language` VARCHAR(16)
- `sign_enabled` BOOL
- `sign_points` INT
- `sign_cooldown_hours` INT（MVP 暂未用，可扩展）
- `verification_enabled` BOOL
- `verification_timeout_seconds` INT
- `verification_restrict_can_send` BOOL
- `moderation_enabled` BOOL
- `moderation_block_links` BOOL
- `moderation_action` VARCHAR(32)
- `moderation_keywords` JSONB（关键词列表）
- `ads_enabled` BOOL
- `monetization_enabled` BOOL
- `created_at` TIMESTAMPTZ
- `updated_at` TIMESTAMPTZ

### `chat_members`
- `id` INT PK
- `chat_id` BIGINT FK -> `tg_chats.id`
- `user_id` BIGINT FK -> `tg_users.id`
- `role` VARCHAR(16)
- `joined_at` TIMESTAMPTZ
- `updated_at` TIMESTAMPTZ
- UNIQUE(`chat_id`,`user_id`)

### `points_accounts`
- `id` INT PK
- `chat_id` BIGINT FK
- `user_id` BIGINT FK
- `balance` INT
- `updated_at` TIMESTAMPTZ
- UNIQUE(`chat_id`,`user_id`)

### `points_transactions`
- `id` INT PK
- `chat_id` BIGINT FK
- `user_id` BIGINT FK
- `txn_type` VARCHAR(32)
- `amount` INT
- `reason` VARCHAR(255)
- `created_at` TIMESTAMPTZ

### `sign_in_logs`
- `id` INT PK
- `chat_id` BIGINT FK
- `user_id` BIGINT FK
- `sign_date` DATE
- `points_awarded` INT
- `created_at` TIMESTAMPTZ
- UNIQUE(`chat_id`,`user_id`,`sign_date`)

### `moderation_violations`
- `id` INT PK
- `chat_id` BIGINT FK
- `user_id` BIGINT FK
- `message_id` INT
- `rule` VARCHAR(64)
- `detail` TEXT
- `action` VARCHAR(32)
- `created_at` TIMESTAMPTZ

### `verification_challenges`
- `id` INT PK
- `chat_id` BIGINT FK
- `user_id` BIGINT FK
- `token` VARCHAR(64)
- `expires_at` TIMESTAMPTZ
- `solved` BOOL
- `timeout_status` VARCHAR(32)：`pending / processing / retryable_failed / succeeded / permanent_failed / uncertain / cancelled`
- `timeout_action` VARCHAR(16)
- `timeout_attempts` INT
- `timeout_next_retry_at / timeout_lease_until / timeout_send_started_at / timeout_completed_at` TIMESTAMPTZ
- `timeout_last_error` TEXT
- `timeout_replay_of_attempt_id` INT
- `created_at` TIMESTAMPTZ
- UNIQUE(`chat_id`,`user_id`)

### `verification_timeout_attempts`
- `id` INT PK
- `challenge_id` INT FK -> `verification_challenges.id`
- `attempt_no` INT，与 `challenge_id` 组成唯一键
- `status` VARCHAR(32)
- `action` VARCHAR(16)
- `lease_until / send_started_at / completed_at / created_at` TIMESTAMPTZ
- `error_code` VARCHAR(64)
- `error_message` TEXT
- `replay_of_id` INT FK -> `verification_timeout_attempts.id`
- 用途：追加保存每次 Telegram 调用与管理员确认重放证据，不覆盖不确定结果。

### `subscription_plans`
- `id` INT PK
- `code` VARCHAR(32) UNIQUE（free/pro/...）
- `name` VARCHAR(64)
- `price_cents` INT
- `duration_days` INT
- `feature_flags` JSONB
- `created_at` TIMESTAMPTZ

### `chat_subscriptions`
- `id` INT PK
- `chat_id` BIGINT UNIQUE FK
- `plan_id` INT FK -> `subscription_plans.id`
- `status` VARCHAR(16)
- `start_at` TIMESTAMPTZ
- `end_at` TIMESTAMPTZ
- `created_at` TIMESTAMPTZ

### `garage_forward_retry_queue`
- `id` INT PK
- `chat_id` BIGINT FK -> `tg_chats.id`
- `source_channel_id / source_message_id` BIGINT
- `message_map_id` INT FK -> `garage_forward_message_map.id`
- `reply_markup_snapshot` JSONB，保存 Telegram 按钮完整快照
- `status` VARCHAR(32)：`pending / processing / retryable_failed / succeeded / permanent_failed / uncertain / cancelled`
- `retry_count / max_retries` INT
- `next_retry_at / lease_until / send_started_at / completed_at` TIMESTAMPTZ
- `last_error` TEXT
- UNIQUE(`chat_id`,`source_channel_id`,`source_message_id`)
- 用途：保存实时投递和重试的同一条执行记录；成功后不删除，结果不确定时禁止自动重放。

### `ad_campaigns`
- `id` INT PK
- `chat_id` BIGINT FK
- `created_by_user_id` BIGINT FK -> `tg_users.id`
- `title` VARCHAR(128)
- `content` TEXT
- `enabled` BOOL
- `created_at` TIMESTAMPTZ

## 2) 主键 / 外键关系

- `chat_settings.chat_id` -> `tg_chats.id`
- `chat_members.chat_id` -> `tg_chats.id`；`chat_members.user_id` -> `tg_users.id`
- `points_* / sign_in_logs / moderation_violations / verification_challenges / ad_campaigns` 均通过 `chat_id` 关联群
- `garage_forward_retry_queue.message_map_id` -> `garage_forward_message_map.id`，来源事件唯一键同时约束消息映射和执行记录

## 3) 关键索引契约

- `verification_challenges(timeout_status, timeout_next_retry_at, timeout_lease_until)` 用于到期认领和租约恢复。
- `verification_timeout_attempts(challenge_id, attempt_no)` 唯一，保证追加尝试顺序。
- `garage_forward_retry_queue(chat_id, source_channel_id, source_message_id)` 唯一，保证来源事件幂等。
- `garage_forward_retry_queue(status, next_retry_at, lease_until)` 用于到期认领。
- `scheduled_message_logs(run_key)` 唯一，`status/next_retry_at/lease_until` 支撑执行队列。
- `ad_rotation_history(dispatch_key)` 唯一，`status/next_retry_at/lease_until` 支撑广告派发队列。
- 上述索引、唯一约束、类型、nullable、server default 和外键删除策略均由 Schema Gate 校验。

## 4) 数据增长与性能优化建议

- `points_transactions`、`moderation_violations` 属于增长型表：
  - 按月分区（Postgres 分区表）
  - 或做冷热分层（归档到对象存储/分析库）
- 读多写多场景：
  - 热点群缓存 `chat_settings`（内存/Redis，可扩展）
  - 积分余额通过 `points_accounts` 聚合存储，避免每次扫流水

## 5) ER 关系说明（文字）

- **群**（`tg_chats`）1:1 **群配置**（`chat_settings`）
- **群** 1:N **成员**（`chat_members`），成员关联到 **用户**（`tg_users`）
- **群 + 用户** 1:1 **积分账户**（`points_accounts`），1:N **积分流水**（`points_transactions`）与 **签到记录**（`sign_in_logs`）
- **群 + 用户** 1:N **违规记录**（`moderation_violations`）
- **群 + 用户** 0/1 **验证挑战**（`verification_challenges`）
- **群** 0/1 **订阅**（`chat_subscriptions`）指向 **套餐**（`subscription_plans`）
- **群** 1:N **广告活动**（`ad_campaigns`）
- **来源消息 + 目标群** 1:1 **车库消息映射**，1:1 **车库投递执行记录**



## 2026-10-10 服务修复增量（Alembic 0008–0014）

本节描述候选代码的数据库结构；迁移已在专用本地 PostgreSQL 验证，不表示生产库已升级。

| Revision | 表与变化 | 一致性约束 |
|---|---|---|
| 0008_mall_confirmation | `points_mall_intents`：token、群、购买者、商品、交易条款 JSON、到期时间、order_id | token 主键；order_id 唯一；确认锁意图→商城配置→商品→账户；同意图只扣分一次 |
| 0009_edit_drafts | `edit_drafts`：token、user_id、chat_id、原状态作用域、状态类型、JSON 载荷、创建与过期时间 | 用户和原群绑定；默认 7 天；返回/切群保留草稿；恢复时校验正式配置版本；清理不触及正式配置 |
| 0010_activity_publications | `activity_publications`：token、domain、群、创建者、entity_id、payload、status、message_id、error、updated_at | 发布前先持久化身份；processing 在传输前提交；未知结果不自动重放 |
| 0011_mall_fulfillment | 订单新增 product_snapshot、fulfiller_user_id、assignment_version、fulfillment_note、fulfilled_at；新增 `mall_notifications` | 商品外键改为 RESTRICT；商品删除为软删除；通知唯一键为订单/角色/分配版本；订单与通知创建同一事务 |
| 0012_ui_feedback | `ui_feedback`：token、user_id、text、status、created_at | 失败的页面反馈独立保存，下次打开管理首页展示；不重执行业务 |
| 0013_activity_media | `auction_items.cover_file_id`、`guess_events.cover_media_type` | 预览、正式发布及后续编辑保留媒体类型 |
| 0014_mall_intent_cancel | `points_mall_intents.cancelled_at` | 取消确认与消费意图共用行锁；取消后旧确认按钮不能成交 |

兑换意图状态由 `order_id`、`cancelled_at`、`expires_at` 推导：已消费优先，其次已取消、已过期，其他为待确认。取消不会删除意图，已消费意图不会通过取消按钮退款。

订单历史快照缺失时显示“历史商品/历史信息未记录”，不反填当前商品内容。人工标记发放只记录操作人、说明及时间，不代表买家确认收货。取消/退款沿用订单状态条件和库存恢复规则；已处理状态不能重复退款。

通知状态使用 pending / processing / retryable_failed / succeeded / permanent_failed / uncertain / cancelled。领取、改派与中断恢复统一按照“订单→通知”锁顺序。明确限流按服务端等待时间退避（最多 5 次），权限/内容拒绝转永久失败，网络未知结果不自动重发；管理员接管通知与订单状态独立。

草稿 JSON 中 `__draft_base_version__` 是恢复时的配置指纹；按钮/消息编辑还保留原正文、媒体和按钮快照。保存前锁目标对象并比较快照，冲突时保留草稿。运行时 `ConversationState` 继续表示活跃输入或已选群，不用切换群字段覆盖旧输入类型。

0008–0014 的 downgrade 均拒绝删除业务记录。回退采用保留新表的兼容应用版本或前向修复；不能恢复旧全库快照抹掉新订单、扣分流水或未知发布记录。所有新字段纳入 ORM/Schema Gate，启动前必须完成 Alembic 升级和结构检查。
