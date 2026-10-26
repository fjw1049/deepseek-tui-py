import { randomBytes, randomUUID, timingSafeEqual } from 'crypto'
import { createServer, type IncomingMessage, type Server } from 'http'
import { isAbsolute, join } from 'path'
import type { Duplex } from 'stream'
import { session, webContents, type DownloadItem, type BrowserWindow, type WebContents } from 'electron'
import { WebSocketServer, type RawData, type WebSocket } from 'ws'
import { DEV_BROWSER_PARTITION, type BrowserBridgeCommand, type BrowserBridgeReply, type BrowserBridgeTab } from '../../shared/browser-bridge'
import { logWarn } from '../logger'

type Deps = {
  useDownloadPreferences?: boolean
  /** The window whose renderer hosts the tabs; guests of any other host are refused. */
  getHost: () => WebContents | null
  sendCommand: (requestId: string, command: BrowserBridgeCommand) => void
  announce: (port: number, token: string) => Promise<void>
}

type Message = { id: number; method: string; params?: Record<string, unknown> }
type Tab = BrowserBridgeTab & { browserId: string; popup?: BrowserWindow; openerId?: string }
type FrameInfo = { parentId?: string; frameIds: string[] }

const REQUEST_TIMEOUT_MS = 15_000
const ALLOWED_BROWSER_METHODS = new Set(['Browser.getVersion'])

function parseMessage(raw: string): Message {
  const message = JSON.parse(raw) as Message
  if (!message || !Number.isSafeInteger(message.id) || typeof message.method !== 'string' ||
    (message.params !== undefined && (!message.params || typeof message.params !== 'object' || Array.isArray(message.params)))) {
    throw new Error('Invalid CDP message')
  }
  return message
}

function frameIds(tree: { frame?: { id?: string }; childFrames?: unknown[] } | undefined): string[] {
  if (!tree?.frame?.id) return []
  return [tree.frame.id, ...((tree.childFrames ?? []) as typeof tree[]).flatMap(frameIds)]
}

/**
 * Loopback CDP bridge to the Workbench browser's tabs, so the runtime drives the page
 * the user sees. Only tab guests of this app's window are reachable, every connection
 * carries the per-launch token, and cross-target CDP is limited to each tab's own
 * frames: a guest's debugger can otherwise reach the app window itself.
 */
export function createBrowserBridge(deps: Deps) {
  const token = randomBytes(24).toString('base64url')
  const tabs = new Map<string, Tab>()
  const sockets = new Map<string, Set<WebSocket>>()
  const connections = new Map<WebSocket, string>()
  const pending = new Map<string, { resolve: (reply: BrowserBridgeReply) => void; timer: NodeJS.Timeout }>()
  let waiters: Array<() => void> = []
  /** Download folders the runtime chose for the tabs it drives; other tabs keep the app's. */
  const downloadDirs = new Map<number, string>()
  const downloads = new Map<string, { browserId: string; begin: Record<string, unknown>; progress?: Record<string, unknown> }>()
  const watched = new Set<number>()
  let server: Server | null = null
  let port = 0

  const notify = (): void => { const current = waiters; waiters = []; current.forEach(wake => wake()) }
  const waitFor = (ready: () => boolean, label: string): Promise<void> => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Workbench browser did not ${label} in time`)), REQUEST_TIMEOUT_MS)
    const check = (): void => { if (ready()) { clearTimeout(timer); resolve() } else waiters.push(check) }
    check()
  })
  const tabsOf = (browserId: string): Tab[] => [...tabs.values()].filter(tab => tab.browserId === browserId)
  const guestOf = (tab: Tab): WebContents | null => {
    const guest = webContents.fromId(tab.webContentsId)
    return guest && !guest.isDestroyed() ? guest : null
  }
  const listTabs = (browserId: string) => {
    const focusedPopup = tabsOf(browserId).find(tab => tab.popup && tab.active)
    return tabsOf(browserId).flatMap(tab => {
      const guest = guestOf(tab)
      // `active` is what the user looks at (a focused popup wins); `panel` is the panel's tab.
      return guest ? [{ tab_id: tab.tabId, url: guest.getURL(), title: guest.getTitle(), active: focusedPopup ? tab === focusedPopup : tab.active,
        panel: !tab.popup && tab.active, popup: !!tab.popup }] : []
    })
  }

  function isTabGuest(id: number): boolean {
    const guest = webContents.fromId(id)
    const host = deps.getHost()
    return !!guest && !guest.isDestroyed() && !!host && guest.getType() === 'webview' &&
      guest.hostWebContents?.id === host.id && guest.session === session.fromPartition(DEV_BROWSER_PARTITION)
  }

  function request(command: BrowserBridgeCommand): Promise<BrowserBridgeReply> {
    const requestId = randomUUID()
    return new Promise(resolve => {
      const timer = setTimeout(() => { pending.delete(requestId); resolve({ ok: false, error: 'Workbench did not respond' }) }, REQUEST_TIMEOUT_MS)
      pending.set(requestId, { resolve, timer })
      deps.sendCommand(requestId, command)
    })
  }

  function sendToBrowser(browserId: string, method: string, params: Record<string, unknown>): void {
    for (const [socket, owner] of connections) {
      if (owner === browserId && socket.readyState === socket.OPEN) socket.send(JSON.stringify({ method, params }))
    }
  }

  /** Download state belongs to the browser, not its currently connected tab. */
  function onDownload(_event: unknown, item: DownloadItem, source: WebContents): void {
    const directory = downloadDirs.get(source.id)
    const tab = [...tabs.values()].find(item => item.webContentsId === source.id)
    if (!directory || !tab) return
    const guid = randomUUID()
    if (!deps.useDownloadPreferences) item.setSavePath(join(directory, guid))
    const record: { browserId: string; begin: Record<string, unknown>; progress?: Record<string, unknown> } = {
      browserId: tab.browserId, begin: { guid, url: item.getURL(), suggestedFilename: item.getFilename(), frameId: '' }
    }
    for (const [key, value] of downloads) {
      if (downloads.size < 200) break
      if (value.progress && value.progress.state !== 'inProgress') downloads.delete(key)
    }
    downloads.set(guid, record)
    sendToBrowser(tab.browserId, 'Browser.downloadWillBegin', record.begin)
    const progress = (state: string): void => {
      record.progress = { guid, state, receivedBytes: item.getReceivedBytes(), totalBytes: item.getTotalBytes(),
        ...(deps.useDownloadPreferences && state === 'completed' ? { filePath: item.getSavePath() } : {}) }
      sendToBrowser(tab.browserId, 'Browser.downloadProgress', record.progress)
    }
    item.on('updated', () => progress('inProgress'))
    item.once('done', (_done, state) => progress(state === 'completed' ? 'completed' : 'canceled'))
  }

  function watchTab(tab: Tab): void {
    const guest = guestOf(tab)
    if (!guest || watched.has(guest.id)) return
    watched.add(guest.id)
    guest.on('did-create-window', child => {
      const parent = tabs.get(tab.tabId)
      if (!parent) { child.destroy(); return }
      const popup: Tab = { browserId: parent.browserId, tabId: randomUUID(), webContentsId: child.webContents.id,
        active: false, visible: true, popup: child, openerId: parent.tabId, inputBlocked: parent.inputBlocked }
      tabs.set(popup.tabId, popup)
      child.on('focus', () => {
        for (const tab of tabsOf(parent.browserId)) if (tab.popup) tab.active = tab === popup
      })
      child.on('blur', () => { popup.active = false })
      child.setIgnoreMouseEvents(!!popup.inputBlocked)
      child.setFocusable(!popup.inputBlocked)
      if (popup.inputBlocked) child.blur()
      watchTab(popup)
      notify()
    })
    guest.once('destroyed', () => {
      watched.delete(guest.id)
      downloadDirs.delete(guest.id)
      // A recreated webview may already own this tab id; leave its entry and sockets alone.
      if (tabs.get(tab.tabId)?.webContentsId !== guest.id) return
      tabs.delete(tab.tabId)
      closeSockets(tab.tabId)
      for (const child of tabsOf(tab.browserId)) if (child.openerId === tab.tabId) child.popup?.destroy()
      notify()
    })
  }

  function closeSockets(tabId: string): void {
    for (const socket of sockets.get(tabId) ?? []) socket.close(1001, 'Tab closed')
    sockets.delete(tabId)
  }

  async function workbenchMethod(browserId: string, method: string, params: Record<string, unknown>): Promise<unknown> {
    const owned = (id: unknown): string => {
      if (typeof id !== 'string' || tabs.get(id)?.browserId !== browserId) throw new Error('Tab does not belong to this browser')
      return id
    }
    if (method === 'Workbench.getDownloads') return { downloads: [...downloads.values()].filter(item => item.browserId === browserId).map(({ begin, progress }) => ({ begin, progress })) }
    if (method === 'Workbench.listTabs') return { tabs: listTabs(browserId) }
    if (method === 'Workbench.createTab') {
      const url = typeof params.url === 'string' ? params.url : 'about:blank'
      if (url !== 'about:blank' && !/^https?:\/\//i.test(url)) throw new Error('Only http(s) pages can be opened')
      const reply = await request({ kind: 'create', browserId, url })
      if (!reply.ok || !reply.tabId) throw new Error(reply.error ?? 'Workbench could not open a tab')
      const tabId = reply.tabId
      await waitFor(() => tabs.get(tabId)?.browserId === browserId, 'open the tab')
      return { tabId }
    }
    if (method === 'Workbench.activateTab' || method === 'Workbench.closeTab') {
      const tabId = owned(params.tabId)
      const popup = tabs.get(tabId)?.popup
      if (popup) {
        if (method === 'Workbench.closeTab') popup.destroy()
        else { popup.show(); if (!tabs.get(tabId)?.inputBlocked) popup.focus() }
        return {}
      }
      const reply = await request({ kind: method === 'Workbench.activateTab' ? 'activate' : 'close', browserId, tabId })
      if (!reply.ok) throw new Error(reply.error ?? 'Workbench could not change the tab')
      if (method === 'Workbench.closeTab') await waitFor(() => !tabs.has(tabId), 'close the tab')
      return {}
    }
    throw new Error(`Unsupported method ${method}`)
  }

  function serveControl(socket: WebSocket): void {
    socket.on('message', (raw: RawData) => void (async () => {
      let message: Message
      try { message = parseMessage(String(raw)) } catch { socket.close(1003, 'Invalid message'); return }
      try {
        if (message.method === 'Workbench.clearCookies') {
          // The runtime cleared its saved logins; Workbench's tabs share this partition. Sites
          // also keep sign-in tokens in storage, so signing out clears that too.
          await session.fromPartition(DEV_BROWSER_PARTITION).clearStorageData({
            storages: ['cookies', 'localstorage', 'indexdb', 'serviceworkers', 'cachestorage', 'websql']
          })
          socket.send(JSON.stringify({ id: message.id, result: {} }))
          return
        }
        const browserId = String(message.params?.browserId ?? '')
        if (!browserId) throw new Error('browserId is required')
        if (message.method !== 'Workbench.openSession') {
          const result = await workbenchMethod(browserId, message.method, message.params ?? {})
          socket.send(JSON.stringify({ id: message.id, result }))
          return
        }
        if (!tabsOf(browserId).length) {
          const reply = await request({ kind: 'open', browserId })
          if (!reply.ok) throw new Error(reply.error ?? 'Workbench browser is unavailable')
          await waitFor(() => tabsOf(browserId).length > 0, 'show the browser')
        }
        socket.send(JSON.stringify({ id: message.id, result: { tabs: listTabs(browserId) } }))
      } catch (error) {
        socket.send(JSON.stringify({ id: message.id, error: { message: error instanceof Error ? error.message : String(error) } }))
      }
    })())
  }

  function serveTab(socket: WebSocket, tab: Tab, guest: WebContents): void {
    const debug = guest.debugger
    try {
      if (!debug.isAttached()) debug.attach('1.3')
    } catch (error) {
      socket.close(1011, String(error))
      return
    }
    // Flattened Electron sessions stay behind the bridge. Every tunneled command
    // is dispatched here again, with the same descendant checks as a root command.
    const ownSessions = new Map<string, { parent?: string; targetId: string }>()
    const set = sockets.get(tab.tabId) ?? new Set<WebSocket>()
    set.add(socket)
    sockets.set(tab.tabId, set)
    connections.set(socket, tab.browserId)
    // Wait for the renderer to protect this session before accepting CDP work.
    const retained = request({ kind: 'retain', browserId: tab.browserId, retained: true })

    const frameInfo = async (targetId: string): Promise<FrameInfo> => {
      // Electron leaves parentFrameId empty; the child's own tree names its parent.
      const { sessionId } = await debug.sendCommand('Target.attachToTarget', { targetId, flatten: true }) as { sessionId: string }
      try {
        const tree = await debug.sendCommand('Page.getFrameTree', {}, sessionId) as { frameTree: { frame: { parentId?: string } } }
        const info = { parentId: tree.frameTree.frame.parentId, frameIds: frameIds(tree.frameTree as never) }
        return info
      } finally {
        await debug.sendCommand('Target.detachFromTarget', { sessionId }).catch(() => {})
      }
    }
    /** Cross-origin frames of this tab, with their parent frame IDs. */
    const ownedFrames = async (sessionId?: string): Promise<{ owned: Map<string, string>; targets: Array<Record<string, unknown>> }> => {
      const tree = await debug.sendCommand('Page.getFrameTree', {}, sessionId) as { frameTree: never }
      const known = new Set(frameIds(tree.frameTree))
      const targets = ((await debug.sendCommand('Target.getTargets')) as { targetInfos: Array<Record<string, unknown>> }).targetInfos
        .filter(target => target.type === 'iframe')
      const owned = new Map<string, string>()
      for (let changed = true; changed;) {
        changed = false
        for (const target of targets) {
          const id = String(target.targetId)
          if (owned.has(id)) continue
          const info = await frameInfo(id).catch(() => null)
          if (info?.parentId && known.has(info.parentId)) {
            owned.set(id, info.parentId)
            info.frameIds.forEach(frame => known.add(frame))
            changed = true
          }
        }
      }
      return { owned, targets }
    }

    /** Forget a session and, at Electron too, the frame sessions opened through it. */
    function forget(sessionId: string): void {
      ownSessions.delete(sessionId)
      for (const [child, owned] of ownSessions) {
        if (owned.parent !== sessionId) continue
        forget(child)
        void debug.sendCommand('Target.detachFromTarget', { sessionId: child }).catch(() => {})
      }
    }

    function emit(message: Record<string, unknown>, sessionId?: string): void {
      if (sessionId) {
        const owned = ownSessions.get(sessionId)
        if (!owned) return
        emit({ method: 'Target.receivedMessageFromTarget', params: {
          sessionId, targetId: owned.targetId, message: JSON.stringify(message)
        } }, owned.parent)
      } else if (socket.readyState === socket.OPEN) socket.send(JSON.stringify(message))
    }

    async function target(method: string, params: Record<string, unknown>, parent?: string): Promise<unknown> {
      if (method === 'Target.getTargets') {
        const { owned, targets } = await ownedFrames(parent)
        return { targetInfos: targets.filter(item => owned.has(String(item.targetId)))
          .map(item => ({ ...item, parentFrameId: owned.get(String(item.targetId)) })) }
      }
      if (method === 'Target.getTargetInfo' && !params.targetId) return debug.sendCommand(method, params, parent)
      if (method === 'Target.attachToTarget') {
        if (params.flatten !== false) throw new Error('Only non-flattened frame sessions are supported')
        if (!(await ownedFrames(parent)).owned.has(String(params.targetId))) throw new Error('Target is outside this tab')
        const attached = await debug.sendCommand(method, { ...params, flatten: true }) as { sessionId: string }
        ownSessions.set(attached.sessionId, { parent, targetId: String(params.targetId) })
        return attached
      }
      if (method === 'Target.sendMessageToTarget' || method === 'Target.detachFromTarget') {
        const sessionId = String(params.sessionId)
        if (!ownSessions.has(sessionId) || ownSessions.get(sessionId)!.parent !== parent) throw new Error('Session is outside this tab')
        if (method === 'Target.detachFromTarget') {
          forget(sessionId)
          await debug.sendCommand(method, { sessionId })
          return {}
        }
        const message = parseMessage(String(params.message))
        try {
          emit({ id: message.id, result: await dispatch(message, sessionId) }, sessionId)
        } catch (error) {
          emit({ id: message.id, error: { message: error instanceof Error ? error.message : String(error) } }, sessionId)
        }
        return {}
      }
      throw new Error(`${method} is not available for Workbench tabs`)
    }

    /** Captures at CSS-pixel size, also while the panel is hidden. */
    async function screenshot(params: Record<string, unknown>): Promise<unknown> {
      if (params.clip || params.captureBeyondViewport) return debug.sendCommand('Page.captureScreenshot', params)
      let image = await guest.capturePage(undefined, { stayHidden: true })
      // A click/navigation can briefly replace the compositor surface. Wait for
      // a painted frame instead of terminating an otherwise healthy recording.
      const paintDeadline = Date.now() + 2000
      while (image.isEmpty()) {
        if (guest.isDestroyed() || socket.readyState !== socket.OPEN) throw new Error('Browser capture was closed')
        if (Date.now() >= paintDeadline) throw new Error('The page has not been painted yet')
        await new Promise(resolve => setTimeout(resolve, 50))
        image = await guest.capturePage(undefined, { stayHidden: true })
      }
      const metrics = await debug.sendCommand('Page.getLayoutMetrics') as { cssLayoutViewport: { clientWidth: number; clientHeight: number } }
      const { clientWidth: width, clientHeight: height } = metrics.cssLayoutViewport
      if (image.getSize().width !== width) image = image.resize({ width, height, quality: 'good' })
      const data = params.format === 'png' ? image.toPNG() : image.toJPEG(Number(params.quality ?? 80))
      return { data: data.toString('base64') }
    }

    function downloadBehavior(params: Record<string, unknown>): Record<string, never> {
      const path = typeof params.downloadPath === 'string' ? params.downloadPath : ''
      if (params.behavior === 'default') downloadDirs.delete(guest.id)
      else if ((params.behavior === 'allow' || params.behavior === 'allowAndName') && isAbsolute(path)) downloadDirs.set(guest.id, path)
      else throw new Error('Unsupported download behavior')
      return {}
    }

    const onMessage = (_event: unknown, method: string, params: Record<string, unknown>, sessionId?: string): void => {
      if (method === 'Target.detachedFromTarget') {
        const detached = String(params.sessionId)
        const owned = ownSessions.get(detached)
        if (owned) {
          forget(detached)
          // Tell the client its frame session ended, as Chrome does, instead of letting
          // its pending commands time out.
          emit({ method, params: { sessionId: detached, targetId: owned.targetId } }, owned.parent)
        }
      }
      // Target lifecycle/events are managed by the bridge, never forwarded raw.
      if (method.startsWith('Target.')) return
      emit({ method, params }, sessionId)
    }
    const onDetach = (): void => socket.close(1011, 'Debugger detached')
    debug.on('message', onMessage)
    debug.on('detach', onDetach)
    socket.on('close', () => {
      debug.removeListener('message', onMessage)
      debug.removeListener('detach', onDetach)
      for (const sessionId of ownSessions.keys()) void debug.sendCommand('Target.detachFromTarget', { sessionId }).catch(() => {})
      ownSessions.clear()
      set.delete(socket)
      connections.delete(socket)
      if (![...connections.values()].includes(tab.browserId)) {
        void request({ kind: 'retain', browserId: tab.browserId, retained: false })
      }
      if (!set.size) {
        sockets.delete(tab.tabId)
        if (debug.isAttached()) try { debug.detach() } catch { /* the guest is gone */ }
      }
    })
    async function dispatch(message: Message, sessionId?: string): Promise<unknown> {
      const { method } = message
      const params = message.params ?? {}
      if (method.startsWith('Target.')) return target(method, params, sessionId)
      if (method.startsWith('Workbench.')) {
        if (sessionId) throw new Error('Workbench commands require a tab connection')
        return workbenchMethod(tab.browserId, method, params)
      }
      if (method === 'Browser.setDownloadBehavior' && !sessionId) return downloadBehavior(params)
      if (method.startsWith('Browser.') && !ALLOWED_BROWSER_METHODS.has(method)) throw new Error(`${method} is not available for Workbench tabs`)
      if (method === 'Page.captureScreenshot' && !sessionId) return screenshot(params)
      return debug.sendCommand(method, params, sessionId)
    }

    socket.on('message', (raw: RawData) => void (async () => {
      let message: Message
      try { message = parseMessage(String(raw)) } catch { socket.close(1003, 'Invalid message'); return }
      try {
        if (!(await retained).ok) throw new Error('Workbench browser was closed before it could be retained')
        const result = await dispatch(message)
        if (socket.readyState === socket.OPEN) socket.send(JSON.stringify({ id: message.id, result }))
      } catch (error) {
        if (socket.readyState === socket.OPEN) {
          socket.send(JSON.stringify({ id: message.id, error: { message: error instanceof Error ? error.message : String(error) } }))
        }
      }
    })())
  }

  function upgrade(request: IncomingMessage, socket: Duplex, head: Buffer, wss: WebSocketServer): void {
    const url = new URL(request.url ?? '/', 'http://127.0.0.1')
    const given = Buffer.from(url.searchParams.get('token') ?? '')
    const expected = Buffer.from(token)
    if (given.length !== expected.length || !timingSafeEqual(given, expected) || request.headers.origin) {
      socket.destroy()
      return
    }
    const tabMatch = /^\/tab\/([^/]+)$/.exec(url.pathname)
    let tabId: string | undefined
    try { tabId = tabMatch ? decodeURIComponent(tabMatch[1]!) : undefined } catch { socket.destroy(); return }
    const tab = tabId ? tabs.get(tabId) : undefined
    const guest = tab ? guestOf(tab) : null
    if (url.pathname !== '/control' && !(tab && guest)) {
      socket.destroy()
      return
    }
    wss.handleUpgrade(request, socket, head, client => {
      if (tab && guest) serveTab(client, tab, guest)
      else serveControl(client)
    })
  }

  return {
    async start(): Promise<void> {
      if (server) return
      const wss = new WebSocketServer({ noServer: true, maxPayload: 16 * 1024 * 1024 })
      server = createServer((_request, response) => { response.statusCode = 404; response.end() })
      server.on('upgrade', (request, socket, head) => upgrade(request, socket, head, wss))
      session.fromPartition(DEV_BROWSER_PARTITION).on('will-download', onDownload)
      await new Promise<void>(resolve => server!.listen(0, '127.0.0.1', resolve))
      port = (server.address() as { port: number }).port
    },
    /** Tells the runtime where the bridge is; repeated whenever the runtime (re)starts. */
    async announce(): Promise<void> {
      if (!port) return
      try { await deps.announce(port, token) } catch (error) {
        logWarn('browser-bridge', 'Runtime did not accept the browser bridge', String(error))
      }
    },
    setTabs(browserId: string, next: BrowserBridgeTab[]): void {
      const accepted = next.filter(tab => isTabGuest(tab.webContentsId))
      for (const tab of tabsOf(browserId)) {
        if (!tab.popup && !accepted.some(item => item.tabId === tab.tabId && item.webContentsId === tab.webContentsId)) {
          tabs.delete(tab.tabId)
          closeSockets(tab.tabId)
        }
      }
      for (const tab of accepted) {
        const known = tabs.get(tab.tabId)
        if (known && known.browserId !== browserId) continue
        const entry = { ...tab, browserId }
        tabs.set(tab.tabId, entry)
        watchTab(entry)
      }
      const anyBlocked = accepted.some(tab => tab.inputBlocked)
      for (const tab of tabsOf(browserId)) if (tab.popup) {
        // A window follows the tab that opened it; one opened by another window, the browser.
        const opener = accepted.find(item => item.tabId === tab.openerId)
        const blocked = opener ? !!opener.inputBlocked : anyBlocked
        tab.inputBlocked = blocked
        tab.popup.setIgnoreMouseEvents(blocked)
        tab.popup.setFocusable(!blocked)
        if (blocked) tab.popup.blur()
      }
      notify()
    },
    /** A tab whose input is held for the agent may not open windows; the runtime hears why. */
    allowPopup(openerId: number, url: string): boolean {
      const opener = [...tabs.values()].find(tab => tab.webContentsId === openerId)
      if (!opener?.inputBlocked) return true
      sendToBrowser(opener.browserId, 'Workbench.popupBlocked', { url })
      return false
    },
    reply(requestId: string, reply: BrowserBridgeReply): void {
      const waiting = pending.get(requestId)
      if (!waiting) return
      pending.delete(requestId)
      clearTimeout(waiting.timer)
      waiting.resolve(reply)
    }
  }
}

export type BrowserBridge = ReturnType<typeof createBrowserBridge>
