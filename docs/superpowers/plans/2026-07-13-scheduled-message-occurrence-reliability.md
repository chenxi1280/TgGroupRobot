# 定时消息执行实例可靠性实现计划

1. 扩展 `ScheduledMessageLog` 为唯一 occurrence 状态记录，补齐初始化 SQL、启动迁移和 schema gate。
2. 增加 occurrence planner/store：锁定到期任务、保存完整快照、推进下一执行时间、恢复过期租约。
3. 增加 Telegram executor 和 worker：发送前标记、错误分类、退避重试、不确定态、批次健康失败。
4. 将 scheduler runner 收敛为依赖装配与调用入口，不吞数据库或发送错误。
5. 增加管理员历史、失败重试、取消和不确定态确认重放入口。
6. 按模型、存储、worker、调度、管理入口、schema 逐层测试，并运行完整回归和硬指标检查。
