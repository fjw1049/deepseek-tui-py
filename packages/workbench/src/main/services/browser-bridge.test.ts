import { EventEmitter } from 'node:events'
import { beforeEach, expect, it, vi } from 'vitest'
import { createBrowserBridge } from './browser-bridge'

const mocks = vi.hoisted(() => ({ server: null as any, guests: new Map<number, any>(), partition: null as any }))
vi.mock('http', () => ({ createServer: () => mocks.server }))
vi.mock('electron', () => ({
  session: { fromPartition: () => mocks.partition },
  webContents: { fromId: (id: number) => mocks.guests.get(id) }
}))
vi.mock('ws', () => ({ WebSocketServer: class {
  handleUpgrade(_request: unknown, socket: unknown, _head: unknown, callback: (socket: unknown) => void) { callback(socket) }
} }))
vi.mock('../logger', () => ({ logWarn: vi.fn() }))

beforeEach(() => {
  mocks.server = Object.assign(new EventEmitter(), { listen: (_port: number, _host: string, done: () => void) => done(), address: () => ({ port: 1234 }) })
  mocks.partition = new EventEmitter()
  mocks.guests.clear()
})

async function harness() {
  let sequence = 0
  const attached = new Map<string, string>()
  const debug = Object.assign(new EventEmitter(), {
    isAttached: () => true, attach: vi.fn(), detach: vi.fn(),
    sendCommand: vi.fn(async (method: string, params: Record<string, any> = {}, sid?: string): Promise<any> => {
      if (method === 'Target.getTargets') return { targetInfos: [
        { targetId: 'host', type: 'page' }, { targetId: 'child', type: 'iframe' },
        { targetId: 'grandchild', type: 'iframe' }, { targetId: 'other', type: 'iframe' }
      ] }
      if (method === 'Target.attachToTarget') { const sessionId = `s${++sequence}`; attached.set(sessionId, params.targetId); return { sessionId } }
      if (method === 'Target.detachFromTarget') { attached.delete(params.sessionId); return {} }
      if (method === 'Page.getFrameTree') {
        const id = sid ? attached.get(sid)! : 'root'
        return { frameTree: { frame: { id, parentId: ({ child: 'root', grandchild: 'child', other: 'outside' } as Record<string, string>)[id] } } }
      }
      return { target: sid ? attached.get(sid) : 'root' }
    })
  })
  const guest = Object.assign(new EventEmitter(), { debugger: debug, id: 2, isDestroyed: () => false,
    getType: () => 'webview', hostWebContents: { id: 1 }, session: mocks.partition, getURL: () => 'http://example.test', getTitle: () => 'Test' })
  mocks.guests.set(2, guest)
  let token = ''
  const commands: any[] = []
  const bridge = createBrowserBridge({ getHost: () => ({ id: 1 }) as any,
    announce: async (_port, value) => { token = value },
    sendCommand: (id, command) => { commands.push(command); bridge.reply(id, { ok: true }) }
  })
  await bridge.start(); await bridge.announce()
  bridge.setTabs('one', [{ tabId: 'tab', webContentsId: 2, active: true, visible: true }])
  const messages: any[] = []
  const socket = Object.assign(new EventEmitter(), { readyState: 1, OPEN: 1,
    send: (value: string) => { messages.push(JSON.parse(value)) }, destroy: vi.fn(),
    close: () => { socket.readyState = 3; socket.emit('close') }
  })
  mocks.server.emit('upgrade', { url: `/tab/tab?token=${token}`, headers: {} }, socket, Buffer.alloc(0))
  let requestId = 0
  async function send(method: string, params: Record<string, unknown> = {}) {
    const id = ++requestId
    socket.emit('message', JSON.stringify({ id, method, params }))
    await vi.waitFor(() => expect(messages.some(m => m.id === id)).toBe(true))
    return messages.find(m => m.id === id)
  }
  return { debug, commands, messages, socket, send, bridge, guest, token }
}

it('checks nested commands and still supports legitimate child and grandchild sessions', async () => {
  const h = await harness()
  try {
    const targets = await h.send('Target.getTargets')
    expect(targets.result.targetInfos.map((t: any) => t.targetId)).toEqual(['child', 'grandchild'])
    const { sessionId } = (await h.send('Target.attachToTarget', { targetId: 'child', flatten: false })).result
    const nested = async (id: number, method: string, params = {}) => {
      await h.send('Target.sendMessageToTarget', { sessionId, message: JSON.stringify({ id, method, params }) })
      return h.messages.filter(m => m.method === 'Target.receivedMessageFromTarget').map(m => JSON.parse(m.params.message)).find(m => m.id === id)
    }
    expect((await nested(90, 'Target.attachToTarget', { targetId: 'host', flatten: false })).error.message).toContain('outside')
    expect((await nested(91, 'Target.getTargets')).result.targetInfos.map((t: any) => t.targetId)).toEqual(['grandchild'])
    const grandchild = (await nested(92, 'Target.attachToTarget', { targetId: 'grandchild', flatten: false })).result.sessionId
    await nested(93, 'Target.sendMessageToTarget', { sessionId: grandchild, message: JSON.stringify({ id: 94, method: 'Runtime.evaluate', params: { expression: '1' } }) })
    expect(h.debug.sendCommand).toHaveBeenCalledWith('Runtime.evaluate', { expression: '1' }, grandchild)
    expect((await nested(95, 'Browser.close')).error.message).toContain('not available')
    expect(h.debug.sendCommand.mock.calls.some(([method, params]) => method === 'Target.attachToTarget' && params?.targetId === 'host')).toBe(false)
    expect(h.debug.sendCommand.mock.calls.some(([method]) => method === 'Target.sendMessageToTarget')).toBe(false)
  } finally { h.socket.close() }
})

it('reports a detached frame session and forgets the sessions opened through it', async () => {
  const h = await harness()
  try {
    const child = (await h.send('Target.attachToTarget', { targetId: 'child', flatten: false })).result.sessionId
    await h.send('Target.sendMessageToTarget', { sessionId: child, message: JSON.stringify({
      id: 1, method: 'Target.attachToTarget', params: { targetId: 'grandchild', flatten: false }
    }) })
    const tunneled = () => h.messages.filter(m => m.method === 'Target.receivedMessageFromTarget')
    const grandchild = tunneled().map(m => JSON.parse(m.params.message)).find(m => m.id === 1).result.sessionId
    // Frame events still travel up through both sessions before the detach.
    h.debug.emit('message', {}, 'Runtime.consoleAPICalled', {}, grandchild)
    expect(tunneled()).toHaveLength(2)
    h.debug.emit('message', {}, 'Target.detachedFromTarget', { sessionId: child, targetId: 'child' })
    expect(h.messages).toContainEqual({ method: 'Target.detachedFromTarget', params: { sessionId: child, targetId: 'child' } })
    expect(h.debug.sendCommand).toHaveBeenCalledWith('Target.detachFromTarget', { sessionId: grandchild })
    h.debug.emit('message', {}, 'Runtime.consoleAPICalled', {}, grandchild)
    expect(tunneled()).toHaveLength(2)
    const stale = await h.send('Target.sendMessageToTarget', { sessionId: child, message: JSON.stringify({ id: 2, method: 'Runtime.evaluate', params: {} }) })
    expect(stale.error.message).toContain('outside')
  } finally { h.socket.close() }
})

it('retains a connected browser until its last page connection closes', async () => {
  const h = await harness()
  expect(h.commands[0]).toEqual({ kind: 'retain', browserId: 'one', retained: true })
  h.socket.close()
  expect(h.commands.at(-1)).toEqual({ kind: 'retain', browserId: 'one', retained: false })
})

it('keeps completed downloads available after the source connection closes', async () => {
  const h = await harness()
  await h.send('Browser.setDownloadBehavior', { behavior: 'allowAndName', downloadPath: '/tmp/audit-downloads' })
  const item = Object.assign(new EventEmitter(), { setSavePath: vi.fn(), getURL: () => 'https://example.test/file', getFilename: () => 'invoice.pdf', getReceivedBytes: () => 12, getTotalBytes: () => 12 })
  mocks.partition.emit('will-download', {}, item, h.guest)
  h.socket.close()
  item.emit('done', {}, 'completed')
  const messages: any[] = []
  const socket = Object.assign(new EventEmitter(), { readyState: 1, OPEN: 1, send: (value: string) => messages.push(JSON.parse(value)), close: () => socket.emit('close') })
  mocks.server.emit('upgrade', { url: `/tab/tab?token=${h.token}`, headers: {} }, socket, Buffer.alloc(0))
  try {
    socket.emit('message', JSON.stringify({ id: 1, method: 'Workbench.getDownloads' }))
    await vi.waitFor(() => expect(messages.find(m => m.id === 1)?.result.downloads).toHaveLength(1))
    expect(messages.find(m => m.id === 1).result.downloads[0]).toMatchObject({ begin: { suggestedFilename: 'invoice.pdf' }, progress: { state: 'completed', receivedBytes: 12 } })
  } finally { socket.emit('close') }
})

it('keeps a tab whose webview was recreated when the old guest is destroyed late', async () => {
  const h = await harness()
  const replacement = Object.assign(new EventEmitter(), { debugger: h.debug, id: 4, isDestroyed: () => false, getType: () => 'webview',
    hostWebContents: { id: 1 }, session: mocks.partition, getURL: () => 'http://example.test/new', getTitle: () => 'New' })
  mocks.guests.set(4, replacement)
  h.bridge.setTabs('one', [{ tabId: 'tab', webContentsId: 4, active: true, visible: true }])
  mocks.guests.delete(2)
  h.guest.emit('destroyed')
  const messages: any[] = []
  const socket = Object.assign(new EventEmitter(), { readyState: 1, OPEN: 1, destroy: vi.fn(),
    send: (value: string) => messages.push(JSON.parse(value)), close: () => socket.emit('close') })
  mocks.server.emit('upgrade', { url: `/tab/tab?token=${h.token}`, headers: {} }, socket, Buffer.alloc(0))
  try {
    socket.emit('message', JSON.stringify({ id: 1, method: 'Workbench.listTabs' }))
    await vi.waitFor(() => expect(messages.find(m => m.id === 1)).toBeDefined())
    expect(socket.destroy).not.toHaveBeenCalled()
    expect(messages.find(m => m.id === 1).result.tabs).toEqual([
      expect.objectContaining({ tab_id: 'tab', url: 'http://example.test/new' })
    ])
  } finally { socket.emit('close') }
})

it('registers child windows with the parent browser and keeps ownership across renderer updates', async () => {
  const h = await harness()
  const childGuest = Object.assign(new EventEmitter(), { id: 3, isDestroyed: () => false, getURL: () => 'https://example.test/login', getTitle: () => 'Login' })
  mocks.guests.set(3, childGuest)
  const child = Object.assign(new EventEmitter(), { webContents: childGuest, setIgnoreMouseEvents: vi.fn(), setFocusable: vi.fn(), blur: vi.fn(), show: vi.fn(), focus: vi.fn(), destroy: vi.fn(() => childGuest.emit('destroyed')) })
  h.guest.emit('did-create-window', child)
  try {
    const result = await h.send('Workbench.listTabs')
    const popup = result.result.tabs.find((tab: any) => tab.popup)
    expect(popup).toMatchObject({ title: 'Login', url: 'https://example.test/login' })
    h.bridge.setTabs('one', [{ tabId: 'tab', webContentsId: 2, active: true, visible: true, inputBlocked: true }])
    expect(child.setIgnoreMouseEvents).toHaveBeenLastCalledWith(true)
    expect(child.setFocusable).toHaveBeenLastCalledWith(false)
    expect((await h.send('Workbench.listTabs')).result.tabs).toHaveLength(2)
    await h.send('Workbench.closeTab', { tabId: popup.tab_id })
    expect(child.destroy).toHaveBeenCalledOnce()
  } finally { h.socket.close() }
})

it('keeps screenshot capture alive across a temporarily unpainted page after navigation', async () => {
  const h = await harness()
  const painted = { isEmpty: () => false, getSize: () => ({ width: 640, height: 480 }), toJPEG: () => Buffer.from('frame') }
  const capturePage = vi.fn().mockResolvedValue(painted)
  Object.assign(h.guest, { capturePage })
  const original = h.debug.sendCommand.getMockImplementation()!
  h.debug.sendCommand.mockImplementation(async (method, params, sid) => method === 'Page.getLayoutMetrics'
    ? { cssLayoutViewport: { clientWidth: 640, clientHeight: 480 } } : original(method, params, sid))
  try {
    expect((await h.send('Page.captureScreenshot')).result.data).toBe(Buffer.from('frame').toString('base64'))
    h.guest.emit('did-start-navigation')
    capturePage.mockResolvedValueOnce({ isEmpty: () => true }).mockResolvedValueOnce(painted)
    const duringNavigation = await h.send('Page.captureScreenshot')
    expect(duringNavigation.error).toBeUndefined()
    expect(duringNavigation.result.data).toBe(Buffer.from('frame').toString('base64'))
    expect(h.socket.readyState).toBe(h.socket.OPEN)
  } finally { h.socket.close() }
})

it('reports a persistently unpainted page after a bounded wait', async () => {
  vi.useFakeTimers()
  const h = await harness()
  const capturePage = vi.fn(async () => ({ isEmpty: () => true }))
  Object.assign(h.guest, { capturePage })
  try {
    h.socket.emit('message', JSON.stringify({ id: 400, method: 'Page.captureScreenshot' }))
    await vi.advanceTimersByTimeAsync(2100)
    expect(h.messages.find(m => m.id === 400)?.error.message).toBe('The page has not been painted yet')
    expect(capturePage.mock.calls.length).toBeLessThanOrEqual(41)
  } finally { h.socket.close(); vi.useRealTimers() }
})

it('cancels a paint wait when the browser is closed', async () => {
  vi.useFakeTimers()
  const h = await harness()
  const capturePage = vi.fn(async () => ({ isEmpty: () => true }))
  Object.assign(h.guest, { capturePage })
  try {
    h.socket.emit('message', JSON.stringify({ id: 401, method: 'Page.captureScreenshot' }))
    await vi.advanceTimersByTimeAsync(0)
    h.socket.close()
    await vi.advanceTimersByTimeAsync(100)
    const calls = capturePage.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(capturePage.mock.calls.length).toBe(calls)
    expect(calls).toBeLessThanOrEqual(2)
  } finally { vi.useRealTimers() }
})

it('blocks windows a page opens while the agent drives its tab, and tells the runtime', async () => {
  const h = await harness()
  try {
    expect(h.bridge.allowPopup(2, 'https://login.test/')).toBe(true)
    h.bridge.setTabs('one', [{ tabId: 'tab', webContentsId: 2, active: true, visible: true, inputBlocked: true }])
    expect(h.bridge.allowPopup(2, 'https://login.test/')).toBe(false)
    expect(h.messages).toContainEqual({ method: 'Workbench.popupBlocked', params: { url: 'https://login.test/' } })
    expect(h.bridge.allowPopup(99, 'https://unknown.test/')).toBe(true)
  } finally { h.socket.close() }
})
