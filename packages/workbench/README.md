# DeepSeek Workbench（GUI）

本目录是 Electron 桌面客户端；对话与工具执行由仓库根目录的 Python Runtime（`deepseek_tui serve`，默认端口 **7878**）提供。

## 从仓库根目录启动

```bash
# 已在根目录 README 装过 Python + 配好 Key 后：
cd packages/workbench && npm ci && cd ../..
unset ELECTRON_RUN_AS_NODE
./scripts/dev-workbench.sh
```

- **界面**：Electron 窗口（开发时 Vite 在 `http://127.0.0.1:5173`，仅内部使用）
- **7878**：Runtime API，**不要**在浏览器里当主界面打开

GUI 会自动拉起：

```bash
python -m deepseek_tui serve --http --host 127.0.0.1 --port 7878 \
  --config <repo>/.deepseek/config.toml --insecure
```

## 环境

| 项 | 建议 |
|----|------|
| Python | ≥ 3.10（推荐 3.12） |
| Node | 20 LTS |
| 安装 GUI 依赖 | `npm ci`（勿随意 `npm update`） |
| API Key | 仓库根 `.deepseek/config.toml` |

国内首次安装 Electron 较慢时，脚本会默认：

```bash
ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
```

## 常用脚本（仓库根）

| 脚本 | 作用 |
|------|------|
| `./scripts/dev-workbench.sh` | 启动 GUI + 自动起 Runtime |
| `./scripts/smoke-workbench-chat.sh` | SSE 聊天冒烟（需 7878 已就绪） |
| `./scripts/verify-workbench.sh` | 类型检查 + 测试 + 可选冒烟 |
| `./scripts/contract-check.sh` | `pytest tests/contract` |

## 排错

**Electron 一启动就崩（`exports` undefined）**  
在 Cursor/CI 里常有 `ELECTRON_RUN_AS_NODE=1`：

```bash
unset ELECTRON_RUN_AS_NODE
./scripts/dev-workbench.sh
```

**7878 在浏览器里是 JSON**  
正常，请用 Electron 窗口。

**重装 GUI 依赖**

```bash
rm -rf node_modules && npm ci
```

## API 契约

`contracts/runtime-api.openapi.yaml` · 实现：`src/deepseek_tui/app_server/runtime_api/`
