# 插件系统（Plugin System）

> 实现位置：
> - 公共接口：`src/deepseek_tui/plugins/`（`PluginHost` / adapters / grants / store）
> - 迁移期后端：`src/deepseek_tui/integrations/plugins.py`
>
> 状态（2026-07-17）：
> - Phase 0 安全与正确性：已完成（含 project-trust / marketplace 边界 / digest 拒 symlink）
> - Phase 1 PluginHost façade + Engine 会话依赖：已完成
> - Phase 2 IR / pure-read discovery / index digest 绑定：已完成
> - Phase 3 Marketplace git-subdir + explicit ref + `npm:` install：已支持
> - Phase 4 Runtime overlay：session MCP
> - Phase 5 CodeBuddy 不改写源码：已完成
> - Phase 6 内容寻址 store：新安装写入 `plugin-host/sources/sha256/<digest>/`
> - Pi sidecar / `package.json#pi.extensions` 运行时：**已移除**

## Store v2

```text
~/.deepseek/plugin-host/
  sources/sha256/<digest>/...
  derived/v1/<digest>/<adapter>.json
  reports/<digest>/<adapter>.json
  grants/<plugin-id>/<digest>.json
```

安装：publish → symlink（失败则 copy）→ lockfile 记录 digest。
卸载：删除 scope 入口（symlink/目录），并撤销 grant。
GC：`deepseek-tui plugin gc [--dry-run]` 删除无 lockfile/symlink 引用的 digest。
回滚：`deepseek-tui plugin rollback <name> <digest>` 重指向 store digest，并同步 lockfile digest + grant。

源树**禁止 symlink**；publish 时 staged 树 digest 必须与 key 一致。

## 1. 目标架构

```text
Source → Locator → FormatAdapter → DerivedPlugin IR
→ Policy/Grants → PluginSession → Engine
```

作者默认使用 Claude 目录布局。运行时唯一真相是 `DerivedPlugin`（inspect）+
`PluginSession`（Engine）。不要把外部插件“转换改写”成 DeepSeek 专用安装副本。

## 2. 公共接口

```python
PluginHost.inspect(...)
PluginHost.apply(InstallPlugin | UpdatePlugin | RemovePlugin | EnablePlugin | TrustPlugin | GrantPlugin | RevokePlugin | GcPlugins | RollbackPlugin)
PluginHost.open_session(workspace=...)
```

CLI 生命周期命令（install/remove/update/enable/disable/trust/grant/…）一律经 `PluginHost.apply`。

## 3. 授权模型

| 概念 | 含义 |
|---|---|
| PermissionClaim | 插件声明需要什么（不可信，仅 UI/文档） |
| AuthorizationGrant | 用户按 `plugin_id + sha256 digest` 实际允许什么（写在 `~/.deepseek`） |
| trusted（lockfile） | **user/claude scope** 的兼容开关；trust 时同时写入 digest-bound grant |

**Trust 的真实含义**：允许该 digest 的 hooks（任意 shell，继承完整用户环境）与 MCP 进程。
没有单独的「低危 / 高危」运行时门控可挡住 shell——`hooks.execute` 即是代码执行面。

规则：
1. 必须 trusted **且** 有匹配 digest 的 grant，hooks/MCP 才装配。
2. **无**「trusted 但零 grant 文件仍放行」的遗留旁路（已删除）。
3. **Project scope**：checkout 内 `installed_plugins.json` 的 `trusted` **一律忽略**；信任只来自 `~/.deepseek` 下的 grant。Project lockfile **永不写入** `trusted: true`。
4. User/claude 上旧安装（lockfile trusted、尚无 grant）在首次装配时自动 heal 写入 grant。
5. **更新插件**会撤销 grant 并将 trusted 清为 false，需重新 `plugin trust`（不自动续签）。
6. 可变目录安装在装配时重算 digest；内容变更 → grant 失配 → 可执行贡献被拒。

## 4. Discovery

`discover_plugins` **纯读**：不再在 list/GET 时回填 lockfile。
缺少或指纹失效的 `contribution_index` 返回 `None`；`open_session` 可构建**内存**
index 供 prompt catalog，显式 `plugin reindex` / install 才写盘。

## 5. 兼容性

- Claude / CodeBuddy / bare skill：adapter probe + CompatReport
- 外来 hooks 的 `timeout` 单位为**秒**（与 Claude Code 文档一致）
- PreToolUse 决策（exit 2 / deny）**尚未**实现；兼容安全类 hooks 目前只能触发、不能拦截（CompatReport 应视为 degraded）
- Pi 包不再识别或激活

## 6. CLI

```text
deepseek-tui plugin doctor <path>
deepseek-tui plugin install <source> [--plugin ID]
deepseek-tui plugin grant|revoke <name>
deepseek-tui plugin trust|untrust <name>
deepseek-tui plugin gc [--dry-run]
deepseek-tui plugin rollback <name> <digest>
deepseek-tui plugin reindex
```

## 7. 明确未完成 / 边界

- Marketplace object sources 的全量 provenance 产品化
- Hooks 沙箱（scrubbed env / 独立宿主进程）
- PreToolUse 阻塞语义
- 旧安装副本的全量迁移进 content store
