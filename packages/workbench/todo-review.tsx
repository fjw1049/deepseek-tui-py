import React from 'react'
import { createRoot } from 'react-dom/client'
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import zh from './src/renderer/src/locales/zh/common.json'
import { InlineTodoBlock } from './src/renderer/src/components/chat/InlineTodoBlock'
import './src/renderer/src/index.css'
i18n.use(initReactI18next).init({ lng: 'zh', resources: { zh: { common: zh } }, defaultNS: 'common' })
const items = [
 {id:'1',content:'梳理现有任务列表的数据流',status:'completed'},
 {id:'2',content:'优化中文长任务描述的换行，检查 packages/workbench/src/renderer/src/components/chat/InlineTodoBlock.tsx 在窄侧栏中的显示',status:'in_progress'},
 {id:'3',content:'验证完成、取消和重新展开的交互',status:'pending'},
 {id:'4',content:'额外的百分比进度展示',status:'cancelled'},
]
function Demo() {
 const [done,setDone]=React.useState(false)
 return <main style={{padding:32, display:'flex', gap:32, alignItems:'flex-start', flexWrap:'wrap'}}>
  {['light','dark'].map(theme=><div key={theme} data-theme={theme} style={{background:'var(--ds-bg-main)',color:'var(--ds-text)',padding:24,width:380}}>
  <h2>{theme} · 中文窄栏</h2><InlineTodoBlock active={!done} session={{anchorBlockId:theme,todoBlockIds:[],items:done?items.map(x=>({...x,status:'completed'})):items,completionPct:done?100:25,inProgressId:done?null:'2',isComplete:done}} />
  <button onClick={()=>setDone(!done)}>切换全部完成</button></div>)}
 </main>
}
createRoot(document.getElementById('root')!).render(<Demo/>);
