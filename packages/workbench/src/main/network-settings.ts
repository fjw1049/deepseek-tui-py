import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { randomUUID } from 'node:crypto'
import { join } from 'node:path'
import { normalizeNetworkSettings, type NetworkSettings } from '../shared/network-settings'
import { resolveUserDeepseekDir } from './deepseek-paths'

export async function writeNetworkSettings(settings?: NetworkSettings): Promise<void> {
  const home = resolveUserDeepseekDir()
  await mkdir(home, { recursive: true })
  const temporary = join(home, `network-${randomUUID()}.tmp`)
  try {
    await writeFile(temporary, JSON.stringify(normalizeNetworkSettings(settings)), 'utf8')
    await rename(temporary, join(home, 'network.json'))
  } finally {
    await rm(temporary, { force: true })
  }
}

/** The routing the runtime reads for model requests (client/network.py). */
export async function readNetworkSettings(): Promise<NetworkSettings> {
  try {
    const raw = await readFile(join(resolveUserDeepseekDir(), 'network.json'), 'utf8')
    return normalizeNetworkSettings(JSON.parse(raw) as NetworkSettings)
  } catch {
    return normalizeNetworkSettings()
  }
}
