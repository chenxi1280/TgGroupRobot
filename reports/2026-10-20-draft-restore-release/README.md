# 日历草稿恢复修复与生产发布记录

## 修复内容

恢复定时消息、轮播规则及轮播消息草稿时清除临时日历状态，保留目标群、对象、输入字段和业务值。已过期的日历按钮不能重新写入；恢复后直接接受手动时间输入。

端到端回归揭示定时/轮播输入另开数据库会话，与上层草稿版本校验持有的锁自等待。相关适配器现传递并复用原事务，保存与版本校验保持同一事务；独立调用仍可自行创建会话。没有取消版本校验或提前释放保护锁。

## 回归证据

定向回归 **43 项全部通过**，其中新增 20 项覆盖五种时间字段与日/小时/分钟/确认四种选择步骤。测试经注册路由退出、恢复、拒绝旧回调、输入日期，再读取原对象的保存值与禁用状态，确认未向群发送消息。输入处理设置 10 秒超时以捕获锁等待。[定向 JUnit](targeted.xml)。

最终全量 **1396 passed，0 failures，0 errors，0 skipped**，耗时 416.74 秒，退出码 0。[全量 JUnit](ui-test-results.xml)、[输出](ui-test-output.log)、[退出码](ui-test-exit-code.txt)。GitHub Actions 独立全量复验同样为 **1396 passed in 65.34s**。

静态检查：Ruff、mypy（680 文件）、质量阈值、调用契约、diff 空白检查均通过。文档站 18 文件零错误/警告/提示，55 条流程、1667 个回调模板匹配，零发现。

所有数据库回归使用上海项目隔离库 tgr_ui_test，核验身份、guard 与互斥锁；测试进程限制为 512 MiB/0.5 CPU。没有启动本机中间件，没有借用生产数据库测试。Telegram 仍为模拟传输；真实手机布局、剪贴板和群消息业务结果尚未验收。

## 发布基线

用户明确授权修复后发布生产，范围包括本聊天已完成并审查的累计页面、输入组件和活动/自动化日历改动。

发布前生产镜像：ghcr.io/chenxi1280/tggrouprobot-bot:ab5d7f011ad2f422f8a1552df09154fdd3a53f5a。主机为马来西亚，当前 release 为 20261015093700_ab5d7f0。通过既有 release-tg GitHub Actions 完成检查、镜像构建和发布，发布后另行核验实际容器、源码、迁移与 HTTP 状态。

## 生产发布结果

北京时间 2026-10-20 23:45 完成生产发布。运行提交 **131872a3f6042185dff17405b0699014aed9ee2b**，release 目录为 `20261020154451_131872a`。镜像标签与提交一致；容器 running、重启次数 0。当前容器未配置 Docker HEALTHCHECK，因此另以 HTTP、数据库 schema gate 与源码哈希核验。

[发布流水线](https://github.com/chenxi1280/TgGroupRobot/actions/runs/39450796023) 的检查、两镜像构建和部署均成功。[流水线记录](github-run.json)。生产数据库版本 `0017_generic_admin_delivery`，schema gate 通过；七个关键文件与本地候选哈希完全一致。[源码及数据库核验](production-source-schema.json)。

管理页本地/宿主 Nginx、文档站及公开 DNS 路径检查通过，HTTP 200；Nginx healthz 为 ok。[容器与基础健康](production-health.txt)、[公开路径检查](production-web-public.txt)。发布后日志样本 16 行，未匹配 error/critical 或 Python traceback；该短时样本不代表长期业务无异常。[日志计数](production-log-counts.json)。

本次核验没有发送真实 Telegram 消息，未宣称手机视觉、原生剪贴板或真实群业务结果验收完成。后续证据文档以仅文档提交推送 master，不再次触发 release-tg 发布；线上代码身份以上述运行提交为准。
