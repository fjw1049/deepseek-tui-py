import { describe, expect, it } from 'vitest'

import {
  filterPetSlashMenu,
  getPetSlashQuery,
  parsePetSlashCommand
} from './pet-slash-commands'

describe('parsePetSlashCommand', () => {
  it('maps wave and jump to decorative bursts', () => {
    expect(parsePetSlashCommand('/pet wave')).toEqual({ type: 'burst', stateId: 'waving' })
    expect(parsePetSlashCommand('/pet jump')).toEqual({ type: 'burst', stateId: 'jumping' })
  })

  it('maps wake and tuck to enabled changes', () => {
    expect(parsePetSlashCommand('/pet wake')).toEqual({ type: 'set_enabled', enabled: true })
    expect(parsePetSlashCommand('/pet tuck')).toEqual({ type: 'set_enabled', enabled: false })
  })

  it('toggles when /pet is submitted alone', () => {
    expect(parsePetSlashCommand('/pet')).toEqual({ type: 'toggle_enabled' })
  })

  it('ignores unknown or non-pet commands', () => {
    expect(parsePetSlashCommand('/pet dance')).toBeNull()
    expect(parsePetSlashCommand('/plan')).toBeNull()
  })
})

describe('getPetSlashQuery', () => {
  it('returns null once the command has extra arguments', () => {
    expect(getPetSlashQuery('/pet wave')).toBe('wave')
    expect(getPetSlashQuery('/pet wa')).toBe('wa')
    expect(getPetSlashQuery('/pet wave now')).toBeNull()
  })
})

describe('filterPetSlashMenu', () => {
  it('filters menu items by token prefix', () => {
    expect(filterPetSlashMenu('wa').map((item) => item.token)).toEqual(['wave', 'wake'])
  })
})
