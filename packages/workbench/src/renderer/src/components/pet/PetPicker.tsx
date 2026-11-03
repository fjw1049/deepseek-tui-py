import { useEffect, useMemo, useState, type ReactElement } from 'react'
import { Check, Heart } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { PetPopularEntry } from '@shared/pet-popular'
import { resolvePetSpritesheetSrc } from '../../lib/pet/pet-catalog'
import { usePetThumbnails } from '../../lib/pet/pet-thumbnails'
import type { PetStateId } from '../../lib/pet/pet-states'
import { PetSprite } from './PetSprite'

export type PetPickerItem = Pick<PetPopularEntry, 'slug' | 'displayName' | 'submittedBy' | 'likeCount'>

const PREVIEW_STATES: ReadonlyArray<{ id: PetStateId; labelKey: string }> = [
  { id: 'idle', labelKey: 'petPreviewIdle' },
  { id: 'running', labelKey: 'petPreviewWorking' },
  { id: 'review', labelKey: 'petPreviewReading' },
  { id: 'waiting', labelKey: 'petPreviewWaiting' },
  { id: 'waving', labelKey: 'petPreviewDone' },
  { id: 'jumping', labelKey: 'petPreviewPatted' },
  { id: 'failed', labelKey: 'petPreviewFailed' },
  { id: 'running-right', labelKey: 'petPreviewWalking' }
]

function PetPreview({ pet, slug }: { pet: PetPickerItem | null; slug: string }): ReactElement {
  const { t } = useTranslation('settings')
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const [state, setState] = useState<PetStateId>('idle')
  const [playKey, setPlayKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    let revoke: (() => void) | null = null
    setFailed(false)
    setSrc(null)
    setState('idle')
    void resolvePetSpritesheetSrc(slug).then((result) => {
      if (cancelled) return result.revoke()
      revoke = result.revoke
      setSrc(result.src)
    }).catch(() => {
      if (!cancelled) {
        setSrc(null)
        setFailed(true)
      }
    })
    return () => {
      cancelled = true
      // The next sheet replaces this one on screen first, so release it a moment later.
      if (revoke) window.setTimeout(revoke, 1000)
    }
  }, [slug])

  return (
    <div className="flex min-w-0 flex-col gap-2.5">
      <div className="relative flex h-64 items-center justify-center overflow-hidden rounded-xl border border-ds-border-muted bg-ds-card dark:bg-white/[0.04]">
        {src ? (
          <PetSprite src={src} stateId={state} playKey={playKey} scale={1.1} label={pet?.displayName ?? slug} />
        ) : (
          <span className="self-center text-[12px] text-ds-faint">
            {t(failed ? 'petMascotPreviewUnavailable' : 'petMascotPreviewLoading')}
          </span>
        )}
      </div>
      <div className="min-w-0">
        <div className="truncate text-[14px] font-semibold text-ds-ink">{pet?.displayName ?? slug}</div>
        <div className="mt-0.5 flex min-w-0 items-center gap-2 text-[12px] text-ds-faint">
          {pet?.submittedBy ? <span className="truncate">{t('petPreviewBy', { name: pet.submittedBy })}</span> : null}
          {pet?.likeCount != null ? (
            <span className="inline-flex shrink-0 items-center gap-0.5">
              <Heart className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
              {pet.likeCount}
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex flex-wrap gap-1" role="group" aria-label={t('petPreviewStates')}>
        {PREVIEW_STATES.map((option) => (
          <button
            key={option.id}
            type="button"
            aria-pressed={state === option.id}
            disabled={!src}
            onClick={() => {
              setState(option.id)
              setPlayKey((key) => key + 1)
            }}
            className={`rounded-md border px-2 py-0.5 text-[11px] transition ${
              state === option.id
                ? 'border-accent/40 bg-accent/10 text-accent'
                : 'border-ds-border bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
            }`}
          >
            {t(option.labelKey)}
          </button>
        ))}
      </div>
    </div>
  )
}

function PetTile({
  pet,
  thumb,
  selected,
  onSelect
}: {
  pet: PetPickerItem
  thumb: string | null | undefined
  selected: boolean
  onSelect: () => void
}): ReactElement {
  return (
    <button
      type="button"
      aria-pressed={selected}
      title={pet.displayName}
      onClick={onSelect}
      className={`group relative flex min-w-0 flex-col items-center gap-1 rounded-xl border px-1 pb-1.5 pt-2 transition ${
        selected
          ? 'border-accent/50 bg-accent/10'
          : 'border-transparent hover:border-ds-border hover:bg-ds-hover'
      }`}
    >
      {/* Petdex thumbnails carry a 3px black band on each side; the 56px image is cropped to 48. */}
      <span className="flex h-12 w-12 items-center justify-center overflow-hidden">
        {thumb ? (
          <img src={thumb} alt="" className="h-14 w-14 max-w-none" draggable={false} />
        ) : (
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-ds-main text-[14px] font-semibold text-ds-faint">
            {pet.displayName.slice(0, 1).toUpperCase()}
          </span>
        )}
      </span>
      <span className={`w-full truncate text-center text-[11px] ${selected ? 'font-semibold text-accent' : 'text-ds-muted group-hover:text-ds-ink'}`}>
        {pet.displayName}
      </span>
      {selected ? (
        <span className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-accent text-white">
          <Check className="h-3 w-3" strokeWidth={2.5} aria-hidden="true" />
        </span>
      ) : null}
    </button>
  )
}

export function PetPicker({
  enabled,
  selectedSlug,
  selectedPet,
  popular,
  onSelect
}: {
  enabled: boolean
  selectedSlug: string
  /** Name and stats for the current pet, when the ranking knows them. */
  selectedPet: PetPickerItem | null
  popular: PetPickerItem[]
  onSelect: (pet: PetPickerItem) => void
}): ReactElement {
  const thumbs = usePetThumbnails(useMemo(() => popular.map((pet) => pet.slug), [popular]))

  return (
    <fieldset
      disabled={!enabled}
      className={`grid min-w-0 gap-4 transition md:grid-cols-[260px_minmax(0,1fr)] ${
        enabled ? '' : 'pointer-events-none opacity-45 grayscale'
      }`}
    >
      <PetPreview pet={selectedPet} slug={selectedSlug} />
      <div className="flex min-w-0 flex-col gap-2">
        <div className="grid max-h-[300px] grid-cols-[repeat(auto-fill,minmax(76px,1fr))] gap-1 overflow-y-auto pr-1">
          {popular.map((pet) => (
            <PetTile
              key={pet.slug}
              pet={pet}
              thumb={thumbs[pet.slug]}
              selected={pet.slug === selectedSlug}
              onSelect={() => onSelect(pet)}
            />
          ))}
        </div>
      </div>
    </fieldset>
  )
}
