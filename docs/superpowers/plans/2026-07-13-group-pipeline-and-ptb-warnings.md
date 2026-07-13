# 群消息流水线与 PTB 跟踪修复计划

1. 增加唯一可吞并继续的 `BusinessRuleError` 领域异常。
2. 修改流水线，只捕获业务异常；其他异常记录堆栈后原样抛出并停止后续 handler。
3. 用真实 `_get_business_handlers()` 验证顺序，并覆盖业务异常继续、编程异常停止。
4. 为按 chat/user 跟踪的 ConversationHandler 增加非按消息回调入口包装，保持文本状态关联且消除错误 tracking warning。
5. 运行群流水线、邀请、积分和全量测试，要求 warnings 为零。
