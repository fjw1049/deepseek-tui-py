import { readFile } from 'node:fs/promises'
import { DEFAULT_EMAIL_PASSWORD_ENV } from '../shared/email-channel'
import { readTomlString } from '../shared/toml-section'
import { resolveDeepseekConfigPath } from './deepseek-paths'

export async function readEmailPasswordEnvKey(): Promise<string> {
  try {
    const content = await readFile(resolveDeepseekConfigPath(), 'utf8')
    return (
      readTomlString(content, 'password_env', { section: 'automation.email' }) ??
      DEFAULT_EMAIL_PASSWORD_ENV
    )
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return DEFAULT_EMAIL_PASSWORD_ENV
    }
    throw error
  }
}
