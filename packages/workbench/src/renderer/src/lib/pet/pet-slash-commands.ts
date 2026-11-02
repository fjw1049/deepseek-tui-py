import type { PetStateId } from './pet-states'

export type PetSlashAction =
  | { type: 'burst'; stateId: Extract<PetStateId, 'waving' | 'jumping'> }
  | { type: 'pat' }
  | { type: 'set_enabled'; enabled: boolean }
  | { type: 'set_chatter'; enabled: boolean }
  | { type: 'toggle_enabled' }
  | { type: 'unknown' }

export type PetSlashMenuItem = {
  command: string
  token: string
  titleKey: string
  descriptionKey: string
}

export const PET_SLASH_MENU: readonly PetSlashMenuItem[] = [
  {
    command: '/pet pat',
    token: 'pat',
    titleKey: 'petSlashPatTitle',
    descriptionKey: 'petSlashPatDescription'
  },
  {
    command: '/pet wave',
    token: 'wave',
    titleKey: 'petSlashWaveTitle',
    descriptionKey: 'petSlashWaveDescription'
  },
  {
    command: '/pet jump',
    token: 'jump',
    titleKey: 'petSlashJumpTitle',
    descriptionKey: 'petSlashJumpDescription'
  },
  {
    command: '/pet wake',
    token: 'wake',
    titleKey: 'petSlashWakeTitle',
    descriptionKey: 'petSlashWakeDescription'
  },
  {
    command: '/pet tuck',
    token: 'tuck',
    titleKey: 'petSlashTuckTitle',
    descriptionKey: 'petSlashTuckDescription'
  },
  {
    command: '/pet mute',
    token: 'mute',
    titleKey: 'petSlashMuteTitle',
    descriptionKey: 'petSlashMuteDescription'
  },
  {
    command: '/pet unmute',
    token: 'unmute',
    titleKey: 'petSlashUnmuteTitle',
    descriptionKey: 'petSlashUnmuteDescription'
  }
] as const

export function getPetSlashQuery(input: string): string | null {
  const trimmed = input.trimStart()
  if (!trimmed.toLowerCase().startsWith('/pet')) return null
  if (/^\/pet(?:\s+\S+){2,}/i.test(trimmed)) return null
  return trimmed.slice(1).toLowerCase().replace(/^pet\b\/?/, '').trim()
}

export function filterPetSlashMenu(query: string): PetSlashMenuItem[] {
  const trimmed = query.trim().toLowerCase()
  if (!trimmed) return [...PET_SLASH_MENU]
  return PET_SLASH_MENU.filter((item) => {
    const haystack = [item.command, item.token, item.titleKey, item.descriptionKey]
      .join(' ')
      .toLowerCase()
    return haystack.includes(trimmed) || item.token.startsWith(trimmed)
  })
}

export function parsePetSlashCommand(input: string): PetSlashAction | null {
  const trimmed = input.trim()
  if (!/^\/pet(?:\s|$)/i.test(trimmed)) return null

  const sub = trimmed.slice(4).trim().toLowerCase()
  if (!sub) return { type: 'toggle_enabled' }
  if (sub === 'pat') return { type: 'pat' }
  if (sub === 'wave') return { type: 'burst', stateId: 'waving' }
  if (sub === 'jump') return { type: 'burst', stateId: 'jumping' }
  if (sub === 'wake' || sub === 'show') return { type: 'set_enabled', enabled: true }
  if (sub === 'tuck' || sub === 'hide') return { type: 'set_enabled', enabled: false }
  if (sub === 'mute') return { type: 'set_chatter', enabled: false }
  if (sub === 'unmute') return { type: 'set_chatter', enabled: true }
  // Caught here so a typo gets a notice instead of being sent to the model.
  return { type: 'unknown' }
}
