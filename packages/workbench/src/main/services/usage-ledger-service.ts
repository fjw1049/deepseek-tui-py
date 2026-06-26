import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'
import { randomUUID } from 'node:crypto'
import { resolveWorkbenchUsageLedgerPath } from '../deepseek-paths'
import {
  emptyUsageLedger,
  normalizeUsageLedger,
  pruneUsageEndpointModel,
  pruneUsageProvider,
  queryUsageLedger,
  USAGE_LEDGER_SCHEMA_VERSION,
  type UsageLedgerV1,
  type UsageQueryResult,
  type UsageRange
} from '../../shared/usage-ledger'
import { buildMockUsageLedger, isUsageMockEnabled } from '../../shared/usage-ledger-mock'
import { withUsageLedgerLock } from './usage-ledger-lock'

async function readLedger(path: string): Promise<{ ledger: UsageLedgerV1; readable: boolean }> {
  try {
    const raw = await readFile(path, 'utf8')
    const parsed = JSON.parse(raw) as Partial<UsageLedgerV1>
    if (parsed.schemaVersion !== USAGE_LEDGER_SCHEMA_VERSION) {
      return { ledger: emptyUsageLedger(), readable: false }
    }
    return { ledger: normalizeUsageLedger(parsed), readable: true }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return { ledger: emptyUsageLedger(), readable: true }
    }
    return { ledger: emptyUsageLedger(), readable: false }
  }
}

async function writeLedger(path: string, ledger: UsageLedgerV1): Promise<void> {
  await mkdir(dirname(path), { recursive: true })
  const payload = JSON.stringify(
    {
      ...ledger,
      updatedAt: new Date().toISOString()
    },
    null,
    2
  )
  const tempPath = join(tmpdir(), `ledger-${randomUUID()}.json`)
  await writeFile(tempPath, payload, 'utf8')
  await rename(tempPath, path)
}

export class UsageLedgerService {
  private readonly path: string

  constructor(path = resolveWorkbenchUsageLedgerPath()) {
    this.path = path
  }

  async query(range: UsageRange, locale = 'en'): Promise<UsageQueryResult> {
    return withUsageLedgerLock(this.path, async () => {
      if (isUsageMockEnabled()) {
        return queryUsageLedger(buildMockUsageLedger(), range, locale)
      }
      const { ledger, readable } = await readLedger(this.path)
      const base = readable ? ledger : emptyUsageLedger()
      return queryUsageLedger(base, range, locale)
    })
  }

  async pruneProvider(providerId: string): Promise<void> {
    await withUsageLedgerLock(this.path, async () => {
      const { ledger, readable } = await readLedger(this.path)
      if (!readable) return
      await writeLedger(this.path, pruneUsageProvider(ledger, providerId))
    })
  }

  async pruneEndpointModel(providerId: string, modelId: string): Promise<void> {
    await withUsageLedgerLock(this.path, async () => {
      const { ledger, readable } = await readLedger(this.path)
      if (!readable) return
      await writeLedger(this.path, pruneUsageEndpointModel(ledger, providerId, modelId))
    })
  }
}

export const usageLedgerService = new UsageLedgerService()
