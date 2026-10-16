// @vitest-environment happy-dom
import { expect, it, vi } from 'vitest'
import { createWorkbenchResizePreview } from './workbench-resize-preview'

function hosts() {
  const shell = document.createElement('div')
  shell.innerHTML = `<div class="ds-workbench-sidebar-wrap" style="width:272px"><div class="ds-workbench-sidebar-slide" style="width:272px"></div></div>
    <div class="ds-chat-column" aria-hidden="false"></div>
    <aside class="ds-workbench-right-panel" style="width:400px"><div class="ds-right-panel-surface" style="width:400px"></div></aside>`
  return {
    shell,
    sidebar: shell.querySelector<HTMLElement>('.ds-workbench-sidebar-wrap')!,
    slide: shell.querySelector<HTMLElement>('.ds-workbench-sidebar-slide')!,
    chat: shell.querySelector<HTMLElement>('.ds-chat-column')!,
    right: shell.querySelector<HTMLElement>('.ds-workbench-right-panel')!,
    surface: shell.querySelector<HTMLElement>('.ds-right-panel-surface')!
  }
}

it('previews both sidebar layers and the panel surface without querying or measuring per frame', () => {
  const { shell, sidebar, slide, right, surface } = hosts()
  const apply = createWorkbenchResizePreview(shell, true, true)
  const query = vi.spyOn(shell, 'querySelector')
  const measure = vi.spyOn(shell, 'getBoundingClientRect')
  for (let delta = 0; delta <= 100; delta++) apply({ left: 272 + delta, right: 400 + delta, chatHidden: false })
  expect(sidebar.style.width).toBe('372px')
  expect(slide.style.width).toBe('372px')
  expect(shell.style.getPropertyValue('--ds-sidebar-width')).toBe('372px')
  expect(right.style.width).toBe('500px')
  expect(surface.style.width).toBe('500px')
  expect(query).not.toHaveBeenCalled()
  expect(measure).not.toHaveBeenCalled()
})

it('can drag out of fill-width and back without leaving fixed surface constraints or hidden chat', () => {
  const { shell, right, surface, chat } = hosts()
  const apply = createWorkbenchResizePreview(shell, true, true)
  apply({ left: 272, right: 900, chatHidden: true })
  expect(right.style.width).toBe('100%')
  expect(right.hasAttribute('data-fill-width')).toBe(true)
  expect(surface.style.minWidth).toBe('100%')
  expect(surface.style.maxWidth).toBe('100%')
  expect(chat.inert).toBe(true)
  expect(chat.getAttribute('aria-hidden')).toBe('true')
  chat.style.setProperty('--ds-chat-rest-width', '500px')
  apply({ left: 272, right: 400, chatHidden: false })
  expect(right.style.width).toBe('400px')
  expect(right.hasAttribute('data-fill-width')).toBe(false)
  expect(surface.style.minWidth).toBe('')
  expect(surface.style.maxWidth).toBe('')
  expect(chat.inert).toBe(false)
  expect(chat.getAttribute('aria-hidden')).toBe('false')
  expect(chat.style.getPropertyValue('--ds-chat-rest-width')).toBe('')
})

it('leaves hidden or collapsed rails alone', () => {
  const { shell, sidebar, slide, right, surface } = hosts()
  createWorkbenchResizePreview(shell, false, false)({ left: 350, right: 700, chatHidden: true })
  expect(sidebar.style.width).toBe('272px')
  expect(slide.style.width).toBe('272px')
  expect(right.style.width).toBe('400px')
  expect(surface.style.width).toBe('400px')
})
