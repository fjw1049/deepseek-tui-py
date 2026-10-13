"""Scoped, bounded condition checks shared by tools and recorded workflows."""

from __future__ import annotations

import asyncio
import json

from deepseek_tui.browser.observation import (
    VISIBLE,
    VISIBLE_TEXT,
    document_identity,
    evaluate,
    root_context,
)


async def check_condition(run, action, deadline):
    try:
        return await asyncio.wait_for(
            _check_condition(run, action, deadline),
            max(0.001, deadline - asyncio.get_running_loop().time()),
        )
    except TimeoutError:
        return False


async def _check_condition(run, action, deadline):
    from deepseek_tui.browser.frames import FrameContext, resolve_frame, resolve_frame_path

    generation = run.generation
    client = await root_context(run)
    frame_id = action.frame_id
    if action.frame_selector:
        frame_id = await resolve_frame(run.session._internal.client, action.frame_selector)
    if action.frame_path:
        frame_id = await resolve_frame_path(
            run.session._internal.client,
            [f if isinstance(f, str) else f.model_dump(by_alias=True) for f in action.frame_path],
        )
    if frame_id:
        if not run.observation_context or run.observation_context.frame_id != frame_id:
            if run.observation_context:
                await run.observation_context.close()
            run.observation_context = await FrameContext.create(
                run.session._internal.client, frame_id
            )
        client = run.observation_context
    identity = await document_identity(client)
    args = json.dumps(
        {
            "kind": action.condition,
            "text": action.text,
            "selector": action.selector,
            "url": action.url_contains,
            "state": action.wait_state,
            "shadow": action.shadow_path,
            "checked": action.checked,
        }
    )
    expression = (
        r"""(a=>{
      let root=document;
      for(const selector of a.shadow){
        const hosts=root.querySelectorAll(selector);
        if(hosts.length!==1 || !hosts[0].shadowRoot)return false;
        root=hosts[0].shadowRoot;
      }
      const nodes=a.selector?Array.from(root.querySelectorAll(a.selector)):[];
      const visible=__VISIBLE__, text=__VISIBLE_TEXT__;
      let passed;
      if(a.kind==='url_contains')passed=location.href.includes(a.url);
      else if(a.kind==='title_contains')passed=document.title.includes(a.text);
      else if(a.kind==='input_value_equals' || a.kind==='selected_equals')
        passed=nodes.length===1 && nodes[0].value===a.text;
      else if(a.kind==='checked_equals')passed=nodes.length===1 && nodes[0].checked===a.checked;
      else {
        if(a.selector && a.text && nodes.length!==1)return false;
        const body=root===document?text(a.selector):Array.from(root.childNodes)
          .filter(n=>n.nodeType===1).map(n=>textFrom(n)).join('\n');
        passed=(!a.text || (a.selector?textFrom(nodes[0]):body)?.includes(a.text)) &&
          (!a.selector || nodes.some(visible)) && (!a.url || location.href.includes(a.url));
      }
      return (!a.url || location.href.includes(a.url)) && (a.state==='hidden'?!passed:passed);
      function textFrom(e){return (__READ_TEXT__)(e)}
    })("""
        + args
        + ")"
    )
    from deepseek_tui.browser.observation import READ_TEXT

    expression = expression.replace("__VISIBLE__", VISIBLE).replace(
        "__VISIBLE_TEXT__", VISIBLE_TEXT
    )
    expression = expression.replace("__READ_TEXT__", READ_TEXT)
    while True:
        if run.generation != generation or run.transferring:
            raise ValueError("Browser control changed while checking the condition")
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        if action.condition != "url_contains" and identity != await asyncio.wait_for(
            document_identity(client), timeout=remaining
        ):
            raise ValueError("Condition target document changed; observe again")
        if frame_id:
            await asyncio.wait_for(
                client.validate_ancestors(),
                max(0.001, deadline - asyncio.get_running_loop().time()),
            )
        if action.condition == "url_contains" and not frame_id:
            client = await root_context(run)
        passed = await asyncio.wait_for(
            evaluate(client, expression),
            timeout=max(0.001, deadline - asyncio.get_running_loop().time()),
        )
        if passed is True:
            return True
        if action.action == "check_text" and action.timeout_ms == 0:
            return False
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.05, remaining))
