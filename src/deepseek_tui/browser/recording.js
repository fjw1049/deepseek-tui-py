// Workbench event capture; Octop still owns binding validation, storage and redaction.
(() => {
  const config = globalThis.__HBR_RECORDER_CONFIG__;
  if (!config?.bindingName || (window !== window.top && !config.framePath?.length)) return;
  const previous = globalThis.__deepseekRecorder;
  if (previous?.config.recordingId === config.recordingId) {
    Object.assign(previous.config, config);
    return;
  }
  previous?.dispose();
  const visible = __VISIBLE__, readText = __READ_TEXT__;
  const pending = new Map(), scrolled = new Map(), revisions = new WeakMap(), emitted = new WeakMap();
  const roots = new WeakSet(), seen = new WeakSet(), removals = [], observers = [];
  let sequence = 0, stopped = false, scrollingUntil = 0, pressed = null, vanished = false;
  const editable = e => e?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(e?.tagName);
  const fullName=__NAME__, role=__ROLE__, context=__SCOPE_CONTEXT__;
  const name=e=>Array.from(fullName(e)).slice(0,300).join('');
  const controls='button,input,textarea,select,a[href],summary,[contenteditable],' +
    ['button','link','textbox','combobox','checkbox','radio','menuitem','option','switch','tab',
     'searchbox'].map(r=>'[role='+r+']').join(',');
  const pointer=e=>/^(pointer|grab)$/.test(getComputedStyle(e).cursor);
  const pageRoot=e=>/^(HTML|BODY)$/.test(e.tagName);
  // The signals observation lists a script-bound control by, so replay finds this target.
  const clickable=e=>!pageRoot(e) && (pointer(e) || e.hasAttribute('onclick') ||
    e.hasAttribute('tabindex') && e.tabIndex>=0);
  // Observation lists a card as its outermost pointer element, not the span under the mouse.
  function outermost(e) {
    if(e.matches(controls) || !pointer(e)) return e;
    while(e.parentElement && !pageRoot(e.parentElement) && pointer(e.parentElement)) e=e.parentElement;
    return e;
  }
  // Replay clicks the listed element here; an icon on a card is not the card's centre.
  function pressTarget(e,event) {
    const element=outermost(e), r=element.getBoundingClientRect();
    return {...describe(element),hit:element===e || !event.detail || !r.width || !r.height ? undefined
      : {x:(event.clientX-r.x)/r.width,y:(event.clientY-r.y)/r.height}};
  }
  // The browser follows a click on label text with its own click on the labelled control.
  const forwarded=e=>!!e.closest('label')?.control && !e.matches(controls);
  function selectors(e) {
    const out=[];
    for (const attr of ['data-testid','data-test','data-cy','id','name','aria-label']) {
      const value=e.getAttribute(attr);
      if(value) out.push('['+attr+'="'+CSS.escape(value)+'"]');
    }
    const parts=[];
    for(let p=e;p;p=p.parentElement) {
      const tag=p.tagName.toLowerCase();
      if(p.id && p.getRootNode().querySelectorAll('#'+CSS.escape(p.id)).length===1) {
        parts.unshift(tag+'#'+CSS.escape(p.id)); break;
      }
      let n=1;
      for(let s=p.previousElementSibling;s;s=s.previousElementSibling)
        if(s.tagName===p.tagName) n++;
      parts.unshift(tag+':nth-of-type('+n+')');
    }
    out.push(parts.join(' > '));
    return [...new Set(out)];
  }
  function shadowPath(e) {
    const path=[];
    for(let root=e.getRootNode();root.host;root=root.host.getRootNode())
      path.unshift(selectors(root.host).at(-1));
    return path;
  }
  function describeScroller(e) {
    return {tag:e.tagName.toLowerCase(), id:e.id, selectorCandidates:selectors(e),
      framePath:config.framePath || [], shadowPath:shadowPath(e),
      frameUrl:config.framePath?.length?location.href:undefined};
  }
  function describe(e) {
    const r=e.getBoundingClientRect();
    const scope=context(e);
    return {tag:e.tagName.toLowerCase(), role:role(e), name:name(e), accessibleName:name(e),
      text:editable(e)?'':readText(e).slice(0,500),
      label:Array.from(e.labels || []).map(readText).join(' ').slice(0,300),
      placeholder:e.getAttribute('placeholder') || '', id:e.id,
      nameAttr:e.getAttribute('name') || '',
      type:e.tagName==='INPUT'?e.type:(e.getAttribute('type') || ''),
      selectorCandidates:selectors(e), framePath:config.framePath || [],
      frameUrl:config.framePath?.length?location.href:undefined,
      shadowPath:shadowPath(e), bbox:{x:r.x,y:r.y,width:r.width,height:r.height},
      scope:scope?{tag:scope.tag,id:scope.id.length<=300?scope.id:undefined,
        keys:scope.keys.filter(([k,v])=>v!==null && v.length<=300),
        text:Array.from(scope.text).slice(0,500).join(''),
        truncated:Array.from(scope.text).length>500 || scope.keys.some(([k,v])=>v?.length>300)}:undefined,
      visible:visible(e), enabled:!e.disabled, isContentEditable:e.isContentEditable,
      clickable:clickable(e)};
  }
  function emit(kind, data={}) {
    if(stopped) return;
    const page=config.framePath?.length ? config.page : {url:location.href,title:document.title};
    globalThis[config.bindingName]?.(JSON.stringify({nonce:config.nonce, schemaVersion:'1.0',
      event:{kind,localSeq:++sequence,ts:new Date().toISOString(),targetId:config.targetId,
        page:{...page,targetId:config.targetId},...data}}));
  }
  function target(event) {
    const node=event.composedPath().find(n=>n.nodeType===1);
    if(!node) return null;
    return node.closest(controls) || node;
  }
  function flush(e) {
    const timer=pending.get(e);
    if(timer) clearTimeout(timer);
    pending.delete(e);
    if(!e.isConnected) {emit('capture_warning',{error:'Pending input target detached before flush'});return;}
    const value=e.type==='checkbox' || e.type==='radio' ? e.checked
      : e.isContentEditable ? e.innerText : e.value;
    let revision=revisions.get(e) || 0;
    const last=emitted.get(e);
    if(last?.revision===revision && last.value===value) return;
    if(last?.revision===revision) revisions.set(e,++revision);
    emitted.set(e,{revision,value});
    emit('input',{target:describe(e),value:'{{sensitive_value}}',redacted:true,
      inputRevision:revision,checked:typeof e.checked==='boolean'?e.checked:undefined});
  }
  function flushScroll(e) {
    clearTimeout(scrolled.get(e));
    scrolled.delete(e);
    if(e.isConnected) emit('scroll',{target:describeScroller(e),scroll:{x:e.scrollLeft,y:e.scrollTop}});
  }
  const flushAll = () => {
    Array.from(scrolled.keys()).forEach(flushScroll);
    Array.from(pending.keys()).forEach(flush);
  };
  function handle(event) {
    if(stopped) return;
    // Scroll events look alike from any source; carousels and scripts are not the user.
    if(event.type==='wheel') { if(event.isTrusted) scrollingUntil=Date.now()+1000; return; }
    if(seen.has(event)) return;
    if(/^(click|keydown|pointerdown|mouseup)$/.test(event.type) && !event.isTrusted) return;
    seen.add(event);
    const e=target(event);
    if((event.type==='input' || event.type==='change') && e && !editable(e) && event.isTrusted) {
      emit('capture_warning',{error:'Input target is unavailable for scoped recording'});return;
    }
    // Styled checkboxes and file pickers hide the control the user is still operating.
    const operated=e && (visible(e) || event.isTrusted && /^(checkbox|radio|file)$/.test(e.type));
    if((event.type==='input' || event.type==='change') && !operated) return;
    if(event.type==='input' && e && editable(e)) {
      revisions.set(e,(revisions.get(e) || 0)+1);
      clearTimeout(pending.get(e));
      pending.set(e,setTimeout(()=>flush(e),300)); return;
    }
    if(event.type==='change' && e && editable(e)) { flush(e); return; }
    if(event.type==='pointerdown') {
      pressed=e && event.button===0 ? {element:outermost(e),target:pressTarget(e,event)} : null;
      vanished=false;
    } else if(event.type==='mouseup') {
      // A menu that acts on mousedown removes its item, so no click ever reaches it.
      if(pressed && !visible(pressed.element)) {
        flushAll();
        emit('click',{target:pressed.target,detail:1});
        vanished=true;
      }
      pressed=null;
    } else if(event.type==='click') {
      flushAll();
      if(vanished) vanished=false;
      else if(e && e.tagName!=='LABEL' && !forwarded(e))
        emit('click',{target:pressTarget(e,event),detail:event.detail});
    } else if(event.type==='keydown') {
      flushAll();
      if(/^( |PageUp|PageDown|Home|End|ArrowUp|ArrowDown|ArrowLeft|ArrowRight)$/.test(event.key)
         && !editable(e)) scrollingUntil=Date.now()+1000;
      // Enter only confirms the candidate while an input method is composing.
      if(e && !event.isComposing &&
         /^(Enter|Tab|Escape|ArrowUp|ArrowDown|ArrowLeft|ArrowRight)$/.test(event.key)) {
        const parts=[];
        if(event.ctrlKey) parts.push('Ctrl'); if(event.metaKey) parts.push('Meta');
        if(event.altKey) parts.push('Alt'); if(event.shiftKey) parts.push('Shift');
        parts.push(event.key); emit('keydown',{key:parts.join('+'),target:describe(e)});
      }
    } else if(event.type==='submit') { flushAll(); }
    else if(event.type==='scroll' && Date.now()<=scrollingUntil) {
      const scroller=event.target.nodeType===9 ? event.target.scrollingElement : event.target;
      if(!scroller || editable(scroller)) return;
      clearTimeout(scrolled.get(scroller));
      scrolled.set(scroller,setTimeout(()=>flushScroll(scroller),250));
    }
  }
  function listen(root,type,callback,options=true) {
    root.addEventListener(type,callback,options);
    removals.push(()=>root.removeEventListener(type,callback,options));
  }
  function watch(root) {
    if(roots.has(root)) return;
    roots.add(root);
    for(const type of ['click','input','change','keydown','submit','scroll','pointerdown','mouseup'])
      listen(root,type,handle);
    listen(root,'wheel',handle,{capture:true,passive:true});
    const observer=new MutationObserver(changes=>changes.forEach(c=>c.addedNodes.forEach(scan)));
    observer.observe(root,{subtree:true,childList:true}); observers.push(observer); scan(root);
  }
  function scan(node) {
    if(node.nodeType!==1 && node.nodeType!==11 && node.nodeType!==9) return;
    for(const e of [...(node.nodeType===1?[node]:[]),...node.querySelectorAll('*')])
      if(e.shadowRoot) watch(e.shadowRoot);
  }
  // This runs in an isolated world: page-world prototypes and history are out of
  // reach, so shadow roots come from scans and same-document navigation from CDP.
  if(window===window.top) listen(window,'popstate',flushAll);
  listen(window,'pagehide',flushAll);
  listen(window,'beforeunload',flushAll);
  globalThis.__deepseekRecorder={config,flush:flushAll,refresh:()=>scan(document),dispose(){
    if(stopped) return;
    flushAll(); stopped=true;
    removals.forEach(remove=>remove()); observers.forEach(observer=>observer.disconnect());
    globalThis.__deepseekRecorder=null;
  }};
  watch(document);
  if(window===window.top) emit('recorder_installed');
})();
