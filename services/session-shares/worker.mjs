const MAX_BYTES = 8 * 1024 * 1024
const TOKEN = /^[A-Za-z0-9_-]{43}$/
const headers = {
  'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff', 'X-Robots-Tag': 'noindex, nofollow',
}
const json = (value, status = 200) => new Response(JSON.stringify(value), {status, headers: {...headers, 'Content-Type':'application/json'}})
const fail = (status, detail) => { throw Object.assign(new Error(detail), {status}) }
const random = () => btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))).replaceAll('+','-').replaceAll('/','_').replaceAll('=','')
const hash = async value => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))), x => x.toString(16).padStart(2,'0')).join('')
const query = (env, sql, ...values) => env.DB.prepare(sql).bind(...values)

// Rate limits are durable and atomic; no shared client administrator credential.
async function allowance(env, key, limit, now) {
  const row = await query(env, `INSERT INTO quotas (key,count,expires_at) VALUES (?,1,?)
    ON CONFLICT(key) DO UPDATE SET count=count+1 WHERE count < ? RETURNING count`, key, now + 86400, limit).first()
  if (!row) fail(429, '今日分享次数已达上限，请明天再试。')
}
async function cleanup(env, now) {
  const expired = await query(env, 'SELECT token FROM shares WHERE expires_at <= ? LIMIT 100', now).all()
  for (const {token} of expired.results) {
    await env.BUCKET.delete(token)
    await query(env, 'DELETE FROM shares WHERE token = ? AND expires_at <= ?', token, now).run()
  }
  await query(env, 'DELETE FROM quotas WHERE expires_at <= ?', now).run()
}
async function body(request) {
  if (Number(request.headers.get('Content-Length')) > MAX_BYTES) fail(413, '分享内容超过 8 MiB，请取消附带项目文件或缩小会话。')
  const reader = request.body?.getReader()
  if (!reader) fail(400, '缺少会话内容')
  const chunks = []; let size = 0
  for (;;) {
    const {done, value} = await reader.read()
    if (done) break
    size += value.byteLength
    if (size > MAX_BYTES) { await reader.cancel(); fail(413, '分享内容超过 8 MiB') }
    chunks.push(value)
  }
  const data = new Uint8Array(size); let offset = 0
  for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.byteLength }
  let payload
  try { payload = JSON.parse(new TextDecoder().decode(data)) } catch { fail(400, '无效的会话内容') }
  const s = payload?.snapshot
  if (!s || s.format !== 'deepseek-session-share' || s.version !== 1 || typeof s.title !== 'string' || !Array.isArray(s.items) || !Array.isArray(s.turns) || !s.turns.length) fail(400, '无效的会话内容')
  const days = payload.expires_in_days ?? 7
  if (!Number.isInteger(days) || days < 1 || days > 30) fail(400, '无效的有效期')
  return {data, days}
}
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
const favicon = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%232563eb'/%3E%3Cpath d='M8 9h16v11H14l-6 5z' fill='white'/%3E%3C/svg%3E"
function page(content, status = 200) {
  return new Response(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>DeepSeek Workbench · 会话分享</title><link rel="icon" href="${favicon}"><style>
  *{box-sizing:border-box}body{margin:0;background:#f6f8fc;color:#172238;font:16px/1.75 system-ui,-apple-system,sans-serif}main{max-width:800px;margin:auto;padding:40px 24px 80px}header{font-size:14px;color:#52627a;margin-bottom:28px}h1{font-size:28px;line-height:1.4;overflow-wrap:anywhere}p{margin:12px 0}.hint{color:#52627a;font-size:14px}.action{display:inline-block;background:#2563eb;color:white;text-decoration:none;border-radius:10px;padding:10px 20px}article{padding:22px;background:white;border:1px solid #dfe6f0;border-radius:14px;margin:18px 0}article b{font-size:14px;color:#2563eb}.message{white-space:pre-wrap;overflow-wrap:anywhere;margin-top:8px}img{max-width:100%;height:auto;border-radius:10px}footer{margin-top:28px;font-size:14px;color:#52627a}@media(max-width:480px){main{padding:24px 16px}h1{font-size:24px}}
  </style></head><body><main><header>DeepSeek Workbench / 会话分享</header>${content}<footer>分享的是当时的对话副本，之后的新消息不会同步。</footer></main></body></html>`, {status,headers:{...headers,'Content-Type':'text/html; charset=utf-8','Content-Security-Policy':"default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"}})
}
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url), now = Math.floor(Date.now()/1000)
    try {
      if (request.method === 'GET' && url.pathname === '/health') {
        await query(env, 'SELECT count(*) AS count FROM shares').first()
        await env.BUCKET.list({limit:1})
        return json({ok:true, protocol:1, max_bytes:MAX_BYTES})
      }
      if (request.method === 'GET' && url.pathname === '/') return page('<h1>让对话接着进行</h1><p>在 DeepSeek Workbench 的会话右上角点击「分享」，复制链接。</p><p>换一台电脑打开链接，再点击「在应用中继续」。</p><p class="hint">拿到完整链接的人可以查看。默认 7 天后失效，也可由分享者提前撤销。</p>')
      if (request.method === 'POST' && url.pathname === '/v1/shares') {
        const day = Math.floor(now / 86400)
        const ip = request.headers.get('CF-Connecting-IP') || 'unknown'
        await allowance(env, `all:${day}`, 1000, now)
        await allowance(env, `ip:${day}:${await hash(ip)}`, 30, now)
        const {data, days} = await body(request)
        const token = random(), deletion = random(), expires = now + days * 86400
        await env.BUCKET.put(token, data)
        try { await query(env,'INSERT INTO shares (token,delete_hash,expires_at) VALUES (?,?,?)',token,await hash(deletion),expires).run() }
        catch (error) { await env.BUCKET.delete(token); throw error }
        ctx.waitUntil(cleanup(env, now).catch(error => console.error('share cleanup failed', error.message)))
        return json({token, delete_key:deletion, expires_at:new Date(expires*1000).toISOString()},201)
      }
      const match = url.pathname.match(/^\/(v1\/shares|s)\/([A-Za-z0-9_-]{43})$/)
      if (!match) fail(404, '分享不存在')
      const [, route, token] = match
      if (!TOKEN.test(token)) fail(404, '分享不存在')
      const row = await query(env,'SELECT delete_hash,expires_at FROM shares WHERE token = ?', token).first()
      if (!row) fail(404, '分享不存在或已撤销')
      if (row.expires_at <= now) {
        ctx.waitUntil(cleanup(env, now).catch(error => console.error('share cleanup failed',error.message)))
        fail(410, '分享已到期')
      }
      if (request.method === 'DELETE' && route === 'v1/shares') {
        const key = request.headers.get('Authorization')?.replace(/^Bearer /,'') || ''
        if (!TOKEN.test(key) || await hash(key) !== row.delete_hash) fail(403,'只有分享者可以撤销链接')
        await env.BUCKET.delete(token)
        await query(env,'DELETE FROM shares WHERE token = ?',token).run()
        return new Response(null,{status:204,headers})
      }
      if (request.method !== 'GET') fail(405, '不支持此操作')
      const object = await env.BUCKET.get(token)
      if (!object) fail(503,'分享内容正在同步，请稍后重试')
      if (route === 'v1/shares') return new Response(object.body,{headers:{...headers,'Content-Type':'application/json'}})
      const {snapshot:s} = await object.json()
      const link = 'deepseek-gui://share?url=' + encodeURIComponent(url.origin + url.pathname)
      const messages = s.items.filter(i => ['user_message','agent_message'].includes(i.kind)).map(i => `<article><b>${i.kind === 'user_message' ? '你' : 'AI'}</b><div class="message">${escape(i.detail || i.summary || '')}</div></article>`).join('')
      const images = Object.values(s.media || {}).filter(v => typeof v === 'string' && /^[A-Za-z0-9+/=]+$/.test(v)).map(v => `<img alt="对话附件" src="data:image/png;base64,${v}">`).join('')
      return page(`<h1>${escape(s.title)}</h1><p class="hint">${escape(new Date(row.expires_at*1000).toISOString().slice(0,10))} 到期 · 拿到链接的人可以查看</p><a class="action" href="${escape(link)}">在应用中继续</a><p class="hint">如未自动打开，可复制本页链接，在应用里选择「分享 → 打开分享」。</p>${messages}${images}`)
    } catch(error) {
      const status = error.status || 503
      if (!error.status) console.error('share request failed', error.message)
      const detail = error.status ? error.message : '分享服务暂时无法连接，请稍后重试。'
      return url.pathname.startsWith('/s/') ? page(`<h1>这个分享暂时无法打开</h1><p>${escape(detail)}</p><p class="hint">请联系分享者获取新的链接。</p>`,status) : json({detail}, status)
    }
  },
}
