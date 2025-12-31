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

### 新人验证系统
- **多种验证模式**：按钮验证、数学题验证、验证码验证
- **权限限制**：验证期间限制发言权限
- **超时处理**：自动处理超时的验证请求

### 内容审核系统
- **关键词过滤**：敏感词检测和自动处理
- **链接屏蔽**：自动检测并处理链接
- **灵活处理方式**：删除、警告、禁言可选
- **审核记录**：完整的违规行为记录

### 反刷屏保护
- **频率检测**：检测短时间内大量消息
- **自动处理**：自动禁言、删除或封禁
- **可配置阈值**：触发条件和惩罚措施可配置

### 自动化功能
- **自动删除**：自动删除进群、退群、置顶等系统消息
- **自动回复**：关键词触发自动回复
- **定时消息**：定时发送群公告或消息

### 邀请链接管理
- **用户生成链接**：普通用户可生成邀请链接
- **邀请统计**：统计邀请人数和排行
- **链接控制**：过期时间和加入人数限制

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
| Python | 3.11+ | 主要编程语言 |
| python-telegram-bot | 21.6 | Telegram Bot API |
| SQLAlchemy | 2.0.36 | ORM 框架 |
| psycopg | 3.2.3 | PostgreSQL 驱动 |
| Pydantic | 2.10.3 | 数据验证 |
| structlog | 24.4.0 | 结构化日志 |
| tenacity | 9.0.0 | 重试机制 |

### 架构设计
- **三层架构**：Handler（处理层）→ Service（业务层）→ Model（数据层）
- **模块化设计**：按功能模块划分，易于扩展
- **异步支持**：全面支持异步操作
- **国际化**：支持中英文多语言

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
cp config/env.example .env
```

2. **编辑 `.env` 文件**

```env
# Telegram Bot Token（必填）
BOT_TOKEN=your_bot_token_here

# 数据库连接（必填）
DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname

# 日志级别（可选，默认 INFO）
LOG_LEVEL=INFO

# 运行环境（可选，默认 dev）
APP_ENV=dev

# Webhook URL（可选，不填则使用长轮询）
WEBHOOK_URL=
```

3. **启动服务**

```bash
docker compose up --build
```

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
```

5. **运行应用**

```bash
python -m bot
```

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

## 目录结构

```
TgGroupRobot/
├── bot/                      # 主应用目录
│   ├── __init__.py
│   ├── __main__.py           # 主入口文件
│   ├── config.py             # 配置管理
│   ├── logging_config.py     # 日志配置
│   ├── db/                   # 数据库相关
│   │   ├── session.py        # 会话管理
│   │   └── base.py           # 基础配置
│   ├── models/               # 数据模型
│   │   ├── core.py           # 核心数据模型
│   │   └── enums.py          # 枚举定义
│   ├── handlers/             # 消息处理器
│   │   ├── admin.py          # 管理员命令
│   │   ├── ads.py            # 广告处理
│   │   ├── anti_flood.py     # 反刷屏
│   │   ├── auto_delete.py    # 自动删除
│   │   ├── auto_reply.py     # 自动回复
│   │   ├── banned_word.py    # 敏感词过滤
│   │   ├── invite_link.py    # 邀请链接
│   │   ├── lottery.py        # 抽奖功能
│   │   ├── moderation.py     # 内容审核
│   │   ├── points.py         # 积分系统
│   │   ├── scheduled.py      # 定时消息
│   │   ├── sign.py           # 签到功能
│   │   ├── solitaire.py      # 接龙功能
│   │   └── start.py          # 启动命令
│   ├── services/             # 业务逻辑服务层
│   │   ├── points_service.py
│   │   ├── invite_service.py
│   │   └── ...
│   ├── keyboards/            # 内联键盘定义
│   │   ├── admin.py
│   │   ├── points.py
│   │   └── ...
│   └── i18n/                 # 国际化
│       └── strings.py        # 语言字符串
├── config/                   # 配置文件目录
├── docs/                     # 文档目录
├── sql/                      # SQL 文件
│   └── init.sql              # 数据库初始化脚本
├── tests/                    # 测试文件
├── .env                      # 环境变量
├── requirements.txt          # 依赖包
├── Dockerfile               # Docker 镜像
├── docker-compose.yml       # Docker 编排
└── README.md                # 项目说明
```

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
4. **启动机器人**：`docker compose up -d`
5. **添加到群组**：将机器人添加到目标群组并授予管理员权限

## 许可证

本项目遵循 MIT 许可证。
