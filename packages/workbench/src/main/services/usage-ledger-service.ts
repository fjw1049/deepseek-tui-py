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
  type UsageLedgerV1,
  type UsageQueryResult,
  type UsageRange
} from '../../shared/usage-ledger'

async function readLedger(path: string): Promise<UsageLedgerV1> {
  try {
    const raw = await readFile(path, 'utf8')
    return normalizeUsageLedger(JSON.parse(raw) as unknown)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return emptyUsageLedger()
    }
    return emptyUsageLedger()
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
    const ledger = await readLedger(this.path)
    return queryUsageLedger(ledger, range, locale)
  }

  async pruneProvider(providerId: string): Promise<void> {
    const ledger = await readLedger(this.path)
    await writeLedger(this.path, pruneUsageProvider(ledger, providerId))
  }

  async pruneEndpointModel(providerId: string, modelId: string): Promise<void> {
    const ledger = await readLedger(this.path)
    await writeLedger(this.path, pruneUsageEndpointModel(ledger, providerId, modelId))
  }
}

export const usageLedgerService = new UsageLedgerService()
