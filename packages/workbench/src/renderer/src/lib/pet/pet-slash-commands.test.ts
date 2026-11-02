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
    expect(parsePetSlashCommand('/pet pat')).toEqual({ type: 'pat' })
  })

  it('maps wake, tuck, mute and unmute', () => {
    expect(parsePetSlashCommand('/pet wake')).toEqual({ type: 'set_enabled', enabled: true })
    expect(parsePetSlashCommand('/pet tuck')).toEqual({ type: 'set_enabled', enabled: false })
    expect(parsePetSlashCommand('/pet mute')).toEqual({ type: 'set_chatter', enabled: false })
    expect(parsePetSlashCommand('/pet unmute')).toEqual({ type: 'set_chatter', enabled: true })
  })

  it('toggles when /pet is submitted alone', () => {
    expect(parsePetSlashCommand('/pet')).toEqual({ type: 'toggle_enabled' })
  })

  it('catches unknown pet commands so they are not sent to the model', () => {
    expect(parsePetSlashCommand('/pet dance')).toEqual({ type: 'unknown' })
    expect(parsePetSlashCommand('/pet wave please')).toEqual({ type: 'unknown' })
  })

  it('ignores other commands', () => {
    expect(parsePetSlashCommand('/plan')).toBeNull()
    expect(parsePetSlashCommand('/petition draft')).toBeNull()
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
    expect(filterPetSlashMenu('mu').map((item) => item.token)).toEqual(['mute', 'unmute'])
  })
})
