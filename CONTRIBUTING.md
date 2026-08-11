# Contributing to Yantu

感谢参与 Yantu。提交前请：

1. 从 `main` 创建主题分支。
2. 不提交 `.env`、API Key、真实数据库、运行日志或个人任务数据。
3. 保持本地优先和轻量原则；新增大型依赖前先在 Issue 说明理由。
4. 为行为变化补充测试，并运行 `python -m pytest`。
5. 提交信息使用简洁的祈使句，Pull Request 说明用户可见变化与验证方式。

AI Provider 应封装在 `src/yantu/ai/`，业务服务不得直接调用特定厂商 API。

