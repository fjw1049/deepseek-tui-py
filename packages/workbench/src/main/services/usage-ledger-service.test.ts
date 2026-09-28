import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, it, vi } from 'vitest'
import { emptyUsageLedger, queryUsageLedger } from '../../shared/usage-ledger'
import { UsageLedgerService } from './usage-ledger-service'

vi.mock('./usage-ledger-lock', () => ({
  withUsageLedgerLock: vi.fn(async () => {
    throw new Error('timed out acquiring usage ledger lock')
  })
}))

it('queries usage when the Python ledger lock file remains on disk', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'usage-ledger-query-'))
  const path = join(dir, 'usage.json')
  const ledger = emptyUsageLedger()
  const day = queryUsageLedger(ledger, '7d').asOfDay
  const totals = {
    input_tokens: 2,
    output_tokens: 1,
    total_tokens: 3,
    cost_usd: 0,
    cost_cny: 0,
    turns: 1
  }
  ledger.days[day] = {
    models: { test: { model: 'test', ...totals } },
    totals
  }
  await writeFile(path, JSON.stringify(ledger))
  await writeFile(`${path}.lock`, `${process.pid}\n`)

  try {
    await expect(new UsageLedgerService(path).query('7d')).resolves.toMatchObject({
      range: '7d',
      summary: { totals: { totalTokens: 3 } }
    })
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})
