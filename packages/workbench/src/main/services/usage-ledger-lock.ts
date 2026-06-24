import { constants, open, unlink } from 'node:fs/promises'
import { mkdir } from 'node:fs/promises'
import { dirname } from 'node:path'

const LOCK_SUFFIX = '.lock'
const LOCK_TIMEOUT_MS = 30_000
const LOCK_RETRY_MS = 50

export async function withUsageLedgerLock<T>(
  ledgerPath: string,
  fn: () => Promise<T>
): Promise<T> {
  const lockPath = `${ledgerPath}${LOCK_SUFFIX}`
  await mkdir(dirname(ledgerPath), { recursive: true })
  const deadline = Date.now() + LOCK_TIMEOUT_MS
  let acquired = false
  while (Date.now() < deadline) {
    try {
      const handle = await open(
        lockPath,
        constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY,
        0o644
      )
      await handle.write(Buffer.from(`${process.pid}\n`, 'utf8'))
      await handle.close()
      acquired = true
      break
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error
      await new Promise((resolve) => setTimeout(resolve, LOCK_RETRY_MS))
    }
  }
  if (!acquired) {
    throw new Error(`timed out acquiring usage ledger lock: ${lockPath}`)
  }
  try {
    return await fn()
  } finally {
    await unlink(lockPath).catch(() => {})
  }
}
