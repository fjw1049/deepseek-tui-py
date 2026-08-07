/**
 * Guest-page element picker for HTML preview → Composer.
 * Host injects via webview.executeJavaScript; picks return over console-message.
 */

export const PREVIEW_PICK_CONSOLE_PREFIX = '__DS_PREVIEW_PICK__v1__'

export const PREVIEW_PICK_TEXT_MAX = 200
export const PREVIEW_PICK_HTML_MAX = 1200
export const PREVIEW_PICK_ANCESTRY_MAX = 3

export type PreviewElementPickPayload = {
  selector: string
  tagName: string
  id?: string
  classes: string[]
  textPreview: string
  htmlSnippet: string
  ancestry: string[]
}

export type PreviewElementPick = PreviewElementPickPayload & {
  filePath: string
}

export type PreviewPickWireMessage =
  | { type: 'pick'; payload: PreviewElementPickPayload }
  | { type: 'cancel' }

export function parsePreviewPickConsoleMessage(message: string): PreviewPickWireMessage | null {
  const trimmed = message.trim()
  if (!trimmed.startsWith(PREVIEW_PICK_CONSOLE_PREFIX)) return null
  const raw = trimmed.slice(PREVIEW_PICK_CONSOLE_PREFIX.length)
  try {
    const parsed = JSON.parse(raw) as PreviewPickWireMessage
    if (!parsed || typeof parsed !== 'object') return null
    if (parsed.type === 'cancel') return { type: 'cancel' }
    if (parsed.type !== 'pick' || !parsed.payload || typeof parsed.payload !== 'object') return null
    const payload = sanitizePickPayload(parsed.payload)
    return payload ? { type: 'pick', payload } : null
  } catch {
    return null
  }
}

/**
 * Electron <webview> console-message puts text on `event.message` (Electron 34+
 * also prefers event-object form over the old multi-arg listener). Be defensive
 * about shape so a silent undefined never kills the pick bridge.
 */
export function extractWebviewConsoleMessage(event: Event): string | null {
  const record = event as Event & {
    message?: unknown
    detail?: { message?: unknown } | unknown
  }
  if (typeof record.message === 'string' && record.message) return record.message
  if (
    record.detail &&
    typeof record.detail === 'object' &&
    typeof (record.detail as { message?: unknown }).message === 'string'
  ) {
    const nested = (record.detail as { message: string }).message
    return nested || null
  }
  return null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function sanitizePickPayload(raw: PreviewElementPickPayload): PreviewElementPickPayload | null {
  const selector = asString(raw.selector).trim()
  const tagName = asString(raw.tagName).trim().toLowerCase()
  if (!selector || !tagName) return null
  const classes = Array.isArray(raw.classes)
    ? raw.classes.filter((item): item is string => typeof item === 'string').slice(0, 8)
    : []
  const ancestry = Array.isArray(raw.ancestry)
    ? raw.ancestry.filter((item): item is string => typeof item === 'string').slice(0, PREVIEW_PICK_ANCESTRY_MAX)
    : []
  const id = asString(raw.id).trim() || undefined
  return {
    selector: selector.slice(0, 500),
    tagName: tagName.slice(0, 64),
    ...(id ? { id: id.slice(0, 128) } : {}),
    classes,
    textPreview: asString(raw.textPreview).slice(0, PREVIEW_PICK_TEXT_MAX),
    htmlSnippet: asString(raw.htmlSnippet).slice(0, PREVIEW_PICK_HTML_MAX),
    ancestry
  }
}

/** Dispose any previous picker instance in the guest page. */
export function buildPreviewPickerCleanupScript(): string {
  return `(() => {
  // Flip the arm flag first so any orphaned capture listeners become no-ops
  // even if dispose() is missing / fails (host tracking can get out of sync).
  try { window.__dsPreviewPickActive = false; } catch {}
  try { window.__dsPreviewPick?.dispose?.(); } catch {}
  try { delete window.__dsPreviewPick; } catch {}
  try { document.getElementById('__ds_preview_pick_overlay__')?.remove(); } catch {}
  try { document.getElementById('__ds_preview_pick_menu__')?.remove(); } catch {}
  try { document.documentElement.style.cursor = ''; } catch {}
})();`
}

/**
 * Inject (or replace) the element picker. Emits console messages with
 * PREVIEW_PICK_CONSOLE_PREFIX for the host to parse.
 */
export function buildPreviewPickerInjectScript(): string {
  const prefix = JSON.stringify(PREVIEW_PICK_CONSOLE_PREFIX)
  const textMax = PREVIEW_PICK_TEXT_MAX
  const htmlMax = PREVIEW_PICK_HTML_MAX
  const ancestryMax = PREVIEW_PICK_ANCESTRY_MAX
  return `(() => {
  try { window.__dsPreviewPick?.dispose?.(); } catch {}
  // Armed flag: every handler checks this so a missed dispose cannot leave
  // click/mousemove capture listeners selecting elements after Inspect is off.
  window.__dsPreviewPickActive = true;

  const PREFIX = ${prefix};
  const TEXT_MAX = ${textMax};
  const HTML_MAX = ${htmlMax};
  const ANCESTRY_MAX = ${ancestryMax};
  const SKIP = new Set(['HTML', 'HEAD', 'BODY', 'SCRIPT', 'STYLE', 'LINK', 'META', 'NOSCRIPT', 'BR', 'HR']);
  const isArmed = () => window.__dsPreviewPickActive === true;

  // Prefer warn (level=2): some Chromium/webview paths are flaky about
  // forwarding console.log (level=1) to the host console-message event.
  const emit = (msg) => {
    if (!isArmed()) return;
    try { console.warn(PREFIX + JSON.stringify(msg)); } catch {}
  };

  const truncate = (value, max) => {
    const text = String(value || '');
    return text.length > max ? text.slice(0, max) : text;
  };

  const labelFor = (el) => {
    const tag = (el.tagName || '').toLowerCase();
    if (!tag) return '';
    if (el.id) return tag + '#' + el.id;
    const classes = el.classList && el.classList.length
      ? '.' + Array.from(el.classList).slice(0, 2).join('.')
      : '';
    return tag + classes;
  };

  const cssEscape = (value) => {
    if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, (ch) => '\\\\' + ch);
  };

  const buildSelector = (el) => {
    if (el.id) return '#' + cssEscape(el.id);
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur !== document.documentElement && parts.length < 6) {
      let part = cur.tagName.toLowerCase();
      if (cur.classList && cur.classList.length) {
        part += '.' + Array.from(cur.classList).slice(0, 2).map(cssEscape).join('.');
      }
      const parent = cur.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((child) => child.tagName === cur.tagName);
        if (siblings.length > 1) {
          part += ':nth-of-type(' + (siblings.indexOf(cur) + 1) + ')';
        }
      }
      parts.unshift(part);
      if (cur === document.body) break;
      cur = parent;
    }
    return parts.join(' > ');
  };

  const buildAncestry = (el) => {
    const out = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && out.length < ANCESTRY_MAX) {
      const label = labelFor(cur);
      if (label) out.unshift(label);
      if (cur === document.body) break;
      cur = cur.parentElement;
    }
    return out;
  };

  const pickTarget = (raw) => {
    let el = raw;
    while (el && el.nodeType === 1) {
      if (!SKIP.has(el.tagName) && el !== document.documentElement) return el;
      el = el.parentElement;
    }
    return null;
  };

  let overlay = document.getElementById('__ds_preview_pick_overlay__');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = '__ds_preview_pick_overlay__';
    overlay.setAttribute('data-ds-preview-pick', '1');
    Object.assign(overlay.style, {
      position: 'fixed',
      pointerEvents: 'none',
      zIndex: '2147483646',
      border: '2px solid #3b82f6',
      background: 'rgba(59, 130, 246, 0.12)',
      borderRadius: '4px',
      display: 'none',
      boxSizing: 'border-box'
    });
    document.documentElement.appendChild(overlay);
  }

  let menu = document.getElementById('__ds_preview_pick_menu__');
  if (!menu) {
    menu = document.createElement('button');
    menu.id = '__ds_preview_pick_menu__';
    menu.type = 'button';
    menu.textContent = '用 Chat 修改此处';
    menu.setAttribute('data-ds-preview-pick', '1');
    Object.assign(menu.style, {
      position: 'fixed',
      zIndex: '2147483647',
      display: 'none',
      pointerEvents: 'auto',
      border: '1px solid rgba(15, 23, 42, 0.12)',
      background: '#0f172a',
      color: '#f8fafc',
      borderRadius: '8px',
      padding: '8px 12px',
      fontSize: '12px',
      fontFamily: 'system-ui, sans-serif',
      boxShadow: '0 8px 24px rgba(0,0,0,0.18)',
      cursor: 'pointer'
    });
    document.documentElement.appendChild(menu);
  }

  let hoverEl = null;
  let menuEl = null;

  const placeOverlay = (el) => {
    if (!el) {
      overlay.style.display = 'none';
      return;
    }
    const rect = el.getBoundingClientRect();
    overlay.style.display = 'block';
    overlay.style.top = Math.max(0, rect.top) + 'px';
    overlay.style.left = Math.max(0, rect.left) + 'px';
    overlay.style.width = Math.max(0, rect.width) + 'px';
    overlay.style.height = Math.max(0, rect.height) + 'px';
  };

  const hideMenu = () => {
    menu.style.display = 'none';
    menuEl = null;
  };

  const collect = (el) => ({
    type: 'pick',
    payload: {
      selector: buildSelector(el),
      tagName: (el.tagName || '').toLowerCase(),
      id: el.id || undefined,
      classes: el.classList ? Array.from(el.classList).slice(0, 8) : [],
      textPreview: truncate((el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(), TEXT_MAX),
      htmlSnippet: truncate(el.outerHTML || '', HTML_MAX),
      ancestry: buildAncestry(el)
    }
  });

  const confirm = (el) => {
    if (!el) return;
    emit(collect(el));
  };

  const onMove = (event) => {
    if (!isArmed()) return;
    if (menu.style.display === 'block' && event.target === menu) return;
    const el = pickTarget(event.target);
    hoverEl = el;
    placeOverlay(el);
  };

  const onClick = (event) => {
    if (!isArmed()) return;
    if (event.target === menu) return;
    const el = pickTarget(event.target);
    if (!el) return;
    event.preventDefault();
    event.stopPropagation();
    hideMenu();
    confirm(el);
  };

  const onContextMenu = (event) => {
    if (!isArmed()) return;
    const el = pickTarget(event.target);
    if (!el) return;
    event.preventDefault();
    event.stopPropagation();
    hoverEl = el;
    menuEl = el;
    placeOverlay(el);
    menu.style.display = 'block';
    const x = Math.min(event.clientX, window.innerWidth - 160);
    const y = Math.min(event.clientY, window.innerHeight - 48);
    menu.style.left = Math.max(8, x) + 'px';
    menu.style.top = Math.max(8, y) + 'px';
  };

  const onMenuClick = (event) => {
    if (!isArmed()) return;
    event.preventDefault();
    event.stopPropagation();
    const el = menuEl || hoverEl;
    hideMenu();
    confirm(el);
  };

  const onKeyDown = (event) => {
    if (!isArmed()) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      emit({ type: 'cancel' });
    }
  };

  const onScroll = () => {
    if (!isArmed()) return;
    hideMenu();
    placeOverlay(hoverEl);
  };

  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onClick, true);
  document.addEventListener('contextmenu', onContextMenu, true);
  document.addEventListener('keydown', onKeyDown, true);
  window.addEventListener('scroll', onScroll, true);
  menu.addEventListener('click', onMenuClick);

  const prevCursor = document.documentElement.style.cursor;
  document.documentElement.style.cursor = 'crosshair';

  window.__dsPreviewPick = {
    dispose() {
      window.__dsPreviewPickActive = false;
      document.removeEventListener('mousemove', onMove, true);
      document.removeEventListener('click', onClick, true);
      document.removeEventListener('contextmenu', onContextMenu, true);
      document.removeEventListener('keydown', onKeyDown, true);
      window.removeEventListener('scroll', onScroll, true);
      menu.removeEventListener('click', onMenuClick);
      document.documentElement.style.cursor = prevCursor;
      try { overlay.remove(); } catch {}
      try { menu.remove(); } catch {}
    }
  };
})();`
}
