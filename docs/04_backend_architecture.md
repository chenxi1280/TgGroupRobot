# 阶段④：后端架构与代码实现（python-telegram-bot + SQLAlchemy）

## 1) 项目目录结构

```
bot/
  __main__.py               # 入口：注册 handlers 并 run_polling
  config.py                 # 配置（.env / 环境变量）
  logging_config.py         # 日志（structlog JSON）
  db/
    base.py                 # SQLAlchemy DeclarativeBase
    session.py              # AsyncEngine + session_factory
  models/
    core.py                 # 业务数据模型（多群隔离）
    enums.py                # 枚举
  services/
    chat_service.py         # 群与群配置确保存在
    user_service.py         # 用户 upsert
    points_service.py       # 积分与签到
    moderation_service.py   # 审核检测与违规落库
    verification_service.py # 新人验证 token 与状态
    subscription_service.py # 套餐/订阅（骨架）
    telegram_perm.py        # 权限校验（是否管理员）
  handlers/
    start.py                # /start
    admin.py                # /admin + InlineKeyboard 回调
    points.py               # /sign /points
    verification.py         # 新成员事件 + 验证回调
    moderation.py           # 消息审核
    ads.py                  # /ad（MVP 广告发布）
  keyboards/
    admin.py                # 管理面板键盘
    verification.py         # 验证按钮
  i18n/
    strings.py              # 多语言字符串（可扩展）

alembic/                    # 迁移
docs/                       # 阶段①~⑤文档
Dockerfile / docker-compose.yml
```

## 2) 核心模块说明（生产级可维护点）

- **依赖注入**：`Application.bot_data["db"]` 注入 `Database`（engine + session_factory）
- **多群隔离**：所有业务写入都以 `chat_id` 为维度；`chat_settings` 一群一份
- **模块化**：handlers 只做“收消息/回消息”，核心逻辑下沉到 services
- **可扩展**：
  - 新增功能：加一个 service + handler，并在 `/admin` 菜单挂载入口
  - 新增语言：在 `bot/i18n/strings.py` 增加字典

## 3) 示例 Handler

- `/start`：`bot/handlers/start.py`
- `/sign`、`/points`：`bot/handlers/points.py`
- `/admin`：`bot/handlers/admin.py`

## 4) 配置管理方案

- 统一读取 `.env`/环境变量（`bot/config.py`）
- 示例环境变量：`config/env.example`（由于环境限制无法写 `.env.example`）

## 5) Docker 部署示例

- `docker-compose.yml` 提供 `db` + `bot` 两个服务
- 容器启动命令：先 `alembic upgrade head` 再 `python -m bot`





