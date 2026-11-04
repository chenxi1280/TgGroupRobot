# 群内验证与网页拼图实施、发布记录

> 日期：2026-11-04（Asia/Shanghai）
> 状态：实现与上海专项测试完成，生产发布待执行
> 需求：[已确认 PRD](./2026-11-04-verification-channels-prd.md)
> 流程：[接入设计](../architecture/2026-11-04-verification-channels-flow.md)

## 1. 最终行为

- 管理菜单先选择“群内验证”或“网页验证”。群内保留按钮、数学题和数字验证码三种原流程；网页统一为拼图滑块。
- 沿用现有 verification_mode，仅新增 web 值，不增加表或字段。现有群配置不批量切换；管理员启用网页后，新挑战才发送 Mini App 链接。管理员审核、直接禁言新人和后续口令审核保留。
- 网页模式先限制发言，校验 Telegram 身份、本人归属、期限、拼图版本和位置。对齐后自动提交，复用已发布的领取、解禁、成员权限回读、审计和欢迎流程。
- 错位生成新拼图，截止时间不变，不触发群内答错处罚；旧拼图不能再次提交。过期、他人、群内题目和旧网页答案请求都不能借网页解禁。
- 先前版本尚未完成的网页按钮/数字题挑战提示联系管理员重新发起；已完成状态可以继续查询。新版本不保留网页答题接口。

## 2. 落点

| 范围 | 文件与行为 |
|---|---|
| 管理配置 | verification_views.py / verification_home_actions.py：两种方式入口、群内三种选择、网页期限与超时动作；原配置文本与旧菜单同步支持 web |
| 入群分流 | verification_handler.py：按每群模式决定提示，Mini App 开关不再将群内题目自动导向网页；网页限制发言 |
| 拼图 | slider_puzzle.py：随机种子和位置留在 challenge.question/answer，Pillow 渲染背景和透明拼图 PNG，版本为种子摘要 |
| HTTP | GET 返回图片、尺寸、垂直位置、版本及状态；POST 仅接收位置和版本，行锁内判定，错位轮换拼图，成功沿用 processing 流程 |
| 网页 | SliderPuzzle.tsx：原生 range 支持触摸/鼠标与键盘；松开自动提交，处理期间禁用；Verify.tsx 删除网页按钮、数学与数字输入界面 |

新增 Pillow 13.0.0，已核对 [ImageDraw 文档](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html)、[Image 文档](https://pillow.readthedocs.io/en/stable/reference/Image.html)、对应版本 ImageDraw/PNG 源码及本地实际 crop/putalpha 实现。不引入验证码外部服务、缓存或独立账户。

## 3. 验证证据

- 上海专用 tgr_ui_test：原 guard 与互斥锁核验后运行，70 项全部通过，0 失败/错误/跳过，98.82 秒；[JUnit](../../reports/2026-11-04-slider-verification/targeted.xml)。测试覆盖两种位置分流、群内三种方式、权限限制、配置持久回读、拼图容差、错位换图不延长期限、旧版本、旧答案、非本人、过期、并发一次解禁、失败不重放和口令审核。
- 首次专项回归 65 通过、1 项测试失败：非本人测试仍提交旧版 action 字段，被新请求结构以 422 拒绝而未进入归属检查。改为合法拼图请求后重跑上述 70 项全部通过；没有据此修改业务校验。
- 前端生产构建、Ruff、mypy（689 文件）、结构质量与调用契约均通过。文档目录完整；55 条流程、1,687 个回调的匹配审计 0 问题。体验审计只有既存 quick-publish 完成度提示，新人验证没有发现项；未修改无关功能。证据：[本地检查](../../reports/2026-11-04-slider-verification/local-checks.json)。
- 浏览器预览使用本地受控模拟响应，不执行 Telegram 解禁。手机尺寸与桌面布局、鼠标拖动、触摸事件拖动、键盘提交以及错位后新拼图重置分别检查，[UI 检查记录](../../reports/2026-11-04-slider-verification/ui-checks.json)及[手机预览](../../output/playwright/slider-mobile.png)、[桌面预览](../../output/playwright/slider-desktop.png)已保存。

## 4. 四个维度自查

| 维度 | 结论与边界 |
|---|---|
| 正确性 | 群内/网页按配置分流；归属、期限、版本和位置在服务端判定；成功流程保留先领取后调用 Telegram 的顺序 |
| 性能 | 仅首次读取或错位刷新时渲染 320×160 PNG，不增加页面后台轮询、数据库字段或中间件 |
| 可维护性 | 复用既有 challenge 和解禁链路；删除旧网页题目提交与组件，不保留两套网页验证方式 |
| 安全性 | 图片种子和横向目标不出 API；PNG 无附带文本元数据；身份与本人挑战校验、行锁和过期处理保持有效 |

## 5. 发布与现场验收

完整 CI 通过后按 master → release-tg → GitHub Actions 发布，随后独立回读镜像、源码、开关、数据库结构和公网资源。当前没有发送真实群测试消息，也没有替用户执行入群；真实 Telegram 手机/桌面从入群到解禁的现场验收尚未完成，不能以浏览器模拟或 CI 替代。
