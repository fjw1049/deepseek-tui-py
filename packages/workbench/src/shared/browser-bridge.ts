/** Partition of the Workbench browser's <webview> tabs. */
export const DEV_BROWSER_PARTITION = 'persist:deepseek-dev-browser'

/** A Workbench browser tab the runtime may drive through the loopback CDP bridge. */
export type BrowserBridgeTab = { tabId: string; webContentsId: number; active: boolean; visible: boolean }

/** Tab changes the runtime asks the Workbench browser to make. */
export type BrowserBridgeCommand =
  | { kind: 'retain'; browserId: string; retained: boolean }
  | { kind: 'open'; browserId: string }
  | { kind: 'create'; browserId: string; url: string }
  | { kind: 'activate'; browserId: string; tabId: string }
  | { kind: 'close'; browserId: string; tabId: string }

export type BrowserBridgeReply = { ok: boolean; tabId?: string; error?: string }
