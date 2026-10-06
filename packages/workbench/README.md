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

| 脚本 / 命令 | 作用 |
|-------------|------|
| `./scripts/dev-workbench.sh` | 启动 GUI + 自动起 Runtime |
| `./scripts/smoke-workbench-chat.sh` | SSE 聊天冒烟（需 7878 已就绪） |
| `uv run pytest tests/contract -q` | Runtime API 契约测试（仓库根执行） |
| `npm run typecheck && npm test` | 本目录 GUI 类型检查 + Vitest |

## 外观：侧边栏背景模糊

macOS 桌面端在「设置 → 外观」中打开对应主题的「半透明侧边栏」，即可调整：

- **不透明度**：15–100%，数值越低，桌面背景越明显。
- **背景模糊（Blur）**：1–64；「自动」使用 macOS 系统毛玻璃。

明暗主题分别保存参数，支持实时预览和跟随系统主题切换。旧配置保留原来的
74% 不透明度与自动模糊；主内容区域仍不透明。自定义模糊不可用时会恢复系统材质
并提示。Windows、Linux 和浏览器预览不显示这些调节项。

自定义 Blur 使用从 Synara 适配的原生 Node-API 插件，开发构建会自动编译；
macOS 打包时按目标架构编译并纳入签名。编译需要可用的 Xcode 或 Command Line Tools。
如果默认 Xcode 尚未完成许可设置，也可使用已安装的 Command Line Tools：

```bash
cd packages/workbench
DEVELOPER_DIR=/Library/Developer/CommandLineTools npm run build
```

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

`contracts/runtime-api.openapi.yaml` · 实现：`src/deepseek_tui/server/`

## 会话分享与跨设备恢复

对话顶部点击「分享 → 复制链接」，另一台电脑打开链接并点击「在应用中继续」。接收方无需配置服务器或密钥，普通对话也无需选择目录。可选携带项目修改。创建链接所需服务由维护者一次性部署，详见 [会话分享部署与使用说明](../../docs/session-sharing.md)。
