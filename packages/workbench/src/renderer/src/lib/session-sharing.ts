import { formatAutomationApiError } from './automation-runtime-client'

export type ShareSettings = { service_url: string; has_upload_key: boolean; ready?: boolean }
export type SharePreview = {
  title: string
  created_at: string
  turn_count: number
  source_workspace: string
  model: string
  project_commit: string | null
  files: string[]
  messages: { role: string; text: string }[]
}

export class SharingError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

export async function sharingRequest<T>(path: string, method = 'POST', payload?: unknown): Promise<T> {
  const result = await window.dsGui.runtimeRequest(
    `/v1/sharing/${path}`, method,
    payload === undefined ? undefined : JSON.stringify(payload)
  )
  if (!result.ok) throw new SharingError(formatAutomationApiError(result.body, `Sharing failed (${result.status})`), result.status)
  return JSON.parse(result.body) as T
}
