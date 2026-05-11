# 后端架构与功能实现说明

本文档按当前代码结构说明 `TgGroupRobot` 的真实后端架构。当前主线已经不是旧的 `backend/bot` 目录结构，而是以 `backend/app` 装配运行时、`backend/platform` 提供平台能力、`backend/features` 承载业务域、`backend/shared` 沉淀跨域能力。

## 1. 系统定位

`TgGroupRobot` 是 Telegram 群运营机器人，核心目标是让一个 Bot 实例管理多个群组，并为每个群提供独立的配置、数据和运营流程。

主要能力包括：

- 群组绑定、多群切换、管理员权限校验和群级配置隔离
- 新人验证、强制订阅、入群刷号保护、新成员限制
- 自动删除、反刷屏、反垃圾、违禁词、处罚动作降级
- 签到、发言积分、邀请积分、自定义积分、等级、商城和积分任务
- 邀请链接、邀请归因、邀请排行和成员增长统计
- 自动回复、定时消息、轮播广告、快捷发布和底部按钮
- 抽奖、接龙、游戏、竞猜、拍卖、促活工具
- 欢迎消息、改名监控、联盟/联合封禁、车库认证、老师搜索、车评
- 内置 Web 后台，支持管理员登录、续费卡密、公告配置等平台管理

## 2. 顶层目录

```text
main.py
backend/
  app/
    bootstrap.py            # 构建 PTB Application，注入依赖，注册 handler
    runtime.py              # 主运行时：polling、scheduler、Web 后台、优雅退出
    router_registry.py      # 功能 Router 注册表
    update_pipeline.py      # 私聊/群聊统一消息分发
    router_base.py          # Router 基类
  platform/
    config/                 # Settings、日志配置
    db/                     # Database、schema gate、启动迁移、ORM models
    scheduler/              # 统一异步调度器和后台任务
    state/                  # conversation state
    telegram/               # Telegram 适配、群消息 pipeline、错误处理
  features/
    admin/                  # 管理员私聊面板与配置入口
    points/                 # 积分、签到、等级、商城
    moderation/             # 风控、违禁词、自动回复
    group_ops/              # 群基础能力、自动删除、底部按钮、群 hooks
    verification/           # 新人验证和超时放行
    activity/               # 抽奖、接龙、游戏、竞猜
    automation/             # 广告、定时消息
    invite/                 # 邀请链接与邀请归因
    garage/                 # 车库认证、老师搜索、车评
    subscription/           # 续费和订阅底座
    nearby/                 # 附近资料与搜索
    web_admin/              # 内置 FastAPI 后台
  shared/
    handlers/               # handler 基类和权限/状态辅助
    services/               # 跨功能 service
    ui/                     # 通用 UI builders、formatters、responses
    callback_parser.py      # callback data 解析
    button_layout_editor.py # 通用按钮布局编辑
```

## 3. 启动链路

根入口是 `main.py`：

```text
main.py
  -> backend.app.runtime.main()
    -> _check_single_instance()
    -> run_bot_with_scheduler()
      -> build_application()
      -> _validate_schema_or_exit()
      -> app.initialize()
      -> app.start()
      -> app.updater.start_polling()
      -> Scheduler.start()
      -> create_admin_web_app() + uvicorn.Server.serve()
      -> 等待 SIGINT/SIGTERM
      -> 依次停止 Web 后台、调度器、polling、Application
```

`build_application()` 完成几件关键事情：

- 从 `.env` 或 `env` 加载 `Settings`
- 配置结构化日志
- 创建 SQLAlchemy `Database(engine + session_factory)`
- 构建 `python-telegram-bot` `Application`
- 显式关闭 HTTPX `trust_env`，避免 IDE 或系统代理污染 Telegram 请求
- 将 `settings` 和 `db` 注入 `app.bot_data`
- 注册命令、功能 Router、通用消息处理器和错误处理器

启动前会先执行启动迁移和 schema gate：

```text
run_startup_schema_migrations()
validate_database_schema()
```

这样可以在 Bot 开始接收 Telegram update 之前发现数据库结构漂移。

## 4. Handler 注册与执行顺序

### 4.1 功能 Router

`backend/app/router_registry.py` 是功能入口清单，当前注册的 Router 包括：

- `AdminRouter`
- `LotteryRouter`
- `SolitaireRouter`
- `InviteRouter`
- `AdsRouter`
- `ScheduledMessageRouter`
- `AutoReplyRouter`
- `BannedWordRouter`
- `PointsRouter`
- `RenewalRouter`
- `NearbyRouter`
- `GroupRouter`
- `VerificationRouter`
- `BottomButtonRouter`
- `GameRuntimeRouter`

新增功能时优先新增独立 Router，并在注册表挂载，而不是直接把回调继续堆进 `bootstrap.py`。

### 4.2 通用处理器

`backend/app/bootstrap.py` 还注册了一组跨功能处理器，它们依赖 PTB handler group 保证顺序：

| Group | 处理器 | 目的 |
|------:|--------|------|
| -99 | `TypeHandler(Update, _raw_update_probe)` | 记录原始 update，便于定位监听和分发问题 |
| -5 | `auto_delete_handler` | 优先清理系统消息，避免被后续风控截断 |
| -4 | `anti_flood_message_handler` | 防刷屏入口 |
| -3 | `anti_spam_message_handler` | 反垃圾、广告、链接、黑名单等入口 |
| -2 | `command_alias_handler` | 群命令别名优先处理 |
| -2 | `MessageRouter.dispatch` | 私聊配置输入和群消息统一分发 |

按钮回调按前缀进入各自处理器，例如 `vfy:`、`adm_vfy:`、`autodel:`、`afcfg:`、`ascfg:`、`gg:` 等。

## 5. 消息分发模型

`backend/app/update_pipeline.py` 中的 `MessageDispatcher` 是普通消息的统一入口。

### 私聊消息

私聊优先读取用户状态：

1. 查询当前私聊状态
2. 如果私聊状态记录了 `managed_chat_id`，切到目标群状态
3. 如果没有，则通过 `ChatResolver.get_current_chat()` 查当前管理群
4. 有配置状态时交给 `PrivateConfigHandler`
5. 无配置状态时进入默认私聊处理

这个设计保证管理员在私聊里点按钮进入配置后，后续文本、媒体、按钮输入能落到正确群组。

### 群聊消息

群聊消息统一进入 `GroupMessageHandler`，并由群消息 pipeline 处理：

- 权限和基础上下文解析
- 新人限制、强制订阅、车库/群控等前置规则
- 违禁词、反垃圾、防刷屏等风控
- 积分、邀请、活动、自动回复等业务逻辑

非文本消息也会进入统一链路，因为媒体消息同样可能触发限制、风控或运营规则。

## 6. 业务分层

项目不是传统单一 MVC，而是以功能域为边界的 vertical slice：

```text
Telegram Update
  -> Router / Handler
  -> Permission / State / Chat resolver
  -> Domain Service
  -> ORM Model / Shared Service
  -> UI formatter / Keyboard builder
  -> Telegram API response
```

推荐职责边界：

- **Router/Handler**：只处理事件匹配、参数解析、权限检查、调用 service、发送响应。
- **Service**：承载业务规则、数据计算、状态变更和事务内操作。
- **UI/Formatter**：生成用户可见文案、按钮和列表展示。
- **Shared/Platform**：只放跨域复用能力，例如权限、发布、callback 解析、状态、数据库、调度器。

## 7. 车库、老师搜索与车评实现

车库相关能力不是单个独立命令，而是接入群消息主链路的运行时功能。入口在 `backend/features/group_ops/group_hooks/garage.py`：

```text
GroupMessageHandler
  -> group_hooks.core
    -> _process_garage_features()
      -> 老师发言限制
      -> 老师搜索 / 开课打卡 / 附近搜索
      -> 车评提交 / 查询 / 排行
      -> 认证老师临时标识提示
```

### 7.1 车库认证

车库认证的管理界面位于 `backend/features/admin/garage/auth_views.py`，业务逻辑主要在 `GarageAuthService`。

已实现能力：

- 启停车库认证开关和认证图标。
- 手动添加、删除认证老师。
- 通过联盟关系共享认证池：如果当前群加入联盟，会优先使用联盟 owner 群的认证老师池。
- 生成老师汇总信息，可按地区或价格分组，并可选择只展示开课老师。
- 老师发言限制：支持关闭、仅图片、图文模式，配置时间间隔、限制条数和白名单。
- 认证老师在群内发言时，可临时回复认证标识，展示认证老师身份。

关键数据：

- `garage_certified_teachers`：认证老师池。
- `garage_speech_whitelist`：老师发言限制白名单。
- `chat_settings`：车库认证开关、认证图标、发言限制模式、汇总分组等群级配置。

### 7.2 老师搜索

老师搜索的管理界面位于 `backend/features/admin/garage/teacher_search_views.py`，群内运行时位于 `backend/features/group_ops/group_hooks/teacher_search.py`，查询逻辑由 `TeacherSearchService` 组合 `teacher_search_settings.py` 和 `teacher_search_queries.py` 提供。

已实现能力：

- 标签搜索：群内发送 `老师搜索 关键词`，可按老师用户名、姓名、地区/地址、价格和服务标签匹配。
- 附近搜索：群内发送 `附近` 或 `附近 关键词`，系统读取用户位置并按距离排序返回老师列表。
- 开课老师：群内发送 `开课老师`，返回当天已开课或满课的老师。
- 开课打卡：支持“发言就是打卡”和“固定话术打卡”，固定话术可配置开课、满课、休息关键词。
- 外部打卡群：搜索群可配置为不打卡，只读取另一个管理群的打卡记录。
- 只显开课：搜索和附近结果可限制为当天开课/满课老师。
- 强制录入位置：认证老师未录入位置前，非管理员、非白名单发言会收到私聊更新定位提示。
- 老师资料维护：支持地区/地址、价格、服务标签、位置、开课状态等资料。
- 底部按钮入口：可配置老师搜索入口文案，群友点击后看到使用说明。

关键数据：

- `teacher_search_settings`：搜索开关、打卡模式、外部打卡群、关键词、附近搜索、强制位置、底部按钮等配置。
- `teacher_profiles`：老师位置、标签、地区/地址、价格和资料更新时间。
- `teacher_daily_attendance`：每日开课/满课/休息记录。
- `member_locations`：普通群友位置，用于附近搜索。
- `garage_certified_teachers`：老师搜索的候选池，只展示有效认证老师。

### 7.3 车评系统

车评管理界面位于 `backend/features/admin/garage/review_views.py`，群内运行时位于 `backend/features/group_ops/group_hooks/car_review.py`，业务逻辑由 `CarReviewService` 组合 `car_review_settings.py` 和 `car_review_reports.py` 提供。

已实现能力：

- 启停车评系统。
- 支持默认模式和简易模式。默认模式会按启用的评分字段校验提交内容。
- 自定义评分项：默认包含人照、颜值、身材、服务、态度、环境、过程，也可新增、改名、启停。
- 自定义提交指令和排行指令。
- 回复老师消息提交车评，系统从被回复消息识别目标老师。
- 支持图片/媒体随报告保存。
- 可指定审核人，新报告提交后私聊通知审核人。
- 报告管理：按全部、待审核、已通过、已发布、已驳回筛选。
- 审核日志：提交、通过、驳回等动作写入审计记录。
- 发布模板：报告发布时按模板渲染时间、老师、提交人、评价、评分、过程等字段。
- 积分奖励配置：审核/发布链路保留提交奖励配置。
- 车评排行：群内可查询总排行、本周排行、本月排行，按均分、报告数排序。
- 老师车评查询：开启查车评后，可按老师用户名查询最近已审核/已发布报告和统计。
- 自动刷新老师榜单信息：可把车评条数、均分写回老师标签，供老师搜索展示。

关键数据：

- `car_review_settings`：开关、模式、查车评模式、提交/排行指令、发布目标、审核人、奖励积分、模板。
- `car_review_custom_fields`：车评评分字段。
- `car_review_reports`：车评报告正文、分数、媒体、状态、发布消息。
- `car_review_audit_logs`：车评审核日志。
- `teacher_profiles`：可承载车评条数和均分标签，用于搜索展示。

### 7.4 管理端入口

车库相关管理能力挂在管理员私聊面板，回调前缀主要包括：

- `grg:`：车库认证、认证老师、老师发言限制、老师汇总。
- `tsearch:`：老师搜索、开课打卡、附近搜索、位置代录、底部入口。
- `crv:`：车评系统、评分项、模板、报告管理、审核/发布配置。

这些入口由 `backend/features/admin/garage/controller.py` 组合到管理员控制器中，最终通过 `AdminRouter` 的 `admin_callback` 进入。

## 8. 调度器与后台任务

调度器位于 `backend/platform/scheduler/core/core.py`。

每个任务继承 `ScheduledTask`，提供：

- 固定执行间隔
- 独立 asyncio task loop
- `is_running` 防重入
- 连续失败计数
- 超过失败阈值后自动暂停
- 运行次数和错误次数统计

`backend/app/runtime.py` 启动时注册任务：

- `LotteryTask`
- `AuctionTask`
- `SolitaireTask`
- `AdsTask`
- `CleanupTask`
- `VerificationTimeoutTask`
- `ScheduledMessageTaskRunner`
- `GroupLockTask`
- `RenameMonitorTask`
- `BottomButtonTask`
- `EngagementTask`
- `GameTask`
- `GuessTask`
- `TeacherSearchTask`

启动参数：

- `SCHEDULER_RUN_IMMEDIATELY`：是否启动后立即跑首轮任务
- `SCHEDULER_INITIAL_STAGGER_SECONDS`：首轮任务错峰间隔

## 9. 数据层

数据库访问统一通过 `backend/platform/db/runtime/session.py` 创建：

```text
create_database(DATABASE_URL)
  -> create_async_engine()
  -> async_sessionmaker()
  -> Database(engine, session_factory)
```

核心模型位于 `backend/platform/db/schema/models/`：

- `chat.py`：`tg_users`、`tg_chats`、`chat_settings`、`chat_members`、`conversation_states`
- `points.py`：积分账户、积分流水、签到、统计、自定义积分、等级、商城
- `moderation.py`：违规、警告、验证挑战、自动回复、违禁词
- `automation.py`：广告、轮播规则、定时消息、邀请链接、邀请追踪
- `activity.py`：抽奖、参与者、中奖记录、接龙
- `expansion_games.py`：游戏、竞猜
- `expansion_auction.py`：拍卖
- `alliance.py`：联盟、联合封禁
- `garage_features.py`：车库认证、老师搜索、车评
- `subscription.py`：套餐、群订阅、续费卡密
- `admin_web.py`：Web 后台账号、会话、审计、应用配置

数据隔离以 `chat_id` 为主轴。群配置、积分、风控、活动、邀请、自动化等业务都按群保存，管理员私聊状态再通过当前管理群映射到具体群配置。

## 10. 内置 Web 后台

`backend/features/web_admin/app.py` 创建 FastAPI 应用，默认由 Bot 主进程在 `ADMIN_WEB_HOST:ADMIN_WEB_PORT` 启动。

主要接口：

- `/admin/`：后台静态页面
- `/admin/api/auth/login`、`/me`、`/logout`：管理员登录和会话
- `/admin/api/key-specs`：卡密规格
- `/admin/api/key-batches`：卡密批次生成和查询
- `/admin/api/keys`：卡密查询、复制、导出
- 公告配置接口：由 `announcement_service` 提供平台公告读写

Web 后台复用同一个 `Database`，但会话通过 FastAPI dependency 独立创建和提交。

## 11. 配置与运行模式

配置入口是 `backend/platform/config/core/settings.py`，加载优先级为项目根目录 `.env`，其次 `env`，再读取环境变量。

常用配置：

- `BOT_TOKEN`
- `DATABASE_URL`
- `PROXY_URL`
- `LOG_LEVEL` / `LOG_FORMAT`
- `STARTUP_SCHEMA_MIGRATIONS_ENABLED`
- `SCHEDULER_RUN_IMMEDIATELY`
- `SCHEDULER_INITIAL_STAGGER_SECONDS`
- `BOT_ADMIN_IDS`
- `ADMIN_WEB_ENABLED`
- `ADMIN_WEB_HOST`
- `ADMIN_WEB_PORT`
- `ADMIN_BOOTSTRAP_USERNAME`
- `ADMIN_BOOTSTRAP_PASSWORD`

本地开发建议使用：

```bash
.venv/bin/python main.py --reload
```

生产运行建议通过 `docker-compose.server.yml` 启动，并让宿主机 Nginx 代理内置 Web 后台。

## 12. 扩展新功能的建议路径

新增一个功能时，优先按以下顺序落地：

1. 在 `backend/features/<domain>/` 下新增 Router、handler、service、ui。
2. 如果需要持久化，先增加 ORM 模型和启动迁移/schema gate。
3. 在 `backend/app/router_registry.py` 注册 Router。
4. 如果涉及群消息，接入群消息 pipeline 或明确 handler group。
5. 如果涉及私聊输入，使用 scoped conversation state，并携带目标 `chat_id`。
6. 补充 focused pytest，至少覆盖按钮回调、私聊输入状态和群运行时主链路。
7. 同步 README、功能真值表和用户手册数据。

关键原则：

- 群可见消息只展示用户需要理解的内容。
- 后台配置细节保留在私聊管理面板或 Web 后台。
- 任何回调都要明确当前群作用域，避免跨群误操作。
- 公共工具只沉淀稳定复用能力，不承载单个功能的业务分支。
