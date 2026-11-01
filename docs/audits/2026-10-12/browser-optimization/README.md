# 浏览器优化方案

主文档：[PLAN.md](PLAN.md)；可视报告：[PLAN.html](PLAN.html)。

保留现有架构，依次完善可信观察、跨入口收据、录制回放、上下文语义、授权与性能。证据目录区分真实 Chrome、mock 与合成实验，保留当前未解决失败。

独立复审已通过：[plan-review.json](evidence/plan-review.json)。默认按钮回归已修，两个真实 Shadow 完整回放通过。审查期间其他工作继续变更录制与测试，最终来源差异见 [source-final-comparison.json](evidence/source-final-comparison.json)，没有将新修改冒充已完成的全组测试覆盖。

本轮只审查和制定方案，未修改现有业务代码。
