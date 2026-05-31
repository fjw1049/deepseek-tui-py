import type { ReactElement } from 'react'
import happyWhaleWordmark from '../../../../asset/img/happy-whale-wordmark.png'

export function SidebarBrand(): ReactElement {
  return (
    <div className="ds-sidebar-brand-mark" aria-label="Happy Whale">
      <img
        src={happyWhaleWordmark}
        alt="Happy Whale"
        className="ds-sidebar-brand-wordmark-img"
        draggable={false}
      />
    </div>
  )
}
