# TgGroupRobot

TgGroupRobot 是一个面向 Telegram 群运营场景的群组管理机器人。项目以一个 Bot 实例服务多个群组为核心模型，支持群组独立配置、私聊按钮化管理、群内实时风控、积分运营、活动互动、自动化消息、邀请增长、车库/老师搜索/车评运营和内置 Web 后台。

管理员的主要使用方式是 `/start` 进入私聊管理面板，再通过按钮完成群组切换、功能配置和日常运营；群内则负责承接普通用户签到、积分、邀请、活动参与、新人验证、内容审核等实时流程。当前版本默认开放群组功能，订阅和续费底座保留，但不作为运行时功能限制。

## 项目定位

- **多群管理**：同一个机器人可管理多个 Telegram 群，每个群的设置、成员、积分、活动、风控规则互相隔离。
- **按钮化配置**：管理员在私聊中通过内联按钮完成绝大多数配置，不依赖额外命令记忆。
- **实时群治理**：群消息进入统一处理链，先经过自动删除、反刷屏、反垃圾、违禁词等规则，再进入积分、邀请、活动等业务处理。
- **运营增长工具**：提供积分中心、邀请链接、签到、发言奖励、积分等级、积分商城、活动、竞猜、拍卖、促活工具等运营能力。
- **自动化投放**：支持定时消息、轮播广告、快捷发布和底部按钮入口。
- **车库业务闭环**：围绕认证老师、开课状态、附近搜索、车评提交审核和排行榜形成群内运营闭环。
- **平台化后台**：内置 FastAPI Web 后台，用于管理员登录、续费卡密批量生成/复制/导出、公告栏配置等平台管理。

## 功能总览

### 群组基础

- 多群独立配置与私聊切群管理
- Telegram 管理员权限校验
- 群组健康检查，覆盖机器人权限、验证、强制订阅、反垃圾、防刷屏、关群、定时消息等状态
- 群组命令启停与别名配置
- 跨群导入设置和按模块克隆配置
- 自动删除进群、退群、置顶、头像、群名、匿名消息等系统提示

### 新人与风控

- 新人验证：按钮、数学题、验证码、管理员审核
- 验证超时处理：禁言或踢出，并由后台任务持续扫描
- 入群刷号保护和加入频率检测
- 强制订阅：频道/群组绑定、提示文案、封面、按钮、处理动作
- 新成员限制：按入群时长限制媒体、链接、纯文本
- 反垃圾、防刷屏、违禁词、黑名单和处罚动作降级

### 积分与会员运营

- 签到积分、连续签到、冷却控制
- 发言积分、字数门槛、每日限制
- 邀请积分和可靠邀请归因
- 积分查询、排行榜、转让、管理员加减分、日志导出、清空
- 自定义积分类型、积分等级和积分商城
- 积分任务页，统一展示签到、发言、邀请任务

### 消息自动化

- 自动回复：关键词规则、封面、按钮
- 定时消息：文本、媒体、按钮、开始/结束时间、重复间隔、详情和删除
- 轮播广告：单次推送、定时开始、间隔轮播、图片配置和看板
- 快捷发布：私聊一键投放文本、媒体和按钮
- 底部按钮：群内输入框下方快捷入口

### 邀请与增长

- 管理员邀请链接创建、列表、详情、统计、预览、清零、导出
- 普通用户自助生成邀请链接
- 基于 `ChatMemberUpdate` 中可靠 invite metadata 的邀请归因
- 邀请排行榜和成员数据统计

### 活动与互动

- 抽奖：创建、参与条件、开奖
- 接龙：创建、加入、状态跟踪
- 游戏：游戏设置和牌局列表
- 竞猜：活动设置、选项、庄家、结算
- 拍卖：拍卖设置、拍品和竞价
- 促活工具：彩蛋活动、奖励配置、统计

### 车库、老师搜索与车评

- **车库认证**：管理员可启停认证能力、设置认证图标、手动添加/删除认证老师，并支持联盟共享认证池。
- **老师发言限制**：可按图片或图文模式限制老师发言频率，支持时间间隔、限制条数和白名单。
- **老师资料**：维护老师地区/地址、价格、服务标签、定位、今日开课状态等资料。
- **老师搜索**：群内支持 `老师搜索 关键词`、`附近`、`附近 关键词`、`开课老师` 等入口。
- **开课打卡**：支持“发言就是打卡”、固定话术打卡，以及搜索群读取其他打卡群的外部打卡模式。
- **附近搜索**：群友先在群内或私聊更新位置，再按距离查询附近老师，可配置只显示今日开课老师。
- **强制录入位置**：开启后，认证老师未录入位置前会被提示到私聊更新定位。
- **车评系统**：支持回复老师消息提交报告、默认/简易模式、自定义评分项、审核人通知、报告管理、审核日志、发布模板和积分奖励。
- **车评查询与排行**：群内支持排行指令、本周/月排行，以及按老师用户名查询已审核/已发布车评。

### 群组扩展

- 欢迎消息：模式、封面、按钮、删除策略
- 改名监控：模板文本和提示删除策略
- 联盟与联合封禁：联盟状态、成员管理、封禁池
- 夜间管控：时段限制、白名单、提示文案、全员禁言、口令开关群

### 内置 Web 后台

- 管理员账号登录与会话
- 续费卡密批量生成、查询、复制、导出
- 平台公告栏配置
- 静态后台页面由 Bot 进程内的 FastAPI 服务提供

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.12+ | 主运行时 |
| python-telegram-bot | 21.6 | Telegram Bot API 与 update 分发 |
| SQLAlchemy | 2.0.36 | ORM 与异步数据库访问 |
| psycopg | 3.2.3 | PostgreSQL 驱动 |
| Pydantic / pydantic-settings | 2.x | 配置和数据校验 |
| structlog | 24.4.0 | 结构化日志 |
| FastAPI / Uvicorn | 0.115 / 0.32 | 内置 Web 后台 |
| openpyxl | 3.1.5 | 卡密导出 |
| pytest / pytest-asyncio | 8.x / 0.25 | 回归测试 |

## 架构总览

项目按运行时装配、平台能力、功能域和共享能力分层：

```text
TgGroupRobot/
├── main.py                         # 统一入口，支持 --reload 开发热重启
├── backend/
│   ├── app/                        # 应用装配、启动链路、router registry、update pipeline
│   ├── platform/                   # 配置、数据库、Telegram 适配、状态、调度器
│   ├── features/                   # 业务功能域：admin、points、moderation、activity 等
│   └── shared/                     # 跨域服务、基础 handler、callback parser、通用 UI
├── docs/                           # 架构、部署、功能基线文档
├── docs-site/                      # 用户手册静态站点
├── scripts/                        # 开发、数据库、部署辅助脚本
├── deploy/                         # 服务器部署和巡检脚本
├── tests/                          # 回归测试
└── config/env.example              # 环境变量模板
```

### 运行时链路

```text
main.py
  -> backend.app.runtime.main()
    -> build_application()
      -> 读取 Settings
      -> 创建 Database(engine + session_factory)
      -> 构建 python-telegram-bot Application
      -> 注入 app.bot_data["settings"] / app.bot_data["db"]
      -> 注册命令、功能 Router、通用消息处理器和错误处理器
    -> schema migrations + schema gate
    -> app.initialize() / app.start()
    -> start_polling(allowed_updates=ALL_TYPES)
    -> Scheduler.start()
    -> 可选启动 FastAPI Web 后台
```

### 路由与消息分发

- `backend/app/router_registry.py` 集中注册功能 Router：后台菜单、抽奖、接龙、邀请、广告、定时消息、自动回复、违禁词、积分、续费、附近、群运维、验证、底部按钮、游戏等。
- `backend/app/bootstrap.py` 注册通用入口，并通过 handler group 固定执行顺序：
  - `group=-99`：原始 update 日志探针
  - `group=-5`：系统消息自动删除
  - `group=-4`：防刷屏
  - `group=-3`：反垃圾
  - `group=-2`：命令别名、统一消息分发、私聊配置输入
- `backend/app/update_pipeline.py` 根据聊天类型分流：私聊优先读取用户配置状态，群聊统一进入 `GroupMessageHandler`。
- 回调按钮使用前缀和正则归属到不同 Router，避免所有功能挤在一个巨型 handler 中。

### 业务模块组织

每个功能域尽量按 vertical slice 收口：Router/Handler 负责 Telegram 事件，Service 负责业务逻辑，UI/Formatter 负责消息和键盘展示，数据模型放在 `backend/platform/db/schema/models/`。

常见功能域：

- `backend/features/admin/`：私聊管理面板、导航、权限、导入导出、欢迎、积分配置、车库/车评管理
- `backend/features/points/`：用户积分、签到、等级、商城、积分消息动作
- `backend/features/moderation/`：反垃圾、反刷屏、违禁词、自动回复、处罚动作
- `backend/features/group_ops/`：群基础流程、自动删除、命令别名、底部按钮、群消息 hooks
- `backend/features/verification/`：新人验证、验证回调、管理员放行、超时提示
- `backend/features/activity/`：抽奖、接龙、游戏、竞猜等互动活动
- `backend/features/automation/`：广告、定时消息和轮播任务
- `backend/features/invite/`：邀请链接、邀请归因和统计
- `backend/features/garage/`：车库认证、老师搜索、车评和联盟相关 service
- `backend/features/web_admin/`：内置 FastAPI 后台、静态页面、卡密和公告服务

### 调度器

`backend/platform/scheduler/core/core.py` 提供统一异步调度器，每个任务继承 `ScheduledTask`，拥有独立循环、运行状态、连续失败计数和自动暂停保护。运行时注册的任务包括：

- 抽奖、拍卖、接龙、游戏、竞猜开奖/结算类任务
- 轮播广告、定时消息、底部按钮、促活任务
- 验证超时、清理、关群、改名监控、老师搜索等后台任务

启动期通过 `SCHEDULER_RUN_IMMEDIATELY` 和 `SCHEDULER_INITIAL_STAGGER_SECONDS` 控制首轮任务是否立即运行以及错峰间隔，避免 Bot 刚开始 polling 时被后台任务抢占。

### 数据模型

数据库使用 PostgreSQL，核心隔离维度是 `chat_id`。主要模型拆分在：

- `chat.py`：Telegram 用户、群、群配置、成员、会话状态、附近资料
- `points.py`：积分账户、流水、签到、每日统计、自定义积分、等级、商城
- `moderation.py`：违规记录、警告、验证挑战、自动回复、违禁词
- `automation.py`：广告、轮播规则、定时消息、邀请链接、邀请追踪
- `activity.py` / `expansion_games.py` / `expansion_auction.py`：抽奖、接龙、游戏、竞猜、拍卖
- `alliance.py` / `garage_features.py`：联盟、联合封禁、车库认证、老师搜索、车评
- `subscription.py`：订阅套餐、群订阅、续费卡密、续费审计
- `admin_web.py`：Web 后台账号、会话、审计和应用配置

启动时会先执行兼容性 schema migrations，再通过 schema gate 校验当前数据库结构，避免运行时代码和数据库漂移。

## 快速开始

### Docker 部署

1. 准备环境变量：

```bash
cp config/env.example .env
```

2. 修改 `.env`：

```env
BOT_TOKEN=your_bot_token_here
DATABASE_URL=postgresql+psycopg://app_user:replace_with_shared_app_password@postgres:5432/tggrouprobot
INFRA_NETWORK_NAME=infra_default
ADMIN_WEB_ENABLED=true
ADMIN_WEB_HOST=0.0.0.0
ADMIN_WEB_PORT=8088
ADMIN_BOOTSTRAP_USERNAME=admin
ADMIN_BOOTSTRAP_PASSWORD=change-me-please
```

3. 启动服务：

```bash
docker compose -f docker-compose.server.yml up --build
```

`docker-compose.server.yml` 会启动 `tggrouprobot-bot`，并把内置 Web 后台端口发布到宿主机本地回环，再由宿主机 Nginx 代理到公网入口。

### 本地开发

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/env.example .env
.venv/bin/python main.py
```

开发热重启：

```bash
.venv/bin/python main.py --reload
```

热重启会监听 `backend/`、`config/`、`main.py`、`.env`、`env` 和 `requirements.txt`，文件变化后优雅重启机器人进程。

## 常用入口

### 用户入口

| 指令 | 说明 | 场景 |
|------|------|------|
| `/start` | 启动机器人，进入私聊引导或群内引导 | 私聊/群组 |
| `/sign` | 签到领取积分 | 群组 |
| `/points` | 查询个人积分 | 私聊/群组 |
| `/积分排行` | 查看积分排行榜 | 群组 |
| `/link` | 生成个人邀请链接 | 群组 |

### 管理员入口

| 入口 | 说明 |
|------|------|
| `/start` + 私聊按钮 | 推荐管理入口，用于选择群组和进入功能面板 |
| `/admin` | 兼容入口，进入管理员面板 |
| 内置 Web 后台 `/admin/` | 管理员账号、续费卡密和公告配置 |

管理员操作会结合 Telegram 群权限和项目权限服务校验，私聊配置状态由 `conversation_states` 与当前管理群组共同决定。

## 文档索引

- [后端架构](docs/architecture/04_backend_architecture.md)
- [数据库设计](docs/architecture/02_database_design.md)
- [功能真值表](docs/setup/06_feature_truth_table.md)
- [命令与菜单](docs/setup/03_commands_and_menus.md)
- [生产运行说明](docs/deployment/PRODUCTION_RUNTIME.md)
- [GitHub Actions SSH 部署](docs/deployment/GITHUB_ACTIONS_SSH_DEPLOY.md)
- [用户手册站点](docs-site/README.md)

## 开发约定

- 新增功能优先按 `backend/features/<domain>/` vertical slice 组织，不把业务继续堆到公共入口。
- Handler 只做事件解析、权限检查和响应组装，核心业务逻辑放到 service。
- 私聊按钮流程需要考虑 `target_chat_id` 和当前管理群组，避免从一个群返回到另一个群。
- 群可见消息只展示用户需要理解的内容，后台配置项和管理细节保留在私聊或 Web 后台。
- 数据库变更必须同步 ORM、启动迁移、schema gate 和回归测试。

## 测试

运行全部测试：

```bash
.venv/bin/python -m pytest
```

运行单个测试文件：

```bash
.venv/bin/python -m pytest tests/test_admin_main_menu.py
```

文档站点检查：

```bash
cd docs-site
npm run check
npm run build
```

## 部署与巡检

生产发布脚本位于 `deploy/`，核心流程包括数据库准备、镜像发布、schema 应用、服务启动和 Web 入口检查。线上运行信息以 `docs/deployment/PRODUCTION_RUNTIME.md` 为准。

常用脚本：

```bash
deploy/release.sh
deploy/check-web.sh
deploy/rollback.sh
```

## License

Proprietary. All rights reserved.
