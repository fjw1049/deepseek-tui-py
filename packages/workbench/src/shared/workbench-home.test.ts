import { homedir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import {
  resolveWorkbenchHome,
  resolveWorkbenchLogsDir,
  resolveWorkbenchMarketplaceCacheDir,
  resolveWorkbenchPetCacheDir
} from './workbench-home'

describe('workbench-home', () => {
  const prev = process.env.DEEPSEEK_HOME

  afterEach(() => {
    if (prev === undefined) delete process.env.DEEPSEEK_HOME
    else process.env.DEEPSEEK_HOME = prev
  })

  it('defaults to ~/.deepseek/workbench', () => {
    delete process.env.DEEPSEEK_HOME
    expect(resolveWorkbenchHome()).toBe(join(homedir(), '.deepseek', 'workbench'))
    expect(resolveWorkbenchLogsDir()).toBe(join(homedir(), '.deepseek', 'workbench', 'logs'))
  })

  it('honors DEEPSEEK_HOME like Python user_deepseek_dir', () => {
    process.env.DEEPSEEK_HOME = '/tmp/custom-deepseek-home'
    expect(resolveWorkbenchHome()).toBe('/tmp/custom-deepseek-home/workbench')
    expect(resolveWorkbenchPetCacheDir()).toBe('/tmp/custom-deepseek-home/workbench/pet-cache')
    expect(resolveWorkbenchMarketplaceCacheDir()).toBe(
      '/tmp/custom-deepseek-home/workbench/marketplace-cache'
    )
  })

  it('home override wins over DEEPSEEK_HOME (tests)', () => {
    process.env.DEEPSEEK_HOME = '/tmp/custom-deepseek-home'
    expect(resolveWorkbenchHome('/tmp/os-home')).toBe(
      join('/tmp/os-home', '.deepseek', 'workbench')
    )
  })
})
