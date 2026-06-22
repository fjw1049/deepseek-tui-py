# GitHub Trending 面板实现文档

## 背景

将聊天空状态的「任务推荐」面板（TaskSuggestionHero）替换为 GitHub 热门仓库浏览面板，数据来自 TrendShift.io。用户可按 日/周/月 切换，点击仓库卡片让 DeepSeek 分析，或跳转 GitHub。

---

## 数据源分析

**TrendShift.io** 是 Next.js SSR 站点，无公开 REST API，数据嵌在服务端渲染的 HTML 中。

| 维度 | URL |
|------|-----|
| 日榜 | `https://trendshift.io/` |
| 周榜 | `https://trendshift.io/weekly` |
| 月榜 | `https://trendshift.io/monthly` |

每条仓库在 HTML 中的关键特征（从 a11y 快照逆向得出）：

| 字段 | HTML 定位方式 |
|------|--------------|
| 仓库名 `owner/repo` | `<a href="/repositories/数字ID">owner/repo</a>` — 链接文本即 `owner/repo` 格式 |
| 描述 | 紧跟仓库链接后的纯文本段落 |
| Stars 总量 | 仓库链接后第 1 个独立数字文本（如 `1.5k`、`995`） |
| 今日/本周增长 | 仓库链接后第 2 个独立数字文本（如 `114`） |
| Topic 标签 | `<a href="/topics/xxx">#TAG_NAME</a>` — 在每条仓库描述之后 |
| 是否新上榜 | 包含文本 `NEW` + 年份（如 `NEW 2026`） |
| 排名 | 按出现顺序，1~25 |

**GitHub URL 推导**：仓库名格式为 `owner/repo`，直接拼 `https://github.com/owner/repo`。

---

## 涉及文件（共 6 个）

| 操作 | 文件路径 |
|------|----------|
| **新建** | `packages/workbench/src/main/services/trending-repos.ts` |
| 修改 | `packages/workbench/src/shared/ds-gui-api.ts` |
| 修改 | `packages/workbench/src/main/ipc/app-ipc-schemas.ts` |
| 修改 | `packages/workbench/src/main/ipc/register-app-ipc-handlers.ts` |
| 修改 | `packages/workbench/src/preload/index.ts` |
| **重写** | `packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx` |
| 修改 | `packages/workbench/src/renderer/src/locales/zh/common.json` |
| 修改 | `packages/workbench/src/renderer/src/locales/en/common.json` |

**不改动**：`MessageTimeline.tsx`（导入名和 props 签名不变）、`workspace-suggestions.ts`（保留不删）、Python 后端代码。

---

## 步骤 1：定义共享类型

**文件**：`packages/workbench/src/shared/ds-gui-api.ts`

在 `WorkspaceSuggestionsResult` 类型定义之后（约 L181），新增三个类型导出：

- `TrendingRepo` — 单条仓库数据
  - `rank: number` — 排名 1~25
  - `name: string` — `"owner/repo"` 格式
  - `description: string` — 仓库描述
  - `stars: string` — 总 star 数，保留原文（如 `"1.5k"`）
  - `gained: string` — 周期内增长数（如 `"114"`）
  - `topics: string[]` — 话题标签数组（如 `["AI agent", "MCP"]`）
  - `isNew: boolean` — 是否标记为 NEW
  - `url: string` — `"https://github.com/owner/repo"`

- `TrendingPeriod` — `'daily' | 'weekly' | 'monthly'`

- `TrendingResult` — 联合类型
  - 成功：`{ ok: true; repos: TrendingRepo[]; period: TrendingPeriod; cachedAt: number }`
  - 失败：`{ ok: false; error: string }`

在 `DsGuiApi` 接口中（约 L230 `getWorkspaceSuggestions` 之后），新增一行方法签名：
- `getTrendingRepos: (period: TrendingPeriod) => Promise<TrendingResult>`

---

## 步骤 2：新增 IPC Schema

**文件**：`packages/workbench/src/main/ipc/app-ipc-schemas.ts`

文件末尾新增：
- `trendingPeriodSchema` — `z.enum(['daily', 'weekly', 'monthly'])`

---

## 步骤 3：新建 Main 进程抓取服务

**文件（新建）**：`packages/workbench/src/main/services/trending-repos.ts`

### 核心逻辑

1. **URL 映射**
   - `daily` → `https://trendshift.io/`
   - `weekly` → `https://trendshift.io/weekly`
   - `monthly` → `https://trendshift.io/monthly`

2. **HTTP 请求**
   - 用全局 `fetch()`（Electron main 进程自带，项目已有先例见 `upstream-models.ts:25`、`deepseek-process.ts:449`）
   - 设置 `User-Agent` 为常见浏览器 UA
   - 超时 `AbortSignal.timeout(10_000)`

3. **HTML 解析**（正则，不引入 cheerio）
   - 提取所有 `<a href="/repositories/\d+">` 链接，取其文本内容作为 `owner/repo`
   - 每个仓库块的边界：从一个 repository 链接到下一个 repository 链接之间的 HTML
   - 在每个块内用正则提取：
     - 描述：repository 链接后、下一个 `<a>` 之前的最长纯文本
     - stars + gained：按顺序匹配独立数字文本（第 1 个是 stars，第 2 个是 gained）
     - topics：所有 `href="/topics/xxx"` 链接的文本内容（去掉 `#` 前缀）
     - isNew：块内是否包含文本 `NEW` 紧跟 4 位数字年份
   - 排名按出现顺序从 1 开始
   - 取前 20 条

4. **缓存**
   - 模块级 `Map<TrendingPeriod, { result: TrendingResult; fetchedAt: number }>`
   - 缓存 TTL：10 分钟（`600_000ms`）
   - 命中缓存直接返回，不发请求

5. **导出函数**
   - `getTrendingRepos(period: TrendingPeriod): Promise<TrendingResult>`
   - 失败返回 `{ ok: false, error: '...' }`，不抛异常

---

## 步骤 4：注册 IPC Handler

**文件**：`packages/workbench/src/main/ipc/register-app-ipc-handlers.ts`

### 新增导入（文件顶部）
- 从 `../services/trending-repos` 导入 `getTrendingRepos`
- 从 `./app-ipc-schemas` 导入 `trendingPeriodSchema`

### 新增 handler（在 `workspace:suggestions` handler 之后，约 L843）
- 注册 `ipcMain.handle('trending:repos', ...)`
- 用 `parseIpcPayload('trending:repos', trendingPeriodSchema, period)` 校验参数
- 调用 `getTrendingRepos(period)` 并返回结果

---

## 步骤 5：Preload 桥接

**文件**：`packages/workbench/src/preload/index.ts`

在 `getWorkspaceSuggestions` 行之后（约 L54），新增一行：
- `getTrendingRepos: (period) => ipcRenderer.invoke('trending:repos', period)`

---

## 步骤 6：重写前端组件

**文件**：`packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx`

### 导出保持不变

- 仍然导出 `TaskSuggestionHero` 组件（名字不改，避免改 MessageTimeline 导入）
- 仍然导出 `TaskSuggestionOfflineHero`（**这个组件不动**，原样保留）
- Props 签名不变：`{ onSelectSuggestion?: (prompt: string) => void }`

### 删除的内容

- 所有 `STATIC_SUGGESTIONS` 定义
- 所有 `DYNAMIC_ICON`、`iconForDynamic`、`parseBranchIntent` 等
- 轮播逻辑（`focusedIndex`、`CAROUSEL_INTERVAL_MS`、底部圆点指示器）
- `WorkspaceSuggestion` 相关的 import 和 state

### 新增的 import

- `TrendingPeriod`, `TrendingRepo` — 从 `../../../../shared/ds-gui-api`
- `Flame`, `Star`, `TrendingUp`, `ExternalLink`, `ArrowUp` — 从 `lucide-react`

### 新增的状态

- `period: TrendingPeriod` — 当前选中的时间维度，默认 `'daily'`
- `repos: TrendingRepo[]` — 仓库列表
- `loading: boolean` — 加载中
- `error: string | null` — 错误信息

### 数据获取

- `useEffect` 依赖 `[period]`
- 调用 `window.dsGui.getTrendingRepos(period)`
- 设置 loading/error/repos 状态
- 用 `let cancelled = false` + cleanup 防竞态

### 布局结构

```
<div class="ds-no-drag w-full">
  <div class="ds-hero-panel ds-glass rounded-[22px] px-5 py-7">

    <!-- 头部：标题 + 时间 Tab -->
    <div class="flex items-start justify-between">
      <div>
        <badge> Flame图标 + t('emptyHeroBadge') </badge>
        <h1> t('emptyHeroTitle') </h1>
        <p> t('emptyHeroSub') </p>
      </div>
      <div class="tab 按钮组 rounded-full border">
        三个按钮：今日 / 本周 / 本月
        选中态：bg-accent text-white
        未选中：text-ds-muted hover:text-ds-ink
      </div>
    </div>

    <!-- 列表区域 -->
    <div class="mt-5 max-h-[480px] overflow-y-auto space-y-1">

      <!-- 加载态：3 个骨架卡片 -->
      <!-- 错误态：错误文本 + 重试按钮 -->
      <!-- 正常态：repo 卡片列表 -->

      {repos.map(repo => (
        <button
          onClick={() => onSelectSuggestion(分析 prompt)}
          class="w-full flex items-start gap-3 rounded-xl px-3 py-3
                 border border-transparent
                 hover:border-ds-border hover:bg-ds-elevated
                 transition text-left group"
        >
          <!-- 排名数字 -->
          <span class="w-6 text-center font-mono text-ds-muted">
            {repo.rank}
          </span>

          <!-- 主体 -->
          <div class="flex-1 min-w-0">
            <!-- 第一行：仓库名 + stars + gained -->
            <div class="flex items-center gap-2">
              <span class="font-semibold text-ds-ink truncate">
                {repo.name}
              </span>
              {repo.isNew && <badge>NEW</badge>}
              <span class="ml-auto flex items-center gap-3 text-xs text-ds-muted">
                <span>Star图标 {repo.stars}</span>
                <span class="text-emerald-500">ArrowUp图标 {repo.gained}</span>
              </span>
            </div>

            <!-- 第二行：描述（1行截断） -->
            <p class="text-xs text-ds-muted line-clamp-1 mt-0.5">
              {repo.description}
            </p>

            <!-- 第三行：topic 标签 -->
            <div class="flex flex-wrap gap-1.5 mt-1.5">
              {repo.topics.map(t => (
                <span class="rounded-full bg-accent/8 px-2 py-0.5
                             text-[11px] text-accent">
                  #{t}
                </span>
              ))}
            </div>
          </div>

          <!-- 右侧：外链按钮（hover 可见） -->
          <button
            onClick={(e) => {
              e.stopPropagation()
              window.dsGui.openExternal(repo.url)
            }}
            class="opacity-0 group-hover:opacity-100 transition"
            title={t('trendingOpenGithub')}
          >
            ExternalLink图标
          </button>
        </button>
      ))}
    </div>

  </div>
</div>
```

### 骨架屏

3 个相同结构的 div，内部用 `animate-pulse` + `bg-ds-border/50 rounded` 色块模拟：
- 一行短色块（模拟排名+名称）
- 一行长色块（模拟描述）
- 三个圆角小色块（模拟 tags）

### 点击交互

主点击 → 调用 `onSelectSuggestion` 传入 prompt：
```
帮我分析 GitHub 仓库 {repo.name}，包括项目定位、核心架构、技术栈和亮点。仓库地址：{repo.url}
```

---

## 步骤 7：更新国际化

### `locales/zh/common.json`

**替换** 以下 key 的值（key 名复用 `emptyHero*`）：

| key | 新值 |
|-----|------|
| `emptyHeroBadge` | `"GitHub Trending"` |
| `emptyHeroTitle` | `"发现热门开源项目"` |
| `emptyHeroSub` | `"实时热门仓库，点击即可让 DeepSeek 帮你深入分析。"` |
| `emptyHeroScanProject` | **删除**（不再需要） |
| `emptyHeroRecommended` | **删除**（不再需要） |

**新增** 以下 key：

| key | 值 |
|-----|-----|
| `trendingDaily` | `"今日"` |
| `trendingWeekly` | `"本周"` |
| `trendingMonthly` | `"本月"` |
| `trendingGained` | `"增长"` |
| `trendingOpenGithub` | `"在 GitHub 打开"` |
| `trendingLoading` | `"正在加载热门仓库..."` |
| `trendingError` | `"加载失败"` |
| `trendingRetry` | `"重试"` |
| `trendingNew` | `"新上榜"` |
| `trendingAnalyzePrompt` | `"帮我分析 GitHub 仓库 {{name}}，包括项目定位、核心架构、技术栈和亮点。仓库地址：{{url}}"` |

**删除**（不再被引用）：
- `promptStructureTitle` / `Desc` / `Flow` / `Tag` / `Sub` / `Prompt`
- `promptBugTitle` / `Desc` / `Flow` / `Tag` / `Sub` / `Prompt`
- `promptPlanTitle` / `Desc` / `Flow` / `Tag` / `Sub` / `Prompt`
- `promptDesignTitle` / `Desc` / `Flow` / `Tag` / `Sub` / `Prompt`

### `locales/en/common.json`

同结构，英文对应值：

| key | 值 |
|-----|-----|
| `emptyHeroBadge` | `"GitHub Trending"` |
| `emptyHeroTitle` | `"Discover trending repositories"` |
| `emptyHeroSub` | `"Live trending repos. Click to have DeepSeek analyze any project."` |
| `trendingDaily` | `"Today"` |
| `trendingWeekly` | `"This week"` |
| `trendingMonthly` | `"This month"` |
| `trendingGained` | `"gained"` |
| `trendingOpenGithub` | `"Open on GitHub"` |
| `trendingLoading` | `"Loading trending repos..."` |
| `trendingError` | `"Failed to load"` |
| `trendingRetry` | `"Retry"` |
| `trendingNew` | `"NEW"` |
| `trendingAnalyzePrompt` | `"Analyze the GitHub repo {{name}}: project purpose, architecture, tech stack, and highlights. Repo URL: {{url}}"` |

同样删除 `promptStructure*`、`promptBug*`、`promptPlan*`、`promptDesign*`、`emptyHeroScanProject`、`emptyHeroRecommended`。

---

## 不需要改动的文件

| 文件 | 原因 |
|------|------|
| `MessageTimeline.tsx` | 导入 `TaskSuggestionHero` 的名字和 `onSelectSuggestion` props 不变 |
| `workspace-suggestions.ts` | 保留不删，不影响新功能 |
| `chat-store.ts` | 不需要新的 store 状态，数据在组件内管理 |
| Python 后端 | 不涉及 |

---

## HTML 解析策略详细说明

TrendShift 页面 HTML 中，仓库列表在 `<main>` 标签内，每个仓库的核心标识是：

```html
<a href="/repositories/数字">owner/repo</a>
```

### 解析伪代码

```
1. fetch HTML
2. 提取 <main>...</main> 内容
3. 用正则找所有 /<a[^>]+href="\/repositories\/\d+"[^>]*>([^<]+)<\/a>/g
   每个匹配的 group(1) 就是 "owner/repo"
4. 对每个匹配位置，向后截取到下一个 /repositories/ 链接之前的 HTML 作为"块"
5. 在每个块内：
   - 描述：最长的无标签纯文本段
   - stars / gained：按顺序匹配 [\d,.]+k? 格式的独立数字
   - topics：所有 href="/topics/" 链接的文本
   - isNew：是否含 "NEW" 文本
6. 过滤掉 name 不含 "/" 的（排除广告链接等噪音）
7. 取前 20 条
```

### 容错

- 某些字段可能提取失败 → description 默认空字符串，stars/gained 默认 `"—"`，topics 默认空数组
- HTML 结构变化导致解析数 < 5 条时 → 仍然返回已解析的数据
- 解析数为 0 → 返回 `{ ok: false, error: 'parse_empty' }`

---

## 缓存策略

```
cache = Map<'daily'|'weekly'|'monthly', { result, fetchedAt }>

getTrendingRepos(period):
  if cache.has(period) && now - cache.get(period).fetchedAt < 600_000:
    return cache.get(period).result
  else:
    result = await fetchAndParse(period)
    if result.ok:
      cache.set(period, { result, fetchedAt: now })
    return result
```

只缓存成功结果。失败结果不缓存，下次请求会重新 fetch。

---

## 验证 Checklist

1. `npm run dev` 启动 workbench
2. 新建 thread → 空状态应显示 Trending 面板（Flame 图标 + "GitHub Trending"）
3. 默认展示日榜数据
4. 点击「本周」/「本月」 tab → 数据刷新，显示 loading → 列表
5. 点击仓库卡片 → composer 输入框填入分析 prompt
6. hover 仓库卡片 → 右侧出现外链图标，点击 → 系统浏览器打开 GitHub
7. 断网测试 → 显示错误文本 + 重试按钮
8. 点击重试 → 重新请求
9. 10 分钟内重复切换 tab → 无网络请求（命中缓存）
10. 切换语言 → 面板文案切换 en/zh
