import { useEffect, useRef, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { useChatStore } from '../../store/chat-store'
import { MarketplaceKindSwitch, MarketplaceSearchCreate } from './marketplace-ui'
import { ConnectorsView } from './ConnectorsView'
import { PluginsView } from './PluginsView'
import { SkillsView } from './SkillsView'

export function MarketplaceView(): ReactElement {
  const { t } = useTranslation('common')
  const kind = useChatStore((s) => s.marketplaceKind)
  const setMarketplaceKind = useChatStore((s) => s.setMarketplaceKind)
  const createHostRef = useRef<HTMLDivElement | null>(null)
  const [createHost, setCreateHost] = useState<HTMLDivElement | null>(null)
  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)

  useEffect(() => {
    setCreateOpen(false)
  }, [kind])

  useLightDismiss({
    open: createOpen,
    onDismiss: () => setCreateOpen(false),
    refs: [createHostRef]
  })

  const panelProps = {
    query,
    createOpen,
    onCreateClose: () => setCreateOpen(false),
    createHost
  }

  return (
    <div className="ds-feature-page ds-plugin-page ds-page-scroll ds-no-drag min-h-0 flex-1 overflow-y-auto px-8 py-8">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="ds-ext-page-title text-[24px] font-semibold tracking-[-0.02em] text-ds-ink">
            {t('extensions')}
          </h1>
          <MarketplaceKindSwitch value={kind} onChange={setMarketplaceKind} />
        </div>
        <p className="mt-2 max-w-3xl text-[14px] leading-6 text-ds-muted">{t('marketplaceIntro')}</p>

        <MarketplaceSearchCreate
          query={query}
          onQueryChange={setQuery}
          placeholder={t('marketplaceSearch')}
          createOpen={createOpen}
          onCreateToggle={() => setCreateOpen((open) => !open)}
          createLabel={t('pluginCreate')}
          createHostRef={(node) => {
            createHostRef.current = node
            setCreateHost(node)
          }}
        />

        {kind === 'mcp' ? <ConnectorsView {...panelProps} /> : null}
        {kind === 'skills' ? <SkillsView {...panelProps} /> : null}
        {kind === 'plugins' ? <PluginsView {...panelProps} /> : null}
      </div>
    </div>
  )
}
