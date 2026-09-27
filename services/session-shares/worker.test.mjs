import { test } from 'node:test'
import assert from 'node:assert/strict'
const origin = process.env.SHARE_TEST_ORIGIN || 'http://127.0.0.1:8791'
const snapshot = {format:'deepseek-session-share',version:1,title:'回家继续测试 <script>alert(1)</script>',turns:[{}],items:[{kind:'user_message',summary:'先完成登录页面'},{kind:'agent_message',detail:'已完成页面，下一步补测试。'}]}

test('persistent upload, escaped browser preview, capability deletion, unavailable after revocation', async () => {
  const health = await fetch(origin+'/health'); assert.equal(health.status,200)
  const response = await fetch(origin+'/v1/shares',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({snapshot})})
  assert.equal(response.status,201,await response.clone().text())
  const {token,delete_key,expires_at} = await response.json()
  assert.match(token,/^[A-Za-z0-9_-]{43}$/); assert.notEqual(token,delete_key)
  assert.ok(Date.parse(expires_at)>Date.now())
  try {
    const read = await fetch(origin+'/v1/shares/'+token)
    assert.equal(read.status,200); assert.deepEqual((await read.json()).snapshot,snapshot)
    const page = await fetch(origin+'/s/'+token); const html = await page.text()
    assert.equal(page.status,200); assert.match(html,/在应用中继续/); assert.match(html,/下一步补测试/)
    assert.ok(!html.includes('<script>')); assert.match(html,/&lt;script&gt;/)
    assert.equal(page.headers.get('cache-control'),'no-store')
    assert.equal((await fetch(origin+'/v1/shares/'+token,{method:'DELETE'})).status,403)
    assert.equal((await fetch(origin+'/v1/shares/'+token,{method:'DELETE',headers:{Authorization:'Bearer '+token}})).status,403)
  } finally {
    assert.equal((await fetch(origin+'/v1/shares/'+token,{method:'DELETE',headers:{Authorization:'Bearer '+delete_key}})).status,204)
  }
  assert.equal((await fetch(origin+'/s/'+token)).status,404)
  assert.equal((await fetch(origin+'/v1/shares/'+token)).status,404)
})

test('reject unsupported snapshots and oversize requests', async () => {
  assert.equal((await fetch(origin+'/v1/shares',{method:'POST',body:JSON.stringify({snapshot:{...snapshot,version:99}})})).status,400)
  assert.equal((await fetch(origin+'/v1/shares',{method:'POST',body:'x'.repeat(8*1024*1024+1)})).status,413)
})
