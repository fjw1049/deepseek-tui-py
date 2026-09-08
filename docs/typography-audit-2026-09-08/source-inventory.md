# 字体审核：源码索引（全 renderer 扫描）

此附件是机械扫描证据，不是“最终生效字号表”。覆盖组件条件分支、CSS、Shadow DOM 声明及行高／字距；可能含注释、已覆盖规则或不在主界面的页面。请结合主报告中的级联核验阅读。没有显式声明的文字从父层继承；图标尺寸不等于字号。

扫描文件 304 个；命中 113 个文件、1587 行。文件名与行号对应审核时工作区快照。

## App.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [8](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/App.tsx:8) | &lt;div className="ds-glass flex items-center gap-2 rounded-full px-4 py-2 text-[13px]"&gt; |

## components/AppTerminalPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [83](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:83) | fontFamily: readTerminalFontFamily(), |
| [84](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:84) | fontSize: getTerminalFontSizePx(), |
| [260](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:260) | fontFamily: readTerminalFontFamily(), |
| [261](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:261) | fontSize: getTerminalFontSizePx(), |
| [320](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:320) | const fontFamily = readTerminalFontFamily() |
| [321](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:321) | const fontSize = getTerminalFontSizePx() |
| [324](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:324) | handle.terminal.options.fontFamily = fontFamily |
| [325](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:325) | handle.terminal.options.fontSize = fontSize |
| [445](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:445) | className="max-w-[200px] truncate px-2 py-0.5 text-[12px] font-medium leading-5" |
| [450](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:450) | &lt;span className="ml-1 rounded bg-ds-hover px-1 py-px text-[10px] font-medium text-ds-faint"&gt; |
| [501](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:501) | &lt;div className="shrink-0 border-b border-red-200/70 bg-red-50/80 px-3 py-2 text-[12.5px] text-red-700 dark:border-red-500/20 dark:bg-red-500/8 dark:text-red-200"&gt; |
| [508](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/AppTerminalPanel.tsx:508) | &lt;div className="flex h-full items-center justify-center px-6 text-center text-[13px] text-ds-faint"&gt; |

## components/ChangeInspector.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [387](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:387) | 'flex min-h-8 w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover active:scale-[0.99] disabled:pointer-events-none disabled:opacity-35' |
| [484](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:484) | &lt;span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-ds-ink"&gt; |
| [498](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:498) | className="w-full resize-none rounded-lg border border-ds-border bg-ds-card px-2.5 py-2 pr-9 text-[12px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-ds-border-strong" |
| [505](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:505) | &lt;button type="button" disabled={busyAction !== null &#124;&#124; !message.trim()} onClick={() =&gt; void submit(false)} className={`inline-flex h-8 items-center justify-center rounded-lg text-[11.5px] font-medium active:scale-[0.98] disabled:opacity-40 ${commitPushPreferred ? 'bg-ds-hover text-ds-ink' : 'bg-accent text-white'}`}&gt; |
| [508](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:508) | &lt;button type="button" disabled={busyAction !== null &#124;&#124; !message.trim() &#124;&#124; !hasRemote} onClick={() =&gt; void submit(true)} className={`inline-flex h-8 items-center justify-center gap-1 rounded-lg px-2 text-[11.5px] font-medium active:scale-[0.98] disabled:opacity-40 ${commitPushPreferred ? 'bg-accent text-white' : 'bg-ds-hover text-ds-ink'}`}&gt; |
| [517](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:517) | &lt;div role="status" className={`absolute right-0 top-[calc(100%+6px)] z-[80] flex w-max max-w-72 items-start gap-1.5 rounded-lg border border-ds-border bg-ds-elevated px-2.5 py-2 text-[11px] leading-4 shadow-lg ${feedback.kind === 'success' ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-200'}`}&gt; |
| [616](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:616) | className="inline-flex h-7 min-w-0 max-w-full items-center gap-1.5 rounded-md px-2 text-left text-[12.5px] font-semibold text-ds-ink transition hover:bg-ds-hover active:scale-[0.98]" |
| [640](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:640) | &lt;div className="px-2 pb-1 pt-1.5 text-[10.5px] font-medium text-ds-faint"&gt; |
| [653](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:653) | className="flex min-h-8 w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover active:scale-[0.99]" |
| [660](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:660) | &lt;span className="max-w-24 shrink-0 truncate text-[10.5px] text-ds-faint"&gt; |
| [735](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:735) | className="flex min-h-8 w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover active:scale-[0.99]" |
| [746](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:746) | &lt;div ref={menuRef} className="ds-change-branch relative min-w-0 flex-1 text-[12.5px]"&gt; |
| [755](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:755) | className="flex h-7 min-w-0 max-w-full items-center gap-1 rounded-md px-2 font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.98] disabled:opacity-45" |
| [781](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:781) | className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ds-ink outline-none placeholder:text-ds-faint" |
| [790](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:790) | &lt;div className="px-2 py-3 text-[12px] text-ds-faint"&gt;{t('gitNoBranches')}&lt;/div&gt; |
| [796](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:796) | &lt;div className="px-2 pb-1 pt-1 text-[10.5px] font-medium text-ds-faint"&gt; |
| [804](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:804) | &lt;div className="px-2 pb-1 pt-1 text-[10.5px] font-medium text-ds-faint"&gt; |
| [812](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:812) | &lt;div className="px-2 pb-1 pt-1 text-[10.5px] font-medium text-ds-faint"&gt; |
| [819](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:819) | &lt;div className="px-2 py-3 text-[12px] text-ds-faint"&gt;{t('gitNoBranches')}&lt;/div&gt; |
| [1343](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1343) | &lt;span className="min-w-0 flex-1 truncate text-[12.5px]"&gt; |
| [1351](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1351) | className={`font-medium ${ |
| [1358](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1358) | &lt;span className="ml-1.5 text-[11px] text-ds-faint"&gt;{parent}&lt;/span&gt; |
| [1362](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1362) | &lt;span className="shrink-0 text-[10px] font-medium text-ds-muted"&gt; |
| [1367](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1367) | &lt;span className="shrink-0 text-[10px] font-medium text-amber-700 dark:text-amber-200"&gt; |
| [1379](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1379) | &lt;div className="min-w-0 flex-1 truncate text-[13px] text-ds-ink"&gt; |
| [1383](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1383) | &lt;span className="shrink-0 text-[11px] font-medium text-amber-700 dark:text-amber-200"&gt; |
| [1422](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1422) | &lt;div role="alert" className="border-b border-ds-border-muted px-2 py-1.5 text-[11px] text-amber-700 dark:text-amber-200"&gt; |
| [1430](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1430) | &lt;div className="sticky top-0 z-10 flex h-7 items-center bg-ds-sidebar px-2 text-[10.5px] font-semibold uppercase tracking-wide text-ds-faint"&gt; |
| [1486](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1486) | &lt;div className="flex flex-1 items-center justify-center text-[12px] text-ds-faint"&gt; |
| [1491](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1491) | &lt;div className="flex flex-1 items-center justify-center px-4 text-center text-[13px] text-ds-faint"&gt; |
| [1529](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1529) | &lt;span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-ds-hover px-1.5 text-[10.5px] font-medium tabular-nums text-ds-muted"&gt; |
| [1560](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1560) | &lt;div className="flex flex-1 items-center justify-center px-6 py-10 text-center text-[13px] text-ds-faint"&gt; |
| [1568](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1568) | &lt;div className="mt-3 text-[13px] font-medium text-ds-muted"&gt; |
| [1571](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ChangeInspector.tsx:1571) | &lt;div className="mt-1 text-[12px] leading-6 text-ds-faint"&gt; |

## components/ConnectionStatusBar.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [84](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ConnectionStatusBar.tsx:84) | &lt;span className="truncate text-[10px] font-medium tabular-nums"&gt;{label}&lt;/span&gt; |
| [88](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ConnectionStatusBar.tsx:88) | className="shrink-0 rounded-md px-1 py-0.5 text-[11.5px] font-semibold text-ds-muted underline decoration-ds-border underline-offset-2 transition hover:text-ds-ink" |
| [100](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ConnectionStatusBar.tsx:100) | className={`ds-no-drag inline-flex h-11 shrink-0 items-center gap-3 rounded-full border border-ds-border px-4 text-[13px] shadow-sm ${barTone}`} |
| [104](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ConnectionStatusBar.tsx:104) | &lt;span className="truncate font-medium"&gt;{label}&lt;/span&gt; |
| [109](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ConnectionStatusBar.tsx:109) | className="shrink-0 rounded-full bg-ds-elevated px-3 py-1.5 text-[12px] font-medium text-ds-ink ring-1 ring-ds-border transition hover:bg-ds-hover" |

## components/DevBrowserPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [1219](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1219) | &lt;div className="shrink-0 border-b border-red-200/70 bg-red-50/85 px-3 py-2 text-[11px] leading-5 text-red-800 dark:border-red-900/50 dark:bg-red-950/35 dark:text-red-100"&gt; |
| [1228](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1228) | &lt;div className="text-[14px] font-medium text-ds-ink"&gt;{t('browserEmptyTitle')}&lt;/div&gt; |
| [1229](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1229) | &lt;div className="max-w-sm text-[12.5px] leading-5 text-ds-muted"&gt; |
| [1235](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1235) | className="mt-1 rounded-full bg-accent px-4 py-2 text-[12.5px] font-semibold text-white" |
| [1290](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1290) | &lt;div className="text-[14px] font-medium text-ds-ink"&gt;{t('browserEmbedUnsupportedTitle')}&lt;/div&gt; |
| [1291](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1291) | &lt;div className="max-w-sm text-[12.5px] leading-5 text-ds-muted"&gt; |
| [1294](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1294) | &lt;div className="max-w-md truncate text-[12px] text-ds-faint" title={activeUrl ?? undefined}&gt; |
| [1300](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DevBrowserPanel.tsx:1300) | className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-[12.5px] font-semibold text-white" |

## components/DiffView.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [367](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:367) | &lt;td colSpan={4} className={`break-all ${metaPad} py-0.5 font-mono text-[12px]`}&gt; |
| [376](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:376) | className={`select-none px-1 text-right align-top font-mono text-[11px] tabular-nums text-ds-faint ${sideCls(row.leftKind)}`} |
| [381](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:381) | className={`max-w-0 break-all whitespace-pre-wrap ${cellPad} align-top font-mono text-[12.5px] leading-[1.45] ${sideCls(row.leftKind)}`} |
| [386](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:386) | className={`select-none border-l border-ds-border-muted/50 px-1 text-right align-top font-mono text-[11px] tabular-nums text-ds-faint ${sideCls(row.rightKind)}`} |
| [391](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:391) | className={`max-w-0 break-all whitespace-pre-wrap ${cellPad} align-top font-mono text-[12.5px] leading-[1.45] ${sideCls(row.rightKind)}`} |
| [410](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:410) | &lt;td className="select-none px-1 text-right align-top font-mono text-[11px] tabular-nums text-ds-faint"&gt; |
| [413](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:413) | &lt;td className="select-none border-r border-ds-border-muted/40 px-1 text-right align-top font-mono text-[11px] tabular-nums text-ds-faint"&gt; |
| [416](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:416) | &lt;td className="max-w-0 break-all whitespace-pre-wrap px-2 align-top font-mono text-[12.5px] leading-[1.45]"&gt; |
| [472](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:472) | className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold ${badge.tone}`} |
| [482](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:482) | className="min-w-0 flex-1 text-[12.5px] font-medium" |
| [485](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:485) | &lt;span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-ds-ink" title={name ?? ''}&gt; |
| [490](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/DiffView.tsx:490) | &lt;span className="shrink-0 text-[12px] tabular-nums"&gt; |

## components/InitialSetupDialog.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [23](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:23) | 'w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3.5 py-3 text-[15px] text-ds-ink shadow-sm outline-none transition placeholder:text-ds-faint focus:border-accent/40 focus:ring-1 focus:ring-accent/30' |
| [172](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:172) | &lt;div className="mx-auto flex max-w-[1000px] justify-center py-10 text-sm text-ds-muted"&gt; |
| [264](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:264) | className="inline-flex items-center gap-1 text-[13px] font-medium text-accent transition hover:brightness-110" |
| [277](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:277) | className={`${fieldClass} pr-10 tracking-[0.02em]`} |
| [294](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:294) | &lt;p className="text-[13px] leading-5 text-amber-700 dark:text-amber-300"&gt; |
| [343](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/InitialSetupDialog.tsx:343) | &lt;div className="mx-4 mb-2 rounded-xl border border-[var(--ds-danger)]/20 bg-[var(--ds-danger-soft)] px-4 py-3 text-[13px] text-[var(--ds-danger)]"&gt; |

## components/RuntimeDiagnosticsDialog.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [280](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:280) | &lt;h2 className="text-[18px] font-semibold text-ds-ink"&gt;{t('runtimeDiagnosticsTitle')}&lt;/h2&gt; |
| [282](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:282) | &lt;p className="mt-1 max-w-2xl text-[13px] leading-5 text-ds-muted"&gt; |
| [307](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:307) | className={`rounded-xl border px-3 py-2 text-[13px] leading-5 ${ |
| [321](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:321) | &lt;p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-amber-900 dark:text-amber-100"&gt; |
| [324](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:324) | &lt;pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-white/70 p-3 font-mono text-[12px] leading-5 text-amber-950 dark:bg-black/20 dark:text-amber-100"&gt; |
| [332](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:332) | &lt;p className="text-[13px] font-semibold text-ds-ink"&gt;{t('runtimeDiagnosticsFindings')}&lt;/p&gt; |
| [334](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:334) | className={`rounded-full px-2 py-1 text-[11px] font-semibold ${ |
| [350](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:350) | &lt;p className="text-[13px] font-semibold"&gt;{issue.title}&lt;/p&gt; |
| [351](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:351) | &lt;p className="mt-1 text-[12px] leading-5 opacity-90"&gt;{issue.message}&lt;/p&gt; |
| [353](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:353) | &lt;p className="mt-1 break-all font-mono text-[11px] opacity-75"&gt; |
| [363](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:363) | &lt;div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-[13px] text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-100"&gt; |
| [371](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:371) | &lt;p className="text-[13px] font-semibold text-ds-ink"&gt;{t('runtimeDiagnosticsStatus')}&lt;/p&gt; |
| [372](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:372) | &lt;dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-[12px] leading-5"&gt; |
| [417](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:417) | &lt;p className="text-[13px] font-semibold text-ds-ink"&gt;{t('runtimeDiagnosticsSettings')}&lt;/p&gt; |
| [419](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:419) | &lt;label className="flex items-center gap-2 rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 text-[13px] text-ds-ink"&gt; |
| [431](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:431) | &lt;label className="min-w-0 text-[12px] font-medium text-ds-muted"&gt; |
| [443](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:443) | className="mt-1 w-full rounded-xl border border-ds-border bg-ds-elevated px-3 py-2 text-[13px] text-ds-ink focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30" |
| [446](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:446) | &lt;span className="mt-1 block text-[11px] text-red-600 dark:text-red-300"&gt; |
| [451](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:451) | &lt;label className="min-w-0 text-[12px] font-medium text-ds-muted sm:col-span-2"&gt; |
| [466](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:466) | className="mt-1 w-full rounded-xl border border-ds-border bg-ds-elevated px-3 py-2 text-[13px] text-ds-ink focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30" |
| [469](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:469) | &lt;label className="min-w-0 text-[12px] font-medium text-ds-muted sm:col-span-2"&gt; |
| [478](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:478) | className="mt-1 w-full rounded-xl border border-ds-border bg-ds-elevated px-3 py-2 text-[13px] text-ds-ink focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30" |
| [481](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:481) | &lt;label className="min-w-0 text-[12px] font-medium text-ds-muted sm:col-span-2"&gt; |
| [491](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:491) | className="mt-1 w-full rounded-xl border border-ds-border bg-ds-elevated px-3 py-2 text-[13px] text-ds-ink focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30" |
| [500](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:500) | &lt;p className="text-[13px] font-semibold text-ds-ink"&gt;{t('runtimeDiagnosticsConfig')}&lt;/p&gt; |
| [501](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:501) | &lt;p className="mt-1 break-all font-mono text-[11px] text-ds-muted"&gt; |
| [508](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:508) | className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-ds-border bg-ds-elevated px-3 py-2 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover" |
| [518](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:518) | className="mt-3 min-h-0 flex-1 resize-none rounded-xl border border-ds-border bg-ds-elevated px-3 py-3 font-mono text-[12px] leading-5 text-ds-ink focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30" |
| [530](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:530) | className="rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] font-medium text-ds-ink transition hover:bg-ds-hover" |
| [539](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:539) | className="inline-flex items-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-55" |
| [548](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:548) | className="inline-flex items-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-55" |
| [557](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/RuntimeDiagnosticsDialog.tsx:557) | className="inline-flex items-center gap-1.5 rounded-xl bg-ds-userbubble px-4 py-2 text-[13px] font-semibold text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55" |

## components/SessionHeader.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [65](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:65) | className="block min-w-0 flex-1 truncate text-[13px] font-medium leading-6 tracking-[-0.01em] text-ds-ink" |
| [71](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:71) | &lt;span className="ds-session-header-meta ds-no-drag inline-flex h-7 shrink-0 select-none items-center gap-1.5 text-[12px] leading-none text-ds-faint"&gt; |
| [81](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:81) | &lt;div className="truncate text-[13px] font-medium leading-none text-ds-muted"&gt; |
| [95](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:95) | &lt;div className="ds-session-header-meta mb-1 flex min-w-0 items-center gap-2 text-[12.5px] font-medium text-ds-faint"&gt; |
| [105](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:105) | className="ds-session-header-title min-w-0 flex-1 rounded-2xl border border-ds-border bg-ds-elevated px-3.5 py-2 text-[21px] font-semibold tracking-[-0.02em] text-ds-ink focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/20" |
| [125](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:125) | className="ds-session-header-title min-w-0 truncate text-left text-[22px] font-semibold tracking-[-0.03em] text-ds-ink transition hover:text-accent" |
| [133](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:133) | &lt;div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 text-[12.5px] text-ds-faint"&gt; |
| [134](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:134) | &lt;span className="inline-flex items-center rounded-full border border-ds-border bg-ds-subtle px-2.5 py-1 font-medium capitalize text-ds-muted"&gt; |
| [148](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:148) | &lt;div className="text-[12.5px] font-medium uppercase tracking-[0.16em] text-ds-faint"&gt; |
| [152](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:152) | &lt;div className={`${showWorkspaceMeta ? 'mt-1' : ''} text-[20px] font-semibold tracking-[-0.02em] text-ds-ink`}&gt; |
| [155](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:155) | &lt;div className="ds-session-header-hint mt-1 text-[13.5px] text-ds-faint"&gt;{t('sessionHeaderHint')}&lt;/div&gt; |
| [159](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionHeader.tsx:159) | &lt;span className="ml-auto shrink-0 rounded-full bg-amber-500/18 px-3 py-1.5 text-[12.5px] font-semibold text-amber-950 dark:text-amber-100"&gt; |

## components/SessionQueries.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [114](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:114) | {notice ? &lt;span className="shrink-0 text-[11px] text-ds-muted"&gt;{notice}&lt;/span&gt; : |
| [123](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SessionQueries.tsx:123) | className="ds-session-query-row group flex h-9 w-full select-none items-center rounded-xl px-2.5 font-ui text-[13px] font-medium leading-6 tracking-[-0.01em] text-ds-ink transition-colors hover:bg-ds-hover focus-within:bg-ds-hover" |

## components/SettingsView.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [516](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:516) | &lt;p className="max-w-md text-sm text-red-700 dark:text-red-300"&gt;{msg}&lt;/p&gt; |
| [519](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:519) | className="inline-flex items-center justify-center rounded-xl bg-ds-userbubble px-4 py-2 text-center text-sm font-medium leading-none text-ds-userbubbleFg" |
| [573](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:573) | &lt;div className="text-[15px] font-semibold"&gt;{t('apiKeyRequiredTitle')}&lt;/div&gt; |
| [574](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:574) | &lt;p className="mt-1 text-[13px] leading-6 text-amber-900/90 dark:text-amber-100/90"&gt; |
| [582](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:582) | &lt;h1 className="text-2xl font-semibold tracking-tight text-ds-ink"&gt; |
| [597](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:597) | &lt;p className="mt-1 text-[14px] text-ds-muted"&gt; |
| [612](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:612) | className={`shrink-0 rounded-full px-3 py-1 text-[12px] font-medium ${ |
| [670](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:670) | className={`w-28 rounded-xl border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:outline-none focus:ring-1 ${ |
| [679](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:679) | &lt;p className="mt-1 text-[12px] text-red-700 dark:text-red-300"&gt;{portError}&lt;/p&gt; |
| [708](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:708) | &lt;div className="flex items-center gap-1 text-[14px] font-semibold text-ds-ink"&gt; |
| [711](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:711) | &lt;p className="mt-1 max-w-2xl text-[13px] leading-6 text-ds-muted"&gt; |
| [729](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:729) | className="w-full min-w-0 flex-1 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30" |
| [746](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:746) | &lt;p className="text-[13px] leading-5 text-amber-700 dark:text-amber-300"&gt; |
| [758](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:758) | &lt;span className="break-all font-mono text-[12px] text-ds-muted" title={logDirPath}&gt; |
| [768](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:768) | className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-1.5 text-center text-[13px] font-medium leading-none text-ds-ink shadow-sm transition hover:bg-ds-hover disabled:opacity-50" |
| [785](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:785) | &lt;p className="max-w-[280px] text-right text-[12px] text-red-700 dark:text-red-300"&gt; |
| [938](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:938) | &lt;div className="flex h-10 w-full min-w-0 items-center justify-center rounded-xl border border-ds-border bg-ds-card/70 px-3 text-center text-[14px] font-medium leading-none text-ds-muted shadow-sm"&gt; |
| [961](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:961) | &lt;p className="text-[13px] leading-6 text-ds-muted"&gt;{t('hooksDesc')}&lt;/p&gt; |
| [966](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:966) | className="w-full max-w-[280px] rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-muted shadow-sm" |
| [969](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:969) | &lt;code className="block truncate rounded-lg bg-ds-main/70 px-2 py-1 font-mono text-[12px] text-ds-ink"&gt; |
| [986](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:986) | &lt;p className="text-[13px] leading-6 text-ds-muted"&gt;{t('hooksActionsDesc')}&lt;/p&gt; |
| [993](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:993) | className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-center text-[13px] font-medium leading-none text-ds-ink shadow-sm transition hover:bg-ds-hover" |
| [1052](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1052) | className="min-w-0 flex-1 bg-transparent px-3 py-2 text-[14px] text-ds-ink focus:outline-none" |
| [1082](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1082) | &lt;div className={`rounded-xl border px-3 py-2 text-[12.5px] leading-5 ${className}`}&gt; |
| [1102](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1102) | &lt;h2 className="text-[16px] font-semibold text-ds-ink"&gt;{title}&lt;/h2&gt; |
| [1142](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1142) | ? 'mt-1 max-w-2xl text-[13px] leading-6 text-ds-muted' |
| [1143](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1143) | : 'mt-0.5 max-w-md text-pretty text-[13px] leading-relaxed text-ds-muted break-keep' |
| [1159](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1159) | &lt;div className="flex items-center gap-1 text-[14px] font-semibold text-ds-ink"&gt; |
| [1235](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1235) | &lt;span className="text-[13px] font-medium text-ds-ink"&gt;{title}&lt;/span&gt; |
| [1288](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1288) | &lt;p className="text-[13px] leading-relaxed text-ds-muted"&gt;{description}&lt;/p&gt; |
| [1295](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1295) | &lt;span className="text-[12px] font-semibold text-ds-muted"&gt; |
| [1298](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1298) | &lt;span className="min-w-0 truncate text-right text-[11px] text-ds-faint"&gt; |
| [1312](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1312) | &lt;span className="self-center text-[12px] text-ds-faint"&gt; |
| [1376](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1376) | &lt;div className="text-[13px] font-semibold text-ds-ink"&gt;{t('petMascotPickTitle')}&lt;/div&gt; |
| [1377](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1377) | &lt;div className="mt-0.5 text-[12px] leading-5 text-ds-muted"&gt; |
| [1394](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1394) | &lt;span className="block text-[12px] font-medium text-ds-faint"&gt; |
| [1397](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1397) | &lt;span className="block truncate text-[14px] font-semibold text-ds-ink"&gt; |
| [1425](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1425) | &lt;span className="min-w-0 truncate text-[12px] font-semibold text-ds-muted"&gt; |
| [1428](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1428) | &lt;span className="flex shrink-0 items-center gap-2 text-[11px] text-ds-faint"&gt; |
| [1446](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1446) | className={`inline-flex max-w-full items-center gap-1 rounded-lg border px-2 py-1 text-[11px] transition ${ |
| [1463](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1463) | className="w-full rounded-lg border border-ds-border bg-ds-card px-2.5 py-1.5 text-[12px] text-ds-ink placeholder:text-ds-faint focus:border-accent/40 focus:outline-none disabled:cursor-not-allowed" |
| [1473](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1473) | className="flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-45" |
| [1479](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1479) | &lt;span className="min-w-0 flex-1 truncate text-[13px] font-semibold"&gt; |
| [1482](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1482) | &lt;span className="shrink-0 text-[11px] text-ds-faint"&gt; |
| [1494](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1494) | className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-ds-border bg-ds-card px-2.5 py-1.5 text-center text-[12px] font-medium leading-none text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-wait disabled:opacity-60" |
| [1500](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/SettingsView.tsx:1500) | &lt;span className="min-w-0 truncate text-right text-[12px] text-red-700 dark:text-red-300"&gt; |

## components/Workbench.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [1538](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:1538) | &lt;p className="min-w-0 flex-1 text-[14px] leading-6 text-amber-950 dark:text-amber-100"&gt; |
| [1546](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:1546) | className="rounded-lg border border-amber-300/70 bg-white px-3 py-1 text-[12px] font-medium text-amber-950 transition hover:bg-amber-100/80 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-100 dark:hover:bg-amber-900/40" |
| [1553](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:1553) | className="rounded-lg border border-amber-300/70 bg-white px-3 py-1 text-[12px] font-medium text-amber-950 transition hover:bg-amber-100/80 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-100 dark:hover:bg-amber-900/40" |
| [1560](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:1560) | className="rounded-lg px-3 py-1 text-[12px] font-medium text-amber-900/80 transition hover:bg-amber-50/70 dark:text-amber-100 dark:hover:bg-amber-900/30" |
| [1718](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/Workbench.tsx:1718) | &lt;span className="inline-flex shrink-0 rounded-full bg-amber-500/16 px-1.5 py-px text-[10px] font-semibold leading-4 text-amber-950 dark:text-amber-100"&gt; |

## components/automation/AutomationCenter.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [422](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:422) | &lt;h1 className="text-[24px] font-semibold text-ds-ink"&gt; |
| [425](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:425) | &lt;p className="mt-1 text-[13px] text-ds-muted"&gt;{t('automationCenterDesc')}&lt;/p&gt; |
| [431](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:431) | className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-white transition hover:opacity-90 disabled:opacity-40" |
| [445](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:445) | className={`flex items-center gap-2 rounded-lg px-3 py-2.5 text-[12px] ${ |
| [463](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:463) | className={`relative pb-3 text-[14px] font-medium transition ${ |
| [474](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:474) | className={`relative pb-3 text-[14px] font-medium transition ${ |
| [493](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:493) | &lt;p className="mt-3 text-[14px] text-ds-muted"&gt;{t('automationNeedRuntime')}&lt;/p&gt; |
| [495](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:495) | className="mt-4 text-[13px] text-accent" |
| [514](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:514) | className="min-w-0 w-full bg-transparent py-2 pl-6 text-[13px] text-ds-ink outline-none placeholder:text-ds-faint" |
| [546](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:546) | &lt;div className="flex items-center justify-center gap-2 py-16 text-[13px] text-ds-muted"&gt; |
| [564](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:564) | leading={&lt;span className="text-[24px] leading-none"&gt;{tpl.icon}&lt;/span&gt;} |
| [614](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:614) | className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-ds-ink hover:bg-ds-hover" |
| [624](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:624) | className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-ds-ink hover:bg-ds-hover" |
| [634](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:634) | className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-ds-ink hover:bg-ds-hover" |
| [645](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:645) | className="flex w-full items-center gap-2 px-3 py-2 text-[12px] text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/20" |
| [680](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:680) | &lt;div className="flex items-center justify-center gap-2 py-16 text-[13px] text-ds-muted"&gt; |
| [685](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:685) | &lt;div className="py-16 text-center text-[13px] text-ds-muted"&gt; |
| [690](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:690) | &lt;div className="grid min-w-[700px] grid-cols-[minmax(140px,1.5fr)_80px_150px_150px_80px] gap-3 border-b border-ds-border-muted bg-ds-subtle/40 px-4 py-2 text-[11px] font-semibold text-ds-faint"&gt; |
| [700](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:700) | className="grid min-w-[700px] grid-cols-[minmax(140px,1.5fr)_80px_150px_150px_80px] items-center gap-3 border-b border-ds-border-muted px-4 py-3 text-[12px] last:border-b-0" |
| [703](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:703) | &lt;span className={`font-medium ${runTone(run.status)}`}&gt;{run.status}&lt;/span&gt; |
| [743](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:743) | &lt;h2 className="truncate text-[16px] font-semibold text-ds-ink"&gt;{selected.name}&lt;/h2&gt; |
| [744](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:744) | &lt;p className="mt-1 text-[12px] text-ds-muted"&gt; |
| [757](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:757) | className="inline-flex shrink-0 items-center gap-1 rounded-md border border-ds-border px-2.5 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover" |
| [767](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:767) | className="mb-5 inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[12px] font-medium text-ds-ink hover:bg-ds-hover" |
| [772](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:772) | &lt;h3 className="text-[12px] font-semibold text-ds-faint"&gt; |
| [775](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:775) | &lt;p className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-ds-ink"&gt; |
| [778](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:778) | &lt;dl className="mt-5 grid grid-cols-2 gap-3 border-y border-ds-border-muted py-4 text-[12px]"&gt; |
| [797](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:797) | &lt;h3 className="text-[13px] font-semibold text-ds-ink"&gt; |
| [810](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:810) | &lt;div className="py-8 text-center text-[12px] text-ds-muted"&gt; |
| [814](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:814) | &lt;div className="py-8 text-center text-[12px] text-ds-muted"&gt; |
| [819](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:819) | &lt;div key={run.id} className="py-3 text-[12px]"&gt; |
| [821](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:821) | &lt;span className={`font-semibold ${runTone(run.status)}`}&gt; |
| [851](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationCenter.tsx:851) | &lt;div className="mt-1 truncate font-mono text-[11px] text-ds-faint"&gt; |

## components/automation/AutomationListCard.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [92](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationListCard.tsx:92) | &lt;h3 className="truncate text-[15px] font-semibold text-ds-ink hover:text-accent"&gt; |
| [97](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationListCard.tsx:97) | &lt;h3 className="min-w-0 truncate text-[15px] font-semibold text-ds-ink"&gt;{title}&lt;/h3&gt; |
| [101](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationListCard.tsx:101) | &lt;p className="mt-2 line-clamp-2 overflow-hidden text-[13px] leading-5 text-ds-muted"&gt; |
| [107](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationListCard.tsx:107) | &lt;span className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px] text-ds-faint"&gt; |
| [111](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationListCard.tsx:111) | &lt;span className="shrink-0 rounded bg-ds-subtle px-1.5 py-0.5 text-[11px] text-ds-muted"&gt; |
| [118](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationListCard.tsx:118) | className="max-w-[28%] shrink truncate text-[12px] text-ds-faint" |
| [128](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationListCard.tsx:128) | className="shrink-0 rounded-md border border-ds-border px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink" |
| [144](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationListCard.tsx:144) | className="shrink-0 rounded-lg bg-accent/10 px-3 py-1.5 text-[12px] font-medium text-accent transition hover:bg-accent/20 disabled:opacity-50" |

## components/automation/AutomationTaskForm.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [247](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:247) | className="mb-4 inline-flex items-center gap-1.5 rounded-full border border-ds-border bg-ds-card px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [252](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:252) | &lt;div className="inline-flex items-center gap-2 rounded-full bg-accent/10 px-3 py-1 text-[12px] font-semibold text-accent"&gt; |
| [256](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:256) | &lt;h1 className="mt-3 text-[28px] font-semibold tracking-[-0.03em] text-ds-ink"&gt; |
| [259](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:259) | &lt;p className="mt-2 max-w-2xl text-[14px] leading-6 text-ds-muted"&gt; |
| [267](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:267) | className="inline-flex items-center gap-2 rounded-xl border border-amber-300/70 bg-amber-50 px-3 py-2 text-[13px] font-semibold text-amber-950 transition hover:bg-amber-100 dark:border-amber-700/70 dark:bg-amber-950/30 dark:text-amber-100" |
| [281](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:281) | &lt;div className="text-[15px] font-semibold"&gt; |
| [284](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:284) | &lt;div className="mt-1 text-[13px] opacity-80"&gt; |
| [295](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:295) | className="rounded-xl border border-emerald-500/30 bg-white/70 px-3 py-2 text-[13px] font-semibold transition hover:bg-white dark:bg-emerald-950/30" |
| [303](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:303) | className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-[13px] font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-60" |
| [316](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:316) | &lt;span className="text-[13px] font-semibold text-ds-ink"&gt;{t('automationPromptLabel')}&lt;/span&gt; |
| [321](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:321) | className="min-h-[132px] resize-y rounded-2xl border border-ds-border bg-ds-main px-4 py-3 text-[14px] leading-6 text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60" |
| [327](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:327) | &lt;span className="text-[13px] font-semibold text-ds-ink"&gt;{t('automationNameLabel')}&lt;/span&gt; |
| [332](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:332) | className="rounded-2xl border border-ds-border bg-ds-main px-4 py-3 text-[14px] text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60" |
| [336](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:336) | &lt;span className="text-[13px] font-semibold text-ds-ink"&gt;{t('automationStatusLabel')}&lt;/span&gt; |
| [350](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:350) | &lt;div className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-ds-ink"&gt; |
| [372](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:372) | className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60" |
| [381](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:381) | className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60" |
| [389](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:389) | className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 text-[14px] text-ds-ink outline-none focus:border-accent/60" |
| [399](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:399) | className={`rounded-full border px-3 py-1.5 text-[12px] font-semibold transition ${ |
| [415](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:415) | className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 font-mono text-[13px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-accent/60" |
| [418](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:418) | &lt;p className="text-[12px] leading-5 text-ds-faint"&gt;{scheduleHint}&lt;/p&gt; |
| [424](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:424) | &lt;div className="mb-3 text-[13px] font-semibold text-ds-ink"&gt;{t('automationDeliveryLabel')}&lt;/div&gt; |
| [446](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:446) | &lt;span className="text-[13px] text-ds-faint"&gt;{t('automationDeliveryNoneHint')}&lt;/span&gt; |
| [449](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:449) | &lt;span className="text-[13px] text-emerald-700 dark:text-emerald-300"&gt; |
| [453](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:453) | &lt;span className="flex flex-wrap items-center gap-2 text-[13px] text-amber-700 dark:text-amber-300"&gt; |
| [458](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:458) | className="rounded-md border border-amber-300/70 px-2 py-0.5 text-[12px] font-medium hover:bg-amber-100/60 dark:border-amber-700/60 dark:hover:bg-amber-950/30" |
| [466](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:466) | &lt;span className="text-[13px] text-emerald-700 dark:text-emerald-300"&gt; |
| [470](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:470) | &lt;span className="flex flex-wrap items-center gap-2 text-[13px] text-amber-700 dark:text-amber-300"&gt; |
| [475](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:475) | className="rounded-md border border-amber-300/70 px-2 py-0.5 text-[12px] font-medium hover:bg-amber-100/60 dark:border-amber-700/60 dark:hover:bg-amber-950/30" |
| [482](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:482) | &lt;span className="text-[13px] text-ds-muted"&gt; |
| [486](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:486) | &lt;span className="flex flex-wrap items-center gap-2 text-[13px] text-amber-700 dark:text-amber-300"&gt; |
| [491](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:491) | className="rounded-md border border-amber-300/70 px-2 py-0.5 text-[12px] font-medium hover:bg-amber-100/60 dark:border-amber-700/60 dark:hover:bg-amber-950/30" |
| [502](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:502) | &lt;summary className="cursor-pointer text-[13px] font-semibold text-ds-ink"&gt; |
| [507](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:507) | &lt;span className="text-[13px] font-semibold text-ds-ink"&gt;{t('automationWorkspaceLabel')}&lt;/span&gt; |
| [512](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:512) | className="rounded-2xl border border-ds-border bg-ds-card px-4 py-3 font-mono text-[13px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-accent/60" |
| [520](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:520) | className={`rounded-2xl border px-4 py-3 text-[13px] leading-6 ${ |
| [534](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:534) | className="rounded-xl border border-ds-border px-4 py-2 text-[13px] font-semibold text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [542](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/automation/AutomationTaskForm.tsx:542) | className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-white shadow-sm transition hover:bg-accent/90 disabled:opacity-60" |

## components/channels/ChannelCenter.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [56](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:56) | &lt;h2 className="text-[15.5px] font-semibold leading-snug tracking-[-0.01em] text-ds-ink"&gt; |
| [59](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:59) | &lt;p className="mt-1 text-[13px] leading-5 text-ds-muted"&gt;{description}&lt;/p&gt; |
| [61](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:61) | &lt;p className="mt-1 text-[11.5px] font-medium text-emerald-600 dark:text-emerald-400"&gt; |
| [65](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:65) | &lt;p className="mt-1 text-[11.5px] text-ds-faint"&gt;{t('channelNotConfigured')}&lt;/p&gt; |
| [145](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:145) | &lt;h1 className="text-[26px] font-bold text-ds-ink"&gt;{t('channelCenterTitle')}&lt;/h1&gt; |
| [146](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:146) | &lt;p className="mt-2 text-[14px] text-ds-muted"&gt;{t('channelCenterDesc')}&lt;/p&gt; |
| [147](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:147) | &lt;p className="mt-1 text-[13px] text-ds-faint"&gt;{t('channelLocalStorageHint')}&lt;/p&gt; |
| [150](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:150) | &lt;div className="mb-6 flex items-center gap-2 rounded-lg bg-blue-50 px-4 py-2.5 text-[13px] text-blue-700 dark:bg-blue-950/20 dark:text-blue-300"&gt; |
| [161](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:161) | &lt;div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-700 dark:text-red-200"&gt; |
| [167](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/ChannelCenter.tsx:167) | &lt;div className="flex items-center justify-center gap-2 py-20 text-[13px] text-ds-muted"&gt; |

## components/channels/FeishuChannelSetup.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [207](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:207) | &lt;div className="flex items-center gap-2 py-8 text-[13px] text-ds-muted"&gt; |
| [212](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:212) | &lt;p className="text-center text-[12px] text-ds-muted"&gt;{t('channelFeishuScanHint')}&lt;/p&gt; |
| [214](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FeishuChannelSetup.tsx:214) | &lt;p className="text-[11px] text-ds-faint"&gt; |

## components/channels/FieldHelpPopover.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [86](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FieldHelpPopover.tsx:86) | &lt;div className="rounded-xl border border-ds-border/70 bg-ds-card/92 px-3.5 py-3 text-[12px] leading-[1.55] text-ds-ink shadow-[0_12px_32px_rgba(15,23,42,0.12)] backdrop-blur-md dark:border-white/10 dark:bg-ds-elevated/94 dark:shadow-[0_14px_36px_rgba(0,0,0,0.34)]"&gt; |
| [87](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/FieldHelpPopover.tsx:87) | &lt;p className="text-[13px] font-medium text-ds-ink"&gt;{title}&lt;/p&gt; |

## components/channels/WecomChannelSetup.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [139](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/WecomChannelSetup.tsx:139) | className={`${CHANNEL_CONTROL} font-mono text-[12px]`} |

## components/channels/channel-setup-ui.ts

| 行号 | 声明／组件上下文 |
|---|---|
| [4](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/channel-setup-ui.ts:4) | `rounded-lg px-3 py-2 text-[13px] ${ |
| [13](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/channel-setup-ui.ts:13) | export const CHANNEL_LABEL = 'text-[13px] font-medium text-ds-ink' |
| [14](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/channel-setup-ui.ts:14) | export const CHANNEL_HINT = 'text-[13px] leading-6 text-ds-muted' |
| [16](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/channel-setup-ui.ts:16) | 'rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink outline-none placeholder:text-ds-faint focus:border-accent/60' |
| [19](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/channel-setup-ui.ts:19) | 'inline-flex items-center gap-1.5 rounded-lg bg-accent/10 px-3 py-2 text-[13px] font-medium text-accent hover:bg-accent/20 disabled:opacity-50' |
| [21](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/channels/channel-setup-ui.ts:21) | 'inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-main px-3 py-2 text-[13px] text-ds-ink hover:bg-ds-hover disabled:opacity-50' |

## components/chat/ApprovalBubble.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [110](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:110) | &lt;pre className="m-0 overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-ds-border bg-ds-card px-2.5 py-2 font-mono text-[12px] leading-5 text-ds-ink"&gt; |
| [173](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:173) | className={`ds-approval-bubble w-full overflow-hidden rounded-2xl border text-[13px] leading-5 ${ |
| [197](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:197) | &lt;span className="font-semibold tracking-[-0.02em] text-ds-ink"&gt;{title}&lt;/span&gt; |
| [199](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:199) | &lt;span className="rounded-md bg-ds-card px-1.5 py-0.5 font-mono text-[11px] leading-4 text-ds-muted"&gt; |
| [204](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:204) | &lt;span className="truncate font-mono text-[11px] text-ds-faint"&gt; |
| [209](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:209) | className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${statusBadgeClass(visualStatus)}`} |
| [214](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:214) | &lt;span className="text-[11px] font-medium text-ds-danger"&gt; |
| [221](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:221) | &lt;p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-5 text-ds-muted"&gt; |
| [225](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:225) | &lt;p className="mt-1.5 text-[12px] leading-5 text-ds-muted"&gt;{t('approvalPolicyHint')}&lt;/p&gt; |
| [233](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:233) | className="mt-2 inline-flex items-center gap-1 rounded-md text-[12px] font-medium text-ds-muted outline-none transition-colors hover:text-ds-ink" |
| [245](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:245) | &lt;p className="mt-2 text-[12px] text-ds-danger"&gt;{block.errorMessage}&lt;/p&gt; |
| [255](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:255) | className="grid grid-cols-[minmax(0,6.5rem)_minmax(0,1fr)] items-start gap-3 text-[12px]" |
| [269](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:269) | className="rounded-xl bg-ds-ink px-3 py-1.5 text-[12px] font-medium text-ds-canvas transition active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50" |
| [277](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:277) | className="rounded-xl border border-ds-border bg-ds-card px-3 py-1.5 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50" |
| [285](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:285) | className={`rounded-xl px-3 py-1.5 text-[12px] font-medium transition hover:bg-ds-hover disabled:pointer-events-none disabled:opacity-50 ${ |
| [294](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ApprovalBubble.tsx:294) | className="rounded-xl px-3 py-1.5 text-[12px] font-medium text-ds-faint transition hover:bg-ds-hover hover:text-ds-muted" |

## components/chat/ComposerApprovalPolicySelector.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [195](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerApprovalPolicySelector.tsx:195) | className={`ds-no-drag inline-flex shrink-0 select-none items-center px-1 font-semibold transition hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 ${ |
| [196](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerApprovalPolicySelector.tsx:196) | dense ? 'h-7 gap-1 text-[12px]' : 'h-9 gap-1.5 text-[13px]' |
| [218](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerApprovalPolicySelector.tsx:218) | &lt;p className="text-[13px] font-semibold leading-5 text-ds-ink"&gt; |
| [223](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerApprovalPolicySelector.tsx:223) | className="shrink-0 text-[12px] font-medium text-accent transition hover:opacity-80" |
| [259](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerApprovalPolicySelector.tsx:259) | className="block text-[13px] font-semibold leading-5" |
| [264](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerApprovalPolicySelector.tsx:264) | &lt;span className="mt-0.5 block text-[12px] leading-5 text-ds-muted"&gt; |

## components/chat/ComposerCommandPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [52](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:52) | 'inline-flex items-center justify-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-45' |
| [66](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:66) | &lt;div className="ds-composer-command-panel__title text-[14px] font-semibold text-ds-ink"&gt; |
| [69](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:69) | &lt;div className="mt-0.5 text-[11px] leading-5 text-ds-faint"&gt;{subtitle}&lt;/div&gt; |
| [91](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:91) | return &lt;div className={`rounded-xl border px-3 py-2 text-[11px] ${tone}`}&gt;{notice.text}&lt;/div&gt; |
| [160](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:160) | className={`flex w-full min-w-0 items-center justify-center rounded-xl px-3 py-2.5 text-center text-[13px] font-medium transition ${ |
| [167](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:167) | {options.length === 0 ? &lt;div className="text-[12px] text-ds-faint"&gt;No matching models.&lt;/div&gt; : null} |
| [204](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:204) | &lt;div className="text-[28px] font-semibold tabular-nums text-ds-ink"&gt;{Math.round(usage.percent)}%&lt;/div&gt; |
| [205](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:205) | &lt;div className="text-right text-[12px] text-ds-muted"&gt; |
| [215](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:215) | &lt;div className="text-[11px] text-ds-faint"&gt;{label}&lt;/div&gt; |
| [216](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:216) | &lt;div className="mt-1 text-[13px] font-medium tabular-nums text-ds-ink"&gt;{formatTokenCount(value)}&lt;/div&gt; |
| [229](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:229) | &lt;p className="text-[12px] leading-6 text-ds-muted"&gt; |
| [247](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:247) | {!activeThread ? &lt;div className="text-[11px] text-ds-faint"&gt;Start a thread first.&lt;/div&gt; : null} |
| [284](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:284) | &lt;span className="min-w-0"&gt;&lt;span className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"&gt;&lt;Plug className="h-4 w-4" /&gt;{server.id}&lt;/span&gt;&lt;span className="mt-1 block truncate font-mono text-[10px] text-ds-faint"&gt;{server.summary}&lt;/span&gt;&lt;/span&gt; |
| [288](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:288) | {servers.length === 0 ? &lt;div className="text-[12px] text-ds-faint"&gt;No MCP servers configured.&lt;/div&gt; : null} |
| [331](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:331) | &lt;div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"&gt;&lt;Package className="h-4 w-4" /&gt;{skill.name}&lt;/div&gt; |
| [332](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:332) | {skill.description ? &lt;div className="mt-1 text-[11px] text-ds-faint"&gt;{skill.description}&lt;/div&gt; : null} |
| [335](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:335) | {skills.length === 0 ? &lt;div className="text-[12px] text-ds-faint"&gt;No skills discovered.&lt;/div&gt; : null} |
| [349](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:349) | &lt;span className="flex min-w-0 items-center gap-2 truncate text-[12px] text-ds-ink"&gt; |
| [359](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:359) | {change.stats ? &lt;span className="shrink-0 text-[10px] tabular-nums"&gt;&lt;span className="text-ds-diff-added"&gt;+{change.stats.added}&lt;/span&gt; &lt;span className="text-ds-diff-removed"&gt;-{change.stats.removed}&lt;/span&gt;&lt;/span&gt; : null} |
| [372](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:372) | &lt;div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"&gt;&lt;GitFork className="h-4 w-4" /&gt;{activeThread?.title ?? 'No active thread'}&lt;/div&gt; |
| [373](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:373) | {activeThread ? &lt;div className="mt-1 text-[11px] text-ds-faint"&gt;{activeThread.model}&lt;/div&gt; : null} |
| [397](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:397) | &lt;div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"&gt;&lt;Settings2 className="h-4 w-4" /&gt;Hooks configuration&lt;/div&gt; |
| [398](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:398) | &lt;div className="mt-2 break-all font-mono text-[10px] text-ds-faint"&gt;{paths?.configPath ?? 'Loading…'} · [hooks]&lt;/div&gt; |
| [399](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerCommandPanel.tsx:399) | &lt;div className="mt-1 break-all font-mono text-[10px] text-ds-faint"&gt;{paths?.hooksDir ?? ''}&lt;/div&gt; |

## components/chat/ComposerLiveChangesHeader.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [52](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerLiveChangesHeader.tsx:52) | &lt;div className="mb-1.5 flex items-center gap-2 rounded-[12px] border border-ds-border-muted/70 bg-ds-card/70 px-3 py-2 text-[12.5px] text-ds-ink"&gt; |
| [54](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerLiveChangesHeader.tsx:54) | &lt;span className="min-w-0 flex-1 truncate font-medium"&gt;{label}&lt;/span&gt; |
| [66](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerLiveChangesHeader.tsx:66) | className="shrink-0 rounded-full bg-ds-hover px-2.5 py-0.5 text-[11.5px] font-semibold text-ds-ink transition hover:bg-ds-hover/80" |

## components/chat/ComposerVoiceBar.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [57](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerVoiceBar.tsx:57) | &lt;p className="text-[12px] font-medium text-ds-ink"&gt; |
| [61](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ComposerVoiceBar.tsx:61) | &lt;p className="text-[11px] tabular-nums text-ds-faint"&gt;{timerLabel}&lt;/p&gt; |

## components/chat/ContextUsageMeter.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [202](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ContextUsageMeter.tsx:202) | className={`overflow-hidden rounded-[12px] border border-ds-border bg-ds-elevated px-5 py-4 text-[12px] leading-[1.5] text-ds-muted shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)] ${ |
| [211](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ContextUsageMeter.tsx:211) | &lt;div className="text-[13px] font-medium tracking-[-0.005em] text-ds-ink"&gt; |
| [214](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ContextUsageMeter.tsx:214) | &lt;div className="mt-1 text-[11.5px] tabular-nums text-ds-faint"&gt; |
| [218](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ContextUsageMeter.tsx:218) | &lt;div className="shrink-0 pt-0.5 text-right text-[11.5px] tabular-nums text-ds-faint"&gt; |
| [287](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ContextUsageMeter.tsx:287) | &lt;p className="mt-3 border-t border-ds-border-muted/40 pt-2.5 text-[10.5px] leading-4 text-ds-faint"&gt; |

## components/chat/ElevationBubble.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [33](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:33) | className="ds-elevation-bubble rounded-2xl border border-ds-border bg-ds-card px-3.5 py-3 text-[13px] leading-6 text-ds-ink shadow-panel" |
| [37](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:37) | &lt;span className="font-semibold tracking-[-0.01em] text-ds-ink"&gt;{t('elevationTitle')}&lt;/span&gt; |
| [39](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:39) | &lt;span className="rounded-md bg-ds-subtle px-1.5 py-0.5 font-mono text-[11px] text-ds-muted"&gt; |
| [45](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:45) | &lt;div className="mt-1 text-[11px] text-ds-faint"&gt; |
| [49](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:49) | &lt;pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-ds-subtle px-3 py-2.5 font-mono text-[12.5px] leading-6 text-ds-ink"&gt; |
| [57](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:57) | className="rounded-[10px] bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white shadow-sm transition hover:brightness-[1.06] active:brightness-95" |
| [64](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:64) | className="rounded-[10px] px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [71](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:71) | &lt;div className="mt-2 text-[12px] font-medium text-ds-muted"&gt;{statusLabel}&lt;/div&gt; |
| [74](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ElevationBubble.tsx:74) | &lt;div className="mt-2 text-[12px] text-ds-danger"&gt;{block.errorMessage}&lt;/div&gt; |

## components/chat/EvolutionBubble.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [25](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:25) | className={`ds-evolution-bubble rounded-2xl border px-3.5 py-3 text-[13px] leading-6 shadow-panel ${ |
| [33](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:33) | &lt;span className="font-semibold tracking-[-0.01em] text-ds-ink"&gt;{t('evolutionTitle')}&lt;/span&gt; |
| [35](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:35) | &lt;span className="rounded-md bg-ds-subtle px-1.5 py-0.5 text-[11px] text-ds-muted"&gt; |
| [40](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:40) | &lt;p className="mt-2 whitespace-pre-wrap text-[14px] text-ds-ink"&gt;{block.summary}&lt;/p&gt; |
| [42](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:42) | &lt;div className="mt-2 font-mono text-[12px] text-ds-muted"&gt;{block.assetPath}&lt;/div&gt; |
| [45](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:45) | &lt;p className="mt-2 text-[12px] text-ds-danger"&gt;{block.errorMessage}&lt;/p&gt; |
| [51](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:51) | className="rounded-[10px] bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white shadow-sm transition hover:brightness-[1.06] active:brightness-95" |
| [58](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:58) | className="rounded-[10px] px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [65](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/EvolutionBubble.tsx:65) | &lt;p className="mt-2 text-[12px] font-medium text-ds-muted"&gt;{statusLabel}&lt;/p&gt; |

## components/chat/FileChip.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [234](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FileChip.tsx:234) | &lt;h2 className="text-[14px] font-semibold text-ds-ink"&gt;{t('fileReferenceChoose')}&lt;/h2&gt; |
| [235](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FileChip.tsx:235) | &lt;p className="mt-0.5 truncate text-[12px] text-ds-faint"&gt;{sourcePath}&lt;/p&gt; |
| [251](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FileChip.tsx:251) | className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] text-ds-ink hover:bg-ds-hover" |

## components/chat/FloatingComposer.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [337](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:337) | // so the runtime's leading-token focus detection still works unchanged. |
| [340](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:340) | // `@name ` on send so the runtime's leading-token connector detection fires. |
| [1499](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1499) | &lt;div className="inline-flex items-center gap-2 text-[13px] font-medium text-ds-ink"&gt; |
| [1503](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1503) | &lt;div className="text-[12px] text-ds-muted"&gt;{t('queuedMessagesHint')}&lt;/div&gt; |
| [1509](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1509) | className="flex min-w-0 max-w-full flex-wrap items-center gap-2 rounded-[12px] border border-ds-border-muted bg-ds-main/80 px-3 py-2 text-[13px] text-ds-ink" |
| [1519](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1519) | className="rounded-full border border-accent/25 bg-accent/10 px-2.5 py-1 text-[12px] font-medium text-accent transition hover:bg-accent/16" |
| [1531](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1531) | className="rounded-full border border-ds-border-muted px-2.5 py-1 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover" |
| [1538](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1538) | className="rounded-full border border-ds-border-muted px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [1575](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1575) | &lt;div className="shrink-0 px-3 pb-1.5 pt-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-ds-faint"&gt; |
| [1603](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1603) | &lt;span className="block text-[13px] font-semibold text-inherit"&gt; |
| [1606](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1606) | &lt;span className="mt-0.5 block truncate text-[11px] leading-4 text-ds-faint"&gt; |
| [1610](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1610) | &lt;span className="rounded-full border border-ds-border-muted px-2 py-0.5 text-[10px] font-semibold text-ds-faint"&gt; |
| [1618](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1618) | &lt;div className="rounded-[12px] border border-dashed border-ds-border-muted px-4 py-5 text-[13px] text-ds-faint"&gt; |
| [1646](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1646) | &lt;span className="block text-[13px] font-semibold text-inherit"&gt; |
| [1649](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1649) | &lt;span className="mt-0.5 block truncate text-[11px] leading-4 text-ds-faint"&gt; |
| [1654](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1654) | &lt;span className="rounded-full border border-ds-border-muted px-2 py-0.5 text-[10px] font-semibold text-ds-faint"&gt; |
| [1658](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1658) | &lt;span className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-semibold text-accent"&gt; |
| [1668](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1668) | &lt;div className="rounded-[12px] border border-dashed border-ds-border-muted px-4 py-5 text-[13px] text-ds-faint"&gt; |
| [1697](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1697) | className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] text-[9px] font-semibold tracking-tight ${badge.className}`} |
| [1708](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1708) | className="max-w-full text-[12px] font-medium" |
| [1710](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1710) | &lt;div className="mt-0.5 flex items-center gap-1 text-[11px] text-ds-faint"&gt; |
| [1777](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1777) | className="ds-no-drag group inline-flex max-w-full items-center gap-1.5 rounded-full border border-[rgba(79,124,255,0.4)] bg-[rgba(79,124,255,0.14)] px-2.5 py-1 text-[12px] font-medium text-[#4f7cff] transition hover:bg-[rgba(79,124,255,0.22)]" |
| [1800](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1800) | className="ds-no-drag group inline-flex max-w-full items-center gap-1.5 rounded-full border border-[rgba(16,185,129,0.4)] bg-[rgba(16,185,129,0.14)] px-2.5 py-1 text-[12px] font-medium text-[#10b981] transition hover:bg-[rgba(16,185,129,0.22)]" |
| [1822](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1822) | className="ds-no-drag inline-flex max-w-full items-center gap-1 rounded-full border border-[rgba(14,165,233,0.4)] bg-[rgba(14,165,233,0.14)] py-0.5 pl-2.5 pr-1 text-[12px] font-medium text-[#0ea5e9]" |
| [1973](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1973) | className="flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50" |
| [1987](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:1987) | className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${ |
| [2008](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2008) | className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${ |
| [2029](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2029) | className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${ |
| [2050](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2050) | className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] transition ${ |
| [2073](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2073) | className="h-0 overflow-hidden px-1.5 text-[12px] leading-5 whitespace-nowrap" |
| [2077](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2077) | &lt;p className="px-1.5 pb-1.5 pt-0.5 text-[12px] leading-5 text-ds-faint"&gt; |
| [2107](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2107) | className="flex w-full items-center justify-between gap-2.5 rounded-xl px-1.5 py-2 text-left text-[13px] text-ds-ink transition hover:bg-ds-hover" |
| [2160](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2160) | className="min-w-0 flex-1 bg-transparent text-[13px] text-ds-ink placeholder:text-ds-faint focus:outline-none" |
| [2169](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2169) | &lt;div className="px-1.5 py-3 text-[12px] text-ds-faint"&gt; |
| [2173](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2173) | &lt;div className="px-1.5 py-3 text-[12px] text-ds-faint"&gt; |
| [2192](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2192) | &lt;div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"&gt; |
| [2197](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2197) | &lt;div className="mt-0.5 line-clamp-2 pl-6 text-[11px] leading-4 text-ds-faint"&gt; |
| [2240](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2240) | className="min-w-0 flex-1 bg-transparent text-[13px] text-ds-ink placeholder:text-ds-faint focus:outline-none" |
| [2249](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2249) | &lt;div className="px-1.5 py-3 text-[12px] text-ds-faint"&gt; |
| [2300](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2300) | &lt;div className="flex items-start gap-2 text-[13px] font-medium text-ds-ink"&gt; |
| [2307](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2307) | &lt;span className="mt-0.5 shrink-0 rounded-full bg-ds-subtle px-1.5 py-0.5 text-[10px] font-medium text-ds-muted"&gt; |
| [2314](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2314) | className={`mt-0.5 line-clamp-2 pl-[26px] text-[11px] leading-4 ${ |
| [2364](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2364) | className="min-w-0 flex-1 bg-transparent text-[13px] text-ds-ink placeholder:text-ds-faint focus:outline-none" |
| [2373](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2373) | &lt;div className="px-1.5 py-3 text-[12px] text-ds-faint"&gt; |
| [2377](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2377) | &lt;div className="px-1.5 py-3 text-[12px] text-ds-faint"&gt; |
| [2402](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2402) | &lt;div className="flex items-center gap-2 text-[13px] font-medium text-ds-ink"&gt; |
| [2411](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2411) | &lt;span className="block truncate font-mono text-[10px] font-normal text-ds-faint"&gt; |
| [2417](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2417) | &lt;span className="ml-auto shrink-0 rounded-full bg-[rgba(168,85,247,0.16)] px-1.5 py-0.5 text-[10px] font-semibold text-[#a855f7]"&gt; |
| [2421](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2421) | &lt;span className="ml-auto shrink-0 text-[10px] font-medium text-ds-faint"&gt; |
| [2427](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2427) | &lt;div className="mt-0.5 line-clamp-2 pl-8 text-[11px] leading-4 text-ds-faint"&gt; |
| [2461](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2461) | className={`ds-no-drag inline-flex shrink-0 select-none items-center gap-1 px-1 font-semibold text-ds-ink ${ |
| [2462](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2462) | compactChrome ? 'h-7 text-[12px]' : 'h-9 gap-1.5 text-[13px]' |
| [2478](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2478) | className={`ds-no-drag group inline-flex max-w-[min(100%,240px)] shrink-0 select-none items-center gap-1 px-1 font-semibold text-[#a855f7] ${ |
| [2479](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2479) | compactChrome ? 'h-7 text-[12px]' : 'h-9 gap-1.5 text-[13px]' |
| [2639](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2639) | &lt;p className="px-3 pb-1 text-right text-[11.5px] text-amber-700 dark:text-amber-200 sm:px-4"&gt; |
| [2643](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/FloatingComposer.tsx:2643) | &lt;p className="px-3 pb-1 text-right text-[11.5px] text-ds-faint sm:px-4"&gt;{t('composerWorkspaceHint')}&lt;/p&gt; |

## components/chat/GitBranchPicker.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [377](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:377) | ? `ds-workspace-context-chip ds-workspace-context-chip--tray flex h-8 items-center gap-2 rounded-md px-2.5 py-1 text-left text-[15px] font-medium ${ |
| [383](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:383) | : 'flex h-8 max-w-[320px] items-center gap-2 rounded-lg px-2 text-[14px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink' |
| [392](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:392) | &lt;span className={`min-w-0 flex-1 truncate ${size === 'tray' ? 'text-[15px]' : ''}`}&gt; |
| [423](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:423) | &lt;span className="min-w-0 flex-1 break-words text-[13px] leading-5"&gt; |
| [444](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitBranchPicker.tsx:444) | className="mx-auto mt-2.5 flex min-h-8 w-fit items-center gap-1.5 rounded-lg border border-ds-border bg-transparent px-3 py-1.5 text-[12.5px] font-semibold text-ds-ink transition hover:bg-ds-hover active:scale-[0.98] disabled:opacity-45" |

## components/chat/GitCommitPopover.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [351](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:351) | &lt;h2 className="truncate text-[18px] font-semibold text-ds-ink"&gt; |
| [355](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:355) | &lt;p className="mt-1 text-[13px] leading-5 text-ds-muted"&gt; |
| [360](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:360) | &lt;p className="mt-0.5 text-[12px] text-ds-faint"&gt;{t('operationDockCommitFlowHint')}&lt;/p&gt; |
| [399](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:399) | &lt;span className="min-w-0 flex-1 text-[13px] font-medium text-ds-ink"&gt; |
| [402](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:402) | &lt;span className="shrink-0 text-[12px] tabular-nums text-ds-faint"&gt; |
| [412](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:412) | &lt;div className="mb-2 flex items-center justify-end gap-2 text-[12px]"&gt; |
| [435](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:435) | &lt;div className="flex items-center gap-2 py-6 text-[13px] text-ds-faint"&gt; |
| [440](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:440) | &lt;p className="py-4 text-[13px] leading-5 text-ds-faint"&gt; |
| [461](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:461) | &lt;span className="block truncate text-[13px] text-ds-ink"&gt; |
| [465](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:465) | &lt;span className="rounded-full bg-ds-hover px-1.5 py-0.5 text-[10px] font-medium text-ds-muted"&gt; |
| [468](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:468) | &lt;span className="rounded-full bg-ds-hover px-1.5 py-0.5 text-[10px] font-medium text-ds-muted"&gt; |
| [486](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:486) | &lt;span className="text-[13px] font-medium text-ds-ink"&gt; |
| [491](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:491) | className="inline-flex items-center gap-1 rounded-lg border border-ds-border px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-45" |
| [513](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:513) | className="w-full resize-none rounded-xl border border-ds-border bg-ds-card px-3 py-2.5 text-[13px] leading-5 text-ds-ink outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/20" |
| [523](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:523) | &lt;div className="flex gap-2 rounded-lg border border-amber-300/70 bg-amber-50 px-3 py-2 text-[12px] leading-5 text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/35 dark:text-amber-100"&gt; |
| [534](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:534) | className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [542](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:542) | className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50" |
| [565](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitCommitPopover.tsx:565) | className="block w-full px-3 py-2 text-left text-[13px] text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-45" |

## components/chat/GitLogDialog.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [229](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:229) | &lt;h2 className="truncate text-[18px] font-semibold text-ds-ink"&gt;{t('gitLogTitle')}&lt;/h2&gt; |
| [231](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:231) | &lt;div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 text-[12px]"&gt; |
| [232](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:232) | &lt;span className="inline-flex max-w-[360px] items-center gap-1.5 truncate font-medium text-ds-ink"&gt; |
| [238](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:238) | className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[11px] font-medium leading-none ${syncStatusClassName(syncStatus.tone)}`} |
| [250](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:250) | &lt;span className="text-[11px] tabular-nums text-ds-faint"&gt; |
| [285](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:285) | &lt;div className="flex min-h-[320px] gap-2 px-5 py-4 text-[13px] leading-5 text-amber-900 dark:text-amber-100"&gt; |
| [290](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:290) | &lt;div className="flex min-h-[320px] items-center justify-center px-5 text-[13px] text-ds-faint"&gt; |
| [296](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:296) | className="sticky top-0 z-10 grid h-8 items-center gap-x-3 border-b border-ds-border bg-ds-elevated px-4 text-[10px] font-semibold uppercase tracking-[0.08em] text-ds-faint" |
| [335](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:335) | className={`inline-flex rounded-md border px-1.5 py-0.5 text-[10px] font-semibold leading-none ${tagClassName(tag.tone)}`} |
| [343](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:343) | className={`min-w-0 truncate text-[13px] leading-5 ${ |
| [353](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:353) | &lt;span className="truncate text-[12px] tabular-nums text-ds-faint"&gt; |
| [357](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:357) | className={`truncate text-[12px] ${isMainline ? 'text-ds-muted' : 'text-ds-faint'}`} |
| [363](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:363) | className="truncate font-mono text-[11px] tabular-nums text-ds-faint" |
| [375](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GitLogDialog.tsx:375) | &lt;div className="flex min-h-[320px] items-center justify-center px-5 text-[13px] text-ds-faint"&gt; |

## components/chat/GreetingDateBar.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [129](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GreetingDateBar.tsx:129) | &lt;div className="flex items-center gap-2 text-[12.5px] font-medium text-ds-faint"&gt; |
| [134](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GreetingDateBar.tsx:134) | &lt;h2 className="min-w-0 text-[22px] font-semibold leading-tight tracking-[-0.02em] text-ds-ink sm:text-[24px]"&gt; |
| [286](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GreetingDateBar.tsx:286) | &lt;span className="text-[11px] font-medium uppercase tracking-[0.08em] text-ds-faint"&gt; |
| [289](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/GreetingDateBar.tsx:289) | &lt;span className="text-[20px] font-semibold tabular-nums leading-none text-ds-ink"&gt; |

## components/chat/InlineTodoBlock.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [29](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/InlineTodoBlock.tsx:29) | 'flex items-start gap-2 text-[14px] leading-6', |
| [36](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/InlineTodoBlock.tsx:36) | 'mt-1 shrink-0 text-[13px] font-semibold', |
| [105](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/InlineTodoBlock.tsx:105) | 'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold', |
| [118](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/InlineTodoBlock.tsx:118) | &lt;span className="ds-inline-todo__title text-[14px] font-semibold text-ds-ink"&gt; |
| [123](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/InlineTodoBlock.tsx:123) | 'text-[13.5px] font-medium', |
| [133](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/InlineTodoBlock.tsx:133) | &lt;span className="text-[13px] tabular-nums text-ds-faint"&gt; |
| [139](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/InlineTodoBlock.tsx:139) | &lt;span className="mt-1 block truncate text-[13px] text-ds-muted"&gt; |
| [172](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/InlineTodoBlock.tsx:172) | className="group flex w-fit max-w-full items-center gap-1 rounded-md py-0.5 text-left text-[13.5px] font-medium text-ds-faint transition hover:text-ds-muted" |

## components/chat/MessageTimeline.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [216](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:216) | className="mt-1 w-fit rounded-md border border-ds-border-muted bg-ds-card/90 px-2 py-0.5 text-[11px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [691](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:691) | className="ds-chip rounded-full px-4 py-2 text-[13px] font-medium text-ds-muted transition hover:text-ds-ink" |
| [755](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:755) | className="rounded-full px-3 py-1.5 text-[12.5px] font-medium text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink" |
| [861](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:861) | className="ds-chip mt-5 rounded-full px-5 py-2.5 text-[13px] font-medium text-ds-ink transition hover:text-ds-ink" |
| [966](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:966) | &lt;p className="text-[13.5px] leading-6 text-ds-faint"&gt; |
| [1124](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1124) | className="max-w-full rounded-full border border-ds-border-muted bg-ds-card/60 px-3 py-1 text-center text-[12px] text-ds-faint" |
| [1163](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1163) | className="rounded-md border border-ds-border-muted bg-ds-card/60 px-3 py-1.5 text-[12px] text-ds-faint" |
| [1316](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1316) | &lt;span className="ds-turn-change-summary__title block truncate text-[15px] font-semibold leading-5 tracking-[-0.01em] text-ds-ink"&gt; |
| [1324](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1324) | className="ds-turn-change-summary__view mt-0.5 inline-flex items-center gap-1 text-[13px] leading-5 text-ds-muted transition-colors duration-150 hover:text-ds-ink" |
| [1335](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1335) | className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-1.5 text-[14px] font-medium text-ds-ink transition-[background-color,color,transform] duration-150 hover:bg-ds-hover active:scale-[0.97] disabled:opacity-50" |
| [1346](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1346) | className="ds-turn-change-summary__review shrink-0 rounded-lg px-3 py-1.5 text-[14px] font-medium text-ds-ink transition-[background-color,border-color,transform] duration-150 hover:bg-ds-hover active:scale-[0.97]" |
| [1370](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1370) | className="ds-turn-change-summary__path min-w-0 flex-1 truncate text-left text-[14px] font-normal text-ds-ink disabled:cursor-default" |
| [1395](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1395) | &lt;span className="shrink-0 text-[14px] tabular-nums"&gt; |
| [1410](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1410) | className="ds-turn-change-summary__footer flex w-full items-center gap-2 px-4 py-2.5 text-left text-[14px] font-medium text-ds-ink transition-[background-color,color,transform] duration-150 hover:bg-ds-hover active:scale-[0.995]" |
| [1429](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1429) | &lt;p className="min-w-0 flex-1 text-[11.5px] leading-4 text-amber-700 dark:text-amber-300"&gt; |
| [1436](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1436) | className="rounded-md px-2 py-1 text-[11.5px] text-ds-muted transition-colors duration-150 hover:bg-ds-hover" |
| [1444](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1444) | className="rounded-md bg-amber-500/15 px-2 py-1 text-[11.5px] font-medium text-amber-800 transition-[background-color,transform] duration-150 hover:bg-amber-500/20 active:scale-[0.97] dark:text-amber-200 disabled:opacity-50" |
| [1450](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1450) | &lt;span className="min-w-0 flex-1 truncate text-[11.5px] text-ds-faint"&gt; |
| [1544](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1544) | className={`ds-work-meta-row group flex w-fit max-w-full items-center gap-1.5 rounded-md py-1 text-left text-[15px] font-medium text-ds-muted transition ${collapsible ? 'hover:opacity-85' : ''}`} |
| [1601](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1601) | className="ds-todo-event-row group flex w-fit max-w-full items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1.5 text-left text-[13.5px] text-emerald-800 transition hover:bg-emerald-500/15 dark:text-emerald-200" |
| [1604](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1604) | &lt;span className="min-w-0 truncate font-medium"&gt; |
| [1607](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1607) | &lt;span className="shrink-0 text-[12.5px] text-emerald-700/75 dark:text-emerald-200/70"&gt; |
| [1734](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1734) | &lt;span className="ds-subagent-summary__title text-[14px] font-semibold tracking-[-0.015em] text-ds-ink"&gt; |
| [1740](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1740) | 'text-[13px] text-ds-muted', |
| [1751](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1751) | className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center text-[15px] font-semibold leading-none tracking-tight text-ds-ink/70" |
| [1949](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1949) | className="rounded-xl border border-ds-border-muted/60 bg-ds-elevated/40 px-3 py-2 text-[12.5px] leading-5 transition hover:bg-ds-hover/30" |
| [1965](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1965) | &lt;span className="min-w-0 flex-1 truncate font-semibold tracking-[-0.01em] text-ds-ink"&gt; |
| [1974](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1974) | &lt;span className="shrink-0 whitespace-nowrap font-medium text-ds-muted"&gt; |
| [1978](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1978) | &lt;span className="shrink-0 whitespace-nowrap text-[11px] text-ds-faint"&gt; |
| [1987](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1987) | className="flex h-5 w-5 shrink-0 items-center justify-center text-[14px] font-semibold leading-none tracking-tight text-ds-ink/70" |
| [1997](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:1997) | className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [2011](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2011) | 'inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-ds-hover px-1 font-mono text-[10px] text-ds-muted', |
| [2012](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2012) | worker.status === 'failed' ? 'font-semibold text-ds-ink' : '', |
| [2044](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2044) | &lt;p className="whitespace-pre-wrap text-[13.5px] leading-6 text-ds-muted"&gt;{shown}&lt;/p&gt; |
| [2049](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2049) | className="mt-0.5 text-[11.5px] font-medium text-ds-faint transition hover:text-ds-muted" |
| [2180](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2180) | className="group flex w-fit max-w-full items-center gap-1.5 py-0.5 text-left text-[13.5px] font-medium text-ds-faint transition hover:text-ds-muted" |
| [2294](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2294) | &lt;div className="ds-process-assistant-md ds-markdown text-[13.5px] leading-6 text-ds-muted"&gt; |
| [2316](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2316) | return &lt;p className="text-[12px] text-ds-faint"&gt;{block.text}&lt;/p&gt; |
| [2351](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2351) | &lt;div className="flex items-center gap-1.5 text-[12px] font-medium text-ds-faint"&gt; |
| [2356](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2356) | &lt;p className="whitespace-pre-wrap text-[12.5px] leading-[1.55] text-ds-faint/70"&gt; |
| [2371](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2371) | &lt;p className="text-[13.5px] leading-6 text-ds-faint/85"&gt;{narration}&lt;/p&gt; |
| [2383](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2383) | className="ds-process-reasoning__toggle group flex w-fit items-center gap-1.5 py-0.5 text-left text-[14px] font-medium text-ds-muted transition hover:opacity-85" |
| [2395](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2395) | &lt;div className="ds-markdown text-[13.5px] leading-6 text-ds-faint/80"&gt; |
| [2423](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2423) | &lt;span className="truncate text-[12px] tracking-tight text-ds-faint/85"&gt; |
| [2750](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2750) | className="ds-user-message-edit-textarea block w-full min-w-0 resize-none break-words bg-transparent text-[15px] font-medium leading-[1.58] text-ds-ink outline-none [overflow-wrap:anywhere]" |
| [2757](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2757) | className="rounded-md px-3 py-1 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50" |
| [2766](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2766) | className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1 text-[13px] font-medium text-white shadow-sm transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50" |
| [2795](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2795) | className="ds-chat-rail-modal__title min-w-0 text-[16px] font-semibold leading-snug text-ds-ink" |
| [2809](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2809) | &lt;p className="text-[13px] leading-5 text-ds-muted"&gt; |
| [2815](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2815) | &lt;ul className="max-h-40 overflow-y-auto rounded-xl border border-ds-border-muted/70 bg-ds-main/30 px-3 py-2 font-mono text-[12px] leading-5 text-ds-ink"&gt; |
| [2824](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2824) | &lt;span className="shrink-0 rounded bg-amber-500/15 px-1.5 text-[10px] font-sans font-medium leading-4 text-amber-500"&gt; |
| [2828](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2828) | &lt;span className="shrink-0 rounded bg-ds-hover px-1.5 text-[10px] font-sans font-medium leading-4 text-ds-muted"&gt; |
| [2843](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2843) | &lt;p className="text-[12px] leading-5 text-amber-500"&gt; |
| [2848](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2848) | &lt;label className="flex cursor-pointer items-center gap-2 text-[12px] leading-5 text-ds-muted"&gt; |
| [2860](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2860) | &lt;p className="text-[12px] leading-5 text-ds-muted"&gt; |
| [2867](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2867) | &lt;p className="text-[12px] leading-5 text-amber-500"&gt; |
| [2878](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2878) | className="rounded-md px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [2887](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2887) | className="rounded-md px-3 py-1.5 text-[13px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-50" |
| [2898](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:2898) | className="rounded-md bg-accent px-3 py-1.5 text-[13px] font-medium text-white shadow-sm transition hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50" |
| [3097](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3097) | className="ds-subagent-bubble rounded-[14px] border border-ds-border-muted/70 bg-ds-card/55 px-4 py-4 text-[13px] leading-6 text-ds-ink shadow-[0_12px_30px_rgba(15,23,42,0.04)]" |
| [3100](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3100) | &lt;div className="flex items-center gap-2 font-semibold tracking-[-0.015em] text-ds-ink"&gt; |
| [3104](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3104) | &lt;span className="text-[14px] font-semibold leading-none text-ds-ink/70" aria-hidden&gt; |
| [3109](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3109) | &lt;span className="font-mono text-[11px] text-ds-faint"&gt;{block.agentId.slice(0, 10)}&lt;/span&gt; |
| [3111](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3111) | &lt;p className="mt-1 text-[12px] text-ds-muted"&gt;{statusLabel}&lt;/p&gt; |
| [3119](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3119) | 'inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-ds-hover px-1 font-mono text-[10px] text-ds-muted', |
| [3120](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3120) | worker.status === 'failed' ? 'font-semibold text-ds-ink' : '', |
| [3131](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3131) | &lt;p className="mt-2 whitespace-pre-wrap text-[13px] text-ds-ink"&gt;{block.summary}&lt;/p&gt; |
| [3182](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3182) | &lt;div className="ds-assistant-message-meta mt-1 flex min-h-5 min-w-0 items-center justify-between gap-3 text-[11.5px] text-ds-faint opacity-0 transition duration-150 group-hover/message:opacity-100"&gt; |
| [3195](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3195) | &lt;div id={`block-${block.id}`} className="ds-card-soft rounded-[12px] px-4 py-3 text-[13.5px] leading-6 text-ds-faint/80"&gt; |
| [3223](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/MessageTimeline.tsx:3223) | &lt;div className="ds-card-soft rounded-[12px] px-3 py-2 text-[13.5px] text-ds-muted"&gt; |

## components/chat/OperationContextDock.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [80](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:80) | 'group flex w-full items-center gap-2.5 rounded-[10px] px-1.5 py-1.5 text-left text-[13px] font-semibold leading-5 transition-colors' |
| [216](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:216) | 'min-w-0 flex-1 truncate text-[12.5px] leading-5 tracking-[-0.01em]', |
| [217](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:217) | active ? 'font-medium text-ds-ink' : 'font-medium text-ds-ink/85' |
| [229](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:229) | &lt;p className="px-1.5 pb-0.5 pt-1 text-[11px] font-medium tracking-[0.02em] text-ds-faint"&gt; |
| [265](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:265) | 'min-w-0 flex-1 truncate text-[12.5px] leading-5 tracking-[-0.01em]', |
| [266](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:266) | running ? 'ds-shiny-text font-medium text-ds-ink' : 'font-medium text-ds-ink/85' |
| [271](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:271) | &lt;span className="shrink-0 text-[11px] text-ds-faint"&gt; |
| [678](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:678) | &lt;span className="shrink-0 text-[11px] tabular-nums text-ds-faint"&gt; |
| [705](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:705) | &lt;span className="ml-auto shrink-0 text-[12px] tabular-nums text-ds-muted"&gt; |
| [710](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:710) | &lt;span className="ml-auto shrink-0 text-[12px] text-ds-faint"&gt;{t('operationDockNoChanges')}&lt;/span&gt; |
| [725](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:725) | &lt;p className="text-[13px] leading-5 text-ds-faint"&gt;{t('gitBranchLoading')}&lt;/p&gt; |
| [727](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:727) | &lt;p className="text-[13px] leading-5 text-ds-faint"&gt;{t('gitNoBranch')}&lt;/p&gt; |
| [760](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:760) | &lt;span className="text-[11px] tabular-nums text-ds-faint"&gt; |
| [809](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:809) | 'flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold tabular-nums', |
| [821](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:821) | 'min-w-0 flex-1 text-[13px] leading-5', |
| [826](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:826) | ? 'font-semibold text-ds-ink' |
| [851](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:851) | &lt;p className="mt-1 text-[13px] leading-5 text-ds-faint"&gt;{t('contextRailEmptyProcess')}&lt;/p&gt; |
| [864](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:864) | &lt;span className="shrink-0 text-[11px] tabular-nums text-ds-faint"&gt; |
| [902](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/OperationContextDock.tsx:902) | &lt;p className="mt-1 text-[13px] leading-5 text-ds-faint"&gt;{t('contextRailEmptyTasks')}&lt;/p&gt; |

## components/chat/ProjectContextMenu.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [87](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ProjectContextMenu.tsx:87) | 'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-ds-ink transition-colors duration-150 hover:bg-ds-hover' |
| [135](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ProjectContextMenu.tsx:135) | className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-red-600 transition-colors duration-150 hover:bg-red-500/10 dark:text-red-400" |

## components/chat/ProjectContextPicker.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [480](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ProjectContextPicker.tsx:480) | size === 'tray' ? (isTemporary ? 'leading-5' : 'text-[15px]') : '' |

## components/chat/PublishConflictBanner.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [136](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:136) | &lt;div className="ds-no-drag mx-2 mb-2 flex items-center justify-between rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[12px] text-emerald-700 dark:text-emerald-300 sm:mx-3"&gt; |
| [145](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:145) | className="ds-no-drag mx-2 mb-2 flex items-center gap-2 px-3 py-1 text-[12px] text-ds-muted sm:mx-3" |
| [161](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:161) | &lt;p className="text-[13px] font-medium leading-5 text-ds-ink"&gt; |
| [164](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:164) | &lt;p className="mt-0.5 text-[12px] leading-5 text-ds-muted"&gt; |
| [170](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:170) | &lt;ul className="mt-2 max-h-28 overflow-y-auto font-mono text-[12px] leading-5 text-ds-ink"&gt; |
| [184](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:184) | &lt;p className="mt-2 inline-flex items-center gap-2 text-[12px] text-ds-muted"&gt; |
| [190](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:190) | &lt;p className="mt-2 text-[12px] text-red-600 dark:text-red-300"&gt; |
| [199](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:199) | &lt;p className="text-[12px] leading-5 text-ds-ink"&gt; |
| [211](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:211) | className="rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50" |
| [222](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:222) | className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50" |
| [239](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:239) | className="rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.98] disabled:opacity-50" |
| [248](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:248) | className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50" |
| [260](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:260) | className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50" |
| [274](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:274) | &lt;p className="text-[12px] font-medium leading-5 text-ds-ink"&gt; |
| [277](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:277) | &lt;p className="text-[12px] leading-5 text-ds-muted"&gt; |
| [282](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:282) | className="mt-1 text-[12px] text-red-600 dark:text-red-300" |
| [295](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:295) | className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50" |
| [311](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:311) | &lt;p className="text-[12px] font-medium leading-5 text-ds-ink"&gt; |
| [314](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:314) | &lt;p className="text-[12px] leading-5 text-ds-muted"&gt; |
| [323](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:323) | className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50" |
| [339](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:339) | &lt;p className="text-[13px] font-medium leading-5 text-ds-ink"&gt; |
| [342](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:342) | &lt;p className="mt-0.5 text-[12px] leading-5 text-ds-muted"&gt; |
| [345](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:345) | &lt;ul className="mt-2 max-h-28 overflow-y-auto font-mono text-[12px] leading-5 text-ds-ink"&gt; |
| [358](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:358) | &lt;p className="mt-2 text-[12px] text-red-600 dark:text-red-300"&gt; |
| [363](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:363) | &lt;p className="mt-2 inline-flex items-center gap-2 text-[12px] text-ds-muted"&gt; |
| [372](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:372) | className="mr-auto rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.98]" |
| [380](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:380) | className="rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.98] disabled:opacity-50" |
| [388](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/PublishConflictBanner.tsx:388) | className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50" |

## components/chat/QueryTrail.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [565](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/QueryTrail.tsx:565) | className="line-clamp-2 text-xs font-medium leading-snug text-ds-ink" |
| [569](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/QueryTrail.tsx:569) | className="mt-1 line-clamp-3 text-xs leading-snug text-ds-muted" |

## components/chat/ReasoningEffortSelector.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [141](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ReasoningEffortSelector.tsx:141) | if (label) label.style.fontSize = '12px' |
| [145](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ReasoningEffortSelector.tsx:145) | if (label) label.style.fontSize = '' |

## components/chat/SharedCodeBlock.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [64](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SharedCodeBlock.tsx:64) | fontStyle: 'italic' |

## components/chat/Sidebar.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [298](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/Sidebar.tsx:298) | &lt;kbd className="ds-kbd ds-sidebar-link-shortcut hidden items-center gap-0.5 rounded-md px-1.5 py-0.5 font-mono font-medium text-ds-faint group-hover:inline-flex group-focus-within:inline-flex"&gt; |

## components/chat/SidebarChatsSection.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [272](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx:272) | className="shrink-0 rounded-md px-1.5 py-1 text-[12px] text-ds-muted transition-colors hover:bg-ds-hover hover:text-ds-ink disabled:opacity-40" |
| [356](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx:356) | className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-ds-ink transition-colors duration-150 hover:bg-ds-hover disabled:opacity-40" |
| [368](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx:368) | className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-ds-ink transition-colors duration-150 hover:bg-ds-hover disabled:opacity-40" |
| [380](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx:380) | className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-ds-ink transition-colors duration-150 hover:bg-ds-hover disabled:opacity-40" |
| [392](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx:392) | className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-red-600 transition-colors duration-150 hover:bg-red-500/10 disabled:opacity-40 dark:text-red-400" |
| [409](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarChatsSection.tsx:409) | &lt;div className="px-2.5 py-2 text-[13px] text-ds-faint"&gt;{t('sidebarChatsEmpty')}&lt;/div&gt; |

## components/chat/SidebarProjectsSection.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [231](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:231) | 'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-ds-ink transition-colors duration-150 hover:bg-ds-hover disabled:opacity-40' |
| [244](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:244) | className="shrink-0 rounded-md px-1.5 py-1 text-[12px] text-ds-muted transition-colors hover:bg-ds-hover hover:text-ds-ink disabled:opacity-40" |
| [400](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:400) | &lt;span className="min-w-0 flex-1 truncate tracking-[-0.01em]"&gt; |
| [426](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:426) | &lt;span className="min-w-0 flex-1 truncate tracking-[-0.01em]"&gt; |
| [455](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:455) | className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-red-600 transition-colors duration-150 hover:bg-red-500/10 disabled:opacity-40 dark:text-red-400" |
| [1143](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:1143) | className="ds-sidebar-thread-row flex w-full min-w-0 items-center gap-1.5 px-2 py-1 text-left text-[12.5px] text-ds-faint transition-colors duration-150 hover:bg-ds-hover/70 hover:text-ds-ink" |
| [1198](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:1198) | &lt;div className="px-1 py-3 text-[13px] text-ds-faint"&gt;{t('sidebarSearchNoResults')}&lt;/div&gt; |
| [1842](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:1842) | &lt;p className="text-[16px] font-semibold text-ds-ink"&gt;{t('sidebarEmptyTitle')}&lt;/p&gt; |
| [1843](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/SidebarProjectsSection.tsx:1843) | &lt;p className="mt-1.5 text-[14px] leading-5 text-ds-muted"&gt; |

## components/chat/StepFlow.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [120](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:120) | &lt;span className="text-[9px] font-semibold leading-none text-ds-ink/75"&gt;{style.mark}&lt;/span&gt; |
| [225](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:225) | 'block tracking-[-0.01em]', |
| [230](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:230) | ? 'text-[12px] leading-5' |
| [231](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:231) | : 'text-[13.5px] leading-6' |
| [237](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:237) | ? 'text-[12px] leading-5' |
| [238](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:238) | : 'text-[13px] leading-5' |
| [243](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:243) | ? 'text-[11.5px] leading-4' |
| [244](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:244) | : 'text-[12.5px] leading-5' |
| [255](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:255) | compact ? 'text-[10.5px] leading-4' : 'text-[11px] leading-4' |
| [266](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:266) | compact ? 'text-[10.5px] leading-4' : 'text-[11px] leading-4' |
| [274](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:274) | &lt;span className="mt-0.5 block truncate text-[10.5px] tabular-nums text-ds-faint"&gt; |
| [304](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:304) | className="flex gap-2 py-0.5 text-[11.5px] leading-[1.45]" |
| [306](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:306) | &lt;span className="shrink-0 font-medium text-ds-faint"&gt; |
| [319](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:319) | &lt;div className="px-3 pb-1 pt-2 text-[10.5px] font-semibold tracking-[0.02em] text-ds-muted"&gt; |
| [322](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:322) | &lt;pre className="max-h-44 overflow-auto px-3 pb-2.5 font-mono text-[11.5px] leading-[1.45] text-ds-ink/90 whitespace-pre-wrap break-words"&gt; |
| [327](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:327) | &lt;summary className="cursor-pointer text-[11px] font-medium text-ds-faint hover:text-ds-muted"&gt; |
| [374](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:374) | &lt;div className="mb-0.5 text-[10px] font-semibold text-ds-faint"&gt;{label}&lt;/div&gt; |
| [375](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:375) | &lt;pre className="max-h-36 overflow-auto font-mono text-[11px] leading-[1.45] text-ds-ink/85 whitespace-pre-wrap break-words"&gt; |
| [397](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/StepFlow.tsx:397) | &lt;p className="px-1 py-2 text-[12.5px] leading-5 text-ds-faint"&gt; |

## components/chat/TaskSuggestionHero.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [41](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:41) | &lt;div className="flex shrink-0 items-center gap-x-2.5 text-[10.5px] font-medium tabular-nums text-ds-faint"&gt; |
| [63](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:63) | className="inline-flex min-w-0 max-w-[104px] shrink-0 items-center gap-0.5 rounded-md border border-accent/12 bg-accent/5 px-1.5 py-0.5 text-[10px] font-medium text-ds-muted" |
| [65](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:65) | &lt;span className="shrink-0 font-semibold text-accent"&gt;#&lt;/span&gt; |
| [107](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:107) | 'inline-flex h-4 shrink-0 items-center rounded-md border px-1 text-[8px] font-semibold tabular-nums', |
| [113](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:113) | &lt;h3 className="min-w-0 flex-1 truncate text-[14.5px] font-semibold leading-tight tracking-[-0.01em] text-ds-ink"&gt; |
| [114](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:114) | {owner ? &lt;span className="font-medium text-ds-muted"&gt;{owner}&lt;/span&gt; : null} |
| [118](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:118) | &lt;p className="mt-1.5 w-full min-w-0 shrink-0 truncate text-[12px] leading-normal text-ds-muted"&gt; |
| [235](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:235) | &lt;h2 className="text-[16px] font-semibold tracking-[-0.02em] text-ds-ink"&gt; |
| [244](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:244) | segmentClassName="px-2.5 py-1 text-[11px]" |
| [270](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:270) | &lt;p className="text-[13px] font-medium text-ds-ink"&gt;{t('trendingError')}&lt;/p&gt; |
| [271](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:271) | &lt;p className="mt-1 text-[12px] leading-5 text-ds-muted"&gt;{error}&lt;/p&gt; |
| [300](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:300) | &lt;p className="max-w-sm text-[20px] font-semibold tracking-[-0.03em] text-ds-ink"&gt; |
| [303](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:303) | &lt;p className="mt-2 max-w-[520px] text-[14px] leading-6 text-ds-muted"&gt;{t('runtimeOfflineHeroSub')}&lt;/p&gt; |
| [307](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:307) | className="ds-chip rounded-full px-4 py-2 text-[12.5px] font-medium text-ds-ink" |
| [314](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:314) | className="ds-chip-muted rounded-full px-4 py-2 text-[12.5px] font-medium text-ds-muted" |
| [321](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/TaskSuggestionHero.tsx:321) | className="ds-chip-muted rounded-full px-4 py-2 text-[12.5px] font-medium text-ds-muted" |

## components/chat/ThreadContextMenu.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [113](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ThreadContextMenu.tsx:113) | 'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-ds-ink transition-colors duration-150 hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent' |
| [209](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ThreadContextMenu.tsx:209) | className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-red-600 transition-colors duration-150 hover:bg-red-500/10 dark:text-red-400" |

## components/chat/ThreadHoverCard.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [80](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ThreadHoverCard.tsx:80) | &lt;span className="min-w-0 flex-1 truncate text-[13.5px] leading-none text-ds-ink"&gt; |
| [89](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/ThreadHoverCard.tsx:89) | &lt;div className="flex h-6 items-center gap-2.5 rounded-lg px-2.5 text-[13px] leading-none text-ds-muted"&gt; |

## components/chat/UserInputBubble.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [66](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:66) | &lt;div className="flex items-center gap-1.5 text-[12px] leading-4 text-ds-faint"&gt; |
| [72](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:72) | &lt;span className="font-medium tracking-[-0.01em]"&gt;{t('userInputAnswered')}&lt;/span&gt; |
| [78](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:78) | &lt;div className="text-[11px] leading-4 text-ds-faint"&gt;{row.header}&lt;/div&gt; |
| [79](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:79) | &lt;div className="mt-0.5 whitespace-pre-wrap break-words text-[13px] font-medium leading-5 tracking-[-0.01em] text-ds-ink"&gt; |
| [86](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:86) | &lt;p className="mt-1 pl-5 text-[12px] text-ds-faint"&gt;{t('userInputSubmitted')}&lt;/p&gt; |
| [99](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:99) | className={`flex items-center gap-1.5 text-[12px] leading-5 ${ |
| [214](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:214) | className="ds-user-input-pending w-full overflow-hidden rounded-2xl border border-ds-border bg-ds-subtle p-4 text-[13px] leading-5 text-ds-ink" |
| [230](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:230) | &lt;span className="min-w-0 flex-1 truncate font-semibold tracking-[-0.02em] text-ds-ink"&gt; |
| [234](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:234) | &lt;span className="shrink-0 font-mono text-[11px] text-ds-faint"&gt; |
| [238](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:238) | &lt;span className="shrink-0 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-400"&gt; |
| [243](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:243) | &lt;span className="max-w-[8rem] truncate font-mono text-[11px] text-ds-faint"&gt; |
| [260](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:260) | &lt;div className="text-[11px] font-medium text-ds-muted"&gt;{question.header}&lt;/div&gt; |
| [286](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:286) | &lt;span className="block text-[13px] font-medium text-ds-ink"&gt; |
| [290](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:290) | &lt;span className="mt-0.5 block text-[11px] leading-[1.35] text-ds-faint"&gt; |
| [322](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:322) | &lt;span className="block text-[13px] font-medium text-ds-ink"&gt; |
| [325](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:325) | &lt;span className="mt-0.5 block text-[11px] leading-[1.35] text-ds-faint"&gt; |
| [338](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:338) | className="mt-1 h-10 w-full rounded-xl border-0 bg-ds-card px-3 text-[13px] text-ds-ink outline-none ring-0 placeholder:text-ds-faint focus:bg-ds-card" |
| [360](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/UserInputBubble.tsx:360) | className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-full bg-ds-ink px-3 text-[12px] font-medium text-ds-canvas transition hover:opacity-90 disabled:pointer-events-none disabled:opacity-40" |

## components/chat/composer-notice.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [14](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/composer-notice.tsx:14) | className={`max-w-[min(100%,560px)] rounded-xl border px-3 py-2 text-[12px] leading-5 ${className}`} |

## components/chat/reasoning-effort-selector.js

| 行号 | 声明／组件上下文 |
|---|---|
| [95](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:95) | font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif; |
| [96](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:96) | -webkit-font-smoothing: antialiased; |
| [142](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:142) | font-size: 12px; |
| [154](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:154) | font: inherit; |
| [236](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:236) | font-size: 14px; |
| [237](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:237) | font-weight: 600; |
| [249](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:249) | font-weight: 400; |
| [326](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:326) | font-size: 13px; |
| [327](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:327) | font-weight: 600; |
| [354](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:354) | font-size: 12px; |
| [355](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:355) | font-weight: 500; |
| [359](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:359) | .intensity-value.is-ultra { color: var(--ultra-text); font-weight: 600; } |
| [361](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:361) | font-size: 11px; |
| [362](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:362) | font-weight: 500; |
| [368](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:368) | font-size: 11px; |
| [369](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:369) | font-weight: 600; |
| [394](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:394) | font: inherit; |
| [395](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:395) | font-size: 13px; |
| [396](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:396) | font-weight: 500; |
| [402](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:402) | font-weight: 400; |
| [406](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:406) | font-size: 12.5px; |
| [430](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:430) | font-size: 13px; |
| [431](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:431) | font-weight: 500; |
| [445](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:445) | font-weight: 600; |
| [488](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:488) | font-size: 12px; |
| [489](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:489) | font-weight: 500; |
| [493](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:493) | .model-effort.is-ultra { color: var(--ultra-text); font-weight: 600; } |
| [526](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:526) | font-size: 13px; |
| [527](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/reasoning-effort-selector.js:527) | font-weight: 500; |

## components/chat/task-status.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [37](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/task-status.tsx:37) | &lt;span className="text-[13px] font-semibold leading-none text-ds-ink/70"&gt;!&lt;/span&gt; |

## components/chat/tool/lazy-full-output.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [51](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/lazy-full-output.tsx:51) | &lt;pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-ds-ink"&gt; |
| [55](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/lazy-full-output.tsx:55) | &lt;div className="mt-1 text-[11px] text-ds-muted"&gt; |
| [67](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/lazy-full-output.tsx:67) | className="absolute bottom-1 right-1 rounded-md border border-ds-border-muted bg-ds-card/90 px-2 py-0.5 text-[11px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50" |

## components/chat/tool/primitives/header.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [64](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/primitives/header.tsx:64) | 'ds-tool-header-row__label shrink-0 font-mono font-medium text-ds-muted', |

## components/chat/tool/primitives/panel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [25](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/primitives/panel.tsx:25) | 'overflow-hidden rounded-[10px] border border-ds-border-muted/60 bg-ds-card/50 px-3 py-2 text-[12px] leading-5 text-ds-ink', |
| [43](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/primitives/panel.tsx:43) | &lt;div className={cn('px-3 py-2 text-[12px] text-ds-faint', className)}&gt;{message}&lt;/div&gt; |

## components/chat/tool/primitives/status.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [45](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/primitives/status.tsx:45) | &lt;span className="text-[0.5625rem] font-medium tracking-[0.02em] text-amber-700 dark:text-amber-400"&gt; |
| [51](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/primitives/status.tsx:51) | className="text-[0.5625rem] tracking-[0.05em] leading-none" |
| [56](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/primitives/status.tsx:56) | className="flex h-3.5 w-3.5 shrink-0 items-center justify-center text-[13px] font-semibold leading-none tracking-tight text-ds-ink/70" |
| [64](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/primitives/status.tsx:64) | &lt;span aria-hidden className="text-[0.5625rem]"&gt; |

## components/chat/tool/renderers/file-edit.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [37](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/file-edit.tsx:37) | &lt;div className="flex items-center gap-2 px-3 py-2 text-[12px] text-ds-muted"&gt; |

## components/chat/tool/renderers/list.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [70](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/list.tsx:70) | return &lt;div className="px-3 py-2 text-[12px] text-ds-faint"&gt;⠋ searching…&lt;/div&gt; |
| [81](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/list.tsx:81) | &lt;div className="max-h-72 overflow-auto bg-ds-subtle/50 py-1 font-mono text-[12px] leading-[1.55]"&gt; |
| [114](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/list.tsx:114) | &lt;p className="px-3 py-1 text-[11px] text-ds-faint"&gt;+{hidden} more lines&lt;/p&gt; |

## components/chat/tool/renderers/read.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [22](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/read.tsx:22) | &lt;span className="text-[12px] text-ds-faint"&gt;⠋ reading…&lt;/span&gt; |
| [48](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/read.tsx:48) | &lt;pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words px-3 pb-2.5 pt-1 font-mono text-[12px] leading-6 text-ds-ink"&gt; |

## components/chat/tool/renderers/shell.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [25](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/shell.tsx:25) | 'overflow-auto bg-ds-subtle/60 px-3 py-2 font-mono text-[12px] leading-[1.55]', |
| [56](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/shell.tsx:56) | &lt;div className="flex items-center gap-2 px-3 pb-2 text-[11px] tabular-nums text-ds-faint"&gt; |

## components/chat/tool/renderers/subagent.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [88](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/subagent.tsx:88) | &lt;span className="shrink-0 font-mono text-[0.6875rem] font-medium text-ds-muted"&gt; |
| [93](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/renderers/subagent.tsx:93) | className="min-w-0 flex-1 truncate text-[13px] text-ds-faint" |

## components/chat/tool/tool-card.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [185](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-card.tsx:185) | &lt;pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-ds-ink"&gt; |
| [193](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-card.tsx:193) | &lt;pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-ds-ink"&gt; |

## components/chat/tool/tool-gate-bar.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [44](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-gate-bar.tsx:44) | &lt;p className="text-[12px] font-medium text-ds-ink"&gt;{t('approvalAskTitle')}&lt;/p&gt; |
| [45](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-gate-bar.tsx:45) | &lt;p className="mt-0.5 text-[11px] leading-5 text-ds-muted"&gt;{t('approvalPolicyHint')}&lt;/p&gt; |
| [50](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-gate-bar.tsx:50) | className="rounded-xl bg-ds-ink px-3 py-1.5 text-[12px] font-medium text-ds-canvas transition active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50" |
| [58](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-gate-bar.tsx:58) | className="rounded-xl border border-ds-border bg-ds-card px-3 py-1.5 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50" |
| [66](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-gate-bar.tsx:66) | className="rounded-xl px-3 py-1.5 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:pointer-events-none disabled:opacity-50" |
| [83](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-gate-bar.tsx:83) | &lt;p className="text-[12px] font-medium text-ds-ink"&gt;{t('elevationTitle')}&lt;/p&gt; |
| [84](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-gate-bar.tsx:84) | &lt;p className="mt-0.5 text-[11px] leading-5 text-ds-muted"&gt;{block.reason}&lt;/p&gt; |
| [89](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-gate-bar.tsx:89) | className="rounded-xl bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition hover:brightness-[1.06] disabled:pointer-events-none disabled:opacity-50" |
| [101](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/chat/tool/tool-gate-bar.tsx:101) | className="rounded-xl px-3 py-1.5 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:pointer-events-none disabled:opacity-50" |

## components/extensions/AddMcpServerDialog.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [134](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:134) | 'h-10 w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 text-[14px] text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30' |
| [145](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:145) | &lt;h2 className="min-w-0 truncate text-[16px] font-semibold text-ds-ink"&gt;{t('mcpDialogAddTitle')}&lt;/h2&gt; |
| [158](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:158) | &lt;label className="mb-1.5 block text-[12px] font-medium text-ds-muted"&gt;{t('mcpDialogType')}&lt;/label&gt; |
| [170](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:170) | &lt;label className="mb-1.5 block text-[12px] font-medium text-ds-muted"&gt;{t('mcpDialogName')}&lt;/label&gt; |
| [181](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:181) | &lt;label className="mb-1.5 block text-[12px] font-medium text-ds-muted"&gt;{t('mcpDialogUrl')}&lt;/label&gt; |
| [191](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:191) | &lt;label className="mb-1.5 block text-[12px] font-medium text-ds-muted"&gt;{t('mcpDialogCommand')}&lt;/label&gt; |
| [195](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:195) | className="min-h-[64px] w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30" |
| [204](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:204) | &lt;label className="text-[12px] font-medium text-ds-muted"&gt;{t('mcpDialogEnv')}&lt;/label&gt; |
| [205](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:205) | &lt;span className="text-[11px] text-ds-faint"&gt;{t('mcpDialogEnvPasteHint')}&lt;/span&gt; |
| [217](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:217) | className="h-9 min-w-0 flex-1 rounded-lg border border-ds-border bg-ds-main/45 px-2.5 font-mono text-[12px] text-ds-ink outline-none focus:border-accent/40" |
| [223](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:223) | className="h-9 min-w-0 flex-1 rounded-lg border border-ds-border bg-ds-main/45 px-2.5 font-mono text-[12px] text-ds-ink outline-none focus:border-accent/40" |
| [240](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:240) | className="mt-2 inline-flex items-center gap-1.5 text-[12px] font-medium text-ds-muted transition hover:text-ds-ink" |
| [248](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:248) | &lt;label className="mb-1.5 block text-[12px] font-medium text-ds-muted"&gt;{t('mcpDialogTimeout')}&lt;/label&gt; |
| [259](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:259) | &lt;div className="rounded-xl border border-red-300/70 bg-red-50 px-3 py-2 text-[13px] text-red-800 dark:border-red-800/60 dark:bg-red-950/25 dark:text-red-200"&gt; |
| [270](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/AddMcpServerDialog.tsx:270) | className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-userbubble px-4 py-2 text-[13px] font-semibold leading-none text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55" |

## components/extensions/ConnectorsView.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [284](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:284) | className="ds-ext-menu-item flex w-full items-center px-3.5 py-2 text-left text-[13px] text-ds-ink transition hover:bg-ds-subtle/60" |
| [294](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ConnectorsView.tsx:294) | className="ds-ext-menu-item flex w-full items-center px-3.5 py-2 text-left text-[13px] text-ds-ink transition hover:bg-ds-subtle/60" |

## components/extensions/ImportMcpJsonDialog.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [91](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:91) | &lt;h2 className="min-w-0 truncate text-[16px] font-semibold text-ds-ink"&gt;{t('mcpImportTitle')}&lt;/h2&gt; |
| [106](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:106) | className="min-h-[220px] w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30" |
| [111](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:111) | &lt;div className="rounded-xl border border-red-300/70 bg-red-50 px-3 py-2 text-[13px] text-red-800 dark:border-red-800/60 dark:bg-red-950/25 dark:text-red-200"&gt; |
| [122](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ImportMcpJsonDialog.tsx:122) | className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-userbubble px-4 py-2 text-[13px] font-semibold leading-none text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55" |

## components/extensions/InstallSkillDialog.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [110](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:110) | &lt;div className="mb-3 text-[14px] font-semibold text-ds-ink"&gt;{t('skillInstallTitle')}&lt;/div&gt; |
| [146](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:146) | &lt;div className="text-[14px] font-semibold text-ds-ink"&gt; |
| [149](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:149) | {!busy ? &lt;div className="text-[12px] text-ds-muted"&gt;{t('skillInstallClickHint')}&lt;/div&gt; : null} |
| [150](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:150) | &lt;div className="mt-1 text-[11px] text-ds-faint"&gt;{t('skillInstallFormats')}&lt;/div&gt; |
| [154](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstallSkillDialog.tsx:154) | &lt;div className="mt-3 rounded-xl border border-red-300/70 bg-red-50 px-3 py-2 text-[13px] text-red-800 dark:border-red-800/60 dark:bg-red-950/25 dark:text-red-200"&gt; |

## components/extensions/InstalledConnectorsPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [70](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledConnectorsPanel.tsx:70) | &lt;div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted"&gt; |
| [128](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledConnectorsPanel.tsx:128) | &lt;h3 className="px-5 pt-4 pb-1 text-[11px] font-semibold tracking-[0.08em] text-ds-faint"&gt; |
| [132](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledConnectorsPanel.tsx:132) | &lt;div className="px-5 pb-4 text-[13px] text-ds-faint"&gt;{empty}&lt;/div&gt; |
| [181](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledConnectorsPanel.tsx:181) | &lt;div className="truncate text-[15px] font-semibold text-ds-ink"&gt;{connector.name}&lt;/div&gt; |
| [183](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledConnectorsPanel.tsx:183) | &lt;p className="mt-0.5 line-clamp-1 font-mono text-[12px] leading-5 text-ds-muted" title={connector.summary}&gt; |
| [188](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledConnectorsPanel.tsx:188) | className={`mt-0.5 line-clamp-1 text-[12px] leading-5 ${ |

## components/extensions/InstalledPluginsPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [169](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:169) | className="inline-flex items-center rounded-md bg-ds-subtle px-1.5 py-0.5 text-[11px] text-ds-muted" |
| [269](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:269) | &lt;div className="text-[13px] font-medium text-ds-ink"&gt;{t('skillTabInstalled')}&lt;/div&gt; |
| [276](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:276) | &lt;div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted"&gt; |
| [281](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:281) | &lt;div className="px-5 py-10 text-center text-[13px] text-ds-faint"&gt;{t('pluginSysEmpty')}&lt;/div&gt; |
| [315](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:315) | &lt;div className="flex items-center gap-1.5 border-b border-t border-ds-border-muted/50 px-5 py-2.5 text-[12px] text-ds-faint"&gt; |
| [322](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:322) | &lt;div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted"&gt; |
| [327](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:327) | &lt;div className="px-5 py-10 text-center text-[13px] text-ds-faint"&gt; |
| [331](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:331) | &lt;div className="px-5 py-10 text-center text-[13px] text-ds-faint"&gt; |
| [517](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:517) | &lt;h2 className="truncate text-[16px] font-semibold text-ds-ink"&gt;{title}&lt;/h2&gt; |
| [518](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:518) | &lt;p className="mt-1 truncate font-mono text-[12px] text-ds-muted"&gt; |
| [523](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:523) | &lt;p className="mt-1 text-[12px] text-ds-faint"&gt; |
| [543](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:543) | className="inline-flex shrink-0 items-center gap-1 rounded-md border border-ds-border px-2.5 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover" |
| [558](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:558) | className="inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[12px] font-medium text-ds-ink hover:bg-ds-hover disabled:opacity-50" |
| [576](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:576) | className="inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[12px] font-medium text-ds-ink hover:bg-ds-hover disabled:opacity-50" |
| [589](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:589) | className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-ds-card px-3 py-2 text-[12px] font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-900/50 dark:text-red-400 dark:hover:bg-red-950/30" |
| [603](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:603) | className="inline-flex items-center gap-1.5 rounded-lg bg-accent/10 px-3 py-2 text-[12px] font-medium text-accent transition hover:bg-accent/20 disabled:opacity-50" |
| [617](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:617) | &lt;h3 className="text-[12px] font-semibold text-ds-faint"&gt;{t('pluginDetailAbout')}&lt;/h3&gt; |
| [618](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:618) | &lt;p className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-ds-ink"&gt; |
| [623](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:623) | &lt;h3 className="mt-4 text-[12px] font-semibold text-ds-faint"&gt; |
| [626](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:626) | &lt;p className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-ds-muted"&gt; |
| [634](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:634) | &lt;h3 className="text-[12px] font-semibold tracking-[0.02em] text-ds-faint"&gt; |
| [638](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:638) | &lt;div className="mt-3 flex items-center gap-2 text-[13px] text-ds-muted"&gt; |
| [643](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:643) | &lt;div className="mt-3 flex items-start gap-2 rounded-xl border border-red-300/70 bg-red-50 px-4 py-3 text-[13px] leading-6 text-red-800 dark:border-red-800/60 dark:bg-red-950/25 dark:text-red-200"&gt; |
| [648](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:648) | &lt;p className="mt-2 text-[13px] text-ds-faint"&gt;{t('pluginRulesEmpty')}&lt;/p&gt; |
| [665](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:665) | &lt;p className="mt-5 rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] leading-5 text-amber-800 dark:text-amber-200"&gt; |
| [670](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:670) | &lt;dl className="mt-5 grid grid-cols-2 gap-3 border-y border-ds-border-muted py-4 text-[12px]"&gt; |
| [701](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:701) | &lt;dd className="mt-1 break-all font-mono text-[11px] text-ds-ink"&gt; |
| [720](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:720) | &lt;dd className="mt-1 break-all font-mono text-[11px] text-ds-ink"&gt; |
| [733](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:733) | &lt;dd className="mt-1 break-all font-mono text-[11px] text-ds-ink"&gt; |
| [741](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:741) | &lt;h3 className="mt-5 text-[13px] font-semibold text-ds-ink"&gt; |
| [744](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:744) | &lt;span className="ml-1.5 font-normal text-ds-faint"&gt;({componentsList.length})&lt;/span&gt; |
| [748](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:748) | &lt;p className="mt-2 text-[12px] text-ds-muted"&gt;—&lt;/p&gt; |
| [754](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:754) | className="inline-flex items-center rounded-full border border-ds-border-muted px-2.5 py-1 text-[12px] text-ds-ink" |
| [762](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:762) | &lt;h3 className="mt-5 text-[13px] font-semibold text-ds-ink"&gt; |
| [765](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:765) | &lt;span className="ml-1.5 font-normal text-ds-faint"&gt; |
| [771](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:771) | &lt;p className="mt-2 text-[12px] text-ds-muted"&gt;{t('pluginDetailNoPermissions')}&lt;/p&gt; |
| [777](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:777) | className="inline-flex items-center rounded-full border border-ds-border-muted px-2.5 py-1 font-mono text-[11px] text-ds-ink" |
| [835](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:835) | &lt;div className="flex items-center gap-1.5 text-[12px] font-semibold text-ds-muted"&gt; |
| [847](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:847) | className="h-8 w-64 rounded-lg border border-ds-border bg-ds-main/45 px-2.5 font-mono text-[12px] text-ds-ink outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30" |
| [853](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:853) | className="ds-ext-row-action inline-flex h-8 items-center justify-center gap-1.5 rounded-lg bg-ds-subtle px-2.5 text-[12px] font-semibold text-ds-ink transition hover:bg-ds-hover disabled:opacity-50" |
| [865](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:865) | &lt;div className="flex items-center gap-2 px-5 py-6 text-[13px] text-ds-muted"&gt; |
| [870](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:870) | &lt;div className="px-5 py-6 text-center text-[13px] text-ds-faint"&gt;{t('pluginMpEmpty')}&lt;/div&gt; |
| [883](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:883) | &lt;span className="truncate text-[13px] font-semibold text-ds-ink"&gt;{mp.name}&lt;/span&gt; |
| [884](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:884) | &lt;span className="truncate font-mono text-[11px] text-ds-faint"&gt;{mp.source}&lt;/span&gt; |
| [885](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:885) | &lt;span className="shrink-0 text-[11px] text-ds-faint"&gt; |
| [915](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:915) | &lt;div className="px-5 py-4 text-center text-[12px] text-ds-faint"&gt; |
| [974](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:974) | &lt;h3 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-ds-ink hover:text-accent"&gt; |
| [978](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:978) | &lt;div className="mt-0.5 truncate font-mono text-[12px] text-ds-faint"&gt;{entry.name}&lt;/div&gt; |
| [980](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:980) | className="mt-2 line-clamp-3 overflow-hidden text-[13px] leading-5 text-ds-muted" |
| [989](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:989) | &lt;span className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px] text-ds-faint"&gt; |
| [991](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:991) | &lt;span className="truncate font-mono" title={entry.spec}&gt; |
| [998](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:998) | className="shrink-0 rounded-md border border-ds-border px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink" |
| [1058](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1058) | &lt;h3 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-ds-ink hover:text-accent"&gt; |
| [1062](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1062) | &lt;div className="mt-0.5 truncate font-mono text-[12px] text-ds-faint"&gt;{entry.name}&lt;/div&gt; |
| [1064](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1064) | className="mt-2 line-clamp-3 overflow-hidden text-[13px] leading-5 text-ds-muted" |
| [1073](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1073) | &lt;span className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px] text-ds-faint"&gt; |
| [1075](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1075) | &lt;span className="truncate font-mono"&gt; |
| [1082](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1082) | className="shrink-0 rounded-md border border-ds-border px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink" |
| [1157](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1157) | &lt;h3 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-ds-ink transition-colors group-hover:text-accent"&gt; |
| [1160](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1160) | &lt;div className="mt-0.5 truncate font-mono text-[12px] text-ds-faint"&gt;{plugin.name}&lt;/div&gt; |
| [1168](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1168) | className="mt-3 line-clamp-2 overflow-hidden text-[13px] leading-5 text-ds-muted" |
| [1176](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledPluginsPanel.tsx:1176) | className="flex min-w-0 flex-1 items-center gap-1.5 text-[12px] text-ds-faint" |

## components/extensions/InstalledSkillsPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [83](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledSkillsPanel.tsx:83) | &lt;div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted"&gt; |
| [88](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledSkillsPanel.tsx:88) | &lt;div className="px-5 py-10 text-center text-[13px] text-ds-faint"&gt; |
| [154](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledSkillsPanel.tsx:154) | &lt;div className="truncate text-[15px] font-semibold text-ds-ink"&gt;{skill.name}&lt;/div&gt; |
| [160](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledSkillsPanel.tsx:160) | className="inline-flex shrink-0 items-center rounded px-1 py-px text-[10px] font-medium leading-4 text-emerald-700 bg-emerald-50 dark:bg-emerald-950/40 dark:text-emerald-300" |
| [167](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/InstalledSkillsPanel.tsx:167) | &lt;p className="mt-0.5 line-clamp-1 text-[13px] leading-5 text-ds-muted" title={skill.description &#124;&#124; skill.path}&gt; |

## components/extensions/MarketplaceBrowser.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [188](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:188) | &lt;div className="flex items-center gap-2 py-10 text-[14px] text-ds-faint"&gt; |
| [206](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:206) | &lt;span className="truncate text-[17px] font-semibold text-ds-ink"&gt;{item.name}&lt;/span&gt; |
| [208](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:208) | &lt;span className="shrink-0 rounded-md bg-ds-subtle px-1.5 py-0.5 text-[11px] font-medium text-ds-muted"&gt; |
| [213](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:213) | &lt;p className="mt-1 line-clamp-2 text-[14px] leading-5 text-ds-muted"&gt;{item.description}&lt;/p&gt; |
| [238](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:238) | &lt;div className="mt-4 flex items-center gap-1.5 text-[12px] text-ds-faint"&gt; |
| [259](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceBrowser.tsx:259) | className={`ds-ext-category-chip rounded-full px-3 py-1.5 text-[12px] font-medium leading-none transition active:scale-[0.97] ${ |

## components/extensions/MarketplaceView.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [40](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceView.tsx:40) | &lt;h1 className="ds-ext-page-title text-[24px] font-semibold tracking-[-0.02em] text-ds-ink"&gt; |
| [45](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/MarketplaceView.tsx:45) | &lt;p className="mt-2 max-w-3xl text-[14px] leading-6 text-ds-muted"&gt;{t('marketplaceIntro')}&lt;/p&gt; |

## components/extensions/PluginsView.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [411](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:411) | &lt;h2 className="text-[14px] font-semibold text-ds-ink"&gt;{t('pluginSysInstallTitle')}&lt;/h2&gt; |
| [412](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:412) | &lt;p className="mt-1 text-[12px] leading-5 text-ds-faint"&gt;{t('pluginSysInstallHint')}&lt;/p&gt; |
| [421](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:421) | className="mt-3 h-10 w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 font-mono text-[13px] text-ds-ink outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30" |
| [430](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:430) | &lt;span className="text-[12px] leading-5 text-ds-muted"&gt;{t('pluginSysInstallTrust')}&lt;/span&gt; |
| [436](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/PluginsView.tsx:436) | className="ds-ext-primary-action mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-3 py-2 text-[13px] font-semibold leading-none text-white shadow-sm transition hover:brightness-110 disabled:opacity-60" |

## components/extensions/ReloadHint.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [49](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/ReloadHint.tsx:49) | &lt;span className="pointer-events-none absolute right-full mr-1.5 whitespace-nowrap text-[12px] font-medium text-emerald-600 dark:text-emerald-400"&gt; |

## components/extensions/SkillPreviewDialog.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [56](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:56) | &lt;h2 className="min-w-0 truncate text-[15px] font-semibold tracking-[-0.015em] text-ds-ink"&gt; |
| [63](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:63) | className="inline-flex shrink-0 items-center gap-1 rounded-md border border-ds-border px-2.5 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover" |
| [71](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:71) | &lt;div className="flex items-center gap-2 py-8 text-[13px] text-ds-muted"&gt; |
| [76](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:76) | &lt;div className="flex items-start gap-2 rounded-xl border border-red-300/70 bg-red-50 px-4 py-3 text-[13px] leading-6 text-red-800 dark:border-red-800/60 dark:bg-red-950/25 dark:text-red-200"&gt; |
| [83](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/SkillPreviewDialog.tsx:83) | &lt;p className="text-[13px] text-ds-faint"&gt;{t('marketplaceDocEmpty')}&lt;/p&gt; |

## components/extensions/marketplace-ui.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [69](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx:69) | 'relative z-10 flex items-center justify-center rounded-full px-5 text-[13px] font-semibold leading-none tracking-[-0.01em] transition-colors duration-200', |
| [105](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx:105) | 'relative -mb-px px-3.5 py-3 text-[13px] font-medium tracking-[-0.01em] transition-colors', |
| [146](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx:146) | className="ds-ext-search h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30" |
| [154](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx:154) | className="inline-flex h-11 items-center justify-center gap-1.5 rounded-2xl border border-ds-border bg-transparent px-3.5 text-[13px] font-medium leading-none text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [198](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/extensions/marketplace-ui.tsx:198) | &lt;div className={`mt-4 rounded-xl border px-3 py-2 text-[13px] leading-5 ${className}`}&gt;{notice.message}&lt;/div&gt; |

## components/ide/IdeChatRailHeader.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [117](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeChatRailHeader.tsx:117) | className="inline-flex max-w-[160px] items-center gap-1 truncate px-2 py-0.5 text-[12px] font-medium leading-5" |
| [155](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeChatRailHeader.tsx:155) | &lt;span className="inline-flex shrink-0 rounded-full bg-amber-500/16 px-1.5 py-px text-[10px] font-semibold leading-4 text-amber-950 dark:text-amber-100"&gt; |
| [232](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeChatRailHeader.tsx:232) | className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover/70" |
| [244](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeChatRailHeader.tsx:244) | className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] text-ds-ink transition hover:bg-ds-hover/70" |
| [277](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeChatRailHeader.tsx:277) | &lt;p className="px-2.5 py-2 text-[12px] text-ds-faint"&gt;{t('ideChatRailHistoryEmpty')}&lt;/p&gt; |
| [298](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeChatRailHeader.tsx:298) | &lt;span className="min-w-0 flex-1 truncate text-[12.5px] font-medium"&gt; |
| [301](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeChatRailHeader.tsx:301) | &lt;span className="shrink-0 text-[11px] tabular-nums text-ds-faint"&gt; |

## components/ide/IdeProjectPicker.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [99](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeProjectPicker.tsx:99) | &lt;span className="block truncate text-[12.5px] font-medium tracking-[-0.01em]"&gt; |
| [102](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeProjectPicker.tsx:102) | &lt;span className="mt-0.5 block truncate text-[11px] text-ds-faint"&gt; |
| [126](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeProjectPicker.tsx:126) | &lt;span className="truncate text-[12.5px]"&gt;{t('ideProjectPickerBrowse')}&lt;/span&gt; |

## components/ide/IdeWorkspaceLayout.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [144](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceLayout.tsx:144) | &lt;span className="absolute right-0.5 top-0.5 min-w-[14px] rounded-full bg-ds-ink px-1 text-[9px] font-semibold leading-[14px] text-ds-canvas"&gt; |

## components/ide/IdeWorkspaceSearchSidebar.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [87](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:87) | &lt;span className="truncate text-[12px] font-medium text-ds-ink"&gt;{t('ideWorkspaceSearchTitle')}&lt;/span&gt; |
| [95](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:95) | className="h-8 w-full rounded-md border border-ds-border bg-ds-elevated px-2.5 text-[12.5px] text-ds-ink outline-none placeholder:text-ds-faint" |
| [110](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:110) | &lt;p className="px-2 py-3 text-[12px] text-amber-700 dark:text-amber-200"&gt;{error}&lt;/p&gt; |
| [112](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:112) | &lt;p className="px-2 py-3 text-[12px] text-ds-faint"&gt;{t('ideWorkspaceSearchHint')}&lt;/p&gt; |
| [114](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:114) | &lt;p className="px-2 py-3 text-[12px] text-ds-faint"&gt;{t('ideWorkspaceSearchEmpty')}&lt;/p&gt; |
| [133](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:133) | &lt;span className="min-w-0 flex-1 truncate text-[12.5px]"&gt; |
| [134](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:134) | &lt;span className="font-medium text-ds-ink"&gt;{name}&lt;/span&gt; |
| [136](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:136) | &lt;span className="ml-1.5 text-[11px] text-ds-faint"&gt;{parent}&lt;/span&gt; |
| [146](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/ide/IdeWorkspaceSearchSidebar.tsx:146) | &lt;p className="px-2 py-2 text-[11px] text-ds-faint"&gt;{t('ideWorkspaceSearchTruncated')}&lt;/p&gt; |

## components/kanban/KanbanCardView.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [67](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanCardView.tsx:67) | &lt;div className="line-clamp-3 pr-6 text-[14px] font-medium leading-5 text-ds-ink"&gt; |
| [70](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanCardView.tsx:70) | &lt;div className="flex min-w-0 items-center gap-2 text-[12px] text-ds-faint"&gt; |

## components/kanban/KanbanColumn.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [102](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanColumn.tsx:102) | &lt;h2 className="min-w-0 flex-1 truncate text-[15px] font-semibold text-ds-ink"&gt; |
| [105](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanColumn.tsx:105) | &lt;span className="text-[13px] text-ds-faint"&gt;{cards.length}&lt;/span&gt; |
| [151](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanColumn.tsx:151) | &lt;li className="list-none px-2 py-6 text-center text-[12px] leading-5 text-ds-faint"&gt; |
| [159](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanColumn.tsx:159) | className="w-full rounded-lg px-3 py-1.5 text-center text-xs text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink" |

## components/kanban/KanbanNewTaskDialog.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [137](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:137) | &lt;h2 className="text-[14px] font-semibold text-ds-ink"&gt;{t('common:kanbanNewTask')}&lt;/h2&gt; |
| [148](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:148) | &lt;label className="flex flex-col gap-1.5 text-[12px] text-ds-muted"&gt; |
| [153](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:153) | className="rounded-lg border border-ds-border bg-ds-card px-2.5 py-2 text-[13px] text-ds-ink outline-none focus:ring-1 focus:ring-sky-500/40" |
| [162](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:162) | &lt;label className="flex flex-col gap-1.5 text-[12px] text-ds-muted"&gt; |
| [167](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:167) | className="rounded-lg border border-ds-border bg-ds-card px-2.5 py-2 text-[13px] text-ds-ink outline-none focus:ring-1 focus:ring-sky-500/40" |
| [176](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:176) | &lt;label className="flex flex-col gap-1.5 text-[12px] text-ds-muted"&gt; |
| [183](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:183) | className="rounded-lg border border-ds-border bg-ds-card px-2.5 py-2 text-[13px] text-ds-ink outline-none focus:ring-1 focus:ring-sky-500/40" |
| [191](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:191) | &lt;span className="text-[11px] leading-4 text-ds-faint"&gt; |
| [195](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:195) | &lt;label className="flex flex-col gap-1.5 text-[12px] text-ds-muted"&gt; |
| [202](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:202) | className="resize-y rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[13px] leading-5 text-ds-ink outline-none focus:ring-1 focus:ring-sky-500/40" |
| [206](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:206) | &lt;label className="flex items-center gap-2 text-[12px] text-ds-muted"&gt; |
| [218](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:218) | className="rounded-lg px-3 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink" |
| [226](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanNewTaskDialog.tsx:226) | className="rounded-lg bg-sky-600 px-3 py-1.5 text-[12px] font-medium text-white transition hover:bg-sky-500 disabled:opacity-50" |

## components/kanban/KanbanOverview.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [36](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanOverview.tsx:36) | &lt;h2 className="min-w-0 truncate text-[15px] font-semibold text-ds-ink"&gt; |
| [39](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanOverview.tsx:39) | &lt;span className="text-[13px] text-ds-faint"&gt;{projectBoard.totalCount}&lt;/span&gt; |
| [67](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanOverview.tsx:67) | className="w-full rounded-lg px-3 py-2 text-center text-[13px] text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink" |
| [97](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanOverview.tsx:97) | &lt;div className="text-sm font-medium text-ds-ink"&gt;{t('kanbanEmptyTitle')}&lt;/div&gt; |
| [98](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanOverview.tsx:98) | &lt;div className="mt-1 text-sm text-ds-faint"&gt;{t('kanbanEmptyHint')}&lt;/div&gt; |

## components/kanban/KanbanProjectBoardView.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [185](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx:185) | &lt;div className="px-8 pb-2 text-[12px] text-ds-muted"&gt;{notice}&lt;/div&gt; |
| [187](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanProjectBoardView.tsx:187) | &lt;div className="px-8 pb-2 text-[12px] text-ds-faint"&gt;{t('kanbanBoardDragTip')}&lt;/div&gt; |

## components/kanban/KanbanView.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [446](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:446) | &lt;h1 className="truncate text-[24px] font-semibold text-ds-ink"&gt;{headerTitle}&lt;/h1&gt; |
| [448](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:448) | &lt;span className="shrink-0 text-[13px] text-ds-faint"&gt; |
| [453](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:453) | &lt;p className="mt-1 text-[13px] text-ds-muted"&gt;{headerDesc}&lt;/p&gt; |
| [458](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:458) | className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-accent px-4 py-2 text-[13px] font-medium text-white transition hover:opacity-90" |
| [466](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:466) | &lt;div className="mt-3 shrink-0 px-8 text-[12px] text-ds-muted"&gt;{notice}&lt;/div&gt; |
| [523](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:523) | &lt;div className="mb-3 text-[13px] font-medium text-ds-ink"&gt;{t('kanbanRenameTitle')}&lt;/div&gt; |
| [531](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:531) | className="w-full rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink outline-none focus:ring-1 focus:ring-sky-500/40" |
| [537](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:537) | className="rounded-lg px-3 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover" |
| [544](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/kanban/KanbanView.tsx:544) | className="rounded-lg bg-sky-600 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-sky-500" |

## components/right-sidebar/RightSidebarCollapsedStrip.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [62](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/RightSidebarCollapsedStrip.tsx:62) | &lt;span className="[writing-mode:vertical-rl] rotate-180 text-[11px] font-medium text-ds-muted"&gt; |
| [67](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/RightSidebarCollapsedStrip.tsx:67) | &lt;span className="max-w-full truncate px-0.5 text-[10px] text-ds-faint [writing-mode:vertical-rl] rotate-180"&gt; |
| [73](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/RightSidebarCollapsedStrip.tsx:73) | &lt;span className="text-[11px] tabular-nums text-ds-muted [writing-mode:vertical-rl] rotate-180"&gt; |

## components/right-sidebar/WorkbenchRightSidebar.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [109](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/WorkbenchRightSidebar.tsx:109) | className={`inline-flex shrink-0 items-center gap-1 rounded-full border py-0.5 text-[11.5px] font-medium transition ${ |

## components/right-sidebar/run-panel.css

| 行号 | 声明／组件上下文 |
|---|---|
| [8](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:8) | font-family: var(--font-ui); |
| [27](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:27) | .ds-run-status { flex-shrink: 0; font-size: 11px; white-space: nowrap; display: inline-flex; align-items: center; gap: 5px; color: var(--ds-text-muted); } |
| [62](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:62) | font-size: 12px; |
| [63](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:63) | font-weight: 550; |
| [85](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:85) | .ds-run-menu-item-text &gt; span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; line-height: 18px; } |
| [105](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:105) | .ds-run-phase-label { color: var(--ds-text); font-size: 14px; font-weight: 550; line-height: 20px; } |
| [106](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:106) | .ds-run-phase .ds-run-phase-label { font-size: 12px; font-weight: 500; } |
| [107](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:107) | .ds-run-phase-preview { color: var(--ds-text-faint); font-size: 11.5px; font-weight: 400; line-height: 18px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } |
| [109](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:109) | .ds-run-phase-count { color: var(--ds-text-faint); font-size: 10px; white-space: nowrap; } |
| [120](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:120) | .ds-run-action-name { display: flex; gap: 5px; align-items: center; flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px; } |
| [121](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:121) | .ds-run-action-number { color: var(--ds-text-faint); font-size: 10px; font-variant-numeric: tabular-nums; } |
| [122](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:122) | .ds-run-target { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10.5px; color: var(--ds-text-faint); text-align: right; } |
| [126](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:126) | .ds-run-action-detail h4 { font-size: 10px; font-weight: 500; color: var(--ds-text-faint); margin-bottom: 5px; } |
| [128](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:128) | .ds-run-action-detail pre { max-height: 240px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: 11px/1.65 var(--font-mono); color: var(--ds-text-muted); } |
| [129](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:129) | .ds-run-target-list { max-height: 240px; overflow: auto; font-size: 11px; } |
| [131](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:131) | .ds-run-target-list span { display: block; color: var(--ds-text-faint); margin-bottom: 3px; font-size: 10px; } |
| [132](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:132) | .ds-run-target-list code { display: block; overflow-wrap: anywhere; color: var(--ds-text-muted); font: 10.5px/1.6 var(--font-mono); } |
| [133](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:133) | .ds-run-footer { display: flex; align-items: center; gap: 7px; flex-shrink: 0; padding: 11px 22px; border-top: 1px solid var(--ds-border-muted); color: var(--ds-text-faint); font-size: 10.5px; } |
| [135](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:135) | .ds-run-footer button, .ds-run-resume { font-size: 11px; padding: 4px 8px; border-radius: 5px; color: var(--ds-text-muted); } |
| [139](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:139) | .ds-run-result-header { display: flex; align-items: center; gap: 7px; margin-bottom: 13px; font-size: 14px; font-weight: 550; } |
| [143](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:143) | .ds-run-panel .ds-markdown.ds-markdown--answer { font-size: 12px; line-height: 1.75; max-width: none; overflow-wrap: anywhere; } |
| [144](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:144) | .ds-run-panel .ds-run-result .ds-markdown.ds-markdown--answer { font-size: 13px; } |
| [147](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:147) | .ds-run-panel .ds-markdown.ds-markdown--answer { font-size: 14px; } |
| [148](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:148) | .ds-run-panel .ds-run-result .ds-markdown.ds-markdown--answer { font-size: 15px; } |
| [149](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:149) | .ds-run-phase-label, .ds-run-result-header, .ds-run-panel .ds-run-process-toggle { font-size: 15px; } |
| [150](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:150) | .ds-run-phase .ds-run-phase-label { font-size: 13px; } |
| [152](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:152) | .ds-run-empty { padding: 12px 0; color: var(--ds-text-faint); font-size: 12px; line-height: 1.7; } |
| [153](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:153) | .ds-run-error { padding: 10px 12px; margin-bottom: 16px; border-radius: 7px; background: var(--ds-danger-soft); color: var(--ds-danger); font-size: 12px; line-height: 1.6; } |
| [155](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:155) | .ds-run-children button { display: flex; align-items: center; gap: 5px; white-space: nowrap; padding: 5px 8px; border-radius: 5px; color: var(--ds-text-faint); font-size: 10.5px; } |
| [164](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:164) | .ds-run-title { font-size: 12px; } |
| [176](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:176) | .ds-run-process-toggle { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; width: 100%; padding: 10px 0; text-align: left; color: var(--ds-text); font-size: 14px; font-weight: 550; line-height: 20px; } |
| [178](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/right-sidebar/run-panel.css:178) | .ds-run-process-stats { margin-left: auto; color: var(--ds-text-faint); font-size: 11px; font-weight: 400; } |

## components/settings/AppearanceSettingsPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [44](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:44) | // -webkit-font-smoothing only has an effect on macOS; hide the toggle elsewhere. |
| [136](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:136) | className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12.5px] font-medium transition disabled:cursor-default disabled:opacity-40 ${ |
| [405](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:405) | &lt;h2 className="text-[16px] font-semibold text-ds-ink"&gt;{titleLabel}&lt;/h2&gt; |
| [426](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:426) | className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink" |
| [434](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:434) | className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium transition hover:bg-ds-hover ${ |
| [474](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:474) | &lt;div className="px-5 pt-2 text-[12.5px] text-ds-faint"&gt; |
| [490](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:490) | className="w-full rounded-lg border border-ds-border bg-ds-card px-2.5 py-1.5 font-mono text-[12px] text-ds-ink placeholder:text-ds-faint focus:border-accent/40 focus:outline-none" |
| [495](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:495) | className="min-w-0 truncate text-[12px] text-red-700 dark:text-red-300" |
| [503](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:503) | className="shrink-0 rounded-lg border border-ds-border bg-ds-card px-3 py-1.5 text-[12.5px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-50" |
| [590](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:590) | &lt;span className="w-8 shrink-0 text-center font-mono text-[13px] leading-none text-ds-muted"&gt; |
| [657](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:657) | className="h-full w-full min-w-0 bg-transparent px-9 text-center font-mono text-[13px] font-medium uppercase leading-10 focus:outline-none" |
| [673](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:673) | 'box-border h-10 w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 text-center text-[14px] leading-10 text-ds-ink shadow-sm placeholder:text-ds-faint focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30' |
| [708](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:708) | className={`${CONTROL_FIELD_CLASS} ${mono ? 'font-mono' : ''} ${className}`.trim()} |
| [749](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:749) | &lt;span className="shrink-0 text-[13px] leading-none text-ds-faint"&gt;px&lt;/span&gt; |
| [756](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:756) | &lt;h2 className="px-1 text-[12.5px] font-medium uppercase tracking-wide text-ds-faint"&gt; |
| [784](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:784) | &lt;div className="text-[14px] font-semibold leading-none text-ds-ink"&gt;{title}&lt;/div&gt; |
| [786](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/AppearanceSettingsPanel.tsx:786) | &lt;p className="mt-1.5 max-w-md text-pretty text-[13px] leading-relaxed text-ds-muted"&gt; |

## components/settings/DataSettingsPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [88](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:88) | &lt;h2 className="text-[16px] font-semibold text-ds-ink"&gt;{title}&lt;/h2&gt; |
| [114](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:114) | &lt;div className="text-[14px] font-semibold leading-none text-ds-ink"&gt;{title}&lt;/div&gt; |
| [117](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:117) | &lt;p className="mt-1.5 max-w-md text-pretty text-[13px] leading-relaxed text-ds-muted"&gt; |
| [121](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:121) | &lt;div className="mt-1.5 max-w-md text-[13px] leading-relaxed text-ds-muted"&gt; |
| [150](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:150) | 'inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-red-300/80 bg-red-50 px-2.5 text-center text-[13px] font-medium leading-none text-red-700 shadow-sm transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-55 dark:border-red-800/70 dark:bg-red-950/30 dark:text-red-200 dark:hover:bg-red-950/45' |
| [173](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:173) | &lt;div className={`rounded-xl border px-3 py-2 text-[12.5px] leading-5 ${className}`}&gt; |
| [521](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:521) | &lt;div className="flex items-center gap-2 px-3 py-6 text-[13px] text-ds-muted"&gt; |
| [526](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:526) | &lt;div className="px-3 py-4 text-[13px] text-red-700 dark:text-red-300"&gt;{loadError}&lt;/div&gt; |
| [532](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:532) | &lt;div className="text-[12.5px] font-medium text-ds-faint"&gt;{t('dataTotalUsed')}&lt;/div&gt; |
| [533](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:533) | &lt;div className="mt-1 text-[28px] font-semibold tracking-tight tabular-nums text-ds-ink"&gt; |
| [537](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:537) | &lt;div className="text-[13px] text-ds-muted"&gt; |
| [581](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:581) | &lt;p className="mt-3 text-[12.5px] leading-5 text-ds-faint"&gt;{t('dataStorageFooter')}&lt;/p&gt; |
| [588](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:588) | &lt;code className="block truncate rounded-lg bg-ds-main/70 px-2 py-1 font-mono text-[12px] text-ds-ink"&gt; |
| [592](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:592) | &lt;p className="text-[12px] text-red-700 dark:text-red-300"&gt;{openDirError}&lt;/p&gt; |
| [650](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:650) | &lt;div className="px-3 py-3 text-[12.5px] leading-5 text-ds-faint"&gt;{t('dataMigrationFooter')}&lt;/div&gt; |
| [658](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:658) | &lt;code className="block truncate rounded-lg bg-ds-main/70 px-2 py-1 font-mono text-[12px] text-ds-ink"&gt; |
| [686](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:686) | &lt;div className="px-3 py-3 text-[12.5px] leading-5 text-ds-faint"&gt;{t('dataBackupFooter')}&lt;/div&gt; |
| [732](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:732) | &lt;div className="px-3 py-3 text-[12.5px] leading-5 text-ds-faint"&gt;{t('dataMaintenanceFooter')}&lt;/div&gt; |
| [776](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:776) | &lt;div className="text-[11.5px] font-medium text-ds-faint"&gt;{label}&lt;/div&gt; |
| [777](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/DataSettingsPanel.tsx:777) | &lt;div className="mt-1 text-[14px] font-semibold tabular-nums text-ds-ink"&gt;{value}&lt;/div&gt; |

## components/settings/GlassSegmentedControl.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [99](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/GlassSegmentedControl.tsx:99) | 'relative z-10 flex items-center justify-center rounded-full text-center text-[12px] font-medium leading-none transition-colors duration-200', |

## components/settings/ModelUsageHeroPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [60](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageHeroPanel.tsx:60) | &lt;h2 className="text-[14px] font-semibold tracking-[-0.01em] text-ds-ink"&gt; |
| [79](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageHeroPanel.tsx:79) | &lt;p className="mt-5 text-[13px] leading-6 text-ds-muted"&gt;{t('usageHeroError')}&lt;/p&gt; |
| [84](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageHeroPanel.tsx:84) | &lt;p className="text-[14px] font-medium text-ds-ink"&gt;{t('usageHeroTitle')}&lt;/p&gt; |
| [85](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageHeroPanel.tsx:85) | &lt;p className="mt-2 text-[12.5px] leading-6 text-ds-muted"&gt;{t('usageHeroEmpty')}&lt;/p&gt; |
| [127](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageHeroPanel.tsx:127) | &lt;p className="text-[10px] font-medium uppercase tracking-[0.06em] text-ds-faint"&gt;{label}&lt;/p&gt; |
| [131](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageHeroPanel.tsx:131) | &lt;p className="mt-0.5 text-[14px] font-semibold tabular-nums text-ds-ink"&gt;{value}&lt;/p&gt; |
| [225](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageHeroPanel.tsx:225) | className="inline-block min-w-full w-max text-[14px] font-semibold tabular-nums text-ds-ink" |

## components/settings/ModelUsagePanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [61](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:61) | &lt;h3 className="text-[14px] font-semibold text-ds-ink"&gt;{t('modelUsageTitle')}&lt;/h3&gt; |
| [62](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:62) | &lt;p className="mt-1 text-[13px] leading-6 text-ds-muted"&gt;{t('modelUsageDesc')}&lt;/p&gt; |
| [73](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:73) | 'rounded-full px-2.5 py-1 text-[11.5px] font-medium transition', |
| [84](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:84) | &lt;div className="text-right text-[12px] tabular-nums text-ds-muted"&gt; |
| [92](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:92) | &lt;p className="mt-4 text-[13px] text-ds-faint"&gt;{t('modelUsageLoading')}&lt;/p&gt; |
| [96](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:96) | &lt;p className="mt-4 rounded-xl border border-red-300/70 bg-red-50/80 px-4 py-5 text-[13px] leading-6 text-red-800 dark:border-red-800/50 dark:bg-red-950/30 dark:text-red-100"&gt; |
| [102](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:102) | &lt;p className="mt-4 rounded-xl border border-dashed border-ds-border px-4 py-5 text-[13px] leading-6 text-ds-muted"&gt; |
| [138](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:138) | className={`min-w-0 truncate text-[12.5px] font-medium ${ |
| [145](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:145) | &lt;span className="shrink-0 text-[11.5px] tabular-nums text-ds-muted"&gt; |
| [155](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsagePanel.tsx:155) | &lt;div className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] tabular-nums text-ds-faint"&gt; |

## components/settings/ModelUsageTrendChart.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [142](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageTrendChart.tsx:142) | &lt;span key={tick} className="text-[10px] leading-none tabular-nums text-ds-faint"&gt; |
| [214](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageTrendChart.tsx:214) | className="flex h-full flex-1 items-center justify-center whitespace-nowrap text-[10px] leading-[14px] tabular-nums text-ds-faint" |
| [229](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/ModelUsageTrendChart.tsx:229) | className="inline-flex min-w-0 max-w-full items-center gap-1 text-[10px] leading-tight text-ds-muted" |

## components/settings/SettingsActionToolbar.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [18](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/SettingsActionToolbar.tsx:18) | return `inline-flex items-center justify-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-center text-[13px] font-medium leading-none text-ds-ink shadow-sm transition hover:bg-ds-hover ${ |
| [25](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/SettingsActionToolbar.tsx:25) | return `inline-flex h-8 w-full items-center justify-center rounded-lg border border-ds-border bg-ds-card px-2.5 text-center text-[13px] font-medium leading-none text-ds-ink shadow-sm transition hover:bg-ds-hover ${ |

## components/settings/SettingsSelect.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [305](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/SettingsSelect.tsx:305) | &lt;span className="w-full truncate text-[13px] font-medium leading-none text-ds-ink"&gt; |

## components/settings/SettingsSidebarNav.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [99](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/SettingsSidebarNav.tsx:99) | &lt;div className="min-w-0 truncate text-[13px] font-medium text-ds-ink"&gt; |

## components/settings/UsageActivityHeatmap.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [163](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:163) | &lt;p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.05em] text-ds-faint"&gt; |
| [176](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:176) | &lt;p className="mb-2.5 shrink-0 text-[11px] font-semibold uppercase tracking-[0.05em] text-ds-faint"&gt; |
| [202](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:202) | className="absolute left-0 -translate-y-1/2 text-[10px] font-medium leading-none text-ds-faint" |
| [218](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:218) | className="absolute top-0 whitespace-nowrap text-[10px] font-medium leading-none text-ds-faint" |
| [323](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:323) | ? 'min-w-0 flex-1 truncate text-left text-[11px] leading-5' |
| [324](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:324) | : 'min-h-[20px] flex-1 text-center text-[12px] leading-5' |
| [338](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:338) | 'min-w-0 flex-1 truncate text-left text-[11px] leading-5 tabular-nums', |
| [342](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:342) | &lt;span className="font-semibold"&gt;{dateLabel}&lt;/span&gt; |
| [344](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:344) | &lt;span className={tokens &gt; 0 ? 'font-medium text-ds-ink/85' : ''}&gt;{tokenLabel}&lt;/span&gt; |
| [352](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:352) | 'min-h-[20px] flex-1 text-center text-[12px] leading-5 tabular-nums', |
| [356](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:356) | &lt;span className="font-semibold"&gt;{dateLabel}&lt;/span&gt; |
| [358](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:358) | &lt;span className={tokens &gt; 0 ? 'font-medium text-ds-ink/85' : ''}&gt;{tokenLabel}&lt;/span&gt; |
| [429](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/UsageActivityHeatmap.tsx:429) | &lt;div className="flex shrink-0 items-center gap-1.5 text-[10px] font-medium text-ds-faint"&gt; |

## components/settings/WebSearchSettingsPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [105](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/WebSearchSettingsPanel.tsx:105) | &lt;h2 className="text-[16px] font-semibold text-ds-ink"&gt;{t('sectionWebSearch')}&lt;/h2&gt; |
| [106](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/WebSearchSettingsPanel.tsx:106) | &lt;p className="mt-1 text-[13px] leading-5 text-ds-muted"&gt;{t('webSearchSectionDesc')}&lt;/p&gt; |
| [186](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/WebSearchSettingsPanel.tsx:186) | &lt;div className="flex flex-wrap items-center gap-2 text-[14px] font-semibold text-ds-ink"&gt; |
| [187](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/WebSearchSettingsPanel.tsx:187) | &lt;span className="inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-ds-subtle px-1.5 text-[11px] font-medium text-ds-muted"&gt; |
| [192](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/WebSearchSettingsPanel.tsx:192) | &lt;span className="text-[11px] font-medium text-accent"&gt; |
| [197](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/WebSearchSettingsPanel.tsx:197) | &lt;p className="mt-1 max-w-2xl text-[13px] leading-6 text-ds-muted"&gt;{t(HINT_KEY[id])}&lt;/p&gt; |
| [205](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/WebSearchSettingsPanel.tsx:205) | className="w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 py-2 pr-10 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30" |
| [223](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/settings/WebSearchSettingsPanel.tsx:223) | &lt;p className="pl-8 text-[12px] leading-5 text-ds-muted"&gt; |

## components/workspace-editor/HtmlDocumentPreview.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [63](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/HtmlDocumentPreview.tsx:63) | &lt;div className="flex min-h-0 flex-1 items-center justify-center px-6 text-center text-[13px] text-ds-faint"&gt; |

## components/workspace-editor/ImageDocumentPreview.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [63](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/ImageDocumentPreview.tsx:63) | &lt;div className="flex min-h-0 flex-1 items-center justify-center px-6 text-center text-[13px] text-ds-faint"&gt; |

## components/workspace-editor/WorkspaceEditorPanel.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [146](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:146) | return &lt;span className="ml-1 shrink-0 text-[10px] text-ds-muted"&gt;✎&lt;/span&gt; |
| [165](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:165) | &lt;div className="ds-workspace-editor-breadcrumb flex h-7 shrink-0 items-center gap-1 overflow-hidden border-b border-[color-mix(in_srgb,var(--ds-text)_10%,transparent)] px-2.5 text-[11px] text-ds-faint"&gt; |
| [180](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:180) | className={isLast ? 'min-w-0 truncate font-medium text-ds-ink' : 'shrink-0'} |
| [224](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:224) | &lt;span className="px-2 py-1 text-[12px] text-ds-faint"&gt;{emptyLabel}&lt;/span&gt; |
| [247](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:247) | className="inline-flex min-w-0 items-center gap-1 truncate px-2 py-1 text-[12px]" |
| [330](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:330) | className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink" |
| [338](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:338) | className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink disabled:opacity-45" |
| [467](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:467) | &lt;div className="flex flex-1 items-center justify-center px-6 text-center text-[13px] text-ds-faint"&gt; |
| [484](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:484) | &lt;div className="shrink-0 border-b border-amber-200/70 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-100"&gt; |
| [489](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:489) | &lt;div className="shrink-0 border-b border-amber-200/70 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-100"&gt; |
| [493](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:493) | &lt;div className="shrink-0 border-b border-amber-200/70 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-100"&gt; |
| [1039](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel.tsx:1039) | &lt;div className="flex flex-1 items-center justify-center px-6 text-center text-[13px] text-ds-faint"&gt; |

## components/workspace-editor/WorkspaceEditorSurface.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [216](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorSurface.tsx:216) | className="absolute z-20 inline-flex items-center gap-1 rounded-md border border-ds-border bg-ds-elevated px-1.5 py-0.5 text-[11px] font-medium text-ds-ink shadow-sm" |
| [265](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorSurface.tsx:265) | fontSize: 12, |

## components/workspace-editor/WorkspaceFileContextMenu.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [92](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileContextMenu.tsx:92) | 'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-ds-ink transition-colors duration-150 hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent' |

## components/workspace-editor/WorkspaceFileTree.tsx

| 行号 | 声明／组件上下文 |
|---|---|
| [281](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:281) | className="ds-workspace-file-tree__row-pad py-1 text-[12px] text-red-600 dark:text-red-300" |
| [293](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:293) | className="ds-workspace-file-tree__row-pad py-1 text-[12px] text-ds-faint" |
| [322](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:322) | className="ds-no-drag ds-workspace-file-tree__row ds-workspace-file-tree__row-pad flex h-7 w-full items-center gap-1.5 text-left text-[12px] text-ds-muted transition hover:bg-ds-hover/55 hover:text-ds-ink" |
| [338](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:338) | &lt;span className={`min-w-0 truncate ${dirHasChanges ? 'font-medium text-ds-diff-added' : ''}`}&gt; |
| [368](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:368) | className={`ds-no-drag ds-workspace-file-tree__row ds-workspace-file-tree__row-pad flex h-7 w-full items-center gap-1.5 text-left text-[12px] transition ${ |
| [382](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:382) | {isDirty ? &lt;span className="ml-auto text-[10px] text-accent"&gt;●&lt;/span&gt; : null} |
| [394](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:394) | &lt;div className="min-w-0 truncate text-[12px] font-semibold text-ds-ink" title={trimmedRoot}&gt; |
| [399](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceFileTree.tsx:399) | &lt;div className="text-[12px] leading-5 text-ds-faint"&gt;{t('workspaceTreeNoRoot')}&lt;/div&gt; |

## index.css

| 行号 | 声明／组件上下文 |
|---|---|
| [16](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:16) | --font-ui: 'Inter', 'PingFang SC', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; |
| [17](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:17) | --font-chat: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Noto Sans SC', sans-serif; |
| [18](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:18) | --font-display: var(--font-ui); |
| [21](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:21) | --font-terminal, which is overridden inline by apply-appearance.ts. */ |
| [22](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:22) | --font-mono: 'SF Mono', SFMono-Regular, ui-monospace, Menlo, Monaco, Consolas, 'Liberation Mono', |
| [24](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:24) | --font-terminal: 'SF Mono', SFMono-Regular, ui-monospace, Menlo, Monaco, Consolas, 'Liberation Mono', |
| [28](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:28) | --ds-chat-font-size: 16px; |
| [304](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:304) | --font-ui: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Segoe UI', |
| [306](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:306) | --font-display: var(--font-ui); |
| [312](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:312) | font-family: var(--font-ui); |
| [313](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:313) | -webkit-font-smoothing: antialiased; |
| [314](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:314) | font-synthesis: none; |
| [586](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:586) | font-family: var(--font-mono); |
| [587](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:587) | font-size: 11px; |
| [588](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:588) | font-weight: 600; |
| [596](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:596) | font-size: 2.55rem; |
| [597](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:597) | font-weight: 700; |
| [620](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:620) | font-size: 17px; |
| [631](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:631) | font-family: var(--font-mono); |
| [632](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:632) | font-size: 12px; |
| [633](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:633) | font-weight: 600; |
| [656](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:656) | font-size: 16px; |
| [657](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:657) | font-weight: 600; |
| [664](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:664) | font-size: 14px; |
| [697](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:697) | font-size: 15px; |
| [698](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:698) | font-weight: 500; |
| [728](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:728) | font-size: 15px; |
| [729](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:729) | font-weight: 700; |
| [843](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:843) | font-family: var(--font-ui); |
| [844](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:844) | -webkit-font-smoothing: antialiased; |
| [845](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:845) | font-synthesis: none; |
| [852](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:852) | font-family: var(--font-ui); |
| [853](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:853) | font-size: 0.9375rem; |
| [858](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:858) | -webkit-font-smoothing: antialiased; |
| [859](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:859) | font-synthesis: none; |
| [881](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:881) | font-family: var(--font-ui); |
| [882](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:882) | font-size: inherit; |
| [883](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:883) | font-weight: inherit; |
| [885](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:885) | -webkit-font-smoothing: antialiased; |
| [886](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:886) | font-synthesis: none; |
| [893](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:893) | font-family: var(--font-ui); |
| [894](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:894) | -webkit-font-smoothing: antialiased; |
| [895](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:895) | font-synthesis: none; |
| [973](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:973) | font-size: 0.68rem; |
| [974](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:974) | font-weight: 650; |
| [993](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:993) | font-size: 0.82rem; |
| [1003](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1003) | font-size: 0.68rem; |
| [1030](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1030) | font-size: 0.74rem; |
| [1137](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1137) | font-family: var(--font-ui); |
| [1138](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1138) | -webkit-font-smoothing: antialiased; |
| [1182](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1182) | font-family: var(--font-ui); |
| [1183](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1183) | font-size: 12.5px; |
| [1184](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1184) | font-weight: 600; |
| [1188](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1188) | -webkit-font-smoothing: antialiased; |
| [1198](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1198) | font-size: 15px; |
| [1199](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1199) | font-weight: 500; |
| [1206](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1206) | font-size: 14px; |
| [1207](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1207) | font-weight: 400; |
| [1386](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1386) | font-weight: 500; |
| [1434](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1434) | font-weight: 600; |
| [1516](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1516) | font-weight: 600; |
| [1534](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1534) | font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Hiragino Sans GB', 'Segoe UI', |
| [1536](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1536) | -webkit-font-smoothing: antialiased; |
| [1537](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1537) | font-synthesis: none; |
| [1579](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1579) | font-size: 12px; |
| [1580](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1580) | font-weight: 650; |
| [1588](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1588) | font-size: 11px; |
| [1589](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1589) | font-weight: 400; |
| [1612](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1612) | font: inherit; |
| [1613](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1613) | font-size: 13px; |
| [1614](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1614) | font-weight: 500; |
| [1628](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1628) | font-weight: 400; |
| [1649](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1649) | font-size: 12.5px; |
| [1741](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1741) | font-size: 13px; |
| [1742](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1742) | font-weight: 600; |
| [1754](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1754) | font-size: 11px; |
| [1755](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1755) | font-weight: 400; |
| [1764](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1764) | font-size: 11px; |
| [1765](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1765) | font-weight: 650; |
| [1819](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:1819) | font-family: var(--font-ui); |
| [2153](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2153) | font-family: var(--font-ui); |
| [2154](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2154) | font-size: 15px; |
| [2155](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2155) | font-weight: 400; |
| [2158](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2158) | -webkit-font-smoothing: antialiased; |
| [2159](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2159) | font-synthesis: none; |
| [2196](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2196) | font-family: var(--font-ui); |
| [2197](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2197) | font-size: 15px; |
| [2198](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2198) | font-weight: 400; |
| [2201](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2201) | -webkit-font-smoothing: antialiased; |
| [2202](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2202) | font-synthesis: none; |
| [2207](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2207) | font-family: var(--font-ui); |
| [2212](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2212) | font-family: var(--font-ui); |
| [2214](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2214) | -webkit-font-smoothing: antialiased; |
| [2215](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2215) | font-synthesis: none; |
| [2585](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2585) | font-family: var(--font-display); |
| [2586](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2586) | font-size: 1.75rem; |
| [2587](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2587) | font-weight: 600; |
| [2595](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2595) | font-family: var(--font-ui); |
| [2596](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2596) | font-size: 0.9375rem; |
| [2597](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2597) | font-weight: 400; |
| [2699](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2699) | font-family: var(--font-display); |
| [2700](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2700) | font-size: clamp(1.35rem, 2.4vw, 1.65rem); |
| [2701](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2701) | font-weight: 500; |
| [2973](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2973) | --font-sidebar: |
| [2976](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2976) | --sidebar-text: 0.9375rem; /* 15px — nav, projects, threads */ |
| [2977](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2977) | --sidebar-text-sm: 0.875rem; /* 14px — indented nav, search */ |
| [2978](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2978) | --sidebar-text-xs: 0.8125rem; /* 13px — section labels, meta */ |
| [2981](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2981) | font-family: var(--font-sidebar); |
| [2982](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2982) | font-size: var(--sidebar-text); |
| [2983](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2983) | font-weight: var(--sidebar-weight); |
| [2987](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2987) | -webkit-font-smoothing: antialiased; |
| [2988](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2988) | -moz-osx-font-smoothing: grayscale; |
| [2989](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:2989) | font-synthesis: none; |
| [3002](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3002) | font-family: inherit; |
| [3003](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3003) | font-size: inherit; |
| [3004](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3004) | font-weight: inherit; |
| [3009](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3009) | font-family: inherit; |
| [3010](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3010) | font-size: 1.125rem; |
| [3011](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3011) | font-weight: var(--sidebar-weight-strong); |
| [3032](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3032) | font-family: inherit; |
| [3033](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3033) | font-size: var(--sidebar-text-xs); |
| [3034](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3034) | font-weight: var(--sidebar-weight-strong); |
| [3041](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3041) | font-size: var(--sidebar-text-xs); |
| [3042](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3042) | font-weight: var(--sidebar-weight-strong); |
| [3058](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3058) | /* Explicit stack — global `input { font-family: var(--font-ui) }` plus |
| [3061](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3061) | font-family: var(--font-sidebar); |
| [3062](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3062) | font-size: var(--sidebar-text-sm); |
| [3063](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3063) | font-weight: var(--sidebar-weight); |
| [3066](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3066) | -webkit-font-smoothing: antialiased; |
| [3067](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3067) | font-synthesis: none; |
| [3074](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3074) | font-family: var(--font-sidebar); |
| [3075](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3075) | font-weight: var(--sidebar-weight); |
| [3079](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3079) | -webkit-font-smoothing: antialiased; |
| [3080](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3080) | font-synthesis: none; |
| [3101](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3101) | font-family: inherit; |
| [3128](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3128) | font-size: var(--sidebar-text-xs); |
| [3129](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3129) | font-weight: var(--sidebar-weight-strong); |
| [3134](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3134) | font-size: var(--sidebar-text-xs); |
| [3135](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3135) | font-weight: var(--sidebar-weight-strong); |
| [3159](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3159) | font-family: inherit; |
| [3160](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3160) | font-size: var(--sidebar-text); |
| [3161](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3161) | font-weight: var(--sidebar-weight); |
| [3207](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3207) | font-weight: var(--sidebar-weight); /* selection = background only */ |
| [3221](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3221) | font-size: 1rem; /* 16px — slightly above --sidebar-text (15px) */ |
| [3222](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3222) | font-weight: 700; |
| [3226](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3226) | font-size: inherit; |
| [3227](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3227) | font-weight: 700; |
| [3244](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3244) | font-size: var(--sidebar-text-sm); |
| [3417](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3417) | font-weight: var(--sidebar-weight); |
| [3434](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3434) | font-size: var(--sidebar-text-xs); |
| [3435](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3435) | font-weight: var(--sidebar-weight); |
| [3443](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3443) | font-size: var(--sidebar-text-xs); |
| [3444](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3444) | font-weight: var(--sidebar-weight); |
| [3452](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3452) | font-family: var(--font-sidebar); |
| [3453](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3453) | font-size: var(--sidebar-text); |
| [3454](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3454) | font-weight: var(--sidebar-weight); |
| [3461](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3461) | font-family: inherit; |
| [3462](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3462) | font-size: inherit; |
| [3463](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3463) | font-weight: inherit; |
| [3485](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3485) | font-weight: inherit; |
| [3530](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3530) | font-family: inherit; |
| [3531](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3531) | font-size: var(--sidebar-text); |
| [3532](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3532) | font-weight: var(--sidebar-weight); |
| [3542](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3542) | font: inherit; |
| [3555](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3555) | font-size: var(--sidebar-text-xs); |
| [3556](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3556) | font-weight: var(--sidebar-weight); |
| [3566](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3566) | font-family: var(--font-sidebar); |
| [3567](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3567) | font-size: var(--sidebar-text); |
| [3568](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3568) | font-weight: var(--sidebar-weight); |
| [3574](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3574) | font-family: inherit; |
| [3575](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3575) | font-size: inherit; |
| [3576](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3576) | font-weight: inherit; |
| [3584](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3584) | font-weight: var(--sidebar-weight-strong); |
| [3595](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3595) | font-family: inherit; |
| [3596](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3596) | font-size: var(--sidebar-text-xs); |
| [3597](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3597) | font-weight: var(--sidebar-weight); |
| [3607](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3607) | font-family: inherit; |
| [3613](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3613) | font-family: var(--font-ui); |
| [3614](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3614) | -webkit-font-smoothing: antialiased; |
| [3615](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3615) | font-synthesis: none; |
| [3694](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3694) | font-family: var(--font-terminal); |
| [3823](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3823) | font-size: 11.5px; |
| [3824](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3824) | font-weight: 500; |
| [3995](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:3995) | font-size: 11px; |
| [4056](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4056) | font-family: inherit; |
| [4057](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4057) | font-size: 12px; |
| [4058](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4058) | font-weight: 400; |
| [4071](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4071) | font-weight: 400; |
| [4134](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4134) | font-size: 10px; |
| [4135](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4135) | font-weight: 500; |
| [4255](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4255) | font-family: var(--font-ui); |
| [4256](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4256) | font-size: 11px; |
| [4257](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4257) | font-weight: 500; |
| [4266](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4266) | font-size: 10.5px; |
| [4267](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4267) | font-weight: 500; |
| [4307](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4307) | font-family: var(--font-ui); |
| [4368](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4368) | font-family: inherit; |
| [4369](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4369) | font-size: 17px; |
| [4370](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4370) | font-weight: 400; |
| [4390](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4390) | font-weight: 400; |
| [4452](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4452) | font-size: 12px; |
| [4453](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4453) | font-weight: 600; |
| [4477](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4477) | font-size: 15px; |
| [4478](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4478) | font-weight: 500; |
| [4487](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4487) | font-size: 13px; |
| [4488](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4488) | font-weight: 400; |
| [4592](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4592) | font-size: 14px; |
| [4593](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4593) | font-weight: 600; |
| [4609](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4609) | font-size: 11px; |
| [4610](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4610) | font-weight: 400; |
| [4626](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4626) | font-size: 12px; |
| [4627](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4627) | font-weight: 400; |
| [4642](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4642) | font-size: 12px; |
| [4659](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4659) | font-size: 11px; |
| [4731](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4731) | font-size: 15px; |
| [4732](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4732) | font-weight: 500; |
| [4738](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4738) | font-size: 14px; |
| [4765](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4765) | font-size: 15px; |
| [4787](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4787) | font-size: 13px; |
| [4788](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4788) | font-weight: 400; |
| [4799](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4799) | font-size: 11px; |
| [4800](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4800) | font-weight: 500; |
| [4843](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4843) | font-size: 13.5px; |
| [4844](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4844) | font-weight: 400; |
| [4855](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4855) | font-size: 12px; |
| [4856](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4856) | font-weight: 400; |
| [4866](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4866) | font-size: 12px; |
| [4884](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4884) | font-family: var(--font-ui); |
| [4885](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4885) | font-size: 15px; |
| [4891](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4891) | font-family: inherit; |
| [4919](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4919) | font-family: var(--font-display); |
| [4920](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4920) | font-weight: 600; |
| [4926](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4926) | font-size: 1.24rem; |
| [4930](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4930) | font-size: 1.08rem; |
| [4934](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4934) | font-size: 0.98rem; |
| [4972](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4972) | font-weight: 500; |
| [4997](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4997) | (--ds-chat-code-font, set by appearance-derive) takes over when present. */ |
| [4998](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4998) | font-family: var(--ds-chat-code-font, var(--font-ui)); |
| [4999](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:4999) | font-size: 0.8em; |
| [5015](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5015) | pack's custom code font takes over via --ds-chat-code-font. */ |
| [5016](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5016) | font-family: var(--ds-chat-code-font, monospace); |
| [5038](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5038) | font-family: var(--ds-chat-code-font, var(--font-ui)); |
| [5039](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5039) | font-size: 0.78em; |
| [5067](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5067) | font: inherit; |
| [5068](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5068) | font-weight: 500; |
| [5119](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5119) | font-weight: 550; |
| [5173](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5173) | font-weight: 500; |
| [5179](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5179) | font-weight: 600; |
| [5191](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5191) | --ds-tool-font: 13px; |
| [5214](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5214) | font-size: var(--ds-tool-font); |
| [5219](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5219) | font-size: var(--ds-tool-font); |
| [5341](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5341) | font-family: var(--font-mono); |
| [5342](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5342) | font-size: 10px; |
| [5343](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5343) | font-weight: 600; |
| [5426](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5426) | font-family: var(--font-mono); |
| [5427](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5427) | font-size: 11px; |
| [5428](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5428) | font-weight: 600; |
| [5683](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5683) | font-family: var(--font-ui); |
| [5684](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5684) | font-size: 11px; |
| [5753](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5753) | font-size: 13px; |
| [5773](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5773) | font-size: 13px; |
| [5774](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5774) | font-weight: 600; |
| [5781](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5781) | font-size: 12px; |
| [5797](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5797) | font-family: var(--font-mono); |
| [5798](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5798) | font-size: 11px; |
| [5806](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5806) | font-size: 11px; |
| [5807](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5807) | font-weight: 600; |
| [5819](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5819) | font-family: var(--font-mono); |
| [5820](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5820) | font-size: 12px; |
| [5849](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5849) | font-family: var(--font-ui); |
| [5850](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5850) | font-size: 11px; |
| [5851](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5851) | font-weight: 600; |
| [5866](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5866) | font-family: var(--font-mono); |
| [5867](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5867) | font-size: 12.5px; |
| [5886](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5886) | font-family: var(--font-ui); |
| [5887](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5887) | font-size: 10px; |
| [5951](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5951) | font-size: 12px; |
| [5960](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5960) | font-size: inherit; |
| [5976](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5976) | font-style: var(--shiki-dark-font-style) !important; |
| [5977](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:5977) | font-weight: var(--shiki-dark-font-weight) !important; |
| [6014](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6014) | font-size: 13px; |
| [6015](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6015) | font-weight: 600; |
| [6047](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6047) | font-size: 16px; |
| [6051](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6051) | -webkit-font-smoothing: antialiased; |
| [6097](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6097) | font-family: var(--font-display); |
| [6098](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6098) | font-weight: 650; |
| [6105](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6105) | font-size: 1.85rem; |
| [6112](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6112) | font-size: 1.35rem; |
| [6119](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6119) | font-size: 1.12rem; |
| [6126](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6126) | font-size: 1rem; |
| [6128](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6128) | font-weight: 600; |
| [6161](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6161) | font-weight: 650; |
| [6166](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6166) | font-style: italic; |
| [6201](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6201) | font-size: 0.88em; |
| [6213](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6213) | font-size: 0.94em; |
| [6230](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6230) | font-size: 15px; |
| [6246](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6246) | font-size: 1.42rem; |
| [6254](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6254) | font-size: 1.16rem; |
| [6260](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6260) | font-size: 1.04rem; |
| [6266](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6266) | font-size: 0.96rem; |
| [6292](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6292) | font-style: italic; |
| [6329](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6329) | font-family: var(--ds-chat-code-font, ui-monospace, monospace); |
| [6330](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6330) | font-size: 11px; |
| [6331](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6331) | font-weight: 500; |
| [6428](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6428) | font-family: var(--font-chat); |
| [6429](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6429) | font-size: var(--ds-chat-font-size, 14px); |
| [6458](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6458) | font-size: var(--ds-chat-font-size, 16px); |
| [6462](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6462) | -webkit-font-smoothing: antialiased; |
| [6514](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6514) | font-family: inherit; |
| [6515](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6515) | font-weight: 600; |
| [6524](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6524) | font-size: 1.4em; |
| [6530](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6530) | font-size: 1.35em; |
| [6536](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6536) | font-size: 1.25em; |
| [6542](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6542) | font-size: 1.1em; |
| [6563](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6563) | font-weight: 500; |
| [6565](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6565) | font-synthesis: none; |
| [6654](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6654) | font-family: var(--ds-chat-code-font, var(--font-mono), ui-monospace, monospace); |
| [6655](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6655) | font-size: 0.9em; |
| [6656](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6656) | font-weight: 400; |
| [6700](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6700) | font-size: 0.94em; |
| [6711](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6711) | font-weight: 500; |
| [6726](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6726) | font-size: 0.9em; |
| [6727](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6727) | font-weight: 500; |
| [6758](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6758) | font-family: var(--font-chat); |
| [6759](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6759) | font-size: var(--ds-chat-font-size, 14px); |
| [6760](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6760) | font-weight: 400; |
| [6773](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6773) | font-size: inherit; |
| [6774](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:6774) | font-weight: 500; |
| [7062](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7062) | -webkit-font-smoothing: subpixel-antialiased; |
| [7351](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7351) | font-family: var(--font-ui); |
| [7352](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7352) | -webkit-font-smoothing: antialiased; |
| [7353](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7353) | font-synthesis: none; |
| [7473](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7473) | font-size: 0.875rem; |
| [7474](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7474) | font-weight: 700; |
| [7599](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7599) | font-size: 0.75rem; |
| [7600](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7600) | font-weight: 600; |
| [7657](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7657) | font-size: 0.625rem; |
| [7658](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7658) | font-weight: 500; |
| [7665](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7665) | font-size: 0.8125rem; |
| [7666](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7666) | font-weight: 600; |
| [7702](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7702) | font-family: var(--font-ui); |
| [7703](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7703) | font-size: 0.8125rem; |
| [7704](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7704) | font-weight: 600; |
| [7707](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7707) | -webkit-font-smoothing: antialiased; |
| [7708](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7708) | font-synthesis: none; |
| [7725](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7725) | font-size: 0.8125rem; |
| [7726](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7726) | font-weight: 600; |
| [7746](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7746) | font-family: var(--font-ui); |
| [7747](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7747) | -webkit-font-smoothing: antialiased; |
| [7748](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7748) | font-synthesis: none; |
| [7865](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7865) | font-weight: 600; |
| [7870](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7870) | font-size: 0.75rem; |
| [7874](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7874) | font-size: 0.8125rem; |
| [7878](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7878) | font-size: 0.875rem; |
| [7909](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7909) | font-family: var(--font-terminal); |
| [7910](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:7910) | font-size: 0.8125rem; |
| [8232](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8232) | font-family: var(--ds-font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace); |
| [8233](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8233) | font-size: 12px; |
| [8510](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8510) | font-family: var(--font-ui); |
| [8650](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8650) | /* ── Appearance: UI density (spacing only, no font-size change) ───────────── |
| [8713](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8713) | :root[data-font-smoothing='off'] body, |
| [8714](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8714) | :root[data-font-smoothing='off'] body * { |
| [8715](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8715) | -webkit-font-smoothing: auto; |
| [8716](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8716) | -moz-osx-font-smoothing: auto; |
| [8722](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8722) | font-size: 12.5px; |
| [8723](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8723) | font-weight: 450; |
| [8769](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8769) | font: inherit; |
| [8770](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8770) | font-size: 14px; |
| [8771](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8771) | font-weight: 500; |
| [8785](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8785) | font-weight: 400; |
| [8840](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8840) | font-size: 14.5px; |
| [8841](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8841) | font-weight: 600; |
| [8853](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8853) | font-size: 12px; |
| [8854](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8854) | font-weight: 400; |
| [8864](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8864) | font-size: 10px; |
| [8865](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8865) | font-weight: 600; |
| [8949](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8949) | font-size: 17px; |
| [8950](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8950) | font-weight: 650; |
| [8958](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8958) | font-size: 13px; |
| [8965](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8965) | font-family: var(--font-mono, ui-monospace, monospace); |
| [8966](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8966) | font-size: 11px; |
| [8994](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:8994) | font-size: 12.5px; |
| [9006](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9006) | font-size: 12px; |
| [9007](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9007) | font-weight: 600; |
| [9019](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9019) | font: inherit; |
| [9020](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9020) | font-size: 14px; |
| [9054](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9054) | font-size: 13px; |
| [9055](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9055) | font-weight: 600; |
| [9106](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9106) | font-size: 13px; |
| [9107](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9107) | font-weight: 560; |
| [9171](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9171) | font-size: 13px; |
| [9172](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9172) | font-weight: 450; |
| [9184](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9184) | font-weight: 400; |
| [9210](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9210) | font-size: 13px; |
| [9211](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9211) | font-weight: 500; |
| [9293](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9293) | font-size: 13px; |
| [9294](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9294) | font-weight: 500; |
| [9323](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9323) | font-size: 12.5px; |
| [9341](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9341) | font-size: 13px; |
| [9351](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9351) | font-size: 15px; |
| [9352](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9352) | font-weight: 600; |
| [9359](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9359) | font-size: 13px; |
| [9385](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9385) | font-size: 14px; |
| [9386](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9386) | font-weight: 620; |
| [9393](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9393) | font-size: 12.5px; |
| [9394](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9394) | font-weight: 450; |
| [9461](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9461) | font-size: 14px; |
| [9462](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9462) | font-weight: 400; |
| [9472](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9472) | font-size: 12.5px; |
| [9473](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9473) | font-weight: 400; |
| [9508](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9508) | font-size: 12.5px; |
| [9509](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9509) | font-weight: 550; |
| [9616](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9616) | font-size: 12px; |
| [9617](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9617) | font-weight: 600; |
| [9911](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9911) | font-size: 15px; |
| [9912](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9912) | font-weight: 650; |
| [9926](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9926) | font-size: 11px; |
| [9927](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9927) | font-weight: 550; |
| [9944](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:9944) | font-size: 12px; |
| [10057](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10057) | font-size: 20px; |
| [10058](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10058) | font-weight: 650; |
| [10066](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10066) | font-size: 13px; |
| [10147](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10147) | font-size: 14px; |
| [10148](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10148) | font-weight: 500; |
| [10159](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10159) | font-size: 13px; |
| [10160](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10160) | font-weight: 400; |
| [10180](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10180) | font-size: 14px; |
| [10219](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10219) | font-size: 14px; |
| [10220](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10220) | font-weight: 400; |
| [10250](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10250) | font-size: 12px; |
| [10251](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10251) | font-weight: 560; |
| [10265](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10265) | font-size: 11.5px; |
| [10312](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10312) | font-size: 12px; |
| [10313](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10313) | font-weight: 550; |
| [10438](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10438) | font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; |
| [10439](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10439) | font-size: 13.5px; |
| [10440](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10440) | font-weight: 500; |
| [10459](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10459) | font-size: 12px; |
| [10471](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10471) | font-size: 13px; |
| [10541](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10541) | font-size: 14px; |
| [10567](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10567) | font-size: 14px; |
| [10568](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10568) | font-weight: 600; |
| [10646](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10646) | font-size: 14px; |
| [10647](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10647) | font-weight: 450; |
| [10700](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10700) | font-size: 14px; |
| [10701](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10701) | font-weight: 600; |
| [10864](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10864) | font-size: 12px; |
| [10865](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10865) | font-weight: 500; |
| [10929](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10929) | font-size: 13px; |
| [10930](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10930) | font-weight: 550; |
| [10940](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10940) | font-size: 11px; |
| [10941](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10941) | font-weight: 450; |
| [10997](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10997) | font-size: 10.5px; |
| [10998](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:10998) | font-weight: 600; |
| [11011](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11011) | font-size: 12px; |
| [11184](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11184) | font-family: var(--font-chat); |
| [11185](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11185) | font-size: var(--ds-answer-font-size, 16px); |
| [11193](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11193) | font-family: var(--font-chat); |
| [11256](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11256) | --ds-chat-font-size: 12px; |
| [11257](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11257) | --ds-chat-code-font-size: 11px; /* Synara chatCodePx ≈ base * 0.95 */ |
| [11258](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11258) | --ds-ide-font-base: 12px; |
| [11259](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11259) | --ds-ide-font-title: 13px; |
| [11260](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11260) | --ds-ide-font-meta: 11px; |
| [11261](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11261) | --ds-ide-font-code: 11px; |
| [11271](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11271) | font-size: var(--ds-ide-font-base); |
| [11279](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11279) | font-family: var(--font-chat); |
| [11280](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11280) | font-size: var(--ds-answer-font-size, 16px); |
| [11296](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11296) | font-weight: 500; /* Synara chat-markdown strong */ |
| [11297](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11297) | font-synthesis: none; |
| [11336](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11336) | font-family: inherit; |
| [11337](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11337) | font-weight: 600; |
| [11343](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11343) | font-size: 1.35em; |
| [11347](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11347) | font-size: 1.25em; |
| [11351](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11351) | font-size: 1.15em; |
| [11355](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11355) | font-size: 1.02em; |
| [11360](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11360) | font-size: 0.9em; |
| [11361](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11361) | font-weight: 400; |
| [11372](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11372) | font-size: calc(var(--ds-answer-font-size, 16px) * 0.9); |
| [11377](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11377) | font-size: 0.68rem; |
| [11384](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11384) | font-size: var(--ds-ide-font-base); |
| [11389](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11389) | font-size: var(--ds-ide-font-meta); |
| [11390](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11390) | font-weight: 600; |
| [11401](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11401) | font-size: var(--ds-ide-font-code); |
| [11406](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11406) | font-size: inherit; |
| [11412](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11412) | font-size: var(--ds-ide-font-title); |
| [11432](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11432) | font-size: var(--ds-ide-font-base); |
| [11439](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11439) | font-size: var(--ds-ide-font-base); |
| [11443](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11443) | font-size: var(--ds-ide-font-meta); |
| [11456](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11456) | --ds-tool-font: var(--ds-ide-font-base); |
| [11462](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11462) | font-size: var(--ds-ide-font-base); |
| [11470](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11470) | font-size: var(--ds-ide-font-base); |
| [11475](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11475) | font-size: var(--ds-ide-font-title); |
| [11479](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11479) | font-size: var(--ds-ide-font-title); |
| [11499](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11499) | --ds-tool-font: var(--ds-ide-font-base); |
| [11560](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11560) | font-size: 15px; |
| [11565](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11565) | font-size: 14px; |
| [11588](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11588) | font-size: var(--ds-ide-font-title); |
| [11595](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11595) | font-size: var(--ds-ide-font-base); |
| [11599](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11599) | font-size: var(--ds-ide-font-meta); |
| [11605](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11605) | font-size: var(--ds-ide-font-meta); |
| [11615](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11615) | font-family: var(--font-chat); |
| [11616](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11616) | font-size: var(--ds-answer-font-size, 16px); |
| [11617](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11617) | font-weight: 400; |
| [11626](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11626) | font-size: var(--ds-ide-font-base); |
| [11650](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11650) | font-size: var(--ds-ide-font-title); |
| [11658](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11658) | font-size: var(--ds-ide-font-base); |
| [11680](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11680) | font-size: var(--ds-ide-font-base); |
| [11685](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11685) | font-size: var(--ds-ide-font-base); |
| [11692](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11692) | font-size: var(--ds-ide-font-code); |
| [11697](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11697) | font-size: var(--ds-ide-font-base); |
| [11701](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11701) | font-size: var(--ds-ide-font-base); |
| [11708](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11708) | font-size: var(--ds-ide-font-base); |
| [11715](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11715) | font-size: var(--ds-ide-font-base); |
| [11722](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11722) | font-size: var(--ds-ide-font-code); |
| [11728](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11728) | font-size: var(--ds-ide-font-base); |
| [11741](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11741) | font-size: var(--ds-ide-font-title); |
| [11748](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11748) | font-size: var(--ds-answer-font-size, 16px); |
| [11759](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11759) | font-family: var(--font-chat); |
| [11760](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11760) | font-size: var(--ds-answer-font-size, 16px); |
| [11761](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11761) | font-weight: 400; |
| [11789](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11789) | --ds-ide-font-base: 12px; |
| [11790](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11790) | --ds-ide-font-title: 13px; |
| [11791](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11791) | --ds-ide-font-meta: 11px; |
| [11792](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11792) | --ds-ide-font-code: 11px; |
| [11811](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11811) | font-size: var(--ds-ide-font-base); |
| [11816](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11816) | font-size: var(--ds-ide-font-title); |
| [11834](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11834) | font-size: var(--ds-ide-font-base); |
| [11840](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11840) | font-size: var(--ds-ide-font-base); |
| [11845](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11845) | font-size: var(--ds-ide-font-base); |
| [11852](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11852) | font-size: var(--ds-ide-font-base); |
| [11856](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11856) | font-size: var(--ds-ide-font-meta); |
| [11862](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11862) | font-size: var(--ds-answer-font-size, 16px); |
| [11876](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11876) | font-size: var(--ds-ide-font-title); |
| [11880](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/index.css:11880) | font-size: var(--ds-ide-font-base); |

## lib/apply-appearance.ts

| 行号 | 声明／组件上下文 |
|---|---|
| [61](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-appearance.ts:61) | // specificity (e.g. --font-ui vs :root[data-ui-font=…]) resolve to us. |
| [68](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-appearance.ts:68) | root.style.setProperty('--ds-chat-font-size', `${appearance.chatFontSizePx}px`) |
| [70](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-appearance.ts:70) | root.style.setProperty('--ds-answer-font-size', `${appearance.chatFontSizePx}px`) |
| [72](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-appearance.ts:72) | // Terminal font: index.css defines --font-terminal at :root; an inline |
| [79](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-appearance.ts:79) | root.style.setProperty('--font-terminal', stack) |
| [81](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-appearance.ts:81) | root.style.removeProperty('--font-terminal') |
| [85](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-appearance.ts:85) | root.removeAttribute('data-font-smoothing') |
| [87](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-appearance.ts:87) | root.setAttribute('data-font-smoothing', 'off') |

## lib/apply-theme.ts

| 行号 | 声明／组件上下文 |
|---|---|
| [53](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-theme.ts:53) | const family = getComputedStyle(document.documentElement).getPropertyValue('--font-ui').trim() |
| [59](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/apply-theme.ts:59) | const family = getComputedStyle(document.documentElement).getPropertyValue('--font-terminal').trim() |

## lib/load-mermaid.ts

| 行号 | 声明／组件上下文 |
|---|---|
| [58](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/load-mermaid.ts:58) | fontFamily: 'var(--font-mono), ui-monospace, monospace', |

## lib/preview-element-picker.ts

| 行号 | 声明／组件上下文 |
|---|---|
| [236](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/preview-element-picker.ts:236) | fontSize: '12px', |
| [237](/Users/user/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/lib/preview-element-picker.ts:237) | fontFamily: 'system-ui, sans-serif', |
