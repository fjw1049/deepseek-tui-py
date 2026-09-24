/** Native window movement while the startup canvas owns the central pointer area. */
export function StartupWindowDragRegions(): React.ReactElement {
  return (
    <div className="ds-startup-drag-regions" aria-hidden>
      <div className="ds-startup-drag-region ds-startup-drag-region--top" />
      <div className="ds-startup-drag-region ds-startup-drag-region--left" />
      <div className="ds-startup-drag-region ds-startup-drag-region--right" />
      <div className="ds-startup-drag-region ds-startup-drag-region--bottom" />
    </div>
  )
}
