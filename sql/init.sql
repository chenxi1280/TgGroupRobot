-- ============================================
-- Telegram 群管理机器人数据库初始化脚本
-- PostgreSQL 数据库结构定义
-- ============================================

-- ============================================
-- 1. 用户表 (tg_users)
-- 存储 Telegram 用户的基本信息
-- ============================================
CREATE TABLE IF NOT EXISTS tg_users (
    id BIGINT PRIMARY KEY,                    -- Telegram 用户 ID（主键）
    username VARCHAR(64),                     -- 用户名（可为空）
    first_name VARCHAR(128),                 -- 名字
    last_name VARCHAR(128),                  -- 姓氏
    language_code VARCHAR(16),               -- 语言代码（如：zh-CN, en-US）
    created_at TIMESTAMPTZ NOT NULL,         -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL          -- 更新时间（带时区）
);

COMMENT ON TABLE tg_users IS 'Telegram 用户表，存储所有使用机器人的用户信息';
COMMENT ON COLUMN tg_users.id IS 'Telegram 用户 ID，作为主键';
COMMENT ON COLUMN tg_users.username IS 'Telegram 用户名（@username）';
COMMENT ON COLUMN tg_users.first_name IS '用户的名字';
COMMENT ON COLUMN tg_users.last_name IS '用户的姓氏';
COMMENT ON COLUMN tg_users.language_code IS '用户的语言偏好设置';
COMMENT ON COLUMN tg_users.created_at IS '记录创建时间';
COMMENT ON COLUMN tg_users.updated_at IS '记录最后更新时间';

-- ============================================
-- 2. 群组表 (tg_chats)
-- 存储 Telegram 群组/频道的基本信息
-- ============================================
CREATE TABLE IF NOT EXISTS tg_chats (
    id BIGINT PRIMARY KEY,                    -- Telegram 群组/频道 ID（主键）
    type VARCHAR(32) NOT NULL,                -- 群组类型（group/supergroup/channel）
    title VARCHAR(255),                       -- 群组标题
    created_at TIMESTAMPTZ NOT NULL,          -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL           -- 更新时间（带时区）
);

COMMENT ON TABLE tg_chats IS 'Telegram 群组/频道表，存储所有机器人所在的群组信息';
COMMENT ON COLUMN tg_chats.id IS 'Telegram 群组/频道 ID，作为主键';
COMMENT ON COLUMN tg_chats.type IS '群组类型：group（普通群组）、supergroup（超级群组）、channel（频道）';
COMMENT ON COLUMN tg_chats.title IS '群组/频道的标题名称';
COMMENT ON COLUMN tg_chats.created_at IS '记录创建时间';
COMMENT ON COLUMN tg_chats.updated_at IS '记录最后更新时间';

-- ============================================
-- 3. 群组配置表 (chat_settings)
-- 存储每个群组的详细配置信息（多群配置隔离的核心表）
-- ============================================
CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id BIGINT PRIMARY KEY,                                    -- 群组 ID（主键，外键关联 tg_chats.id）
    language VARCHAR(16) NOT NULL,                                 -- 群组默认语言
    sign_enabled BOOLEAN NOT NULL,                                 -- 是否启用签到功能
    sign_points INTEGER NOT NULL,                                  -- 签到奖励积分
    sign_cooldown_hours INTEGER NOT NULL,                          -- 签到冷却时间（小时，MVP 暂未使用）
    verification_enabled BOOLEAN NOT NULL,                         -- 是否启用新人验证
    verification_timeout_seconds INTEGER NOT NULL,                 -- 验证超时时间（秒）
    verification_restrict_can_send BOOLEAN NOT NULL,               -- 验证期间是否限制发送消息
    moderation_enabled BOOLEAN NOT NULL,                           -- 是否启用内容审核
    moderation_block_links BOOLEAN NOT NULL,                       -- 是否阻止链接
    moderation_action VARCHAR(32) NOT NULL,                        -- 审核违规时的处理动作（delete/warn/ban）
    moderation_keywords JSONB NOT NULL,                            -- 审核关键词列表（JSON 数组格式）
    ads_enabled BOOLEAN NOT NULL,                                  -- 是否启用广告功能
    monetization_enabled BOOLEAN NOT NULL,                         -- 是否启用商业化功能
    created_at TIMESTAMPTZ NOT NULL,                               -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间（带时区）
    CONSTRAINT fk_chat_settings_chat_id FOREIGN KEY (chat_id) 
        REFERENCES tg_chats(id) ON DELETE CASCADE                  -- 外键约束：删除群组时级联删除配置
);

COMMENT ON TABLE chat_settings IS '群组配置表，每个群组一份独立配置，实现多群配置隔离';
COMMENT ON COLUMN chat_settings.chat_id IS '群组 ID，与 tg_chats.id 一对一关联';
COMMENT ON COLUMN chat_settings.language IS '群组默认语言设置';
COMMENT ON COLUMN chat_settings.sign_enabled IS '是否启用签到功能';
COMMENT ON COLUMN chat_settings.sign_points IS '每次签到奖励的积分数量';
COMMENT ON COLUMN chat_settings.sign_cooldown_hours IS '签到冷却时间（小时），MVP 暂未使用，预留扩展';
COMMENT ON COLUMN chat_settings.verification_enabled IS '是否启用新人入群验证功能';
COMMENT ON COLUMN chat_settings.verification_timeout_seconds IS '新人验证超时时间（秒），超时后自动处理';
COMMENT ON COLUMN chat_settings.verification_restrict_can_send IS '验证期间是否限制新成员发送消息';
COMMENT ON COLUMN chat_settings.moderation_enabled IS '是否启用内容审核功能';
COMMENT ON COLUMN chat_settings.moderation_block_links IS '是否阻止所有链接消息';
COMMENT ON COLUMN chat_settings.moderation_action IS '审核违规时的处理动作：delete（删除）、warn（警告）、ban（封禁）';
COMMENT ON COLUMN chat_settings.moderation_keywords IS '审核关键词列表，JSONB 格式存储数组';
COMMENT ON COLUMN chat_settings.ads_enabled IS '是否启用广告发布功能';
COMMENT ON COLUMN chat_settings.monetization_enabled IS '是否启用商业化功能（订阅/付费等）';
COMMENT ON COLUMN chat_settings.created_at IS '配置创建时间';
COMMENT ON COLUMN chat_settings.updated_at IS '配置最后更新时间';

-- ============================================
-- 4. 群组成员表 (chat_members)
-- 存储每个群组的成员信息及角色
-- ============================================
CREATE TABLE IF NOT EXISTS chat_members (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    role VARCHAR(16) NOT NULL,                                    -- 成员角色（member/admin/owner）
    joined_at TIMESTAMPTZ,                                        -- 加入群组时间
    updated_at TIMESTAMPTZ NOT NULL,                              -- 更新时间（带时区）
    CONSTRAINT fk_chat_members_chat_id FOREIGN KEY (chat_id) 
        REFERENCES tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除成员
    CONSTRAINT fk_chat_members_user_id FOREIGN KEY (user_id) 
        REFERENCES tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除成员记录
    CONSTRAINT uq_chat_member UNIQUE (chat_id, user_id)           -- 唯一约束：同一群组中同一用户只能有一条记录
);

COMMENT ON TABLE chat_members IS '群组成员表，记录每个群组的成员信息及角色';
COMMENT ON COLUMN chat_members.id IS '自增主键';
COMMENT ON COLUMN chat_members.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN chat_members.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN chat_members.role IS '成员角色：member（普通成员）、admin（管理员）、owner（群主）';
COMMENT ON COLUMN chat_members.joined_at IS '成员加入群组的时间';
COMMENT ON COLUMN chat_members.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_chat_members_chat_id ON chat_members(chat_id);
CREATE INDEX IF NOT EXISTS ix_chat_members_user_id ON chat_members(user_id);

-- ============================================
-- 5. 积分账户表 (points_accounts)
-- 存储每个用户在每个群组中的积分余额（多群隔离）
-- ============================================
CREATE TABLE IF NOT EXISTS points_accounts (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    balance INTEGER NOT NULL,                                      -- 积分余额
    updated_at TIMESTAMPTZ NOT NULL,                              -- 更新时间（带时区）
    CONSTRAINT fk_points_accounts_chat_id FOREIGN KEY (chat_id) 
        REFERENCES tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除账户
    CONSTRAINT fk_points_accounts_user_id FOREIGN KEY (user_id) 
        REFERENCES tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除账户
    CONSTRAINT uq_points_account UNIQUE (chat_id, user_id)        -- 唯一约束：同一群组中同一用户只能有一个账户
);

COMMENT ON TABLE points_accounts IS '积分账户表，存储每个用户在每个群组中的积分余额，实现多群积分隔离';
COMMENT ON COLUMN points_accounts.id IS '自增主键';
COMMENT ON COLUMN points_accounts.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN points_accounts.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN points_accounts.balance IS '用户在该群组中的积分余额';
COMMENT ON COLUMN points_accounts.updated_at IS '账户最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_points_accounts_chat_id ON points_accounts(chat_id);
CREATE INDEX IF NOT EXISTS ix_points_accounts_user_id ON points_accounts(user_id);

-- ============================================
-- 6. 积分交易记录表 (points_transactions)
-- 记录所有积分变动历史（增长型表，建议后续做分区）
-- ============================================
CREATE TABLE IF NOT EXISTS points_transactions (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    txn_type VARCHAR(32) NOT NULL,                                -- 交易类型（sign/reward/deduct/transfer 等）
    amount INTEGER NOT NULL,                                      -- 积分变动数量（正数为增加，负数为减少）
    reason VARCHAR(255),                                          -- 变动原因说明
    created_at TIMESTAMPTZ NOT NULL,                              -- 交易创建时间（带时区）
    CONSTRAINT fk_points_transactions_chat_id FOREIGN KEY (chat_id) 
        REFERENCES tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除交易记录
    CONSTRAINT fk_points_transactions_user_id FOREIGN KEY (user_id) 
        REFERENCES tg_users(id) ON DELETE CASCADE                 -- 外键约束：删除用户时级联删除交易记录
);

COMMENT ON TABLE points_transactions IS '积分交易记录表，记录所有积分变动历史，属于增长型表，建议后续按月分区';
COMMENT ON COLUMN points_transactions.id IS '自增主键';
COMMENT ON COLUMN points_transactions.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN points_transactions.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN points_transactions.txn_type IS '交易类型：sign（签到）、reward（奖励）、deduct（扣除）、transfer（转账）等';
COMMENT ON COLUMN points_transactions.amount IS '积分变动数量，正数表示增加，负数表示减少';
COMMENT ON COLUMN points_transactions.reason IS '积分变动的原因说明';
COMMENT ON COLUMN points_transactions.created_at IS '交易记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_points_transactions_chat_id ON points_transactions(chat_id);
CREATE INDEX IF NOT EXISTS ix_points_transactions_user_id ON points_transactions(user_id);
CREATE INDEX IF NOT EXISTS ix_points_transactions_txn_type ON points_transactions(txn_type);
-- 建议后续添加复合索引：CREATE INDEX ix_points_transactions_chat_user_time ON points_transactions(chat_id, user_id, created_at);

-- ============================================
-- 7. 签到记录表 (sign_in_logs)
-- 记录用户每日签到情况（防止重复签到）
-- ============================================
CREATE TABLE IF NOT EXISTS sign_in_logs (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    sign_date DATE NOT NULL,                                      -- 签到日期（仅日期，不含时间）
    points_awarded INTEGER NOT NULL,                              -- 本次签到奖励的积分
    created_at TIMESTAMPTZ NOT NULL,                               -- 记录创建时间（带时区）
    CONSTRAINT fk_sign_in_logs_chat_id FOREIGN KEY (chat_id) 
        REFERENCES tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除签到记录
    CONSTRAINT fk_sign_in_logs_user_id FOREIGN KEY (user_id) 
        REFERENCES tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除签到记录
    CONSTRAINT uq_sign_in_daily UNIQUE (chat_id, user_id, sign_date)  -- 唯一约束：同一用户在同一群组每天只能签到一次
);

COMMENT ON TABLE sign_in_logs IS '签到记录表，记录用户每日签到情况，防止重复签到';
COMMENT ON COLUMN sign_in_logs.id IS '自增主键';
COMMENT ON COLUMN sign_in_logs.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN sign_in_logs.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN sign_in_logs.sign_date IS '签到日期（仅日期，不含时间）';
COMMENT ON COLUMN sign_in_logs.points_awarded IS '本次签到奖励的积分数量';
COMMENT ON COLUMN sign_in_logs.created_at IS '签到记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_sign_in_logs_chat_id ON sign_in_logs(chat_id);
CREATE INDEX IF NOT EXISTS ix_sign_in_logs_user_id ON sign_in_logs(user_id);

-- ============================================
-- 8. 审核违规记录表 (moderation_violations)
-- 记录内容审核发现的违规行为（增长型表，建议后续做分区）
-- ============================================
CREATE TABLE IF NOT EXISTS moderation_violations (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    message_id INTEGER,                                            -- 违规消息的 ID（Telegram message_id）
    rule VARCHAR(64) NOT NULL,                                    -- 违反的规则类型（keyword/link/spam 等）
    detail TEXT,                                                  -- 违规详情说明
    action VARCHAR(32) NOT NULL,                                  -- 执行的处理动作（delete/warn/ban）
    created_at TIMESTAMPTZ NOT NULL,                              -- 记录创建时间（带时区）
    CONSTRAINT fk_moderation_violations_chat_id FOREIGN KEY (chat_id) 
        REFERENCES tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除违规记录
    CONSTRAINT fk_moderation_violations_user_id FOREIGN KEY (user_id) 
        REFERENCES tg_users(id) ON DELETE CASCADE                 -- 外键约束：删除用户时级联删除违规记录
);

COMMENT ON TABLE moderation_violations IS '审核违规记录表，记录内容审核发现的违规行为，属于增长型表，建议后续按月分区';
COMMENT ON COLUMN moderation_violations.id IS '自增主键';
COMMENT ON COLUMN moderation_violations.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN moderation_violations.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN moderation_violations.message_id IS '违规消息的 Telegram message_id';
COMMENT ON COLUMN moderation_violations.rule IS '违反的规则类型：keyword（关键词）、link（链接）、spam（垃圾信息）等';
COMMENT ON COLUMN moderation_violations.detail IS '违规详情说明，可包含具体的关键词或链接内容';
COMMENT ON COLUMN moderation_violations.action IS '执行的处理动作：delete（删除消息）、warn（警告）、ban（封禁用户）';
COMMENT ON COLUMN moderation_violations.created_at IS '违规记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_moderation_violations_chat_id ON moderation_violations(chat_id);
CREATE INDEX IF NOT EXISTS ix_moderation_violations_user_id ON moderation_violations(user_id);

-- ============================================
-- 9. 验证挑战表 (verification_challenges)
-- 存储新人入群验证的挑战信息
-- ============================================
CREATE TABLE IF NOT EXISTS verification_challenges (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    token VARCHAR(64) NOT NULL,                                   -- 验证令牌（用于验证按钮回调）
    expires_at TIMESTAMPTZ NOT NULL,                              -- 验证过期时间（带时区）
    solved BOOLEAN NOT NULL,                                      -- 是否已解决（完成验证）
    created_at TIMESTAMPTZ NOT NULL,                              -- 记录创建时间（带时区）
    CONSTRAINT fk_verification_challenges_chat_id FOREIGN KEY (chat_id) 
        REFERENCES tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除验证记录
    CONSTRAINT fk_verification_challenges_user_id FOREIGN KEY (user_id) 
        REFERENCES tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除验证记录
    CONSTRAINT uq_verification_active UNIQUE (chat_id, user_id)    -- 唯一约束：同一群组中同一用户只能有一个活跃验证
);

COMMENT ON TABLE verification_challenges IS '验证挑战表，存储新人入群验证的挑战信息';
COMMENT ON COLUMN verification_challenges.id IS '自增主键';
COMMENT ON COLUMN verification_challenges.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN verification_challenges.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN verification_challenges.token IS '验证令牌，用于验证按钮回调，确保安全性';
COMMENT ON COLUMN verification_challenges.expires_at IS '验证过期时间，超时后验证失效';
COMMENT ON COLUMN verification_challenges.solved IS '是否已完成验证（true=已完成，false=待验证）';
COMMENT ON COLUMN verification_challenges.created_at IS '验证记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_verification_challenges_chat_id ON verification_challenges(chat_id);
CREATE INDEX IF NOT EXISTS ix_verification_challenges_user_id ON verification_challenges(user_id);
CREATE INDEX IF NOT EXISTS ix_verification_challenges_token ON verification_challenges(token);
CREATE INDEX IF NOT EXISTS ix_verification_challenges_expires_at ON verification_challenges(expires_at);

-- ============================================
-- 10. 订阅套餐表 (subscription_plans)
-- 存储可用的订阅套餐定义
-- ============================================
CREATE TABLE IF NOT EXISTS subscription_plans (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    code VARCHAR(32) NOT NULL UNIQUE,                             -- 套餐代码（如：free/pro/premium）
    name VARCHAR(64) NOT NULL,                                    -- 套餐名称
    price_cents INTEGER NOT NULL,                                 -- 价格（单位：分）
    duration_days INTEGER NOT NULL,                               -- 套餐时长（天数）
    feature_flags JSONB NOT NULL,                                 -- 功能特性标志（JSON 格式）
    created_at TIMESTAMPTZ NOT NULL                               -- 记录创建时间（带时区）
);

COMMENT ON TABLE subscription_plans IS '订阅套餐表，存储可用的订阅套餐定义';
COMMENT ON COLUMN subscription_plans.id IS '自增主键';
COMMENT ON COLUMN subscription_plans.code IS '套餐代码，唯一标识，如：free（免费）、pro（专业版）、premium（高级版）';
COMMENT ON COLUMN subscription_plans.name IS '套餐显示名称';
COMMENT ON COLUMN subscription_plans.price_cents IS '套餐价格，单位：分（例如：999 表示 9.99 元）';
COMMENT ON COLUMN subscription_plans.duration_days IS '套餐有效期，单位：天';
COMMENT ON COLUMN subscription_plans.feature_flags IS '功能特性标志，JSONB 格式存储，如：{"ads_enabled": true, "custom_bot": true}';
COMMENT ON COLUMN subscription_plans.created_at IS '套餐创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_subscription_plans_code ON subscription_plans(code);

-- ============================================
-- 11. 群组订阅表 (chat_subscriptions)
-- 存储每个群组的订阅信息（一个群组只能有一个活跃订阅）
-- ============================================
CREATE TABLE IF NOT EXISTS chat_subscriptions (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL UNIQUE,                                -- 群组 ID（外键关联 tg_chats.id，唯一约束）
    plan_id INTEGER NOT NULL,                                      -- 套餐 ID（外键关联 subscription_plans.id）
    status VARCHAR(16) NOT NULL,                                  -- 订阅状态（active/expired/cancelled）
    start_at TIMESTAMPTZ NOT NULL,                                -- 订阅开始时间（带时区）
    end_at TIMESTAMPTZ,                                           -- 订阅结束时间（带时区，NULL 表示永久有效）
    created_at TIMESTAMPTZ NOT NULL,                              -- 记录创建时间（带时区）
    CONSTRAINT fk_chat_subscriptions_chat_id FOREIGN KEY (chat_id) 
        REFERENCES tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除订阅
    CONSTRAINT fk_chat_subscriptions_plan_id FOREIGN KEY (plan_id) 
        REFERENCES subscription_plans(id) ON DELETE RESTRICT     -- 外键约束：删除套餐时限制删除（必须先处理订阅）
);

COMMENT ON TABLE chat_subscriptions IS '群组订阅表，存储每个群组的订阅信息，一个群组只能有一个活跃订阅';
COMMENT ON COLUMN chat_subscriptions.id IS '自增主键';
COMMENT ON COLUMN chat_subscriptions.chat_id IS '群组 ID，外键关联 tg_chats.id，唯一约束确保一个群组只有一个订阅';
COMMENT ON COLUMN chat_subscriptions.plan_id IS '套餐 ID，外键关联 subscription_plans.id';
COMMENT ON COLUMN chat_subscriptions.status IS '订阅状态：active（活跃）、expired（已过期）、cancelled（已取消）';
COMMENT ON COLUMN chat_subscriptions.start_at IS '订阅开始时间';
COMMENT ON COLUMN chat_subscriptions.end_at IS '订阅结束时间，NULL 表示永久有效';
COMMENT ON COLUMN chat_subscriptions.created_at IS '订阅记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_chat_subscriptions_chat_id ON chat_subscriptions(chat_id);
CREATE INDEX IF NOT EXISTS ix_chat_subscriptions_status ON chat_subscriptions(status);
CREATE INDEX IF NOT EXISTS ix_chat_subscriptions_end_at ON chat_subscriptions(end_at);

-- ============================================
-- 12. 广告活动表 (ad_campaigns)
-- 存储群组内的广告活动信息
-- ============================================
CREATE TABLE IF NOT EXISTS ad_campaigns (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    created_by_user_id BIGINT,                                    -- 创建者用户 ID（外键关联 tg_users.id，可为空）
    title VARCHAR(128) NOT NULL,                                  -- 广告标题
    content TEXT NOT NULL,                                        -- 广告内容
    enabled BOOLEAN NOT NULL,                                     -- 是否启用
    created_at TIMESTAMPTZ NOT NULL,                              -- 记录创建时间（带时区）
    CONSTRAINT fk_ad_campaigns_chat_id FOREIGN KEY (chat_id) 
        REFERENCES tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除广告
    CONSTRAINT fk_ad_campaigns_created_by_user_id FOREIGN KEY (created_by_user_id) 
        REFERENCES tg_users(id) ON DELETE SET NULL                -- 外键约束：删除用户时将创建者设为 NULL
);

COMMENT ON TABLE ad_campaigns IS '广告活动表，存储群组内的广告活动信息';
COMMENT ON COLUMN ad_campaigns.id IS '自增主键';
COMMENT ON COLUMN ad_campaigns.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN ad_campaigns.created_by_user_id IS '创建广告的用户 ID，外键关联 tg_users.id，删除用户时设为 NULL';
COMMENT ON COLUMN ad_campaigns.title IS '广告标题';
COMMENT ON COLUMN ad_campaigns.content IS '广告正文内容';
COMMENT ON COLUMN ad_campaigns.enabled IS '广告是否启用（true=启用，false=禁用）';
COMMENT ON COLUMN ad_campaigns.created_at IS '广告创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_ad_campaigns_chat_id ON ad_campaigns(chat_id);

-- ============================================
-- 数据库初始化完成
-- ============================================

