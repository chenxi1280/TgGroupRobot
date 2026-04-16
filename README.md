# TgGroupRobot

商业级 Telegram 群组管理机器人，支持多群独立配置、自动化管理、积分系统等丰富功能。

## 项目简介

TgGroupRobot 是一个功能完整的 **To C** Telegram 群组管理机器人，支持一个机器人实例管理多个群组，每个群组拥有独立的配置和数据隔离。通过 Telegram 指令和内联键盘菜单即可完成所有配置，无需额外管理后台。

## 核心特性

### 多群组管理
- **多群独立配置**：同一个机器人可添加到多个群组，每个群组配置完全隔离
- **管理员权限验证**：基于 Telegram API 的权限检查系统
- **群组切换管理**：支持在私聊中切换管理不同群组

### 积分系统
- **签到积分**：每日签到获得积分，支持连续签到奖励
- **发言积分**：发送消息获得积分（可配置）
- **邀请积分**：邀请新成员获得积分
- **积分查询**：查看个人积分余额和交易记录
- **积分排行**：群内积分排名展示
- **积分中心**：支持展示规则、发言排行、个人发言量、转让积分、管理员加减分、日志导出和清空积分

### 新人验证系统
- **多种验证模式**：按钮验证、数学题验证、验证码验证
- **权限限制**：验证期间限制发言权限
- **超时处理**：自动处理超时的验证请求
- **新成员限制**：支持按入群时长限制媒体/链接/纯文本并提示

### 内容审核系统
- **关键词过滤**：敏感词检测和自动处理
- **链接屏蔽**：自动检测并处理链接
- **灵活处理方式**：删除、禁言、封禁可选
- **审核记录**：完整的违规行为记录
- **惩罚策略入口**：一键同步反垃圾/防刷屏/关键词/验证超时策略

### 反刷屏保护
- **频率检测**：检测短时间内大量消息
- **自动处理**：自动禁言、删除或封禁
- **可配置阈值**：触发条件和惩罚措施可配置

### 自动化功能
- **自动删除**：自动删除进群、退群、置顶等系统消息
- **自动回复**：关键词触发自动回复
- **定时消息**：定时发送群公告或消息
- **轮播广告**：支持单次推送、定时开始、间隔轮播和图片广告配置
- **快捷发布**：私聊一键投放文本/媒体/按钮

### 邀请链接管理
- **用户生成链接**：普通用户可生成邀请链接
- **邀请统计**：统计邀请人数和排行
- **链接控制**：过期时间和加入人数限制
- **邀请归因**：基于可靠成员变更元数据进行邀请奖励归因，无法确认来源时不会误发奖励

### 群组运维
- **健康检查**：汇总验证、强制订阅、反垃圾、防刷屏、定时消息和机器人权限状态
- **强制订阅**：支持频道绑定、提示文案、按钮和封面配置
- **关群设置**：支持话术开关、定时开关和通知删除策略
- **夜间模式**：支持时段限制、管理员豁免、白名单与提示文案
- **群组命令配置**：支持常用指令启停与别名设置
- **导入设置 / 克隆**：支持跨群复制配置（按模块覆盖）
- **车评系统**：支持审核、发布目标配置、自定义评分项和报告管理
- **群组统计**：成员/邀请/积分/违规摘要一览
- **开放策略**：当前暂时关闭付费/续费逻辑，所有群组功能默认可用

### 频道管理
- **频道同步**：支持来源、模式、关键词过滤和审核记录
- **自动按钮**：同步时附加按钮模板并支持更新

### 抽奖系统
- **创建抽奖**：管理员创建抽奖活动
- **参与抽奖**：用户点击按钮参与
- **自动开奖**：定时或手动开奖

### 接龙功能
- **创建接龙**：创建商品或服务接龙
- **参与接龙**：用户参与接龙
- **状态管理**：接龙状态跟踪

## 技术架构

### 技术栈
| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.12+ | 主要编程语言 |
| python-telegram-bot | 21.6 | Telegram Bot API |
| SQLAlchemy | 2.0.36 | ORM 框架 |
| psycopg | 3.2.3 | PostgreSQL 驱动 |
| Pydantic | 2.10.3 | 数据验证 |
| structlog | 24.4.0 | 结构化日志 |
| tenacity | 9.0.0 | 重试机制 |

### 架构设计
- **四层结构**：`backend/app`（应用装配）→ `backend/platform`（平台能力）→ `backend/features`（功能域）→ `backend/shared`（跨域通用能力）
- **Vertical Slice**：业务按 feature 组织，路由、回调、消息、服务、展示层跟随功能域收口
- **注册表驱动运行时**：启动装配、router registry、message pipeline、session state 统一收口，避免跨模块硬编码分发
- **异步支持**：全面支持异步操作
- **国际化**：支持中英文多语言

### 目录概览
```text
backend/
├── app/        # 启动、装配、router registry、update pipeline
├── platform/   # config、db、scheduler、telegram adapter、state
├── features/   # admin、moderation、activity、automation 等功能域
└── shared/     # callback parser、公共 formatter、通用 service/helper
```

### 数据库设计
- **PostgreSQL** 作为主数据库
- **Bot Schema** 隔离
- **JSONB 字段** 存储动态配置
- **完善的外键约束和索引**
- **TIMESTAMPTZ** 支持时区

## 数据库表结构

### 核心表
- `tg_users` - Telegram 用户表
- `tg_chats` - 群组表
- `chat_settings` - 群组配置表（核心配置隔离表）
- `chat_members` - 群组成员表

### 积分系统
- `points_accounts` - 积分账户表
- `points_transactions` - 积分交易记录

### 审核与安全
- `verification_records` - 验证记录表
- `moderation_logs` - 审核日志表
- `banned_words` - 敏感词表

### 活动管理
- `invite_links` - 邀请链接表
- `lottery_records` - 抽奖记录表
- `solitaire_records` - 接龙记录表
- `scheduled_messages` - 定时消息表

### 商业化
- `ads` - 广告表
- `subscriptions` - 订阅表

## 快速开始

### Docker 部署（推荐）

1. **准备环境变量**

```bash
cp .env.docker.example .env
```

2. **编辑 `.env` 文件**

```env
# Telegram Bot Token（必填）
BOT_TOKEN=your_bot_token_here

# 数据库连接（必填，连接独立 infra）
DATABASE_URL=postgresql+psycopg://app_user:replace_with_shared_app_password@postgres:5432/tggrouprobot
DATABASE_CONNECT_TIMEOUT_SECONDS=10

# 外部 Docker 网络
INFRA_NETWORK_NAME=infra_default

# 日志级别（可选，默认 INFO）
LOG_LEVEL=INFO

# 运行环境（可选，默认 dev）
APP_ENV=dev

# Webhook URL（可选，不填则使用长轮询）
WEBHOOK_URL=
```

3. **启动服务**

```bash
docker compose -f docker-compose.server.yml up --build
```

线上 GitHub Actions 发版、服务器目录和数据库初始化流程，见：

- `docs/deployment/GITHUB_ACTIONS_SSH_DEPLOY.md`
- `docs/deployment/PRODUCTION_RUNTIME.md`
- `docs/setup/06_feature_truth_table.md`

### 本地开发

1. **创建虚拟环境**

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

2. **安装依赖**

```bash
pip install -r requirements.txt
```

3. **配置环境变量**

```bash
cp .env.example .env
# 编辑 .env 文件填入必要配置
```

4. **初始化数据库**

```bash
psql -h host -U user -d dbname -f sql/init.sql
python -m backend.platform.db.init_db
```

5. **运行应用**

```bash
python main.py
```

开发时如需热加载，使用：

```bash
python main.py --reload
```

如果当前 shell 没有激活虚拟环境，也可以直接使用项目里的 Python：

```bash
.venv/bin/python main.py --reload
```

它会监听 `backend/`、`config/`、`main.py`、`.env` / `env` 和 `requirements.txt`，文件变化后自动优雅重启机器人进程；停止开发时按 `Ctrl+C` 即可。

## 指令参考

### 用户指令

| 指令 | 描述 | 使用场景 |
|------|------|----------|
| `/start` | 启动机器人，显示帮助 | 私聊/群组 |
| `/sign` | 签到领积分 | 群组 |
| `/points` | 查询个人积分 | 私聊/群组 |
| `/积分排行` | 查看积分排行榜 | 群组 |
| `/link` | 生成邀请链接 | 群组 |

### 管理员指令

| 指令 | 描述 | 使用场景 |
|------|------|----------|
| `/admin` | 管理员面板 | 群组 |
| `/ad [标题\|内容]` | 发布广告 | 群组 |
| `/lottery` | 创建抽奖 | 群组 |
| `/solitaire` | 创建接龙 | 群组 |

> 管理员指令需要用户在群组中具有管理员权限
>
> 管理员主要配置入口同时支持私聊内联面板，包括主积分、邀请链接、轮播广告、定时消息、强制订阅和群组健康检查。

## 目录结构

```
TgGroupRobot/
├── main.py                   # 根入口
├── backend/
│   ├── bot/                  # Telegram Bot 运行时与业务域
│   │   ├── app.py
│   │   ├── bootstrap.py
│   │   ├── admin/
│   │   ├── activity/
│   │   ├── automation/
│   │   ├── garage/
│   │   ├── group_ops/
│   │   ├── invite/
│   │   ├── moderation/
│   │   ├── nearby/
│   │   ├── shared/
│   │   ├── state/
│   │   ├── subscription/
│   │   ├── ui/
│   │   └── verification/
│   ├── config/core/          # 配置与日志
│   ├── database/
│   │   ├── init_db.py        # 数据库初始化入口
│   │   ├── runtime/          # session / schema gate / startup migrations
│   │   └── schema/models/    # ORM 模型
│   ├── scheduler/            # 调度器与任务
│   └── utils/                # 通用工具
├── scripts/                  # 迁移/运维/开发脚本
├── docs/                     # 文档目录
├── sql/                      # SQL 文件
│   ├── init.sql              # 基础初始化脚本
│   └── migrations/           # 增量 SQL 迁移
├── tests/                    # 测试文件
├── .env                      # 环境变量
├── requirements.txt          # 依赖包
├── Dockerfile               # Docker 镜像
├── docker-compose.yml       # Docker 编排
└── README.md                # 项目说明
```

## 项目逻辑详解

本章节详细说明项目的整体架构、各模块功能、以及核心业务流程的实现逻辑。

### 1. 整体架构与工作原理

#### 1.1 三层架构设计

项目采用经典的三层架构模式，实现关注点分离：

```
┌─────────────────────────────────────────────────────────┐
│                    Handler 层（处理层）                    │
│  接收 Telegram 事件，处理用户交互，调用服务层             │
│  位置：backend/bot/<domain>/*.py                         │
└────────────────────┬────────────────────────────────────┘
                     │ 调用
┌────────────────────▼────────────────────────────────────┐
│                   Service 层（业务层）                    │
│  实现业务逻辑，数据处理，操作数据库模型                   │
│  位置：backend/bot/<domain>/services/*.py               │
└────────────────────┬────────────────────────────────────┘
                     │ 操作
┌────────────────────▼────────────────────────────────────┐
│                    Model 层（数据层）                     │
│  数据库模型定义，数据持久化，ORM 映射                     │
│  位置：backend/database/schema/models/*.py              │
└─────────────────────────────────────────────────────────┘
```

**层级职责说明：**

| 层级 | 职责 | 示例 |
|------|------|------|
| **Handler 层** | 接收 Telegram 事件，解析参数，返回响应 | 接收 `/sign` 指令，调用签到服务 |
| **Service 层** | 实现业务逻辑，数据计算，数据库操作 | 计算连续签到天数，修改积分 |
| **Model 层** | 定义数据结构，数据库映射 | `PointsAccount` 积分账户表 |

#### 1.2 应用启动与路由注册

**入口文件：** `main.py` / `backend/bot/app.py`

应用启动流程如下：

```mermaid
graph TD
    A[main函数] --> B[build_application]
    B --> C[get_settings加载配置]
    C --> D[create_database初始化数据库]
    D --> E[Application.builder创建应用]
    E --> F{配置代理?}
    F -->|是| G[添加proxy支持]
    F -->|否| H[跳过]
    G --> I[注入bot_data]
    H --> I
    I --> J[注册CommandHandler指令]
    J --> K[注册CallbackQueryHandler回调]
    K --> L[注册ConversationHandler对话]
    L --> M[注册MessageHandler消息]
    M --> N[设置group优先级]
    N --> O[返回Application]
    O --> P[run_bot_with_scheduler]
    P --> Q[启动定时任务]
    Q --> R[启动轮询]
    R --> S[开始接收事件]
```

**关键代码位置：** `backend/bot/bootstrap.py`、`backend/bot/app.py`

```python
# 指令注册（159-167行）
app.add_handler(CommandHandler("start", start_command))
app.add_handler(CommandHandler("admin", admin_command))
app.add_handler(CommandHandler("sign", sign_command))

# 回调处理器注册（169-223行）
app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))
app.add_handler(CallbackQueryHandler(join_lottery_callback, pattern=r"^join_lottery_"))

# 消息处理器注册（303-342行）
# group=0: 最高优先级（自动删除、反刷屏、违禁词检测）
# group=1-3: 中等优先级（功能流程、审核）
# group=4-5: 低优先级（积分、别名）
```

#### 1.3 Telegram Bot 事件流转机制

```mermaid
sequenceDiagram
    participant U as 用户
    participant TG as Telegram服务器
    participant B as Bot应用
    participant H as Handler路由
    participant S as Service层
    participant DB as PostgreSQL

    U->>TG: 发送消息/指令/点击按钮
    TG->>B: 推送Update对象
    B->>H: 匹配Handler

    alt 指令事件
        H->>H: CommandHandler匹配
        H->>S: 调用服务方法
    else 回调事件
        H->>H: CallbackQueryHandler匹配
        H->>S: 调用服务方法
    else 消息事件
        H->>H: MessageHandler匹配
        H->>S: 调用服务方法
    end

    S->>DB: 执行数据库操作
    DB-->>S: 返回结果
    S-->>H: 返回业务结果
    H->>B: 构建响应
    B->>TG: 发送API请求
    TG-->>U: 显示响应
```

### 2. 文件功能详解

#### 2.1 入口文件（main.py / backend/bot/app.py）

**核心功能：**
- **build_application()**（137-348行）：构建应用实例并注册所有路由
- **main()**（384-406行）：启动入口，初始化并运行机器人
- **后台任务调度器**：
  - `send_scheduled_messages_job()`（351-381行）：定时消息发送
  - `anti_flood_cleanup_scheduler()`（408-415行）：反刷屏清理
  - `ads_scheduler()`（418-456行）：广告推送

**关键代码片段：**

```python
# 指令注册示例
app.add_handler(CommandHandler("admin", admin_command))

# 回调注册示例（使用正则模式匹配）
app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))

# 消息注册示例（支持群组和私聊，设置优先级）
app.add_handler(
    MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handler),
    group=0  # 优先级0（最高）
)
```

#### 2.2 处理器层（bot/handlers/*.py）

处理器层负责接收和响应 Telegram 事件。每个处理器对应一个功能模块。

| 文件 | 功能 | 关键函数 |
|------|------|----------|
| **start.py** | 启动和取消指令 | `start_command`, `cancel_command` |
| **admin.py** | 管理员面板 | `admin_command`, `admin_callback` |
| **points.py** | 积分系统 | `sign_command`, `points_command` |
| **lottery.py** | 抽奖系统 | `lottery_create_start`, `join_lottery_callback` |
| **invite_link.py** | 邀请链接管理 | `link_command`, `invite_link_menu_callback` |
| **solitaire.py** | 接龙功能 | `solitaire_create_start_callback`, `join_solitaire_callback` |
| **verification.py** | 新人验证 | `new_members_handler`, `verify_callback` |
| **anti_flood.py** | 反刷屏 | `anti_flood_message_handler` |
| **banned_word.py** | 违禁词过滤 | `banned_word_check_handler` |
| **moderation.py** | 内容审核 | `moderation_message_handler` |
| **auto_delete.py** | 自动删除 | `auto_delete_handler` |
| **auto_reply.py** | 自动回复 | `auto_reply_message_handler` |
| **scheduled.py** | 定时消息 | `scheduled_message_handler` |
| **ads.py** | 广告系统 | `ad_command` |
| **chat_group.py** | 群组切换 | `chat_group_list_callback`, `chat_group_select_callback` |

**处理器工作模式示例：**

```python
# bot/handlers/admin.py:48-109
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理员命令处理"""
    # 1. 获取基本信息
    chat = update.effective_chat
    user = update.effective_user

    # 2. 判断聊天类型
    if chat.type != "private":  # 群聊
        # 3. 验证权限
        is_admin = await is_user_admin(context, chat.id, user.id)
        if not is_admin:
            await update.effective_message.reply_text("此命令仅限管理员使用")
            return

        # 4. 设置当前管理群组
        await set_user_current_chat(db, user.id, chat.id)

        # 5. 发送引导按钮
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎛️ 前往设置", url=f"https://t.me/{context.bot.username}")
        ]])
        await update.effective_message.reply_text("欢迎使用...", reply_markup=keyboard)
    else:  # 私聊
        # 6. 获取管理群组列表
        chats = await get_user_managed_chats(db, user.id, context.bot)

        # 7. 显示管理面板
        await _show_private_admin_menu(update, context, current_chat_id)
```

#### 2.3 服务层（bot/services/*.py）

服务层实现核心业务逻辑，处理器层调用服务层方法完成具体功能。

| 文件 | 功能 | 关键方法 |
|------|------|----------|
| **chat_service.py** | 群组基础服务 | `ensure_chat`, `get_chat_settings` |
| **user_service.py** | 用户管理服务 | `ensure_user` |
| **points_service.py** | 积分业务逻辑 | `sign_in`, `change_points`, `get_leaderboard` |
| **lottery_service.py** | 抽奖业务逻辑 | `create_lottery`, `join_lottery`, `draw_lottery` |
| **invite_link_service.py** | 邀请链接业务 | `create_invite_link`, `track_invite` |
| **solitaire_service.py** | 接龙业务逻辑 | `create_solitaire`, `join_solitaire` |
| **chat_group_service.py** | 群组切换服务 | `get_user_managed_chats`, `set_user_current_chat` |
| **telegram_perm.py** | 权限验证服务 | `is_user_admin` |
| **state_service.py** | 状态管理服务 | `get_user_state`, `set_user_state` |

**服务层工作模式示例：**

```python
# bot/services/points_service.py:110-196
async def sign_in(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    settings: ChatSettings
) -> dict:
    """签到业务逻辑"""
    # 1. 检查今日是否已签到
    today = dt.date.today()
    existing = await _get_today_sign_in(session, chat_id, user_id, today)
    if existing:
        return {"success": False, "reason": "already_signed", "data": existing}

    # 2. 获取上次签到时间计算连续天数
    last_sign = await _get_last_sign_in(session, chat_id, user_id)
    consecutive_days = _calculate_consecutive_days(last_sign, today)

    # 3. 计算积分奖励
    points = _calculate_sign_points(consecutive_days, settings)

    # 4. 修改积分
    await change_points(session, chat_id, user_id, points, "sign_in")

    # 5. 创建签到记录
    sign_record = SignInLog(
        chat_id=chat_id,
        user_id=user_id,
        sign_date=today,
        consecutive_days=consecutive_days,
        points_earned=points
    )
    session.add(sign_record)

    return {"success": True, "consecutive_days": consecutive_days, "points": points}
```

#### 2.4 键盘层（bot/keyboards/*.py）

键盘层负责生成 Telegram 内联键盘（InlineKeyboardMarkup）。

| 文件 | 功能 | 关键函数 |
|------|------|----------|
| **admin.py** | 管理员菜单 | `admin_main_menu`, `verification_mode_menu` |
| **points.py** | 积分配置键盘 | `points_config_keyboard` |
| **lottery.py** | 抽奖相关键盘 | `lottery_menu_keyboard`, `get_join_keyboard` |
| **invite_link.py** | 邀请链接键盘 | `invite_link_menu_keyboard` |
| **solitaire.py** | 接龙相关键盘 | `solitaire_menu_keyboard` |

**键盘生成示例：**

```python
# bot/keyboards/admin.py:6-42
def admin_main_menu(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """管理员主菜单

    Args:
        chat_id: 群组ID，用于私聊管理场景。如果提供，callback_data 会包含 chat_id
    """
    if chat_id is not None:
        # 私聊管理场景：callback_data 包含 chat_id
        buttons = [
            [
                InlineKeyboardButton("🎁抽奖", callback_data=f"adm:menu:lottery:{chat_id}"),
                InlineKeyboardButton("🔗邀请链接", callback_data=f"adm:menu:invite:{chat_id}"),
            ],
            [
                InlineKeyboardButton("💰积分", callback_data=f"adm:menu:points:{chat_id}"),
                InlineKeyboardButton("🤖验证", callback_data=f"adm:menu:verification:{chat_id}"),
            ],
            [
                InlineKeyboardButton("🔄切换群组", callback_data="adm:switch_group"),
                InlineKeyboardButton("🔙返回", callback_data=f"adm:back_to_main"),
            ],
        ]
        return InlineKeyboardMarkup(buttons)

    # 群聊场景：callback_data 不包含 chat_id
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁抽奖", callback_data="adm:menu:lottery")],
        # ...
    ])
```

#### 2.5 数据模型层（bot/models/core.py）

数据模型定义所有数据库表结构。

**核心数据表：**

| 表名 | 模型类 | 说明 |
|------|--------|------|
| `tg_users` | `TgUser` | Telegram 用户基本信息 |
| `tg_chats` | `TgChat` | 群组基本信息 |
| `chat_members` | `ChatMember` | 群组成员关系 |
| `chat_settings` | `ChatSettings` | 群组配置（核心） |
| `points_accounts` | `PointsAccount` | 积分账户 |
| `points_transactions` | `PointsTransaction` | 积分交易记录 |
| `sign_in_logs` | `SignInLog` | 签到日志 |
| `lottery_records` | `Lottery` | 抽奖记录 |
| `lottery_participants` | `LotteryParticipant` | 抽奖参与记录 |
| `invite_links` | `InviteLink` | 邀请链接 |

### 3. 指令处理机制

#### 3.1 CommandHandler 工作原理

**注册位置：** `backend/bot/bootstrap.py`

```python
# CommandHandler(指令名称, 处理函数)
app.add_handler(CommandHandler("start", start_command))
app.add_handler(CommandHandler("admin", admin_command))
app.add_handler(CommandHandler("sign", sign_command))
```

当用户发送 `/admin` 指令时：

```mermaid
sequenceDiagram
    participant U as 用户
    participant T as Telegram服务器
    participant B as Bot应用
    participant CH as CommandHandler
    participant H as admin_command
    participant S as Service层
    participant DB as 数据库

    U->>T: 发送 /admin
    T->>B: 接收Update对象
    B->>CH: 路由匹配
    CH->>CH: 检查指令是否为"admin"
    CH->>H: 调用处理函数
    H->>H: 判断聊天类型
    alt 群聊场景
        H->>S: is_user_admin检查权限
        S->>DB: getChatMember API
        DB-->>S: 返回管理员状态
        S-->>H: 权限确认
        H->>S: set_user_current_chat
        H->>B: 生成引导键盘
        B-->>U: 发送跳转按钮
    else 私聊场景
        H->>S: get_user_managed_chats
        S->>DB: 查询群组列表
        DB-->>S: 返回群组
        S-->>H: 群组列表
        H->>B: 生成管理面板
        B-->>U: 发送管理菜单
    end
```

#### 3.2 指令分发流程

**完整调用链路（以 `/admin` 为例）：**

```
1. 用户发送 /admin
   ↓
2. Telegram 推送 Update 到 Bot
   ↓
3. CommandHandler 匹配到 admin_command
   ↓
4. bot/handlers/admin.py:48 admin_command()
   ↓
5. 判断聊天类型 (chat.type)
   ├─ 群聊 → 验证权限 → 发送引导按钮
   └─ 私聊 → 获取群组 → 显示管理面板
   ↓
6. bot/keyboards/admin.py:6 admin_main_menu()
   ↓
7. 生成 InlineKeyboardMarkup
   ↓
8. 返回给用户显示
```

### 4. 键盘交互系统

#### 4.1 回调数据结构设计

**Callback Data 格式规范：**

```
格式：{前缀}:{动作}:{参数}

示例解析：
- adm:menu:lottery:123    → 管理员菜单 -> 抽奖功能 -> 群组123
- join_lottery_456        → 参与抽奖 -> 抽奖ID 456
- inv:user:create:-123456 → 邀请链接 -> 用户创建 -> 群组-123456
```

**前缀定义：**

| 前缀 | 功能模块 | 示例 |
|------|----------|------|
| `adm:` | 管理员功能 | `adm:menu:lottery:123` |
| `lot:` | 抽奖功能 | `lot:create`, `draw_lottery_456` |
| `sol:` | 接龙功能 | `sol:create`, `join_solitaire:789` |
| `inv:` | 邀请链接 | `inv:create`, `inv:detail:456` |
| `pts:` | 积分配置 | `pts:edit:sign_points` |
| `vfy:` | 验证功能 | `vfy:button`, `vfy:math` |
| `scheduled:` | 定时消息 | `scheduled:create` |
| `auto_reply:` | 自动回复 | `auto_reply:create` |
| `ads:` | 广告系统 | `ads:create` |

#### 4.2 CallbackQueryHandler 处理流程

**注册位置：** `backend/bot/bootstrap.py`

```python
# 使用正则表达式匹配回调数据
app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))
app.add_handler(CallbackQueryHandler(join_lottery_callback, pattern=r"^join_lottery_"))
```

**完整交互流程：**

```mermaid
sequenceDiagram
    participant U as 用户
    participant B as Bot
    participant CB as CallbackQueryHandler
    participant H as Handler函数
    participant K as Keyboard生成
    participant S as Service层
    participant DB as 数据库

    U->>B: 点击"抽奖"按钮
    B->>CB: 接收callback_query
    CB->>CB: pattern匹配 ^adm:
    CB->>H: 调用admin_callback
    H->>H: 解析callback_data
    note right of H: data="adm:menu:lottery:123"<br/>parts=["adm","menu","lottery","123"]
    H->>H: 提取参数chat_id=123
    H->>S: 验证管理员权限
    S->>DB: 检查权限
    DB-->>S: 返回结果
    S-->>H: 权限确认
    H->>S: get_lottery_stats
    S->>DB: 查询统计数据
    DB-->>S: 返回统计
    S-->>H: 返回数据
    H->>K: lottery_menu_keyboard(chat_id)
    K->>K: 生成按钮列表
    K-->>H: InlineKeyboardMarkup
    H->>B: edit_message_text
    B-->>U: 更新消息显示
```

**回调处理示例代码：**

```python
# bot/handlers/admin.py:435-493
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理回调处理"""
    q = update.callback_query
    await q.answer()  # 必须调用，避免按钮loading

    data = q.data or ""
    parts = data.split(":")

    # 解析: adm:menu:lottery:123
    if len(parts) >= 4 and parts[1] == "menu":
        action = parts[2]      # "lottery"
        chat_id = int(parts[3]) # 123

        # 检查权限
        if not await is_user_admin(context, chat_id, user.id):
            await _safe_edit_message(q, "你没有该群组的管理权限")
            return

        # 根据action分发到不同处理函数
        if action == "lottery":
            await _handle_private_lottery(update, context, chat_id)
        elif action == "points":
            await _handle_private_points(update, context, chat_id)
        # ...
```

### 5. 核心业务流程详解

#### 5.1 积分系统完整流程

**相关文件：**
- Handler: `bot/handlers/points.py:19-128`
- Service: `bot/services/points_service.py:110-196`
- Model: `bot/models/core.py:166-203`

**签到流程图：**

```mermaid
graph TD
    A[用户发送 /sign] --> B[sign_command]
    B --> C{检查聊天类型}
    C -->|非群聊| D[提示仅在群聊可用]
    C -->|群聊| E[ensure_chat创建群组]
    E --> F[ensure_user创建用户]
    F --> G[get_chat_settings获取配置]
    G --> H{签到是否开启?}
    H -->|否| I[提示功能未开启]
    H -->|是| J[sign_in业务逻辑]
    J --> K{今日是否已签到?}
    K -->|是| L[返回签到信息]
    K -->|否| M[获取上次签到时间]
    M --> N[计算连续签到天数]
    N --> O[计算积分奖励]
    O --> P[change_points修改积分]
    P --> Q[创建SignInLog记录]
    Q --> R[创建PointsTransaction]
    R --> S[提交数据库事务]
    S --> T[返回成功消息]
```

**代码调用链路：**

```
1. 用户发送: /sign
   ↓
2. bot/handlers/points.py:19 sign_command()
   ↓
3. bot/services/chat_service.py:ensure_chat() - 确保群组存在
   ↓
4. bot/services/user_service.py:ensure_user() - 确保用户存在
   ↓
5. bot/services/chat_service.py:get_chat_settings() - 获取配置
   ↓
6. bot/services/points_service.py:110 sign_in() - 签到业务逻辑
   ├─ 检查今日是否已签到
   ├─ _calculate_consecutive_days() - 计算连续天数
   ├─ _calculate_sign_points() - 计算积分
   ├─ change_points() - 修改积分
   └─ 创建签到记录
   ↓
7. 返回结果给用户
```

#### 5.2 抽奖系统完整流程

**相关文件：**
- Handler: `bot/handlers/lottery.py`
- Service: `bot/services/lottery_service.py`
- Keyboard: `bot/keyboards/lottery.py`

**创建抽奖流程：**

```mermaid
stateDiagram-v2
    [*] --> 点击创建按钮
    点击创建按钮 --> lottery_create_start
    lottery_create_start --> 验证管理员权限
    验证管理员权限 --> 设置用户状态
    设置用户状态 --> 提示输入配置
    提示输入配置 --> 用户发送配置JSON
    用户发送配置JSON --> lottery_message_handler
    lottery_message_handler --> 解析配置
    解析配置 --> 配置有效?
    配置有效 --> create_lottery
    配置无效 --> 提示错误
    提示错误 --> 用户发送配置JSON
    create_lottery --> 保存到数据库
    保存到数据库 --> 发送抽奖消息到群组
    发送抽奖消息到群组 --> 清除用户状态
    清除用户状态 --> [*]
```

**参与抽奖流程：**

```mermaid
graph TD
    A[用户点击参与按钮] --> B[join_lottery_callback]
    B --> C[解析lottery_id]
    C --> D[can_join_lottery检查条件]
    D --> E{检查结果}
    E -->|抽奖不存在| F[提示抽奖不存在]
    E -->|已结束| G[提示抽奖已结束]
    E -->|已参与| H[提示已参与]
    E -->|积分不足| I[提示积分不足]
    E -->|通过| J[join_lottery参与]
    J --> K{需要扣积分?}
    K -->|是| L[change_points扣积分]
    K -->|否| M[完成参与]
    L --> M
    M --> N[更新按钮文本]
    N --> O[返回成功消息]
```

#### 5.3 邀请链接系统流程

**相关文件：**
- Handler: `bot/handlers/invite_link.py`
- Service: `bot/services/invite_link_service.py`

**邀请链接创建与追踪流程：**

```mermaid
graph TD
    A[管理员点击创建链接] --> B[invite_link_create_start_callback]
    B --> C[进入对话流程]
    C --> D[输入名称]
    D --> E[输入人数限制]
    E --> F[输入过期时间]
    F --> G[create_invite_link]
    G --> H[调用Telegram API创建链接]
    H --> I[保存到数据库]
    I --> J[返回链接详情]

    K[ChatMemberUpdate到达] --> L[invite_link_join_hint_handler]
    L --> M[缓存invite_link元数据]
    M --> N[new_members_handler]
    N --> O{是否拿到可靠invite_link?}
    O -->|是| P[track_invite记录邀请]
    P --> Q[增加邀请人计数]
    Q --> R[给予邀请积分奖励]
    O -->|否| S[仅记录加入事件，不猜测邀请人]
```

#### 5.4 新人验证系统流程

**相关文件：**
- Handler: `bot/handlers/verification.py`
- Service: `bot/services/verification_service.py`

**验证流程（数学题模式）：**

```mermaid
graph TD
    A[新成员加入群组] --> B[new_members_handler]
    B --> C[获取验证配置]
    C --> D{验证是否开启?}
    D -->|否| E[跳过验证]
    D -->|是| F{验证模式}
    F -->|button| G[发送按钮验证]
    F -->|math| H[生成数学题]
    F -->|captcha| I[生成验证码]
    H --> J[发送验证消息]
    J --> K[限制用户权限]
    K --> L[设置超时定时器]

    M[用户发送答案] --> N[verify_message_handler]
    N --> O[验证答案]
    O --> P{答案正确?}
    P -->|是| Q[恢复权限]
    P -->|否| R[提示错误]
    R --> S{超过重试次数?}
    S -->|是| T[移除用户]
    S -->|否| M
```

#### 5.5 接龙系统流程

**相关文件：**
- Handler: `bot/handlers/solitaire.py`
- Service: `bot/services/solitaire_service.py`

**接龙创建与参与流程：**

```mermaid
graph TD
    A[管理员点击创建接龙] --> B[solitaire_create_start_callback]
    B --> C[设置对话状态]
    C --> D[提示输入配置JSON]
    D --> E[用户发送配置]
    E --> F[solitaire_create_config_message]
    F --> G[解析配置]
    G --> H{配置有效?}
    H -->|否| I[提示错误]
    H -->|是| J[create_solitaire]
    J --> K[保存到数据库]
    K --> L[发送接龙消息到群组]

    M[用户点击参与] --> N[join_solitaire_callback]
    N --> O[创建SolitaireEntry]
    O --> P[更新接龙状态]
    P --> Q[更新消息显示]

    R[用户回复接龙消息] --> S[solitaire_join_message_handler]
    S --> T[解析回复内容]
    T --> U[添加参与记录]
```

### 6. 多群组管理机制

#### 6.1 群组隔离原理

**核心设计：** 每个群组拥有完全独立的配置和数据。

**数据隔离实现：**

1. **配置隔离** - `chat_settings` 表
   ```python
   # 每个群组独立的配置
   chat_id: 123  → settings A (积分开启)
   chat_id: 456  → settings B (积分关闭)
   ```

2. **积分隔离** - `points_accounts` 表
   ```python
   # 复合主键：(chat_id, user_id)
   (123, 1001) → 用户1001在群123的积分: 500
   (456, 1001) → 用户1001在群456的积分: 200
   ```

3. **业务数据隔离** - 所有业务表都包含 `chat_id`
   ```python
   Lottery(chat_id=123, ...)    # 群123的抽奖
   InviteLink(chat_id=456, ...) # 群456的邀请链接
   ```

#### 6.2 私聊管理模式

管理员可以在私聊中管理多个群组，无需在每个群组中单独操作。

**私聊管理流程：**

```mermaid
graph TD
    A[用户私聊 /admin] --> B[get_user_managed_chats]
    B --> C{有管理群组?}
    C -->|否| D[提示添加bot到群组]
    C -->|是| E[get_user_current_chat]
    E --> F{当前群组?}
    F -->|无| G[设置第一个为当前]
    F -->|有| H[使用当前群组]
    G --> I[_show_private_admin_menu]
    H --> I
    I --> J[admin_main_menu带chat_id]
    J --> K[生成按钮]
    K --> L[显示管理面板]

    M[点击功能按钮] --> N[admin_callback]
    N --> O[解析chat_id]
    O --> P[验证权限]
    P --> Q[执行业务逻辑]
    Q --> R[返回结果]
```

**关键代码位置：**

```python
# bot/handlers/admin.py:111-142
async def admin_command(...) -> None:
    if chat.type == "private":  # 私聊
        # 获取用户管理的群组
        chats = await get_user_managed_chats(db, user.id, context.bot)

        # 获取当前管理的群组
        current_chat_id = await get_user_current_chat(db, user.id)

        # 默认选择第一个
        if current_chat_id is None and chats:
            current_chat_id = chats[0][0]
            await set_user_current_chat(db, user.id, current_chat_id)

        # 显示管理面板
        await _show_private_admin_menu(update, context, current_chat_id)
```

#### 6.3 群组切换机制

**相关文件：**
- Handler: `bot/handlers/chat_group.py`
- Service: `bot/services/chat_group_service.py`

**切换流程：**

```mermaid
sequenceDiagram
    participant U as 用户
    participant H as Handler
    participant S as chat_group_service
    participant DB as 数据库

    U->>H: 点击"切换群组"
    H->>H: 解析 callback_data="group:list"
    H->>S: get_user_managed_chats
    S->>DB: 查询群组列表
    DB-->>S: 返回群组
    S-->>H: 返回群组列表
    H->>U: 显示群组列表

    U->>H: 选择群组
    H->>H: 解析 callback_data="group:select:456"
    H->>S: set_user_current_chat(456)
    S->>DB: 更新当前群组
    DB-->>S: 确认
    S-->>H: 完成
    H->>U: 返回管理面板
```

### 7. 数据流转机制

#### 7.1 数据库会话管理

**会话创建：** `bot/db/session.py`

```python
# 会话工厂创建
def create_database(database_url: str, connect_timeout_seconds: int = 10) -> Database:
    engine = create_async_engine(
        database_url,
        connect_args={"connect_timeout": connect_timeout_seconds},
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return Database(session_factory=session_factory)
```

**会话使用模式：**

```python
# 在所有Handler中使用统一模式
async with db.session_factory() as session:
    # 业务逻辑
    result = await session.execute(select(TgUser).where(...))
    user = result.scalar_one_or_none()

    # 修改数据
    user.name = "new_name"

    # 提交事务
    await session.commit()

# 会话自动关闭
```

#### 7.2 ORM 操作流程

```mermaid
graph LR
    A[Handler] -->|创建会话| B[session_factory]
    B --> C[AsyncSession]
    C --> D[Service层调用]
    D --> E[SQLAlchemy查询]
    E --> F[生成SQL]
    F --> G[数据库执行]
    G --> H[返回结果]
    H --> I[session.commit]
    I --> J[会话自动关闭]
```

#### 7.3 配置存储结构

**ChatSettings 表：** `bot/models/core.py:62-143`

```python
class ChatSettings(Base):
    """群组配置表 - 每个群组一条记录"""
    __tablename__ = "chat_settings"

    # 主键
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # 积分配置
    sign_enabled: Mapped[bool] = mapped_column(default=True)
    sign_points: Mapped[int] = mapped_column(default=10)
    message_points: Mapped[int] = mapped_column(default=0)

    # 验证配置
    verification_enabled: Mapped[bool] = mapped_column(default=False)
    verification_mode: Mapped[str] = mapped_column(default="button")

    # 审核配置
    moderation_enabled: Mapped[bool] = mapped_column(default=False)
    moderation_block_links: Mapped[bool] = mapped_column(default=False)

    # ... 更多配置
```

**配置获取与更新：**

```python
# bot/services/chat_service.py
async def get_chat_settings(
    session: AsyncSession,
    chat_id: int
) -> ChatSettings:
    """获取群组配置，如果不存在则创建默认配置"""
    settings = await session.get(ChatSettings, chat_id)
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()
    return settings
```

---

## 开发指南

### 代码规范
- 方法必须添加注释说明功能
- 重要代码段需要注释
- 使用类型注解提高代码可读性

### 测试
```bash
# 运行所有测试
pytest

# 运行单个测试文件
pytest tests/test_specific.py

# 运行特定测试
pytest tests/test_specific.py::test_function
```

### 数据库变更
数据库变更通过维护 `sql/init.sql` 文件管理：
- 修改表结构后，更新 `init.sql` 中对应的 DDL 语句
- 手动执行更新后的 SQL 脚本到数据库

### 日志
日志采用 structlog 进行结构化记录，支持以下级别：
- DEBUG：详细调试信息
- INFO：常规信息
- WARNING：警告信息
- ERROR：错误信息
- CRITICAL：严重错误

## 部署说明

1. **获取 Bot Token**：通过 [@BotFather](https://t.me/botfather) 创建机器人并获取 Token
2. **配置数据库**：准备 PostgreSQL 数据库实例，执行 `sql/init.sql` 初始化表结构
3. **设置环境变量**：正确配置 `.env` 文件
4. **启动机器人**：`docker compose -f docker-compose.server.yml up -d`
5. **添加到群组**：将机器人添加到目标群组并授予管理员权限

说明：
- 容器默认启动命令为 `python main.py`
- 发布脚本会先确保 `tggrouprobot` 数据库存在，再执行项目内的 `sql/init.sql`

## 许可证

本项目遵循 MIT 许可证。
