# 插件系统（Plugin System）

> 实现位置：
> - 公共接口：`src/deepseek_tui/plugins/`（`PluginHost` / adapters / grants / store / Pi sidecar）
> - 迁移期后端：`src/deepseek_tui/integrations/plugins.py`
>
> 状态（2026-07-14）：
> - Phase 0 安全与正确性：已完成
> - Phase 1 PluginHost façade + Engine 会话依赖：已完成（Engine 经 `PluginSession` / `merge_session_skills`，不直接 import collectors）
> - Phase 2 IR / pure-read discovery / index digest 绑定：已完成
> - Phase 3 Marketplace git-subdir + explicit ref + `npm:` install：已支持
> - Phase 4 Runtime overlay / lease：session MCP + Pi tool lease
> - Phase 5 CodeBuddy 不改写源码：已完成
> - Phase 6 Pi sidecar tracer bullet：JS/MJS + 可选 TS（Node `--experimental-strip-types`）
> - Phase 7 内容寻址 store：新安装写入 `plugin-host/sources/sha256/<digest>/`，scope 目录优先 symlink；`plugin gc` / `plugin rollback`

## Store v2

```text
~/.deepseek/plugin-host/
  sources/sha256/<digest>/...
  derived/v1/<digest>/<adapter>.json
  reports/<digest>/<adapter>.json
  grants/<plugin-id>/<digest>.json
```

安装：publish → symlink（失败则 copy）→ lockfile 记录 digest。
卸载：删除 scope 入口（symlink/目录），不自动 GC store。
GC：`deepseek-tui plugin gc [--dry-run]` 删除无 lockfile/symlink 引用的 digest。
回滚：`deepseek-tui plugin rollback <name> <digest>` 将 scope 入口重新指向已有 store digest。

## Pi sidecar

`node [ --experimental-strip-types ] plugins/pi_bridge/bridge.cjs` 经 NDJSON JSON-RPC 加载 `package.json#pi.extensions`。
支持 `initialize` / `tools/*` / `commands/*` / lifecycle / `shutdown`。
ExtensionAPI shim：`registerTool` / `registerCommand` / `on`/`off` / context / ui stubs。
信任插件在 `Engine.create` 时自动 `activate_pi_provider`。
TypeScript entry：Node 22.6+ 经 strip-types 加载（adapter 报告 `PI_TYPESCRIPT_STRIP_TYPES`）；旧 Node 仍 blocked。

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

Engine 通过 `plugin_session` 激活命令/agent/rule，挂载场景时刷新 trust，关闭时
`await plugin_session.close()` 并停止 session-scoped MCP。

## 3. 授权模型

| 概念 | 含义 |
|---|---|
| PermissionClaim | 插件声明需要什么（不可信） |
| AuthorizationGrant | 用户按 `plugin_id + sha256 digest` 实际允许什么 |
| trusted（lockfile） | 兼容开关；trust 时写入 digest-bound grant |

运行时 hooks / MCP / Pi 在 `trusted` 之外还检查 digest-bound grant：
当前内容 digest 无匹配 grant、且该插件已有其它 digest 的 grant 时，跳过可执行贡献。
无任何 grant 文件的旧安装仍可凭 `trusted=true` 过渡。
仅含历史 `fp:` grant 的安装会在首次装配时自动迁移为当前 `sha256:` grant。

更新插件会撤销旧 grant；若仍 trusted，会为新 digest 重新签发。
`content_fingerprint`（`fp:`）只用于 index 失效，不用于授权绑定。

## 4. Discovery

`discover_plugins` **纯读**：不再在 list/GET 时回填 lockfile。
缺少或指纹失效的 `contribution_index` 返回 `None`；`open_session` 可构建**内存**
index 供 prompt catalog，显式 `plugin reindex` / install 才写盘。

Index 绑定：`schema_version` + `content_fingerprint` + `adapter_id/version` + `source_digest`。

## 5. 兼容性

- Claude / CodeBuddy / bare skill / Pi package：adapter probe + CompatReport
- 安装**不再** `normalize_installed_plugin` 改写 vendor 副本
- 加载期继续映射 `${CLAUDE_PLUGIN_ROOT}` / CodeBuddy matcher
- Pi：可安装；激活依赖 Node sidecar + trust/grant

## 6. CLI

```text
deepseek-tui plugin doctor <path>
deepseek-tui plugin install <source> [--plugin ID]
  # source: path | github:… | npm:pkg[@ver] | name@marketplace
deepseek-tui plugin grant|revoke <name>
deepseek-tui plugin trust|untrust <name>
deepseek-tui plugin gc [--dry-run]
deepseek-tui plugin rollback <name> <digest>
deepseek-tui plugin reindex
```

## 7. 明确未完成 / 边界

- **TODO(pi-computer-use):** 专用跟进项——让 `@injaneity/pi-computer-use`（或同类包）在 deepseek-tui 里真 e2e 可用：原生 macOS helper / postinstall、AX 工具面、命令 `/computer-use`。当前 Pi sidecar 仅为 tracer-bullet（JS/MJS + 可选 TS strip-types），**不足以宣称 computer-use 已可用**。有时间再开任务做，不阻塞通用 Claude 插件路径。
- 完整 Pi ExtensionAPI（widgets / keybindings / custom renderers）— 仅当需要更多 Pi 扩展时再扩
- Marketplace object sources 的全量 provenance 产品化
- 旧安装副本的全量迁移进 content store（新安装已走 store；旧副本照常可用）
