import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { homedir } from 'node:os'
import {
  emptyUsageLedger,
  normalizeUsageLedger,
  queryUsageLedger,
  USAGE_LEDGER_SCHEMA_VERSION
} from '../src/shared/usage-ledger'
import { buildMockUsageLedger, mergeUsageLedgers } from '../src/shared/usage-ledger-mock'

function resolveLedgerPath(): string {
  const root = process.env.DEEPSEEK_HOME?.trim() || join(homedir(), '.deepseek')
  return join(root, 'workbench', 'usage', 'ledger-v1.json')
}

async function readExisting(path: string) {
  try {
    const raw = await readFile(path, 'utf8')
    const parsed = JSON.parse(raw) as { schemaVersion?: number }
    if (parsed.schemaVersion !== USAGE_LEDGER_SCHEMA_VERSION) return emptyUsageLedger()
    return normalizeUsageLedger(parsed)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return emptyUsageLedger()
    throw error
  }
}

async function main(): Promise<void> {
  const path = resolveLedgerPath()
  const replace = process.argv.includes('--replace')
  const existing = replace ? emptyUsageLedger() : await readExisting(path)
  const merged = mergeUsageLedgers(existing, buildMockUsageLedger())
  await mkdir(dirname(path), { recursive: true })
  await writeFile(path, `${JSON.stringify(merged, null, 2)}\n`, 'utf8')

  const preview = queryUsageLedger(merged, '30d', 'zh')
  const modelCount = preview.summary?.buckets.length ?? 0
  const totalTokens = preview.summary?.totals.totalTokens ?? 0
  console.log(`Wrote mock usage ledger to ${path}`)
  console.log(`30d preview: ${modelCount} models, ${totalTokens.toLocaleString()} tokens`)
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error))
  process.exit(1)
})
