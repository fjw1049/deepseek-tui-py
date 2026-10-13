"""Visible page observations and observation-bound targets over the existing CDP session."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

# Keep element handles in a controlled world, never in the webpage's main world.
# No input values are included: passwords and user-entered form contents are not evidence.
VISIBLE = r"""e => {
    if (!e.isConnected || e.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
    for (let p=e; p; p=p.parentElement || p.getRootNode()?.host) {
      if (p.matches('[hidden],[inert],[aria-hidden="true"]')) return false;
      const s=window.getComputedStyle.call(p.ownerDocument.defaultView,p);
      if (s.display==='none' || s.visibility==='hidden' || Number(s.opacity)===0) return false;
    }
    return !!e.getClientRects().length;
  }"""

READ_TEXT = r"""root => {
  if (!root) return '';
  const texts=[], visible=__VISIBLE__;
  const walker=(root.ownerDocument || document).createTreeWalker(root,NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n=walker.currentNode, p=n.parentElement;
    if (!p || !visible(p) || p.closest('script,style,noscript,input,textarea')) continue;
    let editable=false;
    for (let e=p; e; e=e.parentElement || e.getRootNode()?.host) {
      if (e.isContentEditable) { editable=true; break; }
    }
    if (!editable && n.textContent.trim()) texts.push(n.textContent.trim());
  }
  return texts.join('\n').trim();
}""".replace("__VISIBLE__", VISIBLE)

LABEL_TEXT = r"""root => {
  if(!root)return '';
  const visible=__VISIBLE__, hiddenRoot=!visible(root);
  const texts=[], walker=root.ownerDocument.createTreeWalker(root,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()) {
    const n=walker.currentNode,p=n.parentElement;
    if(!p || (!hiddenRoot && !visible(p)) || p.closest('script,style,noscript,input,textarea'))continue;
    let editable=false;
    for(let e=p;e;e=e.parentElement || e.getRootNode()?.host)
      if(e.isContentEditable){editable=true;break;}
    if(!editable && n.textContent.trim())texts.push(n.textContent.trim());
  }
  return texts.join(' ').trim();
}""".replace("__VISIBLE__", VISIBLE)

ACCESSIBLE_NAME = r"""e => {
  const read=__READ_TEXT__, label=__LABEL_TEXT__;
  const references=(e.getAttribute('aria-labelledby') || '').split(/\s+/)
    .map(k=>label(e.getRootNode().getElementById?.(k))).join(' ').trim();
  const buttonValue=e.tagName==='INPUT' && /^(button|submit|reset)$/.test(e.type)?e.value:'';
  return (references || e.getAttribute('aria-label') ||
    Array.from(e.labels || []).map(read).join(' ') || read(e) ||
    e.getAttribute('alt') || buttonValue || e.getAttribute('title') ||
    e.getAttribute('placeholder') || '').trim();
}""".replace("__READ_TEXT__", READ_TEXT).replace("__LABEL_TEXT__", LABEL_TEXT)

CANONICAL_ROLE = r"""e => e.getAttribute('role') || ({BUTTON:'button', A:'link',
  TEXTAREA:'textbox', SELECT:e.multiple?'listbox':'combobox', SUMMARY:'button'}[e.tagName]) ||
  (e.tagName==='INPUT'?({checkbox:'checkbox',radio:'radio',range:'slider',number:'spinbutton',
    submit:'button',reset:'button',button:'button',image:'button',file:'button',color:'button'}[e.type]
    || 'textbox'):e.isContentEditable?'textbox':e.tagName.toLowerCase())"""

SCOPE_CONTEXT = r"""e => {
  const attrs=['data-record','data-record-id','data-row-key','data-id','data-account-id','data-recipient','data-resource'];
  let container=null;
  for(let p=e.parentElement || e.getRootNode()?.host;p;p=p.parentElement || p.getRootNode()?.host) {
    if(p.matches(attrs.map(a=>'['+a+']').join(',')+
      ',tr,[role=row],li,[role=listitem],article,section,form,[role=dialog],[role=region]')) {
      container=p;break;
    }
  }
  if(!container) return null;
  const visible=__VISIBLE__, texts=[];
  const walker=container.ownerDocument.createTreeWalker(container,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()) {
    const n=walker.currentNode, p=n.parentElement;
    if(!p || !visible(p) || p.closest('script,style,noscript,input,textarea,select,button,time,[role=timer]'))
      continue;
    let editable=false;
    for(let a=p;a;a=a.parentElement || a.getRootNode()?.host)
      if(a.isContentEditable){editable=true;break;}
    if(!editable && n.textContent.trim()) texts.push(n.textContent.trim());
  }
  return {node:container,keys:attrs.map(a=>[a,container.getAttribute(a)]),
    text:texts.join('\n'),id:container.id,tag:container.tagName.toLowerCase()};
}""".replace("__VISIBLE__", VISIBLE)

COLLECT = (
    r"""({id, selector, limit, textOffset=0, elementOffset=0, optionOffset=0,
               shadowPath=[],continuation=null}) => {
  const previous=window.__deepseekObservation;
  const revision=window.__deepseekPageRevision || {value:0};
  revision.observer?.disconnect();
  revision.observer=new MutationObserver(changes=>{
    if (changes.some(c=>c.attributeName!=='data-deepseek-target')) revision.value++;
  });
  window.__deepseekPageRevision=revision;
  const watched=new WeakSet();
  const watch=root=>{
    if (!watched.has(root)) {
      watched.add(root);
      revision.observer.observe(root,
        {subtree:true,childList:true,characterData:true,attributes:true});
    }
  };
  watch(document);
  const refs = new Map(), warnings = [], texts = [], scrolls=[];
  const identities=window.__deepseekNodeIdentities || {nodes:new WeakMap(),prefix:id,next:0};
  window.__deepseekNodeIdentities=identities;
  const visible = __VISIBLE__;
  const readText = __READ_TEXT__;
  const context = __SCOPE_CONTEXT__;
  const name=__NAME__, canonicalRole=__ROLE__;
  const elements=[], frames=[],snapshot=[];
  let elementCount=0;
  const focused=()=>{
    let e=document.activeElement;
    while(e?.shadowRoot?.activeElement || e?.contentDocument?.activeElement) {
      e=e.shadowRoot?.activeElement || e.contentDocument.activeElement;
    }
    return e;
  };
  let scopeRoot=document;
  for(const hostSelector of shadowPath) {
    const hosts=scopeRoot.querySelectorAll(hostSelector);
    if(hosts.length!==1 || !hosts[0].shadowRoot)
      throw Error('Shadow path must match unique hosts with open shadow roots');
    scopeRoot=hosts[0].shadowRoot;
  }
  let roots = selector ? Array.from(scopeRoot.querySelectorAll(selector))
    : [scopeRoot===document?document.body:scopeRoot];
  if (selector && roots.length!==1)
    throw Error('Observation selector must match exactly one element');
  const walk = root => {
    if (!root) return;
    watch(root.getRootNode());
    texts.push(readText(root));
    const view=(root.ownerDocument || document).defaultView;
    scrolls.push({node:view, x:view.scrollX, y:view.scrollY, window:true});
    for (const e of [...(root.nodeType===1?[root]:[]),...root.querySelectorAll('*')]) {
      if (!visible(e)) continue;
      scrolls.push({node:e, x:e.scrollLeft, y:e.scrollTop});
      const tag=e.tagName.toLowerCase(), role=canonicalRole(e);
      if (e.matches('button,input:not([type=hidden]),select,textarea,a[href],summary') ||
          (e.isContentEditable && !e.parentElement?.isContentEditable) ||
          /^(button|link|textbox|combobox|checkbox|radio|menuitem|option|switch|tab|searchbox)$/
          .test(role)) {
        const index=elementCount++, ref='e'+index, scope=context(e);
        if(!identities.nodes.has(e))identities.nodes.set(e,identities.prefix+':n'+identities.next++);
        const targetId=identities.nodes.get(e);
        snapshot.push({element:e,name:name(e),scope,options:tag==='select'?
          Array.from(e.options).map(o=>({node:o,value:o.value,text:o.text})):[]});
        if (index>=elementOffset && elements.length<limit) {
          const r=e.getBoundingClientRect();
          const options=new Map();
          if(tag==='select')Array.from(e.options).slice(optionOffset,optionOffset+50).forEach((o,i)=>
            options.set(ref+':o'+(optionOffset+i),{node:o,value:o.value,text:o.text}));
          refs.set(ref, {element:e, target_id:targetId, name:name(e), role, options, parent:e.parentElement, scope,
            href:e.tagName==='A'?e.href:null,formAction:e.form?.action || null,
            box:[r.x,r.y,r.width,r.height]});
          elements.push({ref, target_id:targetId, role, tag, name:Array.from(name(e)).slice(0,300).join(''),
            name_truncated:Array.from(name(e)).length>300,
            scope:scope?{tag:scope.tag,id:scope.id.length<=300?scope.id:undefined,
              keys:scope.keys.filter(([k,v])=>v!==null && v.length<=300),
              text:Array.from(scope.text).slice(0,500).join(''),
              truncated:scope.text.length>500 || scope.keys.some(([k,v])=>v?.length>300)}:undefined,
            type:tag==='input'?e.type:e.getAttribute('type') || undefined,
            editable:e.isContentEditable || tag==='textarea' ||
              (tag==='input' && /^(text|search|email|password|tel|url|number)$/.test(e.type)),
            readonly:!!e.readOnly,
            selector:e.id && e.getRootNode()===scopeRoot &&
              scopeRoot.querySelectorAll('#'+CSS.escape(e.id)).length===1
              ? '#'+CSS.escape(e.id):undefined,
            href:tag==='a'?e.href:undefined,
            options:tag==='select'?Array.from(e.options).slice(optionOffset,optionOffset+50)
              .map((o,i)=>({value:o.value.length<=512?o.value:undefined,
              value_omitted:o.value.length>512,option_ref:ref+':o'+(optionOffset+i),
              text:Array.from(o.text).slice(0,300).join(''),disabled:o.disabled ||
                (o.parentElement?.tagName==='OPTGROUP' && o.parentElement.disabled)})):undefined,
            option_offset:tag==='select'?optionOffset:undefined,
            total_options:tag==='select'?e.options.length:undefined,
            next_option_offset:tag==='select'
              ?(e.options.length>optionOffset+50?optionOffset+50:null):undefined,
            disabled:!!e.disabled || e.matches(':disabled') ||
              e.getAttribute('aria-disabled')==='true',
            checked:typeof e.checked==='boolean'?e.checked:undefined,
            selected_text:tag==='select'?e.selectedOptions?.[0]?.text:undefined,
            expanded:e.getAttribute('aria-expanded') || undefined,
            box:{x:r.x,y:r.y,width:r.width,height:r.height}});
        }
      }
      if (e.shadowRoot) walk(e.shadowRoot);
      if (tag==='iframe' || tag==='frame') {
        frames.push({url:e.src || 'about:srcdoc', readable:!!e.contentDocument?.body});
        try {
          if (e.contentDocument?.body) walk(e.contentDocument.body);
          else warnings.push('Unreadable frame');
        }
        catch (_) { warnings.push('Unreadable frame'); }
      }
    }
  };
  roots.forEach(walk);
  const text=Array.from(texts.join('\n').trim());
  if(continuation && (!previous || previous.id!==continuation ||
      previous.snapshot.length!==snapshot.length || previous.fullText!==text.join('') ||
      snapshot.some((v,i)=>v.element!==previous.snapshot[i].element ||
        v.name!==previous.snapshot[i].name ||
        JSON.stringify(v.scope?.keys)!==JSON.stringify(previous.snapshot[i].scope?.keys) ||
        v.options.length!==previous.snapshot[i].options.length ||
        v.options.some((o,j)=>o.node!==previous.snapshot[i].options[j].node ||
          o.value!==previous.snapshot[i].options[j].value ||
          o.text!==previous.snapshot[i].options[j].text))))
    return {error:'paging_snapshot_changed'};
  const state={id,refs,root:scopeRoot,scrolls,visible,name,canonicalRole,context,focused,focus:focused(),
    snapshot,fullText:text.join(''),
    url:location.href,
    scrollX,scrollY,
    width:innerWidth,height:innerHeight,
    revision:window.__deepseekPageRevision.value};
  window.__deepseekObservation=state;
  return {url:location.href,title:document.title,
    text:text.slice(textOffset,textOffset+16000).join(''),elements,
    text_offset:textOffset, element_offset:elementOffset,
    next_text_offset:text.length>textOffset+16000?textOffset+16000:null,
    next_element_offset:elementCount>elementOffset+elements.length?elementOffset+elements.length:null,
    total_elements:elementCount, frames,
    capabilities:{same_origin_frames:true,open_shadow:true,cross_origin_frames:false,closed_shadow:false},
    viewport:{width:innerWidth,height:innerHeight,scroll_x:scrollX,scroll_y:scrollY},
    dom_revision:state.revision,
    truncated:text.length>textOffset+16000 || elementCount>elementOffset+elements.length,
    warnings:[...new Set(warnings)]};
}""".replace("__VISIBLE__", VISIBLE)
    .replace("__READ_TEXT__", READ_TEXT)
    .replace("__SCOPE_CONTEXT__", SCOPE_CONTEXT)
    .replace("__NAME__", ACCESSIBLE_NAME)
    .replace("__ROLE__", CANONICAL_ROLE)
)

VISIBLE_TEXT = r"""selector => {
  const visible=__VISIBLE__, readText=__READ_TEXT__, texts=[];
  const els=selector?Array.from(document.querySelectorAll(selector)):[];
  if (selector && els.length !== 1) return null;
  const walk=root=>{
    if (!root) return;
    texts.push(readText(root));
    for(const e of [...(root.nodeType===1?[root]:[]),...root.querySelectorAll('*')]) {
      if (!visible(e)) continue;
      if(e.shadowRoot) walk(e.shadowRoot);
      if(e.tagName==='IFRAME' || e.tagName==='FRAME') {
        try { if(e.contentDocument?.body) walk(e.contentDocument.body); } catch (_) {}
      }
    }
  };
  walk(selector?els[0]:document.body);
  return texts.join('\n').trim();
}""".replace("__VISIBLE__", VISIBLE).replace("__READ_TEXT__", READ_TEXT)


async def evaluate(client: Any, expression: str) -> Any:
    result = await client.send(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
        },
    )
    if result.get("exceptionDetails"):
        raise RuntimeError("Page evaluation failed: " + str(result["exceptionDetails"].get("text")))
    value = result.get("result", {}).get("value")
    if value is None:
        raise RuntimeError("Page observation unavailable")
    return value


async def document_identity(client: Any) -> tuple[str, str]:
    tree = await client.send("Page.getFrameTree")
    frame = tree.get("frameTree", {}).get("frame", {})
    return str(frame.get("id", "")), str(frame.get("loaderId", ""))


class DocumentContext:
    """Root-document evaluations share one isolated registry, not a page-visible global."""

    def __init__(self, client, identity, context_id):
        self.client, self.identity, self.context_id = client, identity, context_id

    async def send(self, method, params=None):
        if method == "Runtime.evaluate":
            params = {**(params or {}), "contextId": self.context_id}
        return await self.client.send(method, params)

    def on(self, event, callback):
        return self.client.on(event, callback)

    def off(self, event, callback):
        return self.client.off(event, callback)

    async def close(self):
        try:
            await evaluate(
                self,
                "(()=>{window.__deepseekPageRevision?.observer?.disconnect();"
                "window.__deepseekObservation=null;window.__deepseekTarget=null;return true})()",
            )
        except Exception:
            pass  # Navigated documents have already destroyed their execution context.


async def root_context(run):
    client = run.session._internal.client
    identity = await document_identity(client)
    context = run.observation_root_context
    if context and context.client is client and context.identity == identity:
        return context
    if context:
        await context.close()
    world = await client.send(
        "Page.createIsolatedWorld",
        {
            "frameId": identity[0],
            "worldName": "deepseek-browser-targets",
        },
    )
    context = DocumentContext(client, identity, world["executionContextId"])
    run.observation_root_context = context
    return context


async def observe(
    run: Any,
    *,
    selector: str | None = None,
    full: bool = False,
    text_offset: int = 0,
    element_offset: int = 0,
    frame_id: str = "",
    option_offset: int = 0,
    frame_offset: int = 0,
    shadow_path: list[str] | None = None,
    continuation_id: str | None = None,
) -> dict[str, Any]:
    from deepseek_tui.browser.frames import FrameContext, discover_frames

    started = time.perf_counter()
    client = await root_context(run)
    root_identity = await document_identity(client)
    if run.observation_context:
        await run.observation_context.release_observation()
        await run.observation_context.close()
        run.observation_context = None
    if frame_id:
        run.observation_context = await FrameContext.create(run.session._internal.client, frame_id)
        client = run.observation_context
    for _ in range(2):
        identity = await document_identity(client)
        if not frame_id:
            root_identity = identity
        observation_id = "obs_" + uuid.uuid4().hex
        args = json.dumps(
            {
                "id": observation_id,
                "selector": selector,
                "limit": 250 if full else 120,
                "textOffset": text_offset,
                "elementOffset": element_offset,
                "optionOffset": option_offset,
                "shadowPath": shadow_path or [],
                "continuation": continuation_id,
            }
        )
        page = await evaluate(client, f"({COLLECT})({args})")
        if isinstance(page, dict) and page.get("error") == "paging_snapshot_changed":
            raise ValueError("Paging snapshot changed; restart the scoped observation")
        if not isinstance(page, dict) or "text" not in page or "elements" not in page:
            raise RuntimeError("Invalid page observation")
        if identity != await document_identity(client):
            continue
        if frame_id and root_identity != await document_identity(run.session._internal.client):
            raise RuntimeError("Parent page navigated while observing; read again")
        observation = {
            **page,
            "observation_id": observation_id,
            "tab_id": root_identity[0],
            "document_id": root_identity[1],
            "frame_id": frame_id,
            "frame_document_id": identity[1] if frame_id else None,
            "control_generation": run.generation,
            "scope_selector": selector,
            "scope_shadow_path": shadow_path or [],
        }
        run.latest_observation = observation
        if not frame_id:
            frames = (await discover_frames(run.session._internal.client))[1:]
            catalog = [(f.get("id"), f.get("url"), f.get("parent_id")) for f in frames]
            if continuation_id and frame_offset and catalog != run.frame_catalog:
                raise ValueError("Frame catalog changed; restart the observation")
            run.frame_catalog = catalog
            observation["frames"] = [
                {
                    "frame_id": f.get("id"),
                    "url": f.get("url"),
                    "parent_id": f.get("parent_id"),
                    "scoped_observation": True,
                }
                for f in frames[frame_offset : frame_offset + 20]
            ]
            observation["frame_offset"] = frame_offset
            observation["next_frame_offset"] = (
                frame_offset + 20 if len(frames) > frame_offset + 20 else None
            )
            observation.setdefault("capabilities", {})["direct_child_frames"] = True
            observation["capabilities"]["cross_origin_frames"] = "scoped_ancestors_up_to_8"
            from deepseek_tui.browser.capabilities import browser_capabilities

            observation["capabilities"].update(browser_capabilities()["observation"])
            observation["capabilities"]["capabilities_ref"] = "status.environment.capabilities"
            run.url = str(page.get("url", run.url))
        if getattr(run, "active_timings", None) is not None:
            run.active_timings["observe_ms"] = round(
                run.active_timings.get("observe_ms", 0) + (time.perf_counter() - started) * 1000, 2
            )
        return observation
    raise RuntimeError("Page navigated while observing; read again before acting")


async def target(run: Any, action: Any) -> dict[str, Any]:
    """Validate identity and resolve a current, unique, unobstructed DOM target."""
    observation = run.latest_observation
    if (
        not observation
        or observation["observation_id"] != action.observation_id
        or observation["control_generation"] != run.generation
    ):
        return {"error": "stale_observation"}
    client = await root_context(run)
    if await document_identity(client) != (observation["tab_id"], observation["document_id"]):
        return {"error": "stale_document"}
    if action.frame_id and action.frame_id != observation.get("frame_id"):
        return {"error": "stale_frame"}
    if observation.get("frame_id"):
        client = run.observation_context
        if not client or await document_identity(client) != (
            observation["frame_id"],
            observation["frame_document_id"],
        ):
            return {"error": "stale_frame"}
    if (
        action.x is not None
        and not action.ref
        and not action.selector
        and not observation.get("screenshot_artifact_id")
    ):
        return {"error": "screenshot_required"}
    args = json.dumps(
        {
            "id": action.observation_id,
            "ref": action.ref,
            "selector": action.selector,
            "x": action.x,
            "y": action.y,
            "action": action.action,
            "text": action.text,
            "option_ref": action.option_ref,
        }
    )
    resolved = await evaluate(
        client,
        r"""(a=>{
      const s=window.__deepseekObservation;
      if (!s || s.id!==a.id || s.url!==location.href) return {error:'stale_observation'};
      const compatible=e=>{
        if (a.action==='fill' || a.action==='type') {
          if (!(e?.isContentEditable || e?.tagName==='TEXTAREA' ||
              (e?.tagName==='INPUT' &&
                /^(text|search|email|password|tel|url|number)$/.test(e.type))))
            return 'target_not_editable';
          if (e.readOnly) return 'target_readonly';
        }
        if (a.action==='select' && e?.tagName!=='SELECT') return 'target_not_select';
        if (a.action==='select' && !a.option_ref &&
            !Array.from(e.options).some(o=>o.value===a.text && !o.disabled &&
              !(o.parentElement?.tagName==='OPTGROUP' && o.parentElement.disabled)))
          return 'option_unavailable';
        if (a.action==='set_checked' && !(e?.tagName==='INPUT' && e.type==='checkbox'))
          return 'target_not_checkbox';
      };
      if (!a.ref && !a.selector) {
        if ((a.action==='type' || a.action==='press') && !document.hasFocus())
          return {error:'focus_not_active'};
        if ((a.action==='type' || a.action==='press') && s.focused()!==s.focus)
          return {error:'focus_changed'};
        if (a.action==='type') {
          const error=compatible(s.focused());
          if(error) return {error};
          if(s.focused().disabled) return {error:'target_disabled'};
        }
        if (a.x!==null && (s.width!==innerWidth || s.height!==innerHeight ||
            s.scrollX!==scrollX || s.scrollY!==scrollY)) return {error:'stale_viewport'};
        if (a.x!==null && (s.revision!==window.__deepseekPageRevision.value ||
            s.scrolls.some(v=>v.x!==(v.window?v.node.scrollX:v.node.scrollLeft) ||
              v.y!==(v.window?v.node.scrollY:v.node.scrollTop)) ||
            [...s.refs.values()].some(v=>{
              const r=v.element.getBoundingClientRect();
              return !v.element.isConnected ||
                s.name(v.element)!==v.name ||
                [r.x,r.y,r.width,r.height].some((n,i)=>Math.abs(n-v.box[i])>1);
            }))) return {error:'stale_layout'};
        return {};
      }
      let entry=a.ref?s.refs.get(a.ref):null, e=entry?.element;
      if (!a.ref) {
        const all=s.root.querySelectorAll(a.selector);
        if (all.length!==1) return {error:'target_not_unique'};
        e=all[0];
        entry=[...s.refs.values()].find(v=>v.element===e);
        if (!entry) return {error:'target_not_observed'};
      }
      if (!e || !s.visible(e)) return {error:'target_not_visible'};
      if (entry && (s.name(e)!==entry.name || (e.tagName==='A'?e.href:null)!==entry.href ||
          (e.form?.action || null)!==entry.formAction ||
          s.canonicalRole(e)!==entry.role))
        return {error:'target_changed'};
      if(entry) {
        const scope=s.context(e), old=entry.scope;
        if(e.parentElement!==entry.parent || !!scope!==!!old ||
            (scope && (scope.node!==old.node || scope.id!==old.id || scope.text!==old.text ||
              JSON.stringify(scope.keys)!==JSON.stringify(old.keys))))
          return {error:'target_context_changed'};
      }
      if (e.disabled || e.matches(':disabled') || e.getAttribute('aria-disabled')==='true')
        return {error:'target_disabled'};
      const error=compatible(e);
      if(error) return {error};
      if(a.option_ref) {
        const option=entry.options.get(a.option_ref);
        if(!option || !Array.from(e.options).includes(option.node) ||
            option.node.value!==option.value || option.node.text!==option.text ||
            option.node.disabled || option.node.parentElement?.disabled)
          return {error:'stale_option'};
        window.__deepseekSelectedOption=option.node;
      }
      e.scrollIntoView({block:'center',inline:'center'});
      const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
      const hit=e.getRootNode().elementFromPoint?.(x,y) || e.ownerDocument.elementFromPoint(x,y);
      if (!hit || (hit!==e && !e.contains(hit))) return {error:'target_obscured'};
      // Frame-local hit testing cannot detect a parent overlay. Verify the
      // path through each same-origin parent before resolving a nested node.
      let view=e.ownerDocument.defaultView, px=x, py=y;
      while (view!==window) {
        const frame=view.frameElement;
        if (!frame || !s.visible(frame)) return {error:'target_not_visible'};
        for(let p=frame;p;p=p.parentElement || p.getRootNode()?.host) {
          const style=frame.ownerDocument.defaultView.getComputedStyle(p);
          if(style.transform!=='none' || style.perspective!=='none' ||
             Number(style.zoom || 1)!==1 ||
             ['translate','rotate','scale'].some(k=>style[k] && style[k]!=='none'))
            return {error:'frame_coordinates_unavailable'};
        }
        frame.scrollIntoView({block:'center',inline:'center'});
        const b=frame.getBoundingClientRect();
        px+=b.x+frame.clientLeft; py+=b.y+frame.clientTop;
        const outer=frame.ownerDocument.elementFromPoint(px,py);
        if (outer!==frame) return {error:'target_obscured'};
        view=frame.ownerDocument.defaultView;
      }
      if (a.action==='press') {
        e.focus();
        if (s.focused()!==e) return {error:'target_focus_failed'};
      }
      window.__deepseekTarget=e;
      return {bound:true,target_id:entry.target_id,x:px,y:py};
    })("""
        + args
        + ")",
    )
    if not isinstance(resolved, dict):
        raise RuntimeError("Invalid target resolution")
    if not resolved.get("error") and observation.get("frame_id"):
        if action.x is not None and not (action.ref or action.selector):
            return {"error": "frame_coordinates_require_target"}
        if action.action == "scroll" and resolved.get("x") is None:
            resolved.update(
                x=observation["viewport"]["width"] / 2, y=observation["viewport"]["height"] / 2
            )
        if resolved.get("x") is not None:
            coordinates = await client.coordinates(resolved["x"], resolved["y"])
            if coordinates.get("error"):
                return coordinates
            resolved.update(coordinates)
        resolved.update(frame_id=observation["frame_id"], nested=False)
    return resolved


async def target_state(run: Any, action: Any, expression: str) -> Any:
    """Read a targeted node without exposing field contents in observations/logs."""
    client = run.session._internal.client
    if action.observation_id and action.observation_id == run.target_binding_id:
        client = run.observation_context if action.frame_id else await root_context(run)
        return await evaluate(
            client,
            "(()=>{const s=window.__deepseekObservation;"
            "const e=window.__deepseekTarget;if(!s || s.id!=="
            + json.dumps(action.observation_id)
            + " || !e)return false;const entry=[...s.refs.values()].find(v=>v.element===e);"
            "if(!entry || !e.isConnected || s.name(e)!==entry.name || s.canonicalRole(e)!==entry.role)return false;"
            "const c=s.context(e),old=entry.scope;if(e.parentElement!==entry.parent || !!c!==!!old ||"
            "(c && (c.node!==old.node || c.id!==old.id || c.text!==old.text || JSON.stringify(c.keys)!==JSON.stringify(old.keys))))return false;"
            "return (" + expression + ")})()",
        )
    if action.frame_id:
        client = run.observation_context
        return await evaluate(
            client,
            "(()=>{const e=window.__deepseekTarget;return e ? (" + expression + ") : false})()",
        )
    if action.ref:
        node = run.session._internal.ref_cache.lookup(action.ref)
        obj = await client.send("DOM.resolveNode", {"nodeId": node})
        object_id = obj["object"]["objectId"]
        try:
            result = await client.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "returnByValue": True,
                    "functionDeclaration": "function(){const e=this;return " + expression + "}",
                },
            )
            if result.get("exceptionDetails"):
                raise RuntimeError("Target state read failed")
            return result.get("result", {}).get("value")
        finally:
            await client.send("Runtime.releaseObject", {"objectId": object_id})
    return await evaluate(
        client,
        "(()=>{const nodes=document.querySelectorAll("
        + json.dumps(action.selector)
        + ");const e=nodes.length===1?nodes[0]:null;"
        + "return e ? ("
        + expression
        + ") : false})()",
    )


async def describe(run, action):
    previous = run.latest_observation
    if (
        not previous
        or previous["observation_id"] != action.observation_id
        or previous["control_generation"] != run.generation
    ):
        raise ValueError("Describe requires the current observation")
    client = run.observation_context if previous.get("frame_id") else await root_context(run)
    identity = (
        (previous["frame_id"], previous["frame_document_id"])
        if previous.get("frame_id")
        else (previous["tab_id"], previous["document_id"])
    )
    if await document_identity(client) != identity:
        raise ValueError("Describe document changed; observe again")
    args = json.dumps(
        {
            "id": action.observation_id,
            "ref": action.ref,
            "offset": action.detail_offset,
            "optionOffset": action.option_offset,
        }
    )
    detail = await evaluate(
        client,
        r"""(a=>{
      const s=window.__deepseekObservation, entry=s?.refs.get(a.ref),e=entry?.element;
      if(!s || s.id!==a.id || !e?.isConnected || s.name(e)!==entry.name || s.canonicalRole(e)!==entry.role)
        throw Error('Describe target changed; observe again');
      const name=Array.from(s.name(e)),scope=s.context(e);
      const old=entry.scope;
      if(e.parentElement!==entry.parent || !!scope!==!!old || (scope && (scope.node!==old.node ||
          scope.id!==old.id || scope.text!==old.text || JSON.stringify(scope.keys)!==JSON.stringify(old.keys))))
        throw Error('Describe business scope changed; observe again');
      const result={ref:a.ref,target_id:entry.target_id,role:s.canonicalRole(e),tag:e.tagName.toLowerCase(),
        type:e.tagName==='INPUT'?e.type:e.getAttribute('type') || undefined,
        readonly:!!e.readOnly,disabled:!!e.disabled || e.matches(':disabled') || e.getAttribute('aria-disabled')==='true',
        name:name.slice(a.offset,a.offset+2000).join(''),name_offset:a.offset,
        next_name_offset:name.length>a.offset+2000?a.offset+2000:null,
        scope:scope?{tag:scope.tag,id:scope.id,keys:scope.keys,
          text:Array.from(scope.text).slice(a.offset,a.offset+2000).join(''),text_offset:a.offset,
          next_text_offset:Array.from(scope.text).length>a.offset+2000?a.offset+2000:null}:undefined};
      if(e.tagName==='SELECT') {
        result.options=Array.from(e.options).slice(a.optionOffset,a.optionOffset+50).map((o,i)=>{
          const ref=a.ref+':o'+(a.optionOffset+i);
          entry.options.set(ref,{node:o,value:o.value,text:o.text});
          return {option_ref:ref,value:o.value.length<=512?o.value:undefined,
            value_omitted:o.value.length>512,text:Array.from(o.text).slice(0,300).join(''),
            disabled:o.disabled || !!o.parentElement?.disabled};
        });
        result.option_offset=a.optionOffset;result.total_options=e.options.length;
        result.next_option_offset=e.options.length>a.optionOffset+50?a.optionOffset+50:null;
      }
      return result;
    })("""
        + args
        + ")",
    )
    return {**previous, "elements": [detail], "text": "", "details": True}
