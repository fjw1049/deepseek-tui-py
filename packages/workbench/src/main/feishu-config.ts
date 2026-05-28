import { homedir } from 'node:os'
import { readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { readTomlString, upsertTomlSections } from '../shared/toml-section'
import { resolveDeepseekConfigPath } from './deepseek-paths'

export type FeishuConfigV1 = {
  appId: string
  appSecret: string
  domain: string
  chatId: string
}

function resolveHomeDeepseekConfigPath(): string {
  return join(homedir(), '.deepseek', 'config.toml')
}

/** Primary config path plus ``~/.deepseek/config.toml`` when they differ (repo-local dev). */
export function resolveFeishuConfigPaths(): string[] {
  const primary = resolveDeepseekConfigPath()
  const home = resolveHomeDeepseekConfigPath()
  if (resolve(primary) === resolve(home)) return [primary]
  return [primary, home]
}

function emptyFeishuConfig(): FeishuConfigV1 {
  return { appId: '', appSecret: '', domain: 'feishu', chatId: '' }
}

export function parseFeishuFromConfigToml(content: string): FeishuConfigV1 {
  const chatFromAutomation = readTomlString(content, 'feishu_chat_id', { section: 'automation' })
  const chatFromFeishu = readTomlString(content, 'chat_id', { section: 'automation.feishu' })
  return {
    appId: readTomlString(content, 'app_id', { section: 'automation.feishu' }) ?? '',
    appSecret: readTomlString(content, 'app_secret', { section: 'automation.feishu' }) ?? '',
    domain: readTomlString(content, 'domain', { section: 'automation.feishu' }) ?? 'feishu',
    chatId: chatFromAutomation ?? chatFromFeishu ?? ''
  }
}

function mergeFeishuConfig(base: FeishuConfigV1, patch: FeishuConfigV1): FeishuConfigV1 {
  return {
    appId: base.appId || patch.appId,
    appSecret: base.appSecret || patch.appSecret,
    domain: base.domain !== 'feishu' ? base.domain : patch.domain || 'feishu',
    chatId: base.chatId || patch.chatId
  }
}

async function readConfigContent(path: string): Promise<string | null> {
  try {
    return await readFile(path, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}

async function writeConfigAt(path: string, config: FeishuConfigV1): Promise<void> {
  let content = ''
  const existing = await readConfigContent(path)
  if (existing != null) {
    content = existing
  } else {
    content = '# DeepSeek config\n\n[features]\nautomations = true\n\n'
  }

  const domain = config.domain.trim() || 'feishu'
  const chatId = config.chatId.trim()
  const next = upsertTomlSections(content, {
    automation: chatId ? { feishu_chat_id: chatId } : {},
    'automation.feishu': {
      app_id: config.appId.trim(),
      app_secret: config.appSecret.trim(),
      domain,
      ...(chatId ? { chat_id: chatId } : {})
    }
  })

  await writeFile(path, next, 'utf8')
}

export async function readFeishuConfigFile(): Promise<{
  path: string
  exists: boolean
  config: FeishuConfigV1
}> {
  const paths = resolveFeishuConfigPaths()
  let merged = emptyFeishuConfig()
  let anyExists = false
  for (const path of paths) {
    const content = await readConfigContent(path)
    if (content == null) continue
    anyExists = true
    merged = mergeFeishuConfig(merged, parseFeishuFromConfigToml(content))
  }
  return { path: paths[0], exists: anyExists, config: merged }
}

export async function writeFeishuConfigFile(config: FeishuConfigV1): Promise<{ path: string }> {
  const paths = resolveFeishuConfigPaths()
  for (const path of paths) {
    await writeConfigAt(path, config)
  }
  return { path: paths[0] }
}
