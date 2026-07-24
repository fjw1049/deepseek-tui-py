import { resolveProviderIcon, uniquifySvgIds } from './provider-icons.js'
import { clampEffortIndex } from './clamp-effort-index'

class ChatGPTModelSelector extends HTMLElement {
  static observedAttributes = ['value', 'model', 'disabled'];

  #tiers = [
    { key: 'Light',      valuetext: 'Light — fastest' },
    { key: 'Medium',     valuetext: 'Medium — balanced' },
    { key: 'High',       valuetext: 'High — smarter' },
    { key: 'Extra High', valuetext: 'Extra High — much smarter' },
    { key: 'Ultra',      valuetext: 'Ultra — smartest, consumes usage limits faster' },
  ];
  #index = 2;          // default High
  #models = [];        // [{id,label,providerId?}] injected from React
  #modelId = '';       // currently selected model id
  #labels = {
    title: 'Reasoning',
    hint: 'Faster ←→ Smarter',
    warning: 'Uses limits faster',
    aria: 'Reasoning intensity',
    desc: 'Left for faster responses, right for smarter responses.',
    configure: 'Configure custom models',
    dialog: 'Model settings',
  };
  #dragPos = null;     // continuous 0–1 position while dragging, else null
  #open = false;
  #dragging = false;
  #activePointer = null;
  #dragGeom = null;    // cached track geometry for the active gesture
  #hoveringSlider = false;
  #bound = false;
  #particles = [];
  #raf = 0;
  #sparkLast = 0;
  #sparkBox = null;
  #confettiParts = [];
  #confettiRaf = 0;
  #confettiLast = 0;
  #confettiBox = null;
  #lastBurst = 0;
  #burstFiredThisGesture = false;
  #snapSettleCb = null;
  #resizeObserver = null;
  #closeTimer = 0;
  #snapTimer = 0;
  #reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  #onDocPointerDown = (e) => {
    if (!e.composedPath().includes(this)) this.#close();
  };
  #onMotionPrefChange = () => {
    if (this.#open) this.#startSparkles();
    if (this.#reducedMotion.matches) this.#stopConfetti();
  };

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.innerHTML = `
    <style>
      :host {
        --blue: var(--ds-accent, #0371DD);
        --violet: #A278FB;
        --ultra-text: #8B5CF6;
        --ink: var(--ds-text, #1A1D21);
        --ink-2: var(--ds-text-muted, #6B7280);
        --ink-3: var(--ds-text-faint, #9CA3AF);
        --track: var(--ds-chip-muted-bg, #E5E7EB);
        --pill-bg: var(--ds-chip-muted-bg, #F1F2F3);
        --pill-bg-hover: var(--ds-surface-hover, #E8E9EB);
        --card: var(--ds-card-strong, #FFFFFF);
        --hairline: color-mix(in srgb, var(--ds-border, #E5E7EB) 88%, transparent);
        --row-hover: color-mix(in srgb, var(--ink) 5.5%, transparent);
        --row-active: color-mix(in srgb, var(--blue) 12%, transparent);
        --r-card: 18px;
        --r-row: 11px;
        --ease-out: cubic-bezier(0.32, 0.72, 0, 1);
        --ease-swap: cubic-bezier(0.2, 0, 0, 1);
        /* Critically-damped-ish settle (Apple response ~0.35, damping 1.0). */
        --spring: linear(0, 0.09 3.2%, 0.3 7.4%, 0.58 12.8%, 0.8 18.6%, 0.93 24.2%,
          0.99 30.2%, 1.02 37%, 1.015 45%, 1.005 58%, 1);
        display: inline-block;
        position: relative;
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
        -webkit-font-smoothing: antialiased;
        font-variant-numeric: tabular-nums;
        user-select: none;
        -webkit-user-select: none;
      }
      * { box-sizing: border-box; }
      button {
        font: inherit;
        border: 0;
        background: none;
        padding: 0;
        cursor: pointer;
        color: inherit;
        -webkit-tap-highlight-color: transparent;
      }
      svg { display: block; }
      .visually-hidden {
        position: absolute;
        width: 1px; height: 1px;
        overflow: hidden;
        clip-path: inset(50%);
        white-space: nowrap;
      }

      .pill {
        /* Grow with short names; cap long ones so the composer stays calm. */
        width: auto;
        max-width: 220px;
        height: 36px;
        border-radius: 999px;
        background: var(--pill-bg);
        display: inline-flex;
        align-items: center;
        gap: 6px;
        position: relative;
        padding: 0 10px 0 8px;
        transition: background-color 120ms var(--ease-out), transform 100ms ease-out;
      }
      .pill:hover { background: var(--pill-bg-hover); }
      :host([disabled]) .pill { pointer-events: none; opacity: 0.5; cursor: not-allowed; }
      /* Feedback on press, not release — Apple Response. */
      .pill:active { transform: scale(0.97); }
      .pill:focus-visible {
        outline: 2px solid var(--blue);
        outline-offset: 2px;
      }
      /* Icon + name + tier stay glued as one lead cluster. */
      .pill-lead {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
        flex: 1 1 auto;
      }
      .pill-icon {
        flex: none;
        width: 20px;
        height: 20px;
        border-radius: 6px;
        display: grid;
        place-items: center;
        overflow: hidden;
        background: color-mix(in srgb, var(--icon-color, var(--ink-2)) 12%, transparent);
        color: var(--icon-color, var(--ink-2));
      }
      .pill-icon.is-colored {
        background: color-mix(in srgb, var(--icon-color, var(--ink-2)) 10%, transparent);
        color: inherit;
      }
      .pill-icon.is-colored:has(image) {
        background: transparent;
      }
      .pill-icon svg {
        width: 16px;
        height: 16px;
        display: block;
        overflow: visible;
      }
      .pill-icon:has(image) svg {
        width: 100%;
        height: 100%;
      }
      .pill .label {
        min-width: 0;
        display: flex;
        align-items: baseline;
        gap: 5px;
        justify-content: flex-start;
        overflow: hidden;
        font-size: 14px;
        font-weight: 600;
        color: var(--ink);
        letter-spacing: -0.01em;
        white-space: nowrap;
      }
      .pill .model-name {
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
      }
      .pill .tier {
        flex: none;
        font-weight: 400;
        color: var(--ink-2);
        transition: color 220ms var(--ease-out);
      }
      .pill .tier.is-ultra { color: var(--ultra-text); }
      .pill .chev {
        flex: none;
        margin-left: auto;
        color: var(--ink-2);
        transition: rotate 200ms var(--ease-out);
      }
      .pill[aria-expanded="true"] .chev { rotate: 180deg; }

      .popover {
        position: absolute;
        bottom: calc(100% + 10px);
        left: 0;
        width: 316px;
        /* Material: thicker blur + catch-light edge (Apple materials). */
        background: color-mix(in srgb, var(--ds-card-strong, #fff) 78%, transparent);
        backdrop-filter: blur(40px) saturate(190%);
        -webkit-backdrop-filter: blur(40px) saturate(190%);
        border-radius: var(--r-card);
        box-shadow:
          inset 0 0.5px 0 rgba(255, 255, 255, 0.55),
          0 0 0 0.5px rgba(0, 0, 0, 0.08),
          0 4px 16px rgba(0, 0, 0, 0.08),
          0 22px 56px rgba(0, 0, 0, 0.22);
        /* Anchor to the pill — enter/exit along the same path. */
        transform-origin: 28px calc(100% + 18px);
        overflow: hidden;
        z-index: 10;
        display: none;
        opacity: 0;
        scale: 0.94;
        translate: 0 6px;
        transition:
          opacity 160ms cubic-bezier(0.4, 0, 1, 1),
          scale 160ms cubic-bezier(0.4, 0, 1, 1),
          translate 160ms cubic-bezier(0.4, 0, 1, 1);
      }
      .popover.is-open {
        opacity: 1;
        scale: 1;
        translate: 0 0;
        transition:
          opacity 280ms var(--spring),
          scale 320ms var(--spring),
          translate 320ms var(--spring);
      }

      .menu {
        padding: 12px 10px 10px;
        display: flex;
        flex-direction: column;
        gap: 2px;
      }

      .intensity {
        padding: 2px 6px 10px;
      }
      .intensity-top {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 10px;
        min-height: 18px;
        margin-bottom: 10px;
      }
      .intensity-title {
        font-size: 13px;
        font-weight: 600;
        line-height: 1.15;
        color: var(--ink);
        letter-spacing: -0.015em;
      }
      .intensity-meta {
        position: relative;
        min-width: 88px;
        height: 16px;
        text-align: right;
      }
      .intensity-layer {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        opacity: 0;
        translate: 0 2px;
        pointer-events: none;
        transition: opacity 160ms var(--ease-swap), translate 160ms var(--ease-swap);
      }
      .intensity-layer.is-active {
        opacity: 1;
        translate: 0 0;
      }
      .intensity-value {
        font-size: 12px;
        font-weight: 500;
        letter-spacing: -0.01em;
        color: var(--ink-2);
      }
      .intensity-value.is-ultra { color: var(--ultra-text); font-weight: 600; }
      .intensity-hint {
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.01em;
        color: var(--ink-2);
        white-space: nowrap;
      }
      .intensity-warning {
        font-size: 11px;
        font-weight: 600;
        letter-spacing: -0.01em;
        color: var(--ultra-text);
        white-space: nowrap;
      }

      .model-list {
        max-height: 228px;
        overflow-y: auto;
        overscroll-behavior: contain;
        padding: 2px 0;
        margin: 0 -2px;
        scrollbar-width: thin;
        scrollbar-color: color-mix(in srgb, var(--ink) 22%, transparent) transparent;
      }
      .model-item {
        width: 100%;
        min-height: 38px;
        border-radius: var(--r-row);
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 0 10px;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: -0.01em;
        color: var(--ink);
        text-align: left;
        transition:
          background-color 100ms var(--ease-out),
          color 100ms var(--ease-out),
          transform 100ms ease-out;
      }
      .model-item:hover { background: var(--row-hover); }
      .model-item:active { transform: scale(0.985); }
      .model-item.is-active {
        background: var(--row-active);
        color: var(--ink);
        font-weight: 600;
      }
      .model-item:focus-visible {
        outline: 2px solid var(--blue);
        outline-offset: -2px;
      }
      .model-icon {
        flex: none;
        width: 24px;
        height: 24px;
        border-radius: 6px;
        display: grid;
        place-items: center;
        overflow: hidden;
        background: color-mix(in srgb, var(--icon-color, var(--ink-2)) 14%, transparent);
        color: var(--icon-color, var(--ink-2));
      }
      .model-icon.is-colored {
        background: color-mix(in srgb, var(--icon-color, var(--ink-2)) 10%, transparent);
        color: inherit;
      }
      .model-icon.is-colored:has(image) {
        background: transparent;
      }
      .model-icon svg {
        width: 18px;
        height: 18px;
        display: block;
        overflow: visible;
      }
      .model-icon:has(image) svg {
        width: 100%;
        height: 100%;
      }
      .model-label {
        flex: 1 1 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .model-effort {
        flex: none;
        font-size: 12px;
        font-weight: 500;
        letter-spacing: -0.01em;
        color: var(--ink-2);
      }
      .model-effort.is-ultra { color: var(--ultra-text); font-weight: 600; }
      .model-check {
        flex: none;
        color: var(--blue);
        opacity: 0;
        transform: scale(0.85);
        transition: opacity 140ms var(--ease-out), transform 220ms var(--spring);
      }
      .model-item.is-active .model-check {
        opacity: 1;
        transform: scale(1);
      }

      .divider {
        height: 1px;
        background: var(--hairline);
        margin: 8px 4px;
      }

      .footer {
        padding-top: 0;
      }
      .configure-btn {
        width: 100%;
        min-height: 38px;
        border-radius: var(--r-row);
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 0 10px;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: -0.01em;
        color: var(--ink);
        transition: background-color 100ms var(--ease-out), transform 100ms ease-out;
      }
      .configure-btn:hover { background: var(--row-hover); }
      .configure-btn:active { transform: scale(0.985); }
      .configure-btn:focus-visible {
        outline: 2px solid var(--blue);
        outline-offset: -2px;
      }
      .configure-btn svg {
        flex: none;
        color: var(--ink-2);
      }

      .menu-stagger .intensity,
      .menu-stagger .model-list,
      .menu-stagger .footer {
        animation: row-in 280ms var(--ease-out) backwards;
      }
      .menu-stagger .model-list { animation-delay: 35ms; }
      .menu-stagger .footer { animation-delay: 60ms; }
      @keyframes row-in {
        from { opacity: 0; translate: 0 4px; }
        to   { opacity: 1; translate: 0 0; }
      }

      .slider {
        position: relative;
        height: 38px;
        touch-action: none;
        cursor: grab;
        outline: none;
      }
      .slider.is-dragging { cursor: grabbing; }
      .slider:focus-visible::after {
        content: "";
        position: absolute;
        inset: -3px;
        border-radius: 999px;
        border: 2px solid var(--blue);
        pointer-events: none;
      }
      .track {
        position: absolute;
        left: 0; right: 0;
        top: 50%;
        translate: 0 -50%;
        height: 28px;
        border-radius: 999px;
        background: var(--track);
        overflow: hidden;
        box-shadow: inset 0 0.5px 1px rgba(0, 0, 0, 0.06);
      }
      .ticks {
        position: absolute;
        inset: 0;
        pointer-events: none;
      }
      .tick {
        position: absolute;
        top: 50%;
        width: 4px;
        height: 4px;
        border-radius: 999px;
        background: color-mix(in srgb, var(--ink-3) 70%, transparent);
        translate: -50% -50%;
      }
      .fill {
        position: absolute;
        left: 0; top: 0; bottom: 0;
        border-radius: 999px;
        background: var(--blue);
        overflow: hidden;
        width: 50%;
      }
      .fill::after {
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(90deg, #2563EB 0%, #7C3AED 72%, #8B5CF6 100%);
        opacity: 0;
        transition: opacity 280ms var(--ease-out);
      }
      .slider.is-ultra .fill::after { opacity: 1; }
      .sparkles {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        z-index: 1;
        opacity: 0.85;
      }
      .confetti {
        position: absolute;
        left: -32px;
        top: -40px;
        pointer-events: none;
        z-index: 3;
      }
      .knob {
        position: absolute;
        top: 50%;
        width: 32px;
        height: 32px;
        border-radius: 999px;
        background: #fff;
        translate: -50% -50%;
        left: 50%;
        box-shadow:
          0 0 0 0.5px rgba(0, 0, 0, 0.04),
          0 1px 2px rgba(0, 0, 0, 0.12),
          0 3px 8px rgba(0, 0, 0, 0.14);
        transition: scale 100ms ease-out;
      }
      .knob::after {
        content: "";
        position: absolute;
        inset: 0;
        border-radius: 999px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.16);
        opacity: 0;
        transition: opacity 120ms var(--ease-out);
      }
      .slider.is-snapping .fill { transition: width 360ms var(--spring); }
      .slider.is-snapping .knob { transition: left 360ms var(--spring), scale 100ms ease-out; }
      .slider.is-dragging .knob { scale: 1.06; }
      .slider.is-dragging .knob::after { opacity: 1; }

      @media (prefers-reduced-motion: reduce) {
        .popover,
        .popover.is-open {
          transition: opacity 180ms ease !important;
          scale: 1 !important;
          translate: 0 0 !important;
        }
        .menu-stagger .intensity,
        .menu-stagger .model-list,
        .menu-stagger .footer,
        .model-check,
        .intensity-layer {
          animation: none !important;
          transition: opacity 120ms ease !important;
          filter: none !important;
          translate: 0 !important;
          transform: none !important;
        }
        .pill:active,
        .model-item:active,
        .configure-btn:active { transform: none; }
        .slider.is-dragging .knob { scale: 1; }
      }
      @media (prefers-reduced-transparency: reduce) {
        .popover {
          background: var(--ds-card-strong, #fff);
          backdrop-filter: none;
          -webkit-backdrop-filter: none;
        }
      }
      @media (prefers-contrast: more) {
        .popover {
          background: var(--ds-card-strong, #fff);
          box-shadow: 0 0 0 1px var(--ink);
        }
        .model-item.is-active {
          outline: 1px solid var(--blue);
        }
      }
    </style>

    <button class="pill" aria-haspopup="dialog" aria-expanded="false">
      <span class="pill-lead">
        <span class="pill-icon" aria-hidden="true"></span>
        <span class="label"><span class="model-name">Model</span><span class="tier">High</span></span>
      </span>
      <svg class="chev" width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M2.5 4.25 6 7.75l3.5-3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>

    <div class="popover" role="dialog" aria-label="Model settings">
      <div class="menu">
        <div class="intensity">
          <div class="intensity-top">
            <span class="intensity-title">Reasoning</span>
            <div class="intensity-meta">
              <div class="intensity-layer intensity-value-layer is-active">
                <span class="intensity-value">High</span>
              </div>
              <div class="intensity-layer intensity-hint-layer" aria-hidden="true">
                <span class="intensity-hint">Faster ←→ Smarter</span>
              </div>
              <div class="intensity-layer intensity-warning-layer" aria-hidden="true">
                <span class="intensity-warning">Uses limits faster</span>
              </div>
            </div>
          </div>
          <div class="slider" role="slider" tabindex="0"
               aria-orientation="horizontal"
               aria-label="Reasoning intensity"
               aria-describedby="slider-desc"
               aria-valuemin="0" aria-valuemax="4">
            <span class="visually-hidden" id="slider-desc">Left for faster responses, right for smarter responses.</span>
            <div class="track">
              <div class="ticks"></div>
              <div class="fill">
                <canvas class="sparkles" aria-hidden="true"></canvas>
              </div>
            </div>
            <div class="knob"></div>
            <canvas class="confetti" aria-hidden="true"></canvas>
          </div>
        </div>

        <div class="divider" role="separator"></div>
        <div class="model-list"></div>
        <div class="divider" role="separator"></div>

        <div class="footer">
          <button type="button" class="configure-btn">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 20h9" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/>
              <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5Z" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            Configure custom models
          </button>
        </div>
      </div>
    </div>
    `;
  }

  /* ======================= lifecycle ======================= */

  connectedCallback() {
    const $ = (s) => this.shadowRoot.querySelector(s);
    this.$pill = $('.pill');
    this.$tier = $('.tier');
    this.$popover = $('.popover');
    this.$menu = $('.menu');
    this.$slider = $('.slider');
    this.$track = $('.track');
    this.$ticks = $('.ticks');
    this.$fill = $('.fill');
    this.$knob = $('.knob');
    this.$canvas = $('.sparkles');
    this.$confetti = $('.confetti');
    this.$effortV = $('.intensity-value');
    this.$modelName = $('.model-name');
    this.$modelList = $('.model-list');
    this.$configureBtn = $('.configure-btn');
    this.$pillIcon = $('.pill-icon');
    this.$valueLayer = $('.intensity-value-layer');
    this.$hintLayer = $('.intensity-hint-layer');
    this.$warningLayer = $('.intensity-warning-layer');
    this.$intensityTitle = $('.intensity-title');
    this.$intensityHint = $('.intensity-hint');
    this.$intensityWarning = $('.intensity-warning');
    this.$sliderDesc = $('#slider-desc');
    this.#applyLabels();

    if (this.hasAttribute('value')) {
      this.#index = this.#clampIndex(parseInt(this.getAttribute('value'), 10));
    }
    if (this.hasAttribute('model')) {
      this.#modelId = this.getAttribute('model') || '';
    }
    this.#renderModelList();
    this.#updatePillModel();

    if (!this.#bound) {
      this.#bound = true;
      this.#buildTicks();
      this.#bind();
    }
    this.#reducedMotion.addEventListener?.('change', this.#onMotionPrefChange);
    this.#renderState({ animateTier: false });

    this.#resizeObserver = new ResizeObserver(() => {
      this.#layoutSlider();
      this.#sizeCanvas();
      if (this.#dragging) {
        this.#dragGeom = { rect: this.$track.getBoundingClientRect(), ...this.#metrics() };
      }
      if (this.#open) this.#startSparkles();
    });
    this.#resizeObserver.observe(this.$track);
  }

  disconnectedCallback() {
    this.#resizeObserver?.disconnect();
    this.#resizeObserver = null;
    this.#reducedMotion.removeEventListener?.('change', this.#onMotionPrefChange);
    document.removeEventListener('pointerdown', this.#onDocPointerDown, true);
    cancelAnimationFrame(this.#raf);
    this.#raf = 0;
    this.#stopConfetti();
    this.#snapSettleCb = null;
    clearTimeout(this.#closeTimer);
    clearTimeout(this.#snapTimer);
    this.#open = false;
    this.#dragging = false;
    this.#activePointer = null;
    this.#dragGeom = null;
    this.#dragPos = null;
    this.#hoveringSlider = false;
    this.$pill?.setAttribute('aria-expanded', 'false');
    this.$popover?.classList.remove('is-open');
    if (this.$popover) this.$popover.style.display = 'none';
    this.$slider?.classList.remove('is-dragging', 'is-snapping');
  }

  attributeChangedCallback(name, _old, val) {
    if (!this.$pill) return;
    if (name === 'value') {
      const i = this.#clampIndex(parseInt(val, 10));
      if (i !== this.#index) {
        this.#index = i;
        this.#snapSettleCb = i === 4 ? () => { if (this.#index === 4) this.#fireConfetti(); } : null;
        this.#renderState({ snap: true });
        if (i === 4 && this.#reducedMotion.matches) this.#snapSettleCb = null;
      }
    }
    if (name === 'model') {
      this.#modelId = val || '';
      this.#renderModelList();
      this.#updatePillModel();
    }
    if (name === 'disabled' && val !== null) this.#close();
  }

  get value() { return this.#index; }
  set value(v) { this.setAttribute('value', String(this.#clampIndex(v))); }
  get tier() { return this.#tiers[this.#index].key; }
  get models() { return this.#models; }
  set models(list) {
    this.#models = Array.isArray(list) ? list : [];
    this.#renderModelList();
    this.#updatePillModel();
  }
  get labels() { return this.#labels; }
  set labels(next) {
    if (!next || typeof next !== 'object') return;
    this.#labels = { ...this.#labels, ...next };
    this.#applyLabels();
  }

  #applyLabels() {
    const L = this.#labels;
    if (this.$intensityTitle) this.$intensityTitle.textContent = L.title;
    if (this.$intensityHint) this.$intensityHint.textContent = L.hint;
    if (this.$intensityWarning) this.$intensityWarning.textContent = L.warning;
    if (this.$slider) {
      this.$slider.setAttribute('aria-label', L.aria);
    }
    if (this.$sliderDesc) this.$sliderDesc.textContent = L.desc;
    if (this.$popover) this.$popover.setAttribute('aria-label', L.dialog);
    if (this.$configureBtn) {
      // Keep the pencil svg; replace only the trailing text node.
      const svg = this.$configureBtn.querySelector('svg');
      this.$configureBtn.textContent = '';
      if (svg) this.$configureBtn.appendChild(svg);
      this.$configureBtn.append(' ', L.configure);
    }
  }

  #clampIndex(v) {
    return clampEffortIndex(v);
  }

  #inferProvider(id) {
    const trimmed = String(id || '').trim();
    const sep = trimmed.indexOf('::');
    if (sep > 0) return trimmed.slice(0, sep);
    return 'deepseek';
  }

  #renderModelList() {
    if (!this.$modelList) return;
    this.$modelList.innerHTML = '';
    const effortKey = this.#tiers[this.#index].key;
    const isUltra = this.#index === 4;
    for (const m of this.#models) {
      const active = m.id === this.#modelId;
      const providerId = m.providerId || this.#inferProvider(m.id);
      const icon = resolveProviderIcon({
        providerId,
        id: m.id,
        label: m.label,
      });
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'model-item' + (active ? ' is-active' : '');

      const iconEl = document.createElement('span');
      iconEl.className = 'model-icon' + (icon.colored ? ' is-colored' : '');
      iconEl.style.setProperty('--icon-color', icon.color);
      iconEl.innerHTML = uniquifySvgIds(icon.svg);
      iconEl.setAttribute('aria-hidden', 'true');

      const labelEl = document.createElement('span');
      labelEl.className = 'model-label';
      labelEl.textContent = m.label || m.id;

      btn.appendChild(iconEl);
      btn.appendChild(labelEl);

      if (active) {
        const effortEl = document.createElement('span');
        effortEl.className = 'model-effort' + (isUltra ? ' is-ultra' : '');
        effortEl.textContent = effortKey;
        btn.appendChild(effortEl);

        const check = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        check.setAttribute('class', 'model-check');
        check.setAttribute('width', '14');
        check.setAttribute('height', '14');
        check.setAttribute('viewBox', '0 0 16 16');
        check.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', 'M3.5 8.2 6.4 11l6.1-6.4');
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', 'currentColor');
        path.setAttribute('stroke-width', '1.8');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        check.appendChild(path);
        btn.appendChild(check);
      }

      btn.addEventListener('click', () => {
        if (m.id === this.#modelId) return;
        this.#modelId = m.id;
        this.#renderModelList();
        this.#updatePillModel();
        this.dispatchEvent(new CustomEvent('change', {
          bubbles: true,
          detail: { type: 'model', id: m.id },
        }));
        this.#close();
      });
      this.$modelList.appendChild(btn);
    }
  }

  #updatePillModel() {
    const m = this.#models.find((x) => x.id === this.#modelId);
    if (this.$modelName) this.$modelName.textContent = m ? (m.label || m.id) : 'Model';
    if (this.$pillIcon) {
      const icon = resolveProviderIcon({
        providerId: m?.providerId || this.#inferProvider(this.#modelId),
        id: this.#modelId || m?.id,
        label: m?.label,
      });
      this.$pillIcon.className = 'pill-icon' + (icon.colored ? ' is-colored' : '');
      this.$pillIcon.style.setProperty('--icon-color', icon.color);
      this.$pillIcon.innerHTML = uniquifySvgIds(icon.svg);
    }
  }

  /* ======================= events ======================= */

  #bind() {
    this.$pill.addEventListener('click', () => {
      if (this.hasAttribute('disabled')) return;
      this.#open ? this.#close() : this.#openPopover();
    });
    this.$configureBtn.addEventListener('click', () => {
      this.dispatchEvent(new CustomEvent('change', {
        bubbles: true,
        detail: { type: 'configure-models' },
      }));
      this.#close();
    });

    this.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.#open) {
        e.stopPropagation();
        this.#close();
        this.$pill.focus();
      }
    });

    this.$slider.addEventListener('pointerenter', () => { this.#hoveringSlider = true; this.#syncIntensityMeta(); });
    this.$slider.addEventListener('pointerleave', () => { this.#hoveringSlider = false; this.#syncIntensityMeta(); });

    this.$slider.addEventListener('pointerdown', (e) => {
      if (this.#activePointer !== null) return;
      this.#activePointer = e.pointerId;
      e.preventDefault();
      this.$slider.focus({ preventScroll: true });
      try { this.$slider.setPointerCapture(e.pointerId); } catch {}
      this.#dragging = true;
      this.#burstFiredThisGesture = false;
      this.#dragGeom = { rect: this.$track.getBoundingClientRect(), ...this.#metrics() };
      this.$slider.classList.add('is-dragging');
      this.#stopSnap();
      this.#dragTo(e);
    });
    this.$slider.addEventListener('pointermove', (e) => {
      if (this.#dragging && e.pointerId === this.#activePointer) this.#dragTo(e);
    });
    const release = (e) => {
      if (!this.#dragging || e.pointerId !== this.#activePointer) return;
      this.#dragging = false;
      this.#activePointer = null;
      this.#dragGeom = null;
      this.$slider.classList.remove('is-dragging');
      const pos = this.#dragPos ?? this.#index / 4;
      this.#dragPos = null;
      const target = Math.round(pos * 4);
      const celebrate = target === 4 && !this.#burstFiredThisGesture;
      if (celebrate) this.#burstFiredThisGesture = true;
      const farFromStop = Math.abs(pos * 4 - target) * (this.#metrics().span / 4) > 2;
      if (celebrate && farFromStop) {
        this.#snapSettleCb = () => { if (this.#index === 4) this.#fireConfetti(); };
      }
      this.#commit(target, { snap: true });
      if (celebrate && !farFromStop) this.#fireConfetti();
    };
    this.$slider.addEventListener('pointerup', release);
    this.$slider.addEventListener('pointercancel', release);

    this.$slider.addEventListener('keydown', (e) => {
      const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
      if (step !== undefined) {
        e.preventDefault();
        this.#commit(this.#index + step, { snap: false });
      } else if (e.key === 'Home') { e.preventDefault(); this.#commit(0, { snap: false }); }
      else if (e.key === 'End')   { e.preventDefault(); this.#commit(4, { snap: false }); }
    });

    this.$menu.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      e.preventDefault();
      const items = [...this.$menu.querySelectorAll('button, [role="slider"]')];
      const i = items.indexOf(this.shadowRoot.activeElement);
      const next = items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length];
      next.focus();
    });
  }

  /* ======================= popover open/close ======================= */

  #openPopover() {
    this.#open = true;
    this.$pill.setAttribute('aria-expanded', 'true');
    const pop = this.$popover;
    const hostLeft = this.getBoundingClientRect().left;
    const pillLeft = this.$pill.getBoundingClientRect().left;
    pop.style.left = (pillLeft - hostLeft) + 'px';
    pop.style.width = '300px';
    pop.style.display = 'block';
    this.$menu.classList.add('menu-stagger');
    requestAnimationFrame(() => pop.classList.add('is-open'));
    document.addEventListener('pointerdown', this.#onDocPointerDown, true);
    this.#layoutSlider();
    this.#sizeCanvas();
    this.#startSparkles();
    const firstModel = this.$modelList.querySelector('.model-item');
    (firstModel || this.$configureBtn).focus({ preventScroll: true });
  }

  #close() {
    if (!this.#open) return;
    this.#open = false;
    this.$pill.setAttribute('aria-expanded', 'false');
    const active = this.shadowRoot.activeElement;
    if (active && this.$popover.contains(active)) this.$pill.focus();
    const pop = this.$popover;
    pop.classList.remove('is-open');
    this.$menu.classList.remove('menu-stagger');
    document.removeEventListener('pointerdown', this.#onDocPointerDown, true);
    cancelAnimationFrame(this.#raf);
    this.#raf = 0;
    this.#stopConfetti();
    const hide = () => {
      pop.removeEventListener('transitionend', onEnd);
      clearTimeout(this.#closeTimer);
      if (!this.#open) pop.style.display = 'none';
    };
    const onEnd = (e) => {
      if (e.target !== pop || e.propertyName !== 'opacity') return;
      hide();
    };
    pop.addEventListener('transitionend', onEnd);
    this.#closeTimer = setTimeout(hide, 240);
  }

  /* ======================= slider ======================= */

  #buildTicks() {
    for (let i = 0; i < 5; i++) {
      const dot = document.createElement('div');
      dot.className = 'tick';
      this.$ticks.appendChild(dot);
    }
  }

  #metrics() {
    const w = this.$track.clientWidth;
    const K = 34;
    const min = K / 2;
    const max = w - K / 2;
    return { w, K, min, max, span: max - min };
  }

  #layoutSlider() {
    const { min, span } = this.#metrics();
    if (span <= 0) return;
    const dots = this.$ticks.children;
    for (let i = 0; i < dots.length; i++) {
      dots[i].style.left = (min + (i / 4) * span) + 'px';
    }
    this.#positionKnob(this.#dragPos ?? this.#index / 4);
  }

  #positionKnob(pos) {
    const { min, span, K } = this.#metrics();
    if (span <= 0) return;
    const cx = min + pos * span;
    this.$knob.style.left = cx + 'px';
    this.$fill.style.width = (cx + K / 2) + 'px';
  }

  #stopSnap() {
    if (this.$slider.classList.contains('is-snapping')) {
      this.$knob.style.left = getComputedStyle(this.$knob).left;
      this.$fill.style.width = getComputedStyle(this.$fill).width;
      this.$slider.classList.remove('is-snapping');
    }
    this.#snapSettleCb = null;
    clearTimeout(this.#snapTimer);
  }

  #dragTo(e) {
    if (this.$slider.classList.contains('is-snapping')) this.#stopSnap();
    const { rect, w, K } = this.#dragGeom ?? { rect: this.$track.getBoundingClientRect(), ...this.#metrics() };
    if (!rect.width || w <= K) return;
    const frac = (e.clientX - rect.left) / rect.width;
    const pos = Math.min(1, Math.max(0, (frac * w - K / 2) / (w - K)));
    this.#dragPos = pos;
    this.#positionKnob(pos);
    const nearest = Math.round(pos * 4);
    if (nearest !== this.#index) {
      this.#index = nearest;
      this.#renderState({ position: false });
      this.#emit();
    }
  }

  #beginSnap() {
    const settle = this.#snapSettleCb;
    this.#snapSettleCb = null;
    if (this.#reducedMotion.matches) return;
    if (this.#dragging) return;
    this.$slider.classList.add('is-snapping');
    const clear = () => {
      this.$slider.classList.remove('is-snapping');
      this.$knob.removeEventListener('transitionend', onEnd);
      clearTimeout(this.#snapTimer);
      settle?.();
    };
    const onEnd = (e) => { if (e.propertyName === 'left') clear(); };
    this.$knob.addEventListener('transitionend', onEnd);
    clearTimeout(this.#snapTimer);
    this.#snapTimer = setTimeout(clear, 460);
  }

  #commit(i, { snap }) {
    i = this.#clampIndex(i);
    const changed = i !== this.#index;
    this.#index = i;
    if (snap) this.#beginSnap();
    this.#renderState();
    if (changed) this.#emit();
    if (changed && i === 4 && !snap) this.#fireConfetti();
  }

  #renderState({ position = true, animateTier = true, snap = false } = {}) {
    const t = this.#tiers[this.#index];
    const isUltra = this.#index === 4;

    if (position) {
      if (snap) this.#beginSnap();
      this.#positionKnob(this.#index / 4);
    }
    this.$slider.classList.toggle('is-ultra', isUltra);
    this.$slider.setAttribute('aria-valuenow', String(this.#index));
    this.$slider.setAttribute('aria-valuetext', t.valuetext);

    if (this.$tier.textContent !== t.key) {
      this.#swapText(this.$tier, t.key, animateTier);
    }
    this.$tier.classList.toggle('is-ultra', isUltra);

    if (this.$effortV.textContent !== t.key) {
      this.#swapText(this.$effortV, t.key, animateTier);
    }
    this.$effortV.classList.toggle('is-ultra', isUltra);

    // keep selected-row badge in sync without rebuilding the list (preserves scroll)
    const badge = this.$modelList?.querySelector('.model-item.is-active .model-effort');
    if (badge) {
      badge.textContent = t.key;
      badge.classList.toggle('is-ultra', isUltra);
    }
    this.#syncIntensityMeta();
  }

  #swapText(el, text, animate) {
    el.textContent = text;
    if (!animate || this.#reducedMotion.matches || !el.animate) return;
    el.getAnimations().forEach(a => a.cancel());
    el.animate(
      [{ opacity: 0, transform: 'translateY(3px)' }, { opacity: 1, transform: 'translateY(0)' }],
      { duration: 130, easing: 'cubic-bezier(0.32, 0.72, 0, 1)' }
    );
  }

  #syncIntensityMeta() {
    const isUltra = this.#index === 4;
    const showHint = !isUltra && (this.#hoveringSlider || this.#dragging);
    const states = [
      [this.$warningLayer, isUltra],
      [this.$hintLayer, showHint],
      [this.$valueLayer, !isUltra && !showHint],
    ];
    for (const [layer, active] of states) {
      if (!layer) continue;
      layer.classList.toggle('is-active', active);
      layer.setAttribute('aria-hidden', String(!active));
    }
  }

  #emit() {
    this.dispatchEvent(new CustomEvent('change', {
      bubbles: true,
      detail: { type: 'effort', index: this.#index, tier: this.tier },
    }));
  }

  /* ======================= confetti burst (Ultra) ======================= */

  #fireConfetti() {
    if (this.#reducedMotion.matches || !this.#open) return;
    const now = performance.now();
    if (now - this.#lastBurst < 350) return;
    this.#lastBurst = now;

    const MX = 32, MY = 40;
    const sw = this.$slider.offsetWidth, sh = this.$slider.offsetHeight;
    if (!sw) return;
    const dpr = Math.min(2, devicePixelRatio || 1);
    const w = sw + MX * 2, h = sh + MY * 2;
    if (!this.#confettiBox || this.#confettiBox.w !== w || this.#confettiBox.h !== h || this.#confettiBox.dpr !== dpr) {
      this.$confetti.width = w * dpr;
      this.$confetti.height = h * dpr;
      this.$confetti.style.width = w + 'px';
      this.$confetti.style.height = h + 'px';
      this.#confettiBox = { w, h, dpr };
    }

    const cx = (parseFloat(getComputedStyle(this.$knob).left) || sw / 2) + MX;
    const cy = sh / 2 + MY;
    const COLORS = ['#C9B0F0', '#BFA5F2', '#D4C3F7', '#B79EF5'];
    const R = 17;
    const N = 14;
    for (let i = 0; i < N; i++) {
      const ang = (i / N) * Math.PI * 2 + (Math.random() - 0.5) * 0.35;
      const sp = 105 + Math.random() * 45;
      this.#confettiParts.push({
        x: cx + Math.cos(ang) * R,
        y: cy + Math.sin(ang) * R,
        vx: Math.cos(ang) * sp,
        vy: Math.sin(ang) * sp - 25,
        size: 4.5 + Math.random() * 1,
        life: 0,
        ttl: 0.2 + Math.random() * 0.08,
        color: COLORS[i % COLORS.length],
      });
    }
    if (!this.#confettiRaf) {
      this.#confettiLast = now;
      this.#confettiRaf = requestAnimationFrame(this.#confettiTick);
    }
    if (!this.#dragging && this.$knob.animate) {
      this.$knob.animate(
        [{ scale: '1' }, { scale: '1.05' }, { scale: '1' }],
        { duration: 180, easing: 'cubic-bezier(0.32, 0.72, 0, 1)' }
      );
    }
  }

  #confettiTick = (t) => {
    const dt = Math.min(0.032, Math.max(0, (t - this.#confettiLast) / 1000));
    this.#confettiLast = t;
    const box = this.#confettiBox;
    const ctx = this.$confetti.getContext('2d');
    if (!box) { this.#confettiRaf = 0; return; }
    ctx.setTransform(box.dpr, 0, 0, box.dpr, 0, 0);
    ctx.clearRect(0, 0, box.w, box.h);

    this.#confettiParts = this.#confettiParts.filter((p) => {
      p.life += dt;
      if (p.life >= p.ttl) return false;
      const damp = Math.exp(-6 * dt);
      p.vx *= damp;
      p.vy = p.vy * damp - 20 * dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      const k = p.life / p.ttl;
      ctx.globalAlpha = Math.pow(1 - k, 1.5);
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size / 2, 0, Math.PI * 2);
      ctx.fill();
      return true;
    });
    ctx.globalAlpha = 1;

    if (this.#confettiParts.length) {
      this.#confettiRaf = requestAnimationFrame(this.#confettiTick);
    } else {
      this.#confettiRaf = 0;
      ctx.clearRect(0, 0, box.w, box.h);
    }
  };

  #stopConfetti() {
    cancelAnimationFrame(this.#confettiRaf);
    this.#confettiRaf = 0;
    this.#confettiParts = [];
    if (this.#confettiBox) {
      const ctx = this.$confetti.getContext('2d');
      ctx.setTransform(this.#confettiBox.dpr, 0, 0, this.#confettiBox.dpr, 0, 0);
      ctx.clearRect(0, 0, this.#confettiBox.w, this.#confettiBox.h);
    }
  }

  /* ======================= sparkles (Canvas 2D) ======================= */

  #sizeCanvas() {
    const dpr = Math.min(2, devicePixelRatio || 1);
    const w = this.$track.clientWidth;
    const h = this.$track.clientHeight;
    if (!w || !h) return;
    const b = this.#sparkBox;
    if (b && b.w === w && b.h === h && b.dpr === dpr) return;
    this.$canvas.width = w * dpr;
    this.$canvas.height = h * dpr;
    this.$canvas.style.width = w + 'px';
    this.$canvas.style.height = h + 'px';
    this.#sparkBox = { w, h, dpr };
    this.#seedParticles(w, h);
  }

  #seedParticles(w, h) {
    const count = Math.max(6, Math.round(w / 24));
    this.#particles = Array.from({ length: count }, () => ({
      x: Math.random() * w,
      y: 4 + Math.random() * (h - 8),
      r: 0.8 + Math.random() * 0.9,
      phase: Math.random() * Math.PI * 2,
      twinkle: 2.5 + Math.random() * 4.5,
      flow: 85 + Math.random() * 50,
    }));
  }

  #startSparkles() {
    cancelAnimationFrame(this.#raf);
    this.#raf = 0;
    if (this.#reducedMotion.matches) {
      this.#drawSparkles(performance.now(), true);
      return;
    }
    this.#sparkLast = performance.now();
    const loop = (t) => {
      this.#drawSparkles(t);
      this.#raf = requestAnimationFrame(loop);
    };
    this.#raf = requestAnimationFrame(loop);
  }

  #drawSparkles(t, staticFrame = false) {
    if (!this.#sparkBox) return;
    const ctx = this.$canvas.getContext('2d');
    const { w, h, dpr } = this.#sparkBox;
    const dt = staticFrame ? 0 : Math.min(0.032, Math.max(0, (t - this.#sparkLast) / 1000));
    this.#sparkLast = t;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#fff';
    const sec = t / 1000;
    for (const p of this.#particles) {
      p.x -= p.flow * dt;
      if (p.x < -3) p.x += w + 6;
      const s = 0.5 + 0.5 * Math.sin(staticFrame ? p.phase * 3 : sec * p.twinkle + p.phase);
      ctx.globalAlpha = 0.06 + 0.74 * s * s;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
}

if (!customElements.get('reasoning-effort-selector')) {
  customElements.define('reasoning-effort-selector', ChatGPTModelSelector);
}
