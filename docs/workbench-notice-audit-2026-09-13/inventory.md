# Workbench 提示与异常入口索引

这是按源码模式生成的定位索引，不等同于每条命中都是告警或已确认问题。含 catch 的静默路径用于审核遗漏反馈；测试文件不计入。

共 82 个文件、699 个匹配行。

## packages/workbench/src/main/deepseek-process.ts

- [L434](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/deepseek-process.ts:434)：`const onError = (error: Error): void => {`

## packages/workbench/src/main/feishu-register-service.ts

- [L31](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/feishu-register-service.ts:31)：`function registerErrorMessage(error: unknown): string {`

## packages/workbench/src/main/index.ts

- [L186](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:186)：`const notification = new Notification({`
- [L282](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:282)：`const notification = new Notification({`
- [L306](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:306)：`function runtimeFailure(error: string, message: string, status = 0) {`
- [L329](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:329)：`function runtimeJsonError(error: string, message: string): Error {`
- [L348](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:348)：`return { ...(topLevel ? { error: topLevel } : {}), message }`
- [L356](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:356)：`| { ok: false; error: string; message: string }`
- [L375](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:375)：`error: 'runtime_auth_required',`
- [L381](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:381)：`error: info.error ?? 'runtime_request_failed',`
- [L387](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:387)：`error: 'fetch_failed',`
- [L472](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:472)：`.catch(() => undefined)`
- [L479](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:479)：`.catch((error: unknown) => {`
- [L519](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:519)：`.catch((error) => {`
- [L736](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:736)：`dialog.showErrorBox(`
- [L750](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:750)：`void loadRenderer().catch((error) => {`
- [L753](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:753)：`dialog.showErrorBox('DeepSeek Workbench failed to load UI', message)`
- [L760](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:760)：`dialog.showErrorBox(`
- [L1173](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:1173)：`error: 'missing_api_key',`
- [L1185](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:1185)：`error: 'spawn_failed',`
- [L1282](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:1282)：`})().catch((e) => {`
- [L1309](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:1309)：`void ensureRuntime(initial).catch((error) => {`
- [L1316](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:1316)：`void pruneOnStartup().catch((err) => {`
- [L1342](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:1342)：`}).catch((error) => {`
- [L1345](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/index.ts:1345)：`dialog.showErrorBox('DeepSeek GUI failed to start', message)`

## packages/workbench/src/main/ipc/register-app-ipc-handlers.ts

- [L250](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:250)：`const entries = await readdir(current.path, { withFileTypes: true }).catch(() => [])`
- [L661](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:661)：`const entries = await readdir(target, { withFileTypes: true }).catch((error) => {`
- [L680](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:680)：`.catch(() => false)`
- [L712](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:712)：`.catch(() => false)`
- [L769](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:769)：`const pluginStat = await stat(pluginPath).catch(() => null)`
- [L777](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:777)：`const entries = await readdir(rulesDir, { withFileTypes: true }).catch((error) => {`
- [L870](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:870)：`const md = await readFile(join(skillContentDir, 'SKILL.md'), 'utf8').catch(() => '')`
- [L885](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:885)：`.catch(() => false)`
- [L889](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:889)：`.catch(() => false)`
- [L907](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:907)：`await rm(zipPath, { force: true }).catch(() => undefined)`
- [L908](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/ipc/register-app-ipc-handlers.ts:908)：`await rm(extractDir, { recursive: true, force: true }).catch(() => undefined)`

## packages/workbench/src/main/services/git-service.ts

- [L63](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:63)：`function gitFailure(error: unknown): GitBranchesResult {`
- [L105](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:105)：`function gitWorkingChangesFailure(error: unknown): GitWorkingChangesResult {`
- [L382](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:382)：`function isDirtyWorktreeError(error: unknown): boolean {`
- [L815](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:815)：`function gitCommitFailure(error: unknown): GitCommitResult {`
- [L842](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:842)：`function gitPathActionFailure(error: unknown): GitPathActionResult {`
- [L915](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:915)：`function gitPushFailure(error: unknown): GitPushResult {`
- [L933](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:933)：`function gitPullFailure(error: unknown): GitPullResult {`
- [L958](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:958)：`function gitSyncFailure(error: unknown): GitSyncResult {`
- [L1315](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:1315)：`function gitMessageSuggestionFailure(error: unknown): GitCommitMessageSuggestionResult {`
- [L1400](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:1400)：`function gitLogFailure(error: unknown): GitLogResult {`
- [L1458](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/git-service.ts:1458)：`function gitHubRepositoryFailure(error: unknown): GitHubRepositoryResult {`

## packages/workbench/src/main/services/modelscope-marketplace.ts

- [L297](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/modelscope-marketplace.ts:297)：`return { ok: false, error: error instanceof Error ? error.message : String(error) }`

## packages/workbench/src/main/services/trending-repos.ts

- [L207](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/trending-repos.ts:207)：`return { ok: false, error: 'TrendShift returned HTTP ${response.status}.' }`
- [L212](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/trending-repos.ts:212)：`return { ok: false, error: 'TrendShift page did not contain repositories.' }`
- [L219](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/trending-repos.ts:219)：`return { ok: false, error: error instanceof Error ? error.message : String(error) }`

## packages/workbench/src/main/services/usage-ledger-lock.ts

- [L39](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/usage-ledger-lock.ts:39)：`await unlink(lockPath).catch(() => {})`

## packages/workbench/src/main/services/workspace-service.ts

- [L515](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/services/workspace-service.ts:515)：`await unlink(tmpPng).catch(() => {})`

## packages/workbench/src/main/settings-store.ts

- [L306](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/main/settings-store.ts:306)：`function isErrnoException(error: unknown): error is NodeJS.ErrnoException {`

## packages/workbench/src/renderer/src/AppShell.tsx

- [L24](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/AppShell.tsx:24)：`/** Long enough to notice cursor attraction before the veil lifts. */`
- [L81](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/AppShell.tsx:81)：`void window.dsGui.getStartupPhase().then(setStartupPhase).catch(() => undefined)`

## packages/workbench/src/renderer/src/agent/deepseek-runtime.ts

- [L536](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:536)：`...(errorCode ? { error: errorCode } : {}),`
- [L548](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:548)：`? JSON.stringify({ error: info.error, message: info.message })`
- [L731](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:731)：`error: typeof msg.error === 'string' ? msg.error : null,`
- [L810](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:810)：`error: 'runtime_auth_required',`
- [L1330](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:1330)：`error: 'runtime_request_user_input_unsupported',`
- [L1350](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:1350)：`error: 'runtime_request_user_input_unsupported',`
- [L1633](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:1633)：`const outcome = await new Promise<{ type: 'end' } | { type: 'error'; error: Error; status?: number }>(`
- [L1670](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:1670)：`const finish = (result: { type: 'end' } | { type: 'error'; error: Error; status?: number }): void => {`
- [L2126](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:2126)：`await this.submitApprovalDecision(approvalId, 'allow').catch(() => {`
- [L2132](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:2132)：`await this.submitApprovalDecision(approvalId, 'deny').catch(() => {`
- [L2139](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:2139)：`.catch(() => {`
- [L2157](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:2157)：`await this.submitElevationDecision(elevationId, 'allow').catch(() => {`
- [L2163](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:2163)：`await this.submitElevationDecision(elevationId, 'deny').catch(() => {`
- [L2170](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:2170)：`.catch(() => {`
- [L2196](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:2196)：`error: new Error(errMessage),`
- [L2222](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/agent/deepseek-runtime.ts:2222)：`error: e instanceof Error ? e : new Error(String(e))`

## packages/workbench/src/renderer/src/components/ChangeInspector.tsx

- [L534](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:534)：`<div role="status" className={'ds-pop origin-top-right absolute right-0 top-[calc(100%+6px)] z-[80] flex w-max max-w-72 items-start gap-1.5 rounded-lg border border-ds-border bg-ds-elevated px-2.5 py-2 text-[13.5px] leading-4 shadow-lg ${feedback.kind === 'success' ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-200'}'}>`
- [L1488](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1488)：`<div role="alert" className="border-b border-ds-border-muted px-2 py-1.5 text-[13.5px] text-amber-700 dark:text-amber-200">`

## packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx

- [L88](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:88)：`// dom-ready yet (e.g. switching to a newly opened preview tab). .catch()`
- [L99](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:99)：`void (pending as Promise<unknown>).catch(() => {`
- [L185](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:185)：`void pending.catch(() => {`
- [L246](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:246)：`.catch(() => {`
- [L350](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:350)：`const [loadError, setLoadError] = useState<string | null>(null)`
- [L425](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:425)：`void (pending as Promise<unknown>).catch(() => {`
- [L502](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:502)：`setLoadError(null)`
- [L516](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:516)：`if (nextLoading) setLoadError(null)`
- [L530](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:530)：`setLoadError(description || t('browserLoadFailed'))`
- [L578](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:578)：`setLoadError(null)`
- [L603](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:603)：`setLoadError(null)`
- [L650](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:650)：`setLoadError(externalError)`
- [L715](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:715)：`setLoadError(null)`
- [L720](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:720)：`setLoadError(null)`
- [L725](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:725)：`setLoadError(t('browserLoadFailed'))`
- [L744](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:744)：`setLoadError(null)`
- [L757](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:757)：`setLoadError(null)`
- [L772](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:772)：`setLoadError(t('browserInvalidUrl'))`
- [L778](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:778)：`setLoadError(null)`
- [L804](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:804)：`setLoadError(null)`
- [L828](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:828)：`setLoadError(null)`
- [L832](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:832)：`setLoadError(null)`
- [L968](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:968)：`setLoadError(null)`
- [L988](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:988)：`setLoadError(null)`
- [L1190](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1190)：`className={'ds-dev-browser__screenshot-notice ds-dev-browser__screenshot-notice--${screenshotNoticeTone}'}`
- [L1191](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1191)：`role="status"`
- [L1192](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1192)：`aria-live="polite"`
- [L1283](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1283)：`setLoadError(null)`

## packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx

- [L56](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:56)：`const [error, setError] = useState<string | null>(null)`
- [L107](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:107)：`setError(null)`
- [L136](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:136)：`setError(t('firstRunApiKeyValidation'))`
- [L140](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:140)：`setError(null)`
- [L164](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:164)：`setError(e instanceof Error ? e.message : String(e))`

## packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx

- [L117](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:117)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L124](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:124)：`setNotice(null)`
- [L137](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:137)：`setNotice({`
- [L170](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:170)：`setNotice(null)`
- [L173](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:173)：`setNotice({ tone: 'error', message: tSettings('portInvalid') })`
- [L199](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:199)：`setNotice({ tone: 'success', message: t('runtimeDiagnosticsSaved') })`
- [L203](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:203)：`setNotice({`
- [L217](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:217)：`setNotice({ tone: 'info', message: t('runtimeDiagnosticsRetrying') })`
- [L230](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:230)：`setNotice({ tone: 'error', message: result.message ?? t('runtimeDiagnosticsOpenDirFailed') })`
- [L305](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:305)：`{notice ? (`
- [L308](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:308)：`notice.tone === 'error'`
- [L310](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:310)：`: notice.tone === 'success'`
- [L315](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:315)：`{notice.message}`

## packages/workbench/src/renderer/src/components/SessionQueries.tsx

- [L22](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:22)：`const [notice, setNotice] = useState('')`
- [L52](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:52)：`setNotice('')`
- [L60](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:60)：`if (!notice) return`
- [L61](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:61)：`const timer = setTimeout(() => { setNotice(''); setCopiedId(null) }, 1600)`
- [L63](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:63)：`}, [notice, copiedId])`
- [L86](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:86)：`setNotice(t('copySuccess'))`
- [L88](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:88)：`setNotice(t('copyFailed'))`
- [L100](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:100)：`title={notice || t('sessionQueriesHint')}`
- [L113](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:113)：`{notice ? <span className="shrink-0 text-[11px] text-ds-muted">{notice}</span> :`
- [L116](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:116)：`<span role="status" className="sr-only">{notice}</span>`

## packages/workbench/src/renderer/src/components/SettingsView.tsx

- [L174](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:174)：`const [loadError, setLoadError] = useState<string | null>(null)`
- [L177](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:177)：`const [saveError, setSaveError] = useState<string | null>(null)`
- [L333](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:333)：`setLoadError('PRELOAD_BRIDGE')`
- [L341](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:341)：`.catch((e: unknown) => {`
- [L342](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:342)：`if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e))`
- [L420](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:420)：`setSaveError(null)`
- [L441](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:441)：`setSaveError(e instanceof Error ? e.message : String(e))`
- [L453](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:453)：`setSaveError(null)`
- [L1000](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1000)：`<InlineNoticeView notice={hooksNotice} />`
- [L1070](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1070)：`notice`
- [L1072](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1072)：`notice: InlineNotice`
- [L1075](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1075)：`notice.tone === 'error'`
- [L1077](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1077)：`: notice.tone === 'success'`
- [L1083](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1083)：`{notice.message}`
- [L1276](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1276)：`.catch(() => {`
- [L1345](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1345)：`error: string | null`

## packages/workbench/src/renderer/src/components/Workbench.tsx

- [L277](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:277)：`setError,`
- [L306](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:306)：`error: s.error,`
- [L314](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:314)：`setError: s.setError,`
- [L615](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:615)：`if (result === 'none') setError('${t('fileReferenceOpenFailed')}: ${path}')`
- [L618](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:618)：`[activeWorkspaceRoot, layoutMode, openInAppEditorSurface, setError, t, threadFilesystemRoot]`
- [L623](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:623)：`setError(t('ideNeedsWorkspace'))`
- [L631](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:631)：`}, [activeWorkspaceRoot, setError, t])`
- [L808](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:808)：`if (result === 'none') setError('${t('fileReferenceOpenFailed')}: ${path}')`
- [L866](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:866)：`setError,`

## packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx

- [L133](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:133)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L207](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:207)：`loadChannelDeliveryState().catch(() => null)`
- [L212](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:212)：`setNotice({ tone: 'success', message: t('listReloaded') })`
- [L215](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:215)：`setNotice({`
- [L232](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:232)：`setNotice({`
- [L272](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:272)：`setNotice({ tone: 'success', message: t('listReloaded') })`
- [L293](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:293)：`.catch(() => {`
- [L311](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:311)：`if (!notice) return`
- [L312](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:312)：`const timer = window.setTimeout(() => setNotice(null), 10000)`
- [L314](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:314)：`}, [notice])`
- [L320](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:320)：`if (action === 'delete' && !window.confirm(t('automationDeleteConfirm', { name: row.name })))`
- [L323](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:323)：`setNotice(null)`
- [L327](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:327)：`setNotice({ tone: 'success', message: t('automationStartedMsg', { name: row.name }) })`
- [L341](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:341)：`setNotice({`
- [L364](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:364)：`setNotice(null)`
- [L386](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:386)：`setNotice({`
- [L444](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:444)：`role={notice ? 'status' : undefined}`
- [L446](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:446)：`notice?.tone === 'error'`
- [L448](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:448)：`: notice`
- [L454](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:454)：`<span>{notice ? notice.message : t('automationWakeHint')}</span>`

## packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx

- [L56](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:56)：`function errorKey(error: unknown): string {`
- [L109](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:109)：`const [notice, setNotice] = useState<{ tone: 'success' | 'error'; message: string } | null>(null)`
- [L168](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:168)：`setNotice({ tone: 'error', message: t('automationDeliveryFeishuNotConfigured') })`
- [L172](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:172)：`setNotice({ tone: 'error', message: t('automationDeliveryWecomNotConfigured') })`
- [L176](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:176)：`setNotice({ tone: 'error', message: t('automationDeliveryEmailNotConfigured') })`
- [L180](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:180)：`setNotice(null)`
- [L210](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:210)：`setNotice({ tone: 'success', message: t('automationCreateSuccess', { name: record.name }) })`
- [L213](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:213)：`setNotice({`
- [L225](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:225)：`setNotice(null)`
- [L228](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:228)：`setNotice({`
- [L233](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:233)：`setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })`
- [L518](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:518)：`{notice ? (`
- [L521](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:521)：`notice.tone === 'error'`
- [L526](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:526)：`{notice.message}`

## packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx

- [L85](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:85)：`const [error, setError] = useState('')`
- [L123](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:123)：`if (!cancelled) setError(err instanceof Error ? err.message : String(err))`

## packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx

- [L62](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:62)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L80](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:80)：`setNotice({`
- [L110](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:110)：`setNotice(null)`
- [L115](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:115)：`setNotice({ tone: 'error', message: t('channelEmailSecureStorageUnavailable') })`
- [L122](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:122)：`setNotice({ tone: 'error', message: t('channelEmailAuthCodeRequired') })`
- [L134](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:134)：`setNotice({ tone: 'success', message: t('channelEmailSaved') })`
- [L136](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:136)：`setNotice({`
- [L147](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:147)：`setNotice({ tone: 'error', message: t('channelEmailSaveBeforeTest') })`
- [L151](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:151)：`setNotice({ tone: 'info', message: t('channelEmailNeedRuntime') })`
- [L155](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:155)：`setNotice(null)`
- [L174](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:174)：`setNotice({ tone: 'error', message })`
- [L177](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:177)：`setNotice({ tone: 'success', message: t('channelEmailTestOk') })`
- [L179](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:179)：`setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })`
- [L198](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/EmailChannelSetup.tsx:198)：`{notice ? <div className={channelNoticeClass(notice.tone)}>{notice.message}</div> : null}`

## packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx

- [L34](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:34)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L45](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:45)：`setNotice({`
- [L74](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:74)：`setNotice({ tone: 'info', message: t('channelFeishuNeedRuntimeForTest') })`
- [L78](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:78)：`setNotice(null)`
- [L96](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:96)：`setNotice({ tone: 'error', message })`
- [L99](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:99)：`setNotice({ tone: 'success', message: t('channelFeishuTestOk') })`
- [L101](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:101)：`setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })`
- [L109](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:109)：`setNotice({ tone: 'error', message: t('channelFeishuScanUnavailable') })`
- [L113](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:113)：`setNotice(null)`
- [L119](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:119)：`setNotice({ tone: 'error', message: result.message })`
- [L131](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:131)：`setNotice({ tone: 'success', message: t('channelFeishuScanSuccess') })`
- [L137](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:137)：`setNotice({`
- [L152](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:152)：`{notice ? <div className={channelNoticeClass(notice.tone)}>{notice.message}</div> : null}`

## packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx

- [L32](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:32)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L45](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:45)：`setNotice({`
- [L59](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:59)：`setNotice({ tone: 'error', message: t('channelWecomInvalidWebhook') })`
- [L63](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:63)：`setNotice(null)`
- [L69](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:69)：`setNotice({ tone: 'success', message: t('channelWecomSaved') })`
- [L71](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:71)：`setNotice({`
- [L82](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:82)：`setNotice({ tone: 'error', message: t('channelWecomSaveBeforeTest') })`
- [L86](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:86)：`setNotice({ tone: 'info', message: t('channelWecomNeedRuntime') })`
- [L90](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:90)：`setNotice(null)`
- [L105](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:105)：`setNotice({ tone: 'error', message })`
- [L108](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:108)：`setNotice({ tone: 'success', message: t('channelWecomTestOk') })`
- [L110](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:110)：`setNotice({ tone: 'error', message: err instanceof Error ? err.message : String(err) })`
- [L118](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:118)：`{notice ? <div className={channelNoticeClass(notice.tone)}>{notice.message}</div> : null}`

## packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx

- [L83](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:83)：`function NoticeView({ notice }: { notice: Notice | null }): ReactElement | null {`
- [L84](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:84)：`if (!notice) return null`
- [L86](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:86)：`notice.tone === 'error'`
- [L88](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:88)：`: notice.tone === 'success'`
- [L91](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:91)：`return <div className={'rounded-xl border px-3 py-2 text-[11px] ${tone}'}>{notice.text}</div>`
- [L255](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:255)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L274](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:274)：`setNotice({ tone: 'success', text: '${id} ${enabled ? 'enabled' : 'disabled'}.' })`
- [L276](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:276)：`setNotice({ tone: 'error', text: error instanceof Error ? error.message : String(error) })`
- [L289](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:289)：`<NoticeView notice={notice} />`
- [L390](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:390)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L402](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:402)：`if (!result.ok) setNotice({ tone: 'error', text: result.message ?? 'Could not open hooks folder.' })`
- [L404](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:404)：`<NoticeView notice={notice} />`

## packages/workbench/src/renderer/src/components/chat/ComposerStage.tsx

- [L17](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerStage.tsx:17)：`import { ComposerNoticeToast } from './composer-notice'`
- [L22](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerStage.tsx:22)：`/** One-shot notice from parent (e.g. preview pick limit); keyed by nonce. */`
- [L87](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerStage.tsx:87)：`<ComposerNoticeToast notice={composerNotice} />`

## packages/workbench/src/renderer/src/components/chat/FileChip.tsx

- [L56](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FileChip.tsx:56)：`const setError = useChatStore((state) => state.setError)`
- [L110](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FileChip.tsx:110)：`if (!result.ok) setError('${t('fileReferenceOpenFailed')}: ${result.message}')`

## packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx

- [L215](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:215)：`onNoticeChange?: (notice: Notice | null) => void`
- [L864](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:864)：`.catch(() => undefined)`
- [L1043](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1043)：`.catch(() => undefined)`
- [L1137](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1137)：`.catch(() => {`
- [L1146](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1146)：`.catch(() => setAsrConfigured(false))`
- [L2315](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2315)：`? t('composerConnectorFailedHint', { error: errorSuffix })`
- [L2329](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2329)：`error: errorSuffix`

## packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx

- [L70](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:70)：`const [error, setError] = useState<string | null>(null)`
- [L72](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:72)：`const [notice, setNotice] = useState<string | null>(null)`
- [L94](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:94)：`setError(null)`
- [L95](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:95)：`setNotice(null)`
- [L102](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:102)：`setError(null)`
- [L108](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:108)：`setError(null)`
- [L111](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:111)：`setError(result.ok ? null : gitErrorMessage(result))`
- [L214](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:214)：`setError(null)`
- [L215](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:215)：`setNotice(null)`
- [L222](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:222)：`setNotice(t('gitDirtySwitchBlocked', { branch }))`
- [L227](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:227)：`setError(gitErrorMessage(next))`
- [L233](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:233)：`setError(e instanceof Error ? e.message : String(e))`
- [L242](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:242)：`setError(null)`
- [L246](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:246)：`setNotice(t('gitStashPopConflict'))`
- [L253](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:253)：`setNotice(null)`
- [L255](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:255)：`setError(gitErrorMessage(next))`
- [L260](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:260)：`setNotice(null)`
- [L263](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:263)：`setNotice(null)`
- [L265](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:265)：`setError(e instanceof Error ? e.message : String(e))`
- [L415](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:415)：`{typeof document !== 'undefined' && (error || notice)`
- [L419](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:419)：`role="alert"`
- [L420](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:420)：`aria-live="assertive"`
- [L430](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:430)：`{error ?? notice}`
- [L435](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:435)：`setError(null)`
- [L436](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:436)：`setNotice(null)`

## packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx

- [L78](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:78)：`const [error, setError] = useState<string | null>(null)`
- [L119](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:119)：`setError(null)`
- [L243](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:243)：`setError(t('operationDockCommitNoChanges'))`
- [L247](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:247)：`setError(t('operationDockCommitSelectFiles'))`
- [L251](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:251)：`setError(t('operationDockCommitUnavailable'))`
- [L256](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:256)：`setError(null)`
- [L260](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:260)：`setError(result.message)`
- [L265](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:265)：`setError(suggestError instanceof Error ? suggestError.message : String(suggestError))`
- [L274](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:274)：`setError(t('operationDockCommitEmptyMessage'))`
- [L278](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:278)：`setError(t('operationDockCommitSelectFiles'))`
- [L282](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:282)：`setError(t('operationDockCommitUnavailable'))`
- [L287](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:287)：`setError(null)`
- [L291](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:291)：`setError(result.message)`
- [L299](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:299)：`setError(commitError instanceof Error ? commitError.message : String(commitError))`
- [L307](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:307)：`setError(null)`
- [L509](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:509)：`if (error) setError(null)`

## packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx

- [L239](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:239)：`aria-live="polite"`

## packages/workbench/src/renderer/src/components/chat/GoalStrip.tsx

- [L66](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GoalStrip.tsx:66)：`if (!window.confirm(t('goalCancelConfirm'))) return`

## packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx

- [L147](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:147)：`role="status"`

## packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx

- [L215](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx:215)：`if (!window.confirm(confirmMessage)) return`
- [L246](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx:246)：`const ok = window.confirm(t('sidebarChatsDeleteSelectedConfirm', { count: targets.length }))`
- [L254](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx:254)：`const ok = window.confirm(t('sidebarChatsClearAllConfirm', { count: chatsThreads.length }))`

## packages/workbench/src/renderer/src/components/chat/SidebarPinnedSection.tsx

- [L70](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarPinnedSection.tsx:70)：`if (!window.confirm(confirmMessage)) return`

## packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx

- [L628](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:628)：`const ok = window.confirm(`
- [L637](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:637)：`const ok = window.confirm(`
- [L840](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:840)：`if (!window.confirm(confirmMessage)) return`
- [L870](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:870)：`if (!window.confirm(confirmMessage)) return`
- [L877](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:877)：`if (!window.confirm(confirmMessage)) return`
- [L1011](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:1011)：`.catch(() => {`

## packages/workbench/src/renderer/src/components/chat/StreamdownMermaidBlock.tsx

- [L150](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StreamdownMermaidBlock.tsx:150)：`onErrorChange?: (error: string | null) => void`
- [L154](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StreamdownMermaidBlock.tsx:154)：`const [error, setError] = useState<string | null>(null)`
- [L166](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StreamdownMermaidBlock.tsx:166)：`setError(null)`
- [L179](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StreamdownMermaidBlock.tsx:179)：`setError(null)`
- [L181](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StreamdownMermaidBlock.tsx:181)：`.catch((err: unknown) => {`
- [L183](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StreamdownMermaidBlock.tsx:183)：`setError(err instanceof Error ? err.message : String(err))`
- [L190](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StreamdownMermaidBlock.tsx:190)：`<div className="ds-mermaid-fallback" role="alert">`

## packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx

- [L167](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:167)：`const [error, setError] = useState<string | null>(null)`
- [L173](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:173)：`setError(null)`
- [L180](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:180)：`setError(null)`
- [L183](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:183)：`setError(result.error)`
- [L186](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:186)：`.catch((caught: unknown) => {`
- [L189](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:189)：`setError(caught instanceof Error ? caught.message : String(caught))`

## packages/workbench/src/renderer/src/components/chat/composer-notice.tsx

- [L4](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/composer-notice.tsx:4)：`export function ComposerNoticeToast({ notice }: { notice: Notice }): ReactElement {`
- [L6](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/composer-notice.tsx:6)：`notice.tone === 'error'`
- [L8](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/composer-notice.tsx:8)：`: notice.tone === 'success'`
- [L13](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/composer-notice.tsx:13)：`role="status"`
- [L16](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/composer-notice.tsx:16)：`{notice.message}`

## packages/workbench/src/renderer/src/components/chat/tool/lazy-full-output.tsx

- [L36](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/lazy-full-output.tsx:36)：`.catch(() => setState({ loading: false, detail: '' }))`

## packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx

- [L40](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:40)：`const [error, setError] = useState<string | null>(null)`
- [L64](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:64)：`setError(null)`
- [L97](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:97)：`setError(t('mcpDialogNameRequired'))`
- [L101](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:101)：`setError(t('mcpDialogExists', { name: id }))`
- [L109](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:109)：`setError(t('mcpDialogUrlRequired'))`
- [L116](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:116)：`setError(t('mcpDialogCommandRequired'))`
- [L122](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:122)：`setError(null)`
- [L127](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:127)：`setError(e instanceof Error ? e.message : String(e))`

## packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx

- [L47](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:47)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L48](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:48)：`useNoticeAutoDismiss(notice, setNotice)`
- [L85](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:85)：`void readMcpConfig().catch((e) => setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) }))`
- [L118](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:118)：`void reloadMcpWithRuntime(readMcpConfig).catch(() => undefined)`
- [L131](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:131)：`setNotice({ tone: 'info', message: tSettings('mcpReloadDiskOnly') })`
- [L136](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:136)：`setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })`
- [L167](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:167)：`error: runtime?.error ?? null`
- [L187](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:187)：`setNotice({ tone: 'info', message: t('pluginAlreadyAdded') })`
- [L196](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:196)：`setNotice({ tone: 'success', message: t('pluginMcpAdded', { path: result.path }) })`
- [L199](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:199)：`void reloadMcpWithRuntime(readMcpConfig).catch(() => undefined)`
- [L207](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:207)：`if (!window.confirm(t('connectorDeleteConfirm', { name: connector.name }))) return`
- [L209](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:209)：`setNotice(null)`
- [L221](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:221)：`setNotice({ tone: 'success', message: t('connectorDeleted', { name: connector.name, path: result.path }) })`
- [L222](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:222)：`void reloadMcpWithRuntime(readMcpConfig).catch(() => undefined)`
- [L225](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:225)：`setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })`
- [L234](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:234)：`setNotice(null)`
- [L241](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:241)：`void reloadMcpWithRuntime(readMcpConfig).catch(() => undefined)`
- [L244](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:244)：`setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })`
- [L303](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:303)：`{notice ? <NoticeView notice={notice} /> : null}`

## packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx

- [L21](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:21)：`const [error, setError] = useState<string | null>(null)`
- [L39](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:39)：`setError(null)`
- [L50](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:50)：`setError(t('mcpImportParseError'))`
- [L55](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:55)：`setError(t('mcpImportEmpty'))`
- [L59](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:59)：`setError(null)`
- [L78](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:78)：`setError(t('mcpImportResult', { added, skipped }))`

## packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx

- [L26](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:26)：`const [error, setError] = useState<string | null>(null)`
- [L45](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:45)：`setError(null)`
- [L58](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:58)：`setError(result.message)`
- [L81](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:81)：`if (window.confirm(t('skillInstallConflict', { name: result.message ?? file.name }))) {`
- [L86](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:86)：`setError(result.message ?? t('skillInstallBadType'))`
- [L91](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:91)：`setError(null)`
- [L99](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:99)：`setError(t('skillInstallBadType'))`
- [L102](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:102)：`setError(e instanceof Error ? e.message : String(e))`

## packages/workbench/src/renderer/src/components/extensions/InstalledConnectorsPanel.tsx

- [L166](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledConnectorsPanel.tsx:166)：`? t('connectorStatusFailed', { error: errorSuffix })`

## packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx

- [L449](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:449)：`.catch((error) => {`

## packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx

- [L55](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:55)：`/** Renderer-side install; returns a notice to show. 'null' = installed silently. */`
- [L74](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:74)：`const [error, setError] = useState<string | null>(null)`
- [L76](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:76)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L83](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:83)：`setError(null)`
- [L98](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:98)：`setError(result.error)`
- [L101](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:101)：`setError(e instanceof Error ? e.message : String(e))`
- [L153](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:153)：`setNotice(null)`
- [L156](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:156)：`if (outcome) setNotice(outcome)`
- [L158](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:158)：`setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })`
- [L184](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:184)：`{stale ? <NoticeView notice={{ tone: 'info', message: t('marketplaceStale') }} /> : null}`
- [L185](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:185)：`{notice ? <NoticeView notice={notice} /> : null}`
- [L193](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:193)：`<NoticeView notice={{ tone: 'error', message: t('marketplaceLoadFailed', { error }) }} />`

## packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx

- [L33](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:33)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L34](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:34)：`useNoticeAutoDismiss(notice, setNotice)`
- [L51](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:51)：`setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })`
- [L58](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:58)：`setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })`
- [L107](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:107)：`.catch(() => {`
- [L122](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:122)：`setNotice(null)`
- [L131](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:131)：`setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })`
- [L135](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:135)：`setNotice({`
- [L141](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:141)：`setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })`
- [L155](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:155)：`const ok = window.confirm(t('pluginSysTrustConfirm', { name: plugin.name }) + perms)`
- [L176](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:176)：`const ok = window.confirm(t('pluginSysRemoveConfirm', { name: plugin.name }))`
- [L186](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:186)：`setNotice(null)`
- [L194](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:194)：`setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })`
- [L198](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:198)：`setNotice({`
- [L205](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:205)：`setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })`
- [L227](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:227)：`setNotice(null)`
- [L235](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:235)：`setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })`
- [L239](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:239)：`setNotice({ tone: 'success', message: parsed.message ?? t('pluginSysDone') })`
- [L243](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:243)：`setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })`
- [L254](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:254)：`setNotice(null)`
- [L258](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:258)：`setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })`
- [L262](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:262)：`setNotice({ tone: 'success', message: parsed.message ?? t('pluginSysDone') })`
- [L265](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:265)：`setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })`
- [L286](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:286)：`const ok = window.confirm(t('pluginMpRemoveConfirm', { name }))`
- [L343](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:343)：`{notice ? <NoticeView notice={notice} /> : null}`

## packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx

- [L20](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:20)：`const [error, setError] = useState<string | null>(null)`
- [L28](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:28)：`setError(null)`
- [L37](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:37)：`setError(result.message ?? t('skillPreviewError'))`
- [L40](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:40)：`.catch((e) => {`
- [L41](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:41)：`if (!cancelled) setError(e instanceof Error ? e.message : String(e))`

## packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx

- [L33](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:33)：`const [notice, setNotice] = useState<Notice | null>(null)`
- [L34](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:34)：`useNoticeAutoDismiss(notice, setNotice)`
- [L125](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:125)：`if (!result.ok) setNotice({ tone: 'error', message: result.message ?? t('pluginActionFailed') })`
- [L135](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:135)：`? window.confirm(t('skillDeleteConfirmCopies', { name: skill.name, count: removable.length }))`
- [L136](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:136)：`: window.confirm(t('skillDeleteConfirm', { name: skill.name }))`
- [L139](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:139)：`setNotice(null)`
- [L150](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:150)：`setNotice({ tone: 'error', message: failed })`
- [L160](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:160)：`setNotice({ tone: 'success', message: t('skillDeleted', { name: skill.name }) })`
- [L162](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:162)：`setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })`
- [L178](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:178)：`setNotice({ tone: 'success', message: t('skillInstallSuccess', { path }) })`
- [L185](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillsView.tsx:185)：`{notice ? <NoticeView notice={notice} /> : null}`

## packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts

- [L16](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts:16)：`* Auto-dismiss a transient notice so success/error banners don't linger`
- [L19](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts:19)：`* success/info clear faster. A fresh notice restarts the timer; unmount`
- [L21](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts:21)：`* directly from a condition instead of going through setNotice.`
- [L24](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts:24)：`notice: Notice | null,`
- [L25](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts:25)：`setNotice: (value: Notice | null) => void`
- [L28](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts:28)：`if (!notice) return`
- [L29](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts:29)：`const ms = notice.tone === 'error' ? 5000 : 2000`
- [L30](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts:30)：`const timer = window.setTimeout(() => setNotice(null), ms)`
- [L32](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-shared.ts:32)：`}, [notice, setNotice])`

## packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx

- [L190](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx:190)：`export function NoticeView({ notice }: { notice: Notice }): ReactElement {`
- [L192](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx:192)：`notice.tone === 'error'`
- [L194](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx:194)：`: notice.tone === 'success'`
- [L198](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx:198)：`<div className={'mt-4 rounded-xl border px-3 py-2 text-[13px] leading-5 ${className}'}>{notice.message}</div>`

## packages/workbench/src/renderer/src/components/ide/IdeQuickOpenPalette.tsx

- [L35](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeQuickOpenPalette.tsx:35)：`const [error, setError] = useState<string | null>(null)`
- [L62](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeQuickOpenPalette.tsx:62)：`setError(null)`
- [L69](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeQuickOpenPalette.tsx:69)：`setError(t('ideWorkspaceSearchUnavailable'))`
- [L84](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeQuickOpenPalette.tsx:84)：`setError(result.message)`
- [L89](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeQuickOpenPalette.tsx:89)：`setError(null)`
- [L92](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeQuickOpenPalette.tsx:92)：`.catch((err: unknown) => {`
- [L96](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeQuickOpenPalette.tsx:96)：`setError(err instanceof Error ? err.message : String(err))`

## packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx

- [L29](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:29)：`const [error, setError] = useState<string | null>(null)`
- [L39](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:39)：`setError(null)`
- [L45](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:45)：`setError(t('ideWorkspaceSearchUnavailable'))`
- [L61](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:61)：`setError(result.message)`
- [L67](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:67)：`setError(null)`
- [L69](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:69)：`.catch((err: unknown) => {`
- [L74](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:74)：`setError(err instanceof Error ? err.message : String(err))`

## packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx

- [L78](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx:78)：`const [notice, setNotice] = useState<string | null>(null)`
- [L167](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx:167)：`setNotice(t('kanbanDoneDerivedHint'))`
- [L168](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx:168)：`window.setTimeout(() => setNotice(null), 2400)`
- [L172](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx:172)：`setNotice(t('kanbanStatusDerivedHint'))`
- [L173](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx:173)：`window.setTimeout(() => setNotice(null), 2400)`
- [L184](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx:184)：`{notice ? (`
- [L185](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx:185)：`<div className="px-8 pb-2 text-[12px] text-ds-muted">{notice}</div>`

## packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx

- [L101](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:101)：`const [notice, setNotice] = useState<string | null>(null)`
- [L234](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:234)：`setNotice(message)`
- [L235](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:235)：`window.setTimeout(() => setNotice(null), 2400)`
- [L407](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:407)：`if (!window.confirm(t('sidebarThreadDeleteConfirm', { title }))) break`
- [L465](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:465)：`{notice ? (`
- [L466](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:466)：`<div className="mt-3 shrink-0 px-8 text-[12px] text-ds-muted">{notice}</div>`

## packages/workbench/src/renderer/src/components/right-sidebar/RunPanel.tsx

- [L78](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/RunPanel.tsx:78)：`const result = isTask ? detail?.resultSummary || detail?.error : selected?.summary`
- [L85](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/RunPanel.tsx:85)：`const [error, setError] = useState<string | null>(null)`
- [L92](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/RunPanel.tsx:92)：`setError(null)`
- [L101](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/RunPanel.tsx:101)：`setError(err instanceof Error ? err.message : t('taskResumeFailed'))`
- [L136](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/RunPanel.tsx:136)：`<span className="ds-run-status" data-status={status} role="status" title={duration || undefined}>`
- [L163](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/RunPanel.tsx:163)：`{error || failed ? <p role="alert" className="ds-run-error">{error || t('runPanelLoadFailed')}</p> : null}`

## packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx

- [L143](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:143)：`<span aria-live="polite">`
- [L443](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:443)：`<span aria-live="polite">`

## packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx

- [L148](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:148)：`const [loadError, setLoadError] = useState<string | null>(null)`
- [L157](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:157)：`setLoadError(null)`
- [L161](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:161)：`setLoadError(t('archiveNeedRuntime'))`
- [L169](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:169)：`setLoadError(t('archiveLoadFailed'))`
- [L252](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:252)：`setLoadError(null)`
- [L260](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:260)：`setLoadError(message)`
- [L273](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:273)：`setLoadError(t('archiveActionFailed'))`
- [L280](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:280)：`const ok = window.confirm(t('archiveDeleteOneConfirm', { title: thread.title }))`
- [L284](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:284)：`setLoadError(t('archiveActionFailed'))`
- [L292](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:292)：`const ok = window.confirm(t('archiveDeleteAllConfirm', { count: group.threads.length }))`
- [L296](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:296)：`setLoadError(t('archiveActionFailed'))`
- [L300](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:300)：`setLoadError(null)`
- [L312](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:312)：`setLoadError(message)`
- [L322](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:322)：`const ok = window.confirm(t('archiveDeleteAllConfirm', { count: threads.length }))`
- [L326](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:326)：`setLoadError(null)`
- [L343](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ArchiveSettingsPanel.tsx:343)：`setLoadError(message)`

## packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx

- [L165](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:165)：`function InlineNoticeView({ notice }: { notice: InlineNotice }): ReactElement {`
- [L167](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:167)：`notice.tone === 'error'`
- [L169](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:169)：`: notice.tone === 'success'`
- [L174](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:174)：`{notice.message}`
- [L183](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:183)：`const [loadError, setLoadError] = useState<string | null>(null)`
- [L195](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:195)：`const [notice, setNotice] = useState<InlineNotice | null>(null)`
- [L217](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:217)：`setLoadError(null)`
- [L221](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:221)：`setLoadError(t('dataInventoryLoadFailed'))`
- [L228](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:228)：`setLoadError(t('dataInventoryLoadFailed'))`
- [L266](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:266)：`setNotice({ tone, message })`
- [L271](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:271)：`setNotice(null)`
- [L295](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:295)：`if (!window.confirm(t('dataCleanConfirm', { days: cleanAgeDays }))) return`
- [L297](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:297)：`setNotice(null)`
- [L321](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:321)：`if (!window.confirm(t('dataClearHistoryConfirm'))) return`
- [L322](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:322)：`if (!window.confirm(t('dataClearHistoryConfirm2'))) return`
- [L324](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:324)：`setNotice(null)`
- [L359](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:359)：`!window.confirm(t('dataExportSecretsConfirm'))`
- [L366](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:366)：`setNotice(null)`
- [L394](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:394)：`const mode = window.confirm(t('dataImportModeConfirm')) ? 'replace' : 'merge'`
- [L396](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:396)：`setNotice(null)`
- [L452](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:452)：`setNotice(null)`
- [L475](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:475)：`if (!window.confirm(t('dataDeleteAndExitConfirm'))) return`
- [L476](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:476)：`if (!window.confirm(t('dataDeleteAndExitConfirm2'))) return`
- [L517](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:517)：`{notice ? <InlineNoticeView notice={notice} /> : null}`

## packages/workbench/src/renderer/src/components/settings/ModelUsageHeroPanel.tsx

- [L21](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageHeroPanel.tsx:21)：`error: string | null`

## packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx

- [L25](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:25)：`error: string | null`

## packages/workbench/src/renderer/src/components/workspace-editor/ConfirmDialog.tsx

- [L16](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ConfirmDialog.tsx:16)：`* In-app replacement for window.confirm at high-stakes editor decisions`
- [L61](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ConfirmDialog.tsx:61)：`role="alertdialog"`

## packages/workbench/src/renderer/src/components/workspace-editor/HtmlDocumentPreview.tsx

- [L15](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/HtmlDocumentPreview.tsx:15)：`const [error, setError] = useState<string | null>(null)`
- [L22](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/HtmlDocumentPreview.tsx:22)：`setError(null)`
- [L27](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/HtmlDocumentPreview.tsx:27)：`setError('Preview bridge is unavailable.')`
- [L35](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/HtmlDocumentPreview.tsx:35)：`setError(result.message)`
- [L40](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/HtmlDocumentPreview.tsx:40)：`.catch((err: unknown) => {`
- [L42](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/HtmlDocumentPreview.tsx:42)：`setError(err instanceof Error ? err.message : String(err))`

## packages/workbench/src/renderer/src/components/workspace-editor/ImageDocumentPreview.tsx

- [L15](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ImageDocumentPreview.tsx:15)：`const [error, setError] = useState<string | null>(null)`
- [L22](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ImageDocumentPreview.tsx:22)：`setError(null)`
- [L27](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ImageDocumentPreview.tsx:27)：`setError('Preview bridge is unavailable.')`
- [L35](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ImageDocumentPreview.tsx:35)：`setError(result.message)`
- [L40](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ImageDocumentPreview.tsx:40)：`.catch((err: unknown) => {`
- [L42](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ImageDocumentPreview.tsx:42)：`setError(err instanceof Error ? err.message : String(err))`
- [L76](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ImageDocumentPreview.tsx:76)：`onError={() => setError('Failed to load image preview.')}`

## packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx

- [L23](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:23)：`error: string | null`
- [L42](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:42)：`return { entries: [], loading, loaded: false, error: null }`
- [L134](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:134)：`error: result.ok ? null : translateTreeError(result.message)`
- [L158](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:158)：`error: result.ok ? null : translateTreeError(result.message)`
- [L192](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:192)：`error: result.ok ? null : translateTreeError(result.message)`

## packages/workbench/src/renderer/src/hooks/use-persistent-usage.ts

- [L9](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-persistent-usage.ts:9)：`error: string | null`
- [L21](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-persistent-usage.ts:21)：`error: null`
- [L26](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-persistent-usage.ts:26)：`setState((current) => ({ ...current, loading: true, error: null }))`
- [L31](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-persistent-usage.ts:31)：`setState({ data, loading: false, loaded: true, error: null })`
- [L34](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-persistent-usage.ts:34)：`.catch((caught: unknown) => {`
- [L40](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-persistent-usage.ts:40)：`error: caught instanceof Error ? caught.message : String(caught)`

## packages/workbench/src/renderer/src/hooks/use-thread-tasks.ts

- [L25](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-thread-tasks.ts:25)：`error: string | null`
- [L72](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-thread-tasks.ts:72)：`error: typeof t.error === 'string' ? t.error : null,`
- [L91](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-thread-tasks.ts:91)：`error: typeof t.error === 'string' ? t.error : null,`

## packages/workbench/src/renderer/src/hooks/use-thread-usage.ts

- [L163](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/hooks/use-thread-usage.ts:163)：`.catch(() => {`

## packages/workbench/src/renderer/src/lib/composer-connectors.ts

- [L125](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/composer-connectors.ts:125)：`error: runtime?.error ?? null,`
- [L146](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/composer-connectors.ts:146)：`error: s.error ?? null,`

## packages/workbench/src/renderer/src/lib/format-runtime-error.ts

- [L23](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/format-runtime-error.ts:23)：`export function getRuntimeErrorCode(error: unknown): string | null {`
- [L36](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/format-runtime-error.ts:36)：`export function formatRuntimeError(error: unknown): string {`

## packages/workbench/src/renderer/src/lib/format-workspace-picker-error.ts

- [L3](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/format-workspace-picker-error.ts:3)：`export function formatWorkspacePickerError(error: unknown): string {`

## packages/workbench/src/renderer/src/lib/resume-task.ts

- [L28](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/resume-task.ts:28)：`if (!window.confirm(message)) throw new Error(i18n.t('taskResume.cancelled'))`
- [L34](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/resume-task.ts:34)：`if (raw.ok === false) throw new Error(typeof raw.error === 'string' ? raw.error : 'resume task failed')`

## packages/workbench/src/renderer/src/lib/workspace-editor-events.ts

- [L9](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/workspace-editor-events.ts:9)：`void window.dsGui.readWorkspaceFile({ path: trimmedPath, workspaceRoot: root }).catch(() => {`

## packages/workbench/src/renderer/src/store/chat-store-app-actions.ts

- [L46](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-app-actions.ts:46)：`| 'setError'`
- [L85](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-app-actions.ts:85)：`setError: (message) => set({ error: message }),`
- [L104](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-app-actions.ts:104)：`await existing.catch(() => {})`

## packages/workbench/src/renderer/src/store/chat-store-schedulers.ts

- [L78](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-schedulers.ts:78)：`error: options.busyTimeoutMessage()`
- [L100](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-schedulers.ts:100)：`.catch(giveUp)`

## packages/workbench/src/renderer/src/store/chat-store-types.ts

- [L102](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-types.ts:102)：`error: string | null`
- [L148](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store-types.ts:148)：`setError: (message: string | null) => void`

## packages/workbench/src/renderer/src/store/chat-store.ts

- [L28](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:28)：`import { formatRuntimeError, getRuntimeErrorCode } from '../lib/format-runtime-error'`
- [L139](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:139)：`function runtimeErrorDetail(error: unknown): string {`
- [L180](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:180)：`.catch((error: unknown) => {`
- [L261](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:261)：`error: null`
- [L368](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:368)：`.catch(() => {`
- [L473](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:473)：`error: null,`
- [L530](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:530)：`function shouldOpenSettingsForError(error: unknown): boolean {`
- [L535](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:535)：`function settingsSectionForRuntimeError(error: unknown): SettingsRouteSection | null {`
- [L559](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:559)：`const confirmed = window.confirm(`
- [L613](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:613)：`function looksLikeActiveTurnError(error: unknown): boolean {`
- [L763](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:763)：`error: s.error === i18n.t('common:runtimeStreamRecovering') ? null : s.error`
- [L802](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:802)：`error: s.error === i18n.t('common:runtimeStreamRecovering') ? null : s.error`
- [L818](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:818)：`error: nextError,`
- [L952](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:952)：`error: s.error === i18n.t('common:runtimeStreamRecovering') ? null : s.error`
- [L977](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:977)：`error: s.error === i18n.t('common:runtimeStreamRecovering') ? null : s.error`
- [L1015](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1015)：`error: s.error === i18n.t('common:runtimeStreamRecovering') ? null : s.error`
- [L1043](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1043)：`error: s.error === i18n.t('common:runtimeStreamRecovering') ? null : s.error`
- [L1076](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1076)：`error: s.error === i18n.t('common:runtimeStreamRecovering') ? null : s.error`
- [L1104](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1104)：`error: s.error === i18n.t('common:runtimeStreamRecovering') ? null : s.error`
- [L1119](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1119)：`error: s.error === i18n.t('common:runtimeStreamRecovering') ? null : s.error,`
- [L1418](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1418)：`error: null,`
- [L1460](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1460)：`error: formatRuntimeError(err)`
- [L1501](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1501)：`error: null,`
- [L1565](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1565)：`.catch(() => undefined)`
- [L1652](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1652)：`set({ runtimeConnection: 'ready', error: null, runtimeErrorDetail: null })`
- [L1662](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1662)：`const msg = formatRuntimeError(e)`
- [L1669](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1669)：`error: msg,`
- [L1679](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1679)：`error: msg,`
- [L1695](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1695)：`error: formatRuntimeError(`
- [L1732](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1732)：`error: needsInitialSetup ? null : get().error,`
- [L1745](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1745)：`error: formatRuntimeError(e),`
- [L1780](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1780)：`error: null`
- [L1800](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1800)：`error: formatRuntimeError(e)`
- [L1814](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1814)：`set({ error: i18n.t('common:workspaceRequiredToCreateThread') })`
- [L1821](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1821)：`error: formatWorkspacePickerError(e)`
- [L1836](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1836)：`error: null`
- [L1867](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1867)：`error: null`
- [L1902](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1902)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L1954](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1954)：`error: null`
- [L1974](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:1974)：`error: formatRuntimeError(e),`
- [L2041](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2041)：`error: formatRuntimeError(e),`
- [L2051](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2051)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2079](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2079)：`set({ error: null })`
- [L2096](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2096)：`error: formatRuntimeError(e),`
- [L2112](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2112)：`set({ error: i18n.t('common:runtimeStreamRecovering') })`
- [L2146](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2146)：`error: busy ? i18n.t('common:runtimeStreamRecovering') : null,`
- [L2184](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2184)：`error: formatRuntimeError(e),`
- [L2235](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2235)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2290](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2290)：`error: null,`
- [L2318](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2318)：`error: formatRuntimeError(e),`
- [L2398](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2398)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2431](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2431)：`error: null`
- [L2490](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2490)：`error: null,`
- [L2518](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2518)：`error: i18n.t('common:workspaceRequiredToCreateThread')`
- [L2576](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2576)：`error: formatRuntimeError(e),`
- [L2666](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2666)：`const renamed = await p.renameThread(activeThreadId, generatedTitle).then(() => true).catch(() => {`
- [L2709](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2709)：`error: i18n.t('common:runtimeActiveTurn')`
- [L2716](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2716)：`error: formatRuntimeError(e),`
- [L2732](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2732)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2737](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2737)：`set({ error: i18n.t('common:goalCommandUnsupported') })`
- [L2752](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2752)：`set({ error: i18n.t('common:workspaceRequiredToCreateThread') })`
- [L2767](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2767)：`set({ error: i18n.t('common:workspaceRequiredToCreateThread') })`
- [L2778](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2778)：`set({ error: formatRuntimeError(e) })`
- [L2787](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2787)：`error: null`
- [L2793](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2793)：`error: null`
- [L2810](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2810)：`set({ error: formatRuntimeError(e) })`
- [L2831](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2831)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2840](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2840)：`error: formatRuntimeError(e),`
- [L2853](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2853)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2862](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2862)：`error: formatRuntimeError(e),`
- [L2884](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2884)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2889](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2889)：`set({ error: i18n.t('common:runtimeForkUnsupported') })`
- [L2898](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2898)：`error: formatRuntimeError(e),`
- [L2910](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2910)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2915](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2915)：`set({ error: i18n.t('common:runtimeResumeUnsupported') })`
- [L2920](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2920)：`set({ error: null })`
- [L2923](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2923)：`error: formatRuntimeError(e),`
- [L2933](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2933)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2938](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2938)：`set({ error: i18n.t('common:runtimeExportUnsupported') })`
- [L2943](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2943)：`set({ error: null })`
- [L2947](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2947)：`error: formatRuntimeError(e),`
- [L2970](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2970)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L2974](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2974)：`set({ error: i18n.t('common:runtimeCompactBusy') })`
- [L2979](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2979)：`set({ error: i18n.t('common:runtimeCompactUnsupported') })`
- [L2983](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2983)：`set({ busy: true, error: null })`
- [L2991](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:2991)：`error: formatRuntimeError(e),`
- [L3004](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3004)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L3036](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3036)：`error: null`
- [L3042](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3042)：`error: formatRuntimeError(e),`
- [L3054](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3054)：`set({ error: i18n.t('common:runtimeActionNeedsConnection') })`
- [L3087](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3087)：`error: null`
- [L3093](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3093)：`error: formatRuntimeError(e),`
- [L3112](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3112)：`set({ error: i18n.t('common:sidebarPinLimitReached', { count: PINNED_THREADS_LIMIT }) })`
- [L3117](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3117)：`set({ pinnedThreadIds: next, error: null })`
- [L3149](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3149)：`set({ error: i18n.t('common:rewindBusyError') })`
- [L3165](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3165)：`set({ error: i18n.t('common:rewindRestoreUnsupported') })`
- [L3179](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3179)：`set({ error: formatRuntimeError(e) })`
- [L3243](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3243)：`error: i18n.t('common:rewindResendCompletedWithUnresolved', {`
- [L3256](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3256)：`set({ error: i18n.t('common:rewindBusyError') })`
- [L3275](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3275)：`set({ error: formatRuntimeError(e) })`
- [L3300](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3300)：`set({ error: i18n.t('common:rewindBusyError') })`
- [L3308](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3308)：`set({ error: i18n.t('common:rewindRestoreUnsupported') })`
- [L3315](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3315)：`set((s) => ({ error: null, workspaceDirtyTick: s.workspaceDirtyTick + 1 }))`
- [L3319](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3319)：`set({ error: formatRuntimeError(e) })`
- [L3331](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3331)：`set({ error: i18n.t('common:publishConflictUnsupported') })`
- [L3345](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3345)：`? { error: null, workspaceDirtyTick: s.workspaceDirtyTick + 1 }`
- [L3352](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3352)：`set({ error: formatRuntimeError(e) })`
- [L3366](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3366)：`set({ error: 'Current provider does not support approval decisions.' })`
- [L3390](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3390)：`const msg = formatRuntimeError(e)`
- [L3396](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3396)：`error: msg,`
- [L3420](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3420)：`set({ error: 'Current provider does not support evolution approvals.' })`
- [L3436](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3436)：`const msg = formatRuntimeError(e)`
- [L3442](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3442)：`error: msg,`
- [L3458](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3458)：`set({ error: 'Current provider does not support sandbox elevation.' })`
- [L3479](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3479)：`const msg = formatRuntimeError(e)`
- [L3485](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3485)：`error: msg,`
- [L3564](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3564)：`const msg = formatRuntimeError(e)`
- [L3570](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3570)：`error: msg,`
- [L3622](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3622)：`const msg = formatRuntimeError(e)`
- [L3632](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/chat-store.ts:3632)：`error: msg,`

## packages/workbench/src/renderer/src/store/workspace-editor-store.ts

- [L15](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:15)：`error: string | null`
- [L258](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:258)：`error: null,`
- [L283](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:283)：`error: 'File bridge is unavailable.'`
- [L305](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:305)：`error: result.message`
- [L314](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:314)：`error: null,`
- [L332](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:332)：`error: error instanceof Error ? error.message : String(error)`
- [L446](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:446)：`entry.id === tab.id ? { ...entry, error: result.message } : entry`
- [L458](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:458)：`error: null,`
- [L507](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:507)：`return { ...entry, error: result.message }`
- [L513](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/store/workspace-editor-store.ts:513)：`error: null,`

## packages/workbench/src/shared/appearance.ts

- [L770](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/appearance.ts:770)：`| { ok: false; error: 'format' | 'variant-mismatch' }`
- [L777](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/appearance.ts:777)：`if (!trimmed.startsWith(THEME_SHARE_PREFIX)) return { ok: false, error: 'format' }`
- [L782](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/appearance.ts:782)：`return { ok: false, error: 'format' }`
- [L785](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/appearance.ts:785)：`return { ok: false, error: 'format' }`
- [L789](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/appearance.ts:789)：`if (variant !== 'light' && variant !== 'dark') return { ok: false, error: 'format' }`
- [L790](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/appearance.ts:790)：`if (variant !== expectedVariant) return { ok: false, error: 'variant-mismatch' }`
- [L792](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/appearance.ts:792)：`if (typeof rawTheme !== 'object' || rawTheme === null) return { ok: false, error: 'format' }`
- [L797](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/appearance.ts:797)：`if (!accent || !surface || !ink) return { ok: false, error: 'format' }`

## packages/workbench/src/shared/ds-gui-api.ts

- [L241](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/ds-gui-api.ts:241)：`| { ok: false; error: string }`
- [L278](/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/shared/ds-gui-api.ts:278)：`| { ok: false; error: string }`

## 中英文提示文案定位

以下只按 key 名匹配，不作为完整翻译覆盖率统计。

### packages/workbench/src/renderer/src/locales/en/common.json

- `fileReferenceOpenFailed`：Could not open file
- `kanbanSendFailed`：Send failed — check the connection and try again
- `pluginSysTrustConfirm`：Trust plugin "{{name}}"? Its hooks can run arbitrary shell commands as your user (full environment inherited), and MCP servers spawn processes. Only trust plugins you have reviewed.
- `pluginSysRemoveConfirm`：Remove plugin "{{name}}"? This deletes its folder on disk.
- `pluginRulesError`：Could not read plugin rules.
- `pluginMpRemoveConfirm`：Remove marketplace "{{name}}"? Plugins you already installed stay installed.
- `connectorDeleteConfirm`：Delete connector "{{name}}"? This removes it from mcp.json.
- `composerConnectorFailed`："{{name}}" failed to connect and cannot be used{{error}}
- `composerConnectorFailedHint`：Failed to connect{{error}}
- `connectorStatusFailed`：Failed{{error}}
- `skillDeleteConfirm`：Delete skill "{{name}}"? This removes its folder on disk.
- `skillDeleteConfirmCopies`：Delete skill "{{name}}"? This removes {{count}} copies across agent directories.
- `skillPreviewError`：Could not read this skill's documentation.
- `clawAddImOfficialQrSuccess`：Scan succeeded
- `clawAddImOfficialQrFailed`：QR flow failed
- `clawAddImOfficialQrRetry`：Generate again
- `clawDeleteImConfirm`：Delete IM "{{name}}" and its local conversation configuration? This cannot be undone.
- `pluginActionFailed`：Action failed
- `marketplaceLoadFailed`：Could not load the ModelScope catalog: {{error}}
- `pluginCustomNameRequired`：Enter a name first.
- `mcpDialogNameRequired`：Server name is required.
- `mcpDialogCommandRequired`：Command is required.
- `mcpDialogUrlRequired`：Server URL is required.
- `mcpImportParseError`：Failed to parse JSON, please check the format.
- `skillInstallSuccess`：Installed to {{path}}
- `composerOfflineHint`：Reconnect the runtime before sending another message.
- `publishConflictUnsupported`：This runtime cannot resolve file publish conflicts.
- `publishDraftFailed`：Changes were not synced. Try again in a moment.
- `publishSyncFailedTitle`：Changes could not be synced automatically
- `publishSyncFailedBody`：Your changes are safe. Retry syncing them to the project folder.
- `publishSyncRetry`：Retry sync
- `publishRecoveryConfirmKeepProject`：This discards the listed changes from the task copy and leaves the project versions unchanged.
- `publishRecoveryConfirmKeepProjectUnknown`：The old task copy cannot be verified file by file. Continuing discards that copy and rebuilds it from the project; project files stay unchanged.
- `publishRecoveryConfirmUseAgent`：This replaces the listed project files with the versions preserved in this task.
- `publishMissingRetry`：Check workspace again
- `publishMissingRetrying`：Checking…
- `publishMissingRetryFailed`：The original workspace is still unavailable; no project files were changed.
- `composerPluginPendingBadge`：Pending · {{name}}
- `mermaidRenderFailed`：Diagram failed to render — source below is not the diagram.
- `mermaidRenderFailedShort`：Render failed
- `composerAttachFailed`：Could not attach the selected files.
- `composerPasteFailed`：Could not save the pasted text as a file.
- `composerReasoningWarning`：Uses limits faster
- `composerVoiceConfirm`：Transcribe
- `toolOutputTruncatedNotice`：Output too large to display in full — showing the first {{shown}} of {{total}} characters.
- `composerVoiceErrorNotAllowed`：Microphone permission denied
- `composerVoiceErrorUnavailable`：Voice input is unavailable
- `composerVoiceErrorDevice`：No microphone found, or it is in use by another app.
- `automationCreateSuccess`：Created “{{name}}”
- `automationError_prompt_required`：Describe what the task should do first.
- `automationError_once_at_invalid`：Choose a valid one-time run time.
- `automationError_interval_invalid`：Enter an hourly interval greater than 0.
- `automationError_time_of_day_invalid`：Choose a valid run time.
- `automationError_weekdays_required`：Choose at least one weekday.
- `automationError_cron_required`：Enter a cron expression.
- `automationError_cron_invalid`：A cron expression needs 5 fields, e.g. 0 9 * * *.
- `automationDeleteConfirm`：Delete "{{name}}"?
- `automationRunDeliveryFailed`：Delivery failed
- `channelRuntimeOffline`：Runtime offline; configuration remains editable
- `channelWecomInvalidWebhook`：Invalid webhook — paste the full URL or key
- `channelFeishuScanSuccess`：Feishu connected. Credentials saved locally.
- `channelEmailAuthCodeRequired`：Enter the SMTP authorization code.
- `trendingError`：Failed to load
- `trendingRetry`：Retry
- `contextRailTaskStatusFailed`：Failed
- `taskResume.confirm`：Resume with these original permissions? Completed actions will not be undone.
- `taskResumeFailed`：Failed to resume task
- `confirmDialogConfirm`：Confirm
- `workspaceTreeRestartRequired`：Fully restart the app (quit DeepSeek GUI, then reopen). Reloading the page is not enough.
- `workspaceEditorCloseDirtyConfirm`：“{{file}}” has unsaved changes. Close anyway?
- `workspaceEditorDiscardConfirm`：Discard unsaved changes?
- `workspaceEditorOpenExternalFailed`：Could not open externally: {{message}}
- `usageHeroError`：Could not load usage stats.
- `sidebarProjectsClearAllConfirm`：Delete all {{count}} chats in Projects? This cannot be undone.
- `sidebarProjectsDeleteSelectedConfirm`：Delete {{count}} selected chats? This cannot be undone.
- `sidebarChatsClearAllConfirm`：Delete all {{count}} temporary chats in Workspace? This cannot be undone.
- `sidebarChatsDeleteSelectedConfirm`：Delete {{count}} selected temporary chats? This cannot be undone.
- `copySuccess`：Copied
- `copyFailed`：Copy failed
- `runtimeOffline`：Runtime unavailable. Check settings or start `deepseek serve --http`.
- `goalStatus_blocked`：Blocked
- `goalCancelConfirm`：Cancel this goal? The current turn will be interrupted.
- `goalCommandUnsupported`：This runtime does not support goal commands.
- `terminalCreateFailed`：Could not create the terminal: {{message}}
- `terminalWorkspaceRequired`：Choose a working directory first
- `subagentStatusPending`：Pending
- `subagentStatusFailed`：Failed
- `subagentStatusToolFailed`：Tool failed
- `subagentSummaryFailed`：{{count}} failed
- `subagentFailureReason`：Failure reason
- `subagentResumeFailed`：Failed to resume sub-agent
- `approvalPending`：Waiting for your decision…
- `approvalAllowConfirm`：Confirm allow
- `approvalAllowRememberConfirm`：Confirm allow for session
- `approvalConfirmAgain`：Press the same allow button again to confirm this destructive action.
- `approvalFailed`：Request failed
- `evolutionPending`：Waiting for your decision…
- `evolutionFailed`：Request failed
- `elevationPending`：Waiting for elevation…
- `elevationFailed`：Elevation request failed
- `runtimeExportUnsupported`：Current provider does not support exporting to a runtime session.
- `userInputPending`：Waiting for your answer…
- `userInputFailed`：Submit failed
- `runtimeOfflineShort`：Runtime offline
- `retryConnection`：Retry
- `runtimeFetchFailed`：Could not reach the local runtime. Make sure `deepseek serve --http` is running, or enable auto-start in Settings.
- `runtimeAuthRequired`：The local runtime requires a bearer token for thread APIs. Add the runtime token in Settings, or restart the GUI so it can manage the local runtime again.
- `runtimeRequestFailed`：Runtime request failed. Please try again.
- `runtimeSteerUnsupported`：The current runtime does not support adding input while a turn is running.
- `runtimeUserInputUnsupported`：The current runtime does not expose an HTTP submit endpoint for request_user_input yet.
- `workspaceRequiredToCreateThread`：Choose a working directory before creating a thread.
- `gitDirtySwitchBlocked`：Uncommitted local changes conflict with "{{branch}}". Commit or stash them before switching.
- `gitRuntimeCheckoutSwitchBlocked`：This development app is running from the selected checkout. Use an installed build or open the project from a separate checkout before switching branches.
- `gitLogRefreshFailed`：Remote check failed; showing the local cache
- `runtimeOfflineHeroTitle`：Connect the local runtime first
- `runtimeOfflineHeroSub`：Check your deepseek CLI, port, and API key configuration, then retry the connection or open Settings.
- `runtimeDiagnosticsLastError`：Last runtime error
- `runtimeDiagnosticsSkillsCountWithWarnings`：{{count}} discovered · {{warnings}} warnings
- `exportSessionSuccess`：Exported to {{path}}
- `runtimeDiagnosticsRetrying`：Retrying the runtime connection…
- `runtimeDiagnosticsOpenDirFailed`：Could not open the config directory.
- `runtimeDiagnosticsSaveRetry`：Save and retry
- `sidebarOfflineHint`：Connect the runtime first to create and continue threads.
- `sidebarEmptySubOffline`：Connect the runtime first, then create your first thread from above.
- `sidebarWorkspaceRemoveConfirm`：Remove project "{{path}}" from the sidebar? Chat history is kept and will return if you open this folder again.
- `sidebarWorkspaceDeleteFileConfirm`：Delete all chats for project "{{path}}"? This cannot be undone. The folder on disk is not deleted.
- `sidebarDeleteUnpublishedConfirm`：One or more chats still have unsynced code in an isolated copy. Continuing will permanently discard that code and cannot be undone. Delete anyway?
- `sidebarThreadDeleteConfirm`：Delete thread "{{title}}"? This cannot be undone.
- `runtimeForkUnsupported`：This runtime does not support forking threads.
- `runtimeResumeUnsupported`：This runtime does not support resuming threads.
- `runtimeCompactUnsupported`：This runtime does not support compaction.
- `gitStageSuccess`：Selected files staged
- `gitUnstageSuccess`：Selected files unstaged
- `gitCommitLocalSuccess`：Committed locally ({{hash}})
- `gitPushSuccess`：Pushed {{branch}} to the remote
- `gitPullSuccess`：Updated the current branch from its remote
- `gitSyncSuccess`：Local and remote changes are synced
- `browserScreenshotFailed`：Couldn't copy screenshot
- `browserInvalidUrl`：Enter a local/LAN address, or a public https URL.
- `browserLoadFailed`：Page failed to load
- `browserEmbedUnsupportedTitle`：This site can’t be embedded here
- `browserEmbedUnsupportedBody`：This environment can’t embed full websites. Open it in your system browser, or use the desktop sidebar browser.
- `filePreviewFailed`：Could not read the file.
- `turnChangeUndoConfirm`：Restore these files to their state before this turn? The conversation stays.
- `turnChangeUndoConfirmAction`：Restore files
- `turnChangeUndoSuccess`：Restored {{count}} file(s); {{skipped}} skipped
- `rewindBusyError`：Wait for the current turn to finish before rewinding.
- `rewindRestoreUnsupported`：The current runtime does not support rewind restore.
- `rewindResendConfirmTitle`：How should this message be resent?
- `rewindResendConfirmBody`：You can rewind only the conversation, or also restore the files below to their state before this message. Your edited text will then be resent.
- `rewindResendConfirmPreviewFailed`：Could not preview affected files. You can rewind only the conversation, or still try to restore the code.
- `rewindResendConfirmRestore`：Restore code and resend
- `rewindResendConfirmRestoreAvailable`：Restore available files and resend
- `rewindResendConfirmConversationOnly`：Rewind conversation only and resend
- `rewindResendConfirmMoreFiles`：+{{count}} more
- `rewindResendConfirmConflictTag`：conflict
- `rewindResendConfirmSkippedTag`：unavailable
- `rewindResendConfirmConflictNote`：{{count}} file(s) changed after this turn; they stay as-is by default.
- `rewindResendConfirmUnavailableNote`：{{count}} file(s) or previous workspace cannot be restored; other files will still be restored when available.
- `rewindResendConfirmNoCheckpoint`：{{count}} turn(s) have no code restore record. The conversation will still rewind, but their code changes may not be restored with it.
- `rewindResendConfirmForce`：Also overwrite conflicted files (discards those edits)
- `runPanelLoadFailed`：Unable to load progress. Retrying…

### packages/workbench/src/renderer/src/locales/en/settings.json

- `clawFeishuCopyFailed`：Copy failed
- `clawFeishuReceiveIdRequired`：Enter a receive ID first
- `clawTaskDeleteConfirm`：Delete scheduled task “{{name}}”? This cannot be undone.
- `llmModelsFetchFailed`：Could not fetch models automatically; showing common defaults.
- `appearanceRestoreConfirm`：Click again to confirm
- `themePackCopyFailed`：Copy failed
- `themeImportInvalid`：Not a valid theme share string.
- `themeTranslucentUnsupported`：Available in the macOS desktop app. This platform keeps the sidebar opaque.
- `tuiUpdateCheckFailed`：Could not check for updates
- `tuiUpdateRestartPending`：The upgrade finished; the runtime will use it next time it starts.
- `portInvalid`：Port must be between 1 and 65535.
- `applyFailed`：Could not apply
- `autoApplyBlocked`：Fix the port to apply changes
- `apiKeyRequiredTitle`：API key required
- `apiKeyRequiredBody`：Configure at least one model provider API key (DeepSeek / Kimi / GLM / Volcengine). The GUI will download the bundled runtime if needed and start the local service.
- `guiUpdateCheckFailed`：Could not check for GUI updates
- `guiUpdateErrUnsupported`：This build does not support in-app automatic updates. Open the download page to install manually.
- `guiUpdateErrDownloadFailed`：Could not download the update: {{message}}
- `guiUpdateErrInstallFailed`：Could not install the update: {{message}}
- `loadFailed`：Could not load settings: {{message}}
- `preloadBridgeError`：The app bridge is not available. Restart the application or check the preload path.
- `modelUsageError`：Could not load usage: {{message}}
- `modelTestFailed`：Test failed
- `archiveDeleteOneConfirm`：Permanently delete "{{title}}"? This cannot be undone.
- `archiveDeleteAllConfirm`：Permanently delete all {{count}} archived tasks? This cannot be undone.
- `archiveLoadFailed`：Could not load archived tasks. Make sure the local runtime is connected.
- `archiveActionFailed`：Delete failed. Restart the app, then try Delete all again.
- `dataInventoryLoadFailed`：Could not load storage overview. Make sure the local runtime is connected.
- `dataOpenDirFailed`：Could not open the data directory
- `dataOptimizeFailed`：Optimization failed
- `dataCleanConfirm`：Delete conversations older than {{days}} days? This cannot be undone.
- `dataCleanFailed`：Clean failed
- `dataClearHistoryConfirm`：Clear all conversation history? Skills, MCP, plugins, and settings will be kept. This cannot be undone.
- `dataClearHistoryConfirm2`：Confirm again: all conversations and messages will be permanently deleted and cannot be recovered.
- `dataClearHistoryFailed`：Clear failed
- `dataExportSecretsConfirm`：This scope may include API keys and other secrets. Continue exporting?
- `dataExportFailed`：Export failed
- `dataImportModeConfirm`：Replace existing conversations with the import? /  / OK = Replace / Cancel = Merge (skip existing ids)
- `dataImportFailed`：Import failed
- `dataBackupDirFailed`：Could not set backup directory
- `dataBackupFailed`：Backup failed (set a backup directory first)
- `dataDeleteAndExitConfirm`：Delete local GUI settings and caches and quit? Conversations, Skills, and Claw sandboxes will not be deleted.
- `dataDeleteAndExitConfirm2`：Confirm again: GUI settings (~/.deepseek/settings.json) and caches under ~/.deepseek/caches, plus Electron caches, will be cleared and the app will quit immediately. This cannot be undone.
- `dataDeleteAndExitFailed`：Failed to delete local data

### packages/workbench/src/renderer/src/locales/zh/common.json

- `fileReferenceOpenFailed`：无法打开文件
- `kanbanSendFailed`：发送失败，请检查连接后重试
- `pluginSysTrustConfirm`：信任插件“{{name}}”？其 Hooks 将以你的用户身份执行任意 shell（继承完整环境变量），MCP 服务器也会启动进程。仅信任你已审查过的插件。
- `pluginSysRemoveConfirm`：移除插件“{{name}}”？将删除其磁盘上的文件夹。
- `pluginRulesError`：无法读取插件规则文档。
- `pluginMpRemoveConfirm`：移除市场“{{name}}”？已安装的插件不受影响。
- `connectorDeleteConfirm`：确定删除连接器「{{name}}」吗？此操作会从 mcp.json 移除该配置。
- `composerConnectorFailed`：「{{name}}」连接失败，无法使用{{error}}
- `composerConnectorFailedHint`：连接失败，无法使用{{error}}
- `connectorStatusFailed`：连接失败{{error}}
- `skillDeleteConfirm`：确定删除技能「{{name}}」吗？此操作会移除磁盘上的技能目录。
- `skillDeleteConfirmCopies`：确定删除技能「{{name}}」吗？将同时移除 {{count}} 个 agent 目录中的副本。
- `skillPreviewError`：无法读取该技能的说明文档。
- `clawAddImOfficialQrSuccess`：扫码成功
- `clawAddImOfficialQrFailed`：二维码流程失败
- `clawAddImOfficialQrRetry`：重新生成
- `clawDeleteImConfirm`：确定删除 IM「{{name}}」及其本地会话配置吗？此操作无法撤销。
- `pluginActionFailed`：操作失败
- `marketplaceLoadFailed`：无法加载 ModelScope 列表：{{error}}
- `pluginCustomNameRequired`：请先填写名称。
- `mcpDialogNameRequired`：请填写服务器名称。
- `mcpDialogCommandRequired`：请填写命令。
- `mcpDialogUrlRequired`：请填写服务器 URL。
- `mcpImportParseError`：JSON 解析失败，请检查格式。
- `skillInstallSuccess`：已安装到 {{path}}
- `composerOfflineHint`：运行时恢复连接后，才可以继续发送消息。
- `publishConflictUnsupported`：当前版本还不支持解决文件冲突。
- `publishDraftFailed`：没有完成同步，请稍后重试
- `publishSyncFailedTitle`：修改未能自动同步
- `publishSyncFailedBody`：修改仍安全保存在当前任务中，请重试同步到项目文件夹。
- `publishSyncRetry`：重试同步
- `publishRecoveryConfirmKeepProject`：这会放弃这次任务中列出的修改，项目里的版本保持不变。
- `publishRecoveryConfirmKeepProjectUnknown`：旧任务保存的版本无法逐个文件核对。继续后会放弃该版本，并按当前项目重新建立任务工作区；项目文件不会被改动。
- `publishRecoveryConfirmUseAgent`：这会用当前任务保存的版本替换项目中列出的文件。
- `publishMissingRetry`：重新检查工作区
- `publishMissingRetrying`：正在检查…
- `publishMissingRetryFailed`：仍未找到原工作区；项目文件没有被改动。
- `composerPluginPendingBadge`：待使用 · {{name}}
- `mermaidRenderFailed`：图示渲染失败——下面是原始源码，不是渲染结果。
- `mermaidRenderFailedShort`：渲染失败
- `composerAttachFailed`：未能添加所选文件。
- `composerPasteFailed`：未能把粘贴内容写成文件。
- `composerReasoningWarning`：消耗更快
- `composerVoiceConfirm`：转写
- `toolOutputTruncatedNotice`：输出过大，无法完整显示——仅显示前 {{shown}} / 共 {{total}} 字符。
- `composerVoiceErrorNotAllowed`：未授予麦克风权限
- `composerVoiceErrorUnavailable`：语音输入不可用
- `composerVoiceErrorDevice`：未找到麦克风，或被其他程序占用。
- `automationCreateSuccess`：已创建「{{name}}」
- `automationError_prompt_required`：请先填写任务描述。
- `automationError_once_at_invalid`：请选择有效的一次性执行时间。
- `automationError_interval_invalid`：请输入大于 0 的小时间隔。
- `automationError_time_of_day_invalid`：请选择有效的执行时间。
- `automationError_weekdays_required`：每周计划至少选择一天。
- `automationError_cron_required`：请填写 cron 表达式。
- `automationError_cron_invalid`：cron 表达式需为 5 段，如 0 9 * * *。
- `automationDeleteConfirm`：确定删除「{{name}}」？
- `automationRunDeliveryFailed`：投递失败
- `channelRuntimeOffline`：Runtime 未连接，仍可编辑配置
- `channelWecomInvalidWebhook`：Webhook 格式无效，请粘贴完整地址或 key
- `channelFeishuScanSuccess`：飞书已连接，凭证已保存到本地。
- `channelEmailAuthCodeRequired`：请填写 SMTP 授权码。
- `trendingError`：加载失败
- `trendingRetry`：重试
- `contextRailTaskStatusFailed`：失败
- `confirmDialogConfirm`：确定
- `workspaceTreeRestartRequired`：文件树功能需要完全重启应用（Cmd+Q 退出后再打开），不能只刷新页面
- `workspaceEditorCloseDirtyConfirm`：「{{file}}」有未保存的修改，确定关闭？
- `workspaceEditorDiscardConfirm`：放弃未保存的修改？
- `workspaceEditorOpenExternalFailed`：无法用外部应用打开：{{message}}
- `usageHeroError`：无法加载用量统计。
- `sidebarProjectsClearAllConfirm`：确定删除项目中的全部 {{count}} 个会话吗？此操作无法撤销。
- `sidebarProjectsDeleteSelectedConfirm`：确定删除选中的 {{count}} 个会话吗？此操作无法撤销。
- `sidebarChatsClearAllConfirm`：确定删除工作空间中的全部 {{count}} 个临时会话吗？此操作无法撤销。
- `sidebarChatsDeleteSelectedConfirm`：确定删除选中的 {{count}} 个临时会话吗？此操作无法撤销。
- `copySuccess`：已复制
- `copyFailed`：复制失败
- `runtimeOffline`：运行时不可用。请在设置中检查或先启动 `deepseek serve --http`。
- `goalStatus_blocked`：已阻塞
- `goalCancelConfirm`：确定取消当前目标？进行中的回合会被中断。
- `goalCommandUnsupported`：当前运行时不支持目标命令。
- `terminalCreateFailed`：创建终端失败：{{message}}
- `terminalWorkspaceRequired`：请先选择工作目录
- `subagentStatusPending`：等待中
- `subagentStatusFailed`：失败
- `subagentStatusToolFailed`：工具失败
- `subagentSummaryFailed`：{{count}} 个失败
- `subagentFailureReason`：失败原因
- `subagentResumeFailed`：续跑子代理失败
- `approvalPending`：等待你选择…
- `approvalAllowConfirm`：确认允许
- `approvalAllowRememberConfirm`：确认并记住
- `approvalConfirmAgain`：请再次点击相同的允许按钮以确认此破坏性操作。
- `approvalFailed`：请求失败
- `evolutionPending`：等待你选择…
- `evolutionFailed`：请求失败
- `elevationPending`：等待升格确认…
- `elevationFailed`：升格请求失败
- `runtimeExportUnsupported`：当前 Provider 不支持导出为运行时会话。
- `userInputPending`：等待你选择…
- `userInputFailed`：提交失败
- `runtimeOfflineShort`：运行时离线
- `retryConnection`：重试连接
- `runtimeFetchFailed`：无法连接到本地运行时。请确认 `deepseek serve --http` 已启动，或在设置中开启自动启动。
- `runtimeAuthRequired`：本地运行时要求 Bearer Token 才能访问会话接口。请在设置中填写运行时令牌，或重启 GUI 让它重新管理本地运行时。
- `runtimeRequestFailed`：运行时请求失败。请稍后重试。
- `runtimeSteerUnsupported`：当前运行时不支持运行中追加输入。
- `runtimeUserInputUnsupported`：当前运行时尚未暴露 request_user_input 的 HTTP 提交接口。
- `workspaceRequiredToCreateThread`：请先选择一个工作目录，然后再创建会话。
- `gitDirtySwitchBlocked`：本地有未提交的改动与「{{branch}}」冲突，切换前需要提交或暂存这些改动。
- `gitRuntimeCheckoutSwitchBlocked`：当前开发版正从这个代码目录运行。请使用安装版，或从独立 checkout 打开项目后再切换分支。
- `gitLogRefreshFailed`：远程检查失败，正在显示本地缓存
- `runtimeOfflineHeroTitle`：先连接本地运行时
- `runtimeOfflineHeroSub`：确认 deepseek CLI、端口和 API Key 配置正确，然后点击“重试连接”或进入设置检查。
- `runtimeDiagnosticsLastError`：上次运行时错误
- `runtimeDiagnosticsSkillsCountWithWarnings`：已发现 {{count}} 个 · {{warnings}} 条警告
- `exportSessionSuccess`：已导出至 {{path}}
- `runtimeDiagnosticsRetrying`：正在重试运行时连接…
- `runtimeDiagnosticsOpenDirFailed`：无法打开配置目录。
- `runtimeDiagnosticsSaveRetry`：保存并重试
- `sidebarOfflineHint`：连接运行时后即可创建并继续会话。
- `sidebarEmptySubOffline`：先连接运行时，随后从上方创建第一条会话。
- `sidebarWorkspaceRemoveConfirm`：将项目「{{path}}」从侧边栏移除？会话历史会保留，再次打开该文件夹后仍会显示。
- `sidebarWorkspaceDeleteFileConfirm`：确定删除项目「{{path}}」下的全部会话吗？此操作无法撤销。磁盘上的文件夹不会被删除。
- `sidebarDeleteUnpublishedConfirm`：一个或多个会话的隔离副本中还有未同步代码。继续删除会永久丢弃这些代码，且无法恢复。仍要删除吗？
- `sidebarThreadDeleteConfirm`：确定删除会话「{{title}}」吗？此操作无法撤销。
- `runtimeForkUnsupported`：当前运行时不支持分叉会话。
- `runtimeResumeUnsupported`：当前运行时不支持恢复会话。
- `runtimeCompactUnsupported`：当前运行时不支持压缩上下文。
- `gitStageSuccess`：所选文件已暂存
- `gitUnstageSuccess`：所选文件已取消暂存
- `gitCommitLocalSuccess`：已提交到本地（{{hash}}）
- `gitPushSuccess`：已将 {{branch}} 推送到远程
- `gitPullSuccess`：已从远程更新当前分支
- `gitSyncSuccess`：本地与远程更改已同步
- `browserScreenshotFailed`：无法复制截图
- `browserInvalidUrl`：请输入本地/局域网地址，或公网 https 网址。
- `browserLoadFailed`：页面加载失败
- `browserEmbedUnsupportedTitle`：此站点无法在面板内嵌打开
- `browserEmbedUnsupportedBody`：当前环境不支持完整网页内嵌。请用系统浏览器打开，或在桌面版中使用侧栏浏览器。
- `filePreviewFailed`：无法读取文件。
- `turnChangeUndoConfirm`：把这些文件恢复到本轮开始前吗？对话内容会保留。
- `turnChangeUndoConfirmAction`：恢复文件
- `turnChangeUndoSuccess`：已恢复 {{count}} 个文件，跳过 {{skipped}} 个
- `rewindBusyError`：当前回合还在进行，等结束后再回退。
- `rewindRestoreUnsupported`：当前运行时不支持回退恢复。
- `rewindResendConfirmTitle`：要怎样重新发送这条消息？
- `rewindResendConfirmBody`：你可以只回退对话，也可以同时把以下文件还原到该消息之前；随后会重新发送编辑后的内容。
- `rewindResendConfirmPreviewFailed`：无法预览将影响的文件。你可以仅回退对话，或仍尝试还原代码。
- `rewindResendConfirmRestore`：还原代码并重发
- `rewindResendConfirmRestoreAvailable`：还原可恢复文件并重发
- `rewindResendConfirmConversationOnly`：仅回退对话并重发
- `rewindResendConfirmMoreFiles`：等 {{count}} 个
- `rewindResendConfirmConflictTag`：冲突
- `rewindResendConfirmSkippedTag`：不可恢复
- `rewindResendConfirmConflictNote`：{{count}} 个文件在这次对话之后又被改过，默认先保持原样。
- `rewindResendConfirmUnavailableNote`：{{count}} 个文件或旧工作区当前无法恢复；其他文件仍会按选择还原。
- `rewindResendConfirmNoCheckpoint`：其中 {{count}} 个回合没有可用的代码还原记录；对话仍会回退，但这些代码改动可能无法一起还原。
- `rewindResendConfirmForce`：同时覆盖冲突文件（会丢弃他人的改动）
- `taskResume.confirm`：是否按这些原有权限恢复？已执行的操作不会撤销。
- `taskResumeFailed`：续跑任务失败
- `runPanelLoadFailed`：暂时无法加载运行过程，正在重试…

### packages/workbench/src/renderer/src/locales/zh/settings.json

- `clawFeishuCopyFailed`：复制失败
- `clawFeishuReceiveIdRequired`：请先填写接收人 ID
- `clawTaskDeleteConfirm`：确定删除定时任务「{{name}}」？此操作不可恢复。
- `llmModelsFetchFailed`：未能自动获取模型列表，已显示常用模型。
- `appearanceRestoreConfirm`：再次点击确认
- `themePackCopyFailed`：复制失败
- `themeImportInvalid`：不是有效的主题分享串。
- `themeTranslucentUnsupported`：仅 macOS 桌面端支持；当前平台会保持实体侧边栏。
- `tuiUpdateCheckFailed`：无法检查更新
- `tuiUpdateRestartPending`：升级已完成，运行时将在下次启动时使用新版本。
- `portInvalid`：端口必须在 1 到 65535 之间。
- `applyFailed`：应用失败
- `autoApplyBlocked`：修正端口后自动应用
- `apiKeyRequiredTitle`：需要先配置 API Key
- `apiKeyRequiredBody`：请先配置至少一个大模型供应商的 API Key（DeepSeek / Kimi / GLM / 火山）。填写后，GUI 会在需要时自动下载内置运行时并启动服务。
- `guiUpdateCheckFailed`：无法检查 GUI 更新
- `guiUpdateErrUnsupported`：当前构建不支持应用内自动更新，请打开下载页手动安装。
- `guiUpdateErrDownloadFailed`：下载更新失败：{{message}}
- `guiUpdateErrInstallFailed`：安装更新失败：{{message}}
- `loadFailed`：无法加载设置：{{message}}
- `preloadBridgeError`：应用桥接不可用。请重启应用或检查预加载脚本路径。
- `modelUsageError`：无法读取用量：{{message}}
- `modelTestFailed`：测试失败
- `archiveDeleteOneConfirm`：确定永久删除会话「{{title}}」吗？此操作无法撤销。
- `archiveDeleteAllConfirm`：确定永久删除全部 {{count}} 个已归档任务吗？此操作无法撤销。
- `archiveLoadFailed`：无法加载已归档任务。请确认本地 Runtime 已连接。
- `archiveActionFailed`：删除失败。请重启应用后再试「全部删除」。
- `dataInventoryLoadFailed`：无法读取存储概况。请确认本地 Runtime 已连接。
- `dataOpenDirFailed`：无法打开数据目录
- `dataOptimizeFailed`：优化失败
- `dataCleanConfirm`：确定删除 {{days}} 天前的对话吗？此操作不可撤销。
- `dataCleanFailed`：清理失败
- `dataClearHistoryConfirm`：确定清空全部对话历史吗？Skills、MCP、插件与设置会保留。此操作不可撤销。
- `dataClearHistoryConfirm2`：再次确认：将永久删除全部对话与消息，且无法恢复。
- `dataClearHistoryFailed`：清空失败
- `dataExportSecretsConfirm`：所选范围可能包含 API 密钥等敏感信息，确定继续导出吗？
- `dataExportFailed`：导出失败
- `dataImportModeConfirm`：用导入内容替换现有对话？ /  / 确定 = 替换 / 取消 = 合并（跳过已有对话）
- `dataImportFailed`：导入失败
- `dataBackupDirFailed`：无法设置备份目录
- `dataBackupFailed`：备份失败（请先设置备份目录）
- `dataDeleteAndExitConfirm`：确定删除本机 GUI 设置与缓存并退出吗？对话、Skills 与 Claw 沙箱不会被删除。
- `dataDeleteAndExitConfirm2`：再次确认：将清除 GUI 设置（~/.deepseek/settings.json）与 ~/.deepseek/caches 下的缓存及 Electron 缓存并立即退出，此操作不可撤销。
- `dataDeleteAndExitFailed`：删除本机数据失败

