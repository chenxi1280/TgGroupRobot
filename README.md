# TgGroupRobot（商业级 Telegram 群管理机器人）

本项目按 `PROMPT_MASTER.md` 的 ①~⑤ 阶段要求，生成一个 **To C** 的、支持 **多用户/多群** 的 Telegram 群管理机器人（类似但可扩展优于 WeGroupRobot）。

## 主要能力（MVP 已实现骨架）

- **多群独立配置**：同一个 bot 可被多个用户添加到多个群，每个群配置完全隔离
- **管理员面板（Inline Keyboard）**：不依赖外部后台，通过指令与菜单完成配置
- **积分体系**：签到、积分变更、积分查询
- **新人验证与发言限制**：新成员入群自动限制权限，完成验证后放行
- **内容审核**：关键词/链接等基础规则审核，记录违规并可自动处理（删除/警告/禁言）
- **广告与商业化骨架**：广告发布入口、群级订阅/套餐数据模型与开关位
- **生产级工程化**：模块化（handlers/services/models）、日志、异常处理、Docker 部署

## 技术栈

- Python 3.11
- `python-telegram-bot`（长轮询，内置 JobQueue）
- PostgreSQL + SQLAlchemy 2.0
- Alembic 迁移
- Docker / docker-compose

## 快速开始（Docker）

1) 准备环境变量

```bash
cp config/env.example .env
```

编辑 `.env`，至少填入：
- `BOT_TOKEN`

2) 启动

```bash
docker compose up --build
```

3) 把机器人加进群并授予管理员权限（至少需要：删除消息、限制成员、置顶/发送消息等权限视功能而定）

## 本地开发（非 Docker）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m bot
```

## 指令（核心）

- `/start`：欢迎与帮助
- `/admin`：管理员面板（群内使用）
- `/sign`：签到领积分（群内使用）
- `/points`：查询个人积分
- `/ad`：发布广告（管理员；用法：`/ad 标题|内容`）

更多设计见 `docs/`。

## 目录结构

```
bot/
  __init__.py
  __main__.py
  config.py
  logging_config.py
  db/
  models/
  services/
  handlers/
  keyboards/
  i18n/
alembic/
docs/
docker-compose.yml
Dockerfile
requirements.txt
```


