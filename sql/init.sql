-- ============================================
-- Telegram 群管理机器人数据库初始化脚本
-- PostgreSQL 数据库结构定义
-- ============================================

-- 创建 bot schema
CREATE SCHEMA IF NOT EXISTS bot;

-- ============================================
-- 1. 用户表 (tg_users)
-- 存储 Telegram 用户的基本信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.tg_users (
    id BIGINT PRIMARY KEY,                    -- Telegram 用户 ID（主键）
    username VARCHAR(64),                     -- 用户名（可为空）
    first_name VARCHAR(128),                 -- 名字
    last_name VARCHAR(128),                  -- 姓氏
    language_code VARCHAR(16),               -- 语言代码（如：zh-CN, en-US）
    created_at TIMESTAMPTZ NOT NULL,         -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL          -- 更新时间（带时区）
);

COMMENT ON TABLE bot.tg_users IS 'Telegram 用户表，存储所有使用机器人的用户信息';
COMMENT ON COLUMN bot.tg_users.id IS 'Telegram 用户 ID，作为主键';
COMMENT ON COLUMN bot.tg_users.username IS 'Telegram 用户名（@username）';
COMMENT ON COLUMN bot.tg_users.first_name IS '用户的名字';
COMMENT ON COLUMN bot.tg_users.last_name IS '用户的姓氏';
COMMENT ON COLUMN bot.tg_users.language_code IS '用户的语言偏好设置';
COMMENT ON COLUMN bot.tg_users.created_at IS '记录创建时间';
COMMENT ON COLUMN bot.tg_users.updated_at IS '记录最后更新时间';

-- ============================================
-- 2. 群组表 (tg_chats)
-- 存储 Telegram 群组/频道的基本信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.tg_chats (
    id BIGINT PRIMARY KEY,                    -- Telegram 群组/频道 ID（主键）
    type VARCHAR(32) NOT NULL,                -- 群组类型（group/supergroup/channel）
    title VARCHAR(255),                       -- 群组标题
    created_at TIMESTAMPTZ NOT NULL,          -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL           -- 更新时间（带时区）
);

COMMENT ON TABLE bot.tg_chats IS 'Telegram 群组/频道表，存储所有机器人所在的群组信息';
COMMENT ON COLUMN bot.tg_chats.id IS 'Telegram 群组/频道 ID，作为主键';
COMMENT ON COLUMN bot.tg_chats.type IS '群组类型：group（普通群组）、supergroup（超级群组）、channel（频道）';
COMMENT ON COLUMN bot.tg_chats.title IS '群组/频道的标题名称';
COMMENT ON COLUMN bot.tg_chats.created_at IS '记录创建时间';
COMMENT ON COLUMN bot.tg_chats.updated_at IS '记录最后更新时间';

-- ============================================
-- 3. 群组配置表 (chat_settings)
-- 存储每个群组的详细配置信息（多群配置隔离的核心表）
-- ============================================
CREATE TABLE IF NOT EXISTS bot.chat_settings (
    chat_id BIGINT PRIMARY KEY,                                    -- 群组 ID（主键，外键关联 tg_chats.id）
    language VARCHAR(16) NOT NULL,                                 -- 群组默认语言
    sign_enabled BOOLEAN NOT NULL,                                 -- 是否启用签到功能
    sign_points INTEGER NOT NULL,                                  -- 签到奖励积分
    sign_cooldown_hours INTEGER NOT NULL,                          -- 签到冷却时间（小时，MVP 暂未使用）
    sign_consecutive_days INTEGER NOT NULL DEFAULT 0,              -- 连续签到奖励门槛天数
    sign_consecutive_bonus INTEGER NOT NULL DEFAULT 0,             -- 连续签到奖励积分
    verification_enabled BOOLEAN NOT NULL,                         -- 是否启用新人验证
    verification_mode VARCHAR(16) NOT NULL DEFAULT 'button',       -- 验证模式（button/math/captcha）
    verification_timeout_seconds INTEGER NOT NULL,                 -- 验证超时时间（秒）
    verification_restrict_can_send BOOLEAN NOT NULL,               -- 验证期间是否限制发送消息
    moderation_enabled BOOLEAN NOT NULL,                           -- 是否启用内容审核
    moderation_block_links BOOLEAN NOT NULL,                       -- 是否阻止链接
    moderation_action VARCHAR(32) NOT NULL,                        -- 审核违规时的处理动作（delete/warn/ban）
    moderation_keywords JSONB NOT NULL,                            -- 审核关键词列表（JSON 数组格式）
    ads_enabled BOOLEAN NOT NULL,                                  -- 是否启用广告功能
    monetization_enabled BOOLEAN NOT NULL,                         -- 是否启用商业化功能
    welcome_enabled BOOLEAN NOT NULL DEFAULT TRUE,                 -- 是否启用进群欢迎
    welcome_message TEXT,                                          -- 自定义欢迎消息模板
    anti_flood_enabled BOOLEAN NOT NULL DEFAULT FALSE,             -- 是否启用反刷屏
    anti_flood_messages INTEGER NOT NULL DEFAULT 5,                -- 触发消息数量
    anti_flood_seconds INTEGER NOT NULL DEFAULT 5,                 -- 时间窗口（秒）
    anti_flood_action VARCHAR(32) NOT NULL DEFAULT 'mute',         -- 惩罚动作（mute/delete/ban）
    anti_flood_mute_duration INTEGER NOT NULL DEFAULT 60,          -- 禁言时长（秒）
    message_points_enabled BOOLEAN NOT NULL DEFAULT FALSE,         -- 是否启用发言积分
    message_points INTEGER NOT NULL DEFAULT 1,                     -- 每次发言获得积分
    message_points_daily_limit INTEGER,                            -- 每日发言积分上限（null=无限制）
    message_min_length INTEGER,                                    -- 最小字数限制（null=无限制）
    invite_points_enabled BOOLEAN NOT NULL DEFAULT FALSE,          -- 是否启用邀请积分
    invite_points INTEGER NOT NULL DEFAULT 1,                      -- 每次邀请获得积分
    invite_points_daily_limit INTEGER,                             -- 每日邀请积分上限（null=无限制）
    invite_link_enabled BOOLEAN NOT NULL DEFAULT TRUE,             -- 是否开启用户生成链接
    invite_link_notify BOOLEAN NOT NULL DEFAULT TRUE,              -- 是否通知新成员加入
    invite_link_expire_days INTEGER,                               -- 链接过期的天数（null=无限制）
    invite_link_max_joins INTEGER,                                 -- 单个链接最大加入人数（null=无限制）
    invite_link_user_limit INTEGER,                                -- 每个用户可生成链接数量上限（null=无限制）
    auto_delete_enabled BOOLEAN NOT NULL DEFAULT FALSE,            -- 是否开启自动删除
    auto_delete_join BOOLEAN NOT NULL DEFAULT FALSE,               -- 自动删除进群消息
    auto_delete_left BOOLEAN NOT NULL DEFAULT FALSE,               -- 自动删除退群消息
    auto_delete_pinned BOOLEAN NOT NULL DEFAULT FALSE,             -- 自动删除置顶消息
    auto_delete_avatar BOOLEAN NOT NULL DEFAULT FALSE,             -- 自动删除修改头像消息
    auto_delete_title BOOLEAN NOT NULL DEFAULT FALSE,              -- 自动删除修改群名消息
    auto_delete_anonymous BOOLEAN NOT NULL DEFAULT FALSE,          -- 自动删除匿名管理员消息
    points_alias VARCHAR(32) NOT NULL DEFAULT '积分',              -- 积分查询命令别名
    points_rank_alias VARCHAR(32) NOT NULL DEFAULT '积分排行',      -- 积分排行命令别名
    created_at TIMESTAMPTZ NOT NULL,                               -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间（带时区）
    CONSTRAINT fk_chat_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE                  -- 外键约束：删除群组时级联删除配置
);

COMMENT ON TABLE bot.chat_settings IS '群组配置表，每个群组一份独立配置，实现多群配置隔离';
COMMENT ON COLUMN bot.chat_settings.chat_id IS '群组 ID，与 tg_chats.id 一对一关联';
COMMENT ON COLUMN bot.chat_settings.language IS '群组默认语言设置';
COMMENT ON COLUMN bot.chat_settings.sign_enabled IS '是否启用签到功能';
COMMENT ON COLUMN bot.chat_settings.sign_points IS '每次签到奖励的积分数量';
COMMENT ON COLUMN bot.chat_settings.sign_cooldown_hours IS '签到冷却时间（小时），MVP 暂未使用，预留扩展';
COMMENT ON COLUMN bot.chat_settings.sign_consecutive_days IS '连续签到多少天后给予额外奖励（0=不启用）';
COMMENT ON COLUMN bot.chat_settings.sign_consecutive_bonus IS '连续签到达到门槛后额外奖励的积分数';
COMMENT ON COLUMN bot.chat_settings.verification_enabled IS '是否启用新人入群验证功能';
COMMENT ON COLUMN bot.chat_settings.verification_mode IS '验证模式：button（按钮验证）、math（数学题）、captcha（验证码）';
COMMENT ON COLUMN bot.chat_settings.verification_timeout_seconds IS '新人验证超时时间（秒），超时后自动处理';
COMMENT ON COLUMN bot.chat_settings.verification_restrict_can_send IS '验证期间是否限制新成员发送消息';
COMMENT ON COLUMN bot.chat_settings.moderation_enabled IS '是否启用内容审核功能';
COMMENT ON COLUMN bot.chat_settings.moderation_block_links IS '是否阻止所有链接消息';
COMMENT ON COLUMN bot.chat_settings.moderation_action IS '审核违规时的处理动作：delete（删除）、warn（警告）、ban（封禁）';
COMMENT ON COLUMN bot.chat_settings.moderation_keywords IS '审核关键词列表，JSONB 格式存储数组';
COMMENT ON COLUMN bot.chat_settings.ads_enabled IS '是否启用广告发布功能';
COMMENT ON COLUMN bot.chat_settings.monetization_enabled IS '是否启用商业化功能（订阅/付费等）';
COMMENT ON COLUMN bot.chat_settings.welcome_enabled IS '是否启用进群欢迎消息';
COMMENT ON COLUMN bot.chat_settings.welcome_message IS '自定义欢迎消息模板，可使用变量如 {username}';
COMMENT ON COLUMN bot.chat_settings.anti_flood_enabled IS '是否启用反刷屏检测';
COMMENT ON COLUMN bot.chat_settings.anti_flood_messages IS '反刷屏触发消息数量';
COMMENT ON COLUMN bot.chat_settings.anti_flood_seconds IS '反刷屏检测时间窗口（秒）';
COMMENT ON COLUMN bot.chat_settings.anti_flood_action IS '反刷屏惩罚动作：mute（禁言）、delete（删除）、ban（封禁）';
COMMENT ON COLUMN bot.chat_settings.anti_flood_mute_duration IS '反刷屏禁言时长（秒）';
COMMENT ON COLUMN bot.chat_settings.message_points_enabled IS '是否启用发言积分功能';
COMMENT ON COLUMN bot.chat_settings.message_points IS '每次发言获得积分数';
COMMENT ON COLUMN bot.chat_settings.message_points_daily_limit IS '每日发言积分上限（NULL=无限制）';
COMMENT ON COLUMN bot.chat_settings.message_min_length IS '发言最小字数限制（NULL=无限制）';
COMMENT ON COLUMN bot.chat_settings.invite_points_enabled IS '是否启用邀请积分功能';
COMMENT ON COLUMN bot.chat_settings.invite_points IS '每邀请一人获得积分数';
COMMENT ON COLUMN bot.chat_settings.invite_points_daily_limit IS '每日邀请积分上限（NULL=无限制）';
COMMENT ON COLUMN bot.chat_settings.invite_link_enabled IS '是否开启用户生成邀请链接功能';
COMMENT ON COLUMN bot.chat_settings.invite_link_notify IS '是否在有人通过链接加入时通知邀请人';
COMMENT ON COLUMN bot.chat_settings.invite_link_expire_days IS '链接有效天数（NULL=永久有效）';
COMMENT ON COLUMN bot.chat_settings.invite_link_max_joins IS '单个链接最大加入人数（NULL=无限制）';
COMMENT ON COLUMN bot.chat_settings.invite_link_user_limit IS '每个用户可生成的链接数量上限（NULL=无限制）';
COMMENT ON COLUMN bot.chat_settings.auto_delete_enabled IS '是否开启自动删除系统消息功能';
COMMENT ON COLUMN bot.chat_settings.auto_delete_join IS '是否自动删除进群消息（xxx joined the group）';
COMMENT ON COLUMN bot.chat_settings.auto_delete_left IS '是否自动删除退群消息（xxx left the group）';
COMMENT ON COLUMN bot.chat_settings.auto_delete_pinned IS '是否自动删除置顶消息';
COMMENT ON COLUMN bot.chat_settings.auto_delete_avatar IS '是否自动删除修改头像消息';
COMMENT ON COLUMN bot.chat_settings.auto_delete_title IS '是否自动删除修改群名消息';
COMMENT ON COLUMN bot.chat_settings.auto_delete_anonymous IS '是否自动删除匿名管理员消息';
COMMENT ON COLUMN bot.chat_settings.points_alias IS '积分查询命令别名（如：积分）';
COMMENT ON COLUMN bot.chat_settings.points_rank_alias IS '积分排行命令别名（如：积分排行）';
COMMENT ON COLUMN bot.chat_settings.created_at IS '配置创建时间';
COMMENT ON COLUMN bot.chat_settings.updated_at IS '配置最后更新时间';

-- ============================================
-- 4. 群组成员表 (chat_members)
-- 存储每个群组的成员信息及角色
-- ============================================
CREATE TABLE IF NOT EXISTS bot.chat_members (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    role VARCHAR(16) NOT NULL,                                    -- 成员角色（member/admin/owner）
    joined_at TIMESTAMPTZ,                                        -- 加入群组时间
    updated_at TIMESTAMPTZ NOT NULL,                              -- 更新时间（带时区）
    CONSTRAINT fk_chat_members_chat_id FOREIGN KEY (chat_id) 
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除成员
    CONSTRAINT fk_chat_members_user_id FOREIGN KEY (user_id) 
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除成员记录
    CONSTRAINT uq_chat_member UNIQUE (chat_id, user_id)           -- 唯一约束：同一群组中同一用户只能有一条记录
);

COMMENT ON TABLE bot.chat_members IS '群组成员表，记录每个群组的成员信息及角色';
COMMENT ON COLUMN bot.chat_members.id IS '自增主键';
COMMENT ON COLUMN bot.chat_members.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.chat_members.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.chat_members.role IS '成员角色：member（普通成员）、admin（管理员）、owner（群主）';
COMMENT ON COLUMN bot.chat_members.joined_at IS '成员加入群组的时间';
COMMENT ON COLUMN bot.chat_members.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_chat_members_chat_id ON bot.chat_members(chat_id);
CREATE INDEX IF NOT EXISTS ix_chat_members_user_id ON bot.chat_members(user_id);

-- ============================================
-- 5. 积分账户表 (points_accounts)
-- 存储每个用户在每个群组中的积分余额（多群隔离）
-- ============================================
CREATE TABLE IF NOT EXISTS bot.points_accounts (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    balance INTEGER NOT NULL,                                      -- 积分余额
    updated_at TIMESTAMPTZ NOT NULL,                              -- 更新时间（带时区）
    CONSTRAINT fk_points_accounts_chat_id FOREIGN KEY (chat_id) 
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除账户
    CONSTRAINT fk_points_accounts_user_id FOREIGN KEY (user_id) 
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除账户
    CONSTRAINT uq_points_account UNIQUE (chat_id, user_id)        -- 唯一约束：同一群组中同一用户只能有一个账户
);

COMMENT ON TABLE bot.points_accounts IS '积分账户表，存储每个用户在每个群组中的积分余额，实现多群积分隔离';
COMMENT ON COLUMN bot.points_accounts.id IS '自增主键';
COMMENT ON COLUMN bot.points_accounts.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.points_accounts.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.points_accounts.balance IS '用户在该群组中的积分余额';
COMMENT ON COLUMN bot.points_accounts.updated_at IS '账户最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_points_accounts_chat_id ON bot.points_accounts(chat_id);
CREATE INDEX IF NOT EXISTS ix_points_accounts_user_id ON bot.points_accounts(user_id);

-- ============================================
-- 6. 积分交易记录表 (points_transactions)
-- 记录所有积分变动历史（增长型表，建议后续做分区）
-- ============================================
CREATE TABLE IF NOT EXISTS bot.points_transactions (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    txn_type VARCHAR(32) NOT NULL,                                -- 交易类型（sign/reward/deduct/transfer 等）
    amount INTEGER NOT NULL,                                      -- 积分变动数量（正数为增加，负数为减少）
    reason VARCHAR(255),                                          -- 变动原因说明
    created_at TIMESTAMPTZ NOT NULL,                              -- 交易创建时间（带时区）
    CONSTRAINT fk_points_transactions_chat_id FOREIGN KEY (chat_id) 
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除交易记录
    CONSTRAINT fk_points_transactions_user_id FOREIGN KEY (user_id) 
        REFERENCES bot.tg_users(id) ON DELETE CASCADE                 -- 外键约束：删除用户时级联删除交易记录
);

COMMENT ON TABLE bot.points_transactions IS '积分交易记录表，记录所有积分变动历史，属于增长型表，建议后续按月分区';
COMMENT ON COLUMN bot.points_transactions.id IS '自增主键';
COMMENT ON COLUMN bot.points_transactions.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.points_transactions.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.points_transactions.txn_type IS '交易类型：sign（签到）、reward（奖励）、deduct（扣除）、transfer（转账）等';
COMMENT ON COLUMN bot.points_transactions.amount IS '积分变动数量，正数表示增加，负数表示减少';
COMMENT ON COLUMN bot.points_transactions.reason IS '积分变动的原因说明';
COMMENT ON COLUMN bot.points_transactions.created_at IS '交易记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_points_transactions_chat_id ON bot.points_transactions(chat_id);
CREATE INDEX IF NOT EXISTS ix_points_transactions_user_id ON bot.points_transactions(user_id);
CREATE INDEX IF NOT EXISTS ix_points_transactions_txn_type ON bot.points_transactions(txn_type);
-- 建议后续添加复合索引：CREATE INDEX ix_points_transactions_chat_user_time ON bot.points_transactions(chat_id, user_id, created_at);

-- ============================================
-- 7. 签到记录表 (sign_in_logs)
-- 记录用户每日签到情况（防止重复签到）
-- ============================================
CREATE TABLE IF NOT EXISTS bot.sign_in_logs (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    sign_date DATE NOT NULL,                                      -- 签到日期（仅日期，不含时间）
    points_awarded INTEGER NOT NULL,                              -- 本次签到奖励的积分
    created_at TIMESTAMPTZ NOT NULL,                               -- 记录创建时间（带时区）
    CONSTRAINT fk_sign_in_logs_chat_id FOREIGN KEY (chat_id) 
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除签到记录
    CONSTRAINT fk_sign_in_logs_user_id FOREIGN KEY (user_id) 
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除签到记录
    CONSTRAINT uq_sign_in_daily UNIQUE (chat_id, user_id, sign_date)  -- 唯一约束：同一用户在同一群组每天只能签到一次
);

COMMENT ON TABLE bot.sign_in_logs IS '签到记录表，记录用户每日签到情况，防止重复签到';
COMMENT ON COLUMN bot.sign_in_logs.id IS '自增主键';
COMMENT ON COLUMN bot.sign_in_logs.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.sign_in_logs.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.sign_in_logs.sign_date IS '签到日期（仅日期，不含时间）';
COMMENT ON COLUMN bot.sign_in_logs.points_awarded IS '本次签到奖励的积分数量';
COMMENT ON COLUMN bot.sign_in_logs.created_at IS '签到记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_sign_in_logs_chat_id ON bot.sign_in_logs(chat_id);
CREATE INDEX IF NOT EXISTS ix_sign_in_logs_user_id ON bot.sign_in_logs(user_id);

-- ============================================
-- 7.5. 用户每日统计表 (user_daily_stats)
-- 用于发言积分、邀请积分的每日上限控制，以及连续签到统计
-- ============================================
CREATE TABLE IF NOT EXISTS bot.user_daily_stats (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    stat_date DATE NOT NULL,                                      -- 统计日期（仅日期，不含时间）
    message_points_earned INTEGER NOT NULL DEFAULT 0,             -- 今日发言已获得积分
    invite_points_earned INTEGER NOT NULL DEFAULT 0,              -- 今日邀请已获得积分
    invites_count INTEGER NOT NULL DEFAULT 0,                     -- 今日邀请人数
    consecutive_sign_days INTEGER NOT NULL DEFAULT 0,             -- 连续签到天数
    created_at TIMESTAMPTZ NOT NULL,                              -- 记录创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                              -- 更新时间（带时区）
    CONSTRAINT fk_user_daily_stats_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除统计
    CONSTRAINT fk_user_daily_stats_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除统计
    CONSTRAINT uq_user_daily_stat UNIQUE (chat_id, user_id, stat_date) -- 唯一约束：同一用户同一群组每天只有一条统计
);

COMMENT ON TABLE bot.user_daily_stats IS '用户每日统计表，用于发言积分、邀请积分的每日上限控制，以及连续签到统计';
COMMENT ON COLUMN bot.user_daily_stats.id IS '自增主键';
COMMENT ON COLUMN bot.user_daily_stats.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.user_daily_stats.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.user_daily_stats.stat_date IS '统计日期（仅日期，不含时间）';
COMMENT ON COLUMN bot.user_daily_stats.message_points_earned IS '今日发言已获得积分数';
COMMENT ON COLUMN bot.user_daily_stats.invite_points_earned IS '今日邀请已获得积分数';
COMMENT ON COLUMN bot.user_daily_stats.invites_count IS '今日邀请人数';
COMMENT ON COLUMN bot.user_daily_stats.consecutive_sign_days IS '连续签到天数';
COMMENT ON COLUMN bot.user_daily_stats.created_at IS '统计记录创建时间';
COMMENT ON COLUMN bot.user_daily_stats.updated_at IS '统计记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_user_daily_stats_chat_id ON bot.user_daily_stats(chat_id);
CREATE INDEX IF NOT EXISTS ix_user_daily_stats_user_id ON bot.user_daily_stats(user_id);
CREATE INDEX IF NOT EXISTS ix_user_daily_stats_stat_date ON bot.user_daily_stats(stat_date);

-- ============================================
-- 8. 审核违规记录表 (moderation_violations)
-- 记录内容审核发现的违规行为（增长型表，建议后续做分区）
-- ============================================
CREATE TABLE IF NOT EXISTS bot.moderation_violations (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    message_id INTEGER,                                            -- 违规消息的 ID（Telegram message_id）
    rule VARCHAR(64) NOT NULL,                                    -- 违反的规则类型（keyword/link/spam 等）
    detail TEXT,                                                  -- 违规详情说明
    action VARCHAR(32) NOT NULL,                                  -- 执行的处理动作（delete/warn/ban）
    created_at TIMESTAMPTZ NOT NULL,                              -- 记录创建时间（带时区）
    CONSTRAINT fk_moderation_violations_chat_id FOREIGN KEY (chat_id) 
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除违规记录
    CONSTRAINT fk_moderation_violations_user_id FOREIGN KEY (user_id) 
        REFERENCES bot.tg_users(id) ON DELETE CASCADE                 -- 外键约束：删除用户时级联删除违规记录
);

COMMENT ON TABLE bot.moderation_violations IS '审核违规记录表，记录内容审核发现的违规行为，属于增长型表，建议后续按月分区';
COMMENT ON COLUMN bot.moderation_violations.id IS '自增主键';
COMMENT ON COLUMN bot.moderation_violations.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.moderation_violations.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.moderation_violations.message_id IS '违规消息的 Telegram message_id';
COMMENT ON COLUMN bot.moderation_violations.rule IS '违反的规则类型：keyword（关键词）、link（链接）、spam（垃圾信息）等';
COMMENT ON COLUMN bot.moderation_violations.detail IS '违规详情说明，可包含具体的关键词或链接内容';
COMMENT ON COLUMN bot.moderation_violations.action IS '执行的处理动作：delete（删除消息）、warn（警告）、ban（封禁用户）';
COMMENT ON COLUMN bot.moderation_violations.created_at IS '违规记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_moderation_violations_chat_id ON bot.moderation_violations(chat_id);
CREATE INDEX IF NOT EXISTS ix_moderation_violations_user_id ON bot.moderation_violations(user_id);

-- ============================================
-- 9. 验证挑战表 (verification_challenges)
-- 存储新人入群验证的挑战信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.verification_challenges (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    token VARCHAR(64) NOT NULL,                                   -- 验证令牌（用于验证按钮回调）
    expires_at TIMESTAMPTZ NOT NULL,                              -- 验证过期时间（带时区）
    solved BOOLEAN NOT NULL,                                      -- 是否已解决（完成验证）
    verification_type VARCHAR(16) NOT NULL DEFAULT 'button',      -- 验证类型（button/math/captcha）
    question TEXT,                                               -- 验证问题（数学题等）
    answer VARCHAR(64),                                          -- 答案
    created_at TIMESTAMPTZ NOT NULL,                              -- 记录创建时间（带时区）
    CONSTRAINT fk_verification_challenges_chat_id FOREIGN KEY (chat_id) 
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除验证记录
    CONSTRAINT fk_verification_challenges_user_id FOREIGN KEY (user_id) 
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除验证记录
    CONSTRAINT uq_verification_active UNIQUE (chat_id, user_id)    -- 唯一约束：同一群组中同一用户只能有一个活跃验证
);

COMMENT ON TABLE bot.verification_challenges IS '验证挑战表，存储新人入群验证的挑战信息';
COMMENT ON COLUMN bot.verification_challenges.id IS '自增主键';
COMMENT ON COLUMN bot.verification_challenges.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.verification_challenges.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.verification_challenges.token IS '验证令牌，用于验证按钮回调，确保安全性';
COMMENT ON COLUMN bot.verification_challenges.expires_at IS '验证过期时间，超时后验证失效';
COMMENT ON COLUMN bot.verification_challenges.solved IS '是否已完成验证（true=已完成，false=待验证）';
COMMENT ON COLUMN bot.verification_challenges.verification_type IS '验证类型：button（按钮验证）、math（数学题）、captcha（验证码）';
COMMENT ON COLUMN bot.verification_challenges.question IS '验证问题，用于数学题模式等';
COMMENT ON COLUMN bot.verification_challenges.answer IS '验证答案，用于验证用户输入';
COMMENT ON COLUMN bot.verification_challenges.created_at IS '验证记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_verification_challenges_chat_id ON bot.verification_challenges(chat_id);
CREATE INDEX IF NOT EXISTS ix_verification_challenges_user_id ON bot.verification_challenges(user_id);
CREATE INDEX IF NOT EXISTS ix_verification_challenges_token ON bot.verification_challenges(token);
CREATE INDEX IF NOT EXISTS ix_verification_challenges_expires_at ON bot.verification_challenges(expires_at);

-- ============================================
-- 10. 订阅套餐表 (subscription_plans)
-- 存储可用的订阅套餐定义
-- ============================================
CREATE TABLE IF NOT EXISTS bot.subscription_plans (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    code VARCHAR(32) NOT NULL UNIQUE,                             -- 套餐代码（如：free/pro/premium）
    name VARCHAR(64) NOT NULL,                                    -- 套餐名称
    price_cents INTEGER NOT NULL,                                 -- 价格（单位：分）
    duration_days INTEGER NOT NULL,                               -- 套餐时长（天数）
    feature_flags JSONB NOT NULL,                                 -- 功能特性标志（JSON 格式）
    created_at TIMESTAMPTZ NOT NULL                               -- 记录创建时间（带时区）
);

COMMENT ON TABLE bot.subscription_plans IS '订阅套餐表，存储可用的订阅套餐定义';
COMMENT ON COLUMN bot.subscription_plans.id IS '自增主键';
COMMENT ON COLUMN bot.subscription_plans.code IS '套餐代码，唯一标识，如：free（免费）、pro（专业版）、premium（高级版）';
COMMENT ON COLUMN bot.subscription_plans.name IS '套餐显示名称';
COMMENT ON COLUMN bot.subscription_plans.price_cents IS '套餐价格，单位：分（例如：999 表示 9.99 元）';
COMMENT ON COLUMN bot.subscription_plans.duration_days IS '套餐有效期，单位：天';
COMMENT ON COLUMN bot.subscription_plans.feature_flags IS '功能特性标志，JSONB 格式存储，如：{"ads_enabled": true, "custom_bot": true}';
COMMENT ON COLUMN bot.subscription_plans.created_at IS '套餐创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_subscription_plans_code ON bot.subscription_plans(code);

-- ============================================
-- 11. 群组订阅表 (chat_subscriptions)
-- 存储每个群组的订阅信息（一个群组只能有一个活跃订阅）
-- ============================================
CREATE TABLE IF NOT EXISTS bot.chat_subscriptions (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL UNIQUE,                                -- 群组 ID（外键关联 tg_chats.id，唯一约束）
    plan_id INTEGER NOT NULL,                                      -- 套餐 ID（外键关联 subscription_plans.id）
    status VARCHAR(16) NOT NULL,                                  -- 订阅状态（active/expired/cancelled）
    start_at TIMESTAMPTZ NOT NULL,                                -- 订阅开始时间（带时区）
    end_at TIMESTAMPTZ,                                           -- 订阅结束时间（带时区，NULL 表示永久有效）
    created_at TIMESTAMPTZ NOT NULL,                              -- 记录创建时间（带时区）
    CONSTRAINT fk_chat_subscriptions_chat_id FOREIGN KEY (chat_id) 
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除订阅
    CONSTRAINT fk_chat_subscriptions_plan_id FOREIGN KEY (plan_id) 
        REFERENCES bot.subscription_plans(id) ON DELETE RESTRICT     -- 外键约束：删除套餐时限制删除（必须先处理订阅）
);

COMMENT ON TABLE bot.chat_subscriptions IS '群组订阅表，存储每个群组的订阅信息，一个群组只能有一个活跃订阅';
COMMENT ON COLUMN bot.chat_subscriptions.id IS '自增主键';
COMMENT ON COLUMN bot.chat_subscriptions.chat_id IS '群组 ID，外键关联 tg_chats.id，唯一约束确保一个群组只有一个订阅';
COMMENT ON COLUMN bot.chat_subscriptions.plan_id IS '套餐 ID，外键关联 subscription_plans.id';
COMMENT ON COLUMN bot.chat_subscriptions.status IS '订阅状态：active（活跃）、expired（已过期）、cancelled（已取消）';
COMMENT ON COLUMN bot.chat_subscriptions.start_at IS '订阅开始时间';
COMMENT ON COLUMN bot.chat_subscriptions.end_at IS '订阅结束时间，NULL 表示永久有效';
COMMENT ON COLUMN bot.chat_subscriptions.created_at IS '订阅记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_chat_subscriptions_chat_id ON bot.chat_subscriptions(chat_id);
CREATE INDEX IF NOT EXISTS ix_chat_subscriptions_status ON bot.chat_subscriptions(status);
CREATE INDEX IF NOT EXISTS ix_chat_subscriptions_end_at ON bot.chat_subscriptions(end_at);

-- ============================================
-- 12. 广告活动表 (ad_campaigns)
-- 存储群组内的广告活动信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.ad_campaigns (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    created_by_user_id BIGINT,                                    -- 创建者用户 ID（外键关联 tg_users.id，可为空）
    title VARCHAR(128) NOT NULL,                                  -- 广告标题
    content TEXT NOT NULL,                                        -- 广告内容
    image_file_id VARCHAR(256),                                   -- Telegram 图片文件ID
    image_url TEXT,                                             -- 图片URL
    has_image BOOLEAN NOT NULL DEFAULT FALSE,                    -- 是否包含图片
    schedule_time TIMESTAMPTZ,                                   -- 定时推送时间（带时区）
    frequency VARCHAR(32),                                        -- 推送频次（once/daily/weekly/monthly）
    last_sent_at TIMESTAMPTZ,                                    -- 上次发送时间（带时区）
    send_locked BOOLEAN NOT NULL DEFAULT FALSE,                   -- 发送锁定（防重机制）
    enabled BOOLEAN NOT NULL,                                     -- 是否启用
    start_time TIMESTAMPTZ,                                      -- 开始推送时间（带时区，支持自定义推送间隔）
    interval_hours INTEGER,                                       -- 推送间隔（小时），如24表示每24小时推送一次
    max_send_count INTEGER,                                       -- 最大推送次数，NULL表示无限制
    send_count INTEGER NOT NULL DEFAULT 0,                       -- 已推送次数
    created_at TIMESTAMPTZ NOT NULL,                             -- 记录创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                             -- 记录更新时间（带时区）
    CONSTRAINT fk_ad_campaigns_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除广告
    CONSTRAINT fk_ad_campaigns_created_by_user_id FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL                -- 外键约束：删除用户时将创建者设为 NULL
);

COMMENT ON TABLE bot.ad_campaigns IS '广告活动表，存储群组内的广告活动信息';
COMMENT ON COLUMN bot.ad_campaigns.id IS '自增主键';
COMMENT ON COLUMN bot.ad_campaigns.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.ad_campaigns.created_by_user_id IS '创建广告的用户 ID，外键关联 tg_users.id，删除用户时设为 NULL';
COMMENT ON COLUMN bot.ad_campaigns.title IS '广告标题';
COMMENT ON COLUMN bot.ad_campaigns.content IS '广告正文内容';
COMMENT ON COLUMN bot.ad_campaigns.image_file_id IS 'Telegram 图片文件ID，用于发送图片消息';
COMMENT ON COLUMN bot.ad_campaigns.image_url IS '图片URL，用于存储外部图片链接';
COMMENT ON COLUMN bot.ad_campaigns.has_image IS '是否包含图片（true=有图片，false=无图片）';
COMMENT ON COLUMN bot.ad_campaigns.schedule_time IS '定时推送时间，NULL表示立即发送';
COMMENT ON COLUMN bot.ad_campaigns.frequency IS '推送频次：once（单次）、daily（每天）、weekly（每周）、monthly（每月）';
COMMENT ON COLUMN bot.ad_campaigns.last_sent_at IS '上次发送时间，用于频次控制';
COMMENT ON COLUMN bot.ad_campaigns.send_locked IS '发送锁定标志，用于防止重复发送';
COMMENT ON COLUMN bot.ad_campaigns.enabled IS '广告是否启用（true=启用，false=禁用）';
COMMENT ON COLUMN bot.ad_campaigns.start_time IS '开始推送时间，NULL表示立即开始';
COMMENT ON COLUMN bot.ad_campaigns.interval_hours IS '推送间隔（小时），如24表示每24小时推送一次，NULL表示不重复推送';
COMMENT ON COLUMN bot.ad_campaigns.max_send_count IS '最大推送次数，NULL表示无限制';
COMMENT ON COLUMN bot.ad_campaigns.send_count IS '已推送次数';
COMMENT ON COLUMN bot.ad_campaigns.created_at IS '广告创建时间';
COMMENT ON COLUMN bot.ad_campaigns.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_ad_campaigns_chat_id ON bot.ad_campaigns(chat_id);
CREATE INDEX IF NOT EXISTS ix_ad_campaigns_schedule_time ON bot.ad_campaigns(schedule_time);
CREATE INDEX IF NOT EXISTS ix_ad_campaigns_enabled ON bot.ad_campaigns(enabled);

-- ============================================
-- 13. 对话状态表 (conversation_states)
-- 存储用户对话状态，用于多步骤交互
-- ============================================
CREATE TABLE IF NOT EXISTS bot.conversation_states (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    state_type VARCHAR(32) NOT NULL,                              -- 状态类型
    state_data JSONB NOT NULL DEFAULT '{}',                       -- 状态数据（JSONB 格式）
    created_at TIMESTAMPTZ NOT NULL,                              -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                              -- 更新时间（带时区）
    CONSTRAINT fk_conversation_states_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除状态
    CONSTRAINT fk_conversation_states_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除状态
    CONSTRAINT uq_conversation_state UNIQUE (chat_id, user_id)    -- 唯一约束：同一群组中同一用户只能有一个状态
);

COMMENT ON TABLE bot.conversation_states IS '对话状态表，存储用户对话状态，用于多步骤交互';
COMMENT ON COLUMN bot.conversation_states.id IS '自增主键';
COMMENT ON COLUMN bot.conversation_states.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.conversation_states.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.conversation_states.state_type IS '状态类型，标识当前处于什么对话流程';
COMMENT ON COLUMN bot.conversation_states.state_data IS '状态数据，JSONB 格式存储对话过程中的临时数据';
COMMENT ON COLUMN bot.conversation_states.created_at IS '记录创建时间';
COMMENT ON COLUMN bot.conversation_states.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_conversation_states_chat_id ON bot.conversation_states(chat_id);
CREATE INDEX IF NOT EXISTS ix_conversation_states_user_id ON bot.conversation_states(user_id);
CREATE INDEX IF NOT EXISTS ix_conversation_states_state_type ON bot.conversation_states(state_type);

-- ============================================
-- 14. 抽奖表 (lotteries)
-- 存储群组内的抽奖活动信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.lotteries (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    created_by_user_id BIGINT,                                    -- 创建者用户 ID（外键关联 tg_users.id，可为空）
    title VARCHAR(128) NOT NULL DEFAULT '通用抽奖',                -- 抽奖标题
    description TEXT,                                             -- 抽奖描述说明
    draw_time TIMESTAMPTZ NOT NULL,                               -- 开奖时间（带时区）
    prizes JSONB NOT NULL DEFAULT '[]',                           -- 奖品列表（JSONB 数组格式）
    draw_mode VARCHAR(16) NOT NULL DEFAULT 'manual',              -- 开奖模式（random=随机开奖，manual=手动指定中奖人）
    status VARCHAR(16) NOT NULL DEFAULT 'pending',                -- 抽奖状态（pending/completed/cancelled）
    message_id INTEGER,                                           -- 抽奖消息的 Telegram message_id
    -- 参与限制条件
    min_points INTEGER NOT NULL DEFAULT 0,                        -- 最低积分要求（0表示无限制）
    max_participants INTEGER NOT NULL DEFAULT 0,                  -- 最大参与人数（0表示无限制）
    participation_cost INTEGER NOT NULL DEFAULT 0,                -- 参与费用（积分，0表示免费）
    join_start_time TIMESTAMPTZ,                                  -- 参与开始时间（NULL表示创建后立即可参与）
    join_end_time TIMESTAMPTZ,                                    -- 参与结束时间（NULL表示到开奖时间前都可参与）
    requirement_days INTEGER NOT NULL DEFAULT 0,                  -- 入群天数要求（0表示无限制）
    created_at TIMESTAMPTZ NOT NULL,                              -- 创建时间（带时区）
    drawn_at TIMESTAMPTZ,                                         -- 实际开奖时间（带时区）
    CONSTRAINT fk_lotteries_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                -- 外键约束：删除群组时级联删除抽奖
    CONSTRAINT fk_lotteries_created_by_user_id FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL                -- 外键约束：删除用户时将创建者设为 NULL
);

COMMENT ON TABLE bot.lotteries IS '抽奖表，存储群组内的抽奖活动信息';
COMMENT ON COLUMN bot.lotteries.id IS '自增主键';
COMMENT ON COLUMN bot.lotteries.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.lotteries.created_by_user_id IS '创建抽奖的用户 ID，外键关联 tg_users.id，删除用户时设为 NULL';
COMMENT ON COLUMN bot.lotteries.title IS '抽奖标题，默认为"通用抽奖"';
COMMENT ON COLUMN bot.lotteries.description IS '抽奖描述说明，可包含活动详情、规则等';
COMMENT ON COLUMN bot.lotteries.draw_time IS '计划开奖时间';
COMMENT ON COLUMN bot.lotteries.prizes IS '奖品列表，JSONB 数组格式存储，如：[{"name": "一等奖", "quantity": 1}]';
COMMENT ON COLUMN bot.lotteries.draw_mode IS '开奖模式：random（随机开奖）、manual（手动指定中奖人）';
COMMENT ON COLUMN bot.lotteries.status IS '抽奖状态：pending（待开奖）、completed（已完成）、cancelled（已取消）';
COMMENT ON COLUMN bot.lotteries.message_id IS '抽奖消息的 Telegram message_id，用于更新消息';
COMMENT ON COLUMN bot.lotteries.min_points IS '参与抽奖的最低积分要求，0表示无限制';
COMMENT ON COLUMN bot.lotteries.max_participants IS '最大参与人数，0表示无限制';
COMMENT ON COLUMN bot.lotteries.participation_cost IS '参与抽奖需要消耗的积分，0表示免费参与';
COMMENT ON COLUMN bot.lotteries.join_start_time IS '参与开始时间，NULL表示创建后立即可参与';
COMMENT ON COLUMN bot.lotteries.join_end_time IS '参与结束时间，NULL表示到开奖时间前都可参与';
COMMENT ON COLUMN bot.lotteries.requirement_days IS '入群天数要求，0表示无限制';
COMMENT ON COLUMN bot.lotteries.created_at IS '抽奖创建时间';
COMMENT ON COLUMN bot.lotteries.drawn_at IS '实际开奖时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_lotteries_chat_id ON bot.lotteries(chat_id);
CREATE INDEX IF NOT EXISTS ix_lotteries_draw_time ON bot.lotteries(draw_time);
CREATE INDEX IF NOT EXISTS ix_lotteries_status ON bot.lotteries(status);

-- ============================================
-- 15. 抽奖参与者表 (lottery_participants)
-- 存储参与抽奖的用户信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.lottery_participants (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    lottery_id INTEGER NOT NULL,                                  -- 抽奖 ID（外键关联 lotteries.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    points_balance INTEGER NOT NULL DEFAULT 0,                    -- 参与时的积分余额（记录快照）
    created_at TIMESTAMPTZ NOT NULL,                              -- 参与时间（带时区）
    CONSTRAINT fk_lottery_participants_lottery_id FOREIGN KEY (lottery_id)
        REFERENCES bot.lotteries(id) ON DELETE CASCADE,               -- 外键约束：删除抽奖时级联删除参与者
    CONSTRAINT fk_lottery_participants_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除用户时级联删除参与记录
    CONSTRAINT uq_lottery_participant UNIQUE (lottery_id, user_id) -- 唯一约束：同一用户在同一抽奖中只能参与一次
);

COMMENT ON TABLE bot.lottery_participants IS '抽奖参与者表，存储参与抽奖的用户信息';
COMMENT ON COLUMN bot.lottery_participants.id IS '自增主键';
COMMENT ON COLUMN bot.lottery_participants.lottery_id IS '抽奖 ID，外键关联 lotteries.id';
COMMENT ON COLUMN bot.lottery_participants.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.lottery_participants.points_balance IS '参与时的积分余额快照，用于审计';
COMMENT ON COLUMN bot.lottery_participants.created_at IS '用户参与抽奖的时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_lottery_participants_lottery_id ON bot.lottery_participants(lottery_id);
CREATE INDEX IF NOT EXISTS ix_lottery_participants_user_id ON bot.lottery_participants(user_id);

-- ============================================
-- 16. 抽奖中奖记录表 (lottery_winners)
-- 存储抽奖的中奖结果
-- ============================================
CREATE TABLE IF NOT EXISTS bot.lottery_winners (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    lottery_id INTEGER NOT NULL,                                  -- 抽奖 ID（外键关联 lotteries.id）
    user_id BIGINT NOT NULL,                                      -- 用户 ID（外键关联 tg_users.id）
    prize_name VARCHAR(255) NOT NULL,                             -- 中奖奖品名称
    prize_index INTEGER NOT NULL,                                 -- 奖品索引（对应 prizes 数组中的位置）
    created_at TIMESTAMPTZ NOT NULL,                              -- 中奖时间（带时区）
    CONSTRAINT fk_lottery_winners_lottery_id FOREIGN KEY (lottery_id)
        REFERENCES bot.lotteries(id) ON DELETE CASCADE,               -- 外键约束：删除抽奖时级联删除中奖记录
    CONSTRAINT fk_lottery_winners_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE                 -- 外键约束：删除用户时级联删除中奖记录
);

COMMENT ON TABLE bot.lottery_winners IS '抽奖中奖记录表，存储抽奖的中奖结果';
COMMENT ON COLUMN bot.lottery_winners.id IS '自增主键';
COMMENT ON COLUMN bot.lottery_winners.lottery_id IS '抽奖 ID，外键关联 lotteries.id';
COMMENT ON COLUMN bot.lottery_winners.user_id IS '中奖用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.lottery_winners.prize_name IS '中奖奖品名称，如"1USDT"';
COMMENT ON COLUMN bot.lottery_winners.prize_index IS '奖品索引，对应 lotteries.prizes 数组中的位置，从0开始';
COMMENT ON COLUMN bot.lottery_winners.created_at IS '中奖时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_lottery_winners_lottery_id ON bot.lottery_winners(lottery_id);
CREATE INDEX IF NOT EXISTS ix_lottery_winners_user_id ON bot.lottery_winners(user_id);

-- ============================================
-- 17. 定时消息表 (scheduled_messages)
-- 存储定时发送的消息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.scheduled_messages (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    created_by_user_id BIGINT,                                   -- 创建者用户 ID（外键关联 tg_users.id，可为空）
    content TEXT NOT NULL,                                       -- 消息内容
    schedule_type VARCHAR(32) NOT NULL DEFAULT 'none',           -- 定时类型（none/daily/weekly/custom）
    interval_minutes INTEGER,                                    -- 自定义间隔分钟数
    is_active BOOLEAN NOT NULL DEFAULT TRUE,                     -- 是否激活
    next_send_time TIMESTAMPTZ NOT NULL,                         -- 下次发送时间（带时区）
    last_sent_at TIMESTAMPTZ,                                   -- 上次发送时间（带时区）
    send_count INTEGER NOT NULL DEFAULT 0,                      -- 已发送次数
    repeat_enabled BOOLEAN NOT NULL DEFAULT FALSE,              -- 是否重复发送
    created_at TIMESTAMPTZ NOT NULL,                             -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                             -- 更新时间（带时区）
    CONSTRAINT fk_scheduled_messages_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,               -- 外键约束：删除群组时级联删除定时消息
    CONSTRAINT fk_scheduled_messages_created_by_user_id FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL               -- 外键约束：删除用户时将创建者设为 NULL
);

COMMENT ON TABLE bot.scheduled_messages IS '定时消息表，存储定时发送的消息';
COMMENT ON COLUMN bot.scheduled_messages.id IS '自增主键';
COMMENT ON COLUMN bot.scheduled_messages.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.scheduled_messages.created_by_user_id IS '创建消息的用户 ID，外键关联 tg_users.id，删除用户时设为 NULL';
COMMENT ON COLUMN bot.scheduled_messages.content IS '消息内容';
COMMENT ON COLUMN bot.scheduled_messages.schedule_type IS '定时类型：none（一次性）、daily（每天）、weekly（每周）、custom（自定义间隔）';
COMMENT ON COLUMN bot.scheduled_messages.interval_minutes IS '自定义间隔分钟数';
COMMENT ON COLUMN bot.scheduled_messages.is_active IS '是否激活（true=启用，false=禁用）';
COMMENT ON COLUMN bot.scheduled_messages.next_send_time IS '下次发送时间';
COMMENT ON COLUMN bot.scheduled_messages.last_sent_at IS '上次发送时间';
COMMENT ON COLUMN bot.scheduled_messages.send_count IS '已发送次数统计';
COMMENT ON COLUMN bot.scheduled_messages.repeat_enabled IS '是否重复发送（true=重复，false=只发送一次）';
COMMENT ON COLUMN bot.scheduled_messages.created_at IS '消息创建时间';
COMMENT ON COLUMN bot.scheduled_messages.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_scheduled_messages_chat_id ON bot.scheduled_messages(chat_id);
CREATE INDEX IF NOT EXISTS ix_scheduled_messages_schedule_type ON bot.scheduled_messages(schedule_type);
CREATE INDEX IF NOT EXISTS ix_scheduled_messages_is_active ON bot.scheduled_messages(is_active);
CREATE INDEX IF NOT EXISTS ix_scheduled_messages_next_send_time ON bot.scheduled_messages(next_send_time);

-- ============================================
-- 18. 自动回复规则表 (auto_reply_rules)
-- 存储自动回复规则
-- ============================================
CREATE TABLE IF NOT EXISTS bot.auto_reply_rules (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    created_by_user_id BIGINT,                                   -- 创建者用户 ID（外键关联 tg_users.id，可为空）
    keywords JSONB NOT NULL DEFAULT '[]',                        -- 触发关键词列表（JSON 数组格式）
    reply_content TEXT NOT NULL,                                 -- 回复内容
    match_type VARCHAR(16) NOT NULL DEFAULT 'contains',          -- 匹配类型（contains/exact/regex）
    is_active BOOLEAN NOT NULL DEFAULT TRUE,                     -- 是否激活
    match_count INTEGER NOT NULL DEFAULT 0,                      -- 匹配次数统计
    case_sensitive BOOLEAN NOT NULL DEFAULT FALSE,               -- 是否区分大小写
    created_at TIMESTAMPTZ NOT NULL,                             -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                             -- 更新时间（带时区）
    CONSTRAINT fk_auto_reply_rules_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,               -- 外键约束：删除群组时级联删除规则
    CONSTRAINT fk_auto_reply_rules_created_by_user_id FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL               -- 外键约束：删除用户时将创建者设为 NULL
);

COMMENT ON TABLE bot.auto_reply_rules IS '自动回复规则表，存储群组的自动回复规则';
COMMENT ON COLUMN bot.auto_reply_rules.id IS '自增主键';
COMMENT ON COLUMN bot.auto_reply_rules.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.auto_reply_rules.created_by_user_id IS '创建规则的用户 ID，外键关联 tg_users.id，删除用户时设为 NULL';
COMMENT ON COLUMN bot.auto_reply_rules.keywords IS '触发关键词列表，JSONB 数组格式存储';
COMMENT ON COLUMN bot.auto_reply_rules.reply_content IS '自动回复的内容';
COMMENT ON COLUMN bot.auto_reply_rules.match_type IS '匹配类型：contains（包含匹配）、exact（精确匹配）、regex（正则表达式）';
COMMENT ON COLUMN bot.auto_reply_rules.is_active IS '是否激活（true=启用，false=禁用）';
COMMENT ON COLUMN bot.auto_reply_rules.match_count IS '规则被触发的次数统计';
COMMENT ON COLUMN bot.auto_reply_rules.case_sensitive IS '是否区分大小写';
COMMENT ON COLUMN bot.auto_reply_rules.created_at IS '规则创建时间';
COMMENT ON COLUMN bot.auto_reply_rules.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_auto_reply_rules_chat_id ON bot.auto_reply_rules(chat_id);
CREATE INDEX IF NOT EXISTS ix_auto_reply_rules_is_active ON bot.auto_reply_rules(is_active);

-- ============================================
-- 19. 违禁词表 (banned_words)
-- 存储违禁词规则
-- ============================================
CREATE TABLE IF NOT EXISTS bot.banned_words (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    created_by_user_id BIGINT,                                   -- 创建者用户 ID（外键关联 tg_users.id，可为空）
    word VARCHAR(255) NOT NULL,                                  -- 违禁词
    match_type VARCHAR(16) NOT NULL DEFAULT 'contains',          -- 匹配类型（contains/exact/regex）
    action VARCHAR(16) NOT NULL DEFAULT 'delete',                -- 惩罚动作（delete/mute/ban）
    mute_duration INTEGER NOT NULL DEFAULT 60,                   -- 禁言时长（秒）
    notify BOOLEAN NOT NULL DEFAULT TRUE,                        -- 是否发送删除提醒
    notify_message TEXT,                                         -- 自定义提醒消息
    is_active BOOLEAN NOT NULL DEFAULT TRUE,                     -- 是否激活
    trigger_count INTEGER NOT NULL DEFAULT 0,                    -- 触发次数统计
    case_sensitive BOOLEAN NOT NULL DEFAULT FALSE,               -- 是否区分大小写
    created_at TIMESTAMPTZ NOT NULL,                             -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                             -- 更新时间（带时区）
    CONSTRAINT fk_banned_words_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,               -- 外键约束：删除群组时级联删除违禁词
    CONSTRAINT fk_banned_words_created_by_user_id FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL               -- 外键约束：删除用户时将创建者设为 NULL
);

COMMENT ON TABLE bot.banned_words IS '违禁词表，存储群组的违禁词规则';
COMMENT ON COLUMN bot.banned_words.id IS '自增主键';
COMMENT ON COLUMN bot.banned_words.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.banned_words.created_by_user_id IS '创建规则的用户 ID，外键关联 tg_users.id，删除用户时设为 NULL';
COMMENT ON COLUMN bot.banned_words.word IS '违禁词内容';
COMMENT ON COLUMN bot.banned_words.match_type IS '匹配类型：contains（包含匹配）、exact（精确匹配）、regex（正则表达式）';
COMMENT ON COLUMN bot.banned_words.action IS '惩罚动作：delete（删除消息）、mute（禁言）、ban（封禁用户）';
COMMENT ON COLUMN bot.banned_words.mute_duration IS '禁言时长（秒）';
COMMENT ON COLUMN bot.banned_words.notify IS '是否发送删除提醒给用户';
COMMENT ON COLUMN bot.banned_words.notify_message IS '自定义提醒消息';
COMMENT ON COLUMN bot.banned_words.is_active IS '是否激活（true=启用，false=禁用）';
COMMENT ON COLUMN bot.banned_words.trigger_count IS '违禁词被触发的次数统计';
COMMENT ON COLUMN bot.banned_words.case_sensitive IS '是否区分大小写';
COMMENT ON COLUMN bot.banned_words.created_at IS '规则创建时间';
COMMENT ON COLUMN bot.banned_words.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_banned_words_chat_id ON bot.banned_words(chat_id);
CREATE INDEX IF NOT EXISTS ix_banned_words_word ON bot.banned_words(word);
CREATE INDEX IF NOT EXISTS ix_banned_words_is_active ON bot.banned_words(is_active);

-- ============================================
-- 20. 邀请链接管理表 (invite_links)
-- 存储群组邀请链接管理信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.invite_links (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    created_by_user_id BIGINT,                                   -- 创建者用户 ID（外键关联 tg_users.id，可为空）
    invite_link VARCHAR(255) NOT NULL,                           -- Telegram邀请链接
    name VARCHAR(128),                                           -- 链接名称
    status VARCHAR(16) NOT NULL DEFAULT 'active',                -- 状态（active/expired/revoked）
    member_limit INTEGER,                                        -- 成员数量限制（NULL=无限制）
    member_count INTEGER NOT NULL DEFAULT 0,                     -- 当前成员数
    expire_date TIMESTAMPTZ,                                     -- 过期时间（带时区）
    creates_join_request BOOLEAN NOT NULL DEFAULT FALSE,         -- 是否需要审核
    created_at TIMESTAMPTZ NOT NULL,                             -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                             -- 更新时间（带时区）
    CONSTRAINT fk_invite_links_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,               -- 外键约束：删除群组时级联删除邀请链接
    CONSTRAINT fk_invite_links_created_by_user_id FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL               -- 外键约束：删除用户时将创建者设为 NULL
);

COMMENT ON TABLE bot.invite_links IS '邀请链接管理表，存储群组邀请链接管理信息';
COMMENT ON COLUMN bot.invite_links.id IS '自增主键';
COMMENT ON COLUMN bot.invite_links.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.invite_links.created_by_user_id IS '创建链接的用户 ID，外键关联 tg_users.id，删除用户时设为 NULL';
COMMENT ON COLUMN bot.invite_links.invite_link IS 'Telegram邀请链接';
COMMENT ON COLUMN bot.invite_links.name IS '链接名称，便于识别管理';
COMMENT ON COLUMN bot.invite_links.status IS '链接状态：active（有效）、expired（已过期）、revoked（已撤销）';
COMMENT ON COLUMN bot.invite_links.member_limit IS '成员数量限制，NULL表示无限制';
COMMENT ON COLUMN bot.invite_links.member_count IS '当前通过此链接加入的成员数';
COMMENT ON COLUMN bot.invite_links.expire_date IS '链接过期时间，NULL表示永久有效';
COMMENT ON COLUMN bot.invite_links.creates_join_request IS '是否需要审核（true=需要管理员审核）';
COMMENT ON COLUMN bot.invite_links.created_at IS '链接创建时间';
COMMENT ON COLUMN bot.invite_links.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_invite_links_chat_id ON bot.invite_links(chat_id);
CREATE INDEX IF NOT EXISTS ix_invite_links_invite_link ON bot.invite_links(invite_link);
CREATE INDEX IF NOT EXISTS ix_invite_links_status ON bot.invite_links(status);

-- ============================================
-- 20.5. 邀请追踪表 (invite_tracking)
-- 追踪谁邀请了谁加入群组，用于发放邀请积分
-- ============================================
CREATE TABLE IF NOT EXISTS bot.invite_tracking (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    inviter_user_id BIGINT,                                      -- 邀请人用户 ID（外键关联 tg_users.id）
    invited_user_id BIGINT NOT NULL,                             -- 被邀请人用户 ID（外键关联 tg_users.id）
    invite_link_id INTEGER,                                      -- 使用的邀请链接 ID（外键关联 invite_links.id）
    points_awarded BOOLEAN NOT NULL DEFAULT FALSE,               -- 是否已发放积分
    joined_at TIMESTAMPTZ NOT NULL,                              -- 加入时间（带时区）
    created_at TIMESTAMPTZ NOT NULL,                             -- 记录创建时间（带时区）
    CONSTRAINT fk_invite_tracking_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,               -- 外键约束：删除群组时级联删除追踪记录
    CONSTRAINT fk_invite_tracking_inviter_user_id FOREIGN KEY (inviter_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,               -- 外键约束：删除邀请人时设为 NULL
    CONSTRAINT fk_invite_tracking_invited_user_id FOREIGN KEY (invited_user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,                -- 外键约束：删除被邀请人时级联删除记录
    CONSTRAINT fk_invite_tracking_invite_link_id FOREIGN KEY (invite_link_id)
        REFERENCES bot.invite_links(id) ON DELETE SET NULL,            -- 外键约束：删除链接时设为 NULL
    CONSTRAINT uq_invite_tracking UNIQUE (chat_id, invited_user_id)    -- 唯一约束：同一用户在同一群组只记录第一次邀请
);

COMMENT ON TABLE bot.invite_tracking IS '邀请追踪表，记录谁邀请了谁加入群组，用于发放邀请积分。防作弊：只有第一次进群计为有效邀请';
COMMENT ON COLUMN bot.invite_tracking.id IS '自增主键';
COMMENT ON COLUMN bot.invite_tracking.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.invite_tracking.inviter_user_id IS '邀请人的用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.invite_tracking.invited_user_id IS '被邀请人的用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.invite_tracking.invite_link_id IS '使用的邀请链接 ID，外键关联 invite_links.id';
COMMENT ON COLUMN bot.invite_tracking.points_awarded IS '是否已发放邀请积分';
COMMENT ON COLUMN bot.invite_tracking.joined_at IS '成员加入群组的时间';
COMMENT ON COLUMN bot.invite_tracking.created_at IS '追踪记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_invite_tracking_chat_id ON bot.invite_tracking(chat_id);
CREATE INDEX IF NOT EXISTS ix_invite_tracking_inviter_user_id ON bot.invite_tracking(inviter_user_id);
CREATE INDEX IF NOT EXISTS ix_invite_tracking_invited_user_id ON bot.invite_tracking(invited_user_id);
CREATE INDEX IF NOT EXISTS ix_invite_tracking_invite_link_id ON bot.invite_tracking(invite_link_id);

-- ============================================
-- 21. 接龙活动表 (solitaires)
-- 存储群组接龙活动信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.solitaires (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                      -- 群组 ID（外键关联 tg_chats.id）
    created_by_user_id BIGINT,                                   -- 创建者用户 ID（外键关联 tg_users.id，可为空）
    title VARCHAR(255) NOT NULL,                                 -- 接龙标题
    description TEXT,                                            -- 描述说明
    status VARCHAR(16) NOT NULL DEFAULT 'active',                -- 状态（active/closed）
    max_participants INTEGER,                                    -- 最大参与人数（NULL=无限制）
    points_required INTEGER,                                     -- 参与所需积分（NULL=无限制）
    deadline TIMESTAMPTZ,                                        -- 截止时间（带时区，NULL=无限制）
    message_id INTEGER,                                          -- 接龙消息ID（用于更新）
    created_at TIMESTAMPTZ NOT NULL,                             -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                             -- 更新时间（带时区）
    CONSTRAINT fk_solitaires_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,               -- 外键约束：删除群组时级联删除接龙
    CONSTRAINT fk_solitaires_created_by_user_id FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL               -- 外键约束：删除用户时将创建者设为 NULL
);

COMMENT ON TABLE bot.solitaires IS '接龙活动表，存储群组接龙活动信息';
COMMENT ON COLUMN bot.solitaires.id IS '自增主键';
COMMENT ON COLUMN bot.solitaires.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.solitaires.created_by_user_id IS '创建接龙的用户 ID，外键关联 tg_users.id，删除用户时设为 NULL';
COMMENT ON COLUMN bot.solitaires.title IS '接龙标题';
COMMENT ON COLUMN bot.solitaires.description IS '接龙描述说明';
COMMENT ON COLUMN bot.solitaires.status IS '接龙状态：active（进行中）、closed（已结束）';
COMMENT ON COLUMN bot.solitaires.max_participants IS '最大参与人数，NULL表示无限制';
COMMENT ON COLUMN bot.solitaires.points_required IS '参与接龙所需积分，NULL表示无限制';
COMMENT ON COLUMN bot.solitaires.deadline IS '接龙截止时间，NULL表示无限制';
COMMENT ON COLUMN bot.solitaires.message_id IS '接龙消息的 Telegram message_id，用于更新消息';
COMMENT ON COLUMN bot.solitaires.created_at IS '接龙创建时间';
COMMENT ON COLUMN bot.solitaires.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_solitaires_chat_id ON bot.solitaires(chat_id);
CREATE INDEX IF NOT EXISTS ix_solitaires_status ON bot.solitaires(status);
CREATE INDEX IF NOT EXISTS ix_solitaires_deadline ON bot.solitaires(deadline);


-- ============================================
-- 22. 接龙参与记录表 (solitaire_entries)
-- 存储用户参与接龙的记录
-- ============================================
CREATE TABLE IF NOT EXISTS bot.solitaire_entries (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    solitaire_id INTEGER NOT NULL,                               -- 接龙 ID（外键关联 solitaires.id）
    user_id BIGINT NOT NULL,                                     -- 用户 ID（外键关联 tg_users.id）
    username VARCHAR(255),                                       -- 用户名（用于显示，保留以便用户名变更后仍显示原始名称）
    content TEXT NOT NULL DEFAULT '',                             -- 参与内容
    joined_at TIMESTAMPTZ NOT NULL,                              -- 参与时间（带时区）
    updated_at TIMESTAMPTZ,                                      -- 更新时间（带时区，修改内容时更新）
    created_at TIMESTAMPTZ NOT NULL,                             -- 记录创建时间（带时区）
    CONSTRAINT fk_solitaire_entries_solitaire_id FOREIGN KEY (solitaire_id)
        REFERENCES bot.solitaires(id) ON DELETE CASCADE,              -- 外键约束：删除接龙时级联删除参与记录
    CONSTRAINT fk_solitaire_entries_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,                  -- 外键约束：删除用户时级联删除参与记录
    CONSTRAINT uq_solitaire_entries UNIQUE (solitaire_id, user_id)      -- 唯一约束：同一用户在同一接龙中只能参与一次
);

COMMENT ON TABLE bot.solitaire_entries IS '接龙参与记录表，存储用户参与接龙的记录';
COMMENT ON COLUMN bot.solitaire_entries.id IS '自增主键';
COMMENT ON COLUMN bot.solitaire_entries.solitaire_id IS '接龙 ID，外键关联 solitaires.id';
COMMENT ON COLUMN bot.solitaire_entries.user_id IS '用户 ID，外键关联 tg_users.id';
COMMENT ON COLUMN bot.solitaire_entries.username IS '用户名，用于显示，保留用户参与时的用户名';
COMMENT ON COLUMN bot.solitaire_entries.content IS '参与内容，用户填写的报名信息';
COMMENT ON COLUMN bot.solitaire_entries.joined_at IS '参与时间，用户首次参与的时间';
COMMENT ON COLUMN bot.solitaire_entries.updated_at IS '更新时间，用户修改参与内容的时间';
COMMENT ON COLUMN bot.solitaire_entries.created_at IS '记录创建时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_solitaire_entries_solitaire_id ON bot.solitaire_entries(solitaire_id);
CREATE INDEX IF NOT EXISTS ix_solitaire_entries_user_id ON bot.solitaire_entries(user_id);

-- ============================================
-- 数据库初始化完成
-- ============================================

