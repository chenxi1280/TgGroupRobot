# GitHub Actions + SSH 发布

`tggrouprobot` 采用和 `tgmsg` 一致的发布模式：

1. 代码 push 到 GitHub
2. GitHub Actions 在 GitHub runner 上运行
3. runner 通过 SSH 连接服务器
4. 执行 `deploy/release.sh`
5. 服务器接收 release 包并更新 `tggrouprobot-bot` 和用户功能手册站点

## 生产约定

- 服务器目录：`/data/tggrouprobot`
- 当前版本软链：`/data/tggrouprobot/current`
- 共享环境变量：`/data/tggrouprobot/shared/.env`
- 数据库由独立的 `infra-compose` 提供
- 业务容器接入外部网络 `infra_default`
- 用户功能手册站点默认绑定宿主机 `127.0.0.1:18081`，公网由宿主机 Nginx 按 `robot.telema.cn` 转发

## GitHub Secrets

在仓库 `Settings -> Secrets and variables -> Actions` 中新增：

- `PRODUCTION_SSH_PRIVATE_KEY`
- `PRODUCTION_HOST`
- `PRODUCTION_USER`
- `PRODUCTION_PORT` 可选

## GitHub Variables

- `PRODUCTION_BASE_DIR`
  - 推荐值：`/data/tggrouprobot`
- `RELEASE_BRANCHES`
  - 推荐值：`release-tg`

## 第一次发布前的服务器准备

```bash
mkdir -p /data/tggrouprobot/{releases,shared,incoming,backups}
cp /data/tggrouprobot/.env /data/tggrouprobot/shared/.env
```

然后确认 `/data/tggrouprobot/shared/.env` 至少包含：

```env
BOT_TOKEN=...
DATABASE_URL=postgresql+psycopg://app_user:<shared_password>@postgres:5432/tggrouprobot
INFRA_NETWORK_NAME=infra_default
DOCS_SITE_BIND_HOST=127.0.0.1
DOCS_SITE_HOST_PORT=18081
```

## Workflow 做了什么

工作流文件：

- [.github/workflows/deploy-production.yml](/Users/xida/PycharmProjects/TgGroupRobot/.github/workflows/deploy-production.yml)

它会：

1. checkout 当前代码
2. 安装 Node.js，校验并构建 `docs-site`
3. 读取 GitHub Secrets
4. 配置 SSH
5. 调用 `bash deploy/release.sh --host production-server`

而 `deploy/release.sh` 会：

1. 校验当前分支和工作区状态
2. 使用 `git archive` 生成干净 release 包
3. 上传到服务器 `/data/tggrouprobot/incoming`
4. 解压到 `/data/tggrouprobot/releases/<release_id>`
5. 调用 `deploy/server-install-release.sh`
6. 先确保 `tggrouprobot` 数据库存在，再执行项目内 `sql/init.sql`
7. 执行 `docker compose -f docker-compose.server.yml up -d --build --remove-orphans bot docs-site`
8. 更新 `/data/tggrouprobot/current`

## 回滚

```bash
bash /data/tggrouprobot/current/deploy/rollback.sh <release-id>
```

当前线上目录、数据库初始化流程和验收清单，见：

- `docs/deployment/PRODUCTION_RUNTIME.md`
