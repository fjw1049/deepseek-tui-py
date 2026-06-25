import { homedir } from 'node:os'
import { readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { isWecomWebhookConfigured, parseWecomWebhookKey } from '../shared/wecom-channel'
import { readTomlString, upsertTomlSections } from '../shared/toml-section'
import { resolveDeepseekConfigPath } from './deepseek-paths'

export type WecomConfigV1 = {
  webhookKey: string
}

function resolveHomeDeepseekConfigPath(): string {
  return join(homedir(), '.deepseek', 'config.toml')
}

/** Primary config path plus ``~/.deepseek/config.toml`` when they differ (repo-local dev). */
export function resolveWecomConfigPaths(): string[] {
  const primary = resolveDeepseekConfigPath()
  const home = resolveHomeDeepseekConfigPath()
  if (resolve(primary) === resolve(home)) return [primary]
  return [primary, home]
}

function emptyWecomConfig(): WecomConfigV1 {
  return { webhookKey: '' }
}

export function parseWecomFromConfigToml(content: string): WecomConfigV1 {
  const key = readTomlString(content, 'webhook_key', { section: 'automation.wecom' }) ?? ''
  return { webhookKey: parseWecomWebhookKey(key) ?? key.trim() }
}

function mergeWecomConfig(base: WecomConfigV1, patch: WecomConfigV1): WecomConfigV1 {
  return { webhookKey: base.webhookKey || patch.webhookKey }
}

async function readConfigContent(path: string): Promise<string | null> {
  try {
    return await readFile(path, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}

async function writeConfigAt(path: string, config: WecomConfigV1): Promise<void> {
  let content = ''
  const existing = await readConfigContent(path)
  if (existing != null) {
    content = existing
  } else {
    content = '# DeepSeek config\n\n[features]\nautomations = true\n\n'
  }

  const webhookKey = parseWecomWebhookKey(config.webhookKey) ?? config.webhookKey.trim()
  const next = upsertTomlSections(content, {
    'automation.wecom': webhookKey ? { webhook_key: webhookKey } : { webhook_key: '' }
  })

  await writeFile(path, next, 'utf8')
}

export async function readWecomConfigFile(): Promise<{
  path: string
  exists: boolean
  configured: boolean
  config: WecomConfigV1
}> {
  const paths = resolveWecomConfigPaths()
  let merged = emptyWecomConfig()
  let anyExists = false
  for (const path of paths) {
    const content = await readConfigContent(path)
    if (content == null) continue
    anyExists = true
    merged = mergeWecomConfig(merged, parseWecomFromConfigToml(content))
  }
  const webhookKey = parseWecomWebhookKey(merged.webhookKey) ?? merged.webhookKey.trim()
  return {
    path: paths[0],
    exists: anyExists,
    configured: isWecomWebhookConfigured(webhookKey),
    config: { webhookKey }
  }
}

export async function writeWecomConfigFile(config: WecomConfigV1): Promise<{ path: string }> {
  const key = parseWecomWebhookKey(config.webhookKey)
  if (!key) throw new Error('invalid_wecom_webhook_key')
  const paths = resolveWecomConfigPaths()
  for (const path of paths) {
    await writeConfigAt(path, { webhookKey: key })
  }
  return { path: paths[0] }
}
