// Drive REAL trusted input (Input.dispatchMouseEvent) at the running Electron
// renderer and measure frame pacing + scroll response over the query rail.
const WebSocket = require('ws')
const http = require('http')

function getTargets() {
  return new Promise((resolve, reject) => {
    http
      .get('http://127.0.0.1:9222/json', (res) => {
        let d = ''
        res.on('data', (c) => (d += c))
        res.on('end', () => resolve(JSON.parse(d)))
      })
      .on('error', reject)
  })
}

async function main() {
  const targets = await getTargets()
  const page = targets.find((t) => t.type === 'page')
  if (!page) throw new Error('no page target')
  const ws = new WebSocket(page.webSocketDebuggerUrl, { perMessageDeflate: false })
  let id = 0
  const pending = new Map()
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const mid = ++id
      pending.set(mid, { resolve, reject })
      ws.send(JSON.stringify({ id: mid, method, params }))
    })
  ws.on('message', (raw) => {
    const msg = JSON.parse(raw)
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id)
      pending.delete(msg.id)
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
    }
  })
  await new Promise((r) => ws.on('open', r))

  const evalJson = async (expression) => {
    const res = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    return res.result?.value
  }

  const rail = await evalJson(`(() => {
    const nav = document.querySelector('nav[aria-label="Query navigation"]')
    if (!nav) return null
    const r = nav.getBoundingClientRect()
    const scroller = document.querySelector('.ds-scroll-surface')
    return { x: r.left + 10, top: r.top + r.height * 0.35, bottom: r.top + r.height * 0.65, scrollTop: scroller ? scroller.scrollTop : null }
  })()`)
  if (!rail) throw new Error('no rail')

  // Start frame monitor in page
  await evalJson(`(() => {
    window.__frameDeltas = []
    window.__stopFrames = false
    let last = performance.now()
    const loop = (now) => { window.__frameDeltas.push(now - last); last = now; if (!window.__stopFrames) requestAnimationFrame(loop) }
    requestAnimationFrame(loop)
    return true
  })()`)

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  // Phase 1: sweep the pointer up/down the rail (magnification follows)
  let y = rail.top
  let dir = 1
  for (let i = 0; i < 120; i += 1) {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: rail.x, y, button: 'none' })
    y += dir * 4
    if (y > rail.bottom || y < rail.top) dir = -dir
    await sleep(8)
  }
  // Phase 2: wheel over the rail (should scroll the chat)
  for (let i = 0; i < 40; i += 1) {
    await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: rail.x, y, deltaX: 0, deltaY: i < 20 ? 40 : -40 })
    await sleep(12)
  }
  await sleep(150)
  const result = await evalJson(`(() => {
    window.__stopFrames = true
    const d = window.__frameDeltas.slice(5)
    d.sort((a, b) => a - b)
    const p = (q) => +d[Math.floor(d.length * q)].toFixed(1)
    const scroller = document.querySelector('.ds-scroll-surface')
    return { frames: d.length, p50: p(0.5), p90: p(0.9), p99: p(0.99), max: +d[d.length - 1].toFixed(1), scrollTopAfter: scroller ? scroller.scrollTop : null }
  })()`)
  console.log(JSON.stringify({ scrollTopBefore: rail.scrollTop, ...result }, null, 2))
  ws.close()
}

main().catch((e) => {
  console.error('ERR', e.message)
  process.exit(1)
})
