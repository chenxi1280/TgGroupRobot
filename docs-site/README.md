# TgGroupRobot 功能手册站点

这是当前仓库内独立维护的静态文档站，用于展示 TgGroupRobot 的功能步骤、Telegram 风格操作图、流程图和逻辑检查。

## 常用命令

```bash
npm install
npm run dev
npm run check
npm run build
```

## 内容维护

- 功能目录维护在 `src/content/features/catalog.json`。
- 每个功能必须包含入口、前置条件、至少 3 个步骤、流程图、Q&A 和逻辑检查。
- `npm run validate` 会检查真值表、主菜单入口和功能文档之间的覆盖关系。

## 设计约定

- 不使用真实 Telegram 截图；步骤图由组件渲染。
- 付费/套餐功能当前只说明“暂时关闭”，不展示购买或续费流程。
- 如果发现代码和文档流程不一致，先在对应功能的 `logicAudit.status` 标记为 `needsReview`。
