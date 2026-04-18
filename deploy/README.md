# 部署目录说明

`deploy/` 只放和发布、回滚、服务器运行环境相关的脚本。

## 目录职责

- `release.sh`
  - 本地标准发布入口，负责打包并推送 release 到服务器。
- `rollback.sh`
  - 线上版本回滚脚本。
- `server-install-release.sh`
  - 服务器端安装 release、切换软链、拉起服务。
- `compose-up.sh`
  - 统一封装 `docker compose` 启动流程。
- `ensure-database.sh`
  - 使用共享业务子账号连接 infra PostgreSQL，确保本项目数据库存在。
- `apply-schema.sh`
  - 在目标数据库上执行项目内的 `sql/init.sql`。
- `docker-env.sh`
  - 校验 Docker 所需环境变量并封装 compose 命令。
- `check-web.sh`
  - 发布后自动检查 bot 容器、用户手册静态文件、本机后台端口、宿主机 Nginx HTTPS 入口和可选公网 URL。
- `nginx/tggrouprobot.conf.example`
  - 单域名部署示例：`/` 托管用户手册，`/admin/` 反向代理内置后台。

## 维护约定

1. 生产环境只长期运行 `tggrouprobot-bot` 容器。
2. 数据库由独立的 `infra-compose` 提供，不在本项目中创建 PostgreSQL。
3. 服务器环境变量统一放在 `/data/tggrouprobot/shared/.env`。
4. 数据库结构初始化与更新由本项目自己的 `sql/init.sql` 负责。
5. 生产部署不在服务器构建镜像，只拉取 GitHub Actions 推送到 GHCR 的指定 tag。
6. 用户功能手册在 GitHub Actions 中构建为 docs-site 镜像，服务器只释放静态产物到 `/data/infra/www/robot.telema.cn`，由宿主机 Nginx 托管。
7. 后台管理不需要第二个域名。生产环境使用同一个域名的 `/admin/`，由宿主机 Nginx 代理到 `127.0.0.1:8088`。

## 单域名 Web 入口

推荐线上入口：

- `https://robot.telema.cn/`：用户手册静态站点。
- `https://robot.telema.cn/admin/`：后台管理。

生产服务器的 `/data/tggrouprobot/shared/.env` 建议包含：

```dotenv
ADMIN_WEB_ENABLED=true
ADMIN_WEB_HOST=0.0.0.0
ADMIN_WEB_PORT=8088
ADMIN_WEB_PUBLISH_HOST=127.0.0.1
ADMIN_SESSION_DAYS=7
ADMIN_BOOTSTRAP_USERNAME=admin
ADMIN_BOOTSTRAP_PASSWORD=replace_with_a_strong_password
ADMIN_BOOTSTRAP_DISPLAY_NAME=超级管理员
TGGROUPROBOT_DOCS_STATIC_BASE_DIR=/data/infra/www/robot.telema.cn
TGGROUPROBOT_WEB_HOST=robot.telema.cn
TGGROUPROBOT_CHECK_HOST_NGINX=1
TGGROUPROBOT_CHECK_PUBLIC_URLS=0
TGGROUPROBOT_CHECK_ATTEMPTS=6
TGGROUPROBOT_CHECK_RETRY_DELAY_SECONDS=5
```

注意：

- `ADMIN_WEB_HOST=0.0.0.0` 是容器内监听地址，供 Docker 端口映射访问。
- `ADMIN_WEB_PUBLISH_HOST=127.0.0.1` 是宿主机发布地址，避免 `8088` 直接暴露公网。
- 发布脚本默认会运行 `check-web.sh`。如需临时跳过，可以在 GitHub Variables 或执行环境设置 `POST_DEPLOY_CHECKS_ENABLED=false`。
- `TGGROUPROBOT_CHECK_HOST_NGINX=1` 会用 `--resolve robot.telema.cn:443:127.0.0.1` 检查宿主机 Nginx，不依赖公网 DNS。
- `TGGROUPROBOT_CHECK_PUBLIC_URLS=0` 默认关闭公网回环检查，避免服务器网络不支持 hairpin 时误报；需要从服务器侧验证公网解析时再设为 `1`。
- `TGGROUPROBOT_CHECK_ATTEMPTS` 和 `TGGROUPROBOT_CHECK_RETRY_DELAY_SECONDS` 控制发布后检查重试，避免服务刚启动时的短暂窗口误报。
- 宿主机 Nginx 配置可参考 `deploy/nginx/tggrouprobot.conf.example`，启用后执行 `nginx -t && systemctl reload nginx`。

部署后可以在服务器运行：

```bash
bash /data/tggrouprobot/current/deploy/check-web.sh
```
