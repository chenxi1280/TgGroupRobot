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

## 维护约定

1. 生产环境发布 `tggrouprobot-bot` 和 `tggrouprobot-docs-site` 两个容器。
2. 数据库由独立的 `infra-compose` 提供，不在本项目中创建 PostgreSQL。
3. 服务器环境变量统一放在 `/data/tggrouprobot/shared/.env`。
4. 数据库结构初始化与更新由本项目自己的 `sql/init.sql` 负责。
5. 用户功能手册站点由 `docs-site` 构建，默认只绑定宿主机 `127.0.0.1:18081`，公网访问由基础设施服务器宿主机 Nginx 按 `robot.telema.cn` 转发。
