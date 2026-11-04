# 基础验证 Mini App 实施与发布记录

> 后续变更：本页保留 `39adf18` 的历史发布事实；当前“群内三种方式／网页拼图”行为及生产版本见[后续实施记录](./2026-11-04-slider-verification-implementation.md)。

> 日期：2026-11-04（Asia/Shanghai）
> 状态：基础验证 Mini App 已发布并启用；真实 Telegram 手机/桌面现场验收未完成
> 范围：Mini App 外壳、Telegram 身份、按钮/数学题/验证码、原口令审核衔接

## 1. 本次范围

2026-11-04 用户确认采用后续设计中的“验证＋房间制斗牛/炸金花”，快三与黑杰克保持原群内实现。用户随后要求房间输赢共用可兑换商品的群积分，未选择独立不可兑换游戏积分或仅记录胜负的替代方案。因此房间游戏未实施、未发布；这不是用户取消房间需求的记录。本次只交付可独立运行的基础验证部分。

群内现有验证配置继续决定模式、期限、错误和拒绝策略。Mini App 启用后，新挑战在群消息下显示「点击验证」，答案只在成员网页提交。已存在的非网页挑战按原流程完成；人工审核和口令审核仍在原群内/管理员流程处理。没有改动快三、黑杰克规则或积分代码。

## 2. 实现

| 范围 | 落点与行为 |
|---|---|
| 网页 | `miniapp/`，从 Telegram Mini Apps React 模板裁剪；保留 MIT 许可证与来源提交；不含 TON、钱包和游戏界面 |
| 身份 | `backend/features/mini_app/auth.py`，校验原始 `initData` HMAC、签名字段唯一性及 1 小时有效期；不设另一个账号体系 |
| 页面/API | `/miniapp/`；`GET/POST /miniapp/api/verification`。身份放在 `Authorization: tma ...`，挑战放在 `X-Verification-Token`；不把二者放到 API URL |
| 业务 | `backend/features/verification/mini_app_service.py`、`mini_app_actions.py`；本人归属、期限、状态和行锁协调超时任务 |
| 状态 | `verification_challenges.mini_app_status`（可空）；先持久记录 processing 再调用 Telegram，重复请求不重新解禁/处罚/欢迎；失败/未知结果向用户反馈，由管理员核实 |
| 后续审核 | 复用 `verification_state.py` 的挑战生成与群提示；基础验证完成后需口令时不提前解禁 |
| Web 装配 | `backend/app/web.py`；平台后台与成员 Mini App 分别开关、共用服务。后台关闭时成员验证仍能运行 |
| 部署 | Bot 镜像增加前端构建阶段；Compose 传递 `MINI_APP_ENABLED`（默认 false）；Nginx 转发 `/miniapp/` 并关闭该路径访问日志 |
| 数据库 | `0018_mini_app_verification`，仅增加可空字段，已在上海隔离库迁移并通过 schema gate |
| 验证入口 | 只为已启用 Mini App 后的新基础挑战生成网页按钮；旧群内按钮不能替代网页挑战的提交 |

开发环境 `mockEnv` 只生成 UI 预览参数，不能通过真实后端身份认证；生产构建移除这段模拟代码。UI 截图使用本地模拟响应，不能视为真实 Telegram 验收。

## 3. 已完成验证

- 上海专用 `tgr_ui_test`：核验容器标签、数据库、角色与原始 guard，持有互斥锁后迁移/测试。64 项全部通过，124.60 秒；每项 60 秒超时。证据：[专项 JUnit](../../reports/2026-11-04-mini-app-verification/targeted.xml)。
- 覆盖三种基础模式、不可代验、旧 token 失效、错答、到期、超时任务已领取、重复并发、解禁未成功/未知结果、原口令审核，以及数据库结构。
- 本地无数据库的整套回归：1,160 通过、257 因需要隔离数据库而跳过；该次运行发生在最后的辅助函数收敛之前，不能替代最终 CI。证据：[本地 JUnit](../../reports/2026-11-04-mini-app-verification/local-tests.xml)。
- 相关既有验证流程、schema fixture 和前端构建通过；质量阈值、调用契约、Ruff、mypy、文档目录和 55 条流程审计通过。
- 手机尺寸 390×844 的本地开发预览已检查，见[预览截图](../../reports/2026-11-04-mini-app-verification/mobile-preview.png)。这不是手机真实 Telegram 客户端截图。

一项既有快速发布页面回归在累计约 1,390 个群的上海测试库中超过 60 秒：它进入管理群列表后逐群查权限，路径为 `start_handler._handle_private_start → chat_group_service.get_user_managed_chats → PermissionPolicyService.evaluate`。本次未为此修改无关业务或删除测试库数据。发布门禁仍要求 GitHub Actions 在干净 CI 库完整回归通过，不能将中止的上海运行记为通过。

## 4. 发布与实际验收

- 用户已配置 `@testxd02bot` 的 Main Mini App，Bot API 回读 `has_main_web_app=True`。
- 目标 HTTPS 地址为 `https://robot.telema.cn/miniapp/`。
- 按本地 master 提交 → 本地 release-tg 合并 → 推送 release-tg，依赖 GitHub Actions 检查、镜像构建及部署。
- 最终[发布流水线](https://github.com/chenxi1280/TgGroupRobot/actions/runs/41687700966)全部成功，发布提交为 `39adf18d05656634c1ddea9230f7a0e527e000ec`。完整 CI 回归 1,417 项通过、0 失败、0 跳过，耗时 102.78 秒；前端构建、质量阈值、调用契约、Ruff、mypy 和新库迁移均通过。
- 生产运行镜像为 `ghcr.io/chenxi1280/tggrouprobot-bot:39adf18d05656634c1ddea9230f7a0e527e000ec`，容器运行中。独立回读 8 个关键源码文件的 SHA-256 与本地一致，数据库为 `0018_mini_app_verification`，schema gate 通过，`MINI_APP_ENABLED=true`。
- 公网入口、JS、CSS 与原管理页均返回 200；无 Telegram 身份的验证 API 返回 401。已保留 Nginx 和运行配置修改前备份。
- 真实 Telegram 手机/桌面入群、题目提交、限制解除、欢迎消息及口令审核现场验收尚未执行；隔离测试中 Telegram 调用为模拟边界。

## 5. 四个检查维度

| 维度 | 检查结论与边界 |
|---|---|
| 正确性 | 解禁结果与答题状态分开；查询 Telegram 成员权限后才显示完成；未知结果不自动重放；多阶段审核不跳过 |
| 性能 | 网页初次加载和主动提交才查询；不增加后台轮询或中间件。已记录既有群列表测试数据规模对回归时长的影响 |
| 可维护性 | 规则在原验证域；新增成员路由只做认证和请求适配；口令生成/提示由两个入口复用同一函数 |
| 安全性 | 身份和挑战归属由后端确认；前端不接收答案字段；API 不把身份/token 放在 URL，成员页面不复用后台会话 |

## 6. 首轮 CI 拦截与修正

首轮候选 `8dfe40f` 的[流水线](https://github.com/chenxi1280/TgGroupRobot/actions/runs/41685742958)在新库迁移阶段失败：`sql/init.sql` 已创建 `mini_app_status`，随后 `0018` 再次加列导致 DuplicateColumn。镜像和部署阶段均跳过，生产未改变。修正为符合现有 bootstrap＋迁移链约定的 `ADD COLUMN IF NOT EXISTS`，并增加在已初始化字段上重复执行本 revision 后通过 schema gate 的上海数据库回归。

第二轮候选 `ef9e76c` 已通过新库迁移，[流水线](https://github.com/chenxi1280/TgGroupRobot/actions/runs/41686629591)在测试收集时被 AnyIO 4.16 的弃用告警拦截：旧 Starlette TestClient 引用了已弃用的 BlockingPortal 别名。仅将新增身份 HTTP 测试改成现有 httpx AsyncClient/ASGITransport 方式，保留 `-W error`，不降级依赖或屏蔽告警。本地 AnyIO 同步至 CI 的 4.16.0 后重新验证。

## 7. 最终证据与清理

- [GitHub 发布结果](../../reports/2026-11-04-mini-app-verification/github-run.json)与[CI 汇总](../../reports/2026-11-04-mini-app-verification/ci-checks-summary.json)。
- [生产源码与数据库回读](../../reports/2026-11-04-mini-app-verification/production-source-schema.json)、[公网 HTTP 检查](../../reports/2026-11-04-mini-app-verification/production-http.json)、[运行状态](../../reports/2026-11-04-mini-app-verification/production-runtime.json)。
- 已关闭本次本地 Vite 和模拟 API 预览进程。上海专用测试库核验无其他连接后恢复测试前的停止状态，容器与持久卷保留。
- 没有向真实群发送测试消息，也没有替用户执行真实入群；网页与部署检查通过不等同于成员现场验收。待真实成员从新挑战按钮打开 Mini App 后，再确认三种模式、解禁及欢迎消息链路。
