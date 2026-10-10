/** Development preview using the production assistance card; no runtime requests. */
import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { AssistanceCard, type Assistance } from './components/BrowserAssistanceCard'
import i18n from './i18n'
import './index.css'

void i18n.changeLanguage('zh')
function Preview(): React.ReactElement {
  const [scenario, setScenario] = useState('login')
  const [request, setRequest] = useState<Assistance | null>({ id: 'preview', thread_id: 'preview', status: 'pending', reason: '资料下载需要登录。请在网页上完成登录，我会接着整理安装步骤。' })
  const [verified, setVerified] = useState(false)
  const [receipt, setReceipt] = useState('')
  const [away, setAway] = useState(false)
  const reset = (next = scenario): void => {
    setScenario(next); setVerified(false); setReceipt(''); setAway(false)
    setRequest({ id: String(Date.now()), thread_id: 'preview', status: 'pending', reason: next === 'long' ? '在查找资料时，网站要求先确认访问者身份，当前还没有显示你需要的内容。请在网页完成验证，我会继续处理原来的任务。' + '此前找到的资料和任务进度都已保留，无需重新开始。'.repeat(7) : next === 'optional' ? '页面出现了登录提示。如果不影响查看资料，可以忽略并继续。' : next === 'verify' ? '网站需要确认是真人访问。请完成网页上的安全验证。' : '资料下载需要登录。请在网页上完成登录，我会接着整理安装步骤。' })
  }
  return <main style={{ maxWidth: 1100, margin: '32px auto', padding: 20, color: 'var(--ds-text)' }}>
    <div className="mb-5 flex flex-wrap items-center gap-3"><h1 className="mr-auto text-lg">浏览器协助 · 实际组件预览</h1><label className="text-sm">场景 <select className="rounded border border-ds-border bg-ds-main p-2" value={scenario} onChange={e => reset(e.target.value)}><option value="login">需要登录</option><option value="verify">安全验证</option><option value="optional">无关的登录提示</option><option value="long">较长说明</option></select></label><button className="rounded border border-ds-border p-2 text-sm" onClick={() => reset()}>重新体验</button><button className="rounded border border-ds-border p-2 text-sm" onClick={() => setAway(true)}>离开应用</button></div>
    <div className="overflow-hidden rounded-xl border border-ds-border bg-ds-main"><header className="flex items-center gap-3 border-b border-ds-border bg-ds-sidebar px-5 py-3"><strong>DeepSeek</strong><span className="text-sm text-ds-muted">／ 整理产品资料</span><span className="ml-auto text-xs text-ds-muted">{request ? request.status === 'human' ? '你正在操作' : '等你处理' : '继续执行中'}</span></header>
      {away ? <div className="flex min-h-96 flex-col items-center justify-center gap-5 bg-ds-sidebar p-6"><p className="text-xs text-ds-muted">桌面通知效果模拟</p><div className="max-w-sm rounded-xl border border-ds-border bg-ds-canvas p-5"><strong>需要你帮一下忙</strong><p className="my-3 text-sm">浏览器任务需要你处理，进度已保留。</p><button className="rounded-lg border border-ds-border px-3 py-2" onClick={() => setAway(false)}>返回处理</button></div></div> : <div className="grid md:grid-cols-2"><section className="flex min-h-96 flex-col gap-5 p-5"><p className="self-end rounded-xl bg-ds-sidebar p-3 text-sm">帮我找到产品手册，整理安装步骤。</p><p className="text-xs text-ds-muted">✓ 已找到官方资料中心</p>{request ? <AssistanceCard key={request.id} request={request} onReveal={() => document.getElementById('preview-site')?.focus()} onRespond={async (choice, text) => {
        if (choice === 'takeover') { setRequest({ ...request, status: 'human' }); return }
        await new Promise(resolve => setTimeout(resolve, 700))
        if (choice === 'continue' && !verified) throw new Error('网页仍显示验证未完成。请先在右侧完成模拟验证。')
        if (choice === 'ignore' && scenario !== 'optional') { setRequest({ ...request, id: String(Date.now()), status: 'pending', reason: '已尝试直接打开手册，网站仍要求登录。没有找到公开下载入口，需要你处理。' }); return }
        setRequest(null); setReceipt(choice === 'information' ? `已收到补充信息：${text}` : choice === 'ignore' ? '已忽略无关提示，继续查找公开资料。' : '已接回操作，继续整理安装步骤。')
      }} /> : <p className="ds-assistance-receipt">✓ {receipt}</p>}<div className="mt-auto rounded-xl border border-ds-border p-3 text-xs text-ds-muted">随时补充要求…</div></section><section className="flex flex-col border-l border-ds-border bg-ds-canvas" style={request?.status === 'human' ? { boxShadow: 'inset 0 0 0 2px var(--ds-accent)' } : undefined}><div className="border-b border-ds-border px-4 py-3 text-sm">浏览器 <span className="ml-3 text-xs text-ds-muted">资料中心 · 示例网站</span></div><div className="flex flex-1 flex-col items-center justify-center gap-4 p-8"><h2 className="text-lg">产品资料中心</h2><p className="text-sm text-ds-muted">{!request ? '产品手册 · 安装与快速开始' : verified ? '验证已完成，可以返回任务继续' : '完成验证后查看产品手册'}</p><button id="preview-site" className="rounded-lg border border-ds-border px-4 py-2 text-sm disabled:opacity-40" disabled={request?.status !== 'human' || verified} onClick={() => setVerified(true)}>模拟完成{scenario === 'verify' ? '安全验证' : '登录'}</button></div><footer className="border-t border-ds-border p-4 text-xs text-ds-muted">{request?.status === 'human' ? '你正在操作 · 自动操作已暂停' : request ? '等待你的选择' : '助手正在操作'}</footer></section></div>}
    </div><p className="mt-4 text-xs text-ds-muted">使用已接入系统的真实协助卡组件；此页面的网站和通知为模拟，不会访问账号或启动任务。</p>
  </main>
}
createRoot(document.getElementById('root')!).render(<Preview />)
