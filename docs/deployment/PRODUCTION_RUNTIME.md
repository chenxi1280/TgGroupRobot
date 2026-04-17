# Tggrouprobot 线上部署与目录说明

更新时间：`2026-04-04`

本文档记录 `TgGroupRobot` 当前线上真实部署方式、目录结构、用户功能手册站点和数据库初始化流程。

## 1. 当前发布方式

`TgGroupRobot` 当前使用：

- GitHub Actions
- SSH 发布到服务器
- release 目录 + `current` 软链
- `docker compose -f docker-compose.server.yml up -d --build --remove-orphans`

发布链路：

1. GitHub Actions 触发 `deploy/release.sh`
2. 生成 release 包并上传到 `/data/tggrouprobot/incoming`
3. 解压到 `/data/tggrouprobot/releases/<release_id>`
4. 调用 `deploy/server-install-release.sh`
5. 切换 `/data/tggrouprobot/current`
6. 执行数据库检查与 `sql/init.sql`
7. 启动 `tggrouprobot-bot` 和 `tggrouprobot-docs-site`

## 2. 当前线上目录

```text
/data/tggrouprobot
├── backups/
├── current -> /data/tggrouprobot/releases/<release_id>
├── incoming/
├── releases/
└── shared/
    └── .env
```

说明：

- `/data/tggrouprobot/shared/.env` 是 bot 的权威环境变量文件。
- `/data/tggrouprobot/current` 指向当前正在运行的 release。
- `/data/tggrouprobot/incoming` 存放 Actions 上传的 release 包。
- `/data/tggrouprobot/backups` 用于存放归档与备份。

## 3. 数据库与网络

当前依赖：

- PostgreSQL 由 `infra-compose` 提供
- bot 通过 `infra_default` 网络访问服务名 `postgres`

`/data/tggrouprobot/shared/.env` 至少应包含：

```env
BOT_TOKEN=...
DATABASE_URL=postgresql+psycopg://<db_user>:<db_password>@postgres:5432/tggrouprobot
INFRA_NETWORK_NAME=infra_default
DOCS_SITE_HOST_PORT=8080
```

数据库处理流程：

1. `deploy/ensure-database.sh` 从 `DATABASE_URL` 解析连接信息
2. 使用业务账号连接维护库 `postgres`
3. 如果 `tggrouprobot` 数据库不存在，则先创建
4. `deploy/apply-schema.sh` 在目标库执行项目内 `sql/init.sql`
5. 再启动 `tggrouprobot-bot`

## 4. 当前真实挂载

当前线上 `tggrouprobot-bot` 没有宿主机 bind mount。

这意味着：

- 日志默认留在容器标准输出
- 日常检查依赖 `docker logs`

用户功能手册站点由 `docs-site` 构建为静态文件，并通过 `tggrouprobot-docs-site` 容器提供 HTTP 服务。默认宿主机端口为 `8080`，如线上已有反向代理或端口冲突，可在 `/data/tggrouprobot/shared/.env` 中设置：

```env
DOCS_SITE_HOST_PORT=18080
```

## 5. 当前实际 vs 目标架构

目标架构：

- 业务统一使用共享数据库子账号 `app_user`
- 每个项目在发布时自行创建自己的数据库

当前线上实际：

- `TgGroupRobot` 已切换为共享业务账号 `app_user`
- `infra-compose` 的管理员入口已切换为 `postgres`
- PostgreSQL 与 Redis 数据目录已经迁移到 `/data/infra/postgres` 和 `/data/infra/redis`
- `/data/tgmsg/postgres` 与 `/data/tgmsg/redis` 仍保留为回退副本

## 6. 发布后验收清单

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker logs --tail 80 tggrouprobot-bot
docker logs --tail 80 tggrouprobot-docs-site
curl -fsS http://127.0.0.1:${DOCS_SITE_HOST_PORT:-8080}/healthz
docker inspect tggrouprobot-bot --format '{{json .Mounts}}'
readlink -f /data/tggrouprobot/current
```

通过标准：

- `tggrouprobot-bot` 处于 `Up`
- `tggrouprobot-docs-site` 处于 `Up`，且 `/healthz` 返回 `ok`
- 日志持续出现任务执行完成或 Telegram `HTTP/1.1 200 OK`
- `current` 指向最新 release

## 7. 常用运维命令

```bash
# 查看当前版本
readlink -f /data/tggrouprobot/current

# 查看 release 列表
ls -lah /data/tggrouprobot/releases

# 查看上传包
ls -lah /data/tggrouprobot/incoming

# 查看 bot 日志
docker logs --tail 100 tggrouprobot-bot

# 查看用户功能手册站点日志
docker logs --tail 100 tggrouprobot-docs-site

# 回滚
bash /data/tggrouprobot/current/deploy/rollback.sh <release_id>
```
