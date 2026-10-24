import { useRef, useState, type ReactElement, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Circle, Check, MousePointer2, MoveUpRight, Pencil, Redo2, Square, Trash2, Type, Undo2, X } from 'lucide-react'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { ANNOTATION_COLORS, ANNOTATION_SHAPES, ANNOTATION_WIDTHS, type AnnotationShape, type AnnotationTool } from '../../lib/browser-annotation'

/** `rest` waits on the live page; `pick` selects page elements; `sketch` draws on a frozen screenshot. */
export type AnnotationBarState = 'rest' | 'pick' | 'sketch'

const SHAPE_ICON: Record<AnnotationShape, typeof Square> = { rect: Square, ellipse: Circle, arrow: MoveUpRight }
const SHAPE_LABEL: Record<AnnotationShape, string> = { rect: 'annotationRect', ellipse: 'annotationEllipse', arrow: 'annotationArrow' }
const COLOR_LABEL: Record<string, string> = {
  '#E03131': 'annotationColorRed', '#1971C2': 'annotationColorBlue', '#2F9E44': 'annotationColorGreen',
  '#1F1E1D': 'annotationColorBlack', '#FFFFFF': 'annotationColorWhite'
}
const WIDTH_LABEL: Record<number, string> = { 2: 'annotationWidthThin', 4: 'annotationWidthMedium', 8: 'annotationWidthThick', 12: 'annotationWidthExtraThick' }

type Menu = 'shape' | 'color' | 'width'

export function AnnotationToolbar({ state, status, tools, closable = true, tool, disabled, pickEnabled, color, width, canUndo, canRedo, canClear, showHistory, canAdd, adding,
  onPick, onTool, onColorChange, onWidthChange, onUndo, onRedo, onClear, onAdd, onClose }: {
  state: AnnotationBarState
  /** Who controls the page, shown ahead of the tools while the bar rests. */
  status?: ReactNode
  /** More resting tools (recording), after the annotation tools. */
  tools?: ReactNode
  /** False while the bar must stay up (the agent has the page, or something needs the user). */
  closable?: boolean
  /** The drawing tool in use while sketching. */
  tool: AnnotationTool | null
  /** The page cannot be annotated right now (agent working, page loading). */
  disabled: boolean
  pickEnabled: boolean
  color: string
  width: number
  canUndo: boolean
  canRedo: boolean
  canClear: boolean
  showHistory: boolean
  canAdd: boolean
  adding: boolean
  onPick: () => void
  onTool: (tool: AnnotationTool) => void
  onColorChange: (color: string) => void
  onWidthChange: (width: number) => void
  onUndo: () => void
  onRedo: () => void
  onClear: () => void
  onAdd: () => void
  onClose: () => void
}): ReactElement {
  const { t } = useTranslation()
  const [menu, setMenu] = useState<Menu | null>(null)
  const [shape, setShape] = useState<AnnotationShape>('rect')
  const root = useRef<HTMLDivElement>(null)
  useLightDismiss({ open: menu !== null, refs: [root], onDismiss: () => setMenu(null) })
  if (tool && tool !== 'pen' && tool !== 'text' && tool !== shape) setShape(tool)
  const ShapeIcon = SHAPE_ICON[shape]
  const pressed = state === 'sketch' ? tool : null

  const button = (label: string, icon: ReactNode, onClick: () => void, options: { pressed?: boolean; disabled?: boolean } = {}): ReactElement =>
    <button type="button" className="ds-annotation-toolbar__btn" aria-label={t(label)} title={t(label)} aria-pressed={options.pressed}
      disabled={options.disabled} onClick={() => { setMenu(null); onClick() }}>{icon}</button>
  const trigger = (which: Menu, label: string, content: ReactNode, triggerDisabled = false): ReactElement =>
    <button type="button" className="ds-annotation-toolbar__btn is-trigger" aria-label={t(label)} title={t(label)} aria-haspopup="menu"
      aria-expanded={menu === which} disabled={triggerDisabled} onClick={() => setMenu(menu === which ? null : which)}>{content}<ChevronDown size={12} aria-hidden="true" /></button>
  const item = (key: string, label: string, checked: boolean, leading: ReactNode, onSelect: () => void): ReactElement =>
    <button key={key} type="button" role="menuitemradio" aria-checked={checked} className="ds-dock-menu-item" onClick={() => { setMenu(null); onSelect() }}>
      {leading}<span>{t(label)}</span>{checked ? <Check size={14} className="ds-annotation-toolbar__check" aria-hidden="true" /> : null}</button>
  const addReason = state === 'pick' ? t('annotationAddPickHint') : canAdd ? undefined : t('annotationNothingToAdd')

  return <div ref={root} className="ds-annotation-toolbar" role="toolbar" aria-label={t('annotationToolbar')} data-state={state}
    onKeyDown={(e) => { if (e.key === 'Escape' && menu) { e.preventDefault(); e.stopPropagation(); setMenu(null) } }}>
    {state === 'rest' && status ? <>{status}<span className="ds-annotation-toolbar__divider" aria-hidden="true" /></> : null}
    {button('annotationPick', <MousePointer2 size={16} />, onPick, { pressed: state === 'pick', disabled: disabled || !pickEnabled })}
    {button('annotationPen', <Pencil size={16} />, () => onTool('pen'), { pressed: pressed === 'pen', disabled })}
    <span className="ds-annotation-toolbar__split">
      {button(SHAPE_LABEL[shape], <ShapeIcon size={16} />, () => onTool(shape), { pressed: pressed === shape, disabled })}
      {trigger('shape', 'annotationShapes', null, disabled)}
      {menu === 'shape' ? <div className="ds-dock-menu ds-annotation-toolbar__menu" role="menu" aria-label={t('annotationShapes')}>
        {ANNOTATION_SHAPES.map(value => {
          const Icon = SHAPE_ICON[value]
          return item(value, SHAPE_LABEL[value], value === shape, <Icon size={15} aria-hidden="true" />, () => { setShape(value); onTool(value) })
        })}
      </div> : null}
    </span>
    {button('annotationText', <Type size={16} />, () => onTool('text'), { pressed: pressed === 'text', disabled })}
    {state === 'rest' && tools ? <><span className="ds-annotation-toolbar__divider" aria-hidden="true" />{tools}</> : null}
    {state !== 'rest' || closable ? <span className="ds-annotation-toolbar__divider" aria-hidden="true" /> : null}
    {state !== 'rest' ? <>
      <span className="ds-annotation-toolbar__split">
        {trigger('color', 'annotationColor', <span className="ds-annotation-toolbar__swatch" style={{ background: color }} />)}
        {menu === 'color' ? <div className="ds-dock-menu ds-annotation-toolbar__menu" role="menu" aria-label={t('annotationColor')}>
          {ANNOTATION_COLORS.map(value => item(value, COLOR_LABEL[value]!, value === color,
            <span className="ds-annotation-toolbar__swatch" style={{ background: value }} aria-hidden="true" />, () => onColorChange(value)))}
        </div> : null}
      </span>
      <span className="ds-annotation-toolbar__split">
        {trigger('width', 'annotationWidth', <span className="ds-annotation-toolbar__stroke" style={{ height: Math.min(width, 8) }} />)}
        {menu === 'width' ? <div className="ds-dock-menu ds-annotation-toolbar__menu" role="menu" aria-label={t('annotationWidth')}>
          {ANNOTATION_WIDTHS.map(value => item(String(value), WIDTH_LABEL[value]!, value === width,
            <span className="ds-annotation-toolbar__stroke" style={{ height: Math.min(value, 8) }} aria-hidden="true" />, () => onWidthChange(value)))}
        </div> : null}
      </span>
      <span className="ds-annotation-toolbar__divider" aria-hidden="true" />
      {showHistory ? <>
        {button('annotationUndo', <Undo2 size={16} />, onUndo, { disabled: !canUndo })}
        {button('annotationRedo', <Redo2 size={16} />, onRedo, { disabled: !canRedo })}
        {button('annotationClear', <Trash2 size={16} />, onClear, { disabled: !canClear })}
      </> : null}
      {/* Disabled buttons get no hover, so the reason sits on a wrapper. */}
      <span className="ds-annotation-toolbar__reason" title={addReason}>
        <button type="button" className="ds-annotation-toolbar__primary" disabled={!canAdd || adding} aria-busy={adding} onClick={onAdd}>{t('annotationAdd')}</button>
      </span>
    </> : null}
    {state !== 'rest' || closable ? button(state === 'rest' ? 'annotationHide' : 'annotationClose', <X size={16} />, onClose) : null}
  </div>
}
