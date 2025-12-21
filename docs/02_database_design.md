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
- `created_at` TIMESTAMPTZ
- UNIQUE(`chat_id`,`user_id`)

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

## 3) 索引建议

- 高频查询：`chat_id`、`user_id` 组合索引（已在迁移里加了核心索引）
- `verification_challenges.token`、`expires_at`
- 积分流水按 `chat_id/user_id/created_at` 可加复合索引（后续迭代）

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



