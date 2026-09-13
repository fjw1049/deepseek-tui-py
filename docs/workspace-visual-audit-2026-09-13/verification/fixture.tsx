import React from 'react'
import { createRoot } from 'react-dom/client'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import * as monaco from 'monaco-editor'
import '../../../packages/workbench/src/renderer/src/index.css'
import en from '../../../packages/workbench/src/renderer/src/locales/en/common.json'
import zh from '../../../packages/workbench/src/renderer/src/locales/zh/common.json'
import { WorkspaceEditorPanel } from '../../../packages/workbench/src/renderer/src/components/workspace-editor/WorkspaceEditorPanel'
import { MarkdownDocumentPreview } from '../../../packages/workbench/src/renderer/src/components/workspace-editor/MarkdownDocumentPreview'
import { DiffView } from '../../../packages/workbench/src/renderer/src/components/DiffView'
import { useWorkspaceEditorStore as store } from '../../../packages/workbench/src/renderer/src/store/workspace-editor-store'

await i18n.use(initReactI18next).init({ lng: 'zh', fallbackLng: 'en', resources: { en: { common: en }, zh: { common: zh } }, defaultNS: 'common', interpolation: { escapeValue: false } })
const code = `// 工作区文件 · 保持代码与中文注释的阅读节奏\nexport function buildWorkspacePath(root: string, segments: string[]) {\n  return segments.filter(Boolean).map(segment => root + '/' + segment).join('/');\n}\n\n` + Array.from({length: 150}, (_, i) => `const value${i} = ${i};`).join('\n')
const markdown = '# 工作区编辑体验\n\n文件树、编辑器和更改视图使用一致的视觉节奏。中英文混排保持自然间距，让内容成为阅读的重点。\n\n## 代码示例\n\n```typescript\nexport function greet(name: string) {\n  return `你好，${name}`;\n}\n```\n\n- 保留阅读位置\n- 清晰区分未保存与 Git 更改\n'
const tabs = [
  ['/sample/src/workspace.ts', code],
  ['/sample/src/model.ts', 'export const model = { ready: true };'],
  ['/sample/README.md', markdown]
].map(([path, content]) => ({ id: path, path, content, savedContent: content, kind: 'text', loading: false, error: null }))
Object.assign(tabs[0], {line:3,revealNonce:1})
store.setState({ workspaceKey: '/sample', tabs, primaryTabIds: tabs.map(t => t.id), activeTabId: tabs[0].id })
window.dsGui = { listWorkspaceDirectory: async () => ({ok:true, entries:tabs.map(t=>({path:t.path,name:t.path.split('/').pop(),kind:'file'}))}) }
const patch = '@@ -1,4 +1,4 @@\n // 工作区文件 · 清晰呈现实际更改\n-export const title = "Old workspace";\n+export const title = "新的工作区";\n-export const path = root;\n+export const path = segments.filter(Boolean).map(segment => normalizeWorkspaceSegment(segment, root)).join("/");\n export const ready = true;'
window.audit = { store, monaco, i18n, tabs, patch }
createRoot(document.getElementById('root')!).render(<div className="ds-ide-workspace" style={{height:'100vh',display:'flex',flexDirection:'column',background:'var(--ds-bg-canvas)',color:'var(--ds-text)'}}>
  <div style={{padding:'10px 16px',fontSize:12,borderBottom:'1px solid var(--ds-border)'}}>真实组件验证 · 示例文件（不读写实际项目文件）</div>
  <div id="editor-fixture" style={{height:'52%',minHeight:0}}><WorkspaceEditorPanel workspaceRoot="/sample" blocks={[]} /></div>
  <div style={{display:'flex',flex:1,minHeight:0,borderTop:'1px solid var(--ds-border)'}}>
    <div id="diff-fixture" style={{width:'55%',minWidth:0}}><DiffView patch={patch} filePath="/sample/src/workspace.ts" chrome="flush" showStyleToggle /></div>
    <div id="markdown-fixture" style={{display:'flex',width:'45%',minWidth:0,borderLeft:'1px solid var(--ds-border)'}}><MarkdownDocumentPreview content={markdown} /></div>
  </div>
</div>)
