# 2026-10-15 剩余通用能力续建记录

> 对应：竞品差距PRD v0.7。基线：本地master / feecab8及未提交工作树。
> 状态：本轮选定通用能力已本地实现及隔离验证；未提交、推送、部署、写生产或向真实群/频道发消息。整体PRD及全部38项业务组合未完成。

## 本轮补齐的能力

| 范围 | 结果及操作语义 | 主要实现 |
|---|---|---|
| 成功消息跳转、七态摘要 | 从最近成功记录生成公开/私有超级群及频道合法链接；基本群、缺失确认消息ID不造链接。最新失败/未知不覆盖旧成功。长标题/多语言摘要限制UTF-16长度，保留完整链接 | [摘要](../../backend/features/admin/delivery_summary.py)、[列表](../../backend/features/admin/list_browser.py) |
| 广告/定时附加动作 | 删除旧消息、取消旧置顶、置顶独立持久化；正文失败也保留此前动作。确认发送回执与置顶/延删任务同事务保存，避免收尾前崩溃丢任务。延删不再依赖进程定时器 | [动作日志](../../backend/features/automation/delivery_action_journal.py)、[广告执行](../../backend/features/automation/ad_delivery_executor.py)、[定时执行](../../backend/features/automation/scheduled_delivery_executor.py) |
| 动作恢复入口 | 广告首页/两类列表可进入“附加动作/清理恢复”。明确失败可仅恢复动作；429遵守期限，未知不自动重放，正文不因动作失败重复发送。持久事实优先于执行器旧快照 | [恢复页面](../../backend/features/admin/effect_views.py)、[副作用执行](../../backend/features/admin/services/effect_runtime.py) |
| 配置导入/克隆 | 主积分带签到反馈，夜间管控带两套权限/通知，验证带选中JSON配置；新增独立“积分等级与标签”。重建等级ID再映射标签。保留目标原权限快照，无快照时只读目标群，失败整个事务回滚；未选模块保留 | [复制服务](../../backend/shared/services/config_imports.py)、[导入应用](../../backend/shared/services/import_settings_service.py)、[管理路由](../../backend/features/admin/import_export/settings_transfer.py) |
| 联盟处罚及本群解除 | 命令与命中共享池条目/群/类型稳定身份；普通重复不重复处罚，禁言升级封禁为新动作。处罚前检查现有角色/机器人权限/池版本/成员关系。私聊“本群处罚记录/解除”需要明确确认、当前权限、已确认系统施加及远端状态匹配 | [处罚](../../backend/features/group_ops/services/alliance_effects.py)、[消费](../../backend/features/group_ops/services/alliance_runtime.py)、[页面](../../backend/features/admin/alliance_effect_views.py) |
| 业务日切换及旧worker防护 | 旧UTC签到按不可变created_at确定上海业务日，继承旧统计连签；旧正积分激励按不可变流水去重。广告/定时claim绑定attempt_count，旧worker不得发送或覆盖已被接管的尝试，开始发送前检查租约 | [签到](../../backend/features/points/services/points_service_activity.py)、[激励凭证](../../backend/features/activity/services/engagement_claim_receipts.py)、[广告仓储](../../backend/features/automation/ad_delivery_repository.py)、[定时仓储](../../backend/features/automation/scheduled_occurrence_repository.py) |

配置复制不带余额、实际成员标签、标签所有权、收件人同意、草稿或执行历史。目标已拥有的标签状态留在目标群，后续按目标新等级配置对账。

移除联盟池只停止后续传播，退出不自动解封其他群；本群解除不删全联盟池。同一池版本本群已成功解除后不立即再次处罚，新版本独立判断。已有处罚、未知处罚、目标管理员以及状态冲突不取得可解除所有权。禁言解除恢复此前仍有效的个人限制，并与当前群默认权限取交集；解封不自动邀请用户回群。

本轮额外修复了真实联盟名单/移除按钮群ID解析错误、旧UTC签到连签丢失、持久置顶已成功却被旧执行器结果清空的事实覆盖问题。保留真实业务服务及权限校验，未为通过测试放宽生产逻辑。

## 本地验证

使用Python3.12.9、python-telegram-bot21.6、一次性PostgreSQL16；Application/Router/业务服务/事务真实执行，Telegram仅使用伪造令牌和HTTP传输替身。未启动polling或连接生产。

新增[运行测试](../../tests/test_remaining_generic_postgres.py)24个展开用例、[验收边界测试](../../tests/test_remaining_generic_acceptance_postgres.py)16个展开用例，共40个；不是完整业务矩阵数量。

| 维度 | 本轮证据 |
|---|---|
| 操作及状态 | 实际注册回调、七态摘要、完整消息链接、三类中文/字面特殊字符/精确ID/100与101字、删除最后一页纠正页码、长Unicode页面不超4096 UTF-16单位 |
| 权限及隔离 | 导入两端鉴权沿用v0.6；本轮补目标快照获取失败整单回滚、未选模块不变；联盟目标管理员/缺机器人权限/已有处罚/跨群解除拒绝/外来状态冲突 |
| 并发及恢复 | 延删未到期不做、重启/两worker一次、403/429/网络未知分开；主发送失败保留前置事实；已确认回执后崩溃仍恢复置顶/清理且不发正文；仅重试置顶、旧attempt拒绝开始/收尾 |
| 联盟完整本轮路径 | 重复命令、禁言升封禁、不降级；并发命中、确认解除一次、同版本不重罚；池移除/退出取消未执行传播、不自动解封；恢复原个人限制并保留当前群限制 |
| 业务日旧数据 | 旧UTC同业务日不重复签到/付正奖励，旧连签3继承并于次日到4，三并发只一份基础分与奖金；旧行和旧流水不回写 |
| 列表性能 | 每类1000条/125页，通过实际Application+DB+伪HTTP完整渲染，1000条均可达且无重复，P95断言<2秒。单独样本P95自动回复0.0419s、定时0.0335s、广告0.0450s；不是Telegram真实网络时延 |

最终全量：`pytest -q --maxfail=8 --tb=short -W error` **1272 passed / 120.57s**，无跳过、失败或warning。compileall、Ruff、mypy（664源文件）、结构质量0违规、调用契约0违规、`git diff --check`通过。先前3项旧测试假设失败已修正：菜单改按语义寻找开关、两个session替身接受实际行锁参数。新增置顶崩溃及旧结果覆盖回归随后纳入上述最终全量。

本轮不新增数据库revision，复用0017。空库全链初始化/Schema Gate通过；构造0014旧处罚池（无类型列）后升级0015—0017，旧行默认ban且来源/原因保留，重复升级及Schema Gate再次通过。均限于一次性数据库，无生产迁移。

## 尚未完成或未验证

| 项目 | 当前边界 |
|---|---|
| CG00及真实客户端 | 没有部署、生产迁移、现场角色/权限/发送/清理/标签/提醒验证；窄屏、真实消息可访问性及Telegram当前账号行为未采集 |
| 38项全部业务矩阵 | 既有目录、入口/撤权及具体深度见[19/38/74台账](./2026-10-15-implementation-and-own-feature-audit.md)；没有把40个新用例或1272测试总数当全部业务通过。A01-4全部文本出口、A02-5全过期组合、A12全媒体与分段、A15全参与入口、A18完整延删仍非穷举 |
| 旧零积分激励切换 | 旧记录无积分流水，updated_at又可被后续消息修改，无法自动证明准确领奖时间。上线前需核对存量，不自动推定、回填或补发；新正积分领取兼容已有不可变凭证 |
| 解除处罚的外部事实限制 | Telegram不提供唯一的处罚来源ID，后续人工施加完全同形的处罚无法仅靠状态区分；因此本群解除必须管理员确认，差异状态/未知/无所有权直接拒绝，无自动批量解除 |
| 产品决策 | CG06专属机器人、CG17额外玩法及CG15匿名规则未决，不作为代码缺陷擅自实现 |
| 已排除的业务扩展 | CG04/05/07—11/16相关人员撮合、定位、认证/评价推广及该场景交易不在通用续建范围；原缺口保留，不记通过 |

历史v0.4/v0.5/v0.6测试证据及旧source manifest保留；本轮新源文件哈希清单用于固定当前本地候选，不能证明线上运行版本。

## 最终收尾证据

- [全量测试日志](../../reports/2026-10-15-remaining-general-pytest.log)、[迁移演练日志](../../reports/2026-10-15-remaining-general-migration.log)。迁移fixture使用独立一次性库，不调用应用或Telegram。
- [本地候选源文件清单](../../reports/2026-10-15-remaining-general-source-manifest.json)固定相对feecab8的136个已修改/未跟踪Python源文件、测试和迁移，包含此前各轮改动，并非本轮新增文件数。清单SHA256：`7d06a466a5172c3984d229c6f1acf9cbff82abd231a5e80510d738133c3ec49b`。旧清单保留。
- 已核对19组需求、38个功能ID、74条标准及相关本地Markdown链接；当前能力表更新，历史版本记录保持。一次性数据库容器在验证后停止并删除。
