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
    verification_mode VARCHAR(16) NOT NULL DEFAULT 'button',       -- 验证模式（button/math/mute/captcha/admin）
    verification_timeout_seconds INTEGER NOT NULL,                 -- 验证超时时间（秒）
    verification_restrict_can_send BOOLEAN NOT NULL,               -- 验证期间是否限制发送消息
    verification_timeout_action VARCHAR(16) NOT NULL DEFAULT 'mute', -- 验证超时后的处理动作（none/mute/kick）
    verification_mute_duration INTEGER NOT NULL DEFAULT 86400,     -- 验证超时禁言时长（秒，默认1天）
    verification_cover_media_type VARCHAR(16),                     -- 进群验证封面类型
    verification_cover_file_id VARCHAR(256),                       -- 进群验证封面 file_id
    verification_agreement_text TEXT NOT NULL DEFAULT '请阅读并同意本群规则后再发言。', -- 简单接受条约文案
    verification_math_prompt_text TEXT NOT NULL DEFAULT '请回答下面的简单算术题完成验证。', -- 简单加减法前置文案
    verification_wrong_action VARCHAR(16) NOT NULL DEFAULT 'none', -- 答错处理（none/mute/kick）
    verification_direct_mute_duration INTEGER NOT NULL DEFAULT 0,  -- 直接禁言新人时长，0=永久
    join_spam_guard_enabled BOOLEAN NOT NULL DEFAULT FALSE,        -- 进群垃圾拦截总开关
    join_spam_detect_rules_count INTEGER NOT NULL DEFAULT 2,       -- 进群垃圾拦截命中阈值
    join_spam_send_invalid_msg_enabled BOOLEAN NOT NULL DEFAULT FALSE, -- 是否发送进群垃圾拦截提示
    join_spam_mute_member_enabled BOOLEAN NOT NULL DEFAULT TRUE,   -- 是否禁言可疑新人
    join_spam_kick_member_enabled BOOLEAN NOT NULL DEFAULT FALSE,  -- 是否踢出可疑新人
    join_spam_tip_delete_after_seconds INTEGER NOT NULL DEFAULT 60, -- 进群垃圾拦截提示删除时长
    join_self_review_enabled BOOLEAN NOT NULL DEFAULT FALSE,       -- 进群自助审核总开关
    join_self_review_timeout_seconds INTEGER NOT NULL DEFAULT 300, -- 自助审核超时时间
    join_self_review_timeout_action VARCHAR(32) NOT NULL DEFAULT 'reject_allow_retry', -- 自助审核超时策略
    join_self_review_wrong_action VARCHAR(32) NOT NULL DEFAULT 'reject_block', -- 自助审核答错策略
    join_burst_enabled BOOLEAN NOT NULL DEFAULT FALSE,             -- 禁止批量进群总开关
    join_burst_window_seconds INTEGER NOT NULL DEFAULT 30,         -- 批量进群时间窗口
    join_burst_threshold_count INTEGER NOT NULL DEFAULT 10,        -- 批量进群阈值人数
    join_burst_mute_enabled BOOLEAN NOT NULL DEFAULT TRUE,         -- 批量进群是否禁言
    join_burst_kick_enabled BOOLEAN NOT NULL DEFAULT FALSE,        -- 批量进群是否踢出
    join_burst_tip_mode VARCHAR(16) NOT NULL DEFAULT 'tip_and_delete', -- 批量进群提示策略
    new_member_limit_enabled BOOLEAN NOT NULL DEFAULT FALSE,       -- 新成员限制总开关
    new_member_limit_window_seconds INTEGER NOT NULL DEFAULT 3600, -- 新成员限制窗口（秒）
    new_member_limit_block_media BOOLEAN NOT NULL DEFAULT TRUE,    -- 新成员限制媒体消息
    new_member_limit_block_links BOOLEAN NOT NULL DEFAULT TRUE,    -- 新成员限制链接消息
    new_member_limit_text_only BOOLEAN NOT NULL DEFAULT FALSE,     -- 新成员仅允许纯文本
    new_member_limit_delete_message BOOLEAN NOT NULL DEFAULT TRUE, -- 新成员触发时删除消息
    new_member_limit_warn_enabled BOOLEAN NOT NULL DEFAULT TRUE,   -- 新成员限制提示开关
    new_member_limit_warn_text TEXT NOT NULL DEFAULT '新成员需等待 {duration} 才可发送媒体/链接。', -- 新成员提示文案
    new_member_limit_warn_delete_after_seconds INTEGER NOT NULL DEFAULT 60, -- 提示消息删除秒数
    night_mode_enabled BOOLEAN NOT NULL DEFAULT FALSE,            -- 夜间模式总开关
    night_mode_start_time VARCHAR(5),                             -- 夜间模式开始时间（HH:MM）
    night_mode_end_time VARCHAR(5),                               -- 夜间模式结束时间（HH:MM）
    night_mode_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE,        -- 夜间模式是否豁免管理员
    night_mode_whitelist_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb, -- 夜间模式白名单用户ID
    night_mode_delete_message BOOLEAN NOT NULL DEFAULT TRUE,      -- 夜间模式删除消息
    night_mode_warn_enabled BOOLEAN NOT NULL DEFAULT TRUE,        -- 夜间模式提示开关
    night_mode_warn_text TEXT NOT NULL DEFAULT '🌙 夜间模式生效中，请稍后再试。', -- 夜间模式提示文案
    night_mode_warn_delete_after_seconds INTEGER NOT NULL DEFAULT 60, -- 夜间模式提示删除秒数
    command_config_enabled BOOLEAN NOT NULL DEFAULT FALSE,        -- 命令配置总开关
    command_config JSONB NOT NULL DEFAULT '{}'::jsonb,            -- 命令配置明细
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
    anti_flood_mute_duration INTEGER NOT NULL DEFAULT 3600,        -- 禁言时长（秒）
    anti_flood_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE,         -- 是否豁免管理员
    anti_flood_cleanup_messages BOOLEAN NOT NULL DEFAULT FALSE,    -- 触发后是否清理消息
    anti_flood_delete_notify BOOLEAN NOT NULL DEFAULT FALSE,       -- 是否发送并自动删除提醒
    anti_flood_delete_notify_seconds INTEGER NOT NULL DEFAULT 600, -- 提醒消息保留时长（秒）
    anti_spam_enabled BOOLEAN NOT NULL DEFAULT FALSE,              -- 是否启用反垃圾
    anti_spam_action VARCHAR(32) NOT NULL DEFAULT 'mute',          -- 反垃圾惩罚动作（delete/mute/ban）
    anti_spam_mute_duration INTEGER NOT NULL DEFAULT 3600,         -- 反垃圾禁言时长（秒）
    anti_spam_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE,          -- 是否豁免管理员
    anti_spam_delete_notify BOOLEAN NOT NULL DEFAULT FALSE,        -- 是否发送并自动删除提醒
    anti_spam_delete_notify_seconds INTEGER NOT NULL DEFAULT 600,  -- 提醒消息保留时长（秒）
    anti_spam_repeat_messages INTEGER NOT NULL DEFAULT 3,          -- 重复消息触发条数
    anti_spam_repeat_seconds INTEGER NOT NULL DEFAULT 15,          -- 重复消息检测窗口（秒）
    anti_spam_rules JSONB NOT NULL DEFAULT '{}'::jsonb,            -- 反垃圾规则开关与名单配置
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
    invite_link_mode VARCHAR(16) NOT NULL DEFAULT 'direct',        -- 邀请模式：relay/direct
    invite_link_cover_media_type VARCHAR(16),                      -- 邀请封面类型：photo/video/none
    invite_link_cover_file_id VARCHAR(256),                        -- 邀请封面文件ID
    invite_link_text_template TEXT NOT NULL DEFAULT '🔗 邀请好友加入 {group}\n邀请人：{inviter}\n新成员：{invitee}', -- 邀请卡片模板
    invite_link_buttons JSONB NOT NULL DEFAULT '[]'::jsonb,        -- 邀请卡片按钮
    auto_delete_enabled BOOLEAN NOT NULL DEFAULT FALSE,            -- 是否开启自动删除
    auto_delete_join BOOLEAN NOT NULL DEFAULT FALSE,               -- 自动删除进群消息
    auto_delete_left BOOLEAN NOT NULL DEFAULT FALSE,               -- 自动删除退群消息
    auto_delete_pinned BOOLEAN NOT NULL DEFAULT FALSE,             -- 自动删除置顶消息
    auto_delete_avatar BOOLEAN NOT NULL DEFAULT FALSE,             -- 自动删除修改头像消息
    auto_delete_title BOOLEAN NOT NULL DEFAULT FALSE,              -- 自动删除修改群名消息
    auto_delete_anonymous BOOLEAN NOT NULL DEFAULT FALSE,          -- 自动删除匿名管理员消息
    points_display_rule_enabled BOOLEAN NOT NULL DEFAULT TRUE,     -- 是否在积分中心展示规则入口
    points_speech_rank_enabled BOOLEAN NOT NULL DEFAULT TRUE,      -- 是否启用发言总排行入口
    points_personal_speech_enabled BOOLEAN NOT NULL DEFAULT TRUE,  -- 是否启用个人发言量入口
    points_alias VARCHAR(32) NOT NULL DEFAULT '积分',              -- 积分查询命令别名
    points_rank_alias VARCHAR(32) NOT NULL DEFAULT '积分排行',      -- 积分排行命令别名
    control_permission_policy VARCHAR(32) NOT NULL DEFAULT 'can_promote_members', -- 机器人管理权限门槛
    group_lock_phrase_enabled BOOLEAN NOT NULL DEFAULT FALSE,      -- 关群话术开关
    group_lock_open_phrase TEXT,                                   -- 开群词
    group_lock_close_phrase TEXT,                                  -- 关群词
    group_lock_schedule_enabled BOOLEAN NOT NULL DEFAULT FALSE,    -- 关群定时开关
    group_lock_open_time VARCHAR(5),                               -- 开群时间（HH:MM）
    group_lock_close_time VARCHAR(5),                              -- 关群时间（HH:MM）
    group_lock_delete_notice_mode VARCHAR(16) NOT NULL DEFAULT 'keep', -- 删除通知消息策略（delete/keep）
    name_change_monitor_enabled BOOLEAN NOT NULL DEFAULT FALSE,    -- 改名监控总开关
    name_change_monitor_template_text TEXT NOT NULL DEFAULT E'检测到用户{userId}修改{changeType}\n原{changeType}: {oldContent}\n新{changeType}: {newContent}\n\n请注意规避风险', -- 改名监控提示模板
    name_change_monitor_delete_after_seconds INTEGER NOT NULL DEFAULT 60, -- 提示消息自动删除秒数
    force_subscribe_enabled BOOLEAN NOT NULL DEFAULT FALSE,        -- 是否启用发言前强制关注
    force_subscribe_bound_channel_1 TEXT,                          -- 绑定频道/群组1
    force_subscribe_bound_channel_2 TEXT,                          -- 绑定频道/群组2
    force_subscribe_cover_media_type VARCHAR(16),                  -- 引导封面媒体类型
    force_subscribe_cover_file_id VARCHAR(256),                    -- 引导封面文件ID
    force_subscribe_guide_text TEXT NOT NULL DEFAULT '{member}，您需要关注指定频道/群组后才能发言。', -- 引导文案
    force_subscribe_custom_buttons_enabled BOOLEAN NOT NULL DEFAULT FALSE, -- 自定义按钮开关
    force_subscribe_check_mode VARCHAR(8) NOT NULL DEFAULT 'all',  -- 关注校验策略（all/any）
    force_subscribe_not_subscribed_action VARCHAR(32) NOT NULL DEFAULT 'delete_and_warn', -- 未关注处理动作
    force_subscribe_delete_warn_after_seconds INTEGER NOT NULL DEFAULT 60, -- 提示消息删除秒数
    force_subscribe_buttons JSONB NOT NULL DEFAULT '[]'::jsonb,    -- 引导按钮布局（jsonb）
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
COMMENT ON COLUMN bot.chat_settings.verification_mode IS '验证模式：button（简单接受条约）、math（简单加减法）、mute（直接禁言新人）、captcha（验证码）、admin（管理员确认）';
COMMENT ON COLUMN bot.chat_settings.verification_timeout_seconds IS '新人验证超时时间（秒），超时后自动处理（admin/mute 模式不生效）';
COMMENT ON COLUMN bot.chat_settings.verification_restrict_can_send IS '验证期间是否限制新成员发送消息';
COMMENT ON COLUMN bot.chat_settings.verification_timeout_action IS '验证超时后的处理动作：none（不额外处理）、mute（禁言）、kick（踢出群聊）';
COMMENT ON COLUMN bot.chat_settings.verification_mute_duration IS '验证超时禁言时长（秒），默认 86400 秒（1天）';
COMMENT ON COLUMN bot.chat_settings.verification_cover_media_type IS '进群验证封面类型：photo/video';
COMMENT ON COLUMN bot.chat_settings.verification_cover_file_id IS '进群验证封面 Telegram file_id';
COMMENT ON COLUMN bot.chat_settings.verification_agreement_text IS '简单接受条约文案';
COMMENT ON COLUMN bot.chat_settings.verification_math_prompt_text IS '简单加减法前置文案';
COMMENT ON COLUMN bot.chat_settings.verification_wrong_action IS '简单加减法答错处理：none/mute/kick';
COMMENT ON COLUMN bot.chat_settings.verification_direct_mute_duration IS '直接禁言新人时长，0 表示永久禁言';
COMMENT ON COLUMN bot.chat_settings.join_spam_guard_enabled IS '进群垃圾拦截总开关';
COMMENT ON COLUMN bot.chat_settings.join_spam_detect_rules_count IS '进群垃圾拦截命中阈值';
COMMENT ON COLUMN bot.chat_settings.join_spam_send_invalid_msg_enabled IS '进群垃圾拦截是否发送提示';
COMMENT ON COLUMN bot.chat_settings.join_spam_mute_member_enabled IS '进群垃圾拦截是否禁言';
COMMENT ON COLUMN bot.chat_settings.join_spam_kick_member_enabled IS '进群垃圾拦截是否踢出';
COMMENT ON COLUMN bot.chat_settings.join_spam_tip_delete_after_seconds IS '进群垃圾拦截提示删除时长';
COMMENT ON COLUMN bot.chat_settings.join_self_review_enabled IS '进群自助审核总开关';
COMMENT ON COLUMN bot.chat_settings.join_self_review_timeout_seconds IS '自助审核超时时间（秒）';
COMMENT ON COLUMN bot.chat_settings.join_self_review_timeout_action IS '自助审核超时策略';
COMMENT ON COLUMN bot.chat_settings.join_self_review_wrong_action IS '自助审核答错策略';
COMMENT ON COLUMN bot.chat_settings.join_burst_enabled IS '禁止批量进群总开关';
COMMENT ON COLUMN bot.chat_settings.join_burst_window_seconds IS '禁止批量进群时间窗口（秒）';
COMMENT ON COLUMN bot.chat_settings.join_burst_threshold_count IS '禁止批量进群阈值人数';
COMMENT ON COLUMN bot.chat_settings.join_burst_mute_enabled IS '批量进群触发后是否禁言';
COMMENT ON COLUMN bot.chat_settings.join_burst_kick_enabled IS '批量进群触发后是否踢出';
COMMENT ON COLUMN bot.chat_settings.join_burst_tip_mode IS '批量进群提示策略';
COMMENT ON COLUMN bot.chat_settings.new_member_limit_enabled IS '新成员限制总开关';
COMMENT ON COLUMN bot.chat_settings.new_member_limit_window_seconds IS '新成员限制时间窗口（秒）';
COMMENT ON COLUMN bot.chat_settings.new_member_limit_block_media IS '新成员限制媒体消息';
COMMENT ON COLUMN bot.chat_settings.new_member_limit_block_links IS '新成员限制链接消息';
COMMENT ON COLUMN bot.chat_settings.new_member_limit_text_only IS '新成员仅允许纯文本';
COMMENT ON COLUMN bot.chat_settings.new_member_limit_delete_message IS '新成员触发时是否删除消息';
COMMENT ON COLUMN bot.chat_settings.new_member_limit_warn_enabled IS '新成员限制提示开关';
COMMENT ON COLUMN bot.chat_settings.new_member_limit_warn_text IS '新成员限制提示文案';
COMMENT ON COLUMN bot.chat_settings.new_member_limit_warn_delete_after_seconds IS '新成员限制提示删除秒数';
COMMENT ON COLUMN bot.chat_settings.night_mode_enabled IS '夜间模式总开关';
COMMENT ON COLUMN bot.chat_settings.night_mode_start_time IS '夜间模式开始时间（HH:MM）';
COMMENT ON COLUMN bot.chat_settings.night_mode_end_time IS '夜间模式结束时间（HH:MM）';
COMMENT ON COLUMN bot.chat_settings.night_mode_exempt_admin IS '夜间模式是否豁免管理员';
COMMENT ON COLUMN bot.chat_settings.night_mode_whitelist_user_ids IS '夜间模式白名单用户ID';
COMMENT ON COLUMN bot.chat_settings.night_mode_delete_message IS '夜间模式删除消息';
COMMENT ON COLUMN bot.chat_settings.night_mode_warn_enabled IS '夜间模式提示开关';
COMMENT ON COLUMN bot.chat_settings.night_mode_warn_text IS '夜间模式提示文案';
COMMENT ON COLUMN bot.chat_settings.night_mode_warn_delete_after_seconds IS '夜间模式提示删除秒数';
COMMENT ON COLUMN bot.chat_settings.command_config_enabled IS '命令配置总开关';
COMMENT ON COLUMN bot.chat_settings.command_config IS '命令配置明细';
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
COMMENT ON COLUMN bot.chat_settings.anti_flood_exempt_admin IS '反刷屏是否豁免管理员';
COMMENT ON COLUMN bot.chat_settings.anti_flood_cleanup_messages IS '触发反刷屏后是否自动删除触发消息';
COMMENT ON COLUMN bot.chat_settings.anti_flood_delete_notify IS '是否发送并自动删除防刷屏提醒消息';
COMMENT ON COLUMN bot.chat_settings.anti_flood_delete_notify_seconds IS '防刷屏提醒消息保留时长（秒）';
COMMENT ON COLUMN bot.chat_settings.anti_spam_enabled IS '是否启用反垃圾模块';
COMMENT ON COLUMN bot.chat_settings.anti_spam_action IS '反垃圾惩罚动作：delete（删除）、mute（禁言）、ban（封禁）';
COMMENT ON COLUMN bot.chat_settings.anti_spam_mute_duration IS '反垃圾禁言时长（秒）';
COMMENT ON COLUMN bot.chat_settings.anti_spam_exempt_admin IS '反垃圾是否豁免管理员';
COMMENT ON COLUMN bot.chat_settings.anti_spam_delete_notify IS '是否发送并自动删除反垃圾提醒消息';
COMMENT ON COLUMN bot.chat_settings.anti_spam_delete_notify_seconds IS '反垃圾提醒消息保留时长（秒）';
COMMENT ON COLUMN bot.chat_settings.anti_spam_repeat_messages IS '反垃圾重复消息触发条数';
COMMENT ON COLUMN bot.chat_settings.anti_spam_repeat_seconds IS '反垃圾重复消息检测窗口（秒）';
COMMENT ON COLUMN bot.chat_settings.anti_spam_rules IS '反垃圾规则配置（开关、名单、阈值）';
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
COMMENT ON COLUMN bot.chat_settings.invite_link_mode IS '邀请模式：relay（中转/审核）或 direct（直达）';
COMMENT ON COLUMN bot.chat_settings.invite_link_cover_media_type IS '邀请封面类型';
COMMENT ON COLUMN bot.chat_settings.invite_link_cover_file_id IS '邀请封面文件ID';
COMMENT ON COLUMN bot.chat_settings.invite_link_text_template IS '邀请卡片文本模板';
COMMENT ON COLUMN bot.chat_settings.invite_link_buttons IS '邀请卡片按钮布局';
COMMENT ON COLUMN bot.chat_settings.auto_delete_enabled IS '是否开启自动删除系统消息功能';
COMMENT ON COLUMN bot.chat_settings.auto_delete_join IS '是否自动删除进群消息（xxx joined the group）';
COMMENT ON COLUMN bot.chat_settings.auto_delete_left IS '是否自动删除退群消息（xxx left the group）';
COMMENT ON COLUMN bot.chat_settings.auto_delete_pinned IS '是否自动删除置顶消息';
COMMENT ON COLUMN bot.chat_settings.auto_delete_avatar IS '是否自动删除修改头像消息';
COMMENT ON COLUMN bot.chat_settings.auto_delete_title IS '是否自动删除修改群名消息';
COMMENT ON COLUMN bot.chat_settings.auto_delete_anonymous IS '是否自动删除匿名管理员消息';
COMMENT ON COLUMN bot.chat_settings.points_display_rule_enabled IS '是否在积分中心展示规则入口';
COMMENT ON COLUMN bot.chat_settings.points_speech_rank_enabled IS '是否启用发言总排行入口';
COMMENT ON COLUMN bot.chat_settings.points_personal_speech_enabled IS '是否启用个人发言量入口';
COMMENT ON COLUMN bot.chat_settings.points_alias IS '积分查询命令别名（如：积分）';
COMMENT ON COLUMN bot.chat_settings.points_rank_alias IS '积分排行命令别名（如：积分排行）';
COMMENT ON COLUMN bot.chat_settings.control_permission_policy IS '机器人管理权限门槛：all_admins / can_restrict_members / can_change_info / can_promote_members / owner_only';
COMMENT ON COLUMN bot.chat_settings.group_lock_phrase_enabled IS '是否启用关群话术';
COMMENT ON COLUMN bot.chat_settings.group_lock_open_phrase IS '开群词';
COMMENT ON COLUMN bot.chat_settings.group_lock_close_phrase IS '关群词';
COMMENT ON COLUMN bot.chat_settings.group_lock_schedule_enabled IS '是否启用关群定时';
COMMENT ON COLUMN bot.chat_settings.group_lock_open_time IS '开群时间（HH:MM）';
COMMENT ON COLUMN bot.chat_settings.group_lock_close_time IS '关群时间（HH:MM）';
COMMENT ON COLUMN bot.chat_settings.group_lock_delete_notice_mode IS '删除通知消息策略：delete / keep';
COMMENT ON COLUMN bot.chat_settings.name_change_monitor_enabled IS '是否启用改名监控';
COMMENT ON COLUMN bot.chat_settings.name_change_monitor_template_text IS '改名监控提示模板';
COMMENT ON COLUMN bot.chat_settings.name_change_monitor_delete_after_seconds IS '改名监控提示消息删除秒数';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_enabled IS '是否启用发言前强制关注';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_bound_channel_1 IS '强制关注绑定频道/群组1';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_bound_channel_2 IS '强制关注绑定频道/群组2';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_cover_media_type IS '强制关注引导封面媒体类型';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_cover_file_id IS '强制关注引导封面文件ID';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_guide_text IS '强制关注引导文案';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_custom_buttons_enabled IS '强制关注引导按钮开关';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_check_mode IS '强制关注校验模式：all / any';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_not_subscribed_action IS '未关注处理动作';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_delete_warn_after_seconds IS '强制关注提示消息删除秒数';
COMMENT ON COLUMN bot.chat_settings.force_subscribe_buttons IS '强制关注引导按钮布局（JSONB）';
COMMENT ON COLUMN bot.chat_settings.created_at IS '配置创建时间';
COMMENT ON COLUMN bot.chat_settings.updated_at IS '配置最后更新时间';

-- 兼容历史库：为已存在的 chat_settings 表补齐新增列
-- 说明：仅靠 CREATE TABLE IF NOT EXISTS 不会为旧表自动增加新列
ALTER TABLE bot.chat_settings ALTER COLUMN anti_flood_mute_duration SET DEFAULT 3600;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_cleanup_messages BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_delete_notify BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_delete_notify_seconds INTEGER NOT NULL DEFAULT 600;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_action VARCHAR(32) NOT NULL DEFAULT 'mute';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_mute_duration INTEGER NOT NULL DEFAULT 3600;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_delete_notify BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_delete_notify_seconds INTEGER NOT NULL DEFAULT 600;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_repeat_messages INTEGER NOT NULL DEFAULT 3;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_repeat_seconds INTEGER NOT NULL DEFAULT 15;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_rules JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_cover_media_type VARCHAR(16);
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_cover_file_id VARCHAR(256);
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_agreement_text TEXT NOT NULL DEFAULT '请阅读并同意本群规则后再发言。';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_math_prompt_text TEXT NOT NULL DEFAULT '请回答下面的简单算术题完成验证。';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_wrong_action VARCHAR(16) NOT NULL DEFAULT 'none';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS verification_direct_mute_duration INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_guard_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_detect_rules_count INTEGER NOT NULL DEFAULT 2;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_send_invalid_msg_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_mute_member_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_kick_member_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_spam_tip_delete_after_seconds INTEGER NOT NULL DEFAULT 60;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_self_review_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_self_review_timeout_seconds INTEGER NOT NULL DEFAULT 300;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_self_review_timeout_action VARCHAR(32) NOT NULL DEFAULT 'reject_allow_retry';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_self_review_wrong_action VARCHAR(32) NOT NULL DEFAULT 'reject_block';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_window_seconds INTEGER NOT NULL DEFAULT 30;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_threshold_count INTEGER NOT NULL DEFAULT 10;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_mute_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_kick_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS join_burst_tip_mode VARCHAR(16) NOT NULL DEFAULT 'tip_and_delete';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_window_seconds INTEGER NOT NULL DEFAULT 3600;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_block_media BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_block_links BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_text_only BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_delete_message BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_warn_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_warn_text TEXT NOT NULL DEFAULT '新成员需等待 {duration} 才可发送媒体/链接。';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS new_member_limit_warn_delete_after_seconds INTEGER NOT NULL DEFAULT 60;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_start_time VARCHAR(5);
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_end_time VARCHAR(5);
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_whitelist_user_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_delete_message BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_warn_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_warn_text TEXT NOT NULL DEFAULT '🌙 夜间模式生效中，请稍后再试。';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS night_mode_warn_delete_after_seconds INTEGER NOT NULL DEFAULT 60;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS command_config_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS command_config JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS points_display_rule_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS points_speech_rank_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS points_personal_speech_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS control_permission_policy VARCHAR(32) NOT NULL DEFAULT 'can_promote_members';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_phrase_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_open_phrase TEXT;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_close_phrase TEXT;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_schedule_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_open_time VARCHAR(5);
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_close_time VARCHAR(5);
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS group_lock_delete_notice_mode VARCHAR(16) NOT NULL DEFAULT 'keep';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS name_change_monitor_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS name_change_monitor_template_text TEXT NOT NULL DEFAULT E'检测到用户{userId}修改{changeType}\n原{changeType}: {oldContent}\n新{changeType}: {newContent}\n\n请注意规避风险';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS name_change_monitor_delete_after_seconds INTEGER NOT NULL DEFAULT 60;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_bound_channel_1 TEXT;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_bound_channel_2 TEXT;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_cover_media_type VARCHAR(16);
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_cover_file_id VARCHAR(256);
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_guide_text TEXT NOT NULL DEFAULT '{member}，您需要关注指定频道/群组后才能发言。';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_custom_buttons_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_check_mode VARCHAR(8) NOT NULL DEFAULT 'all';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_not_subscribed_action VARCHAR(32) NOT NULL DEFAULT 'delete_and_warn';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_delete_warn_after_seconds INTEGER NOT NULL DEFAULT 60;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS force_subscribe_buttons JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_auth_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_auth_badge VARCHAR(16) NOT NULL DEFAULT '🤝';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_limit_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_limit_mode VARCHAR(16) NOT NULL DEFAULT 'none';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_limit_interval_sec INTEGER NOT NULL DEFAULT 3600;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_limit_max_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_summary_partition_by VARCHAR(16) NOT NULL DEFAULT 'region';
ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS garage_summary_only_open_course BOOLEAN NOT NULL DEFAULT FALSE;

-- ============================================
-- 4.1 欢迎消息配置表 (welcome_messages)
-- 支持多条欢迎配置与模式切换
-- ============================================
CREATE TABLE IF NOT EXISTS bot.welcome_messages (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    title VARCHAR(128) NOT NULL DEFAULT '待配置',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    welcome_mode VARCHAR(32) NOT NULL DEFAULT 'after_verify',
    cover_media_type VARCHAR(16),
    cover_media_file_id VARCHAR(256),
    text_content TEXT NOT NULL DEFAULT '{member}，欢迎加入{group}。',
    buttons JSONB NOT NULL DEFAULT '[]'::jsonb,
    delete_mode VARCHAR(32) NOT NULL DEFAULT 'seconds',
    delete_delay_seconds INTEGER,
    last_sent_message_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_welcome_messages_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_welcome_messages_chat_id ON bot.welcome_messages(chat_id);

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
-- 7.6. 自定义积分类型表 (custom_point_types)
-- 定义每个群内可用的自定义积分类型
-- ============================================
CREATE TABLE IF NOT EXISTS bot.custom_point_types (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                       -- 群组 ID（外键关联 tg_chats.id）
    type_no INTEGER NOT NULL,                                      -- 类型编号
    name VARCHAR(64) NOT NULL,                                     -- 类型名称
    rank_command VARCHAR(32),                                      -- 排行指令别名
    enabled BOOLEAN NOT NULL DEFAULT TRUE,                         -- 是否启用
    created_by_user_id BIGINT,                                     -- 创建者用户 ID
    created_at TIMESTAMPTZ NOT NULL,                               -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间（带时区）
    CONSTRAINT fk_custom_point_types_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_custom_point_types_created_by_user_id FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT uq_custom_point_type_chat_no UNIQUE (chat_id, type_no),
    CONSTRAINT uq_custom_point_type_chat_name UNIQUE (chat_id, name)
);

COMMENT ON TABLE bot.custom_point_types IS '自定义积分类型表，记录每个群内的自定义积分种类';
COMMENT ON COLUMN bot.custom_point_types.id IS '自增主键';
COMMENT ON COLUMN bot.custom_point_types.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.custom_point_types.type_no IS '类型编号';
COMMENT ON COLUMN bot.custom_point_types.name IS '类型名称';
COMMENT ON COLUMN bot.custom_point_types.rank_command IS '排行指令别名';
COMMENT ON COLUMN bot.custom_point_types.enabled IS '是否启用';
COMMENT ON COLUMN bot.custom_point_types.created_by_user_id IS '创建者用户 ID';
COMMENT ON COLUMN bot.custom_point_types.created_at IS '创建时间';
COMMENT ON COLUMN bot.custom_point_types.updated_at IS '更新时间';

CREATE INDEX IF NOT EXISTS ix_custom_point_types_chat_id ON bot.custom_point_types(chat_id);
CREATE INDEX IF NOT EXISTS ix_custom_point_types_type_no ON bot.custom_point_types(type_no);
CREATE INDEX IF NOT EXISTS ix_custom_point_types_name ON bot.custom_point_types(name);
CREATE INDEX IF NOT EXISTS ix_custom_point_types_enabled ON bot.custom_point_types(enabled);

-- ============================================
-- 7.7. 自定义积分账户表 (custom_point_accounts)
-- 记录用户在某个自定义积分类型下的余额
-- ============================================
CREATE TABLE IF NOT EXISTS bot.custom_point_accounts (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                       -- 群组 ID（外键关联 tg_chats.id）
    type_id INTEGER NOT NULL,                                      -- 类型 ID（外键关联 custom_point_types.id）
    user_id BIGINT NOT NULL,                                       -- 用户 ID（外键关联 tg_users.id）
    balance INTEGER NOT NULL DEFAULT 0,                            -- 余额
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间（带时区）
    CONSTRAINT fk_custom_point_accounts_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_custom_point_accounts_type_id FOREIGN KEY (type_id)
        REFERENCES bot.custom_point_types(id) ON DELETE CASCADE,
    CONSTRAINT fk_custom_point_accounts_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT uq_custom_point_account_chat_type_user UNIQUE (chat_id, type_id, user_id)
);

COMMENT ON TABLE bot.custom_point_accounts IS '自定义积分账户表，按群组和积分类型存储用户余额';
COMMENT ON COLUMN bot.custom_point_accounts.id IS '自增主键';
COMMENT ON COLUMN bot.custom_point_accounts.chat_id IS '群组 ID';
COMMENT ON COLUMN bot.custom_point_accounts.type_id IS '积分类型 ID';
COMMENT ON COLUMN bot.custom_point_accounts.user_id IS '用户 ID';
COMMENT ON COLUMN bot.custom_point_accounts.balance IS '余额';
COMMENT ON COLUMN bot.custom_point_accounts.updated_at IS '更新时间';

CREATE INDEX IF NOT EXISTS ix_custom_point_accounts_chat_id ON bot.custom_point_accounts(chat_id);
CREATE INDEX IF NOT EXISTS ix_custom_point_accounts_type_id ON bot.custom_point_accounts(type_id);
CREATE INDEX IF NOT EXISTS ix_custom_point_accounts_user_id ON bot.custom_point_accounts(user_id);

-- ============================================
-- 7.8. 自定义积分流水表 (custom_point_ledger)
-- 记录自定义积分增减流水
-- ============================================
CREATE TABLE IF NOT EXISTS bot.custom_point_ledger (
    id BIGSERIAL PRIMARY KEY,                                      -- 自增主键
    chat_id BIGINT NOT NULL,                                       -- 群组 ID
    type_id INTEGER NOT NULL,                                      -- 类型 ID
    user_id BIGINT NOT NULL,                                       -- 用户 ID
    delta INTEGER NOT NULL,                                        -- 变动值
    reason_note TEXT,                                              -- 备注说明
    operator_user_id BIGINT,                                       -- 操作者用户 ID
    created_at TIMESTAMPTZ NOT NULL,                               -- 创建时间（带时区）
    CONSTRAINT fk_custom_point_ledger_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_custom_point_ledger_type_id FOREIGN KEY (type_id)
        REFERENCES bot.custom_point_types(id) ON DELETE CASCADE,
    CONSTRAINT fk_custom_point_ledger_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT fk_custom_point_ledger_operator_user_id FOREIGN KEY (operator_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

COMMENT ON TABLE bot.custom_point_ledger IS '自定义积分流水表，记录所有自定义积分变动';
COMMENT ON COLUMN bot.custom_point_ledger.id IS '自增主键';
COMMENT ON COLUMN bot.custom_point_ledger.chat_id IS '群组 ID';
COMMENT ON COLUMN bot.custom_point_ledger.type_id IS '积分类型 ID';
COMMENT ON COLUMN bot.custom_point_ledger.user_id IS '用户 ID';
COMMENT ON COLUMN bot.custom_point_ledger.delta IS '变动值，正数为增加，负数为减少';
COMMENT ON COLUMN bot.custom_point_ledger.reason_note IS '变动备注';
COMMENT ON COLUMN bot.custom_point_ledger.operator_user_id IS '操作者用户 ID';
COMMENT ON COLUMN bot.custom_point_ledger.created_at IS '创建时间';

CREATE INDEX IF NOT EXISTS ix_custom_point_ledger_chat_id ON bot.custom_point_ledger(chat_id);
CREATE INDEX IF NOT EXISTS ix_custom_point_ledger_type_id ON bot.custom_point_ledger(type_id);
CREATE INDEX IF NOT EXISTS ix_custom_point_ledger_user_id ON bot.custom_point_ledger(user_id);
CREATE INDEX IF NOT EXISTS ix_custom_point_ledger_created_at ON bot.custom_point_ledger(created_at);
CREATE INDEX IF NOT EXISTS ix_custom_point_ledger_operator_user_id ON bot.custom_point_ledger(operator_user_id);

-- ============================================
-- 7.9. 积分等级设置表 (points_level_settings)
-- 记录每个群的积分等级功能开关
-- ============================================
CREATE TABLE IF NOT EXISTS bot.points_level_settings (
    chat_id BIGINT PRIMARY KEY,                                    -- 群组 ID（外键关联 tg_chats.id）
    enabled BOOLEAN NOT NULL DEFAULT FALSE,                        -- 是否启用
    exclude_teacher_enabled BOOLEAN NOT NULL DEFAULT FALSE,       -- 是否排除老师
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间（带时区）
    CONSTRAINT fk_points_level_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

COMMENT ON TABLE bot.points_level_settings IS '积分等级设置表，记录每个群的积分等级功能开关';
COMMENT ON COLUMN bot.points_level_settings.chat_id IS '群组 ID';
COMMENT ON COLUMN bot.points_level_settings.enabled IS '是否启用';
COMMENT ON COLUMN bot.points_level_settings.exclude_teacher_enabled IS '是否排除老师';
COMMENT ON COLUMN bot.points_level_settings.updated_at IS '更新时间';

-- ============================================
-- 7.10. 积分等级表 (points_levels)
-- 定义各积分门槛对应的权限等级
-- ============================================
CREATE TABLE IF NOT EXISTS bot.points_levels (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                       -- 群组 ID
    level_no INTEGER NOT NULL,                                     -- 等级编号
    level_name VARCHAR(64) NOT NULL,                               -- 等级名称
    point_threshold INTEGER NOT NULL,                              -- 积分门槛
    allow_text BOOLEAN NOT NULL DEFAULT TRUE,                      -- 允许发文字
    allow_audio BOOLEAN NOT NULL DEFAULT TRUE,                     -- 允许发语音
    allow_photo BOOLEAN NOT NULL DEFAULT TRUE,                     -- 允许发图片
    allow_video BOOLEAN NOT NULL DEFAULT TRUE,                     -- 允许发视频
    allow_sticker BOOLEAN NOT NULL DEFAULT TRUE,                   -- 允许发贴纸
    allow_document BOOLEAN NOT NULL DEFAULT TRUE,                  -- 允许发文件
    allow_mention BOOLEAN NOT NULL DEFAULT TRUE,                   -- 允许发送@提到
    enabled BOOLEAN NOT NULL DEFAULT TRUE,                         -- 是否启用
    created_at TIMESTAMPTZ NOT NULL,                               -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间
    CONSTRAINT fk_points_levels_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT uq_points_level_chat_no UNIQUE (chat_id, level_no),
    CONSTRAINT uq_points_level_chat_threshold UNIQUE (chat_id, point_threshold)
);

COMMENT ON TABLE bot.points_levels IS '积分等级表，定义不同积分门槛对应的发送权限等级';
COMMENT ON COLUMN bot.points_levels.id IS '自增主键';
COMMENT ON COLUMN bot.points_levels.chat_id IS '群组 ID';
COMMENT ON COLUMN bot.points_levels.level_no IS '等级编号';
COMMENT ON COLUMN bot.points_levels.level_name IS '等级名称';
COMMENT ON COLUMN bot.points_levels.point_threshold IS '积分门槛';
COMMENT ON COLUMN bot.points_levels.allow_text IS '是否允许发文字';
COMMENT ON COLUMN bot.points_levels.allow_audio IS '是否允许发语音';
COMMENT ON COLUMN bot.points_levels.allow_photo IS '是否允许发图片';
COMMENT ON COLUMN bot.points_levels.allow_video IS '是否允许发视频';
COMMENT ON COLUMN bot.points_levels.allow_sticker IS '是否允许发贴纸';
COMMENT ON COLUMN bot.points_levels.allow_document IS '是否允许发文件';
COMMENT ON COLUMN bot.points_levels.allow_mention IS '是否允许发送@提到';
COMMENT ON COLUMN bot.points_levels.enabled IS '是否启用';
COMMENT ON COLUMN bot.points_levels.created_at IS '创建时间';
COMMENT ON COLUMN bot.points_levels.updated_at IS '更新时间';

CREATE INDEX IF NOT EXISTS ix_points_levels_chat_id ON bot.points_levels(chat_id);
CREATE INDEX IF NOT EXISTS ix_points_levels_level_no ON bot.points_levels(level_no);
CREATE INDEX IF NOT EXISTS ix_points_levels_point_threshold ON bot.points_levels(point_threshold);
CREATE INDEX IF NOT EXISTS ix_points_levels_enabled ON bot.points_levels(enabled);

-- ============================================
-- 7.11. 积分商城设置表 (points_mall_settings)
-- 记录每个群的积分商城全局配置
-- ============================================
CREATE TABLE IF NOT EXISTS bot.points_mall_settings (
    chat_id BIGINT PRIMARY KEY,                                    -- 群组 ID（外键关联 tg_chats.id）
    enabled BOOLEAN NOT NULL DEFAULT FALSE,                        -- 是否启用
    entry_command VARCHAR(32) NOT NULL DEFAULT '积分商城',         -- 入口指令
    auto_unlist_when_out_of_stock BOOLEAN NOT NULL DEFAULT FALSE,   -- 无货是否自动下架
    redeem_notice_delete_seconds INTEGER NOT NULL DEFAULT 60,      -- 兑换提示删除时间
    cover_media_type VARCHAR(16),                                  -- 封面类型
    cover_file_id VARCHAR(256),                                    -- 封面文件 ID
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间
    CONSTRAINT fk_points_mall_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

COMMENT ON TABLE bot.points_mall_settings IS '积分商城设置表，记录每个群的积分商城全局配置';
COMMENT ON COLUMN bot.points_mall_settings.chat_id IS '群组 ID';
COMMENT ON COLUMN bot.points_mall_settings.enabled IS '是否启用';
COMMENT ON COLUMN bot.points_mall_settings.entry_command IS '商城入口指令';
COMMENT ON COLUMN bot.points_mall_settings.auto_unlist_when_out_of_stock IS '无货是否自动下架';
COMMENT ON COLUMN bot.points_mall_settings.redeem_notice_delete_seconds IS '兑换提示删除时间';
COMMENT ON COLUMN bot.points_mall_settings.cover_media_type IS '封面类型';
COMMENT ON COLUMN bot.points_mall_settings.cover_file_id IS '封面文件 ID';
COMMENT ON COLUMN bot.points_mall_settings.updated_at IS '更新时间';

-- ============================================
-- 7.12. 积分商城商品表 (points_mall_products)
-- 记录每个群的商城商品信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.points_mall_products (
    product_id SERIAL PRIMARY KEY,                                 -- 商品 ID
    chat_id BIGINT NOT NULL,                                       -- 群组 ID
    name VARCHAR(128) NOT NULL,                                    -- 商品名称
    price_points INTEGER NOT NULL,                                 -- 所需积分
    stock_total INTEGER NOT NULL DEFAULT 0,                         -- 库存总量
    stock_left INTEGER NOT NULL DEFAULT 0,                          -- 剩余库存
    status VARCHAR(16) NOT NULL DEFAULT 'on_sale',                  -- 状态
    cover_media_type VARCHAR(16),                                  -- 封面类型
    cover_file_id VARCHAR(256),                                    -- 封面文件 ID
    limit_per_user INTEGER,                                        -- 单人限购
    fulfiller_user_id BIGINT,                                      -- 发放人
    description TEXT,                                              -- 商品说明
    sort_weight INTEGER NOT NULL DEFAULT 0,                         -- 排序权重
    created_at TIMESTAMPTZ NOT NULL,                               -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间
    CONSTRAINT fk_points_mall_products_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_points_mall_products_fulfiller_user_id FOREIGN KEY (fulfiller_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

COMMENT ON TABLE bot.points_mall_products IS '积分商城商品表，记录每个群的商城商品信息';
COMMENT ON COLUMN bot.points_mall_products.product_id IS '商品 ID';
COMMENT ON COLUMN bot.points_mall_products.chat_id IS '群组 ID';
COMMENT ON COLUMN bot.points_mall_products.name IS '商品名称';
COMMENT ON COLUMN bot.points_mall_products.price_points IS '所需积分';
COMMENT ON COLUMN bot.points_mall_products.stock_total IS '库存总量';
COMMENT ON COLUMN bot.points_mall_products.stock_left IS '剩余库存';
COMMENT ON COLUMN bot.points_mall_products.status IS '状态';
COMMENT ON COLUMN bot.points_mall_products.cover_media_type IS '封面类型';
COMMENT ON COLUMN bot.points_mall_products.cover_file_id IS '封面文件 ID';
COMMENT ON COLUMN bot.points_mall_products.limit_per_user IS '单人限购';
COMMENT ON COLUMN bot.points_mall_products.fulfiller_user_id IS '发放人';
COMMENT ON COLUMN bot.points_mall_products.description IS '商品说明';
COMMENT ON COLUMN bot.points_mall_products.sort_weight IS '排序权重';
COMMENT ON COLUMN bot.points_mall_products.created_at IS '创建时间';
COMMENT ON COLUMN bot.points_mall_products.updated_at IS '更新时间';

CREATE INDEX IF NOT EXISTS ix_points_mall_products_chat_id ON bot.points_mall_products(chat_id);
CREATE INDEX IF NOT EXISTS ix_points_mall_products_name ON bot.points_mall_products(name);
CREATE INDEX IF NOT EXISTS ix_points_mall_products_status ON bot.points_mall_products(status);
CREATE INDEX IF NOT EXISTS ix_points_mall_products_sort_weight ON bot.points_mall_products(sort_weight);
CREATE INDEX IF NOT EXISTS ix_points_mall_products_fulfiller_user_id ON bot.points_mall_products(fulfiller_user_id);
CREATE INDEX IF NOT EXISTS ix_points_mall_products_created_at ON bot.points_mall_products(created_at);

-- ============================================
-- 7.13. 积分商城订单表 (points_mall_orders)
-- 记录用户的兑换订单
-- ============================================
CREATE TABLE IF NOT EXISTS bot.points_mall_orders (
    order_id SERIAL PRIMARY KEY,                                   -- 订单 ID
    chat_id BIGINT NOT NULL,                                       -- 群组 ID
    product_id INTEGER NOT NULL,                                   -- 商品 ID
    buyer_user_id BIGINT NOT NULL,                                 -- 买家用户 ID
    price_points INTEGER NOT NULL,                                 -- 价格积分
    quantity INTEGER NOT NULL DEFAULT 1,                            -- 数量
    order_status VARCHAR(16) NOT NULL DEFAULT 'created',           -- 订单状态
    operator_user_id BIGINT,                                       -- 操作人
    created_at TIMESTAMPTZ NOT NULL,                               -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间
    CONSTRAINT fk_points_mall_orders_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_points_mall_orders_product_id FOREIGN KEY (product_id)
        REFERENCES bot.points_mall_products(product_id) ON DELETE CASCADE,
    CONSTRAINT fk_points_mall_orders_buyer_user_id FOREIGN KEY (buyer_user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT fk_points_mall_orders_operator_user_id FOREIGN KEY (operator_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

COMMENT ON TABLE bot.points_mall_orders IS '积分商城订单表，记录用户的兑换订单';
COMMENT ON COLUMN bot.points_mall_orders.order_id IS '订单 ID';
COMMENT ON COLUMN bot.points_mall_orders.chat_id IS '群组 ID';
COMMENT ON COLUMN bot.points_mall_orders.product_id IS '商品 ID';
COMMENT ON COLUMN bot.points_mall_orders.buyer_user_id IS '买家用户 ID';
COMMENT ON COLUMN bot.points_mall_orders.price_points IS '价格积分';
COMMENT ON COLUMN bot.points_mall_orders.quantity IS '数量';
COMMENT ON COLUMN bot.points_mall_orders.order_status IS '订单状态';
COMMENT ON COLUMN bot.points_mall_orders.operator_user_id IS '操作人';
COMMENT ON COLUMN bot.points_mall_orders.created_at IS '创建时间';
COMMENT ON COLUMN bot.points_mall_orders.updated_at IS '更新时间';

CREATE INDEX IF NOT EXISTS ix_points_mall_orders_chat_id ON bot.points_mall_orders(chat_id);
CREATE INDEX IF NOT EXISTS ix_points_mall_orders_product_id ON bot.points_mall_orders(product_id);
CREATE INDEX IF NOT EXISTS ix_points_mall_orders_buyer_user_id ON bot.points_mall_orders(buyer_user_id);
CREATE INDEX IF NOT EXISTS ix_points_mall_orders_order_status ON bot.points_mall_orders(order_status);
CREATE INDEX IF NOT EXISTS ix_points_mall_orders_operator_user_id ON bot.points_mall_orders(operator_user_id);
CREATE INDEX IF NOT EXISTS ix_points_mall_orders_created_at ON bot.points_mall_orders(created_at);

-- ============================================
-- 7.14. 积分商城订单流水表 (points_mall_order_logs)
-- 记录订单操作历史
-- ============================================
CREATE TABLE IF NOT EXISTS bot.points_mall_order_logs (
    id BIGSERIAL PRIMARY KEY,                                      -- 自增主键
    order_id INTEGER NOT NULL,                                     -- 订单 ID
    action VARCHAR(32) NOT NULL,                                   -- 动作
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,                    -- 额外载荷
    created_at TIMESTAMPTZ NOT NULL,                               -- 创建时间
    CONSTRAINT fk_points_mall_order_logs_order_id FOREIGN KEY (order_id)
        REFERENCES bot.points_mall_orders(order_id) ON DELETE CASCADE
);

COMMENT ON TABLE bot.points_mall_order_logs IS '积分商城订单流水表，记录订单操作历史';
COMMENT ON COLUMN bot.points_mall_order_logs.id IS '自增主键';
COMMENT ON COLUMN bot.points_mall_order_logs.order_id IS '订单 ID';
COMMENT ON COLUMN bot.points_mall_order_logs.action IS '动作';
COMMENT ON COLUMN bot.points_mall_order_logs.payload IS '额外载荷';
COMMENT ON COLUMN bot.points_mall_order_logs.created_at IS '创建时间';

CREATE INDEX IF NOT EXISTS ix_points_mall_order_logs_order_id ON bot.points_mall_order_logs(order_id);
CREATE INDEX IF NOT EXISTS ix_points_mall_order_logs_action ON bot.points_mall_order_logs(action);
CREATE INDEX IF NOT EXISTS ix_points_mall_order_logs_created_at ON bot.points_mall_order_logs(created_at);

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
-- 8.1. 审核警告计数表 (moderation_warnings)
-- 存储群内用户警告次数，默认 7 天滚动清零
-- ============================================
CREATE TABLE IF NOT EXISTS bot.moderation_warnings (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    warning_count INTEGER NOT NULL DEFAULT 0,
    last_rule VARCHAR(64),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_moderation_warnings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_moderation_warnings_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT uq_moderation_warnings_chat_user UNIQUE (chat_id, user_id)
);

COMMENT ON TABLE bot.moderation_warnings IS '审核警告计数表，按群和用户记录警告次数';
COMMENT ON COLUMN bot.moderation_warnings.warning_count IS '当前有效警告次数';
COMMENT ON COLUMN bot.moderation_warnings.last_rule IS '最后一次触发警告的规则';
COMMENT ON COLUMN bot.moderation_warnings.expires_at IS '警告次数过期时间';

CREATE INDEX IF NOT EXISTS ix_moderation_warnings_chat_id ON bot.moderation_warnings(chat_id);
CREATE INDEX IF NOT EXISTS ix_moderation_warnings_user_id ON bot.moderation_warnings(user_id);
CREATE INDEX IF NOT EXISTS ix_moderation_warnings_expires_at ON bot.moderation_warnings(expires_at);

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
    verification_type VARCHAR(16) NOT NULL DEFAULT 'button',      -- 验证类型（button/math/captcha/admin）
    question TEXT,                                               -- 验证问题（数学题等）
    answer VARCHAR(64),                                          -- 答案
    timeout_handled BOOLEAN NOT NULL DEFAULT FALSE,              -- 超时是否已处理（防止重复处理）
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
COMMENT ON COLUMN bot.verification_challenges.verification_type IS '验证类型：button（按钮验证）、math（数学题）、captcha（验证码）、admin（管理员确认）';
COMMENT ON COLUMN bot.verification_challenges.question IS '验证问题，用于数学题模式等';
COMMENT ON COLUMN bot.verification_challenges.answer IS '验证答案，用于验证用户输入';
COMMENT ON COLUMN bot.verification_challenges.timeout_handled IS '超时是否已处理标志，用于防止定时任务重复处理超时验证';
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
-- 12. 续费卡密与审计
-- ============================================
CREATE TABLE IF NOT EXISTS bot.renewal_card_keys (
    id SERIAL PRIMARY KEY,
    card_key_hash VARCHAR(128) NOT NULL,
    duration_seconds INTEGER NOT NULL,
    expires_at TIMESTAMPTZ,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    used_by_chat_id BIGINT,
    used_by_user_id BIGINT,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_renewal_card_key_hash UNIQUE (card_key_hash),
    CONSTRAINT fk_renewal_card_keys_used_by_chat_id FOREIGN KEY (used_by_chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE SET NULL,
    CONSTRAINT fk_renewal_card_keys_used_by_user_id FOREIGN KEY (used_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS bot.renewal_audit_logs (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    operator_user_id BIGINT,
    action VARCHAR(32) NOT NULL,
    reason VARCHAR(128),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_renewal_audit_logs_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_renewal_audit_logs_operator_user_id FOREIGN KEY (operator_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

COMMENT ON TABLE bot.renewal_card_keys IS '续费卡密表，仅存储卡密哈希和核销状态';
COMMENT ON COLUMN bot.renewal_card_keys.card_key_hash IS '续费卡密哈希值，不存储明文卡密';
COMMENT ON COLUMN bot.renewal_card_keys.duration_seconds IS '核销成功后增加的时长（秒）';
COMMENT ON COLUMN bot.renewal_card_keys.expires_at IS '卡密失效时间，NULL 表示永不过期';
COMMENT ON COLUMN bot.renewal_card_keys.used IS '卡密是否已被使用';
COMMENT ON COLUMN bot.renewal_card_keys.used_by_chat_id IS '核销到的群组';
COMMENT ON COLUMN bot.renewal_card_keys.used_by_user_id IS '执行核销的操作人';
COMMENT ON COLUMN bot.renewal_card_keys.used_at IS '核销时间';
COMMENT ON COLUMN bot.renewal_card_keys.created_at IS '卡密创建时间';

COMMENT ON TABLE bot.renewal_audit_logs IS '续费审计日志，记录核销成功和失败原因';
COMMENT ON COLUMN bot.renewal_audit_logs.chat_id IS '目标群组 ID';
COMMENT ON COLUMN bot.renewal_audit_logs.operator_user_id IS '执行续费操作的用户 ID';
COMMENT ON COLUMN bot.renewal_audit_logs.action IS '审计动作，如 success / failed';
COMMENT ON COLUMN bot.renewal_audit_logs.reason IS '动作原因，如 redeem / card_used / card_not_found';
COMMENT ON COLUMN bot.renewal_audit_logs.payload IS '补充审计上下文';
COMMENT ON COLUMN bot.renewal_audit_logs.created_at IS '审计记录创建时间';

CREATE INDEX IF NOT EXISTS ix_renewal_card_keys_expires_at ON bot.renewal_card_keys(expires_at);
CREATE INDEX IF NOT EXISTS ix_renewal_card_keys_used ON bot.renewal_card_keys(used);
CREATE INDEX IF NOT EXISTS ix_renewal_audit_logs_chat_id ON bot.renewal_audit_logs(chat_id);
CREATE INDEX IF NOT EXISTS ix_renewal_audit_logs_created_at ON bot.renewal_audit_logs(created_at);

-- ============================================
-- 13. 广告活动表 (ad_campaigns)
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
    buttons JSONB NOT NULL DEFAULT '[]'::jsonb,                  -- 按钮配置
    sort_order INTEGER NOT NULL DEFAULT 1,                       -- 轮播顺序
    end_time TIMESTAMPTZ,                                        -- 结束时间
    last_sent_message_id INTEGER,                                -- 上次发送的消息 ID
    last_sent_cycle_no INTEGER NOT NULL DEFAULT 0,               -- 上次发送所在轮次
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
COMMENT ON COLUMN bot.ad_campaigns.buttons IS '轮播按钮配置';
COMMENT ON COLUMN bot.ad_campaigns.sort_order IS '轮播顺序';
COMMENT ON COLUMN bot.ad_campaigns.end_time IS '结束时间';
COMMENT ON COLUMN bot.ad_campaigns.last_sent_message_id IS '上次发送的消息 ID';
COMMENT ON COLUMN bot.ad_campaigns.last_sent_cycle_no IS '上次发送所在轮次';
COMMENT ON COLUMN bot.ad_campaigns.created_at IS '广告创建时间';
COMMENT ON COLUMN bot.ad_campaigns.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_ad_campaigns_chat_id ON bot.ad_campaigns(chat_id);
CREATE INDEX IF NOT EXISTS ix_ad_campaigns_schedule_time ON bot.ad_campaigns(schedule_time);
CREATE INDEX IF NOT EXISTS ix_ad_campaigns_enabled ON bot.ad_campaigns(enabled);
CREATE INDEX IF NOT EXISTS ix_ad_campaigns_sort_order ON bot.ad_campaigns(sort_order);

-- ============================================
-- 14. 轮播规则表 (ad_rotation_rules)
-- 每个群唯一一条规则，用于控制轮播状态与调度
-- ============================================
CREATE TABLE IF NOT EXISTS bot.ad_rotation_rules (
    chat_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    start_at TIMESTAMPTZ,
    interval_seconds INTEGER NOT NULL DEFAULT 7200,
    mode VARCHAR(16) NOT NULL DEFAULT 'send',
    delete_policy VARCHAR(32) NOT NULL DEFAULT 'delete_prev_cycle',
    delete_delay_seconds INTEGER NOT NULL DEFAULT 60,
    unpin_previous BOOLEAN NOT NULL DEFAULT TRUE,
    last_sent_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    current_order_cursor INTEGER NOT NULL DEFAULT 1,
    last_sent_item_id INTEGER,
    last_sent_message_id INTEGER,
    last_pinned_message_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_ad_rotation_rules_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_ad_rotation_rules_last_sent_item_id FOREIGN KEY (last_sent_item_id)
        REFERENCES bot.ad_campaigns(id) ON DELETE SET NULL
);

COMMENT ON TABLE bot.ad_rotation_rules IS '群级轮播规则表';
COMMENT ON COLUMN bot.ad_rotation_rules.chat_id IS '群组 ID';
COMMENT ON COLUMN bot.ad_rotation_rules.enabled IS '轮播是否启用';
COMMENT ON COLUMN bot.ad_rotation_rules.start_at IS '轮播开始时间';
COMMENT ON COLUMN bot.ad_rotation_rules.interval_seconds IS '轮播间隔秒数';
COMMENT ON COLUMN bot.ad_rotation_rules.mode IS '轮播方式：send/send_pin';
COMMENT ON COLUMN bot.ad_rotation_rules.delete_policy IS '删除规则';
COMMENT ON COLUMN bot.ad_rotation_rules.delete_delay_seconds IS '延迟删除秒数';
COMMENT ON COLUMN bot.ad_rotation_rules.unpin_previous IS '是否取消上一条轮播置顶';
COMMENT ON COLUMN bot.ad_rotation_rules.last_sent_at IS '上次轮播时间';
COMMENT ON COLUMN bot.ad_rotation_rules.next_run_at IS '下次轮播时间';
COMMENT ON COLUMN bot.ad_rotation_rules.current_order_cursor IS '当前轮播游标';
COMMENT ON COLUMN bot.ad_rotation_rules.last_sent_item_id IS '上次轮播消息 ID';
COMMENT ON COLUMN bot.ad_rotation_rules.last_sent_message_id IS '上次发送到 TG 的消息 ID';
COMMENT ON COLUMN bot.ad_rotation_rules.last_pinned_message_id IS '上次置顶的消息 ID';

CREATE INDEX IF NOT EXISTS ix_ad_rotation_rules_enabled ON bot.ad_rotation_rules(enabled);
CREATE INDEX IF NOT EXISTS ix_ad_rotation_rules_next_run_at ON bot.ad_rotation_rules(next_run_at);

-- ============================================
-- 15. 对话状态表 (conversation_states)
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
    lottery_type VARCHAR(16) NOT NULL DEFAULT 'common',           -- 抽奖类型（common/points/invite/activity）
    draw_time TIMESTAMPTZ NOT NULL,                               -- 开奖时间（带时区）
    prizes JSONB NOT NULL DEFAULT '[]',                           -- 奖品列表（JSONB 数组格式）
    draw_mode VARCHAR(16) NOT NULL DEFAULT 'manual',              -- 开奖模式（random=随机开奖，manual=手动指定中奖人）
    status VARCHAR(16) NOT NULL DEFAULT 'pending',                -- 抽奖状态（pending/completed/cancelled）
    message_id INTEGER,                                           -- 抽奖消息的 Telegram message_id
    qualification_rules JSONB NOT NULL DEFAULT '{}'::jsonb,       -- 类型附加资格规则
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
COMMENT ON COLUMN bot.lotteries.lottery_type IS '抽奖类型：common（通用）、points（积分）、invite（邀请）、activity（活跃）';
COMMENT ON COLUMN bot.lotteries.draw_time IS '计划开奖时间';
COMMENT ON COLUMN bot.lotteries.prizes IS '奖品列表，JSONB 数组格式存储，如：[{"name": "一等奖", "quantity": 1}]';
COMMENT ON COLUMN bot.lotteries.draw_mode IS '开奖模式：random（随机开奖）、manual（手动指定中奖人）';
COMMENT ON COLUMN bot.lotteries.status IS '抽奖状态：pending（待开奖）、completed（已完成）、cancelled（已取消）';
COMMENT ON COLUMN bot.lotteries.message_id IS '抽奖消息的 Telegram message_id，用于更新消息';
COMMENT ON COLUMN bot.lotteries.qualification_rules IS '附加资格规则，邀请/活跃抽奖使用 JSONB 存储门槛';
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
ALTER TABLE IF EXISTS bot.lotteries ADD COLUMN IF NOT EXISTS lottery_type VARCHAR(16) NOT NULL DEFAULT 'common';
ALTER TABLE IF EXISTS bot.lotteries ADD COLUMN IF NOT EXISTS qualification_rules JSONB NOT NULL DEFAULT '{}'::jsonb;

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
    points_reward INTEGER NOT NULL DEFAULT 0,                     -- 积分奖励
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
COMMENT ON COLUMN bot.lottery_winners.points_reward IS '中奖附带积分奖励';
COMMENT ON COLUMN bot.lottery_winners.created_at IS '中奖时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_lottery_winners_lottery_id ON bot.lottery_winners(lottery_id);
CREATE INDEX IF NOT EXISTS ix_lottery_winners_user_id ON bot.lottery_winners(user_id);
ALTER TABLE bot.lottery_winners ADD COLUMN IF NOT EXISTS points_reward INTEGER NOT NULL DEFAULT 0;

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
    cover_media_type VARCHAR(16),                                -- 封面类型
    cover_media_file_id VARCHAR(256),                            -- 封面文件 ID
    buttons JSONB NOT NULL DEFAULT '[]',                         -- 按钮布局（JSON 数组格式）
    match_type VARCHAR(16) NOT NULL DEFAULT 'contains',          -- 匹配类型（contains/exact/regex）
    sort_order INTEGER NOT NULL DEFAULT 0,                       -- 命中顺序（越小越优先）
    delete_source BOOLEAN NOT NULL DEFAULT FALSE,                -- 命中后是否删除触发消息
    delete_reply_delay_seconds INTEGER NOT NULL DEFAULT 0,       -- 回复延迟删除秒数（0=不删除）
    is_active BOOLEAN NOT NULL DEFAULT TRUE,                     -- 是否激活
    match_count INTEGER NOT NULL DEFAULT 0,                      -- 匹配次数统计
    case_sensitive BOOLEAN NOT NULL DEFAULT FALSE,               -- 是否区分大小写
    stop_after_match BOOLEAN NOT NULL DEFAULT TRUE,              -- 命中后是否停止继续匹配
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
COMMENT ON COLUMN bot.auto_reply_rules.cover_media_type IS '自动回复封面类型：photo/video';
COMMENT ON COLUMN bot.auto_reply_rules.cover_media_file_id IS '自动回复封面文件 ID';
COMMENT ON COLUMN bot.auto_reply_rules.buttons IS '自动回复按钮布局（JSONB）';
COMMENT ON COLUMN bot.auto_reply_rules.match_type IS '匹配类型：contains（包含匹配）、exact（精确匹配）、regex（正则表达式）';
COMMENT ON COLUMN bot.auto_reply_rules.sort_order IS '规则命中顺序，越小越优先';
COMMENT ON COLUMN bot.auto_reply_rules.delete_source IS '命中后是否删除触发消息';
COMMENT ON COLUMN bot.auto_reply_rules.delete_reply_delay_seconds IS '回复延迟删除秒数，0 表示不删除';
COMMENT ON COLUMN bot.auto_reply_rules.is_active IS '是否激活（true=启用，false=禁用）';
COMMENT ON COLUMN bot.auto_reply_rules.match_count IS '规则被触发的次数统计';
COMMENT ON COLUMN bot.auto_reply_rules.case_sensitive IS '是否区分大小写';
COMMENT ON COLUMN bot.auto_reply_rules.stop_after_match IS '命中后是否停止继续匹配（true=命中后停止）';
COMMENT ON COLUMN bot.auto_reply_rules.created_at IS '规则创建时间';
COMMENT ON COLUMN bot.auto_reply_rules.updated_at IS '记录最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_auto_reply_rules_chat_id ON bot.auto_reply_rules(chat_id);
CREATE INDEX IF NOT EXISTS ix_auto_reply_rules_is_active ON bot.auto_reply_rules(is_active);
CREATE INDEX IF NOT EXISTS ix_auto_reply_rules_chat_sort ON bot.auto_reply_rules(chat_id, sort_order);
ALTER TABLE bot.auto_reply_rules ADD COLUMN IF NOT EXISTS cover_media_type VARCHAR(16);
ALTER TABLE bot.auto_reply_rules ADD COLUMN IF NOT EXISTS cover_media_file_id VARCHAR(256);
ALTER TABLE bot.auto_reply_rules ADD COLUMN IF NOT EXISTS buttons JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE bot.auto_reply_rules ADD COLUMN IF NOT EXISTS stop_after_match BOOLEAN NOT NULL DEFAULT TRUE;

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
-- 23. 定时消息任务表 (scheduled_message_tasks)
-- 存储定时消息任务的完整配置
-- ============================================
CREATE TABLE IF NOT EXISTS bot.scheduled_message_tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),              -- UUID 主键
    short_id VARCHAR(8) NOT NULL,                                    -- 短 ID（用于 callback_data）
    chat_id BIGINT NOT NULL,                                         -- 群组 ID（外键关联 tg_chats.id）
    created_by_user_id BIGINT,                                       -- 创建者用户 ID（外键关联 tg_users.id）
    title VARCHAR(128) NOT NULL,                                     -- 任务标题
    enabled BOOLEAN NOT NULL DEFAULT TRUE,                           -- 是否启用

    -- 重复配置
    repeat_interval_min INTEGER NOT NULL DEFAULT 60,                 -- 重复间隔（分钟）：10/15/20/30/60/120/180/240/360/480/720/1440
    day_start_hour INTEGER NOT NULL DEFAULT 0,                       -- 每日开始小时（0-23）
    day_end_hour INTEGER NOT NULL DEFAULT 23,                        -- 每日结束小时（0-23）

    -- 时间范围（Unix 时间戳）
    start_at BIGINT,                                                 -- 开始时间（Unix 时间戳）
    end_at BIGINT,                                                   -- 终止时间（Unix 时间戳）

    -- 内容配置
    text TEXT,                                                       -- 消息文本
    parse_mode VARCHAR(16) NOT NULL DEFAULT 'HTML',                  -- 解析模式：HTML/Markdown/None
    media_type VARCHAR(16) NOT NULL DEFAULT 'none',                  -- 媒体类型：photo/video/sticker/animation/document/none
    media_file_id VARCHAR(256),                                      -- 媒体文件 ID（Telegram）
    buttons JSONB NOT NULL DEFAULT '[]',                             -- 按钮配置（JSONB）：[[{text,url},...],...]

    -- 发送选项
    delete_previous BOOLEAN NOT NULL DEFAULT TRUE,                   -- 发送前删除上一条
    pin_message BOOLEAN NOT NULL DEFAULT FALSE,                      -- 置顶消息

    -- 执行状态
    last_sent_message_id INTEGER,                                    -- 上次发送的消息 ID
    next_run_at BIGINT,                                              -- 下次执行时间（Unix 时间戳）

    -- 时间戳
    created_at TIMESTAMPTZ NOT NULL,                                 -- 创建时间（带时区）
    updated_at TIMESTAMPTZ NOT NULL,                                 -- 更新时间（带时区）

    CONSTRAINT fk_smt_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,                   -- 外键约束：删除群组时级联删除任务
    CONSTRAINT fk_smt_created_by FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL                  -- 外键约束：删除用户时将创建者设为 NULL
);

COMMENT ON TABLE bot.scheduled_message_tasks IS '定时消息任务表，支持灵活的定时消息发送配置';
COMMENT ON COLUMN bot.scheduled_message_tasks.task_id IS 'UUID 主键，唯一标识任务';
COMMENT ON COLUMN bot.scheduled_message_tasks.short_id IS '短 ID（8 位），用于 callback_data 和人工操作';
COMMENT ON COLUMN bot.scheduled_message_tasks.chat_id IS '群组 ID，外键关联 tg_chats.id';
COMMENT ON COLUMN bot.scheduled_message_tasks.created_by_user_id IS '创建者用户 ID，外键关联 tg_users.id，删除用户时设为 NULL';
COMMENT ON COLUMN bot.scheduled_message_tasks.title IS '任务标题，用于识别和管理';
COMMENT ON COLUMN bot.scheduled_message_tasks.enabled IS '是否启用任务（true=启用，false=禁用）';
COMMENT ON COLUMN bot.scheduled_message_tasks.repeat_interval_min IS '重复间隔（分钟），支持：10/15/20/30/60/120/180/240/360/480/720/1440';
COMMENT ON COLUMN bot.scheduled_message_tasks.day_start_hour IS '每日开始小时（0-23），用于时段限制';
COMMENT ON COLUMN bot.scheduled_message_tasks.day_end_hour IS '每日结束小时（0-23），用于时段限制';
COMMENT ON COLUMN bot.scheduled_message_tasks.start_at IS '任务开始时间（Unix 时间戳），NULL 表示立即开始';
COMMENT ON COLUMN bot.scheduled_message_tasks.end_at IS '任务终止时间（Unix 时间戳），NULL 表示无限制';
COMMENT ON COLUMN bot.scheduled_message_tasks.text IS '消息文本内容';
COMMENT ON COLUMN bot.scheduled_message_tasks.parse_mode IS '解析模式：HTML/Markdown/None';
COMMENT ON COLUMN bot.scheduled_message_tasks.media_type IS '媒体类型：photo/video/sticker/animation/document/none';
COMMENT ON COLUMN bot.scheduled_message_tasks.media_file_id IS 'Telegram 媒体文件 ID，用于发送媒体消息';
COMMENT ON COLUMN bot.scheduled_message_tasks.buttons IS '按钮配置，JSONB 数组格式，如：[[{"text":"按钮1","url":"https://..."}],...]';
COMMENT ON COLUMN bot.scheduled_message_tasks.delete_previous IS '发送前是否删除上一条消息（true=删除，false=保留）';
COMMENT ON COLUMN bot.scheduled_message_tasks.pin_message IS '是否置顶消息（true=置顶，false=不置顶）';
COMMENT ON COLUMN bot.scheduled_message_tasks.last_sent_message_id IS '上次发送的消息的 Telegram message_id';
COMMENT ON COLUMN bot.scheduled_message_tasks.next_run_at IS '下次执行时间（Unix 时间戳）';
COMMENT ON COLUMN bot.scheduled_message_tasks.created_at IS '任务创建时间';
COMMENT ON COLUMN bot.scheduled_message_tasks.updated_at IS '任务最后更新时间';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_smt_chat_id ON bot.scheduled_message_tasks(chat_id);
CREATE INDEX IF NOT EXISTS ix_smt_enabled ON bot.scheduled_message_tasks(enabled);
CREATE INDEX IF NOT EXISTS ix_smt_next_run_at ON bot.scheduled_message_tasks(next_run_at) WHERE enabled = TRUE;

-- 兼容历史库：补 short_id 列并回填，确保唯一且非空
ALTER TABLE bot.scheduled_message_tasks ADD COLUMN IF NOT EXISTS short_id VARCHAR(8);
WITH sm_numbered AS (
    SELECT
        task_id,
        lower(lpad(to_hex((row_number() OVER (ORDER BY created_at, task_id))::bigint), 8, '0')) AS sid
    FROM bot.scheduled_message_tasks
    WHERE short_id IS NULL OR short_id = ''
)
UPDATE bot.scheduled_message_tasks AS t
SET short_id = sm_numbered.sid
FROM sm_numbered
WHERE t.task_id = sm_numbered.task_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_smt_short_id ON bot.scheduled_message_tasks(short_id);
ALTER TABLE bot.scheduled_message_tasks ALTER COLUMN short_id SET NOT NULL;

-- ============================================
-- 24. 定时消息日志表 (scheduled_message_logs)
-- 记录定时消息的发送历史（可选）
-- ============================================
CREATE TABLE IF NOT EXISTS bot.scheduled_message_logs (
    id BIGSERIAL PRIMARY KEY,                                       -- 自增主键
    task_id UUID NOT NULL,                                          -- 任务 ID（外键关联 scheduled_message_tasks.task_id）
    chat_id BIGINT NOT NULL,                                        -- 群组 ID
    message_id INTEGER,                                             -- 消息 ID（Telegram message_id）
    sent_at TIMESTAMPTZ NOT NULL,                                   -- 发送时间（带时区）
    success BOOLEAN NOT NULL,                                       -- 是否成功
    error_message TEXT,                                             -- 错误消息
    CONSTRAINT fk_sml_task_id FOREIGN KEY (task_id)
        REFERENCES bot.scheduled_message_tasks(task_id) ON DELETE CASCADE  -- 外键约束：删除任务时级联删除日志
);

COMMENT ON TABLE bot.scheduled_message_logs IS '定时消息日志表，记录定时消息的发送历史';
COMMENT ON COLUMN bot.scheduled_message_logs.id IS '自增主键';
COMMENT ON COLUMN bot.scheduled_message_logs.task_id IS '任务 ID，外键关联 scheduled_message_tasks.task_id';
COMMENT ON COLUMN bot.scheduled_message_logs.chat_id IS '群组 ID';
COMMENT ON COLUMN bot.scheduled_message_logs.message_id IS '发送的消息的 Telegram message_id';
COMMENT ON COLUMN bot.scheduled_message_logs.sent_at IS '消息发送时间';
COMMENT ON COLUMN bot.scheduled_message_logs.success IS '是否发送成功（true=成功，false=失败）';
COMMENT ON COLUMN bot.scheduled_message_logs.error_message IS '失败时的错误消息';

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS ix_sml_task_id ON bot.scheduled_message_logs(task_id);
CREATE INDEX IF NOT EXISTS ix_sml_sent_at ON bot.scheduled_message_logs(sent_at);

-- ============================================
-- 25. 群内周边资料表 (nearby_profiles)
-- 成员在每个群内维护独立的位置与业务信息
-- ============================================
CREATE TABLE IF NOT EXISTS bot.nearby_profiles (
    id SERIAL PRIMARY KEY,                                         -- 自增主键
    chat_id BIGINT NOT NULL,                                       -- 群组 ID（外键关联 tg_chats.id）
    user_id BIGINT NOT NULL,                                       -- 用户 ID（外键关联 tg_users.id）
    latitude NUMERIC(9,6),                                         -- 纬度（WGS84）
    longitude NUMERIC(9,6),                                        -- 经度（WGS84）
    price_text VARCHAR(128),                                       -- 价格描述
    method_text VARCHAR(128),                                      -- 交付方式描述
    address_text TEXT,                                             -- 地址/备注
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,                      -- 是否在附近列表可见
    fuzzy_distance BOOLEAN NOT NULL DEFAULT TRUE,                  -- 是否模糊显示距离
    last_location_at TIMESTAMPTZ,                                  -- 最近一次更新定位时间
    created_at TIMESTAMPTZ NOT NULL,                               -- 创建时间
    updated_at TIMESTAMPTZ NOT NULL,                               -- 更新时间
    CONSTRAINT fk_nearby_profiles_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_nearby_profiles_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT uq_nearby_profile_chat_user UNIQUE (chat_id, user_id)
);

COMMENT ON TABLE bot.nearby_profiles IS '群内成员周边资料表，按 chat_id + user_id 隔离存储用户业务卡片';
COMMENT ON COLUMN bot.nearby_profiles.chat_id IS '群组 ID，确保多群数据隔离';
COMMENT ON COLUMN bot.nearby_profiles.user_id IS '用户 ID';
COMMENT ON COLUMN bot.nearby_profiles.latitude IS '纬度坐标（WGS84）';
COMMENT ON COLUMN bot.nearby_profiles.longitude IS '经度坐标（WGS84）';
COMMENT ON COLUMN bot.nearby_profiles.price_text IS '价格文本描述';
COMMENT ON COLUMN bot.nearby_profiles.method_text IS '交付方式文本描述';
COMMENT ON COLUMN bot.nearby_profiles.address_text IS '地址或备注';
COMMENT ON COLUMN bot.nearby_profiles.is_visible IS '是否在附近列表中可见';
COMMENT ON COLUMN bot.nearby_profiles.fuzzy_distance IS '详情页距离是否模糊显示';
COMMENT ON COLUMN bot.nearby_profiles.last_location_at IS '定位更新时间';

CREATE INDEX IF NOT EXISTS ix_nearby_profiles_chat_id ON bot.nearby_profiles(chat_id);
CREATE INDEX IF NOT EXISTS ix_nearby_profiles_user_id ON bot.nearby_profiles(user_id);
CREATE INDEX IF NOT EXISTS ix_nearby_profiles_visible ON bot.nearby_profiles(chat_id, is_visible);

-- ============================================
-- 26. 联盟功能相关表
-- ============================================
CREATE TABLE IF NOT EXISTS bot.group_alliances (
    alliance_id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    owner_chat_id BIGINT NOT NULL,
    invite_code_hash VARCHAR(128) NOT NULL,
    invite_code_expire_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_group_alliances_owner_chat_id FOREIGN KEY (owner_chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.group_alliance_members (
    id SERIAL PRIMARY KEY,
    alliance_id INTEGER NOT NULL,
    chat_id BIGINT NOT NULL,
    joined_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    CONSTRAINT fk_group_alliance_members_alliance_id FOREIGN KEY (alliance_id)
        REFERENCES bot.group_alliances(alliance_id) ON DELETE CASCADE,
    CONSTRAINT fk_group_alliance_members_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT uq_group_alliance_member_chat UNIQUE (chat_id)
);

CREATE TABLE IF NOT EXISTS bot.group_alliance_settings (
    chat_id BIGINT PRIMARY KEY,
    alliance_id INTEGER NOT NULL,
    joint_ban_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_group_alliance_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_group_alliance_settings_alliance_id FOREIGN KEY (alliance_id)
        REFERENCES bot.group_alliances(alliance_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.group_alliance_ban_pool (
    id SERIAL PRIMARY KEY,
    alliance_id INTEGER NOT NULL,
    target_user_id BIGINT NOT NULL,
    source_chat_id BIGINT NOT NULL,
    source_operator_user_id BIGINT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_group_alliance_ban_pool_alliance_id FOREIGN KEY (alliance_id)
        REFERENCES bot.group_alliances(alliance_id) ON DELETE CASCADE,
    CONSTRAINT fk_group_alliance_ban_pool_target_user_id FOREIGN KEY (target_user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT fk_group_alliance_ban_pool_source_chat_id FOREIGN KEY (source_chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_group_alliance_ban_pool_operator_user_id FOREIGN KEY (source_operator_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT uq_group_alliance_ban_pool UNIQUE (alliance_id, target_user_id)
);

CREATE TABLE IF NOT EXISTS bot.group_alliance_audit (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    alliance_id INTEGER,
    action VARCHAR(64) NOT NULL,
    operator_user_id BIGINT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result VARCHAR(16) NOT NULL DEFAULT 'success',
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_group_alliance_audit_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_group_alliance_audit_alliance_id FOREIGN KEY (alliance_id)
        REFERENCES bot.group_alliances(alliance_id) ON DELETE SET NULL,
    CONSTRAINT fk_group_alliance_audit_operator_user_id FOREIGN KEY (operator_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_group_alliance_members_alliance_id ON bot.group_alliance_members(alliance_id);
CREATE INDEX IF NOT EXISTS ix_group_alliance_settings_alliance_id ON bot.group_alliance_settings(alliance_id);
CREATE INDEX IF NOT EXISTS ix_group_alliance_ban_pool_alliance_id ON bot.group_alliance_ban_pool(alliance_id);
CREATE INDEX IF NOT EXISTS ix_group_alliance_audit_chat_id ON bot.group_alliance_audit(chat_id);
CREATE INDEX IF NOT EXISTS ix_group_alliance_audit_alliance_id ON bot.group_alliance_audit(alliance_id);

-- ============================================
-- 27. 车库转发表
-- ============================================
CREATE TABLE IF NOT EXISTS bot.garage_forward_settings (
    chat_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    sync_mode VARCHAR(16) NOT NULL DEFAULT 'all',
    keyword_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    button_template_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    button_template JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_garage_forward_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

-- 兼容历史库：补转发按钮模板相关字段
ALTER TABLE bot.garage_forward_settings ADD COLUMN IF NOT EXISTS button_template_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bot.garage_forward_settings ADD COLUMN IF NOT EXISTS button_template JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS bot.garage_forward_sources (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    source_channel_id BIGINT NOT NULL,
    source_name VARCHAR(255),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_garage_forward_sources_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.garage_forward_message_map (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    source_channel_id BIGINT NOT NULL,
    source_message_id BIGINT NOT NULL,
    target_message_id BIGINT NOT NULL,
    forwarded_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_garage_forward_message_map_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT uq_garage_forward_message_map UNIQUE (chat_id, source_channel_id, source_message_id)
);

CREATE TABLE IF NOT EXISTS bot.garage_forward_audit_logs (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    source_channel_id BIGINT NOT NULL,
    source_message_id BIGINT,
    action VARCHAR(32) NOT NULL,
    result VARCHAR(16) NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_garage_forward_audit_logs_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_garage_forward_sources_chat_id ON bot.garage_forward_sources(chat_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_garage_forward_source_chat_channel
    ON bot.garage_forward_sources(chat_id, source_channel_id);
CREATE INDEX IF NOT EXISTS ix_garage_forward_audit_logs_chat_id ON bot.garage_forward_audit_logs(chat_id);

-- ============================================
-- 16. 车库认证 / 老师搜索 / 车评系统
-- ============================================
CREATE TABLE IF NOT EXISTS bot.garage_certified_teachers (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    certified_by_user_id BIGINT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_garage_certified_teachers_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_garage_certified_teachers_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT fk_garage_certified_teachers_certified_by_user_id FOREIGN KEY (certified_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT uq_garage_certified_teacher_chat_user UNIQUE (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_garage_certified_teachers_chat_id ON bot.garage_certified_teachers(chat_id);

CREATE TABLE IF NOT EXISTS bot.garage_speech_whitelist (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_by_user_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_garage_speech_whitelist_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_garage_speech_whitelist_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT fk_garage_speech_whitelist_created_by_user_id FOREIGN KEY (created_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT uq_garage_speech_whitelist_chat_user UNIQUE (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_garage_speech_whitelist_chat_id ON bot.garage_speech_whitelist(chat_id);

CREATE TABLE IF NOT EXISTS bot.teacher_search_settings (
    chat_id BIGINT PRIMARY KEY,
    tag_search_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    only_open_course_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    nearby_search_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    attendance_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    attendance_mode VARCHAR(16) NOT NULL DEFAULT 'message',
    attendance_source_chat_id BIGINT,
    attendance_open_keyword VARCHAR(32) NOT NULL DEFAULT '开课',
    attendance_full_keyword VARCHAR(32) NOT NULL DEFAULT '满课',
    attendance_rest_keyword VARCHAR(32) NOT NULL DEFAULT '休息',
    force_location_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    delete_mode VARCHAR(16) NOT NULL DEFAULT 'none',
    footer_button_label VARCHAR(64),
    footer_button_url VARCHAR(512),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_teacher_search_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.teacher_profiles (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    region_text VARCHAR(128),
    price_text VARCHAR(128),
    open_course_today BOOLEAN NOT NULL DEFAULT FALSE,
    open_course_status VARCHAR(16),
    last_location_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_teacher_profiles_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_teacher_profiles_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT uq_teacher_profile_chat_user UNIQUE (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_teacher_profiles_chat_id ON bot.teacher_profiles(chat_id);
CREATE INDEX IF NOT EXISTS ix_teacher_profiles_open_course_today ON bot.teacher_profiles(open_course_today);

CREATE TABLE IF NOT EXISTS bot.teacher_daily_attendance (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    biz_date DATE NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    source_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_teacher_daily_attendance_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_teacher_daily_attendance_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT uq_teacher_attendance_chat_user_date UNIQUE (chat_id, user_id, biz_date)
);
CREATE INDEX IF NOT EXISTS ix_teacher_daily_attendance_chat_id ON bot.teacher_daily_attendance(chat_id);
CREATE INDEX IF NOT EXISTS ix_teacher_daily_attendance_biz_date ON bot.teacher_daily_attendance(biz_date);

CREATE TABLE IF NOT EXISTS bot.member_locations (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    latitude NUMERIC(9, 6) NOT NULL,
    longitude NUMERIC(9, 6) NOT NULL,
    updated_by_user_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_member_locations_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_member_locations_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT fk_member_locations_updated_by_user_id FOREIGN KEY (updated_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT uq_member_location_chat_user UNIQUE (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_member_locations_chat_id ON bot.member_locations(chat_id);

CREATE TABLE IF NOT EXISTS bot.car_review_settings (
    chat_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    review_mode VARCHAR(16) NOT NULL DEFAULT 'default',
    teacher_lookup_mode VARCHAR(16) NOT NULL DEFAULT 'off',
    auto_refresh_board_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    submit_command VARCHAR(64) NOT NULL DEFAULT '提交报告',
    rank_command VARCHAR(64) NOT NULL DEFAULT '出击排行',
    publish_to_main_group BOOLEAN NOT NULL DEFAULT TRUE,
    publish_to_comment_group BOOLEAN NOT NULL DEFAULT FALSE,
    publish_to_bound_channel BOOLEAN NOT NULL DEFAULT FALSE,
    approver_user_id BIGINT,
    reward_points INTEGER NOT NULL DEFAULT 100,
    template_text TEXT NOT NULL DEFAULT E'【时间】：{time}\n【老师】：{teacher}\n【留名】：{author}\n【评价】：{review}\n【人照】：{photo_score}\n【颜值】：{face_score}\n【身材】：{body_score}\n【服务】：{service_score}\n【态度】：{attitude_score}\n【环境】：{env_score}\n【综合】：{total_score}\n【过程】：{process}',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_car_review_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_car_review_settings_approver_user_id FOREIGN KEY (approver_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS bot.car_review_custom_fields (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    field_key VARCHAR(64) NOT NULL,
    field_label VARCHAR(64) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_car_review_custom_fields_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT uq_car_review_field_chat_key UNIQUE (chat_id, field_key)
);
CREATE INDEX IF NOT EXISTS ix_car_review_custom_fields_chat_id ON bot.car_review_custom_fields(chat_id);

CREATE TABLE IF NOT EXISTS bot.car_review_reports (
    report_id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    teacher_user_id BIGINT,
    author_user_id BIGINT,
    review_text TEXT,
    scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    process_text TEXT,
    media_file_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    report_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    approved_by_user_id BIGINT,
    approved_at TIMESTAMPTZ,
    published_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_car_review_reports_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_car_review_reports_teacher_user_id FOREIGN KEY (teacher_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT fk_car_review_reports_author_user_id FOREIGN KEY (author_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT fk_car_review_reports_approved_by_user_id FOREIGN KEY (approved_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_car_review_reports_chat_id ON bot.car_review_reports(chat_id);
CREATE INDEX IF NOT EXISTS ix_car_review_reports_status ON bot.car_review_reports(report_status);

CREATE TABLE IF NOT EXISTS bot.car_review_audit_logs (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    report_id INTEGER,
    operator_user_id BIGINT,
    action VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_car_review_audit_logs_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_car_review_audit_logs_report_id FOREIGN KEY (report_id)
        REFERENCES bot.car_review_reports(report_id) ON DELETE SET NULL,
    CONSTRAINT fk_car_review_audit_logs_operator_user_id FOREIGN KEY (operator_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_car_review_audit_logs_chat_id ON bot.car_review_audit_logs(chat_id);

CREATE TABLE IF NOT EXISTS bot.auction_settings (
    chat_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    pin_message_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    auto_extend_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    create_permission VARCHAR(16) NOT NULL DEFAULT 'admin',
    points_mode VARCHAR(32) NOT NULL DEFAULT 'none',
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_auction_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.auction_items (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    creator_user_id BIGINT,
    source_message_id BIGINT,
    title VARCHAR(255),
    start_price INTEGER NOT NULL DEFAULT 0,
    current_price INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    winner_user_id BIGINT,
    winner_bid_id INTEGER,
    last_announce_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_auction_items_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_auction_items_creator_user_id FOREIGN KEY (creator_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT fk_auction_items_winner_user_id FOREIGN KEY (winner_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_auction_items_chat_id ON bot.auction_items(chat_id);
CREATE INDEX IF NOT EXISTS ix_auction_items_status ON bot.auction_items(status);
CREATE INDEX IF NOT EXISTS ix_auction_items_end_at ON bot.auction_items(end_at);

CREATE TABLE IF NOT EXISTS bot.auction_bids (
    id SERIAL PRIMARY KEY,
    auction_id INTEGER NOT NULL,
    chat_id BIGINT NOT NULL,
    bid_user_id BIGINT NOT NULL,
    bid_amount INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_auction_bids_auction_id FOREIGN KEY (auction_id)
        REFERENCES bot.auction_items(id) ON DELETE CASCADE,
    CONSTRAINT fk_auction_bids_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_auction_bids_bid_user_id FOREIGN KEY (bid_user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_auction_bids_auction_id ON bot.auction_bids(auction_id);
CREATE INDEX IF NOT EXISTS ix_auction_bids_created_at ON bot.auction_bids(created_at);

CREATE TABLE IF NOT EXISTS bot.bottom_button_settings (
    chat_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    header_text TEXT NOT NULL DEFAULT '⌨️ 底部按钮已生成，点击下方按钮即可使用。',
    generated_message_id BIGINT,
    repeat_generate_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    repeat_interval_seconds INTEGER NOT NULL DEFAULT 3600,
    last_generated_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_bottom_button_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.bottom_button_layouts (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    row_no INTEGER NOT NULL,
    col_no INTEGER NOT NULL,
    button_text VARCHAR(32) NOT NULL DEFAULT '按钮',
    payload_text TEXT,
    action_mode VARCHAR(16) NOT NULL DEFAULT 'send',
    sort_key INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_bottom_button_layouts_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT uq_bottom_button_layout_chat_pos UNIQUE (chat_id, row_no, col_no)
);
CREATE INDEX IF NOT EXISTS ix_bottom_button_layouts_chat_id ON bot.bottom_button_layouts(chat_id);

CREATE TABLE IF NOT EXISTS bot.game_settings (
    chat_id BIGINT PRIMARY KEY,
    k3_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    blackjack_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    rake_ratio VARCHAR(16),
    rake_owner_user_id BIGINT,
    auto_schedule_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    auto_start_time VARCHAR(5),
    auto_stop_time VARCHAR(5),
    delete_game_message_mode VARCHAR(16) NOT NULL DEFAULT 'keep',
    k3_panel_message_id BIGINT,
    blackjack_panel_message_id BIGINT,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_game_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_game_settings_rake_owner_user_id FOREIGN KEY (rake_owner_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS bot.game_rounds (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    game_type VARCHAR(16) NOT NULL,
    creator_user_id BIGINT,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    settle_at TIMESTAMPTZ,
    announcement_message_id BIGINT,
    result_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_game_rounds_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_game_rounds_creator_user_id FOREIGN KEY (creator_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_game_rounds_chat_id ON bot.game_rounds(chat_id);
CREATE INDEX IF NOT EXISTS ix_game_rounds_game_type ON bot.game_rounds(game_type);
CREATE INDEX IF NOT EXISTS ix_game_rounds_status ON bot.game_rounds(status);
CREATE INDEX IF NOT EXISTS ix_game_rounds_settle_at ON bot.game_rounds(settle_at);

CREATE TABLE IF NOT EXISTS bot.game_participants (
    id SERIAL PRIMARY KEY,
    round_id INTEGER NOT NULL,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    bet_points INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    choice_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    payout_points INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_game_participants_round_id FOREIGN KEY (round_id)
        REFERENCES bot.game_rounds(id) ON DELETE CASCADE,
    CONSTRAINT fk_game_participants_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_game_participants_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT uq_game_participant_round_user UNIQUE (round_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_game_participants_round_id ON bot.game_participants(round_id);
CREATE INDEX IF NOT EXISTS ix_game_participants_chat_id ON bot.game_participants(chat_id);
CREATE INDEX IF NOT EXISTS ix_game_participants_user_id ON bot.game_participants(user_id);

CREATE TABLE IF NOT EXISTS bot.lottery_settings (
    chat_id BIGINT PRIMARY KEY,
    publish_pin_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    result_pin_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    delete_join_message_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_lottery_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.guess_settings (
    chat_id BIGINT PRIMARY KEY,
    rake_ratio VARCHAR(16),
    rake_owner_user_id BIGINT,
    delete_message_mode VARCHAR(16) NOT NULL DEFAULT 'keep',
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_guess_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_guess_settings_rake_owner_user_id FOREIGN KEY (rake_owner_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS bot.guess_events (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    creator_user_id BIGINT,
    title VARCHAR(128) NOT NULL DEFAULT '竞猜活动',
    cover_file_id VARCHAR(256),
    description TEXT,
    mode VARCHAR(16) NOT NULL DEFAULT 'no_banker',
    banker_user_id BIGINT,
    public_pool INTEGER NOT NULL DEFAULT 0,
    options_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    command_keyword VARCHAR(32) NOT NULL DEFAULT '竞猜',
    deadline_at TIMESTAMPTZ NOT NULL,
    allow_repeat_bet BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    winner_option VARCHAR(64),
    announcement_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_guess_events_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_guess_events_creator_user_id FOREIGN KEY (creator_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT fk_guess_events_banker_user_id FOREIGN KEY (banker_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_guess_events_chat_id ON bot.guess_events(chat_id);
CREATE INDEX IF NOT EXISTS ix_guess_events_status ON bot.guess_events(status);
CREATE INDEX IF NOT EXISTS ix_guess_events_deadline_at ON bot.guess_events(deadline_at);

CREATE TABLE IF NOT EXISTS bot.guess_bets (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    option_key VARCHAR(64) NOT NULL,
    bet_points INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_guess_bets_event_id FOREIGN KEY (event_id)
        REFERENCES bot.guess_events(id) ON DELETE CASCADE,
    CONSTRAINT fk_guess_bets_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_guess_bets_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_guess_bets_event_id ON bot.guess_bets(event_id);
CREATE INDEX IF NOT EXISTS ix_guess_bets_option_key ON bot.guess_bets(option_key);

CREATE TABLE IF NOT EXISTS bot.engagement_settings (
    chat_id BIGINT PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_engagement_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.engagement_egg (
    chat_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    answer VARCHAR(128),
    clues JSONB NOT NULL DEFAULT '[]'::jsonb,
    clue_rewards JSONB NOT NULL DEFAULT '[]'::jsonb,
    clue_times JSONB NOT NULL DEFAULT '[]'::jsonb,
    winner_user_id BIGINT,
    status VARCHAR(16) NOT NULL DEFAULT 'idle',
    published_clue_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_engagement_egg_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_engagement_egg_winner_user_id FOREIGN KEY (winner_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS bot.engagement_egg_events (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    title VARCHAR(128) NOT NULL DEFAULT '彩蛋活动',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    answer VARCHAR(128),
    clues JSONB NOT NULL DEFAULT '[]'::jsonb,
    clue_rewards JSONB NOT NULL DEFAULT '[]'::jsonb,
    clue_times JSONB NOT NULL DEFAULT '[]'::jsonb,
    winner_user_id BIGINT,
    status VARCHAR(16) NOT NULL DEFAULT 'idle',
    published_clue_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_engagement_egg_events_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_engagement_egg_events_winner_user_id FOREIGN KEY (winner_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_engagement_egg_events_chat_id ON bot.engagement_egg_events(chat_id);
CREATE INDEX IF NOT EXISTS ix_engagement_egg_events_status ON bot.engagement_egg_events(status);
CREATE INDEX IF NOT EXISTS ix_engagement_egg_events_created_at ON bot.engagement_egg_events(created_at);

CREATE TABLE IF NOT EXISTS bot.engagement_egg_history (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    event_id INTEGER,
    title VARCHAR(128),
    answer VARCHAR(128),
    winner_user_id BIGINT,
    reward_points INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'finished',
    published_clue_count INTEGER NOT NULL DEFAULT 0,
    snapshot_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_engagement_egg_history_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_engagement_egg_history_winner_user_id FOREIGN KEY (winner_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_engagement_egg_history_chat_id ON bot.engagement_egg_history(chat_id);
CREATE INDEX IF NOT EXISTS ix_engagement_egg_history_event_id ON bot.engagement_egg_history(event_id);
CREATE INDEX IF NOT EXISTS ix_engagement_egg_history_created_at ON bot.engagement_egg_history(created_at);

CREATE TABLE IF NOT EXISTS bot.engagement_chat_reward (
    chat_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    reward_type VARCHAR(32) NOT NULL DEFAULT 'daily_increment',
    daily_message_target INTEGER NOT NULL DEFAULT 200,
    reward_points_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
    after_7d_mode VARCHAR(16) NOT NULL DEFAULT 'continue',
    command_keyword VARCHAR(32) NOT NULL DEFAULT '我爱水群',
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_engagement_chat_reward_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.engagement_chat_stats (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    biz_date DATE NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    streak_days INTEGER NOT NULL DEFAULT 0,
    reward_claimed BOOLEAN NOT NULL DEFAULT FALSE,
    rewarded_points INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_engagement_chat_stats_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_engagement_chat_stats_user_id FOREIGN KEY (user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT uq_engagement_chat_stats_daily UNIQUE (chat_id, user_id, biz_date)
);
CREATE INDEX IF NOT EXISTS ix_engagement_chat_stats_chat_id ON bot.engagement_chat_stats(chat_id);
CREATE INDEX IF NOT EXISTS ix_engagement_chat_stats_biz_date ON bot.engagement_chat_stats(biz_date);

CREATE TABLE IF NOT EXISTS bot.account_inherit_settings (
    chat_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    token_expire_minutes INTEGER NOT NULL DEFAULT 60,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_account_inherit_settings_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bot.account_inherit_tokens (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    old_user_id BIGINT NOT NULL,
    token_hash VARCHAR(128) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    used_by_user_id BIGINT,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_account_inherit_tokens_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_account_inherit_tokens_old_user_id FOREIGN KEY (old_user_id)
        REFERENCES bot.tg_users(id) ON DELETE CASCADE,
    CONSTRAINT fk_account_inherit_tokens_used_by_user_id FOREIGN KEY (used_by_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT uq_account_inherit_token_hash UNIQUE (token_hash)
);
CREATE INDEX IF NOT EXISTS ix_account_inherit_tokens_chat_id ON bot.account_inherit_tokens(chat_id);

CREATE TABLE IF NOT EXISTS bot.account_inherit_audit (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    old_user_id BIGINT,
    new_user_id BIGINT,
    asset_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    result VARCHAR(16) NOT NULL DEFAULT 'success',
    reason VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_account_inherit_audit_chat_id FOREIGN KEY (chat_id)
        REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
    CONSTRAINT fk_account_inherit_audit_old_user_id FOREIGN KEY (old_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL,
    CONSTRAINT fk_account_inherit_audit_new_user_id FOREIGN KEY (new_user_id)
        REFERENCES bot.tg_users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_account_inherit_audit_chat_id ON bot.account_inherit_audit(chat_id);

-- ============================================
-- 数据库初始化完成
-- ============================================
