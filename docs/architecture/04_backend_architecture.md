# 阶段④：后端架构与代码实现（python-telegram-bot + SQLAlchemy）

## 1) 项目目录结构

```
main.py                     # 统一入口
backend/
  bot/
    app.py                  # 启动调度与 polling
    bootstrap.py            # Application 装配与路由注册
    admin/                  # 管理后台相关 handler/router/ui
    activity/               # 抽奖、接龙、积分、游戏
    automation/             # 广告、定时消息
    garage/                 # 车评与转发
    group_ops/              # 群运维与群消息控制
    invite/                 # 邀请链接与继承
    moderation/             # 反垃圾/反刷屏/自动回复
    shared/                 # 通用 dispatch / service / i18n
    state/                  # 会话状态
    subscription/           # 订阅与续费
    ui/                     # 通用 UI/键盘/格式化
    verification/           # 新人验证与欢迎
  config/core/              # 配置和日志
  database/
    init_db.py              # 数据库初始化入口
    runtime/                # Session / schema gate / startup migrations
    schema/models/          # ORM 模型
  scheduler/                # 调度器和后台任务
  utils/                    # 通用工具
scripts/                    # 运维与迁移脚本
docs/                       # 项目文档
sql/                        # init.sql 与增量迁移
```

## 2) 核心模块说明（生产级可维护点）

- **依赖注入**：`Application.bot_data["db"]` 注入 `Database`（engine + session_factory）
- **多群隔离**：所有业务写入都以 `chat_id` 为维度；`chat_settings` 一群一份
- **模块化**：handlers 只做“收消息/回消息”，核心逻辑下沉到 services
- **可扩展**：
  - 新增功能：加一个 service + handler，并在 `/admin` 菜单挂载入口
  - 新增语言：在 `backend/bot/shared/i18n/strings.py` 增加字典

## 3) 示例 Handler

- `/start`：`backend/bot/group_ops/start_handler.py`
- `/sign`、`/points`：`backend/bot/activity/points_handler.py`
- `/admin`：`backend/bot/admin/admin_handler.py`

## 4) 配置管理方案

- 统一读取 `.env`/环境变量（`backend/config/core/settings.py`）
- 示例环境变量：`config/env.example`（由于环境限制无法写 `.env.example`）

## 5) Docker 部署示例

- `docker-compose.yml` / `docker-compose.server.yml` 负责启动 `bot`
- 容器启动命令为 `python main.py`
- 数据库结构初始化通过 `sql/init.sql` 或独立运维脚本完成，不绑定在容器启动命令里


