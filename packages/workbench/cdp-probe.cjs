// Probe the running Electron renderer over CDP: screenshot + style diagnostics.
const WebSocket = require('ws')
const fs = require('fs')
const http = require('http')

function getTargets() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:9222/json', (res) => {
      let d = ''
      res.on('data', (c) => (d += c))
      res.on('end', () => resolve(JSON.parse(d)))
    }).on('error', reject)
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

  const evalExpr = process.argv[2]
  if (evalExpr && evalExpr !== '-') {
    const res = await send('Runtime.evaluate', {
      expression: evalExpr,
      returnByValue: true,
      awaitPromise: true
    })
    console.log(JSON.stringify(res.result?.value ?? res, null, 2))
  }

  const shotPath = process.argv[3]
  if (shotPath) {
    const shot = await send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(shotPath, Buffer.from(shot.data, 'base64'))
    console.log('screenshot ->', shotPath)
  }
  ws.close()
}

main().catch((e) => {
  console.error('ERR', e.message)
  process.exit(1)
})
