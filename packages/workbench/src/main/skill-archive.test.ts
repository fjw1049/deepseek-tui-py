import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, it } from 'vitest'
import { extractSkillArchive } from './skill-archive'

// Real ZIPs generated with Python zipfile. The malicious archive creates
// link -> ../victim.txt, then repeats "link" as a regular file containing OVERWRITE.
const valid = 'UEsDBBQAAAAAAAC6a13zGSGQFwAAABcAAAAIAAAAU0tJTEwubWQjIFRlbXBvcmFyeSB0ZXN0IHNraWxsClBLAQIUAxQAAAAAAAC6a13zGSGQFwAAABcAAAAIAAAAAAAAAAAAAACAAQAAAABTS0lMTC5tZFBLBQYAAAAAAQABADYAAAA9AAAAAAA='
const malicious = 'UEsDBBQAAAAAAAAAIQBEUJ4CDQAAAA0AAAAEAAAAbGluay4uL3ZpY3RpbS50eHRQSwMEFAAAAAAAALprXemeA28JAAAACQAAAAQAAABsaW5rT1ZFUldSSVRFUEsDBBQAAAAAAAC6a13zGSGQFwAAABcAAAAIAAAAU0tJTEwubWQjIFRlbXBvcmFyeSB0ZXN0IHNraWxsClBLAQIUAxQAAAAAAAAAIQBEUJ4CDQAAAA0AAAAEAAAAAAAAAAAAAAD/oQAAAABsaW5rUEsBAhQDFAAAAAAAALprXemeA28JAAAACQAAAAQAAAAAAAAAAAAAAIABLwAAAGxpbmtQSwECFAMUAAAAAAAAumtd8xkhkBcAAAAXAAAACAAAAAAAAAAAAAAAgAFaAAAAU0tJTEwubWRQSwUGAAAAAAMAAwCaAAAAlwAAAAAA'

it('extracts a real ordinary skill archive', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'skill-zip-'))
  try {
    const zip = join(directory, 'skill.zip')
    await writeFile(zip, Buffer.from(valid, 'base64'))
    await extractSkillArchive(zip, join(directory, 'out'))
    expect(await readFile(join(directory, 'out/SKILL.md'), 'utf8')).toBe('# Temporary test skill\n')
  } finally { await rm(directory, { recursive: true, force: true }) }
})

it('rejects a symlink overwrite without touching the external file', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'skill-zip-'))
  try {
    const zip = join(directory, 'skill.zip'), victim = join(directory, 'victim.txt')
    await writeFile(victim, 'original')
    await writeFile(zip, Buffer.from(malicious, 'base64'))
    await expect(extractSkillArchive(zip, join(directory, 'out'))).rejects.toThrow('Symbolic links')
    expect(await readFile(victim, 'utf8')).toBe('original')
  } finally { await rm(directory, { recursive: true, force: true }) }
})


it('rejects an oversized declared deflated member before inflation', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'skill-limit-'))
  try {
    const zip = join(directory, 'large.zip')
    await writeFile(zip, Buffer.from('UEsDBBQAAAAIAPJbbF3Jl7hQBgAAAAAAEAIIAAAAU0tJTEwubWQrycyrBABQSwECFAMUAAAACADyW2xdyZe4UAYAAAAAABACCAAAAAAAAAAAAAAAgAEAAAAAU0tJTEwubWRQSwUGAAAAAAEAAQA2AAAALAAAAAAA', 'base64'))
    await expect(extractSkillArchive(zip, join(directory, 'out'))).rejects.toThrow('extraction limits')
  } finally { await rm(directory, { recursive: true, force: true }) }
})

it('bounds entry count even for tiny files', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'skill-count-'))
  try {
    const source = Buffer.from(valid, 'base64')
    const centralOffset = source.indexOf(Buffer.from('504b0102', 'hex'))
    const endOffset = source.indexOf(Buffer.from('504b0506', 'hex'))
    const local = source.subarray(0, centralOffset)
    const central = source.subarray(centralOffset, endOffset)
    const count = 10_001
    const entries = Array.from({ length: count }, (_, i) => {
      const copy = Buffer.from(central)
      copy.writeUInt32LE(i * local.length, 42)
      return copy
    })
    const end = Buffer.from(source.subarray(endOffset))
    end.writeUInt16LE(count, 8); end.writeUInt16LE(count, 10)
    end.writeUInt32LE(count * central.length, 12); end.writeUInt32LE(count * local.length, 16)
    const zip = join(directory, 'many.zip')
    await writeFile(zip, Buffer.concat([...Array(count).fill(local), ...entries, end]))
    await expect(extractSkillArchive(zip, join(directory, 'out'))).rejects.toThrow('extraction limits')
  } finally { await rm(directory, { recursive: true, force: true }) }
})
