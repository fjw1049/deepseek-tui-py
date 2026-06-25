import { registerApp } from '@larksuiteoapi/node-sdk'
import type { WebContents } from 'electron'

export type FeishuRegisterTarget = 'feishu' | 'lark'

export type FeishuRegisterSuccess = {
  appId: string
  appSecret: string
  domain: FeishuRegisterTarget
  openId?: string
  tenantBrand?: 'feishu' | 'lark'
}

let activeAbort: AbortController | null = null

export function cancelFeishuRegisterApp(): void {
  activeAbort?.abort()
  activeAbort = null
}

function sendRegisterEvent(
  webContents: WebContents,
  payload:
    | { type: 'qr'; url: string; expireIn: number }
    | { type: 'status'; status: string; interval?: number }
): void {
  if (webContents.isDestroyed()) return
  webContents.send('feishu:register-event', payload)
}

function registerErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    const withCode = error as Error & { code?: string; description?: string }
    if (withCode.description?.trim()) return withCode.description.trim()
    if (withCode.code === 'access_denied') return 'Authorization was denied in Feishu / Lark.'
    if (withCode.code === 'expired_token') return 'The QR code expired. Generate a new one.'
    if (withCode.code === 'abort') return 'Feishu registration was cancelled.'
    return error.message
  }
  return String(error)
}

export async function runFeishuRegisterApp(options: {
  target: FeishuRegisterTarget
  webContents: WebContents
}): Promise<{ ok: true; result: FeishuRegisterSuccess } | { ok: false; message: string }> {
  cancelFeishuRegisterApp()
  const abort = new AbortController()
  activeAbort = abort

  try {
    const result = await registerApp({
      signal: abort.signal,
      source: 'deepseek-workbench',
      createOnly: true,
      appPreset: {
        name: 'DeepSeek Agent',
        desc: 'DeepSeek desktop agent notifications and chat'
      },
      onQRCodeReady(info) {
        sendRegisterEvent(options.webContents, {
          type: 'qr',
          url: info.url,
          expireIn: info.expireIn
        })
      },
      onStatusChange(info) {
        sendRegisterEvent(options.webContents, {
          type: 'status',
          status: info.status,
          interval: info.interval
        })
      }
    })

    const tenantBrand = result.user_info?.tenant_brand
    const domain: FeishuRegisterTarget =
      tenantBrand === 'lark'
        ? 'lark'
        : tenantBrand === 'feishu'
          ? 'feishu'
          : options.target

    return {
      ok: true,
      result: {
        appId: result.client_id,
        appSecret: result.client_secret,
        domain,
        openId: result.user_info?.open_id,
        tenantBrand
      }
    }
  } catch (error) {
    if (abort.signal.aborted) {
      return { ok: false, message: 'Feishu registration was cancelled.' }
    }
    return { ok: false, message: registerErrorMessage(error) }
  } finally {
    if (activeAbort === abort) activeAbort = null
  }
}
