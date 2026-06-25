import { safeStorage } from 'electron'
import { mkdir, readFile, unlink, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { DEFAULT_EMAIL_PASSWORD_ENV } from '../shared/email-channel'
import { resolveUserDeepseekDir } from './deepseek-paths'

const EMAIL_SMTP_SECRET_FILE = 'email-smtp.password'

function emailSecretPath(): string {
  return join(resolveUserDeepseekDir(), 'secrets', EMAIL_SMTP_SECRET_FILE)
}

function passwordEnvCandidates(passwordEnv?: string): string[] {
  const keys = new Set<string>()
  const trimmed = passwordEnv?.trim()
  if (trimmed) keys.add(trimmed)
  keys.add(DEFAULT_EMAIL_PASSWORD_ENV)
  return [...keys]
}

export function isEmailSecretStorageAvailable(): boolean {
  return safeStorage.isEncryptionAvailable()
}

export function hasEmailPasswordInProcessEnv(passwordEnv?: string): boolean {
  return passwordEnvCandidates(passwordEnv).some((key) => Boolean(process.env[key]?.trim()))
}

export async function hasEmailSmtpPasswordStored(): Promise<boolean> {
  try {
    await readFile(emailSecretPath())
    return true
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false
    throw error
  }
}

export async function resolveEmailPasswordStatus(passwordEnv?: string): Promise<{
  hasStoredPassword: boolean
  hasEnvPassword: boolean
  passwordConfigured: boolean
}> {
  const hasStoredPassword = await hasEmailSmtpPasswordStored()
  const hasEnvPassword = hasEmailPasswordInProcessEnv(passwordEnv)
  return {
    hasStoredPassword,
    hasEnvPassword,
    passwordConfigured: hasStoredPassword || hasEnvPassword
  }
}

export async function setEmailSmtpPassword(password: string): Promise<void> {
  const trimmed = password.trim()
  if (!trimmed) {
    throw new Error('Email authorization code is required.')
  }
  if (!isEmailSecretStorageAvailable()) {
    throw new Error(
      'Secure storage is unavailable on this system. Set DEEPSEEK_EMAIL_PASSWORD in your environment instead.'
    )
  }
  const encrypted = safeStorage.encryptString(trimmed)
  await mkdir(join(resolveUserDeepseekDir(), 'secrets'), { recursive: true })
  await writeFile(emailSecretPath(), encrypted)
}

export async function clearEmailSmtpPassword(): Promise<void> {
  try {
    await unlink(emailSecretPath())
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return
    throw error
  }
}

async function readStoredEmailSmtpPassword(): Promise<string | undefined> {
  if (!isEmailSecretStorageAvailable()) return undefined
  try {
    const encrypted = await readFile(emailSecretPath())
    return safeStorage.decryptString(encrypted)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return undefined
    throw error
  }
}

/** Inject stored SMTP password into runtime env under the configured env var name. */
export async function applyStoredEmailPasswordToEnv(
  env: NodeJS.ProcessEnv,
  passwordEnvKey: string
): Promise<void> {
  const password = await readStoredEmailSmtpPassword()
  if (!password) return
  const key = passwordEnvKey.trim() || DEFAULT_EMAIL_PASSWORD_ENV
  env[key] = password
}
