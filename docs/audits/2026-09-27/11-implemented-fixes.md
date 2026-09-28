# 第十一篇修复记录：插件、Skill 与 LSP

完成日期：2026-09-28。接续 [原审核](/Users/fjw/Desktop/deepseek-tui-py-main/docs/audits/2026-09-27/11-plugins-skills-lsp.md)。本轮落实 P01—P11 的正确性与边界修复；原文中的长期架构建议并不因此全部完成。开发期间工作区被外部提交到 `0eeaeb8c`，其中已包含本轮代码与测试；本任务没有执行提交，也没有覆盖该提交。

## 已实施的修复

| 原问题 | 实际改动与验收 |
|---|---|
| P01 摘要歧义 | 摘要输入使用 v2 域标识、条目类型、路径长度、执行位和内容长度，分块读取；拒绝特殊文件和读取长度漂移。两棵原先产生同摘要的不同树现在不同。 |
| P02 身份来源不可信 | 授权摘要始终由磁盘内容计算，忽略 provenance 和目录名中的摘要；已存在的源存储条目也校验实际内容。伪造外部 sha256 路径和篡改存储均不能继承旧内容授权。没有引入第二套存储命名空间信任规则。 |
| P03 能力串权 | Hook 与 MCP 分别检查 hooks.execute、mcp.connect，覆盖四种授权组合；显式空能力集合保持为空，grant 内容的 ID/digest 必须匹配所查询身份。 |
| P04 撤销失效 | 移除加载时自动补 grant；会话每次重新获取轻量贡献时刷新授权和实际内容。回退版本不会沿用原版本的执行授权。 |
| P05 Skill 更新丢失 | 本地来源可往返解析；唯一 staging 中安装成功后再替换。替换失败恢复旧目录；恢复也失败时保留独立备份。更新清除新包携带的信任标记，返回提示要求重新审阅。 |
| P06 名称与目录边界 | install/update/uninstall/trust 共用名称、目录和 marker 链接检查；拒绝路径穿越、绝对名称、目标链接和源目录包含安装目标的递归复制。四类操作使用进程内可重入锁串行化。 |
| P07 LSP 生命周期 | 同语言共享启动任务，调用方取消不终止其他等待者；不同语言仍可同时启动。请求 deadline 包含 send，finally 回收 pending；初始化失败关闭 transport。关闭 manager 收拢启动任务与已创建客户端，失效客户端可重建。 |
| P08 诊断对应关系 | file URI 规范生成和解析，文档键保持一致；按文档串行同步，递增版本，拒绝与当前版本不符的诊断；文档等待包含锁与发送时间。 |
| P09 组合 MCP 歧义 | 工具目录和执行使用同一唯一 provider 判定；同 server namespace 冲突时拒绝路由，工具与资源目录过滤歧义来源；调用前刷新子 manager 配置。 |
| P10 下载资源边界 | npm 元数据和 tarball 改为流式限额读取，拒绝重定向；GitHub 下载逐跳验证 HTTPS/允许主机；解包按成员数量及时终止枚举。 |
| P11 贡献不一致 | 适配器与运行时共用 Markdown 枚举；补齐递归 Skill、agent、command、rule 定位与 rule 检查贡献，运行时继续验证资源位于插件根目录内。 |

## 兼容性与保留边界

- **已有插件需要重新显式信任。** 新摘要不会继承旧摘要授权；旧安装字节和目录不做破坏性迁移。重新信任会绑定实际内容的新摘要。
- 撤销保证下一次贡献加载/会话刷新不再重新授权。已经启动的 Hook 或 MCP 进程不会由本补丁自动实时终止；不能把它描述为即时撤销运行中能力。
- 内容散列是加载时检查，不是文件系统快照或操作系统隔离；检查后并发修改、同长度修改以及完整有界目录遍历仍需独立方案。每次加载重新散列也有额外 I/O 成本，目前优先保证身份正确。
- Skill 锁只协调当前进程，目录交换不是跨进程事务；替换期间有短暂目录不可见窗口。新增 staging 与恢复测试未证明断电一致性。
- LSP 未携带 version 的诊断只能尽力关联；没有真实语言服务器或 Windows 端到端验证。manager 关闭后不再接受新启动。
- MCP 同名 namespace 即使来自禁用配置也保守拒绝，未引入命名迁移；P11 统一的是资源定位，不是全部 DerivedPlugin 模型、禁用规则和兼容性状态。
- npm 默认禁用重定向是明确兼容性收紧；GitHub 保留受限重定向。registry 索引读取及更深层压缩格式资源消耗不在此次限额证明范围内。

## 验证

最终相关回归 **564 passed，6.03 秒**：插件、Skill、LSP、MCP、Engine、内置 Skill、focus 白名单及 MCP/Hook P1 parity。新增 [插件回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_plugin_audit_fixes.py) 与 [LSP 回归](/Users/fjw/Desktop/deepseek-tui-py-main/tests/test_lsp_audit_fixes.py)，覆盖篡改、失败恢复、能力隔离、并发启动/取消、URI 与诊断版本；原有两项 manifest 测试改为显式信任，保留其贡献默认值断言。

```sh
DEEPSEEK_HOME=/tmp/audit11-final CLAUDE_PLUGINS_DIR=/tmp/audit11-empty .venv/bin/pytest -q \
  tests/test_plugin*.py tests/test_lsp_audit_fixes.py \
  tests/contract/test_lsp_diagnostics.py tests/contract/test_skills.py \
  tests/test_skill_frontmatter.py tests/test_mcp*.py tests/engine \
  tests/test_bundled_skills.py tests/test_focus_tool_whitelist.py \
  tests/parity/phase_d/test_mcp_hooks_p1.py
```

Ruff F 检查仍报告 4 个既有未使用 import（integrations/plugins.py 三个、plugins/store.py 一个），本轮不清理无关代码；新增测试与探针无 F 类问题。未跑整个仓库测试，未访问真实网络或执行真实第三方插件。原始 `plugins-probe-results.json` 保留为修复前证据，不能用它表示当前行为；当前行为由回归测试验证。
