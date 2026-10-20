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
  return { debug, commands, messages, socket, send }
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
