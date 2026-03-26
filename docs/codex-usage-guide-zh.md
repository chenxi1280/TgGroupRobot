# Codex 使用教程：从入门到多 Agent 协作的实战手册

更新时间：2026-03-25

这不是一篇只讲“怎么下载、怎么提问”的入门文，而是一篇尽量把 **Codex App、多个子代理协作、工作树、Skills、自动化、跨 IDE 工作流** 讲清楚的中文实战教程。

我会把内容分成两类：

- `官方确认`：来自 OpenAI 官方 Codex 文档或官方公告。
- `社区经验`：一线用户常用技巧，但可能会随版本变化，需要你自己验证。

如果你是第一次接触 Codex，可以先通读前 5 节；如果你已经会用一点，重点看第 6、7、8 节。

---

## 1. 先用一句人话理解 Codex

**Codex 不是“一个更会写代码的聊天框”，而是一套围绕项目持续推进任务的编码 Agent 工作台。**

它能做的不只是回答问题，还包括：

- 读取你的项目目录
- 修改文件
- 运行命令
- 审查 diff
- 调用工具
- 使用 skills
- 派出子代理并行做事
- 在本地环境或 worktree 中执行任务
- 定时跑自动化任务

如果你以前主要用 ChatGPT 聊天、用 Claude Code 跑命令，那么可以把 Codex 理解成：

> **把聊天、项目、环境、任务线程、自动化、技能系统和多代理协作，统一进一个桌面工作台。**

---

## 2. Codex 到底适合谁

### 2.1 对程序员


对程序员来说，Codex 更像是一个能带来明显提效的“第二工作台”：

- 用 App 当指挥台
- 用 IDE 当精修台
- 用 worktree 隔离多条开发线
- 用多个 agent 并行推进
- 用 automations 把重复工作变成定时任务

---

## 3. 2026 年的 Codex 形态，建议你这样理解

### 3.1 它不是只有一个入口

官方文档和公告能确认，Codex 现在至少覆盖这些入口：

| 入口 | 适合场景 |
|------|----------|
| Codex App | 图形化主工作台，适合项目管理、线程协作、自动化、worktree |
| IDE 扩展 | 在 VS Code 系编辑器和 JetBrains 中边看代码边协作 |
| CLI | 终端工作流、脚本化、重度命令行用户 |
| Cloud / 远端任务 | 把任务发到云端或远程环境执行 |

官方还明确写到：**App 会共享你在 CLI 和 IDE extension 的会话历史、环境配置与资源使用情况**。这也是很多人喜欢 App 的原因之一，因为它不是孤立的 GUI 壳，而是和整套 Codex 工作流打通的。  
官方来源：[Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)。
˚

---

## 4. 为什么很多人用了 App 以后，不想退回纯命令行

这一节是你原始参考文档里比较缺的部分。

### 4.1 App 的核心优势，不只是“有界面”

从官方文档能确认的 App 能力包括：

- 在侧边栏创建和管理 `projects`
- 同时开多条 `threads`
- 在对话里直接 `review changes`
- 内置 `terminal`
- 支持 `dictation`
- 支持 `automations`
- 支持 `worktrees`
- 可以和 `IDE extension / CLI` 共享上下文
- 可以通过 `command palette` 快速调起操作

官方来源：

- [App](https://developers.openai.com/codex/app)
- [App Features](https://developers.openai.com/codex/app/features)
- [Commands](https://developers.openai.com/codex/app/commands)

### 4.2 真正让新手受益的，是“操作链路短”

很多人说 App 好用，核心不是“看起来高级”，而是下面这些动作都被缩短了：

- 选项目
- 开线程
- 看 diff
- 切终端
- 打开文件
- 语音输入
- 调用 skills
- 开自动化
- 切换本地环境或 worktree

对新手来说，这就像是从“先学一堆命令再开始”变成了“边做边学，先把事跑起来”。

### 4.3 为什么很多人觉得它有“两倍速开发感”

这不是官方术语，但很容易理解：

- App 负责指挥、审查、切线程
- IDE 负责精修和人工兜底
- Worktree 负责隔离多任务
- 子代理负责并行推进

当这四件事组合起来，你会明显感觉不是“一个 AI 帮你写代码”，而是“你在带一个小团队做活”。

---

## 5. Codex App 保姆级教程

如果你是第一次打开 App，可以按这个顺序走。

### 5.1 第一步：下载、登录、进项目

流程其实很短：

1. 打开 Codex 下载页或官网入口
2. 安装桌面 App
3. 登录 OpenAI 账号
4. 选择或添加一个本地项目目录
5. 新建一个 thread，先用中文自然语言描述目标

如果你不知道第一条消息怎么发，直接套这个模板：

```text
请先阅读当前项目结构，不要急着改代码。
先告诉我：
1. 这是一个什么项目
2. 关键目录分别做什么
3. 如果我要实现 xxx，最可能涉及哪些文件
4. 请先给出一个分步计划，等我确认后再开始修改
```

### 5.2 第二步：先理解三层结构

很多新手卡住，不是不会提问，而是不理解结构。

你可以把 Codex App 理解成三层：

| 层级 | 你该怎么理解 |
|------|---------------|
| Project | 一个项目工作区 |
| Thread | 围绕某个目标推进的一条任务线 |
| Environment | 这条任务线实际在哪个目录/分支/工作树里运行 |

一句话记忆：

> **Project 装项目，Thread 装任务，Environment 决定它在哪个代码上下文里干活。**

### 5.3 第三步：把常用命令背下来

官方文档能确认的常用命令有这些：

| 命令/快捷键 | 作用 |
|-------------|------|
| `Cmd+K` | 打开命令面板 |
| `Cmd+Shift+P` | 打开命令面板 |
| `/status` | 查看当前会话与用量状态 |
| `/logout` | 登出 |
| `Shift+Esc` | 聚焦输入框 |
| `Cmd+Option+U` | 开关侧边栏 |
| `Cmd+J` | 开关终端 |
| `Cmd+.` | 开关 diff |
| `Cmd+Shift+Y` | 开关右侧面板 |

官方来源：[Commands](https://developers.openai.com/codex/app/commands)

### 5.4 第四步：把设置一次配对

官方 `Settings` 页面提到的重点项包括：

- `where files open`
- `maximum output size`
- `prevent machine sleep`
- `notifications`
- `appearance`
- `git branch naming`
- `integrations`
- `personalization`
- `archived threads`

这几个设置里，我最建议新手先看的是下面 5 个：

| 设置项 | 为什么重要 |
|--------|------------|
| `Where files open` | 决定你点文件后更偏向在 App 里看，还是让外部编辑器接管 |
| `Prevent machine sleep` | 做长任务、自动化、批量改代码时非常重要 |
| `Git branch naming` | 统一分支命名，后面配合 worktree 很顺 |
| `Integrations` | 把外部服务接进来，减少切换 |
| `Personalization` | 相当于给 Codex 写长期协作规则 |

官方来源：[Settings](https://developers.openai.com/codex/app/settings)

### 5.5 第五步：把 Personalization 当成“全局协作协议”

这不是“写点偏好”这么简单。

你可以在这里长期固定你的工作方式，比如：

```text
默认使用中文回答。
在改代码前先说明将修改哪些文件、为什么改。
优先做小步修改，避免一次性大改难以审查。
不要猜测不存在的文件、环境变量和 API。
涉及行为变化时，尽量补测试或说明测试方案。
如果发现仓库中有我未提交的改动，不要擅自覆盖。
```

这类规则一旦提前写好，你会明显感觉 Codex 越用越稳。

### 5.6 第六步：学会“App 当指挥台，IDE 当精修台”

这是非常重要的高级习惯。

推荐工作流：

1. 在 App 里开线程、下任务、看计划
2. 在 App 里看 diff、看终端输出、切换 thread
3. 需要精修某一段代码时，用外部 IDE 打开并手工调整
4. 回到 App 继续让 Codex 跑后续动作

为什么这招很强：

- App 适合调度和审查
- IDE 适合局部精修和人工判断
- 两者配合，比死守单一界面顺很多

如果你习惯分屏，可以把 App 拖到一侧、IDE 放另一侧。官方没有把这叫成某个专门功能，但这正是桌面 App 形态的现实优势。

---

## 6. Skills：为什么 Codex 比很多纯命令行工具更适合新手

### 6.1 Skills 是什么

Skills 本质上是一组可复用的能力包，通常包括：

- 使用说明
- 脚本
- 参考资料
- 工作流约束

它的意义是让某些类型任务不必每次都重新从头提示。

### 6.2 为什么 App 的 Skills 体验更友好

很多人从纯命令行工具迁移过来，会立刻感受到区别：

- 看得见有哪些 skill
- 更容易安装、启用、管理
- 新手不用先摸清所有目录结构

官方技能仓库的 README 里也明确提到：可以在 Codex 里使用 `skill-installer` 安装 curated 或 experimental skills，安装后重启 Codex 即可生效。  
参考：[OpenAI skills repository README](https://github.com/openai/skills)

### 6.3 你应该怎么用

最实用的方式不是囤一堆，而是按任务装：

- 做 Figma 设计到代码，装对应设计 skill
- 做 OpenAI 文档检索，装对应 docs skill
- 做测试循环，装对应 Playwright skill
- 做图像生成，装 imagegen skill

技能越贴近任务，收益越大。

### 6.4 新手最容易犯的错

- 一次装太多 skill，自己都记不住
- skill 装好了，但没重启 Codex
- 把 skill 当“万能外挂”，不看它的适用范围

最好的做法是：**先解决一个具体问题，再为这个问题补 skill。**

---

## 7. 多个 Agent Team：怎么让 Codex 像小团队一样协作

这是很多教程最容易漏掉、但实际上非常值钱的一块。

### 7.1 先讲结论：Codex 支持子代理，但你要显式说

官方 `Subagents` 文档写得很明确：

- **Codex 不会自动创建子代理**
- 你需要在 prompt 里 **显式要求** 它创建
- 官方建议优先把子代理用于 **read-heavy 的上下文搜集工作**
- 子代理应返回 **摘要、结论和关键文件位置**，而不是一大坨原始输出

官方来源：[Subagents](https://developers.openai.com/codex/concepts/subagents)

### 7.2 官方给出的子代理类型

当前文档中可以确认的默认类型包括：

| 类型 | 适合做什么 |
|------|------------|
| `default` | 通用任务 |
| `worker` | 具体实现、修复、产出 |
| `explorer` | 代码探索、信息搜集、快速定位 |

官方文档还提到，你可以在项目里通过 `.codex/agents` 定义自定义子代理。  
官方来源：[Subagents](https://developers.openai.com/codex/concepts/subagents)

### 7.3 为什么“5 个子代理分工协作”很强

因为很多真实开发任务，本来就不是单线流程，而是：

- 有人负责拆任务
- 有人负责读代码
- 有人负责写代码
- 有人负责测试
- 有人负责审查风险

Codex 把这种协作方式压缩进一个工作台里了。

### 7.4 我推荐的 5-Agent 分工模板

如果你要做一个中等复杂度功能，可以这样分：

| 子代理 | 角色 | 主要职责 |
|--------|------|----------|
| Agent 1 | Planner | 理需求、拆步骤、列改动范围 |
| Agent 2 | Explorer | 扫代码库、找相关文件、梳理现状 |
| Agent 3 | Worker A | 实现主功能 |
| Agent 4 | Worker B | 写测试、补文档、做边界处理 |
| Agent 5 | Reviewer | 复查风险、找回归点、给验收清单 |

这个结构的好处是：

- 拆得足够细
- 又没有细到管理成本过高
- 对个人用户来说刚好能形成“小型 team”感

### 7.5 可以直接复用的多代理提示词

```text
请为这个任务创建 5 个子代理并行协作：

1. Planner：先把需求拆成步骤，明确涉及的文件和风险点
2. Explorer：快速扫描代码库，找出已有实现、复用点和可能冲突
3. Worker A：负责主功能实现
4. Worker B：负责测试、文档和边界情况处理
5. Reviewer：在其他代理完成后复查改动，输出风险和验收清单

要求：
- 先并行做上下文搜集，再进入实现
- 每个代理只返回结论、关键证据和文件路径
- 不要重复劳动
- 最终请主线程汇总成一个清晰的执行方案，再开始修改
```

### 7.6 什么时候不该乱开 5 个代理

下面这几种情况，不建议为了“看起来高级”硬开：

- 只是改一个按钮文案
- 只是修一个非常明确的报错
- 代码库很小，搜一遍只要几十秒
- 你自己都还没讲清目标

一句话原则：

> **任务越复杂、范围越大、可并行性越强，多代理价值越高。**

### 7.7 官方给的模型建议

官方 `Subagents` 文档还给了很实用的建议：

- 编程子代理通常可以从 `gpt-5.4` 开始
- 小型扫描类任务可以考虑 `GPT-5.4 Mini`

如果你只是要“先把上下文看明白”，Explorer 用 mini 往往已经够了。

---

## 8. Codex 高级技巧：工作树 Worktrees 到底怎么用

这是另一个经常被漏讲，但其实非常关键的主题。

### 8.1 Worktree 不是 Codex 独创，它底层来自 Git

先讲人话版：

> **Worktree 的作用，就是把同一个仓库拆成多个相互独立的目录和分支，让你可以同时推进不同功能，互不干扰。**

它底层对应的是 Git 的 `git worktree` 能力，只是 Codex App 把它做成了更容易理解和操作的工作流。

### 8.2 官方对 worktree 的定义

在官方 App 文档里，thread 支持两种主要环境：

| 环境类型 | 说明 |
|----------|------|
| `Local environment` | 直接在当前仓库工作 |
| `Worktree` | 从现有仓库派生出一个新的分支和独立目录，专门给这条 thread 使用 |

官方还明确写到：

- Worktree 会在你当前代码库基础上创建新的 branch
- 会在新目录中检出代码
- 不会污染原目录
- 非默认 branch 的 thread 关闭后会自动归档
- 归档 thread 可以恢复
- 需要时可以 `Handoff` 到本地环境继续工作

官方来源：[Worktrees](https://developers.openai.com/codex/app/worktrees)

### 8.3 为什么它特别适合 Codex

因为你一旦开始让 AI 并行做事，就会遇到三个痛点：

- 一个功能还没验证完，另一个功能又想开工
- 你怕 AI 改着改着把现有分支搞乱
- 你想同时试两个方案，但不想互相覆盖

Worktree 刚好解决这三个问题。

### 8.4 你可以这样理解它的价值

假设你同时要做三件事：

- 功能 A：做登录
- 功能 B：改后台 UI
- 功能 C：修一个定时任务

传统单分支方式很容易变成一锅粥。

如果用 worktree，你可以把三件事拆成三条独立线程：

| Thread | Worktree 分支 | 互相影响吗 |
|--------|---------------|------------|
| Thread A | `feat/login` | 不影响 |
| Thread B | `feat/admin-ui` | 不影响 |
| Thread C | `fix/scheduler` | 不影响 |

等每条都验证完，再决定合并回哪条主线。

### 8.5 App 里怎么用

推荐流程：

1. 在项目里新建 thread
2. 选择 `Worktree` 作为环境
3. 指定从哪个起始分支派生
4. 给这条任务起一个清晰的分支名
5. 让 Codex 在这个 worktree 里独立推进
6. 完成后 review diff
7. 确认没问题，再 handoff 回本地或合并到主线

### 8.6 最适合 worktree 的场景

- 同时做多个功能
- 想对同一问题试两套方案
- 需要长期运行的自动化任务
- 一个线程只负责“探索与试错”，另一个线程负责“正式实现”

### 8.7 最容易忽略的一个细节：setup scripts

官方 `Local environments` 文档写得很明确：

- 你可以在项目里创建 `.codex` 目录
- 可以放 `setup.sh`、`setup.ps1`、`setup.cmd` 等脚本
- Codex 会在环境启动前跑这些脚本
- 你还可以定义 `actions`，把一组常用命令变成可直接执行的动作
- 文档还专门提到：**可以给不同平台写不同脚本**

这点非常适合 worktree，因为每次新环境起起来时，你都能自动完成依赖安装、环境检查、数据库迁移之类的准备动作。  
官方来源：[Local environments](https://developers.openai.com/codex/app/local-environments)

### 8.8 一个非常实用的 worktree 提示词

```text
请基于当前项目创建一个新的 worktree 来开发这个功能：
功能目标：xxx
起始分支：main
建议分支名：feat/xxx

要求：
- 先检查项目是否有 .codex/setup 脚本
- 在新 worktree 中独立完成开发
- 所有改动不要影响当前本地工作目录
- 完成后给我一份可审查的 diff 摘要、测试结论和合并建议
```

### 8.9 如果你想理解底层原理

Git 原生命令大致长这样：

```bash
git worktree add ../repo-feat-login -b feat/login main
```

Codex App 做的事情，本质上就是把这套能力包装成了更直观的产品体验。

---

## 9. Automations：把 Codex 从“会话工具”升级成“值班同事”

这块也是很多人低估的功能。

### 9.1 它能做什么

官方文档给出的定义很直接：**自动化允许你按固定时间执行 prompt**。

你可以理解成：

- 到点自动巡检
- 到点自动汇报
- 到点自动检查报错
- 到点自动生成日报、周报
- 到点自动跑维护任务

官方来源：[Automations](https://developers.openai.com/codex/app/automations)

### 9.2 创建自动化时要填什么

官方页面提到的核心项包括：

- 名称
- prompt
- schedule
- environment
- model
- reasoning effort

这说明自动化不是“固定消息提醒”，而是可以明确指定运行环境和模型参数的任务。

### 9.3 官方给的最佳实践，非常值得抄

文档里有几条非常重要：

- 先在普通 thread 里手动测试 prompt，再交给自动化
- 对自动化，优先使用 worktree 环境，避免污染主工作区
- 注意环境权限和 allowlist
- 对高风险任务要更谨慎，避免无限循环或误操作

这几条几乎就是“别翻车”的关键。

### 9.4 适合新手先做的 3 个自动化

| 自动化 | 价值 |
|--------|------|
| 每天早上巡检日志并总结 | 最容易见到真实收益 |
| 每晚检查测试状态并汇报 | 提醒你别把质量完全交给运气 |
| 每周汇总仓库未处理事项 | 让项目推进更连续 |

### 9.5 一个可以直接用的自动化提示词

```text
每天上午 9 点检查这个项目的关键运行状态：
- 先读取最近日志和测试结果
- 如果发现错误，先定位最可能原因
- 给出简洁中文总结
- 如果问题明确且低风险，可以尝试修复并说明改动
- 最终输出一份适合发给负责人查看的日报
```

---

## 10. 高级技巧：把 App、IDE、Skills、Worktree 组合起来

这一节讲你提到的“真正能拉开差距”的部分。

### 10.1 技巧一：把 App 当指挥台，把 IDE 当精修台

最推荐的组合是：

- App 里开线程和任务
- App 里看 diff 和终端
- IDE 里做局部精修
- 再回 App 继续让 Codex 执行后续工作

这样做的好处是：

- 你不会被单一窗口绑死
- 看大局和改细节可以同时兼顾
- 很适合双屏或分屏操作

### 10.2 技巧二：熟练使用命令面板和窗口切换

把下面这些习惯练熟，效率会明显上升：

- `Cmd+K` 或 `Cmd+Shift+P` 调命令面板
- `Cmd+J` 随时开关终端
- `Cmd+.` 直接看 diff
- `Cmd+Option+U` 快速开关侧边栏

很多人以为提效来自“更强 prompt”，其实一半以上来自你是否能快速切窗口、切上下文、看改动。

### 10.3 技巧三：一个项目里，不要只开一个 thread

比较推荐的 thread 分法：

| Thread 类型 | 作用 |
|-------------|------|
| `Plan Thread` | 专门做需求澄清和方案拆解 |
| `Build Thread` | 正式实现 |
| `Fix Thread` | 专门排障和补丁 |
| `Review Thread` | 审查和总结 |

这样你会发现上下文干净很多。

### 10.4 技巧四：把 5-Agent 模式和 worktree 搭配起来

这是高阶玩法：

- 主线程负责调度
- Explorer 去扫代码
- 两个 Worker 分别在独立 worktree 干活
- Reviewer 回来做统一复查

它的本质就是把“并行协作”做成真正可控的过程，而不是一股脑让一个 agent 在一个目录里乱改。

### 10.5 技巧五：用 `.codex` 目录把环境准备标准化

如果你做的是长期项目，强烈建议把这些东西逐步沉淀进 `.codex`：

- setup scripts
- 常用 actions
- 团队级 personalization 约定
- 自定义 agents

这样你每次开新环境、开新 worktree、开新线程时，都会稳很多。

---

## 11. 官方没完全细讲，但非常值得知道的“社区经验”

这一节我会明确标注：**下面不是全部都有官方文档逐条背书，而是实际使用中很常见的经验。**

### 11.1 关于“删不掉归档内容”的处理

官方 `Settings` 只明确提到有 `Archived threads` 管理入口，没有详细展开所有异常场景。  
如果你遇到归档线程状态异常，比较稳妥的思路是：

1. 先从归档中恢复 thread
2. 回到正常线程视图确认状态
3. 再重新归档或转移到新的任务线

有些用户会分享更激进的“复制 ID 后另起线程处理”的办法，但这类做法属于社区绕路技巧，**不保证每个版本都有效，也不建议你把它当正式能力依赖。**

### 11.2 关于“切模型、切项目、切位置”

官方已经能确认：

- 可以在 App 里快速切换 `project / thread / sidebar / terminal / diff`
- 可以在自动化里显式指定 `model` 和 `reasoning effort`

因此，比较稳的理解是：

> **App 更像任务调度中心，IDE 更像代码精修台；不同入口的模型与推理档位控件，最终以你当前版本界面实际显示为准。**

### 11.3 关于“分屏开发”

官方没有把“外部 IDE 分屏编辑”写成单独功能页，但从 App 的 `where files open` 设置、桌面窗口形态、IDE extension 和共享会话历史这些能力看，**App + IDE 分屏协作** 本身就是 Codex 非常自然的使用方式。

---

## 12. 给新手的最佳起步路线

如果你现在就准备开始，我建议按这个顺序练：

1. 先找一个你自己的真实项目目录接进 Codex App
2. 写好 Personalization 的基本协作规则
3. 先开一个 thread，只做“读项目 + 出计划”
4. 再开一个 thread，实现一个非常小、容易验证的需求
5. 学会看 diff、看终端、看文件打开方式
6. 再尝试第一次用 worktree 隔离一个独立功能
7. 然后再试一次 3 到 5 个子代理并行搜集上下文
8. 最后才开始上自动化

这个顺序的好处是：**你会稳定地获得正反馈，而不是一上来就把所有高级功能同时打开。**

---

## 13. 一份适合直接复制的“新手开工模板”

```text
请作为我的 Codex 开发搭档，按下面规则协作：

1. 默认中文回答
2. 先阅读项目结构，不要立刻改代码
3. 先告诉我相关文件、实现思路和风险点
4. 改动尽量小步进行，方便我审查
5. 如果仓库里有我未提交的改动，不要覆盖
6. 涉及行为变化时，尽量补测试或给出验证步骤
7. 需要时请主动建议是否拆成多个线程、多个子代理或 worktree

本次任务目标：xxx
请先给出计划，等我确认后再开始执行。
```

---

## 14. 一句话总结

如果只用一句话概括 Codex：

> **它最强的地方，不是“会写代码”，而是把项目、环境、线程、技能、自动化和多代理协作收拢成一套能持续推进任务的工作流。**

而你真正该学会的，不只是“怎么提问”，而是这 4 件事：

- 会描述目标
- 会拆任务
- 会隔离上下文
- 会审查结果

一旦这四件事开始顺起来，Codex 对你来说就不再只是一个 AI 工具，而会更像一个真的能带着你推进项目的小型工程团队。

---

## 参考资料（官方）

- [Codex App](https://developers.openai.com/codex/app)
- [Codex App Features](https://developers.openai.com/codex/app/features)
- [Codex App Settings](https://developers.openai.com/codex/app/settings)
- [Codex Commands](https://developers.openai.com/codex/app/commands)
- [Codex Local Environments](https://developers.openai.com/codex/app/local-environments)
- [Codex Worktrees](https://developers.openai.com/codex/app/worktrees)
- [Codex Automations](https://developers.openai.com/codex/app/automations)
- [Codex Subagents](https://developers.openai.com/codex/concepts/subagents)
- [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- [OpenAI Skills Repository](https://github.com/openai/skills)
