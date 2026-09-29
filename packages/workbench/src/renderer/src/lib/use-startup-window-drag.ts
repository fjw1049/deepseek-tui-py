import { useEffect, type RefObject } from 'react'

/** Keep receiving pointer events even while the board is ready to move. */
export function useStartupWindowDrag(ref: RefObject<HTMLDivElement | null>, enabled: boolean): void {
  useEffect(() => {
    const board = ref.current
    const drag = window.dsGui?.startupWindowDrag
    if (!board || !enabled || !drag) return
    let timer: ReturnType<typeof setTimeout> | undefined
    let anchor: { x: number; y: number } | undefined
    let pointer: number | undefined

    const reset = (): void => {
      clearTimeout(timer)
      anchor = undefined
      delete board.dataset.windowDrag
      const captured = pointer
      pointer = undefined
      if (captured !== undefined) {
        drag('end')
        if (board.hasPointerCapture(captured)) board.releasePointerCapture(captured)
      }
    }
    const eligible = (e: PointerEvent): boolean => {
      const rect = board.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      return e.pointerType === 'mouse' && x >= 8 && y >= 8 &&
        x < rect.width - 8 && y < rect.height - 8 && !(x < 112 && y < 48)
    }
    const move = (e: PointerEvent): void => {
      if (pointer !== undefined) {
        if (e.pointerId !== pointer) return
        if (e.buttons & 1) drag('move')
        else reset()
        return
      }
      if (!eligible(e) || e.buttons !== 0) { reset(); return }
      if (anchor && Math.hypot(e.clientX - anchor.x, e.clientY - anchor.y) <= 5) return
      reset()
      anchor = { x: e.clientX, y: e.clientY }
      timer = setTimeout(() => { board.dataset.windowDrag = 'ready' }, 500)
    }
    const down = (e: PointerEvent): void => {
      if (board.dataset.windowDrag !== 'ready' || !eligible(e) || e.button !== 0 || e.buttons !== 1) {
        reset()
        return
      }
      clearTimeout(timer)
      pointer = e.pointerId
      board.setPointerCapture(pointer)
      board.dataset.windowDrag = 'dragging'
      e.preventDefault()
      drag('start')
    }
    const up = (e: PointerEvent): void => {
      if (pointer !== undefined && e.pointerId !== pointer) return
      if (pointer !== undefined) drag('move')
      reset()
      move(e)
    }
    const leave = (): void => { if (pointer === undefined) reset() }
    board.addEventListener('pointermove', move)
    board.addEventListener('pointerdown', down)
    board.addEventListener('pointerup', up)
    board.addEventListener('pointerleave', leave)
    board.addEventListener('pointercancel', reset)
    board.addEventListener('lostpointercapture', reset)
    window.addEventListener('blur', reset)
    document.addEventListener('visibilitychange', reset)
    return () => {
      board.removeEventListener('pointermove', move)
      board.removeEventListener('pointerdown', down)
      board.removeEventListener('pointerup', up)
      board.removeEventListener('pointerleave', leave)
      board.removeEventListener('pointercancel', reset)
      board.removeEventListener('lostpointercapture', reset)
      window.removeEventListener('blur', reset)
      document.removeEventListener('visibilitychange', reset)
      reset()
    }
  }, [ref, enabled])
}
