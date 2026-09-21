import { Columns2, LayoutGrid, Plus, Rows2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { MAX_CHAT_PANES, type ChatArrangement, type ChatLayout } from '../../store/chat-layout-store'

export function ChatSplitToolbar({ layout, onArrange, onAdd }: {
  layout: ChatLayout; onArrange: (arrangement: ChatArrangement) => void; onAdd: () => void
}) {
  const { t } = useTranslation('common')
  return <div className="ds-chat-split-toolbar ds-no-drag">
    <span className="ds-chat-split-toolbar-label">{t('splitAdd')}</span>
    <div className="ds-chat-split-arrangements" role="group" aria-label={t('splitArrangement')}>
      {([['grid', LayoutGrid, 'splitGrid'], ['horizontal', Columns2, 'splitHorizontal'], ['vertical', Rows2, 'splitVertical']] as const).map(([value, Icon, label]) =>
        <button key={value} type="button" className="ds-chat-split-icon" title={t(label)} aria-label={t(label)}
          aria-pressed={(layout.arrangement ?? 'grid') === value} onClick={() => onArrange(value)}>
          <Icon size={15} strokeWidth={1.75} aria-hidden="true" />
        </button>)}
    </div>
    <button type="button" className="ds-chat-split-icon" aria-label={t('splitAddPane')}
      title={t(layout.panes.length >= MAX_CHAT_PANES ? 'splitLimit' : 'splitAddPane')}
      disabled={layout.panes.length >= MAX_CHAT_PANES} onClick={onAdd}><Plus size={16} strokeWidth={1.75} aria-hidden="true" /></button>

  </div>
}
